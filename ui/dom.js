// Tiny DOM helpers. All user text goes in as text nodes, never as HTML:
// presets can come from other people.

export function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "dataset") Object.assign(el.dataset, v);
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (k === "value") el.value = v; // the property: <textarea> ignores the attribute
    else if (k in el && typeof v !== "string") el[k] = v; // e.g. checked, disabled, value
    else el.setAttribute(k, v === true ? "" : String(v));
  }
  append(el, children);
  return el;
}

export function append(el, children) {
  for (const c of [children].flat(Infinity)) { // a single node or any nesting of lists
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

export function clear(el) {
  el.replaceChildren();
  return el;
}

export function toast(message, kind = "info", ms = 4000) {
  const box = document.getElementById("toasts");
  const t = h("div", { class: `toast ${kind}`, role: kind === "error" ? "alert" : "status" }, message);
  box.append(t);
  setTimeout(() => t.classList.add("leaving"), ms);
  setTimeout(() => t.remove(), ms + 400);
}

// Modal dialog. `body` is a node; `actions` are [{label, kind, onClick}] where
// onClick may return false to keep the dialog open. Returns a close function.
export function dialog({ title, body, actions = [], wide = false, onClose }) {
  const close = () => {
    document.removeEventListener("keydown", onKey, true);
    back.remove();
    onClose?.();
  };
  const onKey = (e) => {
    // Only the topmost dialog reacts, so Escape in "Rename" keeps the detail panel open.
    if (e.key === "Escape" && [...document.querySelectorAll(".backdrop")].at(-1) === back) {
      e.stopPropagation();
      close();
    }
  };
  const buttons = actions.map((a) => h("button", {
    class: `btn ${a.kind || ""}`, disabled: a.disabled,
    onclick: async (e) => {
      const btn = e.currentTarget; // currentTarget is gone after the await
      btn.disabled = true;
      try {
        if ((await a.onClick?.()) !== false) close();
      } finally {
        btn.disabled = false;
      }
    },
  }, a.label));
  const box = h("div", { class: `dialog${wide ? " wide" : ""}`, role: "dialog", "aria-modal": "true", "aria-label": title },
    h("div", { class: "dialog-head" }, h("h2", {}, title), h("button", { class: "btn icon ghost", title: "Close", onclick: close }, "✕")),
    h("div", { class: "dialog-body" }, body),
    actions.length ? h("div", { class: "dialog-actions" }, buttons) : null);
  const back = h("div", { class: "backdrop", onmousedown: (e) => { if (e.target === back) close(); } }, box);
  document.body.append(back);
  document.addEventListener("keydown", onKey, true);
  (box.querySelector("input, textarea, select") || buttons.at(-1))?.focus();
  close.box = box;
  back.closeDialog = close;
  return close;
}

export function closeAllDialogs() {
  for (const b of [...document.querySelectorAll(".backdrop")].reverse()) b.closeDialog?.();
}

export function copyText(text) {
  if (navigator.clipboard?.writeText) return navigator.clipboard.writeText(text);
  const ta = h("textarea", { style: { position: "fixed", opacity: "0" } }, text);
  document.body.append(ta);
  ta.select();
  document.execCommand("copy");
  ta.remove();
  return Promise.resolve();
}
