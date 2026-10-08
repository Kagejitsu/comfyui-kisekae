// Tansu: page state and wiring. Views live in organizer.js (and editor.js later).

import { api } from "./api.js";
import { toast } from "./dom.js";
import { openDetail, renderFilters, renderGrid, renderTree } from "./organizer.js";

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
  blur: stored("tansu.blur", true),
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
  $("blur").textContent = state.blur ? "◌" : "◉";
  $("blur").title = state.blur ? "R-rated previews are blurred (click to show them)" : "R-rated previews are shown (click to blur)";
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
    document.querySelectorAll(".backdrop").forEach((b) => b.remove());
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
  state.blur = !state.blur;
  store("tansu.blur", state.blur);
  render();
});
document.addEventListener("keydown", (e) => {
  const typing = e.target.closest?.("input, textarea, select");
  if ((e.key === "/" && !typing) || (e.key === "f" && (e.ctrlKey || e.metaKey) && !document.querySelector(".backdrop"))) {
    e.preventDefault();
    $("search").focus();
    $("search").select();
  }
});
// Come back to the tab after saving from the graph: pick up the changes.
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible" && !document.querySelector(".backdrop")) app.reload();
});

app.reload();
