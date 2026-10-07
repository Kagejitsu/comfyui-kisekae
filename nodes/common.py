"""Shared ComfyUI glue: library roots, templates, vocab, LoRA lookup."""

from __future__ import annotations

import os
from pathlib import Path

import folder_paths

from ..kisekae.char import NONE
from ..kisekae.errors import KisekaeError
from ..kisekae.presets import PresetLibrary, Root
from ..kisekae.vocab import Vocab

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"
CHAR = "KISEKAE_CHAR"
CATEGORY = "kisekae"
USER = Path(folder_paths.get_user_directory()) / "default" / "kisekae"

for sub in ("presets", "vocab", "templates"):
    (USER / sub).mkdir(parents=True, exist_ok=True)

# User presets win over the shipped, read-only examples (named "examples/...").
LIB = PresetLibrary([Root(USER / "presets"), Root(DATA / "examples", "examples/")])


def vocab() -> Vocab:
    # Re-read on every node-definition refresh so edits show up after pressing R.
    return Vocab([DATA / "vocab", USER / "vocab"])


def templates() -> dict[str, Path]:
    found: dict[str, Path] = {}
    for d in (DATA / "templates", USER / "templates"):  # user overrides shipped
        if d.is_dir():
            for p in sorted(d.glob("*.txt")):
                found[p.stem] = p
    return found


def template_names() -> list[str]:
    names = sorted(templates())
    if "anima-mixed" in names:  # default first
        names.remove("anima-mixed")
        names.insert(0, "anima-mixed")
    return names


def template_text(name: str, custom: str) -> str:
    if custom and custom.strip():
        return custom
    path = templates().get(name)
    if path is None:
        raise KisekaeError(f"template {name!r} not found")
    return path.read_text(encoding="utf-8")


def preset_fingerprint(name) -> str | float:
    """IS_CHANGED value: changes when any file the preset touches changes."""
    if not name or name == NONE:
        return ""
    try:
        return LIB.fingerprint(LIB.resolve(name).files)
    except KisekaeError:
        return float("nan")  # always re-run, so the real error is shown


def resolve_loras(loras: list[dict]) -> tuple[list[tuple[str, float, float]], list[tuple[dict, str]]]:
    """Map preset LoRA names to ComfyUI's relative names.

    Exact relative path first, then a unique basename match (with or without
    .safetensors), so presets survive reorganising the loras folder.
    Returns (LORA_STACK, [(lora, status)]); missing files are left out.
    """
    available = folder_paths.get_filename_list("loras")
    by_base: dict[str, list[str]] = {}
    for rel in available:
        base = os.path.basename(rel)
        by_base.setdefault(base, []).append(rel)
        by_base.setdefault(os.path.splitext(base)[0], []).append(rel)

    stack, status = [], []
    for l in loras:
        name = l["name"].replace("\\", "/")
        if name in available:
            hit, note = name, "✓"
        else:
            matches = by_base.get(os.path.basename(name), [])
            if len(matches) == 1:
                hit, note = matches[0], f"✓ → {matches[0]}"
            elif matches:
                hit, note = matches[0], f"⚠ {len(matches)} files match, using {matches[0]}"
            else:
                hit, note = None, "✗ NOT FOUND — left out of the stack"
        if hit:
            stack.append((hit, l["strength"], l["clip_strength"]))
        status.append((l, note))
    return stack, status


def show(text: str, result: tuple) -> dict:
    """Return outputs plus text for the node's display box (web/kisekae.js)."""
    return {"ui": {"text": [text]}, "result": result}
