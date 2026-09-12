"""Isolated request and data isolation test for EduFlow multi-course mode."""
from __future__ import annotations

import importlib
import os
import sys
import tempfile
import types
from pathlib import Path


temporary = tempfile.TemporaryDirectory(prefix="eduflow-multicourse-")
root = Path(temporary.name)
os.environ["SECRET_KEY"] = "multicourse-isolation-test-secret"
os.environ["DATABASE"] = str(root / "app.db")
os.environ["UPLOAD_FOLDER"] = str(root / "uploads")
os.environ["SERVER_SUBMISSION_ROOT"] = str(root / "server-files")
os.environ["ALLOWED_USERS"] = "staff,student,degree_only,bio_only,global_teacher"
os.environ["TEACHERS"] = "global_teacher"
os.environ["DEGREE_USERS"] = "staff,student,degree_only"
os.environ["BIOINFORMATICS_USERS"] = "student,bio_only"
os.environ["BIOINFORMATICS_ASSISTANTS"] = "staff"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    import pam  # noqa: F401
except ImportError:
    pam_stub = types.ModuleType("pam")
    pam_stub.pam = lambda: None
    sys.modules["pam"] = pam_stub

app_module = importlib.import_module(os.environ.get("EDUFLOW_APP_MODULE", "app"))
app = app_module.app
execute = app_module.execute
query = app_module.query
now_iso = app_module.now_iso


def login(client, user_id, course="degree"):
    with client.session_transaction() as browser_session:
        browser_session["_user_id"] = str(user_id)
        browser_session["_fresh"] = True
        browser_session["course_slug"] = course


with app.app_context():
    app_module.init_db(seed=False)
    staff_id = execute(
        "INSERT INTO users(username,display_name,role,created_at) VALUES (?,?,?,?)",
        ("staff", "课程人员", "assistant", now_iso()),
    )
    student_id = execute(
        "INSERT INTO users(username,display_name,role,created_at) VALUES (?,?,?,?)",
        ("student", "双课学生", "student", now_iso()),
    )
    degree_only_id = execute(
        "INSERT INTO users(username,display_name,role,created_at) VALUES (?,?,?,?)",
        ("degree_only", "学位学生", "student", now_iso()),
    )
    global_teacher_id = execute(
        "INSERT INTO users(username,display_name,role,created_at) VALUES (?,?,?,?)",
        ("global_teacher", "全局老师", "teacher", now_iso()),
    )
    bio_only_id = execute(
        "INSERT INTO users(username,display_name,role,created_at) VALUES (?,?,?,?)",
        ("bio_only", "生信学生", "student", now_iso()),
    )
    app_module.sync_configured_course_memberships()
    execute("UPDATE course_memberships SET role='teacher' WHERE course_id=1 AND user_id=?", (staff_id,))
    assert query("SELECT role FROM course_memberships WHERE course_id=2 AND user_id=?", (staff_id,), one=True)["role"] == "assistant"
    assert query("SELECT role FROM course_memberships WHERE course_id=2 AND user_id=?", (student_id,), one=True)["role"] == "student"
    assert query("SELECT role FROM course_memberships WHERE course_id=2 AND user_id=?", (global_teacher_id,), one=True)["role"] == "teacher"
    assert query("SELECT 1 FROM course_memberships WHERE course_id=1 AND user_id=?", (bio_only_id,), one=True) is None

    degree_assignment = execute(
        """INSERT INTO assignments(course_id,title,description,created_by,status,created_at)
           VALUES (1,'学位作业','degree',?,'open',?)""", (staff_id, now_iso()),
    )
    bio_assignment = execute(
        """INSERT INTO assignments(course_id,title,description,created_by,status,created_at)
           VALUES (2,'生信作业','bio',?,'open',?)""", (staff_id, now_iso()),
    )
    degree_exam = execute(
        """INSERT INTO exams(course_id,title,category,mode,start_at,end_at,created_by,created_at)
           VALUES (1,'学位考试','quiz','computer','2026-01-01','2027-01-01',?,?)""", (staff_id, now_iso()),
    )
    bio_exam = execute(
        """INSERT INTO exams(course_id,title,category,mode,start_at,end_at,created_by,created_at)
           VALUES (2,'生信考试','quiz','computer','2026-01-01','2027-01-01',?,?)""", (staff_id, now_iso()),
    )
    degree_file = root / "uploads" / "degree.txt"
    bio_file = root / "uploads" / "bio.txt"
    degree_file.parent.mkdir(parents=True, exist_ok=True)
    degree_file.write_text("degree", encoding="utf-8")
    bio_file.write_text("bio", encoding="utf-8")
    degree_document = execute(
        """INSERT INTO knowledge_documents(course_id,user_id,original_name,stored_path,status,created_by,created_at,updated_at)
           VALUES (1,?,'degree.txt','degree.txt','ready',?,?,?)""", (student_id, staff_id, now_iso(), now_iso()),
    )
    bio_document = execute(
        """INSERT INTO knowledge_documents(course_id,user_id,original_name,stored_path,status,created_by,created_at,updated_at)
           VALUES (2,?,'bio.txt','bio.txt','ready',?,?,?)""", (student_id, staff_id, now_iso(), now_iso()),
    )
    degree_discussion = execute(
        "INSERT INTO discussions(assignment_id,user_id,content,created_at) VALUES (?,?,?,?)",
        (degree_assignment, staff_id, "degree comment", now_iso()),
    )
    bio_discussion = execute(
        "INSERT INTO discussions(assignment_id,user_id,content,created_at) VALUES (?,?,?,?)",
        (bio_assignment, staff_id, "bio comment", now_iso()),
    )
    legacy_attachment = root / "uploads" / "legacy-degree.pdf"
    legacy_attachment.write_bytes(b"degree-only")
    execute("INSERT INTO ai_chat_logs(course_id,user_id,message,reply,created_at) VALUES (1,?,'degree history','ok',?)", (staff_id, now_iso()))
    execute("INSERT INTO ai_chat_logs(course_id,user_id,message,reply,created_at) VALUES (2,?,'bio history','ok',?)", (staff_id, now_iso()))
    execute("""INSERT INTO deepseek_workbench_sessions(course_id,user_id,title,workspace_root,created_at,updated_at)
             VALUES (1,?,'degree session','/tmp',?,?)""", (staff_id, now_iso(), now_iso()))
    execute("""INSERT INTO deepseek_workbench_sessions(course_id,user_id,title,workspace_root,created_at,updated_at)
             VALUES (2,?,'bio session','/tmp',?,?)""", (staff_id, now_iso(), now_iso()))
    degree_token, degree_token_hash = app_module.issue_agent_token(
        "student", app.config["PROJECT_AGENT_TOKEN_SECRET"], scope="degree"
    )
    bio_token, bio_token_hash = app_module.issue_agent_token(
        "student", app.config["PROJECT_AGENT_TOKEN_SECRET"], scope="bioinformatics"
    )
    degree_agent = execute(
        """INSERT INTO project_agents(course_id,user_id,token_hash,workspace_root,created_at)
           VALUES (1,?,?,?,?)""", (student_id, degree_token_hash, "/data/student", now_iso()),
    )
    bio_agent = execute(
        """INSERT INTO project_agents(course_id,user_id,token_hash,workspace_root,created_at)
           VALUES (2,?,?,?,?)""", (student_id, bio_token_hash, "/data/student", now_iso()),
    )
    assert degree_token != bio_token and degree_agent != bio_agent

    degree_group = execute(
        "INSERT INTO study_groups(course_id,name,leader_id,created_by,created_at) VALUES (1,'同名组',?,?,?)",
        (student_id, staff_id, now_iso()),
    )
    bio_group = execute(
        "INSERT INTO study_groups(course_id,name,leader_id,created_by,created_at) VALUES (2,'同名组',?,?,?)",
        (student_id, staff_id, now_iso()),
    )
    execute("INSERT INTO group_members(group_id,user_id,course_id) VALUES (?,?,1)", (degree_group, student_id))
    execute("INSERT INTO group_members(group_id,user_id,course_id) VALUES (?,?,2)", (bio_group, student_id))
    assert query("PRAGMA foreign_key_check") == []

with app.test_client() as client:
    login(client, staff_id)
    me = client.get("/api/auth/me").get_json()
    assert me["role"] == "teacher" and me["course"]["slug"] == "degree"
    assignments = client.get("/assignments").get_data(as_text=True)
    assert "学位作业" in assignments and "生信作业" not in assignments
    exams = client.get("/exams").get_data(as_text=True)
    assert "学位考试" in exams and "生信考试" not in exams
    ai_history = client.get("/ai-chat").get_data(as_text=True)
    assert "degree history" in ai_history and "bio history" not in ai_history
    deepseek_history = client.get("/deepseek-workbench").get_data(as_text=True)
    assert "degree session" in deepseek_history and "bio session" not in deepseek_history
    assert client.get(f"/assignments/{bio_assignment}").status_code == 404
    assert client.get(f"/api/assignments/{bio_assignment}").status_code == 404
    assert client.get(f"/exams/{bio_exam}/submissions").status_code == 404
    assert client.get(f"/knowledge/documents/{bio_document}/download").status_code == 404
    assert client.get(f"/knowledge/documents/{degree_document}/download").status_code == 200
    assert client.get("/uploads/courses/bioinformatics/tasks/hidden.pdf").status_code == 404
    assert client.post(f"/api/assignments/{bio_assignment}/discussions", json={"content": "blocked"}).status_code == 404
    assert client.post(f"/assignments/{bio_assignment}/delete").status_code == 404
    invalid_parent = client.post(
        f"/api/assignments/{degree_assignment}/discussions",
        json={"content": "blocked parent", "parent_id": bio_discussion},
    )
    assert invalid_parent.status_code == 400

    report = client.post(
        "/api/project-agent/report",
        headers={"Authorization": f"Bearer {bio_token}"},
        json={"workspace": "/data/student", "projects": [], "captured_at": now_iso()},
    )
    assert report.status_code == 200
    with app.app_context():
        snapshot = query("SELECT agent_id FROM project_snapshots ORDER BY id DESC LIMIT 1", one=True)
        assert snapshot["agent_id"] == bio_agent

    switched = client.post("/courses/switch", data={"course": "bioinformatics"})
    assert switched.status_code == 302
    me = client.get("/api/auth/me").get_json()
    assert me["role"] == "assistant" and me["course"]["slug"] == "bioinformatics"
    assignments = client.get("/assignments").get_data(as_text=True)
    assert "生信作业" in assignments and "学位作业" not in assignments
    ai_history = client.get("/ai-chat").get_data(as_text=True)
    assert "bio history" in ai_history and "degree history" not in ai_history
    assert client.get(f"/assignments/{degree_assignment}").status_code == 404
    assert client.get(f"/exams/{degree_exam}/submissions").status_code == 404
    assert client.get(f"/knowledge/documents/{degree_document}/download").status_code == 404
    assert client.get("/uploads/legacy-degree.pdf").status_code == 404
    with app.app_context():
        assert query("SELECT id FROM assignments WHERE id=?", (degree_assignment,), one=True)
        assert query("SELECT id FROM assignments WHERE id=?", (bio_assignment,), one=True)

    login(client, degree_only_id)
    assert client.post("/courses/switch", data={"course": "bioinformatics"}).status_code == 403

    login(client, bio_only_id, course="bioinformatics")
    assert client.post("/courses/switch", data={"course": "degree"}).status_code == 403

with app.app_context():
    app.config["BIOINFORMATICS_USERS"] = {"student"}
    app_module.sync_configured_course_memberships()
    assert query("SELECT 1 FROM course_memberships WHERE course_id=2 AND user_id=?", (bio_only_id,), one=True) is None

temporary.cleanup()
print("MULTICOURSE_ISOLATION_TEST_OK")
