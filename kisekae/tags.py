"""Low-level tag string handling: splitting, normalising, escaping, weights.

ComfyUI's tokenizers (including Anima's Qwen3 one) parse ``(text)`` and
``(text:1.2)`` as emphasis, so a booru tag like ``menacing (jojo)`` is read as
``menacing`` + ``jojo``x1.1 unless its brackets are escaped as ``\\(`` ``\\)``.
"""

from __future__ import annotations

import re

_WEIGHT_TAIL = re.compile(r":\s*-?\d+(?:\.\d+)?\s*$")
_WS = re.compile(r"\s+")


def split_items(text: str) -> list[str]:
    """Split on commas and newlines, but not inside unescaped brackets.

    Keeps a user-typed group like ``(a, b:1.2)`` together as one item.
    """
    items: list[str] = []
    buf: list[str] = []
    depth = 0
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            buf.append(text[i:i + 2])
            i += 2
            continue
        if ch == "(":
            depth += 1
        elif ch == ")" and depth > 0:
            depth -= 1
        if ch in ",\n" and depth == 0:
            items.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    items.append("".join(buf))
    return [s for s in (_WS.sub(" ", it).strip() for it in items) if s]


def norm_key(item: str) -> str:
    """Comparison key for dedupe: case/whitespace-insensitive, escapes ignored."""
    return _WS.sub(" ", item.replace("\\(", "(").replace("\\)", ")")).strip().lower()


def escape_item(item: str) -> str:
    """Escape every bracket pair that is not ``(text:number)`` weight syntax.

    Nested is handled: ``(menacing (jojo):1.2)`` -> ``(menacing \\(jojo\\):1.2)``.
    Already-escaped brackets and unmatched brackets are handled too.
    """
    escape_at: set[int] = set()
    stack: list[int] = []
    i = 0
    while i < len(item):
        ch = item[i]
        if ch == "\\":
            i += 2  # skip whatever is already escaped
            continue
        if ch == "(":
            stack.append(i)
        elif ch == ")":
            if not stack:
                escape_at.add(i)
            else:
                start = stack.pop()
                if not _WEIGHT_TAIL.search(item[start + 1:i]):
                    escape_at.update((start, i))
        i += 1
    escape_at.update(stack)  # unmatched "("
    if not escape_at:
        return item
    return "".join("\\" + c if n in escape_at else c for n, c in enumerate(item))


def apply_weight(item: str, weight: float | None) -> str:
    if weight is None or weight == 1:
        return item
    return f"({item}:{weight:g})"


def merge_tags(existing: str, new: str) -> str:
    """Append ``new`` tags after ``existing``, dropping exact repeats."""
    seen = {norm_key(t) for t in split_items(existing)}
    out = split_items(existing)
    for t in split_items(new):
        k = norm_key(t)
        if k not in seen:
            seen.add(k)
            out.append(t)
    return ", ".join(out)


def merge_text(existing: str, new: str) -> str:
    """Append prose: a space after sentence punctuation, else a comma."""
    existing, new = existing.strip(), new.strip()
    if not existing:
        return new
    if not new:
        return existing
    sep = " " if existing[-1] in ".!?," else ", "
    return existing + sep + new
