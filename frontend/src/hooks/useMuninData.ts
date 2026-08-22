import { useMemo } from "react";
import { api } from "../api/client";
import { listAllMemories } from "../api/pagination";
import { toMemoryNode } from "../lib/mappers";
import { useAsync } from "./useAsync";
import type { MemoryNode, GraphEdge, GraphData, RelationshipKind } from "../types/domain";
import type { MemoryRead, TemporalRecordRead } from "../types/api";

const REL_EDGE: Record<string, RelationshipKind> = {
  SUPERSEDES: "supersedes",
  UPDATES: "updates",
  CONTRADICTS: "contradicts",
};

async function loadGraph(
  namespace: string | null,
  limit: number,
): Promise<GraphData> {
  const memories: MemoryRead[] = await api.listMemories({
    namespace,
    limit,
  });
  const nodes: MemoryNode[] = memories.map(toMemoryNode);

  // Build temporal edges by fetching per-node history (concurrency-limited).
  const edges: GraphEdge[] = [];
  const concurrency = 6;
  const queue = [...nodes];
  const worker = async () => {
    while (queue.length) {
      const node = queue.shift();
      if (!node) return;
      try {
        const hist = await api.getMemoryHistory(node.id);
        for (const rec of hist.temporal_decisions as TemporalRecordRead[]) {
          if (!rec.matched_memory_id) continue;
          const kind = REL_EDGE[rec.relationship.toUpperCase()];
          if (!kind) continue;
          edges.push({
            id: `e-${node.id}-${rec.matched_memory_id}`,
            source: node.id,
            target: rec.matched_memory_id,
            relationship: kind,
            confidence: rec.relationship_confidence,
            createdAt: rec.created_at,
          });
        }
      } catch {
        // a single failed history should not break the whole graph
      }
    }
  };
  await Promise.all(
    Array.from({ length: Math.min(concurrency, nodes.length || 1) }, worker),
  );

  return { nodes, edges };
}

export function useGraphData(
  namespace: string | null,
  limit = 100,
  reloadKey = 0,
) {
  const state = useAsync<GraphData>(
    () => loadGraph(namespace, limit),
    [namespace, limit, reloadKey],
  );
  return state;
}

export function useMemories(params: {
  namespace?: string | null;
  memoryType?: string | null;
  status?: string | null;
  agentId?: string | null;
  limit?: number;
}) {
  const state = useAsync<MemoryRead[]>(
    () => api.listMemories(params),
    [
      params.namespace,
      params.memoryType,
      params.status,
      params.agentId,
      params.limit,
    ],
  );
  const data = useMemo(
    () => (state.data ? state.data.map(toMemoryNode) : null),
    [state.data],
  );
  return { ...state, data };
}

export function useAllMemories() {
  const state = useAsync(listAllMemories, []);
  const data = useMemo(
    () => state.data
      ? { ...state.data, memories: state.data.memories.map(toMemoryNode) }
      : null,
    [state.data],
  );
  return { ...state, data };
}

export function useMemoryHistory(id: string | null) {
  return useAsync<TemporalRecordRead[]>(
    async () => {
      if (!id) return [];
      const r = await api.getMemoryHistory(id);
      return r.temporal_decisions;
    },
    [id],
    !!id,
  );
}

export function useSearch(
  query: string,
  namespace: string,
  enabled: boolean,
) {
  return useAsync(
    () => api.searchMemories({ query, namespace, limit: 25 }),
    [query, namespace],
    enabled && query.trim().length > 0,
  );
}
