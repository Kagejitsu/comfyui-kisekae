"""Section nodes (Identity, Head, Hair, ...), all generated from the schema."""

from __future__ import annotations

from ..kisekae import char as C
from ..kisekae.schema import SECTIONS, Section
from .common import CATEGORY, CHAR, LIB, preset_fingerprint, vocab


def make_section_node(sec: Section) -> type:
    class SectionNode:
        DESCRIPTION = (
            f"{sec.label} section. Pick a preset to replace the whole section "
            "(LoRAs included), then override single fields: typed text wins over "
            "the dropdown; the toggle appends instead of replacing. Dropdown picks "
            "may add negatives or clear clashing fields (e.g. a dress clears upper/lower).")
        RETURN_TYPES = (CHAR,)
        RETURN_NAMES = ("char",)
        FUNCTION = "run"
        CATEGORY = CATEGORY

        @classmethod
        def INPUT_TYPES(cls):
            v = vocab()
            req = {
                "preset": ([C.NONE] + LIB.list_with_section(sec.name), {
                    "default": C.NONE,
                    "tooltip": f"Replace the whole {sec.name} section with this preset's {sec.name}"}),
            }
            for f in sec.fields:
                req[f.name] = ([C.KEEP, C.CLEAR] + v.values(sec.name, f.name), {
                    "default": C.KEEP,
                    "tooltip": "(keep) passes the incoming value through; (clear) empties it"})
                req[f"{f.name}_text"] = ("STRING", {
                    "default": "", "multiline": f.multiline,
                    "placeholder": f"{f.name}: typed override (wins over dropdown)",
                    "tooltip": "Typed text wins over the dropdown. (tag:1.2) weights work."})
                req[f"{f.name}_append"] = ("BOOLEAN", {
                    "default": False, "label_on": "append", "label_off": "replace",
                    "tooltip": "append: add to the incoming value; replace: overwrite it"})
            return {
                "required": req,
                "optional": {"char": (CHAR, {"tooltip": "Character from the previous node; empty starts a new one"})},
                "hidden": {"unique_id": "UNIQUE_ID"},
            }

        @classmethod
        def IS_CHANGED(cls, **kw):
            return preset_fingerprint(kw.get("preset"))

        def run(self, preset, char=None, unique_id=None, **kw):
            tag = f"{sec.label}#{unique_id}"
            out = C.copy_char(char)
            if preset and preset != C.NONE:
                data, _files = LIB.resolve_section(preset, sec.name)
                data["origin"] = preset  # an unchanged pick can be saved back as a $ref
                out = C.set_section(out, sec.name, data, f"{tag}: section ← {preset}")
            picks = {f.name: (kw.get(f.name, C.KEEP), kw.get(f"{f.name}_text", ""),
                              bool(kw.get(f"{f.name}_append", False)))
                     for f in sec.fields}
            C.apply_overrides(out, sec.name, picks, vocab(),
                              source=f"node:{tag}", note_prefix=f"{tag}: ")
            return (out,)

    SectionNode.__name__ = SectionNode.__qualname__ = f"Kisekae{sec.label}"
    return SectionNode


SECTION_NODES = {f"Kisekae{s.label}": make_section_node(s) for s in SECTIONS}
SECTION_NAMES = {f"Kisekae{s.label}": f"👘 Kisekae {s.label}" for s in SECTIONS}
