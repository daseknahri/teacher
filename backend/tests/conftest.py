import os
import tempfile

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    tmpdir = tempfile.mkdtemp(prefix="teacher_progress_tests_")
    db_path = os.path.join(tmpdir, "test.db")
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["STORAGE_DIR"] = os.path.join(tmpdir, "storage")

    # Import app after env vars are set, so config binds to test paths.
    from app.database import engine
    from app.main import create_app

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
    engine.dispose()
