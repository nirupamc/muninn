import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";
import { useScope } from "../../lib/scope";
import { api } from "../../api/client";

const PRIMARY = [
  ["01", "/overview", "OVERVIEW", "CORE STATUS"],
  ["02", "/graph", "MEMORY", "NETWORK"],
  ["03", "/memories", "MEMORY", "INDEX"],
  ["04", "/context", "CONTEXT", "ASSEMBLY"],
  ["05", "/timeline", "TEMPORAL", "TRACE"],
  ["06", "/conflicts", "CONFLICT", "CENTER"],
] as const;

const SECONDARY = [
  ["/projects", "PROJECTS"],
  ["/agents", "AGENTS"],
  ["/status", "STATUS"],
] as const;

export function Sidebar() {
  const { namespace, setNamespace } = useScope();
  const [open, setOpen] = useState(false);
  const [projects, setProjects] = useState<Array<{ id: string; name: string; namespace: string; status: string }>>([]);
  const [loadingProjects, setLoadingProjects] = useState(false);

  useEffect(() => {
    async function load() {
      setLoadingProjects(true);
      try {
        const res = await api.listProjects({ limit: 50 });
        setProjects(res.projects);
      } catch (e) {
        console.error("Failed to load projects for sidebar", e);
      } finally {
        setLoadingProjects(false);
      }
    }
    load();
  }, []);

  const handleProjectSelect = (ns: string) => {
    setNamespace(ns);
    setOpen(false);
  };

  return (
    <>
      <button className="mobile-nav-trigger" type="button" onClick={() => setOpen(true)} aria-label="Open operations navigation">
        MUNIN // SECTORS
      </button>
      {open && <button className="mobile-nav-scrim" type="button" aria-label="Close navigation" onClick={() => setOpen(false)} />}
      <nav className={`operations-sidebar ${open ? "mobile-open" : ""}`} aria-label="Operational sectors">
        <div className="sidebar-identity">
          <button type="button" onClick={() => setOpen(false)} className="sidebar-close" aria-label="Close navigation">×</button>
          <span>MEMORY OPERATIONS</span>
          <strong>MUNIN</strong>
          <small>NERV-01 // ACTIVE</small>
        </div>
        <div className="sector-list">
          {PRIMARY.map(([number, to, line1, line2]) => (
            <NavLink
              key={to}
              to={to}
              onClick={() => setOpen(false)}
              className={({ isActive }) => `sector-link ${isActive ? "active" : ""}`}
            >
              <span className="sector-number">{number}</span>
              <span>{line1}<b>{line2}</b></span>
              <i aria-hidden="true" />
            </NavLink>
          ))}
        </div>

        <div className="scope-control">
          <label htmlFor="active-scope">CURRENT OPERATING SCOPE</label>
          <div className="relative">
            <input
              id="active-scope"
              className="munin-input"
              value={namespace}
              spellCheck={false}
              onChange={(event) => setNamespace(event.target.value.trim() || "project:munin")}
            />
            {projects.length > 0 && (
              <div className="absolute bottom-full left-0 right-0 mb-1 bg-[var(--munin-bg-elevated)] border border-[var(--munin-border)] rounded-md overflow-hidden z-10 max-h-60 overflow-auto">
                {projects.map((p) => (
                  <button
                    key={p.id}
                    className={`w-full text-left px-3 py-2 text-sm font-mono hover:bg-[var(--munin-border)] ${namespace === p.namespace ? "bg-[var(--munin-border)]" : ""}`}
                    onClick={() => handleProjectSelect(p.namespace)}
                  >
                    <div className="flex items-center gap-2">
                      <span
                        className="w-1.5 h-1.5 rounded-full"
                        style={{
                          backgroundColor:
                            p.status === "ACTIVE" ? "var(--munin-green)" :
                            p.status === "CONNECTED" ? "var(--munin-cyan)" :
                            p.status === "MEMORIZED" ? "var(--munin-amber)" :
                            p.status === "DISABLED" ? "var(--munin-red)" :
                            "var(--munin-muted)"
                        }}
                      />
                      <span className="truncate">{p.name}</span>
                      <span className="text-[var(--munin-muted)] ml-auto">{p.namespace}</span>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="secondary-nav">
          {SECONDARY.map(([to, label]) => (
            <NavLink
              key={to}
              to={to}
              onClick={() => setOpen(false)}
              className={({ isActive }) => (isActive ? "active" : "")}
            >
              {label}
            </NavLink>
          ))}
        </div>

        <div className="lifecycle-rail">
          <span>MEMORY LIFECYCLE</span>
          <i className="active" />
          <i className="superseded" />
          <i className="invalidated" />
          <i className="archived" />
        </div>
      </nav>
    </>
  );
}