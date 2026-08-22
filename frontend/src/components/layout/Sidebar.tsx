import { NavLink } from "react-router-dom";
import { useScope } from "../../lib/scope";

interface NavItem {
  to: string;
  label: string;
  group?: string;
}

const NAV: NavItem[] = [
  { to: "/overview", label: "OVERVIEW", group: "OPERATIONS" },
  { to: "/graph", label: "MEMORY GRAPH", group: "NETWORK" },
  { to: "/memories", label: "MEMORY EXPLORER", group: "NETWORK" },
  { to: "/timeline", label: "TIMELINE", group: "ANALYSIS" },
  { to: "/conflicts", label: "CONFLICTS", group: "ANALYSIS" },
  { to: "/context", label: "CONTEXT PREVIEW", group: "ANALYSIS" },
  { to: "/projects", label: "PROJECTS", group: "SCOPE" },
  { to: "/agents", label: "AGENTS", group: "SCOPE" },
  { to: "/status", label: "STATUS", group: "SYSTEM" },
];

export function Sidebar() {
  const { namespace, setNamespace } = useScope();
  const groups = NAV.reduce<Record<string, NavItem[]>>((acc, item) => {
    const g = item.group ?? "OTHER";
    (acc[g] ??= []).push(item);
    return acc;
  }, {});

  return (
    <nav className="flex h-full w-[210px] shrink-0 flex-col border-r border-[var(--munin-border)] bg-[var(--munin-panel)]">
      <div className="border-b border-[var(--munin-border)] px-3 py-3">
        <div className="font-display text-[15px] tracking-wide-ext text-[var(--munin-green)]">
          MUNIN
        </div>
        <div className="font-mono text-[9px] text-[var(--munin-muted)]">
          MEMORY OPS SYSTEM
        </div>
      </div>

      <div className="px-3 py-2">
        <label className="font-mono text-[9px] uppercase tracking-wider text-[var(--munin-muted)]">
          Active Scope
        </label>
        <input
          className="munin-input mt-1 w-full"
          value={namespace}
          spellCheck={false}
          onChange={(e) => setNamespace(e.target.value.trim() || "project:munin")}
          aria-label="Active namespace scope"
        />
      </div>

      <div className="flex-1 overflow-y-auto px-2 py-2">
        {Object.entries(groups).map(([group, items]) => (
          <div key={group} className="mb-3">
            <div className="px-2 py-1 font-mono text-[9px] uppercase tracking-wider text-[var(--munin-muted)]">
              {group}
            </div>
            {items.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  `flex items-center justify-between px-2 py-1.5 font-mono text-[12px] border-l-2 ${
                    isActive
                      ? "border-[var(--munin-green)] text-[var(--munin-green)] bg-[rgba(39,227,107,0.07)]"
                      : "border-transparent text-[var(--munin-text)] hover:text-[var(--munin-cyan)]"
                  }`
                }
              >
                <span>{item.label}</span>
              </NavLink>
            ))}
          </div>
        ))}
      </div>

      <div className="border-t border-[var(--munin-border)] px-3 py-2 font-mono text-[8px] text-[var(--munin-muted)]">
        M0–M7A OPERATIONAL
      </div>
    </nav>
  );
}
