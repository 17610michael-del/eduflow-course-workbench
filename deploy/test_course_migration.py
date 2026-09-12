"""Isolated migration test for a populated pre-course EduFlow SQLite database."""
from __future__ import annotations

import importlib
import os
import sqlite3
import sys
import tempfile
import threading
import traceback
import types
from pathlib import Path


temporary = tempfile.TemporaryDirectory(prefix="eduflow-course-migration-")
root = Path(temporary.name)
database = root / "legacy.db"
connection = sqlite3.connect(database)
connection.executescript(
    """
    PRAGMA foreign_keys=ON;
    CREATE TABLE users (
        id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL,
        display_name TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('teacher','student')),
        created_at TEXT NOT NULL, last_login_at TEXT
    );
    CREATE TABLE assignments (
        id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, description TEXT NOT NULL,
        due_date TEXT, attachment_url TEXT, created_by INTEGER NOT NULL REFERENCES users(id),
        status TEXT NOT NULL DEFAULT 'open', created_at TEXT NOT NULL,
        labels TEXT NOT NULL DEFAULT '[]', assignee_usernames TEXT NOT NULL DEFAULT '[]'
    );
    CREATE TABLE study_groups (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,
        leader_id INTEGER NOT NULL REFERENCES users(id), created_by INTEGER NOT NULL REFERENCES users(id),
        created_at TEXT NOT NULL
    );
    CREATE TABLE group_members (
        group_id INTEGER NOT NULL REFERENCES study_groups(id) ON DELETE CASCADE,
        user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
        PRIMARY KEY(group_id,user_id)
    );
    CREATE TABLE drafts (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        draft_type TEXT NOT NULL, context_key TEXT NOT NULL, data TEXT NOT NULL DEFAULT '{}',
        file_url TEXT, file_name TEXT, updated_at TEXT NOT NULL,
        UNIQUE(user_id,draft_type,context_key)
    );
    CREATE TABLE project_agents (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
        token_hash TEXT NOT NULL UNIQUE, workspace_root TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
        agent_version TEXT NOT NULL DEFAULT '', hostname TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL, last_seen_at TEXT
    );
    CREATE TABLE migration_marker(value TEXT NOT NULL);
    CREATE INDEX idx_study_groups_created_custom ON study_groups(created_at);
    CREATE TRIGGER trg_study_groups_custom AFTER INSERT ON study_groups
        BEGIN INSERT INTO migration_marker(value) VALUES (NEW.name); END;
    INSERT INTO users(id,username,display_name,role,created_at) VALUES
        (1,'legacy_teacher','旧老师','teacher','2026-01-01T00:00:00'),
        (2,'legacy_student','旧学生','student','2026-01-01T00:00:00');
    INSERT INTO assignments(id,title,description,created_by,created_at)
        VALUES (11,'旧课程作业','必须保留',1,'2026-01-02T00:00:00');
    INSERT INTO study_groups(id,name,leader_id,created_by,created_at)
        VALUES (12,'旧小组',2,1,'2026-01-02T00:00:00');
    INSERT INTO group_members(group_id,user_id) VALUES (12,2);
    INSERT INTO drafts(id,user_id,draft_type,context_key,data,updated_at)
        VALUES (13,1,'assignment_new','legacy','{}','2026-01-02T00:00:00');
    INSERT INTO project_agents(id,user_id,token_hash,workspace_root,created_at)
        VALUES (14,2,'legacy-token-hash','/data/legacy_student','2026-01-02T00:00:00');
    """
)
connection.close()

os.environ["SECRET_KEY"] = "course-migration-test-secret"
os.environ["DATABASE"] = str(database)
os.environ["UPLOAD_FOLDER"] = str(root / "uploads")
os.environ["SERVER_SUBMISSION_ROOT"] = str(root / "server-files")
os.environ["ALLOWED_USERS"] = "legacy_teacher,legacy_student"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    import pam  # noqa: F401
except ImportError:
    pam_stub = types.ModuleType("pam")
    pam_stub.pam = lambda: None
    sys.modules["pam"] = pam_stub

app_module = importlib.import_module(os.environ.get("EDUFLOW_APP_MODULE", "app"))

errors = []


def initialize():
    try:
        with app_module.app.app_context():
            app_module.init_db(seed=False)
    except Exception:  # pragma: no cover - surfaced by assertion below
        errors.append(traceback.format_exc())


workers = [threading.Thread(target=initialize) for _ in range(2)]
for worker in workers:
    worker.start()
for worker in workers:
    worker.join()
assert not errors, errors

with app_module.app.app_context():
    app_module.init_db(seed=False)
    assert [(row["id"], row["slug"]) for row in app_module.query(
        "SELECT id,slug FROM courses ORDER BY id"
    )] == [(1, "degree"), (2, "bioinformatics"), (3, "bio_undergrad")]
    for table in app_module.COURSE_ROOT_TABLES:
        assert "course_id" in app_module.table_columns(table), table
        assert app_module.query(f"SELECT COUNT(*) n FROM {table} WHERE course_id<>1", one=True)["n"] == 0
    assignment = app_module.query("SELECT * FROM assignments WHERE id=11", one=True)
    assert assignment["title"] == "旧课程作业" and assignment["course_id"] == 1
    assert app_module.query("SELECT course_id FROM study_groups WHERE id=12", one=True)["course_id"] == 1
    assert app_module.query("SELECT course_id FROM group_members WHERE group_id=12", one=True)["course_id"] == 1
    assert app_module.query("SELECT course_id FROM drafts WHERE id=13", one=True)["course_id"] == 1
    assert app_module.query("SELECT course_id FROM project_agents WHERE id=14", one=True)["course_id"] == 1
    degree_members = app_module.query("SELECT COUNT(*) n FROM course_memberships WHERE course_id=1", one=True)["n"]
    assert degree_members == 2
    assert app_module.query(
        "SELECT role FROM course_memberships WHERE course_id=2 AND user_id=1", one=True
    )["role"] == "teacher"
    assert app_module.query("PRAGMA foreign_key_check") == []
    assert app_module.query(
        "SELECT 1 ok FROM sqlite_master WHERE type='index' AND name='idx_study_groups_created_custom'",
        one=True,
    )
    assert app_module.query(
        "SELECT 1 ok FROM sqlite_master WHERE type='trigger' AND name='trg_study_groups_custom'",
        one=True,
    )

temporary.cleanup()
print("COURSE_MIGRATION_TEST_OK")
