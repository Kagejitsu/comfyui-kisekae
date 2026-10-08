"""Tansu step 1a: library operations (index, refs, save/conflict, rename, trash, vocab)."""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from kisekae import char as C
from kisekae import library as L
from kisekae.errors import KisekaeError
from kisekae.presets import PresetLibrary, Root
from kisekae.render import render
from kisekae.save import char_to_preset, keep_file_metadata, write_preset
from kisekae.vocab import Vocab

from .test_core import FIX

SHIPPED = Path(__file__).parent.parent / "data"


class LibCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.user = self.tmp / "user"
        shutil.copytree(FIX, self.user)
        self.lib = PresetLibrary([Root(self.user), Root(SHIPPED / "examples", "examples/")])

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def raw(self, name):
        return json.loads((self.user / f"{name}.json").read_text())

    def entry(self, entries, name):
        return next(e for e in entries if e["name"] == name)


class TestIndex(LibCase):
    def test_entries_errors_and_refs(self):
        (self.user / "characters" / "roxy.webp").write_bytes(b"x")
        d = self.raw("characters/roxy")
        d["tags"] = ["Mushoku", " mushoku ", "Blue  Hair"]
        d["nsfw"] = True
        (self.user / "characters" / "roxy.json").write_text(json.dumps(d))
        entries = L.index(self.lib)
        roxy = self.entry(entries, "characters/roxy")
        self.assertEqual(roxy["title"], "Roxy")
        self.assertEqual(roxy["tags"], ["mushoku", "blue hair"])
        self.assertTrue(roxy["picture"])
        self.assertTrue(roxy["nsfw"])
        self.assertFalse(self.entry(entries, "characters/shinobu")["nsfw"])
        self.assertIn("outfit", roxy["sections"])
        self.assertEqual(roxy["loras"][0]["trigger"], "roxy migurdia")
        self.assertIn("twin braids", roxy["search"])
        self.assertEqual(roxy["refs"], ["outfits/roxy-default"])
        self.assertIn("loop", self.entry(entries, "loop/a")["error"])
        self.assertIn("invalid JSON", self.entry(entries, "bad/bad-json")["error"])
        self.assertTrue(self.entry(entries, "examples/characters/aoi")["readonly"])

        used_by = L.reverse_refs(entries)
        self.assertEqual(sorted(used_by["characters/roxy"]), ["bad/bad-ref-section", "characters/roxy-casual"])
        self.assertEqual(L.tag_counts(entries), {"blue hair": 1, "mushoku": 1})


class TestSave(LibCase):
    def test_create_update_and_conflicts(self):
        data = {"kisekae": 1, "name": "New", "tags": ["A", "a", " b "],
                "sections": {"hair": {"fields": {"color": "red hair"}}}}
        tag = L.save(self.lib, "characters/new", {**data, "nsfw": True}, None)
        self.assertEqual(self.raw("characters/new")["tags"], ["a", "b"])
        self.assertEqual(list(self.raw("characters/new")), ["kisekae", "name", "tags", "nsfw", "sections"])
        with self.assertRaises(L.Conflict):  # create, but it exists now
            L.save(self.lib, "characters/new", data, None)
        data["sections"]["hair"]["fields"]["color"] = "blue hair"
        tag2 = L.save(self.lib, "characters/new", data, tag)
        self.assertNotEqual(tag, tag2)
        # someone else (e.g. the Save Preset node) writes meanwhile
        os.utime(self.user / "characters/new.json", ns=(1, 1))
        with self.assertRaisesRegex(L.Conflict, "changed on disk"):
            L.save(self.lib, "characters/new", data, tag2)

    def test_refuses_invalid_and_readonly(self):
        bad = {"kisekae": 1, "sections": {"hair": {"fields": {"colour": "red"}}}}
        self.assertIn("unknown field hair.colour", L.validate(self.lib, "x/y", bad)[0])
        with self.assertRaisesRegex(KisekaeError, "unknown field"):
            L.save(self.lib, "x/y", bad, None)
        with self.assertRaisesRegex(KisekaeError, "tags"):
            L.save(self.lib, "x/y", {"kisekae": 1, "tags": "oops"}, None)
        with self.assertRaisesRegex(KisekaeError, "nsfw"):
            L.save(self.lib, "x/y", {"kisekae": 1, "nsfw": "yes"}, None)
        L.save(self.lib, "x/sfw", {"kisekae": 1, "nsfw": False}, None)
        self.assertNotIn("nsfw", self.raw("x/sfw"))  # only R-18 presets carry the flag
        shutil.rmtree(self.user / "x")
        with self.assertRaisesRegex(KisekaeError, "examples/"):
            L.save(self.lib, "examples/characters/aoi", {"kisekae": 1}, None)
        self.assertFalse((self.user / "x").exists())

    def test_draft_resolves_with_refs(self):
        d = self.raw("characters/roxy")
        d["sections"]["hair"]["fields"]["color"] = "pink hair"
        res = self.lib.resolve_draft("characters/roxy", d)
        self.assertEqual(res.sections["hair"]["fields"]["color"]["value"], "pink hair")
        self.assertIn("outfit", res.sections)  # the $ref still resolves from disk
        self.assertEqual(self.raw("characters/roxy")["sections"]["hair"]["fields"]["color"], "blue hair")
        loop = {"kisekae": 1, "sections": {"outfit": {"$ref": "characters/roxy-draft"}}}
        self.assertIn("loop", L.validate(self.lib, "characters/roxy-draft", loop)[0])


class TestRename(LibCase):
    def test_dry_run_then_apply_rewrites_every_ref_form(self):
        (self.user / "characters" / "roxy.png").write_bytes(b"pic")
        changed = L.rename(self.lib, "characters/roxy", "mushoku/roxy", dry_run=True)
        self.assertEqual(changed, ["bad/bad-ref-section", "characters/roxy-casual"])
        self.assertTrue((self.user / "characters/roxy.json").exists())  # dry run touched nothing

        L.rename(self.lib, "characters/roxy", "mushoku/roxy", dry_run=False)
        self.assertFalse((self.user / "characters/roxy.json").exists())
        self.assertTrue((self.user / "mushoku/roxy.png").exists())
        casual = self.raw("characters/roxy-casual")
        self.assertEqual(casual["extends"], "mushoku/roxy")
        self.assertIn("mushoku/roxy", json.dumps(casual["sections"]))
        self.assertEqual(self.raw("bad/bad-ref-section")["sections"]["outfit"]["$ref"], "mushoku/roxy#hat")
        self.lib.resolve("characters/roxy-casual")  # still loads

    def test_self_reference_and_refusals(self):
        (self.user / "self.json").write_text(json.dumps(
            {"kisekae": 1, "sections": {"hair": {"fields": {"color": "x"}},
                                        "head": {"$ref": "self#hair"}}}))
        # (#hair into head is invalid on purpose: only the ref string matters here)
        self.assertEqual(L.rename(self.lib, "self", "moved", dry_run=False), ["self"])
        self.assertEqual(self.raw("moved")["sections"]["head"]["$ref"], "moved#hair")
        for old, new, msg in [("examples/characters/aoi", "x", "duplicate"),
                              ("characters/roxy", "characters/shinobu", "already exists"),
                              ("characters/roxy", "../escape", "relative path"),
                              ("characters/roxy", "characters/roxy", "same")]:
            with self.subTest(old=old, new=new), self.assertRaisesRegex(KisekaeError, msg):
                L.rename(self.lib, old, new, dry_run=True)

    def test_duplicate_from_examples(self):
        name = L.duplicate(self.lib, "examples/characters/ren", "characters/ren", "Ren (mine)")
        self.assertEqual(self.raw(name)["name"], "Ren (mine)")
        self.assertEqual(self.raw(name)["sections"]["outfit"]["$ref"], "examples/outfits/shrine")
        with self.assertRaisesRegex(KisekaeError, "already exists"):
            L.duplicate(self.lib, "examples/characters/ren", "characters/ren")


class TestTrash(LibCase):
    def test_trash_restore_and_hidden_from_dropdowns(self):
        (self.user / "outfits" / "roxy-default.webp").write_bytes(b"pic")
        out = L.trash(self.lib, "outfits/roxy-default")
        self.assertEqual(out["still_used_by"], ["characters/roxy"])
        self.assertNotIn("outfits/roxy-default", self.lib.list_names())
        self.assertEqual([e["name"] for e in L.list_trash(self.lib)], ["outfits/roxy-default"])
        with self.assertRaisesRegex(KisekaeError, "not found"):
            self.lib.resolve("characters/roxy")  # the referrer is broken meanwhile

        L.restore(self.lib, out["id"], "outfits/roxy-default")
        self.assertTrue((self.user / "outfits/roxy-default.webp").exists())
        self.lib.resolve("characters/roxy")
        self.assertEqual(L.list_trash(self.lib), [])

    def test_restore_refusals(self):
        out = L.trash(self.lib, "scenes/jojo-menacing")
        (self.user / "scenes/jojo-menacing.json").write_text('{"kisekae": 1}')
        with self.assertRaisesRegex(KisekaeError, "exists now"):
            L.restore(self.lib, out["id"], "scenes/jojo-menacing")
        for bad_id in ["../..", "20261008-120000", ""]:
            with self.subTest(bad_id=bad_id), self.assertRaisesRegex(KisekaeError, "invalid trash entry"):
                L.restore(self.lib, bad_id, "scenes/jojo-menacing")
        with self.assertRaisesRegex(KisekaeError, "can't be deleted"):
            L.trash(self.lib, "examples/characters/aoi")


class TestSaveNodeKeepsMetadata(LibCase):
    def test_tags_and_description_survive_a_graph_save(self):
        d = self.raw("characters/roxy")
        d["tags"], d["description"], d["nsfw"] = ["mushoku"], "set in Tansu", True
        (self.user / "characters/roxy.json").write_text(json.dumps(d))
        ch = C.load_preset(None, self.lib.resolve("characters/roxy"), "characters/roxy")
        data, _ = char_to_preset(ch, self.lib, "characters/roxy")
        data = keep_file_metadata(self.lib, "characters/roxy", data)
        self.assertEqual((data["tags"], data["description"], data["nsfw"]), (["mushoku"], "set in Tansu", True))
        self.assertEqual(list(data)[:5], ["kisekae", "name", "description", "tags", "nsfw"])
        data2, _ = char_to_preset(ch, self.lib, "characters/roxy", description="new words")
        self.assertEqual(keep_file_metadata(self.lib, "characters/roxy", data2)["description"], "new words")
        write_preset(self.lib, "characters/roxy", data, overwrite=True)
        self.assertEqual(render(C.load_preset(None, self.lib.resolve("characters/roxy"), "r"), "{hair}").positive,
                         render(ch, "{hair}").positive)


class TestAddVocab(LibCase):
    def test_adds_to_overlay_without_touching_shipped(self):
        vdir = self.tmp / "vocab"
        shipped = SHIPPED / "vocab"
        before = (shipped / "hair.json").read_bytes()
        vals = L.add_vocab(shipped, vdir, "hair", "color", "pastel pink hair")
        self.assertEqual(vals[-1], "pastel pink hair")
        L.add_vocab(shipped, vdir, "hair", "color", "pastel pink hair")  # no duplicate
        L.add_vocab(shipped, vdir, "hair", "color", "blue hair")  # already shipped
        self.assertEqual(json.loads((vdir / "hair.json").read_text()), {"fields": {"color": ["pastel pink hair"]}})
        self.assertEqual((shipped / "hair.json").read_bytes(), before)
        self.assertEqual(Vocab([shipped, vdir]).errors, [])
        (vdir / "outfit.json").write_text(json.dumps({"fields": {"full": {"hides": [], "options": ["a"]}}}))
        L.add_vocab(shipped, vdir, "outfit", "full", "b")
        self.assertEqual(json.loads((vdir / "outfit.json").read_text())["fields"]["full"]["options"], ["a", "b"])
        for sec, f, v in [("hair", "colour", "x"), ("hat", "x", "x"), ("hair", "color", "two\nlines"), ("hair", "color", " ")]:
            with self.subTest(sec=sec, f=f, v=v), self.assertRaises(KisekaeError):
                L.add_vocab(shipped, vdir, sec, f, v)


if __name__ == "__main__":
    unittest.main()
