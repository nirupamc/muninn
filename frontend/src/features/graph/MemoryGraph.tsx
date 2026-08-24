import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import ForceGraph2D from "react-force-graph-2d";
import { MonitorOverlay, StatusStamp, TargetingContainer } from "@mdrbx/nerv-ui";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useElementSize } from "../../hooks/useElementSize";
import { useScope } from "../../lib/scope";
import { useContextSelection } from "../../lib/contextSelection";
import { MEMORY_TYPE_COLORS, STATUS_COLORS, edgeColor } from "../../lib/mappers";
import { ErrorState, EmptyState, LoadingState } from "../../components/ui/States";
import { MemoryInspector } from "../../components/inspector/MemoryInspector";
import { GraphFilters, defaultFilters } from "./GraphFilters";
import { useMemoryGraphData } from "./useMemoryGraphData";
import type { MemoryFilters } from "../../types/domain";
import type { FGLink, FGNode, GraphRendererHandle } from "./graphTypes";
import { cloneForRenderer } from "./rendererGraph";

const SpatialRenderer = lazy(() => import("./ForceGraph3DRenderer").then((module) => ({ default: module.ForceGraph3DRenderer })));
type GraphMode = "2d" | "3d";
const MODE_KEY = "munin.graph.mode";
const idOf = (endpoint: string | FGNode) => typeof endpoint === "string" ? endpoint : endpoint.id;
const html = (value: string) => value.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
function initialMode(): GraphMode { try { return sessionStorage.getItem(MODE_KEY) === "3d" ? "3d" : "2d"; } catch { return "2d"; } }

export function MemoryGraph() {
  const { namespace, setNamespace } = useScope();
  const contextSelection = useContextSelection();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const requestedMemoryId = searchParams.get("memory");
  const [mode, setModeState] = useState<GraphMode>(initialMode);
  const [nodeLimit, setNodeLimit] = useState(250);
  const [spatialLimit, setSpatialLimit] = useState(150);
  const [filters, setFilters] = useState<MemoryFilters>(() => defaultFilters(namespace));
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<FGNode | null>(null);
  const [hoverId, setHoverId] = useState<string | null>(null);
  const [zoom, setZoom] = useState(1);
  const [controlsOpen, setControlsOpen] = useState(false);
  const graph = useMemoryGraphData(namespace, nodeLimit);
  const rendererRef = useRef<GraphRendererHandle>(null);
  const fg2dRef = useRef<any>(null);
  const { ref: sizeRef, width, height } = useElementSize<HTMLDivElement>();

  const setMode = (next: GraphMode) => { setModeState(next); try { sessionStorage.setItem(MODE_KEY, next); } catch { /* unavailable storage */ } };
  useEffect(() => { setFilters((current) => ({ ...current, namespace, agentId: null })); setSelected(null); }, [namespace]);
  const domainNodes = graph.data?.nodes ?? [];
  const domainEdges = graph.data?.edges ?? [];
  const rendererGraph = useMemo(
    () => cloneForRenderer(domainNodes, domainEdges, mode === "3d" ? spatialLimit : nodeLimit),
    [domainNodes, domainEdges, mode, spatialLimit, nodeLimit],
  );
  const nodes = rendererGraph.nodes;
  const links = rendererGraph.links;
  const agents = useMemo(() => Array.from(new Set(domainNodes.map((node) => node.agentId?.trim() || "unknown"))).sort(), [domainNodes]);
  const searchMatches = useMemo(() => { const query = search.trim().toLowerCase(); return query ? nodes.filter((node) => node.content.toLowerCase().includes(query) || node.id.toLowerCase().includes(query)).slice(0, 8) : []; }, [nodes, search]);
  const visibleNodeIds = useMemo(() => new Set(nodes.filter((node) => (!filters.memoryType || node.memoryType === filters.memoryType) && (!filters.status || node.status === filters.status) && (!filters.agentId || (node.agentId?.trim() || "unknown") === filters.agentId) && node.confidence >= filters.minConfidence && node.importance >= filters.minImportance).map((node) => node.id)), [nodes, filters]);
  const visibleLinkIds = useMemo(() => new Set(links.filter((link) => visibleNodeIds.has(idOf(link.source)) && visibleNodeIds.has(idOf(link.target)) && (link.relationship === "derived_from" ? filters.showConsolidation : filters.showTemporal)).map((link) => link.id)), [links, visibleNodeIds, filters]);
  const emphasis = useMemo(() => { const nodeIds = new Set<string>(); const linkIds = new Set<string>(); for (const focus of [selected?.id, hoverId]) if (focus) { nodeIds.add(focus); for (const link of links) { const source = idOf(link.source); const target = idOf(link.target); if (source === focus || target === focus) { nodeIds.add(source); nodeIds.add(target); linkIds.add(link.id); } } } return { nodeIds, linkIds }; }, [selected, hoverId, links]);
  const query = search.trim().toLowerCase();
  const isDimmed = useCallback((node: FGNode) => (contextSelection.selectedMemoryIds.size > 0 && !contextSelection.selectedMemoryIds.has(node.id)) || (!!query && !node.content.toLowerCase().includes(query) && !node.id.toLowerCase().includes(query)) || (emphasis.nodeIds.size > 0 && !emphasis.nodeIds.has(node.id)), [query, emphasis, contextSelection.selectedMemoryIds]);
  const nodeColor = useCallback((node: FGNode) => node.status !== "active" ? STATUS_COLORS[node.status] : MEMORY_TYPE_COLORS[node.memoryType], []);
  const effectiveNodeColor = useCallback((node: FGNode) => isDimmed(node) ? "#182018" : contextSelection.selectedMemoryIds.has(node.id) ? "#20f0ff" : node.isConsolidated ? "#a472ff" : nodeColor(node), [isDimmed, nodeColor, contextSelection.selectedMemoryIds]);
  const isContextLink = useCallback((link: FGLink) => contextSelection.selectedMemoryIds.has(idOf(link.source)) && contextSelection.selectedMemoryIds.has(idOf(link.target)), [contextSelection.selectedMemoryIds]);
  const effectiveLinkColor = useCallback((link: FGLink) => link.relationship === "contradicts" ? edgeColor(link.relationship) : contextSelection.selectedMemoryIds.size > 0 && !isContextLink(link) ? "rgba(60,80,60,0.12)" : emphasis.linkIds.size > 0 && !emphasis.linkIds.has(link.id) ? "rgba(60,80,60,0.12)" : edgeColor(link.relationship), [contextSelection.selectedMemoryIds, emphasis.linkIds, isContextLink]);
  const effectiveLinkWidth = useCallback((link: FGLink) => link.relationship === "contradicts" ? 2.2 : isContextLink(link) ? 2.4 : emphasis.linkIds.has(link.id) ? 1.8 : 0.8, [emphasis.linkIds, isContextLink]);
  const tooltip = useCallback((node: FGNode) => `<div style="max-width:320px;background:#000;border:1px solid #20f0ff;padding:10px;font:13px/1.45 'Cascadia Mono','JetBrains Mono',monospace;color:#d8d8d0"><b style="color:#20f0ff">MEMORY // ${html(node.id.slice(0, 8).toUpperCase())}</b><div style="color:#a0a09a;text-transform:uppercase">${html(node.memoryType)} // ${html(node.status)}</div><div style="margin:7px 0;font-family:'Segoe UI',system-ui,sans-serif">${html(node.content.slice(0, 160))}</div><div>CONF ${node.confidence.toFixed(2)} // IMPORTANCE ${node.importance.toFixed(2)}</div></div>`, []);
  const drawNode = useCallback((node: FGNode, context: CanvasRenderingContext2D, scale: number) => { const radius = 2.5 + node.importance * 5; context.save(); context.globalAlpha = isDimmed(node) ? 0.14 : Math.max(0.5, node.confidence); context.beginPath(); context.arc(node.x ?? 0, node.y ?? 0, radius, 0, Math.PI * 2); context.fillStyle = nodeColor(node); context.fill(); const ring = contextSelection.selectedMemoryIds.has(node.id) ? "#20f0ff" : node.isConsolidated ? "#a472ff" : selected?.id === node.id ? "#50ff50" : hoverId === node.id ? "#ff9830" : null; if (ring) { context.beginPath(); context.arc(node.x ?? 0, node.y ?? 0, radius + 3, 0, Math.PI * 2); context.strokeStyle = ring; context.lineWidth = 2 / scale; context.stroke(); } if (scale > 2.2 || selected?.id === node.id || hoverId === node.id) { context.font = `${12 / scale}px 'Cascadia Mono', 'JetBrains Mono', monospace`; context.textAlign = "center"; context.textBaseline = "top"; context.fillStyle = "#d8d8d0"; context.globalAlpha = isDimmed(node) ? 0.18 : 0.95; context.fillText(node.label.slice(0, 28), node.x ?? 0, (node.y ?? 0) + radius + 2 / scale); } context.restore(); }, [hoverId, selected, isDimmed, nodeColor, contextSelection.selectedMemoryIds]);

  const fit = () => mode === "2d" ? fg2dRef.current?.zoomToFit?.(500, 50, (node: FGNode) => visibleNodeIds.has(node.id)) : rendererRef.current?.fit();
  const openNode = useCallback((node: FGNode) => { setSelected(node); if (mode === "2d") { fg2dRef.current?.centerAt?.(node.x, node.y, 500); fg2dRef.current?.zoom?.(3, 500); } else rendererRef.current?.focus(node); }, [mode]);
  const reset = () => { setSearch(""); setFilters(defaultFilters(namespace)); setSelected(null); setHoverId(null); if (mode === "2d") fg2dRef.current?.d3ReheatSimulation?.(); else rendererRef.current?.reheat(); };
  useEffect(() => { const id = contextSelection.focusedMemoryId ?? requestedMemoryId; if (!id) return; const node = nodes.find((candidate) => candidate.id === id); if (node) openNode(node); }, [contextSelection.focusedMemoryId, requestedMemoryId, nodes, openNode]);
  const spatialLimited = mode === "3d" && (domainNodes.length > nodes.length || !!graph.data?.limited);

  return <div className="graph-operations relative flex h-full min-h-0 flex-col overflow-hidden">
    <header className="graph-command-rail"><div className="graph-title-block"><span className="sector-kicker">SECTOR 02 // TOPOLOGY</span><h1>MEMORY NETWORK</h1></div><div className="topology-switch" aria-label="Memory topology mode"><span>MEMORY TOPOLOGY</span><button type="button" className={mode === "2d" ? "active" : ""} onClick={() => setMode("2d")} aria-pressed={mode === "2d"}>02D <b>// ANALYSIS</b></button><button type="button" className={mode === "3d" ? "active" : ""} onClick={() => setMode("3d")} aria-pressed={mode === "3d"}>03D <b>// SPATIAL</b></button></div><div className="graph-telemetry"><span>MODE <b>{mode.toUpperCase()}</b></span><span>NODES <b>{nodes.length}</b></span><span>EDGES <b>{links.length}</b></span><span>LIMIT <b>{mode === "3d" ? spatialLimit : nodeLimit}</b></span><span>SCOPE <b>{namespace}</b></span><span>CONTEXT TRACE <b className={contextSelection.result ? "trace-on" : ""}>{contextSelection.result ? "ON" : "OFF"}</b></span></div><div className="graph-actions"><button type="button" className="munin-btn" onClick={() => setControlsOpen((value) => !value)} aria-expanded={controlsOpen}>FILTER</button><button type="button" className="munin-btn" onClick={fit}>FIT</button><button type="button" className="munin-btn" onClick={reset}>RESET</button></div></header>
    <div className={`graph-filter-drawer ${controlsOpen ? "open" : ""}`}><div className="filter-search"><label>SEARCH NETWORK<input className="munin-input" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="> postgres" /></label><label>NAMESPACE<select className="munin-input" value={namespace} onChange={(event) => setNamespace(event.target.value)}>{graph.data?.namespaces.includes(namespace) ? null : <option value={namespace}>{namespace}</option>}{graph.data?.namespaces.map((value) => <option key={value}>{value}</option>)}</select></label><label>{mode === "3d" ? "SPATIAL LIMIT" : "NODE LIMIT"}<select className="munin-input" value={mode === "3d" ? spatialLimit : nodeLimit} onChange={(event) => mode === "3d" ? setSpatialLimit(Math.min(250, Number(event.target.value))) : setNodeLimit(Number(event.target.value))}>{mode === "3d" ? <><option value="100">100</option><option value="150">150</option><option value="250">250 MAX</option></> : <><option value="100">100</option><option value="250">250</option><option value="500">500</option></>}</select></label></div><GraphFilters filters={filters} onChange={setFilters} agents={agents} /></div>
    {searchMatches.length > 0 && <div className="graph-search-results" aria-label="Memory search results">{searchMatches.map((node) => <button type="button" key={node.id} onClick={() => openNode(node)} title={node.content}>{node.label}</button>)}</div>}
    <div ref={sizeRef} className="graph-canvas relative min-h-[260px] flex-1 bg-black"><MonitorOverlay label={`${mode.toUpperCase()} // MEMORY SPACE`} secondaryLabel={`${visibleNodeIds.size} VISIBLE`} color={mode === "3d" ? "cyan" : "green"} opacity={0.15} density="sparse" animated={false} className="pointer-events-none absolute inset-0 z-10" />{graph.loading && !graph.data && <LoadingState label="MAPPING MEMORY NETWORK" />}{graph.error && <ErrorState error={graph.error} onRetry={graph.reload} />}{graph.data && nodes.length === 0 && <EmptyState title="MEMORY NETWORK EMPTY" detail={`NO DURABLE MEMORIES FOUND FOR: ${namespace}`} />}{graph.data && nodes.length > 0 && width > 0 && mode === "2d" && <ForceGraph2D key="munin-graph-2d" ref={fg2dRef} graphData={{ nodes, links }} width={width} height={height} backgroundColor="#000000" nodeId="id" nodeVal={(node: any) => 2.5 + Number(node.importance) * 5} nodeVisibility={(node: any) => visibleNodeIds.has(node.id)} nodeCanvasObject={drawNode as any} nodeLabel={tooltip as any} linkVisibility={(link: any) => visibleLinkIds.has(link.id)} linkColor={(link: any) => effectiveLinkColor(link)} linkWidth={(link: any) => effectiveLinkWidth(link)} linkDirectionalArrowLength={4} linkDirectionalArrowRelPos={0.9} linkDirectionalArrowColor={(link: any) => edgeColor(link.relationship)} linkLabel={(link: any) => String(link.relationship).toUpperCase()} onNodeClick={(node: any) => openNode(node)} onNodeHover={(node: any) => setHoverId(node?.id ?? null)} onZoom={({ k }: { k: number }) => setZoom(k)} cooldownTicks={120} d3VelocityDecay={0.35} />}{graph.data && nodes.length > 0 && width > 0 && mode === "3d" && <Suspense fallback={<LoadingState label="INITIALIZING SPATIAL RENDERER" />}><SpatialRenderer key="munin-graph-3d" ref={rendererRef} nodes={nodes} links={links} width={width} height={height} visibleNodeIds={visibleNodeIds} visibleLinkIds={visibleLinkIds} nodeColor={effectiveNodeColor} nodeOpacity={(node) => isDimmed(node) ? 0.15 : Math.max(0.5, node.confidence)} linkColor={effectiveLinkColor} linkWidth={effectiveLinkWidth} tooltip={tooltip} onNodeClick={openNode} onNodeHover={(node) => setHoverId(node?.id ?? null)} /></Suspense>}{spatialLimited && <StatusStamp text="SPATIAL VIEW LIMITED" color="orange" rotation={0} bordered className="absolute left-4 top-4 z-20" />}{selected && <TargetingContainer label={`SELECTED // ${selected.id.slice(0, 8).toUpperCase()}`} color="cyan" showCrosshairs={false} className="graph-selection-card"><p>{selected.content}</p><span>1-HOP NEIGHBORHOOD HIGHLIGHTED</span>{contextSelection.traceByMemoryId.has(selected.id) && <button type="button" className="munin-btn" onClick={() => { contextSelection.setFocusedMemoryId(selected.id); navigate("/context"); }}>WHY SELECTED?</button>}</TargetingContainer>}<MemoryInspector node={selected} onClose={() => setSelected(null)} /></div>
    <footer className="graph-footer"><span>VISIBLE <b>{visibleNodeIds.size}</b></span><span>SELECTED <b>{selected ? selected.id.slice(0, 8).toUpperCase() : "—"}</b></span>{mode === "2d" && <span>ZOOM <b>{zoom.toFixed(1)}X</b></span>}{contextSelection.result && <button type="button" onClick={contextSelection.clear}>CLEAR CONTEXT TRACE</button>}{!!graph.data?.relationshipFailures && <span className="warning">RELATIONSHIP SOURCES UNAVAILABLE {graph.data.relationshipFailures}</span>}</footer>
  </div>;
}
