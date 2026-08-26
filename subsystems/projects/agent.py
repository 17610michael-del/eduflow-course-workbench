#!/usr/bin/env python3
"""Read-only EduFlow project agent. Runs as the student Linux account."""
from __future__ import annotations

import argparse
import json
import os
import pwd
import shutil
import socket
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


AGENT_VERSION = "1.0"
EXCLUDED_DIRS = {
    ".cache", ".config", ".local", ".npm", ".ssh", ".vscode-server",
    "anaconda3", "miniconda3", "node_modules", "venv", ".venv", "__pycache__",
}
MAX_FILES_PER_PROJECT = 5000
MAX_PROJECTS = 100


def iso_time(timestamp=None):
    moment = datetime.fromtimestamp(timestamp, timezone.utc) if timestamp else datetime.now(timezone.utc)
    return moment.replace(microsecond=0).isoformat()


def run_git(project: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(project), *args], capture_output=True, text=True,
            timeout=5, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def git_status(project: Path) -> dict:
    is_repo = run_git(project, "rev-parse", "--is-inside-work-tree") == "true"
    if not is_repo:
        return {"is_repository": False}
    commit_data = run_git(project, "log", "-1", "--format=%H%x1f%cI%x1f%s").split("\x1f")
    status = run_git(project, "status", "--porcelain")
    return {
        "is_repository": True,
        "branch": run_git(project, "branch", "--show-current") or "detached",
        "commit": commit_data[0] if commit_data else "",
        "commit_at": commit_data[1] if len(commit_data) > 1 else "",
        "commit_message": commit_data[2] if len(commit_data) > 2 else "",
        "changed_files": len(status.splitlines()) if status else 0,
    }


def project_manifest(project: Path) -> dict:
    target = project / ".eduflow-project.json"
    if not target.is_file() or target.stat().st_size > 64 * 1024:
        return {}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {"status": data.get("status", ""), "progress": data.get("progress", 0), "updated": data.get("updated", "")}


def scan_project(project: Path, workspace: Path) -> dict:
    file_count = total_size = 0
    latest = project.stat().st_mtime
    truncated = False
    for root, dirs, files in os.walk(project, followlinks=False):
        dirs[:] = [name for name in dirs if name not in EXCLUDED_DIRS and name != ".git" and not (Path(root) / name).is_symlink()]
        for name in files:
            target = Path(root) / name
            try:
                if target.is_symlink():
                    continue
                info = target.stat()
            except OSError:
                continue
            file_count += 1
            total_size += info.st_size
            latest = max(latest, info.st_mtime)
            if file_count >= MAX_FILES_PER_PROJECT:
                truncated = True
                dirs[:] = []
                break
    return {
        "name": project.name,
        "path": project.relative_to(workspace).as_posix(),
        "last_modified": iso_time(latest),
        "file_count": file_count,
        "total_size": total_size,
        "scan_truncated": truncated,
        "running_processes": 0,
        "git": git_status(project),
        "manifest": project_manifest(project),
    }


def own_processes(workspace: Path, projects: list[dict]) -> list[dict]:
    by_path = {item["path"]: item for item in projects}
    found = []
    proc = Path("/proc")
    if not proc.is_dir():
        return found
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if entry.stat().st_uid != os.getuid():
                continue
            cwd = (entry / "cwd").resolve(strict=True)
            relative = cwd.relative_to(workspace)
            project_name = relative.parts[0] if relative.parts else ""
            if project_name not in by_path:
                continue
            name = (entry / "comm").read_text(encoding="utf-8").strip()[:120]
        except (OSError, ValueError, UnicodeDecodeError):
            continue
        by_path[project_name]["running_processes"] += 1
        found.append({"pid": int(entry.name), "name": name, "project": project_name})
        if len(found) >= 100:
            break
    return found


def collect(workspace: Path) -> dict:
    workspace = workspace.expanduser().resolve(strict=True)
    if not workspace.is_dir():
        raise RuntimeError("workspace is not a directory")
    candidates = []
    for item in sorted(workspace.iterdir(), key=lambda path: path.name.lower()):
        if len(candidates) >= MAX_PROJECTS:
            break
        if item.name.startswith(".") or item.name in EXCLUDED_DIRS or item.is_symlink() or not item.is_dir():
            continue
        candidates.append(item)
    projects = [scan_project(project, workspace) for project in candidates]
    disk = shutil.disk_usage(workspace)
    return {
        "agent_version": AGENT_VERSION,
        "hostname": socket.gethostname(),
        "workspace": str(workspace),
        "captured_at": iso_time(),
        "projects": projects,
        "processes": own_processes(workspace, projects),
        "disk": {"total": disk.total, "used": disk.used, "free": disk.free},
    }


def read_token(path: Path) -> str:
    info = path.stat()
    if stat.S_IMODE(info.st_mode) & 0o077:
        raise RuntimeError("token file permissions must be 600")
    token = path.read_text(encoding="utf-8").strip()
    if not token.startswith("epm_"):
        raise RuntimeError("invalid token file")
    return token


def send_report(server: str, token: str, report: dict) -> dict:
    request = urllib.request.Request(
        server.rstrip("/") + "/api/project-agent/report",
        data=json.dumps(report, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"server rejected report (HTTP {exc.code})") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError("cannot reach EduFlow server") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="EduFlow local project monitor")
    parser.add_argument("--server", default="http://127.0.0.1:8000")
    parser.add_argument("--token-file", required=True, type=Path)
    parser.add_argument("--workspace", default=f"/data/{pwd.getpwuid(os.getuid()).pw_name}", type=Path)
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    interval = max(30, args.interval)
    while True:
        try:
            token = read_token(args.token_file)
            report = collect(args.workspace)
            result = send_report(args.server, token, report)
            print(f"[{iso_time()}] reported {len(report['projects'])} project(s): {result.get('status', 'ok')}", flush=True)
        except Exception as exc:
            print(f"[{iso_time()}] report failed: {exc}", file=sys.stderr, flush=True)
            if args.once:
                return 1
        if args.once:
            return 0
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
