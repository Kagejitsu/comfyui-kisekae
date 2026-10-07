"""Preset library: discovery, loading and reference resolution.

On-disk preset format (see PLAN.md section 4)::

    {
      "kisekae": 1,
      "name": "Shinobu",
      "extends": "characters/base",                 # optional, whole-preset inheritance
      "sections": {
        "hair":   {"fields": {"color": "blonde hair",          # shorthand
                              "length": {"value": "long hair", "weight": 1.1}}},
        "outfit": {"$ref": "outfits/shinobu-default"},        # same-named section
        "head":   {"$ref": "characters/roxy#head",             # another section...
                   "fields": {"expression": "smug"}}           # ...with local overrides
      },
      "negative": ""
    }

Resolved sections have no ``$ref`` left. Each field records the preset file
that defined it (``source``); a section that came purely from a ``$ref`` keeps
that ref as its ``origin`` so Save Preset can write it back as a reference.
"""

from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from .errors import KisekaeError
from .schema import SCHEMA_VERSION, SECTION_NAMES, get_section

MAX_DEPTH = 32
SUFFIX = ".json"


def check_name(name: str) -> str:
    """Validate a preset name like ``outfits/shinobu-default``.

    Names are POSIX-style relative paths without the ``.json`` suffix. Absolute
    paths, ``..`` and backslashes are refused so a name can never point outside
    a library root.
    """
    if not isinstance(name, str):
        raise KisekaeError(f"preset name must be a string, got {name!r}")
    if not name.strip():
        raise KisekaeError("preset name is empty")
    name = name.strip()
    if name.endswith(SUFFIX):
        name = name[: -len(SUFFIX)]
    p = PurePosixPath(name)
    if "#" in name:
        raise KisekaeError(f"invalid preset name {name!r}: '#' is reserved for 'name#section' references")
    if "\\" in name or p.is_absolute() or any(part in ("..", ".", "") for part in name.split("/")):
        raise KisekaeError(f"invalid preset name {name!r}: use a relative path like 'outfits/maid'")
    return name


@dataclass(frozen=True)
class Root:
    path: Path
    prefix: str = ""  # e.g. "examples/" for the shipped, read-only presets


@dataclass
class Resolved:
    name: str
    description: str
    sections: dict
    negative: str
    files: set[Path] = field(default_factory=set)


class PresetLibrary:
    """Ordered library roots; the first root that has a name wins."""

    def __init__(self, roots: list[Root]):
        self.roots = roots
        self._sections_cache: dict[str, tuple[set[Path], str, set[str]]] = {}

    # -- discovery -------------------------------------------------------

    def path_of(self, name: str) -> Path:
        name = check_name(name)
        for root in self.roots:
            if root.prefix and not name.startswith(root.prefix):
                continue
            rel = name[len(root.prefix):]
            candidate = root.path / (rel + SUFFIX)
            if candidate.is_file():
                return candidate
        raise KisekaeError(f"preset {name!r} not found")

    # -- writing (user root only) -----------------------------------------

    def user_path(self, name: str) -> Path:
        """Where ``name`` would be saved: always the first root, never a
        prefixed (shipped, read-only) one."""
        name = check_name(name)
        if name.startswith("examples/"):
            raise KisekaeError("'examples/' is reserved for the shipped presets; save under another folder")
        root = self.roots[0]
        if root.prefix:
            raise KisekaeError("the first library root is read-only")
        path = root.path / (name + SUFFIX)
        self.check_inside_user_root(path)
        return path

    def check_inside_user_root(self, path: Path) -> None:
        """Refuse paths whose existing parts resolve outside the user root
        (e.g. a symlinked sub-folder pointing elsewhere)."""
        root = self.roots[0].path.resolve()
        probe = path.parent
        while not probe.exists() and probe != probe.parent:
            probe = probe.parent
        if not probe.resolve().is_relative_to(root):
            raise KisekaeError(f"refusing to write outside the preset folder: {path}")

    def forget(self, name: str) -> None:
        self._sections_cache.pop(name, None)

    def list_names(self) -> list[str]:
        names: set[str] = set()
        for root in self.roots:
            if not root.path.is_dir():
                continue
            for dirpath, dirnames, filenames in os.walk(root.path, followlinks=True):
                dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
                for fn in filenames:
                    if fn.endswith(SUFFIX) and not fn.startswith("."):
                        rel = Path(dirpath, fn).relative_to(root.path).as_posix()
                        names.add(root.prefix + rel[: -len(SUFFIX)])
        return sorted(names, key=str.casefold)

    def sections_of(self, name: str) -> set[str] | None:
        """Sections a preset provides, or None if it fails to resolve.

        Cached by file fingerprint: dropdowns of 8 node types call this for
        every preset on each refresh, but only changed files are re-read.
        """
        hit = self._sections_cache.get(name)
        if hit and self.fingerprint(hit[0]) == hit[1]:
            return hit[2]
        try:
            res = self.resolve(name)
        except KisekaeError:
            self._sections_cache.pop(name, None)
            return None
        secs = set(res.sections)
        self._sections_cache[name] = (set(res.files), self.fingerprint(res.files), secs)
        return secs

    def list_with_section(self, section: str) -> list[str]:
        """Presets that provide ``section``. Broken presets are still listed,
        so picking one shows its error instead of it silently vanishing."""
        out = []
        for name in self.list_names():
            secs = self.sections_of(name)
            if secs is None or section in secs:
                out.append(name)
        return out

    # -- loading ---------------------------------------------------------

    def load_raw(self, name: str) -> tuple[dict, Path]:
        path = self.path_of(name)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise KisekaeError(f"{path}: invalid JSON at line {e.lineno} column {e.colno}: {e.msg}") from None
        except OSError as e:
            raise KisekaeError(f"{path}: cannot read: {e.strerror}") from None
        if not isinstance(data, dict):
            raise KisekaeError(f"{path}: top level must be a JSON object")
        version = data.get("kisekae")
        if version != SCHEMA_VERSION:
            raise KisekaeError(
                f"{path}: expected \"kisekae\": {SCHEMA_VERSION}, found {version!r}")
        return data, path

    def resolve(self, name: str) -> Resolved:
        return _Resolver(self).preset(check_name(name), ())

    def resolve_section(self, ref: str, section: str) -> tuple[dict, set[Path]]:
        """Resolve ``ref`` (``name`` or ``name#section``) to one section."""
        r = _Resolver(self)
        sec = r.ref_section(ref, section, ())
        return sec, r.files

    @staticmethod
    def fingerprint(files: set[Path]) -> str:
        """Changes whenever any file involved in a resolution changes."""
        parts = []
        for p in sorted(files):
            try:
                parts.append(f"{p}:{p.stat().st_mtime_ns}")
            except OSError:
                parts.append(f"{p}:missing")
        return "|".join(parts)


class _Resolver:
    def __init__(self, lib: PresetLibrary):
        self.lib = lib
        self.files: set[Path] = set()
        self.cache: dict[str, Resolved] = {}

    def preset(self, name: str, chain: tuple[str, ...]) -> Resolved:
        if name in chain:
            raise KisekaeError("preset reference loop: " + " → ".join(chain + (name,)))
        if len(chain) >= MAX_DEPTH:
            raise KisekaeError(f"preset references nested deeper than {MAX_DEPTH}: " + " → ".join(chain))
        if name in self.cache:
            return self.cache[name]
        chain = chain + (name,)

        raw, path = self.lib.load_raw(name)
        self.files.add(path)
        where = str(path)

        sections: dict = {}
        negative = ""
        if raw.get("extends"):
            base = self.preset(check_name(raw["extends"]), chain)
            sections = copy.deepcopy(base.sections)
            negative = base.negative

        raw_sections = raw.get("sections", {})
        if not isinstance(raw_sections, dict):
            raise KisekaeError(f"{where}: \"sections\" must be an object")
        for sec_name, raw_sec in raw_sections.items():
            if sec_name not in SECTION_NAMES:
                raise KisekaeError(f"{where}: unknown section {sec_name!r} (known: {', '.join(SECTION_NAMES)})")
            local = self.section(sec_name, raw_sec, name, where, chain)
            if sec_name in sections and "$ref" not in raw_sec:
                # extends: merge field-by-field over the inherited section
                sections[sec_name] = _overlay(sections[sec_name], local, raw_sec)
            else:
                sections[sec_name] = local

        if "negative" in raw:
            negative = _str(raw["negative"], f"{where}: negative")
        res = Resolved(
            name=_str(raw.get("name", name), f"{where}: name"),
            description=_str(raw.get("description", ""), f"{where}: description"),
            sections=sections,
            negative=negative,
            files=self.files,
        )
        self.cache[name] = res
        return res

    def section(self, sec_name: str, raw_sec, owner: str, where: str, chain: tuple[str, ...]) -> dict:
        if not isinstance(raw_sec, dict):
            raise KisekaeError(f"{where}: section {sec_name!r} must be an object")
        unknown = set(raw_sec) - {"$ref", "fields", "loras", "negative"}
        if unknown:
            raise KisekaeError(f"{where}: section {sec_name!r} has unknown keys {sorted(unknown)}")

        if "$ref" in raw_sec:
            base = self.ref_section(raw_sec["$ref"], sec_name, chain)
            local = _parse_section(sec_name, raw_sec, owner, where)
            has_local = any(k in raw_sec for k in ("fields", "loras", "negative"))
            out = _overlay(base, local, raw_sec)
            out["origin"] = None if has_local else _canon_ref(raw_sec["$ref"], sec_name)
            return out
        return _parse_section(sec_name, raw_sec, owner, where)

    def ref_section(self, ref, sec_name: str, chain: tuple[str, ...]) -> dict:
        if not isinstance(ref, str):
            raise KisekaeError(f"$ref must be a string, got {ref!r}")
        target, _, target_sec = ref.partition("#")
        target_sec = target_sec or sec_name
        if target_sec not in SECTION_NAMES:
            raise KisekaeError(f"$ref {ref!r}: unknown section {target_sec!r}")
        res = self.preset(check_name(target), chain)
        if target_sec not in res.sections:
            raise KisekaeError(f"$ref {ref!r}: preset {target!r} has no {target_sec!r} section")
        return copy.deepcopy(res.sections[target_sec])


def empty_section() -> dict:
    return {"fields": {}, "loras": [], "negative": "", "origin": None}


def _canon_ref(ref: str, sec_name: str) -> str:
    target, _, target_sec = ref.partition("#")
    target = check_name(target)
    return target if (target_sec or sec_name) == sec_name else f"{target}#{target_sec}"


def _overlay(base: dict, local: dict, raw_sec: dict) -> dict:
    """Apply a section's locally written parts over a base section."""
    out = copy.deepcopy(base)
    out["fields"].update(local["fields"])
    if "loras" in raw_sec:
        out["loras"] = local["loras"]
    if "negative" in raw_sec:
        out["negative"] = local["negative"]
    out["origin"] = None
    return out


def _str(v, what: str) -> str:
    if not isinstance(v, str):
        raise KisekaeError(f"{what} must be a string, got {v!r}")
    return v


def _parse_section(sec_name: str, raw_sec: dict, owner: str, where: str) -> dict:
    schema = get_section(sec_name)
    out = empty_section()
    raw_fields = raw_sec.get("fields", {})
    if not isinstance(raw_fields, dict):
        raise KisekaeError(f"{where}: {sec_name}.fields must be an object")
    for fname, fval in raw_fields.items():
        if fname not in schema.field_names:
            raise KisekaeError(
                f"{where}: unknown field {sec_name}.{fname} (known: {', '.join(schema.field_names)})")
        out["fields"][fname] = _parse_field(fval, f"{where}: {sec_name}.{fname}", owner)

    loras = raw_sec.get("loras", [])
    if not isinstance(loras, list):
        raise KisekaeError(f"{where}: {sec_name}.loras must be a list")
    out["loras"] = [_parse_lora(l, f"{where}: {sec_name}.loras[{i}]") for i, l in enumerate(loras)]
    out["negative"] = _str(raw_sec.get("negative", ""), f"{where}: {sec_name}.negative")
    return out


def _parse_field(fval, what: str, owner: str) -> dict:
    if isinstance(fval, str):
        fval = {"value": fval}
    if not isinstance(fval, dict) or "value" not in fval:
        raise KisekaeError(f"{what}: expected a string or {{\"value\": ...}}")
    unknown = set(fval) - {"value", "weight"}
    if unknown:
        raise KisekaeError(f"{what}: unknown keys {sorted(unknown)}")
    out = {"value": _str(fval["value"], what), "source": f"preset:{owner}"}
    w = fval.get("weight")
    if w is not None:
        if isinstance(w, bool) or not isinstance(w, (int, float)):
            raise KisekaeError(f"{what}: weight must be a number")
        out["weight"] = float(w)
    return out


def _parse_lora(l, what: str) -> dict:
    if isinstance(l, str):
        l = {"name": l}
    if not isinstance(l, dict) or not isinstance(l.get("name"), str) or not l["name"]:
        raise KisekaeError(f"{what}: expected {{\"name\": \"<file>.safetensors\", ...}}")
    unknown = set(l) - {"name", "strength", "clip_strength", "trigger"}
    if unknown:
        raise KisekaeError(f"{what}: unknown keys {sorted(unknown)}")
    strength = l.get("strength", 1.0)
    clip = l.get("clip_strength", strength)
    for v in (strength, clip):
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise KisekaeError(f"{what}: strengths must be numbers")
    return {
        "name": l["name"],
        "strength": float(strength),
        "clip_strength": float(clip),
        "trigger": _str(l.get("trigger", ""), f"{what}.trigger"),
    }
