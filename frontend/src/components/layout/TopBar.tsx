import { useHealth } from "../../hooks/useHealth";

function Chip({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div className="flex items-center gap-1.5 font-mono text-[10px]">
      <span className="text-[var(--munin-muted)]">{label}</span>
      <span style={{ color }}>{value}</span>
    </div>
  );
}

export function TopBar() {
  const { data, loading, error } = useHealth();
  const online = !!data && data.status === "ok" && !error;
  return (
    <header className="flex items-center justify-between border-b border-[var(--munin-border)] bg-[var(--munin-panel)] px-4 py-2">
      <div className="font-display text-[14px] tracking-wide-ext text-[var(--munin-text)]">
        MUNIN <span className="text-[var(--munin-green)]">//</span> MEMORY OPERATIONS
        SYSTEM
      </div>
      <div className="flex items-center gap-4">
        <Chip
          label="ENGINE"
          value={online ? "ONLINE" : loading ? "…" : "OFFLINE"}
          color={online ? "var(--munin-green)" : "var(--munin-red)"}
        />
      </div>
    </header>
  );
}
