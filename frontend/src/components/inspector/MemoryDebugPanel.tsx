import { useState, type ReactNode } from "react";
import { api, ApiError } from "../../api/client";
import { useAsync } from "../../hooks/useAsync";
import { fmtDateTime, fmtNum, shortId } from "../../lib/format";
import type { DebugMemoryView, DebugTimelineEntry } from "../../types/api";

// -------------------------------------------------------------------
// Utility
// -------------------------------------------------------------------

function Field({
  label,
  children,
  color,
}: {
  label: string;
  children: ReactNode;
  color?: string;
}) {
  return (
    <div className="grid grid-cols-[120px_1fr] gap-3 border-b border-[var(--munin-border)] py-1.5">
      <dt className="font-mono text-[9px] uppercase tracking-wider text-[var(--munin-muted)]">
        {label}
      </dt>
      <dd
        className="min-w-0 break-all text-right font-mono text-[10px]"
        style={{ color: color ?? "var(--munin-text)" }}
      >
        {children}
      </dd>
    </div>
  );
}

function Section({
  title,
  color,
  children,
}: {
  title: string;
  color: string;
  children: ReactNode;
}) {
  return (
    <section className="mt-4">
      <h3
        className="mb-2 font-display text-[11px] tracking-wide-ext"
        style={{ color }}
      >
        {title}
      </h3>
      {children}
    </section>
  );
}

function LevelBadge({ level }: { level: string }) {
  const colors: Record<string, string> = {
    L0: "var(--munin-green)",
    L1: "var(--munin-cyan)",
    L2: "var(--munin-orange)",
  };
  const c = colors[level] ?? "var(--munin-muted)";
  return (
    <span
      className="rounded px-1.5 py-0.5 font-mono text-[9px]"
      style={{ backgroundColor: `${c}15`, color: c }}
    >
      {level}
    </span>
  );
}

// -------------------------------------------------------------------
// Main Panel
// -------------------------------------------------------------------

interface MemoryDebugPanelProps {
  memoryId: string;
  onClose: () => void;
}

export function MemoryDebugPanel({ memoryId, onClose }: MemoryDebugPanelProps) {
  const debug = useAsync(
    () => api.getMemoryDebug(memoryId),
    [memoryId],
    true,
  );

  const timeline = useAsync(
    () => api.getDebugTimeline({ limit: 20 }),
    [],
    true,
  );

  if (debug.loading) {
    return (
      <div className="p-4 font-mono text-[11px] text-[var(--munin-cyan)]">
        LOADING DEBUG VIEW...
      </div>
    );
  }

  if (debug.error) {
    return (
      <div className="p-4">
        <div className="mb-2 font-mono text-[11px] text-[var(--munin-orange)]">
          {debug.error instanceof ApiError
            ? `ERROR ${debug.error.status}`
            : "LOAD FAILED"}
        </div>
        <div className="font-mono text-[10px] text-[var(--munin-muted)]">
          {debug.error instanceof Error
            ? debug.error.message
            : String(debug.error)}
        </div>
        <button
          type="button"
          className="munin-btn mt-2"
          onClick={onClose}
        >
          CLOSE
        </button>
      </div>
    );
  }

  const data = debug.data;
  if (!data) return null;

  return (
    <div className="debug-panel flex h-full flex-col overflow-hidden">
      {/* Header */}
      <header className="flex items-center justify-between gap-2 border-b border-[var(--munin-border)] px-3 py-2">
        <div className="flex min-w-0 items-center gap-2">
          <div className="truncate font-mono text-[11px] text-[var(--munin-orange)]">
            DEBUGGER // {shortId(memoryId)}
          </div>
        </div>
        <button
          type="button"
          className="munin-btn"
          onClick={onClose}
          aria-label="Close debugger"
        >
          CLOSE
        </button>
      </header>

      {/* Content */}
      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {/* Identity */}
        <Section title="IDENTITY" color="var(--munin-green)">
          <div className="munin-panel-2 p-2">
            <dl>
              <Field label="Memory ID">{data.identity.memory_id}</Field>
              <Field label="Namespace" color="var(--munin-cyan)">
                {data.identity.namespace}
              </Field>
              <Field label="Type">{data.identity.memory_type}</Field>
              <Field label="Status">{data.identity.status}</Field>
              <Field label="Importance">
                {fmtNum(data.identity.importance)}
              </Field>
              <Field label="Confidence" color="var(--munin-cyan)">
                {fmtNum(data.identity.confidence)}
              </Field>
              <Field label="Created">{fmtDateTime(data.identity.created_at)}</Field>
              <Field label="Updated">{fmtDateTime(data.identity.updated_at)}</Field>
              {data.identity.valid_from && (
                <Field label="Valid From">
                  {fmtDateTime(data.identity.valid_from)}
                </Field>
              )}
              {data.identity.valid_until && (
                <Field label="Valid Until">
                  {fmtDateTime(data.identity.valid_until)}
                </Field>
              )}
            </dl>
          </div>
        </Section>

        {/* Representations */}
        <Section title="REPRESENTATIONS" color="var(--munin-cyan)">
          <div className="munin-panel-2 p-2">
            <div className="mb-2 flex gap-2">
              {data.representations.available_levels.map((l) => (
                <LevelBadge key={l} level={l} />
              ))}
            </div>
            {data.representations.l0_gist && (
              <div className="mb-2">
                <div className="font-mono text-[9px] uppercase tracking-wider text-[var(--munin-green)]">
                  L0 GIST ({data.representations.l0_token_cost} tokens)
                </div>
                <div className="mt-1 whitespace-pre-wrap break-words font-mono text-[10px] text-[var(--munin-green)]">
                  {data.representations.l0_gist}
                </div>
              </div>
            )}
            {data.representations.l1_summary && (
              <div className="mb-2">
                <div className="font-mono text-[9px] uppercase tracking-wider text-[var(--munin-cyan)]">
                  L1 SUMMARY ({data.representations.l1_token_cost} tokens)
                </div>
                <div className="mt-1 whitespace-pre-wrap break-words font-mono text-[10px] text-[var(--munin-cyan)]">
                  {data.representations.l1_summary}
                </div>
              </div>
            )}
            <div>
              <div className="font-mono text-[9px] uppercase tracking-wider text-[var(--munin-orange)]">
                L2 FULL ({data.representations.l2_token_cost} tokens)
              </div>
              <div className="mt-1 max-h-32 whitespace-pre-wrap break-words overflow-y-auto font-mono text-[10px] text-[var(--munin-text)]">
                {data.representations.l2_content}
              </div>
            </div>
          </div>
        </Section>

        {/* Provenance */}
        <Section title="SOURCE / PROVENANCE" color="var(--munin-purple)">
          <div className="munin-panel-2 p-2">
            <dl>
              <Field label="Agent">
                {data.provenance.agent_host ?? "Not recorded"}
              </Field>
              <Field label="Model">
                {data.provenance.model ?? "Not recorded"}
              </Field>
              <Field label="Session">
                {data.provenance.session_id
                  ? shortId(data.provenance.session_id)
                  : "Not recorded"}
              </Field>
              <Field label="Observation">
                {data.provenance.observation_type ?? "Not recorded"}
              </Field>
              <Field label="Source">
                {data.provenance.source ?? "Not recorded"}
              </Field>
              <Field label="Source Event">
                {data.provenance.source_event_id
                  ? shortId(data.provenance.source_event_id)
                  : "Not recorded"}
              </Field>
            </dl>
          </div>
        </Section>

        {/* Why Stored */}
        {data.admission && (
          <Section title="WHY STORED" color="var(--munin-green)">
            <div className="munin-panel-2 p-2">
              <div className="mb-2 flex items-center gap-2">
                <span
                  className="rounded px-1.5 py-0.5 font-mono text-[9px]"
                  style={{
                    backgroundColor:
                      data.admission.decision === "STORE"
                        ? "var(--munin-green)"
                        : "var(--munin-orange)",
                    color:
                      data.admission.decision === "STORE"
                        ? "var(--munin-bg)"
                        : "var(--munin-bg)",
                  }}
                >
                  {data.admission.decision}
                </span>
                <span className="font-mono text-[10px] text-[var(--munin-muted)]">
                  Score: {fmtNum(data.admission.admission_score)}
                </span>
              </div>
              <dl>
                {data.admission.importance != null && (
                  <Field label="Importance">
                    {fmtNum(data.admission.importance)}
                  </Field>
                )}
                {data.admission.future_utility != null && (
                  <Field label="Future Utility">
                    {fmtNum(data.admission.future_utility)}
                  </Field>
                )}
                {data.admission.provider && (
                  <Field label="Provider">
                    {data.admission.provider}
                  </Field>
                )}
              </dl>
              {data.admission.reason_codes.length > 0 && (
                <div className="mt-1 break-words font-mono text-[10px] text-[var(--munin-cyan)]">
                  REASON: {data.admission.reason_codes.join(" // ")}
                </div>
              )}
            </div>
          </Section>
        )}

        {/* Dedup / Reinforcement */}
        {(data.dedup || data.reinforcement_count > 0) && (
          <Section title="DEDUP / REINFORCEMENT" color="var(--munin-orange)">
            <div className="munin-panel-2 p-2">
              {data.dedup && (
                <div className="mb-2">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-[10px] text-[var(--munin-orange)]">
                      {data.dedup.relationship}
                    </span>
                    {data.dedup.matched_memory_id && (
                      <span className="font-mono text-[10px] text-[var(--munin-muted)]">
                        MATCHED: {shortId(data.dedup.matched_memory_id)}
                      </span>
                    )}
                  </div>
                  {data.dedup.similarity_score != null && (
                    <div className="font-mono text-[10px] text-[var(--munin-muted)]">
                      SIMILARITY: {fmtNum(data.dedup.similarity_score)}
                    </div>
                  )}
                </div>
              )}
              {data.reinforcement_count > 0 && (
                <div className="font-mono text-[10px] text-[var(--munin-green)]">
                  REINFORCED {data.reinforcement_count} TIME(S)
                </div>
              )}
            </div>
          </Section>
        )}

        {/* Temporal */}
        {data.temporal.length > 0 && (
          <Section title="TEMPORAL RELATIONSHIPS" color="var(--munin-orange)">
            <ol className="space-y-2">
              {data.temporal.map((t, i) => (
                <li key={i} className="munin-panel-2 p-2 font-mono text-[10px]">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[var(--munin-orange)]">
                      {t.relationship}
                    </span>
                    {t.relationship_confidence != null && (
                      <span className="text-[var(--munin-muted)]">
                        CONF: {fmtNum(t.relationship_confidence)}
                      </span>
                    )}
                  </div>
                  {t.matched_memory_id && (
                    <div className="mt-1 text-[var(--munin-muted)]">
                      MATCHED: {shortId(t.matched_memory_id)}
                    </div>
                  )}
                  {t.old_status && (
                    <div className="text-[var(--munin-muted)]">
                      STATUS: {t.old_status} → {t.new_old_status ?? "?"}
                    </div>
                  )}
                </li>
              ))}
            </ol>
          </Section>
        )}

        {/* Source Events */}
        {data.source_events.length > 0 && (
          <Section title="SOURCE EVENTS" color="var(--munin-cyan)">
            <ol className="space-y-2">
              {data.source_events.map((e) => (
                <li
                  key={e.capture_event_id}
                  className="munin-panel-2 p-2 font-mono text-[10px]"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[var(--munin-cyan)]">
                      {e.event_type}
                    </span>
                    <span className="text-[var(--munin-muted)]">
                      {e.source}
                    </span>
                  </div>
                  {e.observation_type && (
                    <div className="mt-1 text-[var(--munin-green)]">
                      OBS: {e.observation_type}
                    </div>
                  )}
                  {e.admission_decision && (
                    <div
                      className="mt-0.5"
                      style={{
                        color:
                          e.admission_decision === "STORE"
                            ? "var(--munin-green)"
                            : "var(--munin-orange)",
                      }}
                    >
                      ADMISSION: {e.admission_decision}
                    </div>
                  )}
                  <div className="mt-1 max-h-16 overflow-y-auto whitespace-pre-wrap break-words text-[var(--munin-muted)]">
                    {e.content_preview}
                  </div>
                </li>
              ))}
            </ol>
          </Section>
        )}

        {/* Recent Timeline */}
        <Section title="RECENT TIMELINE" color="var(--munin-muted)">
          {timeline.loading && (
            <div className="font-mono text-[10px] text-[var(--munin-cyan)]">
              LOADING...
            </div>
          )}
          {timeline.data && timeline.data.length === 0 && (
            <div className="font-mono text-[10px] text-[var(--munin-muted)]">
              NO TIMELINE ENTRIES
            </div>
          )}
          {timeline.data && timeline.data.length > 0 && (
            <ol className="space-y-1">
              {timeline.data.map((entry, i) => (
                <li
                  key={i}
                  className="flex items-center gap-2 font-mono text-[9px]"
                >
                  <span
                    className="shrink-0 rounded px-1 py-0.5"
                    style={{
                      backgroundColor:
                        entry.event_type === "STORED"
                          ? "var(--munin-green)"
                          : entry.event_type === "IGNORED"
                            ? "var(--munin-orange)"
                            : "var(--munin-muted)",
                      color: "var(--munin-bg)",
                    }}
                  >
                    {entry.event_type}
                  </span>
                  <span className="truncate text-[var(--munin-muted)]">
                    {entry.content_preview}
                  </span>
                  <span className="ml-auto shrink-0 text-[var(--munin-muted)]">
                    {fmtDateTime(entry.timestamp)}
                  </span>
                </li>
              ))}
            </ol>
          )}
        </Section>
      </div>
    </div>
  );
}
