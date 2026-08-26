import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { api, ApiError } from "../../api/client";
import type { DriveReportRead, ProjectRead, ProjectScanResponse } from "../../types/api";
import { Panel } from "../../components/ui/Panel";
import { LoadingState, ErrorState, EmptyState } from "../../components/ui/States";
import { useScope } from "../../lib/scope";
import { formatDistanceToNow } from "../../lib/format";

type ProjectStatus = "DISCOVERED" | "CONNECTED" | "MEMORIZED" | "ACTIVE" | "DISABLED";

type FilterKey = "all" | "active" | "memorized" | "no_memories" | "capture" | "ignored";

const FILTERS: ReadonlyArray<readonly [FilterKey, string]> = [
  ["all", "All"],
  ["active", "Active"],
  ["memorized", "Memorized"],
  ["no_memories", "No memories"],
  ["capture", "Capture enabled"],
  ["ignored", "Ignored"],
];

const SKIPPED_CANDIDATES_LIMIT = 25;

function statusColor(status: ProjectStatus): string {
  switch (status) {
    case "ACTIVE": return "var(--munin-green)";
    case "CONNECTED": return "var(--munin-cyan)";
    case "MEMORIZED": return "var(--munin-amber)";
    case "DISCOVERED": return "var(--munin-muted)";
    case "DISABLED": return "var(--munin-red)";
  }
}

function driveStatusColor(status: DriveReportRead["status"]): string {
  switch (status) {
    case "scanned": return "var(--munin-green)";
    case "skipped": return "var(--munin-amber)";
    default: return "var(--munin-red)";
  }
}

export function Projects() {
  const { namespace, setNamespace } = useScope();
  const [projects, setProjects] = useState<ProjectRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
    const [error, setError] = useState<ApiError | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showDetail, setShowDetail] = useState<string | null>(null);
  const [filter, setFilter] = useState<FilterKey>("all");
  const [scanResult, setScanResult] = useState<ProjectScanResponse | null>(null);
  const [lastScanAt, setLastScanAt] = useState<string | null>(null);

  async function loadProjects() {
    try {
      setLoading(true);
      // include_ignored keeps ignored projects auditable/recoverable.
      const res = await api.listProjects({ limit: 1000, include_ignored: true });
      setProjects(res.projects);
      setError(null);
    } catch (e) {
            setError(e instanceof ApiError ? e : new ApiError(e instanceof Error ? e.message : String(e), 0));
    } finally {
      setLoading(false);
    }
  }

  async function loadLastScan() {
    try {
      const status = await api.getDiscoveryStatus();
      if (status.last_scan) {
        setLastScanAt(status.last_scan.finished_at ?? status.last_scan.started_at ?? null);
        setScanResult(status.last_scan as ProjectScanResponse);
      }
    } catch {
      // Diagnostics are best-effort; never block the registry view.
    }
  }

  async function scanWorkstation() {
    try {
      setScanning(true);
      setError(null);
      const res = await api.scanProjects({ include_auto_drives: true });
      setScanResult(res);
      await loadProjects();
    } catch (e) {
            setError(e instanceof ApiError ? e : new ApiError(e instanceof Error ? e.message : "Failed to scan workstation", 0));
    } finally {
      setScanning(false);
    }
  }

  async function toggleCapture(project: ProjectRead) {
    try {
      if (project.capture_enabled) {
        await api.disableProjectCapture(project.id);
      } else {
        await api.enableProjectCapture(project.id);
      }
      await loadProjects();
    } catch (e) {
            setError(e instanceof ApiError ? e : new ApiError(e instanceof Error ? e.message : "Failed to toggle capture", 0));
    }
  }

  async function setIgnored(project: ProjectRead, ignored: boolean) {
    try {
      await api[ignored ? "ignoreProject" : "unignoreProject"](project.id);
      await loadProjects();
    } catch (e) {
            setError(e instanceof ApiError ? e : new ApiError(e instanceof Error ? e.message : "Failed to update ignore state", 0));
    }
  }

  function selectProject(project: ProjectRead) {
    if (project.ignored) return;
    setNamespace(project.namespace);
    setSelectedId(project.id);
  }

  useEffect(() => {
    loadProjects();
    loadLastScan();
  }, []);

  const visible = useMemo(() => {
    switch (filter) {
      case "active":
        return projects.filter((p) => !p.ignored && p.status === "ACTIVE");
      case "memorized":
        return projects.filter((p) => !p.ignored && p.memory_count > 0);
      case "no_memories":
        return projects.filter((p) => !p.ignored && p.memory_count === 0);
      case "capture":
        return projects.filter((p) => !p.ignored && p.capture_enabled);
      case "ignored":
        return projects.filter((p) => p.ignored);
      default:
        return projects.filter((p) => !p.ignored);
    }
  }, [projects, filter]);

  if (loading && projects.length === 0) return <LoadingState label="LOADING PROJECT REGISTRY" />;
  if (error && projects.length === 0) return <ErrorState error={error} onRetry={loadProjects} />;

  return (
    <div className="h-full overflow-auto p-3">
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <span className="font-mono text-[10px] uppercase tracking-wider text-[var(--munin-muted)]">Filter</span>
        {FILTERS.map(([key, label]) => (
          <button
            key={key}
            type="button"
            onClick={() => setFilter(key)}
            aria-pressed={filter === key}
            className={`rounded border px-2 py-1 font-mono text-xs ${filter === key
              ? "border-[var(--munin-green)] bg-[rgba(39,227,107,0.08)] text-[var(--munin-green)]"
              : "border-[var(--munin-border)] text-[var(--munin-muted)] hover:text-[var(--munin-cyan)]"}`}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="flex items-start gap-3">
        <Panel title="Workstation Projects" subtitle={`${visible.length} of ${projects.length} registered projects`} className="min-w-0 flex-1">
          <div className="overflow-auto">
            <table className="munin-table w-full">
              <thead>
                <tr>
                  <th className="w-8"></th>
                  <th>Project</th>
                  <th className="w-32">Status</th>
                  <th className="w-16">Git</th>
                  <th className="w-28">Capture</th>
                  <th className="w-24">Memories</th>
                  <th className="w-40">Last Activity</th>
                  <th className="w-56">Path</th>
                  <th className="w-44">Namespace</th>
                  <th className="w-40"></th>
                </tr>
              </thead>
              <tbody>
                {visible.length === 0 && (
                  <tr>
                    <td colSpan={10} className="py-8 text-center text-[var(--munin-muted)]">
                      No projects match this filter. Click "Scan Workstation" to discover filesystem projects.
                    </td>
                  </tr>
                )}
                {visible.map((p) => (
                  <tr
                    key={p.id}
                    className={`munin-row ${selectedId === p.id ? "selected" : ""} ${p.ignored ? "opacity-50" : ""}`}
                    onClick={() => selectProject(p)}
                  >
                    <td>
                      <div className="mt-2 h-2 w-2 rounded-full" style={{ backgroundColor: statusColor(p.status) }} />
                    </td>
                    <td className="font-mono text-[var(--munin-cyan)]">
                      {p.name}
                      {p.ignored && (
                        <span className="ml-2 rounded px-1.5 py-0.5 text-[10px]" style={{ backgroundColor: "rgba(255,80,80,0.15)", color: "var(--munin-red)" }}>
                          IGNORED
                        </span>
                      )}
                    </td>
                    <td>
                      <span
                        className="inline-block rounded px-2 py-0.5 text-xs font-medium"
                        style={{ backgroundColor: `${statusColor(p.status)}22`, color: statusColor(p.status) }}
                        title={`discovery_source: ${p.discovery_source ?? "manual"}`}
                      >
                        {p.status}
                      </span>
                    </td>
                    <td className="text-sm">
                      {p.git_root ? <span style={{ color: "var(--munin-green)" }}>Yes</span> : <span className="text-[var(--munin-muted)]">No</span>}
                    </td>
                    <td>
                      <label className="inline-flex cursor-pointer items-center gap-2" onClick={(e) => e.stopPropagation()}>
                        <input type="checkbox" checked={p.capture_enabled} onChange={() => toggleCapture(p)} className="munin-checkbox" />
                        <span className="text-sm">{p.capture_enabled ? "ON" : "OFF"}</span>
                      </label>
                    </td>
                    <td className="font-mono text-sm">{p.memory_count}</td>
                    <td className="font-mono text-sm text-[var(--munin-muted)]">
                      {p.last_activity_at ? `${formatDistanceToNow(new Date(p.last_activity_at))} ago` : "Never"}
                    </td>
                    <td className="max-w-[220px] truncate font-mono text-sm text-[var(--munin-muted)]" title={p.canonical_path}>
                      {p.canonical_path}
                    </td>
                    <td className="font-mono text-sm text-[var(--munin-dim)]">{p.namespace}</td>

                    <td className="text-right">
                      <div className="flex justify-end gap-1" onClick={(e) => e.stopPropagation()}>
                        <button className="munin-btn ghost text-xs" onClick={() => setShowDetail(p.id)}>Details</button>
                        {p.ignored ? (
                          <button className="munin-btn ghost text-xs" onClick={() => setIgnored(p, false)}>Unignore</button>
                        ) : (
                          <button className="munin-btn ghost text-xs" onClick={() => setIgnored(p, true)}>Ignore</button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
        <div className="flex w-48 flex-shrink-0 flex-col gap-2">
          <button className="munin-btn primary" onClick={scanWorkstation} disabled={scanning}>
            {scanning ? "Scanningâ€¦" : "Scan Workstation"}
          </button>
          <button className="munin-btn secondary" onClick={loadProjects} disabled={loading || scanning}>
            Refresh
          </button>
          {lastScanAt && (
            <div className="font-mono text-[10px] text-[var(--munin-muted)]">
              Last scan: {formatDistanceToNow(new Date(lastScanAt))} ago
            </div>
          )}
        </div>
      </div>

      {scanResult && (
        <ScanDiagnostics result={scanResult} />
      )}

      {error && projects.length > 0 && (
              <div className="mt-3 rounded border border-[var(--munin-red)] px-3 py-2 text-sm" style={{ color: "var(--munin-red)" }}>
          {error?.message || "An error occurred"}
        </div>
      )}

      {/* Project Detail Modal */}
      {showDetail && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={() => setShowDetail(null)}>
          <div className="max-h-[80vh] w-full max-w-3xl overflow-auto rounded-lg border border-[var(--munin-border)] bg-[var(--munin-bg-elevated)]" onClick={(e) => e.stopPropagation()}>
            <ProjectDetail project={projects.find((p) => p.id === showDetail)!} onClose={() => setShowDetail(null)} onChanged={loadProjects} />
          </div>
        </div>
      )}
    </div>
  );
}

function ScanDiagnostics({ result }: { result: ProjectScanResponse }) {
  const [showSkipped, setShowSkipped] = useState(false);
  // The persisted last-scan summary omits discovered/existing arrays and uses
  // slightly different count keys than the live /scan response â€” read defensively.
  const summary = result as unknown as Record<string, unknown>;
  const newCount = Number(summary.projects_new_count ?? summary.projects_new ?? result.discovered?.length ?? 0);
  const existingCount = Number(summary.projects_existing_count ?? summary.projects_existing ?? result.existing?.length ?? 0);
  const scannedDrives = result.drives.filter((d) => d.status === "scanned");
  const boundedSkipped = (result.skipped_candidates ?? []).slice(0, SKIPPED_CANDIDATES_LIMIT);
  const totalSkipped = (result.skipped_candidates ?? []).length;
  const hiddenSkipped = totalSkipped - boundedSkipped.length;
  const reasonEntries = Object.entries(result.skipped_by_reason ?? {}).sort((a, b) => b[1] - a[1]);

  return (
    <Panel
      title="Scan Diagnostics"
      subtitle={`${result.drives.length} drives Â· ${scannedDrives.length} scanned Â· ${result.projects_found} projects found (${newCount} new)`}
      className="mt-4"
    >
      <div className="grid grid-cols-2 gap-px bg-[var(--munin-border)] sm:grid-cols-4 lg:grid-cols-7">
        <Stat label="Duration" value={`${(result.duration_ms / 1000).toFixed(1)}s`} />
        <Stat label="Dirs considered" value={String(result.directories_considered)} />
        <Stat label="Dirs skipped" value={String(result.directories_skipped)} />
        <Stat label="Permission errors" value={String(result.permission_errors)} />
        <Stat label="Max depth" value={String(result.max_depth_reached)} />
        <Stat label="New projects" value={String(newCount)} />
        <Stat label="Existing projects" value={String(existingCount)} />
      </div>

      <div className="mt-3">
        <h4 className="mb-2 font-mono text-xs uppercase tracking-wider text-[var(--munin-muted)]">Drives</h4>
        <ul className="divide-y divide-[var(--munin-border)]">
          {(result.drives ?? []).map((d) => (
            <li key={d.root_path} className="grid grid-cols-[auto_1fr_auto] items-center gap-3 px-1 py-1.5 font-mono text-xs">
              <span className="whitespace-nowrap text-[var(--munin-cyan)]">{d.root_path}</span>
              <span className="truncate text-[var(--munin-muted)]">{d.drive_type}{d.reason ? ` â€” ${d.reason}` : ""}</span>
              <span style={{ color: driveStatusColor(d.status) }}>{d.status.toUpperCase()}</span>
            </li>
          ))}
        </ul>
      </div>

      {reasonEntries.length > 0 && (
        <div className="mt-3">
          <h4 className="mb-2 font-mono text-xs uppercase tracking-wider text-[var(--munin-muted)]">Skipped by reason</h4>
          <div className="flex flex-wrap gap-2">
            {reasonEntries.map(([reason, count]) => (
              <span key={reason} className="rounded border border-[var(--munin-border)] px-2 py-0.5 font-mono text-xs text-[var(--munin-muted)]">
                {reason}: {count}
              </span>
            ))}
          </div>
        </div>
      )}

      {totalSkipped > 0 && (
        <div className="mt-3">
          <button
            type="button"
            className="font-mono text-xs uppercase tracking-wider text-[var(--munin-muted)] hover:text-[var(--munin-cyan)]"
            onClick={() => setShowSkipped((v) => !v)}
          >
            {showSkipped ? "â–¾" : "â–¸"} Skipped candidates ({totalSkipped})
          </button>
          {showSkipped && (
            <ul className="mt-2 max-h-48 divide-y divide-[var(--munin-border)] overflow-y-auto">
              {boundedSkipped.map((s) => (
                <li key={s.path} className="grid grid-cols-[1fr_auto] gap-3 px-1 py-1 font-mono text-[11px]">
                  <span className="truncate text-[var(--munin-dim)]" title={s.path}>{s.path}</span>
                  <span className="whitespace-nowrap text-[var(--munin-muted)]">{s.reason}</span>
                </li>
              ))}
              {hiddenSkipped > 0 && (
                <li className="px-1 py-1 font-mono text-[11px] text-[var(--munin-muted)]">
                  â€¦and {hiddenSkipped} more (bounded view)
                </li>
              )}
            </ul>
          )}
        </div>
      )}
    </Panel>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-[var(--munin-bg)] p-2">
      <div className="font-mono text-[9px] uppercase tracking-wider text-[var(--munin-muted)]">{label}</div>
      <div className="font-mono text-sm">{value}</div>
    </div>
  );
}

function ProjectDetail({ project, onClose, onChanged }: { project: ProjectRead; onClose: () => void; onChanged: () => void }) {
  const { setNamespace } = useScope();
  const [activity, setActivity] = useState<import("../../types/api").ProjectActivityResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const res = await api.getProjectActivity(project.id, 50);
        setActivity(res);
      } catch (e) {
        console.error(e);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [project.id]);

  async function toggleIgnored() {
    try {
      await api[project.ignored ? "unignoreProject" : "ignoreProject"](project.id);
      onChanged();
    } catch (e) {
      console.error(e);
    }
  }

  const sources = activity?.recent_captures.map((c) => c.source) ?? [];
  const uniqueSources = [...new Set(sources)];

  return (
    <div className="p-6">
      <div className="mb-6 flex items-start justify-between">
        <div>
          <h2 className="font-mono text-xl text-[var(--munin-cyan)]">{project.name}</h2>
          <p className="font-mono text-sm text-[var(--munin-muted)]">{project.canonical_path}</p>
        </div>
        <button className="munin-btn ghost" onClick={onClose}>Ã—</button>
      </div>

      <div className="mb-6 grid grid-cols-2 gap-4">
        <Field label="Namespace"><span className="font-mono text-sm">{project.namespace}</span></Field>
        <Field label="Status">
          <span className="font-medium" style={{ color: statusColor(project.status) }}>{project.status}</span>
          {project.ignored && (
            <span className="ml-2 rounded px-1.5 py-0.5 text-[10px]" style={{ backgroundColor: "rgba(255,80,80,0.15)", color: "var(--munin-red)" }}>
              IGNORED
            </span>
          )}
        </Field>
        <Field label="Git repository">
          {project.git_root ? <span className="font-mono text-sm">{project.git_root}</span> : <span className="text-[var(--munin-muted)]">No â€” non-Git project</span>}
        </Field>
        <Field label="Memories">{project.memory_count}</Field>
        <Field label="Capture">{project.capture_enabled ? "Enabled" : "Disabled"}</Field>
        <Field label="Discovered">
          {`${formatDistanceToNow(new Date(project.discovered_at))} ago`}
          {project.last_discovered_at && ` Â· last seen ${formatDistanceToNow(new Date(project.last_discovered_at))} ago`}
        </Field>
        <Field label="Discovery source">{project.discovery_source ?? "manual"}</Field>
        <Field label="Last activity">
          {project.last_activity_at ? `${formatDistanceToNow(new Date(project.last_activity_at))} ago` : "Never"}
        </Field>
        {(project.remote_url || project.default_branch) && (
          <>
            <Field label="Git Remote"><span className="truncate font-mono text-sm">{project.remote_url ?? "â€”"}</span></Field>
            <Field label="Default Branch"><span className="font-mono text-sm">{project.default_branch ?? "â€”"}</span></Field>
          </>
        )}
        <Field label="Discovery evidence" wide>
          {project.discovery_evidence.length === 0 ? (
            <span className="text-[var(--munin-muted)]">No markers recorded</span>
          ) : (
            <div className="flex flex-wrap gap-2">
              {project.discovery_evidence.map((m) => (
                <span key={m} className="rounded border border-[var(--munin-border)] px-2 py-0.5 font-mono text-xs">{m}</span>
              ))}
            </div>
          )}
        </Field>
      </div>

      <div className="mb-4">
        <h3 className="mb-2 text-sm font-medium text-[var(--munin-muted)]">Active Sources</h3>
        <div className="flex flex-wrap gap-2">
          {uniqueSources.length === 0 ? (
            <span className="text-sm text-[var(--munin-muted)]">No capture activity yet</span>
          ) : (
            uniqueSources.map((s) => (
              <span key={s} className="rounded border border-[var(--munin-border)] bg-[var(--munin-bg)] px-2 py-1 font-mono text-xs">{s}</span>
            ))
          )}
        </div>
      </div>

      <div className="mb-4">
        <h3 className="mb-2 text-sm font-medium text-[var(--munin-muted)]">Recent Capture Events</h3>
        {loading ? (
          <LoadingState label="Loading activity..." />
        ) : activity?.recent_captures.length === 0 ? (
          <EmptyState title="No capture events yet" />
        ) : (
          <div className="max-h-64 space-y-2 overflow-auto">
            {activity?.recent_captures.map((c) => (
              <div key={c.id} className="rounded border border-[var(--munin-border)] bg-[var(--munin-bg)] p-3">
                <div className="mb-1 flex items-center justify-between">
                  <span className="font-mono text-xs text-[var(--munin-cyan)]">{c.event_type}</span>
                  <span className="font-mono text-xs text-[var(--munin-muted)]">{formatDistanceToNow(new Date(c.occurred_at))} ago</span>
                </div>
                <div className="line-clamp-2 text-sm text-[var(--munin-dim)]">{c.content}</div>
                <div className="mt-1 flex items-center gap-2 text-xs">
                                    <span className="rounded bg-[var(--munin-border)] px-1.5 py-0.5">{c.processing_status}</span>
                  {c.memory_id && <span className="rounded px-1.5 py-0.5" style={{ backgroundColor: "rgba(39,227,107,0.15)", color: "var(--munin-green)" }}>Stored</span>}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="flex justify-end gap-2 border-t border-[var(--munin-border)] pt-4">
        {!project.ignored && (
          <button className="munin-btn primary" onClick={() => { setNamespace(project.namespace); onClose(); }}>
            Select as Scope
          </button>
        )}
        <button className="munin-btn secondary" onClick={toggleIgnored}>
          {project.ignored ? "Unignore" : "Ignore"}
        </button>
        {!project.ignored && (
          <>
            <NavLink to="/explorer" className="munin-btn secondary" onClick={onClose}>
              Open in Explorer
            </NavLink>
            <NavLink to="/graph" className="munin-btn secondary" onClick={onClose}>
              Open in Graph
            </NavLink>
          </>
        )}
      </div>
    </div>
  );
}

function Field({ label, children, wide }: { label: string; children: ReactNode; wide?: boolean }) {
  return (
    <div className={`rounded border border-[var(--munin-border)] bg-[var(--munin-bg)] p-3 ${wide ? "col-span-2" : ""}`}>
      <div className="mb-1 text-xs text-[var(--munin-muted)]">{label}</div>
      <div className="text-sm">{children}</div>
    </div>
  );
}
