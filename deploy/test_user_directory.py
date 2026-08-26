"""Read-only smoke test for the all-role course user directory."""
from app import app, query


def check(label, condition, detail=""):
    if not condition:
        raise AssertionError(f"{label}: {detail}")
    print(f"PASS {label}: {detail}")


with app.app_context():
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
