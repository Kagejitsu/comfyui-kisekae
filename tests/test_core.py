"""Core tests. Run with:  python -m unittest discover -s tests -v"""

import json
import shutil
import tempfile
import time
import unittest
from collections import Counter
from pathlib import Path

from kisekae import char as C
from kisekae import loras
from kisekae.errors import KisekaeError
from kisekae.presets import PresetLibrary, Root, check_name
from kisekae.render import parse_template, render
from kisekae.tags import escape_item, merge_tags, merge_text, norm_key, split_items

HERE = Path(__file__).parent
FIX = HERE / "fixtures" / "presets"
TEMPLATES = HERE.parent / "data" / "templates"

# Kate's hand-written Anima prompt, the target the builder must reproduce.
ROXY_ORIGINAL = """\
masterpiece, best quality, score_7, best quality, amazing quality, looking at viewer, vignetting, dim lighting,
roxy migurdia, long hair, blue hair, hair between eyes, blue eyes, ahoge, very long hair, twin braids, sidelocks,
shirt, skirt, long sleeves, dress, hat, ribbon, jacket, boots, collared shirt, socks, black skirt, black ribbon, capelet, witch hat, white jacket, white footwear, black socks, grey shirt, white capelet,
@araki hirohiko, jojo no kimyou na bouken, jojo pose, contrapposto, twisted torso, leaning back, foreshortening, menacing (jojo), dramatic shadow
flamboyant pose, both hands are on her hips, you can see the power emanating off of her,
aura, glowing eyes, wind, floating hair, speed lines, dramatic lighting, backlighting, rim lighting, from below, debris, cracked ground, intense stare, serious"""

ROXY_EXPECTED = """\
masterpiece, best quality, score_7, amazing quality, looking at viewer, vignetting, dim lighting,
roxy migurdia, blue hair, long hair, very long hair, hair between eyes, ahoge, twin braids, sidelocks, blue eyes, hat, witch hat,
dress, shirt, long sleeves, collared shirt, grey shirt, jacket, capelet, white jacket, white capelet, skirt, black skirt, socks, black socks, boots, white footwear, ribbon, black ribbon,
@araki hirohiko, jojo no kimyou na bouken, jojo pose, contrapposto, twisted torso, leaning back, foreshortening, menacing \\(jojo\\), dramatic shadow,
flamboyant pose, both hands are on her hips, you can see the power emanating off of her,
aura, glowing eyes, wind, floating hair, speed lines, dramatic lighting, backlighting, rim lighting, from below, debris, cracked ground, intense stare, serious"""


def lib() -> PresetLibrary:
    return PresetLibrary([Root(FIX)])


def template(name: str) -> str:
    return (TEMPLATES / f"{name}.txt").read_text()


class TestTags(unittest.TestCase):
    def test_split_respects_brackets_and_newlines(self):
        self.assertEqual(split_items("a, (b, c:1.2),\n d ,, "), ["a", "(b, c:1.2)", "d"])
        self.assertEqual(split_items(r"menacing \(jojo\), x"), [r"menacing \(jojo\)", "x"])

    def test_escape(self):
        cases = {
            "menacing (jojo)": r"menacing \(jojo\)",
            "(red eyes:1.3)": "(red eyes:1.3)",
            "(menacing (jojo):1.2)": r"(menacing \(jojo\):1.2)",
            r"already \(done\)": r"already \(done\)",
            "(emphasis)": r"\(emphasis\)",
            "unmatched (": r"unmatched \(",
            "unmatched )": r"unmatched \)",
            "plain": "plain",
            "(neg:-0.5)": "(neg:-0.5)",
        }
        for raw, want in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(escape_item(raw), want)

    def test_norm_key(self):
        self.assertEqual(norm_key(r"  Menacing  \(JoJo\) "), "menacing (jojo)")

    def test_merge(self):
        self.assertEqual(merge_tags("a, b", "B, c"), "a, b, c")
        self.assertEqual(merge_tags("", "x"), "x")
        self.assertEqual(merge_text("She smiles.", "Wind blows."), "She smiles. Wind blows.")
        self.assertEqual(merge_text("flamboyant pose", "hands on hips"), "flamboyant pose, hands on hips")


class TestPresets(unittest.TestCase):
    def test_ref_pulls_same_named_section(self):
        res = lib().resolve("characters/roxy")
        outfit = res.sections["outfit"]
        self.assertEqual(outfit["fields"]["full"]["value"], "dress")
        self.assertEqual(outfit["fields"]["full"]["source"], "preset:outfits/roxy-default")
        self.assertEqual(outfit["origin"], "outfits/roxy-default")
        self.assertIsNone(res.sections["hair"]["origin"])
        self.assertEqual(res.negative, "short hair")

    def test_ref_only_takes_the_one_section(self):
        # shinobu-default also has a hair section; the outfit $ref must not bring it.
        res = lib().resolve("characters/shinobu")
        self.assertNotIn("accessories", res.sections["hair"]["fields"])
        self.assertEqual(res.sections["outfit"]["fields"]["lower"]["value"], "skirt")
        self.assertEqual(res.sections["hair"]["fields"]["length"]["weight"], 1.1)

    def test_extends_and_ref_with_local_override(self):
        res = lib().resolve("characters/roxy-casual")
        hair = res.sections["hair"]["fields"]
        self.assertEqual(hair["style"]["value"], "ponytail")              # overridden
        self.assertEqual(hair["color"]["value"], "blue hair")             # inherited
        self.assertEqual(res.sections["outfit"]["fields"]["full"]["value"], "white dress, sleeveless dress")
        head = res.sections["head"]
        self.assertEqual(head["fields"]["expression"]["value"], "smug")   # local wins over $ref
        self.assertEqual(head["fields"]["eyes"]["value"], "blue eyes")    # from $ref
        self.assertIsNone(head["origin"])                                 # edited -> not a pure ref
        self.assertEqual(res.sections["identity"]["loras"][0]["trigger"], "roxy migurdia")
        self.assertEqual(res.negative, "short hair")

    def test_loop_detected(self):
        with self.assertRaisesRegex(KisekaeError, "loop: loop/a → loop/b → loop/a"):
            lib().resolve("loop/a")

    def test_errors_are_specific(self):
        for name, pattern in {
            "bad/unknown-field": r"unknown field hair\.colour",
            "bad/bad-json": r"invalid JSON at line 2",
            "bad/bad-ref-section": r"unknown section 'hat'",
            "bad/missing-section": r"has no 'head' section",
            "nope/missing": r"not found",
        }.items():
            with self.subTest(name=name), self.assertRaisesRegex(KisekaeError, pattern):
                lib().resolve(name)

    def test_name_safety(self):
        for bad in ["../etc/passwd", "/etc/passwd", "a/../../b", "a\\b", "", "a//b", "./a"]:
            with self.subTest(bad=bad), self.assertRaises(KisekaeError):
                check_name(bad)
        self.assertEqual(check_name("outfits/maid.json"), "outfits/maid")
        self.assertEqual(check_name("キャラ/忍"), "キャラ/忍")

    def test_listing_and_section_filter(self):
        names = lib().list_names()
        self.assertIn("characters/roxy", names)
        self.assertIn("scenes/jojo-menacing", names)
        with_outfit = lib().list_with_section("outfit")
        self.assertIn("outfits/roxy-default", with_outfit)
        self.assertNotIn("scenes/jojo-menacing", with_outfit)
        self.assertIn("loop/a", with_outfit)  # broken presets stay visible

    def test_prefixed_root_and_priority(self):
        with tempfile.TemporaryDirectory() as tmp:
            user, shipped = Path(tmp, "user"), Path(tmp, "shipped")
            shutil.copytree(FIX / "outfits", shipped / "outfits")
            (user / "outfits").mkdir(parents=True)
            (user / "outfits" / "mine.json").write_text(
                json.dumps({"kisekae": 1, "sections": {"outfit": {"$ref": "examples/outfits/roxy-default"}}}))
            L = PresetLibrary([Root(user), Root(shipped, "examples/")])
            self.assertIn("examples/outfits/roxy-default", L.list_names())
            res = L.resolve("outfits/mine")
            self.assertEqual(res.sections["outfit"]["fields"]["full"]["value"], "dress")

    def test_fingerprint_changes_on_edit(self):
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copytree(FIX, tmp, dirs_exist_ok=True)
            L = PresetLibrary([Root(Path(tmp))])
            files = L.resolve("characters/roxy").files
            self.assertEqual(len(files), 2)  # roxy + its outfit ref
            before = L.fingerprint(files)
            time.sleep(0.01)
            Path(tmp, "outfits", "roxy-default.json").touch()
            self.assertNotEqual(before, L.fingerprint(files))


class TestChar(unittest.TestCase):
    def roxy(self):
        return C.load_preset(None, lib().resolve("characters/roxy"), "characters/roxy")

    def test_override_precedence(self):
        ch = self.roxy()
        C.apply_field(ch, "hair", "color", choice="red hair", text="", source="node")
        self.assertEqual(ch["sections"]["hair"]["fields"]["color"]["value"], "red hair")
        C.apply_field(ch, "hair", "color", choice="green hair", text="pink hair", source="node")
        self.assertEqual(ch["sections"]["hair"]["fields"]["color"]["value"], "pink hair")  # text wins
        C.apply_field(ch, "hair", "color", choice=C.KEEP, text="  ", source="node")
        self.assertEqual(ch["sections"]["hair"]["fields"]["color"]["value"], "pink hair")  # keep
        C.apply_field(ch, "hair", "color", choice=C.CLEAR, source="node")
        self.assertNotIn("color", ch["sections"]["hair"]["fields"])

    def test_append_toggle(self):
        ch = self.roxy()
        C.apply_field(ch, "outfit", "accessories", text="Ribbon, choker", append=True, source="node")
        f = ch["sections"]["outfit"]["fields"]["accessories"]
        self.assertEqual(f["value"], "ribbon, black ribbon, choker")
        self.assertEqual(f["source"], "preset:outfits/roxy-default + node")
        self.assertIsNone(ch["sections"]["outfit"]["origin"])  # edited

    def test_load_modes(self):
        roxy = self.roxy()
        scene = lib().resolve("scenes/jojo-menacing")
        merged = C.load_preset(roxy, scene, "scenes/jojo-menacing", "merge")
        self.assertEqual(merged["sections"]["head"]["fields"]["expression"]["value"], "intense stare, serious")
        self.assertEqual(merged["sections"]["head"]["fields"]["eyes"]["value"], "blue eyes")
        overlay = C.load_preset(roxy, scene, "scenes/jojo-menacing", "overlay")
        self.assertNotIn("eyes", overlay["sections"]["head"]["fields"])     # whole section replaced
        self.assertIn("hair", overlay["sections"])                          # untouched section kept
        replace = C.load_preset(roxy, scene, "scenes/jojo-menacing", "replace")
        self.assertNotIn("hair", replace["sections"])
        self.assertEqual(roxy["sections"]["head"]["fields"]["expression"]["value"], "smile")  # input untouched

    def test_branching_is_safe(self):
        roxy = self.roxy()
        a = C.set_section(roxy, "outfit", lib().resolve("outfits/shinobu-default").sections["outfit"], "swap")
        self.assertEqual(roxy["sections"]["outfit"]["fields"]["full"]["value"], "dress")
        self.assertEqual(a["sections"]["outfit"]["fields"]["full"]["value"], "white dress, sleeveless dress")
        self.assertEqual(a["trace"][-1], "swap")


class TestRender(unittest.TestCase):
    def roxy_jojo(self):
        ch = C.load_preset(None, lib().resolve("characters/roxy"), "characters/roxy")
        return C.load_preset(ch, lib().resolve("scenes/jojo-menacing"), "scenes/jojo-menacing", "merge")

    def test_roxy_golden(self):
        r = render(self.roxy_jojo(), template("anima-mixed"))
        self.assertEqual(r.positive, ROXY_EXPECTED)
        self.assertEqual(r.negative, "short hair")
        self.assertEqual(r.removed, ["best quality", "roxy migurdia"])  # dup quality; who == trigger
        self.assertEqual(r.escaped, [("menacing (jojo)", r"menacing \(jojo\)")])

    def test_roxy_matches_hand_written_prompt(self):
        """Same tags as Kate's prompt, minus her accidental duplicate."""
        got = Counter(norm_key(t) for t in split_items(render(self.roxy_jojo(), template("anima-mixed")).positive))
        want = Counter(norm_key(t) for t in split_items(ROXY_ORIGINAL))
        want["best quality"] -= 1
        self.assertEqual(got, want)

    def test_tags_template_drops_prose(self):
        r = render(self.roxy_jojo(), template("illustrious-tags"))
        self.assertNotIn("flamboyant pose", r.positive)
        self.assertIn("jojo pose", r.positive)

    def test_explicit_field_not_repeated(self):
        r = render(self.roxy_jojo(), "{head}\n{head.expression}")
        self.assertEqual(r.lines[1], "intense stare, serious")
        self.assertNotIn("serious", r.lines[0])

    def test_weights_literals_and_toggles(self):
        ch = C.load_preset(None, lib().resolve("characters/shinobu"), "characters/shinobu")
        r = render(ch, "masterpiece, {hair}\n\n{identity}", dedupe=False, escape=False)
        self.assertEqual(r.positive, "masterpiece, blonde hair, (long hair:1.1),\noshino shinobu, monogatari (series), 1girl")
        r = render(ch, "{identity}")
        self.assertEqual(r.positive, r"oshino shinobu, monogatari \(series\), 1girl")

    def test_triggers_toggle_and_loras(self):
        ch = self.roxy_jojo()
        self.assertTrue(render(ch, "{triggers}").positive)
        self.assertEqual(render(ch, "{triggers}", include_triggers=False).positive, "")
        found = loras.collect(ch)
        self.assertEqual([l["name"] for l in found], ["Characters/Mushoku/roxy.safetensors"])
        self.assertEqual(loras.syntax(found), "<lora:roxy:0.8>")

    def test_bad_templates(self):
        for t, pattern in {
            "{hat}": "unknown placeholder",
            "{hair.colour}": "unknown field",
            "{!hair}": "needs a field",
            "{triggers.x}": "takes no field",
            "{hair": "stray",
        }.items():
            with self.subTest(t=t), self.assertRaisesRegex(KisekaeError, pattern):
                parse_template(t)


if __name__ == "__main__":
    unittest.main()
