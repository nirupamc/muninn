import { useMemo } from "react";
import { useAllMemories } from "../../hooks/useMuninData";
import { Panel } from "../../components/ui/Panel";
import { LoadingState, ErrorState, EmptyState } from "../../components/ui/States";

export function Projects() {
  const mem = useAllMemories();
  const scopes = useMemo(() => {
    const map = new Map<string, number>();
    for (const m of mem.data?.memories ?? []) map.set(m.namespace, (map.get(m.namespace) ?? 0) + 1);
    return Array.from(map.entries()).sort((a, b) => b[1] - a[1]);
  }, [mem.data]);

  if (mem.loading) return <LoadingState label="ENUMERATING SCOPES" />;
  if (mem.error) return <ErrorState error={mem.error} onRetry={mem.reload} />;

  return (
    <div className="h-full overflow-auto p-3">
      <Panel title="Project Scopes" subtitle={mem.data?.complete ? "Complete namespace inventory" : "Loaded namespace inventory // capped at 10,000"} bodyClassName="overflow-auto">
        <table className="munin-table">
          <thead>
            <tr>
              <th>Namespace</th>
              <th>Memories</th>
            </tr>
          </thead>
          <tbody>
            {scopes.length === 0 && (
              <tr>
                <td colSpan={2} className="text-[var(--munin-muted)]">
                  No scopes found.
                </td>
              </tr>
            )}
            {scopes.map(([ns, count]) => (
              <tr key={ns} className="munin-row">
                <td className="text-[var(--munin-cyan)]">{ns}</td>
                <td>{count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </div>
  );
}
