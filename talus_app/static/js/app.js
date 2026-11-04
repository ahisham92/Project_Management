// Talus — the page: inputs on the left, the live answer on the right.
// Every change recalculates in a worker and redraws; projects save themselves.
import { DEFAULTS, complete, BASES, GROUND_S, armourDesign, parsePoints } from "../engine/project.js";
import { PRESETS, PRESET_KEYS, soilFrom } from "../engine/materials.js";
import { METHOD_NAMES } from "../engine/lem.js";
import { rockArmour, accropode, damageLevels, COEFFS } from "../engine/armour.js";
import { sectionSVG, esc } from "./section.js";
import { fosColour } from "./shapes.js";
import { docx } from "./docx.js";

const T = window.__TALUS || { api: "api", base: "./", static: "static/", openId: null };
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const f2 = (v) => (Number.isFinite(v) ? v.toFixed(2) : "–");
const f3 = (v) => (Number.isFinite(v) ? v.toFixed(3) : "–");
const f1 = (v) => (Number.isFinite(v) ? v.toFixed(1) : "–");
const fmt = (v, d = 2) => (Number.isFinite(v) ? (+v.toFixed(d)).toLocaleString(undefined, { maximumFractionDigits: d }) : "–");
const deg = (cot) => (Math.atan(1 / cot) * 180 / Math.PI);

const state = {
  project: null, id: null, version: null,
  result: null, partial: [], seismic: null, selected: null,
  view: "3d", trials: false, motion: true, tab: "methods",
  verify: null, optimise: null, offline: false, dirty: false,
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
  });
  apply(cur());
})();

// ------------------------------------------------------------------ the inputs

const ICONS = {
  shape: '<path d="M2 15h5l6-9h5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/>',
  ground: '<path d="M2 7h16M2 12h16M2 17h16" stroke="currentColor" stroke-width="1.6"/><circle cx="6" cy="9.5" r="1" fill="currentColor"/><circle cx="13" cy="14.5" r="1" fill="currentColor"/>',
  water: '<path d="M10 2c3 4 5 7 5 9.5A5 5 0 0 1 5 11.5C5 9 7 6 10 2z" fill="none" stroke="currentColor" stroke-width="1.6"/>',
  waves: '<path d="M1 8c2-2 4-2 6 0s4 2 6 0 4-2 6 0M1 13c2-2 4-2 6 0s4 2 6 0 4-2 6 0" fill="none" stroke="currentColor" stroke-width="1.6"/>',
  load: '<path d="M4 3v10M10 3v10M16 3v10" stroke="currentColor" stroke-width="1.6"/><path d="M2 12l2 3 2-3M8 12l2 3 2-3M14 12l2 3 2-3" fill="currentColor"/>',
  quake: '<path d="M1 10h3l2-6 3 12 3-9 2 5 2-2h3" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/>',
  design: '<path d="M4 16l4-4 3 3 6-8" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M13 7h4v4" fill="none" stroke="currentColor" stroke-width="1.8"/>',
  gear: '<circle cx="10" cy="10" r="3" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M10 1v3M10 16v3M1 10h3M16 10h3M3.6 3.6l2.1 2.1M14.3 14.3l2.1 2.1M3.6 16.4l2.1-2.1M14.3 5.7l2.1-2.1" stroke="currentColor" stroke-width="1.6"/>',
};
const icon = (k) => `<svg class="icon" viewBox="0 0 20 20" aria-hidden="true">${ICONS[k] || ""}</svg>`;

const KINDS = [
  ["cut", "Cut slope", '<path d="M2 24h18l14-16h18" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linejoin="round"/><path d="M2 24h18l14-16h18v18H2z" fill="currentColor" opacity=".15"/>'],
  ["embankment", "Embankment", '<path d="M2 24h12l10-14h8l10 14h10" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linejoin="round"/><path d="M14 24l10-14h8l10 14z" fill="currentColor" opacity=".18"/>'],
  ["section", "Any section", '<path d="M2 22h10l6-8h6l6-6h20" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linejoin="round"/><path d="M2 26h50M2 18h14" stroke="currentColor" stroke-width="1.2" stroke-dasharray="3 2" opacity=".6"/>'],
  ["revetment", "Revetment", '<path d="M2 20h14l16-13h20" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linejoin="round"/><path d="M2 15c3-2 6-2 9 0s6 2 9 0" fill="none" stroke="#2a78d6" stroke-width="2"/><circle cx="21" cy="15" r="2" fill="currentColor"/><circle cx="25" cy="12" r="2" fill="currentColor"/><circle cx="29" cy="9" r="2" fill="currentColor"/>'],
];

const soilOptions = (sel, keys = PRESET_KEYS) => keys.map((k) => `<option value="${k}" ${k === sel ? "selected" : ""}>${PRESETS[k].name}</option>`).join("");
const slopeSub = (p, k) => { const c = +get(p, k); return Number.isFinite(c) && c > 0 ? `${deg(c).toFixed(1)}° from horizontal` : ""; };

function earthquakeItems() {
  return [
    { kind: "toggle", k: "seismic.on", l: "Check earthquake" },
    { k: "seismic.ag", l: "Peak ground acceleration ag", sub: "on rock, as a fraction of g", u: "g", min: 0, max: 0.8, step: 0.01, slider: true, show: (p) => p.seismic.on, picks: [0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4] },
    { kind: "select", k: "seismic.ground", l: "Ground type (EN 1998-1)", options: Object.keys(GROUND_S).map((g) => [g, `${g} (S = ${GROUND_S[g]})`]), show: (p) => p.seismic.on },
    { kind: "html", show: (p) => p.seismic.on, html: () => `<div class="note">kh = 0.5·ag·S·ST and kv = ±0.5·kh (EN 1998-5 4.1.3.3). Both directions of kv are checked. Talus also finds the yield acceleration and the Newmark displacement.</div>` },
  ];
}
function loadItems(withNails) {
  const items = [
    { k: "load.q", l: "Surcharge on the crest", sub: "traffic, storage, cranes", u: "kPa", min: 0, max: 100, step: 1, slider: true, picks: [0, 5, 10, 20, 50] },
    { k: "load.setback", l: "Set back from the crest edge", u: "m", min: 0, max: 30, step: 0.5, show: (p) => +p.load.q > 0 },
    { k: "load.width", l: "Loaded width", u: "m", min: 0.5, max: 60, step: 0.5, show: (p) => +p.load.q > 0 },
  ];
  if (withNails) items.push(
    { kind: "toggle", k: "nails.on", l: "Soil nails / anchors" },
    { k: "nails.rows", l: "Rows", u: "", min: 1, max: 12, step: 1, show: (p) => p.nails.on },
    { k: "nails.length", l: "Length", u: "m", min: 1, max: 30, step: 0.5, show: (p) => p.nails.on },
    { k: "nails.angle", l: "Inclination below horizontal", u: "°", min: 0, max: 45, step: 1, show: (p) => p.nails.on },
    { k: "nails.T", l: "Tensile capacity per row", sub: "per metre run of slope", u: "kN/m", min: 0, max: 1000, step: 5, show: (p) => p.nails.on },
    { k: "nails.qb", l: "Pull-out resistance", sub: "per metre of nail beyond the slip, per metre run", u: "kN/m²", min: 0, max: 500, step: 5, show: (p) => p.nails.on },
  );
  return items;
}
function designItems() {
  return [
    { kind: "seg", k: "design.basis", l: "Design basis", options: [["fos", "Factor of safety"], ["ec7", "Eurocode 7"]], onChange: (p) => { p.design.targets = null; } },
    { kind: "select", k: "design.method", l: "Governing method", options: [["mp", "Morgenstern-Price"], ["spencer", "Spencer"], ["bishop", "Bishop simplified"], ["janbuCorrected", "Janbu corrected"], ["ordinary", "Ordinary (Fellenius)"]] },
    { kind: "targets" },
  ];
}
function advancedItems(crack = true) {
  const it = [
    { k: "advanced.slices", l: "Slices", sub: "plus every geometric break", u: "", min: 10, max: 200, step: 5 },
    { kind: "toggle", k: "advanced.noncircular", l: "Also search non-circular surfaces" },
    { kind: "toggle", k: "advanced.block", l: "Also search blocks along weak layers", sub: "wedges sliding just inside each lower layer or on the hard base" },
  ];
  if (crack) it.push({ k: "advanced.crack", l: "Tension crack depth", u: "m", min: 0, max: 10, step: 0.1 });
  return it;
}

const bermsOn = (p) => !!p.geom.berms?.on;
const bermRows = (p) => p.geom.berms?.rows || [];
const bermTotal = (p) => bermRows(p).reduce((a, r) => a + (+r.h || 0), 0);
const shapeSum = (p) => bermsOn(p)
  ? `${bermRows(p).length} benches · ${+bermTotal(p).toFixed(2)} m`
  : `${p.geom.H} m · 1:${p.geom.cot}`;
/** Turning berms on splits the present slope into two benches with a 4 m berm. */
function startBerms(p) {
  if (!p.geom.berms) p.geom.berms = { on: false, rows: [] };
  if (p.geom.berms.on && !bermRows(p).length) {
    const h = Math.round((+p.geom.H || 6) / 2 * 100) / 100, c = +p.geom.cot || 2;
    p.geom.berms.rows = [{ h, cot: c, berm: 4 }, { h, cot: c, berm: 0 }];
  }
  if (!p.geom.berms.on && bermRows(p).length) {
    // back to one slope: keep the height and the overall steepness
    const H = bermTotal(p), run = bermRows(p).reduce((a, r, i, R) => a + r.h * r.cot + (i < R.length - 1 ? +r.berm || 0 : 0), 0);
    p.geom.H = +H.toFixed(2); p.geom.cot = +(run / H).toFixed(2);
  }
}
function shapeItems(heightLabel, cotLabel, cotOpt) {
  return [
    { k: "geom.H", l: heightLabel, u: "m", min: 1, max: 40, step: 0.25, slider: true, show: (p) => !bermsOn(p) },
    { k: "geom.cot", l: cotLabel, sub: (p) => slopeSub(p, "geom.cot"), u: "H/V", step: 0.05, slider: true, ...cotOpt, show: (p) => !bermsOn(p) },
    { kind: "toggle", k: "geom.berms.on", l: "Benches with berms", onChange: startBerms },
    { kind: "benches", show: bermsOn },
  ];
}

const SPEC = {
  cut: [
    { g: "Shape", icon: "shape", open: true, sum: shapeSum, items: [
      ...shapeItems("Height of the cut", "Slope 1 : n", { min: 0.25, max: 5, picks: [0.5, 1, 1.5, 2, 2.5, 3] }),
      { k: "geom.base", l: "Firm stratum below the toe", sub: "how deep a slip can go", u: "m", min: 1, max: 60, step: 0.5 },
    ] },
    { g: "Ground", icon: "ground", open: true, sum: (p) => soilFrom(p.soil).name, items: [
      { kind: "soil", k: "soil", l: "Soil" },
      { kind: "toggle", k: "lower.on", l: "A different layer below" },
      { k: "lower.depth", l: "Its top, below the crest", u: "m", min: 0.5, max: 40, step: 0.5, show: (p) => p.lower.on },
      { kind: "soil", k: "lower", l: "Lower layer", show: (p) => p.lower.on },
    ] },
    { g: "Groundwater", icon: "water", sum: (p) => (p.water.on ? `${p.water.back} m below crest` : "dry"), items: [
      { kind: "toggle", k: "water.on", l: "Groundwater" },
      { k: "water.back", l: "Depth below the crest edge", sub: "level behind it, falling under the face to the toe", u: "m", min: 0, max: 40, step: 0.25, slider: true, show: (p) => p.water.on },
      { k: "water.front", l: "Depth below the toe level", u: "m", min: 0, max: 20, step: 0.25, show: (p) => p.water.on },
    ] },
    { g: "Loads", icon: "load", sum: (p) => `${p.load.q} kPa${p.nails?.on ? " · nails" : ""}`, items: loadItems(true) },
    { g: "Earthquake", icon: "quake", sum: (p) => (p.seismic.on ? `ag ${p.seismic.ag} g` : "off"), items: earthquakeItems() },
    { g: "Design", icon: "design", sum: (p) => (p.design.basis === "ec7" ? "EC7" : "FoS") + " · " + (METHOD_NAMES[p.design.method] || "").split(" ")[0], items: designItems() },
    { g: "Advanced", icon: "gear", items: advancedItems() },
  ],
  embankment: [
    { g: "Shape", icon: "shape", open: true, sum: shapeSum, items: [
      ...shapeItems("Height", "Side slopes 1 : n", { min: 1, max: 6, picks: [1.5, 2, 2.5, 3, 4] }),
      { k: "geom.crest", l: "Crest width", u: "m", min: 1, max: 60, step: 0.5 },
      { k: "geom.base", l: "Firm stratum below ground", u: "m", min: 1, max: 60, step: 0.5 },
    ] },
    { g: "Ground", icon: "ground", open: true, sum: (p) => `${soilFrom(p.fill).name} on ${soilFrom(p.soil).name.toLowerCase()}`, items: [
      { kind: "soil", k: "fill", l: "Embankment fill" },
      { kind: "soil", k: "soil", l: "Foundation soil" },
    ] },
    { g: "Water", icon: "water", sum: (p) => (p.water.on ? `${p.water.level} m held on the left` : "none"), items: [
      { kind: "toggle", k: "water.on", l: "Water held against it (river, canal, pond)" },
      { k: "water.level", l: "Water level above ground", u: "m", min: 0, max: 30, step: 0.25, slider: true, show: (p) => p.water.on },
      { k: "water.low", l: "Level after a rapid drawdown", u: "m", min: 0, max: 30, step: 0.25, show: (p) => p.water.on },
    ] },
    { g: "Loads", icon: "load", sum: (p) => `${p.load.q} kPa`, items: loadItems(false) },
    { g: "Earthquake", icon: "quake", sum: (p) => (p.seismic.on ? `ag ${p.seismic.ag} g` : "off"), items: earthquakeItems() },
    { g: "Design", icon: "design", sum: (p) => (p.design.basis === "ec7" ? "EC7" : "FoS"), items: designItems() },
    { g: "Advanced", icon: "gear", items: advancedItems() },
  ],
  section: [
    { g: "Section", icon: "shape", open: true, sum: (p) => `${parsePoints(p.ground).length} ground points`, items: [
      { kind: "points", k: "ground", l: "Ground surface", sub: "x, y per line, left to right. Paste from Excel or CAD." },
      { k: "base", l: "Hard base level", sub: "no slip goes below it", u: "m", step: 0.5 },
    ] },
    { g: "Layers", icon: "ground", open: true, sum: (p) => `${(p.layers || []).length} layers`, items: [{ kind: "layers" }] },
    { g: "Water", icon: "water", sum: (p) => ({ none: "none", line: "water line", ru: `ru ${p.water.ru}` }[p.water.mode] || ""), items: [
      { kind: "seg", k: "water.mode", l: "Pore water", options: [["none", "None"], ["line", "Water line"], ["ru", "ru"]] },
      { kind: "points", k: "water.line", l: "Piezometric line", sub: "x, y per line. Above the ground it is ponded water.", show: (p) => p.water.mode === "line" },
      { kind: "html", show: (p) => p.water.mode === "line", html: () => `<button type="button" class="linkish" data-copy-ground>Put the water at the ground surface</button>` },
      { k: "water.ru", l: "Pore pressure ratio ru", u: "", min: 0, max: 1, step: 0.05, show: (p) => p.water.mode === "ru" },
    ] },
    { g: "Loads", icon: "load", sum: (p) => `${p.load.q} kPa`, items: [
      { k: "load.q", l: "Surcharge", u: "kPa", min: 0, max: 200, step: 1, slider: true, picks: [0, 5, 10, 20, 50] },
      { k: "load.x1", l: "From x", u: "m", step: 0.5, show: (p) => +p.load.q > 0 },
      { k: "load.x2", l: "To x", u: "m", step: 0.5, show: (p) => +p.load.q > 0 },
    ] },
    { g: "Earthquake", icon: "quake", sum: (p) => (p.seismic.on ? `ag ${p.seismic.ag} g` : "off"), items: earthquakeItems() },
    { g: "Design", icon: "design", sum: (p) => (p.design.basis === "ec7" ? "EC7" : "FoS") + " · " + (METHOD_NAMES[p.design.method] || "").split(" ")[0], items: designItems() },
    { g: "Advanced", icon: "gear", items: advancedItems() },
  ],
  revetment: [
    { g: "Shape", icon: "shape", open: true, sum: (p) => `+${p.geom.crest} to ${p.geom.toe} · 1:${p.geom.cot}`, items: [
      { k: "geom.crest", l: "Crest level", u: "m", min: -5, max: 20, step: 0.1, slider: true },
      { k: "geom.toe", l: "Seabed level at the toe", u: "m", min: -30, max: 5, step: 0.1, slider: true },
      { k: "geom.cot", l: "Armour slope 1 : n", sub: (p) => slopeSub(p, "geom.cot"), u: "H/V", min: 1.33, max: 5, step: 0.01, slider: true, picks: [1.33, 1.5, 2, 2.5, 3] },
      { k: "geom.berm", l: "Crest width", u: "m", min: 2, max: 60, step: 0.5 },
      { k: "geom.base", l: "Firm stratum below the seabed", u: "m", min: 1, max: 60, step: 0.5 },
    ] },
    { g: "Waves & armour", icon: "waves", open: true, sum: (p) => `Hs ${p.waves.Hs} m · ${armourName(p.armour.type)}`, items: [
      { k: "waves.Hs", l: "Design wave height Hs", u: "m", min: 0.2, max: 12, step: 0.05, slider: true },
      { k: "waves.Tp", l: "Peak period Tp", u: "s", min: 2, max: 25, step: 0.1, slider: true },
      { k: "waves.hours", l: "Storm duration", u: "h", min: 1, max: 48, step: 0.5 },
      { kind: "seg", k: "armour.type", l: "Armour", options: [["rock", "Rock"], ["accropode1", "Accropode™"], ["accropode2", "Accropode™ II"]],
        onChange: (p) => { if (p.armour.type !== "rock" && (+p.geom.cot < 1.33 || +p.geom.cot > 1.5)) { p.geom.cot = 1.5; toast("Interlocking units sit on 4:3 to 3:2 slopes, so the slope is now 1:1.5."); } } },
      { kind: "select", k: "armour.P", l: "What is under the armour", options: [["0.1", "Impermeable (clay, geotextile on sand) P 0.1"], ["0.4", "Filter on permeable core P 0.4"], ["0.5", "Homogeneous rock P 0.5"], ["0.6", "Armour on rock core P 0.6"]], show: (p) => p.armour.type === "rock" },
      { k: "armour.rhoR", l: "Rock density", u: "kg/m³", min: 2300, max: 3200, step: 10, show: (p) => p.armour.type === "rock" },
      { k: "armour.rhoC", l: "Concrete density", u: "kg/m³", min: 2200, max: 2800, step: 10, show: (p) => p.armour.type !== "rock" },
      { kind: "seg", k: "waves.section", l: "Part of the structure", options: [["trunk", "Trunk"], ["head", "Head / roundhead"]], show: (p) => p.armour.type !== "rock" },
      { k: "waves.seabed", l: "Seabed slope in front", u: "m/m", min: 0, max: 0.2, step: 0.005 },
    ] },
    { g: "Water levels", icon: "water", sum: (p) => `HWL ${p.water.HWL} · LWL ${p.water.LWL}`, items: [
      { k: "water.HWL", l: "High water level (design)", u: "m", min: -10, max: 15, step: 0.05, slider: true },
      { k: "water.LWL", l: "Low water level", u: "m", min: -10, max: 15, step: 0.05, slider: true },
      { k: "water.inside", l: "Water inside during drawdown", sub: "blank: from how freely the core drains", u: "m", min: -20, max: 20, step: 0.05, blank: true },
      { k: "water.gw", l: "Unit weight of water", u: "kN/m³", min: 9.7, max: 10.3, step: 0.01, picks: [9.81, 10.05] },
    ] },
    { g: "Ground", icon: "ground", sum: (p) => `${soilFrom(p.core).name} on ${soilFrom(p.soil).name.toLowerCase()}`, items: [
      { kind: "soil", k: "core", l: "Core / backfill" },
      { kind: "soil", k: "soil", l: "Seabed soil" },
    ] },
    { g: "Loads", icon: "load", sum: (p) => `${p.load.q} kPa`, items: loadItems(false) },
    { g: "Earthquake", icon: "quake", sum: (p) => (p.seismic.on ? `ag ${p.seismic.ag} g` : "off"), items: earthquakeItems() },
    { g: "Design", icon: "design", sum: (p) => (p.design.basis === "ec7" ? "EC7" : "FoS"), items: designItems() },
    { g: "Advanced", icon: "gear", items: advancedItems(false) },
  ],
};

const armourName = (t) => ({ rock: "rock", accropode1: "Accropode", accropode2: "Accropode II" }[t] || t);

function renderInputs() {
  const p = state.project;
  const host = $("#inputs");
  const openNow = new Set($$("details.group[open]", host).map((d) => d.dataset.g));
  const first = !host.dataset.kind || host.dataset.kind !== p.type;
  host.dataset.kind = p.type;
  const kinds = `<div class="kinds" role="group" aria-label="Kind of slope">${KINDS.map(([k, n, svg]) =>
    `<button type="button" class="kind" data-kind="${k}" aria-pressed="${p.type === k}"><svg viewBox="0 0 54 28">${svg}</svg>${n}</button>`).join("")}</div>`;
  const groups = SPEC[p.type].map((G) => {
    const open = first ? G.open : openNow.has(G.g);
    return `<details class="group" data-g="${G.g}" ${open ? "open" : ""}><summary>${icon(G.icon)}${G.g}<span class="sum">${G.sum ? esc(G.sum(p)) : ""}</span></summary><div class="group-body">${G.items.map((it) => item(it, p)).join("")}</div></details>`;
  }).join("");
  host.innerHTML = kinds + groups;
}

function item(it, p) {
  if (it.show && !it.show(p)) return "";
  const sub = typeof it.sub === "function" ? it.sub(p) : it.sub;
  const lab = `<span class="lab">${esc(it.l || "")}${sub ? `<small>${esc(sub)}</small>` : ""}</span>`;
  const kind = it.kind || "num";
  if (kind === "num") {
    const v = get(p, it.k);
    const val = v === null || v === undefined ? "" : v;
    return `<div class="f">${lab}<span class="num"><input type="number" inputmode="decimal" data-k="${it.k}" value="${val}" step="${it.step ?? "any"}" ${it.min !== undefined ? `min="${it.min}"` : ""} ${it.max !== undefined ? `max="${it.max}"` : ""} ${it.blank ? 'placeholder="auto"' : ""}><span class="unit">${esc(it.u || "")}</span></span>${it.slider ? `<input type="range" data-k="${it.k}" min="${it.min}" max="${it.max}" step="${it.step}" value="${val}" aria-label="${esc(it.l)}">` : ""}${it.picks ? `<div class="picks" style="grid-column:1/-1">${it.picks.map((v2) => `<button type="button" data-pick="${it.k}" data-v="${v2}">${v2}</button>`).join("")}</div>` : ""}</div>`;
  }
  if (kind === "toggle") return `<label class="toggle"><span>${esc(it.l)}</span><input type="checkbox" data-k="${it.k}" ${get(p, it.k) ? "checked" : ""}></label>`;
  if (kind === "select") {
    const v = String(get(p, it.k));
    return `<div class="f wide">${lab}<select data-k="${it.k}">${it.options.map(([o, n]) => `<option value="${o}" ${String(o) === v ? "selected" : ""}>${esc(n)}</option>`).join("")}</select></div>`;
  }
  if (kind === "seg") {
    const v = String(get(p, it.k));
    return `<div class="f wide">${lab}<div class="seg" role="group">${it.options.map(([o, n]) => `<button type="button" data-seg="${it.k}" data-v="${o}" aria-pressed="${String(o) === v}">${esc(n)}</button>`).join("")}</div></div>`;
  }
  if (kind === "html") return it.html(p);
  if (kind === "soil") return soilWidget(it, p);
  if (kind === "targets") return targetsWidget(p);
  if (kind === "benches") return benchesWidget(p);
  if (kind === "points") {
    const v = get(p, it.k) ?? "";
    const n = parsePoints(v).length;
    return `<div class="f wide">${lab}<textarea class="pts" data-k="${it.k}" rows="${Math.min(10, Math.max(3, String(v).split("\n").length + 1))}" spellcheck="false" aria-label="${esc(it.l)}">${esc(v)}</textarea><span class="note" data-ptcount="${it.k}">${n} points</span></div>`;
  }
  if (kind === "layers") return layersWidget(p);
  return "";
}

function soilWidget(it, p) {
  const spec = get(p, it.k) || {};
  const s = soilFrom(spec);
  const editing = spec._edit;
  const val = (k) => (spec[k] !== undefined && spec[k] !== null && spec[k] !== "" ? spec[k] : "");
  const ph = (k) => PRESETS[s.preset]?.[k] ?? "";
  const fld = (k, l, u, show = true) => (show ? `<div class="f"><span class="lab">${l}</span><span class="num"><input type="number" inputmode="decimal" data-k="${it.k}.${k}" value="${val(k)}" placeholder="${ph(k)}" step="any"><span class="unit">${u}</span></span></div>` : "");
  return `<div class="f wide"><span class="lab">${esc(it.l)}</span><select data-soil="${it.k}">${soilOptions(s.preset)}</select>
    <div class="soil-sum"><span><b>γ</b> ${s.gamma}/${s.gsat} kN/m³</span><span><b>c'</b> ${s.c} kPa</span><span><b>φ'</b> ${s.phi}°</span>${s.clay && s.su > 0 ? `<span><b>su</b> ${s.su}${s.suGrad ? ` + ${s.suGrad}/m` : ""} kPa</span>` : ""}
    <button type="button" class="linkish" data-soiledit="${it.k}">${editing ? "Done" : "Use site values"}</button></div>
    ${editing ? `<div class="subgrid">${fld("gamma", "Unit weight above water γ", "kN/m³")}${fld("gsat", "Saturated unit weight γsat", "kN/m³")}${fld("c", "Effective cohesion c'", "kPa")}${fld("phi", "Effective friction angle φ'", "°")}${fld("su", "Undrained strength su (clays)", "kPa", s.clay || it.alwaysSu)}${fld("suGrad", "su increase with depth", "kPa/m", s.clay || it.alwaysSu)}${fld("suMax", "su cap", "kPa", it.alwaysSu)}<div class="note">Blank fields keep the typical value shown. Typical values are a starting point; use site data for design.</div></div>` : ""}</div>`;
}

function layersWidget(p) {
  const L = p.layers || [];
  const cards = L.map((layer, i) => {
    const soil = soilWidget({ k: `layers.${i}.soil`, l: "Material", alwaysSu: true }, p);
    const top = i === 0 ? `<div class="note">Its top is the ground surface.</div>`
      : `<div class="f wide"><span class="lab">Top of this layer<small>x, y per line; it carries on flat to both ends</small></span><textarea class="pts" data-k="layers.${i}.top" rows="3" spellcheck="false">${esc(layer.top || "")}</textarea></div>`;
    return `<div class="bench"><div class="bench-head"><input class="lname" type="text" data-k="layers.${i}.soil.name" value="${esc(layer.soil?.name || "")}" placeholder="Layer ${i + 1}" aria-label="Layer name" maxlength="40">
      ${L.length > 1 ? `<button type="button" class="linkish" data-layer-del="${i}">Remove</button>` : ""}</div>${soil}${top}</div>`;
  }).join("");
  return `<div class="f wide"><span class="lab">From the top down<small>each layer lies below its top line and above the next one</small></span>${cards}
    <button type="button" class="btn btn-ghost btn-sm" data-layer-add>Add a layer</button></div>`;
}

function benchesWidget(p) {
  const rows = bermRows(p), n = rows.length;
  const fld = (i, k, l, u, step) => `<div class="f"><span class="lab">${l}</span><span class="num"><input type="number" inputmode="decimal" step="${step}" min="0" data-k="geom.berms.rows.${i}.${k}" value="${rows[i][k] ?? ""}"><span class="unit">${u}</span></span></div>`;
  const body = rows.map((r, i) => `<div class="bench">
      <div class="bench-head"><b>${n === 1 ? "Slope" : i === 0 ? "Top bench" : i === n - 1 ? "Bottom bench" : `Bench ${i + 1}`}</b>${n > 1 ? `<button type="button" class="linkish" data-bench-del="${i}">Remove</button>` : ""}</div>
      ${fld(i, "h", "Height", "m", 0.05)}${fld(i, "cot", "Slope 1 : n", "H/V", 0.05)}
      ${i < n - 1 ? fld(i, "berm", "Berm at its foot", "m", 0.5) : ""}</div>`).join("");
  return `<div class="f wide"><span class="lab">From the crest down<small data-bench-total>${+bermTotal(p).toFixed(2)} m high in all</small></span>${body}
    <button type="button" class="btn btn-ghost btn-sm" data-bench-add>Add a bench</button></div>`;
}

function targetsWidget(p) {
  const base = BASES[p.design.basis] || BASES.fos;
  const t = { ...base.targets, ...(p.design.targets || {}) };
  const row = (k, l) => `<div class="f"><span class="lab">${l}</span><span class="num"><input type="number" step="0.05" min="0.5" max="3" data-target="${k}" value="${t[k]}"><span class="unit">F</span></span></div>`;
  return `<div class="note">${esc(base.name)}${p.design.basis === "ec7" ? ": strengths divided by γφ' = γc' = 1.25, γcu = 1.4; variable loads × 1.3; the over-design factor must reach 1.0." : "."}</div>
    ${row("static", "Long term / steady")}${row("short", "Short term / end of construction")}${row("transient", "Drawdown / transient")}${row("seismic", "Seismic")}`;
}

// input events
const inputsEl = () => $("#inputs");
function onInput(ev) {
  const el = ev.target;
  const p = state.project;
  if (el.dataset.k) {
    let v;
    if (el.type === "checkbox") v = el.checked;
    else if (el.tagName === "SELECT" || el.tagName === "TEXTAREA" || el.type === "text") v = el.value;
    else v = el.value === "" ? null : +el.value;
    set(p, el.dataset.k, v);
    for (const G of SPEC[p.type]) for (const it of G.items) if (it.k === el.dataset.k && it.onChange) it.onChange(p);
    if (el.type === "range") { const n = el.parentElement.querySelector(`input[type=number][data-k="${el.dataset.k}"]`); if (n) n.value = el.value; }
    if (el.type === "number") { const r = el.parentElement.parentElement.querySelector(`input[type=range][data-k="${el.dataset.k}"]`); if (r && el.value !== "") r.value = el.value; }
    if (el.tagName === "TEXTAREA") { const c = $(`[data-ptcount="${el.dataset.k}"]`, inputsEl()); if (c) c.textContent = `${parsePoints(el.value).length} points`; }
    const structural = el.type === "checkbox" || el.tagName === "SELECT";
    changed(structural);
  } else if (el.dataset.soil) {
    const old = get(p, el.dataset.soil) || {};
    set(p, el.dataset.soil, { preset: el.value, _edit: old._edit, ...(old.name ? { name: old.name } : {}) });
    changed(true);
  } else if (el.dataset.target) {
    p.design.targets = { ...(p.design.targets || {}), [el.dataset.target]: +el.value };
    changed(false);
  }
}
function onClick(ev) {
  const b = ev.target.closest("button");
  if (!b) return;
  const p = state.project;
  if (b.dataset.kind && b.dataset.kind !== p.type) { switchKind(b.dataset.kind); return; }
  if (b.dataset.pick) { set(p, b.dataset.pick, +b.dataset.v); changed(true); return; }
  if (b.dataset.seg) {
    const v = b.dataset.v;
    set(p, b.dataset.seg, v);
    for (const G of SPEC[p.type]) for (const it of G.items) if (it.k === b.dataset.seg && it.onChange) it.onChange(p);
    changed(true); return;
  }
  if (b.dataset.layerAdd !== undefined) {
    const L = p.layers || (p.layers = []);
    const pts = parsePoints(p.ground);
    const x0 = pts[0]?.[0] ?? 0, x1 = pts[pts.length - 1]?.[0] ?? 50;
    const prev = L.length > 1 ? parsePoints(L[L.length - 1].top) : null;
    const y = prev?.length ? prev[0][1] - 3 : Math.min(...pts.map((q) => q[1])) - 3;
    L.push({ soil: { preset: "stiffClay", name: `Layer ${L.length + 1}` }, top: `${x0}, ${y}\n${x1}, ${y}` });
    changed(true); return;
  }
  if (b.dataset.layerDel !== undefined) { p.layers.splice(+b.dataset.layerDel, 1); changed(true); return; }
  if (b.dataset.copyGround !== undefined) { p.water.line = p.ground; changed(true); return; }
  if (b.dataset.benchAdd !== undefined) {
    const rows = bermRows(p), last = rows[rows.length - 1] || { h: 3, cot: 2 };
    if (rows.length) rows[rows.length - 1].berm = rows[rows.length - 1].berm || 4;
    rows.push({ h: last.h, cot: last.cot, berm: 0 });
    p.geom.berms.rows = rows; changed(true); return;
  }
  if (b.dataset.benchDel !== undefined) {
    p.geom.berms.rows.splice(+b.dataset.benchDel, 1);
    if (!p.geom.berms.rows.length) { p.geom.berms.on = false; }
    changed(true); return;
  }
  if (b.dataset.soiledit) { const s = get(p, b.dataset.soiledit) || {}; s._edit = !s._edit; set(p, b.dataset.soiledit, s); renderInputs(); }
}

function switchKind(kind) {
  const keepName = state.project.name && !Object.values(DEFAULTS).some((d) => d.name === state.project.name);
  const keep = { seismic: state.project.seismic, design: { ...state.project.design, targets: null } };
  state.project = complete({ type: kind, ...keep, name: keepName ? state.project.name : DEFAULTS[kind].name });
  $("#projectName").value = state.project.name;
  state.selected = null;
  changed(true);
}

// ------------------------------------------------------------------ calculating

let worker = null, busyId = 0, jobRunning = false;
function newWorker() {
  if (worker) worker.terminate();
  worker = new Worker(new URL("./worker.js", import.meta.url), { type: "module" });
  worker.onmessage = onWorker;
  worker.onerror = (e) => { setBusy(false); toast("Calculation failed: " + (e.message || "error"), true); };
}
function run(kind, extra = {}) {
  if (jobRunning || !worker) newWorker();
  busyId++;
  jobRunning = true;
  worker.postMessage({ id: busyId, kind, project: strip(state.project), ...extra });
  return busyId;
}
function strip(p) { return JSON.parse(JSON.stringify(p, (k, v) => (k === "_edit" ? undefined : v))); }

let calcTimer;
function changed(structural) {
  if (structural) renderInputs(); else refreshSums();
  clearTimeout(calcTimer);
  calcTimer = setTimeout(analyse, structural ? 30 : 220);
  scheduleSave();
}
function refreshSums() {
  const bt = $("[data-bench-total]", inputsEl());
  if (bt) bt.textContent = `${+bermTotal(state.project).toFixed(2)} m high in all`;
  for (const d of $$("details.group", inputsEl())) {
    const G = SPEC[state.project.type].find((x) => x.g === d.dataset.g);
    if (G?.sum) d.querySelector(".sum").textContent = G.sum(state.project);
  }
  for (const it of SPEC[state.project.type].flatMap((G) => G.items)) {
    if (typeof it.sub === "function") {
      const inp = $(`input[type=number][data-k="${it.k}"]`, inputsEl());
      const small = inp?.closest(".f")?.querySelector(".lab small");
      if (small) small.textContent = it.sub(state.project);
    }
  }
}

function analyse() {
  state.partial = [];
  state.seismic = null;
  state.analyseId = run("analyse");
  setBusy(true, "Calculating…");
}

function setBusy(on, text) {
  $("#busy").classList.toggle("hidden", !on);
  if (text) $("#busyText").textContent = text;
}

function onWorker(ev) {
  const m = ev.data;
  if (m.id !== busyId) return;
  if (m.kind === "case") {
    state.partial[m.i] = m.case;
    setBusy(true, `Case ${m.i + 1} of ${m.n}…`);
    if (!state.result || state.result.project.type !== state.project.type) return;
    renderCases(true);
  } else if (m.kind === "done") {
    state.result = m.result;
    state.ms = m.ms;
    if (!state.result.cases.find((c) => c.key === state.selected)) state.selected = (state.result.worst?.key) || state.result.cases[0]?.key;
    setBusy(true, "Earthquake extras…");
    renderAll();
  } else if (m.kind === "seismic") {
    state.seismic = m.data;
    jobRunning = false;
    setBusy(false);
    if (state.tab === "seismic") renderPanel();
  } else if (m.kind === "step") {
    state.optimise = { ...(state.optimise || {}), steps: [...(state.optimise?.steps || []), { cot: m.cot, worst: m.worst }] };
    renderPanel();
  } else if (m.kind === "optimised") {
    jobRunning = false; setBusy(false);
    state.optimise = { ...(state.optimise || {}), done: m.result, running: false };
    state.tab = "optimise"; renderTabs(); renderPanel();
  } else if (m.kind === "check") {
    state.verify.rows[m.i] = m;
    renderPanel();
  } else if (m.kind === "verified") {
    jobRunning = false; setBusy(false);
    state.verify.done = true; renderPanel();
  } else if (m.kind === "error") {
    jobRunning = false; setBusy(false);
    console.error(m.stack);
    toast("Calculation error: " + m.message, true);
  }
}

// ------------------------------------------------------------------ the answer

let view3d = null;
async function ensure3D() {
  if (view3d || state.view !== "3d") return view3d;
  try {
    const { View3D } = await import("./view3d.js");
    view3d = new View3D($("#view"));
    view3d.setMotion(state.motion);
  } catch (e) {
    console.error(e);
    state.view = "section";
    toast("3D is not available on this device; showing the section.");
  }
  return view3d;
}

function currentCase() {
  return state.result?.cases.find((c) => c.key === state.selected) || state.result?.cases[0];
}

async function renderView() {
  const r = state.result, c = currentCase();
  const host = $("#view");
  $("#viewMsg").classList.toggle("hidden", !!r);
  $$(".vbtn[data-view]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.view === state.view)));
  $("#btnTrials").setAttribute("aria-pressed", String(state.trials));
  $("#btnMotion").setAttribute("aria-pressed", String(state.motion));
  $("#btnTrials").classList.toggle("hidden", state.view !== "section");
  $("#btnMotion").classList.toggle("hidden", state.view !== "3d");
  if (!r) return;
  const old = $("svg.section", host);
  if (state.view === "section") {
    if (view3d) view3d.renderer.domElement.classList.add("hidden");
    const w = host.clientWidth || 900, h = host.clientHeight || 480;
    const svg = sectionSVG(r, c, { width: w, height: h, trials: state.trials, reinforcement: r.geometry.reinforcement, faceDir: r.geometry.faceDir });
    if (old) old.outerHTML = svg; else host.insertAdjacentHTML("afterbegin", svg);
  } else {
    if (old) old.remove();
    const v = await ensure3D();
    if (v) {
      v.renderer.domElement.classList.remove("hidden");
      const arm = r.geometry.armour;
      v.show(r, c, { armour: arm, reinforcement: r.geometry.reinforcement, faceDir: r.geometry.faceDir });
    } else renderView();
  }
  renderVerdict();
  renderLegend();
}

function renderVerdict() {
  const r = state.result;
  if (!r) return;
  const w = r.worst, c = currentCase();
  if (!w) { $("#ovVerdict").innerHTML = `<div class="glass verdict fail"><div class="lines"><b>No slip surface found.</b> Check the geometry.</div></div>`; return; }
  const pass = r.pass;
  const shown = c || w;
  $("#ovVerdict").innerHTML = `<div class="glass verdict ${shown.pass ? "pass" : "fail"}">
    <div class="fos">${f2(shown.F)}</div>
    <div class="lines"><b>${esc(shown.name)}</b><br>needs ${f2(shown.target)} · ${shown.pass ? "✓ safe" : "✕ not enough"}<br>
    <span class="${pass ? "state-good" : "state-critical"}">${pass ? "All cases pass" : `Worst: ${esc(w.name)} ${f2(w.F)}`}</span></div></div>`;
  const pill = $("#fpill");
  if (pill) {
    pill.className = `fpill ${pass ? "pass" : "fail"}${pill.classList.contains("on") ? " on" : ""}`;
    pill.innerHTML = `<b>${f2(w.F)}</b><span>${esc(w.name)} · needs ${f2(w.target)}</span><span>${pass ? "✓" : "✕"}</span>`;
  }
}

// On a phone the slope scrolls away while you type: a small pill keeps the answer in sight.
(() => {
  const pill = $("#fpill"), view = $("#view");
  if (!pill || !view || !("IntersectionObserver" in window)) return;
  new IntersectionObserver(([e]) => pill.classList.toggle("on", !e.isIntersecting), { threshold: 0.15 }).observe(view);
  pill.addEventListener("click", () => view.scrollIntoView({ behavior: "smooth", block: "start" }));
})();

function renderLegend() {
  const r = state.result;
  if (!r) return;
  const sw = (c, t) => `<span><i style="background:${c}"></i>${esc(t)}</span>`;
  const names = [...new Set(r.geometry.layers.map((l) => l.mat.name))];
  import("./shapes.js").then(({ colourOf }) => {
    let html = names.map((n, k) => sw(colourOf(n, k), n)).join("") + sw("rgba(42,120,214,.6)", "water");
    if (state.view === "section" && state.trials) html += `<span style="display:flex;align-items:center;gap:6px">trial F <span class="fbar"></span> higher</span>`;
    $("#legend").innerHTML = html;
  });
}

function renderCases(partial) {
  const list = partial ? state.partial : state.result?.cases || [];
  $("#cases").innerHTML = list.filter(Boolean).map((c) => {
    if (c.error) return `<button class="case" data-case="${c.key}"><span class="cn">${esc(c.name)}</span><span class="ct state-critical">${esc(c.error)}</span></button>`;
    const col = fosColour(c.F, c.target);
    const pct = Math.max(4, Math.min(100, (c.F / c.target) / 1.6 * 100));
    return `<button class="case${partial ? " pending" : ""}" data-case="${c.key}" aria-pressed="${c.key === state.selected}">
      <span class="cn">${esc(c.name)}</span>
      <span class="cf"><b style="color:${col}">${f2(c.F)}</b><span class="pill ${c.pass ? "good" : "bad"}">${c.pass ? "✓ OK" : "✕ low"}</span></span>
      <span class="bar slim"><span class="bar-fill" style="width:${pct}%;background:${col}"></span><span class="bar-plan" style="left:${100 / 1.6}%"></span></span>
      <span class="ct">needs ${f2(c.target)} · ${esc(METHOD_NAMES[c.method] || "")}</span></button>`;
  }).join("");
}

const TABS = [
  ["methods", "Methods"], ["slices", "Slices"], ["armour", "Armour"], ["seismic", "Earthquake"],
  ["optimise", "Optimise"], ["verify", "Verification"], ["about", "How it works"],
];
function renderTabs() {
  const tabs = TABS.filter(([k]) => (k !== "armour" || state.project.type === "revetment") && (k !== "optimise" || state.project.type !== "section"));
  if (!tabs.find(([k]) => k === state.tab)) state.tab = "methods";
  $("#dtabs").innerHTML = tabs.map(([k, n]) => `<button role="tab" data-tab="${k}" aria-selected="${k === state.tab}">${n}</button>`).join("");
}

function renderPanel() {
  const P = $("#dpanel");
  const r = state.result, c = currentCase();
  const t = state.tab;
  if (t === "methods") P.innerHTML = c ? methodsPanel(c) : "";
  else if (t === "slices") P.innerHTML = c ? slicesPanel(c) : "";
  else if (t === "armour") P.innerHTML = armourPanel();
  else if (t === "seismic") P.innerHTML = seismicPanel();
  else if (t === "optimise") P.innerHTML = optimisePanel();
  else if (t === "verify") P.innerHTML = verifyPanel();
  else if (t === "about") P.innerHTML = aboutPanel();
}

function methodsPanel(c) {
  if (c.error) return `<div class="warn">${esc(c.error)}</div>`;
  const rows = Object.entries(c.results).map(([m, F]) => `<tr class="${m === c.method ? "best" : ""}"><td>${esc(METHOD_NAMES[m])}${m === c.method ? " <span class='pill good'>governing</span>" : ""}</td><td class="num">${f3(F)}</td><td class="num">${f2(F / c.target)}</td></tr>`).join("");
  const s = c.surface;
  return `<div class="kpis">
      <div class="kpi"><div class="k">Factor of safety</div><div class="v" style="color:${fosColour(c.F, c.target)}">${f3(c.F)}</div><div class="s">needs ${f2(c.target)} · ${c.pass ? "passes" : "fails"} by ${f1(Math.abs(c.ratio - 1) * 100)}%</div></div>
      <div class="kpi"><div class="k">Sliding mass</div><div class="v">${fmt(c.weight, 0)} kN/m</div><div class="s">${fmt(c.weight / 9.81, 0)} t per metre run · depth ${f2(s.depth)} m</div></div>
      <div class="kpi"><div class="k">Surface</div><div class="v">${s.circle ? "Circle" : s.kind === "block" ? "Block" : "Non-circular"}</div><div class="s">${s.circle ? `centre (${f2(s.circle.xc)}, ${f2(s.circle.yc)}), R ${f2(s.circle.R)} m` : `${s.slip.length} nodes`}</div></div>
      ${c.lambda ? `<div class="kpi"><div class="k">Interslice λ</div><div class="v">${f3(c.lambda)}</div><div class="s">${esc(METHOD_NAMES[c.method])}</div></div>` : ""}
    </div>
    <p class="explain mt-sm">${esc(c.note)}${c.fellBack ? " The rigorous method did not converge on this surface, so Bishop is shown." : ""}${c.fromCircle ? ` A non-circular surface was found ${f1((1 - c.F / c.fromCircle) * 100)}% lower than the best circle.` : ""}</p>
    <div class="table-scroll mt-sm"><table class="tight"><thead><tr><th>Method (same surface)</th><th class="num">F</th><th class="num">F / target</th></tr></thead><tbody>${rows}</tbody></table></div>
    <p class="note mt-sm">Every method is solved on the governing surface. Spencer and Morgenstern-Price satisfy force and moment equilibrium; Bishop moment only; Janbu force only (corrected by f0); Ordinary ignores interslice forces and is shown for comparison.</p>`;
}

function slicesPanel(c) {
  if (!c.slices) return "";
  const head = ["#", "x left", "x right", "b", "α °", "base l", "W kN", "c kPa", "φ °", "u kPa", "N kN", "N' kN", "S kN", "E downslope kN", "X downslope kN"];
  const rows = c.slices.map((s, i) => `<tr><td>${i + 1}</td><td class="num">${f2(s.x0)}</td><td class="num">${f2(s.x1)}</td><td class="num">${f2(s.b)}</td><td class="num">${f1(s.alpha)}</td><td class="num">${f2(s.l)}</td><td class="num">${f1(s.W)}</td><td class="num">${f1(s.c)}</td><td class="num">${f1(s.phi)}</td><td class="num">${f1(s.u)}</td><td class="num">${f1(s.N)}</td><td class="num">${f1(s.Neff)}</td><td class="num">${f1(s.S)}</td><td class="num">${f1(s.Er)}</td><td class="num">${f1(s.Xr)}</td></tr>`).join("");
  return `<div class="row between"><span class="note">${c.slices.length} slices on the governing surface, ${esc(METHOD_NAMES[c.method])}, F = ${f3(c.F)}. Slices break at every layer, water and load boundary.</span><button class="btn btn-ghost btn-sm" data-csv>Download CSV</button></div>
    <div class="table-scroll mt-sm"><table class="tight"><thead><tr>${head.map((h) => `<th class="num">${h}</th>`).join("")}</tr></thead><tbody>${rows}</tbody></table></div>`;
}

function armourPanel() {
  const a = state.result?.extras?.armour;
  if (!a) return "";
  const u = a.unit;
  const warn = [...(u.warnings || []), ...(a.toe.warnings || [])].map((w) => `<div class="warn">${esc(w)}</div>`).join("");
  let main;
  if (u.kind === "rock") {
    main = `<div class="kpis">
      <div class="kpi"><div class="k">Armour rock</div><div class="v">${u.grading ? esc(u.grading.name) : "too heavy"}</div><div class="s">needs M50 ≥ ${fmt(u.M50 / 1000, 2)} t (Dn50 ${f2(u.Dn50)} m)</div></div>
      <div class="kpi"><div class="k">Layer</div><div class="v">${f2(u.thickness)} m</div><div class="s">2 layers · ${f2(u.perSquareMetre.tonnes)} t/m² of slope</div></div>
      <div class="kpi"><div class="k">Underlayer</div><div class="v">${u.underlayer.grading ? esc(u.underlayer.grading.name) : "–"}</div><div class="s">${f2(u.underlayer.thickness)} m thick · M50/10</div></div>
      <div class="kpi"><div class="k">Toe rock</div><div class="v">${a.toe.grading ? esc(a.toe.grading.name) : "–"}</div><div class="s">M50 ≥ ${fmt(a.toe.M50 / 1000, 2)} t · ht/h ${f2(a.toe.ratio)}</div></div>
    </div>
    <div class="table-scroll mt-sm"><table class="tight"><thead><tr><th>Formula</th><th class="num">Ns = Hs/ΔDn50</th><th class="num">Dn50 m</th><th class="num">M50 t</th><th>Notes</th></tr></thead><tbody>
      <tr class="${u.Dn50 === u.hudson.Dn50 ? "best" : ""}"><td>Hudson, KD ${u.KD}</td><td class="num">${f3(u.hudson.Ns)}</td><td class="num">${f3(u.hudson.Dn50)}</td><td class="num">${f2(u.hudson.M50 / 1000)}</td><td>${Hs_h(a) > 0.6 ? "breaking" : "non-breaking"} waves</td></tr>
      <tr class="${u.Dn50 === u.vdm.Dn50 ? "best" : ""}"><td>${esc(u.vdm.formula)}</td><td class="num">${f3(u.vdm.Ns)}</td><td class="num">${f3(u.vdm.Dn50)}</td><td class="num">${f2(u.vdm.M50 / 1000)}</td><td>${u.vdm.plunging ? "plunging" : "surging"}, ξ ${f2(u.vdm.xi)} (ξcr ${f2(u.vdm.xicr)}), S ${u.S}, N ${a.N}</td></tr>
    </tbody></table></div>`;
  } else {
    main = `<div class="kpis">
      <div class="kpi"><div class="k">${esc(armourName(u.kind))} unit</div><div class="v">${f2(u.size)} m³</div><div class="s">${f1(u.mass)} t each · needs ≥ ${f2(u.V)} m³</div></div>
      <div class="kpi"><div class="k">Unit height</div><div class="v">${f2(u.height)} m</div><div class="s">Dn ${f2(u.DnDesign)} m · V = 0.341 H³</div></div>
      <div class="kpi"><div class="k">Layer</div><div class="v">${f2(u.thickness)} m</div><div class="s">single layer · ${f1(u.units100)} units per 100 m²</div></div>
      <div class="kpi"><div class="k">Underlayer</div><div class="v">${u.underlayer.grading ? esc(u.underlayer.grading.name) : "–"}</div><div class="s">${f2(u.underlayer.thickness)} m thick</div></div>
    </div>
    <p class="explain mt-sm">Hudson with KD ${u.KD} (${esc(state.project.waves.section)}), Ns = ${f2(u.Ns)}. ${esc(u.src)}</p>
    <div class="${u.interlock.slopeOk ? "ok" : "warn"} mt-sm"><b>Interlocking:</b> ${u.interlock.slopeOk ? "slope within 4:3 to 3:2." : "slope outside 4:3 to 3:2."} ${esc(u.interlock.placement)}</div>`;
  }
  const comp = slopeComparison();
  return `${main}${warn ? `<div class="mt-sm" style="display:grid;gap:6px">${warn}</div>` : ""}
    <div class="kpis mt">
      <div class="kpi"><div class="k">Run-up Ru2%</div><div class="v">${f2(a.runup.Ru2)} m</div><div class="s">to +${f2(a.HWL + a.runup.Ru2)} m · γf ${a.runup.gammaF}</div></div>
      <div class="kpi"><div class="k">Overtopping</div><div class="v">${a.overtopping.q < 0.01 ? "< 0.01" : f2(a.overtopping.q)} l/s/m</div><div class="s">freeboard ${f2(a.overtopping.Rc)} m</div></div>
      <div class="kpi"><div class="k">Waves</div><div class="v">ξ ${f2(u.waves?.xim ?? a.runup.xi10)}</div><div class="s">depth at toe ${f2(a.h)} m · Hs/h ${f2(Hs_h(a))}</div></div>
    </div>
    <h3 class="mt" style="font-size:.875rem">Optimising the slope: armour per metre of revetment</h3>
    <div class="table-scroll mt-sm"><table class="tight"><thead><tr><th>Slope</th><th>Rock grading</th><th class="num">Rock layer m</th><th class="num">Rock m³/m</th><th class="num">Accropode m³</th><th class="num">Units/m</th></tr></thead><tbody>
    ${comp.map((r) => `<tr class="${Math.abs(r.cot - state.project.geom.cot) < 1e-6 ? "best" : ""}"><td>1:${r.cot}</td><td>${r.rock.grading ? esc(r.rock.grading.name) : "too heavy"}</td><td class="num">${f2(r.rock.thickness)}</td><td class="num">${f1(r.rockVol)}</td><td class="num">${r.acc ? f2(r.acc.size) : "–"}</td><td class="num">${r.acc ? f1(r.accUnits) : "–"}</td></tr>`).join("")}
    </tbody></table></div><p class="note mt-sm">Flatter slopes need lighter rock but a longer face; interlocking units only work from 4:3 to 3:2. Global stability of each option is on the load cases above.</p>`;
}
const Hs_h = (a) => +state.project.waves.Hs / a.h;

function slopeComparison() {
  const p = state.project;
  const H = +p.geom.crest - +p.geom.toe;
  const a = state.result.extras.armour;
  return [1.33, 1.5, 2, 2.5, 3, 3.5, 4].map((cot) => {
    const Lf = H * Math.sqrt(1 + cot * cot);
    const common = { Hs: +p.waves.Hs, Tp: +p.waves.Tp, h: a.h, cot, rhoW: +p.armour.rhoW };
    const rock = rockArmour({ ...common, rhoR: +p.armour.rhoR, P: +p.armour.P, S: damageLevels(cot).start, N: a.N, breaking: +p.waves.Hs / a.h > 0.6, governing: p.armour.governing || "max" });
    const acc = cot <= 1.5 ? accropode({ ...common, rhoC: +p.armour.rhoC, unit: p.armour.type === "accropode2" ? "accropode2" : "accropode1", section: p.waves.section }) : null;
    return { cot, rock, rockVol: rock.thickness * Lf, acc, accUnits: acc ? acc.units100 / 100 * Lf : 0 };
  });
}

function seismicPanel() {
  const c = state.result?.cases.find((k) => k.key === "seismic");
  if (!state.project.seismic.on) return `<p class="explain">Earthquake checks are off. Turn them on under Earthquake.</p>`;
  if (!c) return "";
  const s = c.seismic, y = state.seismic;
  const nm = y?.newmark;
  const verdict = !nm ? "" : nm.D < 1 ? "negligible" : nm.D < 5 ? "small: acceptable for most slopes" : nm.D < 15 ? "moderate: check what the slope supports" : "large: likely damaging";
  return `<div class="kpis">
    <div class="kpi"><div class="k">kh / kv</div><div class="v">${f3(s.kh)} / ±${f3(Math.abs(s.kv))}</div><div class="s">ag ${s.ag} g · S ${s.S} · ST ${s.ST}</div></div>
    <div class="kpi"><div class="k">Pseudo-static F</div><div class="v" style="color:${fosColour(c.F, c.target)}">${f3(c.F)}</div><div class="s">needs ${f2(c.target)} · kv ${s.kvUsed > 0 ? "upwards" : "downwards"} governs</div></div>
    <div class="kpi"><div class="k">Yield acceleration ky</div><div class="v">${y ? f3(y.ky) + " g" : "…"}</div><div class="s">kh at which F = 1.0</div></div>
    <div class="kpi"><div class="k">Newmark sliding</div><div class="v">${nm ? (nm.D < 0.1 ? "≈ 0" : f1(nm.D) + " cm") : "…"}</div><div class="s">${nm && nm.D >= 0.1 ? `range ${f1(nm.low)}–${f1(nm.high)} cm · ${verdict}` : nm ? "ky above the peak acceleration" : "calculating"}</div></div>
  </div>
  <p class="explain mt-sm">${esc(s.basis)}. The peak acceleration at the surface is amax = ag·S·ST = ${f3(s.amax)} g. ${y ? `The slope starts to slide when the horizontal acceleration reaches ky = ${f3(y.ky)} g.` : ""} ${nm ? esc(nm.note) : ""}</p>`;
}

function optimisePanel() {
  const o = state.optimise;
  const p = state.project;
  let body = `<p class="explain">Finds the steepest slope (smallest n in 1:n) that meets every target in every load case, keeping everything else as it is. Each try is a full search of all cases.</p>
    <div class="row mt-sm"><button class="btn btn-primary" data-optimise ${o?.running ? "disabled" : ""}>${o?.running ? "Optimising…" : "Find the steepest safe slope"}</button><span class="note">Now: ${bermsOn(p) ? bermRows(p).map((r) => `1:${r.cot}`).join(" / ") + " (benches; the search sets every bench to the same slope and keeps the berms)" : `1:${p.geom.cot} (${f1(deg(+p.geom.cot))}°)`}</span></div>`;
  if (o?.steps?.length) body += `<div class="table-scroll mt-sm"><table class="tight"><thead><tr><th>Try</th><th>Slope</th><th>Worst case</th><th class="num">F / target</th></tr></thead><tbody>${o.steps.map((s, i) => `<tr><td>${i + 1}</td><td>1:${f2(s.cot)}</td><td>${esc(s.worst?.name || "–")}</td><td class="num"><span class="pill ${s.worst?.pass ? "good" : "bad"}">${f3(s.worst?.ratio)}</span></td></tr>`).join("")}</tbody></table></div>`;
  if (o?.done) {
    const d = o.done;
    body += d.cot ? `<div class="ok mt-sm"><b>Steepest safe slope: 1:${d.cot} (${f1(d.angle)}°).</b> Worst case ${esc(d.worst.name)} at F = ${f3(d.worst.F)}. <button class="btn btn-primary btn-sm" data-apply="${d.cot}">Use 1:${d.cot}${bermsOn(p) ? " on every bench" : ""}</button></div>`
      : `<div class="warn mt-sm">${esc(d.message)}</div>`;
  }
  return body;
}

function verifyPanel() {
  const v = state.verify;
  let body = `<p class="explain">These checks run the same engine against closed-form solutions and published benchmarks. They run in the build pipeline too, so a change that breaks one never ships.</p>
    <div class="row mt-sm"><button class="btn btn-primary" data-verify ${v && !v.done ? "disabled" : ""}>${v && !v.done ? "Running…" : v ? "Run again" : "Run the checks"}</button>${v?.done ? `<span class="${v.rows.every((r) => r.rows.every((x) => x.pass)) ? "state-good" : "state-critical"}">${v.rows.reduce((a, r) => a + r.rows.filter((x) => x.pass).length, 0)} of ${v.rows.reduce((a, r) => a + r.rows.length, 0)} pass</span>` : ""}</div>`;
  if (v) {
    body += `<div class="table-scroll mt-sm"><table class="tight"><thead><tr><th>Check</th><th>Result</th><th class="num">Talus</th><th class="num">Expected</th><th class="num">Diff</th><th></th></tr></thead><tbody>`;
    for (const r of v.rows.filter(Boolean)) {
      r.rows.forEach((x, i) => {
        body += `<tr>${i === 0 ? `<td rowspan="${r.rows.length}"><b>${esc(r.check.title)}</b><div class="note">${esc(r.check.group)} · ${esc(r.check.source)}</div></td>` : ""}<td>${esc(x.label)}</td><td class="num">${fmt(x.value, 4)}</td><td class="num">${fmt(x.expected, 4)}</td><td class="num">${Number.isFinite(x.error) ? (x.error * 100).toFixed(3) + "%" : "–"}</td><td><span class="pill ${x.pass ? "good" : "bad"}">${x.pass ? "pass" : "fail"}</span></td></tr>`;
      });
    }
    body += `</tbody></table></div>`;
  }
  return body;
}

function aboutPanel() {
  return `<div class="explain" style="display:grid;gap:10px;max-width:860px">
  <p><b>What Talus does.</b> For each load case it searches thousands of circular slip surfaces (entry, exit and radius), refines the lowest with a simplex search, then solves the critical one exactly by every method. Optionally it frees the circle into a non-circular surface. The analysis is two-dimensional, per metre run; the 3D view extrudes the section so it can be seen.</p>
  <p><b>Slices.</b> The mass above the surface is cut into vertical slices that break at every layer boundary, water line, load edge and crossing, so weights, centroids and pore pressures are exact for the geometry. Weight uses γ above the water line and γsat below; pore pressure is γw times the head above the base; water standing on the ground is a pressure on the surface.</p>
  <p><b>Methods.</b> One general limit equilibrium formulation (Fredlund and Krahn 1977) gives Bishop simplified, Janbu simplified (with Janbu's f0 correction), Spencer (constant interslice inclination) and Morgenstern-Price (half-sine). Ordinary is shown for comparison. The slices are solved one after another exactly for each F and λ, and λ is found where force and moment equilibrium give the same F.</p>
  <p><b>Load cases.</b> Cut slopes: long term (drained), short term (undrained clays), seismic. Embankments: end of construction, steady seepage, rapid drawdown, seismic. Revetments: high and low water, drawdown under the wave trough, seismic. Targets follow USACE EM 1110-2-1902 or, with Eurocode 7, the M2 partial factors with an over-design factor of 1.0.</p>
  <p><b>Earthquake.</b> Pseudo-static kh = 0.5·ag·S·ST, kv = ±0.5·kh (EN 1998-5), both kv directions checked; yield acceleration by bisection; permanent displacement by Jibson (2007).</p>
  <p><b>Armour.</b> Rock by Hudson and by Van der Meer (1988), or its shallow-water form (Van Gent et al. 2003) when h &lt; 3Hs, with the larger governing; EN 13383 gradings; toe by Van der Meer (1998); run-up and overtopping by EurOtop (2018). Accropode™ and Accropode™ II by Hudson with CLI's design KD (15 / 11.5 and 16 / 12.3), valid on 4:3 to 3:2 slopes; Accropode is a trademark of CLI, and units must be designed and placed to CLI's guidance.</p>
  <p><b>Limits.</b> Typical soil values are starting points: use site data. Seepage lines are simplified (straight lines), not a flow net. Talus is a design aid; the engineer of record remains responsible.</p></div>`;
}

function renderAll() {
  renderCases(false);
  renderTabs();
  renderPanel();
  renderView();
}

// ------------------------------------------------------------------ events on the answer

document.addEventListener("click", (ev) => {
  if (!ev.target.closest(".menu-wrap")) $("#reportMenu").classList.add("hidden");
  const b = ev.target.closest("button");
  if (!b) return;
  if (b.dataset.case) { state.selected = b.dataset.case; renderCases(false); renderPanel(); renderView(); return; }
  if (b.dataset.tab) {
    state.tab = b.dataset.tab; renderTabs(); renderPanel();
    if (state.tab === "verify" && !state.verify) startVerify();
    return;
  }
  if (b.dataset.view) { state.view = b.dataset.view; renderView(); return; }
  if (b.id === "btnTrials") { state.trials = !state.trials; renderView(); return; }
  if (b.id === "btnMotion") { state.motion = !state.motion; view3d?.setMotion(state.motion); renderView(); return; }
  if (b.dataset.optimise !== undefined) {
    state.optimise = { running: true, steps: [] };
    run("optimise"); setBusy(true, "Optimising…"); renderPanel(); return;
  }
  if (b.dataset.apply) { state.project.geom.cot = +b.dataset.apply; if (bermsOn(state.project)) for (const r of bermRows(state.project)) r.cot = +b.dataset.apply; state.optimise = null; changed(true); toast(`Slope set to 1:${b.dataset.apply}`); return; }
  if (b.dataset.verify !== undefined) { startVerify(); return; }
  if (b.dataset.csv !== undefined) { downloadCSV(); return; }
  if (b.id === "btnProjects") { openDrawer(); return; }
  if (b.id === "btnReport") { $("#reportMenu").classList.toggle("hidden"); return; }
  if (b.dataset.report) { $("#reportMenu").classList.add("hidden"); b.dataset.report === "word" ? wordReport() : printReport(); return; }
  if (b.dataset.close !== undefined) { $("#drawer").classList.add("hidden"); return; }
  if (b.dataset.new) { newProject(b.dataset.new); return; }
});

function startVerify() {
  state.verify = { rows: [], done: false };
  run("verify"); setBusy(true, "Running checks…"); renderPanel();
}

function downloadCSV() {
  const c = currentCase();
  const head = ["slice", "x_left", "x_right", "width", "alpha_deg", "base_length", "W_kN", "c_kPa", "phi_deg", "u_kPa", "N_kN", "N_eff_kN", "S_kN", "E_right_kN", "X_right_kN", "material"];
  const lines = [head.join(",")].concat(c.slices.map((s, i) => [i + 1, s.x0, s.x1, s.b, s.alpha, s.l, s.W, s.c, s.phi, s.u, s.N, s.Neff, s.S, s.Er, s.Xr, `"${s.mat}"`].map((v) => (typeof v === "number" ? +v.toFixed(4) : v)).join(",")));
  const blob = new Blob([lines.join("\n")], { type: "text/csv" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `${(state.project.name || "talus").replace(/[^\w-]+/g, "_")}_${c.key}_slices.csv`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

// ------------------------------------------------------------------ projects

async function api(path, opt = {}) {
  const r = await fetch(T.api + path, { credentials: "same-origin", headers: { "Content-Type": "application/json", Accept: "application/json" }, ...opt });
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
  const data = strip(state.project);
  try { localStorage.setItem("talus-last", JSON.stringify({ id: state.id, data })); } catch (e) { /* private mode */ }
  if (state.offline) { $("#saveState").textContent = "Saved on this device"; return; }
  try {
    const r = state.id ? await api(`/projects/${state.id}`, { method: "PUT", body: JSON.stringify({ data }) })
      : await api(`/projects`, { method: "POST", body: JSON.stringify({ data }) });
    state.id = r.id; state.version = r.version; state.dirty = false;
    history.replaceState(null, "", `${T.base}p/${r.id}`);
    $("#saveState").textContent = "Saved";
    $("#saveState").className = "save-state saved";
  } catch (e) {
    $("#saveState").textContent = "Not saved: " + e.message;
  }
}

async function openDrawer() {
  $("#drawer").classList.remove("hidden");
  const list = $("#projList");
  list.innerHTML = `<div class="note">Loading…</div>`;
  try {
    const { projects } = await api("/projects");
    list.innerHTML = projects.length ? projects.map((p) => `<div class="proj ${p.id === state.id ? "current" : ""}" data-open="${p.id}"><span class="pn">${esc(p.name)}</span><span class="pm">${{ cut: "Cut slope", embankment: "Embankment", revetment: "Revetment" }[p.kind]}</span><span class="pm">${new Date(p.updated * 1000).toLocaleString()}</span><span><button class="btn btn-ghost btn-sm" data-dup="${p.id}">Copy</button> <button class="btn btn-danger btn-sm" data-del="${p.id}">Delete</button></span></div>`).join("")
      : `<div class="note">No projects yet.</div>`;
  } catch (e) { list.innerHTML = `<div class="note">Projects are kept on this device only here (${esc(e.message)}).</div>`; }
}
$("#drawer").addEventListener("click", async (ev) => {
  if (ev.target === $("#drawer")) { $("#drawer").classList.add("hidden"); return; }
  const del = ev.target.closest("[data-del]"), dup = ev.target.closest("[data-dup]"), open = ev.target.closest("[data-open]");
  try {
    if (del) {
      ev.stopPropagation();
      if (!confirm("Delete this project? Its earlier versions go with it.")) return;
      await api(`/projects/${del.dataset.del}`, { method: "DELETE" });
      if (+del.dataset.del === state.id) { state.id = null; }
      openDrawer(); return;
    }
    if (dup) { ev.stopPropagation(); const r = await api(`/projects/${dup.dataset.dup}/duplicate`, { method: "POST", body: "{}" }); loadProject(r); $("#drawer").classList.add("hidden"); return; }
    if (open) { const r = await api(`/projects/${open.dataset.open}`); loadProject(r); $("#drawer").classList.add("hidden"); }
  } catch (e) { toast(e.message, true); }
});

function loadProject(r) {
  state.id = r.id; state.version = r.version;
  state.project = complete(r.data);
  state.selected = null; state.result = null; state.optimise = null;
  $("#projectName").value = state.project.name;
  history.replaceState(null, "", `${T.base}p/${r.id}`);
  $("#saveState").textContent = "Saved"; $("#saveState").className = "save-state saved";
  renderInputs(); analyse();
}

function newProject(kind) {
  state.id = null;
  state.project = complete({ type: kind });
  state.selected = null; state.result = null; state.optimise = null;
  $("#projectName").value = state.project.name;
  $("#drawer").classList.add("hidden");
  renderInputs(); analyse(); save();
}

$("#projectName").addEventListener("input", (ev) => { state.project.name = ev.target.value; scheduleSave(); });

// ------------------------------------------------------------------ report

/** An input as a person would read it: labels for choices, Yes/No for switches. */
function reportValue(it, v) {
  if (v === undefined || v === null || v === "") return "auto";
  if (typeof v === "boolean") return v ? "Yes" : "No";
  const opts = typeof it.options === "function" ? it.options(state.project) : it.options;
  if (Array.isArray(opts)) { const o = opts.find((o) => String(Array.isArray(o) ? o[0] : o) === String(v)); if (o) return Array.isArray(o) ? o[1] : String(o); }
  return `${v} ${it.u || ""}`.trim();
}

const soilText = (s) => `${s.name}: γ ${s.gamma}/${s.gsat} kN/m³, c' ${s.c} kPa, φ' ${s.phi}°${s.clay && s.su ? `, su ${s.su}${s.suGrad ? ` + ${s.suGrad}/m` : ""}${s.suMax ? ` (max ${s.suMax})` : ""} kPa` : ""}`;
const ptsText = (v) => parsePoints(v || "").map(([x, y]) => `(${+x.toFixed(2)}, ${+y.toFixed(2)})`).join(" ");

/** The inputs as rows of a table, grouped as on screen. */
function reportInputs(p) {
  const out = [];
  for (const G of SPEC[p.type]) {
    const rows = [];
    for (const it of G.items) {
      if (it.show && !it.show(p)) continue;
      if (it.kind === "soil") rows.push([it.l, soilText(soilFrom(get(p, it.k)))]);
      else if (it.kind === "points") rows.push([it.l, ptsText(get(p, it.k))]);
      else if (it.kind === "layers") (p.layers || []).forEach((L, i) => rows.push([`Layer ${i + 1}${i ? `, top ${ptsText(L.top)}` : ", top is the ground"}`, soilText(soilFrom(L.soil))]));
      else if (it.kind === "benches") { if (bermsOn(p)) rows.push(["Benches, from the crest down", bermRows(p).map((r, i, R) => `${r.h} m at 1:${r.cot}${i < R.length - 1 ? `, berm ${r.berm} m` : ""}`).join("; ")]); }
      else if (it.k && it.kind !== "html") rows.push([it.l, reportValue(it, get(p, it.k))]);
    }
    if (rows.length) out.push({ group: G.g }, ...rows);
  }
  return out;
}

const surfaceText = (c) => c.surface.circle
  ? `Critical circle: centre (${f2(c.surface.circle.xc)}, ${f2(c.surface.circle.yc)}) m, radius ${f2(c.surface.circle.R)} m.`
  : `${c.surface.kind === "block" ? "Critical block along a weak layer" : "Non-circular critical surface"}: ${c.surface.slip.map(([x, y]) => `(${f2(x)}, ${f2(y)})`).join(" ")}.`;

/** The report as blocks, shared by the printed (PDF) and the Word versions. */
function reportBlocks(snapshot) {
  const r = state.result, p = state.project;
  const B = [];
  const geo = { reinforcement: r.geometry.reinforcement, faceDir: r.geometry.faceDir };
  B.push({ t: "title", text: `${p.name} · slope stability` });
  B.push({ t: "note", text: `Talus ${T.version || ""} · ${new Date().toLocaleString()} · ${BASES[p.design.basis].name} · governing method ${METHOD_NAMES[p.design.method]} · ${KINDS.find((k) => k[0] === p.type)?.[1] || p.type}` });
  B.push({ t: "h1", text: "Result" });
  B.push({ t: "p", text: r.pass ? "**All load cases meet their targets.**" : `**Not enough: ${r.worst.name} F = ${f3(r.worst.F)} against ${f2(r.worst.target)}.**` });
  B.push({ t: "table", head: ["Load case", "F", "Target", "F / target", ""], widths: [0.44, 0.14, 0.14, 0.14, 0.14],
    rows: r.cases.map((c) => [c.name, c.error ? "–" : f3(c.F), f2(c.target), c.error ? "–" : f2(c.F / c.target), c.error ? "error" : c.pass ? "OK" : "Not OK"]) });
  if (snapshot) B.push({ t: "img", src: snapshot, w: 1600, h: 900, widthCm: 15 }, { t: "caption", text: "3D view of the governing case (the section extruded per metre run)." });
  B.push({ t: "h1", text: "Inputs" });
  B.push({ t: "table", widths: [0.38, 0.62], rows: reportInputs(p) });
  const a = r.extras?.armour;
  if (a) {
    B.push({ t: "h1", text: "Armour" });
    B.push({ t: "p", text: a.unit.kind === "rock"
      ? `Rock ${a.unit.grading?.name || "(above EN 13383 gradings)"}: M50 ≥ ${fmt(a.unit.M50 / 1000, 2)} t, Dn50 ${f2(a.unit.Dn50)} m (Hudson ${f2(a.unit.hudson.Dn50)} m, ${a.unit.vdm.formula} ${f2(a.unit.vdm.Dn50)} m). Two layers, ${f2(a.unit.thickness)} m. Underlayer ${a.unit.underlayer.grading?.name || "–"}, ${f2(a.unit.underlayer.thickness)} m.`
      : `${armourName(a.unit.kind)} ${f2(a.unit.size)} m³ (${f1(a.unit.mass)} t), height ${f2(a.unit.height)} m, single layer ${f2(a.unit.thickness)} m, ${f1(a.unit.units100)} units per 100 m², KD ${a.unit.KD}.` });
    B.push({ t: "p", text: `Toe rock ${a.toe.grading?.name || "–"} (M50 ≥ ${fmt(a.toe.M50 / 1000, 2)} t). Run-up Ru2% ${f2(a.runup.Ru2)} m; overtopping ${f2(a.overtopping.q)} l/s/m.` });
  }
  const sz = state.seismic;
  if (sz) {
    B.push({ t: "h1", text: "Earthquake" });
    B.push({ t: "p", text: `Yield acceleration ky = ${f3(sz.ky)} g; peak surface acceleration ${f3(sz.amax)} g; Newmark displacement ${sz.newmark ? f1(sz.newmark.D) + " cm" : "–"} (Jibson 2007).` });
  }
  r.cases.forEach((c, i) => {
    if (c.error) return;
    B.push({ t: "break" });
    B.push({ t: "h1", text: `${i + 1}. ${c.name}: F = ${f3(c.F)} (needs ${f2(c.target)}) ${c.pass ? "OK" : "Not OK"}` });
    if (c.note) B.push({ t: "p", text: c.note });
    B.push({ t: "img", svg: sectionSVG(r, c, { width: 1000, height: 460, ...geo }), w: 1000, h: 460 });
    B.push({ t: "caption", text: `Section with the critical surface, ${METHOD_NAMES[c.method]}.` });
    B.push({ t: "table", head: Object.keys(c.results).map((m) => METHOD_NAMES[m]), rows: [Object.values(c.results).map((F) => f3(F))] });
    B.push({ t: "p", text: `${surfaceText(c)} Sliding mass ${fmt(c.weight, 0)} kN/m.` });
    if (c.slices && c.name === r.worst.name) {
      B.push({ t: "h2", text: `Slices on the governing surface (${c.slices.length}, ${METHOD_NAMES[c.method]})` });
      B.push({ t: "table", small: true, head: ["#", "x left", "x right", "α °", "W kN", "c kPa", "φ °", "u kPa", "N' kN", "S kN", "E kN", "X kN"],
        rows: c.slices.map((s, k) => [k + 1, f2(s.x0), f2(s.x1), f1(s.alpha), f1(s.W), f1(s.c), f1(s.phi), f1(s.u), f1(s.Neff), f1(s.S), f1(s.Er), f1(s.Xr)]) });
      B.push({ t: "note", text: "E and X are the interslice normal and shear forces on the downslope side of each slice (Fredlund and Krahn sign). All forces per metre run." });
    }
  });
  B.push({ t: "break" }, { t: "h1", text: "Method" });
  for (const m of aboutPanel().matchAll(/<p>([\s\S]*?)<\/p>/g)) B.push({ t: "p", text: m[1].replace(/<b>(.*?)<\/b>/g, "**$1**").replace(/<[^>]+>/g, "").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&") });
  return B;
}

const md = (t) => esc(t).replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>");

function blocksHTML(B) {
  return B.map((b) => {
    if (b.t === "title") return `<h1>${esc(b.text)}</h1>`;
    if (b.t === "h1") return `<h2>${esc(b.text)}</h2>`;
    if (b.t === "h2") return `<h3>${esc(b.text)}</h3>`;
    if (b.t === "note") return `<p class="rnote">${md(b.text)}</p>`;
    if (b.t === "caption") return `<p class="rcap">${md(b.text)}</p>`;
    if (b.t === "break") return `<div class="page"></div>`;
    if (b.t === "img") return b.svg || `<img src="${b.src}" alt="" style="width:100%;max-height:9cm;object-fit:contain">`;
    if (b.t === "table") return `<table class="${b.small ? "rsmall" : ""}">${b.head ? `<tr>${b.head.map((h) => `<th>${esc(h)}</th>`).join("")}</tr>` : ""}${b.rows.map((r) => r.group ? `<tr><th colspan="9" style="text-align:left">${esc(r.group)}</th></tr>` : `<tr>${r.map((v) => `<td>${md(v)}</td>`).join("")}</tr>`).join("")}</table>`;
    return `<p>${md(b.text)}</p>`;
  }).join("\n");
}

function snapshot3d() {
  if (!view3d || state.view !== "3d") return "";
  try { return view3d.snapshot(); } catch (e) { return ""; }
}

function printReport() {
  if (!state.result) return;
  $("#report").innerHTML = `<div class="wrap">${blocksHTML(reportBlocks(snapshot3d()))}</div>`;
  setTimeout(() => window.print(), 50);
}

/** An SVG or a data URL drawn to a PNG, at twice its size for print. */
function toPNG(b) {
  return new Promise((resolve) => {
    const img = new Image();
    const done = () => {
      const k = b.svg ? 2 : 1, w = (b.svg ? b.w : img.naturalWidth) * k, h = (b.svg ? b.h : img.naturalHeight) * k;
      const cv = document.createElement("canvas"); cv.width = w; cv.height = h;
      const g = cv.getContext("2d"); g.fillStyle = "#fff"; g.fillRect(0, 0, w, h); g.drawImage(img, 0, 0, w, h);
      cv.toBlob(async (blob) => resolve(blob ? { png: new Uint8Array(await blob.arrayBuffer()), w, h } : null), "image/png");
    };
    img.onload = done; img.onerror = () => resolve(null);
    if (b.svg) {
      // the drawing uses the page's colour tokens; a picture on its own needs them spelt out
      const svg = b.svg.replace(/var\(--grid\)/g, "#e1e0d9").replace(/var\(--muted\)/g, "#898781").replace(/var\(--surface\)/g, "#ffffff")
        .replace("<svg ", `<svg width="${b.w}" height="${b.h}" font-family="Calibri, Arial, sans-serif" `);
      img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
    } else img.src = b.src;
  });
}

async function wordReport() {
  if (!state.result) return;
  toast("Building the Word report…");
  const B = reportBlocks(snapshot3d());
  for (const b of B) if (b.t === "img") Object.assign(b, (await toPNG(b)) || { png: null });
  const blob = docx(B, { title: `${state.project.name} · slope stability`, footer: `${state.project.name} · Talus ${T.version || ""}` });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `${(state.project.name || "talus").replace(/[^\w\- ]+/g, "").trim() || "talus"}.docx`;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 4000);
}

// ------------------------------------------------------------------ start

inputsEl().addEventListener("input", onInput);
inputsEl().addEventListener("change", (ev) => { if (ev.target.tagName === "SELECT" || ev.target.type === "checkbox") return; onInput(ev); });
inputsEl().addEventListener("click", onClick);
window.addEventListener("resize", () => { if (state.view === "section") renderView(); });

async function start() {
  let opened = null;
  try {
    if (T.openId) opened = await api(`/projects/${T.openId}`);
    else {
      const { projects } = await api("/projects");
      if (projects.length) opened = await api(`/projects/${projects[0].id}`);
    }
  } catch (e) {
    state.offline = true;
  }
  if (opened) { loadProject(opened); return; }
  let last = null;
  try { last = JSON.parse(localStorage.getItem("talus-last") || "null"); } catch (e) { /* none */ }
  state.project = complete(last?.data || { type: "cut" });
  $("#projectName").value = state.project.name;
  renderInputs(); analyse();
  if (!state.offline) save();
}
start();

document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape") $("#reportMenu").classList.add("hidden");
  if (ev.key === "Escape" && !$("#drawer").classList.contains("hidden")) $("#drawer").classList.add("hidden");
});
