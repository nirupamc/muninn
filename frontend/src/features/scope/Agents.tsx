import { useEffect, useMemo, useState } from "react";
import { api } from "../../api/client";
import { useAllMemories } from "../../hooks/useMuninData";
import { Panel } from "../../components/ui/Panel";
import { LoadingState, ErrorState, EmptyState } from "../../components/ui/States";
import type { CaptureStatusResponse } from "../../types/api";

const AGENT_CONFIG = [
  { name: "codex", label: "CODEX", capture: true, injection: true, sessionSource: "OpenAI Codex session files" },
  { name: "kilo", label: "KILO", capture: true, injection: true, sessionSource: "Kilo Code session files" },
  { name: "opencode", label: "OPENCODE", capture: true, injection: true, sessionSource: "OpenCode session files" },
  { name: "cline", label: "CLINE", capture: true, injection: true, sessionSource: "Cline session files" },
  { name: "aider", label: "AIDER", capture: true, injection: true, sessionSource: "Aider session files" },
];

export function Agents() {
  const mem = useAllMemories();
  const [capture, setCapture] = useState<CaptureStatusResponse | null>(null);

  useEffect(() => {
    api.getCaptureStatus().then(setCapture).catch(() => {});
  }, []);

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
    <div className="h-full overflow-y-auto p-3">
      <div className="mx-auto max-w-[1400px] space-y-3">
        {/* Agent Integrations */}
        <Panel title="Agent Integrations" subtitle="M8.3 supported agent session adapters">
          <div className="grid grid-cols-1 gap-px bg-[var(--munin-border)] sm:grid-cols-2 lg:grid-cols-3">
            {AGENT_CONFIG.map(({ name, label, capture: cap, injection, sessionSource }) => {
              const adapterHealth = capture?.adapter_health?.[name] ?? [];
              const available = adapterHealth.some((a) => a.available);
              const memoryCount = agents.find(([a]) => a.toLowerCase() === name)?.[1]?.count ?? 0;
              return (
                <div key={name} className="bg-[var(--munin-panel-2)] p-3">
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-[13px] text-[var(--munin-cyan)]">{label}</span>
                    <span
                      className="rounded px-1.5 py-0.5 font-mono text-[9px]"
                      style={{
                        backgroundColor: available ? "rgba(39,227,107,0.1)" : "rgba(255,152,48,0.1)",
                        color: available ? "var(--munin-green)" : "var(--munin-orange)",
                      }}
                    >
                      {available ? "AVAILABLE" : "NOT DETECTED"}
                    </span>
                  </div>
                  <div className="mt-2 space-y-1 font-mono text-[10px]">
                    <div className="flex justify-between">
                      <span className="text-[var(--munin-muted)]">Capture</span>
                      <span style={{ color: cap ? "var(--munin-green)" : "var(--munin-muted)" }}>{cap ? "YES" : "NO"}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-[var(--munin-muted)]">Injection</span>
                      <span style={{ color: injection ? "var(--munin-green)" : "var(--munin-muted)" }}>{injection ? "YES" : "NO"}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-[var(--munin-muted)]">Memories</span>
                      <span className="text-[var(--munin-text)]">{memoryCount}</span>
                    </div>
                    <div className="text-[var(--munin-muted)]">{sessionSource}</div>
                  </div>
                </div>
              );
            })}
          </div>
        </Panel>

        {/* Agent Provenance from Memories */}
        <Panel title="Agent Provenance" subtitle="Memories written by agent across all scopes" bodyClassName="overflow-auto">
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
                  <td className="text-[var(--munin-cyan)]">{a}</td>
                  <td>{info.count}</td>
                  <td className="text-[var(--munin-text)]">
                    {Array.from(info.namespaces).join(", ")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      </div>
    </div>
  );
}
