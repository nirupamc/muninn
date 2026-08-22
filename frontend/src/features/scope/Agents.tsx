import { useMemo } from "react";
import { useAllMemories } from "../../hooks/useMuninData";
import { Panel } from "../../components/ui/Panel";
import { LoadingState, ErrorState, EmptyState } from "../../components/ui/States";

export function Agents() {
  const mem = useAllMemories();
  const agents = useMemo(() => {
    const map = new Map<string, { count: number; namespaces: Set<string> }>();
    for (const m of mem.data?.memories ?? []) {
      const a = m.agentId ?? "(none)";
      const entry = map.get(a) ?? { count: 0, namespaces: new Set<string>() };
      entry.count += 1;
      entry.namespaces.add(m.namespace);
      map.set(a, entry);
    }
    return Array.from(map.entries()).sort((a, b) => b[1].count - a[1].count);
  }, [mem.data]);

  if (mem.loading) return <LoadingState label="ENUMERATING AGENTS" />;
  if (mem.error) return <ErrorState error={mem.error} onRetry={mem.reload} />;

  return (
    <div className="h-full overflow-auto p-3">
      <Panel title="Agent Provenance" subtitle={mem.data?.complete ? "Complete writer provenance inventory" : "Loaded writer provenance // capped at 10,000"} bodyClassName="overflow-auto">
        <table className="munin-table">
          <thead>
            <tr>
              <th>Agent</th>
              <th>Memories</th>
              <th>Scopes</th>
            </tr>
          </thead>
          <tbody>
            {agents.length === 0 && (
              <tr>
                <td colSpan={3} className="text-[var(--munin-muted)]">
                  No agents recorded.
                </td>
              </tr>
            )}
            {agents.map(([a, info]) => (
              <tr key={a} className="munin-row">
                <td className="text-[var(--munin-text)]">{a}</td>
                <td>{info.count}</td>
                <td className="text-[var(--munin-cyan)]">
                  {Array.from(info.namespaces).join(", ")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </div>
  );
}
