// Templates page (PLAN-tansu.md §8, phase 2): edit prompt layouts with a
// placeholder palette and a live preview against any preset.

import { api } from "./api.js";
import { append, clear, dialog, h, toast } from "./dom.js";

const ORIGIN = { shipped: "🔒 shipped", yours: "yours", override: "yours (replaces shipped)" };

export async function openTemplates(root, sc, state, { name }) {
  const page = { root, sc, state, list: [], name: name || "anima-mixed", text: "", dirty: false, timer: null };
  try {
    page.list = (await api.templates()).templates;
  } catch (e) {
    toast(e.message, "error", 8000);
  }
  select(page, page.list.some((t) => t.name === page.name) ? page.name : page.list[0]?.name);
  return page;
}

function current(page) {
  return page.list.find((t) => t.name === page.name);
}

function select(page, name) {
  page.name = name;
  page.text = current(page)?.text ?? "";
  page.dirty = false;
  history.replaceState(null, "", `#templates/${encodeURIComponent(name || "")}`);
  render(page);
}

function render(page) {
  clear(page.root);
  const t = current(page);
  const nav = h("nav", { class: "sidebar tool-nav", "aria-label": "Templates" },
    page.list.map((x) => h("button", {
      class: `tree-item ${x.name === page.name ? "active" : ""}`,
      onclick: async () => {
        if (page.dirty && !(await confirmDrop())) return;
        select(page, x.name);
      },
    }, h("span", { class: "tree-label" }, x.name), h("span", { class: "count" }, x.origin === "shipped" ? "🔒" : x.origin === "override" ? "✎" : ""))),
    h("div", { class: "tree-sep" }),
    h("button", { class: "tree-item", onclick: () => saveAs(page, "") }, "＋ New template"));

  page.dirtyEl = h("span", { class: "dirty-dot", hidden: !page.dirty }, "●");
  const ta = h("textarea", {
    class: "text template", spellcheck: false, value: page.text,
    oninput: (e) => {
      page.text = e.target.value;
      page.dirty = page.text !== (t?.text ?? "");
      page.dirtyEl.hidden = !page.dirty;
      preview(page);
    },
  });
  page.textarea = ta;
  const readonly = t?.origin === "shipped";
  const actions = [
    readonly
      ? h("button", { class: "btn primary", title: "Save your own version under the same name; the node dropdown then uses yours", onclick: () => save(page, page.name) }, "Save as my version")
      : h("button", { class: "btn primary", onclick: () => save(page, page.name) }, "Save", h("kbd", {}, "Ctrl+S")),
    h("button", { class: "btn", onclick: () => saveAs(page, `${page.name}-copy`) }, "Save as…"),
    t && t.origin !== "shipped" ? h("button", {
      class: "btn danger", title: t.origin === "override" ? "Delete your version; the shipped one comes back" : "Move to templates/.trash/",
      onclick: () => remove(page),
    }, t.origin === "override" ? "↺ Back to shipped" : "🗑 Delete") : null,
  ];

  page.previewEl = h("div", {});
  const presets = page.state.presets.filter((p) => !p.error);
  page.presetSel = h("select", { class: "text", onchange: () => preview(page, 0) },
    presets.map((p) => h("option", { value: p.name, selected: p.name === page.state.lastPreviewPreset }, p.title === p.name ? p.name : `${p.title} · ${p.name}`)));

  append(page.root, [h("div", { class: "layout" }, nav, h("main", { class: "tool-main template-main" },
    h("div", { class: "tool-head" }, h("h1", {}, page.name || "New template"), page.dirtyEl,
      h("span", { class: "muted" }, t ? ORIGIN[t.origin] : ""), h("div", { class: "spacer" }), actions),
    h("div", { class: "template-cols" },
      h("div", { class: "template-edit" },
        ta,
        palette(page),
        h("p", { class: "muted small" },
          "One template line = one prompt line. Empty placeholders and stray commas are removed. ",
          "A field placed on its own (e.g. {head.expression}) is left out of its section's {head}.")),
      h("aside", { class: "editor-preview" },
        h("div", { class: "row" }, h("h3", {}, "Preview with"), page.presetSel),
        page.previewEl)))),
  ]);
  preview(page, 0);
}

function palette(page) {
  const insert = (text) => {
    const ta = page.textarea;
    const [a, b] = [ta.selectionStart, ta.selectionEnd];
    ta.setRangeText(text, a, b, "end");
    ta.focus();
    ta.dispatchEvent(new Event("input"));
  };
  return h("div", { class: "palette" },
    h("div", { class: "muted small" }, "Click to insert · Shift+click a field to leave it out ({!section.field})"),
    h("div", { class: "palette-row" },
      h("button", { class: "chip", onclick: () => insert("{triggers}") }, "{triggers}"),
      page.sc.sections.map((s) => h("button", { class: "chip", onclick: () => insert(`{${s.name}}`) }, `{${s.name}}`))),
    h("details", {}, h("summary", {}, "Single fields"),
      page.sc.sections.map((s) => h("div", { class: "palette-row" },
        h("span", { class: "muted small sec" }, s.label),
        s.fields.map((f) => h("button", {
          class: "chip small", title: "Shift+click: {!…} leaves the field out",
          onclick: (e) => insert(`{${e.shiftKey ? "!" : ""}${s.name}.${f.name}}`),
        }, f.name))))));
}

function preview(page, ms = 300) {
  clearTimeout(page.timer);
  page.timer = setTimeout(async () => {
    const preset = page.presetSel?.value;
    if (!preset) return;
    page.state.lastPreviewPreset = preset;
    const el = page.previewEl;
    if (!page.text.trim()) {
      clear(el).append(h("p", { class: "muted" }, "The template is empty."));
      return;
    }
    try {
      const r = await api.render(preset, { template_text: page.text });
      clear(el);
      append(el, [
        h("div", { class: "label" }, "Positive ", h("span", { class: "muted" }, `≈ ${r.tokens} tokens`)),
        h("pre", { class: "prompt" }, r.positive || "(empty)"),
        h("details", {}, h("summary", {}, "Placeholder breakdown"),
          h("table", { class: "breakdown" }, r.breakdown.map(([ph, items]) =>
            h("tr", {}, h("td", { class: "mono" }, ph), h("td", {}, items.length ? items.join(", ") : h("span", { class: "muted" }, "(empty)")))))),
      ]);
    } catch (e) {
      clear(el).append(h("div", { class: "error-box" }, e.message));
    }
  }, ms);
}

async function save(page, name) {
  try {
    page.list = (await api.saveTemplate(name, page.text)).templates;
    toast(`Saved template ${name} (press R in ComfyUI to see it in the Prompt node)`, "ok", 5000);
    select(page, name);
  } catch (e) {
    toast(e.message, "error", 8000);
  }
}

function saveAs(page, suggestion) {
  const input = h("input", { class: "text", value: suggestion, spellcheck: false, placeholder: "anima-portrait" });
  const fresh = !suggestion;
  dialog({
    title: fresh ? "New template" : "Save template as",
    body: h("div", { class: "form" }, h("label", {}, "Name", input),
      h("p", { class: "muted" }, "Letters, digits, - _ and . only. A shipped template's name makes yours replace it.")),
    actions: [{ label: "Cancel" }, {
      label: fresh ? "Create" : "Save", kind: "primary", onClick: async () => {
        const name = input.value.trim();
        if (page.list.some((t) => t.name === name && t.origin !== "shipped")) {
          toast(`${name} already exists; open it and save there`, "error", 6000);
          return false;
        }
        if (fresh) page.text = "{style.quality}, {scene.composition}\n{triggers}, {identity}, {hair}, {head}, {body}\n{outfit}\n{style}, {pose}\n{scene}";
        await save(page, name);
      },
    }],
  });
}

function remove(page) {
  const t = current(page);
  dialog({
    title: t.origin === "override" ? `Delete your version of ${t.name}?` : `Delete ${t.name}?`,
    body: h("p", {}, t.origin === "override"
      ? "The shipped template comes back. Your version moves to templates/.trash/."
      : "It moves to templates/.trash/. Prompt nodes that use it will need another template."),
    actions: [{ label: "Cancel" }, {
      label: "Delete", kind: "danger", onClick: async () => {
        try {
          page.list = (await api.trashTemplate(t.name)).templates;
          toast(`Deleted ${t.name}`, "ok");
          select(page, page.list.some((x) => x.name === t.name) ? t.name : page.list[0]?.name);
        } catch (e) {
          toast(e.message, "error", 8000);
          return false;
        }
      },
    }],
  });
}

function confirmDrop() {
  return new Promise((resolve) => dialog({
    title: "Unsaved changes",
    body: h("p", {}, "Drop your changes to this template?"),
    actions: [{ label: "Stay", onClick: () => resolve(false) }, { label: "Drop changes", kind: "danger", onClick: () => resolve(true) }],
    onClose: () => resolve(false),
  }));
}

export function templateKeys(page, e) {
  if ((e.ctrlKey || e.metaKey) && e.key === "s") {
    e.preventDefault();
    if (current(page)?.origin !== "shipped") save(page, page.name);
  }
}
