"""Prompt node: CHAR -> prompt text, negatives and LoRAs."""

from __future__ import annotations

from ..kisekae.char import copy_char
from ..kisekae.render import render
from .common import CATEGORY, CHAR, resolve_loras, show, template_names, template_text
from ..kisekae import loras as lora_mod


def render_inputs() -> dict:
    """Inputs shared by Prompt and Debug Prompt."""
    return {
        "template": (template_names(), {
            "tooltip": "Prompt layout. Add your own .txt files in user/default/kisekae/templates/"}),
        "template_text": ("STRING", {
            "default": "", "multiline": True,
            "placeholder": "custom template (wins over the dropdown when not empty)\n"
                           "{section}  {section.field}  {!section.field}  {triggers}"}),
        "escape_parens": ("BOOLEAN", {
            "default": True,
            "tooltip": "Escape brackets inside tags, e.g. menacing \\(jojo\\), so ComfyUI "
                       "doesn't read them as emphasis. (tag:1.2) weights are kept."}),
        "dedupe": ("BOOLEAN", {"default": True, "tooltip": "Remove exact repeated tags (first one kept)"}),
        "include_triggers": ("BOOLEAN", {"default": True, "tooltip": "Fill {triggers} with LoRA trigger words"}),
    }


def do_render(char, template, template_text_, escape_parens, dedupe, include_triggers):
    return render(char, template_text(template, template_text_),
                  escape=escape_parens, dedupe=dedupe, include_triggers=include_triggers)


class KisekaePrompt:
    DESCRIPTION = "Turn the character into prompt text. Attach it anywhere in a chain."
    RETURN_TYPES = ("STRING", "STRING", "LORA_STACK", "STRING", "STRING", CHAR)
    RETURN_NAMES = ("positive", "negative", "LORA_STACK", "lora_syntax", "trigger_words", "char")
    OUTPUT_TOOLTIPS = (
        "Positive prompt",
        "Negative prompt",
        "Standard LoRA stack: LoraManager's Lora Loader (lora_stack input) and other stack loaders accept it",
        "<lora:name:strength> text for LoraManager's LoRA Text Loader",
        "LoRA trigger words",
        "The character, unchanged",
    )
    FUNCTION = "run"
    CATEGORY = CATEGORY

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"char": (CHAR,), **render_inputs()}}

    def run(self, char, template, template_text, escape_parens, dedupe, include_triggers):
        r = do_render(char, template, template_text, escape_parens, dedupe, include_triggers)
        stack, status = resolve_loras(r.loras)
        found = [l for l, s in status if not s.startswith("✗")]
        shown = r.positive
        missing = [f"⚠ LoRA not found: {l['name']}" for l, s in status if s.startswith("✗")]
        if missing:
            shown += "\n\n" + "\n".join(missing)
        return show(shown, (r.positive, r.negative, stack, lora_mod.syntax(found),
                            ", ".join(r.triggers), copy_char(char)))
