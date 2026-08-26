"""Isolated smoke test for the DeepSeek project workbench (no real API call)."""
from __future__ import annotations

import tempfile
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("SECRET_KEY", "isolated-test-import-secret")

import app as app_module


def main():
    with tempfile.TemporaryDirectory(prefix="eduflow-ds-workbench-") as temporary:
        root = Path(temporary)
        app_module.DATABASE = root / "test.db"
        app_module.app.config.update(
            TESTING=True,
            SECRET_KEY="isolated-test-secret",
            DEEPSEEK_API_KEY="test-only-not-real",
            WORKBENCH_WORKSPACE_BASE=str(root / "data"),
        )
        student_root = root / "data" / "student01"
        project_root = student_root / "demo-project"
        project_root.mkdir(parents=True)
        (project_root / "main.py").write_text("def hello():\n    return 'hello'\n", encoding="utf-8")
        (student_root / ".env").write_text("SECRET=must-not-leak", encoding="utf-8")

        with app_module.app.app_context():
            app_module.init_db(seed=False)
            created = app_module.now_iso()
            student_id = app_module.execute(
                "INSERT INTO users(username,display_name,role,created_at) VALUES (?,?,?,?)",
                ("student01", "测试学生", "student", created),
            )
            other_id = app_module.execute(
                "INSERT INTO users(username,display_name,role,created_at) VALUES (?,?,?,?)",
                ("student02", "其他学生", "student", created),
            )

        client = app_module.app.test_client()
        with client.session_transaction() as session:
            session["_user_id"] = str(student_id)
            session["_fresh"] = True

        page = client.get("/deepseek-workbench")
        assert page.status_code == 200
        html = page.get_data(as_text=True)
        assert "DeepSeek 项目工作台" in html
        assert "Claude" not in html and "Codex" not in html and "Agent" not in html

        listing = client.get("/api/deepseek-workbench/files?path=.")
        assert listing.status_code == 200
        names = [item["name"] for item in listing.get_json()["entries"]]
        assert "demo-project" in names and ".env" not in names
        assert client.get("/api/deepseek-workbench/files?path=../student02").status_code == 400
        preview = client.get("/api/deepseek-workbench/file?path=demo-project/main.py")
        assert preview.status_code == 200 and "def hello" in preview.get_json()["content"]

        created_session = client.post("/api/deepseek-workbench/sessions")
        assert created_session.status_code == 201
        session_id = created_session.get_json()["id"]
        calls = []

        def fake_deepseek(_config, messages, _tools, **_kwargs):
            calls.append(messages)
            if len(calls) == 1:
                return {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": "call_test_1",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": '{"path":"demo-project/main.py"}'},
                    }],
                }
            assert any(item.get("role") == "tool" and "def hello" in item.get("content", "") for item in messages)
            return {"role": "assistant", "content": "入口文件是 `demo-project/main.py`。"}

        original = app_module.deepseek_tool_chat
        app_module.deepseek_tool_chat = fake_deepseek
        try:
            response = client.post(
                f"/api/deepseek-workbench/sessions/{session_id}/messages",
                json={"message": "请分析入口文件"},
            )
        finally:
            app_module.deepseek_tool_chat = original
        assert response.status_code == 200, response.get_data(as_text=True)
        payload = response.get_json()
        assert payload["tool_events"][0]["name"] == "read_file"
        assert "main.py" in payload["reply"]

        with client.session_transaction() as session:
            session["_user_id"] = str(other_id)
            session["_fresh"] = True
        assert client.delete(f"/api/deepseek-workbench/sessions/{session_id}").status_code == 404
        print("DEEPSEEK_WORKBENCH_TEST_OK")


if __name__ == "__main__":
    main()
