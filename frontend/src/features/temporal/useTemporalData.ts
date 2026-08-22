import { api } from "../../api/client";
import { listAllMemories } from "../../api/pagination";
import { useAsync } from "../../hooks/useAsync";
import { toMemoryNode } from "../../lib/mappers";
import type { TemporalRecordRead } from "../../types/api";
import type { MemoryNode } from "../../types/domain";

export type TemporalRelationship = "SUPERSEDES" | "UPDATES" | "CONTRADICTS";

export interface TemporalData {
  memories: MemoryNode[];
  records: TemporalRecordRead[];
  namespaces: string[];
  completeDataset: boolean;
  historyFailures: number;
}

export interface TemporalChain {
  id: string;
  memoryIds: string[];
  records: TemporalRecordRead[];
}

const SUPPORTED = new Set<TemporalRelationship>(["SUPERSEDES", "UPDATES", "CONTRADICTS"]);

async function loadTemporalData(namespace: string): Promise<TemporalData> {
  const all = await listAllMemories();
  const namespaces = Array.from(new Set(all.memories.map((memory) => memory.namespace))).sort();
  const memories = all.memories.filter((memory) => memory.namespace === namespace).map(toMemoryNode);
  const memoryIds = new Set(memories.map((memory) => memory.id));
  const records = new Map<string, TemporalRecordRead>();
  const queue = [...memories];
  let historyFailures = 0;

  const worker = async () => {
    while (queue.length) {
      const memory = queue.shift();
      if (!memory) return;
      try {
        const history = await api.getMemoryHistory(memory.id);
        for (const record of history.temporal_decisions) {
          const relationship = record.relationship.toUpperCase() as TemporalRelationship;
          if (!SUPPORTED.has(relationship)) continue;
          if (!record.matched_memory_id || !record.created_memory_id) continue;
          if (!memoryIds.has(record.matched_memory_id) || !memoryIds.has(record.created_memory_id)) continue;
          records.set(record.id, record);
        }
      } catch {
        historyFailures += 1;
      }
    }
  };

  await Promise.all(Array.from({ length: Math.min(8, memories.length || 1) }, worker));
  return {
    memories,
    records: Array.from(records.values()).sort((a, b) => a.created_at.localeCompare(b.created_at) || a.id.localeCompare(b.id)),
    namespaces,
    completeDataset: all.complete,
    historyFailures,
  };
}

export function buildTemporalChains(records: TemporalRecordRead[]): TemporalChain[] {
  const adjacency = new Map<string, Set<string>>();
  for (const record of records) {
    if (!record.matched_memory_id || !record.created_memory_id) continue;
    if (!adjacency.has(record.matched_memory_id)) adjacency.set(record.matched_memory_id, new Set());
    if (!adjacency.has(record.created_memory_id)) adjacency.set(record.created_memory_id, new Set());
    adjacency.get(record.matched_memory_id)!.add(record.created_memory_id);
    adjacency.get(record.created_memory_id)!.add(record.matched_memory_id);
  }

  const visited = new Set<string>();
  const chains: TemporalChain[] = [];
  for (const start of adjacency.keys()) {
    if (visited.has(start)) continue;
    const queue = [start];
    const ids: string[] = [];
    visited.add(start);
    while (queue.length) {
      const id = queue.shift()!;
      ids.push(id);
      for (const neighbor of adjacency.get(id) ?? []) {
        if (!visited.has(neighbor)) { visited.add(neighbor); queue.push(neighbor); }
      }
    }
    const idSet = new Set(ids);
    const chainRecords = records.filter((record) =>
      !!record.matched_memory_id && !!record.created_memory_id &&
      idSet.has(record.matched_memory_id) && idSet.has(record.created_memory_id),
    );
    chains.push({ id: [...ids].sort()[0], memoryIds: ids, records: chainRecords });
  }
  const newest = (chain: TemporalChain) => chain.records[chain.records.length - 1]?.created_at ?? "";
  return chains.sort((a, b) => newest(b).localeCompare(newest(a)));
}

export function useTemporalData(namespace: string) {
  return useAsync(() => loadTemporalData(namespace), [namespace]);
}
