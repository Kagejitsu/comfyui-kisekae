"""Text reports for the Debug JSON and Debug Prompt nodes."""

from __future__ import annotations

import json
import re

from .char import ordered_sections
from .render import Rendered

DEBUG_VIEWS = ("resolved", "sources", "trace")
ALL = "(all)"


def _sections(char: dict, section: str) -> list[str]:
    secs = ordered_sections(char)
    return secs if section == ALL else [s for s in secs if s == section]


def char_json(char: dict, view: str = "resolved", section: str = ALL) -> str:
    """``resolved``: clean values. ``sources``: where every value came from.
    ``trace``: what each node did, in order."""
    if view == "trace":
        lines = [f"{i:>3}. {t}" for i, t in enumerate(char.get("trace", []), 1)]
        return "\n".join(lines) or "(no operations yet)"

    out: dict = {"name": char.get("name", "")}
    sections: dict = {}
    for sec in _sections(char, section):
        data = char["sections"][sec]
        entry: dict = {}
        fields = {}
        for fname, f in data["fields"].items():
            if view == "sources":
                fields[fname] = {k: v for k, v in f.items()}
            elif f.get("weight") not in (None, 1):
                fields[fname] = {"value": f["value"], "weight": f["weight"]}
            else:
                fields[fname] = f["value"]
        entry["fields"] = fields
        if data.get("loras"):
            entry["loras"] = data["loras"]
        if data.get("negative"):
            entry["negative"] = data["negative"]
        if view == "sources" and data.get("origin"):
            entry["origin"] = f"$ref {data['origin']}"
        sections[sec] = entry
    out["sections"] = sections
    if char.get("negative") and section == ALL:
        out["negative"] = char["negative"]
    return json.dumps(out, indent=2, ensure_ascii=False)


_TOKENISH = re.compile(r"\w+|[^\w\s]")


def rough_tokens(text: str) -> int:
    """Very rough token estimate (words + punctuation), NOT the real tokenizer."""
    return len(_TOKENISH.findall(text))


def prompt_report(r: Rendered, lora_status: list[tuple[dict, str]]) -> str:
    """Debug Prompt view. ``lora_status``: (lora, resolved path or warning)."""
    parts = ["── POSITIVE ──", r.positive or "(empty)",
             "", "── NEGATIVE ──", r.negative or "(empty)",
             "", "── PLACEHOLDERS ──"]
    for ph, items in r.breakdown:
        parts.append(f"{ph:<22} → {', '.join(items) if items else '(empty)'}")
    if r.removed:
        parts += ["", "── DUPLICATES REMOVED ──", ", ".join(r.removed)]
    if r.escaped:
        parts += ["", "── BRACKETS ESCAPED ──"]
        parts += [f"{a}  →  {b}" for a, b in r.escaped]
    if lora_status:
        parts += ["", "── LORAS ──"]
        for l, status in lora_status:
            parts.append(f"[{l['section']}] {l['name']}  {l['strength']:g}/{l['clip_strength']:g}  {status}")
    if r.triggers:
        parts += ["", "── TRIGGERS ──", ", ".join(r.triggers)]
    parts += ["", f"≈ {rough_tokens(r.positive)} tokens (rough estimate, not the model's tokenizer)"]
    return "\n".join(parts)
