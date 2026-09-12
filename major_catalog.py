"""北京农学院 2026 年本科/硕士招生专业白名单（唯一数据源）。

数据来源（仅用于维护与代码注释，运行时不联网）：
- 本科（2026 招生章程，去重）：
  https://zsb.bua.edu.cn/info/1043/2104.htm （2026-06-04）
- 硕士招生目录：https://yz.bua.edu.cn/info/1237/2468.htm
- 硕士专业代码/学院表：https://yz.bua.edu.cn/info/1240/1916.htm

存储值格式：``本科｜农学``、``硕士｜083600 生物工程``。
前缀用于区分同名本科/硕士专业（如 生物工程、植物保护、林学），
数据库只保存该规范字符串；白名单校验、模板 optgroup 选项与友好显示都由本模块派生。
"""
from __future__ import annotations

UNDERGRAD_LEVEL = "本科"
GRADUATE_LEVEL = "硕士"
# 全角竖线，避免与名称中的普通字符冲突。
MAJOR_SEPARATOR = "\uff5c"

# 本科专业（中外合作办学作为独立专业选项保留）。
UNDERGRAD_MAJORS = (
    "农学", "园艺", "植物保护", "生物育种技术", "设施农业科学与工程", "农业资源与环境",
    "动物科学", "动物医学", "食品科学与工程", "食品质量与安全", "酿酒工程", "食品营养与健康",
    "生物工程", "应用化学", "园林", "林学", "风景园林", "国际经济与贸易", "投资学", "会计学",
    "工商管理", "农林经济管理", "农村区域发展", "旅游管理", "法学", "社会工作", "物联网工程",
    "数据科学与大数据技术", "环境设计", "国际经济与贸易（中外合作办学）",
    "食品科学与工程（中外合作办学）", "农业资源与环境（中外合作办学）",
)

# 硕士专业：(专业代码, 规范名称)，代码用于消歧，仅作存储值/显示的一部分。
GRADUATE_MAJORS = (
    ("083600", "生物工程"), ("090400", "植物保护"), ("086000", "生物与医药"),
    ("095132", "资源利用与植物保护"), ("090100", "作物学"), ("090200", "园艺学"),
    ("095131", "农艺与种业"), ("090500", "畜牧学"), ("090600", "兽医学"),
    ("095133", "畜牧"), ("095200", "兽医"), ("120200", "工商管理学"),
    ("120300", "农林经济管理"), ("025400", "国际商务"), ("095137", "农业管理"),
    ("090700", "林学"), ("086200", "风景园林"), ("095400", "林业"),
    ("083200", "食品科学与工程"), ("095135", "食品加工与安全"),
    ("140500", "智能科学与技术"), ("095136", "农业工程与信息技术"),
    ("035200", "社会工作"), ("095138", "农村发展"),
)


def make_major_value(level: str, label: str) -> str:
    """规范存储值：``层级｜标签``。"""
    return f"{level}{MAJOR_SEPARATOR}{label}"


def _graduate_label(code: str, name: str) -> str:
    return f"{code} {name}"


UNDERGRAD_OPTIONS = tuple(
    {"value": make_major_value(UNDERGRAD_LEVEL, name), "label": name}
    for name in UNDERGRAD_MAJORS
)
GRADUATE_OPTIONS = tuple(
    {
        "value": make_major_value(GRADUATE_LEVEL, _graduate_label(code, name)),
        "label": _graduate_label(code, name),
    }
    for code, name in GRADUATE_MAJORS
)
MAJOR_GROUPS = (
    {"level": UNDERGRAD_LEVEL, "label": "本科专业", "options": UNDERGRAD_OPTIONS},
    {"level": GRADUATE_LEVEL, "label": "硕士专业", "options": GRADUATE_OPTIONS},
)
MAJOR_VALUES = frozenset(
    option["value"] for group in MAJOR_GROUPS for option in group["options"]
)


def major_groups():
    """模板 optgroup 数据：本科/硕士分组，每项含存储值 value 与显示名 label。"""
    return MAJOR_GROUPS


def is_valid_major(value: str) -> bool:
    """仅接受白名单中的规范存储值（含层级前缀），旧自由文本一律不通过。"""
    return (value or "").strip() in MAJOR_VALUES


def major_display(value: str) -> str:
    """把存储值转成友好显示；未知/旧自由文本原样返回，不输出原始分隔符。"""
    text = (value or "").strip()
    if not text:
        return ""
    if MAJOR_SEPARATOR in text:
        level, _, label = text.partition(MAJOR_SEPARATOR)
        label = label.strip()
        if level in (UNDERGRAD_LEVEL, GRADUATE_LEVEL) and label:
            return f"{label}（{level}）"
    return text
