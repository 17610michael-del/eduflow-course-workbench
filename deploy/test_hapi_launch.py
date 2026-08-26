"""Isolated test for the EduFlow -> per-user HAPI single-sign-on launch."""
from __future__ import annotations

import os
import socket
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("SECRET_KEY", "hapi-launch-test-import-secret")

import app as app_module


class _Connection:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def main():
    with tempfile.TemporaryDirectory(prefix="eduflow-hapi-launch-") as temporary:
        root = Path(temporary)
        home = root / "student01-home"
        access_dir = home / ".config" / "eduflow-hapi"
        access_dir.mkdir(parents=True)
        token = "ehh_" + "a" * 48
        (access_dir / "access.env").write_text(
            f"HAPI_HUB_URL=http://10.98.103.193:32003\nHAPI_HUB_TOKEN={token}\n",
            encoding="utf-8",
        )

        app_module.DATABASE = root / "test.db"
        app_module.app.config.update(TESTING=True, SECRET_KEY="hapi-launch-test-secret")
        with app_module.app.app_context():
            app_module.init_db(seed=False)
            user_id = app_module.execute(
                "INSERT INTO users(username,display_name,role,created_at) VALUES (?,?,?,?)",
                ("student01", "测试学生", "student", app_module.now_iso()),
            )

        original_pwd = app_module.pwd
        original_connect = socket.create_connection
        app_module.pwd = SimpleNamespace(
            getpwnam=lambda username: SimpleNamespace(pw_uid=1003, pw_dir=str(home))
        )
        socket.create_connection = lambda *_args, **_kwargs: _Connection()
        try:
            client = app_module.app.test_client()
            with client.session_transaction() as session:
                session["_user_id"] = str(user_id)
                session["_fresh"] = True
            response = client.get("/hapi/launch")
            assert response.status_code == 302
            assert response.location == f"http://10.98.103.193:32003/#token={token}"
            assert "?token=" not in response.location
        finally:
            app_module.pwd = original_pwd
            socket.create_connection = original_connect

    print("HAPI_LAUNCH_TEST_OK")


if __name__ == "__main__":
    main()
