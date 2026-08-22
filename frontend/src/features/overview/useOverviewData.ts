import { useMemo } from "react";
import { api } from "../../api/client";
import { listAllMemories } from "../../api/pagination";
import { useAsync } from "../../hooks/useAsync";
import { toMemoryNode } from "../../lib/mappers";
import type { MemoryRead, TemporalRecordRead } from "../../types/api";
import type { MemoryNode } from "../../types/domain";

const RECENT_LIMIT = 10;

export type ActivityKind = "MEMORY" | "SUPERSEDES" | "UPDATES" | "CONTRADICTS";

export interface OverviewActivity {
  memory: MemoryNode;
  kind: ActivityKind;
  occurredAt: string;
}

interface OverviewPayload {
  memories: MemoryRead[];
  complete: boolean;
  activities: OverviewActivity[];
}

function activityFromHistory(memory: MemoryNode, history: TemporalRecordRead[]): OverviewActivity {
  const supported = history
    .filter(
      (record) =>
        record.created_memory_id === memory.id &&
        ["SUPERSEDES", "UPDATES", "CONTRADICTS"].includes(record.relationship.toUpperCase()),
    )
    .sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
  return {
    memory,
    kind: supported ? (supported.relationship.toUpperCase() as ActivityKind) : "MEMORY",
    occurredAt: supported?.created_at ?? memory.createdAt,
  };
}

async function loadOverview(namespace: string): Promise<OverviewPayload> {
  const { memories, complete } = await listAllMemories();
  const recent = memories
    .map(toMemoryNode)
    .filter((memory) => memory.namespace === namespace)
    .sort((a, b) => b.createdAt.localeCompare(a.createdAt))
    .slice(0, RECENT_LIMIT);
  const activities = await Promise.all(
    recent.map(async (memory) => {
      try {
        const history = await api.getMemoryHistory(memory.id);
        return activityFromHistory(memory, history.temporal_decisions);
      } catch {
        return activityFromHistory(memory, []);
      }
    }),
  );
  return { memories, complete, activities };
}

export function useOverviewData(namespace: string) {
  const state = useAsync<OverviewPayload>(() => loadOverview(namespace), [namespace]);
  const data = useMemo(
    () => state.data ? { ...state.data, memories: state.data.memories.map(toMemoryNode) } : null,
    [state.data],
  );
  return { ...state, data };
}
