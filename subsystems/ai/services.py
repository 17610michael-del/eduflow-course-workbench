from __future__ import annotations

import json
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from xml.etree import ElementTree


class DeepSeekError(RuntimeError):
    pass


def _settings(config):
    key = config.get("DEEPSEEK_API_KEY", "")
    if not key:
        raise DeepSeekError("DeepSeek API Key 尚未配置")
    return key, config.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")


def deepseek_chat(config, messages, *, model=None, json_mode=False, max_tokens=4096):
    key, base_url = _settings(config)
    payload = {
        "model": model or config.get("DEEPSEEK_CHAT_MODEL", "deepseek-v4-flash"),
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": False,
        "thinking": {"type": "disabled"},
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    request = urllib.request.Request(
        base_url + "/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("error", {}).get("message", "")
        except Exception:
            detail = ""
        raise DeepSeekError(f"DeepSeek 请求失败（HTTP {exc.code}）{': ' + detail if detail else ''}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise DeepSeekError("DeepSeek 暂时无法连接，请稍后重试") from exc
    try:
        content = result["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise DeepSeekError("DeepSeek 返回内容无效") from exc
    if not content:
        raise DeepSeekError("DeepSeek 返回了空内容，请重试")
    if not json_mode:
        return content.strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise DeepSeekError("DeepSeek 未返回有效 JSON，请重试") from exc


def assignment_assistant(config, context, message, history):
    system = (
        "你是课程任务助教。只能依据提供的任务说明和讨论上下文回答；不编造提交要求。"
        "回答使用简洁中文，给出可执行建议。"
    )
    context_text = json.dumps({
        "任务标题": context["title"], "任务说明": context["description"],
        "最近讨论": context["recent_discussions"],
    }, ensure_ascii=False)
    messages = [{"role": "system", "content": system}, {"role": "system", "content": context_text}]
    for item in history[-8:]:
        role = item.get("role") if isinstance(item, dict) else None
        content = item.get("content") if isinstance(item, dict) else None
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": str(content)[:4000]})
    messages.append({"role": "user", "content": message[:4000]})
    return deepseek_chat(config, messages, max_tokens=1200)


def generate_questions(config, topic, count, question_type):
    prompt = f"""请围绕“{topic}”生成 {count} 道 {question_type} 类型的课程考试题。
必须输出 json 对象，格式为：
{{"questions":[{{"type":"{question_type}","prompt":"题干","options":[],"answer":"参考答案","points":10}}]}}
type 只能是 single、multiple、true_false、fill、essay。single/multiple 必须给出至少两个 options；其他题型 options 为空数组。题目不得重复，总分可合理分配。"""
    result = deepseek_chat(
        config,
        [{"role": "system", "content": "你是严谨的考试命题专家，必须输出有效 json。"},
         {"role": "user", "content": prompt}],
        model=config.get("DEEPSEEK_REASONING_MODEL"), json_mode=True, max_tokens=6000,
    )
    questions = result.get("questions") if isinstance(result, dict) else None
    if not isinstance(questions, list):
        raise DeepSeekError("DeepSeek 题目结构无效")
    return questions


def enhance_learning_analysis(config, report):
    prompt = """根据以下学习统计生成个性化学情分析。必须输出 json：
{"summary":"两三句话总结","weak_topics":["知识点1","知识点2"],"suggestion":"具体学习建议"}
不要修改或虚构统计数字，建议应具体、温和、可执行。\n""" + json.dumps(report, ensure_ascii=False)
    result = deepseek_chat(
        config,
        [{"role": "system", "content": "你是课程学情分析助手，必须输出有效 json。"},
         {"role": "user", "content": prompt}],
        model=config.get("DEEPSEEK_REASONING_MODEL"), json_mode=True, max_tokens=1600,
    )
    if not isinstance(result, dict):
        raise DeepSeekError("DeepSeek 学情分析结构无效")
    return result


def extract_document_text(path):
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise DeepSeekError("服务器缺少 PDF 解析组件") from exc
        try:
            reader = PdfReader(str(path))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as exc:
            raise DeepSeekError("PDF 文件解析失败，请确认文件未损坏或未加密") from exc
    elif suffix == ".docx":
        try:
            with zipfile.ZipFile(path) as archive:
                root = ElementTree.fromstring(archive.read("word/document.xml"))
        except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as exc:
            raise DeepSeekError("DOCX 文件解析失败，请确认文件未损坏") from exc
        text = "\n".join(node.text or "" for node in root.iter() if node.tag.endswith("}t"))
    elif suffix == ".doc":
        raise DeepSeekError("旧版 DOC 暂不支持自动解析，请另存为 DOCX 后上传")
    else:
        raise DeepSeekError("仅支持 PDF、DOCX 题库识别")
    text = text.strip()
    if not text:
        raise DeepSeekError("文档没有提取到文字；扫描版 PDF 请先进行 OCR")
    return text[:120000]


def recognize_document_questions(config, text, filename):
    prompt = f"""从文件“{filename}”的文本中识别全部考试题、选项和参考答案。
必须输出 json 对象：
{{"questions":[{{"type":"single|multiple|true_false|fill|essay","prompt":"题干","options":[],"answer":"参考答案，可为空","points":0}}]}}
保持原题顺序，不要凭空补题；无法判断分值时使用 0。文档文本如下：\n{text}"""
    result = deepseek_chat(
        config,
        [{"role": "system", "content": "你是试卷结构化识别器，必须输出有效 json。"},
         {"role": "user", "content": prompt}],
        model=config.get("DEEPSEEK_REASONING_MODEL"), json_mode=True, max_tokens=12000,
    )
    questions = result.get("questions") if isinstance(result, dict) else None
    if not isinstance(questions, list) or not questions:
        raise DeepSeekError("文档中没有识别到有效题目")
    return questions
