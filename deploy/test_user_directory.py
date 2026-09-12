"""Isolated smoke test for the all-role course user directory."""
import os
import sys
import tempfile
from pathlib import Path


temporary = tempfile.TemporaryDirectory(prefix="eduflow-user-directory-")
os.environ["SECRET_KEY"] = "user-directory-test-secret"
os.environ["DATABASE"] = os.path.join(temporary.name, "test.db")
os.environ["UPLOAD_FOLDER"] = os.path.join(temporary.name, "uploads")
os.environ["SERVER_SUBMISSION_ROOT"] = os.path.join(temporary.name, "server-files")
os.environ["ALLOWED_USERS"] = "demo_teacher,demo_student"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import app, init_db, query  # noqa: E402


def check(label, condition, detail=""):
    if not condition:
        raise AssertionError(f"{label}: {detail}")
    print(f"PASS {label}: {detail}")


with app.app_context():
    init_db()
    users = [dict(row) for row in query("SELECT id,username,display_name,role FROM users ORDER BY id")]
    check("users available", bool(users), f"{len(users)} account(s)")
    first_user = users[0]

with app.test_client() as client:
    with client.session_transaction() as session:
        session["_user_id"] = str(first_user["id"])
        session["_fresh"] = True

    directory = client.get("/users")
    directory_html = directory.get_data(as_text=True)
    check("directory route", directory.status_code == 200, "HTTP 200")
    check("all roles represented", all(label in directory_html for label in ("老师", "助教", "学生")), "role sections rendered")
    check("known users rendered", all(user["display_name"] in directory_html for user in users), "all database users visible")

    home_html = client.get("/").get_data(as_text=True)
    check("dashboard link", 'href="/users"' in home_html and "老师 · 助教 · 学生" in home_html, "participant card opens all users")
    check("student directory preserved", client.get("/students").status_code == 200, "HTTP 200")

print("USER_DIRECTORY_TEST_OK")
temporary.cleanup()
