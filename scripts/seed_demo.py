"""Seed and verify the real Munin portfolio demo dataset through HTTP APIs.

The script is safe to rerun: every remember operation has a stable idempotency
key and consolidation is idempotent for an equivalent source set. It never
opens or writes the SQLite database directly.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Any

import httpx

from app.sdk import MuninClient
from app.sdk.models import AgentContext, RememberResult

DEFAULT_NAMESPACE = "demo:munin"
DEMO_USER = "demo-user"
SESSION_ID = "munin-portfolio-demo"


@dataclass(frozen=True)
class SeedMemory:
    key: str
    content: str
    agent: str
    user: str = DEMO_USER


MEMORIES = [
    SeedMemory("persistent-layer", "Munin is a persistent memory layer for AI agents.", "cursor"),
    SeedMemory("backend-complete", "Munin M0 through M7A are complete.", "cursor"),
    SeedMemory("frontend-current", "Current frontend milestone is M7B.", "cursor"),
    SeedMemory("fastapi", "Munin uses FastAPI.", "cursor"),
    SeedMemory("semantic", "Munin supports semantic retrieval.", "qwen"),
    SeedMemory("admission", "Munin supports memory admission.", "qwen"),
    SeedMemory("dedup", "Munin supports deduplication.", "qwen"),
    SeedMemory("temporal", "Munin supports temporal memory.", "deepseek"),
    SeedMemory("context", "Munin supports context assembly.", "deepseek"),
    SeedMemory("decay-consolidation", "Munin supports decay and consolidation.", "deepseek"),
    SeedMemory("continuity", "Munin supports cross-agent continuity.", "cursor"),
    SeedMemory("local-first", "Munin is local-first.", "qwen"),
    SeedMemory("model-independent", "User prefers model-independent memory.", "deepseek"),
]


def remember(client: MuninClient, seed: SeedMemory) -> RememberResult:
    result = client.remember(
        seed.content,
        role="user",
        user_id=seed.user,
        agent_id=seed.agent,
        session_id=SESSION_ID,
        idempotency_key=f"m7b-demo-{seed.key}-v1",
    )
    if not result.remembered:
        raise RuntimeError(f"Demo memory was not stored: {seed.key} ({result.decision})")
    return result


def list_memories(http: httpx.Client, namespace: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for offset in range(0, 10_000, 200):
        response = http.get(
            "/api/v1/memories",
            params={"namespace": namespace, "limit": 200, "offset": offset},
        )
        response.raise_for_status()
        page = response.json()
        records.extend(page)
        if len(page) < 200:
            return records
    raise RuntimeError("Demo namespace exceeded the 10,000-memory safety cap")


def temporal_records(http: httpx.Client, memories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for memory in memories:
        response = http.get(f"/api/v1/memories/{memory['id']}/history")
        response.raise_for_status()
        for record in response.json()["temporal_decisions"]:
            records[record["id"]] = record
    return list(records.values())


def seed(base_url: str, namespace: str) -> None:
    outcomes: dict[str, RememberResult] = {}
    with MuninClient(
        base_url=base_url,
        namespace=namespace,
        user_id=DEMO_USER,
        timeout=(5.0, 90.0),
    ) as client, httpx.Client(base_url=base_url, timeout=90.0) as http:
        health = client.health()
        if health.status != "ok":
            raise RuntimeError(f"Munin is not healthy: {health.status}")

        for item in MEMORIES:
            outcomes[item.key] = remember(client, item)

        sqlite = remember(client, SeedMemory(
            "temporal-sqlite", "Munin uses SQLite for demo persistence.", "cursor"
        ))
        postgres = remember(client, SeedMemory(
            "temporal-postgres",
            "Munin switched from SQLite to PostgreSQL for demo persistence.",
            "qwen",
        ))
        if postgres.temporal_relationship != "SUPERSEDES":
            raise RuntimeError(
                f"Expected natural SUPERSEDES, received {postgres.temporal_relationship}"
            )
        if not sqlite.memory_id or not postgres.memory_id:
            raise RuntimeError("Temporal demo did not return both canonical memory IDs")

        building = remember(client, SeedMemory(
            "reinforcement-origin", "User is building Munin.", "cursor"
        ))
        reinforced = remember(client, SeedMemory(
            "reinforcement-confirm", "Yes, still building Munin.", "qwen"
        ))
        if reinforced.dedup_relationship != "REINFORCES":
            raise RuntimeError(
                f"Expected natural REINFORCES, received {reinforced.dedup_relationship}"
            )

        python_pref = remember(client, SeedMemory(
            "conflict-python-v3", "I prefer Python.", "cursor", "demo-conflict-user-v3"
        ))
        rust_pref = remember(client, SeedMemory(
            "conflict-rust-v3", "I prefer Rust.", "deepseek", "demo-conflict-user-v3"
        ))
        if rust_pref.temporal_relationship != "CONTRADICTS":
            raise RuntimeError(
                f"Expected natural CONTRADICTS, received {rust_pref.temporal_relationship}"
            )
        if not python_pref.memory_id or not rust_pref.memory_id:
            raise RuntimeError("Conflict demo did not return both canonical memory IDs")

        source_ids = [outcomes[key].memory_id for key in ("semantic", "admission", "context")]
        if any(memory_id is None for memory_id in source_ids):
            raise RuntimeError("Consolidation source memory is unavailable")
        consolidation = client.consolidate([str(memory_id) for memory_id in source_ids])
        derived_id = consolidation["consolidated_memory_id"]
        provenance_response = http.get(f"/api/v1/memories/{derived_id}/consolidation")
        provenance_response.raise_for_status()
        provenance = provenance_response.json()

        qwen_context = client.get_context(
            "Continue working on Munin.", agent_id="qwen", token_budget=1500
        )
        qwen_update = remember(client, SeedMemory(
            "qwen-update", "Demo verification includes Timeline and Conflict Center.", "qwen"
        ))
        deepseek_context = client.get_context(
            "Does demo verification include Timeline and Conflict Center?",
            agent_id="deepseek",
            token_budget=1500,
        )

        memories = list_memories(http, namespace)
        temporal = temporal_records(http, memories)
        by_id = {memory["id"]: memory for memory in memories}
        if by_id[sqlite.memory_id]["status"] != "superseded":
            raise RuntimeError("Temporal demo source was not superseded")
        if by_id[postgres.memory_id]["status"] != "active":
            raise RuntimeError("Temporal demo replacement is not active")
        preferences_active = (
            by_id[python_pref.memory_id]["status"] == "active"
            and by_id[rust_pref.memory_id]["status"] == "active"
        )
        if not preferences_active:
            raise RuntimeError("Unresolved contradiction memories must both remain active")
        if {source["memory_id"] for source in provenance["sources"]} != set(source_ids):
            raise RuntimeError("Consolidation provenance did not preserve all source links")
        if not any(
            "demo verification includes Timeline" in memory.content
            for memory in deepseek_context.memories_used
        ):
            raise RuntimeError("DeepSeek did not retrieve Qwen's update")

        print_report(
            namespace=namespace,
            memories=memories,
            temporal=temporal,
            consolidation=consolidation,
            qwen_context=qwen_context,
            deepseek_context=deepseek_context,
            qwen_update=qwen_update,
            building=building,
            reinforced=reinforced,
        )


def print_report(
    *,
    namespace: str,
    memories: list[dict[str, Any]],
    temporal: list[dict[str, Any]],
    consolidation: dict[str, Any],
    qwen_context: AgentContext,
    deepseek_context: AgentContext,
    qwen_update: RememberResult,
    building: RememberResult,
    reinforced: RememberResult,
) -> None:
    relationships = [record["relationship"] for record in temporal]
    agents = sorted({memory.get("agent_id") or "unknown" for memory in memories})
    consolidated = [
        memory
        for memory in memories
        if memory.get("metadata", {}).get("is_consolidated") is True
    ]
    print("\nMUNIN DEMO DATASET\n")
    print(f"namespace: {namespace}")
    print(f"memories: {len(memories)}")
    transition_count = sum(item in {"SUPERSEDES", "UPDATES"} for item in relationships)
    print(f"temporal transitions: {transition_count}")
    print(f"contradictions: {relationships.count('CONTRADICTS')}")
    print(f"consolidated memories: {len(consolidated)}")
    print(f"agents: {', '.join(agents)}")
    print(f"reinforcement: {reinforced.dedup_relationship} (canonical={building.memory_id})")
    print(
        f"consolidation: {consolidation['consolidated_memory_id']} "
        f"(new={consolidation['is_new']})"
    )
    print(f"qwen selected memories: {len(qwen_context.memories_used)}")
    print(f"qwen update: {qwen_update.memory_id}")
    print(f"deepseek selected memories: {len(deepseek_context.memories_used)}")
    print('\nContext query: "Continue working on Munin."')
    for memory in qwen_context.memories_used:
        print(f"- {memory.memory_id} [{memory.memory_type}] {memory.content}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed and verify Munin's real demo dataset")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--namespace", default=DEFAULT_NAMESPACE)
    args = parser.parse_args()
    seed(args.base_url.rstrip("/"), args.namespace)


if __name__ == "__main__":
    main()
