"""Isolated integration test for the local project monitor."""
from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone


temporary = tempfile.TemporaryDirectory(prefix="eduflow-project-test-")
os.environ["DATABASE"] = os.path.join(temporary.name, "test.db")
os.environ["UPLOAD_FOLDER"] = os.path.join(temporary.name, "uploads")
os.environ["SERVER_SUBMISSION_ROOT"] = os.path.join(temporary.name, "server-files")

from app import app, execute, init_db, query  # noqa: E402


with app.app_context():
    init_db()
    teacher = query("SELECT id FROM users WHERE role='teacher' ORDER BY id LIMIT 1", one=True)
    student = query("SELECT id,username FROM users WHERE role='student' ORDER BY id LIMIT 1", one=True)
    other_id = execute(
        "INSERT INTO users(username,display_name,role,created_at) VALUES (?,?,?,?)",
        ("other_student", "其他学生", "student", datetime.now().isoformat()),
    )

with app.test_client() as client:
    with client.session_transaction() as session:
        session["_user_id"] = str(student["id"])
        session["_fresh"] = True

    assert client.post(f"/api/project-agents/{student['username']}/token", json={}).status_code == 403
    assert client.post("/api/project-agents/other_student/token", json={}).status_code == 403

    with client.session_transaction() as session:
        session["_user_id"] = str(teacher["id"])
        session["_fresh"] = True

    token_response = client.post(f"/api/project-agents/{student['username']}/token", json={})
    assert token_response.status_code == 200, token_response.get_data(as_text=True)
    token = token_response.json["token"]
    assert token.startswith("epm_")
    repeat_response = client.post(f"/api/project-agents/{student['username']}/token", json={})
    assert repeat_response.status_code == 200
    assert repeat_response.json["token"] == token
    empty_token_response = client.post("/api/project-agents/other_student/token", json={})
    assert empty_token_response.status_code == 200
    empty_token = empty_token_response.json["token"]

    with client.session_transaction() as session:
        session["_user_id"] = str(student["id"])
        session["_fresh"] = True

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    report = {
        "agent_version": "test",
        "hostname": "test-host",
        "workspace": f"/data/{student['username']}",
        "captured_at": now,
        "projects": [{
            "name": "safe-project",
            "path": "safe-project",
            "last_modified": now,
            "file_count": 12,
            "total_size": 2048,
            "running_processes": 1,
            "git": {"is_repository": True, "branch": "main", "commit": "abc123", "changed_files": 2},
            "manifest": {"status": "数据分析", "progress": 45, "updated": now},
        }],
        "processes": [{"pid": 123, "name": "python3", "project": "safe-project"}],
        "disk": {"total": 10000, "used": 4000, "free": 6000},
    }
    assert client.post("/api/project-agent/report", json=report).status_code == 401
    accepted = client.post(
        "/api/project-agent/report", json=report,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert accepted.status_code == 200, accepted.get_data(as_text=True)
    empty_report = dict(report)
    empty_report["workspace"] = "/data/other_student"
    empty_report["projects"] = []
    assert client.post(
        "/api/project-agent/report", json=empty_report,
        headers={"Authorization": f"Bearer {empty_token}"},
    ).status_code == 200

    student_page = client.get("/projects")
    student_html = student_page.get_data(as_text=True)
    assert student_page.status_code == 200
    assert "safe-project" in student_html
    assert "其他学生" not in student_html
    assert 'name="ai_provider"' not in student_html
    assert 'name="model"' not in student_html
    assert 'name="api_key"' not in student_html

    with app.app_context():
        agent = query("SELECT token_hash,last_seen_at FROM project_agents WHERE user_id=?", (student["id"],), one=True)
        assert agent is not None and len(agent["token_hash"]) == 64
        assert token not in agent["token_hash"]
        assert query("SELECT COUNT(*) n FROM project_snapshots", one=True)["n"] == 2

    with client.session_transaction() as session:
        session["_user_id"] = str(teacher["id"])
        session["_fresh"] = True
    teacher_page = client.get("/projects")
    teacher_html = teacher_page.get_data(as_text=True)
    assert teacher_page.status_code == 200
    assert "safe-project" in teacher_html and "其他学生" in teacher_html
    assert "Agent 正常，暂无项目" in teacher_html
    assert 'name="ai_provider"' not in teacher_html
    assert 'name="model"' not in teacher_html
    assert 'name="api_key"' not in teacher_html

temporary.cleanup()
print("PROJECT_MONITOR_TEST_OK")
