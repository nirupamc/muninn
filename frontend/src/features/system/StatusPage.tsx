import { useHealth } from "../../hooks/useHealth";
import { Panel } from "../../components/ui/Panel";
import { LoadingState, ErrorState } from "../../components/ui/States";

export function StatusPage() {
  const health = useHealth();
  if (health.loading) return <LoadingState label="QUERYING ENGINE" />;
  if (health.error) return <ErrorState error={health.error} onRetry={health.reload} />;

  const online = health.data?.status === "ok";
  return (
    <div className="h-full overflow-auto p-3">
      <Panel title="System Status" subtitle="Munin memory engine health" scan>
        <div className="p-3 font-mono text-[12px]">
          <Row label="Service" value={health.data?.service ?? "—"} color="var(--munin-cyan)" />
          <Row label="Status" value={online ? "ONLINE" : "OFFLINE"} color={online ? "var(--munin-green)" : "var(--munin-red)"} />
          <Row label="Backend checkpoint" value="M0–M7A VERIFIED" color="var(--munin-green)" />
          <Row label="Frontend checkpoint" value="M7B" color="var(--munin-cyan)" />
          <Row label="Database telemetry" value="UNAVAILABLE" color="var(--munin-muted)" />
        </div>
      </Panel>
    </div>
  );
}

function Row({ label, value, color }: { label: string; value: string; color: string }) {
  return <div className="flex justify-between border-b border-[var(--munin-border)] py-1.5"><span className="text-[var(--munin-muted)]">{label}</span><span style={{ color }}>{value}</span></div>;
}
