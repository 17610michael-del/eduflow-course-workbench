"""Isolated integration test for per-student AI knowledge bases."""
from __future__ import annotations

import io
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch


temporary = tempfile.TemporaryDirectory(prefix="eduflow-knowledge-test-")
os.environ["SECRET_KEY"] = "knowledge-test-secret"
os.environ["DEEPSEEK_API_KEY"] = "test-key"
os.environ["DATABASE"] = os.path.join(temporary.name, "test.db")
os.environ["UPLOAD_FOLDER"] = os.path.join(temporary.name, "uploads")
os.environ["SERVER_SUBMISSION_ROOT"] = os.path.join(temporary.name, "server-files")
os.environ["SESSION_COOKIE_SECURE"] = "0"

from app import app, execute, init_db, query  # noqa: E402


with app.app_context():
    init_db()
    teacher = query("SELECT id FROM users WHERE role='teacher' ORDER BY id LIMIT 1", one=True)
    student = query("SELECT id,username FROM users WHERE role='student' ORDER BY id LIMIT 1", one=True)
    other_id = execute(
        "INSERT INTO users(username,display_name,role,created_at) VALUES (?,?,?,?)",
        ("knowledge_other", "其他知识库学生", "student", datetime.now().isoformat()),
    )
    other_doc_id = execute(
        """INSERT INTO knowledge_documents
           (user_id,original_name,stored_path,file_size,status,chunk_count,char_count,created_by,created_at,updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (other_id, "private.txt", "knowledge/knowledge_other/private.txt", 10, "ready", 1, 10,
         teacher["id"], datetime.now().isoformat(), datetime.now().isoformat()),
    )
    execute(
        "INSERT INTO knowledge_chunks(document_id,user_id,chunk_index,content,created_at) VALUES (?,?,?,?,?)",
        (other_doc_id, other_id, 0, "独有词鲲鹏三号只属于其他学生", datetime.now().isoformat()),
    )

with app.test_client() as client:
    with client.session_transaction() as session:
        session["_user_id"] = str(student["id"])
        session["_fresh"] = True

    page = client.get("/knowledge")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "我的 AI 知识库" in html and 'href="/knowledge"' in html
    assert "其他知识库学生" not in html

    upload = client.post(
        "/knowledge/documents",
        data={
            "username": "knowledge_other",
            "document": (io.BytesIO("光合作用将光能转化为化学能。\n\n叶绿体是重要场所。".encode("utf-8")), "biology.txt"),
        },
        content_type="multipart/form-data",
    )
    assert upload.status_code == 302

    with app.app_context():
        document = query(
            "SELECT * FROM knowledge_documents WHERE user_id=? AND original_name='biology.txt'",
            (student["id"],), one=True,
        )
        assert document is not None and document["status"] == "ready" and document["chunk_count"] >= 1
        assert query("SELECT COUNT(*) n FROM knowledge_chunks WHERE user_id=?", (student["id"],), one=True)["n"] >= 1

    download = client.get(f"/knowledge/documents/{document['id']}/download")
    assert download.status_code == 200 and "attachment" in download.headers.get("Content-Disposition", "")

    with patch("app.knowledge_base_assistant", return_value="光合作用将光能转化为化学能 [1]"):
        answer = client.post("/api/knowledge/chat", json={"message": "什么是光合作用？", "username": "knowledge_other"})
    assert answer.status_code == 200, answer.get_data(as_text=True)
    assert answer.json["sources"][0]["name"] == "biology.txt"
    assert answer.json["sources"][0]["url"].endswith(f"/{document['id']}/download")

    isolated = client.post("/api/knowledge/chat", json={"message": "鲲鹏三号是什么？", "username": "knowledge_other"})
    assert isolated.status_code == 422
    assert client.get(f"/knowledge/documents/{other_doc_id}/download").status_code == 403
    assert client.post(f"/knowledge/documents/{other_doc_id}/delete").status_code == 403

    with client.session_transaction() as session:
        session["_user_id"] = str(teacher["id"])
        session["_fresh"] = True
    teacher_page = client.get("/knowledge?username=knowledge_other")
    teacher_html = teacher_page.get_data(as_text=True)
    assert teacher_page.status_code == 200
    assert "其他知识库学生" in teacher_html and "private.txt" in teacher_html

    clear = client.post("/api/knowledge/chat/clear", json={"username": "knowledge_other"})
    assert clear.status_code == 200

    with client.session_transaction() as session:
        session["_user_id"] = str(student["id"])
        session["_fresh"] = True
    deleted = client.post(f"/knowledge/documents/{document['id']}/delete")
    assert deleted.status_code == 302
    with app.app_context():
        assert query("SELECT id FROM knowledge_documents WHERE id=?", (document["id"],), one=True) is None
    assert not Path(app.config["UPLOAD_FOLDER"], document["stored_path"]).exists()

temporary.cleanup()
print("KNOWLEDGE_BASE_TEST_OK")
