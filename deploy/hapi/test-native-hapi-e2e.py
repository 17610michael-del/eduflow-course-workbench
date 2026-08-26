#!/usr/bin/env python3
"""EduFlow native-DeepSeek HAPI end-to-end test (runs on 193 as kltst).
Reads hub token from the 0600 access.env file; never prints secrets."""
import json
import sys
import time
import urllib.request
import urllib.error
import os

BASE = "http://127.0.0.1:32099"
ACCESS_ENV = "/data/kltst/homework/services/hapi/test-instance/access.env"
WORKSPACE = "/data/kltst/hapi-ds-test"
ESCAPE_TARGET = "/data/kltst/escape.txt"

token = None
with open(ACCESS_ENV) as fh:
    for line in fh:
        if line.startswith("HAPI_HUB_TOKEN="):
            token = line.strip().split("=", 1)[1]
if not token:
    sys.exit("no token in access.env")


def req(method, path, body=None, jwt=None, expect_error=False):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    if jwt:
        r.add_header("Authorization", "Bearer " + jwt)
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        if expect_error:
            return exc.code, json.loads(exc.read().decode() or "{}")
        raise


results = []

def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(("PASS" if ok else "FAIL") + f"  {name}" + (f"  ({detail})" if detail else ""))


# 1. auth
status, data = req("POST", "/api/auth", {"accessToken": token})
jwt = data.get("token")
check("auth-token-exchange", status == 200 and bool(jwt))

# 2. machines
status, data = req("GET", "/api/machines", jwt=jwt)
machines = data.get("machines", [])
check("runner-machine-online", status == 200 and len(machines) >= 1, f"{len(machines)} machine(s)")
machine_id = machines[0]["id"]

# 3. spawn deepseek session
status, data = req("POST", f"/api/machines/{machine_id}/spawn", {
    "directory": WORKSPACE,
    "agent": "deepseek",
    "model": "deepseek-v4-flash",
    "sessionType": "simple",
}, jwt=jwt)
session_id = data.get("sessionId") or (data.get("session") or {}).get("id")
check("spawn-deepseek-session", status == 200 and bool(session_id), f"status={status} session={session_id}")
if not session_id:
    print(json.dumps(data)[:500])
    sys.exit(1)

time.sleep(3)


def get_messages(limit=200):
    _, payload = req("GET", f"/api/sessions/{session_id}/messages?limit={limit}", jwt=jwt)
    return payload.get("messages", payload if isinstance(payload, list) else [])


def wait_turn_done(timeout=300):
    """Wait until message count is stable across 3 polls and at least one message exists."""
    last_count = -1
    stable = 0
    deadline = time.time() + timeout
    while time.time() < deadline:
        msgs = get_messages()
        count = len(msgs)
        if count == last_count and count > 0:
            stable += 1
            if stable >= 3:
                return msgs
        else:
            stable = 0
        last_count = count
        time.sleep(4)
    return get_messages()


def send(text):
    status, _ = req("POST", f"/api/sessions/{session_id}/messages", {"text": text}, jwt=jwt)
    return status == 200


# 4. create + read file via DeepSeek
hello_path = os.path.join(WORKSPACE, "hello.txt")
if os.path.exists(hello_path):
    os.remove(hello_path)
check("send-create-prompt", send("请在当前项目根目录创建文件 hello.txt，内容为一行：hello deepseek。创建后用 read_file 读取确认。"))
msgs = wait_turn_done()
ok_file = os.path.isfile(hello_path)
content = open(hello_path, encoding="utf-8").read().strip() if ok_file else ""
check("deepseek-created-file", ok_file and "hello deepseek" in content, repr(content[:60]))

# 5. modify file via DeepSeek
check("send-modify-prompt", send("请把 hello.txt 的内容改为：hello eduflow（仍然只有一行）。"))
msgs = wait_turn_done()
content = open(hello_path, encoding="utf-8").read().strip() if os.path.isfile(hello_path) else ""
check("deepseek-modified-file", "hello eduflow" in content, repr(content[:60]))

# 6. path escape must be rejected
if os.path.exists(ESCAPE_TARGET):
    os.remove(ESCAPE_TARGET)
check("send-escape-prompt", send("请使用 write_file 在 ../escape.txt 写入 forbidden。"))
msgs = wait_turn_done()
check("path-escape-blocked", not os.path.exists(ESCAPE_TARGET))

# 7. model switching
status, _ = req("POST", f"/api/sessions/{session_id}/model", {"model": "deepseek-v4-pro"}, jwt=jwt)
check("switch-to-v4-pro", status == 200, f"status={status}")
status, _ = req("POST", f"/api/sessions/{session_id}/model", {"model": "gpt-5"}, jwt=jwt, expect_error=True)
check("reject-unsupported-model", status in (400, 409), f"status={status}")

# 8. cleanup workspace test file
try:
    os.remove(hello_path)
except OSError:
    pass

failed = [r for r in results if not r[1]]
print(f"\n{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
