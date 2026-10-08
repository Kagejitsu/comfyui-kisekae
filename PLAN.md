# comfyui-kisekae — design & build plan

着せ替え (*kisekae*, "dress-up"): a ComfyUI node pack that builds character
prompts from JSON presets, with a dropdown + typed override (and an
append/replace toggle) on every field. Nodes are chained; each passes a JSON
character state to the next, and a Prompt node can be attached anywhere.

License: **GPL-3.0**. Public repo: `Kagejitsu/comfyui-kisekae` (created only
with Kate's go-ahead). Status: **phase 3 done 2026-10-07**: 13 nodes, 46 unittest tests green, live checks pass (conflict rules, negatives, Save Preset round trip, exact token count via Anima's Qwen tokenizer). Phase 4 (polish & publish) in progress: section-node text/append inputs are "advanced" (hidden behind the node's Show advanced inputs toggle; auto-opened when in use), new nodes start compact.

---

## 1. Decisions already made

| Topic | Decision |
|---|---|
| Output style | Tags **and** prose mixed in one prompt. Prose is just a field value. |
| Presets | All-in-one JSON, able to **reference** other presets (`$ref`, `extends`) |
| Layout | Chained nodes, one per section, passing `KISEKAE_CHAR`; Prompt node attaches anywhere |
| Overrides | Per field: dropdown + typed text + **append/replace toggle** |
| Hair | Its own node, separate from Head |
| LoRAs | Stored in presets; output `LORA_STACK` + `<lora:…>` text; **no hard dependency** on LoraManager |
| Debugging | **Debug JSON** and **Debug Prompt** nodes, both pass-through |
| Distribution | Public GitHub + ComfyUI Registry, GPL-3, generic example presets only |

## 2. Repository layout

```
comfyui-kisekae/
  __init__.py              NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS, WEB_DIRECTORY
  pyproject.toml           [project] + [tool.comfy] for the Registry
  LICENSE                  GPL-3.0
  README.md
  kisekae/                 pure-Python core — NO ComfyUI imports (unit-testable)
    schema.py              sections + fields: the single source of truth
    char.py                CHAR state: new / deep-copy / apply section / apply field override
    presets.py             library discovery, load, $ref/extends resolution, cycle check,
                           mtime fingerprint, atomic + path-safe save
    vocab.py               dropdown values (shipped + user overlay), companion negatives
    render.py              template engine, paren escaping, dedupe, weights, negatives
    loras.py               collect LoRAs → LORA_STACK tuples / <lora:> syntax / triggers
  nodes/                   ComfyUI adapters (classic V1 node API for widest compatibility)
    section.py             factory: builds a node class from a schema section
    preset_io.py           Load Preset, Save Preset
    prompt.py              Prompt
    debug.py               Debug JSON, Debug Prompt
  web/
    kisekae.js             renders debug text on the node; later: widget UX polish
  data/
    vocab/<section>.json   default dropdown values
    templates/*.txt        prompt layout templates (anima-mixed, illustrious-tags)
    examples/              example presets (original characters only)
  examples/workflows/      example .json workflows (kept out of data/examples: that folder is the preset library)
  tests/                   pytest against kisekae/ core
```

Dev install: `ln -s ~/Projects/comfyui-kisekae ~/ComfyUI/custom_nodes/comfyui-kisekae`.

## 3. Sections & fields

Every section also has an `extra` field (multiline): a catch-all for anything
the named fields do not cover.

| Section (node) | Fields |
|---|---|
| **identity** | who, series, gender (`1girl`, `1boy`…), age (apparent), species, skin |
| **head** | face, eyes, eyebrows, ears, mouth, expression, makeup, eyewear, accessories |
| **hair** | color, length, style (twin braids, ahoge, sidelocks…), bangs, accessories |
| **body** | body_type, proportions, height, bust, waist, hips, thighs, muscle, extras (tail, wings, horns) |
| **outfit** | headwear, full (dress, uniform…), upper, outerwear, lower, legwear, footwear, handwear, accessories, underwear |
| **style** | quality, artist (`@name`), style_series (e.g. jojo), art_style |
| **pose** | pose, hands, action, prose (multiline) |
| **scene** | composition (camera/framing), lighting, background, effects |

`schema.py` holds this table; nodes, vocab, render and validation all read it,
so adding a field is a one-line change.

## 4. Data model

### 4.1 Preset file (on disk)

```json
{
  "kisekae": 1,
  "name": "Shinobu",
  "description": "Default look",
  "extends": null,
  "sections": {
    "identity": {
      "fields": {
        "who":    { "value": "oshino shinobu" },
        "series": { "value": "monogatari (series)" },
        "gender": { "value": "1girl" }
      },
      "loras": [
        { "name": "Illustrious/Characters/Monogatari/shinobu.safetensors",
          "strength": 0.8, "clip_strength": 0.8, "trigger": "shinobu" }
      ]
    },
    "hair":   { "fields": { "color": { "value": "blonde hair" },
                            "length": { "value": "long hair", "weight": 1.1 } } },
    "outfit": { "$ref": "outfits/shinobu-default" },
    "head":   { "fields": { "eyes": { "value": "yellow eyes" },
                            "expression": { "value": "smug" } } }
  },
  "negative": ""
}
```

- An **outfit preset** is just a preset that only has an `outfit` section. There is one
  file format for everything.
- `schema_version` lives in the `"kisekae": 1` key, so files can be migrated later.

### 4.2 References

| Form | Meaning |
|---|---|
| `"extends": "characters/base"` | Whole-preset inheritance; this file's sections are applied on top |
| `"outfit": { "$ref": "outfits/x" }` | Take the **same-named** section from preset `outfits/x` |
| `"outfit": { "$ref": "characters/roxy#outfit" }` | Take a named section from another preset |
| `$ref` + `"fields"` together | Load the ref, then apply the local fields on top (local wins) |

- Paths are relative to the library roots (§4.4) without `.json`. The user library is
  searched first, then the shipped examples (`examples/…`).
- Resolution is recursive, depth limit 32. **Cycles fail loudly** with the chain shown,
  e.g. `a → b → a`.
- Field-level refs (`"$ref": "x#hair.color"`) are left for later.

### 4.3 Runtime CHAR (`KISEKAE_CHAR`)

This is the resolved state passed between nodes: no `$ref`s left. Each field records
where its value came from, for the debug nodes.

```json
{
  "kisekae": 1,
  "name": "Shinobu",
  "sections": {
    "outfit": {
      "fields": { "full": { "value": "white dress, sleeveless dress",
                            "source": "ref:outfits/shinobu-default" } },
      "loras": [],
      "origin": "ref:outfits/shinobu-default"
    }
  },
  "negative": "",
  "trace": [ "load preset characters/shinobu", "Outfit#14: section ← outfits/maid" ]
}
```

- Every node `deepcopy`s its input before changing it, so **branching a chain is safe**:
  one CHAR can feed two different Outfit nodes.
- `origin` lets Save Preset write a section back as a `$ref` when it was not changed (§5.2).

### 4.4 Where files live

| What | Path |
|---|---|
| User presets | `ComfyUI/user/default/kisekae/presets/` (via `folder_paths.get_user_directory()`) |
| User vocab overlay | `ComfyUI/user/default/kisekae/vocab/` (merged over the shipped vocab) |
| User templates | `ComfyUI/user/default/kisekae/templates/` |
| Shipped examples | `<repo>/data/…` (read-only) |

User data never lives in the repo, so updating the node can't clobber it.

## 5. Nodes

### 5.1 Section nodes: Identity, Head, Hair, Body, Outfit, Style, Pose, Scene

All are generated by one factory from `schema.py`.

**Inputs**

- `char`: optional `KISEKAE_CHAR`. Without it, the node starts a new empty character.
- `preset`: dropdown of presets that contain this section, or `(none)`. Picking one
  **replaces the whole section, including its LoRAs**. That is what an outfit swap is.
- Per field `f`:
  - `f`: dropdown — `(keep)`, `(clear)`, then the vocab values
  - `f_text`: text box (multiline for `prose` and `extra`)
  - `f_append`: boolean, default **off** (replace)

**Order of application:** incoming CHAR → section preset → each field override.

**Per-field rules**

- Typed text (if not empty) wins over the dropdown. `(keep)` with no text passes the value through.
- `append` **on**: new text is added after the existing value, with exact duplicates dropped.
  `append` **off**: new text replaces the existing value.
- `(clear)` empties the field.
- **Weights** are typed inline, e.g. `(red eyes:1.3)`. Presets may also use `"weight": 1.3`.

**Outputs:** `char`.

Editing a preset file on disk must re-run the node. `IS_CHANGED` returns a fingerprint of
the mtimes of every preset file used, so ComfyUI's cache can't serve stale results.

### 5.2 Preset I/O

**Load Preset**

- Inputs: `preset` (dropdown of all presets); optional `char`; `mode` =
  - `replace`: the result is exactly the preset;
  - `overlay`: the preset's sections replace whole sections, and other sections are kept;
  - `merge`: the preset's fields replace single fields, LoRAs and negatives are added.
    This is how a "scene" preset sets `head.expression` without wiping the
    character's eyes. It was found while reproducing the Roxy/JoJo prompt.
- Output: `char`.

**Save Preset** (output node)

- Inputs: `char`, `path` (e.g. `characters/roxy`), `overwrite` (default **off**),
  `keep_refs` (default **on**: an unchanged section whose `origin` is a ref is written
  back as `$ref`; edited sections are written out in full).
- Safety: writes **only inside the user preset folder**. `..`, absolute paths and
  symlink escapes are rejected (this matters for a public node). Saves are atomic
  (write to a temporary file, then rename). Saving onto an existing file without
  `overwrite` is an error, never a silent overwrite.
- New presets show up in dropdowns after ComfyUI's **Refresh** (R).

### 5.3 Prompt

**Inputs**

- `char`
- `template`: dropdown of template files
- `template_text`: optional custom template, which wins when not empty
- `escape_parens`: default **on**
- `dedupe`: default **on**
- `include_triggers`: default **on**

**Outputs:** `positive` STRING, `negative` STRING, `LORA_STACK`, `lora_syntax` STRING,
`trigger_words` STRING, `char` (pass-through).

**Template rules**

- `{section}` places all of a section's fields in schema order.
- `{section.field}` places one field. That field is then left out of that section's
  `{section}` placeholder, so nothing is printed twice.
- `{!section.field}` leaves a field out entirely (the `illustrious-tags` template
  uses `{!pose.prose}`).
- `{triggers}` places the LoRA trigger words.
- Literal text is allowed, e.g. `masterpiece, {style}`.
- One template line = one prompt line. Empty placeholders, dangling commas and empty lines
  are removed. Each non-final line ends with `,`.

**Default template `anima-mixed`** (follows Kate's Roxy/JoJo prompt):

```
{style.quality}, {scene.composition}, {scene.lighting}
{triggers}, {identity}, {hair}, {head}, {body}
{outfit}
{style}, {pose}
{pose.prose}
{scene}, {head.expression}
```

There is also an `illustrious-tags` template (same blocks, no prose line).

**Parenthesis escaping (verified need).** ComfyUI's Anima `Qwen3Tokenizer` subclasses
`SDTokenizer` with weight parsing on, so `menacing (jojo)` is currently read as
`menacing` + `jojo`×1.1.

- When `escape_parens` is on, brackets inside tags become `\(` `\)`.
- Exceptions:
  - text that matches the weight form `(text:number)` is left alone;
  - brackets that are already escaped are left alone.

**Dedupe** removes exact repeats (after trimming and lower-casing) across the whole
positive prompt. The first occurrence is kept.

**Negative prompt** = the CHAR's global `negative` + each section's `negative` + vocab
companion negatives for values picked from dropdowns (phase 3), with dedupe applied.

**LoRAs**

- Collected from every section in CHAR order.
- If the same file appears twice, the last one wins.
- `LORA_STACK` = `[(path, model_strength, clip_strength), …]`. This is the standard tuple
  that LoraManager's Lora Loader `lora_stack` input (and Efficiency/Comfyroll stack
  loaders) accept. Verified against the installed LoraManager.
- A missing LoRA file is a **warning** shown in the debug nodes, not a crash. It is left
  out of the stack.

### 5.4 Debug nodes (output nodes, pass-through)

Both nodes take `char` and output it unchanged, so they can sit **in the middle of a
chain**. Both show their report in a read-only text box on the node (`web/kisekae.js`:
`onExecuted` → text widget; the stock front end only does this for its own PreviewAny)
and also output it as `text`.

**Debug JSON**

- `view` = `resolved` (clean CHAR) | `sources` (every field with its `source`) |
  `trace` (the list of operations each node performed)
- `section`: filter, `(all)` or one section

**Debug Prompt**

- Renders the CHAR with the same template options as the Prompt node. Shows:
  - the final positive and negative prompts;
  - a **per-placeholder breakdown** (`{hair}` → `long hair, blonde hair`);
  - what dedupe removed;
  - what got escaped;
  - the LoRA list with resolved paths and missing-file warnings;
  - a rough token count.
- It doesn't need a Prompt node, so it can be dropped anywhere in a chain to check
  the state so far.

## 6. Vocab (dropdown values)

```json
{ "section": "hair", "field": "length",
  "options": [ "short hair", "medium hair", "long hair", "very long hair",
               { "value": "short hair", "negative": "long hair" } ] }
```

- A user overlay file with the same `section`/`field` **adds** values, or **replaces**
  them if it sets `"replace": true`.
- Phase 3 adds **conflict rules**, e.g. a dropdown-picked `full` outfit hides upper/lower,
  and `barefoot` hides legwear/footwear. They apply to **dropdown picks only**: preset text
  and typed text are never pruned. This is so Shinobu's `white dress … skirt` survives.

## 7. Testing

- **stdlib `unittest` on `kisekae/`** (no ComfyUI, no pytest needed; pytest can still run them).
  Run: `python -m unittest discover -s tests -t . -v`. Covers:
  - ref resolution, `extends`, cycle detection, local-over-ref precedence
  - append/replace/clear/keep logic
  - template rendering, explicit-field exclusion, empty-line cleanup
  - escaping edge cases: `menacing (jojo)`, `(red eyes:1.3)`, `\(already\)`
  - dedupe
  - Save Preset path-escape attempts
  - keep_refs round trip
- **ComfyUI smoke test:** start `comfy`, POST an example workflow to `/prompt`, check that
  the Prompt node output equals a golden string, and check the server log for import errors.
- **Kate's trial:** build her Roxy/JoJo prompt with the nodes and diff it against the
  hand-written one.

## 8. Build order

| Phase | Deliverable | Done when |
|---|---|---|
| **1. Core** ✅ | `schema`, `char`, `presets` (+refs), `render`, `tags`, `loras`, tests | ✅ 2026-10-07: 24 tests green; Roxy prompt reproduced (`tests/test_core.py`) |
| **2. Nodes MVP** ✅ | section factory + 8 section nodes, Load Preset, Prompt (incl. LORA_STACK/lora_syntax/triggers, pulled forward), **Debug JSON**, **Debug Prompt**, `kisekae.js`, vocab, example presets | ✅ loads with no errors; live `/prompt` chain run OK; cache re-runs when a `$ref`'d file changes. ⏳ Kate's hands-on trial in the UI |
| **3. Persistence & LoRAs** ✅ | Save Preset (keep_refs), vocab negatives + conflict rules, real token count (optional CLIP input) | Save → refresh → load round-trips; stack feeds LoraManager Lora Loader |
| **4. Polish & publish** | widget UX (~~hide `_append`/`_text` until used~~ done via `advanced` inputs, section colours), README (done; placeholder screenshots in docs/screenshots/ for Kate to replace), `pyproject.toml` (done; PublisherId must match the Registry publisher), example workflow (done), GitHub repo, Registry | Kate approves → public repo + Registry listing |
| **Later** | random/wildcard fields with seed, WD14 "preset from image", field-level refs, multi-character, V3 node API | — |

A git commit at the end of each phase. GitHub creation, pushing and Registry
publishing happen **only on Kate's go-ahead**.

## 9. Risks / notes

- **Widget count.** Head has 10 fields × 3 widgets = 30 widgets, which makes a tall node.
  Phase 4 JS is meant to fix this. If it's unbearable in phase 2, move the polish earlier.
- **Dropdown refresh.** ComfyUI calls `INPUT_TYPES` again on Refresh, so new presets appear
  without a restart. A saved workflow that names a deleted preset gets a clear error,
  not a crash.
- **Classic (V1) node API** is chosen for compatibility with older ComfyUI installs. V3
  migration can come later.
- **Example presets:** original characters only. Nothing from Kate's library, no real LoRA
  file names.

## 10. Notes from phase 2

- A **section node's preset dropdown takes only that node's own section**. Picking
  `outfits/maid` on the Outfit node does *not* bring the maid preset's `head.headwear`
  (maid headdress). To get every section a preset defines, use **Load Preset** with
  `mode=merge`.
- The Head node has 34 widgets (preset + 11 fields × 3), as predicted. Phase 4 polish.
- Dev install: `~/ComfyUI/custom_nodes/comfyui-kisekae` → symlink to this repo.
  Python changes need a ComfyUI restart; preset/vocab/template edits only need R (refresh).
- **`headwear` moved from Head to Outfit** (2026-10-07, before any release): hats belong
  to outfits, and a `$ref` to an outfit only carries the outfit section. Found while
  building Kate's Roxy presets, where the witch hat has to swap with the outfit. Outfit
  fields now run head to toe.

## 11. Notes from phase 3

- **Conflict rules** (`hides` in vocab) run in two passes per node: first clear the
  hidden fields of the *incoming* character, then apply this node's overrides. So a
  field set explicitly on the same node always survives, whatever the field order.
  Appended picks and typed text never hide anything.
- **Companion negatives** are stored on the field entry, so they disappear when the
  value is replaced. A negative that also appears in the positive is dropped and
  listed under "NEGATIVES DROPPED" in Debug Prompt.
- **Save Preset** folds field negatives into the section's `negative` (a saved value is
  plain text, not a dropdown pick any more). A `$ref` is kept only if it still resolves
  and does not lead back to the file being written. Re-saving identical content
  reports `UNCHANGED`, so re-queuing a workflow with a Save node doesn't error.
- **Token count:** Debug Prompt has an optional `clip` input. It counts with each
  encoder's own tokenizer (`qwen3_06b`/`t5xxl` for Anima, `clip_l`/`clip_g` with
  75-token chunks for SDXL). Counts include start/end tokens.
