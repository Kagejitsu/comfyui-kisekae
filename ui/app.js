// Tansu: page state and wiring. Views live in organizer.js (and editor.js later).

import { api } from "./api.js";
import { closeAllDialogs, dialog, h, toast } from "./dom.js";
import { confirmLeave, editorKeys, openEditor, schema } from "./editor.js";
import { openDetail, renderFilters, renderGrid, renderTree } from "./organizer.js";
import { openTemplates, templateKeys } from "./templates.js";
import { openVocab } from "./vocab.js";

const $ = (id) => document.getElementById(id);

function stored(key, fallback) {
  try {
    const v = localStorage.getItem(key);
    return v === null ? fallback : JSON.parse(v);
  } catch {
    return fallback;
  }
}

function store(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // private window or blocked storage: the setting just isn't remembered
  }
}

const state = {
  presets: [],
  used_by: {},
  tags: {},
  trashCount: 0,
  visible: [],
  revealed: new Set(), // NSFW previews shown this session
  // R-18 cards: "show", "blur" (default) or "hide". Older pages stored a blur on/off boolean.
  nsfwMode: stored("tansu.nsfw", stored("tansu.blur", true) ? "blur" : "show"),
  filter: {
    folder: stored("tansu.folder", null),
    q: "",
    tags: new Map(), // tag -> 1 (required) | -1 (excluded)
    kinds: new Set(),
    sort: stored("tansu.sort", "name"),
  },
};

function render() {
  renderTree($("tree"), state, app);
  renderFilters($("filters"), state, app);
  renderGrid($("grid"), $("status"), state, app);
  $("blur").textContent = { show: "🔞 Show", blur: "🔞 Blur", hide: "🔞 Hide" }[state.nsfwMode];
  $("blur").title = {
    show: "R-18 cards are shown. Click to blur them",
    blur: "R-18 cards are blurred. Click to hide them",
    hide: "R-18 cards are hidden. Click to show them",
  }[state.nsfwMode];
}

let editor = null; // the open preset editor, if any
let tool = null; // the open Dropdowns or Templates page, if any
let lastHash = location.hash;

const active = () => editor || tool; // whatever may hold unsaved changes

function showView(view) {
  document.body.dataset.view = view; // presets | editor | dropdowns | templates
  document.body.classList.toggle("editing", view !== "presets");
  $("editor").hidden = view !== "editor";
  $("tool").hidden = view !== "dropdowns" && view !== "templates";
  $("organizer").hidden = view !== "presets";
  for (const a of document.querySelectorAll(".views a")) {
    a.classList.toggle("on", a.dataset.view === (view === "editor" ? "presets" : view));
  }
  lastHash = location.hash;
}

async function showEditor(name, folder) {
  tool = null;
  showView("editor");
  editor = await openEditor(app, state, { name, folder });
  document.title = `${name || "New preset"} · Tansu`;
}

async function showTool(kind, args) {
  editor = null;
  showView(kind);
  const sc = await schema();
  if (kind === "dropdowns") {
    tool = await openVocab($("tool"), sc, { section: args[0], field: args[1] });
    document.title = "Dropdowns · Tansu";
  } else {
    tool = await openTemplates($("tool"), sc, state, { name: args[0] });
    tool.kind = "templates";
    document.title = "Templates · Tansu";
  }
}

function showOrganizer() {
  editor = null;
  tool = null;
  showView("presets");
  document.title = "Tansu · Kisekae presets";
}

// #edit/<name>, #new[/<folder>], #dropdowns[/<section>/<field>], #templates[/<name>];
// anything else is the organizer.
async function route() {
  const m = location.hash.match(/^#(edit|new|dropdowns|templates)(?:\/(.*))?$/);
  if (!m) return showOrganizer();
  const args = (m[2] || "").split("/").map(decodeURIComponent);
  if (m[1] === "edit") return showEditor(decodeURIComponent(m[2] || ""), "");
  if (m[1] === "new") return showEditor(null, decodeURIComponent(m[2] || ""));
  return showTool(m[1], args);
}

const app = {
  async reload() {
    try {
      const data = await api.library();
      state.presets = data.presets;
      state.used_by = data.used_by;
      state.tags = data.tags;
      state.trashCount = data.trash;
      for (const tag of [...state.filter.tags.keys()]) {
        if (!(tag in state.tags)) state.filter.tags.delete(tag);
      }
      // a remembered folder that has since been emptied, renamed or deleted
      const f = state.filter.folder;
      if (f && !["user:", "trash", "examples/"].includes(f) && !state.presets.some((p) => p.name.startsWith(f))) {
        app.setFolder(null);
      }
    } catch (e) {
      toast(`Could not load the library: ${e.message}`, "error", 8000);
    }
    render();
  },
  setFolder(folder) {
    state.filter.folder = folder;
    store("tansu.folder", folder);
    render();
  },
  toggleKind(kind) {
    const k = state.filter.kinds;
    k.has(kind) ? k.delete(kind) : k.add(kind);
    render();
  },
  cycleTag(tag) {
    const m = state.filter.tags;
    const next = { 0: 1, 1: -1, "-1": 0 }[m.get(tag) || 0];
    next ? m.set(tag, next) : m.delete(tag);
    render();
  },
  reveal(name) {
    state.revealed.add(name);
    render();
  },
  openDetail(index) {
    openDetail(state, index, app);
  },
  async openEditor(name, { replace = false, folder = "" } = {}) {
    if (!replace && editor && !(await confirmLeave(editor))) return;
    closeAllDialogs();
    history.pushState(null, "", name ? `#edit/${encodeURIComponent(name)}` : `#new${folder ? `/${encodeURIComponent(folder)}` : ""}`);
    await showEditor(name, folder);
  },
  async closeEditor(force = false) {
    if (!force && !(await confirmLeave(editor))) return;
    history.pushState(null, "", location.pathname);
    showOrganizer();
    await app.reload();
  },
  editorSaved(name) {
    history.replaceState(null, "", `#edit/${encodeURIComponent(name)}`);
    lastHash = location.hash;
    document.title = `${name} · Tansu`;
    app.reload(); // keep the organizer and the editor's preset pickers current
  },
  openByName(name) {
    let i = state.visible.findIndex((p) => p.name === name);
    if (i < 0) {
      // not in the current filter: clear filters so it can be shown
      state.filter = { ...state.filter, folder: null, q: "", tags: new Map(), kinds: new Set() };
      $("search").value = "";
      render();
      i = state.visible.findIndex((p) => p.name === name);
    }
    if (i < 0) return toast(`${name} is not in the library`, "error");
    closeAllDialogs();
    openDetail(state, i, app);
  },
};

// -- wiring ----------------------------------------------------------------------

let searchTimer;
$("search").addEventListener("input", (e) => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    state.filter.q = e.target.value;
    renderGrid($("grid"), $("status"), state, app);
  }, 120);
});
$("sort").value = state.filter.sort;
$("sort").addEventListener("change", (e) => {
  state.filter.sort = e.target.value;
  store("tansu.sort", e.target.value);
  render();
});
$("refresh").addEventListener("click", () => app.reload().then(() => toast("Library reloaded")));
$("theme").addEventListener("click", () => {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try {
    localStorage.setItem("tansu.theme", next);
  } catch {
    // not remembered
  }
});
$("blur").addEventListener("click", () => {
  state.nsfwMode = { show: "blur", blur: "hide", hide: "show" }[state.nsfwMode];
  store("tansu.nsfw", state.nsfwMode);
  render();
});
function showHelp() {
  const keys = [
    ["/", "or Ctrl+F", "search"],
    ["Enter", "on a card", "open its details"],
    ["Double-click", "a card", "open it in the editor"],
    ["← / →", "in details", "previous / next card"],
    ["Esc", "", "close the top dialog"],
    ["Ctrl+S", "in the editor", "save"],
    ["?", "", "this help"],
  ];
  dialog({
    title: "Shortcuts & tips",
    body: h("div", { class: "form" },
      h("table", { class: "keys" }, keys.map(([k, where, what]) =>
        h("tr", {}, h("td", {}, h("kbd", {}, k)), h("td", { class: "muted" }, where), h("td", {}, what)))),
      h("p", { class: "muted" }, "Tag chips cycle: click to require the tag, again to exclude it, again to clear."),
      h("p", { class: "muted" }, "🔞 cycles R-18 cards between blurred, hidden and shown. Mark a preset R-18 in its details or in the editor."),
      h("p", { class: "muted" }, "Drop an image on a card, or use 🖼 Picture… in its details, to give a preset a picture."),
      h("p", { class: "muted" }, "Presets live in ComfyUI/user/default/kisekae/presets/. Press R in ComfyUI after changes here to refresh the node dropdowns.")),
    actions: [{ label: "Close" }],
  });
}

$("help").addEventListener("click", showHelp);
$("new").addEventListener("click", () => {
  const f = state.filter.folder;
  app.openEditor(null, { folder: f && f !== "user:" && f !== "trash" && !f.startsWith("examples/") ? f : "" });
});
window.addEventListener("hashchange", async () => {
  if (active()?.dirty && !(await confirmLeave(active()))) {
    history.pushState(null, "", lastHash || location.pathname); // stay in the editor
    return;
  }
  route();
});
window.addEventListener("beforeunload", (e) => {
  if (active()?.dirty) e.preventDefault();
});
document.addEventListener("keydown", (e) => {
  if (editor) return editorKeys(editor, e);
  if (tool?.kind === "templates") return templateKeys(tool, e);
  if (tool) return;
  const typing = e.target.closest?.("input, textarea, select");
  if (e.key === "?" && !typing && !document.querySelector(".backdrop")) return showHelp();
  if ((e.key === "/" && !typing) || (e.key === "f" && (e.ctrlKey || e.metaKey) && !document.querySelector(".backdrop"))) {
    e.preventDefault();
    $("search").focus();
    $("search").select();
  }
});
// Come back to the tab after saving from the graph: pick up the changes.
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible" && !active() && !document.querySelector(".backdrop")) app.reload();
});

app.reload().then(route);
