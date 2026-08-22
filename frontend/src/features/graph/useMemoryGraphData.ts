import { ApiError, api } from "../../api/client";
import { listAllMemories } from "../../api/pagination";
import { useAsync } from "../../hooks/useAsync";
import { toMemoryNode } from "../../lib/mappers";
import type { GraphData, GraphEdge, RelationshipKind } from "../../types/domain";

export interface MemoryGraphData extends GraphData {
  completeDataset: boolean;
  namespaceTotal: number;
  namespaces: string[];
  limited: boolean;
  relationshipFailures: number;
}

const TEMPORAL: Record<string, RelationshipKind> = {
  SUPERSEDES: "supersedes",
  UPDATES: "updates",
  CONTRADICTS: "contradicts",
};

async function loadMemoryGraph(namespace: string, nodeLimit: number): Promise<MemoryGraphData> {
  const all = await listAllMemories();
  const namespaces = Array.from(new Set(all.memories.map((memory) => memory.namespace))).sort();
  const scoped = all.memories.filter((memory) => memory.namespace === namespace);
  const nodes = scoped.slice(0, nodeLimit).map(toMemoryNode);
  const nodeIds = new Set(nodes.map((node) => node.id));
  const edges = new Map<string, GraphEdge>();
  const queue = [...nodes];
  let relationshipFailures = 0;

  const worker = async () => {
    while (queue.length > 0) {
      const node = queue.shift();
      if (!node) return;
      try {
        const history = await api.getMemoryHistory(node.id);
        for (const record of history.temporal_decisions) {
          const relationship = TEMPORAL[record.relationship.toUpperCase()];
          const source = record.matched_memory_id;
          const target = record.created_memory_id;
          if (!relationship || !source || !target || !nodeIds.has(source) || !nodeIds.has(target)) continue;
          edges.set(`temporal-${record.id}`, {
            id: `temporal-${record.id}`,
            source,
            target,
            relationship,
            confidence: record.relationship_confidence,
            createdAt: record.created_at,
          });
        }
      } catch {
        relationshipFailures += 1;
      }

      if (node.isConsolidated) {
        try {
          const provenance = await api.getMemoryConsolidation(node.id);
          for (const source of provenance.sources) {
            if (!nodeIds.has(source.memory_id) || !nodeIds.has(provenance.created_memory_id)) continue;
            const id = `consolidation-${provenance.consolidation_id}-${source.memory_id}`;
            edges.set(id, {
              id,
              source: source.memory_id,
              target: provenance.created_memory_id,
              relationship: "derived_from",
              confidence: provenance.confidence,
              createdAt: provenance.created_at,
            });
          }
        } catch (error) {
          if (!(error instanceof ApiError && error.status === 404)) relationshipFailures += 1;
        }
      }
    }
  };

  await Promise.all(Array.from({ length: Math.min(8, nodes.length || 1) }, worker));
  return {
    nodes,
    edges: Array.from(edges.values()),
    completeDataset: all.complete,
    namespaceTotal: scoped.length,
    namespaces,
    limited: scoped.length > nodes.length || !all.complete,
    relationshipFailures,
  };
}

export function useMemoryGraphData(namespace: string, nodeLimit: number) {
  return useAsync(() => loadMemoryGraph(namespace, nodeLimit), [namespace, nodeLimit]);
}
