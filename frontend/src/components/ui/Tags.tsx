import type { MemoryStatus, MemoryType } from "../../types/api";
import { STATUS_COLORS, MEMORY_TYPE_COLORS } from "../../lib/mappers";

export function StatusTag({ status }: { status: MemoryStatus }) {
  const color = STATUS_COLORS[status] ?? "var(--munin-muted)";
  return (
    <span className="status-tag" style={{ color }}>
      {status}
    </span>
  );
}

export function TypeTag({ type }: { type: MemoryType }) {
  const color = MEMORY_TYPE_COLORS[type] ?? "var(--munin-muted)";
  return (
    <span className="status-tag" style={{ color }}>
      {type}
    </span>
  );
}

/** Compact status marker used inside dense tables/rows. */
export function Marker({ label, color }: { label: string; color: string }) {
  return (
    <span
      className="font-mono text-[10px] uppercase tracking-wider"
      style={{ color }}
    >
      [{label}]
    </span>
  );
}
