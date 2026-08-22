import type { ReactNode } from "react";

interface StatBlockProps {
  label: string;
  value: ReactNode;
  color?: string;
  sub?: ReactNode;
}

export function StatBlock({ label, value, color, sub }: StatBlockProps) {
  return (
    <div className="munin-panel-2 flex flex-col justify-between p-3">
      <div className="font-mono text-[10px] uppercase tracking-wider text-[var(--munin-muted)]">
        {label}
      </div>
      <div
        className="font-display text-[28px] leading-none mt-1"
        style={{ color: color ?? "var(--munin-green)" }}
      >
        {value}
      </div>
      {sub && (
        <div className="font-mono text-[10px] text-[var(--munin-muted)] mt-1">
          {sub}
        </div>
      )}
    </div>
  );
}
