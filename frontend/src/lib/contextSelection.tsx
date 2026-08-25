import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import type { ContextMemoryUsed, ContextResponse } from "../types/api";

interface ContextSelectionValue {
  result: ContextResponse | null;
  selectedMemoryIds: Set<string>;
  traceByMemoryId: Map<string, ContextMemoryUsed>;
  assembledAt: string | null;
  focusedMemoryId: string | null;
  setResult: (result: ContextResponse) => void;
  setFocusedMemoryId: (id: string | null) => void;
  clear: () => void;
}

const ContextSelection = createContext<ContextSelectionValue | null>(null);

export function ContextSelectionProvider({ children }: { children: ReactNode }) {
  const [result, setStoredResult] = useState<ContextResponse | null>(null);
  const [assembledAt, setAssembledAt] = useState<string | null>(null);
  const [focusedMemoryId, setFocusedMemoryId] = useState<string | null>(null);
  const selectedMemoryIds = useMemo(() => new Set(result?.memories_used.map((memory) => memory.memory_id) ?? []), [result]);
  const traceByMemoryId = useMemo(() => new Map(result?.memories_used.map((memory) => [memory.memory_id, memory]) ?? []), [result]);
  const setResult = (next: ContextResponse) => { setStoredResult(next); setAssembledAt(new Date().toISOString()); setFocusedMemoryId(null); };
  const clear = () => { setStoredResult(null); setAssembledAt(null); setFocusedMemoryId(null); };
  return <ContextSelection.Provider value={{ result, selectedMemoryIds, traceByMemoryId, assembledAt, focusedMemoryId, setResult, setFocusedMemoryId, clear }}>{children}</ContextSelection.Provider>;
}

export function useContextSelection(): ContextSelectionValue {
  const value = useContext(ContextSelection);
  if (!value) throw new Error("useContextSelection must be used within ContextSelectionProvider");
  return value;
}
