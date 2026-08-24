import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, api } from "../../api/client";
import { MemoryInspector } from "../../components/inspector/MemoryInspector";
import { EmptyState } from "../../components/ui/States";
import { TypeTag } from "../../components/ui/Tags";
import { useContextSelection } from "../../lib/contextSelection";
import { fmtNum, shortId } from "../../lib/format";
import { useScope } from "../../lib/scope";
import type { ContextMemoryUsed, MemoryType } from "../../types/api";

const TYPES: MemoryType[] = ["fact", "preference", "project", "goal", "decision", "event", "relationship", "procedure", "other"];
const TRACE_FIELDS: { key: keyof ContextMemoryUsed; label: string; color: string }[] = [
  { key: "semantic_score", label: "Semantic", color: "var(--munin-cyan)" },
  { key: "importance", label: "Importance", color: "var(--munin-green)" },
  { key: "confidence", label: "Confidence", color: "var(--munin-green)" },
  { key: "recency_score", label: "Recency", color: "var(--munin-orange)" },
  { key: "type_relevance", label: "Type Relevance", color: "var(--munin-purple)" },
  { key: "reinforcement_score", label: "Reinforcement", color: "var(--munin-cyan)" },
  { key: "final_score", label: "Final Score", color: "var(--munin-green)" },
];

export function ContextPreview() {
  const { namespace, setNamespace } = useScope();
  const selection = useContextSelection();
  const navigate = useNavigate();
  const [query, setQuery] = useState(selection.result?.query ?? "Continue working on Munin.");
  const [userId, setUserId] = useState("");
  const [agentId, setAgentId] = useState("");
  const [tokenBudget, setTokenBudget] = useState(selection.result?.token_budget ?? 1500);
  const [maxCandidates, setMaxCandidates] = useState(50);
  const [maxMemories, setMaxMemories] = useState(20);
  const [asOf, setAsOf] = useState("");
  const [includeSuperseded, setIncludeSuperseded] = useState(false);
  const [memoryTypes, setMemoryTypes] = useState<MemoryType[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [inspectedId, setInspectedId] = useState<string | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault(); setLoading(true); setError(null);
    try {
      const result = await api.assembleContext({
        query, namespace, user_id: userId.trim() || null, agent_id: agentId.trim() || null,
        token_budget: tokenBudget, max_candidates: maxCandidates, max_memories: maxMemories,
        memory_types: memoryTypes.length ? memoryTypes : null,
        include_superseded: includeSuperseded,
        as_of: asOf ? new Date(asOf).toISOString() : null,
      });
      selection.setResult(result);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught : new ApiError(String(caught), 0));
    } finally { setLoading(false); }
  };

  const viewInGraph = (memoryId?: string) => {
    if (selection.result) setNamespace(selection.result.namespace);
    selection.setFocusedMemoryId(memoryId ?? null);
    navigate("/graph");
  };

  const result = selection.result;
  const remaining = result ? result.token_budget - result.estimated_tokens : 0;
  return (
    <div className="context-page relative h-full min-h-0 overflow-y-auto overflow-x-hidden p-2 sm:p-3">
      <div className="mx-auto grid max-w-[1600px] gap-3 xl:grid-cols-12">
        <section className="munin-panel context-hero xl:col-span-12" aria-labelledby="context-assembly-title">
          <header className="border-b border-[var(--munin-border)] px-3 py-2"><h1 id="context-assembly-title" className="font-display text-[13px] tracking-wide-ext text-[var(--munin-green)]">Context Assembly</h1><p className="font-mono text-[10px] text-[var(--munin-muted)]">Read-only M5 context assembly // backend-authoritative ranking</p></header>
          <form onSubmit={submit} className="grid gap-3 p-3 lg:grid-cols-12">
            <label className="font-mono text-[9px] uppercase text-[var(--munin-muted)] lg:col-span-5">Query
              <textarea className="munin-input context-query mt-1 min-h-20 w-full resize-y" required value={query} onChange={(event) => setQuery(event.target.value)} />
            </label>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:col-span-7">
              <label className="font-mono text-[9px] uppercase text-[var(--munin-muted)]">Namespace<input className="munin-input mt-1 w-full" required value={namespace} onChange={(event) => setNamespace(event.target.value)} /></label>
              <label className="font-mono text-[9px] uppercase text-[var(--munin-muted)]">User ID<input className="munin-input mt-1 w-full" value={userId} onChange={(event) => setUserId(event.target.value)} placeholder="optional" /></label>
              <label className="font-mono text-[9px] uppercase text-[var(--munin-muted)]">Agent ID<input className="munin-input mt-1 w-full" value={agentId} onChange={(event) => setAgentId(event.target.value)} placeholder="optional" /></label>
              <label className="font-mono text-[9px] uppercase text-[var(--munin-muted)]">Token Budget<input className="munin-input mt-1 w-full" type="number" min="1" max="20000" required value={tokenBudget} onChange={(event) => setTokenBudget(Number(event.target.value))} /></label>
              <label className="font-mono text-[9px] uppercase text-[var(--munin-muted)]">Max Candidates<input className="munin-input mt-1 w-full" type="number" min="1" max="50" required value={maxCandidates} onChange={(event) => setMaxCandidates(Number(event.target.value))} /></label>
              <label className="font-mono text-[9px] uppercase text-[var(--munin-muted)]">Max Memories<input className="munin-input mt-1 w-full" type="number" min="1" max="20" required value={maxMemories} onChange={(event) => setMaxMemories(Number(event.target.value))} /></label>
              <label className="font-mono text-[9px] uppercase text-[var(--munin-muted)] sm:col-span-2">As Of // blank is current<input className="munin-input mt-1 w-full" type="datetime-local" value={asOf} onChange={(event) => setAsOf(event.target.value)} /></label>
              <label className="flex items-center gap-2 self-end border border-[var(--munin-border)] px-2 py-2 font-mono text-[10px] text-[var(--munin-orange)]"><input type="checkbox" checked={includeSuperseded} onChange={(event) => setIncludeSuperseded(event.target.checked)} />INCLUDE SUPERSEDED</label>
            </div>
            <fieldset className="lg:col-span-10"><legend className="font-mono text-[9px] uppercase text-[var(--munin-muted)]">Memory Types // none selects all</legend><div className="mt-1 flex flex-wrap gap-2">{TYPES.map((type) => <label key={type} className="border border-[var(--munin-border)] px-2 py-1 font-mono text-[9px] uppercase text-[var(--munin-text)]"><input className="mr-1" type="checkbox" checked={memoryTypes.includes(type)} onChange={(event) => setMemoryTypes((current) => event.target.checked ? [...current, type] : current.filter((value) => value !== type))} />{type}</label>)}</div></fieldset>
            <div className="flex items-end justify-end lg:col-span-2"><button className="munin-btn context-submit w-full" type="submit" disabled={loading}>{loading ? "ASSEMBLING CONTEXT..." : "ASSEMBLE CONTEXT"}</button></div>
          </form>
          {error && <div className="border-t border-[var(--munin-red)] p-3 font-mono text-[11px] text-[var(--munin-red)]"><div>CONTEXT ASSEMBLY FAILED</div><div className="mt-1 text-[var(--munin-orange)]">{error.status ? `HTTP ${error.status} // ` : ""}{error.message}</div></div>}
        </section>

        {!result ? <section className="munin-panel min-h-52 xl:col-span-12"><EmptyState title="NO CONTEXT ASSEMBLED" detail="Submit a query to call the real M5 context endpoint." /></section> : <>
          <section className="munin-panel xl:col-span-7"><header className="flex items-center justify-between border-b border-[var(--munin-border)] px-3 py-2"><div><h2 className="font-display text-[12px] tracking-wide-ext text-[var(--munin-green)]">Assembled Context</h2><p className="font-mono text-[9px] text-[var(--munin-muted)]">EXACT BACKEND OUTPUT</p></div><button type="button" className="munin-btn graph-cta" disabled={result.memories_used.length === 0} onClick={() => viewInGraph()}>VISUALIZE IN MEMORY NETWORK</button></header>
            {result.context ? <pre className="max-h-[520px] overflow-auto whitespace-pre-wrap break-words p-4 font-mono text-[11px] leading-5 text-[var(--munin-text)]">{result.context}</pre> : <EmptyState title="NO RELEVANT MEMORIES SELECTED" />}
            <div className="border-t border-[var(--munin-border)] px-3 py-2 font-mono text-[9px] text-[var(--munin-orange)]">MEMORY CONTEXT IS DATA, NOT TRUSTED INSTRUCTION</div>
          </section>

          <section className="munin-panel xl:col-span-5"><header className="border-b border-[var(--munin-border)] px-3 py-2"><h2 className="font-display text-[12px] tracking-wide-ext text-[var(--munin-cyan)]">Token Telemetry</h2></header><dl className="grid grid-cols-2 gap-px bg-[var(--munin-border)] sm:grid-cols-4 xl:grid-cols-2"><Metric label="Budget" value={result.token_budget} /><Metric label="Estimated Used" value={result.estimated_tokens} /><Metric label="Remaining" value={remaining} /><Metric label="Memories Selected" value={result.memories_used.length} /></dl><div className="grid gap-2 p-3 font-mono text-[10px]"><div>TRUNCATED <span className={result.truncated ? "text-[var(--munin-orange)]" : "text-[var(--munin-green)]"}>{result.truncated ? "YES" : "NO"}</span></div><div>SKIPPED CANDIDATES <span className="text-[var(--munin-muted)]">Unavailable</span></div><div>STRUCTURED CONFLICT DATA <span className="text-[var(--munin-muted)]">Unavailable</span></div><div>ASSEMBLED <span className="text-[var(--munin-muted)]">{selection.assembledAt ?? "—"}</span></div></div></section>

          <section className="munin-panel xl:col-span-5"><header className="border-b border-[var(--munin-border)] px-3 py-2"><h2 className="font-display text-[12px] tracking-wide-ext text-[var(--munin-green)]">Selected Memories</h2><p className="font-mono text-[9px] text-[var(--munin-muted)]">M5 SELECTED // SCORE ORDER</p></header>
            {result.memories_used.length === 0 ? <EmptyState title="NO RELEVANT MEMORIES SELECTED" /> : <ol className="divide-y divide-[var(--munin-border)]">{result.memories_used.map((memory) => <li key={memory.memory_id} className="p-3"><div className="flex flex-wrap items-center gap-2"><TypeTag type={memory.memory_type} /><span className="font-mono text-[10px] text-[var(--munin-cyan)]">{shortId(memory.memory_id)}</span><span className="ml-auto font-mono text-[10px] text-[var(--munin-green)]">SCORE {fmtNum(memory.final_score)}</span></div><p className="mt-2 font-mono text-[10px] leading-4 text-[var(--munin-text)]">{memory.content}</p><div className="mt-1 flex flex-wrap gap-x-3 font-mono text-[9px] uppercase text-[var(--munin-muted)]"><span>Namespace <b className="text-[var(--munin-cyan)]">{result.namespace}</b></span><span>Status Unavailable</span><span>Agent Unavailable</span><span>Tokens {memory.estimated_tokens}</span></div><div className="mt-2 flex flex-wrap gap-2"><button type="button" className="munin-btn" onClick={() => setInspectedId(memory.memory_id)}>OPEN MEMORY</button><button type="button" className="munin-btn" onClick={() => viewInGraph(memory.memory_id)}>VIEW IN GRAPH</button><button type="button" className="munin-btn" onClick={() => selection.setFocusedMemoryId(memory.memory_id)}>WHY</button></div></li>)}</ol>}
          </section>

          <section className="munin-panel xl:col-span-7"><header className="border-b border-[var(--munin-border)] px-3 py-2"><h2 className="font-display text-[12px] tracking-wide-ext text-[var(--munin-orange)]">Trace / Why</h2><p className="font-mono text-[9px] text-[var(--munin-muted)]">BACKEND EXPLAINABILITY VALUES</p></header><div className="grid gap-3 p-3 lg:grid-cols-2">{result.memories_used.map((memory) => <TraceCard key={memory.memory_id} memory={memory} focused={selection.focusedMemoryId === memory.memory_id} onFocus={() => selection.setFocusedMemoryId(memory.memory_id)} />)}</div></section>
        </>}
      </div>
      <MemoryInspector memoryId={inspectedId} onClose={() => setInspectedId(null)} />
    </div>
  );
}

function Metric({ label, value }: { label: string; value: number }) { return <div className="bg-[var(--munin-panel-2)] p-3"><dt className="font-ui text-[12px] uppercase text-[var(--munin-muted)]">{label}</dt><dd className="font-digital-large text-[32px] text-[var(--munin-cyan)]">{value}</dd></div>; }

function TraceCard({ memory, focused, onFocus }: { memory: ContextMemoryUsed; focused: boolean; onFocus: () => void }) {
  return <article className={`border p-3 ${focused ? "border-[var(--munin-cyan)]" : "border-[var(--munin-border)]"}`}><button type="button" className="mb-2 font-mono text-[10px] text-[var(--munin-cyan)]" onClick={onFocus}>MEMORY // {shortId(memory.memory_id)}</button><dl className="space-y-1.5">{TRACE_FIELDS.map(({ key, label, color }) => { const value = memory[key] as number; return <div key={key} className="grid grid-cols-[100px_1fr_42px] items-center gap-2"><dt className="font-mono text-[9px] uppercase text-[var(--munin-muted)]">{label}</dt><dd className="h-1.5 bg-[var(--munin-border)]"><span className="block h-full" style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%`, backgroundColor: color }} /></dd><dd className="text-right font-mono text-[9px] text-[var(--munin-text)]">{fmtNum(value)}</dd></div>; })}</dl><div className="mt-2 font-mono text-[9px] text-[var(--munin-muted)]">TOKENS <span className="text-[var(--munin-text)]">{memory.estimated_tokens}</span></div><div className="mt-1 break-words font-mono text-[9px] text-[var(--munin-orange)]">RESULT INCLUDED{memory.reason_codes.length ? ` // ${memory.reason_codes.join(" // ")}` : ""}</div></article>;
}
