"""Isolated test for per-instance course branding."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


temporary = tempfile.TemporaryDirectory(prefix="eduflow-course-branding-")
os.environ["SECRET_KEY"] = "course-branding-test-secret"
os.environ["DATABASE"] = str(Path(temporary.name) / "test.db")
os.environ["UPLOAD_FOLDER"] = str(Path(temporary.name) / "uploads")
os.environ["SERVER_SUBMISSION_ROOT"] = str(Path(temporary.name) / "server-files")
os.environ["ALLOWED_USERS"] = "demo_teacher,demo_student"
os.environ["COURSE_NAME"] = "学位+"
os.environ["COURSE_SUBTITLE"] = "193 内网服务器"
os.environ["COURSE_BADGE"] = "CS"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import app, init_db, query  # noqa: E402


with app.app_context():
    init_db()
    teacher = query("SELECT id FROM users WHERE username='demo_teacher'", one=True)

with app.test_client() as client:
    with client.session_transaction() as session:
        session["_user_id"] = str(teacher["id"])
        session["_fresh"] = True
    response = client.get("/")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert '<div class="course-badge">CS</div>' in html
    assert "<strong>学位+</strong>" in html
    assert "<small>193 内网服务器</small>" in html

temporary.cleanup()
print("COURSE_BRANDING_TEST_OK")
