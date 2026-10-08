// Dropdowns page (PLAN-tansu.md §8, phase 2): the node dropdown values per field,
// with their companion negatives and "clears" (hides) rules. Every change
// rewrites the user's overlay entry for that field; shipped files never change.

import { api } from "./api.js";
import { append, clear, h, toast } from "./dom.js";

const ORIGIN = {
  shipped: { label: "shipped", title: "Comes with Kisekae" },
  changed: { label: "changed", title: "A shipped value you changed (Reset brings back the original)" },
  yours: { label: "yours", title: "Added by you" },
};

export async function openVocab(root, sc, { section, field }) {
  const page = { root, sc, section: section || "outfit", field: field || "full", view: null, dirty: false };
  render(page);
  await load(page);
  return page;
}

async function load(page) {
  try {
    page.view = await api.vocabField(page.section, page.field);
  } catch (e) {
    toast(e.message, "error", 8000);
  }
  renderMain(page);
}

async function save(page, entry) {
  try {
    page.view = await api.setVocabField(page.section, page.field, entry);
    const f = page.sc.sections.find((s) => s.name === page.section).fields.find((x) => x.name === page.field);
    f.values = page.view.options.map((o) => o.value); // keeps the editor's suggestions and the counts current
    page.root.querySelector(".tool-nav .tree-item.active .count").textContent = f.values.length;
    // the R hint once per visit; after that a short note is enough
    toast(page.hinted ? "Saved" : "Dropdown updated. Press R in ComfyUI to see it on the nodes", "ok", page.hinted ? 1500 : 4000);
    page.hinted = true;
  } catch (e) {
    toast(e.message, "error", 9000);
  }
  renderMain(page);
}

// -- overlay entry helpers ------------------------------------------------------------

function entryCopy(page) {
  return structuredClone(page.view.entry || {});
}

function findOpt(entry, value) {
  return (entry.options || []).findIndex((o) => (typeof o === "string" ? o : o.value) === value);
}

function upsert(page, opt, patch) {
  // Redefine an option in the overlay, starting from what it is now, so a shipped
  // value keeps its own hides/negative unless the patch changes them.
  const entry = entryCopy(page);
  entry.options ??= [];
  const base = { value: opt.value };
  if (opt.negative) base.negative = opt.negative;
  if (opt.custom_hides) base.hides = opt.hides;
  const next = { ...base, ...patch };
  if (next.negative === "") delete next.negative;
  if (next.hides === undefined) delete next.hides;
  const i = findOpt(entry, opt.value);
  if (i >= 0) entry.options[i] = next;
  else entry.options.push(next);
  return save(page, entry);
}

function dropOpt(page, value) {
  const entry = entryCopy(page);
  const i = findOpt(entry, value);
  if (i >= 0) entry.options.splice(i, 1);
  return save(page, entry);
}

function setRemoved(page, value, removed) {
  const entry = entryCopy(page);
  const set = new Set(entry.remove || []);
  removed ? set.add(value) : set.delete(value);
  entry.remove = [...set];
  const i = findOpt(entry, value);
  if (removed && i >= 0) entry.options.splice(i, 1); // hiding a value drops your changes to it
  return save(page, entry);
}

// -- layout -----------------------------------------------------------------------------

function render(page) {
  clear(page.root);
  page.mainEl = h("div", { class: "tool-main" });
  const nav = h("nav", { class: "sidebar tool-nav", "aria-label": "Fields" },
    page.sc.sections.map((s) => [
      h("div", { class: "tree-item root static" }, s.label),
      s.fields.map((f) => h("button", {
        class: `tree-item ${s.name === page.section && f.name === page.field ? "active" : ""}`,
        style: { paddingLeft: "1.6rem" },
        onclick: () => {
          history.replaceState(null, "", `#dropdowns/${s.name}/${f.name}`);
          page.section = s.name;
          page.field = f.name;
          render(page);
          load(page);
        },
      }, h("span", { class: "tree-label" }, f.name.replace("_", " ")), h("span", { class: "count" }, f.values.length))),
    ]));
  append(page.root, [h("div", { class: "layout" }, nav, h("main", {}, page.mainEl))]);
}

function hidesEditor(current, fields, onChange, { disabled = false } = {}) {
  const pick = h("select", {
    class: "text small-select", disabled,
    onchange: (e) => {
      if (e.target.value) onChange([...current, e.target.value]);
    },
  }, h("option", { value: "" }, "＋ clears…"),
  fields.filter((f) => !current.includes(f)).map((f) => h("option", { value: f }, f)));
  return h("div", { class: "hides" },
    current.length ? current.map((f) => h("span", { class: "pill" }, f, disabled ? null : h("button", {
      class: "x", title: `Stop clearing ${f}`, onclick: () => onChange(current.filter((x) => x !== f)),
    }, "×"))) : h("span", { class: "muted small" }, "nothing"),
    disabled ? null : pick);
}

function renderMain(page) {
  const v = page.view;
  const el = page.mainEl;
  clear(el);
  if (!v) return;
  const sec = page.sc.sections.find((s) => s.name === page.section);
  const entry = v.entry || {};

  const defaultBlock = h("div", { class: "ed-card" },
    h("div", { class: "row" }, h("h3", {}, "When a value is picked, clear…"),
      h("span", { class: "muted small" }, "the default for this field's values; a value can override it")),
    hidesEditor(v.default_hides, v.fields, (next) => {
      const e = entryCopy(page);
      const same = JSON.stringify(next) === JSON.stringify(v.shipped_default_hides);
      if (same) delete e.hides;
      else e.hides = next;
      save(page, e);
    }),
    JSON.stringify(v.default_hides) !== JSON.stringify(v.shipped_default_hides)
      ? h("button", {
        class: "btn small ghost", onclick: () => { const e = entryCopy(page); delete e.hides; save(page, e); },
      }, `↺ Back to shipped default (${v.shipped_default_hides.join(", ") || "nothing"})`)
      : null,
    h("label", { class: "check" },
      h("input", {
        type: "checkbox", checked: !!entry.replace,
        onchange: (e) => { const x = entryCopy(page); x.replace = e.target.checked; save(page, x); },
      }), "Replace the shipped list entirely (only your values)"));

  const rows = v.options.map((o) => {
    const neg = h("input", {
      class: "text", value: o.negative, placeholder: "—", spellcheck: false,
      title: "Added to the negative prompt while this value is picked",
      onchange: (e) => upsert(page, o, { negative: e.target.value.trim() }),
    });
    const actions = {
      shipped: h("button", { class: "btn small ghost", title: "Hide it from the dropdown", onclick: () => setRemoved(page, o.value, true) }, "Hide"),
      changed: h("button", { class: "btn small ghost", title: "Undo your changes to this shipped value", onclick: () => dropOpt(page, o.value) }, "↺ Reset"),
      yours: h("button", { class: "btn small ghost danger", title: "Remove your value", onclick: () => dropOpt(page, o.value) }, "Delete"),
    }[o.origin];
    return h("tr", {},
      h("td", { class: "mono" }, o.value),
      h("td", {}, h("span", { class: `origin ${o.origin}`, title: ORIGIN[o.origin].title }, ORIGIN[o.origin].label)),
      h("td", {}, neg),
      h("td", {},
        hidesEditor(o.hides, v.fields, (next) => upsert(page, o, { hides: next })),
        o.custom_hides ? h("button", {
          class: "btn small ghost", title: "Use the field's default again",
          onclick: () => upsert(page, { ...o, custom_hides: false }, {}),
        }, "↺ default") : null),
      h("td", {}, actions));
  });

  const addValue = h("input", { class: "text", placeholder: "new value, e.g. gothic dress", spellcheck: false });
  const addNeg = h("input", { class: "text", placeholder: "negative (optional)", spellcheck: false });
  const add = () => {
    const value = addValue.value.trim();
    if (!value) return;
    if (v.options.some((o) => o.value === value)) return toast(`${value} is already in the dropdown`, "error");
    if (v.removed.includes(value)) return setRemoved(page, value, false);
    const e = entryCopy(page);
    e.options = [...(e.options || []), addNeg.value.trim() ? { value, negative: addNeg.value.trim() } : value];
    save(page, e);
  };
  addValue.addEventListener("keydown", (e) => { if (e.key === "Enter") add(); });
  addNeg.addEventListener("keydown", (e) => { if (e.key === "Enter") add(); });

  append(el, [
    h("div", { class: "tool-head" },
      h("h1", {}, `${sec.label} → ${page.field.replace("_", " ")}`),
      h("span", { class: "muted" }, `${v.options.length} values · changes go to user/default/kisekae/vocab/${page.section}.json`)),
    v.errors.length ? h("div", { class: "error-box" }, h("strong", {}, "Some dropdown files have problems:"), v.errors.map((x) => h("div", {}, x))) : null,
    h("p", { class: "muted" }, "Negatives and “clears” apply when the value is picked from a node's dropdown, not to typed text or preset values."),
    defaultBlock,
    h("div", { class: "ed-card" },
      h("table", { class: "vocab" },
        h("thead", {}, h("tr", {}, ["Value", "", "Negative when picked", "Clears", ""].map((t) => h("th", {}, t)))),
        h("tbody", {}, rows,
          h("tr", { class: "add-row" }, h("td", {}, addValue), h("td", {}), h("td", {}, addNeg), h("td", {}),
            h("td", {}, h("button", { class: "btn small primary", onclick: add }, "＋ Add")))))),
    v.removed.length ? h("div", { class: "ed-card" },
      h("h3", {}, "Hidden shipped values"),
      h("div", { class: "card-foot" }, v.removed.map((value) => h("span", { class: "pill" }, value,
        h("button", { class: "x", title: "Show it again", onclick: () => setRemoved(page, value, false) }, "↺"))))) : null,
  ]);
}
