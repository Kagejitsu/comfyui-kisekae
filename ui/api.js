// Fetch wrappers for /kisekae/api. Errors throw an Error whose message is the
// server's {"error": ...} text; `.conflict` is set for 409s.

async function call(method, path, { query, body, blob } = {}) {
  const url = new URL(`/kisekae/api/${path}`, location.origin);
  for (const [k, v] of Object.entries(query || {})) url.searchParams.set(k, v);
  const res = await fetch(url, {
    method,
    headers: body ? { "Content-Type": "application/json" } : blob ? { "Content-Type": "application/octet-stream" } : undefined,
    body: body ? JSON.stringify(body) : blob,
  });
  let data = null;
  try {
    data = await res.json();
  } catch {
    // non-JSON (e.g. a proxy error page)
  }
  if (!res.ok) {
    const err = new Error(data?.error || `${res.status} ${res.statusText}`);
    err.status = res.status;
    err.conflict = !!data?.conflict;
    throw err;
  }
  return data;
}

export const api = {
  library: () => call("GET", "library"),
  preset: (name) => call("GET", "preset", { query: { name } }),
  save: (name, data, etag) => call("PUT", "preset", { body: { name, data, etag } }),
  render: (name, extra = {}) => call("POST", "render", { body: { name, ...extra } }),
  rename: (from, to, dryRun) => call("POST", "rename", { body: { from, to, dry_run: dryRun } }),
  duplicate: (from, to, title) => call("POST", "duplicate", { body: { from, to, title } }),
  trash: (name) => call("POST", "trash", { body: { name } }),
  trashList: () => call("GET", "trash"),
  restore: (id, name) => call("POST", "restore", { body: { id, name } }),
  schema: () => call("GET", "schema"),
  addVocab: (section, field, value) => call("POST", "vocab", { body: { section, field, value } }),
  loras: (q) => call("GET", "loras", { query: { q } }),
  vocabField: (section, field) => call("GET", "vocab/field", { query: { section, field } }),
  setVocabField: (section, field, entry) => call("PUT", "vocab/field", { body: { section, field, entry } }),
  templates: () => call("GET", "templates"),
  saveTemplate: (name, text) => call("PUT", "template", { body: { name, text } }),
  trashTemplate: (name) => call("POST", "template/trash", { body: { name } }),
  setPicture: (name, blob) => call("POST", "picture", { query: { name }, blob }),
  pictureFromOutput: (name, type, path) => call("POST", "picture/output", { body: { name, type, path } }),
  removePicture: (name) => call("POST", "picture/remove", { body: { name } }),
  outputs: (limit = 60) => call("GET", "outputs", { query: { limit } }),
  outputThumbUrl: (o) => `/kisekae/api/outputs/thumb?type=${encodeURIComponent(o.type)}&path=${encodeURIComponent(o.path)}`,
  pictureUrl: (name, version, { thumb = false } = {}) =>
    `/kisekae/api/picture?name=${encodeURIComponent(name)}&v=${encodeURIComponent(version ?? "")}${thumb ? "&thumb=1" : ""}`,
};
