"""Phase 3: vocab negatives + conflict rules, Save Preset, report extras."""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from kisekae import char as C
from kisekae.errors import KisekaeError
from kisekae.presets import PresetLibrary, Root
from kisekae.render import render
from kisekae.report import prompt_report
from kisekae.save import char_to_preset, write_preset
from kisekae.vocab import Vocab

from .test_core import FIX, lib, template

VOCAB = Vocab([Path(__file__).parent.parent / "data" / "vocab"])


def roxy(L=None):
    L = L or lib()
    return C.load_preset(None, L.resolve("characters/roxy"), "characters/roxy")


def picks(**kw):
    """picks(full="dress") -> dropdown pick; picks(upper=("", "blouse")) -> typed."""
    out = {}
    for f, v in kw.items():
        if isinstance(v, tuple):
            choice, text, *app = v
            out[f] = (choice or C.KEEP, text, bool(app and app[0]))
        else:
            out[f] = (v, "", False)
    return out


def fields(ch, sec):
    return {k: v["value"] for k, v in ch["sections"][sec]["fields"].items()}


class TestConflictRules(unittest.TestCase):
    def test_dress_pick_clears_upper_and_lower(self):
        ch = C.apply_overrides(roxy(), "outfit", picks(full="dress"), VOCAB, source="n")
        f = fields(ch, "outfit")
        self.assertNotIn("upper", f)
        self.assertNotIn("lower", f)
        self.assertEqual(f["outerwear"], "jacket, capelet, white jacket, white capelet")  # not hidden
        self.assertIn("outfit.upper cleared (hidden by outfit.full = dress)", ch["trace"])

    def test_explicit_field_on_same_node_survives(self):
        ch = C.apply_overrides(roxy(), "outfit", picks(full="dress", upper=("", "blouse")), VOCAB, source="n")
        f = fields(ch, "outfit")
        self.assertEqual(f["upper"], "blouse")
        self.assertNotIn("lower", f)

    def test_earlier_field_survives_two_pass(self):
        # legwear comes before footwear in schema order; barefoot must not undo it
        ch = C.apply_overrides(roxy(), "outfit", picks(legwear="pantyhose", footwear="barefoot"), VOCAB, source="n")
        self.assertEqual(fields(ch, "outfit")["legwear"], "pantyhose")
        ch = C.apply_overrides(roxy(), "outfit", picks(footwear="barefoot"), VOCAB, source="n")
        self.assertNotIn("legwear", fields(ch, "outfit"))

    def test_typed_and_appended_never_prune(self):
        ch = C.apply_overrides(roxy(), "outfit", picks(full=("", "dress")), VOCAB, source="n")
        self.assertIn("upper", fields(ch, "outfit"))
        ch = C.apply_overrides(roxy(), "outfit", picks(full=("dress", "", True)), VOCAB, source="n")
        self.assertIn("upper", fields(ch, "outfit"))
        self.assertEqual(fields(ch, "outfit")["full"], "dress")  # already there, appended once

    def test_option_override_hides_nothing(self):
        ch = C.apply_overrides(roxy(), "outfit", picks(full="maid apron"), VOCAB, source="n")
        self.assertIn("upper", fields(ch, "outfit"))

    def test_no_vocab_means_no_rules(self):
        ch = C.apply_overrides(roxy(), "outfit", picks(full="dress"), None, source="n")
        self.assertIn("upper", fields(ch, "outfit"))


class TestNegatives(unittest.TestCase):
    def test_pick_brings_negative_and_conflicts_drop(self):
        ch = C.apply_overrides(roxy(), "hair", picks(length="short hair"), VOCAB, source="n")
        self.assertEqual(ch["sections"]["hair"]["fields"]["length"]["negative"], "long hair, very long hair")
        r = render(ch, template("anima-mixed"))
        # Roxy's own preset negative "short hair" now contradicts the positive
        self.assertEqual(r.negative, "long hair, very long hair")
        self.assertEqual(r.neg_conflicts, ["short hair"])

    def test_typed_value_has_no_negative(self):
        ch = C.apply_overrides(roxy(), "hair", picks(length=("", "short hair")), VOCAB, source="n")
        self.assertNotIn("negative", ch["sections"]["hair"]["fields"]["length"])

    def test_replacing_value_drops_its_negative(self):
        ch = C.apply_overrides(roxy(), "hair", picks(length="short hair"), VOCAB, source="n")
        ch = C.apply_overrides(ch, "hair", picks(length=("", "medium hair")), VOCAB, source="n")
        self.assertEqual(render(ch, "{hair}").negative, "short hair")


class TestSave(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.user = self.tmp / "user"
        shutil.copytree(FIX, self.user)
        self.L = PresetLibrary([Root(self.user), Root(self.tmp / "shipped", "examples/")])

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def save(self, ch, target, **kw):
        overwrite = kw.pop("overwrite", False)
        data, notes = char_to_preset(ch, self.L, target, **kw)
        path, status = write_preset(self.L, target, data, overwrite=overwrite)
        return data, notes, path, status

    def test_round_trip_keeps_refs(self):
        ch = roxy(self.L)
        C.apply_field(ch, "hair", "length", text="(long hair:1.2)", source="n")
        data, notes, path, status = self.save(ch, "characters/roxy-copy", name="Roxy copy")
        self.assertEqual(status, "created")
        self.assertEqual(data["sections"]["outfit"], {"$ref": "outfits/roxy-default"})
        self.assertIn("outfit: saved as $ref outfits/roxy-default", notes)
        self.assertEqual(data["sections"]["identity"]["loras"][0]["trigger"], "roxy migurdia")
        self.assertEqual(data["negative"], "short hair")
        again = C.load_preset(None, self.L.resolve("characters/roxy-copy"), "x")
        self.assertEqual(render(again, template("anima-mixed")).positive,
                         render(ch, template("anima-mixed")).positive)

    def test_full_write_and_weights(self):
        ch = C.load_preset(None, self.L.resolve("characters/shinobu"), "s")
        data, *_ = self.save(ch, "characters/shinobu-flat", keep_refs=False)
        self.assertIn("fields", data["sections"]["outfit"])
        self.assertEqual(data["sections"]["hair"]["fields"]["length"], {"value": "long hair", "weight": 1.1})

    def test_field_negatives_folded_into_section(self):
        ch = C.apply_overrides(roxy(self.L), "hair", picks(length="short hair"), VOCAB, source="n")
        data, *_ = self.save(ch, "characters/roxy-short")
        self.assertEqual(data["sections"]["hair"]["negative"], "long hair, very long hair")
        self.assertEqual(render(C.load_preset(None, self.L.resolve("characters/roxy-short"), "x"), "{hair}").negative,
                         "long hair, very long hair")  # preset "short hair" negative dropped as conflict

    def test_never_overwrites_silently(self):
        ch = roxy(self.L)
        self.save(ch, "characters/new")
        _d, _n, _p, status = self.save(ch, "characters/new")
        self.assertEqual(status, "unchanged")  # same content re-run is fine
        C.apply_field(ch, "hair", "color", text="red hair", source="n")
        with self.assertRaisesRegex(KisekaeError, "already exists"):
            self.save(ch, "characters/new")
        self.assertEqual(self.save(ch, "characters/new", overwrite=True)[3], "overwritten")
        self.assertEqual(sorted(p.name for p in (self.user / "characters").iterdir() if p.name.startswith(".")), [])

    def test_self_ref_written_in_full(self):
        # Saving over characters/roxy itself: its outfit ref is fine (no loop)...
        ch = roxy(self.L)
        C.apply_field(ch, "hair", "color", text="red hair", source="n")
        data, *_ = self.save(ch, "characters/roxy", overwrite=True)
        self.assertEqual(data["sections"]["outfit"], {"$ref": "outfits/roxy-default"})
        # ...but a section whose ref leads back to the target file is written in full.
        (self.user / "outfits" / "via-roxy.json").write_text(json.dumps(
            {"kisekae": 1, "sections": {"outfit": {"$ref": "characters/roxy"}}}))
        ch2 = C.set_section(ch, "outfit", self.L.resolve("outfits/via-roxy").sections["outfit"], "swap")
        ch2["sections"]["outfit"]["origin"] = "outfits/via-roxy"
        data, notes, *_ = self.save(ch2, "characters/roxy", overwrite=True)
        self.assertIn("fields", data["sections"]["outfit"])
        self.assertTrue(any("would loop" in n for n in notes))
        self.L.resolve("characters/roxy")  # and the result loads without a loop

    def test_refuses_to_escape(self):
        ch = roxy(self.L)
        for bad in ["../evil", "/etc/evil", "examples/x", "a#b"]:
            with self.subTest(bad=bad), self.assertRaises(KisekaeError):
                self.save(ch, bad)
        outside = self.tmp / "outside"
        outside.mkdir()
        os.symlink(outside, self.user / "linked")
        with self.assertRaisesRegex(KisekaeError, "outside the preset folder"):
            self.save(ch, "linked/x")
        os.symlink(outside / "target.json", self.user / "file-link.json")
        with self.assertRaisesRegex(KisekaeError, "symlink"):
            self.save(ch, "file-link")
        self.assertEqual(list(outside.iterdir()), [])


class TestReportExtras(unittest.TestCase):
    def test_conflicts_and_token_counts(self):
        ch = C.apply_overrides(roxy(), "hair", picks(length="short hair"), VOCAB, source="n")
        r = render(ch, "{hair}")
        text = prompt_report(r, [], {"clip_g": 79, "clip_l": 79, "qwen3_06b": 40})
        self.assertIn("NEGATIVES DROPPED (also in positive) ──\nshort hair", text)
        self.assertIn("clip_l: 79  (2 × 75-token chunks)", text)
        self.assertIn("qwen3_06b: 40", text)
        self.assertNotIn("rough estimate", text)
        self.assertIn("rough estimate", prompt_report(r, []))


if __name__ == "__main__":
    unittest.main()
