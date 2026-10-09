// "Set picture" dialog: upload, drop or paste an image, or pick one of ComfyUI's
// recent generations. The server keeps the replaced picture in presets/.trash/.

import { api } from "./api.js";
import { append, clear, dialog, h, toast } from "./dom.js";

const TYPES = ["image/png", "image/jpeg", "image/webp"];
const SOURCE = {
  own: "Current picture",
  parent: "Current: inherited from the preset it extends",
  lora: "Current: the LoRA's preview",
};

function ago(seconds) {
  const s = Math.max(0, Date.now() / 1000 - seconds);
  if (s < 90) return "just now";
  if (s < 5400) return `${Math.round(s / 60)} min ago`;
  if (s < 129600) return `${Math.round(s / 3600)} h ago`;
  return new Date(seconds * 1000).toLocaleDateString();
}

function okType(file) {
  return !file.type || TYPES.includes(file.type); // the server checks the bytes either way
}

// A dropped image dragged from a web page arrives as a URL, not a file. From the
// ComfyUI tab (its queue and gallery use /view?…) it's same-origin, so fetch it.
async function droppedFile(dt) {
  if (dt.files.length) return dt.files[0];
  const url = (dt.getData("text/uri-list") || dt.getData("text/plain") || "").split("\n")[0].trim();
  if (!url) return null;
  let u;
  try {
    u = new URL(url, location.href);
  } catch {
    return null;
  }
  if (u.origin !== location.origin) {
    throw new Error("Images from other sites can't be dropped here; save it first, then drop the file");
  }
  const res = await fetch(u);
  if (!res.ok) throw new Error(`Could not fetch the dropped image (${res.status})`);
  const blob = await res.blob();
  return new File([blob], u.searchParams.get("filename") || "dropped image", { type: blob.type });
}

/**
 * Open the picture dialog for preset `p` (an organizer library entry).
 * `file` preselects a dropped file; `onDone` runs after a change was saved.
 */
export function pictureDialog(p, { file = null, onDone } = {}) {
  let choice = null; // { file } | { output }
  let objectUrl = null;

  const caption = h("div", { class: "muted small" });
  const previewBox = h("div", { class: "pic picture-preview" });
  const show = (src, text, video = false) => {
    clear(previewBox);
    previewBox.classList.toggle("placeholder", !src);
    previewBox.append(src
      ? h(video ? "video" : "img", { src, alt: "", muted: true, autoplay: video, loop: true, playsInline: true })
      : h("span", { class: "big" }, "🖼"));
    caption.textContent = text;
  };
  if (p.picture) show(api.pictureUrl(p.name, p.picture.version), SOURCE[p.picture.kind] || "Current picture", p.picture.video);
  else show(null, "No picture yet");

  let useBtn = null;
  const choose = (c, src, text) => {
    choice = c;
    show(src, text);
    for (const t of grid.querySelectorAll(".output.on")) t.classList.remove("on");
    if (c.output) c.tile.classList.add("on");
    if (useBtn) useBtn.disabled = false;
  };
  const chooseFile = (f) => {
    if (!f) return;
    if (!okType(f)) return toast("Use a PNG, JPEG or WebP image", "error", 6000);
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    objectUrl = URL.createObjectURL(f);
    choose({ file: f }, objectUrl, `New: ${f.name}`);
  };

  const input = h("input", { type: "file", accept: TYPES.join(","), hidden: true, onchange: (e) => chooseFile(e.target.files[0]) });
  const drop = h("div", {
    class: "drop-zone", tabindex: 0,
    onclick: () => input.click(),
    onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } },
    ondragover: (e) => { e.preventDefault(); drop.classList.add("over"); },
    ondragleave: () => drop.classList.remove("over"),
    ondrop: async (e) => {
      e.preventDefault();
      drop.classList.remove("over");
      try {
        chooseFile(await droppedFile(e.dataTransfer));
      } catch (err) {
        toast(err.message, "error", 7000);
      }
    },
  }, input,
  h("strong", {}, "Drop an image here"),
  h("span", { class: "muted small" }, "or click to choose a file · or paste with Ctrl+V · PNG, JPEG or WebP"));

  const grid = h("div", { class: "output-grid" }, h("div", { class: "muted" }, "Loading…"));
  api.outputs(60).then(({ outputs }) => {
    clear(grid);
    if (!outputs.length) {
      grid.append(h("div", { class: "muted" }, "No images in ComfyUI's output folder yet."));
      return;
    }
    append(grid, outputs.map((o) => {
      const src = api.outputThumbUrl(o);
      const tile = h("button", {
        class: "output", title: `${o.path}${o.type === "temp" ? " (preview, cleared when ComfyUI restarts)" : ""}`,
        onclick: () => choose({ output: o, tile }, src, `New: ${o.path}`),
        ondblclick: () => useBtn?.click(),
      }, h("img", { src, loading: "lazy", alt: "" }),
      h("span", { class: "when" }, o.type === "temp" ? `preview · ${ago(o.mtime)}` : ago(o.mtime)));
      return tile;
    }));
  }).catch((e) => { clear(grid).append(h("div", { class: "error-box" }, e.message)); });

  const onPaste = (e) => {
    const cd = e.clipboardData;
    const f = [...(cd?.files || [])].find((x) => x.type.startsWith("image/")) ||
      [...(cd?.items || [])].find((x) => x.kind === "file" && x.type.startsWith("image/"))?.getAsFile();
    if (f) {
      e.preventDefault();
      chooseFile(f);
    }
  };
  document.addEventListener("paste", onPaste);

  const own = p.picture?.kind === "own";
  const close = dialog({
    title: `Picture · ${p.title}`,
    wide: true,
    body: h("div", { class: "picture-dialog" },
      h("div", { class: "picture-side" }, previewBox, caption),
      h("div", { class: "picture-pick" },
        drop,
        h("h3", {}, "Recent generations"),
        h("p", { class: "muted small" }, "Newest first, from ComfyUI's output folder. Double-click to use one right away."),
        grid)),
    actions: [
      {
        label: "Remove picture", kind: "danger ghost", disabled: !own,
        onClick: async () => {
          try {
            await api.removePicture(p.name);
            toast(`Removed the picture of ${p.title} (kept in presets/.trash/)`, "ok", 6000);
            onDone?.();
          } catch (e) {
            toast(e.message, "error", 7000);
            return false;
          }
        },
      },
      { label: "Cancel" },
      {
        label: "Use this picture", kind: "primary", disabled: true,
        onClick: async () => {
          if (!choice) return false;
          try {
            if (choice.file) await api.setPicture(p.name, choice.file);
            else await api.pictureFromOutput(p.name, choice.output.type, choice.output.path);
            toast(`New picture for ${p.title}${own ? "; the old one is in presets/.trash/" : ""}`, "ok", 5000);
            onDone?.();
          } catch (e) {
            toast(e.message, "error", 7000);
            return false;
          }
        },
      },
    ],
    onClose: () => {
      document.removeEventListener("paste", onPaste);
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    },
  });
  useBtn = close.box.querySelector(".dialog-actions .btn.primary");
  if (file) chooseFile(file);
  return close;
}

// Let a file dropped on `el` open the dialog with it preselected.
export function acceptPictureDrops(el, p, onDone) {
  const hasImage = (e) => [...e.dataTransfer.types].some((t) => t === "Files" || t === "text/uri-list");
  el.addEventListener("dragover", (e) => {
    if (!hasImage(e)) return;
    e.preventDefault();
    el.classList.add("drop-over");
  });
  el.addEventListener("dragleave", () => el.classList.remove("drop-over"));
  el.addEventListener("drop", async (e) => {
    if (!hasImage(e)) return;
    e.preventDefault();
    e.stopPropagation();
    el.classList.remove("drop-over");
    try {
      const file = await droppedFile(e.dataTransfer);
      if (file) pictureDialog(p, { file, onDone });
    } catch (err) {
      toast(err.message, "error", 7000);
    }
  });
}
