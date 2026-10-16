"""Keep all pytest database writes away from the project's runtime SQLite file."""
import os
import shutil
import tempfile
from pathlib import Path

_test_dir = Path(tempfile.mkdtemp(prefix="ai-panel-tests-"))
os.environ["DATABASE_URL"] = "sqlite:///" + (_test_dir / "test.db").as_posix()

def pytest_unconfigure():
    shutil.rmtree(_test_dir, ignore_errors=True)
