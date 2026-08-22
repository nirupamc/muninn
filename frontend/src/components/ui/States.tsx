import type { ReactNode } from "react";
import { ApiError } from "../../api/client";

export function LoadingState({
  label = "SYNCHRONIZING",
}: {
  label?: string;
}) {
  return (
    <div className="flex h-full w-full items-center justify-center p-8">
      <div className="text-center">
        <div className="munin-cursor font-mono text-[13px] text-[var(--munin-green)]">
          MEMORY NETWORK
        </div>
        <div className="mt-2 font-mono text-[11px] text-[var(--munin-cyan)]">
          {label}...
        </div>
      </div>
    </div>
  );
}

export function ErrorState({
  error,
  onRetry,
}: {
  error: ApiError | null;
  onRetry?: () => void;
}) {
  const target = error?.body
    ? typeof error.body === "string"
      ? error.body
      : JSON.stringify(error.body)
    : "";
  return (
    <div className="flex h-full w-full items-center justify-center p-8">
      <div className="max-w-md border border-[var(--munin-red)] bg-black p-5 text-center">
        <div className="font-display text-[15px] tracking-wide-ext glow-red">
          ▓ CONNECTION FAILURE ▓
        </div>
        <div className="mt-3 font-mono text-[12px] text-[var(--munin-red)]">
          MUNIN MEMORY ENGINE
          <br />
          UNREACHABLE
        </div>
        <div className="mt-3 font-mono text-[10px] text-[var(--munin-muted)]">
          <div>TARGET</div>
          <div className="text-[var(--munin-text)]">
            {error?.status ? `${error.status}` : "127.0.0.1:8000"}
          </div>
          {error?.message && (
            <div className="mt-2 text-[var(--munin-orange)]">
              {error.message}
            </div>
          )}
          {target && target.length < 200 && (
            <div className="mt-1 text-[var(--munin-muted)] break-all">
              {target}
            </div>
          )}
        </div>
        {onRetry && (
          <button className="munin-btn mt-4" onClick={onRetry}>
            &gt; RETRY
          </button>
        )}
      </div>
    </div>
  );
}

export function EmptyState({
  title,
  detail,
}: {
  title: string;
  detail?: ReactNode;
}) {
  return (
    <div className="flex h-full w-full items-center justify-center p-8">
      <div className="text-center">
        <div className="font-display text-[14px] tracking-wide-ext text-[var(--munin-muted)]">
          {title}
        </div>
        {detail && (
          <div className="mt-2 font-mono text-[11px] text-[var(--munin-muted)]">
            {detail}
          </div>
        )}
      </div>
    </div>
  );
}
