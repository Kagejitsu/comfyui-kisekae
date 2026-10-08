"""Prompt templates: shipped files plus the user's own (Tansu template page).

A user template with the same name as a shipped one replaces it. Deleting a
user template moves it to ``templates/.trash/``; the template scan only looks
at ``*.txt`` directly in each folder, so trashed files never show up.
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

from .errors import KisekaeError
from .render import parse_template

NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


def check_name(name) -> str:
    if not isinstance(name, str) or not NAME.match(name) or name.endswith(".txt"):
        raise KisekaeError("template names use letters, digits, '-', '_' and '.', e.g. 'anima-portrait'")
    return name


def list_templates(shipped: Path, user: Path) -> list[dict]:
    found: dict[str, dict] = {}
    for origin, d in (("shipped", shipped), ("yours", user)):
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.txt")):
            text = p.read_text(encoding="utf-8")
            if p.stem in found:  # a user file overriding a shipped one
                found[p.stem] = {"name": p.stem, "origin": "override", "text": text,
                                 "shipped_text": found[p.stem]["text"]}
            else:
                found[p.stem] = {"name": p.stem, "origin": origin, "text": text}
    return sorted(found.values(), key=lambda t: (t["name"] != "anima-mixed", t["name"]))


def save_template(user: Path, name: str, text) -> Path:
    name = check_name(name)
    if not isinstance(text, str) or not text.strip():
        raise KisekaeError("the template is empty")
    parse_template(text)  # raises on unknown placeholders or fields
    user.mkdir(parents=True, exist_ok=True)
    path = user / f"{name}.txt"
    tmp = user / f".{name}.txt.tmp"
    tmp.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def trash_template(user: Path, name: str) -> str:
    """Move the user's template to templates/.trash/. Shipped ones can't be deleted."""
    path = user / f"{check_name(name)}.txt"
    if not path.is_file():
        raise KisekaeError(f"{name!r} is not one of your templates (shipped templates can't be deleted)")
    trash = user / ".trash"
    trash.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = trash / f"{stamp}-{name}.txt"
    n = 1
    while dest.exists():  # deleted twice within a second
        n += 1
        dest = trash / f"{stamp}-{name}-{n}.txt"
    os.replace(path, dest)
    return dest.name
