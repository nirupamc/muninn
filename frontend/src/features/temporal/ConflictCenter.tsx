import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { MemoryInspector } from "../../components/inspector/MemoryInspector";
import { EmptyState, ErrorState, LoadingState } from "../../components/ui/States";
import { StatusTag, TypeTag } from "../../components/ui/Tags";
import { fmtDateTime, fmtNum, shortId } from "../../lib/format";
import { useScope } from "../../lib/scope";
import type { MemoryType, TemporalRecordRead } from "../../types/api";
import type { MemoryNode } from "../../types/domain";
import { useTemporalData } from "./useTemporalData";

const TYPES: MemoryType[] = ["fact", "preference", "project", "goal", "decision", "event", "relationship", "procedure", "other"];

export function ConflictCenter() {
  const { namespace, setNamespace } = useScope();
  const data = useTemporalData(namespace);
  const navigate = useNavigate();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [type, setType] = useState<MemoryType | "all">("all");
  const [agent, setAgent] = useState("all");
  const [minConfidence, setMinConfidence] = useState(0);
  const memoryById = useMemo(() => new Map((data.data?.memories ?? []).map((memory) => [memory.id, memory])), [data.data]);
  const agents = useMemo(() => Array.from(new Set((data.data?.memories ?? []).map((memory) => memory.agentId?.trim() || "unknown"))).sort(), [data.data]);
  const allConflicts = useMemo(() => (data.data?.records ?? []).filter((record) => record.relationship.toUpperCase() === "CONTRADICTS").sort((a, b) => b.created_at.localeCompare(a.created_at)), [data.data]);
  const conflicts = useMemo(() => allConflicts.filter((record) => {
    if ((record.relationship_confidence ?? 0) < minConfidence) return false;
    const memories = [memoryById.get(record.matched_memory_id ?? ""), memoryById.get(record.created_memory_id ?? "")].filter(Boolean) as MemoryNode[];
    return memories.some((memory) => (type === "all" || memory.memoryType === type) && (agent === "all" || (memory.agentId?.trim() || "unknown") === agent));
  }), [allConflicts, memoryById, type, agent, minConfidence]);

  if (data.loading && !data.data) return <LoadingState label="LOADING CONFLICT INDEX" />;
  if (data.error && !data.data) return <ErrorState error={data.error} onRetry={data.reload} />;

  return <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden">
    <header className="border-b border-[var(--munin-border)] bg-[var(--munin-panel)] px-3 py-2">
      <div className="flex flex-wrap items-end gap-2"><div className="mr-auto"><h1 className="font-display text-[15px] tracking-wide-ext text-[var(--munin-red)]">Conflict Center</h1><p className="font-mono text-[9px] text-[var(--munin-muted)]">READ-ONLY M4 CONTRADICTION INDEX</p></div>
        <Select label="Namespace" value={namespace} options={data.data?.namespaces ?? [namespace]} onChange={setNamespace} />
        <Select label="Memory Type" value={type} options={["all", ...TYPES]} onChange={(value) => setType(value as MemoryType | "all")} />
        <Select label="Agent" value={agent} options={["all", ...agents]} onChange={setAgent} />
        <label className="font-mono text-[9px] uppercase text-[var(--munin-muted)]">Min relationship confidence<span className="mt-1 flex items-center gap-2"><input type="range" min="0" max="1" step="0.05" value={minConfidence} onChange={(event) => setMinConfidence(Number(event.target.value))} aria-label="Minimum relationship confidence" /><output className="w-8 text-[var(--munin-cyan)]">{minConfidence.toFixed(2)}</output></span></label>
        <button type="button" className="munin-btn" onClick={() => { setType("all"); setAgent("all"); setMinConfidence(0); }}>RESET</button>
      </div>
    </header>
    {data.data && <div className="flex flex-wrap gap-x-4 border-b border-[var(--munin-border)] px-3 py-1 font-mono text-[9px] text-[var(--munin-muted)]"><span>REAL CONTRADICTIONS <b className={allConflicts.length ? "text-[var(--munin-red)]" : "text-[var(--munin-green)]"}>{allConflicts.length}</b></span><span>VISIBLE <b className="text-[var(--munin-cyan)]">{conflicts.length}</b></span><span>SCOPE <b className="text-[var(--munin-cyan)]">{namespace}</b></span>{data.data.historyFailures > 0 && <span className="text-[var(--munin-orange)]">CONFLICT INDEX DEGRADED // {data.data.historyFailures} HISTORY REQUESTS FAILED</span>}</div>}
    <main className="min-h-0 flex-1 overflow-y-auto p-3">
      {data.data && data.data.historyFailures === 0 && allConflicts.length === 0 && <div className="mx-auto mt-10 max-w-xl border border-[var(--munin-green)] p-6 text-center"><div className="font-display text-[13px] tracking-wide-ext text-[var(--munin-green)]">Status // Nominal</div><EmptyState title="NO UNRESOLVED CONTRADICTIONS" detail={<>IN CURRENT SCOPE // {namespace}</>} /></div>}
      {data.data && data.data.historyFailures > 0 && allConflicts.length === 0 && <div className="mx-auto mt-10 max-w-xl border border-[var(--munin-orange)] p-6 text-center"><div className="font-display text-[13px] tracking-wide-ext text-[var(--munin-orange)]">Conflict Index Degraded</div><p className="mt-2 font-mono text-[10px] text-[var(--munin-muted)]">ZERO CONFLICTS CANNOT BE CONFIRMED // {data.data.historyFailures} HISTORY REQUESTS FAILED</p><button type="button" className="munin-btn mt-4" onClick={data.reload}>RETRY</button></div>}
      {allConflicts.length > 0 && conflicts.length === 0 && <EmptyState title="NO CONFLICTS MATCH CURRENT FILTERS" />}
      <div className="mx-auto max-w-6xl space-y-4">{conflicts.map((record) => <ConflictCard key={record.id} record={record} left={memoryById.get(record.matched_memory_id ?? "")} right={memoryById.get(record.created_memory_id ?? "")} onOpen={setSelectedId} onGraph={(id) => navigate(`/graph?memory=${encodeURIComponent(id)}`)} onTimeline={(id) => navigate(`/timeline?memory=${encodeURIComponent(id)}`)} />)}</div>
    </main>
    <MemoryInspector memoryId={selectedId} onClose={() => setSelectedId(null)} />
  </div>;
}

function ConflictCard({ record, left, right, onOpen, onGraph, onTimeline }: { record: TemporalRecordRead; left?: MemoryNode; right?: MemoryNode; onOpen: (id: string) => void; onGraph: (id: string) => void; onTimeline: (id: string) => void }) {
  const focusId = right?.id ?? left?.id;
  return <article className="border border-[var(--munin-red)] bg-black" tabIndex={0} aria-label={`Memory contradiction ${shortId(record.id)}`}><header className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--munin-red)] px-3 py-2"><h2 className="font-display text-[12px] tracking-wide-ext text-[var(--munin-red)]">▓ Memory Conflict ▓</h2><time className="font-mono text-[9px] text-[var(--munin-muted)]">{fmtDateTime(record.created_at)}</time></header><div className="grid items-stretch md:grid-cols-[1fr_72px_1fr]"><MemorySide label="Memory A" memory={left} onOpen={onOpen} /><div className="flex items-center justify-center border-y border-[var(--munin-red)] py-3 font-display text-[13px] text-[var(--munin-red)] md:border-x md:border-y-0">VS</div><MemorySide label="Memory B" memory={right} onOpen={onOpen} /></div><footer className="border-t border-[var(--munin-red)] p-3 font-mono text-[9px]"><dl className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4"><div><dt className="text-[var(--munin-muted)]">RELATIONSHIP</dt><dd className="text-[var(--munin-red)]">CONTRADICTS</dd></div><div><dt className="text-[var(--munin-muted)]">RELATIONSHIP CONFIDENCE</dt><dd className="text-[var(--munin-text)]">{fmtNum(record.relationship_confidence)}</dd></div><div><dt className="text-[var(--munin-muted)]">REASON CODES</dt><dd className="break-words text-[var(--munin-cyan)]">{record.reason_codes.length ? record.reason_codes.join(" // ") : "Unavailable"}</dd></div><div><dt className="text-[var(--munin-muted)]">DECISION ID</dt><dd className="text-[var(--munin-text)]">{shortId(record.id)}</dd></div></dl>{focusId && <div className="mt-3 flex flex-wrap gap-2"><button type="button" className="munin-btn" onClick={() => onGraph(focusId)}>VIEW IN GRAPH</button><button type="button" className="munin-btn" onClick={() => onTimeline(focusId)}>VIEW TIMELINE</button></div>}</footer></article>;
}

function MemorySide({ label, memory, onOpen }: { label: string; memory?: MemoryNode; onOpen: (id: string) => void }) { if (!memory) return <div className="p-4 font-mono text-[10px] text-[var(--munin-muted)]">{label.toUpperCase()} // DETAIL UNAVAILABLE</div>; return <section className="p-4"><div className="flex flex-wrap items-center gap-2"><h3 className="font-display text-[10px] tracking-wide-ext text-[var(--munin-cyan)]">{label}</h3><span className="font-mono text-[9px] text-[var(--munin-muted)]">{shortId(memory.id)}</span></div><div className="mt-2 flex gap-2"><TypeTag type={memory.memoryType} /><StatusTag status={memory.status} /></div><p className="mt-3 whitespace-pre-wrap font-mono text-[11px] leading-5 text-[var(--munin-text)]">{memory.content}</p><dl className="mt-3 grid grid-cols-2 gap-2 font-mono text-[9px]"><div><dt className="text-[var(--munin-muted)]">CONFIDENCE</dt><dd>{fmtNum(memory.confidence)}</dd></div><div><dt className="text-[var(--munin-muted)]">AGENT</dt><dd>{memory.agentId ?? "unknown"}</dd></div></dl><button type="button" className="munin-btn mt-3" onClick={() => onOpen(memory.id)}>OPEN {label.toUpperCase()}</button></section>; }
function Select({ label, value, options, onChange }: { label: string; value: string; options: string[]; onChange: (value: string) => void }) { return <label className="font-mono text-[9px] uppercase text-[var(--munin-muted)]">{label}<select className="munin-input mt-1 block min-w-28" value={value} onChange={(event) => onChange(event.target.value)}>{options.map((option) => <option key={option} value={option}>{option.toUpperCase()}</option>)}</select></label>; }
