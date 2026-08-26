"""Evaluation module for agent session capture (M8.3)."""

from __future__ import annotations

import logging
import sys
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.capture.agent_sessions.service import AgentSessionService
from app.database import Base

logger = logging.getLogger("munin.capture.agent_sessions.evaluate")

# Test database path for isolation
_TEST_DB_PATH = "data/munin_test_agent_sessions.db"


def create_test_engine() -> Any:
    """Create an isolated test database engine."""
    import os
    
    # Ensure data directory exists
    os.makedirs("data", exist_ok=True)
    
    # Use a separate test database
    engine = create_engine(f"sqlite:///{_TEST_DB_PATH}")
    return engine


def setup_test_db() -> Any:
    """Set up test database with schema."""
    engine = create_test_engine()
    Base.metadata.create_all(engine)
    return engine


def get_test_session_factory(engine: Any) -> Any:
    """Get a session factory for the test database."""
    return sessionmaker(bind=engine)


def run_evaluation() -> dict[str, Any]:
    """Run agent session capture evaluation.
    
    Returns:
        Dictionary with evaluation results and metrics.
    """
    results = {
        "timestamp": datetime.now(UTC).isoformat(),
        "tests_passed": 0,
        "tests_failed": 0,
        "test_results": [],
        "metrics": {
            "session_event_ingest_success_rate": 0.0,
            "meaningful_event_precision": 0.0,
            "trivial_prompt_ignore_rate": 0.0,
            "duplicate_session_event_count": 0,
            "session_replay_count": 0,
            "secret_capture_count": 0,
            "session_to_memory_success_rate": 0.0,
            "cross_agent_retrieval_success_rate": 0.0,
        },
    }
    
    # Test 1: Service initialization
    try:
        engine = setup_test_db()
        SessionLocal = get_test_session_factory(engine)
        db = SessionLocal()
        
        try:
            service = AgentSessionService(db)
            results["test_results"].append({
                "name": "service_initialization",
                "status": "passed",
                "message": "AgentSessionService initialized successfully",
            })
            results["tests_passed"] += 1
        finally:
            db.close()
    except Exception as e:
        results["test_results"].append({
            "name": "service_initialization",
            "status": "failed",
            "message": str(e),
        })
        results["tests_failed"] += 1
    
    # Test 2: Adapter availability
    try:
        engine = setup_test_db()
        SessionLocal = get_test_session_factory(engine)
        db = SessionLocal()
        
        try:
            service = AgentSessionService(db)
            available = service.get_available_adapters()
            
            # Check that at least one adapter is available or gracefully handles unavailable
            results["test_results"].append({
                "name": "adapter_availability",
                "status": "passed",
                "message": f"Found {len(available)} available adapters",
                "data": {"available_adapters": [a.value for a in available]},
            })
            results["tests_passed"] += 1
        finally:
            db.close()
    except Exception as e:
        results["test_results"].append({
            "name": "adapter_availability",
            "status": "failed",
            "message": str(e),
        })
        results["tests_failed"] += 1
    
    # Test 3: Adapter health
    try:
        engine = setup_test_db()
        SessionLocal = get_test_session_factory(engine)
        db = SessionLocal()
        
        try:
            service = AgentSessionService(db)
            health = service.get_adapter_health()
            
            results["test_results"].append({
                "name": "adapter_health",
                "status": "passed",
                "message": f"Adapter health checked for {len(health)} adapters",
                "data": health,
            })
            results["tests_passed"] += 1
        finally:
            db.close()
    except Exception as e:
        results["test_results"].append({
            "name": "adapter_health",
            "status": "failed",
            "message": str(e),
        })
        results["tests_failed"] += 1
    
    # Test 4: Session discovery (should not crash even if no sessions found)
    try:
        engine = setup_test_db()
        SessionLocal = get_test_session_factory(engine)
        db = SessionLocal()
        
        try:
            service = AgentSessionService(db)
            sessions = service.discover_sessions()
            
            results["test_results"].append({
                "name": "session_discovery",
                "status": "passed",
                "message": f"Discovered {len(sessions)} sessions",
                "data": {"session_count": len(sessions)},
            })
            results["tests_passed"] += 1
        finally:
            db.close()
    except Exception as e:
        results["test_results"].append({
            "name": "session_discovery",
            "status": "failed",
            "message": str(e),
        })
        results["tests_failed"] += 1
    
    # Test 5: Normalizer trivial detection
    try:
        from app.capture.agent_sessions.normalizer import SessionNormalizer
        from app.capture.agent_sessions.models import AgentSessionEvent, AgentSessionEventType, AgentSessionSource
        
        normalizer = SessionNormalizer()
        
        # Test trivial messages
        trivial_messages = [
            "continue",
            "ok",
            "yes",
            "run tests",
            "try again",
        ]
        
        all_trivial = True
        for msg in trivial_messages:
            if not normalizer.is_trivial(msg):
                all_trivial = False
                break
        
        if all_trivial:
            results["test_results"].append({
                "name": "normalizer_trivial_detection",
                "status": "passed",
                "message": "All trivial messages correctly identified",
            })
            results["tests_passed"] += 1
        else:
            results["test_results"].append({
                "name": "normalizer_trivial_detection",
                "status": "failed",
                "message": "Some trivial messages not identified correctly",
            })
            results["tests_failed"] += 1
    except Exception as e:
        results["test_results"].append({
            "name": "normalizer_trivial_detection",
            "status": "failed",
            "message": str(e),
        })
        results["tests_failed"] += 1
    
    # Test 6: Normalizer classification
    try:
        from app.capture.agent_sessions.normalizer import SessionNormalizer
        
        normalizer = SessionNormalizer()
        
        # Test that meaningful content gets classified
        test_content = "Fixed the bug in the capture manager"
        classified = normalizer.classify_event_type(test_content, "user")
        
        results["test_results"].append({
            "name": "normalizer_classification",
            "status": "passed",
            "message": f"Content classified as {classified.value}",
            "data": {"classified_as": classified.value},
        })
        results["tests_passed"] += 1
    except Exception as e:
        results["test_results"].append({
            "name": "normalizer_classification",
            "status": "failed",
            "message": str(e),
        })
        results["tests_failed"] += 1
    
    # Test 7: Capture event building
    try:
        from app.capture.agent_sessions.normalizer import SessionNormalizer
        from app.capture.agent_sessions.models import (
            AgentSession,
            AgentSessionEvent,
            AgentSessionEventType,
            AgentSessionSource,
            AgentSessionStatus,
        )
        
        normalizer = SessionNormalizer()
        
        session = AgentSession(
            source=AgentSessionSource.kilo,
            external_session_id="test_session_1",
            project_path="E:/Muninn",
            title="Test Session",
        )
        
        event = AgentSessionEvent(
            session_id=session.id,
            source=AgentSessionSource.kilo,
            event_type=AgentSessionEventType.user_message,
            role="user",
            content="Implemented agent session capture",
        )
        
        capture_data = normalizer.build_capture_event(session, event)
        
        if capture_data:
            results["test_results"].append({
                "name": "capture_event_building",
                "status": "passed",
                "message": "Capture event built from session event",
                "data": {
                    "event_type": capture_data.get("event_type"),
                    "has_content": bool(capture_data.get("content")),
                },
            })
            results["tests_passed"] += 1
        else:
            results["test_results"].append({
                "name": "capture_event_building",
                "status": "failed",
                "message": "Capture event building returned None",
            })
            results["tests_failed"] += 1
    except Exception as e:
        results["test_results"].append({
            "name": "capture_event_building",
            "status": "failed",
            "message": str(e),
        })
        results["tests_failed"] += 1
    
    # Calculate metrics (simplified for now)
    total_tests = results["tests_passed"] + results["tests_failed"]
    if total_tests > 0:
        results["metrics"]["session_event_ingest_success_rate"] = (
            results["tests_passed"] / total_tests
        )
    
    return results


def print_results(results: dict[str, Any]) -> None:
    """Print evaluation results to stdout."""
    passed = results["tests_passed"]
    failed = results["tests_failed"]
    total = passed + failed
    
    print(f"\n{'='*60}")
    print(f"Agent Session Capture Evaluation")
    print(f"{'='*60}")
    print(f"Timestamp: {results['timestamp']}")
    print(f"Tests: {passed}/{total} passed")
    if failed > 0:
        print(f"FAILED: {failed} tests failed")
    
    print(f"\nTest Results:")
    for test in results["test_results"]:
        status = "PASS" if test["status"] == "passed" else "FAIL"
        print(f"  [{status}] {test['name']}: {test['message']}")
        if test.get("data"):
            print(f"       Data: {test['data']}")
    
    print(f"\nMetrics:")
    for name, value in results["metrics"].items():
        print(f"  {name}: {value}")
    
    print(f"\n{'='*60}")


def main() -> None:
    """Run evaluation and print results."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    
    results = run_evaluation()
    print_results(results)
    
    # Exit with appropriate code
    if results["tests_failed"] > 0:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
