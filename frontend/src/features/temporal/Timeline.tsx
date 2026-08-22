import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { MemoryInspector } from "../../components/inspector/MemoryInspector";
import { EmptyState, ErrorState, LoadingState } from "../../components/ui/States";
import { StatusTag, TypeTag } from "../../components/ui/Tags";
import { fmtDateTime, fmtNum, shortId } from "../../lib/format";
import { useScope } from "../../lib/scope";
import type { MemoryStatus, MemoryType, TemporalRecordRead } from "../../types/api";
import type { MemoryNode } from "../../types/domain";
import { buildTemporalChains, useTemporalData, type TemporalRelationship } from "./useTemporalData";

const TYPES: MemoryType[] = ["fact", "preference", "project", "goal", "decision", "event", "relationship", "procedure", "other"];
const STATUSES: MemoryStatus[] = ["active", "superseded", "invalidated", "archived"];
const RELATIONSHIPS: TemporalRelationship[] = ["SUPERSEDES", "UPDATES", "CONTRADICTS"];
const RELATION_COLORS: Record<TemporalRelationship, string> = { SUPERSEDES: "var(--munin-orange)", UPDATES: "#ffc24b", CONTRADICTS: "var(--munin-red)" };

export function Timeline() {
  const { namespace, setNamespace } = useScope();
  const data = useTemporalData(namespace);
  const [params] = useSearchParams();
  const focusedId = params.get("memory");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [type, setType] = useState<MemoryType | "all">("all");
  const [status, setStatus] = useState<MemoryStatus | "all">("all");
  const [agent, setAgent] = useState("all");
  const [relationship, setRelationship] = useState<TemporalRelationship | "all">("all");

  const memoryById = useMemo(() => new Map((data.data?.memories ?? []).map((memory) => [memory.id, memory])), [data.data]);
  const agents = useMemo(() => Array.from(new Set((data.data?.memories ?? []).map((memory) => memory.agentId?.trim() || "unknown"))).sort(), [data.data]);
  const chains = useMemo(() => {
    const q = query.trim().toLowerCase();
    const records = (data.data?.records ?? []).filter((record) => {
      if (relationship !== "all" && record.relationship.toUpperCase() !== relationship) return false;
      const memories = [memoryById.get(record.matched_memory_id ?? ""), memoryById.get(record.created_memory_id ?? "")].filter(Boolean) as MemoryNode[];
      return memories.some((memory) => {
        if (type !== "all" && memory.memoryType !== type) return false;
        if (status !== "all" && memory.status !== status) return false;
        if (agent !== "all" && (memory.agentId?.trim() || "unknown") !== agent) return false;
        return !q || memory.id.toLowerCase().includes(q) || memory.content.toLowerCase().includes(q);
      });
    });
    return buildTemporalChains(records);
  }, [data.data, memoryById, query, type, status, agent, relationship]);

  if (data.loading && !data.data) return <LoadingState label="LOADING TEMPORAL INDEX" />;
  if (data.error && !data.data) return <ErrorState error={data.error} onRetry={data.reload} />;

  return <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden">
    <header className="border-b border-[var(--munin-border)] bg-[var(--munin-panel)] px-3 py-2">
      <div className="flex flex-wrap items-end gap-2">
        <div className="mr-auto"><h1 className="font-display text-[15px] tracking-wide-ext text-[var(--munin-green)]">Temporal Timeline</h1><p className="font-mono text-[9px] text-[var(--munin-muted)]">M4 AUTHORITATIVE RELATIONSHIP HISTORY</p></div>
        <label className="font-mono text-[9px] uppercase text-[var(--munin-muted)]">Search<input className="munin-input mt-1 block w-52" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="content or memory ID" /></label>
        <Select label="Namespace" value={namespace} onChange={setNamespace} options={data.data?.namespaces ?? [namespace]} />
        <Select label="Type" value={type} onChange={(value) => setType(value as MemoryType | "all")} options={["all", ...TYPES]} />
        <Select label="Status" value={status} onChange={(value) => setStatus(value as MemoryStatus | "all")} options={["all", ...STATUSES]} />
        <Select label="Agent" value={agent} onChange={setAgent} options={["all", ...agents]} />
        <Select label="Relationship" value={relationship} onChange={(value) => setRelationship(value as TemporalRelationship | "all")} options={["all", ...RELATIONSHIPS]} />
        <button type="button" className="munin-btn" onClick={() => { setQuery(""); setType("all"); setStatus("all"); setAgent("all"); setRelationship("all"); }}>RESET</button>
      </div>
    </header>

    {data.data && <div className="flex flex-wrap gap-x-4 border-b border-[var(--munin-border)] px-3 py-1 font-mono text-[9px] text-[var(--munin-muted)]"><span>CHAINS <b className="text-[var(--munin-cyan)]">{chains.length}</b></span><span>TRANSITIONS <b className="text-[var(--munin-cyan)]">{chains.reduce((count, chain) => count + chain.records.length, 0)}</b></span><span>MEMORIES <b className="text-[var(--munin-green)]">{data.data.memories.length}</b></span>{!data.data.completeDataset && <span className="text-[var(--munin-orange)]">DATASET CAPPED AT 10,000</span>}{data.data.historyFailures > 0 && <span className="text-[var(--munin-orange)]">TEMPORAL INDEX DEGRADED // {data.data.historyFailures} FAILED</span>}</div>}

    <main className="min-h-0 flex-1 overflow-y-auto p-3">
      {data.data && data.data.records.length === 0 && <EmptyState title="NO TEMPORAL TRANSITIONS FOUND" detail={<>Current scope has {data.data.memories.length} memories but no recorded SUPERSEDES / UPDATES / CONTRADICTS relationships.</>} />}
      {data.data && data.data.records.length > 0 && chains.length === 0 && <EmptyState title="NO TRANSITIONS MATCH CURRENT FILTERS" />}
      <div className="mx-auto max-w-5xl space-y-4">{chains.map((chain, index) => <section key={chain.id} className="munin-panel" aria-labelledby={`chain-${chain.id}`}><header className="border-b border-[var(--munin-border)] px-3 py-2"><h2 id={`chain-${chain.id}`} className="font-display text-[11px] tracking-wide-ext text-[var(--munin-cyan)]">Chain {String(index + 1).padStart(2, "0")} // {chain.memoryIds.length} Memories</h2></header><ol className="p-3">{chain.records.map((record) => <Transition key={record.id} record={record} source={memoryById.get(record.matched_memory_id ?? "")} target={memoryById.get(record.created_memory_id ?? "")} focusedId={focusedId} onOpen={setSelectedId} />)}</ol></section>)}</div>
    </main>
    <MemoryInspector memoryId={selectedId} onClose={() => setSelectedId(null)} />
  </div>;
}

function Transition({ record, source, target, focusedId, onOpen }: { record: TemporalRecordRead; source?: MemoryNode; target?: MemoryNode; focusedId: string | null; onOpen: (id: string) => void }) {
  const relationship = record.relationship.toUpperCase() as TemporalRelationship;
  return <li className="mb-3 last:mb-0"><MemoryItem memory={source} focused={source?.id === focusedId} onOpen={onOpen} /><div className="ml-4 border-l-2 py-3 pl-4 font-mono text-[10px]" style={{ borderColor: RELATION_COLORS[relationship], color: RELATION_COLORS[relationship] }}><div className="font-display tracking-wide-ext">{relationship} ↓</div><div className="mt-1 text-[var(--munin-muted)]">DECIDED {fmtDateTime(record.created_at)} // CONF {fmtNum(record.relationship_confidence)}</div>{record.reason_codes.length > 0 && <div className="break-words text-[var(--munin-cyan)]">{record.reason_codes.join(" // ")}</div>}<div className="text-[var(--munin-muted)]">OLD STATUS {record.old_status ?? "Unavailable"} → {record.new_old_status ?? "Unavailable"}</div><div className="text-[var(--munin-muted)]">OLD VALID UNTIL {fmtDateTime(record.old_valid_until_before)} → {fmtDateTime(record.old_valid_until_after)}</div><div className="text-[var(--munin-muted)]">NEW VALID FROM {fmtDateTime(record.new_valid_from)}</div></div><MemoryItem memory={target} focused={target?.id === focusedId} onOpen={onOpen} /></li>;
}

function MemoryItem({ memory, focused, onOpen }: { memory?: MemoryNode; focused: boolean; onOpen: (id: string) => void }) {
  if (!memory) return <div className="border border-[var(--munin-border)] p-3 font-mono text-[10px] text-[var(--munin-muted)]">MEMORY DETAIL UNAVAILABLE</div>;
  return <button id={`memory-${memory.id}`} type="button" onClick={() => onOpen(memory.id)} className={`block w-full border bg-black p-3 text-left focus-visible:outline focus-visible:outline-1 focus-visible:outline-[var(--munin-cyan)] ${focused ? "border-[var(--munin-cyan)]" : "border-[var(--munin-border)]"}`} aria-label={`Inspect memory ${memory.id}`}><div className="flex flex-wrap items-center gap-2"><TypeTag type={memory.memoryType} /><StatusTag status={memory.status} /><span className="font-mono text-[9px] text-[var(--munin-cyan)]">{shortId(memory.id)}</span>{memory.status === "active" && <span className="ml-auto font-mono text-[9px] text-[var(--munin-green)]">CURRENT TRUTH</span>}</div><p className={`mt-2 font-mono text-[11px] leading-5 ${memory.status === "active" ? "text-[var(--munin-text)]" : "text-[var(--munin-muted)]"}`}>{memory.content}</p><div className="mt-2 grid gap-1 font-mono text-[9px] text-[var(--munin-muted)] sm:grid-cols-2 lg:grid-cols-4"><span>CREATED {fmtDateTime(memory.createdAt)}</span><span>VALID FROM {fmtDateTime(memory.validFrom)}</span><span>VALID UNTIL {fmtDateTime(memory.validUntil)}</span><span>AGENT {memory.agentId ?? "unknown"}</span><span>CONF {fmtNum(memory.confidence)}</span><span>IMPORTANCE {fmtNum(memory.importance)}</span></div></button>;
}

function Select({ label, value, options, onChange }: { label: string; value: string; options: string[]; onChange: (value: string) => void }) { return <label className="font-mono text-[9px] uppercase text-[var(--munin-muted)]">{label}<select className="munin-input mt-1 block min-w-28" value={value} onChange={(event) => onChange(event.target.value)}>{options.map((option) => <option key={option} value={option}>{option.toUpperCase()}</option>)}</select></label>; }
