// Preset editor (PLAN-tansu.md §7): a form over the preset JSON, a raw JSON tab,
// and a live prompt preview. The form edits `ed.draft` in place; structural
// changes (switching a section's source, adding a LoRA) re-render the form.

import { api } from "./api.js";
import { append, clear, dialog, h, toast } from "./dom.js";

const SECTION_ICON = {
  identity: "👤", head: "🙂", hair: "💇", body: "🧍", outfit: "👘", style: "🎨", pose: "🤸", scene: "🎬",
};
let schemaCache = null;
let loraCache = new Map(); // query -> results

async function schema() {
  if (!schemaCache) schemaCache = await api.schema();
  return schemaCache;
}

function blankPreset() {
  return { kisekae: 1, name: "", sections: {} };
}

function clean(o) {
  // drop empty bits so the saved JSON stays tidy
  const sec = o;
  if (sec.fields && !Object.keys(sec.fields).length) delete sec.fields;
  if (sec.loras && !sec.loras.length) delete sec.loras;
  if (sec.negative === "") delete sec.negative;
  return sec;
}

function fieldValue(raw) {
  if (raw === undefined) return { value: "", weight: "" };
  if (typeof raw === "string") return { value: raw, weight: "" };
  return { value: raw.value ?? "", weight: raw.weight ?? "" };
}

// -- entry point ---------------------------------------------------------------------

export async function openEditor(app, state, { name = null, folder = "" } = {}) {
  const sc = await schema();
  const ed = {
    app, state, sc,
    name, isNew: !name, readonly: false, etag: null,
    draft: blankPreset(), dirty: false, tab: "form",
    preview: null, previewTimer: null, resolved: {},
  };
  if (name) {
    try {
      const r = await api.preset(name);
      Object.assign(ed, { draft: r.data, etag: r.etag, readonly: r.readonly });
    } catch (e) {
      toast(e.message, "error", 8000);
      return app.closeEditor(true);
    }
  } else {
    ed.path = folder ? folder.replace(/\/?$/, "/") : "";
  }
  render(ed);
  schedulePreview(ed, 0);
  return ed;
}

// -- layout ----------------------------------------------------------------------------

function render(ed) {
  const root = document.getElementById("editor");
  clear(root);
  ed.titleEl = h("h1", {}, ed.draft.name || ed.name || "New preset");
  ed.dirtyEl = h("span", { class: "dirty-dot", title: "Unsaved changes", hidden: !ed.dirty }, "●");
  ed.saveBtn = h("button", { class: "btn primary", disabled: ed.readonly, onclick: () => save(ed) }, "Save", h("kbd", {}, "Ctrl+S"));
  const tabs = h("div", { class: "tabs" },
    ["form", "json"].map((t) => h("button", {
      class: `tab ${ed.tab === t ? "on" : ""}`, onclick: () => switchTab(ed, t),
    }, t === "form" ? "Form" : "Raw JSON")));
  const bar = h("div", { class: "editor-bar" },
    h("button", { class: "btn ghost", onclick: () => ed.app.closeEditor() }, "← Organizer"),
    ed.titleEl, ed.dirtyEl, h("div", { class: "spacer" }), tabs, ed.saveBtn);
  ed.formEl = h("div", { class: "editor-form" });
  ed.previewEl = h("aside", { class: "editor-preview" });
  append(root, [
    bar,
    ed.readonly ? h("div", { class: "banner" },
      "🔒 This is a shipped example and is read-only. ",
      h("button", { class: "btn small", onclick: () => duplicateToEdit(ed) }, "Duplicate to edit")) : null,
    h("div", { class: "editor-cols" }, ed.formEl, ed.previewEl),
  ]);
  renderBody(ed);
  renderPreview(ed);
}

function renderBody(ed) {
  clear(ed.formEl);
  if (ed.tab === "json") return renderJson(ed);
  renderForm(ed);
}

function changed(ed, { rerender = false } = {}) {
  ed.dirty = true;
  ed.dirtyEl.hidden = false;
  ed.titleEl.textContent = ed.draft.name || ed.name || ed.path || "New preset";
  if (rerender) renderBody(ed);
  schedulePreview(ed);
}

// -- form --------------------------------------------------------------------------------

function renderForm(ed) {
  const d = ed.draft;
  const ro = ed.readonly;
  const names = ed.state.presets.map((p) => p.name);
  const presetList = h("datalist", { id: "dl-presets" }, names.map((n) => h("option", { value: n })));
  const tagList = h("datalist", { id: "dl-tags" }, Object.keys(ed.state.tags).map((t) => h("option", { value: t })));

  const pathInput = ed.isNew
    ? h("input", {
      class: "text", value: ed.path || "", placeholder: "characters/my-character", spellcheck: false, disabled: ro,
      oninput: (e) => { ed.path = e.target.value.trim(); changed(ed); },
    })
    : h("div", { class: "mono readonly-path", title: "Use Rename / move in the organizer to change it" }, ed.name);

  const header = h("section", { class: "ed-card head" },
    h("div", { class: "grid2" },
      h("label", {}, "Path", pathInput),
      h("label", {}, "Display name", h("input", {
        class: "text", value: d.name || "", placeholder: "Shown on cards and in Save Preset", disabled: ro,
        oninput: (e) => { d.name = e.target.value; changed(ed); },
      }))),
    h("label", {}, "Description", h("textarea", {
      class: "text", rows: 2, value: d.description || "", disabled: ro,
      oninput: (e) => { e.target.value ? (d.description = e.target.value) : delete d.description; changed(ed); },
    })),
    h("div", { class: "grid2" },
      h("label", {}, "Tags", tagInput(ed)),
      h("label", {}, "Extends", h("div", { class: "row" },
        h("input", {
          class: "text", list: "dl-presets", value: d.extends || "", placeholder: "(none): start from another preset",
          spellcheck: false, disabled: ro,
          onchange: (e) => { e.target.value.trim() ? (d.extends = e.target.value.trim()) : delete d.extends; changed(ed, { rerender: true }); },
        })))),
    h("label", { class: "check", title: "Blurred or hidden in Tansu depending on the 🔞 setting. The nodes ignore it." },
      h("input", {
        type: "checkbox", checked: d.nsfw === true, disabled: ro,
        onchange: (e) => { e.target.checked ? (d.nsfw = true) : delete d.nsfw; changed(ed); },
      }), "🔞 R-18 preset"),
    d.extends ? h("p", { class: "muted small" }, `Sections left as “inherit” come from ${d.extends}; fields you fill in apply on top.`) : null);

  const sections = ed.sc.sections.map((s) => sectionCard(ed, s));
  const neg = h("section", { class: "ed-card" },
    h("h3", {}, "⊖ Preset negative"),
    h("input", {
      class: "text", value: d.negative || "", placeholder: "Added to the negative prompt for this preset", disabled: ro,
      oninput: (e) => { e.target.value ? (d.negative = e.target.value) : delete d.negative; changed(ed); },
    }));
  append(ed.formEl, [presetList, tagList, header, sections, neg]);
}

function tagInput(ed) {
  const d = ed.draft;
  const box = h("div", { class: "tag-input" });
  const draw = () => {
    clear(box);
    for (const t of d.tags || []) {
      box.append(h("span", { class: "pill" }, t, ed.readonly ? null : h("button", {
        class: "x", title: `Remove ${t}`, onclick: () => {
          d.tags = d.tags.filter((x) => x !== t);
          if (!d.tags.length) delete d.tags;
          draw();
          changed(ed);
        },
      }, "×")));
    }
    if (ed.readonly) return;
    const input = h("input", { list: "dl-tags", placeholder: d.tags?.length ? "" : "add a tag…", spellcheck: false });
    const add = () => {
      const t = input.value.trim().toLowerCase().replace(/\s+/g, " ");
      input.value = "";
      if (!t || d.tags?.includes(t)) return;
      d.tags = [...(d.tags || []), t];
      draw();
      changed(ed);
      box.querySelector("input")?.focus();
    };
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === ",") { e.preventDefault(); add(); }
      if (e.key === "Backspace" && !input.value && d.tags?.length) {
        d.tags = d.tags.slice(0, -1);
        if (!d.tags.length) delete d.tags;
        draw();
        changed(ed);
        box.querySelector("input")?.focus();
      }
    });
    input.addEventListener("change", add); // picked from the suggestions
    box.append(input);
  };
  draw();
  return box;
}

function sectionMode(raw) {
  if (!raw) return "none";
  return "$ref" in raw ? "ref" : "fields";
}

function sectionCard(ed, s) {
  const d = ed.draft;
  d.sections ??= {};
  const raw = d.sections[s.name];
  const mode = sectionMode(raw);
  const ro = ed.readonly;
  const setMode = (m) => {
    if (m === "none") delete d.sections[s.name];
    else if (m === "fields") d.sections[s.name] = clean({ fields: { ...(raw?.fields || {}) }, loras: raw?.loras || [], negative: raw?.negative || "" });
    else d.sections[s.name] = { $ref: raw?.$ref || "", ...(raw?.fields ? { fields: raw.fields } : {}) };
    changed(ed, { rerender: true });
  };
  const noneLabel = d.extends ? "inherit" : "none";
  const modes = h("div", { class: "seg" },
    [["none", noneLabel], ["fields", "fields"], ["ref", "$ref"]].map(([m, label]) => h("button", {
      class: mode === m ? "on" : "", disabled: ro, onclick: () => mode !== m && setMode(m),
      title: { none: d.extends ? "Inherited unchanged from the extended preset" : "Not part of this preset",
        fields: "Written here", ref: "Taken from another preset (optionally with fields on top)" }[m],
    }, label)));
  const filled = raw ? Object.keys(raw.fields || {}).length + (raw.loras?.length || 0) : 0;
  const head = h("div", { class: "ed-card-head" },
    h("h3", {}, `${SECTION_ICON[s.name] || ""} ${s.label}`),
    mode === "ref" ? h("span", { class: "muted small" }, raw.$ref ? `from ${raw.$ref}` : "") : null,
    filled ? h("span", { class: "count" }, filled) : null,
    h("div", { class: "spacer" }),
    !ro && mode !== "none" ? h("button", {
      class: "btn small ghost", title: "Move this section into its own preset and reference it from here",
      onclick: () => extractSection(ed, s),
    }, "⇪ As preset") : null,
    modes);
  const card = h("section", { class: `ed-card section ${mode === "none" ? "collapsed" : ""}` }, head);
  if (mode === "none") return card;

  if (mode === "ref") {
    card.append(h("label", { class: "ref-row" }, "Reference",
      h("input", {
        class: "text", list: "dl-presets", value: raw.$ref, placeholder: "outfits/maid  or  characters/aoi#outfit",
        spellcheck: false, disabled: ro,
        onchange: (e) => { raw.$ref = e.target.value.trim(); changed(ed, { rerender: true }); },
      })),
    h("p", { class: "muted small" }, "Fields filled in below apply on top of the reference; empty ones show what it provides."));
  }
  const inherited = ed.resolved[s.name] || {};
  card.append(h("div", { class: "fields" }, s.fields.map((f) => fieldRow(ed, s, f, inherited[f.name]))));
  if ((mode === "fields" || raw.loras) && !(ed.readonly && !raw.loras?.length)) card.append(loraRows(ed, s));
  card.append(h("label", { class: "neg-row" }, "Section negative", h("input", {
    class: "text", value: raw.negative || "", disabled: ro, placeholder: "e.g. short hair",
    oninput: (e) => { e.target.value ? (raw.negative = e.target.value) : delete raw.negative; changed(ed); },
  })));
  return card;
}

function fieldRow(ed, s, f, inheritedValue) {
  const raw = ed.draft.sections[s.name];
  const cur = fieldValue(raw.fields?.[f.name]);
  const ro = ed.readonly;
  const listId = `dl-${s.name}-${f.name}`;
  const write = () => {
    raw.fields ??= {};
    const v = input.value;
    const w = weight.value === "" ? null : Number(weight.value);
    if (!v.trim()) delete raw.fields[f.name];
    else raw.fields[f.name] = w !== null && w !== 1 && !Number.isNaN(w) ? { value: v, weight: w } : v;
    if (!Object.keys(raw.fields).length) delete raw.fields;
    addBtn.hidden = ro || !v.trim() || f.values.includes(v.trim());
    changed(ed);
  };
  const props = {
    class: "text", value: cur.value, disabled: ro, spellcheck: false, list: f.multiline ? undefined : listId,
    placeholder: inheritedValue ? `↳ ${inheritedValue}` : (f.values.length ? `e.g. ${f.values.slice(0, 2).join(" · ")}` : ""),
    oninput: write,
  };
  const input = f.multiline ? h("textarea", { ...props, rows: 2 }) : h("input", props);
  const weight = h("input", {
    class: "text weight", type: "number", step: "0.05", min: "0", max: "3", value: cur.weight,
    placeholder: "1.0", title: "Weight, e.g. 1.2 → (value:1.2)", disabled: ro, oninput: write,
  });
  const addBtn = h("button", {
    class: "btn small ghost add-vocab", title: `Add “${cur.value}” to the ${s.name}.${f.name} dropdown on the nodes`,
    hidden: ro || !cur.value.trim() || f.values.includes(cur.value.trim()),
    onclick: async () => {
      try {
        const { values } = await api.addVocab(s.name, f.name, input.value.trim());
        f.values = values;
        addBtn.hidden = true;
        listEl.replaceChildren(...values.map((v) => h("option", { value: v })));
        toast(`Added to the ${s.label} → ${f.name} dropdown (press R in ComfyUI to see it)`, "ok", 5000);
      } catch (e) {
        toast(e.message, "error", 7000);
      }
    },
  }, "＋ dropdown");
  const listEl = h("datalist", { id: listId }, f.values.map((v) => h("option", { value: v })));
  return h("div", { class: `field-row ${f.multiline ? "multi" : ""}` },
    h("span", { class: "fname", title: f.kind === "text" ? "Prose: written as a sentence" : "" }, f.name.replace("_", " ")),
    input, weight, addBtn, listEl);
}

function loraRows(ed, s) {
  const raw = ed.draft.sections[s.name];
  const ro = ed.readonly;
  raw.loras ??= [];
  const box = h("div", { class: "loras-edit" }, h("div", { class: "sub" }, "LoRAs"));
  raw.loras.forEach((l, i) => {
    if (typeof l === "string") raw.loras[i] = l = { name: l };
    const linked = l.clip_strength === undefined || l.clip_strength === l.strength;
    const nameIn = h("input", {
      class: "text", value: l.name || "", list: "dl-loras", placeholder: "search your loras folder…", spellcheck: false, disabled: ro,
      oninput: (e) => { l.name = e.target.value; searchLoras(e.target.value); changed(ed); },
      onchange: (e) => {
        const hit = (loraCache.get("last") || []).find((x) => x.name === e.target.value);
        if (hit && !l.trigger && hit.triggers.length) {
          l.trigger = hit.triggers[0];
          trig.value = l.trigger;
          changed(ed);
        }
      },
    });
    const str = h("input", {
      class: "text weight", type: "number", step: "0.05", value: l.strength ?? 1, title: "Model strength", disabled: ro,
      oninput: (e) => { l.strength = Number(e.target.value); if (linkBox.checked) delete l.clip_strength; changed(ed); },
    });
    const clip = h("input", {
      class: "text weight", type: "number", step: "0.05", value: l.clip_strength ?? l.strength ?? 1,
      title: "CLIP strength", disabled: ro || linked,
      oninput: (e) => { l.clip_strength = Number(e.target.value); changed(ed); },
    });
    const linkBox = h("input", {
      type: "checkbox", checked: linked, disabled: ro, title: "CLIP strength follows model strength",
      onchange: (e) => {
        clip.disabled = e.target.checked;
        if (e.target.checked) delete l.clip_strength;
        else l.clip_strength = l.strength ?? 1;
        changed(ed);
      },
    });
    const trig = h("input", {
      class: "text", value: l.trigger || "", placeholder: "trigger words", disabled: ro,
      oninput: (e) => { e.target.value ? (l.trigger = e.target.value) : delete l.trigger; changed(ed); },
    });
    box.append(h("div", { class: "lora-row" }, nameIn,
      h("span", { class: "muted small" }, "model"), str,
      h("label", { class: "link", title: "Link CLIP strength to model strength" }, linkBox, "🔗"),
      h("span", { class: "muted small" }, "clip"), clip, trig,
      ro ? null : h("button", {
        class: "btn small ghost", title: "Remove", onclick: () => { raw.loras.splice(i, 1); changed(ed, { rerender: true }); },
      }, "✕")));
  });
  if (!ro) {
    box.append(h("button", {
      class: "btn small", onclick: () => { raw.loras.push({ name: "", strength: 1 }); changed(ed, { rerender: true }); },
    }, "＋ LoRA"));
  }
  if (!document.getElementById("dl-loras")) document.body.append(h("datalist", { id: "dl-loras" }));
  return box;
}

let loraTimer;
function searchLoras(q) {
  clearTimeout(loraTimer);
  loraTimer = setTimeout(async () => {
    try {
      const { loras } = await api.loras(q);
      loraCache.set("last", loras);
      document.getElementById("dl-loras")?.replaceChildren(
        ...loras.map((l) => h("option", { value: l.name }, l.triggers.length ? l.triggers[0] : "")));
    } catch {
      // the picker just shows no suggestions
    }
  }, 200);
}

// -- raw JSON tab ----------------------------------------------------------------------------

function renderJson(ed) {
  const ta = h("textarea", {
    class: "text json", spellcheck: false, value: JSON.stringify(ed.draft, null, 2), disabled: ed.readonly,
    oninput: () => {
      try {
        ed.draft = JSON.parse(ta.value);
        err.textContent = "";
        changed(ed);
      } catch (e) {
        err.textContent = `Not valid JSON yet: ${e.message}`;
        ed.dirty = true;
        ed.dirtyEl.hidden = false;
      }
    },
  });
  const err = h("div", { class: "json-error" });
  append(ed.formEl, [h("section", { class: "ed-card" }, ta, err)]);
}

function switchTab(ed, tab) {
  if (tab === ed.tab) return;
  if (ed.tab === "json") {
    const err = ed.formEl.querySelector(".json-error")?.textContent;
    if (err) return toast("Fix the JSON first: the form can't show it while it doesn't parse.", "error", 6000);
    if (typeof ed.draft !== "object" || ed.draft === null || Array.isArray(ed.draft)) {
      return toast("The preset must be a JSON object.", "error");
    }
  }
  ed.tab = tab;
  render(ed);
}

// -- preview -------------------------------------------------------------------------------------

function previewName(ed) {
  return ed.isNew ? (ed.path && !ed.path.endsWith("/") ? ed.path : "untitled/new-preset") : ed.name;
}

function schedulePreview(ed, ms = 300) {
  clearTimeout(ed.previewTimer);
  ed.previewTimer = setTimeout(async () => {
    const tpl = ed.templateSel?.value || ed.preview?.template || "anima-mixed";
    try {
      const r = await api.render(previewName(ed), { data: ed.draft, template: tpl });
      ed.preview = { ...r, template: tpl };
      if (r.sections) {
        const before = JSON.stringify(ed.resolved);
        ed.resolved = r.sections;
        // refresh "inherited" placeholders without stealing focus from the field being typed in
        if (before !== JSON.stringify(r.sections)) refreshPlaceholders(ed);
      }
    } catch (e) {
      ed.preview = { problems: [e.message], template: tpl };
    }
    renderPreview(ed);
  }, ms);
}

function refreshPlaceholders(ed) {
  for (const card of ed.formEl.querySelectorAll(".ed-card.section")) {
    const sec = ed.sc.sections[[...ed.formEl.querySelectorAll(".ed-card.section")].indexOf(card)];
    const inherited = ed.resolved[sec.name] || {};
    card.querySelectorAll(".field-row").forEach((row, i) => {
      const f = sec.fields[i];
      const input = row.querySelector("input.text:not(.weight), textarea");
      if (input && inherited[f.name] && !input.value) input.placeholder = `↳ ${inherited[f.name]}`;
    });
  }
}

function renderPreview(ed) {
  const el = ed.previewEl;
  if (!el) return;
  const p = ed.preview;
  clear(el);
  ed.templateSel = h("select", { class: "text", onchange: () => schedulePreview(ed, 0) },
    ed.sc.templates.map((t) => h("option", { value: t, selected: t === (p?.template || "anima-mixed") }, t)));
  append(el, [
    h("div", { class: "row" }, h("h3", {}, "Live preview"), h("div", { class: "spacer" }), ed.templateSel),
    !p ? h("p", { class: "muted" }, "Rendering…") : null,
    p?.problems?.length ? h("div", { class: "error-box" }, h("strong", {}, "Won't load as it is:"), p.problems.map((x) => h("div", {}, x))) : null,
    p && !p.problems?.length ? [
      h("div", { class: "label" }, "Positive ", h("span", { class: "muted" }, `≈ ${p.tokens} tokens`)),
      h("pre", { class: "prompt" }, p.positive || "(empty)"),
      h("div", { class: "label" }, "Negative"),
      h("pre", { class: "prompt neg" }, p.negative || "(none)"),
      p.loras?.length ? [h("div", { class: "label" }, "LoRAs"), h("ul", { class: "loras" }, p.loras.map((l) => h("li", {},
        h("span", { class: l.status.startsWith("✗") ? "bad" : l.status.startsWith("⚠") ? "warn" : "ok" }, l.status.split(" ")[0]), " ",
        h("span", { class: "mono" }, l.name), " ", h("span", { class: "muted" }, `${l.strength}${l.trigger ? ` · “${l.trigger}”` : ""}`))))] : null,
      p.neg_conflicts?.length ? h("p", { class: "muted small" }, `Dropped from the negative (also in the positive): ${p.neg_conflicts.join(", ")}`) : null,
      h("details", {}, h("summary", {}, "Placeholder breakdown"),
        h("table", { class: "breakdown" }, p.breakdown.map(([ph, items]) =>
          h("tr", {}, h("td", { class: "mono" }, ph), h("td", {}, items.length ? items.join(", ") : h("span", { class: "muted" }, "(empty)")))))),
    ] : null,
  ]);
}

// -- saving ---------------------------------------------------------------------------------------

async function save(ed, { force = false } = {}) {
  if (ed.readonly) return;
  if (ed.tab === "json" && ed.formEl.querySelector(".json-error")?.textContent) {
    return toast("Fix the JSON before saving.", "error");
  }
  const name = ed.isNew ? ed.path : ed.name;
  if (!name || name.endsWith("/")) return toast("Give the preset a path first, e.g. characters/my-character", "error", 6000);
  for (const sec of Object.values(ed.draft.sections || {})) clean(sec);
  if (ed.draft.name === "") delete ed.draft.name; // the card falls back to the file name
  let etag = ed.etag;
  if (force) {
    try {
      etag = (await api.preset(name)).etag;
    } catch {
      etag = null; // deleted meanwhile: save creates it again
    }
  }
  try {
    const r = await api.save(name, ed.draft, ed.isNew && !force ? null : etag);
    Object.assign(ed, { etag: r.etag, dirty: false, isNew: false, name });
    ed.dirtyEl.hidden = true;
    toast(`Saved ${name}`, "ok");
    ed.app.editorSaved(name);
  } catch (e) {
    if (e.conflict) return conflictDialog(ed, e.message);
    toast(e.message, "error", 9000);
  }
}

function conflictDialog(ed, message) {
  dialog({
    title: "The file changed",
    body: h("div", { class: "form" },
      h("p", {}, message, "."),
      h("p", { class: "muted" }, "Something else wrote it meanwhile, for example the Save Preset node. Reload to see that version (your edits here are dropped), or overwrite it with yours.")),
    actions: [
      { label: "Cancel" },
      {
        label: "Reload theirs", onClick: async () => {
          ed.dirty = false;
          await ed.app.openEditor(ed.name || ed.path, { replace: true });
        },
      },
      { label: "Overwrite with mine", kind: "danger", onClick: () => save(ed, { force: true }) },
    ],
  });
}

function duplicateToEdit(ed) {
  const input = h("input", { class: "text", value: ed.name.replace(/^examples\//, ""), spellcheck: false });
  dialog({
    title: "Duplicate to edit",
    body: h("div", { class: "form" }, h("label", {}, "New path", input)),
    actions: [{ label: "Cancel" }, {
      label: "Duplicate", kind: "primary", onClick: async () => {
        try {
          const { name } = await api.duplicate(ed.name, input.value.trim(), "");
          await ed.app.reload();
          await ed.app.openEditor(name, { replace: true });
        } catch (e) {
          toast(e.message, "error", 7000);
          return false;
        }
      },
    }],
  });
}

function extractSection(ed, s) {
  const base = (ed.name || ed.path || "preset").split("/").pop();
  const folder = { outfit: "outfits", style: "styles", scene: "scenes", pose: "poses" }[s.name] || `${s.name}s`;
  const input = h("input", { class: "text", value: `${folder}/${base}`, spellcheck: false });
  dialog({
    title: `Save ${s.label} as its own preset`,
    body: h("div", { class: "form" },
      h("label", {}, "New preset path", input),
      h("p", { class: "muted" }, `Creates a preset holding just this ${s.name} section, and makes this preset reference it with $ref, so other presets can share or swap it.`)),
    actions: [{ label: "Cancel" }, {
      label: "Create", kind: "primary", onClick: async () => {
        const target = input.value.trim();
        const sec = structuredClone(ed.draft.sections[s.name]);
        const data = { kisekae: 1, name: `${ed.draft.name || base}: ${s.name}`, sections: { [s.name]: clean(sec) } };
        try {
          await api.save(target, data, null);
          ed.draft.sections[s.name] = { $ref: target };
          toast(`Created ${target}; ${s.label} now references it. Save this preset to keep the change.`, "ok", 7000);
          await ed.app.reload();
          changed(ed, { rerender: true });
        } catch (e) {
          toast(e.message, "error", 8000);
          return false;
        }
      },
    }],
  });
}

export function confirmLeave(ed) {
  return new Promise((resolve) => {
    if (!ed?.dirty) return resolve(true);
    dialog({
      title: "Unsaved changes",
      body: h("p", {}, "Leave the editor and drop your changes?"),
      actions: [
        { label: "Stay", onClick: () => resolve(false) },
        { label: "Drop changes", kind: "danger", onClick: () => resolve(true) },
      ],
      onClose: () => resolve(false),
    });
  });
}

export function editorKeys(ed, e) {
  if ((e.ctrlKey || e.metaKey) && e.key === "s") {
    e.preventDefault();
    save(ed);
  }
}
