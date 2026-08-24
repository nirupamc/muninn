import type { GraphEdge, MemoryNode } from "../../types/domain";

export interface FGNode extends MemoryNode { x?: number; y?: number; z?: number }
export interface FGLink extends Omit<GraphEdge, "source" | "target"> { source: string | FGNode; target: string | FGNode }
export interface GraphRendererHandle {
  fit: () => void;
  focus: (node: FGNode) => void;
  reheat: () => void;
}
