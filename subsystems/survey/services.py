"""学情问卷（learning survey）的题目定义与答卷校验。

SURVEY_QUESTIONS 是 45 道题的权威定义（含末尾的姓名/学号两道必答填空题）。
问卷按八个部分分组渲染。
"""
from __future__ import annotations

import re

MASTERY_OPTIONS = ["熟练", "基本掌握", "了解", "完全不会"]


def _q(qtype: str, prompt: str, options: list[str] | None = None) -> dict:
    return {"type": qtype, "prompt": prompt, "options": options or []}


def _matrix(number: int, title: str, items: list[str]) -> list[dict]:
    return [_q("single", f"{number}. {title}：{name}", MASTERY_OPTIONS) for name in items]


_ITEMS: list[dict] = [
    _q("single", "1. 您所在的年级：", [
        "大学一年级", "大学二年级", "大学三年级", "大学四年级",
        "硕士一年级", "硕士二年级", "硕士三年级",
    ]),
    _q("single", "2. 您的本科专业背景：（选择“其他”可在第 30 题补充说明）", [
        "生物学类", "医学", "农学", "计算机/信息类", "数学/统计", "其他",
    ]),
    _q("single", "3. 在本课程之前，您是否学习或接触过生物信息学相关课程或培训？", [
        "系统学习过相关课程", "参加过相关培训或讲座", "通过科研项目自学过",
        "有少量接触，但没有系统学习", "完全没有接触过",
    ]),
    _q("fill", "4. 您目前的主要研究方向是？"),
]
_ITEMS += _matrix(5, "请评估您在以下方面的掌握程度", [
    "分子生物学", "生物统计学", "遗传学", "细胞生物学", "基因组学", "生物信息学",
])
_ITEMS += [
    _q("multiple", "6. 您目前掌握或接触过哪些计算机/编程工具？（可多选）", [
        "R", "Python", "Linux/Unix", "Perl", "Java", "C/C++", "其他", "尚未接触任何编程工具",
    ]),
    _q("single", "7. 您如何评价自己的编程能力？", [
        "完全没有编程基础", "能看懂少量代码，但难以独立编写", "修改并运行已有代码",
        "能根据分析需求独立编写程序", "能较熟练地完成数据分析及程序开发",
    ]),
    _q("single", "8. 您对Linux命令行操作的熟悉程度如何？", [
        "完全不了解", "听说过，但没有使用过", "能完成简单的文件和目录操作",
        "能使用常见Linux命令完成数据处理", "能熟练使用Linux及Shell脚本开展分析",
    ]),
]
_ITEMS += _matrix(9, "您对以下生物信息学知识或技术的了解程度如何", [
    "NCBI、Ensembl等生物数据库", "BLAST及序列比对", "多序列比对与系统发育分析",
    "高通量测序（NGS）数据分析", "基因组数据分析", "转录组/RNA-seq数据分析",
    "蛋白质组数据分析", "GO/KEGG等功能富集分析", "生物信息学数据可视化",
])
_ITEMS += [
    _q("single", "10. 您是否使用过公共生物信息学数据库获取科研数据？", [
        "经常使用", "使用过多次", "偶尔使用过", "知道相关数据库但没有实际使用", "完全没有使用过",
    ]),
    _q("multiple", "11. 您曾经处理过哪些类型的生物学数据？（可多选）", [
        "DNA/RNA序列数据", "全基因组测序数据", "RNA-seq/转录组数据", "单细胞测序数据",
        "蛋白质组数据", "代谢组数据", "微生物组/宏基因组数据", "其他", "尚未实际处理过生物学数据",
    ]),
    _q("single", "12. 您目前独立完成生物信息学分析任务的能力如何？", [
        "尚不能独立完成", "在详细教程指导下可以完成简单分析",
        "借助网络资料或AI工具可以完成常规分析", "能够独立完成较完整的分析流程",
        "能够根据科研问题自主设计和优化分析流程",
    ]),
    _q("single", "13. 您目前的科研课题是否涉及生物信息学或生物大数据分析？", [
        "高度相关，是课题的主要研究方法", "有一定相关，需要进行部分数据分析",
        "基本不涉及", "能够独立完成较完整的分析流程", "尚未确定研究课题",
    ]),
    _q("multiple", "14. 当科研中遇到生物信息学分析问题时，您通常采用哪些方式解决？（可多选）", [
        "查阅教材或专业书籍", "搜索网络教程", "阅读相关论文", "请教师兄师姐或同学",
        "请教导师或专业教师", "使用生成式AI工具", "使用商业分析平台或委托第三方分析",
        "暂时没有遇到过相关问题", "其他",
    ]),
    _q("multiple", "15. 您认为目前影响自己开展生物信息学分析的主要困难有哪些？（可多选）", [
        "生物学基础知识不足", "统计学基础薄弱", "编程基础薄弱", "Linux操作不熟悉",
        "不理解生物信息学算法原理", "不熟悉数据库和分析工具", "不知道如何选择合适的分析方法",
        "软件安装及环境配置困难", "不知道如何解释分析结果", "英文文献阅读困难",
        "缺乏真实科研数据实践机会", "其他",
    ]),
    _q("multiple", "16. 您选修本课程的主要原因是：（可多选）", [
        "课题研究实际需要", "学位/学分要求", "提升就业竞争力", "个人兴趣", "导师建议",
    ]),
    _q("multiple", "17. 您希望通过本课程达到的目标是：（可多选，最多选 3 项）", [
        "理解生物信息学基本原理与算法思想", "能独立分析自己课题产生的组学数据",
        "掌握编程与流程搭建能力", "读懂并复现文献中的生信分析",
        "为毕业论文/学位论文研究做准备", "为未来就业或继续深造做准备", "其他",
    ]),
    _q("multiple", "18. 您最希望课程重点讲授哪些内容？（可多选，最多选 6 项）", [
        "生物信息学基础与发展前沿", "生物数据库及数据检索", "DNA/RNA序列分析",
        "BLAST及序列比对", "系统发育分析", "基因组学分析", "RNA-seq/转录组分析",
        "单细胞组学分析", "蛋白质组学分析", "代谢组学分析", "微生物组/宏基因组分析",
        "多组学联合分析", "功能注释与富集分析", "R语言及数据可视化",
        "Python生物信息学分析", "生物信息学常用Linux操作", "机器学习与生物信息学",
        "人工智能/大语言模型与生物信息学", "其他",
    ]),
    _q("single", "19. 对于生物信息学算法，您希望课程讲解到什么程度？", [
        "以工具使用为主，不需要深入算法", "简单介绍基本原理即可", "原理与实践并重",
        "希望较深入学习核心算法", "希望能够进一步学习算法实现及开发",
    ]),
    _q("multiple", "20. 您更希望课程使用哪类数据进行实践教学？（可多选）", [
        "教师设计的小型示例数据", "公共数据库中的真实数据", "已发表论文的配套数据",
        "教师科研项目中的实际数据", "学生自己的科研数据", "不同类型数据均适当涉及",
    ]),
    _q("single", "21. 您是否使用过ChatGPT、DeepSeek、Claude、Gemini等生成式AI/大语言模型？", [
        "经常使用", "偶尔使用", "使用过，但很少", "听说过但没有使用", "完全不了解",
    ]),
    _q("multiple", "22. 您曾使用生成式AI完成哪些学习或科研任务？（可多选）", [
        "查找或解释专业知识", "阅读、翻译或总结文献", "编写R/Python代码", "修改和调试代码",
        "解释生物信息学分析结果", "设计数据分析流程", "辅助科研写作", "数据整理或可视化",
        "尚未使用过", "其他",
    ]),
    _q("single", "23. 您希望课程合理使用AI辅助生物信息学分析吗？", [
        "非常希望", "比较希望", "一般", "不太需要", "完全不需要",
    ]),
    _q("multiple", "24. 您最希望学习哪些AI辅助生物信息学能力？（可多选）", [
        "使用AI辅助编写R/Python代码", "使用AI排查代码错误", "使用AI解释生物信息学概念和算法",
        "使用AI辅助设计分析流程", "使用AI解读分析结果", "使用AI辅助文献检索和阅读",
        "判断AI生成内容是否准确可靠", "数据安全、科研伦理及规范使用AI", "其他",
    ]),
    _q("multiple", "25. 您希望《生物信息学》课程采用哪些教学方式？（可多选）", [
        "教师理论讲授", "教师现场演示软件/代码操作", "上机实践", "真实科研案例教学",
        "项目式学习", "小组合作学习", "文献阅读与汇报", "课堂讨论",
        "线上视频/微课辅助学习", "AI辅助学习", "其他",
    ]),
    _q("single", "26. 您认为课程中理论教学与实践教学的比例设置为多少比较合适？", [
        "理论80%，实践20%", "理论60%，实践40%", "理论50%，实践50%",
        "理论40%，实践60%", "理论20%，实践80%",
    ]),
    _q("multiple", "27. 您希望课程作业主要采用哪些形式？（可多选）", [
        "基础知识练习", "数据分析操作题", "编程作业", "文献阅读与汇报", "生物信息学案例分析",
        "小型科研项目", "小组合作项目", "结合本人科研课题完成分析任务", "其他",
    ]),
    _q("multiple", "28. 您认为目前学习中最大的障碍是：（可多选，最多选 3 项）", [
        "数学/统计学基础薄弱", "编程基础薄弱", "生物学背景知识不足", "英文文献/文档阅读困难",
        "缺少实践数据和真实问题", "课程进度太快", "其他",
    ]),
    _q("essay", "29. 通过本课程的学习，您最希望解决的一个生物信息学或科研数据分析问题是什么？"),
    _q("essay", "30. 您对本课程的教学内容、教学方式、实践安排或考核方式还有哪些期待和建议？"),
    _q("fill", "31. 您的姓名："),
    _q("fill", "32. 您的学号："),
]

SURVEY_QUESTIONS: list[dict] = [
    {"id": f"q{index}", **item}
    for index, item in enumerate(_ITEMS, 1)
]

# 按八个部分分组（每个部分标题 + 题目 id 列表）。
SURVEY_SECTIONS: list[tuple[str, list[str]]] = [
    ("一、基本情况", ["q1", "q2", "q3", "q4"]),
    ("二、基础知识掌握程度", ["q5", "q6", "q7", "q8", "q9", "q10"]),
    ("三、编程与工具能力", ["q11", "q12", "q13"]),
    ("四、生物信息学知识与技术", ["q14", "q15", "q16", "q17", "q18", "q19", "q20", "q21", "q22", "q23"]),
    ("五、科研实践与困难", ["q24", "q25", "q26", "q27", "q28"]),
    ("六、课程期望与目标", ["q29", "q30", "q31", "q32", "q33"]),
    ("七、AI 工具使用情况", ["q34", "q35", "q36", "q37"]),
    ("八、教学建议与期待", ["q38", "q39", "q40", "q41", "q42", "q43", "q44", "q45"]),
]


def survey_sections() -> list[dict]:
    """返回按八个部分分组的题目列表：[{"title": str, "questions": [question, ...]}, ...]

    每个 question 额外附带 "label" 字段（question_label 的结果），供前端渲染
    data-qlabel 属性；不修改 SURVEY_QUESTIONS 中的原始题目定义。
    """
    by_id = {question["id"]: question for question in SURVEY_QUESTIONS}
    sections = []
    for title, ids in SURVEY_SECTIONS:
        questions = []
        for qid in ids:
            question = by_id.get(qid)
            if question:
                questions.append({**question, "label": question_label(question)})
        sections.append({"title": title, "questions": questions})
    return sections


_NUMBER_RE = re.compile(r"^\s*(\d+)\s*[.．、]")
_MATRIX_RE = re.compile(r"^\s*(\d+)\s*[.．、]\s*.+?：(.+)$")


def question_label(question: dict) -> str:
    """从题干提取用于提示的题号标签。

    普通题返回主序号字符串（如 "12. 您目前..." -> "12"）；矩阵行返回
    "主序号-知识点名"（如 "5. 请评估您在以下方面的掌握程度：分子生物学" ->
    "5-分子生物学"）。矩阵行通过题干中的全角冒号 "：" 及其后的知识点名识别；
    冒号后为括号备注（如 "（可多选）"）或空内容时不视为矩阵行。
    """
    prompt = question.get("prompt", "")
    number_match = _NUMBER_RE.match(prompt)
    number = number_match.group(1) if number_match else question.get("id", "")
    matrix_match = _MATRIX_RE.match(prompt)
    if matrix_match:
        name = matrix_match.group(2).strip()
        if name and not name.startswith("（"):
            return f"{number}-{name}"
    return number


def find_missing(answers: dict) -> list[str]:
    """返回所有“必答但未答”的题目 id（按 SURVEY_QUESTIONS 顺序）。

    single/fill 需非空字符串；multiple 需非空列表且至少一个非空项；
    essay 永远不算缺失。
    """
    if not isinstance(answers, dict):
        answers = {}
    missing: list[str] = []
    for question in SURVEY_QUESTIONS:
        qid = question["id"]
        qtype = question["type"]
        raw = answers.get(qid)
        if qtype == "essay":
            continue
        if qtype in ("single", "fill"):
            value = str(raw).strip() if raw is not None else ""
            if not value:
                missing.append(qid)
        elif qtype == "multiple":
            if not isinstance(raw, list) or not any(str(item).strip() for item in raw):
                missing.append(qid)
    return missing


def validate_answers(answers: dict) -> dict:
    """校验答卷并返回规范化后的答卷。

    收集全部必答缺失项，有缺失时抛 ValueError（消息列出全部缺失题号标签）。
    无缺失时返回规范化 dict：single/fill/essay -> str，multiple -> list[str]；
    essay 允许空字符串。multiple 选项仍须合法。
    """
    if not isinstance(answers, dict):
        raise ValueError("答卷格式无效，请重新填写")
    missing = find_missing(answers)
    if missing:
        by_id = {question["id"]: question for question in SURVEY_QUESTIONS}
        labels = "、".join(question_label(by_id[qid]) for qid in missing)
        raise ValueError("请完成必答题：" + labels)
    normalized: dict = {}
    for question in SURVEY_QUESTIONS:
        qid = question["id"]
        raw = answers.get(qid)
        if question["type"] == "single":
            value = str(raw).strip() if raw is not None else ""
            if value and value not in set(question["options"]):
                raise ValueError(f"{question_label(question)} 题包含无效选项：{value}")
            normalized[qid] = value
        elif question["type"] in ("fill", "essay"):
            normalized[qid] = str(raw).strip() if raw is not None else ""
        elif question["type"] == "multiple":
            value = [str(item).strip() for item in raw if str(item).strip()]
            valid = set(question["options"])
            invalid = [item for item in value if item not in valid]
            if invalid:
                raise ValueError(f"{question_label(question)} 题包含无效选项：{'、'.join(invalid)}")
            normalized[qid] = value
    return normalized


def answers_for_prompt(answers: dict) -> str:
    """把答卷格式化为“题号. 题干\\n回答：...”文本，供 AI 分析使用。"""
    lines: list[str] = []
    for index, question in enumerate(SURVEY_QUESTIONS, 1):
        value = answers.get(question["id"], "")
        if question["type"] == "multiple":
            if isinstance(value, list):
                rendered = "、".join(str(item) for item in value)
            else:
                rendered = str(value)
        else:
            rendered = str(value) if value else "（未作答）"
        lines.append(f"{index}. {question['prompt']}")
        lines.append(f"回答：{rendered}")
    return "\n".join(lines)


def aggregate_single_multiple(responses: list[dict]) -> dict:
    """统计每道 single/multiple 题的选项分布。

    responses 为已解析的答卷 dict（qid -> 值）列表。
    返回 {qid: {"counts": {option: int}, "responses": int}}。
    """
    result: dict = {}
    for question in SURVEY_QUESTIONS:
        if question["type"] not in ("single", "multiple"):
            continue
        counts = {option: 0 for option in question["options"]}
        answered = 0
        for answers in responses:
            if not isinstance(answers, dict):
                continue
            value = answers.get(question["id"])
            if question["type"] == "multiple":
                if not isinstance(value, list) or not value:
                    continue
                answered += 1
                for item in value:
                    if item in counts:
                        counts[item] += 1
            else:
                if not isinstance(value, str) or not value:
                    continue
                answered += 1
                if value in counts:
                    counts[value] += 1
        result[question["id"]] = {"counts": counts, "responses": answered}
    return result
