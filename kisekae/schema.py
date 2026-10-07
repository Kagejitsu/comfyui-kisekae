"""Sections and fields — the single source of truth.

Nodes, vocab, rendering and preset validation all read from here, so adding a
field is a one-line change.
"""

from __future__ import annotations

from dataclasses import dataclass

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Field:
    name: str
    # "tags": comma-separated tags; append merges and dedupes items.
    # "text": free prose; append joins as text.
    kind: str = "tags"
    multiline: bool = False


@dataclass(frozen=True)
class Section:
    name: str
    label: str
    fields: tuple[Field, ...]

    def field(self, name: str) -> Field:
        for f in self.fields:
            if f.name == name:
                return f
        raise KeyError(name)

    @property
    def field_names(self) -> tuple[str, ...]:
        return tuple(f.name for f in self.fields)


def _fields(*names: str) -> tuple[Field, ...]:
    # Every section ends with a multiline catch-all "extra" field.
    return tuple(Field(n) for n in names) + (Field("extra", multiline=True),)


SECTIONS: tuple[Section, ...] = (
    Section("identity", "Identity", _fields(
        "who", "series", "gender", "age", "species", "skin")),
    Section("head", "Head", _fields(
        "face", "eyes", "eyebrows", "ears", "mouth", "expression",
        "makeup", "eyewear", "accessories")),
    Section("hair", "Hair", _fields(
        "color", "length", "style", "bangs", "accessories")),
    Section("body", "Body", _fields(
        "body_type", "proportions", "height", "bust", "waist", "hips",
        "thighs", "muscle", "extras")),
    Section("outfit", "Outfit", _fields(
        "headwear", "full", "upper", "outerwear", "lower", "legwear", "footwear",
        "handwear", "accessories", "underwear")),
    Section("style", "Style", _fields(
        "quality", "artist", "style_series", "art_style")),
    Section("pose", "Pose", (
        Field("pose"), Field("hands"), Field("action"),
        Field("prose", kind="text", multiline=True),
        Field("extra", multiline=True))),
    Section("scene", "Scene", _fields(
        "composition", "lighting", "background", "effects")),
)

SECTION_NAMES: tuple[str, ...] = tuple(s.name for s in SECTIONS)
_BY_NAME = {s.name: s for s in SECTIONS}


def get_section(name: str) -> Section:
    try:
        return _BY_NAME[name]
    except KeyError:
        raise KeyError(
            f"unknown section {name!r} (known: {', '.join(SECTION_NAMES)})"
        ) from None
