import { useMemo } from "react";
import { Gauge, TerminalDisplay } from "@mdrbx/nerv-ui";
import { useHealth } from "../../hooks/useHealth";
import { useScope } from "../../lib/scope";
import { Panel } from "../../components/ui/Panel";
import { StatBlock } from "../../components/ui/StatBlock";
import { EmptyState, ErrorState, LoadingState } from "../../components/ui/States";
import { StatusTag, TypeTag } from "../../components/ui/Tags";
import { fmtDateTime } from "../../lib/format";
import type { MemoryStatus } from "../../types/api";
import { useOverviewData, type ActivityKind } from "./useOverviewData";

const STATUSES: MemoryStatus[] = ["active", "superseded", "invalidated", "archived"];
const STATUS_COLOR: Record<MemoryStatus, string> = {
  active: "var(--munin-green)",
  superseded: "var(--munin-orange)",
  invalidated: "var(--munin-red)",
  archived: "var(--munin-muted)",
};
const ACTIVITY_COLOR: Record<ActivityKind, string> = {
  MEMORY: "var(--munin-cyan)",
  SUPERSEDES: "var(--munin-orange)",
  UPDATES: "var(--munin-amber)",
  CONTRADICTS: "var(--munin-red)",
};

function timeOnly(iso: string): string {
  const formatted = fmtDateTime(iso);
  return formatted === "—" ? formatted : formatted.slice(11, 19);
}

export function Overview() {
  const { namespace, setNamespace } = useScope();
  const overview = useOverviewData(namespace);
  const health = useHealth();

  const stats = useMemo(() => {
    const all = overview.data?.memories ?? [];
    const scoped = all.filter((memory) => memory.namespace === namespace);
    const byStatus = Object.fromEntries(
      STATUSES.map((status) => [status, scoped.filter((memory) => memory.status === status).length]),
    ) as Record<MemoryStatus, number>;
    const namespaces = Array.from(new Set(all.map((memory) => memory.namespace)))
      .map((name) => {
        const memories = all.filter((memory) => memory.namespace === name);
        return { name, total: memories.length, active: memories.filter((memory) => memory.status === "active").length };
      })
      .sort((a, b) => b.total - a.total || a.name.localeCompare(b.name));
    const agentCounts = new Map<string, number>();
    for (const memory of scoped) {
      const agent = memory.agentId?.trim() || "unknown";
      agentCounts.set(agent, (agentCounts.get(agent) ?? 0) + 1);
    }
    const agents = Array.from(agentCounts, ([id, count]) => ({ id, count }))
      .sort((a, b) => b.count - a.count || a.id.localeCompare(b.id));
    return { scoped, byStatus, namespaces, agents };
  }, [overview.data, namespace]);

  if (overview.loading && !overview.data) return <LoadingState label="MEMORY CORE SYNCHRONIZING" />;
  if (overview.error) return <ErrorState error={overview.error} onRetry={overview.reload} />;
  if (!overview.data) return null;

  const complete = overview.data.complete;
  const activeRatio = stats.scoped.length
    ? Math.round((stats.byStatus.active / stats.scoped.length) * 100)
    : 0;
  const apiOnline = health.data?.status === "ok" && !health.error;
  const activities = overview.data.activities.filter(
    ({ memory }) => memory.namespace === namespace,
  );

  return (
    <div className="h-full min-h-0 overflow-y-auto overflow-x-hidden p-2 sm:p-3">
      <div className="mx-auto grid w-full max-w-[1600px] grid-cols-1 gap-3 xl:grid-cols-12">
        <Panel
          title="Memory Core Status"
          subtitle={complete ? "Complete current-scope lifecycle inventory" : "Safety limit reached; showing loaded records"}
          right={
            <div className="text-right font-mono text-[9px] uppercase tracking-wider text-[var(--munin-muted)]">
              <div>Current scope</div>
              <div className="max-w-[180px] truncate text-[var(--munin-cyan)]" title={namespace}>{namespace}</div>
            </div>
          }
          className="xl:col-span-8"
        >
          <div className="grid grid-cols-2 gap-px bg-[var(--munin-border)] sm:grid-cols-3 lg:grid-cols-5">
            <StatBlock
              label={complete ? "Total Memories" : "Loaded Memories"}
              value={stats.scoped.length}
              color="var(--munin-cyan)"
              sub={complete ? "complete scope" : "partial scope"}
            />
            {STATUSES.map((status) => (
              <StatBlock key={status} label={status} value={stats.byStatus[status]} color={STATUS_COLOR[status]} />
            ))}
          </div>
          {stats.scoped.length === 0 && (
            <div className="border-t border-[var(--munin-border)]">
              <EmptyState title="NO DURABLE MEMORIES IN CURRENT SCOPE" detail="Select a discovered namespace below or enter another scope in the navigation." />
            </div>
          )}
        </Panel>

        <Panel title="Engine Status" subtitle="Live service telemetry" className="xl:col-span-4" scan>
          <div className="grid gap-3 p-3 sm:grid-cols-[1fr_auto] xl:grid-cols-1 2xl:grid-cols-[1fr_auto]">
            <TerminalDisplay
              lines={[
                `MEMORY ENGINE  ${apiOnline ? "ONLINE" : health.loading ? "CHECKING" : "OFFLINE"}`,
                `API            ${apiOnline ? "NOMINAL" : health.loading ? "CHECKING" : "DEGRADED"}`,
                "DATABASE       UNAVAILABLE",
                `${complete ? "MEMORIES" : "LOADED"}       ${stats.scoped.length}`,
                `SCOPE          ${namespace}`,
              ]}
              color={apiOnline ? "green" : health.loading ? "cyan" : "orange"}
              title="MUNIN // SERVICE CHANNEL"
              showCursor={health.loading}
              className="min-w-0"
            />
            <div className="flex items-center gap-3 sm:flex-col sm:justify-center xl:flex-row 2xl:flex-col">
              <Gauge value={activeRatio} label="ACTIVE MEMORY RATIO" unit="%" color="cyan" size={92} showTicks />
              <div className="font-mono text-[10px] text-[var(--munin-muted)]">
                <div>ACTIVE / {complete ? "TOTAL" : "LOADED"}</div>
                <div className="text-[var(--munin-green)]">{stats.byStatus.active} / {stats.scoped.length}</div>
              </div>
            </div>
          </div>
        </Panel>

        <Panel
          title="Recent Memory Activity"
          subtitle="Newest current-scope memories by creation time"
          right={<span className="font-mono text-[9px] text-[var(--munin-muted)]">LATEST 10</span>}
          className="min-h-[310px] xl:col-span-7"
          bodyClassName="overflow-hidden"
        >
          {activities.length === 0 ? (
            <EmptyState title="NO RECENT MEMORY ACTIVITY" detail={`No durable memories in ${namespace}.`} />
          ) : (
            <ol className="divide-y divide-[var(--munin-border)]">
              {activities.map(({ memory, kind, occurredAt }) => (
                <li key={memory.id} className="grid gap-2 px-3 py-2 sm:grid-cols-[64px_94px_1fr] sm:items-start">
                  <time dateTime={occurredAt} className="font-mono text-[10px] text-[var(--munin-muted)]">{timeOnly(occurredAt)}</time>
                  <span className="font-mono text-[10px] tracking-wider" style={{ color: ACTIVITY_COLOR[kind] }}>{kind}</span>
                  <div className="min-w-0">
                    <div className="mb-1 flex flex-wrap gap-1.5"><TypeTag type={memory.memoryType} /><StatusTag status={memory.status} /></div>
                    <p className="break-words font-mono text-[11px] leading-4 text-[var(--munin-text)] sm:line-clamp-2">{memory.content}</p>
                    <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 font-mono text-[9px] uppercase text-[var(--munin-muted)]">
                      <span>Agent: <span className="text-[var(--munin-cyan)]">{memory.agentId ?? "unknown"}</span></span>
                      <span>Namespace: <span className="text-[var(--munin-cyan)]">{memory.namespace}</span></span>
                    </div>
                  </div>
                </li>
              ))}
            </ol>
          )}
        </Panel>

        <div className="grid min-w-0 gap-3 md:grid-cols-2 xl:col-span-5 xl:grid-cols-1 2xl:grid-cols-2">
          <Panel title="Project / Namespace Scopes" subtitle={complete ? "Complete memory inventory" : "Loaded memory inventory"}>
            {stats.namespaces.length === 0 ? <EmptyState title="NO NAMESPACES DISCOVERED" /> : (
              <ul className="divide-y divide-[var(--munin-border)]">
                {stats.namespaces.map((scope) => {
                  const selected = scope.name === namespace;
                  return (
                    <li key={scope.name}>
                      <button
                        type="button"
                        onClick={() => setNamespace(scope.name)}
                        aria-pressed={selected}
                        className={`grid w-full grid-cols-[1fr_auto] gap-3 border-l-2 px-3 py-2 text-left font-mono transition-colors ${selected ? "border-[var(--munin-green)] bg-[rgba(39,227,107,0.07)]" : "border-transparent hover:border-[var(--munin-cyan)] hover:bg-[rgba(34,211,238,0.04)]"}`}
                      >
                        <span className="min-w-0 truncate text-[11px] text-[var(--munin-cyan)]" title={scope.name}>{scope.name}</span>
                        <span className="text-right text-[10px] text-[var(--munin-text)]">{scope.total}</span>
                        <span className="text-[9px] uppercase text-[var(--munin-muted)]">{selected ? "active scope" : "select scope"}</span>
                        <span className="text-right text-[9px] text-[var(--munin-muted)]">{scope.active} active</span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </Panel>

          <Panel title="Agent Provenance" subtitle="Memories written by agent in current scope">
            {stats.agents.length === 0 ? <EmptyState title="NO AGENT PROVENANCE" detail="No agent_id values are available in this scope." /> : (
              <ul className="divide-y divide-[var(--munin-border)]">
                {stats.agents.map((agent) => (
                  <li key={agent.id} className="flex items-center justify-between gap-3 px-3 py-2 font-mono">
                    <span className={agent.id === "unknown" ? "text-[11px] text-[var(--munin-muted)]" : "min-w-0 truncate text-[11px] text-[var(--munin-cyan)]"} title={agent.id}>{agent.id}</span>
                    <span className="whitespace-nowrap text-[10px] text-[var(--munin-text)]">{agent.count} {agent.count === 1 ? "memory" : "memories"}</span>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </div>
      </div>
    </div>
  );
}
