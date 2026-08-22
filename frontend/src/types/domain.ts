// Frontend domain models for the graph + UI layer.
// API DTOs are mapped into these via lib/mappers.

export type RelationshipKind =
  | "semantic"
  | "reinforces"
  | "supersedes"
  | "updates"
  | "contradicts"
  | "derived_from";

export interface MemoryNode {
  id: string;
  label: string;
  content: string;
  memoryType: import("./api").MemoryType;
  status: import("./api").MemoryStatus;
  importance: number;
  /** Backend-owned value; null while the list API does not expose it. */
  effectiveImportance: number | null;
  confidence: number;
  namespace: string;
  userId: string | null;
  agentId: string | null;
  sessionId: string | null; // not exposed by backend; null unless discovered
  createdAt: string;
  updatedAt: string;
  lastAccessedAt: string | null;
  validFrom: string | null;
  validUntil: string | null;
  sourceEventId: string | null;
  metadata: Record<string, unknown>;
  isConsolidated: boolean;
  /** Not exposed by backend; null unless derived from loaded graph edges. */
  reinforcementCount: number | null;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  relationship: RelationshipKind;
  confidence: number | null;
  createdAt: string | null;
}

export interface GraphData {
  nodes: MemoryNode[];
  edges: GraphEdge[];
}

export interface MemoryFilters {
  query: string;
  namespace: string | null;
  memoryType: import("./api").MemoryType | null;
  status: import("./api").MemoryStatus | null;
  agentId: string | null;
  minConfidence: number;
  minImportance: number;
  showTemporal: boolean;
  showConsolidation: boolean;
}
