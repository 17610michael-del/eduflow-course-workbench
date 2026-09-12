"""Exercise the guarded SQLite reset against a temporary three-course database only."""
from __future__ import annotations

import importlib
import os
import sqlite3
import subprocess
import sys
import tempfile
import types
from pathlib import Path


temporary = tempfile.TemporaryDirectory(prefix="eduflow-reset-test-")
root = Path(temporary.name)
database = root / "app.db"
backup = root / "backup.db"
os.environ.update({
    "SECRET_KEY": "reset-test-secret",
    "DATABASE": str(database),
    "UPLOAD_FOLDER": str(root / "uploads"),
    "SERVER_SUBMISSION_ROOT": str(root / "server-files"),
    "ALLOWED_USERS": "kltst,wsst",
    "TEACHERS": "wsst",
    "ASSISTANTS": "kltst",
    "DEGREE_USERS": "",
    "BIOINFORMATICS_USERS": "",
    "BIOINFORMATICS_ASSISTANTS": "",
    "BIO_UNDERGRAD_USERS": "",
    "BIO_UNDERGRAD_ASSISTANTS": "",
    "COURSE_ONLY_SLUG": "",
})
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    import pam  # noqa: F401
except ImportError:
    pam_stub = types.ModuleType("pam")
    pam_stub.pam = lambda: None
    sys.modules["pam"] = pam_stub

app_module = importlib.import_module("app")
with app_module.app.app_context():
    app_module.init_db(seed=False)
    app_module.execute(
        "INSERT INTO users(username,display_name,role,created_at) VALUES ('kltst','旧助教','assistant',?)",
        (app_module.now_iso(),),
    )

script = Path(__file__).with_name("reset-eduflow-production.py")
dry_run = subprocess.run(
    [sys.executable, str(script), "--database", str(database), "--backup", str(backup)],
    check=True, capture_output=True, text=True,
)
assert "RESET_DATABASE_DRY_RUN" in dry_run.stdout
assert not backup.exists()

applied = subprocess.run(
    [sys.executable, str(script), "--database", str(database), "--backup", str(backup), "--apply"],
    check=True, capture_output=True, text=True,
)
assert "RESET_DATABASE_OK users=2 courses=3 memberships=6 business_rows=0" in applied.stdout
assert backup.is_file()

connection = sqlite3.connect(database)
try:
    assert connection.execute("SELECT COUNT(*) FROM courses").fetchone()[0] == 3
    assert connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 2
    assert connection.execute("SELECT COUNT(*) FROM course_memberships").fetchone()[0] == 6
    assert connection.execute("SELECT COUNT(*) FROM survey_responses").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM survey_analyses").fetchone()[0] == 0
finally:
    connection.close()

temporary.cleanup()
print("PRODUCTION_RESET_TEST_OK")
