import { useEffect, useMemo, useState, type ReactNode } from "react";
import { ApiError, api } from "../../api/client";
import { useAsync } from "../../hooks/useAsync";
import { toMemoryNode } from "../../lib/mappers";
import { fmtDateTime, fmtNum, shortId } from "../../lib/format";
import type { ConsolidationRead } from "../../types/api";
import type { MemoryNode } from "../../types/domain";
import { StatusTag, TypeTag } from "../ui/Tags";
import { MemoryDebugPanel } from "./MemoryDebugPanel";

interface MemoryInspectorProps {
  memoryId?: string | null;
  node?: MemoryNode | null;
  onClose: () => void;
}

function Field({ label, children, color }: { label: string; children: ReactNode; color?: string }) {
  return (
    <div className="grid grid-cols-[120px_1fr] gap-3 border-b border-[var(--munin-border)] py-1.5">
      <dt className="font-mono text-[9px] uppercase tracking-wider text-[var(--munin-muted)]">{label}</dt>
      <dd className="min-w-0 break-all text-right font-mono text-[10px]" style={{ color: color ?? "var(--munin-text)" }}>{children}</dd>
    </div>
  );
}

function SectionError({ label }: { label: string }) {
  return <div className="border border-[var(--munin-orange)] p-2 font-mono text-[10px] text-[var(--munin-orange)]">{label} UNAVAILABLE</div>;
}

export function MemoryInspector({ memoryId, node, onClose }: MemoryInspectorProps) {
  const requestedId = memoryId ?? node?.id ?? null;
  const [activeId, setActiveId] = useState<string | null>(requestedId);
  const [backStack, setBackStack] = useState<string[]>([]);
  const [showDebug, setShowDebug] = useState(false);

  useEffect(() => { setActiveId(requestedId); setBackStack([]); }, [requestedId]);

  const detail = useAsync(() => api.getMemory(activeId!), [activeId], !!activeId);
  const history = useAsync(() => api.getMemoryHistory(activeId!), [activeId], !!activeId);
  const derived = useAsync<ConsolidationRead | null>(async () => {
    try { return await api.getMemoryConsolidation(activeId!); }
    catch (error) { if (error instanceof ApiError && error.status === 404) return null; throw error; }
  }, [activeId], !!activeId);
  const usedIn = useAsync(() => api.getConsolidationsFromSource(activeId!), [activeId], !!activeId);
  const sourceEventId = detail.data?.source_event_id ?? (node?.id === activeId ? node.sourceEventId : null);
  const event = useAsync(() => api.getEvent(sourceEventId!), [sourceEventId], !!sourceEventId);

  const memory = useMemo(() => {
    if (detail.data?.id === activeId) return toMemoryNode(detail.data);
    return node?.id === activeId ? node : null;
  }, [detail.data, node, activeId]);

  if (!activeId) return null;

  const navigate = (id: string) => {
    if (id === activeId) return;
    setBackStack((stack) => activeId ? [...stack, activeId] : stack);
    setActiveId(id);
  };
  const goBack = () => setBackStack((stack) => {
    const previous = stack[stack.length - 1];
    if (previous) setActiveId(previous);
    return stack.slice(0, -1);
  });
  const linkId = (id: string | null) => id ? (
    <button type="button" className="text-[var(--munin-cyan)] underline decoration-dotted underline-offset-2 hover:text-[var(--munin-green)]" onClick={() => navigate(id)} title={id}>{shortId(id)}</button>
  ) : "—";

  return (
    <aside className="memory-inspector fixed inset-0 z-40 flex flex-col overflow-hidden border-l border-[var(--munin-border-bright)] bg-[var(--munin-panel)] shadow-[var(--munin-glow)] sm:absolute sm:left-auto sm:w-[440px]" aria-label="Memory Inspector" aria-live="polite">
      <header className="flex items-center justify-between gap-2 border-b border-[var(--munin-border)] px-3 py-2">
        <div className="flex min-w-0 items-center gap-2">
          {backStack.length > 0 && <button type="button" className="munin-btn" onClick={goBack} aria-label="Back to previous memory">← BACK</button>}
          <div className="truncate font-mono text-[11px] text-[var(--munin-green)]" title={activeId}>MEMORY // {shortId(activeId)}</div>
        </div>
        <div className="flex gap-1">
          <button type="button" className="munin-btn" onClick={() => setShowDebug(!showDebug)} title="Open memory debugger">
            {showDebug ? "INSPECT" : "DEBUG"}
          </button>
          <button type="button" className="munin-btn" onClick={onClose} aria-label="Close memory inspector">CLOSE</button>
        </div>
      </header>

      {showDebug && activeId ? (
        <MemoryDebugPanel memoryId={activeId} onClose={() => setShowDebug(false)} />
      ) : (
      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {detail.loading && !memory && <div className="py-8 text-center font-mono text-[11px] text-[var(--munin-cyan)]">LOADING MEMORY...</div>}
        {detail.error && !memory && <SectionError label="MEMORY DETAIL" />}
        {memory && (
          <>
            <section aria-labelledby="inspector-core">
              <h2 id="inspector-core" className="mb-2 font-display text-[12px] tracking-wide-ext text-[var(--munin-green)]">Core Memory</h2>
              <div className="mb-2 flex flex-wrap gap-2"><TypeTag type={memory.memoryType} /><StatusTag status={memory.status} />{memory.isConsolidated && <span className="status-tag text-[var(--munin-purple)]">CONSOLIDATED</span>}</div>
              <div className="munin-panel-2 mb-3 whitespace-pre-wrap break-words p-3 font-mono text-[11px] leading-5 text-[var(--munin-text)]">{memory.content}</div>
              {/* M10 — Hierarchical Representations */}
              <div className="mb-3 border border-[var(--munin-border)] p-2">
                <div className="mb-1 font-mono text-[9px] uppercase tracking-wider text-[var(--munin-muted)]">Representations</div>
                <div className="flex gap-2 mb-1">
                  <span className={`rounded px-1.5 py-0.5 font-mono text-[9px] ${memory.gist ? "bg-[rgba(39,227,107,0.1)] text-[var(--munin-green)]" : "text-[var(--munin-muted)]"}`}>L0 GIST</span>
                  <span className={`rounded px-1.5 py-0.5 font-mono text-[9px] ${memory.summary ? "bg-[rgba(34,211,238,0.1)] text-[var(--munin-cyan)]" : "text-[var(--munin-muted)]"}`}>L1 SUMMARY</span>
                  <span className="rounded bg-[rgba(255,152,48,0.1)] px-1.5 py-0.5 font-mono text-[9px] text-[var(--munin-orange)]">L2 FULL</span>
                </div>
                {memory.gist && <div className="mb-1 font-mono text-[10px] text-[var(--munin-green)]">L0: {memory.gist}</div>}
                {!memory.gist && <div className="mb-1 font-mono text-[10px] text-[var(--munin-muted)]">L0: NOT RECORDED</div>}
                {memory.summary && <div className="font-mono text-[10px] text-[var(--munin-cyan)]">L1: {memory.summary}</div>}
                {!memory.summary && <div className="font-mono text-[10px] text-[var(--munin-muted)]">L1: NOT RECORDED</div>}
              </div>
              <dl>
                <Field label="Memory ID">{memory.id}</Field><Field label="Namespace" color="var(--munin-cyan)">{memory.namespace}</Field>
                <Field label="User ID">{memory.userId ?? "Unavailable"}</Field><Field label="Agent ID">{memory.agentId ?? "Unavailable"}</Field>
                <Field label="Source Event">{memory.sourceEventId ? shortId(memory.sourceEventId) : "Unavailable"}</Field>
                <Field label="Stored Importance">{fmtNum(memory.importance)}</Field><Field label="Effective Importance">Unavailable</Field>
                <Field label="Confidence" color="var(--munin-cyan)">{fmtNum(memory.confidence)}</Field>
                <Field label="Created At">{fmtDateTime(memory.createdAt)}</Field><Field label="Updated At">{fmtDateTime(memory.updatedAt)}</Field>
                <Field label="Last Accessed">{fmtDateTime(memory.lastAccessedAt)}</Field><Field label="Valid From">{fmtDateTime(memory.validFrom)}</Field><Field label="Valid Until">{fmtDateTime(memory.validUntil)}</Field>
              </dl>
            </section>

            <section className="mt-5" aria-labelledby="inspector-temporal">
              <h2 id="inspector-temporal" className="mb-2 font-display text-[12px] tracking-wide-ext text-[var(--munin-orange)]">Temporal History</h2>
              {history.loading && <div className="font-mono text-[10px] text-[var(--munin-cyan)]">LOADING TEMPORAL HISTORY...</div>}
              {history.error && <SectionError label="TEMPORAL HISTORY" />}
              {history.data && history.data.temporal_decisions.length === 0 && <div className="font-mono text-[10px] text-[var(--munin-muted)]">NO TEMPORAL RELATIONSHIPS</div>}
              <ol className="space-y-2">{history.data?.temporal_decisions.map((record) => (
                <li key={record.id} className="munin-panel-2 p-2 font-mono text-[10px]">
                  <div className="flex items-center justify-between gap-2"><span className="text-[var(--munin-orange)]">{record.relationship}</span><time className="text-[var(--munin-muted)]">{fmtDateTime(record.created_at)}</time></div>
                  <div className="mt-1 text-[var(--munin-muted)]">MATCHED MEMORY: {linkId(record.matched_memory_id)}</div>
                  <div className="text-[var(--munin-muted)]">CREATED MEMORY: {linkId(record.created_memory_id)}</div>
                  <div className="text-[var(--munin-muted)]">RELATIONSHIP CONFIDENCE: <span className="text-[var(--munin-text)]">{fmtNum(record.relationship_confidence)}</span></div>
                  {record.reason_codes.length > 0 && <div className="mt-1 break-words text-[var(--munin-cyan)]">REASON: {record.reason_codes.join(" // ")}</div>}
                </li>
              ))}</ol>
            </section>

            <section className="mt-5" aria-labelledby="inspector-source">
              <h2 id="inspector-source" className="mb-2 font-display text-[12px] tracking-wide-ext text-[var(--munin-cyan)]">Source Provenance</h2>
              {!memory.sourceEventId && <div className="font-mono text-[10px] text-[var(--munin-muted)]">SOURCE EVENT UNAVAILABLE</div>}
              {memory.sourceEventId && event.loading && <div className="font-mono text-[10px] text-[var(--munin-cyan)]">LOADING SOURCE EVENT...</div>}
              {event.error && <SectionError label="SOURCE EVENT DETAIL" />}
              {event.data && event.data.id === memory.sourceEventId && <div className="munin-panel-2 p-2"><dl>
                <Field label="Event ID">{event.data.id}</Field><Field label="Role">{event.data.role}</Field><Field label="Agent">{event.data.agent_id ?? "Unavailable"}</Field><Field label="Session">{event.data.session_id ?? "Unavailable"}</Field><Field label="Timestamp">{fmtDateTime(event.data.created_at)}</Field>
              </dl><div className="mt-2 whitespace-pre-wrap break-words font-mono text-[10px] text-[var(--munin-text)]">{event.data.content}</div></div>}
            </section>

            <section className="mt-5" aria-labelledby="inspector-consolidation">
              <h2 id="inspector-consolidation" className="mb-2 font-display text-[12px] tracking-wide-ext text-[var(--munin-purple)]">Consolidation Provenance</h2>
              {(derived.loading || usedIn.loading) && <div className="font-mono text-[10px] text-[var(--munin-cyan)]">LOADING CONSOLIDATION PROVENANCE...</div>}
              {(derived.error || usedIn.error) && <SectionError label="CONSOLIDATION PROVENANCE" />}
              {derived.data && <div className="munin-panel-2 mb-2 p-2 font-mono text-[10px]"><div className="text-[var(--munin-purple)]">CONSOLIDATED MEMORY // DERIVED FROM</div><div className="mt-1 text-[var(--munin-muted)]">{derived.data.reason}</div><ul className="mt-2 space-y-1">{derived.data.sources.map((source) => <li key={source.memory_id}>{linkId(source.memory_id)} <span className="text-[var(--munin-muted)]">[{source.memory_type}] {source.content}</span></li>)}</ul></div>}
              {usedIn.data?.map((record) => <div key={record.consolidation_id} className="munin-panel-2 mb-2 p-2 font-mono text-[10px]"><div className="text-[var(--munin-purple)]">USED IN CONSOLIDATION</div><div className="mt-1">DERIVED MEMORY: {linkId(record.created_memory_id)}</div><div className="text-[var(--munin-muted)]">{fmtDateTime(record.created_at)} // CONF {fmtNum(record.confidence)}</div></div>)}
              {!derived.loading && !usedIn.loading && !derived.error && !usedIn.error && !derived.data && usedIn.data?.length === 0 && <div className="font-mono text-[10px] text-[var(--munin-muted)]">NO CONSOLIDATION PROVENANCE</div>}
            </section>

            <details className="mt-5 border border-[var(--munin-border)] p-2">
              <summary className="cursor-pointer font-display text-[11px] tracking-wide-ext text-[var(--munin-muted)]">Raw Metadata</summary>
              <pre className="mt-2 max-h-56 overflow-auto whitespace-pre-wrap break-all font-mono text-[9px] text-[var(--munin-text)]">{JSON.stringify(memory.metadata, null, 2)}</pre>
            </details>
          </>
        )}
      </div>
      )}
    </aside>
  );
}
