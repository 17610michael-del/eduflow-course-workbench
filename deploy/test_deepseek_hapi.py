"""Isolated test for the standalone DeepSeek-only HAPI-style workbench."""
from __future__ import annotations

import importlib
import os
import sqlite3
import sys
import tempfile
from pathlib import Path


def main():
    with tempfile.TemporaryDirectory(prefix="deepseek-hapi-test-") as temporary:
        root = Path(temporary)
        course_db = root / "course.db"
        workbench_db = root / "workbench.db"
        workspace = root / "data" / "student01"
        project = workspace / "test-project"
        project.mkdir(parents=True)
        (project / "main.py").write_text("print('deepseek')\n", encoding="utf-8")
        (workspace / ".env").write_text("SECRET=hidden", encoding="utf-8")
        database = sqlite3.connect(course_db)
        database.execute(
            "CREATE TABLE users(id INTEGER PRIMARY KEY,username TEXT,display_name TEXT,role TEXT)"
        )
        database.execute(
            "INSERT INTO users VALUES (1,'student01','测试学生','student')"
        )
        database.execute(
            "INSERT INTO users VALUES (2,'student02','其他学生','student')"
        )
        database.commit()
        database.close()

        os.environ.update({
            "SECRET_KEY": "standalone-test-secret",
            "DATABASE": str(course_db),
            "DEEPSEEK_HAPI_DATABASE": str(workbench_db),
            "WORKBENCH_WORKSPACE_BASE": str(root / "data"),
            "DEEPSEEK_API_KEY": "not-a-real-key",
        })
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        module = importlib.import_module("subsystems.deepseek_hapi.app")
        module.app.config["TESTING"] = True
        client = module.app.test_client()
        with client.session_transaction() as auth:
            auth["_user_id"] = "1"

        page = client.get("/")
        assert page.status_code == 200
        html = page.get_data(as_text=True)
        assert "DeepSeek 项目工作台" in html
        assert "代理" not in html and "Claude" not in html and "Codex" not in html
        assert 'name="model"' in html and 'name="agent"' not in html
        assert "DeepSeek V4 Flash" in html and "DeepSeek V4 Pro" in html

        created = client.post("/api/sessions", json={"project":"test-project","model":"deepseek-v4-flash"})
        assert created.status_code == 201
        session_id = created.get_json()["id"]
        listing = client.get(f"/api/files?session={session_id}&path=.")
        assert listing.status_code == 200
        assert [item["name"] for item in listing.get_json()["entries"]] == ["main.py"]
        assert client.get(f"/api/files?session={session_id}&path=../").status_code == 400

        calls = []
        def fake_deepseek(_config, messages, _tools, **kwargs):
            calls.append((messages, kwargs))
            if len(calls) == 1:
                return {"content": None, "tool_calls": [{
                    "id":"call_1", "type":"function",
                    "function":{"name":"read_file","arguments":'{"path":"main.py"}'},
                }]}
            assert kwargs["model"] == "deepseek-v4-flash"
            assert any(item.get("role") == "tool" and "deepseek" in item.get("content", "") for item in messages)
            return {"content":"入口文件是 `main.py`。"}
        original = module.deepseek_tool_chat
        module.deepseek_tool_chat = fake_deepseek
        try:
            response = client.post(f"/api/sessions/{session_id}/messages",json={"message":"分析入口"})
        finally:
            module.deepseek_tool_chat = original
        assert response.status_code == 200, response.get_data(as_text=True)
        assert response.get_json()["tool_events"][0]["name"] == "read_file"

        with client.session_transaction() as auth:
            auth["_user_id"] = "2"
        assert client.delete(f"/api/sessions/{session_id}").status_code == 404
        print("DEEPSEEK_HAPI_TEST_OK")


if __name__ == "__main__":
    main()
