"""Load Preset and Save Preset nodes."""

from __future__ import annotations

import json

from ..kisekae import char as C
from ..kisekae.save import char_to_preset, keep_file_metadata, write_preset
from .common import CATEGORY, CHAR, LIB, USER, preset_fingerprint, show


class KisekaeLoadPreset:
    DESCRIPTION = (
        "Load a whole preset. replace: exactly the preset. overlay: its sections "
        "replace whole sections. merge: its fields replace single fields "
        "(e.g. a scene preset setting head.expression keeps the character's eyes).")
    RETURN_TYPES = (CHAR,)
    RETURN_NAMES = ("char",)
    FUNCTION = "run"
    CATEGORY = CATEGORY

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "preset": ([C.NONE] + LIB.list_names(), {"default": C.NONE}),
                "mode": (list(C.LOAD_MODES), {"default": "replace"}),
            },
            "optional": {"char": (CHAR,)},
        }

    @classmethod
    def IS_CHANGED(cls, **kw):
        return preset_fingerprint(kw.get("preset"))

    def run(self, preset, mode, char=None):
        if not preset or preset == C.NONE:
            return (C.copy_char(char),)
        return (C.load_preset(char, LIB.resolve(preset), preset, mode),)


class KisekaeSavePreset:
    DESCRIPTION = (
        "Save the character as a preset in user/default/kisekae/presets/. "
        "keep_refs writes unchanged sections back as $ref (e.g. the outfit stays a "
        "reference to its outfit preset). Never overwrites unless 'overwrite' is on; "
        "re-running with identical content is fine. Press R afterwards to see it in dropdowns.")
    RETURN_TYPES = (CHAR, "STRING")
    RETURN_NAMES = ("char", "saved_as")
    FUNCTION = "run"
    OUTPUT_NODE = True
    CATEGORY = CATEGORY

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "char": (CHAR,),
            "path": ("STRING", {"default": "characters/new-character",
                                "tooltip": "Relative path without .json, e.g. characters/roxy-casual"}),
            "name": ("STRING", {"default": "", "tooltip": "Display name; empty keeps the character's name"}),
            "description": ("STRING", {"default": "", "multiline": False}),
            "keep_refs": ("BOOLEAN", {"default": True, "label_on": "keep $refs", "label_off": "write in full"}),
            "overwrite": ("BOOLEAN", {"default": False, "label_on": "overwrite", "label_off": "never overwrite"}),
        }}

    def run(self, char, path, name, description, keep_refs, overwrite):
        data, notes = char_to_preset(char, LIB, path, keep_refs=keep_refs,
                                     name=name.strip(), description=description.strip())
        data = keep_file_metadata(LIB, path, data)
        written, status = write_preset(LIB, path, data, overwrite=overwrite)
        rel = written.relative_to(USER)
        text = "\n".join([f"{status.upper()}: {rel}", *notes, "", json.dumps(data, indent=2, ensure_ascii=False)])
        return show(text, (C.copy_char(char), str(written)))
