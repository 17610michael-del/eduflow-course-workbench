"""Isolated end-to-end test for optional group assignments."""
from __future__ import annotations

import io
import importlib
import os
import sys
import tempfile
from pathlib import Path


test_root = tempfile.TemporaryDirectory(prefix="eduflow-group-assignment-")
root = Path(test_root.name)
os.environ["SECRET_KEY"] = "group-assignment-test-secret"
os.environ["DATABASE"] = str(root / "app.db")
os.environ["UPLOAD_FOLDER"] = str(root / "uploads")
os.environ["SERVER_SUBMISSION_ROOT"] = str(root / "server-files")
os.environ["ALLOWED_USERS"] = "teacher,leader,member"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

app_module = importlib.import_module(os.environ.get("EDUFLOW_APP_MODULE", "app"))
app = app_module.app
if os.environ.get("EDUFLOW_TEMPLATE_FOLDER"):
    app.template_folder = os.environ["EDUFLOW_TEMPLATE_FOLDER"]
execute = app_module.execute
init_db = app_module.init_db
now_iso = app_module.now_iso
query = app_module.query


def login(client, user_id):
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


with app.app_context():
    init_db(seed=False)
    teacher_id = execute(
        "INSERT INTO users(username,display_name,role,created_at) VALUES (?,?,?,?)",
        ("teacher", "测试老师", "teacher", now_iso()),
    )
    leader_id = execute(
        "INSERT INTO users(username,display_name,role,created_at) VALUES (?,?,?,?)",
        ("leader", "张组长", "student", now_iso()),
    )
    member_id = execute(
        "INSERT INTO users(username,display_name,role,created_at) VALUES (?,?,?,?)",
        ("member", "李组员", "student", now_iso()),
    )
    group_id = execute(
        "INSERT INTO study_groups(name,leader_id,created_by,created_at) VALUES (?,?,?,?)",
        ("协作测试组", leader_id, teacher_id, now_iso()),
    )
    execute("INSERT INTO group_members(group_id,user_id) VALUES (?,?)", (group_id, leader_id))
    execute("INSERT INTO group_members(group_id,user_id) VALUES (?,?)", (group_id, member_id))

with app.test_client() as client:
    login(client, teacher_id)
    form = client.get("/assignments/new")
    html = form.get_data(as_text=True)
    assert form.status_code == 200
    assert "个人作业" in html and "分组大作业" in html
    assert 'value="individual" checked' in html, "individual mode must remain the default"

    individual_created = client.post(
        "/assignments/new",
        data={
            "title": "默认个人作业",
            "description": "每人独立完成。",
            "assignment_mode": "individual",
            "assignees": ["leader", "member"],
        },
    )
    assert individual_created.status_code == 302
    with app.app_context():
        individual = query("SELECT * FROM assignments WHERE title=?", ("默认个人作业",), one=True)
        assert individual["assignment_mode"] == "individual"
        assert query("SELECT 1 FROM assignment_groups WHERE assignment_id=?", (individual["id"],), one=True) is None
        individual_id = individual["id"]

    login(client, member_id)
    personal_submission = client.post(
        f"/assignments/{individual_id}/submit",
        data={"source": "local", "local_file": (io.BytesIO(b"%PDF-1.4\npersonal test"), "personal.pdf")},
        content_type="multipart/form-data",
    )
    assert personal_submission.status_code == 302
    with app.app_context():
        personal_row = query("SELECT * FROM submissions WHERE assignment_id=?", (individual_id,), one=True)
        assert personal_row["student_id"] == member_id and personal_row["group_id"] is None

    login(client, teacher_id)
    created = client.post(
        "/assignments/new",
        data={
            "title": "可选分组大作业",
            "description": "完成小组项目并由组长提交。",
            "assignment_mode": "group",
            "group_ids": str(group_id),
        },
    )
    assert created.status_code == 302

    with app.app_context():
        assignment = query("SELECT * FROM assignments WHERE title=?", ("可选分组大作业",), one=True)
        assert assignment["assignment_mode"] == "group"
        assert set(__import__("json").loads(assignment["assignee_usernames"])) == {"leader", "member"}
        assert query("SELECT group_id FROM assignment_groups WHERE assignment_id=?", (assignment["id"],), one=True)["group_id"] == group_id
        assignment_id = assignment["id"]

    login(client, member_id)
    member_page = client.get(f"/assignments/{assignment_id}")
    assert member_page.status_code == 200
    assert "等待组长提交小组作业" in member_page.get_data(as_text=True)
    denied = client.post(f"/assignments/{assignment_id}/submit", data={})
    assert denied.status_code == 302

    login(client, leader_id)
    submitted = client.post(
        f"/assignments/{assignment_id}/submit",
        data={"source": "local", "local_file": (io.BytesIO(b"%PDF-1.4\nteam test"), "team-result.pdf")},
        content_type="multipart/form-data",
    )
    assert submitted.status_code == 302
    with app.app_context():
        submission = query("SELECT * FROM submissions WHERE assignment_id=?", (assignment_id,), one=True)
        assert submission["group_id"] == group_id and submission["student_id"] == leader_id

    login(client, member_id)
    shared_page = client.get(f"/assignments/{assignment_id}").get_data(as_text=True)
    assert "协作测试组 已提交" in shared_page

    login(client, teacher_id)
    graded = client.post(
        f"/assignments/{assignment_id}/grades/{leader_id}",
        data={"score": "88", "feedback": "小组合作良好"},
    )
    assert graded.status_code == 302
    with app.app_context():
        grades = query("SELECT student_id,score FROM grades WHERE assignment_id=? ORDER BY student_id", (assignment_id,))
        assert {row["student_id"] for row in grades} == {leader_id, member_id}
        assert {row["score"] for row in grades} == {88}

    login(client, member_id)
    graded_page = client.get(f"/assignments/{assignment_id}").get_data(as_text=True)
    assert "88" in graded_page and "小组合作良好" in graded_page

print("OPTIONAL_GROUP_ASSIGNMENT_TEST_OK")
test_root.cleanup()
