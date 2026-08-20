"""Namespace isolation tests."""


def test_memory_namespace_isolation(client):
    client.post(
        "/api/v1/memories",
        json={
            "namespace": "ragparser",
            "content": "RagParser uses Python",
            "memory_type": "project",
        },
    )
    client.post(
        "/api/v1/memories",
        json={
            "namespace": "munin",
            "content": "Munin uses FastAPI",
            "memory_type": "project",
        },
    )

    munin = client.get("/api/v1/memories", params={"namespace": "munin"})
    assert munin.status_code == 200
    bodies = [item["content"] for item in munin.json()]
    assert bodies == ["Munin uses FastAPI"]

    ragparser = client.get("/api/v1/memories", params={"namespace": "ragparser"})
    bodies = [item["content"] for item in ragparser.json()]
    assert bodies == ["RagParser uses Python"]


def test_event_namespace_isolation(client):
    client.post(
        "/api/v1/events",
        json={
            "namespace": "ragparser",
            "role": "user",
            "content": "Parse this PDF",
        },
    )
    client.post(
        "/api/v1/events",
        json={
            "namespace": "munin",
            "role": "user",
            "content": "Store this memory",
        },
    )

    munin = client.get("/api/v1/events", params={"namespace": "munin"})
    assert munin.status_code == 200
    bodies = [item["content"] for item in munin.json()]
    assert bodies == ["Store this memory"]

    ragparser = client.get("/api/v1/events", params={"namespace": "ragparser"})
    bodies = [item["content"] for item in ragparser.json()]
    assert bodies == ["Parse this PDF"]
