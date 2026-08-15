"""Read-mostly production permission smoke test for the student role."""
from app import app, get_db, query, role_for_linux_user


def check(label, condition, detail=""):
    if not condition:
        raise AssertionError(f"{label}: {detail}")
    print(f"PASS {label}: {detail}")


with app.app_context():
    check("linux role classification", role_for_linux_user("example_student") == "student", "example_student -> student")
    student = query("SELECT * FROM users WHERE username='demo_student'", one=True)
    check("seeded student available", student is not None, "demo_student")
    student_id = student["id"]

with app.test_client() as client:
    with client.session_transaction() as session:
        session["_user_id"] = str(student_id)
        session["_fresh"] = True

    response = client.get("/api/auth/me")
    check("student session", response.status_code == 200 and response.json["role"] == "student", str(response.json))
    check("view assignments page", client.get("/assignments").status_code == 200, "HTTP 200")
    home_html = client.get("/").get_data(as_text=True)
    check("student dashboard hides teacher metrics", "待我审阅" not in home_html and "我发布的" not in home_html, "teacher-only cards absent")
    check("student dashboard shows own metrics", "我的提交" in home_html and "我的互动" in home_html, "student cards present")
    check("student dashboard cards link to filters", "view=submitted" in home_html and "view=assigned" in home_html and "view=interactions" in home_html, "all student cards clickable")
    check("submitted filter works", client.get("/assignments?view=submitted").status_code == 200, "HTTP 200")
    check("interaction filter works", client.get("/assignments?view=interactions").status_code == 200, "HTTP 200")
    check("read assignments API", client.get("/api/assignments").status_code == 200, "HTTP 200")
    check("view assignment detail", client.get("/assignments/1").status_code == 200, "HTTP 200")
    check("view shared student directory", client.get("/students").status_code == 200, "HTTP 200")
    check("read shared student API", client.get("/api/students").status_code == 200, "HTTP 200")
    check("cannot create assignment", client.post("/api/assignments", json={"title": "x", "description": "x"}).status_code == 403, "HTTP 403")
    analytics_page = client.get("/analytics")
    check("can view own analytics", analytics_page.status_code == 200, "HTTP 200")
    own_report = client.post("/api/analyze", json={"username": "teacher01"})
    check("analytics forced to self", own_report.status_code == 200 and own_report.json["username"] == "demo_student", "requested teacher but received own report")
    check("cannot close assignment", client.post("/assignments/1/close").status_code == 302, "redirected with teacher-only warning")
    detail_html = client.get("/assignments/1").get_data(as_text=True)
    check("student submission button visible", "提交作业" in detail_html, "local/server submission modal present")
    submission = client.post("/api/assignments/1/submissions", data={})
    check("submission endpoint accepts student role", submission.status_code == 400 and submission.json["error"] == "file_required", "student passed role check; file required")

print("STUDENT_ROLE_TEST_OK")
