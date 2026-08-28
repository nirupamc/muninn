import { useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../../api/client";
import { useAsync } from "../../hooks/useAsync";
import { useScope } from "../../lib/scope";
import { Panel } from "../../components/ui/Panel";
import { EmptyState, ErrorState, LoadingState } from "../../components/ui/States";
import { fmtDateTime, shortId } from "../../lib/format";
import type { CaptureEventRead, DebugTimelineEntry } from "../../types/api";

type OutcomeFilter = "all" | "STORED" | "IGNORED" | "TRIVIAL" | "SECRET_REJECTED" | "OTHER";

const EVENT_COLORS: Record<string, string> = {
  DECISION: "var(--munin-orange)",
  TEST_RESULT: "var(--munin-green)",
  ERROR: "var(--munin-red)",
  BLOCKER: "var(--munin-red)",
  VERIFICATION: "var(--munin-green)",
  COMMAND_RUN: "var(--munin-cyan)",
  COMMAND_RESULT: "var(--munin-cyan)",
  FILE_EDIT: "var(--munin-amber)",
  FILE_CREATE: "var(--munin-amber)",
  FILE_DELETE: "var(--munin-red)",
  GIT_COMMIT: "var(--munin-purple)",
  BUILD_RESULT: "var(--munin-purple)",
  USER_MESSAGE: "var(--munin-muted)",
  AGENT_MESSAGE: "var(--munin-muted)",
  TOOL_CALL: "var(--munin-muted)",
  TOOL_RESULT: "var(--munin-muted)",
  SESSION_START: "var(--munin-muted)",
  SESSION_END: "var(--munin-muted)",
  OTHER: "var(--munin-muted)",
};

const OUTCOME_COLORS: Record<string, string> = {
  STORED: "var(--munin-green)",
  IGNORED: "var(--munin-orange)",
  TRIVIAL: "var(--munin-muted)",
  SECRET_REJECTED: "var(--munin-red)",
  REINFORCED: "var(--munin-cyan)",
  DUPLICATE: "var(--munin-cyan)",
};

function OutcomeBadge({ label }: { label: string }) {
  const color = OUTCOME_COLORS[label] ?? "var(--munin-muted)";
  return (
    <span
      className="rounded px-1.5 py-0.5 font-mono text-[9px]"
      style={{ backgroundColor: `${color}18`, color }}
    >
      {label}
    </span>
  );
}

function EventTypeBadge({ type }: { type: string }) {
  const color = EVENT_COLORS[type] ?? "var(--munin-muted)";
  return (
    <span
      className="rounded px-1.5 py-0.5 font-mono text-[9px]"
      style={{ backgroundColor: `${color}18`, color }}
    >
      {type}
    </span>
  );
}

export function Observations() {
  const { namespace } = useScope();
  const [outcomeFilter, setOutcomeFilter] = useState<OutcomeFilter>("all");
  const [timelineEntries, setTimelineEntries] = useState<DebugTimelineEntry[]>([]);
  const [captureEvents, setCaptureEvents] = useState<CaptureEventRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [tl, ce] = await Promise.all([
          api.getDebugTimeline({ namespace, limit: 100 }).catch(() => []),
          api.listCaptureEvents({ limit: 100, project_id: undefined }).catch(() => []),
        ]);
        if (!cancelled) {
          setTimelineEntries(tl);
          setCaptureEvents(ce);
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof ApiError ? e : new ApiError(String(e), 0));
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => { cancelled = true; };
  }, [namespace]);

  const filtered = useMemo(() => {
    if (outcomeFilter === "all") return timelineEntries;
    return timelineEntries.filter((e) => {
      const detail = e.details as Record<string, unknown>;
      const admission = String(detail?.admission_decision ?? "").toUpperCase();
      if (outcomeFilter === "STORED") return admission === "STORE";
      if (outcomeFilter === "IGNORED") return admission === "IGNORE";
      if (outcomeFilter === "TRIVIAL") return e.event_type === "TRIVIAL";
      if (outcomeFilter === "SECRET_REJECTED") return e.event_type === "SECRET_REJECTED";
      return admission !== "STORE" && admission !== "IGNORE";
    });
  }, [timelineEntries, outcomeFilter]);

  const stats = useMemo(() => {
    let stored = 0, ignored = 0, total = 0;
    for (const e of timelineEntries) {
      total++;
      const detail = e.details as Record<string, unknown>;
      const admission = String(detail?.admission_decision ?? "").toUpperCase();
      if (admission === "STORE") stored++;
      else if (admission === "IGNORE") ignored++;
    }
    return { total, stored, ignored };
  }, [timelineEntries]);

  if (loading) return <LoadingState label="LOADING OBSERVATIONS" />;
  if (error) return <ErrorState error={error} />;

  return (
    <div className="h-full overflow-y-auto overflow-x-hidden p-2 sm:p-3">
      <div className="mx-auto grid w-full max-w-[1600px] gap-3 xl:grid-cols-12">
        {/* Summary Stats */}
        <Panel title="Observation Summary" subtitle="M12 structured observation pipeline" className="xl:col-span-12">
          <div className="grid grid-cols-2 gap-px bg-[var(--munin-border)] sm:grid-cols-4">
            <div className="bg-[var(--munin-panel-2)] p-3">
              <div className="font-mono text-[10px] uppercase tracking-wider text-[var(--munin-muted)]">Timeline Entries</div>
              <div className="font-digital-large text-[28px] text-[var(--munin-cyan)]">{stats.total}</div>
            </div>
            <div className="bg-[var(--munin-panel-2)] p-3">
              <div className="font-mono text-[10px] uppercase tracking-wider text-[var(--munin-muted)]">Stored as Memory</div>
              <div className="font-digital-large text-[28px] text-[var(--munin-green)]">{stats.stored}</div>
            </div>
            <div className="bg-[var(--munin-panel-2)] p-3">
              <div className="font-mono text-[10px] uppercase tracking-wider text-[var(--munin-muted)]">Ignored</div>
              <div className="font-digital-large text-[28px] text-[var(--munin-orange)]">{stats.ignored}</div>
            </div>
            <div className="bg-[var(--munin-panel-2)] p-3">
              <div className="font-mono text-[10px] uppercase tracking-wider text-[var(--munin-muted)]">Capture Events</div>
              <div className="font-digital-large text-[28px] text-[var(--munin-text)]">{captureEvents.length}</div>
            </div>
          </div>
        </Panel>

        {/* Filter Bar */}
        <section className="xl:col-span-12">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-[9px] uppercase tracking-wider text-[var(--munin-muted)]">Outcome:</span>
            {(["all", "STORED", "IGNORED", "TRIVIAL", "SECRET_REJECTED", "OTHER"] as OutcomeFilter[]).map((f) => (
              <button
                key={f}
                type="button"
                className={`rounded border px-2 py-1 font-mono text-[10px] ${
                  outcomeFilter === f
                    ? "border-[var(--munin-green)] bg-[rgba(39,227,107,0.08)] text-[var(--munin-green)]"
                    : "border-[var(--munin-border)] text-[var(--munin-muted)] hover:text-[var(--munin-cyan)]"
                }`}
                onClick={() => setOutcomeFilter(f)}
              >
                {f.toUpperCase()}
              </button>
            ))}
          </div>
        </section>

        {/* Timeline */}
        <Panel
          title="Observation Timeline"
          subtitle="Recent structured observations from the M12 pipeline"
          right={<span className="font-mono text-[9px] text-[var(--munin-muted)]">{filtered.length} ENTRIES</span>}
          className="xl:col-span-7 min-h-[400px]"
        >
          {filtered.length === 0 ? (
            <EmptyState
              title="NO OBSERVATIONS FOUND"
              detail="Observations are created when agent sessions, tool calls, and commands are captured."
            />
          ) : (
            <ol className="divide-y divide-[var(--munin-border)]">
              {filtered.map((entry, i) => {
                const detail = entry.details as Record<string, unknown>;
                const admission = String(detail?.admission_decision ?? "").toUpperCase();
                const obsType = String(detail?.observation_type ?? entry.event_type);
                const agent = String(detail?.agent_host ?? detail?.agent_id ?? "unknown");
                const model = String(detail?.model ?? "");
                return (
                  <li key={i} className="grid gap-1 px-3 py-2 sm:grid-cols-[90px_100px_1fr_100px] sm:items-start">
                    <time className="font-mono text-[10px] text-[var(--munin-muted)]">
                      {fmtDateTime(entry.timestamp)}
                    </time>
                    <div className="flex flex-wrap items-center gap-1">
                      <EventTypeBadge type={obsType} />
                    </div>
                    <div className="min-w-0">
                      <div className="truncate font-mono text-[10px] text-[var(--munin-text)]">
                        {entry.content_preview || "—"}
                      </div>
                      <div className="mt-0.5 flex gap-3 font-mono text-[8px] text-[var(--munin-muted)]">
                        {agent !== "unknown" && <span>AGENT: <span className="text-[var(--munin-cyan)]">{agent}</span></span>}
                        {model && <span>MODEL: <span className="text-[var(--munin-cyan)]">{model}</span></span>}
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      {admission && <OutcomeBadge label={admission} />}
                      {entry.memory_id && (
                        <span className="font-mono text-[9px] text-[var(--munin-green)]">
                          MEM: {shortId(entry.memory_id)}
                        </span>
                      )}
                    </div>
                  </li>
                );
              })}
            </ol>
          )}
        </Panel>

        {/* Capture Events */}
        <Panel
          title="Capture Events"
          subtitle="Raw capture events from agent adapters"
          right={<span className="font-mono text-[9px] text-[var(--munin-muted)]">LATEST {captureEvents.length}</span>}
          className="xl:col-span-5 min-h-[400px]"
        >
          {captureEvents.length === 0 ? (
            <EmptyState
              title="NO CAPTURE EVENTS"
              detail="Events are created by agent session adapters (Codex, Cline, Aider, etc.)."
            />
          ) : (
            <ol className="max-h-[500px] divide-y divide-[var(--munin-border)] overflow-y-auto">
              {captureEvents.map((event) => (
                <li key={event.id} className="px-3 py-2">
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <EventTypeBadge type={event.event_type} />
                      <span className="font-mono text-[9px] text-[var(--munin-cyan)]">{event.source}</span>
                    </div>
                    <span className="font-mono text-[9px] text-[var(--munin-muted)]">
                      {fmtDateTime(event.occurred_at)}
                    </span>
                  </div>
                  <div className="mt-1 truncate font-mono text-[10px] text-[var(--munin-text)]">
                    {event.content}
                  </div>
                  <div className="mt-1 flex items-center gap-2 font-mono text-[8px]">
                    <span className="text-[var(--munin-muted)]">STATUS: {event.processing_status}</span>
                    {event.admission_decision && (
                      <OutcomeBadge label={event.admission_decision} />
                    )}
                    {event.memory_id && (
                      <span className="text-[var(--munin-green)]">STORED: {shortId(event.memory_id)}</span>
                    )}
                    {event.error && (
                      <span className="text-[var(--munin-red)]">ERROR: {event.error}</span>
                    )}
                  </div>
                </li>
              ))}
            </ol>
          )}
        </Panel>
      </div>
    </div>
  );
}
