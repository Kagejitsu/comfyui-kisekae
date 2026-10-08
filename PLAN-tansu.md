# Tansu 箪笥: preset organizer & editor (plan)

*Tansu* is the wardrobe chest that kisekae clothes come out of. Tansu is a full-page
web UI, in the spirit of LoRA Manager's tab, for browsing, editing and organizing
Kisekae presets. The name is a working title and easy to change.

Status: **planned 2026-10-08**, nothing built yet.

---

## 1. Decisions from the discussion (2026-10-08)

| Topic | Decision |
|---|---|
| Shape | Its own browser tab, opened from a 👘 button in ComfyUI's top bar, served by ComfyUI itself (no extra server, no installs) |
| Phase 1 scope | Organizer + editor + safe file management + tags |
| Card pictures | Display only in phase 1: the preset's own image file, else its LoRA's preview (from LoRA Manager's sidecar files), else a placeholder. **Capturing** a picture (e.g. "use last generated image") is a later phase |
| Tags | Free tags on presets, with tag filtering in the organizer |
| Vocab & templates | Phase 1: only "＋ add to dropdown" from the editor. Phase 2: full vocab page and template page |
| Send to ComfyUI | Not now. Revisit later if it turns out to be needed |
| Not copied from LoRA Manager | Bulk mode |

## 2. How it fits into ComfyUI

- **Server:** aiohttp routes added to ComfyUI's own server (`PromptServer.instance.routes`),
  the same way LoRA Manager does it. Everything lives under `/kisekae`:
  - `/kisekae`: the page
  - `/kisekae/static/…`: its JS/CSS
  - `/kisekae/api/…`: JSON API
- **The page is not in `web/`.** ComfyUI loads *every* `.js` file in `WEB_DIRECTORY` into
  the graph editor, so the app lives in a separate `ui/` folder served by our static route.
- **Top-bar button:** `web/kisekae.js` adds a 👘 button that opens `/kisekae` in a new
  tab (Shift+click opens a new window). It uses the frontend's action-bar API, with
  LoRA Manager's fallback for older frontends.
- **Frontend:** plain ES modules and CSS. No build step, no npm, no CDN, so it works
  offline. Hundreds of presets render fine without virtual scrolling.
- **Security:**
  - ComfyUI's origin-only middleware already rejects cross-site POSTs (unless the
    user runs `--enable-cors-header`). We add no CORS of our own.
  - All user text is rendered with `textContent`, never `innerHTML`, because
    presets may come from other people.
  - The image route only serves files inside the preset roots or ComfyUI's `loras`
    folders.

```
ui/                      the Tansu page (not auto-loaded by ComfyUI)
  index.html
  app.js                 routing between organizer / editor, state, keyboard shortcuts
  api.js                 fetch wrappers, error toasts
  organizer.js           tree, grid, search, tag/section filters, detail panel
  editor.js              form, LoRA picker, raw JSON tab, save/conflict handling
  preview.js             live prompt preview pane
  dom.js                 tiny element helpers (textContent only)
  tansu.css              light/dark themes via CSS variables
kisekae/library.py       NEW pure-Python library operations (index, refs, rename, trash, tags, drafts)
nodes/routes.py          NEW thin aiohttp layer over kisekae/library.py
web/kisekae.js           + top-bar button
```

## 3. Data changes

- **Tags:** new optional top-level `"tags": ["mushoku", "swimwear"]` in presets.
  - The loader already tolerates unknown top-level keys.
  - Tags are lowercased and trimmed on save.
  - Tags are **not** inherited through `extends` or `$ref`. They describe the file
    itself.
- **Picture sidecar:** `characters/roxy.webp` (or `.png`, `.jpg`, `.jpeg`) next to
  `characters/roxy.json`. Phase 1 only reads it; you can drop files in by hand. A
  later phase adds capture.
- **Picture fallback:** the first LoRA in the preset (identity section first) is looked
  up the same way the nodes do (exact path, then filename). Then:
  - its LoRA Manager `<stem>.metadata.json` → `preview_url` is used, else a
    `<stem>.{webp,png,jpeg,jpg,mp4}` sidecar;
  - `.mp4` previews play muted on hover, as in LoRA Manager.
- **NSFW blur:** LoRA Manager stores `preview_nsfw_level` in its metadata. Previews
  above PG-13 are blurred with a "show" button, matching LoRA Manager. A page-level
  toggle turns the blur off.
- **Save Preset node keeps tags and description:** when overwriting an existing file,
  it carries over `tags`, and `description` when that input is empty. Otherwise a save
  from the graph would wipe what was set in Tansu.
- **Trash:** `presets/.trash/<timestamp>/<name>.json` (+ its picture). Folders starting
  with `.` are already skipped by the library scan, so trashed presets never show up
  in node dropdowns.

## 4. Backend: `kisekae/library.py` (pure, unit-tested)

| Function | What it does |
|---|---|
| `index(lib)` | One entry per preset. **Fields:** name, display name, description, tags, sections provided, LoRA names, outgoing refs (`extends`, `$ref`s), read-only flag (examples), mtime, picture source. **Errors:** the resolve error for a broken preset. **Searchable text:** all field values, joined. |
| `reverse_refs(index)` | "Used by": which presets point at each preset, directly. Transitive refs are shown in the detail panel by following the links. |
| `rename(lib, old, new, dry_run)` | Moves the file (and its picture) and rewrites every `extends` / `$ref` / `name#section` that points at it, in **user** presets only. The dry run returns the list of files that would change. Each file is written atomically. Refuses examples, existing targets and anything that would escape the user root. |
| `duplicate(lib, name, new)` | Copies a preset, including one from examples, into the user library. |
| `trash(lib, name)` / `restore(lib, entry)` / `list_trash(lib)` | Delete = move into `.trash/`. Refuses examples. The response lists presets that still reference it, so the UI can warn first. |
| `resolve_draft(lib, name, data)` | Resolves an **unsaved** preset (the editor's current state) as if it were saved under `name`, refs included. The live preview uses it. Needs a small hook in `_Resolver` so one name maps to in-memory data. |
| `validate(lib, name, data)` | The same checks as loading (schema, fields, LoRAs, refs, loops), returned as a list of messages with JSON paths, e.g. `sections.hair.fields.colour: unknown field`. |
| `save(lib, name, data, etag)` | Validates, then writes atomically via `write_preset`. `etag` = the mtime and size the editor loaded. A mismatch → **conflict**, e.g. Save Preset wrote the file meanwhile. `etag=None` means "create, must not exist". |
| `add_vocab(section, field, value)` | Appends to the user overlay `vocab/<section>.json`, creating it if needed, and keeps the shipped file untouched. |

The existing `PresetLibrary.user_path`, `check_inside_user_root`, `write_preset` and
`forget` are reused for every write.

## 5. API: `nodes/routes.py` (thin)

| Method & path | Body / query | Returns |
|---|---|---|
| `GET /kisekae` | | the page |
| `GET /kisekae/api/library` | | index + reverse refs + all tags with counts |
| `GET /kisekae/api/preset?name=` | | raw JSON + etag + read-only flag |
| `PUT /kisekae/api/preset` | `{name, data, etag}` | `{etag}` or 409 conflict / 400 with validation messages |
| `POST /kisekae/api/render` | `{name, data, template, template_text}` | positive, negative, placeholder breakdown, LoRA status, rough tokens, validation messages |
| `POST /kisekae/api/rename` | `{from, to, dry_run}` | files that change / done |
| `POST /kisekae/api/duplicate` | `{from, to}` | new name |
| `POST /kisekae/api/trash` | `{name}` | trash entry + still-referenced-by list |
| `GET /kisekae/api/trash` · `POST /kisekae/api/restore` | | list / restore |
| `GET /kisekae/api/picture?name=` | | the preset's picture or LoRA preview (path-checked) |
| `GET /kisekae/api/loras?q=` | | LoRA files with trigger words (`civitai.trainedWords`) and preview, for the picker |
| `GET /kisekae/api/schema` | | sections/fields, vocab values per field, template names |
| `POST /kisekae/api/vocab` | `{section, field, value}` | updated values |

Errors are `{"error": "…"}` with the same wording the nodes use.

## 6. The organizer page

- **Top bar:** "👘 Tansu", search box (Ctrl+F; matches name, display name, tags, field
  values and LoRA names), sort (name / last modified), **New preset** button,
  theme toggle, NSFW-blur toggle.
- **Left sidebar:** folder tree of the user library, plus `examples/` shown read-only
  and dimmed. Folder counts. A Trash entry at the bottom.
- **Filter row:**
  - **tag chips:** click to require a tag; click again to exclude it. Several chips
    combine with AND.
  - **kind chips:** derived from sections: *character* (has identity), *outfit*
    (outfit only), *scene/style* (pose/scene/style without identity), *broken*.
- **Cards:**
  - the picture (as in §3);
  - display name, path, tag pills;
  - section badges (ID · HEAD · HAIR · BODY · OUTFIT · STYLE · POSE · SCENE);
  - LoRA count;
  - a red ⚠ for a broken preset.
- **Detail panel** (click a card):
  - **Shows:** description, tags, the resolved prompt (default template) with
    negatives, the LoRAs with found/missing status, **Uses** (refs out) and
    **Used by** (refs in), all clickable. Any error appears in full.
  - **Actions:** Edit · Duplicate · Rename/Move · Delete · Copy name.
  - ←/→ step through the filtered list, as in LoRA Manager.
- **Rename/Move dialog:** a new path (with folder suggestions), then a confirmation
  listing every preset whose references will be rewritten.
- **Delete dialog:**
  - warns if other presets still reference the preset (they would become broken);
  - says the file goes to Trash and can be restored.

## 7. The editor page

Two columns: the form on the left, the **live preview** on the right.

- **Header:**
  - path (editable only for a new preset; use Rename to move an existing one);
  - display name, description;
  - tags (pill input with autocomplete from existing tags);
  - **extends** (preset picker, with a note "fields here apply on top").
- **One card per section**, in schema order, collapsed when empty. Each card has a
  source switch:
  - **none:** the section isn't in the preset;
  - **fields:** written here;
  - **$ref:** a preset picker, plus optional local fields on top ("Ren's geta" case).
  - Field rows:
    - a text input with the vocab values as suggestions (dropdown and typing in one
      box);
    - an optional weight;
    - a **＋ add to dropdown** button when the value isn't in the vocab yet.
  - **LoRA rows:** a picker that searches your loras folder (with preview and trigger
    words), strength, clip strength (linked to strength unless unlinked), trigger
    (prefilled from LoRA Manager metadata).
  - **Section negative.**
- **Preset negative.**
- **Raw JSON tab:** edits the same data. Switching back to the form re-parses, and any
  error is shown inline instead of being lost.
- **Live preview** (debounced ~300 ms, via `/api/render`):
  - template picker;
  - positive and negative;
  - placeholder breakdown;
  - LoRA status;
  - rough token count;
  - validation messages, each linking to its field.
- **Saving:**
  - Ctrl+S or the Save button;
  - a dot marks unsaved changes, and leaving or closing with unsaved changes asks
    first;
  - on a **conflict** (the file changed on disk): show what happened and offer
    *Reload* or *Overwrite*;
  - examples open read-only with a **Duplicate to edit** button.
- **Not offered in the editor:** vocab negatives and conflict rules (`hides`). These
  apply only to dropdown picks on nodes; preset values are plain text (§6 of
  PLAN.md). The "add to dropdown" button says it affects the nodes' dropdowns.

## 8. Build order

| Step | Deliverable | Done when |
|---|---|---|
| **1a. Library core** | `kisekae/library.py`: index, reverse refs, rename with ref rewrite, duplicate, trash/restore, draft resolve, validate, save with etag, add_vocab. Save Preset keeps tags/description. Tests. | unittest green, including rename rewrite across `extends`/`$ref`/`#section`, conflict detection, escape attempts, trash invisible to dropdowns |
| **1b. API + organizer** | `nodes/routes.py`, `ui/` organizer page, top-bar button, picture route with LoRA-preview fallback and NSFW blur | Kate's library shows with LoRA pictures; search, tags and filters work; rename/delete/restore work live; headless-Waterfox screenshots check both themes |
| **1c. Editor** | form, LoRA picker, raw JSON tab, live preview, add-to-dropdown, conflict handling | Kate's Roxy rebuilt in the editor renders the same prompt as the nodes; a Save Preset run while editing triggers the conflict dialog |
| **1d. Polish & release** | keyboard shortcuts, empty/error states, README "Tansu" section + screenshots, version 0.2.0 | Kate's hands-on trial; **publishing = bump the version and push, only on Kate's go-ahead** |
| **2. Vocab & templates** | vocab page (values, negatives, hides, hide shipped values), template page (editor, placeholder palette, live preview against any preset) | — |
| **Later** | picture capture ("use last generated image" from the queue history / output folder, or upload), render-a-preview, Send to ComfyUI | — |

A git commit at each step. Pushing and Registry releases only with Kate's go-ahead.

## 9. Testing

- **Core:** stdlib `unittest` on `kisekae/library.py`, using temporary libraries like
  `tests/test_phase3.py`. No ComfyUI or aiohttp needed.
- **API:** the routes are thin. A scratch script exercises them against the live
  server with curl/urllib (list, save, conflict, rename dry run, trash/restore).
- **UI:** headless Waterfox + WebDriver BiDi (the recipe already used for the node
  widgets):
  - scripted clicks and typing;
  - screenshots of each page in light and dark;
  - a check that no user string ends up as HTML.

## 10. Risks / notes

- **Rename rewrites other files.** It is the one operation that touches many presets
  at once. Mitigations:
  - a mandatory dry-run list before applying;
  - atomic per-file writes;
  - a rewrite only changes the exact ref strings that match;
  - the result report lists every file changed.
- **Users without LoRA Manager** get no LoRA previews or trigger-word autofill. Cards
  fall back to the placeholder and the picker to plain filenames. Nothing breaks.
- **Big preview videos** load only on hover, with `preload="none"`.
- **Theme:** Tansu keeps its own light/dark toggle (remembered in localStorage)
  rather than reading ComfyUI's palette. This is simpler and is what LoRA Manager
  does too.
