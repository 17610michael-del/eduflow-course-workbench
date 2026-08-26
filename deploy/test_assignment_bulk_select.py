"""Read-only smoke test for bulk assignment recipient controls."""
from app import app, query


with app.app_context():
    teacher = query("SELECT id FROM users WHERE role='teacher' ORDER BY id LIMIT 1", one=True)
    assert teacher is not None, "teacher account required"

with app.test_client() as client:
    with client.session_transaction() as session:
        session["_user_id"] = str(teacher["id"])
        session["_fresh"] = True

    response = client.get("/assignments/new")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'data-select-label="全选学生"' in html
    assert 'data-select-label="全选老师 / 助教"' in html
    assert 'data-select-label="全选小组"' in html
    assert html.count("data-toggle-checks") == 3

print("ASSIGNMENT_BULK_SELECT_TEST_OK")
