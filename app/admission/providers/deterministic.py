"""Deterministic admission provider for tests and offline defaults."""

from __future__ import annotations

import re
from typing import Any

from app.admission.base import AdmissionProvider
from app.admission.models import (
    AdmissionAnalysis,
    AdmissionCandidate,
    CandidateAnalysis,
    ReasonCode,
)
from app.models.memory import MemoryType

_REMEMBER = re.compile(
    r"(?i)\b(?:remember(?:\s+that)?|please\s+remember|don't\s+forget|"
    r"keep\s+in\s+mind|note\s+that)\b"
)
_PROJECT = re.compile(
    r"(?i)\b(?:i(?:'m| am)\s+building|building|working\s+on|developing)\b"
)
_PREFER = re.compile(r"(?i)\b(?:i\s+prefer|my\s+preferred|prefer)\b")
_FEEL_LIKE = re.compile(r"(?i)\b(?:feel\s+like|today|right\s+now|this\s+morning)\b")
_GOAL = re.compile(r"(?i)\b(?:my\s+goal|long[- ]term\s+goal|i\s+want\s+to\s+build|"
                   r"aim(?:ing)?\s+to)\b")
_DECISION = re.compile(r"(?i)\b(?:we\s+decided|decided\s+to|chose\s+to|will\s+use)\b")
_TRIVIAL_FOOD = re.compile(
    r"(?i)\b(?:ate|eaten|burger|pizza|lunch|dinner|coffee|snack)\b"
)
_EPHEMERAL = re.compile(
    r"(?i)\b(?:sleepy|tired|hungry|back\s+in\s+\w+|port\s+\d+|just\s+now|"
    r"right\s+now|currently\s+on)\b"
)
_DEBUGGING = re.compile(r"(?i)\b(?:debugging|fixing)\b")


class DeterministicAdmissionProvider(AdmissionProvider):
    """
    Rule-based extractor that produces structured candidates without LLMs.

    Designed for reproducible tests and a safe default offline provider.
    """

    def __init__(self, model_name: str = "deterministic-rules-v1") -> None:
        self._model_name = model_name

    @property
    def provider_name(self) -> str:
        return "deterministic"

    @property
    def model_name(self) -> str:
        return self._model_name

    def analyze_event(
        self,
        *,
        role: str,
        content: str,
        context: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> AdmissionAnalysis:
        text = (content or "").strip()
        if not text:
            return AdmissionAnalysis(candidates=[])

        # Split multi-fact utterances on common conjunctions while keeping clauses.
        clauses = _split_clauses(text)
        candidates: list[CandidateAnalysis] = []
        for clause in clauses:
            analysis = self._analyze_clause(clause, original=text)
            if analysis is not None:
                candidates.append(analysis)

        # If splitting produced nothing useful, analyze the whole text once.
        if not candidates:
            analysis = self._analyze_clause(text, original=text)
            if analysis is not None:
                candidates.append(analysis)

        return AdmissionAnalysis(candidates=candidates)

    def _analyze_clause(self, clause: str, *, original: str) -> CandidateAnalysis | None:
        clause = clause.strip(" .,;")
        if not clause:
            return None

        explicit_remember = bool(_REMEMBER.search(clause) or _REMEMBER.search(original))

        # Food / trivial chatter
        if _TRIVIAL_FOOD.search(clause) and not _PROJECT.search(clause):
            return CandidateAnalysis(
                candidate=AdmissionCandidate(
                    content=_normalize_statement(clause, prefix="User mentioned"),
                    memory_type=MemoryType.event,
                    importance=0.15,
                    confidence=0.95,
                    future_utility=0.05,
                    stability=0.05,
                    specificity=0.4,
                    explicitness=0.7,
                    triviality=0.95,
                ),
                provider_recommendation="IGNORE",
                reason_codes=[ReasonCode.TRIVIAL, ReasonCode.EPHEMERAL, ReasonCode.LOW_FUTURE_UTILITY],
                explanation="Ephemeral personal detail",
            )

        # Ephemeral state
        if _EPHEMERAL.search(clause) and not (
            _PROJECT.search(clause) or _PREFER.search(clause) or _GOAL.search(clause)
        ):
            return CandidateAnalysis(
                candidate=AdmissionCandidate(
                    content=_normalize_statement(clause, prefix="User reported"),
                    memory_type=MemoryType.event,
                    importance=0.2,
                    confidence=0.9,
                    future_utility=0.05,
                    stability=0.05,
                    specificity=0.3,
                    explicitness=0.8,
                    triviality=0.85,
                ),
                provider_recommendation="IGNORE",
                reason_codes=[ReasonCode.EPHEMERAL, ReasonCode.LOW_FUTURE_UTILITY],
                explanation="Temporary state",
            )

        # Temporary preference / mood wording ("feel like using X today")
        if _FEEL_LIKE.search(clause) and (
            _PREFER.search(clause)
            or re.search(r"(?i)\b(?:using|use)\b", clause)
        ):
            return CandidateAnalysis(
                candidate=AdmissionCandidate(
                    content=_normalize_statement(clause, prefix="User"),
                    memory_type=MemoryType.preference,
                    importance=0.4,
                    confidence=0.7,
                    future_utility=0.25,
                    stability=0.2,
                    specificity=0.5,
                    explicitness=0.5,
                    triviality=0.4,
                ),
                provider_recommendation="IGNORE",
                reason_codes=[ReasonCode.EPHEMERAL, ReasonCode.LOW_FUTURE_UTILITY],
                explanation="Temporary preference wording",
            )

        # Temporary preference wording with prefer + today/feel
        if _PREFER.search(clause) and _FEEL_LIKE.search(clause):
            return CandidateAnalysis(
                candidate=AdmissionCandidate(
                    content=_normalize_statement(clause, prefix="User"),
                    memory_type=MemoryType.preference,
                    importance=0.4,
                    confidence=0.7,
                    future_utility=0.25,
                    stability=0.2,
                    specificity=0.5,
                    explicitness=0.5,
                    triviality=0.4,
                ),
                provider_recommendation="IGNORE",
                reason_codes=[ReasonCode.EPHEMERAL, ReasonCode.LOW_FUTURE_UTILITY],
                explanation="Temporary preference wording",
            )

        # Debugging — factual work signal, not affection
        if _DEBUGGING.search(clause):
            tool = _extract_named_tool(clause) or "the mentioned tool"
            return CandidateAnalysis(
                candidate=AdmissionCandidate(
                    content=f"User is currently working with {tool}.",
                    memory_type=MemoryType.fact,
                    importance=0.45,
                    confidence=0.75,
                    future_utility=0.4,
                    stability=0.35,
                    specificity=0.6,
                    explicitness=0.7,
                    triviality=0.35,
                ),
                provider_recommendation="IGNORE",
                reason_codes=[ReasonCode.SPECIFIC_FACT, ReasonCode.LOW_FUTURE_UTILITY],
                explanation="Near-term work context; not a durable preference",
            )

        # Project
        if _PROJECT.search(clause):
            project = _extract_project_name(clause) or "a project"
            details = _extract_project_details(clause)
            content = f"User is building {project}"
            if details:
                content = f"{content}{details}"
            content = content.rstrip(".") + "."
            reasons = [ReasonCode.ONGOING_PROJECT, ReasonCode.HIGH_FUTURE_UTILITY]
            if explicit_remember:
                reasons.append(ReasonCode.EXPLICIT_REMEMBER_REQUEST)
            return CandidateAnalysis(
                candidate=AdmissionCandidate(
                    content=content,
                    memory_type=MemoryType.project,
                    importance=0.9,
                    confidence=0.95,
                    future_utility=0.92,
                    stability=0.8,
                    specificity=0.85,
                    explicitness=0.95 if explicit_remember else 0.9,
                    triviality=0.05,
                ),
                provider_recommendation="STORE",
                reason_codes=reasons,
                explanation="Ongoing project statement",
            )

        # Stable preference
        if _PREFER.search(clause):
            content = _normalize_preference(clause)
            reasons = [ReasonCode.STABLE_PREFERENCE, ReasonCode.EXPLICIT_USER_STATEMENT]
            if explicit_remember:
                reasons.append(ReasonCode.EXPLICIT_REMEMBER_REQUEST)
            return CandidateAnalysis(
                candidate=AdmissionCandidate(
                    content=content,
                    memory_type=MemoryType.preference,
                    importance=0.8,
                    confidence=0.95,
                    future_utility=0.85,
                    stability=0.85,
                    specificity=0.75,
                    explicitness=0.98 if explicit_remember else 0.9,
                    triviality=0.05,
                ),
                provider_recommendation="STORE",
                reason_codes=reasons,
                explanation="Stable preference",
            )

        # Goal
        if _GOAL.search(clause):
            content = _normalize_goal(clause)
            return CandidateAnalysis(
                candidate=AdmissionCandidate(
                    content=content,
                    memory_type=MemoryType.goal,
                    importance=0.88,
                    confidence=0.92,
                    future_utility=0.9,
                    stability=0.75,
                    specificity=0.8,
                    explicitness=0.9,
                    triviality=0.05,
                ),
                provider_recommendation="STORE",
                reason_codes=[ReasonCode.LONG_TERM_GOAL, ReasonCode.HIGH_FUTURE_UTILITY],
                explanation="Explicit goal",
            )

        # Decision
        if _DECISION.search(clause):
            content = _normalize_decision(clause)
            return CandidateAnalysis(
                candidate=AdmissionCandidate(
                    content=content,
                    memory_type=MemoryType.decision,
                    importance=0.85,
                    confidence=0.93,
                    future_utility=0.8,
                    stability=0.7,
                    specificity=0.85,
                    explicitness=0.9,
                    triviality=0.05,
                ),
                provider_recommendation="STORE",
                reason_codes=[ReasonCode.EXPLICIT_DECISION, ReasonCode.SPECIFIC_FACT],
                explanation="Explicit decision",
            )

        # Explicit remember of a generic fact
        if explicit_remember:
            cleaned = _REMEMBER.sub("", clause).strip(" :,.")
            cleaned = re.sub(r"(?i)^that\s+", "", cleaned).strip()
            cleaned = re.sub(r"(?i)^i\s+", "", cleaned).strip()
            statement = cleaned[0].upper() + cleaned[1:] if cleaned else cleaned
            if not statement.lower().startswith("user"):
                statement = f"User {statement[0].lower() + statement[1:]}" if statement else "User fact."
            if not statement.endswith("."):
                statement += "."
            return CandidateAnalysis(
                candidate=AdmissionCandidate(
                    content=statement,
                    memory_type=MemoryType.fact,
                    importance=0.75,
                    confidence=0.9,
                    future_utility=0.75,
                    stability=0.7,
                    specificity=0.7,
                    explicitness=0.98,
                    triviality=0.1,
                ),
                provider_recommendation="STORE",
                reason_codes=[
                    ReasonCode.EXPLICIT_REMEMBER_REQUEST,
                    ReasonCode.EXPLICIT_USER_STATEMENT,
                ],
                explanation="Explicit remember request",
            )

        # Tech stack fact: "using SQLite"
        using = re.search(
            r"(?i)\b(?:using|use|uses)\s+([A-Za-z0-9][\w\-]*(?:\s+[A-Za-z0-9][\w\-]*){0,3})",
            clause,
        )
        if using and re.search(r"(?i)\b(sqlite|fastapi|python|postgres|redis)\b", clause):
            tech = using.group(1).strip()
            subject = "Munin" if re.search(r"(?i)\bmunin\b", original) else "The project"
            return CandidateAnalysis(
                candidate=AdmissionCandidate(
                    content=f"{subject} currently uses {tech}.",
                    memory_type=MemoryType.fact,
                    importance=0.8,
                    confidence=0.9,
                    future_utility=0.75,
                    stability=0.65,
                    specificity=0.85,
                    explicitness=0.85,
                    triviality=0.1,
                ),
                provider_recommendation="STORE",
                reason_codes=[ReasonCode.SPECIFIC_FACT, ReasonCode.HIGH_FUTURE_UTILITY],
                explanation="Technology choice fact",
            )

        # Default: low-value conversational content
        return CandidateAnalysis(
            candidate=AdmissionCandidate(
                content=_normalize_statement(clause, prefix="User said"),
                memory_type=MemoryType.other,
                importance=0.25,
                confidence=0.55,
                future_utility=0.15,
                stability=0.2,
                specificity=0.3,
                explicitness=0.4,
                triviality=0.7,
            ),
            provider_recommendation="IGNORE",
            reason_codes=[
                ReasonCode.LOW_FUTURE_UTILITY,
                ReasonCode.TRIVIAL,
                ReasonCode.TOO_UNCERTAIN,
            ],
            explanation="No durable signal detected",
        )


def _split_clauses(text: str) -> list[str]:
    # Keep "and" splits for multi-fact messages while avoiding tiny fragments.
    parts = re.split(r"\s*(?:,|\band\b)\s+", text, flags=re.IGNORECASE)
    cleaned = [p.strip() for p in parts if p and len(p.strip()) > 8]
    return cleaned if cleaned else [text]


def _normalize_statement(text: str, *, prefix: str) -> str:
    t = text.strip()
    t = re.sub(r"(?i)^i(?:'m| am)\s+", "", t)
    t = t[0].upper() + t[1:] if t else t
    if not t.lower().startswith("user"):
        t = f"{prefix} {t[0].lower() + t[1:]}" if t else prefix
    if not t.endswith("."):
        t += "."
    return t


def _extract_project_name(clause: str) -> str | None:
    m = re.search(
        r"(?i)\b(?:building|working on|developing)\s+([A-Za-z][\w\-]*)",
        clause,
    )
    return m.group(1) if m else None


def _extract_project_details(clause: str) -> str:
    bits: list[str] = []
    if re.search(r"(?i)\bin\s+python\b", clause):
        bits.append(" in Python")
    desc = re.search(
        r"(?i),\s*a\s+(.+)$",
        clause,
    )
    if desc:
        bits.append(f", a {desc.group(1).strip().rstrip('.')}")
    return "".join(bits)


def _extract_named_tool(clause: str) -> str | None:
    m = re.search(r"(?i)\b([A-Za-z][\w\.]{1,40})\b(?:\s+all\s+week)?\s*$", clause)
    # Prefer known frameworks in the clause
    for name in ("FastAPI", "Django", "Flask", "React", "Munin", "RagParser"):
        if re.search(rf"(?i)\b{re.escape(name)}\b", clause):
            return name
    return m.group(1) if m else None


def _normalize_preference(clause: str) -> str:
    m = re.search(
        r"(?i)\b(?:prefer|preferred)\s+(.+)$",
        _REMEMBER.sub("", clause).strip(),
    )
    if m:
        rest = m.group(1).strip().rstrip(".")
        return f"User prefers {rest}."
    return _normalize_statement(clause, prefix="User")


def _normalize_goal(clause: str) -> str:
    m = re.search(r"(?i)\b(?:goal(?:\s+is)?|aim(?:ing)?\s+to)\s+(?:to\s+)?(.+)$", clause)
    if m:
        rest = m.group(1).strip().rstrip(".")
        return f"User's goal is to {rest}."
    return _normalize_statement(clause, prefix="User")


def _normalize_decision(clause: str) -> str:
    m = re.search(r"(?i)\b(?:decided to|chose to|will use)\s+(.+)$", clause)
    if m:
        rest = m.group(1).strip().rstrip(".")
        return f"Decision: {rest}."
    return _normalize_statement(clause, prefix="Decision")
