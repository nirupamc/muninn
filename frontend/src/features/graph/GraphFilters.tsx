import type { MemoryFilters } from "../../types/domain";
import type { MemoryType, MemoryStatus } from "../../types/api";

const TYPES: (MemoryType | "all")[] = ["all", "project", "goal", "preference", "decision", "fact", "procedure", "event", "relationship", "other"];
const STATUSES: (MemoryStatus | "all")[] = ["all", "active", "superseded", "invalidated", "archived"];

export function GraphFilters({ filters, onChange, agents }: { filters: MemoryFilters; onChange: (next: MemoryFilters) => void; agents: string[] }) {
  const set = (patch: Partial<MemoryFilters>) => onChange({ ...filters, ...patch });
  return (
    <div className="grid grid-cols-2 gap-2 p-2 font-mono text-[10px] sm:grid-cols-3 lg:grid-cols-6">
      <label className="uppercase text-[var(--munin-muted)]">Type
        <select className="munin-input mt-1 w-full" value={filters.memoryType ?? "all"} onChange={(event) => set({ memoryType: event.target.value === "all" ? null : event.target.value as MemoryType })}>{TYPES.map((value) => <option key={value} value={value}>{value.toUpperCase()}</option>)}</select>
      </label>
      <label className="uppercase text-[var(--munin-muted)]">Status
        <select className="munin-input mt-1 w-full" value={filters.status ?? "all"} onChange={(event) => set({ status: event.target.value === "all" ? null : event.target.value as MemoryStatus })}>{STATUSES.map((value) => <option key={value} value={value}>{value.toUpperCase()}</option>)}</select>
      </label>
      <label className="uppercase text-[var(--munin-muted)]">Agent
        <select className="munin-input mt-1 w-full" value={filters.agentId ?? "all"} onChange={(event) => set({ agentId: event.target.value === "all" ? null : event.target.value })}><option value="all">ALL</option>{agents.map((value) => <option key={value} value={value}>{value}</option>)}</select>
      </label>
      <label className="uppercase text-[var(--munin-muted)]">Min confidence <span className="text-[var(--munin-cyan)]">{filters.minConfidence.toFixed(2)}</span>
        <input className="mt-2 block w-full accent-[var(--munin-cyan)]" type="range" min="0" max="1" step="0.05" value={filters.minConfidence} onChange={(event) => set({ minConfidence: Number(event.target.value) })} />
      </label>
      <label className="uppercase text-[var(--munin-muted)]">Min importance <span className="text-[var(--munin-cyan)]">{filters.minImportance.toFixed(2)}</span>
        <input className="mt-2 block w-full accent-[var(--munin-cyan)]" type="range" min="0" max="1" step="0.05" value={filters.minImportance} onChange={(event) => set({ minImportance: Number(event.target.value) })} />
      </label>
      <fieldset className="flex flex-col justify-center border border-[var(--munin-border)] px-2 py-1"><legend className="px-1 uppercase text-[var(--munin-muted)]">Edge types</legend>
        <label className="text-[var(--munin-orange)]"><input className="mr-1" type="checkbox" checked={filters.showTemporal} onChange={(event) => set({ showTemporal: event.target.checked })} />TEMPORAL</label>
        <label className="text-[var(--munin-purple)]"><input className="mr-1" type="checkbox" checked={filters.showConsolidation} onChange={(event) => set({ showConsolidation: event.target.checked })} />CONSOLIDATION</label>
      </fieldset>
    </div>
  );
}

export function defaultFilters(namespace: string): MemoryFilters {
  return { query: "", namespace, memoryType: null, status: null, agentId: null, minConfidence: 0, minImportance: 0, showTemporal: true, showConsolidation: true };
}
