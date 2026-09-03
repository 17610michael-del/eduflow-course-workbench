"""Back up and reset the EduFlow production SQLite database."""
from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import sqlite3
import sys


TABLES = {
    "ai_chat_logs",
    "analysis_reports",
    "assignment_groups",
    "assignments",
    "audit_logs",
    "chat_logs",
    "course_events",
    "deepseek_workbench_messages",
    "deepseek_workbench_sessions",
    "discussions",
    "drafts",
    "exam_attempts",
    "exam_grades",
    "exam_submissions",
    "exams",
    "grades",
    "group_members",
    "group_messages",
    "knowledge_chat_logs",
    "knowledge_chunks",
    "knowledge_documents",
    "login_failures",
    "project_agents",
    "project_snapshots",
    "question_bank",
    "study_groups",
    "submissions",
    "users",
}

DELETE_ORDER = [
    "deepseek_workbench_messages",
    "deepseek_workbench_sessions",
    "knowledge_chat_logs",
    "knowledge_chunks",
    "knowledge_documents",
    "project_snapshots",
    "project_agents",
    "chat_logs",
    "ai_chat_logs",
    "analysis_reports",
    "exam_grades",
    "exam_attempts",
    "exam_submissions",
    "exams",
    "question_bank",
    "grades",
    "submissions",
    "discussions",
    "assignment_groups",
    "assignments",
    "group_messages",
    "group_members",
    "study_groups",
    "drafts",
    "course_events",
    "audit_logs",
    "login_failures",
]


def table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }


def check_database(connection: sqlite3.Connection) -> None:
    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        raise RuntimeError(f"integrity_check failed: {integrity}")
    foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
    if foreign_keys:
        raise RuntimeError(f"foreign_key_check found {len(foreign_keys)} errors")
    actual = table_names(connection)
    if actual != TABLES:
        raise RuntimeError(
            "schema mismatch; missing="
            f"{sorted(TABLES - actual)}, unexpected={sorted(actual - TABLES)}"
        )


def counts(connection: sqlite3.Connection) -> dict[str, int]:
    return {
        table: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        for table in sorted(TABLES)
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True, type=pathlib.Path)
    parser.add_argument("--backup", required=True, type=pathlib.Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    if not args.database.is_file():
        raise RuntimeError(f"database not found: {args.database}")
    if args.backup.exists():
        raise RuntimeError(f"backup already exists: {args.backup}")
    args.backup.parent.mkdir(parents=True, exist_ok=True)

    source = sqlite3.connect(args.database)
    source.execute("PRAGMA foreign_keys=ON")
    check_database(source)
    before = counts(source)
    print("RESET_DATABASE_DRY_RUN")
    print("USERS_BEFORE=" + str(before["users"]))
    print("BUSINESS_ROWS_BEFORE=" + str(sum(before.values()) - before["users"]))
    if not args.apply:
        source.close()
        return 0

    backup = sqlite3.connect(args.backup)
    source.backup(backup)
    backup.close()
    verified_backup = sqlite3.connect(f"file:{args.backup}?mode=ro", uri=True)
    check_database(verified_backup)
    backup_counts = counts(verified_backup)
    verified_backup.close()
    if backup_counts != before:
        raise RuntimeError("backup row counts do not match source")

    source.execute("PRAGMA secure_delete=ON")
    source.execute("BEGIN IMMEDIATE")
    try:
        for table in DELETE_ORDER:
            source.execute(f'DELETE FROM "{table}"')
        source.execute("DELETE FROM users WHERE username <> 'kltst'")
        now = dt.datetime.now().replace(microsecond=0).isoformat()
        row = source.execute("SELECT id FROM users WHERE username='kltst'").fetchone()
        if row is None:
            source.execute(
                "INSERT INTO users(username,display_name,role,created_at,last_login_at) "
                "VALUES ('kltst','kltst','teacher',?,NULL)",
                (now,),
            )
        else:
            source.execute(
                "UPDATE users SET display_name='kltst',role='teacher',last_login_at=NULL "
                "WHERE username='kltst'"
            )
        source.execute(
            "INSERT INTO users(username,display_name,role,created_at,last_login_at) "
            "VALUES ('wsst','wsst','teacher',?,NULL)",
            (now,),
        )
        failures = source.execute("PRAGMA foreign_key_check").fetchall()
        if failures:
            raise RuntimeError(f"post-reset foreign key errors: {len(failures)}")
        source.commit()
    except Exception:
        source.rollback()
        raise

    source.execute("VACUUM")
    source.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    check_database(source)
    after = counts(source)
    if after["users"] != 2 or any(
        count for table, count in after.items() if table != "users"
    ):
        raise RuntimeError(f"unexpected post-reset counts: {after}")
    users = source.execute("SELECT username,role FROM users ORDER BY username").fetchall()
    if users != [("kltst", "teacher"), ("wsst", "teacher")]:
        raise RuntimeError(f"unexpected retained users: {users}")
    source.close()
    args.backup.chmod(0o600)
    print("RESET_DATABASE_OK users=2 business_rows=0")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"RESET_DATABASE_FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
