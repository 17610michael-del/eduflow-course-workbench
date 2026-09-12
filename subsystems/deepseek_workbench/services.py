from __future__ import annotations

import json
import re
from pathlib import Path


SAFE_TEXT_SUFFIXES = {
    ".c", ".cc", ".cpp", ".css", ".csv", ".go", ".h", ".hpp", ".html",
    ".ini", ".java", ".js", ".json", ".jsx", ".md", ".php", ".py", ".r",
    ".rb", ".rs", ".sh", ".sql", ".toml", ".ts", ".tsx", ".txt", ".xml",
    ".yaml", ".yml",
}
BLOCKED_NAMES = {
    ".env", ".git", ".ssh", ".gnupg", "id_rsa", "id_ed25519", "credentials",
    "credentials.json", "secrets.json", "access.env",
}
MAX_FILE_BYTES = 200_000
MAX_LIST_ENTRIES = 200
MAX_SEARCH_FILES = 250
MAX_SEARCH_RESULTS = 40


WORKBENCH_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "List files and directories inside the current student's isolated project workspace.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Workspace-relative directory; use . for root"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a safe text/code file inside the current student's isolated workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "start_line": {"type": "integer", "minimum": 1},
                    "end_line": {"type": "integer", "minimum": 1},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_text",
            "description": "Search literal text in safe text/code files inside the isolated workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "path": {"type": "string", "description": "Workspace-relative directory; use . for root"},
                },
                "required": ["query"],
            },
        },
    },
]

WORKBENCH_WRITE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create or overwrite a safe text/code file inside the isolated project workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Project-relative file path"},
                    "content": {"type": "string", "description": "Complete UTF-8 file content"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Replace exact text in an existing safe text/code file inside the project.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_text": {"type": "string", "description": "Exact existing text to replace"},
                    "new_text": {"type": "string", "description": "Replacement text"},
                    "replace_all": {"type": "boolean", "description": "Replace every occurrence; defaults to false"},
                },
                "required": ["path", "old_text", "new_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_directory",
            "description": "Create a new directory, including missing parent directories, inside the isolated project.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Project-relative directory path"}},
                "required": ["path"],
            },
        },
    },
]

PROJECT_WORKBENCH_TOOLS = WORKBENCH_TOOLS + WORKBENCH_WRITE_TOOLS


def workspace_for_username(base_root, username):
    if not re.fullmatch(r"[a-z_][a-z0-9_-]*", str(username)):
        raise ValueError("invalid workspace username")
    base = Path(base_root).resolve()
    target = (base / username).resolve()
    if target.parent != base:
        raise ValueError("workspace escaped base root")
    return target


def _safe_target(root, relative_path="."):
    root = Path(root).resolve()
    raw = str(relative_path or ".").strip().replace("\\", "/")
    if raw.startswith("/") or "\x00" in raw:
        raise ValueError("路径必须相对于个人工作区")
    target = (root / raw).resolve()
    if target != root and root not in target.parents:
        raise ValueError("路径超出个人工作区")
    relative_parts = target.relative_to(root).parts if target != root else ()
    if any(part.startswith(".") or part.lower() in BLOCKED_NAMES for part in relative_parts):
        raise ValueError("该路径属于受保护内容")
    return target


def list_directory(root, relative_path="."):
    root = Path(root).resolve()
    target = _safe_target(root, relative_path)
    if not target.exists():
        raise ValueError("目录不存在")
    if not target.is_dir():
        raise ValueError("路径不是目录")
    entries = []
    for child in sorted(target.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
        if child.is_symlink() or child.name.startswith(".") or child.name.lower() in BLOCKED_NAMES:
            continue
        try:
            resolved = child.resolve()
            if resolved != root and root not in resolved.parents:
                continue
            entries.append({
                "name": child.name,
                "path": str(child.relative_to(root)).replace("\\", "/"),
                "type": "directory" if child.is_dir() else "file",
                "size": child.stat().st_size if child.is_file() else None,
            })
        except OSError:
            continue
        if len(entries) >= MAX_LIST_ENTRIES:
            break
    return entries


def read_file(root, relative_path, start_line=1, end_line=None):
    root = Path(root).resolve()
    target = _safe_target(root, relative_path)
    if not target.is_file() or target.is_symlink():
        raise ValueError("文件不存在")
    if target.name.lower() in BLOCKED_NAMES or target.suffix.lower() not in SAFE_TEXT_SUFFIXES:
        raise ValueError("该文件类型不允许读取")
    if target.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("文件超过 200KB，请指定更小文件")
    lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    start = max(int(start_line or 1), 1)
    end = min(int(end_line or (start + 399)), len(lines), start + 399)
    selected = [f"{index}: {lines[index - 1]}" for index in range(start, end + 1)]
    return {"path": str(target.relative_to(root)).replace("\\", "/"), "start_line": start,
            "end_line": end, "total_lines": len(lines), "content": "\n".join(selected)}


def search_text(root, query, relative_path="."):
    root = Path(root).resolve()
    needle = str(query or "").strip()
    if not needle or len(needle) > 200:
        raise ValueError("搜索词长度必须为 1-200 个字符")
    target = _safe_target(root, relative_path)
    if not target.is_dir():
        raise ValueError("搜索路径不是目录")
    results, scanned = [], 0
    for candidate in sorted(target.rglob("*")):
        if scanned >= MAX_SEARCH_FILES or len(results) >= MAX_SEARCH_RESULTS:
            break
        if not candidate.is_file() or candidate.is_symlink():
            continue
        try:
            relative = candidate.relative_to(root)
        except ValueError:
            continue
        if any(part.startswith(".") or part.lower() in BLOCKED_NAMES for part in relative.parts):
            continue
        if candidate.suffix.lower() not in SAFE_TEXT_SUFFIXES:
            continue
        try:
            if candidate.stat().st_size > MAX_FILE_BYTES:
                continue
            scanned += 1
            for line_number, line in enumerate(candidate.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if needle.lower() in line.lower():
                    results.append({"path": str(relative).replace("\\", "/"), "line": line_number, "text": line[:500]})
                    if len(results) >= MAX_SEARCH_RESULTS:
                        break
        except OSError:
            continue
    return {"query": needle, "results": results, "scanned_files": scanned}


def write_file(root, relative_path, content):
    root = Path(root).resolve()
    target = _safe_target(root, relative_path)
    if target.exists() and (not target.is_file() or target.is_symlink()):
        raise ValueError("目标路径不是普通文件")
    if target.name.lower() in BLOCKED_NAMES or target.suffix.lower() not in SAFE_TEXT_SUFFIXES:
        raise ValueError("该文件类型不允许写入")
    if not target.parent.is_dir() or target.parent.is_symlink():
        raise ValueError("父目录不存在，请先创建目录")
    text = str(content)
    encoded = text.encode("utf-8")
    if len(encoded) > MAX_FILE_BYTES:
        raise ValueError("写入内容超过 200KB")
    existed = target.exists()
    target.write_text(text, encoding="utf-8")
    return {
        "path": str(target.relative_to(root)).replace("\\", "/"),
        "created": not existed,
        "bytes": len(encoded),
    }


def edit_file(root, relative_path, old_text, new_text, replace_all=False):
    root = Path(root).resolve()
    target = _safe_target(root, relative_path)
    if not target.is_file() or target.is_symlink():
        raise ValueError("文件不存在")
    if target.name.lower() in BLOCKED_NAMES or target.suffix.lower() not in SAFE_TEXT_SUFFIXES:
        raise ValueError("该文件类型不允许修改")
    if target.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("文件超过 200KB")
    old = str(old_text)
    replacement = str(new_text)
    if not old:
        raise ValueError("old_text 不能为空")
    original = target.read_text(encoding="utf-8", errors="strict")
    occurrences = original.count(old)
    if occurrences == 0:
        raise ValueError("未找到需要替换的原文")
    if occurrences > 1 and not replace_all:
        raise ValueError("原文出现多次，请提供更精确内容或设置 replace_all")
    updated = original.replace(old, replacement, -1 if replace_all else 1)
    if len(updated.encode("utf-8")) > MAX_FILE_BYTES:
        raise ValueError("修改后文件超过 200KB")
    target.write_text(updated, encoding="utf-8")
    return {
        "path": str(target.relative_to(root)).replace("\\", "/"),
        "replacements": occurrences if replace_all else 1,
        "bytes": len(updated.encode("utf-8")),
    }


def create_directory(root, relative_path):
    root = Path(root).resolve()
    raw = str(relative_path or "").strip().replace("\\", "/")
    if not raw or raw == ".":
        raise ValueError("请输入新目录路径")
    target = _safe_target(root, raw)
    if target.exists():
        if target.is_dir() and not target.is_symlink():
            return {"path": str(target.relative_to(root)).replace("\\", "/"), "created": False}
        raise ValueError("目标路径已存在且不是目录")
    target.mkdir(parents=True, exist_ok=False)
    return {"path": str(target.relative_to(root)).replace("\\", "/"), "created": True}


def execute_workbench_tool(root, name, arguments):
    if not isinstance(arguments, dict):
        raise ValueError("工具参数无效")
    if name == "list_directory":
        return list_directory(root, arguments.get("path", "."))
    if name == "read_file":
        return read_file(root, arguments.get("path", ""), arguments.get("start_line", 1), arguments.get("end_line"))
    if name == "search_text":
        return search_text(root, arguments.get("query", ""), arguments.get("path", "."))
    if name == "write_file":
        return write_file(root, arguments.get("path", ""), arguments.get("content", ""))
    if name == "edit_file":
        return edit_file(
            root, arguments.get("path", ""), arguments.get("old_text", ""),
            arguments.get("new_text", ""), bool(arguments.get("replace_all", False)),
        )
    if name == "create_directory":
        return create_directory(root, arguments.get("path", ""))
    raise ValueError("不支持的工具")


def tool_result_text(value):
    return json.dumps(value, ensure_ascii=False)[:30_000]
