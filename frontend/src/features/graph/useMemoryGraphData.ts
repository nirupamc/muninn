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

  // Phase 1: Collect ALL temporal edges from ALL scoped memories.
  // This discovers which memories participate in relationships.
  const allEdges = new Map<string, GraphEdge>();
  let relationshipFailures = 0;
  const historyQueue = [...scoped];

  const historyWorker = async () => {
    while (historyQueue.length > 0) {
      const memory = historyQueue.shift();
      if (!memory) return;
      try {
        const history = await api.getMemoryHistory(memory.id);
        for (const record of history.temporal_decisions) {
          const relationship = TEMPORAL[record.relationship.toUpperCase()];
          const source = record.matched_memory_id;
          const target = record.created_memory_id;
          if (!relationship || !source || !target) continue;
          // Only include edges where both endpoints are in the scoped namespace
          const sourceMemory = all.memories.find((m) => m.id === source);
          const targetMemory = all.memories.find((m) => m.id === target);
          if (!sourceMemory || !targetMemory) continue;
          if (sourceMemory.namespace !== namespace || targetMemory.namespace !== namespace) continue;
          allEdges.set(`temporal-${record.id}`, {
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

      // Also check consolidation provenance
      const memNode = toMemoryNode(memory);
      if (memNode.isConsolidated) {
        try {
          const provenance = await api.getMemoryConsolidation(memory.id);
          for (const source of provenance.sources) {
            const sourceMemory = all.memories.find((m) => m.id === source.memory_id);
            const targetMemory = all.memories.find((m) => m.id === provenance.created_memory_id);
            if (!sourceMemory || !targetMemory) continue;
            if (sourceMemory.namespace !== namespace || targetMemory.namespace !== namespace) continue;
            const id = `consolidation-${provenance.consolidation_id}-${source.memory_id}`;
            allEdges.set(id, {
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

  await Promise.all(Array.from({ length: Math.min(8, scoped.length || 1) }, historyWorker));

  // Phase 2: Build relationship-aware node set.
  // Start with the top `nodeLimit` memories by recency, then add any
  // memory that is an endpoint of a discovered relationship.
  const baseNodes = scoped.slice(0, nodeLimit);
  const baseNodeIds = new Set(baseNodes.map((m) => m.id));

  // Collect all memory IDs that participate in edges
  const edgeEndpointIds = new Set<string>();
  for (const edge of allEdges.values()) {
    edgeEndpointIds.add(edge.source);
    edgeEndpointIds.add(edge.target);
  }

  // Add edge endpoints that aren't already in the base set
  // (up to a reasonable extra budget to avoid blowing past nodeLimit)
  const extraIds = [...edgeEndpointIds].filter((id) => !baseNodeIds.has(id));
  const extraMemories = extraIds
    .map((id) => scoped.find((m) => m.id === id))
    .filter((m): m is (typeof scoped)[number] => !!m);

  // Combine: base + extras, then cap at nodeLimit + edge budget
  const edgeBudget = Math.min(extraMemories.length, Math.max(50, Math.floor(nodeLimit * 0.3)));
  const selectedMemories = [...baseNodes, ...extraMemories.slice(0, edgeBudget)];
  const nodeIds = new Set(selectedMemories.map((m) => m.id));

  // Phase 3: Filter edges to only those whose both endpoints are in the final node set
  const finalEdges = [...allEdges.values()].filter(
    (edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target),
  );

  const nodes = selectedMemories.map(toMemoryNode);

  return {
    nodes,
    edges: finalEdges,
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
