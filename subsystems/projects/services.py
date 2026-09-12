from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime


AGENT_VERSION = "1.0"
MAX_PROJECTS = 100
MAX_PROCESSES = 100
MAX_REPORT_BYTES = 512 * 1024


def issue_agent_token(username: str, secret: str, *, scope: str = "degree") -> tuple[str, str]:
    """Derive a stable, unguessable per-user token from a server-side secret."""
    normalized_username = str(username or "").strip()
    if not normalized_username or not secret:
        raise ValueError("username_and_secret_required")
    token_subject = normalized_username if scope == "degree" else f"{scope}:{normalized_username}"
    digest = hmac.new(
        str(secret).encode("utf-8"),
        f"eduflow-project-agent:{token_subject}".encode("utf-8"),
        hashlib.sha256,
    ).digest()
    encoded = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    token = "epm_" + encoded
    return token, hash_agent_token(token)


def hash_agent_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _text(value, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _integer(value, minimum: int = 0, maximum: int = 10**15) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = minimum
    return max(minimum, min(number, maximum))


def _timestamp(value) -> str:
    text = _text(value, 40)
    if not text:
        return ""
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return ""
    return text


def sanitize_agent_report(payload) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("invalid_report")
    projects = payload.get("projects")
    if not isinstance(projects, list):
        raise ValueError("projects_required")
    clean_projects = []
    for item in projects[:MAX_PROJECTS]:
        if not isinstance(item, dict):
            continue
        name = _text(item.get("name"), 120)
        path = _text(item.get("path"), 300)
        if not name or not path or path.startswith("/") or ".." in path.split("/"):
            continue
        git = item.get("git") if isinstance(item.get("git"), dict) else {}
        manifest = item.get("manifest") if isinstance(item.get("manifest"), dict) else {}
        clean_projects.append({
            "name": name,
            "path": path,
            "last_modified": _timestamp(item.get("last_modified")),
            "file_count": _integer(item.get("file_count"), maximum=10**8),
            "total_size": _integer(item.get("total_size")),
            "scan_truncated": bool(item.get("scan_truncated")),
            "running_processes": _integer(item.get("running_processes"), maximum=10**5),
            "git": {
                "is_repository": bool(git.get("is_repository")),
                "branch": _text(git.get("branch"), 120),
                "commit": _text(git.get("commit"), 64),
                "commit_at": _timestamp(git.get("commit_at")),
                "commit_message": _text(git.get("commit_message"), 300),
                "changed_files": _integer(git.get("changed_files"), maximum=10**6),
            },
            "manifest": {
                "status": _text(manifest.get("status"), 80),
                "progress": _integer(manifest.get("progress"), maximum=100),
                "updated": _timestamp(manifest.get("updated")),
            },
        })
    processes = []
    raw_processes = payload.get("processes")
    if isinstance(raw_processes, list):
        for item in raw_processes[:MAX_PROCESSES]:
            if not isinstance(item, dict):
                continue
            processes.append({
                "pid": _integer(item.get("pid"), maximum=10**9),
                "name": _text(item.get("name"), 120),
                "project": _text(item.get("project"), 120),
            })
    disk = payload.get("disk") if isinstance(payload.get("disk"), dict) else {}
    clean = {
        "agent_version": _text(payload.get("agent_version"), 30),
        "hostname": _text(payload.get("hostname"), 120),
        "workspace": _text(payload.get("workspace"), 400),
        "captured_at": _timestamp(payload.get("captured_at")),
        "projects": clean_projects,
        "processes": processes,
        "disk": {
            "total": _integer(disk.get("total")),
            "used": _integer(disk.get("used")),
            "free": _integer(disk.get("free")),
        },
    }
    if len(json.dumps(clean, ensure_ascii=False).encode("utf-8")) > MAX_REPORT_BYTES:
        raise ValueError("report_too_large")
    return clean


def load_snapshot(payload_text: str | None) -> dict:
    try:
        payload = json.loads(payload_text or "{}")
    except (json.JSONDecodeError, TypeError):
        return {"projects": [], "processes": [], "disk": {}}
    return payload if isinstance(payload, dict) else {"projects": [], "processes": [], "disk": {}}


def human_size(value) -> str:
    size = float(value or 0)
    units = ("B", "KB", "MB", "GB", "TB")
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return "0 B"
