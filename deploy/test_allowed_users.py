"""Isolated tests for the fail-closed EduFlow login allowlist."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("SECRET_KEY", "allowed-users-test-import-secret")

import app as app_module


def main():
    with tempfile.TemporaryDirectory(prefix="eduflow-allowed-users-") as temporary:
        root = Path(temporary)
        app_module.DATABASE = root / "test.db"
        app_module.app.config.update(
            TESTING=True,
            SECRET_KEY="allowed-users-test-secret",
            ALLOWED_USERS={"kltst", "wsst"},
        )
        with app_module.app.app_context():
            app_module.init_db(seed=False)
            allowed_id = app_module.execute(
                "INSERT INTO users(username,display_name,role,created_at) VALUES (?,?,?,?)",
                ("kltst", "kltst", "teacher", app_module.now_iso()),
            )
            blocked_id = app_module.execute(
                "INSERT INTO users(username,display_name,role,created_at) VALUES (?,?,?,?)",
                ("michaelk", "michaelk", "student", app_module.now_iso()),
            )

        pam_calls: list[str] = []
        original_pam = app_module.pam_authenticate
        original_role = app_module.role_for_linux_user
        app_module.pam_authenticate = lambda username, _password: pam_calls.append(username) is None
        app_module.role_for_linux_user = lambda _username: "teacher"
        try:
            client = app_module.app.test_client()
            response = client.post(
                "/login", data={"username": "michaelk", "password": "not-used"}
            )
            assert response.status_code == 200
            assert pam_calls == []

            api_response = client.post(
                "/api/auth/login", json={"username": "michaelk", "password": "not-used"}
            )
            assert api_response.status_code == 401
            assert pam_calls == []

            with client.session_transaction() as session:
                session["_user_id"] = str(blocked_id)
                session["_fresh"] = True
            blocked_session = client.get("/")
            assert blocked_session.status_code == 302
            assert "/login" in blocked_session.location

            allowed_response = client.post(
                "/login", data={"username": "kltst", "password": "accepted"}
            )
            assert allowed_response.status_code == 302
            assert pam_calls == ["kltst"]
            with app_module.app.app_context():
                row = app_module.query("SELECT role FROM users WHERE id=?", (allowed_id,), one=True)
                assert row["role"] == "teacher"

            app_module.app.config["ALLOWED_USERS"] = set()
            with client.session_transaction() as session:
                session.clear()
            fail_closed = client.post(
                "/login", data={"username": "kltst", "password": "accepted"}
            )
            assert fail_closed.status_code == 200
            assert pam_calls == ["kltst"]
        finally:
            app_module.pam_authenticate = original_pam
            app_module.role_for_linux_user = original_role

    print("ALLOWED_USERS_TEST_OK")


if __name__ == "__main__":
    main()
