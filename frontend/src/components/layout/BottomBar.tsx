import { useScope } from "../../lib/scope";

export function BottomBar() {
  const { namespace } = useScope();
  return (
    <footer className="flex items-center justify-between border-t border-[var(--munin-border)] bg-[var(--munin-panel)] px-4 py-1.5 font-mono text-[10px] text-[var(--munin-muted)]">
      <span>MUNIN MEMORY OPS <span className="text-[var(--munin-green)]">//</span> M7B CHECKPOINT</span>
      <span>SCOPE <span className="text-[var(--munin-cyan)]">{namespace}</span></span>
    </footer>
  );
}
