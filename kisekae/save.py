"""CHAR -> preset JSON, and safe writing into the user library."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .char import ordered_sections
from .errors import KisekaeError
from .presets import SUFFIX, PresetLibrary, check_name
from .schema import SCHEMA_VERSION, get_section

RESERVED_PREFIX = "examples/"


def _field_json(f: dict):
    if f.get("weight") not in (None, 1):
        return {"value": f["value"], "weight": f["weight"]}
    return f["value"]


def _lora_json(l: dict) -> dict:
    out = {"name": l["name"], "strength": l["strength"]}
    if l.get("clip_strength", l["strength"]) != l["strength"]:
        out["clip_strength"] = l["clip_strength"]
    if l.get("trigger"):
        out["trigger"] = l["trigger"]
    return out


def _ref_is_safe(lib: PresetLibrary, origin: str, target: Path) -> bool:
    """A section may be written back as ``$ref`` only if that ref still
    resolves and never leads back to the file being written (a loop)."""
    name = origin.partition("#")[0]
    try:
        files = lib.resolve(name).files
    except KisekaeError:
        return False
    return target.resolve() not in {p.resolve() for p in files}


def char_to_preset(char: dict, lib: PresetLibrary, target: str, *, keep_refs: bool = True,
                   name: str = "", description: str = "") -> tuple[dict, list[str]]:
    """Build preset JSON from a CHAR. Returns (data, notes for the user).

    Field-level vocab negatives are folded into the section negative, because
    a saved field is just text: it is no longer a dropdown pick.
    """
    target_path = lib.user_path(target)
    notes: list[str] = []
    sections: dict = {}
    for sec in ordered_sections(char):
        data = char["sections"][sec]
        origin = data.get("origin")
        if keep_refs and origin:
            if _ref_is_safe(lib, origin, target_path):
                sections[sec] = {"$ref": origin}
                notes.append(f"{sec}: saved as $ref {origin}")
                continue
            notes.append(f"{sec}: written in full ($ref {origin} would loop or no longer resolves)")
        fields = {f: _field_json(data["fields"][f])
                  for f in get_section(sec).field_names if f in data["fields"]}
        negs = [data.get("negative", "")] + [data["fields"][f].get("negative", "") for f in fields]
        negative = ", ".join(n for n in negs if n.strip())
        entry: dict = {"fields": fields}
        if data.get("loras"):
            entry["loras"] = [_lora_json(l) for l in data["loras"]]
        if negative:
            entry["negative"] = negative
        if fields or entry.get("loras") or negative:
            sections[sec] = entry
    out = {"kisekae": SCHEMA_VERSION, "name": name or char.get("name") or target.rsplit("/", 1)[-1]}
    if description:
        out["description"] = description
    out["sections"] = sections
    if char.get("negative"):
        out["negative"] = char["negative"]
    return out, notes


def write_preset(lib: PresetLibrary, target: str, data: dict, *, overwrite: bool = False) -> tuple[Path, str]:
    """Write atomically into the user library. Returns (path, status) where
    status is "created", "overwritten" or "unchanged"."""
    path = lib.user_path(target)
    if path.is_symlink():
        raise KisekaeError(f"{path} is a symlink; refusing to write through it")
    if path.exists():
        try:
            if json.loads(path.read_text(encoding="utf-8")) == data:
                return path, "unchanged"  # re-running the same workflow is not an error
        except (OSError, json.JSONDecodeError):
            pass
        if not overwrite:
            raise KisekaeError(f"preset {target!r} already exists; turn on 'overwrite' to replace it")
        status = "overwritten"
    else:
        status = "created"
    path.parent.mkdir(parents=True, exist_ok=True)
    lib.check_inside_user_root(path)  # again, after mkdir: catches symlinked folders
    atomic_write_json(path, data)
    lib.forget(target)
    return path, status


def atomic_write_json(path: Path, data) -> None:
    """Write via a temporary file in the same folder, then rename, so an
    interrupted write never leaves a half-written file."""
    fd, tmp = tempfile.mkstemp(prefix=".kisekae-", suffix=SUFFIX, dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def keep_file_metadata(lib: PresetLibrary, target: str, data: dict) -> dict:
    """Carry the existing file's tags and R-18 flag (and description, when the
    new data has none) into ``data``, so saving from the graph doesn't wipe what was set in
    the Tansu editor."""
    path = lib.user_path(target)
    try:
        old = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return data
    if not isinstance(old, dict):
        return data
    out = {}
    for k, v in data.items():
        out[k] = v
        if k == "name":
            if not data.get("description") and isinstance(old.get("description"), str) and old["description"]:
                out["description"] = old["description"]
            if "tags" not in data and isinstance(old.get("tags"), list) and old["tags"]:
                out["tags"] = old["tags"]
            if "nsfw" not in data and old.get("nsfw") is True:
                out["nsfw"] = True
    return out
