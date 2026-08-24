import type { GraphEdge, MemoryNode } from "../../types/domain";
import type { FGLink, FGNode } from "./graphTypes";

type Endpoint = GraphEdge["source"] | FGNode;

function endpointId(endpoint: Endpoint): string {
  return typeof endpoint === "string" ? endpoint : endpoint.id;
}

function cleanNode(node: MemoryNode | FGNode): FGNode {
  const { x: _x, y: _y, z: _z, vx: _vx, vy: _vy, vz: _vz, fx: _fx, fy: _fy, fz: _fz, ...domainNode } = node as FGNode & Record<string, unknown>;
  return { ...domainNode } as FGNode;
}

export function cloneForRenderer(domainNodes: readonly MemoryNode[], domainEdges: readonly GraphEdge[], limit: number) {
  const nodes = domainNodes.slice(0, limit).map(cleanNode);
  const nodeIds = new Set(nodes.map((node) => node.id));
  const edgeById = new Map<string, FGLink>();

  for (const edge of domainEdges) {
    if (edgeById.has(edge.id)) continue;
    const source = endpointId(edge.source as Endpoint);
    const target = endpointId(edge.target as Endpoint);
    if (!source || !target || !nodeIds.has(source) || !nodeIds.has(target)) continue;
    edgeById.set(edge.id, { ...edge, source, target });
  }

  return { nodes, links: Array.from(edgeById.values()) };
}
