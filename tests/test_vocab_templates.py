"""Tansu phase 2: dropdown (vocab) overlay editing and user templates."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from kisekae import char as C
from kisekae import library as L
from kisekae import templates as T
from kisekae.errors import KisekaeError
from kisekae.vocab import Vocab

from .test_phase3 import picks, roxy

DATA = Path(__file__).parent.parent / "data"
SHIPPED = DATA / "vocab"


class Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def overlay(self, section, fields):
        (self.tmp / f"{section}.json").write_text(json.dumps({"fields": fields}))


class TestVocabMerge(Tmp):
    def test_user_values_inherit_the_field_default_hides(self):
        self.overlay("outfit", {"full": ["gothic dress"]})
        v = Vocab([SHIPPED, self.tmp])
        self.assertEqual(v.option("outfit", "full", "gothic dress")["hides"], ["outfit.upper", "outfit.lower"])
        ch = C.apply_overrides(roxy(), "outfit", picks(full="gothic dress"), v, source="n")
        self.assertNotIn("upper", ch["sections"]["outfit"]["fields"])

    def test_overlay_can_change_the_default_and_remove_values(self):
        self.overlay("outfit", {"full": {"hides": [], "options": ["robe"], "remove": ["nurse"]}})
        v = Vocab([SHIPPED, self.tmp])
        self.assertEqual(v.option("outfit", "full", "robe")["hides"], [])
        self.assertEqual(v.option("outfit", "full", "dress")["hides"], ["outfit.upper", "outfit.lower"])
        self.assertNotIn("nurse", v.values("outfit", "full"))
        self.assertEqual(v.errors, [])
        self.overlay("outfit", {"full": {"remove": "nurse"}})
        self.assertIn("remove", Vocab([SHIPPED, self.tmp]).errors[0])


class TestVocabEditing(Tmp):
    def test_field_view_origins(self):
        self.overlay("hair", {"length": {"options": [{"value": "short hair", "negative": "long hair"}, "wavy bob"],
                                         "remove": ["very long hair"]}})
        view = L.vocab_field(SHIPPED, self.tmp, "hair", "length")
        origin = {o["value"]: o["origin"] for o in view["options"]}
        self.assertEqual(origin["short hair"], "changed")
        self.assertEqual(origin["wavy bob"], "yours")
        self.assertEqual(origin["long hair"], "shipped")
        self.assertEqual(view["removed"], ["very long hair"])
        self.assertIn("outfit.legwear", view["fields"])

    def test_set_field_round_trip_and_validation(self):
        view = L.set_vocab_field(SHIPPED, self.tmp, "outfit", "full",
                                 {"options": [{"value": "robe", "hides": ["outfit.upper"]}], "remove": ["nurse"]})
        robe = next(o for o in view["options"] if o["value"] == "robe")
        self.assertEqual((robe["hides"], robe["custom_hides"]), (["outfit.upper"], True))
        with self.assertRaisesRegex(KisekaeError, "unknown field 'outfit.hat'"):
            L.set_vocab_field(SHIPPED, self.tmp, "outfit", "full", {"options": [{"value": "x", "hides": ["outfit.hat"]}]})
        self.assertIn("robe", Vocab([SHIPPED, self.tmp]).values("outfit", "full"))  # the bad edit wasn't written
        L.set_vocab_field(SHIPPED, self.tmp, "outfit", "full", {})
        self.assertEqual(json.loads((self.tmp / "outfit.json").read_text()), {"fields": {}})

    def test_refuses_to_clobber_a_broken_overlay(self):
        (self.tmp / "hair.json").write_text("{oops")
        with self.assertRaisesRegex(KisekaeError, "fix it by hand"):
            L.set_vocab_field(SHIPPED, self.tmp, "hair", "color", {"options": ["x"]})
        self.assertEqual((self.tmp / "hair.json").read_text(), "{oops")

    def test_add_to_dropdown_unhides_a_removed_value(self):
        self.overlay("outfit", {"full": {"remove": ["nurse"]}})
        L.add_vocab(SHIPPED, self.tmp, "outfit", "full", "nurse")
        self.assertIn("nurse", Vocab([SHIPPED, self.tmp]).values("outfit", "full"))


class TestTemplates(Tmp):
    def test_list_save_override_and_trash(self):
        shipped = DATA / "templates"
        names = [t["name"] for t in T.list_templates(shipped, self.tmp)]
        self.assertEqual(names[0], "anima-mixed")
        T.save_template(self.tmp, "portrait", "{identity}, {hair}\n{head}")
        T.save_template(self.tmp, "anima-mixed", "{identity}")
        by = {t["name"]: t for t in T.list_templates(shipped, self.tmp)}
        self.assertEqual(by["portrait"]["origin"], "yours")
        self.assertEqual(by["anima-mixed"]["origin"], "override")
        self.assertIn("{style.quality}", by["anima-mixed"]["shipped_text"])
        T.trash_template(self.tmp, "anima-mixed")
        T.save_template(self.tmp, "anima-mixed", "{identity}")
        T.trash_template(self.tmp, "anima-mixed")  # same second: kept as a second trash file
        self.assertEqual(len(list((self.tmp / ".trash").iterdir())), 2)
        self.assertEqual({t["name"]: t["origin"] for t in T.list_templates(shipped, self.tmp)}["anima-mixed"], "shipped")

    def test_refusals(self):
        for name in ["../evil", "a/b", ".hidden", "x.txt", ""]:
            with self.subTest(name=name), self.assertRaises(KisekaeError):
                T.save_template(self.tmp, name, "{hair}")
        with self.assertRaisesRegex(KisekaeError, "unknown"):
            T.save_template(self.tmp, "bad", "{hair.colour}")
        with self.assertRaisesRegex(KisekaeError, "shipped"):
            T.trash_template(self.tmp, "anima-mixed")
        self.assertEqual(list(self.tmp.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
