"""Load Preset node (Save Preset arrives in phase 3)."""

from __future__ import annotations

from ..kisekae import char as C
from .common import CATEGORY, CHAR, LIB, preset_fingerprint


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
