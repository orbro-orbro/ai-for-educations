from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Iterable


_MAIN_PROGRAM = re.compile(r"(?is)(?:func\s+)?main\s*\([^)]*\)\s*\{.*\}")
_ALL_CHANGES = re.compile(
    r"(?i)(replace\s+(?:(?:all|every)\s+)?lines?\s+[\d,\s]+|all\s+modified\s+lines?|final\s+code|完整(?:程序|答案|代码))"
)
_CODE_FENCE = re.compile(r"(?s)```[^\n]*\n(.*?)```")
_DECLARATION_BLOCK = re.compile(
    r"(?is)\b(?:func|class|struct|enum|interface)\s+[A-Za-z_]\w*[^{}]*\{.*\}"
)


def contains_answer_leakage(
    content: str,
    *,
    level: int,
    protected_answers: Iterable[str] = (),
) -> bool:
    if (
        _MAIN_PROGRAM.search(content)
        or _ALL_CHANGES.search(content)
        or (level <= 3 and _DECLARATION_BLOCK.search(content))
    ):
        return True
    for block in _CODE_FENCE.findall(content):
        non_empty = [line for line in block.splitlines() if line.strip()]
        if (
            len(non_empty) >= 8
            or _MAIN_PROGRAM.search(block)
            or (level <= 3 and _DECLARATION_BLOCK.search(block))
        ):
            return True
    normalized = _normalize(content)
    if len(normalized) >= 20:
        for protected in protected_answers:
            protected_normalized = _normalize(protected)
            if protected_normalized and SequenceMatcher(
                None, normalized, protected_normalized
            ).ratio() >= 0.88:
                return True
    if level <= 2 and content.count("\n") >= 12:
        return True
    return False


def _normalize(value: str) -> str:
    return "".join(value.casefold().split()).replace("```cangjie", "").replace("```", "")


def safe_fallback(level: int) -> str:
    return {
        1: "先对照真实错误位置，列出这里可能出现的输入情况。",
        2: "回顾与该位置相关的课程概念，并检查它要求覆盖哪些情况。",
        3: "先列出缺失情况，再只修改对应的局部分支并重新运行。",
        4: "结合真实执行证据逐步复盘根因，再由你完成最终修改。",
    }[level]
