import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(scope="session")
def tmp_paths():
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(db_fd)
    workspace_dir = tempfile.mkdtemp()
    os.environ["COMPLETE_AI_DB_PATH"] = db_path
    os.environ["COMPLETE_AI_WORKSPACE_ROOT"] = os.path.join(workspace_dir, "workspace")
    os.environ["COMPLETE_AI_SANDBOX_ROOT"] = os.path.join(workspace_dir, "sandboxes")
    yield {"db_path": db_path, "workspace_dir": workspace_dir}
    os.remove(db_path)


@pytest.fixture(scope="session")
def seeded_org(tmp_paths):
    from simulator.organization import generate_organization, persist

    data = generate_organization(seed=4242, workspace_root=os.environ["COMPLETE_AI_WORKSPACE_ROOT"])
    persist(data, os.environ["COMPLETE_AI_WORKSPACE_ROOT"])
    return data


@pytest.fixture
def session(seeded_org):
    from db import SessionLocal

    s = SessionLocal()
    yield s
    s.rollback()
    s.close()


@pytest.fixture
def client(tmp_path, monkeypatch):
    """API tests get their own throwaway database and workspace, never
    shared with the rest of the suite — avoids order-dependent flakiness
    from a task that really commits sandbox/db/ticket-store state."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from models import Base
    from simulator.organization import generate_organization, persist

    db_path = tmp_path / "api_test.db"
    workspace_root = str(tmp_path / "workspace")
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    TestSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    data = generate_organization(seed=555, workspace_root=workspace_root)

    import db as db_module

    monkeypatch.setattr(db_module, "SessionLocal", TestSessionLocal)
    persist(data, workspace_root, drop=False)

    import api.main as api_main

    monkeypatch.setattr(api_main, "SessionLocal", TestSessionLocal)
    monkeypatch.setattr(api_main, "init_db", lambda drop=False: None)
    monkeypatch.setenv("COMPLETE_AI_WORKSPACE_ROOT", workspace_root)
    monkeypatch.setenv("COMPLETE_AI_SANDBOX_ROOT", str(tmp_path / "sandboxes"))

    from fastapi.testclient import TestClient

    return TestClient(api_main.app)
