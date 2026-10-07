"""Debug nodes: pass-through, show what is flowing at that point in a chain."""

from __future__ import annotations

from ..kisekae.char import copy_char
from ..kisekae.report import ALL, DEBUG_VIEWS, char_json, prompt_report
from ..kisekae.schema import SECTION_NAMES
from .common import CATEGORY, CHAR, count_tokens, resolve_loras, show
from .prompt import do_render, render_inputs


class KisekaeDebugJSON:
    DESCRIPTION = (
        "Show the character data at this point. resolved: clean values; "
        "sources: where each value came from; trace: what each node did. Passes char through.")
    RETURN_TYPES = (CHAR, "STRING")
    RETURN_NAMES = ("char", "text")
    FUNCTION = "run"
    OUTPUT_NODE = True
    CATEGORY = CATEGORY

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "char": (CHAR,),
            "view": (list(DEBUG_VIEWS), {"default": "resolved"}),
            "section": ([ALL] + list(SECTION_NAMES), {"default": ALL}),
        }}

    def run(self, char, view, section):
        text = char_json(char, view, section)
        return show(text, (copy_char(char), text))


class KisekaeDebugPrompt:
    DESCRIPTION = (
        "Render the prompt at this point without a Prompt node, with a breakdown: "
        "each placeholder's text, removed duplicates, escaped brackets, LoRAs. Connect a CLIP "
        "for exact token counts. Passes char through.")
    RETURN_TYPES = (CHAR, "STRING")
    RETURN_NAMES = ("char", "text")
    FUNCTION = "run"
    OUTPUT_NODE = True
    CATEGORY = CATEGORY

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"char": (CHAR,), **render_inputs()},
                "optional": {"clip": ("CLIP", {"tooltip": "Optional: connect your text encoder for exact token counts"})}}

    def run(self, char, template, template_text, escape_parens, dedupe, include_triggers, clip=None):
        r = do_render(char, template, template_text, escape_parens, dedupe, include_triggers)
        _stack, status = resolve_loras(r.loras)
        counts = count_tokens(clip, r.positive) if clip is not None else None
        text = prompt_report(r, status, counts)
        return show(text, (copy_char(char), text))
