"""Regression test: capture evaluation must use isolated DB, not production."""

import inspect

from app.capture.evaluate import run_evaluation


def test_capture_evaluation_isolated_db_pattern():
    """
    Architectural test: verify that run_evaluation creates its own engine/session.
    
    This is a regression test for the bug where app.capture.evaluate
    was using the production data/munin.db instead of an isolated
    temporary database, leaving test_repo entries in the real registry.
    """
    source = inspect.getsource(run_evaluation)
    
    # Should NOT reference SessionLocal from app.database
    assert "from app.database import SessionLocal" not in source, (
        "Evaluation still imports SessionLocal from app.database"
    )
    assert "SessionLocal()" not in source, (
        "Evaluation still uses SessionLocal() directly"
    )
    
    # Should NOT use the global engine from app.database
    assert "from app.database import Base, engine" not in source, (
        "Evaluation imports global engine from app.database"
    )
    assert "from app.database import SessionLocal, Base, engine" not in source, (
        "Evaluation imports SessionLocal and engine from app.database"
    )
    
    # Should create isolated engine
    assert "eval_engine" in source or "_eval_engine" in source, (
        "Evaluation doesn't create isolated engine"
    )
    assert "eval.db" in source or "eval_dir" in source, (
        "Evaluation doesn't create temporary DB file"
    )
    
    # Should create dedicated sessionmaker
    assert "EvalSession" in source or "TestSession" in source, (
        "Evaluation doesn't create dedicated sessionmaker"
    )
    
    # Should use create_db_engine
    assert "create_db_engine" in source, (
        "Evaluation doesn't use create_db_engine for isolation"
    )
    
    # Should use tempfile.mkdtemp
    assert "mkdtemp" in source, (
        "Evaluation doesn't create temporary directory"
    )
    
    # Should create all tables on the isolated engine
    assert "Base.metadata.create_all" in source, (
        "Evaluation doesn't create tables on isolated engine"
    )
