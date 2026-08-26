"""Provision a deterministic HMAC project-agent token without printing it."""
from __future__ import annotations

import argparse
import ast
import os
import pwd
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

from subsystems.projects.services import issue_agent_token  # noqa: E402


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if value[:1] in {"'", '"'} and value[-1:] == value[:1]:
            try:
                value = str(ast.literal_eval(value))
            except (SyntaxError, ValueError):
                value = value[1:-1]
        values[key] = value
    return values


def write_token(username: str, token: str) -> Path:
    account = pwd.getpwnam(username)
    config_dir = Path(account.pw_dir) / ".config"
    token_dir = config_dir / "eduflow-monitor"
    token_file = token_dir / "token"
    config_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    token_dir.mkdir(mode=0o700, exist_ok=True)
    os.chown(config_dir, account.pw_uid, account.pw_gid)
    os.chown(token_dir, account.pw_uid, account.pw_gid)
    os.chmod(token_dir, 0o700)
    temporary = token_dir / f".token.{os.getpid()}"
    try:
        temporary.write_text(token + "\n", encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.chown(temporary, account.pw_uid, account.pw_gid)
        os.replace(temporary, token_file)
    finally:
        if temporary.exists():
            temporary.unlink()
    return token_file


def register_agent(database: Path, username: str, token_hash: str, workspace: str) -> None:
    """Write SQLite as its owning service account, never as root."""
    database_owner = database.stat()
    original_uid, original_gid = os.geteuid(), os.getegid()
    connection = None
    try:
        os.setegid(database_owner.st_gid)
        os.seteuid(database_owner.st_uid)
        connection = sqlite3.connect(database)
        connection.execute("PRAGMA foreign_keys=ON")
        user = connection.execute(
            "SELECT id,role FROM users WHERE username=?", (username,)
        ).fetchone()
        if not user or user[1] != "student":
            raise ValueError(f"EduFlow 中不存在学生账号：{username}")
        existing = connection.execute(
            "SELECT id FROM project_agents WHERE user_id=?", (user[0],)
        ).fetchone()
        if existing:
            connection.execute(
                "UPDATE project_agents SET token_hash=?,workspace_root=?,enabled=1 WHERE id=?",
                (token_hash, workspace, existing[0]),
            )
        else:
            connection.execute(
                """INSERT INTO project_agents
                   (user_id,token_hash,workspace_root,enabled,created_at)
                   VALUES (?,?,?,1,?)""",
                (user[0], token_hash, workspace, datetime.now(timezone.utc).isoformat()),
            )
        connection.commit()
    finally:
        if connection is not None:
            connection.close()
        os.seteuid(original_uid)
        os.setegid(original_gid)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("username")
    parser.add_argument("--env-file", type=Path, default=APP_DIR / ".env")
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("请由 root 通过 sudo 执行")

    env = load_env(args.env_file)
    secret = env.get("PROJECT_AGENT_TOKEN_SECRET") or env.get("SECRET_KEY")
    database_value = env.get("DATABASE")
    if not secret or not database_value:
        parser.error(".env 缺少 SECRET_KEY 或 DATABASE")
    database = Path(database_value)
    if not database.is_absolute():
        database = APP_DIR / database

    token, token_hash = issue_agent_token(args.username, secret)
    workspace = f"/data/{args.username}"
    try:
        register_agent(database, args.username, token_hash, workspace)
    except ValueError as exc:
        parser.error(str(exc))
    try:
        write_token(args.username, token)
    except KeyError:
        parser.error(f"Linux 中不存在用户：{args.username}")
    print(f"已安全配置：{args.username} -> {workspace}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
