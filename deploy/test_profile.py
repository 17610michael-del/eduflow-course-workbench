"""Verify the extended profile module: columns, office-schedule validation, completeness,
settings save/echo, profile-view permissions and legacy fallback."""
from __future__ import annotations

import importlib
import json
import os
import re
import sys
import tempfile
import types
from pathlib import Path

temporary = tempfile.TemporaryDirectory(prefix="eduflow-profile-")
root = Path(temporary.name)
os.environ.update({
    "SECRET_KEY": "profile-test-secret",
    "DATABASE": str(root / "profile.db"),
    "UPLOAD_FOLDER": str(root / "uploads"),
    "SERVER_SUBMISSION_ROOT": str(root / "server-files"),
    "ALLOWED_USERS": "teacher1,student1,student2",
    "TEACHERS": "teacher1",
    "ASSISTANTS": "",
    "DEGREE_USERS": "student1,student2",
    "BIOINFORMATICS_USERS": "student1,student2",
    "BIOINFORMATICS_ASSISTANTS": "",
    "BIO_UNDERGRAD_USERS": "",
    "BIO_UNDERGRAD_ASSISTANTS": "",
    "COURSE_ONLY_SLUG": "",
    "SESSION_COOKIE_NAME": "profile_session",
    "REMEMBER_COOKIE_NAME": "profile_remember",
    "LOGIN_HINT_COOKIE_PREFIX": "profile_",
})
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    import pam  # noqa: F401
except ImportError:
    pam_stub = types.ModuleType("pam")
    pam_stub.pam = lambda: None
    sys.modules["pam"] = pam_stub

app_module = importlib.import_module("app")
app = app_module.app
APP_CSS = (Path(__file__).resolve().parents[1] / "static" / "app.css").read_text(encoding="utf-8")
UG_MAJOR = "本科｜农学"
GR_MAJOR = "硕士｜083600 生物工程"
SLOT_A = {"weekday": 1, "start": "14:00", "end": "16:00", "location": "A楼302"}
SLOT_B = {"weekday": 3, "start": "09:00", "end": "10:00", "location": "B楼201"}


def _canon(slots):
    return json.dumps({"v": 1, "slots": slots}, ensure_ascii=False, separators=(",", ":"))


def _schedule_script(html):
    match = re.search(
        r'<script type="application/json" id="office-schedule-initial">(.*?)</script>',
        html, re.S,
    )
    assert match, "office-schedule-initial script not found"
    return json.loads(match.group(1))


def _rejects_parse(raw):
    try:
        app_module.parse_office_schedule(raw)
    except ValueError:
        return True
    return False


with app.app_context():
    app_module.init_db(seed=False)
    stamp = app_module.now_iso()
    teacher_id = app_module.execute(
        "INSERT INTO users(username,display_name,role,created_at) VALUES ('teacher1','teacher1','teacher',?)", (stamp,)
    )
    student1_id = app_module.execute(
        "INSERT INTO users(username,display_name,role,created_at) VALUES ('student1','student1','student',?)", (stamp,)
    )
    student2_id = app_module.execute(
        "INSERT INTO users(username,display_name,role,created_at) VALUES ('student2','student2','student',?)", (stamp,)
    )
    app_module.sync_configured_course_memberships()


def make_client(user_id, slug):
    client = app.test_client()
    with client.session_transaction() as s:
        s["_user_id"] = str(user_id)
        s["_fresh"] = True
        s["course_slug"] = slug
    return client


# 1) New columns exist on users table (office_hours kept for rollback).
assert ".schedule-editor[hidden] { display:none; }" in APP_CSS
with app.app_context():
    cols = {r["name"] for r in app_module.query("PRAGMA table_info(users)")}
    for c in ("email", "wechat", "major", "advisor", "office_hours", "office_schedule"):
        assert c in cols, f"missing users column: {c}"

# 2) Validation helpers.
assert app_module.is_valid_email("a@b.com") is True
assert app_module.is_valid_email(" student@bua.edu.cn ") is True
assert app_module.is_valid_email("graduate@lab.example.com") is True
assert app_module.is_valid_email("not-an-email") is False
assert app_module.is_valid_email("a@@b.com") is False
assert app_module.is_valid_email("a@localhost") is False
assert app_module.is_valid_email("a@b..com") is False
assert app_module.is_valid_email(".a@b.com") is False
assert app_module.is_valid_email("a.@b.com") is False
assert app_module.is_valid_email("a..b@b.com") is False
assert app_module.is_valid_email("a@-b.com") is False
assert app_module.is_valid_email(("a" * 250) + "@b.com") is False
assert app_module.is_valid_email("") is False
assert app_module.is_valid_wechat("twechat1") is True
assert app_module.is_valid_wechat("1badwechat") is False  # 数字开头
assert app_module.is_valid_wechat("ab") is False          # 过短
assert app_module.is_valid_wechat("") is False

# 3) office_schedule 解析与规范化：正常 2 组、排序、去空白。
two_raw = json.dumps({"v": 1, "slots": [
    {"weekday": 3, "start": "09:00", "end": "10:00", "location": " B楼201 "},
    {"weekday": 1, "start": "14:00", "end": "16:00", "location": "A楼302"},
]}, ensure_ascii=False)
slots, canonical = app_module.parse_office_schedule(two_raw)
assert slots == [SLOT_A, SLOT_B], slots
assert canonical == _canon([SLOT_A, SLOT_B]), canonical
assert " " not in canonical and "\n" not in canonical
# 同日不重叠 + 不同日同时间：通过且排序。
mixed_raw = json.dumps({"v": 1, "slots": [
    {"weekday": 2, "start": "14:00", "end": "16:00", "location": "B楼"},
    {"weekday": 2, "start": "16:00", "end": "17:00", "location": "C楼"},
    {"weekday": 1, "start": "14:00", "end": "16:00", "location": "A楼"},
]}, ensure_ascii=False)
mixed_slots, mixed_canonical = app_module.parse_office_schedule(mixed_raw)
assert [s["weekday"] for s in mixed_slots] == [1, 2, 2]
assert [s["start"] for s in mixed_slots] == ["14:00", "14:00", "16:00"]
assert mixed_canonical == _canon(mixed_slots)
# 模板展示 helper 对合法值给出星期标签，对任何坏值返回 [] 且不抛异常。
rows = app_module.office_schedule_rows(canonical)
assert [r["weekday_label"] for r in rows] == ["周一", "周三"]
assert app_module.office_schedule_rows("{bad json") == []
assert app_module.office_schedule_rows(None) == []
assert app_module.office_schedule_rows("") == []
assert app_module.office_schedule_rows(json.dumps({"v": 1, "slots": [{"weekday": 9}]})) == []

# 4) 非法 office_schedule 全部拒绝且只抛 ValueError。
assert _rejects_parse("{not json")                                                        # 坏 JSON
assert _rejects_parse("null")                                                             # null
assert _rejects_parse(json.dumps({"v": 2, "slots": [SLOT_A]}))                            # 错误版本
assert _rejects_parse(json.dumps({"v": 1, "slots": {"weekday": 1}}))                      # slots 非数组
assert _rejects_parse(json.dumps({"v": 1}))                                               # 缺 slots
assert _rejects_parse(json.dumps({"v": 1, "slots": []}))                                  # 0 组
assert _rejects_parse(json.dumps({"v": 1, "slots": [{"weekday": 1, "start": "14:00", "end": "16:00"}]}))  # 缺 location
assert _rejects_parse(json.dumps({"v": 1, "slots": [{"weekday": "1", "start": "14:00", "end": "16:00", "location": "A"}]}))  # weekday 字符串
assert _rejects_parse(json.dumps({"v": 1, "slots": [{"weekday": 0, "start": "14:00", "end": "16:00", "location": "A"}]}))   # weekday 越界
assert _rejects_parse(json.dumps({"v": 1, "slots": [{"weekday": 8, "start": "14:00", "end": "16:00", "location": "A"}]}))   # weekday 越界
assert _rejects_parse(json.dumps({"v": 1, "slots": [{"weekday": True, "start": "14:00", "end": "16:00", "location": "A"}]}))  # bool 拒绝
assert _rejects_parse(json.dumps({"v": 1, "slots": [{"weekday": 1, "start": "25:00", "end": "26:00", "location": "A"}]}))   # 非法时间
assert _rejects_parse(json.dumps({"v": 1, "slots": [{"weekday": 1, "start": "9:00", "end": "10:00", "location": "A"}]}))    # 非 HH:MM
assert _rejects_parse(json.dumps({"v": 1, "slots": [{"weekday": 1, "start": "16:00", "end": "16:00", "location": "A"}]}))   # start == end
assert _rejects_parse(json.dumps({"v": 1, "slots": [{"weekday": 1, "start": "17:00", "end": "16:00", "location": "A"}]}))   # start > end
assert _rejects_parse(json.dumps({"v": 1, "slots": [{"weekday": 1, "start": "14:00", "end": "16:00", "location": "   "}]})) # 地点空
assert _rejects_parse(json.dumps({"v": 1, "slots": [{"weekday": 1, "start": "14:00", "end": "16:00", "location": "地" * 51}]}))  # 51 字
assert _rejects_parse(json.dumps({"v": 1, "slots": [dict(SLOT_A, weekday=1, start="14:00", end="16:00")] * 11}, ensure_ascii=False))  # 11 组
assert _rejects_parse(json.dumps({"v": 1, "slots": [
    {"weekday": 1, "start": "14:00", "end": "16:00", "location": "A"},
    {"weekday": 1, "start": "14:00", "end": "16:00", "location": "B"},
]}, ensure_ascii=False))  # 同日重复
assert _rejects_parse(json.dumps({"v": 1, "slots": [
    {"weekday": 1, "start": "14:00", "end": "16:00", "location": "A"},
    {"weekday": 1, "start": "15:00", "end": "17:00", "location": "B"},
]}, ensure_ascii=False))  # 同日重叠

# 5) compose_office_hours 组合串。
assert app_module.compose_office_hours([SLOT_A, SLOT_B]) == "周一 14:00–16:00 · A楼302；周三 09:00–10:00 · B楼201"

# 6) _profile_complete 各分支。
assert app_module.is_valid_major(UG_MAJOR) is True
assert app_module.is_valid_major(GR_MAJOR) is True
assert app_module.is_valid_major("计算机学院") is False
complete_student = {"email": "a@b.com", "major": UG_MAJOR, "advisor": "李四"}
assert app_module._profile_complete("s1", "张三", "student", student_id="202600010001", **complete_student) is True
assert app_module._profile_complete("s1", "张三", "student", student_id="202600010001", email="", major=UG_MAJOR, advisor="李四") is False  # 缺邮箱
assert app_module._profile_complete("s1", "张三", "student", student_id="202600010001", email="a@b.com", major="", advisor="李四") is False  # 缺专业
assert app_module._profile_complete("s1", "张三", "student", student_id="202600010001", email="a@b.com", major="计算机学院", advisor="李四") is False  # 旧自由文本专业失效
assert app_module._profile_complete("s1", "张三", "student", student_id="202600010001", email="a@b.com", major=UG_MAJOR, advisor="") is True  # 导师选填
valid_schedule = _canon([SLOT_A])
complete_teacher = {"email": "t@b.com", "wechat": "twechat1", "office_schedule": valid_schedule}
assert app_module._profile_complete("t1", "李老师", "teacher", student_id="", **complete_teacher) is True
assert app_module._profile_complete("t1", "李老师", "teacher", student_id="", email="t@b.com", wechat="", office_schedule=valid_schedule) is False  # 缺微信
assert app_module._profile_complete("t1", "李老师", "teacher", student_id="", email="t@b.com", wechat="twechat1", office_schedule="") is False  # 缺 schedule
assert app_module._profile_complete("t1", "李老师", "teacher", student_id="", email="t@b.com", wechat="twechat1", office_schedule="{bad") is False  # 坏 schedule
assert app_module._profile_complete("t1", "李老师", "teacher", student_id="", email="t@b.com", wechat="twechat1", office_hours="每周三 14:00") is False  # 旧 office_hours 不算完整
assert app_module._profile_complete("a1", "王助教", "assistant", student_id="", **complete_teacher) is True  # 助教同老师规则

# 7) settings POST：学生全字段保存成功，且伪造 sched_* 被忽略。
student_client = make_client(student1_id, "bioinformatics")
resp = student_client.post("/settings", data={
    "display_name": "张三", "student_id": "202600010001",
    "email": "a@b.com", "major": UG_MAJOR, "advisor": "李四",
    "sched_weekday": ["1"], "sched_start": ["14:00"], "sched_end": ["16:00"], "sched_location": ["伪造地点"],
}, follow_redirects=True)
assert resp.status_code == 200
assert "个人资料已更新" in resp.get_data(as_text=True)
with app.app_context():
    row = app_module.query("SELECT * FROM users WHERE id=?", (student1_id,), one=True)
    assert row["display_name"] == "张三" and row["student_id"] == "202600010001"
    assert row["email"] == "a@b.com" and row["major"] == UG_MAJOR and row["advisor"] == "李四"
    assert (row["office_schedule"] or "") == "" and (row["office_hours"] or "") == ""

# 8) 设置页使用本科/硕士分组下拉，不把旧自由文本变成可保存选项。
with app.app_context():
    app_module.execute("UPDATE users SET major='计算机学院' WHERE id=?", (student1_id,))
settings_html = student_client.get("/settings").get_data(as_text=True)
assert '<select id="profile-major"' in settings_html
assert '<optgroup label="本科专业">' in settings_html
assert '<optgroup label="硕士专业">' in settings_html
assert 'name@bua.edu.cn' in settings_html
assert 'value="计算机学院"' not in settings_html
assert '<select' in settings_html and 'name="sched_weekday"' not in settings_html  # 学生无 schedule 编辑器
resp = student_client.post("/settings", data={
    "display_name": "张三", "student_id": "202600010001",
    "email": "a@b.com", "major": "计算机学院", "advisor": "",
}, follow_redirects=True)
assert "请从下拉列表中选择有效的专业" in resp.get_data(as_text=True)
with app.app_context():
    assert app_module.query("SELECT major FROM users WHERE id=?", (student1_id,), one=True)["major"] == "计算机学院"

# 9) 导师选填但长度上限仍由服务端执行。
resp = student_client.post("/settings", data={
    "display_name": "张三", "student_id": "202600010001",
    "email": "student@bua.edu.cn", "major": UG_MAJOR, "advisor": "导" * 51,
}, follow_redirects=True)
assert "导师/课题组不能超过 50 个字符" in resp.get_data(as_text=True)

# 10) 邮箱非法被拒且不落库。
with app.app_context():
    app_module.execute("UPDATE users SET email='' WHERE id=?", (student1_id,))
resp = student_client.post("/settings", data={
    "display_name": "张三", "student_id": "202600010001",
    "email": "not-an-email", "major": GR_MAJOR, "advisor": "李四",
}, follow_redirects=True)
assert resp.status_code == 200
assert "邮箱格式不正确" in resp.get_data(as_text=True)
with app.app_context():
    assert app_module.query("SELECT email FROM users WHERE id=?", (student1_id,), one=True)["email"] == ""

# 11) 微信号非法被拒且不落库（老师）。
teacher_client = make_client(teacher_id, "bioinformatics")
resp = teacher_client.post("/settings", data={
    "display_name": "李老师", "email": "t@b.com",
    "wechat": "1badwechat", "sched_weekday": ["1"],
    "sched_start": ["14:00"], "sched_end": ["16:00"], "sched_location": ["A楼302"],
}, follow_redirects=True)
assert resp.status_code == 200
assert "微信号格式不正确" in resp.get_data(as_text=True)
with app.app_context():
    row = app_module.query("SELECT * FROM users WHERE id=?", (teacher_id,), one=True)
    assert row["wechat"] == "" and (row["office_schedule"] or "") == ""

# 12) 老师合法保存：规范 JSON + office_hours 组合串双写。
resp = teacher_client.post("/settings", data={
    "display_name": "李老师", "email": "t@b.com", "wechat": "twechat1",
    "sched_weekday": ["3", "1"],
    "sched_start": ["09:00", "14:00"],
    "sched_end": ["10:00", "16:00"],
    "sched_location": ["B楼201", "A楼302"],
}, follow_redirects=True)
assert resp.status_code == 200
assert "个人资料已更新" in resp.get_data(as_text=True)
with app.app_context():
    row = app_module.query("SELECT * FROM users WHERE id=?", (teacher_id,), one=True)
    assert row["wechat"] == "twechat1"
    assert row["office_schedule"] == _canon([SLOT_A, SLOT_B]), row["office_schedule"]
    assert row["office_hours"] == "周一 14:00–16:00 · A楼302；周三 09:00–10:00 · B楼201"

# 13) 非法 schedule（同日重叠）不落库且回显已填行。
with app.app_context():
    before = app_module.query("SELECT office_schedule FROM users WHERE id=?", (teacher_id,), one=True)["office_schedule"]
resp = teacher_client.post("/settings", data={
    "display_name": "李老师", "email": "t@b.com", "wechat": "twechat1",
    "sched_weekday": ["1", "1"],
    "sched_start": ["14:00", "15:00"],
    "sched_end": ["16:00", "17:00"],
    "sched_location": ["A楼302", "B楼201"],
}, follow_redirects=True)
assert resp.status_code == 200
assert "重复或重叠" in resp.get_data(as_text=True)
echo = _schedule_script(resp.get_data(as_text=True))
assert [r["location"] for r in echo] == ["A楼302", "B楼201"], echo
with app.app_context():
    after = app_module.query("SELECT office_schedule FROM users WHERE id=?", (teacher_id,), one=True)["office_schedule"]
    assert after == before, "invalid schedule must not overwrite stored value"

# 14) 不完整行（缺 end）报错并回显。
resp = teacher_client.post("/settings", data={
    "display_name": "李老师", "email": "t@b.com", "wechat": "twechat1",
    "sched_weekday": ["1", "2"],
    "sched_start": ["14:00", "09:00"],
    "sched_end": ["16:00"],
    "sched_location": ["A楼302", "B楼201"],
}, follow_redirects=True)
assert "完整填写" in resp.get_data(as_text=True)
echo = _schedule_script(resp.get_data(as_text=True))
assert len(echo) == 2 and echo[1]["end"] == ""

# 15) 空 schedule 行报错；11 组报错。
resp = teacher_client.post("/settings", data={
    "display_name": "李老师", "email": "t@b.com", "wechat": "twechat1",
}, follow_redirects=True)
assert "请至少填写一组" in resp.get_data(as_text=True)
eleven = {"sched_weekday": [str((i % 7) + 1) for i in range(11)],
          "sched_start": ["08:00"] * 11, "sched_end": ["09:00"] * 11,
          "sched_location": [f"R{i}" for i in range(11)]}
resp = teacher_client.post("/settings", data={
    "display_name": "李老师", "email": "t@b.com", "wechat": "twechat1", **eleven,
}, follow_redirects=True)
assert "最多 10 组" in resp.get_data(as_text=True)

# 16) XSS：地点含脚本标签，保存与展示都被转义。
xss_location = "<script>alert(1)</script>"
resp = teacher_client.post("/settings", data={
    "display_name": "李老师", "email": "t@b.com", "wechat": "twechat1",
    "sched_weekday": ["1"], "sched_start": ["14:00"], "sched_end": ["16:00"],
    "sched_location": [xss_location],
}, follow_redirects=True)
settings_html = resp.get_data(as_text=True)
assert xss_location not in settings_html
profile_html = teacher_client.get("/users/teacher1").get_data(as_text=True)
assert xss_location not in profile_html
assert "&lt;script&gt;alert(1)&lt;/script&gt;" in profile_html

# 17) 旧 office_hours 回退展示：新字段为空/坏时资料页与设置页显示原文，且不算完整。
for bad_value in ("", "{bad json"):
    with app.app_context():
        app_module.execute("UPDATE users SET office_schedule=?, office_hours='旧地点 周三 14:00' WHERE id=?",
                           (bad_value, teacher_id))
    assert teacher_client.get("/settings").status_code == 200
    assert teacher_client.get("/").status_code == 200
    assert teacher_client.get("/users/teacher1").status_code == 200
    settings_html = teacher_client.get("/settings").get_data(as_text=True)
    assert "旧答疑安排：旧地点 周三 14:00" in settings_html
    profile_html = teacher_client.get("/users/teacher1").get_data(as_text=True)
    assert "旧答疑安排：旧地点 周三 14:00" in profile_html
    assert app_module._profile_complete("t1", "李老师", "teacher", email="t@b.com", wechat="twechat1",
                                        office_hours="旧地点 周三 14:00") is False

# 18) 合法 schedule 覆盖旧文本展示。
with app.app_context():
    app_module.execute("UPDATE users SET office_schedule=?, office_hours='不应显示' WHERE id=?",
                       (_canon([SLOT_A]), teacher_id))
settings_html = teacher_client.get("/settings").get_data(as_text=True)
assert "旧答疑安排：不应显示" not in settings_html
assert "A楼302" in settings_html and "14:00" in settings_html
profile_html = teacher_client.get("/users/teacher1").get_data(as_text=True)
assert "周一" in profile_html and "14:00" in profile_html

# 19) /users/<username> 权限矩阵。
assert student_client.get("/users/student1").status_code == 200      # 学生看自己
assert student_client.get("/users/teacher1").status_code == 200      # 学生看老师
assert student_client.get("/users/student2").status_code == 404      # 学生看另一学生
assert teacher_client.get("/users/student1").status_code == 200      # 老师看学生
assert teacher_client.get("/users/nonexistent").status_code == 404   # 老师看不存在的用户

# 20) 弹窗文案包含“邮箱”。
incomplete = make_client(student2_id, "bioinformatics")
home = incomplete.get("/").get_data(as_text=True)
assert "请完善个人信息" in home and "邮箱" in home

temporary.cleanup()
print("PROFILE_TEST_OK")
