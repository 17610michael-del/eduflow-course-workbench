"""Verify single-course locking, explicit assistants, and per-port cookie names."""
from __future__ import annotations

import importlib
import os
import sys
import tempfile
import types
from pathlib import Path


temporary = tempfile.TemporaryDirectory(prefix="eduflow-single-course-")
root = Path(temporary.name)
os.environ.update({
    "SECRET_KEY": "single-course-test-secret",
    "DATABASE": str(root / "bio.db"),
    "UPLOAD_FOLDER": str(root / "uploads"),
    "SERVER_SUBMISSION_ROOT": str(root / "server-files"),
    "ALLOWED_USERS": "wsst,kltst",
    "TEACHERS": "wsst",
    "ASSISTANTS": "kltst",
    "DEGREE_USERS": "",
    "BIOINFORMATICS_USERS": "",
    "BIOINFORMATICS_ASSISTANTS": "kltst",
    "COURSE_ONLY_SLUG": "bioinformatics",
    "SESSION_COOKIE_NAME": "eduflow_bio_session",
    "REMEMBER_COOKIE_NAME": "eduflow_bio_remember",
    "LOGIN_HINT_COOKIE_PREFIX": "bio_",
})
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    import pam  # noqa: F401
except ImportError:
    pam_stub = types.ModuleType("pam")
    pam_stub.pam = lambda: None
    sys.modules["pam"] = pam_stub

app_module = importlib.import_module("app")
app = app_module.app

with app.app_context():
    app_module.init_db(seed=False)
    stamp = app_module.now_iso()
    wsst_id = app_module.execute(
        "INSERT INTO users(username,display_name,role,created_at) VALUES ('wsst','wsst','teacher',?)", (stamp,)
    )
    kltst_id = app_module.execute(
        "INSERT INTO users(username,display_name,role,created_at) VALUES ('kltst','kltst','assistant',?)", (stamp,)
    )
    app_module.sync_configured_course_memberships()
    assert app_module.role_for_linux_user("wsst") == "teacher"
    assert app_module.role_for_linux_user("kltst") == "assistant"
    assert app_module.query(
        "SELECT role FROM course_memberships WHERE course_id=2 AND user_id=?", (kltst_id,), one=True
    )["role"] == "assistant"
    outsider_id = app_module.execute(
        "INSERT INTO users(username,display_name,role,created_at) VALUES ('outsider','outsider','teacher',?)", (stamp,)
    )
    app_module.execute(
        "INSERT INTO course_memberships(course_id,user_id,role,created_at) VALUES (2,?,'teacher',?)",
        (outsider_id, stamp),
    )
    app_module.sync_configured_course_memberships()
    assert app_module.query(
        "SELECT 1 FROM course_memberships WHERE course_id=2 AND user_id=?", (outsider_id,), one=True
    ) is None

assert app.config["SESSION_COOKIE_NAME"] == "eduflow_bio_session"
assert app.config["REMEMBER_COOKIE_NAME"] == "eduflow_bio_remember"
with app.test_client() as client:
    with client.session_transaction() as browser_session:
        browser_session["_user_id"] = str(wsst_id)
        browser_session["_fresh"] = True
        browser_session["course_slug"] = "degree"
    response = client.get("/")
    assert response.status_code == 200
    with client.session_transaction() as browser_session:
        assert browser_session["course_slug"] == "bioinformatics"
    assert client.post("/courses/switch", data={"course": "degree"}).status_code == 403

temporary.cleanup()

# Second pass: the undergraduate instance locks onto course 3.
temporary = tempfile.TemporaryDirectory(prefix="eduflow-single-course-ug-")
root = Path(temporary.name)
os.environ.update({
    "DATABASE": str(root / "bio_u.db"),
    "UPLOAD_FOLDER": str(root / "uploads"),
    "SERVER_SUBMISSION_ROOT": str(root / "server-files"),
    "COURSE_ONLY_SLUG": "bio_undergrad",
    "BIO_UNDERGRAD_USERS": "student_u",
    "BIO_UNDERGRAD_ASSISTANTS": "kltst",
    "ALLOWED_USERS": "wsst,kltst,student_u",
})
import config as config_module  # noqa: E402
importlib.reload(config_module)
app_module.app.config.from_object(config_module.Config)
with app_module.app.app_context():
    app_module.init_db(seed=False)
    stamp = app_module.now_iso()
    app_module.execute(
        "INSERT INTO users(username,display_name,role,created_at) VALUES ('student_u','student_u','student',?)", (stamp,)
    )
    app_module.sync_configured_course_memberships()
    row = app_module.query(
        "SELECT role FROM course_memberships WHERE course_id=3 AND user_id=(SELECT id FROM users WHERE username='student_u')",
        one=True,
    )
    assert row["role"] == "student"
    assert app_module.query(
        "SELECT slug,name FROM courses WHERE id=3", one=True
    )["slug"] == "bio_undergrad"
temporary.cleanup()

print("SINGLE_COURSE_INSTANCE_TEST_OK")
