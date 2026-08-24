import type { ReactNode } from "react";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";
import { BottomBar } from "./BottomBar";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="operations-shell flex h-screen w-screen flex-col overflow-hidden bg-[var(--munin-bg)]">
      <TopBar />
      <div className="flex min-h-0 flex-1">
        <Sidebar />
        <main className="active-view flex min-h-0 flex-1 flex-col bg-[var(--munin-bg)]">
          {children}
        </main>
      </div>
      <BottomBar />
    </div>
  );
}
