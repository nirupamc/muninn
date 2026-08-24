import { forwardRef, useImperativeHandle, useMemo, useRef } from "react";
import ForceGraph3D, { type ForceGraphMethods } from "react-force-graph-3d";
import type { FGLink, FGNode, GraphRendererHandle } from "./graphTypes";

interface Props {
  nodes: FGNode[];
  links: FGLink[];
  width: number;
  height: number;
  visibleNodeIds: Set<string>;
  visibleLinkIds: Set<string>;
  nodeColor: (node: FGNode) => string;
  nodeOpacity: (node: FGNode) => number;
  linkColor: (link: FGLink) => string;
  linkWidth: (link: FGLink) => number;
  tooltip: (node: FGNode) => string;
  onNodeClick: (node: FGNode) => void;
  onNodeHover: (node: FGNode | null) => void;
}

export const ForceGraph3DRenderer = forwardRef<GraphRendererHandle, Props>(function ForceGraph3DRenderer(props, ref) {
  const graphRef = useRef<ForceGraphMethods<FGNode, FGLink> | undefined>(undefined);
  const graphData = useMemo(() => ({
    nodes: props.nodes.map((node) => ({ ...node })),
    links: props.links.map((link) => ({
      ...link,
      source: typeof link.source === "string" ? link.source : link.source.id,
      target: typeof link.target === "string" ? link.target : link.target.id,
    })),
  }), [props.nodes, props.links]);

  useImperativeHandle(ref, () => ({
    fit: () => graphRef.current?.zoomToFit(500, 70, (node) => props.visibleNodeIds.has(String(node.id))),
    focus: (node) => {
      const distance = 90;
      const length = Math.hypot(node.x ?? 0, node.y ?? 0, node.z ?? 0) || 1;
      const ratio = 1 + distance / length;
      graphRef.current?.cameraPosition({ x: (node.x ?? 0) * ratio, y: (node.y ?? 0) * ratio, z: (node.z ?? 1) * ratio }, { x: node.x ?? 0, y: node.y ?? 0, z: node.z ?? 0 }, 650);
    },
    reheat: () => graphRef.current?.d3ReheatSimulation(),
  }), [props.visibleNodeIds]);

  return <ForceGraph3D
    ref={graphRef}
    graphData={graphData}
    width={props.width}
    height={props.height}
    backgroundColor="#000000"
    nodeId="id"
    showNavInfo={false}
    enableNavigationControls
    nodeVal={(node) => 2.5 + Number(node.importance) * 5}
    nodeVisibility={(node) => props.visibleNodeIds.has(String(node.id))}
    nodeColor={(node) => props.nodeColor(node as FGNode)}
    nodeOpacity={0.9}
    nodeLabel={(node) => props.tooltip(node as FGNode)}
    linkVisibility={(link) => props.visibleLinkIds.has(String(link.id))}
    linkColor={(link) => props.linkColor(link as FGLink)}
    linkWidth={(link) => props.linkWidth(link as FGLink)}
    linkDirectionalArrowLength={3.5}
    linkDirectionalArrowRelPos={0.88}
    linkDirectionalArrowColor={(link) => props.linkColor(link as FGLink)}
    onNodeClick={(node) => props.onNodeClick(node as FGNode)}
    onNodeHover={(node) => props.onNodeHover(node as FGNode | null)}
    cooldownTicks={100}
    d3VelocityDecay={0.35}
  />;
});
