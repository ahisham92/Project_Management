// Pontoon — the page: a few inputs on the left, the live design on the right.
// Every change recalculates in a worker and redraws; projects save themselves.
import { complete, sectionDefaults, fingerDefaults } from "../engine/project.js";
import { KIND_NAMES } from "../engine/model.js";
import { REGIONS, REF, STEEL, TIMBER, CORROSION, PHI_GB } from "../engine/codes.js";
import { exportIFC } from "../engine/ifc.js";
import { heelSVG, pileSVG, esc } from "./section.js";

const T = window.__PONTOON || { api: "api", base: "./", static: "static/", openId: null };
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const fx = (v, d = 2) => (Number.isFinite(v) ? (+v.toFixed(d)).toLocaleString(undefined, { maximumFractionDigits: d }) : "–");
const mm = (m) => `${fx(m * 1000, 0)} mm`;

const state = {
  project: null, id: null, version: null, result: null,
  view: "layout", level: "HAT", mode: 2, tab: "checks", open: new Set(), verify: null, offline: false,
};

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
    if (state.result) renderView();
  });
  apply(cur());
})();

// ------------------------------------------------------------------ the inputs

const ICONS = {
  boat: '<path d="M2 12h16l-3 4H5z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/><path d="M10 3v9M10 4l5 6h-5" fill="none" stroke="currentColor" stroke-width="1.5"/>',
  water: '<path d="M1 8c2-2 4-2 6 0s4 2 6 0 4-2 6 0M1 13c2-2 4-2 6 0s4 2 6 0 4-2 6 0" fill="none" stroke="currentColor" stroke-width="1.6"/>',
  pontoon: '<rect x="2" y="7" width="16" height="5" rx="1" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M1 15c2-1.5 4-1.5 6 0s4 1.5 6 0 4-1.5 6 0" fill="none" stroke="currentColor" stroke-width="1.4"/>',
  pile: '<rect x="8" y="2" width="4" height="16" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M2 13h16" stroke="currentColor" stroke-width="1.4" stroke-dasharray="2 2"/>',
  design: '<path d="M4 16l4-4 3 3 6-8" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M13 7h4v4" fill="none" stroke="currentColor" stroke-width="1.8"/>',
};
const icon = (k) => `<svg class="icon" viewBox="0 0 20 20" aria-hidden="true">${ICONS[k] || ""}</svg>`;

const KINDS = [
  ["concrete", "Concrete", '<rect x="4" y="9" width="46" height="10" rx="1.5" fill="currentColor" opacity=".25" stroke="currentColor" stroke-width="2"/><path d="M2 17c4-2 8-2 12 0s8 2 12 0 8-2 12 0 8 2 12 0" fill="none" stroke="#2a78d6" stroke-width="2"/>'],
  ["framed", "Framed", '<rect x="4" y="7" width="46" height="3" fill="currentColor"/><rect x="7" y="11" width="12" height="8" rx="2" fill="currentColor" opacity=".55"/><rect x="35" y="11" width="12" height="8" rx="2" fill="currentColor" opacity=".55"/><path d="M2 17c4-2 8-2 12 0s8 2 12 0 8-2 12 0 8 2 12 0" fill="none" stroke="#2a78d6" stroke-width="2"/>'],
  ["modular", "Modular", '<g fill="currentColor" opacity=".5"><rect x="4" y="10" width="8" height="8" rx="1.5"/><rect x="13" y="10" width="8" height="8" rx="1.5"/><rect x="22" y="10" width="8" height="8" rx="1.5"/><rect x="31" y="10" width="8" height="8" rx="1.5"/><rect x="40" y="10" width="8" height="8" rx="1.5"/></g><path d="M2 17c4-2 8-2 12 0s8 2 12 0 8-2 12 0 8 2 12 0" fill="none" stroke="#2a78d6" stroke-width="2"/>'],
  ["attenuator", "Attenuator", '<rect x="8" y="5" width="38" height="18" rx="1.5" fill="currentColor" opacity=".25" stroke="currentColor" stroke-width="2"/><path d="M2 13c3-3 6-3 8 0M44 14c2-1 4-1 8 0" fill="none" stroke="#2a78d6" stroke-width="2"/>'],
];

const auto = (key) => (p) => {
  const r = state.result;
  if (!r) return "";
  const m = { walkW: r.layout.walkW, fingerW: r.layout.fingerW, fingerL: r.layout.fingerL, glen: r.gangway.length, disp: r.vessel.dispEst };
  return Number.isFinite(m[key]) ? `auto: ${fx(m[key], key === "disp" ? 1 : 2)}` : "";
};

function sectionItems(p) {
  if (p.type === "concrete" || p.type === "attenuator") return [
    { k: "section.D", l: "Depth of the pontoon", u: "m", min: 0.4, max: 3, step: 0.05, slider: true },
    { k: "section.wall", l: "Wall thickness", u: "m", min: 0.03, max: 0.3, step: 0.005 },
    { k: "section.deck", l: "Deck thickness", u: "m", min: 0.05, max: 0.3, step: 0.005 },
    { k: "section.base", l: "Base thickness", u: "m", min: 0.03, max: 0.3, step: 0.005 },
    ...(p.type === "attenuator" ? [{ k: "section.ballast", l: "Concrete ballast in the base", sub: "lowers G, deepens the draft", u: "m", min: 0, max: 1, step: 0.05 }] : []),
    { k: "section.fc", l: "Concrete strength f'c", u: "MPa", min: 32, max: 65, step: 1, picks: [40, 50] },
    { k: "section.mesh", l: "Mesh in deck and base", sub: "SL82 = 252, SL92 = 318, SL102 = 393", u: "mm²/m", min: 100, max: 1500, step: 1, picks: [179, 252, 318, 393] },
    { k: "finger.D", l: "Finger depth", u: "m", min: 0.4, max: 2, step: 0.05 },
  ];
  if (p.type === "framed") return [
    { kind: "seg", k: "section.frame", l: "Frame", options: [["aluminium", "Aluminium"], ["steel", "Galv. steel"], ["timber", "Timber"]] },
    { kind: "seg", k: "section.deck", l: "Decking", options: [["timber", "Timber"], ["composite", "Composite"], ["aluminium", "Aluminium"]] },
    { k: "section.floats", l: "Floats across the walkway", u: "", min: 1, max: 4, step: 1, picks: [1, 2, 3] },
    { k: "section.floatH", l: "Float depth", u: "m", min: 0.2, max: 1.2, step: 0.05, slider: true },
    { k: "section.cover", l: "Floats cover this much of the length", u: "", min: 0.3, max: 1, step: 0.05 },
    { k: "section.frameH", l: "Frame depth above the floats", u: "m", min: 0.05, max: 0.6, step: 0.05 },
    { k: "section.frameMr", l: "Frame bending capacity φMb", sub: "from the supplier", u: "kN·m", min: 5, max: 500, step: 1 },
  ];
  return [
    { k: "section.cube", l: "Cube height", u: "m", min: 0.3, max: 0.6, step: 0.05, picks: [0.4, 0.5] },
    { k: "section.cubeMass", l: "Mass of one 500 × 500 cube", u: "kg", min: 3, max: 15, step: 0.1 },
  ];
}

function spec(p) {
  return [
    { g: "Boats & berths", icon: "boat", open: true, sum: (p) => `${p.layout.berths} × ${p.vessel.L} m ${p.vessel.kind === "yacht" ? "yachts" : "boats"}`, items: [
      { k: "vessel.L", l: "Design boat length", u: "m", min: 6, max: 50, step: 0.5, slider: true, picks: [8, 10, 12, 15, 20, 25] },
      { kind: "seg", k: "vessel.kind", l: "Boats", options: [["motor", "Motor"], ["yacht", "Yacht"]] },
      { k: "layout.berths", l: "Number of berths", u: "", min: 1, max: 200, step: 1, slider: true, picks: [10, 20, 40, 60] },
      { kind: "seg", k: "layout.sides", l: "Berths on", options: [["2", "Both sides"], ["1", "One side"]], num: true },
      { kind: "seg", k: "access", l: "Access (AS 3962 Cl 4.3)", options: [["unrestricted", "Public / marina"], ["restricted", "Private (1–2 boats)"]] },
    ] },
    { g: "Site", icon: "water", open: true, sum: (p) => `HAT ${p.site.HAT} · Hs ${p.site.Hs} m · ${p.site.region}`, items: [
      { kind: "select", k: "site.region", l: "Wind region (AS/NZS 1170.2)", options: Object.keys(REGIONS).filter((k) => k !== "src").map((k) => [k, REGIONS[k].name]) },
      { k: "site.HAT", l: "Highest astronomical tide", u: "m CD", min: 0, max: 12, step: 0.05 },
      { k: "site.LAT", l: "Lowest astronomical tide", u: "m CD", min: -2, max: 2, step: 0.05 },
      { k: "site.seabed", l: "Seabed level", u: "m CD", min: -40, max: 0, step: 0.1, slider: true },
      { k: "site.Hs", l: "Design wave Hs (1 in 50 y)", u: "m", min: 0, max: 3, step: 0.05, slider: true, picks: [0.25, 0.4, 0.6, 1.0] },
      { k: "site.Tp", l: "Wave period Tp", u: "s", min: 1, max: 15, step: 0.1 },
      { k: "site.current", l: "Current", sub: "AS 3962 uses at least 1.0 m/s", u: "m/s", min: 0, max: 4, step: 0.1 },
      { kind: "seg", k: "water", l: "Water", options: [["sea", "Sea (1026 kg/m³)"], ["fresh", "Fresh (1000)"]] },
      { k: "site.surge", l: "Storm surge", u: "m", min: 0, max: 3, step: 0.05 },
      { k: "site.slr", l: "Sea level rise over the life", u: "m", min: 0, max: 1.5, step: 0.05 },
      { k: "site.scour", l: "Scour at the piles", u: "m", min: 0, max: 3, step: 0.1 },
      { kind: "toggle", k: "site.debris", l: "Flood debris (estuary with a catchment)" },
    ] },
    { g: "Pontoon", icon: "pontoon", open: true, sum: (p) => KIND_NAMES[p.type], items: [
      { k: "layout.walkwayWidth", l: "Walkway width", sub: auto("walkW"), u: "m", min: 1.5, max: 8, step: 0.1, blank: true },
      { k: "layout.fingerWidth", l: "Finger width", sub: auto("fingerW"), u: "m", min: 0.6, max: 3, step: 0.1, blank: true },
      { k: "layout.fingerLength", l: "Finger length", sub: auto("fingerL"), u: "m", min: 3, max: 40, step: 0.5, blank: true },
      { k: "layout.moduleLength", l: "Module length", u: "m", min: 3, max: 30, step: 0.5, picks: [10, 12, 15, 20] },
      ...sectionItems(p),
      { k: "section.sdl", l: "Walers, fenders and services", u: "kPa", min: 0, max: 2, step: 0.05 },
      { k: "layout.gangwayLanding", l: "Gangway landing level", u: "m CD", min: -2, max: 12, step: 0.05 },
      { k: "layout.gangwayLength", l: "Gangway length", sub: auto("glen"), u: "m", min: 3, max: 40, step: 0.5, blank: true },
    ] },
    { g: "Piles", icon: "pile", sum: (p) => `${p.piles.type} at ${p.piles.spacing} m · ${p.piles.soil.type}`, items: [
      { kind: "seg", k: "piles.type", l: "Pile", options: [["steel", "Steel tube"], ["concrete", "Precast concrete"], ["timber", "Timber"]] },
      { k: "piles.spacing", l: "Spacing along the walkway", u: "m", min: 3, max: 30, step: 0.5, slider: true, picks: [6, 8, 10, 12, 15] },
      { kind: "toggle", k: "piles.auto", l: "Choose the lightest pile that works" },
      { k: "piles.d", l: "Outside diameter", u: "mm", min: 168, max: 2000, step: 0.1, show: (p) => p.piles.type === "steel" && !p.piles.auto },
      { k: "piles.t", l: "Wall thickness", u: "mm", min: 4, max: 40, step: 0.1, show: (p) => p.piles.type === "steel" && !p.piles.auto },
      { kind: "select", k: "piles.grade", l: "Steel grade", options: Object.entries(STEEL.grades).map(([k, g]) => [k, g.name]), show: (p) => p.piles.type === "steel" },
      { kind: "toggle", k: "piles.coating", l: "Coated or sleeved for the full life (no corrosion loss)", show: (p) => p.piles.type === "steel", bool01: true },
      { kind: "seg", k: "piles.concrete.shape", l: "Section", options: [["square", "Square"], ["round", "Round / spun"]], show: (p) => p.piles.type === "concrete" },
      { k: "piles.concrete.b", l: "Size", u: "mm", min: 250, max: 1200, step: 25, show: (p) => p.piles.type === "concrete" && !p.piles.auto },
      { k: "piles.concrete.bars", l: "Bars", u: "", min: 4, max: 32, step: 4, show: (p) => p.piles.type === "concrete" && !p.piles.auto },
      { k: "piles.concrete.db", l: "Bar size", u: "mm", min: 12, max: 40, step: 4, show: (p) => p.piles.type === "concrete" && !p.piles.auto },
      { k: "piles.concrete.fc", l: "f'c", u: "MPa", min: 40, max: 80, step: 5, show: (p) => p.piles.type === "concrete" },
      { k: "piles.concrete.cover", l: "Cover", u: "mm", min: 30, max: 100, step: 5, show: (p) => p.piles.type === "concrete" },
      { k: "piles.timber.D", l: "Diameter", u: "mm", min: 200, max: 700, step: 10, show: (p) => p.piles.type === "timber" && !p.piles.auto },
      { kind: "select", k: "piles.timber.grade", l: "Stress grade", options: Object.keys(TIMBER.grades).map((k) => [k, k]), show: (p) => p.piles.type === "timber" },
      { k: "piles.timber.phi", l: "Capacity factor φ (AS 1720.1 Table 2.1)", u: "", min: 0.5, max: 0.95, step: 0.05, show: (p) => p.piles.type === "timber" },
      { kind: "seg", k: "piles.soil.type", l: "Ground", options: [["sand", "Sand"], ["clay", "Clay"]] },
      { k: "piles.soil.phi", l: "Friction angle φ'", u: "°", min: 25, max: 42, step: 1, show: (p) => p.piles.soil.type === "sand", picks: [28, 32, 36] },
      { k: "piles.soil.gamma", l: "Submerged unit weight γ'", u: "kN/m³", min: 5, max: 12, step: 0.5, show: (p) => p.piles.soil.type === "sand" },
      { k: "piles.soil.su", l: "Undrained shear strength su", u: "kPa", min: 5, max: 200, step: 1, show: (p) => p.piles.soil.type === "clay", picks: [10, 25, 50, 100] },
      { k: "piles.arr", l: "Average risk rating (AS 2159 Cl 4.3.2)", u: "ARR", min: 1, max: 5, step: 0.1 },
      { k: "piles.embed", l: "Embedment", sub: "blank: the shortest that works", u: "m", min: 1, max: 40, step: 0.5, blank: true },
    ] },
    { g: "Design basis", icon: "design", sum: (p) => `${p.site.life} y · IL ${p.site.importance}`, items: [
      { k: "site.life", l: "Design life", u: "years", min: 5, max: 100, step: 5, picks: [25, 50] },
      { kind: "seg", k: "site.importance", l: "Importance level (AS/NZS 1170.0)", options: [["1", "1"], ["2", "2"], ["3", "3"], ["4", "4"]], num: true },
      { kind: "seg", k: "site.basis", l: "Wind return period", options: [["1170", "AS/NZS 1170.0 Table F2"], ["as3962", "AS 3962 (1 in 50 y)"]] },
      { kind: "seg", k: "design.freeboardSet", l: "Freeboard limits", options: [["as3962", "AS 3962"], ["tmr", "AS 3962 + Qld TMR 375–500 mm"]] },
      { kind: "toggle", k: "design.chine", l: "Opposite chine must stay submerged (Cl 4.12.2)" },
      { k: "design.tiltLimit", l: "Tilt limit under the stability load", sub: "blank: none", u: "°", min: 1, max: 20, step: 0.5, blank: true },
      { k: "vessel.disp", l: "Boat displacement", sub: auto("disp"), u: "t", min: 0.5, max: 500, step: 0.1, blank: true },
      { k: "fender.k", l: "Fender / rubbing strip stiffness", u: "kN/m", min: 50, max: 5000, step: 10 },
      { k: "piles.guideAbove", l: "Guide roller above the deck", u: "m", min: -0.5, max: 1.5, step: 0.05 },
    ] },
  ];
}

function renderInputs() {
  const p = state.project, host = $("#inputs");
  const openNow = new Set($$("details.group[open]", host).map((d) => d.dataset.g));
  const first = !host.dataset.kind || host.dataset.kind !== p.type;
  host.dataset.kind = p.type;
  const kinds = `<div class="kinds" role="group" aria-label="Kind of pontoon">${KINDS.map(([k, n, svg]) =>
    `<button type="button" class="kind" data-kind="${k}" aria-pressed="${p.type === k}"><svg viewBox="0 0 54 28">${svg}</svg>${n}</button>`).join("")}</div>`;
  host.innerHTML = kinds + spec(p).map((G) => {
    const open = first ? G.open : openNow.has(G.g);
    return `<details class="group" data-g="${G.g}" ${open ? "open" : ""}><summary>${icon(G.icon)}${G.g}<span class="sum">${esc(G.sum ? G.sum(p) : "")}</span></summary><div class="group-body">${G.items.map((it) => item(it, p)).join("")}</div></details>`;
  }).join("") + `<p class="note" style="margin:10px 4px">Blank boxes are worked out for you from AS 3962. Type a value to fix it.</p>`;
}

function item(it, p) {
  if (it.show && !it.show(p)) return "";
  const sub = typeof it.sub === "function" ? it.sub(p) : it.sub;
  const lab = `<span class="lab">${esc(it.l || "")}${sub ? `<small data-sub="${it.k}">${esc(sub)}</small>` : ""}</span>`;
  const kind = it.kind || "num";
  if (kind === "num") {
    const v = get(p, it.k), val = v === null || v === undefined ? "" : v;
    return `<div class="f">${lab}<span class="num"><input type="number" inputmode="decimal" data-k="${it.k}" value="${val}" step="${it.step ?? "any"}" ${it.min !== undefined ? `min="${it.min}"` : ""} ${it.max !== undefined ? `max="${it.max}"` : ""} ${it.blank ? 'placeholder="auto"' : ""}><span class="unit">${esc(it.u || "")}</span></span>${it.slider ? `<input type="range" data-k="${it.k}" min="${it.min}" max="${it.max}" step="${it.step}" value="${val}" aria-label="${esc(it.l)}">` : ""}${it.picks ? `<div class="picks" style="grid-column:1/-1">${it.picks.map((v2) => `<button type="button" data-pick="${it.k}" data-v="${v2}">${v2}</button>`).join("")}</div>` : ""}</div>`;
  }
  if (kind === "toggle") return `<label class="toggle"><span>${esc(it.l)}</span><input type="checkbox" data-k="${it.k}" ${it.bool01 ? "data-bool01" : ""} ${get(p, it.k) ? "checked" : ""}></label>`;
  if (kind === "select") {
    const v = String(get(p, it.k));
    return `<div class="f wide">${lab}<select data-k="${it.k}">${it.options.map(([o, n]) => `<option value="${o}" ${String(o) === v ? "selected" : ""}>${esc(n)}</option>`).join("")}</select></div>`;
  }
  if (kind === "seg") {
    const v = String(get(p, it.k));
    return `<div class="f wide">${lab}<div class="seg" role="group">${it.options.map(([o, n]) => `<button type="button" data-seg="${it.k}" data-v="${o}" ${it.num ? "data-num" : ""} aria-pressed="${String(o) === v}">${esc(n)}</button>`).join("")}</div></div>`;
  }
  return "";
}

function onInput(ev) {
  const el = ev.target, p = state.project;
  if (!el.dataset.k) return;
  let v;
  if (el.type === "checkbox") v = el.dataset.bool01 !== undefined ? (el.checked ? 1 : 0) : el.checked;
  else if (el.tagName === "SELECT") v = el.value;
  else v = el.value === "" ? null : +el.value;
  set(p, el.dataset.k, v);
  if (el.type === "range") { const n = el.parentElement.querySelector(`input[type=number][data-k="${el.dataset.k}"]`); if (n) n.value = el.value; }
  if (el.type === "number") { const r = el.parentElement.parentElement.querySelector(`input[type=range][data-k="${el.dataset.k}"]`); if (r && el.value !== "") r.value = el.value; }
  changed(el.type === "checkbox" || el.tagName === "SELECT");
}
function onClick(ev) {
  const b = ev.target.closest("button");
  if (!b) return;
  const p = state.project;
  if (b.dataset.kind && b.dataset.kind !== p.type) { switchKind(b.dataset.kind); return; }
  if (b.dataset.pick) { set(p, b.dataset.pick, +b.dataset.v); changed(true); return; }
  if (b.dataset.seg) { set(p, b.dataset.seg, b.dataset.num !== undefined ? +b.dataset.v : b.dataset.v); changed(true); }
}
function switchKind(kind) {
  const p = state.project;
  state.project = complete({ ...p, type: kind, section: sectionDefaults(kind), finger: fingerDefaults(kind), layout: { ...p.layout, walkwayWidth: null, fingerWidth: null } });
  changed(true);
}

// ------------------------------------------------------------------ calculating

let worker = null, busyId = 0;
function newWorker() {
  if (worker) worker.terminate();
  worker = new Worker(new URL("./worker.js", import.meta.url), { type: "module" });
  worker.onmessage = onWorker;
  worker.onerror = (e) => { setBusy(false); toast("Calculation failed: " + (e.message || "error"), true); };
}
function run(kind) {
  newWorker();
  busyId++;
  worker.postMessage({ id: busyId, kind, project: JSON.parse(JSON.stringify(state.project)) });
}
let calcTimer;
function changed(structural) {
  if (structural) renderInputs(); else refreshSums();
  clearTimeout(calcTimer);
  calcTimer = setTimeout(() => { run("analyse"); setBusy(true, "Calculating…"); }, structural ? 30 : 250);
  scheduleSave();
}
function refreshSums() {
  for (const d of $$("details.group", $("#inputs"))) {
    const G = spec(state.project).find((x) => x.g === d.dataset.g);
    if (G?.sum) d.querySelector(".sum").textContent = G.sum(state.project);
  }
}
function refreshAutos() {
  for (const it of spec(state.project).flatMap((G) => G.items)) {
    if (typeof it.sub !== "function") continue;
    const small = $(`small[data-sub="${it.k}"]`);
    if (small) small.textContent = it.sub(state.project);
  }
}
function setBusy(on, text) {
  $("#busy").classList.toggle("hidden", !on);
  if (text) $("#busyText").textContent = text;
}
function onWorker(ev) {
  const m = ev.data;
  if (m.id !== busyId) return;
  if (m.kind === "done") { state.result = m.result; state.ms = m.ms; setBusy(false); refreshAutos(); renderAll(); }
  else if (m.kind === "check") { state.verify.rows[m.i] = m.res; renderPanel(); }
  else if (m.kind === "verified") { state.verify.done = true; setBusy(false); renderPanel(); }
  else if (m.kind === "error") { setBusy(false); console.error(m.stack); toast("Calculation error: " + m.message, true); }
}

// ------------------------------------------------------------------ the answer

let view3d = null;
async function ensure3D() {
  if (view3d) return view3d;
  try {
    const { View3D } = await import("./view3d.js");
    view3d = new View3D($("#view"));
  } catch (e) {
    console.error(e);
    state.view = "section";
    toast("3D is not available on this device; showing the section.");
  }
  return view3d;
}

async function renderView() {
  const r = state.result, host = $("#view");
  $("#viewMsg").classList.toggle("hidden", !!r);
  $$(".vbtn[data-view]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.view === state.view)));
  $$(".vbtn[data-level]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.level === state.level)));
  $("#levelBtns").classList.toggle("hidden", state.view !== "layout");
  if (!r) return;
  $("svg.section", host)?.remove();
  const flat = state.view === "section" || state.view === "pile";
  if (flat) {
    if (view3d) view3d.renderer.domElement.classList.add("hidden");
    const w = host.clientWidth || 900, h = host.clientHeight || 480;
    host.insertAdjacentHTML("afterbegin", state.view === "section" ? heelSVG(r, state.heelWhich || "finger", { width: w, height: h }) : pileSVG(r, { width: w, height: h }));
  } else {
    const v = await ensure3D();
    if (!v) return renderView();
    v.renderer.domElement.classList.remove("hidden");
    if (state.view === "modes") v.showMode(r, state.mode); else v.showLayout(r, state.level);
  }
  renderVerdict();
  renderLegend();
}

function renderVerdict() {
  const r = state.result, w = r.worst;
  const fails = r.checks.filter((c) => !c.pass);
  const big = w ? (Number.isFinite(w.ratio) ? fx(w.ratio, 2) : "✕") : "–";
  $("#ovVerdict").innerHTML = `<div class="glass verdict ${r.pass ? "pass" : "fail"}">
    <div class="fos">${big}</div>
    <div class="lines"><b>${r.pass ? "Every check passes" : `${fails.length} check${fails.length > 1 ? "s" : ""} not met`}</b><br>
    highest ratio: ${esc(w?.group || "")} · ${esc(w?.name || "")}<br><span class="${r.pass ? "state-good" : "state-critical"}">${esc(r.kindName)} · ${r.checks.length} checks</span></div></div>`;
  const pill = $("#fpill");
  pill.className = `fpill ${r.pass ? "pass" : "fail"}${pill.classList.contains("on") ? " on" : ""}`;
  pill.innerHTML = `<b>${big}</b><span>${esc(w?.name || "")}</span><span>${r.pass ? "✓" : "✕"}</span>`;
}

(() => {
  const pill = $("#fpill"), view = $("#view");
  if (!pill || !view || !("IntersectionObserver" in window)) return;
  new IntersectionObserver(([e]) => pill.classList.toggle("on", !e.isIntersecting), { threshold: 0.15 }).observe(view);
  pill.addEventListener("click", () => view.scrollIntoView({ behavior: "smooth", block: "start" }));
})();

function renderLegend() {
  const r = state.result, sw = (c, t) => `<span><i style="background:${c}"></i>${esc(t)}</span>`;
  let html = "";
  if (state.view === "layout") html = sw("#c9c6bd", r.kindName) + sw("#5b6470", `${r.piles.n} piles`) + sw("#f7f7f5", `${r.layout.berths} boats`) + sw("rgba(42,120,214,.6)", `water at ${state.level} ${fx(r.levels[state.level], 2)} m CD`);
  else if (state.view === "modes") {
    const md = state.mode === "roll" ? { name: "Roll", T: r.dyn.roll } : r.dyn.flex[state.mode];
    html = `<span><b>${esc(md.name)}</b> · natural period ${fx(md.T, md.T < 1 ? 3 : 2)} s · shape exaggerated</span>`;
  } else if (state.view === "section") html = `<span>Show</span>` + ["walkway", "finger"].map((k) => `<button type="button" class="linkish" data-heel="${k}">${k === "walkway" ? "walkway" : "finger"}</button>`).join(" ");
  else html = sw("#eb6834", "bending moment") + sw("#1baf7a", "deflection");
  $("#legend").innerHTML = html;
}

function renderSummary() {
  const r = state.result, L = r.layout, P = r.piles;
  const tile = (k, v, s, ok) => `<div class="case" ${ok === false ? 'style="border-color:var(--critical)"' : ""}><span class="cn">${esc(k)}</span><span class="cf"><b>${v}</b></span><span class="ct">${s}</span></div>`;
  const gr = (g) => r.checks.filter((c) => c.group === g || (g === "Floating" && (c.group === r.floats.walkway.name || c.group === "Finger")));
  const ok = (g) => gr(g).every((c) => c.pass);
  $("#summary").innerHTML = [
    tile("Walkway", `${fx(L.walkW, 1)} × ${fx(L.walkLen, 0)} m`, `${L.modules} modules of ${fx(L.moduleL, 1)} m · freeboard ${mm(r.floats.walkway.freeboardDL)}`, gr(r.floats.walkway.name).every((c) => c.pass)),
    tile("Fingers", `${fx(L.fingerW, 1)} × ${fx(L.fingerL, 1)} m`, `${(L.perSide + 1) * L.sides} fingers · freeboard ${mm(r.floats.finger.freeboardDL)}`, gr("Finger").every((c) => c.pass)),
    tile("Piles", `${P.n} × ${esc(P.ps.desc.split(" ").slice(0, 4).join(" "))}`, `toe ${fx(P.toe, 1)} m CD · embedded ${fx(P.Lreq, 1)} m`, ok("Piles")),
    tile("Gangway", `${fx(r.gangway.length, 1)} m`, `1 : ${fx(1 / r.gangway.slope, 1)} at LAT · ${fx(L.gangwayW, 1)} m clear`, ok("Gangway")),
  ].join("");
}

const TABS = [["checks", "Checks"], ["loads", "Loads"], ["piles", "Piles"], ["motion", "Motion"], ["layout", "Layout & quantities"], ["verify", "Verification"], ["basis", "Design basis"]];
function renderTabs() {
  $("#dtabs").innerHTML = TABS.map(([k, n]) => `<button role="tab" data-tab="${k}" aria-selected="${k === state.tab}">${n}</button>`).join("");
}
function renderPanel() {
  const P = $("#dpanel"), t = state.tab;
  if (!state.result && t !== "verify") { P.innerHTML = ""; return; }
  P.innerHTML = { checks: checksPanel, loads: loadsPanel, piles: pilesPanel, motion: motionPanel, layout: layoutPanel, verify: verifyPanel, basis: basisPanel }[t]();
}
function renderAll() { renderView(); renderSummary(); renderTabs(); renderPanel(); }

const ratioColour = (c) => (c.pass ? (c.ratio > 0.9 ? "var(--warning)" : "var(--good)") : "var(--critical)");
function checksPanel() {
  const r = state.result, groups = [...new Set(r.checks.map((c) => c.group))];
  const advice = r.advice.length ? `<div class="stack">${r.advice.map((a) => `<div class="note-box"><b>${esc(a.src)}.</b> ${esc(a.text)}</div>`).join("")}</div>` : "";
  return advice + groups.map((g) => `<h3 class="ghead">${esc(g)}</h3>` + r.checks.filter((c) => c.group === g).map((c) => {
    const open = state.open.has(c.key), pct = c.ratio === null ? 0 : Math.max(3, Math.min(100, (c.ratio / 1.5) * 100));
    const val = c.ratio === null ? `${fx(c.value, 3)} ${esc(c.unit)}` : `${fx(c.value, 3)} ${esc(c.unit)} ${c.sense === "min" ? "≥" : "≤"} ${fx(c.limit, 3)}`;
    return `<div class="chk ${c.pass ? "" : "bad"}"><button type="button" class="chk-head" data-chk="${esc(c.key)}" aria-expanded="${open}">
      <span class="chk-n">${esc(c.name)}<small>${esc(c.src)}</small></span><span class="chk-v tabular">${val}</span>
      <span class="chk-r">${c.ratio === null ? `<span class="pill">info</span>` : `<span class="bar slim"><span class="bar-fill" style="width:${pct}%;background:${ratioColour(c)}"></span><span class="bar-plan" style="left:${100 / 1.5}%"></span></span><b class="tabular">${Number.isFinite(c.ratio) ? fx(c.ratio, 2) : "✕"}</b>`}</span>
      <span class="pill ${c.pass ? "good" : "bad"}">${c.pass ? "✓" : "✕"}</span></button>
      ${open && c.working.length ? `<ol class="working">${c.working.map((w) => `<li>${esc(w)}</li>`).join("")}</ol>` : ""}${open && c.note ? `<div class="note">${esc(c.note)}</div>` : ""}</div>`;
  }).join("")).join("");
}

function loadsPanel() {
  const r = state.result, w = r.wind, v = r.vessel;
  const rows = r.loads.map((L) => `<tr><td>${esc(L.combo.name)}<br><small class="muted">${esc(L.combo.src)}</small></td><td class="num">${fx(L.level, 2)}</td>
    ${["Y", "X"].map((d) => `<td class="num">${fx(L.dirs[d].wind, 1)}</td><td class="num">${fx(L.dirs[d].current, 1)}</td><td class="num">${fx(L.dirs[d].wave, 1)}</td><td class="num"><b>${fx(L.dirs[d].total, 1)}</b></td>`).join("")}
    <td class="num"><b>${fx(Math.max(L.dirs.X.total, L.dirs.Y.total) / r.piles.n, 1)}</b></td></tr>`).join("");
  return `<div class="kpis">
      <div class="kpi"><div class="k">Wind</div><div class="v">${fx(w.V, 1)} m/s</div><div class="s">VR ${fx(w.VR, 1)} (R = ${w.R} y, region ${esc(r.project.site.region)}) × Mz,cat ${fx(w.Mz, 2)} · q = 0.0006V² = ${fx(w.q, 3)} kPa</div></div>
      <div class="kpi"><div class="k">Current</div><div class="v">${fx(r.loads[0].Vc, 2)} m/s</div><div class="s">p = ½ρv² = ${fx(r.loads[0].pc, 3)} kPa per unit CD</div></div>
      <div class="kpi"><div class="k">Design wave</div><div class="v">H1 ${fx(r.struct.walkway.H1, 2)} m</div><div class="s">1.67 Hs · λ ${fx(r.struct.walkway.lam, 1)} m · Froude–Krylov ${fx(r.loads[0].parts.fk, 2)} kN/m (min 2 kN/m)</div></div>
      <div class="kpi"><div class="k">Berthing</div><div class="v">${fx(r.berth.E, 2)} kJ</div><div class="s">½ M V² Cm: ${fx(v.disp, 1)} t at ${r.berth.V} m/s, Cm ${fx(r.berth.Cm, 2)}</div></div>
    </div>
    <div class="table-scroll mt-sm"><table class="tight"><thead><tr><th rowspan="2">Combination (factored)</th><th rowspan="2" class="num">Level m CD</th><th colspan="4">Across the arm (kN, boats head-on)</th><th colspan="4">Along the arm (kN, boats beam-on)</th><th rowspan="2" class="num">Per pile kN</th></tr>
    <tr><th class="num">wind</th><th class="num">current</th><th class="num">wave</th><th class="num">total</th><th class="num">wind</th><th class="num">current</th><th class="num">wave</th><th class="num">total</th></tr></thead><tbody>${rows}</tbody></table></div>
    <p class="note mt-sm">Wind, current and wave columns are unfactored; totals apply the AS 3962 Cl 4.2 factors. Boats beam-on: the windward boat takes full load and each one behind it 20 % (AS 3962 Cl 4.8.3.3); the same shelter is applied to current, an assumption. Vessel areas from AS 3962 Table 4.4 (${fx(v.windHead, 1)} m² head-on, ${fx(v.windBeam, 1)} m² beam-on); drag coefficients Tables 4.3 and 4.5. The arm is taken as rigid, so the piles share the load equally.</p>`;
}

function pilesPanel() {
  const r = state.result, P = r.piles;
  const rows = P.results.map((c) => `<tr class="${c === P.gov ? "best" : ""}"><td>${esc(c.combo.name)}</td><td class="num">${fx(c.level, 2)}</td><td class="num">${fx(c.e, 2)}</td><td class="num">${fx(c.H, 1)}</td><td class="num">${fx(c.Mmax, 1)}</td><td class="num">${fx(c.resp.zMax, 2)}</td><td class="num">${fx(c.resp.delta * 1000, 0)}</td><td class="num">${fx(c.brom.Hu, 1)}</td><td>${esc(c.brom.mode)}</td></tr>`).join("");
  return `<div class="kpis">
      <div class="kpi"><div class="k">Pile</div><div class="v">${esc(P.ps.desc)}</div><div class="s">${P.auto ? `chosen from ${P.tried} standard sizes` : "as given"}${P.ps.loss ? ` · ${fx(P.ps.loss, 2)} mm corrosion allowed` : ""}</div></div>
      <div class="kpi"><div class="k">Levels</div><div class="v">${fx(P.pileTop, 2)} / ${fx(P.toe, 2)} m CD</div><div class="s">top / toe · embedded ${fx(P.Lreq, 1)} m below the scoured bed</div></div>
      <div class="kpi"><div class="k">Capacities</div><div class="v">φM ${fx(P.ps.phiM, 0)} kN·m</div><div class="s">φV ${fx(P.ps.phiV, 0)} kN · φg ${fx(P.phiG, 2)}</div></div>
      <div class="kpi"><div class="k">Number</div><div class="v">${P.n}</div><div class="s">at ${fx(+r.project.piles.spacing, 1)} m along the walkway</div></div>
    </div>
    <div class="table-scroll mt-sm"><table class="tight"><thead><tr><th>Case</th><th class="num">Level</th><th class="num">e m</th><th class="num">H* kN</th><th class="num">M* kN·m</th><th class="num">at depth m</th><th class="num">head δ mm</th><th class="num">Rd kN</th><th>Broms mode</th></tr></thead><tbody>${rows}</tbody></table></div>
    <p class="note mt-sm">e is the height of the guide above the scoured bed. M* from an elastic pile on a Winkler subgrade (nh after Terzaghi for sand, k = 67su for clay); Rd from Broms with the soil factored by φg and the pile at φM. Open the Pile view above for the diagram.</p>`;
}

function motionPanel() {
  const r = state.result, d = r.dyn;
  const btn = (i, name, Tn) => `<button type="button" class="case" data-mode="${i}" aria-pressed="${state.view === "modes" && String(state.mode) === String(i)}"><span class="cn">${esc(name)}</span><span class="cf"><b>${fx(Tn, Tn < 1 ? 3 : 2)} s</b></span><span class="ct">${fx(1 / Tn, 2)} Hz</span></button>`;
  return `<p class="note">Natural periods of a ${fx(r.layout.moduleL, 1)} m walkway module on the water (free–free beam on the hydrostatic spring, with added mass). Pick one to see it move. The design wave period is ${fx(+r.project.site.Tp, 1)} s.</p>
    <div class="cases mt-sm">${d.flex.map((m, i) => btn(i, m.name, m.T)).join("")}${btn("roll", "Roll", d.roll)}</div>
    <div class="kpis mt-sm">
      <div class="kpi"><div class="k">Arm swaying on its piles</div><div class="v">${fx(d.sway, 2)} s</div><div class="s">${fx(d.Marm, 0)} t with boats, ${r.piles.n} piles</div></div>
      <div class="kpi"><div class="k">Pile alone</div><div class="v">${fx(d.pile[0]?.T, 3)} s</div><div class="s">cantilever in the ground, with entrained water</div></div>
      <div class="kpi"><div class="k">Heave added mass</div><div class="v">${fx(d.ma, 2)} t/m</div><div class="s">ρπB²/8 (flat-bottomed section)</div></div>
    </div>`;
}

function layoutPanel() {
  const r = state.result, L = r.layout, v = r.vessel, p = r.project;
  const fingers = (L.perSide + 1) * L.sides;
  const conc = (p.type === "concrete" || p.type === "attenuator") ? r.floats.walkway.sec.parts.concA * L.walkLen + r.floats.finger.sec.parts.concA * L.fingerL * fingers : null;
  const pileLen = (r.piles.pileTop - r.piles.toe) * r.piles.n;
  const row = (a, b, c = "") => `<tr><td>${esc(a)}</td><td class="num">${b}</td><td>${esc(c)}</td></tr>`;
  return `<div class="table-scroll"><table class="tight"><tbody>
    ${row("Design boat", `${fx(v.L, 1)} m ${v.motor ? "motor" : "yacht"}`, `beam ${fx(v.beam, 2)} m, draught ${fx(v.draught, 2)} m (AS 3962 Tables 3.1, 3.2)`)}
    ${row("Berth width", `${fx(L.berthW, 2)} m`, "beam + 1.0 m (+1.5 m over 20 m), AS 3962 Table 3.2")}
    ${row("Walkway", `${fx(L.walkW, 2)} × ${fx(L.walkLen, 1)} m`, `${L.modules} modules; ${L.auto?.walkwayWidth ? "width: narrowest that passes every floating check" : "width as given"} (Cl 3.5 minimum ${L.walkNeeded > 200 ? 2.4 : L.walkNeeded > 100 ? 1.8 : 1.5} m)`)}
    ${row("Fingers", `${fingers} × ${fx(L.fingerW, 2)} × ${fx(L.fingerL, 1)} m`, `length ≥ 0.8 L (Cl 3.5); ${L.auto?.fingerWidth ? "width: narrowest that passes every floating check" : "width as given"}`)}
    ${row("Gangway", `${fx(r.gangway.length, 1)} m × ${fx(L.gangwayW, 1)} m`, `slope ≤ 1:${L.slope} at LAT; clear width Table 3.3 for ${L.berths} berths`)}
    ${row("Guide piles", `${r.piles.n} × ${fx(r.piles.pileTop - r.piles.toe, 1)} m`, `${r.piles.ps.desc}; ${fx(pileLen, 0)} m in all`)}
    ${conc ? row("Concrete in the pontoons", `${fx(conc, 1)} m³`, "shell only") : ""}
    ${row("Deck area", `${fx(L.walkW * L.walkLen + L.fingerW * L.fingerL * fingers, 0)} m²`, "")}
  </tbody></table></div>`;
}

function verifyPanel() {
  const V = state.verify;
  if (!V) return `<p class="note">Runs every part of the engine against an independent closed-form answer: beam theory, beams on elastic foundations, free–free vibration, hydrostatics and the wall-sided formula, wave theory, AS 4100, AS 3600, Broms, AS/NZS 1170.2 and AS 2159 tables. The same checks run in CI on every change.</p><button type="button" class="btn btn-primary btn-sm mt-sm" data-verify>Run the checks</button>`;
  const done = V.rows.filter(Boolean), ok = done.filter((x) => x.ok).length;
  return `<p><b>${ok} of ${done.length} pass</b>${V.done ? "" : " · running…"}</p>` + done.map((c) => `<div class="chk ${c.ok ? "" : "bad"}"><div class="chk-head"><span class="chk-n">${esc(c.name)}<small>${esc(c.ref)}</small></span><span class="pill ${c.ok ? "good" : "bad"}">${c.ok ? "✓" : "✕"}</span></div>
    <table class="tight"><tbody>${c.rows.map((x) => `<tr><td>${esc(x.what)}</td><td class="num">Pontoon ${fx(x.got, 6)}</td><td class="num">reference ${fx(x.want, 6)}</td><td class="num">${x.err < 1e-12 ? "exact" : `rel. ${x.err.toExponential(1)}`}</td></tr>`).join("")}</tbody></table></div>`).join("");
}

function basisPanel() {
  const r = state.result;
  const flags = [["AS 3962 values", "Clause values are from AS 3962-2001; confirm against your copy of AS 3962:2020."], ["AS 2159 φgb", PHI_GB.src + " — from a secondary source, confirm."], ["Corrosion", CORROSION.src], ["Timber", TIMBER.src], ["Steel plate grade", "Grade 350 plate yield by thickness per AS/NZS 3678; confirm for the mill certificate."]];
  return `<h3 class="ghead">Standards</h3><ul class="plain">${Object.values(REF).map((t) => `<li>${esc(t)}</li>`).join("")}</ul>
    <h3 class="ghead">To confirm before issue</h3><ul class="plain">${flags.map(([a, b]) => `<li><b>${esc(a)}:</b> ${esc(b)}</li>`).join("")}</ul>
    <h3 class="ghead">How it works</h3><ul class="plain">
    <li>Floating checks use the exact immersed shape of the section at any heel (polygon clipping), so they hold beyond small angles. Verification shows they reproduce the wall-sided formula.</li>
    <li>Longitudinal bending uses a finite element beam on the hydrostatic spring (γw × waterplane width). Live load cases are 3 kPa on half the length and 4.5 kN at L/2 and L/4. The wave is H1 = 1.67 Hs passing along the pontoon at 16 phases.</li>
    <li>Lateral loads use AS 3962 Cl 4.2 combinations at HAT + sea level rise, at LAT and, with surge, at the storm level. Berthing is AS 3962 Cl 4.9: perpendicular at the mid-point (Ce = 1) at 0.3 m/s (0.2 m/s over 25 m), with added mass Cm = 1 + 2D/B (PIANC 2002). The energy is shared by the fender and the piles of one module in series.</li>
    <li>Pile actions come from an elastic pile on a Winkler subgrade. Ground resistance is Broms (1964) for free-head piles with the soil factored by φg (AS 2159 Cl 4.3) and the pile at its design moment.</li>
    <li>Natural modes come from the same beam with the consistent mass matrix and heave added mass.</li>
    <li>Revit: the IFC4 file holds IfcSlab pontoons, IfcPile piles and an IfcBeam gangway as extruded solids. Each carries a PT_Design property set with its design results, plus MarineTwin's MT_Common.</li></ul>
    <p class="note">Calculated in ${fx(state.ms, 0)} ms. Pontoon ${esc(T.version || "")}.</p>`;
}

// tabs and view buttons
$("#dtabs").addEventListener("click", (ev) => { const b = ev.target.closest("[data-tab]"); if (!b) return; state.tab = b.dataset.tab; renderTabs(); renderPanel(); });
$("#dpanel").addEventListener("click", (ev) => {
  const c = ev.target.closest("[data-chk]");
  if (c) { const k = c.dataset.chk; state.open.has(k) ? state.open.delete(k) : state.open.add(k); renderPanel(); return; }
  const m = ev.target.closest("[data-mode]");
  if (m) { state.mode = m.dataset.mode === "roll" ? "roll" : +m.dataset.mode; state.view = "modes"; renderView(); renderPanel(); $("#view").scrollIntoView({ behavior: "smooth", block: "nearest" }); return; }
  if (ev.target.closest("[data-verify]")) { state.verify = { rows: [], done: false }; run("verify"); setBusy(true, "Running checks…"); renderPanel(); }
});
$(".ov-tr").addEventListener("click", (ev) => {
  const v = ev.target.closest("[data-view]"), l = ev.target.closest("[data-level]");
  if (v) { state.view = v.dataset.view; renderView(); }
  if (l) { state.level = l.dataset.level; renderView(); }
});
$("#legend").addEventListener("click", (ev) => { const b = ev.target.closest("[data-heel]"); if (b) { state.heelWhich = b.dataset.heel; renderView(); } });

// ------------------------------------------------------------------ projects

async function api(path, opt = {}) {
  const r = await fetch(T.api + path, { credentials: "same-origin", headers: { "Content-Type": "application/json", Accept: "application/json" }, ...opt });
  if (!r.ok) throw Object.assign(new Error((await r.json().catch(() => ({}))).error || r.statusText), { status: r.status });
  return r.json();
}
let saveTimer;
function scheduleSave() {
  $("#saveState").textContent = "Editing…";
  $("#saveState").className = "save-state";
  clearTimeout(saveTimer);
  saveTimer = setTimeout(save, 1200);
}
async function save() {
  const data = JSON.parse(JSON.stringify(state.project));
  try { localStorage.setItem("pontoon-last", JSON.stringify({ id: state.id, data })); } catch (e) { /* private mode */ }
  if (state.offline) { $("#saveState").textContent = "Saved on this device"; return; }
  try {
    const r = state.id ? await api(`/projects/${state.id}`, { method: "PUT", body: JSON.stringify({ data }) }) : await api(`/projects`, { method: "POST", body: JSON.stringify({ data }) });
    state.id = r.id; state.version = r.version;
    history.replaceState(null, "", `${T.base}p/${r.id}`);
    $("#saveState").textContent = "Saved";
    $("#saveState").className = "save-state saved";
  } catch (e) { $("#saveState").textContent = "Not saved: " + e.message; }
}
async function openDrawer() {
  $("#drawer").classList.remove("hidden");
  const list = $("#projList");
  list.innerHTML = `<div class="note">Loading…</div>`;
  try {
    const { projects } = await api("/projects");
    list.innerHTML = projects.length ? projects.map((p) => `<div class="proj ${p.id === state.id ? "current" : ""}" data-open="${p.id}"><span class="pn">${esc(p.name)}</span><span class="pm">${esc(KIND_NAMES[p.kind] || p.kind)} · ${new Date(p.updated * 1000).toLocaleString()}</span><span class="row" style="gap:6px"><button class="linkish" data-dup="${p.id}">Duplicate</button><button class="linkish" data-del="${p.id}">Delete</button></span></div>`).join("")
      : `<div class="note">No projects yet.</div>`;
  } catch (e) { list.innerHTML = `<div class="note">Projects are kept on this device only here (${esc(e.message)}).</div>`; }
}
$("#btnProjects").addEventListener("click", openDrawer);
$("#drawer").addEventListener("click", async (ev) => {
  if (ev.target === $("#drawer") || ev.target.closest("[data-close]")) { $("#drawer").classList.add("hidden"); return; }
  const nw = ev.target.closest("[data-new]");
  if (nw) { newProject(nw.dataset.new); return; }
  const del = ev.target.closest("[data-del]"), dup = ev.target.closest("[data-dup]"), open = ev.target.closest("[data-open]");
  try {
    if (del) {
      ev.stopPropagation();
      if (!confirm("Delete this project? Its earlier versions go with it.")) return;
      await api(`/projects/${del.dataset.del}`, { method: "DELETE" });
      if (+del.dataset.del === state.id) state.id = null;
      openDrawer(); return;
    }
    if (dup) { ev.stopPropagation(); loadProject(await api(`/projects/${dup.dataset.dup}/duplicate`, { method: "POST", body: "{}" })); $("#drawer").classList.add("hidden"); return; }
    if (open) { loadProject(await api(`/projects/${open.dataset.open}`)); $("#drawer").classList.add("hidden"); }
  } catch (e) { toast(e.message, true); }
});
function loadProject(r) {
  state.id = r.id; state.version = r.version;
  state.project = complete(r.data);
  state.result = null;
  $("#projectName").value = state.project.name;
  history.replaceState(null, "", `${T.base}p/${r.id}`);
  $("#saveState").textContent = "Saved"; $("#saveState").className = "save-state saved";
  renderInputs(); run("analyse"); setBusy(true, "Calculating…");
}
function newProject(kind) {
  state.id = null;
  state.project = complete({ type: kind, name: `${KIND_NAMES[kind]} pontoon` });
  state.result = null;
  $("#projectName").value = state.project.name;
  $("#drawer").classList.add("hidden");
  renderInputs(); run("analyse"); save();
}
$("#projectName").addEventListener("input", (ev) => { state.project.name = ev.target.value; scheduleSave(); });

// ------------------------------------------------------------------ IFC and report

function download(name, text, type) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type }));
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
$("#btnIFC").addEventListener("click", () => {
  if (!state.result) return;
  const name = (state.project.name || "pontoon").replace(/[^\w-]+/g, "_");
  download(`${name}.ifc`, exportIFC(state.result, { author: T.me?.name || "" }), "application/x-step");
  toast("IFC saved. In Revit: Insert → Link IFC (or File → Open → IFC).");
});

function reportInputs() {
  const p = state.project;
  return spec(p).map((G) => {
    const rows = G.items.filter((it) => (!it.show || it.show(p)) && it.k).map((it) => {
      let v = get(p, it.k);
      if (v === null || v === undefined || v === "") v = "auto";
      else if (typeof v === "boolean") v = v ? "Yes" : "No";
      else if (it.options) { const o = it.options.find((o) => String(o[0]) === String(v)); v = o ? o[1] : v; }
      else v = `${v} ${it.u || ""}`;
      return `<tr><td>${esc(it.l)}</td><td>${esc(v)}</td></tr>`;
    }).join("");
    return `<tr><th colspan="2" style="text-align:left">${esc(G.g)}</th></tr>${rows}`;
  }).join("");
}
$("#btnReport").addEventListener("click", () => {
  const r = state.result;
  if (!r) return;
  const p = r.project;
  let img = "";
  if (view3d && state.view === "layout") { try { img = `<img src="${view3d.snapshot()}" style="width:100%;max-height:9cm;object-fit:contain">`; } catch (e) { /* none */ } }
  const groups = [...new Set(r.checks.map((c) => c.group))];
  const checks = groups.map((g) => `<h2>${esc(g)}</h2>` + r.checks.filter((c) => c.group === g).map((c) => `<div style="page-break-inside:avoid"><h3>${esc(c.name)} — ${c.ratio === null ? "information" : `ratio ${fx(c.ratio, 3)}`} ${c.pass ? "✓" : "✕"}</h3><p><i>${esc(c.src)}</i>. ${c.ratio === null ? `${fx(c.value, 4)} ${esc(c.unit)}` : `${fx(c.value, 4)} ${esc(c.unit)} ${c.sense === "min" ? "≥" : "≤"} ${fx(c.limit, 4)} ${esc(c.unit)}`}</p>${c.working.length ? `<ol>${c.working.map((w) => `<li>${esc(w)}</li>`).join("")}</ol>` : ""}</div>`).join("")).join("");
  $("#report").innerHTML = `<div class="wrap"><h1>${esc(p.name)} · ${esc(r.kindName)}</h1>
    <p>Pontoon ${esc(T.version || "")} · ${new Date().toLocaleString()}${T.me?.name ? ` · ${esc(T.me.name)}` : ""}</p>
    <h2>Result</h2><p><b>${r.pass ? "Every check passes." : `${r.checks.filter((c) => !c.pass).length} checks are not met.`}</b> Highest ratio ${fx(r.worst?.ratio, 3)}: ${esc(r.worst?.group)} — ${esc(r.worst?.name)}.</p>
    ${r.advice.map((a) => `<p><b>${esc(a.src)}:</b> ${esc(a.text)}</p>`).join("")}
    ${img}<h2>Layout</h2>${layoutPanel()}<h2>Inputs</h2><table>${reportInputs()}</table>
    <div class="page"></div><h2>Loads</h2>${loadsPanel()}<h2>Piles</h2>${pilesPanel()}${pileSVG(r, { width: 900, height: 460 })}
    <div class="page"></div><h2>Stability</h2>${heelSVG(r, "walkway", { width: 900, height: 380 })}${heelSVG(r, "finger", { width: 900, height: 380 })}
    <div class="page"></div><h1>Checks, with working</h1>${checks}
    <div class="page"></div><h2>Natural periods</h2><p>${r.dyn.flex.map((m) => `${esc(m.name)} ${fx(m.T, 3)} s`).join(" · ")} · Roll ${fx(r.dyn.roll, 2)} s · Arm sway ${fx(r.dyn.sway, 2)} s</p>
    <h2>Design basis</h2>${basisPanel()}</div>`;
  setTimeout(() => window.print(), 50);
});

// ------------------------------------------------------------------ start

$("#inputs").addEventListener("input", onInput);
$("#inputs").addEventListener("click", onClick);
window.addEventListener("resize", () => { if (state.view === "section" || state.view === "pile") renderView(); });
document.addEventListener("keydown", (ev) => { if (ev.key === "Escape") $("#drawer").classList.add("hidden"); });

async function start() {
  let opened = null;
  try {
    if (T.openId) opened = await api(`/projects/${T.openId}`);
    else { const { projects } = await api("/projects"); if (projects.length) opened = await api(`/projects/${projects[0].id}`); }
  } catch (e) { state.offline = true; }
  if (opened) { loadProject(opened); return; }
  let last = null;
  try { last = JSON.parse(localStorage.getItem("pontoon-last") || "null"); } catch (e) { /* none */ }
  state.project = complete(last?.data || {});
  $("#projectName").value = state.project.name;
  renderInputs(); renderTabs(); run("analyse"); setBusy(true, "Calculating…");
  if (!state.offline) save();
}
start();
