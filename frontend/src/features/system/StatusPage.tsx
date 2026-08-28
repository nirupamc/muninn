import { useEffect, useState } from "react";
import { api, ApiError } from "../../api/client";
import { useHealth } from "../../hooks/useHealth";
import { Panel } from "../../components/ui/Panel";
import { LoadingState, ErrorState } from "../../components/ui/States";
import type { CaptureStatusResponse, ProjectListResponse } from "../../types/api";

export function StatusPage() {
  const health = useHealth();
  const [capture, setCapture] = useState<CaptureStatusResponse | null>(null);
  const [projects, setProjects] = useState<ProjectListResponse | null>(null);
  const [loadError, setLoadError] = useState<ApiError | null>(null);

  useEffect(() => {
    Promise.all([
      api.getCaptureStatus().catch(() => null),
      api.listProjects({ limit: 500 }).catch(() => null),
    ]).then(([cap, proj]) => {
      setCapture(cap);
      setProjects(proj);
    }).catch((e) => setLoadError(e instanceof ApiError ? e : new ApiError(String(e), 0)));
  }, []);

  if (health.loading) return <LoadingState label="QUERYING ENGINE" />;
  if (health.error) return <ErrorState error={health.error} onRetry={health.reload} />;

  const online = health.data?.status === "ok";
  const adapterNames = capture?.adapter_health ? Object.keys(capture.adapter_health) : [];
  const activeAdapters = adapterNames.filter((name) =>
    capture?.adapter_health[name]?.some((a) => a.available),
  );

  return (
    <div className="h-full overflow-auto p-3">
      <div className="mx-auto max-w-[1200px] space-y-3">
        <Panel title="System Status" subtitle="Munin memory engine health" scan>
          <div className="grid grid-cols-2 gap-px bg-[var(--munin-border)] sm:grid-cols-4">
            <Row label="Backend" value={online ? "ONLINE" : "OFFLINE"} color={online ? "var(--munin-green)" : "var(--munin-red)"} />
            <Row label="Service" value={health.data?.service ?? "—"} color="var(--munin-cyan)" />
            <Row label="API" value={online ? "NOMINAL" : "DEGRADED"} color={online ? "var(--munin-green)" : "var(--munin-red)"} />
            <Row label="Milestones" value="M10-M14" color="var(--munin-green)" />
          </div>
        </Panel>

        <Panel title="Memory Engine" subtitle="Core subsystem status">
          <div className="grid grid-cols-2 gap-px bg-[var(--munin-border)] sm:grid-cols-4">
            <Row label="Projects" value={String(projects?.total ?? "—")} color="var(--munin-cyan)" />
            <Row label="Capture Events" value={String(capture?.total_capture_events ?? "—")} color="var(--munin-cyan)" />
            <Row label="Pending Events" value={String(capture?.pending_events ?? "—")} color={capture?.pending_events ? "var(--munin-orange)" : "var(--munin-green)"} />
            <Row label="Capture Projects" value={String(capture?.projects_with_capture ?? "—")} color="var(--munin-cyan)" />
          </div>
        </Panel>

        <Panel title="Agent Adapters" subtitle="M8 agent session capture integrations">
          {adapterNames.length === 0 ? (
            <div className="p-3 font-mono text-[11px] text-[var(--munin-muted)]">NO ADAPTER DATA AVAILABLE</div>
          ) : (
            <div className="divide-y divide-[var(--munin-border)]">
              {adapterNames.map((name) => {
                const adapters = capture?.adapter_health[name] ?? [];
                const available = adapters.some((a) => a.available);
                return (
                  <div key={name} className="flex items-center justify-between px-3 py-2 font-mono text-[11px]">
                    <span className="text-[var(--munin-cyan)]">{name.toUpperCase()}</span>
                    <span style={{ color: available ? "var(--munin-green)" : "var(--munin-orange)" }}>
                      {available ? "AVAILABLE" : "UNAVAILABLE"}
                    </span>
                  </div>
                );
              })}
            </div>
          )}
        </Panel>

        <Panel title="Capabilities" subtitle="Active memory system capabilities">
          <div className="grid grid-cols-2 gap-2 p-3 sm:grid-cols-3 lg:grid-cols-4">
            {[
              { label: "Hierarchical Memory", tag: "M10", active: true },
              { label: "L0/L1/L2", tag: "M10", active: true },
              { label: "Hybrid Retrieval", tag: "M11", active: true },
              { label: "BM25 Lexical", tag: "M11", active: true },
              { label: "RRF Fusion", tag: "M11", active: true },
              { label: "Observations", tag: "M12", active: true },
              { label: "Memory Debugger", tag: "M13", active: true },
              { label: "Dense Retrieval", tag: "M11", active: true },
            ].map(({ label, tag, active }) => (
              <div key={label} className="flex items-center justify-between border border-[var(--munin-border)] px-2 py-1.5">
                <span className="font-mono text-[10px] text-[var(--munin-text)]">{label}</span>
                <span className="rounded bg-[rgba(39,227,107,0.1)] px-1 py-0.5 font-mono text-[8px] text-[var(--munin-green)]">{tag}</span>
              </div>
            ))}
          </div>
        </Panel>

        {loadError && (
          <div className="border border-[var(--munin-orange)] p-2 font-mono text-[10px] text-[var(--munin-orange)]">
            PARTIAL DATA — SOME SUBSYSTEMS UNREACHABLE: {loadError.message}
          </div>
        )}
      </div>
    </div>
  );
}

function Row({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div className="bg-[var(--munin-panel-2)] p-3">
      <div className="font-mono text-[10px] uppercase tracking-wider text-[var(--munin-muted)]">{label}</div>
      <div className="mt-1 font-mono text-[14px]" style={{ color }}>{value}</div>
    </div>
  );
}
