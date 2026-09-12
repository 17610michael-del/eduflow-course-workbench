"""Manage one course instance's student roster and keep ALLOWED_USERS in sync.

Examples (on 193, as kltst; no sudo needed, restart the service afterwards):
    # 生信（研）: replace whole roster
    venv/bin/python deploy/set_course_roster.py \
        --env /data/kltst/homework/data-bio/.env --students "test_s1,s2026001"

    # 学位+: add / remove students
    venv/bin/python deploy/set_course_roster.py --env .env --add "s2025001"
    venv/bin/python deploy/set_course_roster.py --env .env --remove "s2025099"

    # show current roster
    venv/bin/python deploy/set_course_roster.py --env /data/kltst/homework/data-bio-u/.env --show
"""
from __future__ import annotations

import argparse
import os
import pathlib

STAFF = {"kltst", "wsst"}
COURSE_KEYS = {
    "degree": "DEGREE_USERS",
    "bioinformatics": "BIOINFORMATICS_USERS",
    "bio_undergrad": "BIO_UNDERGRAD_USERS",
}


def parse_csv(value: str) -> set[str]:
    return {x.strip() for x in value.split(",") if x.strip()}


def read_env(path: pathlib.Path) -> tuple[list[str], dict[str, str]]:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    values: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"')
    return lines, values


def write_env(path: pathlib.Path, lines: list[str], updates: dict[str, str]) -> None:
    seen: set[str] = set()
    output: list[str] = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else ""
        if key in updates:
            if key not in seen:
                output.append(f"{key}={updates[key]}")
                seen.add(key)
        else:
            output.append(line)
    for key, value in updates.items():
        if key not in seen:
            output.append(f"{key}={value}")
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text("\n".join(output) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", required=True, type=pathlib.Path)
    parser.add_argument("--students", help="完整替换学生名单（逗号分隔）")
    parser.add_argument("--add", help="追加学生（逗号分隔）")
    parser.add_argument("--remove", help="移出学生（逗号分隔）")
    parser.add_argument("--show", action="store_true")
    args = parser.parse_args()

    lines, values = read_env(args.env)
    slug = values.get("COURSE_ONLY_SLUG", "degree") or "degree"
    users_key = COURSE_KEYS[slug]
    roster = parse_csv(values.get(users_key, "")) - STAFF

    if args.show or not any([args.students is not None, args.add, args.remove]):
        print(f"env={args.env} course={slug} key={users_key}")
        print("students=" + (",".join(sorted(roster)) or "(empty)"))
        print("allowed=" + values.get("ALLOWED_USERS", ""))
        return 0

    if args.students is not None:
        roster = parse_csv(args.students) - STAFF
    if args.add:
        roster |= parse_csv(args.add) - STAFF
    if args.remove:
        roster -= parse_csv(args.remove)

    updates = {
        users_key: ",".join(sorted(roster)),
        "ALLOWED_USERS": ",".join(sorted(STAFF | roster)),
    }
    write_env(args.env, lines, updates)
    print(f"ROSTER_UPDATED course={slug} students={updates[users_key] or '(empty)'}")
    print(f"ALLOWED_USERS={updates['ALLOWED_USERS']}")
    print("请重启对应服务使名单生效（homework / homework-bio / homework-bio-u）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
