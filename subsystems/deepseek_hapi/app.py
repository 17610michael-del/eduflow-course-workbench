from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from functools import wraps
from pathlib import Path

from flask import Flask, abort, g, jsonify, redirect, render_template, request, session

from subsystems.ai.services import DeepSeekError, deepseek_tool_chat
from subsystems.deepseek_workbench.services import (
    WORKBENCH_TOOLS,
    execute_workbench_tool,
    list_directory,
    read_file,
    tool_result_text,
    workspace_for_username,
)


APP_ROOT = Path(__file__).resolve().parent
COURSE_ROOT = APP_ROOT.parents[1]
COURSE_DATABASE = Path(os.environ.get("DATABASE", COURSE_ROOT / "data" / "app.db"))
WORKBENCH_DATABASE = Path(os.environ.get(
    "DEEPSEEK_HAPI_DATABASE", COURSE_ROOT / "data" / "deepseek-hapi.db"
))
WORKSPACE_BASE = Path(os.environ.get("WORKBENCH_WORKSPACE_BASE", "/data"))
ALLOWED_MODELS = {
    "deepseek-v4-flash": "DeepSeek V4 Flash",
    "deepseek-v4-pro": "DeepSeek V4 Pro",
}
DEFAULT_MODEL = os.environ.get("DEEPSEEK_CHAT_MODEL", "deepseek-v4-flash")
if DEFAULT_MODEL not in ALLOWED_MODELS:
    DEFAULT_MODEL = "deepseek-v4-flash"


app = Flask(__name__, template_folder="templates", static_folder="static")
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY", ""),
    DEEPSEEK_API_KEY=os.environ.get("DEEPSEEK_API_KEY", ""),
    DEEPSEEK_BASE_URL=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    DEEPSEEK_CHAT_MODEL=DEFAULT_MODEL,
    DEEPSEEK_REASONING_MODEL=os.environ.get("DEEPSEEK_REASONING_MODEL", "deepseek-v4-pro"),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "0") == "1",
)
if not app.config["SECRET_KEY"]:
    raise RuntimeError("SECRET_KEY must be configured")


def now_iso():
    return datetime.now().replace(microsecond=0).isoformat()


def workbench_db():
    if "workbench_db" not in g:
        WORKBENCH_DATABASE.parent.mkdir(parents=True, exist_ok=True)
        g.workbench_db = sqlite3.connect(WORKBENCH_DATABASE)
        g.workbench_db.row_factory = sqlite3.Row
        g.workbench_db.execute("PRAGMA foreign_keys=ON")
    return g.workbench_db


@app.teardown_appcontext
def close_databases(_error=None):
    database = g.pop("workbench_db", None)
    if database is not None:
        database.close()


def init_database():
    database = workbench_db()
    database.executescript(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL DEFAULT '新对话',
            model TEXT NOT NULL,
            workspace_root TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            role TEXT NOT NULL CHECK(role IN ('user','assistant')),
            content TEXT NOT NULL,
            tool_events TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_ds_hapi_sessions_user ON sessions(user_id,updated_at);
        CREATE INDEX IF NOT EXISTS idx_ds_hapi_messages_session ON messages(session_id,id);
        """
    )
    database.commit()


@app.before_request
def prepare_request():
    init_database()


def current_course_user():
    user_id = session.get("_user_id")
    if not user_id or not str(user_id).isdigit() or not COURSE_DATABASE.is_file():
        return None
    database = sqlite3.connect(COURSE_DATABASE)
    database.row_factory = sqlite3.Row
    try:
        return database.execute(
            "SELECT id,username,display_name,role FROM users WHERE id=?", (int(user_id),)
        ).fetchone()
    finally:
        database.close()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_course_user()
        if not user:
            if request.path.startswith("/api/"):
                return jsonify({"error": "请先登录课程工作台"}), 401
            return redirect("http://10.98.103.193/login")
        g.course_user = user
        return view(*args, **kwargs)
    return wrapped


def user_workspace():
    return workspace_for_username(WORKSPACE_BASE, g.course_user["username"])


def owned_session(session_id):
    return workbench_db().execute(
        "SELECT * FROM sessions WHERE id=? AND user_id=?", (session_id, g.course_user["id"])
    ).fetchone()


def safe_project_root(relative_path="."):
    root = user_workspace()
    raw = str(relative_path or ".").strip().replace("\\", "/")
    if raw.startswith("/") or "\x00" in raw:
        raise ValueError("项目路径必须位于个人工作区")
    target = (root / raw).resolve()
    if target != root and root not in target.parents:
        raise ValueError("项目路径超出个人工作区")
    if not target.is_dir() or target.is_symlink():
        raise ValueError("项目目录不存在")
    return target


@app.get("/")
@login_required
def index():
    sessions = workbench_db().execute(
        "SELECT * FROM sessions WHERE user_id=? ORDER BY updated_at DESC,id DESC",
        (g.course_user["id"],),
    ).fetchall()
    selected = None
    requested_id = request.args.get("session", type=int)
    if requested_id:
        selected = owned_session(requested_id)
        if not selected:
            abort(404)
    elif sessions:
        selected = sessions[0]
    messages = []
    if selected:
        rows = workbench_db().execute(
            "SELECT * FROM messages WHERE session_id=? ORDER BY id", (selected["id"],)
        ).fetchall()
        for row in rows:
            item = dict(row)
            try:
                item["tool_events"] = json.loads(item["tool_events"] or "[]")
            except json.JSONDecodeError:
                item["tool_events"] = []
            messages.append(item)
    workspace = user_workspace()
    workspace_available = workspace.is_dir() and os.access(workspace, os.R_OK | os.X_OK)
    projects = []
    if workspace_available:
        try:
            projects = [entry for entry in list_directory(workspace, ".") if entry["type"] == "directory"]
        except (OSError, ValueError):
            workspace_available = False
    entries = []
    if selected:
        try:
            entries = list_directory(Path(selected["workspace_root"]), ".")
        except (OSError, ValueError):
            entries = []
    return render_template(
        "index.html", user=g.course_user, sessions=sessions, selected=selected,
        messages=messages, workspace=workspace, workspace_available=workspace_available,
        projects=projects, entries=entries, models=ALLOWED_MODELS,
        api_enabled=bool(app.config["DEEPSEEK_API_KEY"]),
    )


@app.post("/api/sessions")
@login_required
def create_session():
    data = request.get_json(silent=True) or {}
    model = str(data.get("model") or DEFAULT_MODEL)
    if model not in ALLOWED_MODELS:
        return jsonify({"error": "不支持该 DeepSeek 模型"}), 400
    project_path = str(data.get("project") or ".")
    try:
        project_root = safe_project_root(project_path)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    created = now_iso()
    cursor = workbench_db().execute(
        """INSERT INTO sessions(user_id,title,model,workspace_root,created_at,updated_at)
           VALUES (?,?,?,?,?,?)""",
        (g.course_user["id"], "新对话", model, str(project_root), created, created),
    )
    workbench_db().commit()
    return jsonify({"id": cursor.lastrowid, "url": f"/?session={cursor.lastrowid}"}), 201


@app.patch("/api/sessions/<int:session_id>")
@login_required
def update_session(session_id):
    if not owned_session(session_id):
        return jsonify({"error": "对话不存在"}), 404
    data = request.get_json(silent=True) or {}
    model = str(data.get("model") or "")
    if model not in ALLOWED_MODELS:
        return jsonify({"error": "不支持该 DeepSeek 模型"}), 400
    workbench_db().execute(
        "UPDATE sessions SET model=?,updated_at=? WHERE id=? AND user_id=?",
        (model, now_iso(), session_id, g.course_user["id"]),
    )
    workbench_db().commit()
    return jsonify({"ok": True, "model": model})


@app.delete("/api/sessions/<int:session_id>")
@login_required
def delete_session(session_id):
    if not owned_session(session_id):
        return jsonify({"error": "对话不存在"}), 404
    workbench_db().execute(
        "DELETE FROM sessions WHERE id=? AND user_id=?", (session_id, g.course_user["id"])
    )
    workbench_db().commit()
    return jsonify({"ok": True})


@app.get("/api/files")
@login_required
def files():
    selected = owned_session(request.args.get("session", type=int))
    if not selected:
        return jsonify({"error": "对话不存在"}), 404
    try:
        entries = list_directory(Path(selected["workspace_root"]), request.args.get("path", "."))
    except (OSError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"entries": entries})


@app.get("/api/file")
@login_required
def file_preview():
    selected = owned_session(request.args.get("session", type=int))
    if not selected:
        return jsonify({"error": "对话不存在"}), 404
    try:
        result = read_file(Path(selected["workspace_root"]), request.args.get("path", ""))
    except (OSError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(result)


@app.post("/api/sessions/<int:session_id>/messages")
@login_required
def send_message(session_id):
    selected = owned_session(session_id)
    if not selected:
        return jsonify({"error": "对话不存在"}), 404
    data = request.get_json(silent=True) or {}
    prompt = str(data.get("message") or "").strip()
    if not prompt:
        return jsonify({"error": "请输入消息"}), 400
    if len(prompt) > 8000:
        return jsonify({"error": "单条消息不能超过 8000 个字符"}), 400
    history = workbench_db().execute(
        "SELECT role,content FROM messages WHERE session_id=? ORDER BY id DESC LIMIT 20",
        (session_id,),
    ).fetchall()
    messages = [{
        "role": "system",
        "content": (
            "你是一个直接由 DeepSeek API 驱动的项目助手。你不是 Claude、Codex，也不存在其他协同助手。"
            "当前项目目录已经由系统隔离。你可以浏览目录、读取安全文本文件和搜索代码。"
            "工具是只读的，不得声称修改、创建、删除文件或执行了终端命令。"
            "使用简洁中文回答，并在引用代码时标明相对路径和行号。"
        ),
    }]
    for row in reversed(history):
        messages.append({"role": row["role"], "content": row["content"][:12000]})
    messages.append({"role": "user", "content": prompt})
    events = []
    reply = ""
    try:
        for _ in range(6):
            assistant = deepseek_tool_chat(
                app.config, messages, WORKBENCH_TOOLS, model=selected["model"], max_tokens=4096
            )
            tool_calls = assistant.get("tool_calls") or []
            assistant_message = {"role": "assistant", "content": assistant.get("content")}
            if tool_calls:
                assistant_message["tool_calls"] = tool_calls
            messages.append(assistant_message)
            if not tool_calls:
                reply = str(assistant.get("content") or "").strip()
                break
            for call in tool_calls[:8]:
                function = call.get("function") or {}
                name = str(function.get("name") or "")
                try:
                    raw = function.get("arguments") or "{}"
                    arguments = json.loads(raw) if isinstance(raw, str) else raw
                    result = execute_workbench_tool(Path(selected["workspace_root"]), name, arguments)
                    output = tool_result_text(result)
                    events.append({"name": name, "ok": True})
                except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
                    output = json.dumps({"error": str(exc)}, ensure_ascii=False)
                    events.append({"name": name or "unknown", "ok": False})
                messages.append({
                    "role": "tool", "tool_call_id": str(call.get("id") or ""), "content": output,
                })
        if not reply:
            raise DeepSeekError("工具调用次数过多，请缩小问题范围后重试")
    except DeepSeekError as exc:
        return jsonify({"error": str(exc)}), 502
    created = now_iso()
    title = selected["title"]
    if title == "新对话":
        title = prompt.replace("\n", " ")[:30] or "新对话"
    database = workbench_db()
    database.execute(
        "INSERT INTO messages(session_id,role,content,tool_events,created_at) VALUES (?,'user',?,'[]',?)",
        (session_id, prompt, created),
    )
    database.execute(
        "INSERT INTO messages(session_id,role,content,tool_events,created_at) VALUES (?,'assistant',?,?,?)",
        (session_id, reply, json.dumps(events, ensure_ascii=False), created),
    )
    database.execute(
        "UPDATE sessions SET title=?,updated_at=? WHERE id=? AND user_id=?",
        (title, created, session_id, g.course_user["id"]),
    )
    database.commit()
    return jsonify({"reply": reply, "tool_events": events, "title": title})


if __name__ == "__main__":
    app.run(host=os.environ.get("DEEPSEEK_HAPI_HOST", "0.0.0.0"),
            port=int(os.environ.get("DEEPSEEK_HAPI_PORT", "3066")))
