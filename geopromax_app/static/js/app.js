// GeoProMax: the page. Inputs on the left; the plan or the section, the time
// bar, the headline numbers and the detail tabs on the right. Every result is
// worked out in the browser: the query point on this thread (it is quick), the
// plan grid and the section in a worker.

import { PRESETS, PRESET_KEYS, LOAD_TYPES, layerFrom, loadFrom, complete, checks, depthOf, TEMPLATES } from "../engine/project.js";
import { computePoint, settlementAt, timeCurve, timeTo } from "../engine/settlement.js";
import { extents, loadPressure } from "../engine/stress.js";
import { runChecks } from "../engine/verify.js";
import { drawPlan, sample, rampCSS } from "./plan.js";
import { timeChart, depthChart, sectionView, soilColour, esc } from "./charts.js";

const G = window.__GEOPROMAX || { api: "api", base: "./", static: "static/", openId: null };
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const fmt = (v, d = 1) => (Number.isFinite(v) ? (+v.toFixed(d)).toLocaleString(undefined, { maximumFractionDigits: d }) : "–");
const mm = (m, d = 0) => fmt(m * 1000, d);
const yrs = (t) => (!Number.isFinite(t) ? "–" : t < 1 / 12 ? `${fmt(t * 365, 0)} days` : t < 1 ? `${fmt(t * 12, 1)} months` : `${fmt(t, t < 10 ? 1 : 0)} year${t === 1 ? "" : "s"}`);

const state = {
  project: null, id: null, version: null, offline: false, dirty: false,
  res: null, grid: null, gridAsk: 0, view: "plan", tab: "time", depthMode: "stress",
  verify: null, playing: false, snap: null,
};

// ------------------------------------------------------------------ helpers

function get(obj, path) { return path.split(".").reduce((o, k) => (o == null ? undefined : o[k]), obj); }
function set(obj, path, v) {
  const ks = path.split(".");
  let o = obj;
  for (let i = 0; i < ks.length - 1; i++) { if (o[ks[i]] == null || typeof o[ks[i]] !== "object") o[ks[i]] = {}; o = o[ks[i]]; }
  o[ks[ks.length - 1]] = v;
}

let toastTimer;
function toast(text, bad) {
  const t = $(".toast");
  t.textContent = text;
  t.classList.toggle("error", !!bad);
  t.classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.add("hidden"), bad ? 6000 : 2600);
}

// theme switch, shared with the rest of the site
(() => {
  const LABELS = { system: "Auto", light: "Light", dark: "Dark" }, NEXT = { system: "light", light: "dark", dark: "system" };
  const cur = () => { try { return localStorage.getItem("pm-theme") || "system"; } catch (e) { return "system"; } };
  const apply = (t) => {
    if (t === "system") document.documentElement.removeAttribute("data-theme"); else document.documentElement.setAttribute("data-theme", t);
    const b = $("[data-theme-toggle]"); if (b) b.textContent = LABELS[t];
  };
  document.addEventListener("click", (ev) => {
    if (!ev.target.closest("[data-theme-toggle]")) return;
    const t = NEXT[cur()] || "light";
    try { localStorage.setItem("pm-theme", t); } catch (e) { /* private mode */ }
    apply(t);
    renderView(); renderPanel();
  });
  apply(cur());
})();

// ------------------------------------------------------------------ the inputs

const ICONS = {
  layers: '<path d="M2 5h16M2 10h16M2 15h16" stroke="currentColor" stroke-width="1.6" fill="none" stroke-linecap="round"/>',
  water: '<path d="M10 3 C7 8 5 10 5 12.5a5 5 0 0010 0C15 10 13 8 10 3z" stroke="currentColor" stroke-width="1.6" fill="none"/>',
  load: '<path d="M4 4h12M6 4v7M10 4v7M14 4v7M4 11l2 3 2-3M8 11l2 3 2-3M12 11l2 3 2-3M2 16h16" stroke="currentColor" stroke-width="1.4" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
  calc: '<path d="M3 16 L8 9 L12 12 L17 4" stroke="currentColor" stroke-width="1.6" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
  point: '<circle cx="10" cy="9" r="3" stroke="currentColor" stroke-width="1.6" fill="none"/><path d="M10 12v6" stroke="currentColor" stroke-width="1.6"/>',
};
const icon = (k) => `<svg class="icon" viewBox="0 0 20 20" aria-hidden="true">${ICONS[k] || ""}</svg>`;
const SVG = {
  up: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="M4 10l4-4 4 4"/></svg>',
  down: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="M4 6l4 4 4-4"/></svg>',
  copy: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="5" y="5" width="8" height="8" rx="1.5"/><path d="M3 10V4a1 1 0 011-1h6"/></svg>',
  del: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M4 4l8 8M12 4l-8 8"/></svg>',
};

/** A number field: label (with a hint below it), the box and its unit. */
function num(k, label, unit, o = {}) {
  const v = get(state.project, k);
  const val = v === null || v === undefined ? "" : v;
  const sub = typeof o.sub === "function" ? o.sub(state.project) : o.sub;
  return `<div class="f"><span class="lab">${label}${sub ? `<small data-sub="${k}">${esc(sub)}</small>` : ""}</span><span class="num"><input type="number" inputmode="decimal" data-k="${k}" value="${val}" step="${o.step ?? "any"}" ${o.min !== undefined ? `min="${o.min}"` : ""} ${o.max !== undefined ? `max="${o.max}"` : ""} ${o.blank ? `placeholder="${o.ph || "auto"}"` : ""} aria-label="${esc(label.replace(/<[^>]+>/g, ""))}"><span class="unit">${esc(unit || "")}</span></span>${o.picks ? `<div class="picks" style="grid-column:1/-1">${o.picks.map((p) => `<button type="button" data-pick="${k}" data-v="${p}">${p}</button>`).join("")}</div>` : ""}</div>`;
}
function seg(k, label, options) {
  const v = String(get(state.project, k));
  return `<div class="f wide">${label ? `<span class="lab">${label}</span>` : ""}<div class="seg" role="group" aria-label="${esc(label || k)}">${options.map(([o, n]) => `<button type="button" data-seg="${k}" data-v="${o}" aria-pressed="${String(o) === v}">${esc(n)}</button>`).join("")}</div></div>`;
}
const toggle = (k, label, sub) => `<label class="toggle"><span>${esc(label)}${sub ? `<span class="tsub">${esc(sub)}</span>` : ""}</span><input type="checkbox" data-k="${k}" ${get(state.project, k) ? "checked" : ""}></label>`;
const tools = (kind, i, n, dup) => `<div class="tools">
  ${kind === "layer" ? `<button type="button" class="iconbtn" data-act="${kind}-up" data-i="${i}" ${i === 0 ? "disabled" : ""} title="Move up" aria-label="Move up">${SVG.up}</button>
  <button type="button" class="iconbtn" data-act="${kind}-down" data-i="${i}" ${i === n - 1 ? "disabled" : ""} title="Move down" aria-label="Move down">${SVG.down}</button>` : ""}
  ${dup ? `<button type="button" class="iconbtn" data-act="${kind}-dup" data-i="${i}" title="Duplicate" aria-label="Duplicate">${SVG.copy}</button>` : ""}
  <button type="button" class="iconbtn" data-act="${kind}-del" data-i="${i}" title="Remove" aria-label="Remove">${SVG.del}</button></div>`;

function layersWidget(p) {
  const tops = [];
  let z = 0;
  for (const l of p.layers) { tops.push(z); z += +l.thickness || 0; }
  const cards = p.layers.map((l, i) => {
    const k = `layers.${i}`;
    return `<div class="item" data-layer="${i}">
      <div class="item-head"><span class="chip" style="background:${soilColour(l, i)}"></span><input class="lname" data-k="${k}.name" value="${esc(l.name)}" aria-label="Layer name">${tools("layer", i, p.layers.length, true)}</div>
      <div class="note">${fmt(tops[i], 2)} to ${fmt(tops[i] + (+l.thickness || 0), 2)} m below ground</div>
      <div class="f wide"><span class="lab">Start from a typical soil<small>fills in the values below; change any of them after</small></span><select data-preset="${i}">
        <option value="">Choose…</option>${PRESET_KEYS.map((key) => `<option value="${key}" ${key === l.preset ? "selected" : ""}>${esc(PRESETS[key].name)}</option>`).join("")}</select></div>
      <div class="two">
        ${num(`${k}.thickness`, "Thickness", "m", { min: 0, step: 0.1 })}
        ${num(`${k}.E`, "Young's modulus E", "kPa", { min: 0, step: 500, sub: "0 skips immediate" })}
        ${num(`${k}.gamma`, "Unit weight γ", "kN/m³", { min: 0, step: 0.5, sub: "above water" })}
        ${num(`${k}.gammaSat`, "Saturated γsat", "kN/m³", { min: 0, step: 0.5, sub: "below water" })}
        ${num(`${k}.nu`, "Poisson's ratio ν", "", { min: 0, max: 0.49, step: 0.05 })}
      </div>
      ${toggle(`${k}.consolidating`, "Consolidates", "clay, silt or organic soil: Cc, Cr and cv")}
      ${l.consolidating ? `<div class="sub">
        <div class="two">
          ${num(`${k}.Cc`, "Compression Cc", "", { min: 0, step: 0.01 })}
          ${num(`${k}.Cr`, "Recompression Cr", "", { min: 0, step: 0.005 })}
          ${num(`${k}.e0`, "Void ratio e0", "", { min: 0, step: 0.05 })}
          ${num(`${k}.OCR`, "OCR", "", { min: 1, step: 0.1, sub: "σ'p / σ'v0" })}
          ${num(`${k}.POP`, "POP", "kPa", { min: 0, step: 5, sub: "added to σ'p" })}
          ${num(`${k}.cv`, "cv", "m²/yr", { min: 0, step: 0.1 })}
          ${num(`${k}.Ca`, "Creep Cα", "", { min: 0, step: 0.001 })}
        </div>
        ${seg(`${k}.drainage`, "Drains through", [["double", "Top and bottom"], ["single", "One face only"]])}
      </div>` : ""}
    </div>`;
  }).join("");
  return `${cards || `<div class="note">No layers yet.</div>`}
    <div class="addrow"><select id="addPreset" aria-label="Soil for the new layer">${PRESET_KEYS.map((key) => `<option value="${key}">${esc(PRESETS[key].name)}</option>`).join("")}</select>
    <button type="button" class="btn btn-ghost btn-sm" data-act="layer-add">+ Add layer</button></div>`;
}

const loadSub = (l) => {
  if (l.type === "embankment") return `q = γ·H = ${fmt(loadPressure(l), 0)} kPa${+l.slope > 0 && +l.H > 0 ? ` · sides 1:${fmt(+l.slope / +l.H, 1)}` : ""}`;
  if (l.type === "circle") return `${fmt(Math.PI * (+l.R) ** 2 * (+l.q) / 1000, 1)} MN in all`;
  return `${fmt((+l.B) * (+l.L) * (+l.q) / 1000, 1)} MN in all`;
};
function loadsWidget(p) {
  const cards = p.loads.map((l, i) => {
    const k = `loads.${i}`;
    let fields = "";
    if (l.type === "rect") fields = num(`${k}.B`, "Width B", "m", { min: 0, step: 0.5, sub: "along x" }) + num(`${k}.L`, "Length L", "m", { min: 0, step: 0.5, sub: "along y" }) + num(`${k}.q`, "Pressure q", "kPa", { step: 5 });
    if (l.type === "circle") fields = num(`${k}.R`, "Radius R", "m", { min: 0, step: 0.5 }) + num(`${k}.q`, "Pressure q", "kPa", { step: 5 });
    if (l.type === "embankment") fields = num(`${k}.H`, "Height H", "m", { min: 0, step: 0.25 }) + num(`${k}.gamma`, "Fill γ", "kN/m³", { min: 0, step: 0.5 })
      + num(`${k}.crest`, "Crest width", "m", { min: 0, step: 0.5 }) + num(`${k}.slope`, "Side slope run", "m", { min: 0, step: 0.5, sub: "each side" })
      + num(`${k}.L`, "Length", "m", { min: 0, step: 5 });
    return `<div class="item ${l.on === false ? "off" : ""}" data-load="${i}">
      <div class="item-head"><input class="lname" data-k="${k}.name" value="${esc(l.name)}" aria-label="Load name">${tools("load", i, p.loads.length, true)}</div>
      ${toggle(`${k}.on`, "Switched on")}
      ${seg(`${k}.type`, "", LOAD_TYPES)}
      <div class="two">
        ${num(`${k}.x`, "Centre x", "m", { step: 0.5 })}${num(`${k}.y`, "Centre y", "m", { step: 0.5 })}
        ${fields}
        ${num(`${k}.t0`, "Applied at", "yr", { min: 0, step: 0.25, sub: "0 = at the start" })}
      </div>
      ${l.type === "embankment" ? seg(`${k}.axis`, "Runs along", [["y", "y"], ["x", "x"]]) : ""}
      <div class="note" data-loadsub="${i}">${esc(loadSub(l))}</div>
    </div>`;
  }).join("");
  return `${cards || `<div class="note">No loads yet.</div>`}
    <div class="addrow">${LOAD_TYPES.map(([t, n]) => `<button type="button" class="btn btn-ghost btn-sm" data-act="load-add" data-type="${t}">+ ${n}</button>`).join("")}</div>`;
}

const GROUPS = [
  { g: "Soil profile", icon: "layers", open: true, sum: (p) => `${p.layers.length} layer${p.layers.length === 1 ? "" : "s"} · ${fmt(depthOf(p), 1)} m`, body: layersWidget },
  { g: "Groundwater", icon: "water", open: false, sum: (p) => `${fmt(+p.waterTable, 2)} m deep`,
    body: () => num("waterTable", "Water table depth", "m", { min: 0, step: 0.25, sub: "below ground; hydrostatic below it" }) },
  { g: "Loads", icon: "load", open: true, sum: (p) => `${p.loads.filter((l) => l.on !== false).length} on`, body: loadsWidget },
  { g: "Analysis", icon: "calc", open: false, sum: (p) => `${p.method === "westergaard" ? "Westergaard" : "Boussinesq"} · ${fmt(+p.life, 0)} yr`,
    body: (p) => seg("method", "Stress distribution", [["boussinesq", "Boussinesq"], ["westergaard", "Westergaard"]])
      + `<div class="note">${p.method === "westergaard" ? "Westergaard: a soil reinforced by thin stiff layers (varved clays). It spreads the load more, so stresses under the centre are lower." : "Boussinesq: a uniform elastic half-space. The usual choice."}</div>`
      + num("life", "Design life", "years", { min: 0.1, step: 1, picks: [10, 25, 50, 100], sub: "the end of the time axis" })
      + num("subLayers", "Sub-layers per layer", "", { min: 2, max: 50, step: 1, sub: "more is finer; 10 is plenty" })
      + num("grid.n", "Plan grid", "pts", { min: 11, max: 81, step: 2, sub: "points along each side" })
      + num("grid.margin", "Plan margin", "m", { min: 0, step: 1, blank: true, ph: "auto", sub: "around the loads; blank = soil depth" })
      + seg("section", "Section A–A′ runs along", [["x", "x"], ["y", "y"]]) },
  { g: "Query point", icon: "point", open: true, sum: (p) => `(${fmt(+p.query.x, 1)}, ${fmt(+p.query.y, 1)})`,
    body: () => `<div class="two" style="display:grid;grid-template-columns:1fr 1fr;gap:8px 10px">${num("query.x", "x", "m", { step: 0.5 })}${num("query.y", "y", "m", { step: 0.5 })}</div>
      <div class="note">Or click anywhere on the plan. The cards, the charts and the section are for this point.</div>
      <div class="picks"><button type="button" data-act="query-max">Go to the largest settlement</button>${state.project.loads.map((l, i) => `<button type="button" data-act="query-load" data-i="${i}">Centre of ${esc(l.name || `load ${i + 1}`)}</button>`).join("")}</div>` },
];

function renderInputs() {
  const p = state.project;
  const host = $("#inputs");
  const openNow = new Set($$("details.group[open]", host).map((d) => d.dataset.g));
  const first = !host.dataset.ready;
  host.dataset.ready = "1";
  const scroll = host.scrollTop;
  host.innerHTML = GROUPS.map((G2) => {
    const open = first ? G2.open : openNow.has(G2.g);
    return `<details class="group" data-g="${G2.g}" ${open ? "open" : ""}><summary>${icon(G2.icon)}${G2.g}<span class="sum">${esc(G2.sum(p))}</span></summary><div class="group-body">${G2.body(p)}</div></details>`;
  }).join("");
  host.scrollTop = scroll;
}
function refreshSums() {
  for (const d of $$("details.group", $("#inputs"))) {
    const G2 = GROUPS.find((x) => x.g === d.dataset.g);
    d.querySelector(".sum").textContent = G2.sum(state.project);
  }
  state.project.loads.forEach((l, i) => { const el = $(`[data-loadsub="${i}"]`); if (el) el.textContent = loadSub(l); });
}

function onInput(ev) {
  const el = ev.target;
  const p = state.project;
  if (el.dataset.preset !== undefined) {
    if (!el.value) return;
    const i = +el.dataset.preset, old = p.layers[i];
    p.layers[i] = { ...layerFrom(el.value, old.thickness), name: PRESETS[el.value].name };
    changed(true);
    return;
  }
  if (!el.dataset.k) return;
  let v;
  if (el.type === "checkbox") v = el.checked;
  else if (el.type === "text" || el.tagName === "SELECT") v = el.value;
  else v = el.value === "" ? null : +el.value;
  set(p, el.dataset.k, v);
  if (/^layers\.\d+\.name$/.test(el.dataset.k) || /^loads\.\d+\.name$/.test(el.dataset.k)) { changed(false, true); return; }
  changed(el.type === "checkbox" || /\.thickness$/.test(el.dataset.k));
}

function onClick(ev) {
  const b = ev.target.closest("button");
  if (!b) return;
  const p = state.project;
  if (b.dataset.seg) {
    set(p, b.dataset.seg, b.dataset.v);
    changed(true);
    return;
  }
  if (b.dataset.pick) { set(p, b.dataset.pick, +b.dataset.v); changed(true); return; }
  const act = b.dataset.act, i = +b.dataset.i;
  if (!act) return;
  if (act === "layer-add") { const key = $("#addPreset").value; p.layers.push({ ...layerFrom(key, 3), name: PRESETS[key].name }); }
  else if (act === "layer-del") p.layers.splice(i, 1);
  else if (act === "layer-dup") p.layers.splice(i + 1, 0, JSON.parse(JSON.stringify(p.layers[i])));
  else if (act === "layer-up" && i > 0) [p.layers[i - 1], p.layers[i]] = [p.layers[i], p.layers[i - 1]];
  else if (act === "layer-down" && i < p.layers.length - 1) [p.layers[i + 1], p.layers[i]] = [p.layers[i], p.layers[i + 1]];
  else if (act === "load-add") {
    const e = p.loads.length ? extents(p.loads, 0) : null;
    const at = e ? { x: Math.round(e.x2 + 10) } : {};
    const l = loadFrom(b.dataset.type, at);
    l.name = `${l.name} ${p.loads.length + 1}`;
    p.loads.push(l);
  }
  else if (act === "load-del") p.loads.splice(i, 1);
  else if (act === "load-dup") { const c = JSON.parse(JSON.stringify(p.loads[i])); c.name += " (copy)"; c.x = (+c.x || 0) + 5; p.loads.splice(i + 1, 0, c); }
  else if (act === "query-load") { p.query = { x: +p.loads[i].x || 0, y: +p.loads[i].y || 0 }; }
  else if (act === "query-max") {
    if (!state.grid) return;
    const g = state.grid.g; let k = 0;
    for (let n = 1; n < state.grid.values.length; n++) if (state.grid.values[n] > state.grid.values[k]) k = n;
    p.query = { x: +(g.x1 + ((g.x2 - g.x1) * (k % g.nx)) / (g.nx - 1)).toFixed(2), y: +(g.y1 + ((g.y2 - g.y1) * Math.floor(k / g.nx)) / (g.ny - 1)).toFixed(2) };
  }
  else return;
  changed(true);
}

// ------------------------------------------------------------------ undo, redo, saving

const undo = [], redo = [];
let burst = null;
const snapNow = () => JSON.stringify(state.project);
function remember() {
  if (!burst) { if (state.snap && state.snap !== snapNow()) { undo.push(state.snap); if (undo.length > 60) undo.shift(); redo.length = 0; } }
  clearTimeout(burst);
  burst = setTimeout(() => { burst = null; state.snap = snapNow(); undoButtons(); }, 700);
  undoButtons();
}
function undoButtons() {
  $("#btnUndo").disabled = !undo.length && !(burst && state.snap !== snapNow());
  $("#btnRedo").disabled = !redo.length;
}
function stepHistory(back) {
  if (burst) { clearTimeout(burst); burst = null; const now = snapNow(); if (now !== state.snap) { undo.push(state.snap); redo.length = 0; } state.snap = now; }
  const from = back ? undo : redo, to = back ? redo : undo;
  if (!from.length) return;
  to.push(state.snap);
  state.snap = from.pop();
  state.project = complete(JSON.parse(state.snap));
  $("#projectName").value = state.project.name;
  renderInputs(); analyse(); scheduleSave(); undoButtons();
}
function resetHistory() { undo.length = 0; redo.length = 0; clearTimeout(burst); burst = null; state.snap = snapNow(); undoButtons(); }

function changed(structural, nameOnly) {
  remember();
  if (structural) renderInputs(); else refreshSums();
  scheduleSave();
  if (nameOnly) { renderView(); renderPanel(); return; }
  analyse();
}

async function api(path, opt = {}) {
  const r = await fetch(G.api + path, { credentials: "same-origin", headers: { "Content-Type": "application/json", Accept: "application/json" }, ...opt });
  if (!r.ok) throw Object.assign(new Error((await r.json().catch(() => ({}))).error || r.statusText), { status: r.status });
  return r.json();
}
let saveTimer;
function scheduleSave() {
  state.dirty = true;
  $("#saveState").textContent = "Editing…";
  $("#saveState").className = "save-state";
  clearTimeout(saveTimer);
  saveTimer = setTimeout(save, 1200);
}
async function save() {
  const data = state.project;
  try { localStorage.setItem("geopromax-last", JSON.stringify({ id: state.id, data })); } catch (e) { /* private mode */ }
  if (state.offline) { $("#saveState").textContent = "Saved on this device"; return; }
  try {
    const r = state.id ? await api(`/projects/${state.id}`, { method: "PUT", body: JSON.stringify({ data }) })
      : await api(`/projects`, { method: "POST", body: JSON.stringify({ data }) });
    state.id = r.id; state.version = r.version; state.dirty = false;
    history.replaceState(null, "", `${G.base}p/${r.id}`);
    $("#saveState").textContent = "Saved";
    $("#saveState").className = "save-state saved";
  } catch (e) {
    $("#saveState").textContent = "Not saved: " + e.message;
  }
}
window.addEventListener("beforeunload", (ev) => { if (state.dirty && !state.offline) { save(); } });

// ------------------------------------------------------------------ calculating

const TMIN = 0.01;
const tFromSlider = (u) => 10 ** (Math.log10(TMIN) + (u / 1000) * (Math.log10(life()) - Math.log10(TMIN)));
const sliderFromT = (t) => Math.round(((Math.log10(Math.max(TMIN, t)) - Math.log10(TMIN)) / (Math.log10(life()) - Math.log10(TMIN))) * 1000);
const life = () => Math.max(0.1, +state.project.life || 50);
const nowT = () => Math.min(life(), Math.max(TMIN, +state.project.t || 1));

function sectionLine() {
  const p = state.project, e = gridBox();
  const along = p.section === "y" ? "y" : "x";
  return along === "x"
    ? { along, at: +p.query.y || 0, a1: e.x1, a2: e.x2, depth: depthOf(p) || 10 }
    : { along, at: +p.query.x || 0, a1: e.y1, a2: e.y2, depth: depthOf(p) || 10 };
}
function gridBox() {
  const p = state.project;
  // By default the plan reaches about as far past the loads as the soil is deep:
  // the settlement trough dies out over roughly that distance.
  const auto = Math.max(5, Math.min(depthOf(p) || 10, 60));
  const e = extents(p.loads, p.grid.margin === null || p.grid.margin === "" ? auto : +p.grid.margin);
  // keep the query point on the plan
  const qx = +p.query.x || 0, qy = +p.query.y || 0, pad = 2;
  return { x1: Math.min(e.x1, qx - pad), x2: Math.max(e.x2, qx + pad), y1: Math.min(e.y1, qy - pad), y2: Math.max(e.y2, qy + pad) };
}

let worker = null, gridTimer = null, waitingTime = false, pendingTime = null;
function newWorker() {
  if (worker) worker.terminate();
  worker = new Worker(new URL("./worker.js", import.meta.url), { type: "module" });
  worker.onmessage = onWorker;
  worker.onerror = (e) => { setBusy(false); toast("The plan could not be worked out: " + (e.message || "worker error"), true); };
}
function askGrid() {
  clearTimeout(gridTimer);
  gridTimer = setTimeout(() => {
    const p = state.project;
    const n = Math.max(11, Math.min(81, Math.round(+p.grid.n || 41)));
    const b = gridBox();
    // equal spacing in x and y, with about n points along the longer side
    const span = Math.max(b.x2 - b.x1, b.y2 - b.y1), d = span / (n - 1);
    const g = { ...b, nx: Math.max(5, Math.round((b.x2 - b.x1) / d) + 1), ny: Math.max(5, Math.round((b.y2 - b.y1) / d) + 1) };
    newWorker();
    state.gridAsk++;
    waitingTime = false;
    setBusy(true, "Working out the plan…");
    worker.postMessage({ id: state.gridAsk, kind: "grid", project: JSON.parse(JSON.stringify(p)), g, t: nowT(), section: sectionLine() });
  }, 180);
}
function askTime() {
  if (!state.grid || !worker) return;
  if (waitingTime) { pendingTime = nowT(); return; }
  waitingTime = true;
  worker.postMessage({ id: state.gridAsk, kind: "time", t: nowT() });
}
function onWorker(ev) {
  const m = ev.data;
  if (m.id !== state.gridAsk) return;
  if (m.kind === "progress") { $("#busyText").textContent = `Working out the plan… ${Math.round(m.done * 100)}%`; return; }
  if (m.kind === "error") { setBusy(false); toast("The plan could not be worked out: " + m.message, true); return; }
  if (m.kind === "grid") { state.grid = m; setBusy(false); }
  if (m.kind === "time") {
    state.grid = { ...state.grid, values: m.values, min: m.min, max: m.max, tilt: m.tilt, line: m.line };
    waitingTime = false;
    if (pendingTime !== null) { pendingTime = null; askTime(); }
  }
  renderView(); renderKpis();
}
function setBusy(on, text) {
  $("#busy").classList.toggle("hidden", !on);
  if (text) $("#busyText").textContent = text;
}

function analyse() {
  const p = state.project;
  try {
    state.res = computePoint(p, +p.query.x || 0, +p.query.y || 0);
  } catch (e) {
    state.res = null;
    toast("Could not work out the settlement: " + e.message, true);
  }
  state.curve = state.res ? timeCurve(state.res, life()) : null;
  syncTimebar();
  renderVerdict(); renderKpis(); renderTabs(); renderPanel();
  askGrid();
}

// ------------------------------------------------------------------ the answer

function syncTimebar() {
  $("#tSlider").value = sliderFromT(nowT());
  $("#tValue").textContent = yrs(nowT());
}

function renderVerdict() {
  const host = $("#ovVerdict");
  if (!state.res) { host.innerHTML = ""; return; }
  const now = settlementAt(state.res, nowT()), fin = settlementAt(state.res, life());
  host.innerHTML = `<div class="glass verdict"><div class="fos">${mm(now.total)}<span class="unit">mm</span></div>
    <div class="lines"><b>at (${fmt(+state.project.query.x, 1)}, ${fmt(+state.project.query.y, 1)}) after ${yrs(nowT())}</b><br>
    ${fmt(now.U * 100, 0)}% of primary consolidation done · ${mm(fin.total)} mm at ${yrs(life())}</div></div>`;
  const pill = $("#fpill");
  pill.innerHTML = `<b>${mm(now.total)} mm</b><span>after ${yrs(nowT())} · ${mm(fin.total)} mm at ${yrs(life())}</span>`;
}

const tiltBadge = (t) => {
  if (!(t > 0)) return `<span class="badge good">✓ level</span>`;
  const r = 1 / t;
  if (r >= 500) return `<span class="badge good">✓ flatter than 1/500</span>`;
  if (r >= 300) return `<span class="badge warning">▲ steeper than 1/500</span>`;
  return `<span class="badge critical">✕ steeper than 1/300</span>`;
};
function renderKpis() {
  const host = $("#kpis");
  const r = state.res;
  if (!r) { host.innerHTML = ""; return; }
  const now = settlementAt(r, nowT()), fin = settlementAt(r, life());
  const t90 = Math.max(0, ...r.layers.filter((l) => l.layer.consolidating && l.primary > 0).map((l) => timeTo(l.layer, 0.9)));
  const g = state.grid;
  host.innerHTML = [
    [`Now, at the query point`, `${mm(now.total)} mm`, `after ${yrs(nowT())}`, "main"],
    [`At design life`, `${mm(fin.total)} mm`, `after ${yrs(life())}`],
    [`Immediate`, `${mm(r.immediate)} mm`, `elastic, as the loads go on`],
    [`Primary consolidation`, `${mm(r.primary)} mm`, r.primary > 0 ? `90% done ${t90 > 0 ? `after ${yrs(t90 + (r.stages.at(-1)?.t || 0))}` : "straight away"}` : "no consolidating layer under load"],
    [`Creep`, `${mm(fin.secondary)} mm`, `secondary compression by ${yrs(life())}`],
    // the query point may fall between grid points, so it counts too
    [`Largest on the plan`, g ? `${mm(Math.max(g.max, now.total))} mm` : "…", g ? `steepest tilt ${g.tilt > 0 ? `1/${fmt(1 / g.tilt, 0)}` : "none"} ${tiltBadge(g.tilt)}` : "working it out"],
  ].map(([k, v, s, cls]) => `<div class="kpi ${cls || ""}"><div class="k">${k}</div><div class="v">${v}</div><div class="s">${s}</div></div>`).join("");
}

function renderLegend() {
  const g = state.grid;
  $("#legend").innerHTML = state.view === "plan" && g
    ? `<div><div>Total settlement after ${yrs(nowT())} (mm)</div><div class="ramp" style="background:${rampCSS()}"></div><div class="ends"><span>0</span><span>${mm(g.max)}</span></div></div>`
    : `<span><b>A–A′</b> ${sectionLine().along === "x" ? `along x at y = ${fmt(sectionLine().at, 1)} m` : `along y at x = ${fmt(sectionLine().at, 1)} m`}</span><span><i style="background:var(--critical)"></i>Settled ground after ${yrs(nowT())}, drawn deeper than scale</span><span><i style="background:var(--series-2)"></i>Δσ as a share of the largest load pressure</span><span><i style="background:var(--water)"></i>Water table</span>`;
}

let planFrame = null;
function renderView() {
  const plan = $("#plan"), sec = $("#sectionHost");
  $$("[data-view]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.view === state.view)));
  plan.classList.toggle("hidden", state.view !== "plan");
  sec.classList.toggle("hidden", state.view !== "section");
  renderLegend();
  if (state.view === "plan") {
    planFrame = drawPlan(plan, state.project, state.grid, { query: state.project.query, section: sectionLine() });
  } else {
    const box = $("#view").getBoundingClientRect();
    sec.innerHTML = sectionView(state.project, sectionLine(), state.grid, box);
  }
}

const TABS = [
  ["time", "Time"], ["depth", "With depth"], ["layers", "Layers"], ["rows", "Sub-layers"], ["checks", "Checks"], ["verify", "Verification"], ["about", "Methods"],
];
function renderTabs() {
  const n = checks(state.project).length;
  $("#dtabs").innerHTML = TABS.map(([k, name]) => `<button role="tab" data-tab="${k}" aria-selected="${state.tab === k}">${name}${k === "checks" && n ? ` <span class="pill warn">${n}</span>` : ""}</button>`).join("");
}

function renderPanel() { $("#dpanel").innerHTML = panelHTML(state.tab); }

function panelHTML(tab) {
  const r = state.res, p = state.project;
  if (!r) return `<div class="note">Nothing to show yet.</div>`;
  if (tab === "time") {
    const keyTimes = [0.1, 0.5, 1, 2, 5, 10, 25, 50, 100].filter((t) => t <= life());
    if (!keyTimes.includes(life())) keyTimes.push(life());
    return `${timeChart(state.curve, { t: nowT(), now: settlementAt(r, nowT()), stages: r.stages })}
      <div class="table-scroll" style="margin-top:12px"><table class="tight"><thead><tr><th>Time</th><th class="num">Immediate (mm)</th><th class="num">Primary (mm)</th><th class="num">Creep (mm)</th><th class="num">Total (mm)</th><th class="num">Primary done</th></tr></thead>
      <tbody>${keyTimes.map((t) => { const s = settlementAt(r, t); return `<tr><td>${yrs(t)}</td><td class="num">${mm(s.immediate, 1)}</td><td class="num">${mm(s.primary, 1)}</td><td class="num">${mm(s.secondary, 1)}</td><td class="num"><b>${mm(s.total, 1)}</b></td><td class="num">${fmt(s.U * 100, 0)}%</td></tr>`; }).join("")}</tbody></table></div>`;
  } else if (tab === "depth") {
    return `<div class="seg" style="max-width:320px;margin-bottom:8px" role="group" aria-label="What to plot">
      <button type="button" data-depth="stress" aria-pressed="${state.depthMode === "stress"}">Stresses</button><button type="button" data-depth="strain" aria-pressed="${state.depthMode === "strain"}">Strains</button></div>
      ${depthChart(p, r, state.depthMode)}`;
  } else if (tab === "layers") {
    const fin = (lr) => { const one = { ...r, layers: [lr] }; return settlementAt(one, life()); };
    const total = settlementAt(r, life()).total || 1;
    return `<div class="table-scroll"><table class="tight"><thead><tr><th>Layer</th><th class="num">Depth (m)</th><th class="num">Immediate (mm)</th><th class="num">Primary (mm)</th><th class="num">Creep at ${yrs(life())} (mm)</th><th class="num">90% consolidated</th><th class="num">Share</th></tr></thead><tbody>
      ${r.layers.map((lr, i) => { const f = fin(lr); const share = (f.total / total) * 100; return `<tr><td><span class="swatch" style="background:${soilColour(lr.layer, i)}"></span>${esc(lr.name)}</td><td class="num">${fmt(lr.top, 2)}–${fmt(lr.bottom, 2)}</td><td class="num">${mm(lr.immediate, 1)}</td><td class="num">${mm(lr.primary, 1)}</td><td class="num">${mm(f.secondary, 1)}</td><td class="num">${lr.layer.consolidating && lr.primary > 0 ? yrs(timeTo(lr.layer, 0.9)) : "–"}</td><td class="num">${fmt(share, 0)}%</td></tr>`; }).join("")}
      </tbody><tfoot><tr><td>All layers</td><td></td><td class="num">${mm(r.immediate, 1)}</td><td class="num">${mm(r.primary, 1)}</td><td class="num">${mm(settlementAt(r, life()).secondary, 1)}</td><td></td><td class="num">100%</td></tr></tfoot></table></div>
      <p class="note" style="margin-top:8px">Times to 90% are from when each load goes on. Creep starts once a layer is 95% consolidated under the last stage.</p>`;
  } else if (tab === "rows") {
    return `<div class="table-scroll"><table class="tight"><thead><tr><th>Layer</th><th class="num">z (m)</th><th class="num">u0 (kPa)</th><th class="num">σ'v0 (kPa)</th><th class="num">σ'p (kPa)</th><th class="num">Δσ (kPa)</th><th class="num">σ'f (kPa)</th><th class="num">ε imm. (%)</th><th class="num">ε cons. (%)</th><th class="num">s (mm)</th></tr></thead><tbody>
      ${r.rows.map((x) => `<tr><td>${esc(x.name)}</td><td class="num">${fmt(x.z, 2)}</td><td class="num">${fmt(x.u0, 1)}</td><td class="num">${fmt(x.sv0, 1)}</td><td class="num">${x.sp === null ? "–" : fmt(x.sp, 1)}</td><td class="num">${fmt(x.dsig, 1)}</td><td class="num">${fmt(x.svf, 1)}</td><td class="num">${fmt(x.epsImm * 100, 3)}</td><td class="num">${fmt(x.epsCons * 100, 3)}</td><td class="num">${mm(x.sImm + x.sCons, 2)}</td></tr>`).join("")}
      </tbody></table></div>`;
  } else if (tab === "checks") {
    const c = checks(p);
    return c.length ? `<div class="checks">${c.map((x) => `<div class="${x.level === "critical" ? "warn bad-text" : "warn"}">${x.level === "critical" ? "✕" : "▲"} ${esc(x.text)}</div>`).join("")}</div>`
      : `<div class="ok">✓ Nothing to flag in the inputs.</div>`;
  } else if (tab === "verify") {
    if (!state.verify) state.verify = runChecks();
    const v = state.verify, ok = v.filter((x) => x.pass).length;
    return `<div class="${ok === v.length ? "ok" : "warn"}" style="margin-bottom:10px">${ok === v.length ? "✓" : "▲"} ${ok} of ${v.length} checks agree with the reference. The same checks run on every change to the code.</div>
      <div class="table-scroll"><table class="tight"><thead><tr><th>What</th><th>Reference</th><th class="num">Expected</th><th class="num">GeoProMax</th><th></th></tr></thead><tbody>
      ${v.map((x) => `<tr><td>${esc(x.name)}<div class="note">${esc(x.group)}</div></td><td class="ink2">${esc(x.reference)}</td><td class="num">${fmtCheck(x.expected)} ${esc(x.unit)}</td><td class="num">${fmtCheck(x.got)} ${esc(x.unit)}</td><td>${x.pass ? `<span class="pill good">✓ agrees</span>` : `<span class="pill bad">✕ differs</span>`}</td></tr>`).join("")}
      </tbody></table></div>`;
  } else if (tab === "about") {
    return METHODS;
  }
  return "";
}
const fmtCheck = (v) => (Math.abs(v) < 1 ? v.toFixed(4) : v.toFixed(2));

const METHODS = `<div class="explain" style="display:grid;gap:10px;max-width:820px">
  <p><b>Stresses.</b> Each load is a flexible pressure on the ground surface. The increase in vertical stress Δσ is found from <b>Boussinesq</b> (a uniform elastic half-space) or <b>Westergaard</b> (a half-space reinforced by thin stiff layers, using the layer's Poisson's ratio). Rectangles are solved exactly with the corner method (Newmark 1935), so points outside a load are as exact as points under it. Circles are split into 40 strips of the same area, and embankment side slopes into 20 steps. Loads add together.</p>
  <p><b>In-situ stresses.</b> σ'v0 = σv − u, with the unit weight above the water table and the saturated unit weight below it, and hydrostatic pore pressure (γw = 9.81 kN/m³).</p>
  <p><b>Immediate settlement.</b> Each sub-layer compresses by <code>Δσ·h / M</code>, with the constrained modulus <code>M = E(1−ν)/((1+ν)(1−2ν))</code>. Set E to 0 to leave a layer out.</p>
  <p><b>Primary consolidation.</b> For layers that consolidate: σ'p = OCR·σ'v0 + POP. Then <code>Δe = Cr·log(σ'f/σ'v0)</code> while σ'f ≤ σ'p, <code>Cc·log(σ'f/σ'v0)</code> when the soil is normally consolidated, and <code>Cr·log(σ'p/σ'v0) + Cc·log(σ'f/σ'p)</code> across σ'p; the settlement is <code>Δe·h/(1+e0)</code>.</p>
  <p><b>Rate.</b> Terzaghi's one-dimensional theory for each layer: <code>Tv = cv·t / Hdr²</code>, with Hdr half the layer for drainage through both faces and the whole layer for one. Loads that go on later (Applied at) are stages: each stage's extra settlement consolidates from its own time.</p>
  <p><b>Creep.</b> Once a layer is 95% consolidated under the last stage (at t95), it keeps settling by <code>Cα·h/(1+ep)·log(t/t95)</code>.</p>
  <p><b>Tilt.</b> The steepest slope of the settled surface between neighbouring plan points. 1/500 is the usual limit against cracking in framed buildings and 1/300 the one against structural damage (Bjerrum 1963).</p>
  <p class="note">Results are for design and checking by an engineer. They assume flexible loads; a stiff raft settles more evenly than the plan shows. Units: m, kN, kPa, years; settlement in mm.</p>
</div>`;

// ------------------------------------------------------------------ events on the answer

$("#dtabs").addEventListener("click", (ev) => { const b = ev.target.closest("[data-tab]"); if (!b) return; state.tab = b.dataset.tab; renderTabs(); renderPanel(); });
$("#dpanel").addEventListener("click", (ev) => { const b = ev.target.closest("[data-depth]"); if (!b) return; state.depthMode = b.dataset.depth; renderPanel(); });
$$("[data-view]").forEach((b) => b.addEventListener("click", () => { state.view = b.dataset.view; renderView(); }));

$("#plan").addEventListener("click", (ev) => {
  if (!planFrame || !state.grid) return;
  const r = ev.currentTarget.getBoundingClientRect();
  const [x, y] = planFrame.inv(ev.clientX - r.left, ev.clientY - r.top);
  const g = state.grid.g;
  if (x < g.x1 || x > g.x2 || y < g.y1 || y > g.y2) return;
  state.project.query = { x: +x.toFixed(1), y: +y.toFixed(1) };
  changed(true);
});
$("#plan").addEventListener("mousemove", (ev) => {
  const hv = $("#hover");
  if (!planFrame || !state.grid) { hv.classList.add("hidden"); return; }
  const r = ev.currentTarget.getBoundingClientRect();
  const [x, y] = planFrame.inv(ev.clientX - r.left, ev.clientY - r.top);
  const s = sample(state.grid, x, y);
  if (s === null) { hv.classList.add("hidden"); return; }
  hv.classList.remove("hidden");
  hv.innerHTML = `x ${fmt(x, 1)}, y ${fmt(y, 1)} m · <b>${mm(s)} mm</b>`;
});
$("#plan").addEventListener("mouseleave", () => $("#hover").classList.add("hidden"));

$("#tSlider").addEventListener("input", (ev) => {
  state.project.t = +tFromSlider(+ev.target.value).toPrecision(3);
  $("#tValue").textContent = yrs(nowT());
  renderVerdict(); renderKpis();
  if (state.tab === "time") renderPanel();
  askTime();
  scheduleSave();
});
let playStart = 0;
function playFrame(now) {
  if (!state.playing) return;
  const u = Math.min(1000, ((now - playStart) / 7000) * 1000);
  state.project.t = +tFromSlider(u).toPrecision(3);
  syncTimebar(); renderVerdict(); renderKpis(); askTime();
  if (u >= 1000) { stopPlay(); if (state.tab === "time") renderPanel(); return; }
  requestAnimationFrame(playFrame);
}
function stopPlay() { state.playing = false; $("#btnPlay").setAttribute("aria-pressed", "false"); }
$("#btnPlay").addEventListener("click", () => {
  if (state.playing) { stopPlay(); return; }
  state.playing = true; $("#btnPlay").setAttribute("aria-pressed", "true");
  state.view = "plan"; renderView();
  playStart = performance.now();
  requestAnimationFrame(playFrame);
});

let resizeTimer;
window.addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(renderView, 80); });

// the answer follows you down the page on a phone
new IntersectionObserver(([e]) => $("#fpill").classList.toggle("on", !e.isIntersecting)).observe($("#view"));
$("#fpill").addEventListener("click", () => $("#view").scrollIntoView({ behavior: "smooth", block: "start" }));

// ------------------------------------------------------------------ projects

async function openDrawer() {
  $("#drawer").classList.remove("hidden");
  const list = $("#projList");
  list.innerHTML = `<div class="note">Loading…</div>`;
  if (state.offline) { list.innerHTML = `<div class="note">Projects are kept on this device only here: the site could not be reached.</div>`; return; }
  try {
    const { projects } = await api("/projects");
    list.innerHTML = projects.length ? projects.map((p) => `<div class="proj ${p.id === state.id ? "current" : ""}" data-open="${p.id}"><span class="pn">${esc(p.name)}</span><span class="pm">version ${p.version}</span><span class="pm">${new Date(p.updated * 1000).toLocaleString()}</span><span><button class="btn btn-ghost btn-sm" data-hist="${p.id}">History</button> <button class="btn btn-ghost btn-sm" data-dup="${p.id}">Copy</button> <button class="btn btn-danger btn-sm" data-del="${p.id}">Delete</button></span></div>`).join("")
      : `<div class="note">No projects yet. Everything you do is saved as you go.</div>`;
  } catch (e) { list.innerHTML = `<div class="note">Projects could not be listed (${esc(e.message)}).</div>`; }
}
$("#btnProjects").addEventListener("click", openDrawer);
$("#drawer").addEventListener("click", async (ev) => {
  if (ev.target === $("#drawer") || ev.target.closest("[data-close]")) { $("#drawer").classList.add("hidden"); return; }
  const tpl = ev.target.closest("[data-new]");
  if (tpl) { newProject(tpl.dataset.new); return; }
  const del = ev.target.closest("[data-del]"), dup = ev.target.closest("[data-dup]"), open = ev.target.closest("[data-open]");
  const hist = ev.target.closest("[data-hist]"), back = ev.target.closest("[data-restore]");
  try {
    if (hist) {
      ev.stopPropagation();
      const row = hist.closest(".proj"), old = row.nextElementSibling;
      if (old?.classList.contains("versions")) { old.remove(); return; }
      const { versions } = await api(`/projects/${hist.dataset.hist}/versions`);
      row.insertAdjacentHTML("afterend", `<div class="versions">${versions.length ? versions.map((v) => `<div class="ver"><span>Version ${v.version}</span><span class="pm">${new Date(v.saved * 1000).toLocaleString()}</span><button class="btn btn-ghost btn-sm" data-restore="${hist.dataset.hist}:${v.id}">Bring back</button></div>`).join("") : `<div class="note">No earlier versions yet: each save keeps the one before it (up to 30).</div>`}</div>`);
      return;
    }
    if (back) {
      ev.stopPropagation();
      const [pid, vid] = back.dataset.restore.split(":");
      const r = await api(`/projects/${pid}/versions/${vid}/restore`, { method: "POST", body: "{}" });
      loadProject(r); $("#drawer").classList.add("hidden"); toast("Earlier version brought back. The one before is in History too."); return;
    }
    if (del) {
      ev.stopPropagation();
      if (!confirm("Delete this project? Its earlier versions go with it.")) return;
      await api(`/projects/${del.dataset.del}`, { method: "DELETE" });
      if (+del.dataset.del === state.id) state.id = null;
      openDrawer(); return;
    }
    if (dup) { ev.stopPropagation(); const r = await api(`/projects/${dup.dataset.dup}/duplicate`, { method: "POST", body: "{}" }); loadProject(r); $("#drawer").classList.add("hidden"); return; }
    if (open) { const r = await api(`/projects/${open.dataset.open}`); loadProject(r); $("#drawer").classList.add("hidden"); }
  } catch (e) { toast(e.message, true); }
});
$("#fileOpen").addEventListener("change", async (ev) => {
  const f = ev.target.files?.[0];
  ev.target.value = "";
  if (!f) return;
  try {
    const data = JSON.parse(await f.text());
    if (!Array.isArray(data.layers) || !Array.isArray(data.loads)) throw new Error("this is not a GeoProMax project file");
    state.id = null;
    state.project = complete(data);
    startOver();
    $("#drawer").classList.add("hidden");
    save();
    toast(`Opened ${f.name} as a new project.`);
  } catch (e) { toast("Could not open the file: " + e.message, true); }
});

function startOver() {
  state.grid = null; state.verify = null;
  $("#projectName").value = state.project.name;
  renderInputs(); analyse(); resetHistory();
}
function loadProject(r) {
  state.id = r.id; state.version = r.version;
  state.project = complete(r.data);
  history.replaceState(null, "", `${G.base}p/${r.id}`);
  $("#saveState").textContent = "Saved"; $("#saveState").className = "save-state saved";
  startOver();
}
function newProject(template) {
  state.id = null;
  state.project = complete({ template });
  $("#drawer").classList.add("hidden");
  startOver(); save();
}
$("#projectName").addEventListener("input", (ev) => { state.project.name = ev.target.value; scheduleSave(); });

// ------------------------------------------------------------------ report and downloads

function download(name, text, type) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type }));
  a.download = name;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}
const safeName = () => (state.project.name || "GeoProMax").replace(/[^\w\- ]+/g, "").trim() || "GeoProMax";

function csv() {
  const r = state.res, q = (v) => (typeof v === "string" ? `"${v.replace(/"/g, '""')}"` : Number.isFinite(v) ? +v.toPrecision(6) : "");
  const lines = [[`GeoProMax settlement: ${state.project.name}`], [`Query point x (m)`, +state.project.query.x, `y (m)`, +state.project.query.y], [],
    ["Layer", "z (m)", "u0 (kPa)", "sv0' (kPa)", "sp' (kPa)", "dsigma (kPa)", "sf' (kPa)", "strain immediate (%)", "strain consolidation (%)", "settlement (mm)"],
    ...r.rows.map((x) => [x.name, x.z, x.u0, x.sv0, x.sp ?? "", x.dsig, x.svf, x.epsImm * 100, x.epsCons * 100, (x.sImm + x.sCons) * 1000]),
    [], ["Time (years)", "Immediate (mm)", "Primary (mm)", "Creep (mm)", "Total (mm)", "Primary done (%)"],
    ...state.curve.map((s) => [s.t, s.immediate * 1000, s.primary * 1000, s.secondary * 1000, s.total * 1000, s.U * 100])];
  download(`${safeName()}.csv`, lines.map((l) => l.map(q).join(",")).join("\r\n"), "text/csv");
}

function printReport() {
  const p = state.project, r = state.res;
  if (!r) return;
  // A report is printed on white paper: draw it in the light theme, then put the theme back.
  const theme = document.documentElement.getAttribute("data-theme");
  document.documentElement.setAttribute("data-theme", "light");
  const restore = () => {
    if (theme) document.documentElement.setAttribute("data-theme", theme); else document.documentElement.removeAttribute("data-theme");
    window.removeEventListener("afterprint", restore);
    renderView();
  };
  window.addEventListener("afterprint", restore);
  const now = settlementAt(r, nowT()), fin = settlementAt(r, life());
  // the plan as an image, drawn off screen at a print-friendly size
  const c = document.createElement("canvas");
  c.style.cssText = "position:fixed;left:-9999px;top:0;width:900px;height:620px";
  document.body.appendChild(c);
  drawPlan(c, p, state.grid, { query: p.query, section: sectionLine() });
  const planImg = state.grid ? c.toDataURL("image/png") : "";
  c.remove();
  const kv = (k, v) => `<div>${k}<b>${v}</b></div>`;
  const layerRows = p.layers.map((l, i) => `<tr><td>${esc(l.name)}</td><td>${fmt(+l.thickness, 2)}</td><td>${l.gamma} / ${l.gammaSat}</td><td>${l.E}</td><td>${l.nu}</td><td>${l.consolidating ? `Cc ${l.Cc}, Cr ${l.Cr}, e0 ${l.e0}, OCR ${l.OCR}${+l.POP ? `, POP ${l.POP} kPa` : ""}, cv ${l.cv} m²/yr, Cα ${l.Ca}, ${l.drainage === "single" ? "one face" : "both faces"}` : "–"}</td></tr>`).join("");
  const loadRows = p.loads.map((l) => `<tr><td>${esc(l.name)}${l.on === false ? " (off)" : ""}</td><td>${LOAD_TYPES.find((t) => t[0] === l.type)?.[1]}</td><td>(${fmt(+l.x, 2)}, ${fmt(+l.y, 2)})</td><td>${l.type === "rect" ? `${l.B} × ${l.L} m` : l.type === "circle" ? `R ${l.R} m` : `crest ${l.crest} m, sides ${l.slope} m, H ${l.H} m, ${l.L} m long along ${l.axis}`}</td><td>${fmt(loadPressure(l), 1)}</td><td>${fmt(+l.t0 || 0, 2)}</td></tr>`).join("");
  const c2 = checks(p);
  const ver = runChecks(), vok = ver.filter((x) => x.pass).length;
  $("#report").innerHTML = `
    <h1>${esc(p.name)}</h1>
    <p class="rnote">GeoProMax ${esc(G.version || "")} · settlement analysis · ${new Date().toLocaleDateString()}${G.me?.name ? ` · ${esc(G.me.name)}` : ""}</p>
    <h2>Results at the query point (${fmt(+p.query.x, 2)}, ${fmt(+p.query.y, 2)})</h2>
    <div class="kv">${kv(`After ${yrs(nowT())}`, `${mm(now.total)} mm`)}${kv(`At design life (${yrs(life())})`, `${mm(fin.total)} mm`)}${kv("Immediate", `${mm(r.immediate)} mm`)}${kv("Primary consolidation", `${mm(r.primary)} mm`)}${kv(`Creep by ${yrs(life())}`, `${mm(fin.secondary)} mm`)}${kv("Largest on the plan", state.grid ? `${mm(state.grid.max)} mm, tilt ${state.grid.tilt > 0 ? `1/${fmt(1 / state.grid.tilt, 0)}` : "none"}` : "–")}</div>
    ${planImg ? `<h2>Plan: total settlement after ${yrs(nowT())} (mm)</h2><img src="${planImg}" alt="Plan of settlement">` : ""}
    <h2>Settlement with time</h2>${timeChart(state.curve, { t: nowT(), now, stages: r.stages })}
    <div class="page"></div>
    <h2>Cross-section A–A′</h2>${sectionView(p, sectionLine(), state.grid, { width: 900, height: 460 }, { titles: true })}
    <h2>Stresses with depth</h2>${depthChart(p, r, "stress")}
    <div class="page"></div>
    <h2>Inputs</h2>
    <p class="rnote">Water table ${fmt(+p.waterTable, 2)} m below ground · ${p.method === "westergaard" ? "Westergaard" : "Boussinesq"} stresses · ${p.subLayers} sub-layers per layer · design life ${yrs(life())}</p>
    <table><thead><tr><th>Layer</th><th>Thickness (m)</th><th>γ / γsat (kN/m³)</th><th>E (kPa)</th><th>ν</th><th>Consolidation</th></tr></thead><tbody>${layerRows}</tbody></table>
    <table style="margin-top:8pt"><thead><tr><th>Load</th><th>Shape</th><th>Centre (m)</th><th>Size</th><th>q (kPa)</th><th>Applied at (yr)</th></tr></thead><tbody>${loadRows}</tbody></table>
    <h2>Results by layer</h2>${panelHTML("layers")}
    <h2>Checks</h2>${c2.length ? `<ul>${c2.map((x) => `<li>${esc(x.text)}</li>`).join("")}</ul>` : `<p>Nothing to flag in the inputs.</p>`}
    <p class="rnote">Verification: ${vok} of ${ver.length} checks against closed-form solutions and hand calculations agree. Methods: Boussinesq / Westergaard stresses (corner method), constrained-modulus immediate settlement, Cc–Cr consolidation with Terzaghi's rate, Cα creep after t95.</p>`;
  window.print();
}
$("#btnReport").addEventListener("click", (ev) => {
  ev.stopPropagation();
  const m = $("#reportMenu"), open = m.classList.toggle("hidden");
  $("#btnReport").setAttribute("aria-expanded", String(!open));
});
document.addEventListener("click", (ev) => { if (!ev.target.closest(".menu-wrap")) $("#reportMenu").classList.add("hidden"); });
$("#reportMenu").addEventListener("click", (ev) => {
  const b = ev.target.closest("[data-report]");
  if (!b) return;
  $("#reportMenu").classList.add("hidden");
  if (b.dataset.report === "pdf") printReport();
  if (b.dataset.report === "csv") csv();
  if (b.dataset.report === "json") download(`${safeName()}.json`, JSON.stringify(state.project, null, 2), "application/json");
});

// ------------------------------------------------------------------ start

const inputs = $("#inputs");
inputs.addEventListener("input", (ev) => { if (ev.target.tagName === "SELECT" || ev.target.type === "checkbox") return; onInput(ev); });
inputs.addEventListener("change", (ev) => { if (ev.target.tagName === "SELECT" || ev.target.type === "checkbox") onInput(ev); });
inputs.addEventListener("click", onClick);
$("#btnUndo").addEventListener("click", () => stepHistory(true));
$("#btnRedo").addEventListener("click", () => stepHistory(false));

document.addEventListener("keydown", (ev) => {
  const typing = ev.target.closest?.("input, textarea, select");
  if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "z" && !typing) { ev.preventDefault(); stepHistory(!ev.shiftKey); return; }
  if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "y" && !typing) { ev.preventDefault(); stepHistory(false); return; }
  if (ev.key === "Escape") { $("#reportMenu").classList.add("hidden"); $("#drawer").classList.add("hidden"); }
});

async function start() {
  let opened = null;
  try {
    if (G.openId) opened = await api(`/projects/${G.openId}`);
    else {
      const { projects } = await api("/projects");
      if (projects.length) opened = await api(`/projects/${projects[0].id}`);
    }
  } catch (e) {
    state.offline = true;
  }
  if (opened) { loadProject(opened); return; }
  let last = null;
  try { last = JSON.parse(localStorage.getItem("geopromax-last") || "null"); } catch (e) { /* none */ }
  state.project = complete(last?.data || { template: "embankment" });
  startOver();
  if (!state.offline) save();
}
start();

export { TEMPLATES };
