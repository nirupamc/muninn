import { useEffect, useMemo, useState } from "react";
import { useAllMemories } from "../../hooks/useMuninData";
import { useScope } from "../../lib/scope";
import { ErrorState, EmptyState, LoadingState } from "../../components/ui/States";
import { TypeTag, StatusTag } from "../../components/ui/Tags";
import { MemoryInspector } from "../../components/inspector/MemoryInspector";
import { fmtDateTime, fmtNum } from "../../lib/format";
import type { MemoryNode } from "../../types/domain";
import type { MemoryStatus, MemoryType } from "../../types/api";

type SortKey = "created" | "updated" | "importance" | "confidence" | "type" | "status";
type Direction = "asc" | "desc";

const TYPES: MemoryType[] = ["fact", "preference", "project", "goal", "decision", "event", "relationship", "procedure", "other"];
const STATUSES: MemoryStatus[] = ["active", "superseded", "invalidated", "archived"];

function compare(a: MemoryNode, b: MemoryNode, key: SortKey): number {
  switch (key) {
    case "created": return a.createdAt.localeCompare(b.createdAt);
    case "updated": return a.updatedAt.localeCompare(b.updatedAt);
    case "importance": return a.importance - b.importance;
    case "confidence": return a.confidence - b.confidence;
    case "type": return a.memoryType.localeCompare(b.memoryType);
    case "status": return a.status.localeCompare(b.status);
  }
}

export function MemoryExplorer() {
  const { namespace, setNamespace } = useScope();
  const memories = useAllMemories();
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState(namespace);
  const [type, setType] = useState<MemoryType | "all">("all");
  const [status, setStatus] = useState<MemoryStatus | "all">("all");
  const [agent, setAgent] = useState("all");
  const [minConfidence, setMinConfidence] = useState(0);
  const [minImportance, setMinImportance] = useState(0);
  const [sortKey, setSortKey] = useState<SortKey>("updated");
  const [direction, setDirection] = useState<Direction>("desc");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  useEffect(() => setScope(namespace), [namespace]);

  const options = useMemo(() => {
    const all = memories.data?.memories ?? [];
    const namespaces = Array.from(new Set(all.map((memory) => memory.namespace))).sort();
    const scoped = scope === "all" ? all : all.filter((memory) => memory.namespace === scope);
    const agents = Array.from(new Set(scoped.map((memory) => memory.agentId?.trim() || "unknown"))).sort();
    return { namespaces, agents };
  }, [memories.data, scope]);

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return [...(memories.data?.memories ?? [])]
      .filter((memory) => {
        if (scope !== "all" && memory.namespace !== scope) return false;
        if (type !== "all" && memory.memoryType !== type) return false;
        if (status !== "all" && memory.status !== status) return false;
        if (agent !== "all" && (memory.agentId?.trim() || "unknown") !== agent) return false;
        if (memory.confidence < minConfidence || memory.importance < minImportance) return false;
        if (q && !memory.content.toLowerCase().includes(q) && !memory.id.toLowerCase().includes(q)) return false;
        return true;
      })
      .sort((a, b) => {
        const order = compare(a, b, sortKey) || a.id.localeCompare(b.id);
        return direction === "asc" ? order : -order;
      });
  }, [memories.data, query, scope, type, status, agent, minConfidence, minImportance, sortKey, direction]);

  const reset = () => {
    setQuery(""); setScope(namespace); setType("all"); setStatus("all"); setAgent("all");
    setMinConfidence(0); setMinImportance(0); setSortKey("updated"); setDirection("desc");
  };

  if (memories.loading && !memories.data) return <LoadingState label="MEMORY INDEX SYNCHRONIZING" />;
  if (memories.error) return <ErrorState error={memories.error} onRetry={memories.reload} />;
  const total = memories.data?.memories.length ?? 0;

  return (
    <div className="relative flex h-full min-h-0 overflow-hidden">
      <section className="flex min-w-0 flex-1 flex-col" aria-label="Memory Explorer">
        <header className="border-b border-[var(--munin-border)] bg-[var(--munin-panel)] p-2 sm:p-3">
          <div className="mb-2 flex flex-wrap items-end gap-2">
            <label className="min-w-[180px] flex-1 font-mono text-[9px] uppercase tracking-wider text-[var(--munin-muted)]">
              Search memories // text
              <input className="munin-input mt-1 w-full" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="> postgres" />
            </label>
            <label className="font-mono text-[9px] uppercase text-[var(--munin-muted)]">Scope
              <select className="munin-input mt-1 block max-w-[210px]" value={scope} onChange={(event) => { const value = event.target.value; setScope(value); setAgent("all"); if (value !== "all") setNamespace(value); }}>
                <option value="all">ALL NAMESPACES</option>
                {options.namespaces.map((value) => <option key={value} value={value}>{value}</option>)}
              </select>
            </label>
            <label className="font-mono text-[9px] uppercase text-[var(--munin-muted)]">Type
              <select className="munin-input mt-1 block" value={type} onChange={(event) => setType(event.target.value as MemoryType | "all")}>
                <option value="all">ALL</option>{TYPES.map((value) => <option key={value}>{value}</option>)}
              </select>
            </label>
            <label className="font-mono text-[9px] uppercase text-[var(--munin-muted)]">Status
              <select className="munin-input mt-1 block" value={status} onChange={(event) => setStatus(event.target.value as MemoryStatus | "all")}>
                <option value="all">ALL</option>{STATUSES.map((value) => <option key={value}>{value}</option>)}
              </select>
            </label>
            <label className="font-mono text-[9px] uppercase text-[var(--munin-muted)]">Agent provenance
              <select className="munin-input mt-1 block max-w-[180px]" value={agent} onChange={(event) => setAgent(event.target.value)}>
                <option value="all">ALL</option>{options.agents.map((value) => <option key={value}>{value}</option>)}
              </select>
            </label>
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <label className="font-mono text-[9px] uppercase text-[var(--munin-muted)]">Min confidence <span className="text-[var(--munin-cyan)]">{minConfidence.toFixed(2)}</span>
              <input className="mt-2 block w-28 accent-[var(--munin-cyan)]" type="range" min="0" max="1" step="0.05" value={minConfidence} onChange={(event) => setMinConfidence(Number(event.target.value))} />
            </label>
            <label className="font-mono text-[9px] uppercase text-[var(--munin-muted)]">Min stored importance <span className="text-[var(--munin-cyan)]">{minImportance.toFixed(2)}</span>
              <input className="mt-2 block w-28 accent-[var(--munin-cyan)]" type="range" min="0" max="1" step="0.05" value={minImportance} onChange={(event) => setMinImportance(Number(event.target.value))} />
            </label>
            <label className="font-mono text-[9px] uppercase text-[var(--munin-muted)]">Sort
              <select className="munin-input mt-1 block" value={sortKey} onChange={(event) => setSortKey(event.target.value as SortKey)}>
                <option value="updated">UPDATED</option><option value="created">CREATED</option><option value="importance">IMPORTANCE</option><option value="confidence">CONFIDENCE</option><option value="type">TYPE</option><option value="status">STATUS</option>
              </select>
            </label>
            <button type="button" className="munin-btn" onClick={() => setDirection((value) => value === "asc" ? "desc" : "asc")} aria-label={`Sort ${direction === "asc" ? "ascending" : "descending"}`}>{direction === "asc" ? "ASC ↑" : "DESC ↓"}</button>
            <button type="button" className="munin-btn" onClick={reset}>RESET FILTERS</button>
            <div className="ml-auto font-mono text-[10px] text-[var(--munin-muted)]">SHOWING <span className="text-[var(--munin-green)]">{rows.length}</span> / {memories.data?.complete ? total : `${total}+`}</div>
          </div>
          {!memories.data?.complete && <div className="mt-2 font-mono text-[10px] text-[var(--munin-orange)]">DATASET CAPPED AT 10,000 RECORDS</div>}
        </header>

        {total === 0 ? <EmptyState title="NO DURABLE MEMORIES FOUND" /> : rows.length === 0 ? <EmptyState title="NO MEMORIES MATCH CURRENT FILTERS" /> : (
          <div className="min-h-0 flex-1 overflow-auto">
            <table className="munin-table table-fixed" aria-label="Memory records">
              <thead><tr><th className="w-[100px]">Type</th><th className="w-[110px]">Status</th><th>Content</th><th className="hidden w-[150px] lg:table-cell">Namespace</th><th className="hidden w-[110px] md:table-cell">Agent</th><th className="hidden w-[80px] sm:table-cell">Importance</th><th className="w-[80px]">Confidence</th><th className="hidden w-[150px] xl:table-cell">Updated</th></tr></thead>
              <tbody>{rows.map((memory) => (
                <tr key={memory.id} className="munin-row focus-visible:outline focus-visible:outline-1 focus-visible:outline-[var(--munin-cyan)]" tabIndex={0} aria-label={`Inspect memory ${memory.id}`} onClick={() => setSelectedId(memory.id)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); setSelectedId(memory.id); } }}>
                  <td><TypeTag type={memory.memoryType} /></td><td><StatusTag status={memory.status} /></td>
                  <td><div className="truncate text-[var(--munin-text)]" title={memory.content}>{memory.content}</div><div className="mt-1 truncate text-[9px] text-[var(--munin-muted)] md:hidden">{memory.agentId ?? "unknown"} // {memory.namespace}</div></td>
                  <td className="hidden truncate text-[var(--munin-cyan)] lg:table-cell">{memory.namespace}</td><td className="hidden truncate md:table-cell">{memory.agentId ?? "unknown"}</td>
                  <td className="hidden sm:table-cell">{fmtNum(memory.importance)}</td><td>{fmtNum(memory.confidence)}</td><td className="hidden xl:table-cell">{fmtDateTime(memory.updatedAt)}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </section>
      <MemoryInspector memoryId={selectedId} onClose={() => setSelectedId(null)} />
    </div>
  );
}
