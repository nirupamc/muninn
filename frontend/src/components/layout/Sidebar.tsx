import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";
import { useScope } from "../../lib/scope";
import { api } from "../../api/client";

const PRIMARY = [
  ["01", "/overview", "OVERVIEW", "CORE STATUS"],
  ["02", "/memories", "MEMORY", "EXPLORER"],
  ["03", "/graph", "MEMORY", "GRAPH"],
  ["04", "/context", "CONTEXT", "RETRIEVAL"],
  ["05", "/observations", "OBSERVATIONS", "ACTIVITY"],
  ["06", "/timeline", "TEMPORAL", "TRACE"],
  ["07", "/conflicts", "CONFLICT", "CENTER"],
  ["08", "/agents", "AGENTS", "SYSTEM"],
] as const;

const SECONDARY = [
  ["/projects", "PROJECTS"],
  ["/status", "STATUS"],
] as const;

export function Sidebar() {
  const { namespace, setNamespace } = useScope();
  const [open, setOpen] = useState(false);
  const [projects, setProjects] = useState<Array<{ id: string; name: string; namespace: string; status: string; memory_count: number }>>([]);
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
        {/* Fixed: brand header */}
        <div className="sidebar-identity">
          <button type="button" onClick={() => setOpen(false)} className="sidebar-close" aria-label="Close navigation">×</button>
          <span>MEMORY OPERATIONS</span>
          <strong>MUNIN</strong>
          <small>NERV-01 // ACTIVE</small>
        </div>

        {/* Fixed: main navigation — never scrolls */}
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

        {/* Scrollable: project scope list — independently scrollable */}
        <div className="scope-control">
          <label htmlFor="active-scope">CURRENT OPERATING SCOPE</label>
          <input
            id="active-scope"
            className="munin-input"
            value={namespace}
            spellCheck={false}
            onChange={(event) => setNamespace(event.target.value.trim() || "project:munin")}
          />
          {projects.length > 0 && (
            <div className="project-list">
              {projects.map((p) => (
                <button
                  key={p.id}
                  className={`project-item ${namespace === p.namespace ? "active" : ""}`}
                  onClick={() => handleProjectSelect(p.namespace)}
                  title={`${p.name} — ${p.namespace} — ${p.memory_count} memories`}
                >
                  <span
                    className="project-dot"
                    style={{
                      backgroundColor:
                        p.status === "ACTIVE" ? "var(--munin-green)" :
                        p.status === "CONNECTED" ? "var(--munin-cyan)" :
                        p.status === "MEMORIZED" ? "var(--munin-amber)" :
                        p.status === "DISABLED" ? "var(--munin-red)" :
                        "var(--munin-muted)"
                    }}
                  />
                  <span className="project-name">{p.name}</span>
                  <span className="project-count">{p.memory_count}</span>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Fixed: secondary nav */}
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

        {/* Fixed: lifecycle rail */}
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