"""Isolated smoke test for the standalone AI conversation workspace."""
import os
import sys
import tempfile
from pathlib import Path


temporary = tempfile.TemporaryDirectory(prefix="eduflow-ai-chat-")
os.environ["SECRET_KEY"] = "ai-chat-test-secret"
os.environ["DATABASE"] = os.path.join(temporary.name, "test.db")
os.environ["UPLOAD_FOLDER"] = os.path.join(temporary.name, "uploads")
os.environ["SERVER_SUBMISSION_ROOT"] = os.path.join(temporary.name, "server-files")
os.environ["ALLOWED_USERS"] = "demo_teacher,demo_student"
os.environ["DEEPSEEK_API_KEY"] = "test-only-not-real"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import app, init_db, query, table_columns  # noqa: E402
from subsystems.ai import services


with app.app_context():
    init_db()
    user = query("SELECT id FROM users ORDER BY id LIMIT 1", one=True)
    assert user is not None, "at least one user account is required"

with app.test_client() as client:
    with client.session_transaction() as session:
        session["_user_id"] = str(user["id"])
        session["_fresh"] = True

    response = client.get("/ai-chat")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'data-ai-chat-form' in html
    assert 'href="/ai-chat"' in html
    assert "DeepSeek 工作台" in html and "DeepSeek API 直连" in html
    assert "Claude" not in html and "Codex" not in html and "Agent" not in html

with app.app_context():
    assert {"user_id", "message", "reply", "created_at"} <= table_columns("ai_chat_logs")

captured = {}
original = services.deepseek_chat
try:
    services.deepseek_chat = lambda _config, messages, **_kwargs: captured.setdefault("messages", messages) and "测试回复"
    reply = services.course_chat_assistant(
        {},
        "继续说明",
        [{"role": "user", "content": "上一问"}, {"role": "assistant", "content": "上一答"}],
    )
    assert reply == "测试回复"
    assert [item["role"] for item in captured["messages"][-3:]] == ["user", "assistant", "user"]
finally:
    services.deepseek_chat = original

print("AI_CHAT_TEST_OK")
temporary.cleanup()
