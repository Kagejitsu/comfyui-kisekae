"""Dropdown values per field, with optional negatives and conflict rules.

Shipped files: ``data/vocab/<section>.json``; user overlay files with the same
name add to them::

    {"fields": {
        "color": ["blonde hair", "black hair"],                  # added after shipped values
        "length": {"replace": true, "options": ["long hair"]},   # replaces shipped values
        "full": {
            "hides": ["outfit.upper", "outfit.lower"],           # default for every option
            "options": [
                "dress",
                {"value": "maid apron", "hides": []},             # per-option override
                {"value": "short hair", "negative": "long hair"}  # companion negative
            ]}
    }}

Both extras apply to **dropdown picks only**; preset text and typed text are
never pruned and add no negatives.

* ``negative``: added to the negative prompt while the picked value is in place.
* ``hides``: picking the value clears those fields (``section.field``) of the
  incoming character, unless the same node sets them explicitly.
"""

from __future__ import annotations

import json
from pathlib import Path

from .errors import KisekaeError
from .schema import SECTION_NAMES, SECTIONS, get_section


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise KisekaeError(f"{path}: invalid JSON at line {e.lineno} column {e.colno}: {e.msg}") from None
    fields = data.get("fields") if isinstance(data, dict) else None
    if not isinstance(fields, dict):
        raise KisekaeError(f"{path}: expected {{\"fields\": {{...}}}}")
    return fields


def _hides(raw, what: str) -> list[str]:
    if not isinstance(raw, list) or not all(isinstance(h, str) for h in raw):
        raise KisekaeError(f"{what}: \"hides\" must be a list like [\"outfit.upper\"]")
    for h in raw:
        sec, _, fld = h.partition(".")
        if sec not in SECTION_NAMES or fld not in get_section(sec).field_names:
            raise KisekaeError(f"{what}: \"hides\" names unknown field {h!r}")
    return list(raw)


def _options(raw, what: str) -> tuple[list[dict], bool]:
    replace, default_hides = False, []
    if isinstance(raw, dict):
        replace = bool(raw.get("replace", False))
        default_hides = _hides(raw.get("hides", []), what)
        raw = raw.get("options", [])
    if not isinstance(raw, list):
        raise KisekaeError(f"{what}: expected a list of options")
    out = []
    for o in raw:
        if isinstance(o, str):
            o = {"value": o}
        if not isinstance(o, dict) or not isinstance(o.get("value"), str) or not o["value"].strip():
            raise KisekaeError(f"{what}: bad option {o!r}")
        neg = o.get("negative", "")
        if not isinstance(neg, str):
            raise KisekaeError(f"{what}: negative of {o['value']!r} must be a string")
        hides = _hides(o["hides"], what) if "hides" in o else default_hides
        out.append({"value": o["value"].strip(), "negative": neg, "hides": hides})
    return out, replace


class Vocab:
    """``options[section][field]`` -> list of {"value", "negative", "hides"}."""

    def __init__(self, dirs: list[Path]):
        # dirs in load order: shipped first, user overlays after
        self.options: dict[str, dict[str, list[dict]]] = {
            s.name: {f.name: [] for f in s.fields} for s in SECTIONS}
        self.errors: list[str] = []
        for d in dirs:
            for sec in SECTIONS:
                path = d / f"{sec.name}.json"
                if not path.is_file():
                    continue
                try:
                    self._merge(sec, _read(path), path)
                except KisekaeError as e:
                    # A broken vocab file must not take the whole node pack down.
                    self.errors.append(str(e))

    def _merge(self, sec, fields: dict, path: Path) -> None:
        for fname, raw in fields.items():
            if fname not in sec.field_names:
                raise KisekaeError(f"{path}: unknown field {sec.name}.{fname}")
            opts, replace = _options(raw, f"{path}: {sec.name}.{fname}")
            have = [] if replace else self.options[sec.name][fname]
            index = {o["value"]: i for i, o in enumerate(have)}
            for o in opts:
                if o["value"] in index:
                    have[index[o["value"]]] = o  # overlay redefines negative/hides
                else:
                    index[o["value"]] = len(have)
                    have.append(o)
            self.options[sec.name][fname] = have

    def values(self, section: str, field: str) -> list[str]:
        return [o["value"] for o in self.options[section][field]]

    def option(self, section: str, field: str, value: str) -> dict | None:
        for o in self.options[section][field]:
            if o["value"] == value:
                return o
        return None
