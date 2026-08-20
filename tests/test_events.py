"""Event API tests."""


def _create_event(client, **overrides):
    payload = {
        "namespace": "cortex-development",
        "user_id": "user-1",
        "agent_id": "cursor",
        "session_id": "session-001",
        "role": "user",
        "content": "I am building Munin using FastAPI.",
        "metadata": {"source": "chat"},
    }
    payload.update(overrides)
    return client.post("/api/v1/events", json=payload)


def test_event_crud(client):
    create = _create_event(client)
    assert create.status_code == 201
    body = create.json()
    event_id = body["id"]
    assert body["role"] == "user"
    assert body["session_id"] == "session-001"
    assert body["metadata"] == {"source": "chat"}
    assert "created_at" in body

    listed = client.get("/api/v1/events", params={"namespace": "cortex-development"})
    assert listed.status_code == 200
    assert any(item["id"] == event_id for item in listed.json())

    got = client.get(f"/api/v1/events/{event_id}")
    assert got.status_code == 200
    assert got.json()["content"] == "I am building Munin using FastAPI."

    deleted = client.delete(f"/api/v1/events/{event_id}")
    assert deleted.status_code == 204

    missing = client.get(f"/api/v1/events/{event_id}")
    assert missing.status_code == 404


def test_event_validation(client):
    empty = _create_event(client, content="  ")
    assert empty.status_code == 422

    bad_role = _create_event(client, role="narrator")
    assert bad_role.status_code == 422


def test_event_filters_and_pagination(client):
    _create_event(client, session_id="s1", role="user", content="one")
    _create_event(client, session_id="s1", role="assistant", content="two")
    _create_event(client, session_id="s2", role="user", content="three", user_id="user-2")

    by_session = client.get(
        "/api/v1/events",
        params={"namespace": "cortex-development", "session_id": "s1"},
    )
    assert by_session.status_code == 200
    assert len(by_session.json()) == 2

    by_role = client.get(
        "/api/v1/events",
        params={"namespace": "cortex-development", "role": "assistant"},
    )
    assert len(by_role.json()) == 1
    assert by_role.json()[0]["content"] == "two"

    by_user = client.get(
        "/api/v1/events",
        params={"namespace": "cortex-development", "user_id": "user-2"},
    )
    assert len(by_user.json()) == 1

    by_agent = client.get(
        "/api/v1/events",
        params={"namespace": "cortex-development", "agent_id": "cursor"},
    )
    assert len(by_agent.json()) == 3

    page = client.get(
        "/api/v1/events",
        params={"namespace": "cortex-development", "limit": 1, "offset": 0},
    )
    assert len(page.json()) == 1


def test_event_newest_first(client):
    first = _create_event(client, content="older")
    second = _create_event(client, content="newer")
    assert first.status_code == 201
    assert second.status_code == 201

    listed = client.get("/api/v1/events", params={"namespace": "cortex-development"})
    ids = [item["id"] for item in listed.json()]
    assert ids.index(second.json()["id"]) < ids.index(first.json()["id"])
