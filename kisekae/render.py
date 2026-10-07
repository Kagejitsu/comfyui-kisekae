"""Template rendering: CHAR -> positive / negative prompt text.

Template rules (PLAN.md section 5.3):

* ``{section}`` places all of a section's fields in schema order.
* ``{section.field}`` places one field, and removes it from that section's
  ``{section}`` placeholder so nothing is printed twice.
* ``{!section.field}`` leaves a field out entirely (e.g. drop prose for a
  tags-only model).
* ``{triggers}`` places LoRA trigger words.
* Literal text in the template is kept (``masterpiece, {style}`` works).
* One template line = one prompt line; empty items and lines are dropped and
  every line but the last ends with a comma.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import loras as lora_mod
from .char import ordered_sections
from .errors import KisekaeError
from .schema import SECTION_NAMES, get_section
from .tags import apply_weight, escape_item, norm_key, split_items

PLACEHOLDER = re.compile(r"\{(!?)([a-z_]+)(?:\.([a-z_]+))?\}")
SPECIAL = ("triggers",)


@dataclass
class Rendered:
    positive: str
    negative: str
    lines: list[str] = field(default_factory=list)
    breakdown: list[tuple[str, list[str]]] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    escaped: list[tuple[str, str]] = field(default_factory=list)
    loras: list[dict] = field(default_factory=list)
    triggers: list[str] = field(default_factory=list)


def parse_template(template: str) -> set[tuple[str, str]]:
    """Validate placeholders; return the explicitly placed/omitted (section, field)s."""
    explicit: set[tuple[str, str]] = set()
    for m in PLACEHOLDER.finditer(template):
        omit, sec, fld = m.group(1), m.group(2), m.group(3)
        if omit and not fld:
            raise KisekaeError(f"template: {m.group(0)} — '!' needs a field, like {{!pose.prose}}")
        if sec in SPECIAL:
            if fld or omit:
                raise KisekaeError(f"template: {{{sec}}} takes no field")
            continue
        if sec not in SECTION_NAMES:
            raise KisekaeError(
                f"template: unknown placeholder {m.group(0)} "
                f"(sections: {', '.join(SECTION_NAMES)}; also {{triggers}})")
        if fld:
            if fld not in get_section(sec).field_names:
                raise KisekaeError(
                    f"template: unknown field {m.group(0)} "
                    f"(fields of {sec}: {', '.join(get_section(sec).field_names)})")
            explicit.add((sec, fld))
    leftover = PLACEHOLDER.sub("", template)
    if "{" in leftover or "}" in leftover:
        raise KisekaeError("template: stray '{' or '}' (placeholders look like {hair} or {hair.color})")
    return explicit


def _field_items(char: dict, sec: str, fld: str) -> list[str]:
    entry = char["sections"].get(sec, {}).get("fields", {}).get(fld)
    if not entry:
        return []
    return [apply_weight(t, entry.get("weight")) for t in split_items(entry["value"])]


def _section_items(char: dict, sec: str, explicit: set[tuple[str, str]]) -> list[str]:
    items: list[str] = []
    for fld in get_section(sec).field_names:
        if (sec, fld) not in explicit:
            items += _field_items(char, sec, fld)
    return items


def render(char: dict, template: str, *, escape: bool = True, dedupe: bool = True,
           include_triggers: bool = True) -> Rendered:
    explicit = parse_template(template)
    out = Rendered(positive="", negative="")
    out.loras = lora_mod.collect(char)
    out.triggers = lora_mod.triggers(out.loras) if include_triggers else []

    seen: set[str] = set()

    def finish(items: list[str]) -> list[str]:
        kept = []
        for it in items:
            if dedupe:
                k = norm_key(it)
                if k in seen:
                    out.removed.append(it)
                    continue
                seen.add(k)
            if escape:
                esc = escape_item(it)
                if esc != it:
                    out.escaped.append((it, esc))
                it = esc
            kept.append(it)
        return kept

    def substitute(m: re.Match) -> str:
        omit, sec, fld = m.group(1), m.group(2), m.group(3)
        if omit:
            return ""
        if sec == "triggers":
            items = out.triggers
        elif fld:
            items = _field_items(char, sec, fld)
        else:
            items = _section_items(char, sec, explicit)
        out.breakdown.append((m.group(0), list(items)))
        return ", ".join(items)

    for tline in template.splitlines():
        items = finish(split_items(PLACEHOLDER.sub(substitute, tline)))
        if items:
            out.lines.append(", ".join(items))
    out.positive = ",\n".join(out.lines)

    neg_sources = [char.get("negative", "")]
    neg_sources += [char["sections"][s].get("negative", "") for s in ordered_sections(char)]
    seen = set()  # negatives dedupe among themselves only
    out.negative = ", ".join(finish(split_items(",".join(neg_sources))))
    return out
