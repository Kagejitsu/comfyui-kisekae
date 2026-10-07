"""Dropdown values per field.

Shipped files: ``data/vocab/<section>.json``; user overlay files with the same
name add to them::

    {"fields": {
        "color": ["blonde hair", "black hair"],                 # added after shipped values
        "length": {"replace": true, "options": ["long hair"]}   # replaces shipped values
    }}

An option may be a string or ``{"value": ..., "negative": ...}``; the
``negative`` companion is used by phase 3.
"""

from __future__ import annotations

import json
from pathlib import Path

from .errors import KisekaeError
from .schema import SECTIONS


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise KisekaeError(f"{path}: invalid JSON at line {e.lineno} column {e.colno}: {e.msg}") from None
    fields = data.get("fields") if isinstance(data, dict) else None
    if not isinstance(fields, dict):
        raise KisekaeError(f"{path}: expected {{\"fields\": {{...}}}}")
    return fields


def _options(raw, what: str) -> tuple[list[dict], bool]:
    replace = False
    if isinstance(raw, dict):
        replace = bool(raw.get("replace", False))
        raw = raw.get("options", [])
    if not isinstance(raw, list):
        raise KisekaeError(f"{what}: expected a list of options")
    out = []
    for o in raw:
        if isinstance(o, str):
            o = {"value": o}
        if not isinstance(o, dict) or not isinstance(o.get("value"), str) or not o["value"].strip():
            raise KisekaeError(f"{what}: bad option {o!r}")
        out.append({"value": o["value"].strip(), "negative": o.get("negative", "")})
    return out, replace


class Vocab:
    """``options[section][field]`` -> list of {"value", "negative"}."""

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
            seen = {o["value"] for o in have}
            for o in opts:
                if o["value"] not in seen:
                    seen.add(o["value"])
                    have.append(o)
            self.options[sec.name][fname] = have

    def values(self, section: str, field: str) -> list[str]:
        return [o["value"] for o in self.options[section][field]]
