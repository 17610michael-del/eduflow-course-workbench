from __future__ import annotations

import json
from datetime import datetime, timedelta

QUESTION_TYPES = {"single", "multiple", "true_false", "fill", "essay"}


def normalize_questions(raw: str) -> list[dict]:
    """Validate the browser question-builder payload and return stable question records."""
    if not raw.strip():
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        # Backward compatibility for exams created before the question builder.
        return [{"id": "q1", "type": "essay", "prompt": raw.strip(), "options": [], "points": 100}]
    if not isinstance(value, list):
        raise ValueError("机考题目格式无效")
    result = []
    for index, item in enumerate(value, 1):
        if not isinstance(item, dict):
            raise ValueError(f"第 {index} 题格式无效")
        question_type = str(item.get("type", "essay"))
        prompt = str(item.get("prompt", "")).strip()
        if question_type not in QUESTION_TYPES or not prompt:
            raise ValueError(f"请完整填写第 {index} 题")
        options = [str(x).strip() for x in item.get("options", []) if str(x).strip()]
        if question_type in {"single", "multiple"} and len(options) < 2:
            raise ValueError(f"第 {index} 题至少需要两个选项")
        points = int(item.get("points", 0) or 0)
        if points < 0 or points > 100:
            raise ValueError(f"第 {index} 题分值需为 0 到 100")
        result.append({"id": f"q{index}", "type": question_type, "prompt": prompt,
                       "options": options, "answer": item.get("answer", ""), "points": points})
    return result


def attempt_deadline(started_at: datetime, exam_end: datetime, duration_minutes: int) -> datetime:
    return min(exam_end, started_at + timedelta(minutes=max(duration_minutes, 1)))
