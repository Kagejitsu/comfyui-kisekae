"""Tansu web routes: the organizer/editor page and its JSON API (PLAN-tansu.md §5).

A thin aiohttp layer over ``kisekae/library.py``. Writes are POST/PUT, which
ComfyUI's origin-only middleware already protects from cross-site requests.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import os
from pathlib import Path

import folder_paths
from aiohttp import web
from server import PromptServer

from ..kisekae import char as C
from ..kisekae import library as L
from ..kisekae import templates as T
from ..kisekae.errors import KisekaeError
from ..kisekae.loras import collect
from ..kisekae.render import render
from ..kisekae.report import rough_tokens
from ..kisekae.schema import SECTIONS
from .common import DATA, LIB, REPO, USER, resolve_loras, template_names, template_text, vocab

UI = REPO / "ui"
log = logging.getLogger("kisekae")
routes = PromptServer.instance.routes

# LoRA Manager's preview naming, in its order of preference (py/utils/constants.py there).
LORA_PREVIEW_EXTS = (".webp", ".preview.webp", ".preview.png", ".preview.jpeg", ".preview.jpg",
                     ".preview.mp4", ".png", ".jpeg", ".jpg", ".mp4", ".gif", ".webm", ".avif")
VIDEO_EXTS = (".mp4", ".webm")


def _json(data, status: int = 200) -> web.Response:
    return web.json_response(data, status=status, dumps=lambda d: json.dumps(d, ensure_ascii=False))


def _error(e: Exception) -> web.Response:
    if isinstance(e, L.Conflict):
        return _json({"error": str(e), "conflict": True}, 409)
    if isinstance(e, KisekaeError):
        return _json({"error": str(e)}, 400)
    log.exception("kisekae: unexpected error in Tansu API")
    return _json({"error": f"{type(e).__name__}: {e}"}, 500)


def api(handler):
    async def wrapped(request: web.Request) -> web.Response:
        try:
            return await handler(request)
        except web.HTTPException:
            raise  # deliberate HTTP responses such as 404
        except Exception as e:  # every other error becomes {"error": ...} for the UI
            return _error(e)
    return wrapped


async def _body(request: web.Request) -> dict:
    try:
        data = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise KisekaeError("request body must be JSON") from None
    if not isinstance(data, dict):
        raise KisekaeError("request body must be a JSON object")
    return data


def _arg(data: dict, key: str) -> str:
    v = data.get(key)
    if not isinstance(v, str) or not v.strip():
        raise KisekaeError(f"missing {key!r}")
    return v


# -- pictures -------------------------------------------------------------------

def _inside(path: Path, roots: list[str]) -> bool:
    real = path.resolve()
    return any(real.is_relative_to(Path(r).resolve()) for r in roots)


def _lora_preview(lora_name: str) -> tuple[Path, int] | None:
    """(file, nsfw level) of a LoRA's LoRA Manager preview, if there is one."""
    stack, _ = resolve_loras([{"name": lora_name, "strength": 1.0, "clip_strength": 1.0}])
    if not stack:
        return None
    full = folder_paths.get_full_path("loras", stack[0][0])
    if not full:
        return None
    stem = os.path.splitext(full)[0]
    nsfw, preview = 0, None
    try:
        meta = json.loads(Path(stem + ".metadata.json").read_text(encoding="utf-8"))
        nsfw = int(meta.get("preview_nsfw_level") or 0)
        if isinstance(meta.get("preview_url"), str) and meta["preview_url"]:
            preview = Path(meta["preview_url"])
    except (OSError, ValueError, AttributeError):
        pass
    candidates = [preview] if preview else []
    candidates += [Path(stem + ext) for ext in LORA_PREVIEW_EXTS]
    loras_dirs = folder_paths.get_folder_paths("loras")
    for p in candidates:
        if p.is_file() and _inside(p, loras_dirs):
            return p, nsfw
    return None


def _picture(name: str, entry: dict | None = None, depth: int = 0) -> dict | None:
    """Where a preset's card picture comes from (PLAN-tansu.md §3): its own
    picture, else a LoRA preview, else the picture of the preset it extends."""
    own = L.picture_of(LIB, name)
    if own:
        return {"kind": "own", "path": own, "nsfw": 0}
    loras = (entry or {}).get("loras")
    if loras is None:
        try:
            loras = collect(C.load_preset(None, LIB.resolve(name), name))
        except KisekaeError:
            return None
    for lora in loras:  # first LoRA that has a preview
        hit = _lora_preview(lora["name"])
        if hit:
            return {"kind": "lora", "path": hit[0], "nsfw": hit[1]}
    try:
        parent = LIB.load_raw(name)[0].get("extends")
    except KisekaeError:
        return None
    if isinstance(parent, str) and parent and depth < 8:
        return _picture(parent, None, depth + 1)
    return None


# -- page & static ---------------------------------------------------------------

@routes.get("/kisekae")
async def page(request: web.Request) -> web.Response:
    return web.FileResponse(UI / "index.html", headers={"Cache-Control": "no-cache"})


@routes.get("/kisekae/static/{path:.+}")
async def static(request: web.Request) -> web.Response:
    path = (UI / request.match_info["path"]).resolve()
    if not path.is_relative_to(UI.resolve()) or not path.is_file():
        raise web.HTTPNotFound()
    ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if path.suffix == ".js":
        ctype = "text/javascript"
    return web.FileResponse(path, headers={"Cache-Control": "no-cache", "Content-Type": ctype})


# -- API -------------------------------------------------------------------------

@routes.get("/kisekae/api/library")
@api
async def library(request: web.Request) -> web.Response:
    entries = L.index(LIB)
    for e in entries:
        pic = _picture(e["name"], e if not e["error"] else None)
        e["picture"] = None if pic is None else {
            "kind": pic["kind"], "nsfw": pic["nsfw"], "video": pic["path"].suffix.lower() in VIDEO_EXTS,
            "version": int(pic["path"].stat().st_mtime)}
    return _json({"presets": entries, "used_by": L.reverse_refs(entries), "tags": L.tag_counts(entries),
                  "trash": len(L.list_trash(LIB))})


@routes.get("/kisekae/api/picture")
@api
async def picture(request: web.Request) -> web.Response:
    pic = _picture(L.check_name(request.query.get("name", "")))
    if pic is None:
        raise web.HTTPNotFound()
    return web.FileResponse(pic["path"], headers={"Cache-Control": "max-age=60"})


@routes.get("/kisekae/api/preset")
@api
async def get_preset(request: web.Request) -> web.Response:
    return _json(L.read(LIB, request.query.get("name", "")))


@routes.put("/kisekae/api/preset")
@api
async def put_preset(request: web.Request) -> web.Response:
    body = await _body(request)
    expected = body.get("etag")
    if expected is not None and not isinstance(expected, str):
        raise KisekaeError("etag must be a string or null")
    return _json({"etag": L.save(LIB, _arg(body, "name"), body.get("data"), expected)})


@routes.post("/kisekae/api/render")
@api
async def render_preset(request: web.Request) -> web.Response:
    """Render a saved preset, or unsaved ``data`` as if saved under ``name``."""
    body = await _body(request)
    name = _arg(body, "name")
    if "data" in body:
        problems = L.validate(LIB, name, body["data"])
        if problems:
            return _json({"problems": problems})
        resolved = LIB.resolve_draft(name, body["data"])
    else:
        resolved = LIB.resolve(name)
    template = template_text(body.get("template") or "anima-mixed", body.get("template_text") or "")
    r = render(C.load_preset(None, resolved, name), template)
    _stack, status = resolve_loras(r.loras)
    return _json({
        "problems": [], "positive": r.positive, "negative": r.negative, "tokens": rough_tokens(r.positive),
        # resolved field values, so the editor can show what a $ref/extends section inherits
        "sections": {sec: {f: v["value"] for f, v in data["fields"].items()}
                     for sec, data in resolved.sections.items()},
        "breakdown": [[ph, items] for ph, items in r.breakdown],
        "neg_conflicts": r.neg_conflicts,
        "loras": [{"name": l["name"], "strength": l["strength"], "clip_strength": l["clip_strength"],
                   "trigger": l["trigger"], "section": l.get("section", ""), "status": s} for l, s in status],
    })


@routes.post("/kisekae/api/rename")
@api
async def rename(request: web.Request) -> web.Response:
    body = await _body(request)
    changed = L.rename(LIB, _arg(body, "from"), _arg(body, "to"), dry_run=bool(body.get("dry_run", True)))
    return _json({"changed": changed})


@routes.post("/kisekae/api/duplicate")
@api
async def duplicate(request: web.Request) -> web.Response:
    body = await _body(request)
    return _json({"name": L.duplicate(LIB, _arg(body, "from"), _arg(body, "to"), body.get("title") or "")})


@routes.post("/kisekae/api/trash")
@api
async def trash(request: web.Request) -> web.Response:
    body = await _body(request)
    return _json(L.trash(LIB, _arg(body, "name")))


@routes.get("/kisekae/api/trash")
@api
async def list_trash(request: web.Request) -> web.Response:
    return _json({"entries": L.list_trash(LIB)})


@routes.post("/kisekae/api/restore")
@api
async def restore(request: web.Request) -> web.Response:
    body = await _body(request)
    return _json({"name": L.restore(LIB, _arg(body, "id"), _arg(body, "name"))})


@routes.get("/kisekae/api/schema")
@api
async def schema(request: web.Request) -> web.Response:
    v = vocab()
    return _json({
        "sections": [{"name": s.name, "label": s.label,
                      "fields": [{"name": f.name, "kind": f.kind, "multiline": f.multiline,
                                  "values": v.values(s.name, f.name)} for f in s.fields]}
                     for s in SECTIONS],
        "templates": template_names(),
    })


@routes.post("/kisekae/api/vocab")
@api
async def add_vocab(request: web.Request) -> web.Response:
    body = await _body(request)
    values = L.add_vocab(DATA / "vocab", USER / "vocab", _arg(body, "section"), _arg(body, "field"),
                         _arg(body, "value"))
    return _json({"values": values})


@routes.get("/kisekae/api/loras")
@api
async def loras(request: web.Request) -> web.Response:
    """LoRA files for the editor's picker, with LoRA Manager trigger words when known."""
    q = request.query.get("q", "").lower()
    out = []
    for rel in folder_paths.get_filename_list("loras"):
        if q and q not in rel.lower():
            continue
        triggers: list[str] = []
        full = folder_paths.get_full_path("loras", rel)
        if full:
            try:
                meta = json.loads(Path(os.path.splitext(full)[0] + ".metadata.json").read_text(encoding="utf-8"))
                words = (meta.get("civitai") or {}).get("trainedWords") or meta.get("trainedWords") or []
                triggers = [w for w in words if isinstance(w, str)]
            except (OSError, ValueError, AttributeError):
                pass
        out.append({"name": rel, "triggers": triggers})
        if len(out) >= 200:
            break
    return _json({"loras": out})


# -- dropdowns (vocab) and templates: Tansu phase 2 ----------------------------------

@routes.get("/kisekae/api/vocab/field")
@api
async def get_vocab_field(request: web.Request) -> web.Response:
    q = request.query
    return _json(L.vocab_field(DATA / "vocab", USER / "vocab", q.get("section", ""), q.get("field", "")))


@routes.put("/kisekae/api/vocab/field")
@api
async def put_vocab_field(request: web.Request) -> web.Response:
    body = await _body(request)
    return _json(L.set_vocab_field(DATA / "vocab", USER / "vocab", _arg(body, "section"), _arg(body, "field"),
                                   body.get("entry")))


@routes.get("/kisekae/api/templates")
@api
async def list_templates(request: web.Request) -> web.Response:
    return _json({"templates": T.list_templates(DATA / "templates", USER / "templates")})


@routes.put("/kisekae/api/template")
@api
async def put_template(request: web.Request) -> web.Response:
    body = await _body(request)
    T.save_template(USER / "templates", _arg(body, "name"), body.get("text"))
    return _json({"templates": T.list_templates(DATA / "templates", USER / "templates")})


@routes.post("/kisekae/api/template/trash")
@api
async def trash_template(request: web.Request) -> web.Response:
    body = await _body(request)
    T.trash_template(USER / "templates", _arg(body, "name"))
    return _json({"templates": T.list_templates(DATA / "templates", USER / "templates")})

