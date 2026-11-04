// Talus — the page: inputs on the left, the live answer on the right.
// Every change recalculates in a worker and redraws; projects save themselves.
import { DEFAULTS, complete, BASES, GROUND_S, armourDesign, parsePoints } from "../engine/project.js";
import { PRESETS, PRESET_KEYS, soilFrom } from "../engine/materials.js";
import { METHOD_NAMES } from "../engine/lem.js";
import { rockArmour, accropode, damageLevels, COEFFS } from "../engine/armour.js";
import { sectionSVG, esc } from "./section.js";
import { fosColour } from "./shapes.js";
import { docx } from "./docx.js";
import { COV, COV_LABEL } from "../engine/prob.js";
import { readDXF, dxfLayers, guessRole, upperOutline, sectionFromDXF } from "../engine/dxf.js";

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
  verify: null, optimise: null, prob: null, fem: null, offline: false, dirty: false,
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
  reinf: '<path d="M3 4l14 6M3 9l14 6M5 2v16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>',
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
function loadItems() {
  const items = [
    { k: "load.q", l: "Surcharge on the crest", sub: "traffic, storage, cranes", u: "kPa", min: 0, max: 100, step: 1, slider: true, picks: [0, 5, 10, 20, 50] },
    { k: "load.setback", l: "Set back from the crest edge", u: "m", min: 0, max: 30, step: 0.5, show: (p) => +p.load.q > 0 },
    { k: "load.width", l: "Loaded width", u: "m", min: 0.5, max: 60, step: 0.5, show: (p) => +p.load.q > 0 },
  ];
  return items;
}
const NAIL_ITEMS = [
    { kind: "toggle", k: "nails.on", l: "Soil nails / anchors" },
    { k: "nails.rows", l: "Rows", u: "", min: 1, max: 12, step: 1, show: (p) => p.nails.on },
    { k: "nails.length", l: "Length", u: "m", min: 1, max: 30, step: 0.5, show: (p) => p.nails.on },
    { k: "nails.angle", l: "Inclination below horizontal", u: "°", min: 0, max: 45, step: 1, show: (p) => p.nails.on },
    { k: "nails.T", l: "Tensile capacity per row", sub: "per metre run of slope", u: "kN/m", min: 0, max: 1000, step: 5, show: (p) => p.nails.on },
    { k: "nails.qb", l: "Pull-out resistance", sub: "per metre of nail beyond the slip, per metre run", u: "kN/m²", min: 0, max: 500, step: 5, show: (p) => p.nails.on },
];
const GRID_ITEMS = [
    { kind: "toggle", k: "grids.on", l: "Geogrid layers in the fill", sub: "face to face; basal reinforcement on soft ground" },
    { k: "grids.n", l: "Layers", u: "", min: 1, max: 40, step: 1, show: (p) => p.grids.on },
    { k: "grids.bottom", l: "Lowest layer above ground", u: "m", min: 0, max: 10, step: 0.05, show: (p) => p.grids.on },
    { k: "grids.spacing", l: "Vertical spacing", u: "m", min: 0.1, max: 3, step: 0.05, show: (p) => p.grids.on && +p.grids.n > 1 },
    { k: "grids.T", l: "Design tensile strength", sub: "long-term, after reduction factors", u: "kN/m", min: 0, max: 2000, step: 5, show: (p) => p.grids.on },
    { k: "grids.Ci", l: "Interaction coefficient Ci", sub: "pull-out: 2 Ci (c + σv tan φ) per metre of grid", u: "", min: 0, max: 1.2, step: 0.05, show: (p) => p.grids.on },
];
const pileItems = (where) => [
    { kind: "toggle", k: "piles.on", l: "Row of piles or sheet piles", sub: "a shear force where the slip cuts them" },
    { k: "piles.x", l: where.l, sub: where.sub, u: "m", step: 0.5, show: (p) => p.piles.on },
    { k: "piles.length", l: "Length below ground", u: "m", min: 0.5, max: 60, step: 0.5, show: (p) => p.piles.on },
    { k: "piles.Vp", l: "Shear capacity of one pile", sub: "design lateral resistance (or per metre of wall with spacing 1)", u: "kN", min: 0, max: 10000, step: 10, show: (p) => p.piles.on },
    { k: "piles.spacing", l: "Spacing along the slope", u: "m", min: 0.1, max: 20, step: 0.1, show: (p) => p.piles.on },
];
const reinfSum = (p) => [p.nails?.on && "nails", p.grids?.on && `${p.grids.n} geogrid${+p.grids.n > 1 ? "s" : ""}`, p.piles?.on && "piles"].filter(Boolean).join(" · ") || "none";

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
      { kind: "toggle", k: "water.flow", l: "Flow net (finite elements)", sub: "pore pressures from steady seepage through each soil's permeability k, between these two levels", show: (p) => p.water.on },
    ] },
    { g: "Loads", icon: "load", sum: (p) => `${p.load.q} kPa`, items: loadItems() },
    { g: "Reinforcement", icon: "reinf", sum: reinfSum, items: [...NAIL_ITEMS, ...pileItems({ l: "Pile row, from the toe", sub: "horizontal distance into the slope" })] },
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
      { kind: "toggle", k: "water.flow", l: "Flow net (finite elements)", sub: "seepage through the fill and foundation by their permeabilities k, instead of a straight line to the toe", show: (p) => p.water.on },
      { kind: "toggle", k: "water.staged", l: "Staged drawdown (three-stage method)", sub: "Duncan, Wright and Wong (1990), USACE EM 1110-2-1902: undrained strengths from the consolidation before drawdown in soils that do not drain freely", show: (p) => p.water.on },
    ] },
    { g: "Loads", icon: "load", sum: (p) => `${p.load.q} kPa`, items: loadItems() },
    { g: "Reinforcement", icon: "reinf", sum: reinfSum, items: [...GRID_ITEMS, ...pileItems({ l: "Pile row, from the toe", sub: "into the slope being checked (land side, or water side for drawdown)" })] },
    { g: "Earthquake", icon: "quake", sum: (p) => (p.seismic.on ? `ag ${p.seismic.ag} g` : "off"), items: earthquakeItems() },
    { g: "Design", icon: "design", sum: (p) => (p.design.basis === "ec7" ? "EC7" : "FoS"), items: designItems() },
    { g: "Advanced", icon: "gear", items: advancedItems() },
  ],
  section: [
    { g: "Section", icon: "shape", open: true, sum: (p) => `${parsePoints(p.ground).length} ground points`, items: [
      { kind: "dxf" },
      { kind: "points", k: "ground", l: "Ground surface", sub: "x, y per line, left to right. Paste from Excel or CAD." },
      { k: "base", l: "Hard base level", sub: "no slip goes below it", u: "m", step: 0.5 },
    ] },
    { g: "Layers", icon: "ground", open: true, sum: (p) => `${(p.layers || []).length} layers`, items: [{ kind: "layers" }] },
    { g: "Water", icon: "water", sum: (p) => ({ none: "none", line: "water line", ru: `ru ${p.water.ru}`, flow: "flow net" }[p.water.mode] || ""), items: [
      { kind: "seg", k: "water.mode", l: "Pore water", options: [["none", "None"], ["line", "Water line"], ["flow", "Flow net"], ["ru", "ru"]] },
      { k: "water.left", l: "Water level at the left end", sub: "blank: no flow across the left end", u: "m", min: -500, max: 3000, step: 0.25, blank: true, ph: "none", show: (p) => p.water.mode === "flow" },
      { k: "water.right", l: "Water level at the right end", sub: "blank: no flow across the right end", u: "m", min: -500, max: 3000, step: 0.25, blank: true, ph: "none", show: (p) => p.water.mode === "flow" },
      { kind: "html", show: (p) => p.water.mode === "flow", html: () => `<div class="note">Steady seepage by finite elements through each layer's permeability k. The water stands on the ground wherever the ground near an end is below its level; elsewhere the ground is a seepage face.</div>` },
      { kind: "points", k: "water.line", l: "Piezometric line", sub: "x, y per line. Above the ground it is ponded water.", show: (p) => p.water.mode === "line" },
      { kind: "html", show: (p) => p.water.mode === "line", html: () => `<button type="button" class="linkish" data-copy-ground>Put the water at the ground surface</button>` },
      { k: "water.ru", l: "Pore pressure ratio ru", u: "", min: 0, max: 1, step: 0.05, show: (p) => p.water.mode === "ru" },
    ] },
    { g: "Loads", icon: "load", sum: (p) => `${p.load.q} kPa`, items: [
      { k: "load.q", l: "Surcharge", u: "kPa", min: 0, max: 200, step: 1, slider: true, picks: [0, 5, 10, 20, 50] },
      { k: "load.x1", l: "From x", u: "m", step: 0.5, show: (p) => +p.load.q > 0 },
      { k: "load.x2", l: "To x", u: "m", step: 0.5, show: (p) => +p.load.q > 0 },
    ] },
    { g: "Reinforcement", icon: "reinf", sum: reinfSum, items: pileItems({ l: "Pile row at x", sub: "in the section's own coordinates" }) },
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
    { g: "Loads", icon: "load", sum: (p) => `${p.load.q} kPa`, items: loadItems() },
    { g: "Reinforcement", icon: "reinf", sum: reinfSum, items: [...GRID_ITEMS, ...pileItems({ l: "Pile row, from the toe", sub: "into the slope being checked (land side, or water side for drawdown)" })] },
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
    return `<div class="f">${lab}<span class="num"><input type="number" inputmode="decimal" data-k="${it.k}" value="${val}" step="${it.step ?? "any"}" ${it.min !== undefined ? `min="${it.min}"` : ""} ${it.max !== undefined ? `max="${it.max}"` : ""} ${it.blank ? `placeholder="${it.ph || "auto"}"` : ""}><span class="unit">${esc(it.u || "")}</span></span>${it.slider ? `<input type="range" data-k="${it.k}" min="${it.min}" max="${it.max}" step="${it.step}" value="${val}" aria-label="${esc(it.l)}">` : ""}${it.picks ? `<div class="picks" style="grid-column:1/-1">${it.picks.map((v2) => `<button type="button" data-pick="${it.k}" data-v="${v2}">${v2}</button>`).join("")}</div>` : ""}</div>`;
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
  if (kind === "dxf") return dxfWidget();
  return "";
}

// ------------------------------------------------------------------ DXF import

let dxf = null;   // { file, segs, layers: [{ name, role, preset, ... }], scale, top, error }
const DXF_ROLES = [["ground", "Ground surface"], ["layer", "Top of a soil"], ["water", "Water line"], ["ignore", "Ignore"]];
function dxfWidget() {
  if (!dxf) return `<div class="f wide dxf"><label class="btn btn-ghost btn-sm filebtn">Import a DXF drawing<input type="file" accept=".dxf,application/dxf,image/vnd.dxf" data-dxf hidden></label>
    <span class="note">From AutoCAD, Civil 3D, Slide or SLOPE/W (ASCII DXF). Each CAD layer becomes the ground, the top of a soil or the water line.</span></div>`;
  const sc = dxf.scale;
  const rows = dxf.layers.map((L, i) => `<div class="dxfrow"><div><b>${esc(L.name)}</b><span class="note"> ${L.segments} lines · x ${fx1(L.x0 * sc)} to ${fx1(L.x1 * sc)}, y ${fx1(L.y0 * sc)} to ${fx1(L.y1 * sc)}</span></div>
    <select data-dxfrole="${i}" aria-label="What ${esc(L.name)} is">${DXF_ROLES.map(([v, n]) => `<option value="${v}" ${L.role === v ? "selected" : ""}>${n}</option>`).join("")}</select>
    ${L.role === "layer" ? `<select data-dxfsoil="${i}" aria-label="Soil below ${esc(L.name)}">${soilOptions(L.preset)}</select>` : ""}</div>`).join("");
  return `<div class="f wide dxf glass"><div class="row between"><b>${esc(dxf.file)}</b><button type="button" class="linkish" data-dxfcancel>Cancel</button></div>
    <div class="seg" role="group" aria-label="Drawing units">${[[1, "metres"], [0.001, "millimetres"]].map(([v, n]) => `<button type="button" data-dxfscale="${v}" aria-pressed="${sc === v}">${n}</button>`).join("")}</div>
    ${dxfPreview()}
    <div class="dxfrow"><div>Soil under the ground</div><select data-dxftop aria-label="Soil under the ground">${soilOptions(dxf.top)}</select></div>
    ${rows}
    ${dxf.error ? `<div class="pill warn">${esc(dxf.error)}</div>` : ""}
    <button type="button" class="btn btn-sm" data-dxfapply>Use this section</button>
    <span class="note">Soil tops are ordered from the top down. Each layer is read as the upper edge of its lines, so a closed soil region gives its top. A flat line at the very bottom becomes the hard base.</span></div>`;
}
const fx1 = (v) => (Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(1));
function dxfPreview() {
  const sc = dxf.scale, W = 320, H = 150;
  const all = dxf.layers.filter((L) => L.role !== "ignore");
  if (!all.length) return "";
  const x0 = Math.min(...all.map((L) => L.x0)) * sc, x1 = Math.max(...all.map((L) => L.x1)) * sc;
  const y0 = Math.min(...all.map((L) => L.y0)) * sc, y1 = Math.max(...all.map((L) => L.y1)) * sc;
  const s = Math.min((W - 12) / ((x1 - x0) || 1), (H - 12) / ((y1 - y0) || 1));
  const X = (x) => 6 + (x - x0) * s, Y = (y) => H - 6 - (y - y0) * s;
  const col = { ground: "#5b4a2e", layer: "#a07c4a", water: "#2a78d6" };
  const paths = all.map((L) => {
    const pts = upperOutline(dxf.segs[L.name], sc);
    return pts.length > 1 ? `<path d="${pts.map((p, k) => `${k ? "L" : "M"}${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join("")}" fill="none" stroke="${col[L.role]}" stroke-width="${L.role === "ground" ? 2 : 1.2}" ${L.role === "water" ? 'stroke-dasharray="5 3"' : ""}/>` : "";
  }).join("");
  return `<svg viewBox="0 0 ${W} ${H}" class="dxfprev" role="img" aria-label="Preview of the imported section">${paths}</svg>`;
}
async function dxfLoad(file) {
  try {
    const text = await file.text();
    const segs = readDXF(text);
    const layers = dxfLayers(segs).map((L) => ({ ...L, role: guessRole(L.name), preset: "stiffClay" }));
    if (!layers.length) { toast("No lines found in that drawing (is it an ASCII DXF?)", true); return; }
    // nothing named like the ground: take the layer that spans the widest
    if (!layers.some((L) => L.role === "ground")) layers[0].role = "ground";
    const span = Math.max(...layers.map((L) => L.x1 - L.x0));
    dxf = { file: file.name, segs, layers, scale: span > 5000 ? 0.001 : 1, top: "sand" };
  } catch (e) { toast("Could not read that drawing: " + e.message, true); return; }
  renderInputs();
}
function dxfApply() {
  const r = sectionFromDXF(dxf.segs, dxf.layers, { scale: dxf.scale, top: dxf.top });
  if (r.error) { dxf.error = r.error; renderInputs(); return; }
  const p = state.project;
  p.ground = r.ground; p.base = r.base; p.layers = r.layers;
  if (r.water) { p.water.mode = p.water.mode === "flow" ? "flow" : "line"; p.water.line = r.water.line; }
  const [a, b] = r.extent;
  if (p.load) { p.load.x1 = Math.max(a, Math.min(b, +p.load.x1 || a)); p.load.x2 = Math.max(a, Math.min(b, +p.load.x2 || a)); }
  if (p.piles) p.piles.x = (a + b) / 2;
  toast(`Section imported from ${dxf.file}`);
  dxf = null;
  changed(true);
}

function soilWidget(it, p) {
  const spec = get(p, it.k) || {};
  const s = soilFrom(spec);
  const editing = spec._edit;
  const val = (k) => (spec[k] !== undefined && spec[k] !== null && spec[k] !== "" ? spec[k] : "");
  const ph = (k) => PRESETS[s.preset]?.[k] ?? { cR: s.c, phiR: Math.min(14, s.phi), kRatio: 1 }[k] ?? "";
  const flowOn = !!(p.water?.flow || p.water?.mode === "flow");
  const stagedOn = !!(p.water?.on && p.water?.staged && p.type === "embankment");
  const kFields = () => (flowOn || stagedOn ? fld("k", "Permeability k", "m/s") : "") + (flowOn ? fld("kRatio", "Anisotropy kh / kv", "") : "")
    + (stagedOn && !s.hb ? `${fld("cR", "R envelope cR (CU, total)", "kPa")}${fld("phiR", "R envelope φR", "°")}<div class="f"><span class="lab">Drains freely in drawdown</span><select data-k="${it.k}.drains"><option value="" ${spec.drains !== "yes" && spec.drains !== "no" ? "selected" : ""}>auto (k ≥ 1e-5 m/s)</option><option value="yes" ${spec.drains === "yes" ? "selected" : ""}>yes</option><option value="no" ${spec.drains === "no" ? "selected" : ""}>no</option></select></div>` : "");
  const fld = (k, l, u, show = true) => (show ? `<div class="f"><span class="lab">${l}</span><span class="num"><input type="number" inputmode="decimal" data-k="${it.k}.${k}" value="${val(k)}" placeholder="${ph(k)}" step="any"><span class="unit">${u}</span></span></div>` : "");
  return `<div class="f wide"><span class="lab">${esc(it.l)}</span><select data-soil="${it.k}">${soilOptions(s.preset)}</select>
    <div class="soil-sum"><span><b>γ</b> ${s.gamma}/${s.gsat} kN/m³</span>${s.hb ? `<span><b>GSI</b> ${s.GSI}</span><span><b>mi</b> ${s.mi}</span><span><b>σci</b> ${s.sci} MPa</span>${s.D ? `<span><b>D</b> ${s.D}</span>` : ""}` : `<span><b>c'</b> ${s.c} kPa</span><span><b>φ'</b> ${s.phi}°</span>`}${flowOn ? `<span><b>k</b> ${s.k.toExponential(0)} m/s</span>` : ""}${!s.hb && s.clay && s.su > 0 ? `<span><b>su</b> ${s.su}${s.suGrad ? ` + ${s.suGrad}/m` : ""} kPa</span>` : ""}
    <button type="button" class="linkish" data-soiledit="${it.k}">${editing ? "Done" : "Use site values"}</button></div>
    ${editing && s.hb ? `<div class="subgrid">${fld("gamma", "Unit weight above water γ", "kN/m³")}${fld("gsat", "Saturated unit weight γsat", "kN/m³")}${fld("GSI", "Geological Strength Index GSI", "")}${fld("mi", "Intact rock constant mi", "")}${fld("sci", "Intact compressive strength σci", "MPa")}${fld("D", "Disturbance D", "0–1")}${kFields()}<div class="note">Generalised Hoek-Brown (2002). Each slice takes the tangent strength at the normal stress on its base, iterated to convergence. Use D 0.7 to 1 for blasted faces.</div></div>` : ""}
    ${editing && !s.hb ? `<div class="subgrid">${fld("gamma", "Unit weight above water γ", "kN/m³")}${fld("gsat", "Saturated unit weight γsat", "kN/m³")}${fld("c", "Effective cohesion c'", "kPa")}${fld("phi", "Effective friction angle φ'", "°")}${fld("su", "Undrained strength su (clays)", "kPa", s.clay || it.alwaysSu)}${fld("suGrad", "su increase with depth", "kPa/m", s.clay || it.alwaysSu)}${fld("suMax", "su cap", "kPa", it.alwaysSu)}${kFields()}<div class="note">Blank fields keep the typical value shown. Typical values are a starting point; use site data for design.</div></div>` : ""}</div>`;
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
  if (el.dataset.dxf !== undefined) { if (ev.type === "change" && el.files?.[0]) dxfLoad(el.files[0]); return; }
  if (el.dataset.dxfrole !== undefined) { dxf.layers[+el.dataset.dxfrole].role = el.value; dxf.error = null; renderInputs(); return; }
  if (el.dataset.dxfsoil !== undefined) { dxf.layers[+el.dataset.dxfsoil].preset = el.value; return; }
  if (el.dataset.dxftop !== undefined) { dxf.top = el.value; return; }
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
  if (b.dataset.dxfcancel !== undefined) { dxf = null; renderInputs(); return; }
  if (b.dataset.dxfscale) { dxf.scale = +b.dataset.dxfscale; renderInputs(); return; }
  if (b.dataset.dxfapply !== undefined) { dxfApply(); return; }
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
  if (state.prob && !state.prob.running) state.prob = null;
  if (state.fem && !state.fem.running) state.fem = null;
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
  } else if (m.kind === "probStep") {
    state.prob = { ...(state.prob || {}), running: true, done: m.done, n: m.n };
    setBusy(true, `Sample ${m.done} of ${m.n}…`);
    if (state.tab === "prob") renderPanel();
  } else if (m.kind === "probDone") {
    jobRunning = false; setBusy(false);
    state.prob = { result: m.result, running: false };
    if (m.result.error) toast(m.result.error, true);
    if (state.tab === "prob") renderPanel();
  } else if (m.kind === "femStep") {
    state.fem = { ...(state.fem || {}), running: true, runs: m.run, srf: m.srf };
    setBusy(true, `Strength reduction ${f2(m.srf)}…`);
    if (state.tab === "fem") renderPanel();
  } else if (m.kind === "femDone") {
    jobRunning = false; setBusy(false);
    state.fem = { result: m.result, running: false };
    if (m.result.error) toast(m.result.error, true);
    if (state.tab === "fem") renderPanel();
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
  ["optimise", "Optimise"], ["prob", "Probability"], ["fem", "Finite elements"], ["verify", "Verification"], ["about", "How it works"],
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
  else if (t === "prob") P.innerHTML = probPanel();
  else if (t === "fem") P.innerHTML = femPanel();
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
    <p class="explain mt-sm">${esc(c.note)}${c.fellBack ? " The rigorous method did not converge on this surface, so Bishop is shown." : ""}${c.fromCircle ? ` A non-circular surface was found ${f1((1 - c.F / c.fromCircle) * 100)}% lower than the best circle.` : ""}${c.staged ? ` Stages on the critical circle: before drawdown F = ${f3(c.staged.F1)}; undrained after drawdown F = ${f3(c.staged.F2)}; with the drained strength where lower (${c.staged.drainedSlices} of ${c.staged.slices} slices) F = ${f3(c.staged.F3)}. The conventional no-drainage analysis gives ${f3(c.staged.conventional)}. R envelope by default φR 14°, cR = c' unless entered: use CU test values.` : ""}</p>
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

// ------------------------------------------------------------------ probability

/** USACE ETL 1110-2-547 (1997): expected performance by reliability index. */
const PERFORMANCE = [[5, "High", "good"], [4, "Good", "good"], [3, "Above average", "good"], [2.5, "Below average", "warn"], [2, "Poor", "bad"], [1.5, "Unsatisfactory", "bad"], [-Infinity, "Hazardous", "bad"]];
const performanceOf = (b) => PERFORMANCE.find(([t]) => b >= t);

/** Which variables the project has, for the COV inputs. */
function probProps(p) {
  const out = new Set(["gamma"]);
  const soils = [];
  for (const G of SPEC[p.type]) for (const it of G.items) if (it.kind === "soil" && (!it.show || it.show(p))) soils.push(soilFrom(get(p, it.k)));
  if (p.type === "section") for (const L of p.layers || []) soils.push(soilFrom(L.soil));
  for (const s of soils) {
    if (s.hb) { out.add("GSI"); out.add("sci"); continue; }
    out.add("tanphi"); if (s.c > 0) out.add("c"); if (s.clay && s.su > 0) out.add("su");
  }
  return ["tanphi", "c", "su", "GSI", "sci", "gamma"].filter((k) => out.has(k));
}

function histSVG(r) {
  const W = 560, H = 190, pad = { l: 34, r: 10, t: 12, b: 28 };
  const x0 = Math.min(r.min, 0.95), x1 = Math.max(r.max, r.deterministic * 1.02);
  const X = (x) => pad.l + (x - x0) / (x1 - x0) * (W - pad.l - pad.r);
  const top = Math.max(...r.hist.map((h) => h.n));
  const Y = (n) => H - pad.b - n / top * (H - pad.t - pad.b);
  const bars = r.hist.map((h) => `<rect x="${X(h.x0) + 0.5}" y="${Y(h.n)}" width="${Math.max(0.5, X(h.x1) - X(h.x0) - 1)}" height="${H - pad.b - Y(h.n)}" fill="${h.x1 <= 1 ? "var(--critical)" : "var(--series-1, #2a78d6)"}" opacity="${h.x1 <= 1 ? 0.85 : 0.75}"/>`).join("");
  const step = (x1 - x0) > 1.5 ? 0.5 : (x1 - x0) > 0.6 ? 0.2 : 0.1;
  let ticks = "";
  for (let x = Math.ceil(x0 / step) * step; x <= x1 + 1e-9; x += step) ticks += `<text x="${X(x)}" y="${H - 10}" font-size="10" text-anchor="middle" fill="var(--muted)">${+x.toFixed(2)}</text>`;
  return `<svg viewBox="0 0 ${W} ${H}" class="chart" role="img" aria-label="Distribution of the factor of safety">
    <line x1="${pad.l}" y1="${H - pad.b}" x2="${W - pad.r}" y2="${H - pad.b}" stroke="var(--grid)"/>${bars}${ticks}
    <line x1="${X(1)}" y1="${pad.t - 4}" x2="${X(1)}" y2="${H - pad.b}" stroke="var(--critical)" stroke-width="1.5" stroke-dasharray="4 3"/><text x="${X(1) + 4}" y="${pad.t + 6}" font-size="10" fill="var(--critical)">F = 1</text>
    <line x1="${X(r.deterministic)}" y1="${pad.t - 4}" x2="${X(r.deterministic)}" y2="${H - pad.b}" stroke="var(--ink)" stroke-width="1.2"/><text x="${X(r.deterministic) + 5}" y="${pad.t + 6}" font-size="10" fill="var(--ink-2)">design ${f2(r.deterministic)}</text>
    <text x="${W - pad.r}" y="${pad.t + 6}" font-size="10" text-anchor="end" fill="var(--muted)">factor of safety →</text></svg>`;
}

function tornadoSVG(r) {
  const S = r.sens.filter((s) => Number.isFinite(s.low) && Number.isFinite(s.high));
  if (!S.length) return "";
  const W = 560, row = 24, pad = { l: 170, r: 40, t: 8 }, H = pad.t + row * S.length + 22;
  const lo = Math.min(...S.map((s) => s.low)), hi = Math.max(...S.map((s) => s.high));
  const X = (x) => pad.l + (x - lo) / ((hi - lo) || 1) * (W - pad.l - pad.r);
  const bars = S.map((s, i) => { const y = pad.t + i * row; return `<text x="${pad.l - 8}" y="${y + 15}" font-size="11" text-anchor="end" fill="var(--ink-2)">${esc(s.name)}</text>
    <rect x="${X(s.low)}" y="${y + 4}" width="${Math.max(1, X(s.high) - X(s.low))}" height="${row - 8}" rx="3" fill="var(--series-1, #2a78d6)" opacity="0.8"/>
    <text x="${X(s.high) + 4}" y="${y + 15}" font-size="10" fill="var(--muted)">${f2(s.low)}–${f2(s.high)}</text>`; }).join("");
  return `<svg viewBox="0 0 ${W} ${H}" class="chart" role="img" aria-label="Sensitivity of F to each variable">
    <line x1="${X(r.atMeans)}" y1="${pad.t}" x2="${X(r.atMeans)}" y2="${H - 18}" stroke="var(--ink)" stroke-width="1"/>${bars}
    <text x="${X(r.atMeans)}" y="${H - 4}" font-size="10" text-anchor="middle" fill="var(--muted)">F at the means ${f2(r.atMeans)}</text></svg>`;
}

function probPanel() {
  const p = state.project, c = currentCase(), st = state.prob;
  if (!c) return "";
  const cov = { ...COV, ...(p.prob?.cov || {}) };
  const props = probProps(p);
  const fields = props.map((k) => `<div class="f"><span class="lab">COV of ${COV_LABEL[k]}</span><span class="num"><input type="number" inputmode="decimal" min="0" max="100" step="1" data-pk="cov.${k}" value="${+(cov[k] * 100).toFixed(1)}"><span class="unit">%</span></span></div>`).join("");
  const n = p.prob?.n || 2000;
  const r = st?.result && !st.result.error && st.result.case.key === c.key ? st.result : null;
  let out = `<p class="explain">Soil and rock properties are never known exactly. Here each one is uncertain, lognormal around the value entered, and ${n.toLocaleString()} combinations are solved on the critical surface of <b>${esc(c.name)}</b>. The share that fail gives the probability of failure, and β says how many standard deviations the mean F sits above 1.</p>
    <div class="probgrid mt-sm">${fields}<div class="f"><span class="lab">Samples</span><select data-pk="n">${[500, 1000, 2000, 5000, 10000].map((v) => `<option value="${v}" ${v === n ? "selected" : ""}>${v.toLocaleString()}</option>`).join("")}</select></div></div>
    <div class="row mt-sm"><button class="btn btn-primary" data-prob ${st?.running ? "disabled" : ""}>${st?.running ? `Sampling… ${st.done || 0} of ${st.n || n}` : r ? "Run again" : "Run the Monte Carlo"}</button><span class="note">Latin hypercube, fixed seed: the same inputs always give the same answer. Typical COVs from Phoon and Kulhawy (1999) and Duncan (2000).</span></div>`;
  if (r) {
    const perf = performanceOf(r.betaLN);
    out += `<div class="kpis mt">
      <div class="kpi"><div class="k">Probability of failure</div><div class="v">${r.pf < 0.0005 ? `< ${(1 / r.n * 100).toFixed(2)}%` : (r.pf * 100).toFixed(r.pf < 0.01 ? 2 : 1) + "%"}</div><div class="s">${r.fails} of ${r.n.toLocaleString()} samples below F = 1 · lognormal fit ${(r.pfLN * 100).toFixed(r.pfLN < 0.01 ? 3 : 1)}%</div></div>
      <div class="kpi"><div class="k">Reliability index</div><div class="v">β ${f2(r.betaLN)}</div><div class="s"><span class="pill ${perf[2]}">${perf[1]}</span> USACE (1997) · normal β ${f2(r.betaN)}</div></div>
      <div class="kpi"><div class="k">Mean F</div><div class="v">${f3(r.mean)}</div><div class="s">SD ${f3(r.sd)} · COV ${f1(r.cov * 100)}% · design ${f3(r.deterministic)}</div></div>
      <div class="kpi"><div class="k">5% – 95%</div><div class="v">${f2(r.p05)} – ${f2(r.p95)}</div><div class="s">median ${f3(r.p50)} · ${esc(r.methodName)}</div></div>
    </div>
    <h3 class="mt">Distribution of F</h3>${histSVG(r)}
    <h3 class="mt">What matters most</h3><p class="note">Each variable alone moved one standard deviation either way, the others at their means.</p>${tornadoSVG(r)}`;
  }
  return out;
}

// ------------------------------------------------------------------ finite elements

function femPanel() {
  const c = currentCase(), st = state.fem;
  if (!c) return "";
  const r = st?.result && !st.result.error && st.result.case.key === c.key ? st.result : null;
  let out = `<p class="explain">A second, independent answer for <b>${esc(c.name)}</b>: the slope as a continuum of finite elements, with the soil strengths divided by a factor until it can no longer stand (Griffiths and Lane 1999). No slip surface is assumed; the mechanism forms by itself.</p>
    <div class="row mt-sm"><button class="btn btn-primary" data-fem ${st?.running ? "disabled" : ""}>${st?.running ? `Solving… trial ${st.runs || 0}${st.srf ? `, SRF ${f2(st.srf)}` : ""}` : r ? "Run again" : "Run the strength reduction"}</button><span class="note">Takes a few seconds: each trial factor runs up to 500 viscoplastic iterations.</span></div>`;
  if (r) {
    const d = c.F ? (r.F / c.F - 1) * 100 : NaN;
    const agree = Math.abs(d) <= 5 ? ["good", "agrees"] : Math.abs(d) <= 10 ? ["warn", "close"] : ["bad", "differs"];
    out += `<div class="kpis mt">
      <div class="kpi"><div class="k">Finite element F</div><div class="v" style="color:${fosColour(r.F, c.target)}">${f2(r.F)}</div><div class="s">stable at ${f3(r.F)}, fails at ${f3(r.failedAt)} · needs ${f2(c.target)}</div></div>
      <div class="kpi"><div class="k">Limit equilibrium F</div><div class="v">${f2(c.F)}</div><div class="s">${esc(METHOD_NAMES[c.method] || "")}</div></div>
      <div class="kpi"><div class="k">Difference</div><div class="v">${d >= 0 ? "+" : ""}${f1(d)}%</div><div class="s"><span class="pill ${agree[0]}">${agree[1]}</span> within 5% is the usual agreement</div></div>
      <div class="kpi"><div class="k">Model</div><div class="v">${r.elements} quads</div><div class="s">${r.dof.toLocaleString()} unknowns · ${r.runs} trials</div></div>
    </div>
    <div class="row mt-sm"><div class="seg" role="group" aria-label="Show">${[["fail", "At failure"], ["stable", "Last stable"]].map(([k, n]) => `<button type="button" data-fem-show="${k}" aria-pressed="${(state.femShow || "fail") === k}">${n}</button>`).join("")}</div><span class="note">${(state.femShow || "fail") === "fail" ? "Colour: the plastic shear strain added between the last stable factor and failure, which is the mechanism; the mesh moves as it does." : "Colour: plastic shear strain at the last stable factor; mesh displaced."} Exaggerated.</span></div>
    ${femSVG(state.femShow === "stable" ? r.stable : r.mesh, c)}
    ${r.reinforced ? `<div class="pill warn mt-sm">Nails, anchors, geogrids and piles are not in the finite element model: compare with the case without them.</div>` : ""}`;
  }
  return out;
}

function femSVG(m, c) {
  if (!m) return "";
  const W = 760, H = 300, pad = 12;
  const x0 = Math.min(...m.X), x1 = Math.max(...m.X), y0 = Math.min(...m.Y), y1 = Math.max(...m.Y);
  const s = Math.min((W - 2 * pad) / (x1 - x0), (H - 2 * pad) / (y1 - y0));
  const ox = pad + ((W - 2 * pad) - s * (x1 - x0)) / 2, oy = pad + ((H - 2 * pad) - s * (y1 - y0)) / 2;
  const dmax = Math.max(1e-12, ...m.dx.map((v, k) => Math.hypot(v, m.dy[k])));
  const mag = 0.05 * (x1 - x0) / dmax;
  const X = (k) => ox + (m.X[k] + mag * m.dx[k] - x0) * s, Y = (k) => H - oy - (m.Y[k] + mag * m.dy[k] - y0) * s;
  const smax = Math.max(1e-12, ...m.shear);
  const order = [0, 4, 1, 5, 2, 6, 3, 7];
  const polys = m.els.map((e, i) => {
    const t = Math.min(1, m.shear[i] / smax);
    const col = t < 0.08 ? "var(--raised)" : `rgba(235, 104, 52, ${Math.min(1, 0.1 + t).toFixed(2)})`;
    return `<path d="${order.map((a, k) => `${k ? "L" : "M"}${X(e[a]).toFixed(1)},${Y(e[a]).toFixed(1)}`).join("")}Z" fill="${col}" stroke="var(--grid)" stroke-width="0.5"/>`;
  }).join("");
  return `<svg viewBox="0 0 ${W} ${H}" class="chart mt-sm" role="img" aria-label="Finite element mesh with the plastic shear strain">${polys}</svg>
    <p class="note">${m.converged ? `Settled after ${m.iters} iterations.` : `Did not settle within ${m.iters} iterations: the failure mechanism is the orange band.`} Displacements are exaggerated; they come from E = 100 MPa and ν = 0.3, which do not change the factor of safety.</p>`;
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
  <p><b>Flow net.</b> With the flow net on, pore pressures come from steady seepage solved by finite elements (linear triangles on a mesh that follows the ground) through each soil's permeability k and anisotropy kh/kv. The phreatic surface is found as SEEP/W and Slide do: above it the permeability falls to a small residual, ground above the outside water is a seepage face, and the iterations repeat until the heads settle. It reproduces Darcy flow exactly and the Dupuit–Charny discharge of a rectangular dam to within 2% (Verification). After a rapid drawdown the heads stay at the steady flow net, held at most at the ground surface.</p>
  <p><b>Staged drawdown.</b> Optionally, the embankment drawdown case uses the three-stage method of Duncan, Wright and Wong (1990), adopted in USACE EM 1110-2-1902 Appendix G. Stage 1 solves the slope at full water with steady seepage and takes the effective normal and shear stress on each slice base as its consolidation stresses. Stage 2 gives each slice in a soil that does not drain freely (k below 1e-5 m/s unless set) an undrained strength interpolated by the consolidation stress ratio Kc between the R envelope (Kc = 1) and the effective envelope (Kc = Kf), the lower if they cross. Stage 3 uses the drained strength where it is lower at the stage 2 effective stresses. All three are solved on the same surface, and the critical circle is searched with the staged F itself.</p>
  <p><b>Finite elements.</b> The Finite elements tab gives an independent factor of safety by strength reduction (Griffiths and Lane 1999; Smith, Griffiths and Margetts): plane strain, eight-node quadrilaterals with reduced integration on a mesh that follows the ground and the base, elastic-viscoplastic Mohr-Coulomb with zero dilation, gravity switched on at once, water on the ground as a pressure, pore pressures subtracted for drained soils. c', tan φ' and su are divided by a trial factor until the iterations no longer settle; that factor, found by bisection, is F. It reproduces Griffiths and Lane's undrained example (1.45) and Bishop and Morgenstern's c'-φ' chart value (1.38) within the tolerances in Verification.</p>
  <p><b>Load cases.</b> Cut slopes: long term (drained), short term (undrained clays), seismic. Embankments: end of construction, steady seepage, rapid drawdown, seismic. Revetments: high and low water, drawdown under the wave trough, seismic. Targets follow USACE EM 1110-2-1902 or, with Eurocode 7, the M2 partial factors with an over-design factor of 1.0.</p>
  <p><b>Earthquake.</b> Pseudo-static kh = 0.5·ag·S·ST, kv = ±0.5·kh (EN 1998-5), both kv directions checked; yield acceleration by bisection; permanent displacement by Jibson (2007).</p>
  <p><b>Armour.</b> Rock by Hudson and by Van der Meer (1988), or its shallow-water form (Van Gent et al. 2003) when h &lt; 3Hs, with the larger governing; EN 13383 gradings; toe by Van der Meer (1998); run-up and overtopping by EurOtop (2018). Accropode™ and Accropode™ II by Hudson with CLI's design KD (15 / 11.5 and 16 / 12.3), valid on 4:3 to 3:2 slopes; Accropode is a trademark of CLI, and units must be designed and placed to CLI's guidance.</p>
  <p><b>Rock.</b> Rock masses follow the generalised Hoek-Brown criterion (Hoek, Carranza-Torres and Corkum 2002) from GSI, mi, σci and D. Each slice takes the tangent to the envelope at the effective normal stress on its base (Balmer 1952); the solution is repeated with the new normal stresses until every slice carries the envelope strength. The equivalent c', φ' of Hoek et al. (2002) is in the verification set for comparison.</p>
  <p><b>Reinforcement.</b> Nails and anchors pull along their axis, limited by their strength and their bond beyond the slip. Geogrids pull horizontally where the slip cuts them, limited by their design strength and by pull-out of the shorter end, 2 Ci (c + σv tan φ) per metre. A row of piles or a sheet-pile wall adds its shear capacity per metre run (pile capacity / spacing) where the slip cuts it, against the movement. Every force enters the slices at its own point, in all methods.</p>
  <p><b>Probability.</b> Each soil or rock property is lognormal around the value entered with its coefficient of variation; one variable per material and property. Latin hypercube samples from a fixed seed are solved on the critical surface of the load case by the governing method. The probability of failure is the share with F &lt; 1; β is given for a lognormal F, with the USACE (1997) performance levels. Properties are taken as independent, which is on the safe side for c' and φ'.</p>
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
  if (b.dataset.prob !== undefined) {
    state.prob = { running: true, done: 0 };
    run("prob", { caseKey: currentCase()?.key }); setBusy(true, "Sampling…"); renderPanel(); return;
  }
  if (b.dataset.fem !== undefined) {
    const c = currentCase();
    state.fem = { running: true, runs: 0 };
    run("fem", { caseKey: c?.key, guess: c?.F }); setBusy(true, "Strength reduction…"); renderPanel(); return;
  }
  if (b.dataset.femShow) { state.femShow = b.dataset.femShow; renderPanel(); return; }
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

const soilText = (s) => s.hb ? `${s.name}: γ ${s.gamma}/${s.gsat} kN/m³, Hoek-Brown GSI ${s.GSI}, mi ${s.mi}, σci ${s.sci} MPa, D ${s.D || 0}` : `${s.name}: γ ${s.gamma}/${s.gsat} kN/m³, c' ${s.c} kPa, φ' ${s.phi}°${s.clay && s.su ? `, su ${s.su}${s.suGrad ? ` + ${s.suGrad}/m` : ""}${s.suMax ? ` (max ${s.suMax})` : ""} kPa` : ""}`;
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
  const pr = state.prob?.result;
  if (pr && !pr.error) {
    const perf = performanceOf(pr.betaLN);
    B.push({ t: "break" }, { t: "h1", text: `Probability: ${pr.case.name}` });
    B.push({ t: "p", text: `${pr.n.toLocaleString()} Latin hypercube samples (seed ${pr.seed}) of lognormal properties, solved on the critical surface by ${pr.methodName}.` });
    B.push({ t: "table", widths: [0.5, 0.5], rows: [
      ["Probability of failure P(F < 1)", `${(pr.pf * 100).toFixed(2)}% (${pr.fails} of ${pr.n}); lognormal fit ${(pr.pfLN * 100).toFixed(3)}%`],
      ["Reliability index β (lognormal)", `${f2(pr.betaLN)}, ${perf[1].toLowerCase()} (USACE 1997); normal β ${f2(pr.betaN)}`],
      ["Mean and SD of F", `${f3(pr.mean)} and ${f3(pr.sd)} (COV ${f1(pr.cov * 100)}%); design F ${f3(pr.deterministic)}`],
      ["5%, 50%, 95% of F", `${f3(pr.p05)}, ${f3(pr.p50)}, ${f3(pr.p95)}`],
      ...pr.vars.map((v) => [v.name, `mean ${+v.mean.toPrecision(4)}, COV ${f1(v.cov * 100)}%`]),
    ] });
    B.push({ t: "img", svg: histSVG(pr).replace("<svg ", '<svg xmlns="http://www.w3.org/2000/svg" '), w: 560, h: 190, widthCm: 15 }, { t: "caption", text: "Distribution of F; red: samples below 1." });
    const tor = tornadoSVG(pr);
    if (tor) { const h = +tor.match(/viewBox="0 0 560 (\d+(?:\.\d+)?)"/)?.[1] || 200; B.push({ t: "img", svg: tor.replace("<svg ", '<svg xmlns="http://www.w3.org/2000/svg" '), w: 560, h, widthCm: 15 }, { t: "caption", text: "Sensitivity: each variable alone at its mean ± one standard deviation." }); }
  }
  const fe = state.fem?.result;
  if (fe && !fe.error) {
    const cc = r.cases.find((k) => k.key === fe.case.key);
    B.push({ t: "h1", text: `Finite element strength reduction: ${fe.case.name}` });
    B.push({ t: "p", text: `${fe.elements} eight-node quadrilaterals (${fe.dof} unknowns), elastic-viscoplastic Mohr-Coulomb with ψ = 0, gravity switched on, strengths reduced until the solution no longer converges in 500 iterations (Griffiths and Lane 1999). F = ${f3(fe.F)} (fails at ${f3(fe.failedAt)}), against ${f3(cc?.F)} by limit equilibrium.` });
    const svg = femSVG(fe.mesh, cc).match(/<svg[\s\S]*?<\/svg>/)?.[0];
    if (svg) B.push({ t: "img", svg: svg.replace("<svg ", '<svg xmlns="http://www.w3.org/2000/svg" '), w: 760, h: 300, widthCm: 16 }, { t: "caption", text: "Plastic shear strain at failure on the displaced mesh (exaggerated)." });
  }
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
      const LIGHT = { grid: "#e1e0d9", raised: "#f4f3ef", muted: "#898781", surface: "#ffffff", ink: "#0b0b0b", "ink-2": "#52514e", critical: "#d03b3b", "series-1": "#2a78d6" };
      const svg = b.svg.replace(/var\(--([a-z0-9-]+)\)/g, (m, k) => LIGHT[k] || "#52514e")
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
// the probability inputs live in the answer panel; they change the next run, not the answer
$("#dpanel").addEventListener("change", (ev) => {
  const k = ev.target.dataset?.pk;
  if (!k) return;
  const p = state.project;
  p.prob = p.prob || {};
  if (k === "n") p.prob.n = +ev.target.value;
  else { p.prob.cov = p.prob.cov || {}; const v = +ev.target.value; if (Number.isFinite(v) && v >= 0) p.prob.cov[k.slice(4)] = v / 100; }
  scheduleSave();
});
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
