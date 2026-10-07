"""The runtime character state (``KISEKAE_CHAR``) passed between nodes.

A CHAR is a plain dict so it serialises straight into the Debug JSON view::

    {"kisekae": 1, "name": "...", "sections": {<section>: <resolved section>},
     "negative": "...", "trace": ["what each node did", ...]}

Every mutating helper works on a deep copy and returns it, so one CHAR can
safely feed several branches of a workflow.
"""

from __future__ import annotations

import copy

from .errors import KisekaeError
from .presets import Resolved, empty_section
from .schema import SCHEMA_VERSION, SECTION_NAMES, get_section
from .tags import merge_tags, merge_text

# Dropdown sentinels shared with the nodes.
KEEP = "(keep)"
CLEAR = "(clear)"
NONE = "(none)"

LOAD_MODES = ("replace", "overlay", "merge")


def new_char(name: str = "") -> dict:
    return {"kisekae": SCHEMA_VERSION, "name": name, "sections": {}, "negative": "", "trace": []}


def copy_char(char: dict | None) -> dict:
    if char is None:
        return new_char()
    if not isinstance(char, dict) or char.get("kisekae") != SCHEMA_VERSION:
        raise KisekaeError("input is not a kisekae character")
    return copy.deepcopy(char)


def ordered_sections(char: dict) -> list[str]:
    """Section names present in ``char``, in schema order."""
    return [s for s in SECTION_NAMES if s in char["sections"]]


def load_preset(char: dict | None, preset: Resolved, ref_name: str, mode: str = "replace") -> dict:
    """Apply a whole resolved preset.

    ``replace``: the result is exactly the preset.
    ``overlay``: the preset's sections replace whole sections; others are kept.
    ``merge``:   the preset's fields replace single fields; everything else is
                 kept (a scene preset can set head.expression without wiping
                 the character's eyes). LoRAs and negatives are added.
    """
    if mode not in LOAD_MODES:
        raise KisekaeError(f"unknown load mode {mode!r} (use {', '.join(LOAD_MODES)})")
    out = copy_char(char)
    if mode == "replace":
        out["sections"] = {}
        out["negative"] = preset.negative
    elif preset.negative:
        out["negative"] = merge_tags(out["negative"], preset.negative)

    if mode == "merge":
        for name, sec in preset.sections.items():
            if name not in out["sections"]:
                out["sections"][name] = copy.deepcopy(sec)
                continue
            have = out["sections"][name]
            have["fields"].update(copy.deepcopy(sec["fields"]))
            have["loras"] = have.get("loras", []) + copy.deepcopy(sec.get("loras", []))
            if sec.get("negative"):
                have["negative"] = merge_tags(have.get("negative", ""), sec["negative"])
            have["origin"] = None
    else:
        out["sections"].update(copy.deepcopy(preset.sections))
        out["name"] = preset.name
    out["trace"].append(f"load preset {ref_name} ({mode})")
    return out


def set_section(char: dict | None, section: str, data: dict, note: str) -> dict:
    """Replace a whole section (its fields, LoRAs and negative)."""
    get_section(section)
    out = copy_char(char)
    out["sections"][section] = copy.deepcopy(data)
    out["trace"].append(note)
    return out


def apply_field(char: dict, section: str, field: str, *, choice: str = KEEP,
                text: str = "", append: bool = False, source: str = "",
                note_prefix: str = "") -> dict:
    """Apply one field override, mutating ``char`` in place (callers copy first).

    Precedence: typed ``text`` (if not blank) > dropdown ``choice`` > incoming.
    ``choice`` may be KEEP (pass through) or CLEAR (empty the field).
    ``append`` adds to the incoming value instead of replacing it.
    """
    spec = get_section(section).field(field)
    text = (text or "").strip()
    if text:
        new, how = text, "typed"
    elif choice == CLEAR:
        sec = char["sections"].get(section)
        if sec and sec["fields"].pop(field, None) is not None:
            sec["origin"] = None
            char["trace"].append(f"{note_prefix}{section}.{field} cleared")
        return char
    elif choice in (KEEP, NONE, "", None):
        return char
    else:
        new, how = choice, "dropdown"

    sec = char["sections"].setdefault(section, empty_section())
    sec["origin"] = None  # edited, so no longer a pure reference
    old = sec["fields"].get(field)
    if append and old and old["value"].strip():
        merge = merge_text if spec.kind == "text" else merge_tags
        value = merge(old["value"], new)
        entry = dict(old, value=value, source=f"{old['source']} + {source}".strip(" +"))
        verb = "appended"
    else:
        entry = {"value": new, "source": source}
        verb = "set"
    sec["fields"][field] = entry
    char["trace"].append(f"{note_prefix}{section}.{field} {verb} ({how}): {new}")
    return char
