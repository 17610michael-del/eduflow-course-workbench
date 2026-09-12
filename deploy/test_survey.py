"""Verify the learning-survey module: tables, submission, analysis, isolation and permissions."""
from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import types
from datetime import datetime, timedelta
from pathlib import Path

temporary = tempfile.TemporaryDirectory(prefix="eduflow-survey-")
root = Path(temporary.name)
os.environ.update({
    "SECRET_KEY": "survey-test-secret",
    "DATABASE": str(root / "survey.db"),
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
    "SESSION_COOKIE_NAME": "survey_session",
    "REMEMBER_COOKIE_NAME": "survey_remember",
    "LOGIN_HINT_COOKIE_PREFIX": "survey_",
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

from subsystems.survey.services import (  # noqa: E402
    SURVEY_QUESTIONS, answers_for_prompt, find_missing, question_label,
    survey_sections, validate_answers,
)

FAKE_ANALYSIS = {
    "summary": "测试画像：基础扎实，编程待提升。",
    "strengths": ["分子生物学基础扎实"],
    "weaknesses": ["编程基础薄弱"],
    "study_plan": ["第一阶段：夯实 Python 基础", "第二阶段：练习 Linux 命令"],
    "prerequisites": ["Python 入门", "Linux 基础"],
    "practice_advice": ["每天练习 30 分钟 Linux 命令"],
    "ai_tool_advice": ["使用 AI 辅助调试代码"],
}
app_module.survey_learning_analysis = lambda config, answers_text: dict(FAKE_ANALYSIS)

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

# 1) Tables created and registered as course-root tables.
with app.app_context():
    existing = {r["name"] for r in app_module.query(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('survey_responses','survey_analyses')"
    )}
    assert existing == {"survey_responses", "survey_analyses"}, f"missing survey tables: {existing}"
    assert "survey_responses" in app_module.COURSE_ROOT_TABLES
    assert "survey_analyses" in app_module.COURSE_ROOT_TABLES

# 2) Questions integrity and helpers.
assert len(SURVEY_QUESTIONS) == 45
assert {q["id"] for q in SURVEY_QUESTIONS} == {f"q{i}" for i in range(1, 46)}
assert all(q["type"] in {"single", "multiple", "fill", "essay"} for q in SURVEY_QUESTIONS)
sections = survey_sections()
assert len(sections) == 8
assert sum(len(s["questions"]) for s in sections) == 45
try:
    validate_answers({"q1": ""})
    raise AssertionError("validate_answers should reject missing answers")
except ValueError:
    pass
try:
    validate_answers({"q1": "大学三年级", "q6": ["不存在的选项"]})
    raise AssertionError("validate_answers should reject invalid multiple options")
except ValueError:
    pass
assert "回答：大学三年级" in answers_for_prompt({"q1": "大学三年级"})

# 2b) find_missing / question_label / validate_answers 消息格式。
assert find_missing({}) == [f"q{i}" for i in range(1, 42)] + ["q44", "q45"]  # 除 q42/q43 两道 essay 外全部 43 个
assert find_missing({"q42": "补充", "q43": "建议"}) == [f"q{i}" for i in range(1, 42)] + ["q44", "q45"]  # 只答 essay 仍 43 个
full_answers = {}
for q in SURVEY_QUESTIONS:
    if q["type"] == "essay":
        full_answers[q["id"]] = ""  # essay 留空
    elif q["type"] == "multiple":
        full_answers[q["id"]] = [q["options"][0]]
    else:
        full_answers[q["id"]] = q["options"][0] if q["options"] else "测试回答"
assert find_missing(full_answers) == []  # 全答（essay 留空）返回空
by_id = {q["id"]: q for q in SURVEY_QUESTIONS}
assert question_label(by_id["q1"]) == "1"
assert question_label(by_id["q5"]) == "5-分子生物学"
assert question_label(by_id["q25"]) == "12"  # 普通题取主序号
try:
    validate_answers({"q1": ""})
    raise AssertionError("validate_answers should reject missing answers")
except ValueError as exc:
    assert str(exc).startswith("请完成必答题：")
    assert "1" in str(exc)
bad_full = dict(full_answers)
first_multiple = next(q for q in SURVEY_QUESTIONS if q["type"] == "multiple")
bad_full[first_multiple["id"]] = ["不存在的选项"]
try:
    validate_answers(bad_full)
    raise AssertionError("validate_answers should reject invalid multiple options")
except ValueError:
    pass
bad_single = dict(full_answers)
first_single = next(q for q in SURVEY_QUESTIONS if q["type"] == "single")
bad_single[first_single["id"]] = "不存在的选项"
try:
    validate_answers(bad_single)
    raise AssertionError("validate_answers should reject invalid single option")
except ValueError:
    pass


def make_client(user_id, slug):
    client = app.test_client()
    with client.session_transaction() as s:
        s["_user_id"] = str(user_id)
        s["_fresh"] = True
        s["course_slug"] = slug
    return client


def build_form(*, first=True):
    form = {}
    for q in SURVEY_QUESTIONS:
        key = f"answer_{q['id']}"
        if q["type"] == "multiple":
            form[key] = [q["options"][0]] if first else [q["options"][-1]]
        elif q["type"] == "single":
            form[key] = q["options"][0] if first else q["options"][-1]
        else:
            form[key] = "测试回答" if first else "第二次回答"
    return form


student = make_client(student1_id, "bioinformatics")

# 3) survey_pending shows the red dot before submission.
assert "nav-dot" in student.get("/").get_data(as_text=True)

# 4) Student submits -> response + analysis persisted.
resp = student.post("/survey", data=build_form())
assert resp.status_code == 302, f"expected redirect after submit, got {resp.status_code}"
with app.app_context():
    resp_row = app_module.query(
        "SELECT * FROM survey_responses WHERE course_id=2 AND user_id=?", (student1_id,), one=True
    )
    assert resp_row is not None, "survey_responses row missing"
    ana_row = app_module.query(
        "SELECT * FROM survey_analyses WHERE course_id=2 AND user_id=?", (student1_id,), one=True
    )
    assert ana_row is not None, "survey_analyses row missing"
    analysis = json.loads(ana_row["analysis"])
    assert analysis["summary"] == FAKE_ANALYSIS["summary"]

# 5) survey_pending cleared after submission.
assert "nav-dot" not in student.get("/").get_data(as_text=True)

# 6) Students cannot open another student's detail.
resp = student.get("/survey/student/student2")
assert resp.status_code in (302, 403), f"expected denial, got {resp.status_code}"

# 7) Teacher overview lists both students.
teacher = make_client(teacher_id, "bioinformatics")
resp = teacher.get("/survey/overview")
assert resp.status_code == 200
overview_text = resp.get_data(as_text=True)
assert "student1" in overview_text and "student2" in overview_text
assert "student2" in overview_text

# 8) Course isolation: switching course_slug leaves the other course unanswered.
student_degree = make_client(student1_id, "degree")
assert "提交问卷" in student_degree.get("/survey").get_data(as_text=True)
with app.app_context():
    assert app_module.query(
        "SELECT * FROM survey_responses WHERE course_id=1 AND user_id=?", (student1_id,), one=True
    ) is None
# Submitted course shows read-only view, not the form.
read_only = student.get("/survey").get_data(as_text=True)
assert "你已提交问卷" in read_only and ">提交问卷</button>" not in read_only

# 9) Duplicate submission overwrites instead of erroring.
resp = student.post("/survey", data=build_form(first=False))
assert resp.status_code == 302
with app.app_context():
    n = app_module.query(
        "SELECT COUNT(*) n FROM survey_responses WHERE course_id=2 AND user_id=?", (student1_id,), one=True
    )["n"]
    assert n == 1, "duplicate submission should upsert to a single row"
    n2 = app_module.query(
        "SELECT COUNT(*) n FROM survey_analyses WHERE course_id=2 AND user_id=?", (student1_id,), one=True
    )["n"]
    assert n2 == 1

# 10) Staff view student detail; non-student member -> 404; regenerate works.
resp = teacher.get("/survey/student/student1")
assert resp.status_code == 200
assert "student1" in resp.get_data(as_text=True)
assert teacher.get("/survey/student/teacher1").status_code == 404
resp = teacher.post("/survey/student/student1/regenerate")
assert resp.status_code == 302
with app.app_context():
    assert app_module.query(
        "SELECT * FROM survey_analyses WHERE course_id=2 AND user_id=?", (student1_id,), one=True
    ) is not None

# 11) Missing a required answer -> 200 re-render with hint, no new row; essays optional -> 302.
student2 = make_client(student2_id, "bioinformatics")
missing_form = build_form()
del missing_form["answer_q3"]  # 缺一道必答（q3，题干序号 3）
resp = student2.post("/survey", data=missing_form)
assert resp.status_code == 200, f"expected re-render 200, got {resp.status_code}"
text = resp.get_data(as_text=True)
assert "请完成必答题" in text
assert "3" in text
assert "请完成必答题：3" in text
with app.app_context():
    assert app_module.query(
        "SELECT * FROM survey_responses WHERE course_id=2 AND user_id=?", (student2_id,), one=True
    ) is None
# 所有必答作答但两道 essay 留空 -> 302 成功且 survey_responses 有行。
essay_empty_form = build_form()
essay_empty_form["answer_q42"] = ""
essay_empty_form["answer_q43"] = ""
resp = student2.post("/survey", data=essay_empty_form)
assert resp.status_code == 302, f"expected redirect 302, got {resp.status_code}"
with app.app_context():
    assert app_module.query(
        "SELECT * FROM survey_responses WHERE course_id=2 AND user_id=?", (student2_id,), one=True
    ) is not None

# 12) _profile_complete 判定：完整 / 缺姓名 / 学生缺学号/邮箱/专业 / 教师缺微信/答疑。
valid_major = "本科｜农学"
complete_student = {"email": "a@b.com", "major": valid_major, "advisor": "李四"}
assert app_module._profile_complete("alice", "张三", "student", student_id="202600010001", **complete_student) is True
assert app_module._profile_complete("alice", "alice", "student", student_id="202600010001", **complete_student) is False  # 姓名 == 用户名
assert app_module._profile_complete("alice", "", "student", student_id="202600010001", **complete_student) is False  # 缺姓名
assert app_module._profile_complete("alice", "张三", "student", student_id="", **complete_student) is False  # 学生缺学号
assert app_module._profile_complete("alice", "张三", "student", student_id="   ", **complete_student) is False  # 学号空白视为缺
assert app_module._profile_complete("alice", "张三", "student", student_id="2023001", **complete_student) is False  # 学号非 12 位数字
assert app_module._profile_complete("alice", "张三", "student", student_id="202600010001", email="", major=valid_major, advisor="李四") is False  # 学生缺邮箱
assert app_module._profile_complete("alice", "张三", "student", student_id="202600010001", email="a@b.com", major="", advisor="李四") is False  # 学生缺学院专业
assert app_module._profile_complete("alice", "张三", "student", student_id="202600010001", email="a@b.com", major="计算机学院", advisor="李四") is False  # 旧专业文本必须重选
assert app_module._profile_complete("alice", "张三", "student", student_id="202600010001", email="a@b.com", major=valid_major, advisor="") is True  # 导师选填
complete_teacher = {"email": "t@b.com", "wechat": "twechat1",
                    "office_schedule": json.dumps(
                        {"v": 1, "slots": [{"weekday": 1, "start": "14:00", "end": "16:00", "location": "A楼302"}]},
                        ensure_ascii=False)}
assert app_module._profile_complete("bob", "李老师", "teacher", student_id="", **complete_teacher) is True  # 老师不要求学号
assert app_module._profile_complete("bob", "李老师", "teacher", student_id="", email="t@b.com", wechat="", office_schedule=complete_teacher["office_schedule"]) is False  # 老师缺微信
assert app_module._profile_complete("bob", "李老师", "teacher", student_id="", email="t@b.com", wechat="twechat1", office_schedule="") is False  # 老师缺答疑安排
assert app_module._profile_complete("bob", "李老师", "teacher", student_id="", email="t@b.com", wechat="twechat1", office_hours="每周三 14:00 A 楼 302") is False  # 旧 office_hours 不算完整

# 13) 学生经 /settings POST 保存完整资料（必填且校验）。
with app.app_context():
    app_module.execute("UPDATE users SET display_name='student1',student_id='',email='',major='',advisor='' WHERE id=?", (student1_id,))
settings_client = make_client(student1_id, "bioinformatics")
base_student_form = {"display_name": "张三", "email": "a@b.com", "major": valid_major, "advisor": "李四"}
# 非法学号被拒绝且不落库。
resp = settings_client.post(
    "/settings",
    data={**base_student_form, "student_id": "2023001"},
    follow_redirects=True,
)
assert resp.status_code == 200
assert "12 位数字" in resp.get_data(as_text=True)
with app.app_context():
    assert app_module.query("SELECT student_id FROM users WHERE id=?", (student1_id,), one=True)["student_id"] == ""
# 空学号同样被拒绝。
resp = settings_client.post("/settings", data={**base_student_form, "student_id": ""}, follow_redirects=True)
assert "12 位数字" in resp.get_data(as_text=True)
# 合法完整资料保存成功。
resp = settings_client.post(
    "/settings",
    data={**base_student_form, "student_id": "202600010001"},
    follow_redirects=True,
)
assert resp.status_code == 200
assert "个人资料已更新" in resp.get_data(as_text=True)
with app.app_context():
    row = app_module.query("SELECT * FROM users WHERE id=?", (student1_id,), one=True)
    assert row["display_name"] == "张三"
    assert row["student_id"] == "202600010001"
    assert row["email"] == "a@b.com"
    assert row["major"] == valid_major
    assert row["advisor"] == "李四"

# 14) 资料不完整的学生提交问卷 -> 302、profile_force 为真、survey_responses 有行。
with app.app_context():
    app_module.execute("UPDATE users SET display_name='student2',student_id='' WHERE id=?", (student2_id,))
incomplete_client = make_client(student2_id, "bioinformatics")
resp = incomplete_client.post("/survey", data=build_form())
assert resp.status_code == 302, f"expected redirect after submit, got {resp.status_code}"
with incomplete_client.session_transaction() as s:
    assert s.get("profile_force") == 1, "incomplete student submit should set profile_force"
with app.app_context():
    assert app_module.query(
        "SELECT * FROM survey_responses WHERE course_id=2 AND user_id=?", (student2_id,), one=True
    ) is not None

# 15) 资料完整但姓名不匹配 -> 提交成功且响应含“不一致”提示。
with app.app_context():
    app_module.execute("UPDATE users SET display_name='张三',student_id='202600010001',email='a@b.com',major=?,advisor='李四' WHERE id=?", (valid_major, student1_id))
mismatch_client = make_client(student1_id, "bioinformatics")
mismatch_form = build_form()
mismatch_form["answer_q44"] = "王五"      # 与 display_name 不一致
mismatch_form["answer_q45"] = "202600010001"   # 与 student_id 一致
resp = mismatch_client.post("/survey", data=mismatch_form, follow_redirects=True)
assert resp.status_code == 200
assert "不一致" in resp.get_data(as_text=True)

# 16) 弹窗纯前端取消（sessionStorage），服务端只在设置页抑制弹窗。
dismiss_client = make_client(student2_id, "bioinformatics")
# 资料不完整：首页渲染弹窗。
assert "请完善个人信息" in dismiss_client.get("/").get_data(as_text=True)
# 设置页不弹窗（否则无法填写）。
assert "请完善个人信息" not in dismiss_client.get("/settings").get_data(as_text=True)

# 17) 登录后弹窗：资料不完整时 profile_prompt 为真并渲染弹窗文案。
prompt_client = make_client(student2_id, "bioinformatics")
assert "请完善个人信息" in prompt_client.get("/").get_data(as_text=True)

temporary.cleanup()
print("SURVEY_TEST_OK")
