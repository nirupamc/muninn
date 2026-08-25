import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { Panel } from "../../components/ui/Panel";
import { LoadingState, ErrorState, EmptyState } from "../../components/ui/States";
import { useScope } from "../../lib/scope";
import { formatDistanceToNow } from "../../lib/format";
import { NavLink } from "react-router-dom";

type ProjectStatus = "DISCOVERED" | "CONNECTED" | "MEMORIZED" | "ACTIVE" | "DISABLED";

interface ProjectRow {
  id: string;
  name: string;
  namespace: string;
  root_path: string;
  canonical_path: string;
  git_root: string | null;
  remote_url: string | null;
  default_branch: string | null;
  status: ProjectStatus;
  capture_enabled: boolean;
  discovered_at: string;
  last_activity_at: string | null;
  metadata: Record<string, unknown>;
}

function statusColor(status: ProjectStatus): string {
  switch (status) {
    case "ACTIVE": return "var(--munin-green)";
    case "CONNECTED": return "var(--munin-cyan)";
    case "MEMORIZED": return "var(--munin-amber)";
    case "DISCOVERED": return "var(--munin-muted)";
    case "DISABLED": return "var(--munin-red)";
  }
}

function statusLabel(status: ProjectStatus): string {
  return status;
}

export function Projects() {
  const { namespace, setNamespace } = useScope();
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showDetail, setShowDetail] = useState<string | null>(null);

  async function loadProjects() {
    try {
      setLoading(true);
      const res = await api.listProjects({ limit: 200 });
      setProjects(res.projects);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load projects");
    } finally {
      setLoading(false);
    }
  }

  async function scanProjects() {
    try {
      setLoading(true);
      await api.scanProjects();
      await loadProjects();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to scan projects");
    }
  }

  async function toggleCapture(project: ProjectRow) {
    try {
      if (project.capture_enabled) {
        await api.disableProjectCapture(project.id);
      } else {
        await api.enableProjectCapture(project.id);
      }
      await loadProjects();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to toggle capture");
    }
  }

  async function selectProject(project: ProjectRow) {
    setNamespace(project.namespace);
    setSelectedId(project.id);
  }

  useEffect(() => {
    loadProjects();
  }, []);

  if (loading) return <LoadingState label="LOADING PROJECT REGISTRY" />;

  return (
    <div className="h-full overflow-auto p-3">
      <div className="flex items-center justify-between mb-4">
        <Panel title="Workstation Projects" subtitle={`${projects.length} registered projects`} className="flex-1 min-w-0">
          <div className="overflow-auto">
            <table className="munin-table w-full">
              <thead>
                <tr>
                  <th className="w-8"></th>
                  <th>Project</th>
                  <th className="w-32">Status</th>
                  <th className="w-28">Capture</th>
                  <th className="w-48">Last Activity</th>
                  <th className="w-64">Path</th>
                  <th className="w-48">Namespace</th>
                  <th className="w-8"></th>
                </tr>
              </thead>
              <tbody>
                {projects.length === 0 && (
                  <tr>
                    <td colSpan={8} className="text-[var(--munin-muted)] text-center py-8">
                      No projects registered. Click "Scan Workspace" to discover Git repositories.
                    </td>
                  </tr>
                )}
                {projects.map((p) => (
                  <tr
                    key={p.id}
                    className={`munin-row ${selectedId === p.id ? "selected" : ""}`}
                    onClick={() => selectProject(p)}
                  >
                    <td>
                      <div
                        className="w-2 h-2 rounded-full mt-2"
                        style={{ backgroundColor: statusColor(p.status) }}
                      />
                    </td>
                    <td className="font-mono text-[var(--munin-cyan)]">{p.name}</td>
                    <td>
                      <span
                        className="inline-block px-2 py-0.5 text-xs rounded font-medium"
                        style={{ backgroundColor: `${statusColor(p.status)}22`, color: statusColor(p.status) }}
                      >
                        {statusLabel(p.status)}
                      </span>
                    </td>
                    <td>
                      <label className="inline-flex items-center gap-2 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={p.capture_enabled}
                          onChange={(e) => { e.stopPropagation(); toggleCapture(p); }}
                          className="munin-checkbox"
                        />
                        <span className="text-sm">{p.capture_enabled ? "ON" : "OFF"}</span>
                      </label>
                    </td>
                    <td className="text-sm text-[var(--munin-muted)] font-mono">
                      {p.last_activity_at
                        ? formatDistanceToNow(new Date(p.last_activity_at)) + " ago"
                        : "Never"}
                    </td>
                    <td className="text-sm text-[var(--munin-muted)] font-mono truncate max-w-[200px]" title={p.canonical_path}>
                      {p.canonical_path}
                    </td>
                    <td className="text-sm font-mono text-[var(--munin-dim)]">{p.namespace}</td>
                    <td className="text-right">
                      <button
                        className="munin-btn ghost text-xs"
                        onClick={(e) => { e.stopPropagation(); setShowDetail(p.id); }}
                      >
                        Details
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
        <div className="ml-3 flex flex-col gap-2 w-48 flex-shrink-0">
          <button className="munin-btn primary" onClick={scanProjects} disabled={loading}>
            Scan Workspace
          </button>
          <button className="munin-btn secondary" onClick={loadProjects} disabled={loading}>
            Refresh
          </button>
        </div>
      </div>

      {/* Project Detail Modal */}
      {showDetail && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4" onClick={() => setShowDetail(null)}>
          <div className="bg-[var(--munin-bg-elevated)] border border-[var(--munin-border)] rounded-lg w-full max-w-3xl max-h-[80vh] overflow-auto" onClick={(e) => e.stopPropagation()}>
            <ProjectDetail project={projects.find(p => p.id === showDetail)!} onClose={() => setShowDetail(null)} />
          </div>
        </div>
      )}
    </div>
  );
}

function ProjectDetail({ project, onClose }: { project: ProjectRow; onClose: () => void }) {
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

  const sources = activity?.recent_captures.map(c => c.source) ?? [];
  const uniqueSources = [...new Set(sources)];

  return (
    <div className="p-6">
      <div className="flex items-start justify-between mb-6">
        <div>
          <h2 className="text-xl font-mono text-[var(--munin-cyan)]">{project.name}</h2>
          <p className="text-sm text-[var(--munin-muted)] font-mono">{project.canonical_path}</p>
        </div>
        <button className="munin-btn ghost" onClick={onClose}>×</button>
      </div>

      <div className="grid grid-cols-2 gap-4 mb-6">
        <div className="p-3 bg-[var(--munin-bg)] rounded border border-[var(--munin-border)]">
          <div className="text-xs text-[var(--munin-muted)] mb-1">Namespace</div>
          <div className="font-mono text-sm">{project.namespace}</div>
        </div>
        <div className="p-3 bg-[var(--munin-bg)] rounded border border-[var(--munin-border)]">
          <div className="text-xs text-[var(--munin-muted)] mb-1">Status</div>
          <div className="font-medium" style={{ color: statusColor(project.status) }}>{statusLabel(project.status)}</div>
        </div>
        <div className="p-3 bg-[var(--munin-bg)] rounded border border-[var(--munin-border)]">
          <div className="text-xs text-[var(--munin-muted)] mb-1">Capture</div>
          <div className="font-medium">{project.capture_enabled ? "Enabled" : "Disabled"}</div>
        </div>
        <div className="p-3 bg-[var(--munin-bg)] rounded border border-[var(--munin-border)]">
          <div className="text-xs text-[var(--munin-muted)] mb-1">Discovered</div>
          <div className="font-mono text-sm">{formatDistanceToNow(new Date(project.discovered_at))} ago</div>
        </div>
        <div className="p-3 bg-[var(--munin-bg)] rounded border border-[var(--munin-border)] col-span-2">
          <div className="text-xs text-[var(--munin-muted)] mb-1">Git Remote</div>
          <div className="font-mono text-sm truncate">{project.remote_url ?? "—"}</div>
        </div>
        <div className="p-3 bg-[var(--munin-bg)] rounded border border-[var(--munin-border)] col-span-2">
          <div className="text-xs text-[var(--munin-muted)] mb-1">Default Branch</div>
          <div className="font-mono text-sm">{project.default_branch ?? "—"}</div>
        </div>
      </div>

      <div className="mb-4">
        <h3 className="text-sm font-medium text-[var(--munin-muted)] mb-2">Active Sources</h3>
        <div className="flex flex-wrap gap-2">
          {uniqueSources.length === 0 ? (
            <span className="text-sm text-[var(--munin-muted)]">No capture activity yet</span>
          ) : (
            uniqueSources.map(s => (
              <span key={s} className="px-2 py-1 text-xs bg-[var(--munin-bg)] border border-[var(--munin-border)] rounded font-mono">
                {s}
              </span>
            ))
          )}
        </div>
      </div>

      <div className="mb-4">
        <h3 className="text-sm font-medium text-[var(--munin-muted)] mb-2">Recent Capture Events</h3>
        {loading ? (
          <LoadingState label="Loading activity..." />
        ) : activity?.recent_captures.length === 0 ? (
          <EmptyState title="No capture events yet" />
        ) : (
          <div className="space-y-2 max-h-64 overflow-auto">
            {activity?.recent_captures.map((c) => (
              <div key={c.id} className="p-3 bg-[var(--munin-bg)] rounded border border-[var(--munin-border)]">
                <div className="flex items-center justify-between mb-1">
                  <span className="font-mono text-xs text-[var(--munin-cyan)]">{c.event_type}</span>
                  <span className="text-xs text-[var(--munin-muted)] font-mono">{formatDistanceToNow(new Date(c.occurred_at))} ago</span>
                </div>
                <div className="text-sm text-[var(--munin-dim)] line-clamp-2">{c.content}</div>
                <div className="flex items-center gap-2 mt-1 text-xs">
                  <span className="px-1.5 py-0.5 rounded bg-[var(--munin-border)]">{c.processing_status}</span>
                  {c.memory_id && <span className="px-1.5 py-0.5 rounded bg-[var(--munin-green)]/20 text-[var(--munin-green)]">Stored</span>}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="flex gap-2 justify-end pt-4 border-t border-[var(--munin-border)]">
        <button className="munin-btn primary" onClick={() => { setNamespace(project.namespace); onClose(); }}>
          Select as Scope
        </button>
        <NavLink to="/explorer" className="munin-btn secondary" onClick={onClose}>
          Open in Explorer
        </NavLink>
        <NavLink to="/graph" className="munin-btn secondary" onClick={onClose}>
          Open in Graph
        </NavLink>
      </div>
    </div>
  );
}