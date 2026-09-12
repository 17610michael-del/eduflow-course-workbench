from __future__ import annotations

import re
from pathlib import Path

from subsystems.ai.services import DeepSeekError, extract_document_text


KNOWLEDGE_EXTENSIONS = {"pdf", "docx", "txt", "md"}
MAX_KNOWLEDGE_TEXT = 300_000
MAX_CHUNKS_PER_DOCUMENT = 500


def extract_knowledge_text(path: str | Path) -> str:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md"}:
        try:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError as exc:
            raise DeepSeekError("文本文件读取失败") from exc
    elif suffix in {".pdf", ".docx"}:
        text = extract_document_text(path)
    else:
        raise DeepSeekError("知识库仅支持 PDF、DOCX、TXT 和 Markdown")
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[\t\u00a0]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        raise DeepSeekError("文档没有提取到可索引文字")
    return text[:MAX_KNOWLEDGE_TEXT]


def chunk_knowledge_text(text: str, *, size: int = 1000, overlap: int = 140) -> list[str]:
    paragraphs = [item.strip() for item in re.split(r"\n\s*\n", text) if item.strip()]
    chunks: list[str] = []
    current = ""

    def append_long(value: str):
        start = 0
        while start < len(value) and len(chunks) < MAX_CHUNKS_PER_DOCUMENT:
            piece = value[start:start + size].strip()
            if piece:
                chunks.append(piece)
            if start + size >= len(value):
                break
            start += max(1, size - overlap)

    for paragraph in paragraphs:
        if len(paragraph) > size:
            if current:
                chunks.append(current)
                current = ""
            append_long(paragraph)
            continue
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= size:
            current = candidate
        else:
            chunks.append(current)
            tail = current[-overlap:].strip()
            current = f"{tail}\n\n{paragraph}".strip() if tail else paragraph
        if len(chunks) >= MAX_CHUNKS_PER_DOCUMENT:
            break
    if current and len(chunks) < MAX_CHUNKS_PER_DOCUMENT:
        chunks.append(current)
    return chunks


def _query_terms(query: str) -> list[str]:
    normalized = str(query or "").lower().strip()
    terms = {word for word in re.findall(r"[a-z0-9_\-]{2,}", normalized)}
    for sequence in re.findall(r"[\u4e00-\u9fff]{2,}", normalized):
        if len(sequence) <= 4:
            terms.add(sequence)
        for width in (2, 3, 4):
            for index in range(max(0, len(sequence) - width + 1)):
                terms.add(sequence[index:index + width])
    return sorted(terms, key=len, reverse=True)[:80]


def rank_knowledge_chunks(rows, query: str, *, limit: int = 6) -> list[dict]:
    query_text = str(query or "").lower().strip()
    terms = _query_terms(query_text)
    scored = []
    for row in rows:
        item = dict(row)
        content = str(item.get("content") or "")
        lowered = content.lower()
        score = 0
        if query_text and query_text in lowered:
            score += 30
        for term in terms:
            count = lowered.count(term)
            if count:
                score += min(count, 5) * max(1, len(term) - 1)
        if score:
            item["score"] = score
            item["snippet"] = re.sub(r"\s+", " ", content).strip()[:180]
            scored.append(item)
    scored.sort(key=lambda item: (-item["score"], item.get("document_id", 0), item.get("chunk_index", 0)))
    if not scored and any(word in query_text for word in ("总结", "概括", "核心", "主要", "全部", "这些资料")):
        for row in list(rows)[:limit]:
            item = dict(row)
            item["score"] = 0
            item["snippet"] = re.sub(r"\s+", " ", str(item.get("content") or "")).strip()[:180]
            scored.append(item)
    return scored[:limit]
