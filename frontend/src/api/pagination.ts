import { api } from "./client";
import type { MemoryRead } from "../types/api";

export const MEMORY_PAGE_SIZE = 200;
export const MEMORY_DATASET_CAP = 10_000;
const MAX_PAGES = MEMORY_DATASET_CAP / MEMORY_PAGE_SIZE;

export interface AllMemoriesResult {
  memories: MemoryRead[];
  complete: boolean;
}

export async function listAllMemories(): Promise<AllMemoriesResult> {
  const memories: MemoryRead[] = [];
  for (let page = 0; page < MAX_PAGES; page += 1) {
    const batch = await api.listMemories({
      limit: MEMORY_PAGE_SIZE,
      offset: page * MEMORY_PAGE_SIZE,
    });
    memories.push(...batch);
    if (batch.length < MEMORY_PAGE_SIZE) return { memories, complete: true };
  }
  return { memories, complete: false };
}
