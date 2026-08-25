import { createContext, useContext, useState, type ReactNode } from "react";

interface ScopeValue {
  namespace: string;
  setNamespace: (ns: string) => void;
}

const ScopeContext = createContext<ScopeValue | null>(null);

export function ScopeProvider({
  initial = "project:munin",
  children,
}: {
  initial?: string;
  children: ReactNode;
}) {
  const [namespace, setNamespace] = useState(initial);
  return (
    <ScopeContext.Provider value={{ namespace, setNamespace }}>
      {children}
    </ScopeContext.Provider>
  );
}

export function useScope(): ScopeValue {
  const v = useContext(ScopeContext);
  if (!v) throw new Error("useScope must be used within ScopeProvider");
  return v;
}
