"""把题库原文排成易读的参考答案；不改动评分要点。"""

from __future__ import annotations

import html
import re


def _is_heading(text: str, has_next: bool) -> bool:
    """识别原文中的短分节名，如「构造函数」「数组转List」。"""
    return (has_next and 2 <= len(text) <= 14
            and not re.search(r"[，,。；;：:？！?！()（）<>\n]", text))


def _is_code(text: str) -> bool:
    stripped = text.lstrip()
    return ("->" in stripped or stripped.startswith((
        "Map<", "List<", "Set<", "public ", "private ", "SELECT ", "select ",
    )))


def _readable_paragraphs(text: str) -> str:
    """只改变视觉断行，保留原句与标点。"""
    blocks = []
    for line in text.splitlines() or [text]:
        line = line.strip()
        if not line:
            continue
        if _is_code(line):
            blocks.append(f'<pre class="answer-code"><code>{html.escape(line)}</code></pre>')
            continue
        if len(line) <= 160:
            blocks.append(f"<p>{html.escape(line)}</p>")
            continue
        pieces = re.findall(r"[^，。；]+[，。；]?", line)
        paragraphs = []
        current = ""
        for piece in pieces:
            current += piece
            if len(current) >= 85:
                paragraphs.append(current)
                current = ""
        if current:
            if paragraphs and len(current) < 35:
                paragraphs[-1] += current
            else:
                paragraphs.append(current)
        blocks.extend(f"<p>{html.escape(part)}</p>" for part in paragraphs)
    return "".join(blocks)


def render_reference_answer(question: dict) -> str:
    """统一用于看答案、判分结果和错题集。"""
    raw_points = question.get("core_points") or question.get("rubric") or []
    points = [str(point).strip() for point in raw_points if str(point).strip()]

    sections: list[tuple[str, list[str]]] = []
    heading = ""
    entries: list[str] = []
    for index, point in enumerate(points):
        if _is_heading(point, index + 1 < len(points)):
            if entries:
                sections.append((heading, entries))
                entries = []
            heading = point
        else:
            entries.append(point)
    if entries:
        sections.append((heading, entries))

    output = ['<div class="answer-layout">']
    if not points:
        output.append('<div class="answer-empty">本题暂无具体参考答案，提交后由 AI 独立判断并评分。</div>')
    number = 0
    for heading, entries in sections:
        output.append('<section class="answer-section">')
        if heading:
            output.append(f'<h4 class="answer-heading">{html.escape(heading)}</h4>')
        output.append('<div class="answer-points">')
        for entry in entries:
            number += 1
            output.append(
                '<div class="answer-point">'
                f'<span class="answer-index">{number:02d}</span>'
                f'<div class="answer-body">{_readable_paragraphs(entry)}</div>'
                '</div>'
            )
        output.append('</div></section>')

    extras = [str(x).strip() for x in question.get("extra_points") or [] if str(x).strip()]
    if extras:
        output.append('<details class="answer-extra"><summary>补充说明</summary>')
        for extra in extras:
            output.append(f'<div class="answer-extra-item">{_readable_paragraphs(extra)}</div>')
        output.append('</details>')
    output.append('</div>')
    return "".join(output)
