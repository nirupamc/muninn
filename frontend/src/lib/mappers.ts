import type { MemoryRead, MemoryType, MemoryStatus } from "../types/api";
import type {
  MemoryNode,
  GraphEdge,
  RelationshipKind,
} from "../types/domain";

export function toMemoryNode(m: MemoryRead): MemoryNode {
  const meta = (m.metadata ?? {}) as Record<string, unknown>;
  return {
    id: m.id,
    label: shortLabel(m.content),
    content: m.content,
    gist: m.gist ?? null,
    summary: m.summary ?? null,
    memoryType: m.memory_type,
    status: m.status,
    importance: m.importance,
    effectiveImportance: null,
    confidence: m.confidence,
    namespace: m.namespace,
    userId: m.user_id,
    agentId: m.agent_id,
    sessionId: null,
    createdAt: m.created_at,
    updatedAt: m.updated_at,
    lastAccessedAt: m.last_accessed_at,
    validFrom: m.valid_from,
    validUntil: m.valid_until,
    sourceEventId: m.source_event_id,
    metadata: meta,
    isConsolidated:
      meta["is_consolidated"] === true || meta["is_consolidated"] === "true",
    reinforcementCount: null,
  };
}

export function shortLabel(content: string, max = 48): string {
  const clean = (content || "").replace(/\s+/g, " ").trim();
  return clean.length > max ? clean.slice(0, max - 1) + "…" : clean;
}

/** Map a temporal relationship string to a graph edge kind. */
export function temporalToEdgeKind(rel: string): RelationshipKind | null {
  switch (rel.toUpperCase()) {
    case "SUPERSEDES":
      return "supersedes";
    case "UPDATES":
      return "updates";
    case "CONTRADICTS":
      return "contradicts";
    default:
      return null;
  }
}

export function buildEdgesFromHistory(
  node: MemoryNode,
  matchedMemoryIds: Set<string>,
  history: { matched_memory_id: string | null; relationship: string; relationship_confidence: number | null; created_at: string | null }[],
): GraphEdge[] {
  const edges: GraphEdge[] = [];
  for (const rec of history) {
    if (!rec.matched_memory_id) continue;
    const kind = temporalToEdgeKind(rec.relationship);
    if (!kind) continue;
    edges.push({
      id: `e-${node.id}-${rec.matched_memory_id}`,
      source: node.id,
      target: rec.matched_memory_id,
      relationship: kind,
      confidence: rec.relationship_confidence,
      createdAt: rec.created_at,
    });
    matchedMemoryIds.add(rec.matched_memory_id);
  }
  return edges;
}

export const MEMORY_TYPE_COLORS: Record<MemoryType, string> = {
  project: "#22e36b",
  goal: "#27e36b",
  preference: "#22d3ee",
  decision: "#ff9d2e",
  fact: "#27e36b",
  procedure: "#22d3ee",
  event: "#5d6b5d",
  relationship: "#a472ff",
  other: "#8aa08a",
};

export const STATUS_COLORS: Record<MemoryStatus, string> = {
  active: "#27e36b",
  superseded: "#ff9d2e",
  invalidated: "#ff3b3b",
  archived: "#5d6b5d",
};

/** Edge color by relationship; semantic treated as cyan/low opacity. */
export function edgeColor(kind: RelationshipKind): string {
  switch (kind) {
    case "reinforces":
      return "#27e36b";
    case "supersedes":
      return "#ff9d2e";
    case "updates":
      return "#ffc24b";
    case "contradicts":
      return "#ff3b3b";
    case "derived_from":
      return "#a472ff";
    case "semantic":
    default:
      return "#22d3ee";
  }
}
