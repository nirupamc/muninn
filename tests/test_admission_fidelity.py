"""M2 candidate extraction fidelity regressions (polarity, entities, temporal phrases)."""

from __future__ import annotations

from app.admission.providers.deterministic import DeterministicAdmissionProvider


def _store_contents(text: str) -> list[str]:
    provider = DeterministicAdmissionProvider()
    analysis = provider.analyze_event(role="user", content=text)
    return [
        c.candidate.content
        for c in analysis.candidates
        if c.provider_recommendation == "STORE"
    ]


def test_entity_preservation_ragparser_building():
    contents = _store_contents("I'm building RagParser.")
    assert contents
    assert any("RagParser" in c for c in contents)
    assert not any(re_search_a_project(c) for c in contents)


def test_entity_preservation_ragparser_working_on_paraphrase():
    contents = _store_contents("RagParser is the document parser I'm working on.")
    assert contents
    assert any("RagParser" in c for c in contents)


def test_polarity_do_not_prefer():
    contents = _store_contents("I do not prefer Python.")
    assert contents
    assert any("does not prefer" in c.lower() for c in contents)
    assert not any(
        "prefers python" in c.lower() and "does not" not in c.lower() for c in contents
    )


def test_polarity_do_not_prefer_anymore():
    contents = _store_contents("I do not prefer Python anymore.")
    assert contents
    joined = " ".join(contents).lower()
    assert "does not prefer" in joined
    assert "python" in joined


def test_temporal_no_longer_use():
    contents = _store_contents("I no longer use SQLite.")
    assert contents
    joined = " ".join(contents).lower()
    assert "no longer" in joined
    assert "sqlite" in joined


def test_temporal_still_use():
    contents = _store_contents("I still use FastAPI.")
    assert contents
    joined = " ".join(contents).lower()
    assert "still" in joined
    assert "fastapi" in joined


def test_temporal_now_prefer():
    contents = _store_contents("I now prefer Rust.")
    assert contents
    joined = " ".join(contents).lower()
    assert "now prefer" in joined
    assert "rust" in joined


def test_temporal_used_to_prefer():
    contents = _store_contents("I used to prefer JavaScript.")
    assert contents
    joined = " ".join(contents).lower()
    assert "used to prefer" in joined
    assert "javascript" in joined


def test_temporal_switched_from_to():
    contents = _store_contents("I switched from OpenAI to local models.")
    assert contents
    joined = " ".join(contents).lower()
    assert "switched from" in joined
    assert "openai" in joined
    assert "local models" in joined


def test_still_prefer_preserved():
    contents = _store_contents("I still prefer OpenAI APIs.")
    assert contents
    joined = " ".join(contents).lower()
    assert "still prefer" in joined
    assert "openai" in joined


def re_search_a_project(text: str) -> bool:
    return text.strip().lower() in {"user is building a project.", "user is building a project"}
