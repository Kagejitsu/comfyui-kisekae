"""Library operations behind the Tansu organizer/editor (see PLAN-tansu.md).

Pure Python like the rest of ``kisekae/``: the aiohttp routes in
``nodes/routes.py`` are a thin layer over these functions. Every write goes to
the user root (the first library root) through the same path checks and
atomic writes as Save Preset; the shipped examples are read-only.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

from .errors import KisekaeError
from .presets import SUFFIX, PresetLibrary, _Resolver, check_name
from .save import atomic_write_json, write_preset
from .schema import SECTION_NAMES, get_section
from .vocab import Vocab

PICTURE_EXTS = (".webp", ".png", ".jpg", ".jpeg")
TRASH = ".trash"
_TRASH_ID = re.compile(r"^\d{8}-\d{6}-\d{3}$")


class Conflict(KisekaeError):
    """The file changed on disk since the editor loaded it."""


# -- small helpers ------------------------------------------------------------

def is_readonly(lib: PresetLibrary, name: str) -> bool:
    return any(r.prefix and name.startswith(r.prefix) for r in lib.roots)


def user_names(lib: PresetLibrary) -> list[str]:
    return [n for n in lib.list_names() if not is_readonly(lib, n)]


def etag(path: Path) -> str | None:
    try:
        st = path.stat()
    except FileNotFoundError:
        return None
    return f"{st.st_mtime_ns}-{st.st_size}"


def picture_of(lib: PresetLibrary, name: str) -> Path | None:
    """The preset's own picture: ``roxy.webp`` (etc.) next to ``roxy.json``."""
    try:
        path = lib.path_of(name)
    except KisekaeError:
        return None
    for ext in PICTURE_EXTS:
        p = path.with_suffix(ext)
        if p.is_file():
            return p
    return None


def norm_tags(tags) -> list[str]:
    if tags is None:
        return []
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        raise KisekaeError('"tags" must be a list of strings')
    out: list[str] = []
    for t in tags:
        t = " ".join(t.split()).lower()
        if t and t not in out:
            out.append(t)
    return out


def refs_out(raw: dict) -> list[str]:
    """Preset names a raw preset points at directly (extends and $refs)."""
    out = []
    ext = raw.get("extends")
    if isinstance(ext, str) and ext:
        out.append(ext)
    secs = raw.get("sections")
    if isinstance(secs, dict):
        for sec in secs.values():
            ref = sec.get("$ref") if isinstance(sec, dict) else None
            if isinstance(ref, str) and ref:
                out.append(ref.partition("#")[0])
    return list(dict.fromkeys(out))


# -- index ----------------------------------------------------------------------

def index(lib: PresetLibrary) -> list[dict]:
    """One summary per preset for the organizer. Broken presets are included
    with their error, never dropped."""
    resolver = _Resolver(lib)  # shared: each referenced preset is read once
    out = []
    for name in lib.list_names():
        entry = {
            "name": name, "title": name.rsplit("/", 1)[-1], "description": "", "tags": [],
            "sections": [], "loras": [], "refs": [], "readonly": is_readonly(lib, name),
            "mtime": 0.0, "picture": False, "search": "", "error": None,
        }
        try:
            raw, path = lib.load_raw(name)
            entry["mtime"] = path.stat().st_mtime
            entry["title"] = raw.get("name") if isinstance(raw.get("name"), str) and raw["name"] else entry["title"]
            entry["description"] = raw.get("description") if isinstance(raw.get("description"), str) else ""
            entry["tags"] = norm_tags(raw.get("tags"))
            entry["refs"] = refs_out(raw)
            entry["picture"] = picture_of(lib, name) is not None
            res = resolver.preset(name, ())
        except KisekaeError as e:
            entry["error"] = str(e)
            out.append(entry)
            continue
        entry["sections"] = list(res.sections)
        words = [entry["title"], entry["description"], *entry["tags"]]
        for sec in res.sections.values():
            words += [f["value"] for f in sec["fields"].values()]
            for l in sec["loras"]:
                entry["loras"].append({"name": l["name"], "strength": l["strength"], "trigger": l["trigger"]})
                words += [l["name"], l["trigger"]]
        entry["search"] = " ".join(w for w in words if w).lower()
        out.append(entry)
    return out


def reverse_refs(entries: list[dict]) -> dict[str, list[str]]:
    """``{target: [presets that reference it directly]}``."""
    used_by: dict[str, list[str]] = {}
    for e in entries:
        for target in e["refs"]:
            used_by.setdefault(target, []).append(e["name"])
    return used_by


def tag_counts(entries: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for e in entries:
        for t in e["tags"]:
            counts[t] = counts.get(t, 0) + 1
    return dict(sorted(counts.items()))


# -- reading & saving -----------------------------------------------------------

def read(lib: PresetLibrary, name: str) -> dict:
    raw, path = lib.load_raw(name)
    return {"name": check_name(name), "data": raw, "etag": etag(path), "readonly": is_readonly(lib, name)}


def validate(lib: PresetLibrary, name: str, data) -> list[str]:
    """Problems that would stop ``data`` loading as ``name`` (empty = fine)."""
    try:
        norm_tags(data.get("tags") if isinstance(data, dict) else None)
        lib.resolve_draft(name, data)
    except KisekaeError as e:
        return [str(e)]
    return []


def save(lib: PresetLibrary, name: str, data, expected: str | None) -> str:
    """Write ``data`` as ``name``; returns the new etag.

    ``expected`` is the etag the editor loaded; ``None`` means "create, must not
    exist". Anything else on disk raises ``Conflict``.
    """
    name = check_name(name)
    path = lib.user_path(name)
    problems = validate(lib, name, data)
    if problems:
        raise KisekaeError(problems[0])
    if "tags" in data:
        data = {**data, "tags": norm_tags(data["tags"])}
        if not data["tags"]:
            del data["tags"]
    current = etag(path)
    if expected is None and current is not None:
        raise Conflict(f"preset {name!r} already exists")
    if expected is not None and current != expected:
        raise Conflict(f"preset {name!r} changed on disk since it was opened"
                       if current else f"preset {name!r} was deleted or moved since it was opened")
    write_preset(lib, name, data, overwrite=True)
    return etag(path)


# -- rename / duplicate ----------------------------------------------------------

def _rewrite(raw: dict, old: str, new: str) -> bool:
    """Point every reference to ``old`` at ``new``. Returns whether anything changed."""
    changed = False
    if raw.get("extends") == old:
        raw["extends"] = new
        changed = True
    secs = raw.get("sections")
    if isinstance(secs, dict):
        for sec in secs.values():
            if not isinstance(sec, dict) or not isinstance(sec.get("$ref"), str):
                continue
            target, hash_, part = sec["$ref"].partition("#")
            if target == old:
                sec["$ref"] = new + hash_ + part
                changed = True
    return changed


def _sidecars(path: Path) -> list[Path]:
    return [path.with_suffix(ext) for ext in PICTURE_EXTS if path.with_suffix(ext).is_file()]


def rename(lib: PresetLibrary, old: str, new: str, *, dry_run: bool) -> list[str]:
    """Move a user preset (and its picture) and rewrite every user preset that
    references it. Returns the names of the presets whose references change.

    Order matters: the new file is written first, then the referrers, then the
    old file goes, so an interruption never leaves a dangling reference.
    """
    old, new = check_name(old), check_name(new)
    if is_readonly(lib, old):
        raise KisekaeError("shipped example presets can't be renamed; duplicate it instead")
    if old == new:
        raise KisekaeError("the new name is the same as the old one")
    old_path = lib.path_of(old)
    if old_path != lib.user_path(old):
        raise KisekaeError(f"preset {old!r} is not in your preset folder")
    new_path = lib.user_path(new)
    if new_path.exists():
        raise KisekaeError(f"preset {new!r} already exists")

    rewrites: dict[str, dict] = {}
    for name in user_names(lib):
        try:
            raw, _ = lib.load_raw(name)
        except KisekaeError:
            continue  # unreadable files can't point anywhere we can fix
        if _rewrite(raw, old, new):
            rewrites[name] = raw
    if dry_run:
        return sorted(rewrites)

    moved = rewrites.pop(old, None)  # a preset that references itself
    data = moved if moved is not None else lib.load_raw(old)[0]
    write_preset(lib, new, data)
    for pic in _sidecars(old_path):
        os.replace(pic, new_path.with_suffix(pic.suffix))
    for name, raw in rewrites.items():
        write_preset(lib, name, raw, overwrite=True)
    old_path.unlink()
    lib.forget(old)
    return sorted(rewrites) + ([old] if moved is not None else [])


def duplicate(lib: PresetLibrary, src: str, dst: str, title: str = "") -> str:
    """Copy any preset (examples included) into the user folder."""
    raw, src_path = lib.load_raw(src)
    if lib.user_path(dst).exists():
        raise KisekaeError(f"preset {check_name(dst)!r} already exists")
    if title:
        raw["name"] = title
    path, _ = write_preset(lib, dst, raw)
    for pic in _sidecars(src_path)[:1]:
        path.with_suffix(pic.suffix).write_bytes(pic.read_bytes())
    return check_name(dst)


# -- trash ---------------------------------------------------------------------

def _trash_root(lib: PresetLibrary) -> Path:
    return lib.roots[0].path / TRASH


def _new_trash_id(lib: PresetLibrary) -> str:
    while True:  # one folder per deletion; ids are timestamps down to the millisecond
        now = time.time()
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now)) + f"-{int(now * 1000) % 1000:03d}"
        if not (_trash_root(lib) / stamp).exists():
            return stamp
        time.sleep(0.002)


def referrers(lib: PresetLibrary, name: str) -> list[str]:
    """User presets that reference ``name`` directly."""
    out = []
    for other in user_names(lib):
        try:
            raw, _ = lib.load_raw(other)
        except KisekaeError:
            continue
        if other != name and name in refs_out(raw):
            out.append(other)
    return out


def trash(lib: PresetLibrary, name: str) -> dict:
    """Move a user preset (and its picture) to ``.trash/<id>/``. Returns the
    trash entry and the presets that still reference it."""
    name = check_name(name)
    if is_readonly(lib, name):
        raise KisekaeError("shipped example presets can't be deleted")
    path = lib.user_path(name)
    if not path.is_file():
        raise KisekaeError(f"preset {name!r} not found")
    still_used = referrers(lib, name)
    stamp = _new_trash_id(lib)
    dest = _trash_root(lib) / stamp / (name + SUFFIX)
    dest.parent.mkdir(parents=True, exist_ok=True)
    lib.check_inside_user_root(dest)
    for pic in _sidecars(path):
        os.replace(pic, dest.with_suffix(pic.suffix))
    os.replace(path, dest)
    lib.forget(name)
    return {"id": stamp, "name": name, "still_used_by": still_used}


def list_trash(lib: PresetLibrary) -> list[dict]:
    root = _trash_root(lib)
    out = []
    if not root.is_dir():
        return out
    for entry in sorted(root.iterdir(), reverse=True):
        if not (entry.is_dir() and _TRASH_ID.match(entry.name)):
            continue
        for p in sorted(entry.rglob("*" + SUFFIX)):
            out.append({"id": entry.name, "name": p.relative_to(entry).as_posix()[: -len(SUFFIX)]})
    return out


def restore(lib: PresetLibrary, trash_id: str, name: str) -> str:
    if not isinstance(trash_id, str) or not _TRASH_ID.match(trash_id):
        raise KisekaeError(f"invalid trash entry {trash_id!r}")
    name = check_name(name)
    src = _trash_root(lib) / trash_id / (name + SUFFIX)
    if not src.is_file():
        raise KisekaeError(f"{name!r} is not in trash entry {trash_id}")
    dest = lib.user_path(name)
    if dest.exists():
        raise KisekaeError(f"a preset named {name!r} exists now; rename it first")
    dest.parent.mkdir(parents=True, exist_ok=True)
    lib.check_inside_user_root(dest)
    for pic in _sidecars(src):
        os.replace(pic, dest.with_suffix(pic.suffix))
    os.replace(src, dest)
    for d in [*src.parents]:  # tidy now-empty folders inside this trash entry
        if d == _trash_root(lib):
            break
        try:
            d.rmdir()
        except OSError:
            break
    lib.forget(name)
    return name


# -- vocab ---------------------------------------------------------------------

def add_vocab(shipped: Path, user: Path, section: str, field: str, value: str) -> list[str]:
    """Add ``value`` to the user's dropdown overlay for ``section.field``.
    Returns the field's dropdown values afterwards."""
    if section not in SECTION_NAMES:
        raise KisekaeError(f"unknown section {section!r}")
    sec = get_section(section)
    if field not in sec.field_names:
        raise KisekaeError(f"unknown field {section}.{field}")
    if not isinstance(value, str) or not value.strip() or "\n" in value:
        raise KisekaeError("dropdown values must be one non-empty line")
    value = value.strip()
    if value in Vocab([shipped, user]).values(section, field):
        return Vocab([shipped, user]).values(section, field)

    path = user / f"{section}.json"
    data: dict = {"fields": {}}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise KisekaeError(f"{path}: invalid JSON at line {e.lineno} column {e.colno}: {e.msg}") from None
        if not isinstance(data, dict) or not isinstance(data.setdefault("fields", {}), dict):
            raise KisekaeError(f'{path}: expected {{"fields": {{...}}}}')
    entry = data["fields"].get(field)
    if entry is None:
        data["fields"][field] = [value]
    elif isinstance(entry, list):
        entry.append(value)
    elif isinstance(entry, dict) and isinstance(entry.setdefault("options", []), list):
        entry["options"].append(value)
    else:
        raise KisekaeError(f"{path}: {field} must be a list or an object with \"options\"")
    user.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, data)
    return Vocab([shipped, user]).values(section, field)
