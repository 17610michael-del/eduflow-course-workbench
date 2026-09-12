"""Prepare isolated single-course environment files without printing secrets.

Supports the three 193 instances:
  degree         -> main .env (port 80 / backend 8000)
  bioinformatics -> 生信（研） (port 8081 / backend 8001)
  bio_undergrad  -> 生信（本） (port 8082 / backend 8002)
"""
from __future__ import annotations

import argparse
import os
import pathlib
import secrets


def read_env(path: pathlib.Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value
    return values


def format_env_value(value: str) -> str:
    # bash `source` and systemd EnvironmentFile both accept double-quoted values.
    if any(ch in value for ch in (" ", "\t", "#")):
        return '"' + value.replace('"', '\\"') + '"'
    return value


def update_env(path: pathlib.Path, updates: dict[str, str]) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    seen: set[str] = set()
    output: list[str] = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else ""
        if key in updates:
            if key not in seen:
                output.append(f"{key}={format_env_value(updates[key])}")
                seen.add(key)
        else:
            output.append(line)
    for key, value in updates.items():
        if key not in seen:
            output.append(f"{key}={format_env_value(value)}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text("\n".join(output) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def csv_union(value: str, required: set[str]) -> str:
    return ",".join(sorted({item.strip() for item in value.split(",") if item.strip()} | required))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--main-env", required=True, type=pathlib.Path)
    parser.add_argument("--bio-env", required=True, type=pathlib.Path)
    parser.add_argument("--bio-data", required=True, type=pathlib.Path)
    parser.add_argument("--slug", choices=["bioinformatics", "bio_undergrad"], default="bioinformatics")
    parser.add_argument("--course-name", default="生信（研）")
    parser.add_argument("--course-badge", default="BIO-G")
    parser.add_argument("--subtitle", default="193 内网服务器 · 8081")
    parser.add_argument("--backend-port", default="8001")
    parser.add_argument("--cookie-tag", default="bio")
    parser.add_argument("--users-key", default="BIOINFORMATICS_USERS")
    parser.add_argument("--assistants-key", default="BIOINFORMATICS_ASSISTANTS")
    args = parser.parse_args()

    main_values = read_env(args.main_env)
    existing_bio = read_env(args.bio_env)

    update_env(args.main_env, {
        "COURSE_ONLY_SLUG": "degree",
        "ASSISTANTS": "kltst",
        "SESSION_COOKIE_NAME": "eduflow_degree_session",
        "REMEMBER_COOKIE_NAME": "eduflow_degree_remember",
        "LOGIN_HINT_COOKIE_PREFIX": "degree_",
        "SEED_DEMO_DATA": "0",
    })

    bio_users = existing_bio.get(args.users_key, "")
    allowed = csv_union(bio_users, {"kltst", "wsst"})
    updates = {
        "SECRET_KEY": existing_bio.get("SECRET_KEY") or secrets.token_hex(32),
        "PROJECT_AGENT_TOKEN_SECRET": existing_bio.get("PROJECT_AGENT_TOKEN_SECRET") or secrets.token_hex(32),
        "COURSE_NAME": args.course_name,
        "COURSE_SUBTITLE": args.subtitle,
        "COURSE_BADGE": args.course_badge,
        "COURSE_ONLY_SLUG": args.slug,
        "DATABASE": str(args.bio_data / "app.db"),
        "UPLOAD_FOLDER": str(args.bio_data / "uploads"),
        "SERVER_SUBMISSION_ROOT": str(args.bio_data / "server-files"),
        "TEACHERS": "wsst",
        "ASSISTANTS": "kltst",
        "DEGREE_USERS": "",
        "BIOINFORMATICS_USERS": existing_bio.get("BIOINFORMATICS_USERS", ""),
        "BIOINFORMATICS_ASSISTANTS": existing_bio.get("BIOINFORMATICS_ASSISTANTS", ""),
        "BIO_UNDERGRAD_USERS": existing_bio.get("BIO_UNDERGRAD_USERS", ""),
        "BIO_UNDERGRAD_ASSISTANTS": existing_bio.get("BIO_UNDERGRAD_ASSISTANTS", ""),
        args.users_key: bio_users,
        args.assistants_key: "kltst",
        "ALLOWED_USERS": allowed,
        "TEACHER_GROUP": main_values.get("TEACHER_GROUP", "teacher"),
        "ASSISTANT_GROUP": main_values.get("ASSISTANT_GROUP", "assistant"),
        "DEEPSEEK_BASE_URL": main_values.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        "DEEPSEEK_CHAT_MODEL": main_values.get("DEEPSEEK_CHAT_MODEL", "deepseek-v4-flash"),
        "DEEPSEEK_REASONING_MODEL": main_values.get("DEEPSEEK_REASONING_MODEL", "deepseek-v4-pro"),
        "DEEPSEEK_3066_MENU_ENABLED": "0",
        "HAPI_SERVER_HOST": main_values.get("HAPI_SERVER_HOST", "10.98.103.193"),
        "HAPI_PORT_BASE": "33000",
        "HAPI_PUBLIC_URL_TEMPLATE": "",
        "HOST": "127.0.0.1",
        "PORT": args.backend_port,
        "FLASK_DEBUG": "0",
        # The 8081/8082 entries are plain HTTP on the internal network.
        "SESSION_COOKIE_SECURE": "0",
        "SESSION_COOKIE_NAME": f"eduflow_{args.cookie_tag}_session",
        "REMEMBER_COOKIE_NAME": f"eduflow_{args.cookie_tag}_remember",
        "LOGIN_HINT_COOKIE_PREFIX": f"{args.cookie_tag}_",
        "SEED_DEMO_DATA": "0",
    }
    update_env(args.bio_env, updates)
    for directory in (args.bio_data, args.bio_data / "uploads", args.bio_data / "server-files"):
        directory.mkdir(parents=True, exist_ok=True)
    print(f"BIO_INSTANCE_ENV_READY slug={args.slug} path={args.bio_env} data={args.bio_data}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
