from __future__ import annotations

import json
import os
import shutil
import sqlite3
import uuid
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path

import bleach
import pam
from flask import (
    Flask, abort, flash, g, jsonify, redirect, render_template, request,
    send_from_directory, session, url_for,
)
from flask_login import (
    LoginManager, UserMixin, current_user, login_required, login_user, logout_user,
)
from markdown import markdown
from werkzeug.utils import secure_filename
from subsystems.ai.services import (
    DeepSeekError, assignment_assistant, enhance_learning_analysis,
    extract_document_text, generate_questions, recognize_document_questions,
)
from subsystems.exams.services import attempt_deadline, normalize_questions

from config import Config

try:
    import grp
    import pwd
except ImportError:  # Windows 本地开发环境没有 Unix 账号模块
    grp = None
    pwd = None


app = Flask(__name__)
app.config.from_object(Config)
login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "请先使用服务器账号登录。"
login_manager.login_message_category = "warning"

DATABASE = Path(app.config["DATABASE"])
UPLOAD_DIR = Path(app.config["UPLOAD_FOLDER"])
SERVER_SUBMISSION_ROOT = Path(app.config["SERVER_SUBMISSION_ROOT"])
ALLOWED_EXTENSIONS = {"pdf", "doc", "docx", "zip", "png", "jpg", "jpeg"}
LOCK_WINDOW = timedelta(minutes=15)
MAX_LOGIN_FAILURES = 5


class User(UserMixin):
    def __init__(self, row):
        self.id = int(row["id"])
        self.username = row["username"]
        self.display_name = row["display_name"]
        self.role = row["role"]

    @property
    def name(self):
        return self.display_name

    @property
    def is_teacher(self):
        return self.role == "teacher"

    @property
    def is_staff(self):
        return self.role in ("teacher", "assistant")


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        DATABASE.parent.mkdir(parents=True, exist_ok=True)
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        g.db.execute("PRAGMA journal_mode = WAL")
    return g.db


@app.teardown_appcontext
def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


@app.after_request
def prevent_private_page_cache(response):
    """Prevent authenticated screens from reappearing through browser back/forward cache."""
    if request.endpoint != "static" and (
        current_user.is_authenticated or request.endpoint in {"login", "logout"}
    ):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0, private"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        response.headers.add("Vary", "Cookie")
    return response


def query(sql: str, params: tuple = (), one: bool = False):
    rows = get_db().execute(sql, params).fetchall()
    return (rows[0] if rows else None) if one else rows


def execute(sql: str, params: tuple = ()) -> int:
    db = get_db()
    cursor = db.execute(sql, params)
    db.commit()
    return cursor.lastrowid


def table_columns(table: str) -> set[str]:
    return {row["name"] for row in query(f"PRAGMA table_info({table})")}


def ensure_column(table: str, column: str, definition: str):
    if column not in table_columns(table):
        execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def migrate_users_role_check():
    """Old databases only allowed teacher/student; rebuild users to accept assistant."""
    row = query("SELECT sql FROM sqlite_master WHERE type='table' AND name='users'", one=True)
    if row and "assistant" in (row["sql"] or ""):
        return
    db = get_db()
    db.execute("PRAGMA foreign_keys = OFF")
    try:
        db.execute("BEGIN")
        db.execute(
            """CREATE TABLE users_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                display_name TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('teacher','assistant','student')),
                created_at TEXT NOT NULL,
                last_login_at TEXT
            )"""
        )
        db.execute(
            """INSERT INTO users_new(id,username,display_name,role,created_at,last_login_at)
               SELECT id,username,display_name,role,created_at,last_login_at FROM users"""
        )
        db.execute("DROP TABLE users")
        db.execute("ALTER TABLE users_new RENAME TO users")
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise
    finally:
        db.execute("PRAGMA foreign_keys = ON")


def init_db(seed: bool = True):
    db = get_db()
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            display_name TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('teacher','assistant','student')),
            created_at TEXT NOT NULL,
            last_login_at TEXT
        );
        CREATE TABLE IF NOT EXISTS assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            due_date TEXT,
            attachment_url TEXT,
            created_by INTEGER NOT NULL REFERENCES users(id),
            status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','closed')),
            created_at TEXT NOT NULL,
            labels TEXT NOT NULL DEFAULT '[]',
            assignee_usernames TEXT NOT NULL DEFAULT '[]',
            reviewer_usernames TEXT NOT NULL DEFAULT '[]'
        );
        CREATE TABLE IF NOT EXISTS discussions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            assignment_id INTEGER NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id),
            parent_id INTEGER REFERENCES discussions(id) ON DELETE CASCADE,
            content TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT 'comment' CHECK(kind IN ('comment','system')),
            attachment_url TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            assignment_id INTEGER NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
            student_id INTEGER NOT NULL REFERENCES users(id),
            file_url TEXT NOT NULL,
            submitted_at TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS grades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            assignment_id INTEGER NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
            student_id INTEGER NOT NULL REFERENCES users(id),
            score INTEGER NOT NULL CHECK(score BETWEEN 0 AND 100),
            feedback TEXT NOT NULL DEFAULT '',
            graded_by INTEGER NOT NULL REFERENCES users(id),
            graded_at TEXT NOT NULL,
            UNIQUE(assignment_id, student_id)
        );
        CREATE TABLE IF NOT EXISTS study_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            leader_id INTEGER NOT NULL REFERENCES users(id),
            created_by INTEGER NOT NULL REFERENCES users(id),
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS group_members (
            group_id INTEGER NOT NULL REFERENCES study_groups(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
            PRIMARY KEY(group_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS exams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            category TEXT NOT NULL CHECK(category IN ('quiz','midterm','final')),
            mode TEXT NOT NULL CHECK(mode IN ('paper','computer')),
            start_at TEXT NOT NULL,
            end_at TEXT NOT NULL,
            paper_url TEXT,
            instructions TEXT NOT NULL DEFAULT '',
            questions TEXT NOT NULL DEFAULT '',
            created_by INTEGER NOT NULL REFERENCES users(id),
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS exam_submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exam_id INTEGER NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
            student_id INTEGER NOT NULL REFERENCES users(id),
            answer_text TEXT NOT NULL DEFAULT '',
            file_url TEXT,
            submitted_at TEXT NOT NULL,
            UNIQUE(exam_id, student_id)
        );
        CREATE TABLE IF NOT EXISTS exam_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exam_id INTEGER NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
            student_id INTEGER NOT NULL REFERENCES users(id),
            started_at TEXT NOT NULL,
            deadline_at TEXT NOT NULL,
            answers TEXT NOT NULL DEFAULT '{}',
            submitted_at TEXT,
            submit_reason TEXT CHECK(submit_reason IN ('manual','time_limit','exam_ended')),
            UNIQUE(exam_id, student_id)
        );
        CREATE TABLE IF NOT EXISTS exam_grades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exam_id INTEGER NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
            student_id INTEGER NOT NULL REFERENCES users(id),
            score INTEGER NOT NULL CHECK(score BETWEEN 0 AND 100),
            feedback TEXT NOT NULL DEFAULT '',
            graded_by INTEGER NOT NULL REFERENCES users(id),
            graded_at TEXT NOT NULL,
            UNIQUE(exam_id, student_id)
        );
        CREATE TABLE IF NOT EXISTS question_bank (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_type TEXT NOT NULL,
            prompt TEXT NOT NULL,
            options TEXT NOT NULL DEFAULT '[]',
            answer TEXT NOT NULL DEFAULT '',
            points INTEGER NOT NULL DEFAULT 0,
            source TEXT NOT NULL DEFAULT 'manual',
            source_file TEXT,
            status TEXT NOT NULL DEFAULT 'ready' CHECK(status IN ('pending','ready','failed')),
            created_by INTEGER NOT NULL REFERENCES users(id),
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS group_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL REFERENCES study_groups(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id),
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS course_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            event_type TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id INTEGER,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            actor_id INTEGER NOT NULL REFERENCES users(id),
            action TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id INTEGER,
            assignment_id INTEGER,
            student_id INTEGER,
            details TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS drafts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            draft_type TEXT NOT NULL CHECK(draft_type IN ('assignment_new','exam_new','assignment_submission','exam_answer')),
            context_key TEXT NOT NULL,
            data TEXT NOT NULL DEFAULT '{}',
            file_url TEXT,
            file_name TEXT,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, draft_type, context_key)
        );
        CREATE TABLE IF NOT EXISTS chat_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            assignment_id INTEGER NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id),
            message TEXT NOT NULL,
            reply TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS analysis_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            report TEXT NOT NULL,
            generated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS login_failures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            failed_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_discussions_assignment ON discussions(assignment_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_submissions_assignment_student ON submissions(assignment_id, student_id, version);
        CREATE INDEX IF NOT EXISTS idx_grades_student ON grades(student_id, assignment_id);
        CREATE INDEX IF NOT EXISTS idx_exam_submissions_exam ON exam_submissions(exam_id, student_id);
        CREATE INDEX IF NOT EXISTS idx_exam_grades_student ON exam_grades(student_id, exam_id);
        CREATE INDEX IF NOT EXISTS idx_drafts_user_type ON drafts(user_id, draft_type, context_key);
        CREATE INDEX IF NOT EXISTS idx_attempts_student_exam ON exam_attempts(student_id, exam_id);
        CREATE INDEX IF NOT EXISTS idx_audit_assignment ON audit_logs(assignment_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_question_bank_status ON question_bank(status, created_at);
        CREATE INDEX IF NOT EXISTS idx_group_messages_group ON group_messages(group_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_course_events_time ON course_events(created_at);
        CREATE INDEX IF NOT EXISTS idx_failures_username ON login_failures(username, failed_at);
        """
    )
    db.commit()
    ensure_column("exams", "duration_minutes", "INTEGER NOT NULL DEFAULT 60")
    ensure_column("exams", "question_data", "TEXT NOT NULL DEFAULT '[]'")
    ensure_column("assignments", "reviewer_usernames", "TEXT NOT NULL DEFAULT '[]'")
    migrate_users_role_check()
    if seed and not query("SELECT id FROM users LIMIT 1", one=True):
        seed_db()


def seed_db():
    db = get_db()
    created = "2026-08-01T09:30:00"
    teacher = db.execute(
        "INSERT INTO users(username,display_name,role,created_at) VALUES ('demo_teacher','示例教师','teacher',?)",
        (created,),
    ).lastrowid
    student = db.execute(
        "INSERT INTO users(username,display_name,role,created_at) VALUES ('demo_student','示例学生','student',?)",
        (created,),
    ).lastrowid
    desc1 = """## 任务要求

1. 阅读指定文献 3 篇，并记录核心观点。
2. 完成一篇不少于 **800 字**的文献综述。
3. 截止前在 Activity 区提交 PDF 文件。

> 参考文献采用 GB/T 7714 标准。

### 任务分配

@demo_student

如有问题，请在下方留言或询问 AI 助教。"""
    a1 = db.execute(
        """INSERT INTO assignments(title,description,due_date,created_by,status,created_at,labels,assignee_usernames)
           VALUES (?,?,?,?, 'open',?,?,?)""",
        ("第2次作业 - 文献综述", desc1, "2026-08-20T23:59", teacher, "2026-08-02T10:00:00",
         json.dumps(["第2次作业", "文献综述"], ensure_ascii=False), json.dumps(["demo_student"])),
    ).lastrowid
    desc2 = """## 任务要求

使用 Python 实现二叉树的前序、中序和后序遍历，并分析算法复杂度。

### 任务分配

@demo_student"""
    db.execute(
        """INSERT INTO assignments(title,description,due_date,created_by,status,created_at,labels,assignee_usernames)
           VALUES (?,?,?,?, 'open',?,?,?)""",
        ("第1次作业 - 二叉树遍历", desc2, "2026-08-14T23:59", teacher, "2026-07-28T14:20:00",
         json.dumps(["第1次作业", "数据结构"], ensure_ascii=False), json.dumps(["demo_student"])),
    )
    system_id = db.execute(
        "INSERT INTO discussions(assignment_id,user_id,content,kind,created_at) VALUES (?,?,?,'system',?)",
        (a1, teacher, "示例教师添加了标签并指派了任务", "2026-08-02T10:01:00"),
    ).lastrowid
    question = db.execute(
        "INSERT INTO discussions(assignment_id,user_id,content,created_at) VALUES (?,?,?,?)",
        (a1, student, "老师，第 3 篇文献的访问链接失效了，能补一份吗？", "2026-08-07T15:24:00"),
    ).lastrowid
    db.execute(
        "INSERT INTO discussions(assignment_id,user_id,parent_id,content,created_at) VALUES (?,?,?,?,?)",
        (a1, teacher, question, "@demo_student 已重新上传到附件区，请查收。", "2026-08-08T09:10:00"),
    )
    db.commit()


@app.cli.command("init-db")
def init_db_command():
    init_db()
    print(f"Database initialized: {DATABASE}")


@app.before_request
def ensure_database():
    init_db()


@login_manager.user_loader
def load_user(user_id):
    row = query("SELECT * FROM users WHERE id=?", (user_id,), one=True)
    return User(row) if row else None


@login_manager.unauthorized_handler
def unauthorized():
    if request.path.startswith("/api/"):
        return jsonify({"error": "authentication_required"}), 401
    return redirect(url_for("login", next=request.full_path))


def teacher_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if current_user.role != "teacher":
            if request.path.startswith("/api/"):
                return jsonify({"error": "teacher_required"}), 403
            flash("此操作仅老师可用。", "warning")
            return redirect(url_for("home"))
        return view(*args, **kwargs)
    return wrapped


def staff_required(view):
    """老师或助教可用：可审阅、评分，但不能发布任务/考试。"""
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if current_user.role not in ("teacher", "assistant"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "staff_required"}), 403
            flash("此操作仅老师或助教可用。", "warning")
            return redirect(url_for("home"))
        return view(*args, **kwargs)
    return wrapped


def role_for_linux_user(username: str) -> str:
    if username in app.config["TEACHERS"]:
        return "teacher"
    if grp is None or pwd is None:
        return "student"
    try:
        account = pwd.getpwnam(username)
    except KeyError:
        return "student"
    try:
        assistant_group = grp.getgrnam(app.config["ASSISTANT_GROUP"])
        if username in assistant_group.gr_mem or account.pw_gid == assistant_group.gr_gid:
            return "assistant"
    except (KeyError, PermissionError):
        pass
    try:
        teacher_group = grp.getgrnam(app.config["TEACHER_GROUP"])
        if username in teacher_group.gr_mem or account.pw_gid == teacher_group.gr_gid:
            return "teacher"
    except (KeyError, PermissionError):
        pass
    return "student"


def pam_authenticate(username: str, password: str) -> bool:
    authenticator = pam.pam()
    return bool(authenticator.authenticate(username, password, service="login"))


def locked_until(username: str):
    cutoff = (datetime.now() - LOCK_WINDOW).replace(microsecond=0).isoformat()
    execute("DELETE FROM login_failures WHERE failed_at < ?", (cutoff,))
    failures = query("SELECT failed_at FROM login_failures WHERE username=? ORDER BY failed_at DESC", (username,))
    if len(failures) < MAX_LOGIN_FAILURES:
        return None
    return datetime.fromisoformat(failures[0]["failed_at"]) + LOCK_WINDOW


def record_login_failure(username: str):
    execute("INSERT INTO login_failures(username,failed_at) VALUES (?,?)", (username, now_iso()))


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("home"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        remember = request.form.get("remember") == "1"
        until = locked_until(username) if username else None
        if until:
            flash(f"登录失败次数过多，请在 {until.strftime('%H:%M')} 后重试。", "danger")
        elif not username or not password or not pam_authenticate(username, password):
            if username:
                record_login_failure(username)
            flash("服务器用户名或密码错误。", "danger")
        else:
            execute("DELETE FROM login_failures WHERE username=?", (username,))
            role = role_for_linux_user(username)
            existing = query("SELECT * FROM users WHERE username=?", (username,), one=True)
            if existing:
                execute("UPDATE users SET role=?,last_login_at=? WHERE id=?", (role, now_iso(), existing["id"]))
                row = query("SELECT * FROM users WHERE id=?", (existing["id"],), one=True)
            else:
                user_id = execute(
                    "INSERT INTO users(username,display_name,role,created_at,last_login_at) VALUES (?,?,?,?,?)",
                    (username, username, role, now_iso(), now_iso()),
                )
                row = query("SELECT * FROM users WHERE id=?", (user_id,), one=True)
            login_user(User(row), remember=remember, duration=app.config["REMEMBER_COOKIE_DURATION"])
            next_url = request.args.get("next")
            response = redirect(next_url if next_url and next_url.startswith("/") else url_for("home"))
            known_users = [x for x in request.cookies.get("known_usernames", "").split(",") if x]
            known_users = [username] + [x for x in known_users if x != username]
            known_users = known_users[:8]
            response.set_cookie(
                "last_username", username, max_age=10 * 365 * 24 * 60 * 60,
                httponly=True, samesite="Lax", secure=app.config["SESSION_COOKIE_SECURE"],
            )
            response.set_cookie(
                "known_usernames", ",".join(known_users), max_age=10 * 365 * 24 * 60 * 60,
                httponly=True, samesite="Lax", secure=app.config["SESSION_COOKIE_SECURE"],
            )
            return response
    known_users = [x for x in request.cookies.get("known_usernames", "").split(",") if x]
    last_username = request.cookies.get("last_username", "")
    if last_username and last_username not in known_users:
        known_users.insert(0, last_username)
    return render_template("login.html", last_username=last_username, known_usernames=known_users[:8])


@app.post("/logout")
@login_required
def logout():
    logout_user()
    # logout_user stores a marker in the session so Flask-Login can expire the
    # persistent remember cookie on the outgoing response. Clearing the entire
    # session here would remove that marker and immediately log the user back in.
    return redirect(url_for("login"))


@app.template_filter("relative_time")
def relative_time(value):
    if not value:
        return ""
    try:
        delta = datetime.now() - datetime.fromisoformat(value)
    except ValueError:
        return value
    seconds = max(int(delta.total_seconds()), 0)
    if seconds < 60: return "刚刚"
    if seconds < 3600: return f"{seconds // 60} 分钟前"
    if seconds < 86400: return f"{seconds // 3600} 小时前"
    if seconds < 2592000: return f"{seconds // 86400} 天前"
    return datetime.fromisoformat(value).strftime("%Y-%m-%d")


@app.template_filter("date_cn")
def date_cn(value):
    if not value: return "未设置"
    try: return datetime.fromisoformat(value).strftime("%Y年%m月%d日 %H:%M")
    except ValueError: return value


@app.template_filter("markdown")
def safe_markdown(value):
    rendered = markdown(value or "", extensions=["fenced_code", "tables", "sane_lists"])
    tags = set(bleach.sanitizer.ALLOWED_TAGS) | {
        "p", "pre", "code", "h1", "h2", "h3", "h4", "ul", "ol", "li",
        "blockquote", "table", "thead", "tbody", "tr", "th", "td", "hr", "br",
    }
    return bleach.clean(rendered, tags=tags, attributes={"a": ["href", "title"]}, protocols={"http", "https", "mailto"})


@app.context_processor
def layout_data():
    if not current_user.is_authenticated:
        return {}
    data = {"nav_assignment_count": query("SELECT COUNT(*) AS n FROM assignments", one=True)["n"],
            "nav_exam_count": query("SELECT COUNT(*) AS n FROM exams", one=True)["n"]}
    if current_user.role == "teacher":
        data["nav_draft_count"] = query("SELECT COUNT(*) n FROM drafts WHERE user_id=? AND draft_type='assignment_new'",
                                        (current_user.id,), one=True)["n"]
    return data


def save_upload(file, category="general"):
    if not file or not file.filename:
        return None
    original = secure_filename(file.filename)
    suffix = Path(original or file.filename).suffix.lower().lstrip(".")
    if suffix not in ALLOWED_EXTENSIONS:
        raise ValueError("不支持该文件类型")
    safe_categories = {"general", "tasks", "exams"}
    category = category if category in safe_categories else "general"
    target_dir = UPLOAD_DIR / category
    target_dir.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}.{suffix}"
    file.save(target_dir / name)
    return f"{category}/{name}"


def get_draft(draft_type, context_key):
    row = query("SELECT * FROM drafts WHERE user_id=? AND draft_type=? AND context_key=?",
                (current_user.id, draft_type, str(context_key)), one=True)
    if not row: return None
    item = dict(row)
    try: item["data"] = json.loads(item["data"] or "{}")
    except json.JSONDecodeError: item["data"] = {}
    return item


def save_draft(draft_type, context_key, data, file=None):
    existing = get_draft(draft_type, context_key)
    file_url = existing["file_url"] if existing else None
    file_name = existing["file_name"] if existing else None
    if file and file.filename:
        file_name = file.filename
        category = "exams" if draft_type in {"exam_new", "exam_answer"} else "tasks"
        file_url = save_upload(file, category)
    execute("""INSERT INTO drafts(user_id,draft_type,context_key,data,file_url,file_name,updated_at)
               VALUES (?,?,?,?,?,?,?) ON CONFLICT(user_id,draft_type,context_key) DO UPDATE SET
               data=excluded.data,file_url=excluded.file_url,file_name=excluded.file_name,updated_at=excluded.updated_at""",
            (current_user.id, draft_type, str(context_key), json.dumps(data, ensure_ascii=False),
             file_url, file_name, now_iso()))
    return get_draft(draft_type, context_key)


def delete_draft(draft_type, context_key):
    execute("DELETE FROM drafts WHERE user_id=? AND draft_type=? AND context_key=?",
            (current_user.id, draft_type, str(context_key)))


def write_audit(action, entity_type, entity_id=None, assignment_id=None, student_id=None, details=None):
    execute("""INSERT INTO audit_logs(actor_id,action,entity_type,entity_id,assignment_id,student_id,details,created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (current_user.id, action, entity_type, entity_id, assignment_id, student_id,
             json.dumps(details or {}, ensure_ascii=False), now_iso()))


def record_course_event(event_type, entity_type, entity_id, title, content):
    execute("""INSERT INTO course_events(user_id,event_type,entity_type,entity_id,title,content,created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (current_user.id, event_type, entity_type, entity_id, title, content, now_iso()))


def available_server_files(username):
    """List only regular, allowed files in this user's designated staging area."""
    user_dir = SERVER_SUBMISSION_ROOT / username
    user_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for candidate in sorted(user_dir.iterdir(), key=lambda p: p.name.lower()):
        suffix = candidate.suffix.lower().lstrip(".")
        if candidate.is_file() and not candidate.is_symlink() and suffix in ALLOWED_EXTENSIONS:
            size = candidate.stat().st_size
            if size <= app.config["MAX_CONTENT_LENGTH"]:
                files.append({"name": candidate.name, "size": size})
    return files


def copy_server_submission(username, filename):
    if not filename or Path(filename).name != filename:
        raise ValueError("服务器文件选择无效")
    user_dir = (SERVER_SUBMISSION_ROOT / username).resolve()
    candidate = (user_dir / filename).resolve()
    if candidate.parent != user_dir or not candidate.is_file() or candidate.is_symlink():
        raise ValueError("服务器文件不存在或不可用")
    suffix = candidate.suffix.lower().lstrip(".")
    if suffix not in ALLOWED_EXTENSIONS:
        raise ValueError("不支持该文件类型")
    if candidate.stat().st_size > app.config["MAX_CONTENT_LENGTH"]:
        raise ValueError("文件不能超过 20MB")
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}.{suffix}"
    shutil.copy2(candidate, UPLOAD_DIR / stored_name)
    return stored_name


def hydrate_assignment(row):
    if not row: return None
    item = dict(row)
    item["labels"] = json.loads(item["labels"] or "[]")
    item["assignee_usernames"] = json.loads(item["assignee_usernames"] or "[]")
    item["reviewer_usernames"] = json.loads(item.get("reviewer_usernames") or "[]")
    if item["assignee_usernames"]:
        marks = ",".join("?" for _ in item["assignee_usernames"])
        item["assignees"] = [dict(x) for x in query(f"SELECT * FROM users WHERE username IN ({marks})", tuple(item["assignee_usernames"]))]
    else:
        item["assignees"] = []
    if item["reviewer_usernames"]:
        marks = ",".join("?" for _ in item["reviewer_usernames"])
        item["reviewers"] = [dict(x) for x in query(f"SELECT * FROM users WHERE username IN ({marks})", tuple(item["reviewer_usernames"]))]
    else:
        item["reviewers"] = []
    return item


def staff_scoped_sets():
    """按当前老师/助教维度计算任务归属：我发布的、指派给我、待我审阅。
    “我发布的/指派给我”只算还在进行中的开放任务；“待我审阅”只算我负责且还有未评分提交的任务。
    """
    rows = query("SELECT id, created_by, status, reviewer_usernames FROM assignments")
    published, assigned, responsible = set(), set(), set()
    for r in rows:
        reviewers = set(json.loads(r["reviewer_usernames"] or "[]"))
        if r["created_by"] == current_user.id:
            responsible.add(r["id"])
            if r["status"] == "open":
                published.add(r["id"])
        if current_user.username in reviewers:
            responsible.add(r["id"])
            if r["status"] == "open":
                assigned.add(r["id"])
    review = set()
    if responsible:
        marks = ",".join("?" for _ in responsible)
        ungraded = query(
            f"""SELECT DISTINCT s.assignment_id FROM submissions s
                LEFT JOIN grades g ON g.assignment_id=s.assignment_id AND g.student_id=s.student_id
                WHERE s.assignment_id IN ({marks}) AND g.id IS NULL""",
            tuple(responsible),
        )
        review = {r["assignment_id"] for r in ungraded}
    return published, assigned, review


@app.get("/")
@login_required
def home():
    assignments = query(
        """SELECT a.*,u.display_name creator_name,
           (SELECT COUNT(*) FROM discussions d WHERE d.assignment_id=a.id AND d.kind='comment') comment_count,
           (SELECT COUNT(DISTINCT student_id) FROM submissions s WHERE s.assignment_id=a.id) submitted_count
           FROM assignments a JOIN users u ON u.id=a.created_by ORDER BY a.created_at DESC"""
    )
    discussion_activities = query(
        """SELECT d.*,u.display_name user_name,u.role,a.title assignment_title FROM discussions d
           JOIN users u ON u.id=d.user_id JOIN assignments a ON a.id=d.assignment_id
           ORDER BY d.created_at DESC LIMIT 12"""
    )
    event_activities = query(
        """SELECT ce.*,u.display_name user_name,u.role FROM course_events ce
           JOIN users u ON u.id=ce.user_id ORDER BY ce.created_at DESC LIMIT 12"""
    )
    activities = []
    for row in discussion_activities:
        item = dict(row)
        item.update({"entity_type": "assignment", "entity_id": item["assignment_id"],
                     "title": item["assignment_title"], "event_type": item["kind"]})
        activities.append(item)
    activities.extend(dict(row) for row in event_activities)
    activities = sorted(activities, key=lambda item: item["created_at"], reverse=True)[:8]
    attention = query(
        """SELECT d.*,u.display_name user_name,a.title assignment_title FROM discussions d
           JOIN users u ON u.id=d.user_id JOIN assignments a ON a.id=d.assignment_id
           WHERE d.kind='comment' AND u.role='student' AND d.parent_id IS NULL ORDER BY d.created_at DESC LIMIT 5"""
    )
    if current_user.role in ("teacher", "assistant"):
        published_ids, assigned_ids, review_ids = staff_scoped_sets()
        published = len(published_ids) if current_user.role == "teacher" else 0
        assigned = len(assigned_ids)
        review = len(review_ids)
        submitted = interactions = 0
        if current_user.role == "assistant":
            graded = query("SELECT COUNT(*) n FROM grades WHERE graded_by=?", (current_user.id,), one=True)["n"]
            graded += query("SELECT COUNT(*) n FROM exam_grades WHERE graded_by=?", (current_user.id,), one=True)["n"]
        else:
            graded = 0
        exam_total = query("SELECT COUNT(*) n FROM exams", one=True)["n"]
        exam_completed = query("SELECT COUNT(*) n FROM exams WHERE end_at < ?", (now_iso(),), one=True)["n"]
    else:
        assigned = sum(current_user.username in json.loads(x["assignee_usernames"] or "[]") for x in assignments)
        published, review = 0, 0
        graded = 0
        submitted = query("SELECT COUNT(DISTINCT assignment_id) n FROM submissions WHERE student_id=?", (current_user.id,), one=True)["n"]
        interactions = query("SELECT COUNT(*) n FROM discussions WHERE user_id=? AND kind='comment'", (current_user.id,), one=True)["n"]
        exam_total = query("SELECT COUNT(*) n FROM exams", one=True)["n"]
        exam_completed = query("SELECT COUNT(DISTINCT exam_id) n FROM exam_submissions WHERE student_id=?",
                               (current_user.id,), one=True)["n"]
    stats = {"assigned": assigned, "published": published, "review": review, "graded": graded,
             "submitted": submitted, "interactions": interactions,
             "participants": query("SELECT COUNT(*) n FROM users", one=True)["n"],
             "exam_total": exam_total, "exam_completed": exam_completed,
             "exam_percent": round(exam_completed / max(exam_total, 1) * 100)}
    return render_template("home.html", assignments=assignments, activities=activities, attention=attention, stats=stats)


@app.get("/assignments")
@login_required
def assignments_page():
    keyword = request.args.get("q", "").strip()
    sort = request.args.get("sort", "newest")
    view = request.args.get("view", "all").strip()
    where, params = "", ()
    if keyword:
        where, params = "WHERE a.title LIKE ? OR a.description LIKE ?", (f"%{keyword}%", f"%{keyword}%")
    order = "a.due_date ASC" if sort == "due" else "a.created_at DESC"
    rows = query(
        f"""SELECT a.*,u.display_name creator_name,
        (SELECT COUNT(*) FROM discussions d WHERE d.assignment_id=a.id AND d.kind='comment') comment_count,
        (SELECT COUNT(DISTINCT student_id) FROM submissions s WHERE s.assignment_id=a.id) submitted_count
        FROM assignments a JOIN users u ON u.id=a.created_by {where} ORDER BY {order}""", params)
    assignments = []
    for row in rows:
        item = dict(row); item["labels_list"] = json.loads(item["labels"] or "[]")
        item["assignee_count"] = len(json.loads(item["assignee_usernames"] or "[]")); assignments.append(item)
    all_assignments = list(assignments)
    total_count = len(all_assignments)
    submitted_ids = set()
    view_names = {"all": "全部任务", "completed": "已完成任务"}
    if current_user.role in ("teacher", "assistant"):
        published_ids, assigned_ids, review_ids = staff_scoped_sets()
        if current_user.role == "teacher":
            if view not in {"all", "completed", "review", "assigned", "published"}: view = "all"
            view_names.update({"review": "待我审阅", "assigned": "指派给我", "published": "我的发布"})
        else:
            if view not in {"all", "completed", "review", "assigned"}: view = "all"
            view_names.update({"review": "待我审阅", "assigned": "指派给我"})
        if view == "review": assignments = [x for x in assignments if x["id"] in review_ids]
        elif view == "completed": assignments = [x for x in assignments if x["status"] == "closed"]
        elif view == "assigned": assignments = [x for x in assignments if x["id"] in assigned_ids]
        elif view == "published": assignments = [x for x in assignments if x["id"] in published_ids]
        completed_count = sum(x["status"] == "closed" for x in all_assignments)
    else:
        if view not in {"all", "completed", "assigned", "submitted", "interactions"}: view = "all"
        view_names.update({"assigned": "指派给我", "submitted": "我的提交", "interactions": "我的互动"})
        submitted_ids = {x["assignment_id"] for x in query("SELECT DISTINCT assignment_id FROM submissions WHERE student_id=?", (current_user.id,))}
        interaction_ids = {x["assignment_id"] for x in query("SELECT DISTINCT assignment_id FROM discussions WHERE user_id=? AND kind='comment'", (current_user.id,))}
        if view in {"completed", "submitted"}: assignments = [x for x in assignments if x["id"] in submitted_ids]
        elif view == "assigned": assignments = [x for x in assignments if current_user.username in json.loads(x["assignee_usernames"] or "[]")]
        elif view == "interactions": assignments = [x for x in assignments if x["id"] in interaction_ids]
        completed_count = len(submitted_ids)
    return render_template("assignments.html", assignments=assignments, keyword=keyword, sort=sort,
                           view=view, view_name=view_names.get(view, "全部任务"), total_count=total_count,
                           completed_count=completed_count,
                           completion_percent=round(completed_count / max(total_count, 1) * 100))


@app.route("/assignments/new", methods=["GET", "POST"])
@teacher_required
def assignment_new():
    students = query("SELECT * FROM users WHERE role='student' ORDER BY display_name")
    reviewers = query("SELECT * FROM users WHERE role IN ('teacher','assistant') ORDER BY CASE role WHEN 'teacher' THEN 0 ELSE 1 END, display_name")
    draft_key = request.args.get("draft", "").strip() or request.form.get("draft_key", "").strip() or uuid.uuid4().hex
    draft = get_draft("assignment_new", draft_key)
    if request.method == "POST":
        title = request.form.get("title", "").strip(); description = request.form.get("description", "").strip()
        if not title or not description:
            flash("标题和任务说明不能为空。", "danger")
            return render_template("assignment_form.html", students=students, reviewers=reviewers, draft=draft, draft_key=draft_key)
        try: attachment = save_upload(request.files.get("attachment"), "tasks") or (draft["file_url"] if draft else None)
        except ValueError as exc:
            flash(str(exc), "danger"); return render_template("assignment_form.html", students=students, reviewers=reviewers, draft=draft, draft_key=draft_key)
        labels = [x.strip() for x in request.form.get("labels", "").split(",") if x.strip()]
        assignees = request.form.getlist("assignees")
        reviewers_usernames = request.form.getlist("reviewers")
        assignment_id = execute(
            """INSERT INTO assignments(title,description,due_date,attachment_url,created_by,status,created_at,labels,assignee_usernames,reviewer_usernames)
               VALUES (?,?,?,?,?,'open',?,?,?,?)""",
            (title, description, request.form.get("due_date") or None, attachment, current_user.id, now_iso(),
             json.dumps(labels, ensure_ascii=False), json.dumps(assignees), json.dumps(reviewers_usernames)),
        )
        execute("INSERT INTO discussions(assignment_id,user_id,content,kind,created_at) VALUES (?,?,?,'system',?)",
                (assignment_id, current_user.id, f"{current_user.name} 创建任务并指派给 {len(assignees)} 位学生", now_iso()))
        delete_draft("assignment_new", draft_key)
        flash("任务已创建。", "success")
        return redirect(url_for("assignment_detail", assignment_id=assignment_id))
    return render_template("assignment_form.html", students=students, reviewers=reviewers, draft=draft, draft_key=draft_key)


@app.get("/assignment-drafts")
@teacher_required
def assignment_drafts_page():
    drafts = query("""SELECT * FROM drafts WHERE user_id=? AND draft_type='assignment_new'
                    ORDER BY updated_at DESC""", (current_user.id,))
    items = []
    for row in drafts:
        item = dict(row)
        try: item["data"] = json.loads(item["data"] or "{}")
        except json.JSONDecodeError: item["data"] = {}
        items.append(item)
    return render_template("assignment_drafts.html", drafts=items)


@app.post("/assignment-drafts/<context_key>/delete")
@teacher_required
def delete_assignment_draft(context_key):
    draft = get_draft("assignment_new", context_key)
    if not draft: abort(404)
    write_audit("delete", "assignment_draft", draft["id"], details={"title": draft["data"].get("title", "")})
    delete_draft("assignment_new", context_key)
    flash("任务草稿已删除。", "success")
    return redirect(url_for("assignment_drafts_page"))


@app.get("/assignments/<int:assignment_id>")
@login_required
def assignment_detail(assignment_id):
    assignment = hydrate_assignment(query(
        """SELECT a.*,u.display_name creator_name,
        (SELECT COUNT(DISTINCT student_id) FROM submissions s WHERE s.assignment_id=a.id) submitted_count
        FROM assignments a JOIN users u ON u.id=a.created_by WHERE a.id=?""", (assignment_id,), one=True))
    if not assignment: abort(404)
    rows = query("""SELECT d.*,u.display_name user_name,u.username,u.role user_role FROM discussions d
                     JOIN users u ON u.id=d.user_id WHERE d.assignment_id=? ORDER BY d.created_at""", (assignment_id,))
    roots, replies = [], {}
    for row in rows:
        item = dict(row)
        if item["parent_id"]: replies.setdefault(item["parent_id"], []).append(item)
        else: roots.append(item)
    participants = query("""SELECT DISTINCT u.id,u.username,u.display_name,u.role FROM users u
                          JOIN discussions d ON d.user_id=u.id WHERE d.assignment_id=?""", (assignment_id,))
    submissions = query("""SELECT s.*,u.display_name name,u.username FROM submissions s
                         JOIN users u ON u.id=s.student_id WHERE s.assignment_id=? ORDER BY s.submitted_at DESC""", (assignment_id,))
    latest_submissions = query("""SELECT s.*,u.display_name name,u.username,
                                g.score,g.feedback,g.graded_at
                         FROM submissions s
                         JOIN users u ON u.id=s.student_id
                         LEFT JOIN grades g ON g.assignment_id=s.assignment_id AND g.student_id=s.student_id
                         WHERE s.assignment_id=? AND s.version=(
                           SELECT MAX(s2.version) FROM submissions s2
                           WHERE s2.assignment_id=s.assignment_id AND s2.student_id=s.student_id
                         ) ORDER BY s.submitted_at DESC""", (assignment_id,))
    chat_logs = query("SELECT * FROM chat_logs WHERE assignment_id=? AND user_id=? ORDER BY created_at DESC LIMIT 10",
                      (assignment_id, current_user.id))
    server_files = available_server_files(current_user.username) if current_user.role == "student" else []
    my_submissions = [x for x in submissions if x["student_id"] == current_user.id]
    my_grade = query("SELECT * FROM grades WHERE assignment_id=? AND student_id=?",
                     (assignment_id, current_user.id), one=True) if current_user.role == "student" else None
    submission_draft = get_draft("assignment_submission", assignment_id) if current_user.role == "student" else None
    return render_template("assignment_detail.html", assignment=assignment, discussions=roots, replies=replies,
                           participants=participants, submissions=submissions, latest_submissions=latest_submissions,
                           my_submissions=my_submissions, my_grade=my_grade,
                           submission_draft=submission_draft,
                           server_files=server_files, server_submission_path=str(SERVER_SUBMISSION_ROOT / current_user.username),
                           chat_logs=list(reversed(chat_logs)))


@app.post("/assignments/<int:assignment_id>/comment")
@login_required
def add_comment(assignment_id):
    assignment = query("SELECT * FROM assignments WHERE id=?", (assignment_id,), one=True)
    if not assignment: abort(404)
    if assignment["status"] == "closed":
        flash("任务已关闭。", "warning"); return redirect(url_for("assignment_detail", assignment_id=assignment_id))
    content = request.form.get("content", "").strip(); parent_id = request.form.get("parent_id", type=int)
    try: attachment = save_upload(request.files.get("attachment"), "tasks")
    except ValueError as exc:
        flash(str(exc), "danger"); return redirect(url_for("assignment_detail", assignment_id=assignment_id))
    if not content and not attachment:
        flash("请输入评论或添加附件。", "warning"); return redirect(url_for("assignment_detail", assignment_id=assignment_id))
    if parent_id:
        parent = query("SELECT id,parent_id FROM discussions WHERE id=? AND assignment_id=?", (parent_id, assignment_id), one=True)
        if not parent: abort(400)
        parent_id = parent["parent_id"] or parent["id"]
    execute("INSERT INTO discussions(assignment_id,user_id,parent_id,content,attachment_url,created_at) VALUES (?,?,?,?,?,?)",
            (assignment_id, current_user.id, parent_id, content or "提交了一个附件", attachment, now_iso()))
    if attachment and current_user.role == "student":
        version = query("SELECT COALESCE(MAX(version),0)+1 n FROM submissions WHERE assignment_id=? AND student_id=?",
                        (assignment_id, current_user.id), one=True)["n"]
        execute("INSERT INTO submissions(assignment_id,student_id,file_url,submitted_at,version) VALUES (?,?,?,?,?)",
                (assignment_id, current_user.id, attachment, now_iso(), version))
    flash("评论已发布。", "success")
    return redirect(url_for("assignment_detail", assignment_id=assignment_id) + "#activity")


@app.post("/assignments/<int:assignment_id>/submit")
@login_required
def submit_assignment(assignment_id):
    if current_user.role != "student":
        flash("仅学生可以提交作业。", "warning")
        return redirect(url_for("assignment_detail", assignment_id=assignment_id))
    assignment = query("SELECT * FROM assignments WHERE id=?", (assignment_id,), one=True)
    if not assignment: abort(404)
    if assignment["status"] == "closed":
        flash("任务已关闭，不能继续提交。", "warning")
        return redirect(url_for("assignment_detail", assignment_id=assignment_id))
    submission_draft = get_draft("assignment_submission", assignment_id)
    source = request.form.get("source", "local")
    original_name = ""
    try:
        if source == "server":
            original_name = request.form.get("server_file", "")
            stored_name = copy_server_submission(current_user.username, original_name)
        else:
            local_file = request.files.get("local_file")
            original_name = local_file.filename if local_file else ""
            stored_name = save_upload(local_file, "tasks") or (submission_draft["file_url"] if submission_draft else None)
            if stored_name and not original_name and submission_draft:
                original_name = submission_draft["file_name"] or "草稿文件"
            if not stored_name:
                raise ValueError("请选择本地文件")
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("assignment_detail", assignment_id=assignment_id) + "#activity")
    version = query("SELECT COALESCE(MAX(version),0)+1 n FROM submissions WHERE assignment_id=? AND student_id=?",
                    (assignment_id, current_user.id), one=True)["n"]
    execute("INSERT INTO submissions(assignment_id,student_id,file_url,submitted_at,version) VALUES (?,?,?,?,?)",
            (assignment_id, current_user.id, stored_name, now_iso(), version))
    execute("""INSERT INTO discussions(assignment_id,user_id,content,kind,attachment_url,created_at)
               VALUES (?,?,?,'system',?,?)""",
            (assignment_id, current_user.id, f"{current_user.name} 提交了作业 {original_name}（v{version}）",
             stored_name, now_iso()))
    delete_draft("assignment_submission", assignment_id)
    flash(f"作业提交成功，当前版本 v{version}。", "success")
    return redirect(url_for("assignment_detail", assignment_id=assignment_id) + "#activity")


@app.post("/assignments/<int:assignment_id>/grades/<int:student_id>")
@staff_required
def grade_assignment(assignment_id, student_id):
    assignment = query("SELECT id FROM assignments WHERE id=?", (assignment_id,), one=True)
    student = query("SELECT id FROM users WHERE id=? AND role='student'", (student_id,), one=True)
    submission = query("SELECT id FROM submissions WHERE assignment_id=? AND student_id=? LIMIT 1",
                       (assignment_id, student_id), one=True)
    if not assignment or not student or not submission:
        abort(404)
    score = request.form.get("score", type=int)
    feedback = request.form.get("feedback", "").strip()
    if score is None or not 0 <= score <= 100:
        flash("请输入 0 到 100 之间的分数。", "danger")
        return redirect(url_for("assignment_detail", assignment_id=assignment_id) + "#grading")
    if len(feedback) > 2000:
        flash("教师评语不能超过 2000 个字符。", "danger")
        return redirect(url_for("assignment_detail", assignment_id=assignment_id) + "#grading")
    execute("""INSERT INTO grades(assignment_id,student_id,score,feedback,graded_by,graded_at)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(assignment_id,student_id) DO UPDATE SET
                 score=excluded.score,feedback=excluded.feedback,
                 graded_by=excluded.graded_by,graded_at=excluded.graded_at""",
            (assignment_id, student_id, score, feedback, current_user.id, now_iso()))
    flash(f"评分已保存：{score} 分。", "success")
    return redirect(url_for("assignment_detail", assignment_id=assignment_id) + "#grading")


@app.post("/assignments/<int:assignment_id>/submissions/<int:submission_id>/delete")
@login_required
def delete_submission(assignment_id, submission_id):
    submission = query("""SELECT s.*,u.display_name student_name FROM submissions s
                        JOIN users u ON u.id=s.student_id WHERE s.id=? AND s.assignment_id=?""",
                       (submission_id, assignment_id), one=True)
    if not submission: abort(404)
    if current_user.role != "teacher" and submission["student_id"] != current_user.id: abort(403)
    write_audit("delete", "submission", submission_id, assignment_id, submission["student_id"],
                {"file_url": submission["file_url"], "version": submission["version"],
                 "student_name": submission["student_name"]})
    execute("DELETE FROM submissions WHERE id=?", (submission_id,))
    execute("""INSERT INTO discussions(assignment_id,user_id,content,kind,created_at)
               VALUES (?,?,?,'system',?)""",
            (assignment_id, current_user.id,
             f"{current_user.name} 删除了 {submission['student_name']} 的作业版本 v{submission['version']}", now_iso()))
    flash("提交记录已删除，操作已写入审计日志。", "success")
    return redirect(url_for("assignment_detail", assignment_id=assignment_id) + "#activity")


@app.post("/assignments/<int:assignment_id>/delete")
@teacher_required
def delete_assignment(assignment_id):
    assignment = query("SELECT * FROM assignments WHERE id=?", (assignment_id,), one=True)
    if not assignment: abort(404)
    submission_count = query("SELECT COUNT(*) n FROM submissions WHERE assignment_id=?", (assignment_id,), one=True)["n"]
    write_audit("delete", "assignment", assignment_id, assignment_id, details={
        "title": assignment["title"], "submission_count": submission_count,
        "status": assignment["status"], "snapshot": dict(assignment),
    })
    execute("DELETE FROM assignments WHERE id=?", (assignment_id,))
    flash("任务已删除，任务摘要和删除记录已保留。", "success")
    return redirect(url_for("assignments_page"))


@app.get("/audit-log")
@login_required
def audit_log_page():
    if current_user.role in ("teacher", "assistant"):
        logs = query("""SELECT l.*,u.display_name actor_name,s.display_name student_name
                      FROM audit_logs l JOIN users u ON u.id=l.actor_id
                      LEFT JOIN users s ON s.id=l.student_id ORDER BY l.created_at DESC LIMIT 300""")
    else:
        logs = query("""SELECT l.*,u.display_name actor_name,s.display_name student_name
                      FROM audit_logs l JOIN users u ON u.id=l.actor_id
                      LEFT JOIN users s ON s.id=l.student_id
                      WHERE l.student_id=? ORDER BY l.created_at DESC LIMIT 100""", (current_user.id,))
    return render_template("audit_log.html", logs=logs)


@app.post("/assignments/<int:assignment_id>/close")
@teacher_required
def close_assignment(assignment_id):
    assignment = query("SELECT * FROM assignments WHERE id=?", (assignment_id,), one=True)
    if not assignment: abort(404)
    status = "open" if assignment["status"] == "closed" else "closed"
    execute("UPDATE assignments SET status=? WHERE id=?", (status, assignment_id))
    execute("INSERT INTO discussions(assignment_id,user_id,content,kind,created_at) VALUES (?,?,?,'system',?)",
            (assignment_id, current_user.id, f"{current_user.name} {'重新打开' if status == 'open' else '关闭'}了任务", now_iso()))
    return redirect(url_for("assignment_detail", assignment_id=assignment_id))


@app.get("/uploads/<path:filename>")
@login_required
def uploaded_file(filename):
    return send_from_directory(UPLOAD_DIR, filename, as_attachment=True)


@app.get("/analytics")
@login_required
def analytics_page():
    if current_user.role in ("teacher", "assistant"):
        students = query("SELECT * FROM users WHERE role='student' ORDER BY display_name")
    else:
        students = query("SELECT * FROM users WHERE id=?", (current_user.id,))
    return render_template("analytics.html", students=students)


@app.get("/students")
@login_required
def students_page():
    where, params = ("WHERE u.role='student'", ()) if current_user.role in ("teacher", "assistant") else (
        "WHERE u.role='student' AND u.id=?", (current_user.id,))
    students = query(
        f"""SELECT u.id,u.username,u.display_name,u.created_at,u.last_login_at,
        sg.name group_name,CASE WHEN sg.leader_id=u.id THEN 1 ELSE 0 END is_group_leader,
        (SELECT COUNT(*) FROM discussions d WHERE d.user_id=u.id AND d.kind='comment') discussion_count,
        (SELECT COUNT(DISTINCT assignment_id) FROM submissions s WHERE s.student_id=u.id) submission_count,
        (SELECT COUNT(DISTINCT exam_id) FROM exam_submissions es WHERE es.student_id=u.id) exam_submission_count,
        (SELECT COUNT(*) FROM exams) exam_total
        FROM users u LEFT JOIN group_members gm ON gm.user_id=u.id
        LEFT JOIN study_groups sg ON sg.id=gm.group_id
        {where} ORDER BY CASE WHEN sg.name IS NULL THEN 1 ELSE 0 END,sg.name,
        is_group_leader DESC,u.display_name COLLATE NOCASE,u.username COLLATE NOCASE""", params)
    assignments = query("SELECT assignee_usernames FROM assignments")
    result = []
    for row in students:
        item = dict(row)
        item["assigned_count"] = sum(item["username"] in json.loads(a["assignee_usernames"] or "[]") for a in assignments)
        result.append(item)
    grouped_students = []
    if current_user.role in ("teacher", "assistant"):
        for item in result:
            group_name = item["group_name"] or "未分组"
            if not grouped_students or grouped_students[-1]["name"] != group_name:
                grouped_students.append({"name": group_name, "students": []})
            grouped_students[-1]["students"].append(item)
    return render_template("students.html", students=result, grouped_students=grouped_students)


@app.route("/settings", methods=["GET", "POST"])
@login_required
def user_settings():
    if request.method == "POST":
        display_name = request.form.get("display_name", "").strip()
        if not 2 <= len(display_name) <= 50:
            flash("真实姓名需为 2 到 50 个字符。", "danger")
        else:
            execute("UPDATE users SET display_name=? WHERE id=?", (display_name, current_user.id))
            flash("真实姓名已更新。", "success")
            return redirect(url_for("user_settings"))
    profile = query("""SELECT u.*,sg.name group_name,CASE WHEN sg.leader_id=u.id THEN 1 ELSE 0 END is_group_leader
                     FROM users u LEFT JOIN group_members gm ON gm.user_id=u.id
                     LEFT JOIN study_groups sg ON sg.id=gm.group_id WHERE u.id=?""", (current_user.id,), one=True)
    return render_template("settings.html", profile=profile)


@app.route("/groups", methods=["GET", "POST"])
@login_required
def groups_page():
    if request.method == "POST":
        if current_user.role != "teacher": abort(403)
        name = request.form.get("name", "").strip()
        leader_id = request.form.get("leader_id", type=int)
        member_ids = {int(x) for x in request.form.getlist("member_ids") if x.isdigit()}
        if leader_id: member_ids.add(leader_id)
        valid_ids = {x["id"] for x in query("SELECT id FROM users WHERE role='student'")}
        if not name or not leader_id or leader_id not in valid_ids or not member_ids or not member_ids <= valid_ids:
            flash("请填写组名并选择有效的组长和成员。", "danger")
        elif query("SELECT id FROM study_groups WHERE name=?", (name,), one=True):
            flash("小组名称已存在。", "danger")
        else:
            occupied = query(f"SELECT user_id FROM group_members WHERE user_id IN ({','.join('?' for _ in member_ids)})", tuple(member_ids))
            if occupied:
                flash("所选学生中有人已加入其他小组。", "danger")
            else:
                group_id = execute("INSERT INTO study_groups(name,leader_id,created_by,created_at) VALUES (?,?,?,?)",
                                   (name, leader_id, current_user.id, now_iso()))
                for user_id in member_ids:
                    execute("INSERT INTO group_members(group_id,user_id) VALUES (?,?)", (group_id, user_id))
                flash("学习小组已创建。", "success")
                return redirect(url_for("groups_page"))
    students = query("""SELECT u.*,gm.group_id FROM users u LEFT JOIN group_members gm ON gm.user_id=u.id
                      WHERE u.role='student' ORDER BY u.display_name""") if current_user.role == "teacher" else []
    group_where, params = ("", ()) if current_user.role == "teacher" else (
        "WHERE sg.id IN (SELECT group_id FROM group_members WHERE user_id=?)", (current_user.id,))
    groups = query(f"""SELECT sg.*,u.display_name leader_name,u.username leader_username,
                     (SELECT COUNT(*) FROM group_members gm WHERE gm.group_id=sg.id) member_count
                     FROM study_groups sg JOIN users u ON u.id=sg.leader_id {group_where} ORDER BY sg.name""", params)
    result = []
    for group in groups:
        item = dict(group)
        item["members"] = query("""SELECT u.*,CASE WHEN u.id=? THEN 1 ELSE 0 END is_leader
                                 FROM group_members gm JOIN users u ON u.id=gm.user_id
                                 WHERE gm.group_id=? ORDER BY is_leader DESC,u.display_name""", (group["leader_id"], group["id"]))
        item["messages"] = query("""SELECT gm.*,u.display_name user_name,u.username,u.role
                                  FROM group_messages gm JOIN users u ON u.id=gm.user_id
                                  WHERE gm.group_id=? ORDER BY gm.created_at DESC LIMIT 50""", (group["id"],))
        item["messages"] = list(reversed(item["messages"]))
        result.append(item)
    return render_template("groups.html", groups=result, students=students)


@app.post("/groups/<int:group_id>/messages")
@login_required
def add_group_message(group_id):
    group = query("SELECT id,name FROM study_groups WHERE id=?", (group_id,), one=True)
    if not group:
        abort(404)
    if current_user.role != "teacher":
        membership = query("SELECT 1 ok FROM group_members WHERE group_id=? AND user_id=?",
                           (group_id, current_user.id), one=True)
        if not membership:
            abort(403)
    content = request.form.get("content", "").strip()
    if not content:
        flash("请输入交流内容。", "warning")
    elif len(content) > 2000:
        flash("单条消息不能超过 2000 个字符。", "danger")
    else:
        execute("INSERT INTO group_messages(group_id,user_id,content,created_at) VALUES (?,?,?,?)",
                (group_id, current_user.id, content, now_iso()))
    return redirect(url_for("groups_page") + f"#group-{group_id}")


def insert_bank_questions(questions, source, source_file=None):
    inserted = []
    for item in questions:
        question_id = execute(
            """INSERT INTO question_bank(question_type,prompt,options,answer,points,source,source_file,status,created_by,created_at)
               VALUES (?,?,?,?,?,?,?,'ready',?,?)""",
            (item["type"], item["prompt"], json.dumps(item.get("options", []), ensure_ascii=False),
             str(item.get("answer", "")), item.get("points", 0), source, source_file,
             current_user.id, now_iso()))
        inserted.append(question_id)
    return inserted


@app.route("/question-bank", methods=["GET", "POST"])
@teacher_required
def question_bank_page():
    if request.method == "POST":
        source_file = request.files.get("source_file")
        if not source_file or not source_file.filename:
            flash("请选择 PDF、Word 题库文件。", "danger")
        elif Path(source_file.filename).suffix.lower() not in {".pdf", ".docx"}:
            flash("题库自动识别支持 PDF、DOCX；旧版 DOC 请先另存为 DOCX。", "danger")
        else:
            original_name = source_file.filename
            try:
                file_url = save_upload(source_file, "exams")
            except ValueError as exc:
                flash(str(exc), "danger")
            else:
                import_id = execute(
                    """INSERT INTO question_bank(question_type,prompt,options,source,source_file,status,created_by,created_at)
                       VALUES ('essay',?,'[]','upload',?,'pending',?,?)""",
                    (f"待识别：{original_name}", file_url, current_user.id, now_iso()))
                try:
                    document_text = extract_document_text(UPLOAD_DIR / file_url)
                    raw_questions = recognize_document_questions(app.config, document_text, original_name)
                    questions = normalize_questions(json.dumps(raw_questions, ensure_ascii=False))
                    if not questions:
                        raise DeepSeekError("文档中没有识别到有效题目")
                    insert_bank_questions(questions, "deepseek_recognized", file_url)
                    execute("DELETE FROM question_bank WHERE id=?", (import_id,))
                except (DeepSeekError, ValueError, OSError) as exc:
                    execute("UPDATE question_bank SET status='failed' WHERE id=?", (import_id,))
                    flash(f"题库识别失败：{exc}", "danger")
                else:
                    record_course_event("question_import", "question_bank", import_id, original_name,
                                        f"{current_user.name} 通过 DeepSeek 从文档识别并导入了 {len(questions)} 道题")
                    flash(f"DeepSeek 已从文件识别并导入 {len(questions)} 道题。", "success")
                return redirect(url_for("question_bank_page"))
    ready_rows = query("""SELECT qb.*,u.display_name creator_name FROM question_bank qb
                          JOIN users u ON u.id=qb.created_by WHERE qb.status='ready'
                          ORDER BY qb.created_at DESC""")
    ready = []
    for row in ready_rows:
        item = dict(row)
        try:
            item["options_list"] = json.loads(item["options"] or "[]")
        except json.JSONDecodeError:
            item["options_list"] = []
        ready.append(item)
    imports = query("""SELECT qb.*,u.display_name creator_name FROM question_bank qb
                       JOIN users u ON u.id=qb.created_by WHERE qb.status!='ready'
                       ORDER BY qb.created_at DESC""")
    return render_template("question_bank.html", questions=ready, imports=imports)


@app.post("/api/question-bank/imports/<int:import_id>/complete")
@teacher_required
def complete_question_import(import_id):
    import_item = query("SELECT * FROM question_bank WHERE id=? AND status='pending'", (import_id,), one=True)
    if not import_item:
        return jsonify({"error": "import_not_found"}), 404
    payload = request.get_json(silent=True) or {}
    raw_questions = payload.get("questions", [])
    try:
        questions = normalize_questions(json.dumps(raw_questions, ensure_ascii=False))
    except (ValueError, TypeError) as exc:
        execute("UPDATE question_bank SET status='failed' WHERE id=?", (import_id,))
        return jsonify({"error": str(exc)}), 400
    if not questions:
        return jsonify({"error": "no_questions"}), 400
    insert_bank_questions(questions, "api_recognized", import_item["source_file"])
    execute("DELETE FROM question_bank WHERE id=?", (import_id,))
    return jsonify({"ok": True, "imported": len(questions)})


@app.post("/api/question-bank/generate")
@teacher_required
def generate_question_bank():
    payload = request.get_json(silent=True) or {}
    supplied = payload.get("questions")
    if supplied is not None:
        try:
            questions = normalize_questions(json.dumps(supplied, ensure_ascii=False))
        except (ValueError, TypeError) as exc:
            return jsonify({"error": str(exc)}), 400
    else:
        topic = str(payload.get("topic", "")).strip()
        try:
            count = min(max(int(payload.get("count", 5) or 5), 1), 20)
        except (TypeError, ValueError):
            return jsonify({"error": "invalid_question_count"}), 400
        question_type = str(payload.get("type", "essay"))
        if not topic or question_type not in {"single", "multiple", "true_false", "fill", "essay"}:
            return jsonify({"error": "invalid_generation_request"}), 400
        try:
            raw_questions = generate_questions(app.config, topic, count, question_type)
            questions = normalize_questions(json.dumps(raw_questions, ensure_ascii=False))
        except (DeepSeekError, ValueError, TypeError) as exc:
            return jsonify({"error": str(exc)}), 502
    ids = insert_bank_questions(questions, "api_generated")
    return jsonify({"ok": True, "created": len(ids), "ids": ids})


@app.post("/question-bank/<int:question_id>/delete")
@teacher_required
def delete_question_bank_item(question_id):
    item = query("SELECT id,prompt FROM question_bank WHERE id=?", (question_id,), one=True)
    if not item:
        abort(404)
    write_audit("delete", "question_bank", question_id, details={"prompt": item["prompt"]})
    execute("DELETE FROM question_bank WHERE id=?", (question_id,))
    flash("题目已从题库删除。", "success")
    return redirect(url_for("question_bank_page"))


@app.route("/exams", methods=["GET", "POST"])
@login_required
def exams_page():
    exam_draft = get_draft("exam_new", "new") if current_user.role == "teacher" else None
    if request.method == "POST":
        if current_user.role != "teacher": abort(403)
        title = request.form.get("title", "").strip()
        category = request.form.get("category", "quiz")
        mode = request.form.get("mode", "paper")
        start_at, end_at = request.form.get("start_at", ""), request.form.get("end_at", "")
        instructions = request.form.get("instructions", "").strip()
        questions = request.form.get("questions", "").strip()
        question_data_raw = request.form.get("question_data", "[]")
        bank_ids = [int(value) for value in request.form.getlist("bank_question_ids") if value.isdigit()]
        duration_minutes = request.form.get("duration_minutes", type=int) or 60
        try:
            start_time, end_time = datetime.fromisoformat(start_at), datetime.fromisoformat(end_at)
            paper_url = save_upload(request.files.get("paper"), "exams") or (exam_draft["file_url"] if exam_draft else None)
            question_data = normalize_questions(question_data_raw) if mode == "computer" else []
            if mode == "computer" and bank_ids:
                marks = ",".join("?" for _ in bank_ids)
                bank_rows = query(f"SELECT * FROM question_bank WHERE status='ready' AND id IN ({marks})", tuple(bank_ids))
                bank_questions = [{"type": row["question_type"], "prompt": row["prompt"],
                                   "options": json.loads(row["options"] or "[]"), "points": row["points"]}
                                  for row in bank_rows]
                question_data = normalize_questions(json.dumps(bank_questions + question_data, ensure_ascii=False))
        except (ValueError, TypeError) as exc:
            flash(str(exc) if str(exc) else "考试时间或文件无效。", "danger")
        else:
            if not title or category not in {"quiz", "midterm", "final"} or mode not in {"paper", "computer"} or end_time <= start_time or not 1 <= duration_minutes <= 1440:
                flash("请完整填写考试信息，并确保结束时间晚于开始时间。", "danger")
            elif mode == "paper" and not paper_url:
                flash("纸笔考试请上传试卷文件。", "danger")
            elif mode == "computer" and not question_data:
                flash("机考请至少创建一道网页题目。", "danger")
            else:
                exam_id = execute("""INSERT INTO exams(title,category,mode,start_at,end_at,paper_url,instructions,questions,
                           duration_minutes,question_data,created_by,created_at)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (title, category, mode, start_at, end_at, paper_url, instructions, questions,
                         duration_minutes, json.dumps(question_data, ensure_ascii=False), current_user.id, now_iso()))
                category_name = {"quiz": "随堂测试", "midterm": "期中考试", "final": "期末考试"}[category]
                record_course_event("exam_publish", "exam", exam_id, title,
                                    f"{current_user.name} 发布了{category_name}，共 {len(question_data)} 题")
                delete_draft("exam_new", "new")
                flash("考试已发布。", "success")
                return redirect(url_for("exams_page"))
    exams = query("""SELECT e.*,u.display_name creator_name,
                    (SELECT COUNT(*) FROM exam_submissions es WHERE es.exam_id=e.id) submitted_count
                    FROM exams e JOIN users u ON u.id=e.created_by ORDER BY e.start_at DESC""")
    submissions = {}
    if current_user.role == "student":
        submissions = {x["exam_id"]: x for x in query("SELECT * FROM exam_submissions WHERE student_id=?", (current_user.id,))}
    now = datetime.now()
    exam_items = []
    for row in exams:
        item = dict(row); start = datetime.fromisoformat(item["start_at"]); end = datetime.fromisoformat(item["end_at"])
        item["phase"] = "upcoming" if now < start else "active" if now <= end else "ended"
        item["submission"] = submissions.get(item["id"])
        item["draft"] = get_draft("exam_answer", item["id"]) if current_user.role == "student" else None
        item["grade"] = query("SELECT * FROM exam_grades WHERE exam_id=? AND student_id=?",
                              (item["id"], current_user.id), one=True) if current_user.role == "student" else None
        try: item["question_count"] = len(json.loads(item["question_data"] or "[]"))
        except json.JSONDecodeError: item["question_count"] = 0
        exam_items.append(item)
    total_count = len(exam_items)
    completed_count = (sum(item["phase"] == "ended" for item in exam_items) if current_user.role in ("teacher", "assistant")
                       else sum(bool(item["submission"]) for item in exam_items))
    question_bank = query("SELECT * FROM question_bank WHERE status='ready' ORDER BY created_at DESC") if current_user.role == "teacher" else []
    return render_template("exams.html", exams=exam_items, exam_draft=exam_draft, question_bank=question_bank,
                           total_count=total_count, completed_count=completed_count,
                           completion_percent=round(completed_count / max(total_count, 1) * 100))


@app.get("/exams/<int:exam_id>/submissions")
@staff_required
def exam_submissions_page(exam_id):
    exam = query("SELECT e.*,u.display_name creator_name FROM exams e JOIN users u ON u.id=e.created_by WHERE e.id=?",
                 (exam_id,), one=True)
    if not exam:
        abort(404)
    try:
        questions = normalize_questions(exam["question_data"] or exam["questions"]) if exam["mode"] == "computer" else []
    except ValueError:
        questions = []
    rows = query("""SELECT es.*,u.display_name student_name,u.username,
                    eg.score,eg.feedback,eg.graded_at
                    FROM exam_submissions es JOIN users u ON u.id=es.student_id
                    LEFT JOIN exam_grades eg ON eg.exam_id=es.exam_id AND eg.student_id=es.student_id
                    WHERE es.exam_id=? ORDER BY u.display_name COLLATE NOCASE,u.username COLLATE NOCASE""", (exam_id,))
    submissions = []
    for row in rows:
        item = dict(row)
        if exam["mode"] == "computer":
            try:
                answers = json.loads(item["answer_text"] or "{}")
            except json.JSONDecodeError:
                answers = {}
            item["answers"] = [{"question": question, "answer": answers.get(question["id"], "")}
                               for question in questions]
        submissions.append(item)
    return render_template("exam_submissions.html", exam=exam, questions=questions, submissions=submissions)


@app.post("/exams/<int:exam_id>/submissions/<int:student_id>/grade")
@staff_required
def grade_exam_submission(exam_id, student_id):
    submission = query("SELECT id FROM exam_submissions WHERE exam_id=? AND student_id=?",
                       (exam_id, student_id), one=True)
    if not submission:
        abort(404)
    score = request.form.get("score", type=int)
    feedback = request.form.get("feedback", "").strip()
    if score is None or not 0 <= score <= 100:
        flash("考试成绩必须为 0 到 100 分。", "danger")
    else:
        execute("""INSERT INTO exam_grades(exam_id,student_id,score,feedback,graded_by,graded_at)
                   VALUES (?,?,?,?,?,?) ON CONFLICT(exam_id,student_id) DO UPDATE SET
                   score=excluded.score,feedback=excluded.feedback,graded_by=excluded.graded_by,graded_at=excluded.graded_at""",
                (exam_id, student_id, score, feedback, current_user.id, now_iso()))
        exam = query("SELECT title FROM exams WHERE id=?", (exam_id,), one=True)
        write_audit("grade", "exam_submission", submission["id"], student_id=student_id,
                    details={"exam_id": exam_id, "score": score, "feedback": feedback})
        record_course_event("exam_grade", "exam", exam_id, exam["title"],
                            f"{current_user.name} 完成了一份考试答卷评分")
        flash("考试成绩已保存，学生端已可查看。", "success")
    return redirect(url_for("exam_submissions_page", exam_id=exam_id) + f"#student-{student_id}")


@app.post("/exams/<int:exam_id>/submit")
@login_required
def submit_exam(exam_id):
    if current_user.role != "student": abort(403)
    exam = query("SELECT * FROM exams WHERE id=?", (exam_id,), one=True)
    if not exam: abort(404)
    now = datetime.now()
    if not datetime.fromisoformat(exam["start_at"]) <= now <= datetime.fromisoformat(exam["end_at"]):
        flash("当前不在考试作答时间内。", "warning")
        return redirect(url_for("exams_page"))
    attempt = query("SELECT * FROM exam_attempts WHERE exam_id=? AND student_id=?",
                    (exam_id, current_user.id), one=True)
    if exam["mode"] == "computer" and not attempt:
        flash("请先进入机考页面开始考试。", "warning"); return redirect(url_for("exams_page"))
    answers = {key.removeprefix("answer_"): request.form.getlist(key) if len(request.form.getlist(key)) > 1 else request.form.get(key, "")
               for key in request.form if key.startswith("answer_")}
    answer = json.dumps(answers, ensure_ascii=False) if exam["mode"] == "computer" else request.form.get("answer_text", "").strip()
    answer_draft = get_draft("exam_answer", exam_id)
    try: file_url = save_upload(request.files.get("answer_file"), "exams") or (answer_draft["file_url"] if answer_draft else None)
    except ValueError as exc:
        flash(str(exc), "danger"); return redirect(url_for("exams_page"))
    if exam["mode"] == "computer" and attempt and attempt["submitted_at"]:
        flash("该机考已经交卷。", "warning"); return redirect(url_for("exams_page"))
    if exam["mode"] == "paper" and not file_url:
        flash("请上传答卷。", "danger"); return redirect(url_for("exams_page"))
    execute("""INSERT INTO exam_submissions(exam_id,student_id,answer_text,file_url,submitted_at)
               VALUES (?,?,?,?,?) ON CONFLICT(exam_id,student_id) DO UPDATE SET
               answer_text=excluded.answer_text,file_url=COALESCE(excluded.file_url,exam_submissions.file_url),submitted_at=excluded.submitted_at""",
            (exam_id, current_user.id, answer, file_url, now_iso()))
    if exam["mode"] == "computer":
        deadline = datetime.fromisoformat(attempt["deadline_at"])
        reason = "manual" if now < deadline else "time_limit"
        execute("UPDATE exam_attempts SET answers=?,submitted_at=?,submit_reason=? WHERE id=?",
                (answer, now_iso(), reason, attempt["id"]))
    record_course_event("exam_submit", "exam", exam_id, exam["title"],
                        f"{current_user.name} 提交了考试答卷")
    delete_draft("exam_answer", exam_id)
    flash("考试答案已提交。", "success")
    return redirect(url_for("exams_page"))


@app.get("/exams/<int:exam_id>/take")
@login_required
def take_exam(exam_id):
    if current_user.role != "student": abort(403)
    exam = query("SELECT * FROM exams WHERE id=? AND mode='computer'", (exam_id,), one=True)
    if not exam: abort(404)
    now = datetime.now(); start = datetime.fromisoformat(exam["start_at"]); end = datetime.fromisoformat(exam["end_at"])
    if now < start or now > end:
        flash("当前不在机考开放时间内。", "warning"); return redirect(url_for("exams_page"))
    attempt = query("SELECT * FROM exam_attempts WHERE exam_id=? AND student_id=?", (exam_id, current_user.id), one=True)
    if not attempt:
        deadline = attempt_deadline(now, end, exam["duration_minutes"])
        attempt_id = execute("INSERT INTO exam_attempts(exam_id,student_id,started_at,deadline_at) VALUES (?,?,?,?)",
                             (exam_id, current_user.id, now_iso(), deadline.replace(microsecond=0).isoformat()))
        attempt = query("SELECT * FROM exam_attempts WHERE id=?", (attempt_id,), one=True)
        record_course_event("exam_start", "exam", exam_id, exam["title"],
                            f"{current_user.name} 开始了网页机考")
    if attempt["submitted_at"]:
        flash("该机考已交卷。", "warning"); return redirect(url_for("exams_page"))
    deadline = datetime.fromisoformat(attempt["deadline_at"])
    if now >= deadline:
        execute("UPDATE exam_attempts SET submitted_at=?,submit_reason='time_limit' WHERE id=?", (now_iso(), attempt["id"]))
        execute("""INSERT INTO exam_submissions(exam_id,student_id,answer_text,submitted_at) VALUES (?,?,?,?)
                   ON CONFLICT(exam_id,student_id) DO UPDATE SET answer_text=excluded.answer_text,submitted_at=excluded.submitted_at""",
                (exam_id, current_user.id, attempt["answers"], now_iso()))
        record_course_event("exam_submit", "exam", exam_id, exam["title"],
                            f"{current_user.name} 的考试已到时自动交卷")
        flash("考试时间已到，系统已自动交卷。", "warning"); return redirect(url_for("exams_page"))
    try: questions = normalize_questions(exam["question_data"] or exam["questions"])
    except ValueError: questions = []
    try: saved_answers = json.loads(attempt["answers"] or "{}")
    except json.JSONDecodeError: saved_answers = {}
    return render_template("exam_take.html", exam=exam, questions=questions, attempt=attempt,
                           saved_answers=saved_answers, deadline_ms=int(deadline.timestamp() * 1000))


@app.post("/api/exams/<int:exam_id>/answers")
@login_required
def save_exam_answers(exam_id):
    if current_user.role != "student": abort(403)
    attempt = query("SELECT * FROM exam_attempts WHERE exam_id=? AND student_id=?", (exam_id, current_user.id), one=True)
    if not attempt or attempt["submitted_at"]: return jsonify({"error": "attempt_unavailable"}), 409
    now = datetime.now()
    if now >= datetime.fromisoformat(attempt["deadline_at"]): return jsonify({"error": "time_expired"}), 409
    answers = (request.get_json(silent=True) or {}).get("answers", {})
    if not isinstance(answers, dict): return jsonify({"error": "invalid_answers"}), 400
    execute("UPDATE exam_attempts SET answers=? WHERE id=?", (json.dumps(answers, ensure_ascii=False), attempt["id"]))
    return jsonify({"ok": True, "saved_at": now_iso()})


@app.route("/api/drafts/<draft_type>/<context_key>", methods=["GET", "POST", "DELETE"])
@login_required
def draft_api(draft_type, context_key):
    allowed = {
        "assignment_new": "teacher", "exam_new": "teacher",
        "assignment_submission": "student", "exam_answer": "student",
    }
    if draft_type not in allowed or current_user.role != allowed[draft_type]: abort(403)
    if draft_type == "assignment_submission":
        target = query("SELECT id FROM assignments WHERE id=?", (context_key,), one=True)
        if not target: abort(404)
    if draft_type == "exam_answer":
        target = query("SELECT id FROM exams WHERE id=?", (context_key,), one=True)
        if not target: abort(404)
    if request.method == "GET":
        draft = get_draft(draft_type, context_key)
        return jsonify(draft or {})
    if request.method == "DELETE":
        delete_draft(draft_type, context_key)
        return jsonify({"ok": True})
    if request.content_type and request.content_type.startswith("multipart/form-data"):
        raw = request.form.get("data", "{}")
        try: data = json.loads(raw)
        except json.JSONDecodeError: return jsonify({"error": "invalid_data"}), 400
        file = request.files.get("file")
    else:
        data = request.get_json(silent=True) or {}; file = None
    if not isinstance(data, dict): return jsonify({"error": "invalid_data"}), 400
    try: draft = save_draft(draft_type, context_key, data, file)
    except ValueError as exc: return jsonify({"error": str(exc)}), 400
    return jsonify({"ok": True, "updated_at": draft["updated_at"],
                    "file_name": draft["file_name"], "file_url": draft["file_url"]})


def analysis_for(user):
    activity = query("""SELECT
        (SELECT COUNT(*) FROM discussions WHERE user_id=? AND kind='comment') question_count,
        (SELECT COUNT(DISTINCT assignment_id) FROM submissions WHERE student_id=?) submitted_tasks,
        (SELECT COUNT(*) FROM assignments) total_tasks""", (user["id"], user["id"]), one=True)
    engagement = "active" if activity["question_count"] >= 2 else "normal"
    ratio = activity["submitted_tasks"] / max(activity["total_tasks"], 1)
    return {"username": user["username"], "name": user["display_name"],
            "mastery": {"overall_score": round(.55 + min(activity["question_count"] * .05, .15) + ratio * .25, 2),
                        "weak_topics": ["任务规划", "知识迁移"], "engagement": engagement,
                        "suggestion": "建议结合近期提问安排针对性练习，并及时完成未提交任务。"},
            "activity": dict(activity), "generated_at": now_iso()}


@app.get("/api/auth/me")
@login_required
def api_auth_me():
    return jsonify({"id": current_user.id, "username": current_user.username,
                    "display_name": current_user.display_name, "role": current_user.role})


@app.get("/api/students")
@login_required
def api_students():
    rows = query(
        """SELECT u.username,u.display_name,u.created_at,u.last_login_at,
        (SELECT COUNT(*) FROM discussions d WHERE d.user_id=u.id AND d.kind='comment') discussion_count,
        (SELECT COUNT(*) FROM submissions s WHERE s.student_id=u.id) submission_count
        FROM users u WHERE u.role='student' ORDER BY u.display_name,u.username"""
    )
    return jsonify([dict(row) for row in rows])


@app.post("/api/auth/login")
def api_auth_login():
    data = request.get_json(silent=True) or {}
    username, password = str(data.get("username", "")).strip(), str(data.get("password", ""))
    remember = bool(data.get("remember", False))
    until = locked_until(username) if username else None
    if until: return jsonify({"error": "temporarily_locked", "retry_at": until.isoformat()}), 429
    if not username or not password or not pam_authenticate(username, password):
        if username: record_login_failure(username)
        return jsonify({"error": "invalid_credentials"}), 401
    execute("DELETE FROM login_failures WHERE username=?", (username,))
    role = role_for_linux_user(username)
    existing = query("SELECT * FROM users WHERE username=?", (username,), one=True)
    if existing:
        execute("UPDATE users SET role=?,last_login_at=? WHERE id=?", (role, now_iso(), existing["id"])); user_id = existing["id"]
    else:
        user_id = execute("INSERT INTO users(username,display_name,role,created_at,last_login_at) VALUES (?,?,?,?,?)",
                          (username, username, role, now_iso(), now_iso()))
    login_user(User(query("SELECT * FROM users WHERE id=?", (user_id,), one=True)),
               remember=remember, duration=app.config["REMEMBER_COOKIE_DURATION"])
    return api_auth_me()


@app.post("/api/auth/logout")
@login_required
def api_auth_logout():
    logout_user()
    return jsonify({"ok": True})


@app.get("/api/assignments")
@login_required
def api_assignments():
    return jsonify([hydrate_assignment(x) for x in query("SELECT * FROM assignments ORDER BY due_date")])


@app.post("/api/assignments")
@teacher_required
def api_assignment_create():
    data = request.get_json(silent=True) or {}
    if not data.get("title") or not data.get("description"): return jsonify({"error": "required_fields"}), 400
    assignment_id = execute("""INSERT INTO assignments(title,description,due_date,created_by,status,created_at,labels,assignee_usernames)
        VALUES (?,?,?,?,'open',?,?,?)""", (data["title"], data["description"], data.get("due_date"), current_user.id,
        now_iso(), json.dumps(data.get("labels", []), ensure_ascii=False), json.dumps(data.get("assignees", []))))
    return jsonify({"id": assignment_id}), 201


@app.get("/api/assignments/<int:assignment_id>")
@login_required
def api_assignment_detail(assignment_id):
    item = hydrate_assignment(query("SELECT * FROM assignments WHERE id=?", (assignment_id,), one=True))
    return jsonify(item) if item else (jsonify({"error": "not_found"}), 404)


@app.get("/api/assignments/<int:assignment_id>/discussions")
@login_required
def api_discussions(assignment_id):
    rows = query("""SELECT d.*,u.username,u.display_name,u.role FROM discussions d
                  JOIN users u ON u.id=d.user_id WHERE assignment_id=? ORDER BY d.created_at""", (assignment_id,))
    return jsonify([dict(x) for x in rows])


@app.post("/api/assignments/<int:assignment_id>/discussions")
@login_required
def api_discussion_create(assignment_id):
    data = request.get_json(silent=True) or {}; content = str(data.get("content", "")).strip()
    if not content: return jsonify({"error": "content_required"}), 400
    discussion_id = execute("INSERT INTO discussions(assignment_id,user_id,parent_id,content,created_at) VALUES (?,?,?,?,?)",
                            (assignment_id, current_user.id, data.get("parent_id"), content, now_iso()))
    return jsonify({"id": discussion_id}), 201


@app.post("/api/assignments/<int:assignment_id>/chat")
@login_required
def api_assignment_chat(assignment_id):
    assignment = query("SELECT * FROM assignments WHERE id=?", (assignment_id,), one=True)
    if not assignment: return jsonify({"error": "not_found"}), 404
    data = request.get_json(silent=True) or {}; message = str(data.get("message", "")).strip()
    history = data.get("history", [])
    if not message: return jsonify({"error": "message_required"}), 400
    recent = query("SELECT content FROM discussions WHERE assignment_id=? ORDER BY created_at DESC LIMIT 5", (assignment_id,))
    context = {"title": assignment["title"], "description": assignment["description"],
               "recent_discussions": [x["content"] for x in recent], "history": history[-10:]}
    try:
        reply = assignment_assistant(app.config, context, message, history)
    except DeepSeekError as exc:
        return jsonify({"error": str(exc)}), 502
    generated = now_iso()
    execute("INSERT INTO chat_logs(assignment_id,user_id,message,reply,created_at) VALUES (?,?,?,?,?)",
            (assignment_id, current_user.id, message, reply, generated))
    return jsonify({"reply": reply, "generated_at": generated})


@app.post("/api/assignments/<int:assignment_id>/submissions")
@login_required
def api_submission_create(assignment_id):
    if current_user.role != "student": return jsonify({"error": "student_required"}), 403
    try: filename = save_upload(request.files.get("file"))
    except ValueError as exc: return jsonify({"error": str(exc)}), 400
    if not filename: return jsonify({"error": "file_required"}), 400
    version = query("SELECT COALESCE(MAX(version),0)+1 n FROM submissions WHERE assignment_id=? AND student_id=?",
                    (assignment_id, current_user.id), one=True)["n"]
    submission_id = execute("INSERT INTO submissions(assignment_id,student_id,file_url,submitted_at,version) VALUES (?,?,?,?,?)",
                            (assignment_id, current_user.id, filename, now_iso(), version))
    return jsonify({"id": submission_id, "file_url": f"/uploads/{filename}", "version": version}), 201


@app.post("/api/analyze")
@login_required
def api_analyze():
    data = request.get_json(silent=True) or request.form
    username = current_user.username if current_user.role == "student" else str(data.get("username", "")).strip()
    user = query("SELECT * FROM users WHERE username=? AND role='student'", (username,), one=True)
    if not user: return jsonify({"error": "student_not_found"}), 404
    report = analysis_for(user)
    try:
        ai_analysis = enhance_learning_analysis(app.config, report)
    except DeepSeekError as exc:
        return jsonify({"error": str(exc)}), 502
    weak_topics = ai_analysis.get("weak_topics")
    if isinstance(weak_topics, list) and weak_topics:
        report["mastery"]["weak_topics"] = [str(item)[:80] for item in weak_topics[:6]]
    if ai_analysis.get("suggestion"):
        report["mastery"]["suggestion"] = str(ai_analysis["suggestion"])[:1200]
    report["mastery"]["summary"] = str(ai_analysis.get("summary", ""))[:1200]
    report["ai_provider"] = "deepseek"
    execute("INSERT INTO analysis_reports(username,report,generated_at) VALUES (?,?,?)",
            (username, json.dumps(report, ensure_ascii=False), report["generated_at"]))
    return jsonify(report)


@app.errorhandler(413)
def too_large(_error):
    if request.path.startswith("/api/"): return jsonify({"error": "file_too_large"}), 413
    flash("文件不能超过 20MB。", "danger"); return redirect(request.referrer or url_for("home"))


if __name__ == "__main__":
    with app.app_context(): init_db()
    app.run(host=app.config["HOST"], port=app.config["PORT"], debug=app.config["DEBUG"])
