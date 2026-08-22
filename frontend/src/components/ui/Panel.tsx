import type { ReactNode } from "react";

interface PanelProps {
  title?: string;
  subtitle?: string;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
  scan?: boolean;
}

export function Panel({
  title,
  subtitle,
  right,
  children,
  className = "",
  bodyClassName = "",
  scan = false,
}: PanelProps) {
  return (
    <section
      className={`munin-panel relative flex flex-col ${scan ? "crt-scanlines" : ""} ${className}`}
    >
      {title !== undefined && (
        <header className="flex items-center justify-between border-b border-[var(--munin-border)] px-3 py-2">
          <div>
            <h2 className="font-display text-[13px] tracking-wide-ext text-[var(--munin-green)]">
              {title}
            </h2>
            {subtitle && (
              <p className="font-mono text-[10px] text-[var(--munin-muted)]">
                {subtitle}
              </p>
            )}
          </div>
          {right}
        </header>
      )}
      <div className={`flex-1 min-h-0 ${bodyClassName}`}>{children}</div>
    </section>
  );
}
