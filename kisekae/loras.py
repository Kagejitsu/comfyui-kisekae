"""Collect LoRAs from a CHAR (resolving file paths is the node layer's job)."""

from __future__ import annotations

from .char import ordered_sections
from .tags import norm_key, split_items


def collect(char: dict) -> list[dict]:
    """LoRAs in section order. If a file appears twice, the last one wins, in
    the position of the first."""
    by_name: dict[str, dict] = {}
    for sec in ordered_sections(char):
        for lora in char["sections"][sec].get("loras", []):
            entry = dict(lora, section=sec)
            if lora["name"] in by_name:
                by_name[lora["name"]].update(entry)
            else:
                by_name[lora["name"]] = entry
    return list(by_name.values())


def triggers(loras: list[dict]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for lora in loras:
        for t in split_items(lora.get("trigger", "")):
            if norm_key(t) not in seen:
                seen.add(norm_key(t))
                out.append(t)
    return out


def syntax(loras: list[dict]) -> str:
    """``<lora:name:strength>`` text, as read by LoraManager's LoRA Text Loader."""
    parts = []
    for l in loras:
        name = l["name"].rsplit("/", 1)[-1]
        if name.endswith(".safetensors"):
            name = name[: -len(".safetensors")]
        if l["clip_strength"] != l["strength"]:
            parts.append(f"<lora:{name}:{l['strength']:g}:{l['clip_strength']:g}>")
        else:
            parts.append(f"<lora:{name}:{l['strength']:g}>")
    return " ".join(parts)
