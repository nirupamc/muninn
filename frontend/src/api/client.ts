// Centralized transport for the Munin memory engine.
// All components go through this client — no raw fetch() scattered around.

const BASE: string =
  (import.meta.env.VITE_MUNIN_API_URL as string | undefined) ?? "";

export class ApiError extends Error {
  status: number;
  body: unknown;
  constructor(message: string, status: number, body?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${BASE}${path}`;
  let res: Response;
  try {
    res = await fetch(url, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(init?.headers ?? {}),
      },
    });
  } catch (e) {
    throw new ApiError(
      "MEMORY ENGINE CONNECTION LOST",
      0,
      e instanceof Error ? e.message : String(e),
    );
  }

  if (!res.ok) {
    let body: unknown;
    try {
      body = await res.json();
    } catch {
      body = await res.text().catch(() => null);
    }
    const message =
      (body && typeof body === "object" && "detail" in body
        ? String((body as { detail: unknown }).detail)
        : null) ?? `HTTP ${res.status}`;
    throw new ApiError(message, res.status, body);
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  base: BASE,

  getHealth: () => request<{ status: string; service: string }>("/health"),

  listMemories: (params: {
    namespace?: string | null;
    user_id?: string | null;
    agent_id?: string | null;
    memory_type?: string | null;
    status?: string | null;
    limit?: number;
    offset?: number;
  } = {}) => {
    const q = new URLSearchParams();
    if (params.namespace) q.set("namespace", params.namespace);
    if (params.user_id) q.set("user_id", params.user_id);
    if (params.agent_id) q.set("agent_id", params.agent_id);
    if (params.memory_type) q.set("memory_type", params.memory_type);
    if (params.status) q.set("status", params.status);
    q.set("limit", String(params.limit ?? 100));
    q.set("offset", String(params.offset ?? 0));
    return request<import("../types/api").MemoryRead[]>(
      `/api/v1/memories?${q.toString()}`,
    );
  },

  getMemory: (id: string) =>
    request<import("../types/api").MemoryRead>(`/api/v1/memories/${id}`),

  searchMemories: (payload: {
    query: string;
    namespace: string;
    user_id?: string | null;
    agent_id?: string | null;
    limit?: number;
    min_score?: number;
  }) =>
    request<import("../types/api").MemorySearchResponse>(
      "/api/v1/memories/search",
      {
        method: "POST",
        body: JSON.stringify({
          query: payload.query,
          namespace: payload.namespace,
          user_id: payload.user_id ?? null,
          agent_id: payload.agent_id ?? null,
          limit: payload.limit ?? 20,
          min_score: payload.min_score ?? 0.0,
        }),
      },
    ),

  getMemoryHistory: (id: string) =>
    request<import("../types/api").MemoryHistoryResponse>(
      `/api/v1/memories/${id}/history`,
    ),

  getEvent: (id: string) =>
    request<import("../types/api").EventRead>(`/api/v1/events/${id}`),

  getMemoryConsolidation: (id: string) =>
    request<import("../types/api").ConsolidationRead>(
      `/api/v1/memories/${id}/consolidation`,
    ),

  getConsolidationsFromSource: (id: string) =>
    request<import("../types/api").ConsolidationRead[]>(
      `/api/v1/memories/${id}/consolidated-from`,
    ),

  assembleContext: (payload: import("../types/api").ContextRequest) =>
    request<import("../types/api").ContextResponse>("/api/v1/context", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
};
