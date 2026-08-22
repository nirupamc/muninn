import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ForceGraph2D } from "react-force-graph";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useElementSize } from "../../hooks/useElementSize";
import { useScope } from "../../lib/scope";
import { useContextSelection } from "../../lib/contextSelection";
import { MEMORY_TYPE_COLORS, STATUS_COLORS, edgeColor } from "../../lib/mappers";
import { ErrorState, EmptyState, LoadingState } from "../../components/ui/States";
import { MemoryInspector } from "../../components/inspector/MemoryInspector";
import { GraphFilters, defaultFilters } from "./GraphFilters";
import { useMemoryGraphData } from "./useMemoryGraphData";
import type { MemoryNode, GraphEdge, MemoryFilters, RelationshipKind } from "../../types/domain";

interface FGNode extends MemoryNode { x?: number; y?: number }
interface FGLink extends Omit<GraphEdge, "source" | "target"> { source: string | FGNode; target: string | FGNode }

const idOf = (endpoint: string | FGNode) => typeof endpoint === "string" ? endpoint : endpoint.id;
const html = (value: string) => value.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");

export function MemoryGraph() {
  const { namespace, setNamespace } = useScope();
  const contextSelection = useContextSelection();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const requestedMemoryId = searchParams.get("memory");
  const [nodeLimit, setNodeLimit] = useState(250);
  const [filters, setFilters] = useState<MemoryFilters>(() => defaultFilters(namespace));
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<FGNode | null>(null);
  const [hoverId, setHoverId] = useState<string | null>(null);
  const [zoom, setZoom] = useState(1);
  const [controlsOpen, setControlsOpen] = useState(false);
  const graph = useMemoryGraphData(namespace, nodeLimit);
  const fgRef = useRef<any>(null);
  const { ref: sizeRef, width, height } = useElementSize<HTMLDivElement>();

  useEffect(() => {
    setFilters((current) => ({ ...current, namespace, agentId: null }));
    setSelected(null);
  }, [namespace]);

  const nodes = useMemo<FGNode[]>(() => (graph.data?.nodes ?? []).map((node) => ({ ...node })), [graph.data]);
  const links = useMemo<FGLink[]>(() => (graph.data?.edges ?? []).map((edge) => ({ ...edge })), [graph.data]);
  const agents = useMemo(() => Array.from(new Set(nodes.map((node) => node.agentId?.trim() || "unknown"))).sort(), [nodes]);
  const searchMatches = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return [];
    return nodes.filter((node) => node.content.toLowerCase().includes(query) || node.id.toLowerCase().includes(query)).slice(0, 8);
  }, [nodes, search]);

  useEffect(() => {
    if (!contextSelection.focusedMemoryId) return;
    const node = nodes.find((candidate) => candidate.id === contextSelection.focusedMemoryId);
    if (node) openNode(node);
  // openNode intentionally follows loaded graph coordinates.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [contextSelection.focusedMemoryId, nodes]);

  useEffect(() => {
    if (!requestedMemoryId) return;
    const node = nodes.find((candidate) => candidate.id === requestedMemoryId);
    if (node) openNode(node);
  // openNode intentionally follows loaded graph coordinates.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requestedMemoryId, nodes]);

  const visibleNodeIds = useMemo(() => {
    const ids = new Set<string>();
    for (const node of nodes) {
      if (filters.memoryType && node.memoryType !== filters.memoryType) continue;
      if (filters.status && node.status !== filters.status) continue;
      if (filters.agentId && (node.agentId?.trim() || "unknown") !== filters.agentId) continue;
      if (node.confidence < filters.minConfidence || node.importance < filters.minImportance) continue;
      ids.add(node.id);
    }
    return ids;
  }, [nodes, filters]);

  const visibleLinkIds = useMemo(() => {
    const ids = new Set<string>();
    for (const link of links) {
      if (!visibleNodeIds.has(idOf(link.source)) || !visibleNodeIds.has(idOf(link.target))) continue;
      if (link.relationship === "derived_from" ? filters.showConsolidation : filters.showTemporal) ids.add(link.id);
    }
    return ids;
  }, [links, visibleNodeIds, filters.showConsolidation, filters.showTemporal]);

  const emphasis = useMemo(() => {
    const nodeIds = new Set<string>();
    const linkIds = new Set<string>();
    if (selected) {
      nodeIds.add(selected.id);
      for (const link of links) {
        const source = idOf(link.source); const target = idOf(link.target);
        if (source === selected.id || target === selected.id) { nodeIds.add(source); nodeIds.add(target); linkIds.add(link.id); }
      }
    }
    if (hoverId) {
      nodeIds.add(hoverId);
      for (const link of links) {
        const source = idOf(link.source); const target = idOf(link.target);
        if (source === hoverId || target === hoverId) { nodeIds.add(source); nodeIds.add(target); linkIds.add(link.id); }
      }
    }
    return { nodeIds, linkIds };
  }, [selected, hoverId, links]);

  const query = search.trim().toLowerCase();
  const isSearchMatch = useCallback((node: FGNode) => !query || node.content.toLowerCase().includes(query) || node.id.toLowerCase().includes(query), [query]);
  const isDimmed = useCallback((node: FGNode) => {
    if (contextSelection.selectedMemoryIds.size > 0 && !contextSelection.selectedMemoryIds.has(node.id)) return true;
    if (!isSearchMatch(node)) return true;
    return emphasis.nodeIds.size > 0 && !emphasis.nodeIds.has(node.id);
  }, [isSearchMatch, emphasis, contextSelection.selectedMemoryIds]);

  const nodeColor = useCallback((node: FGNode) => {
    if (node.status !== "active") return STATUS_COLORS[node.status];
    return MEMORY_TYPE_COLORS[node.memoryType];
  }, []);

  const drawNode = useCallback((node: FGNode, context: CanvasRenderingContext2D, scale: number) => {
    const radius = 2.5 + node.importance * 5;
    context.save();
    context.globalAlpha = isDimmed(node) ? 0.14 : Math.max(0.45, node.confidence);
    context.beginPath(); context.arc(node.x ?? 0, node.y ?? 0, radius, 0, Math.PI * 2); context.fillStyle = nodeColor(node); context.fill();
    if (node.isConsolidated) { context.beginPath(); context.arc(node.x ?? 0, node.y ?? 0, radius + 2, 0, Math.PI * 2); context.strokeStyle = "#a472ff"; context.lineWidth = 1.2 / scale; context.stroke(); }
    if (contextSelection.selectedMemoryIds.has(node.id)) { context.beginPath(); context.arc(node.x ?? 0, node.y ?? 0, radius + 3, 0, Math.PI * 2); context.strokeStyle = "#27e36b"; context.lineWidth = 2.4 / scale; context.stroke(); }
    if (selected?.id === node.id || hoverId === node.id) { context.beginPath(); context.arc(node.x ?? 0, node.y ?? 0, radius + 3.5, 0, Math.PI * 2); context.strokeStyle = selected?.id === node.id ? "#22d3ee" : "#27e36b"; context.lineWidth = 2 / scale; context.stroke(); }
    if (scale > 2.2 || selected?.id === node.id || hoverId === node.id) {
      const label = node.label.slice(0, 28); context.font = `${10 / scale}px ui-monospace, monospace`; context.textAlign = "center"; context.textBaseline = "top"; context.fillStyle = "#c8d6c8"; context.globalAlpha = isDimmed(node) ? 0.18 : 0.9; context.fillText(label, node.x ?? 0, (node.y ?? 0) + radius + 2 / scale);
    }
    context.restore();
  }, [hoverId, selected, isDimmed, nodeColor, contextSelection.selectedMemoryIds]);

  const tooltip = useCallback((node: FGNode) => `<div style="max-width:280px;background:#000;border:1px solid #2f3d2f;padding:8px;font:11px monospace;color:#c8d6c8"><div style="color:#22d3ee">MEMORY // ${html(node.id.slice(0, 6).toUpperCase())}</div><div style="color:#5d6b5d;text-transform:uppercase">${html(node.memoryType)} // ${html(node.status)}</div><div style="margin:5px 0">${html(node.content.slice(0, 140))}</div><div>CONFIDENCE ${node.confidence.toFixed(2)} // IMPORTANCE ${node.importance.toFixed(2)}</div><div>AGENT ${html(node.agentId ?? "unknown")}</div></div>`, []);

  const graphData = useMemo(() => ({ nodes, links }), [nodes, links]);
  const fit = () => fgRef.current?.zoomToFit?.(500, 50, (node: FGNode) => visibleNodeIds.has(node.id));
  const openNode = (node: FGNode) => { setSelected(node); fgRef.current?.centerAt?.(node.x, node.y, 500); fgRef.current?.zoom?.(3, 500); };
  const reset = () => { setSearch(""); setFilters(defaultFilters(namespace)); setSelected(null); setHoverId(null); fgRef.current?.d3ReheatSimulation?.(); setTimeout(fit, 50); };
  const isContextLink = (link: FGLink) => contextSelection.selectedMemoryIds.has(idOf(link.source)) && contextSelection.selectedMemoryIds.has(idOf(link.target));

  return (
    <div className="relative flex h-full min-h-0 flex-col overflow-hidden">
      <header className="border-b border-[var(--munin-border)] bg-[var(--munin-panel)]">
        <div className="flex flex-wrap items-end gap-2 p-2">
          <label className="min-w-[170px] flex-1 font-mono text-[9px] uppercase text-[var(--munin-muted)]">Search network
            <input className="munin-input mt-1 w-full" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="> postgres" />
          </label>
          <label className="font-mono text-[9px] uppercase text-[var(--munin-muted)]">Namespace
            <select className="munin-input mt-1 block max-w-[210px]" value={namespace} onChange={(event) => setNamespace(event.target.value)}>{graph.data?.namespaces.includes(namespace) ? null : <option value={namespace}>{namespace}</option>}{graph.data?.namespaces.map((value) => <option key={value}>{value}</option>)}</select>
          </label>
          <label className="font-mono text-[9px] uppercase text-[var(--munin-muted)]">Node limit
            <select className="munin-input mt-1 block" value={nodeLimit} onChange={(event) => setNodeLimit(Number(event.target.value))}><option value="100">100</option><option value="250">250</option><option value="500">500</option></select>
          </label>
          <button type="button" className="munin-btn md:hidden" onClick={() => setControlsOpen((value) => !value)} aria-expanded={controlsOpen}>FILTERS</button>
          <button type="button" className="munin-btn" onClick={fit}>FIT</button><button type="button" className="munin-btn" onClick={reset}>RESET</button>
          {selected && <button type="button" className="munin-btn" onClick={() => setSelected(null)}>CLEAR FOCUS</button>}
          {contextSelection.result && <><span className="border border-[var(--munin-green)] px-2 py-1 font-mono text-[9px] text-[var(--munin-green)]">GRAPH MODE // CONTEXT TRACE</span><button type="button" className="munin-btn" onClick={contextSelection.clear}>CLEAR CONTEXT TRACE</button></>}
        </div>
        <div className={controlsOpen ? "block" : "hidden md:block"}><GraphFilters filters={filters} onChange={setFilters} agents={agents} /></div>
        {searchMatches.length > 0 && <div className="flex max-h-24 flex-wrap gap-1 overflow-auto border-t border-[var(--munin-border)] bg-black p-2" aria-label="Memory search results">{searchMatches.map((node) => <button type="button" key={node.id} className="munin-btn max-w-[260px] truncate text-[var(--munin-cyan)]" onClick={() => openNode(node)} title={node.content}>{node.label}</button>)}</div>}
      </header>

      <div ref={sizeRef} className="relative min-h-[260px] flex-1 bg-black">
        {graph.loading && !graph.data && <LoadingState label="MAPPING MEMORY NETWORK" />}
        {graph.error && <ErrorState error={graph.error} onRetry={graph.reload} />}
        {graph.data && nodes.length === 0 && <EmptyState title="MEMORY NETWORK EMPTY" detail={`NO DURABLE MEMORIES FOUND FOR: ${namespace}`} />}
        {graph.data && nodes.length > 0 && width > 0 && <ForceGraph2D
          ref={fgRef} graphData={graphData} width={width} height={height} backgroundColor="#000000" nodeId="id"
          nodeVal={(node: any) => 2.5 + Number(node.importance) * 5} nodeVisibility={(node: any) => visibleNodeIds.has(node.id)} nodeCanvasObject={drawNode as any} nodeLabel={tooltip as any}
          linkVisibility={(link: any) => visibleLinkIds.has(link.id)} linkColor={(link: any) => link.relationship === "contradicts" ? edgeColor(link.relationship) : contextSelection.selectedMemoryIds.size > 0 && !isContextLink(link) ? "rgba(60,80,60,0.12)" : emphasis.linkIds.size > 0 && !emphasis.linkIds.has(link.id) ? "rgba(60,80,60,0.12)" : edgeColor(link.relationship)}
          linkWidth={(link: any) => link.relationship === "contradicts" ? 2.2 : isContextLink(link) ? 2.4 : emphasis.linkIds.has(link.id) ? 1.8 : 0.8} linkDirectionalArrowLength={4} linkDirectionalArrowRelPos={0.9} linkDirectionalArrowColor={(link: any) => edgeColor(link.relationship)} linkLabel={(link: any) => String(link.relationship).toUpperCase()}
          onNodeClick={(node: any) => openNode(node as FGNode)} onNodeHover={(node: any) => setHoverId(node?.id ?? null)} onZoom={({ k }: { k: number }) => setZoom(k)} cooldownTicks={120} d3VelocityDecay={0.35}
        />}
        {selected && <div className="absolute bottom-2 left-2 max-w-[calc(100%-1rem)] border border-[var(--munin-cyan)] bg-black p-2 font-mono text-[10px]"><div className="text-[var(--munin-cyan)]">SELECTED // {selected.id.slice(0, 6).toUpperCase()}</div><div className="truncate text-[var(--munin-text)]">{selected.content}</div><div className="text-[var(--munin-muted)]">1-HOP NEIGHBORHOOD HIGHLIGHTED</div>{contextSelection.traceByMemoryId.has(selected.id) && <button type="button" className="munin-btn mt-2" onClick={() => { contextSelection.setFocusedMemoryId(selected.id); navigate("/context"); }}>WHY SELECTED?</button>}</div>}
        <MemoryInspector node={selected} onClose={() => setSelected(null)} />
      </div>

      <footer className="flex flex-wrap gap-x-4 gap-y-1 border-t border-[var(--munin-border)] bg-[var(--munin-panel)] px-3 py-1 font-mono text-[9px] text-[var(--munin-muted)]">
        <span>NODES <b className="text-[var(--munin-green)]">{nodes.length}</b></span><span>EDGES <b className="text-[var(--munin-green)]">{links.length}</b></span><span>VISIBLE <b className="text-[var(--munin-cyan)]">{visibleNodeIds.size}</b></span><span>SCOPE <b className="text-[var(--munin-cyan)]">{namespace}</b></span><span>SELECTED <b className="text-[var(--munin-cyan)]">{selected ? selected.id.slice(0, 6).toUpperCase() : "—"}</b></span><span>ZOOM {zoom.toFixed(1)}x</span>
        {graph.data?.limited && <span className="text-[var(--munin-orange)]">LIMITED {nodes.length} / {graph.data.completeDataset ? graph.data.namespaceTotal : `${graph.data.namespaceTotal}+`}</span>}
        {!!graph.data?.relationshipFailures && <span className="text-[var(--munin-orange)]">RELATIONSHIP SOURCES UNAVAILABLE {graph.data.relationshipFailures}</span>}
      </footer>
    </div>
  );
}
