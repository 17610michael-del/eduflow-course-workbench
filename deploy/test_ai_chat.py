"""Read-only smoke test for the standalone AI conversation workspace."""
from app import app, query, table_columns
from subsystems.ai import services


with app.app_context():
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
