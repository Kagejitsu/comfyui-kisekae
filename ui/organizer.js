// Organizer views: folder tree, filter chips, card grid, detail panel, dialogs.
// Pure rendering over the state object owned by app.js; actions call back into it.

import { api } from "./api.js";
import { append, clear, closeAllDialogs, copyText, dialog, h, toast } from "./dom.js";
import { acceptPictureDrops, pictureDialog } from "./picture.js";

const SECTION_ABBR = {
  identity: "ID", head: "HEAD", hair: "HAIR", body: "BODY",
  outfit: "OUTFIT", style: "STYLE", pose: "POSE", scene: "SCENE",
};
const KINDS = {
  character: { label: "Characters", icon: "👤" },
  outfit: { label: "Outfits", icon: "👘" },
  scene: { label: "Scenes & styles", icon: "🎬" },
  other: { label: "Other", icon: "🧩" },
  broken: { label: "Broken", icon: "⚠" },
};
const EXAMPLES = "examples/";
const NSFW_BLUR_FROM = 4; // Civitai levels: 1 PG, 2 PG-13, 4 R, 8 X, 16 XXX

// R-18: marked in the preset, or a LoRA preview LoRA Manager rates R or above.
export function isAdult(p) {
  return p.nsfw || (p.picture?.nsfw ?? 0) >= NSFW_BLUR_FROM;
}

export function kindOf(p) {
  if (p.error) return "broken";
  const s = new Set(p.sections);
  if (s.has("identity")) return "character";
  if (s.size && [...s].every((x) => x === "outfit")) return "outfit";
  if (s.has("pose") || s.has("scene") || s.has("style")) return "scene";
  return "other";
}

// -- filtering -------------------------------------------------------------------

export function filtered(state) {
  const { folder, q, tags, kinds, sort } = state.filter;
  const words = q.toLowerCase().split(/\s+/).filter(Boolean);
  const out = state.presets.filter((p) => {
    if (state.nsfwMode === "hide" && isAdult(p)) return false;
    if (folder && folder !== "trash") {
      const prefix = folder.endsWith("/") ? folder : folder + "/";
      if (folder === "user:") {
        if (p.readonly) return false;
      } else if (!p.name.startsWith(prefix)) return false;
    }
    if (kinds.size && !kinds.has(kindOf(p))) return false;
    for (const [tag, mode] of tags) {
      if (mode > 0 && !p.tags.includes(tag)) return false;
      if (mode < 0 && p.tags.includes(tag)) return false;
    }
    const hay = `${p.name} ${p.search} ${p.title}`.toLowerCase();
    return words.every((w) => hay.includes(w));
  });
  const by = {
    name: (a, b) => a.name.localeCompare(b.name),
    title: (a, b) => a.title.localeCompare(b.title) || a.name.localeCompare(b.name),
    mtime: (a, b) => b.mtime - a.mtime,
  }[sort] || ((a, b) => a.name.localeCompare(b.name));
  return out.sort((a, b) => (a.readonly - b.readonly) || by(a, b)); // your presets before the examples
}

// -- folder tree -------------------------------------------------------------------

function buildTree(names) {
  const root = { children: new Map(), count: 0 };
  for (const name of names) {
    const parts = name.split("/").slice(0, -1);
    let node = root;
    root.count++;
    let path = "";
    for (const part of parts) {
      path += part + "/";
      if (!node.children.has(part)) node.children.set(part, { path, children: new Map(), count: 0 });
      node = node.children.get(part);
      node.count++;
    }
  }
  return root;
}

export function renderTree(el, state, app) {
  const user = state.presets.filter((p) => !p.readonly).map((p) => p.name);
  const examples = state.presets.filter((p) => p.readonly).map((p) => p.name.slice(EXAMPLES.length));
  const item = (label, folder, count, depth, extra = "") =>
    h("button", {
      class: `tree-item ${extra} ${state.filter.folder === folder ? "active" : ""}`,
      style: { paddingLeft: `${0.75 + depth * 0.9}rem` },
      onclick: () => app.setFolder(folder),
    }, h("span", { class: "tree-label" }, label), count != null ? h("span", { class: "count" }, count) : null);
  const walk = (node, prefix, depth) => [...node.children.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .flatMap(([part, child]) => [
      item(`📁 ${part}`, prefix + child.path, child.count, depth),
      ...walk(child, prefix, depth + 1),
    ]);
  clear(el);
  append(el, [
    item("🗂 All presets", null, state.presets.length, 0, "root"),
    item("🏠 My presets", "user:", user.length, 0, "root"),
    ...walk(buildTree(user), "", 1),
    item("📦 Examples", EXAMPLES, examples.length, 0, "root dim"),
    ...walk(buildTree(examples), EXAMPLES, 1).map((b) => (b.classList.add("dim"), b)),
    h("div", { class: "tree-sep" }),
    item("🗑 Trash", "trash", state.trashCount, 0, "root"),
  ]);
}

// -- filter chips -------------------------------------------------------------------

export function renderFilters(el, state, app) {
  clear(el);
  const present = new Set(state.presets.map(kindOf));
  const kindChips = Object.entries(KINDS).filter(([k]) => present.has(k)).map(([k, { label, icon }]) =>
    h("button", {
      class: `chip ${state.filter.kinds.has(k) ? "on" : ""} ${k === "broken" ? "warn" : ""}`,
      onclick: () => app.toggleKind(k),
      title: `Show ${label.toLowerCase()} only (click again to clear)`,
    }, `${icon} ${label}`));
  const tagChips = Object.entries(state.tags).map(([tag, n]) => {
    const mode = state.filter.tags.get(tag) || 0;
    return h("button", {
      class: `chip tag ${mode > 0 ? "on" : mode < 0 ? "off" : ""}`,
      onclick: () => app.cycleTag(tag),
      title: mode > 0 ? "Required: click to exclude" : mode < 0 ? "Excluded: click to clear" : "Click to require this tag",
    }, mode < 0 ? "− " : mode > 0 ? "＋ " : "# ", tag, h("span", { class: "count" }, n));
  });
  append(el, [
    h("div", { class: "chip-row" }, kindChips),
    tagChips.length ? h("div", { class: "chip-row tags" }, tagChips) : null,
  ]);
}

// -- cards ---------------------------------------------------------------------------

function picture(p, state, app, { thumb = false } = {}) {
  const pic = p.picture;
  if (!pic) {
    return h("div", { class: `pic placeholder kind-${kindOf(p)}` },
      h("span", { class: "big" }, KINDS[kindOf(p)].icon));
  }
  const src = api.pictureUrl(p.name, pic.version, { thumb });
  const media = pic.video
    ? h("video", { src, muted: true, loop: true, playsInline: true, preload: "metadata" })
    : h("img", { src, loading: "lazy", alt: "" });
  const blurred = state.nsfwMode === "blur" && isAdult(p) && !state.revealed.has(p.name);
  const box = h("div", { class: `pic ${blurred ? "blurred" : ""}` }, media);
  if (blurred) {
    box.append(h("div", { class: "nsfw-cover" },
      h("span", {}, p.nsfw ? "R-18" : "R-rated preview"),
      h("button", {
        class: "btn small", onclick: (e) => {
          e.stopPropagation();
          app.reveal(p.name);
        },
      }, "Show")));
  }
  if (pic.video) {
    box.addEventListener("mouseenter", () => media.play().catch(() => {}));
    box.addEventListener("mouseleave", () => media.pause());
  }
  return box;
}

function card(p, index, state, app) {
  const loras = p.loras.length;
  const el = h("article", {
    class: `card ${p.error ? "broken" : ""} ${p.readonly ? "readonly" : ""}`, tabindex: 0,
    onclick: () => app.openDetail(index),
    ondblclick: () => { closeAllDialogs(); app.openEditor(p.name); },
    onkeydown: (e) => { if (e.key === "Enter") app.openDetail(index); },
  },
  picture(p, state, app, { thumb: true }),
  h("div", { class: "badges" },
    p.sections.map((s) => h("span", { class: "badge" }, SECTION_ABBR[s] || s)),
    p.nsfw ? h("span", { class: "badge adult", title: "Marked R-18" }, "🔞") : null,
    p.error ? h("span", { class: "badge warn", title: p.error }, "⚠ broken") : null),
  h("div", { class: "card-info" },
    h("div", { class: "title" }, p.title),
    h("div", { class: "path" }, p.readonly ? "🔒 " : "", p.name),
    h("div", { class: "card-foot" },
      p.tags.slice(0, 4).map((t) => h("span", { class: "pill" }, t)),
      p.tags.length > 4 ? h("span", { class: "pill" }, `+${p.tags.length - 4}`) : null,
      loras ? h("span", { class: "lora-count", title: p.loras.map((l) => l.name).join("\n") }, `◆ ${loras} LoRA${loras > 1 ? "s" : ""}`) : null)));
  if (!p.readonly) acceptPictureDrops(el, p, () => app.reload());
  return el;
}

export function renderGrid(el, statusEl, state, app) {
  clear(el);
  if (state.filter.folder === "trash") {
    statusEl.textContent = "";
    return renderTrash(el, app);
  }
  const list = filtered(state);
  state.visible = list;
  const hidden = state.nsfwMode === "hide" ? state.presets.filter(isAdult).length : 0;
  statusEl.textContent = (list.length === state.presets.length
    ? `${list.length} presets`
    : `${list.length} of ${state.presets.length} presets`) + (hidden ? ` · ${hidden} R-18 hidden` : "");
  if (!list.length) {
    el.append(h("div", { class: "empty" },
      state.presets.length ? "Nothing matches these filters." : "No presets yet. Save one from the graph with 👘 Save Preset."));
    return;
  }
  append(el, list.map((p, i) => card(p, i, state, app)));
}

// -- trash -----------------------------------------------------------------------------

async function renderTrash(el, app) {
  el.append(h("div", { class: "empty" }, "Loading trash…"));
  let entries;
  try {
    ({ entries } = await api.trashList());
  } catch (e) {
    clear(el).append(h("div", { class: "empty" }, e.message));
    return;
  }
  clear(el);
  if (!entries.length) {
    el.append(h("div", { class: "empty" }, "The trash is empty. Deleted presets land here and can be restored."));
    return;
  }
  const when = (id) => id.replace(/^(\d{4})(\d\d)(\d\d)-(\d\d)(\d\d)(\d\d).*/, "$1-$2-$3 $4:$5:$6");
  el.append(h("div", { class: "trash-list" },
    h("p", { class: "muted" }, `Trashed presets live in presets/.trash/ and never show in node dropdowns.`),
    entries.map((t) => h("div", { class: "trash-row" },
      h("span", { class: "title" }, t.name),
      h("span", { class: "muted" }, `deleted ${when(t.id)}`),
      h("button", {
        class: "btn small", onclick: async () => {
          try {
            await api.restore(t.id, t.name);
            toast(`Restored ${t.name}`, "ok");
            await app.reload();
          } catch (e) {
            toast(e.message, "error", 7000);
          }
        },
      }, "Restore")))));
}

// -- detail panel ------------------------------------------------------------------------

function link(name, app) {
  return h("button", { class: "linkish", onclick: () => app.openByName(name) }, name);
}

export function openDetail(state, index, app) {
  const list = state.visible;
  let i = index;
  let close;
  const show = () => {
    const p = list[i];
    const body = detailBody(p, state, app, () => close());
    const nav = h("div", { class: "detail-nav" },
      h("button", { class: "btn icon", disabled: i === 0, title: "Previous (←)", onclick: () => go(-1) }, "‹"),
      h("span", { class: "muted" }, `${i + 1} / ${list.length}`),
      h("button", { class: "btn icon", disabled: i === list.length - 1, title: "Next (→)", onclick: () => go(1) }, "›"));
    const wrap = h("div", {}, nav, body);
    if (close) {
      close.box.querySelector(".dialog-head h2").textContent = p.title;
      close.box.querySelector(".dialog-body").replaceChildren(wrap);
    } else {
      close = dialog({ title: p.title, body: wrap, wide: true, onClose: () => document.removeEventListener("keydown", onKey) });
      close.box.classList.add("detail");
    }
  };
  const go = (d) => {
    const n = i + d;
    if (n >= 0 && n < list.length) { i = n; show(); }
  };
  const onKey = (e) => {
    if (e.target.closest?.("input, textarea")) return;
    if ([...document.querySelectorAll(".backdrop")].at(-1) !== close.box.parentElement) return;
    if (e.key === "ArrowLeft") go(-1);
    if (e.key === "ArrowRight") go(1);
  };
  show();
  document.addEventListener("keydown", onKey);
}

function detailBody(p, state, app, close) {
  const usedBy = state.used_by[p.name] || [];
  const promptBox = h("div", { class: "prompt-box muted" }, "Rendering…");
  if (!p.error) {
    api.render(p.name).then((r) => {
      clear(promptBox).classList.remove("muted");
      append(promptBox, [
        h("div", { class: "label" }, "Positive ", h("span", { class: "muted" }, `≈ ${r.tokens} tokens · anima-mixed`)),
        h("pre", { class: "prompt" }, r.positive || "(empty)"),
        h("div", { class: "label" }, "Negative"),
        h("pre", { class: "prompt neg" }, r.negative || "(none)"),
        r.loras.length ? [h("div", { class: "label" }, "LoRAs"),
          h("ul", { class: "loras" }, r.loras.map((l) => h("li", {},
            h("span", { class: l.status.startsWith("✗") ? "bad" : l.status.startsWith("⚠") ? "warn" : "ok" }, l.status.split(" ")[0]), " ",
            h("span", { class: "mono" }, l.name), " ",
            h("span", { class: "muted" }, `${l.strength}${l.clip_strength !== l.strength ? ` / ${l.clip_strength}` : ""}${l.trigger ? ` · “${l.trigger}”` : ""}`))))] : null,
      ]);
    }).catch((e) => { promptBox.textContent = e.message; });
  } else {
    promptBox.remove();
  }

  const afterPicture = async () => {
    close();
    await app.reload();
    app.openByName(p.name);
  };
  const pic = h("div", { class: "detail-pic" }, picture(p, state, app));
  if (!p.readonly) {
    pic.classList.add("settable");
    pic.title = "Click to change the picture, or drop an image here";
    pic.addEventListener("click", (e) => {
      if (!e.target.closest("button")) pictureDialog(p, { onDone: afterPicture }); // not the blur's Show
    });
    acceptPictureDrops(pic, p, afterPicture);
  }

  const actions = h("div", { class: "detail-actions" },
    h("button", { class: "btn primary", onclick: () => { close(); app.openEditor(p.name); } }, p.readonly ? "👁 View" : "✎ Edit"),
    h("button", {
      class: "btn", disabled: p.readonly, title: p.readonly ? "Examples are read-only: duplicate first" : "Upload, drop or paste a picture, or pick a recent generation",
      onclick: () => pictureDialog(p, { onDone: afterPicture }),
    }, "🖼 Picture…"),
    h("button", { class: "btn", onclick: () => duplicateDialog(p, app, close) }, "⧉ Duplicate"),
    h("button", { class: "btn", disabled: p.readonly, title: p.readonly ? "Examples are read-only: duplicate first" : "", onclick: () => renameDialog(p, app, close) }, "↦ Rename / move"),
    h("button", { class: "btn danger", disabled: p.readonly, title: p.readonly ? "Examples are read-only" : "", onclick: () => deleteDialog(p, state, app, close) }, "🗑 Delete"),
    h("button", { class: "btn ghost", onclick: () => copyText(p.name).then(() => toast(`Copied ${p.name}`)) }, "⧉ Copy name"),
    h("button", {
      class: `btn ${p.nsfw ? "on-adult" : ""}`, disabled: p.readonly,
      title: p.readonly ? "Examples are read-only" : p.nsfw ? "Marked R-18: click to unmark" : "Mark this preset R-18",
      onclick: () => toggleAdult(p, app, close),
    }, p.nsfw ? "🔞 R-18: on" : "🔞 R-18: off"));

  return h("div", { class: "detail-grid" },
    pic,
    h("div", { class: "detail-main" },
      h("div", { class: "path mono" }, p.readonly ? "🔒 " : "", p.name),
      actions,
      p.description ? h("p", { class: "desc" }, p.description) : null,
      p.tags.length ? h("div", { class: "card-foot" }, p.tags.map((t) => h("span", { class: "pill" }, t))) : null,
      p.error ? h("pre", { class: "error-box" }, p.error) : null,
      h("div", { class: "badges static" }, p.sections.map((s) => h("span", { class: "badge" }, SECTION_ABBR[s] || s))),
      promptBox,
      h("div", { class: "refs" },
        h("div", {}, h("div", { class: "label" }, "Uses"),
          p.refs.length ? p.refs.map((r) => link(r, app)) : h("span", { class: "muted" }, "nothing")),
        h("div", {}, h("div", { class: "label" }, "Used by"),
          usedBy.length ? usedBy.map((r) => link(r, app)) : h("span", { class: "muted" }, "nothing")))));
}

async function toggleAdult(p, app, closeDetail) {
  try {
    const { data, etag } = await api.preset(p.name);
    if (p.nsfw) delete data.nsfw;
    else data.nsfw = true;
    await api.save(p.name, data, etag);
    toast(`${p.name} ${p.nsfw ? "is no longer marked R-18" : "marked R-18"}`, "ok");
    closeDetail();
    await app.reload();
    app.openByName(p.name);
  } catch (e) {
    toast(e.message, "error", 7000);
  }
}

// -- dialogs --------------------------------------------------------------------------------

function nameInput(value) {
  return h("input", { class: "text", value, spellcheck: false, autocomplete: "off" });
}

function duplicateDialog(p, app, closeDetail) {
  const base = p.readonly ? p.name.slice(EXAMPLES.length) : `${p.name}-copy`;
  const input = nameInput(base);
  const title = nameInput(p.readonly ? p.title : `${p.title} (copy)`);
  dialog({
    title: "Duplicate preset",
    body: h("div", { class: "form" },
      h("label", {}, "New path", input), h("label", {}, "Display name", title),
      h("p", { class: "muted" }, "References inside the copy keep pointing where they did.")),
    actions: [{ label: "Cancel" }, {
      label: "Duplicate", kind: "primary", onClick: async () => {
        try {
          const { name } = await api.duplicate(p.name, input.value.trim(), title.value.trim());
          toast(`Created ${name}`, "ok");
          closeDetail();
          await app.reload();
          app.openByName(name);
        } catch (e) {
          toast(e.message, "error", 7000);
          return false;
        }
      },
    }],
  });
}

function renameDialog(p, app, closeDetail) {
  const input = nameInput(p.name);
  const preview = h("div", { class: "muted" }, "Press Check to see which presets will be updated.");
  let checked = null;
  const check = async () => {
    const to = input.value.trim();
    try {
      const { changed } = await api.rename(p.name, to, true);
      checked = to;
      clear(preview).classList.remove("muted");
      append(preview, changed.length
        ? [h("p", {}, changed.length > 1
          ? `${changed.length} presets reference ${p.name} and will be updated:`
          : `1 preset references ${p.name} and will be updated:`),
          h("ul", { class: "mono" }, changed.map((n) => h("li", {}, n)))]
        : h("p", {}, "No other preset references it."));
    } catch (e) {
      checked = null;
      preview.textContent = e.message;
    }
    return false;
  };
  input.addEventListener("input", () => { checked = null; });
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") check(); });
  dialog({
    title: "Rename / move preset",
    body: h("div", { class: "form" }, h("label", {}, "New path", input), preview),
    actions: [{ label: "Cancel" }, { label: "Check", onClick: check }, {
      label: "Rename", kind: "primary", onClick: async () => {
        const to = input.value.trim();
        if (checked !== to) {
          await check();
          if (checked !== to) return false;
          toast("Review the list, then press Rename again.");
          return false;
        }
        try {
          const { changed } = await api.rename(p.name, to, false);
          toast(`Renamed to ${to}${changed.length ? `; updated ${changed.length} reference${changed.length > 1 ? "s" : ""}` : ""}`, "ok", 6000);
          closeDetail();
          await app.reload();
          app.openByName(to);
        } catch (e) {
          toast(e.message, "error", 7000);
          return false;
        }
      },
    }],
  });
}

function deleteDialog(p, state, app, closeDetail) {
  const usedBy = state.used_by[p.name] || [];
  dialog({
    title: `Delete ${p.name}?`,
    body: h("div", { class: "form" },
      usedBy.length
        ? [h("p", { class: "warn-text" }, usedBy.length > 1
          ? `⚠ ${usedBy.length} presets still reference it and will show as broken until you restore it or change them:`
          : "⚠ 1 preset still references it and will show as broken until you restore it or change it:"),
          h("ul", { class: "mono" }, usedBy.map((n) => h("li", {}, n)))]
        : null,
      h("p", {}, "It moves to the Trash (presets/.trash/), where you can restore it.")),
    actions: [{ label: "Cancel" }, {
      label: "Move to Trash", kind: "danger", onClick: async () => {
        try {
          await api.trash(p.name);
          toast(`Moved ${p.name} to the Trash`, "ok");
          closeDetail();
          await app.reload();
        } catch (e) {
          toast(e.message, "error", 7000);
          return false;
        }
      },
    }],
  });
}
