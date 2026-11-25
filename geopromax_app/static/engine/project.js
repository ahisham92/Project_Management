// A GeoProMax project: the inputs only. Everything shown is worked out again
// from these, in the browser.

import { parsePoints, equivalentRaft, grossPressure, appliedPressure, loadForce } from "./stress.js";
import { initialStress } from "./settlement.js";

const CLAY = (name, gamma, gammaSat, E, nu, Cc, Cr, e0, OCR, cv, Ca) => ({ name, gamma, gammaSat, E, nu, consolidating: true, Cc, Cr, e0, OCR, cv, Ca });
const GRAN = (name, gamma, gammaSat, E, nu) => ({ name, gamma, gammaSat, E, nu, consolidating: false });

/** Typical soils to start a layer from. Every value can be changed after.
 *  They are mid-range textbook values, not a substitute for a site investigation. */
export const PRESETS = {
  // clays and organic soils
  peat:       CLAY("Peat",                       11, 11.5, 500,   0.35, 2.50, 0.25, 6.00, 1.0, 2.0, 0.100),
  organic:    CLAY("Organic clay",               14, 15,   1500,  0.35, 0.90, 0.12, 2.50, 1.0, 0.8, 0.030),
  marineClay: CLAY("Very soft marine clay",      15, 15.5, 1500,  0.35, 0.80, 0.10, 2.00, 1.0, 0.7, 0.020),
  softClay:   CLAY("Soft clay",                  16, 17,   3000,  0.35, 0.45, 0.06, 1.40, 1.0, 1.5, 0.012),
  firmClay:   CLAY("Firm clay",                  18, 19,   8000,  0.30, 0.25, 0.04, 0.90, 2.0, 3,   0.006),
  stiffClay:  CLAY("Stiff clay",                 19, 20,   25000, 0.25, 0.15, 0.03, 0.65, 4.0, 6,   0.002),
  hardClay:   CLAY("Hard clay or glacial till",  21, 21.5, 50000, 0.25, 0.08, 0.015, 0.40, 8.0, 10, 0.001),
  // silts
  softSilt:   CLAY("Soft clayey silt",           17, 18,   5000,  0.30, 0.25, 0.04, 1.00, 1.0, 10,  0.006),
  silt:       CLAY("Silt",                       18, 19,   10000, 0.30, 0.15, 0.03, 0.80, 1.5, 20,  0.004),
  loess:      GRAN("Loess (can collapse when wetted)", 15, 18, 8000, 0.30),
  // sands and gravels
  looseSand:  GRAN("Loose sand",                 17, 19,   10000, 0.30),
  siltySand:  GRAN("Silty sand",                 17.5, 19.5, 15000, 0.30),
  clayeySand: GRAN("Clayey sand",                18, 20,   20000, 0.30),
  sand:       GRAN("Medium dense sand",          18, 20,   30000, 0.30),
  denseSand:  GRAN("Dense sand and gravel",      19, 21,   60000, 0.25),
  gravel:     GRAN("Very dense gravel",          20, 22,   100000, 0.25),
  // fills and residual soils
  fill:       GRAN("Compacted fill",             18, 20,   15000, 0.30),
  looseFill:  GRAN("Loose or uncontrolled fill", 16, 18,   4000,  0.30),
  rockfill:   GRAN("Rockfill",                   20, 22,   80000, 0.25),
  residual:   GRAN("Residual soil",              18, 19.5, 20000, 0.30),
  // rocks
  rock:       GRAN("Weathered rock",             22, 23,   200000, 0.20),
  mudstone:   GRAN("Marl or mudstone",           21, 22,   150000, 0.25),
  chalk:      GRAN("Chalk",                      19, 20,   100000, 0.25),
  soundRock:  GRAN("Sound rock",                 25, 25.5, 5000000, 0.20),
};
// Strength for the bearing check: friction angle φ' (degrees), cohesion c' (kPa) and, for clays and silts, undrained strength su (kPa).
const STRENGTH = {
  peat: [25, 0, 10], organic: [24, 0, 15], marineClay: [23, 0, 12], softClay: [25, 0, 20], firmClay: [26, 2, 50], stiffClay: [27, 5, 100], hardClay: [30, 10, 200],
  softSilt: [28, 0, 25], silt: [30, 0, 50], loess: [30, 5, 0],
  looseSand: [30, 0, 0], siltySand: [31, 0, 0], clayeySand: [30, 2, 0], sand: [34, 0, 0], denseSand: [38, 0, 0], gravel: [40, 0, 0],
  fill: [33, 0, 0], looseFill: [28, 0, 0], rockfill: [42, 0, 0], residual: [30, 5, 0],
  rock: [38, 100, 0], mudstone: [30, 150, 0], chalk: [33, 50, 0], soundRock: [45, 1000, 0],
};
for (const [k, [phi, c, su]] of Object.entries(STRENGTH)) Object.assign(PRESETS[k], { phi, c, su });

export const PRESET_GROUPS = [
  ["Clays and organic soils", ["peat", "organic", "marineClay", "softClay", "firmClay", "stiffClay", "hardClay"]],
  ["Silts", ["softSilt", "silt", "loess"]],
  ["Sands and gravels", ["looseSand", "siltySand", "clayeySand", "sand", "denseSand", "gravel"]],
  ["Fills and residual soils", ["fill", "looseFill", "rockfill", "residual"]],
  ["Rocks", ["rock", "mudstone", "chalk", "soundRock"]],
];
export const PRESET_KEYS = Object.keys(PRESETS);

const DRAINS = { on: false, spacing: 1.5, pattern: "tri", dw: 0.066, ch: 3 };
const LAYER_DEFAULTS = { phi: 0, c: 0, su: 0, Einc: 0, model: "cc", mv: 0.3, Cc: 0.3, Cr: 0.05, e0: 1.0, OCR: 1, POP: 0, cv: 2, Ca: 0.01, drainage: "double" };

export function layerFrom(key, thickness = 3) {
  const p = PRESETS[key] || PRESETS.sand;
  return { ...LAYER_DEFAULTS, ...p, preset: key, thickness, drains: { ...DRAINS } };
}

export const LOAD_TYPES = [
  ["pad", "Pad footing", "a column load on a square or rectangular footing"],
  ["strip", "Strip footing", "a wall load on a long footing"],
  ["rect", "Raft or area load", "a uniform pressure on a rectangle"],
  ["building", "Building", "a footprint, storeys and a load per storey"],
  ["circle", "Circular tank", "a uniform pressure on a circle"],
  ["ring", "Ring foundation", "a ring wall, a silo or a chimney base"],
  ["polygon", "Any shape", "a uniform pressure on a polygon you type in"],
  ["embankment", "Embankment or fill", "crest, side slopes and height"],
  ["pilegroup", "Pile group", "piles taken as an equivalent raft at depth"],
];
export const LOAD_NAMES = { ...Object.fromEntries(LOAD_TYPES.map(([k, n]) => [k, n])), field: "Raft from SAFE" };

export function loadFrom(type, at = {}) {
  const base = { on: true, t0: 0, x: 0, y: 0, angle: 0, Df: 0, net: false, rigid: false };
  const T = {
    pad:        { name: "Pad footing", B: 2.5, L: 2.5, P: 1500, Df: 1.5, rigid: true },
    strip:      { name: "Strip footing", B: 1.2, L: 20, w: 150, Df: 1, rigid: true },
    rect:       { name: "Raft", B: 10, L: 20, q: 80 },
    building:   { name: "Building", B: 20, L: 30, storeys: 8, perStorey: 12, extra: 15, Df: 2, net: true },
    circle:     { name: "Tank", R: 10, q: 120 },
    ring:       { name: "Ring foundation", R: 10, Ri: 8, q: 150, Df: 1, rigid: true },
    polygon:    { name: "Area", q: 60, pts: "0, 0\n20, 0\n20, 8\n8, 8\n8, 20\n0, 20" },
    embankment: { name: "Embankment", crest: 12, slope: 6, H: 3, gamma: 20, L: 80, axis: "y" },
    pilegroup:  { name: "Pile group", B: 6, L: 6, Lp: 15, pileType: "friction", Q: 12000, Df: 1.5, rigid: true, nPiles: 9, pileD: 0.6, install: "bored" },
    field:      { name: "Raft from SAFE", cells: [], size: 1, Df: 1 },
  }[type] || {};
  return { type: T.name ? type : "rect", ...base, ...(T.name ? T : { name: "Raft", B: 10, L: 20, q: 80 }), ...at };
}

/** A grid of pad footings under a building's columns, centred on (x, y). */
export function padGrid({ nx = 4, ny = 3, sx = 6, sy = 6, B = 2.5, P = 1500, Df = 1.5, x = 0, y = 0, t0 = 0 } = {}) {
  const out = [];
  for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++) {
    // edge and corner columns carry about half and a quarter of an inner one
    const edge = (i === 0 || i === nx - 1 ? 1 : 0) + (j === 0 || j === ny - 1 ? 1 : 0);
    const share = nx > 2 && ny > 2 ? [1, 0.6, 0.4][edge] : 1;
    out.push(loadFrom("pad", { name: `${String.fromCharCode(65 + (i % 26))}${j + 1}`, B, L: B, P: Math.round(P * share), Df, t0,
      x: +(x + (i - (nx - 1) / 2) * sx).toFixed(3), y: +(y + (j - (ny - 1) / 2) * sy).toFixed(3) }));
  }
  return out;
}

/**
 * Kinds of structure with the settlement and tilt they usually tolerate.
 * These are the commonly quoted guide values (Skempton & MacDonald 1956,
 * Bjerrum 1963, Eurocode 7 Annex H, Moulton 1985); the project's own limits
 * can be typed over them.
 */
export const STRUCTURES = [
  ["frame-pads", "Framed building on pad footings", 50, 500, "50 mm and 1/500: the usual limits against cracking of panels and finishes"],
  ["frame-raft", "Framed building on a raft", 75, 500, "rafts even settlements out, so more total settlement is accepted"],
  ["masonry", "Load-bearing masonry walls", 25, 1000, "unreinforced walls crack early, most of all when the ends settle more (hogging)"],
  ["steel-shed", "Steel frame with flexible cladding", 75, 300, "1/300: where structural damage and cracking of walls starts"],
  ["tall", "Tall stiff building", 100, 500, "a lean of 1/250 can be seen; 1/500 keeps a margin"],
  ["tank", "Steel storage tank", 150, 200, "flexible tank bottoms follow the ground; check the shell separately"],
  ["silo", "Silo, chimney or tower", 100, 500, "tilt governs, as for tall stiff structures"],
  ["bridge", "Bridge pier or abutment", 50, 250, "1/250 between supports of continuous decks; 1/200 for simple spans"],
  ["machine", "Machine sensitive to settlement", 15, 750, "1/750: Bjerrum's limit for sensitive machinery"],
  ["crane", "Crane rails or gantry", 50, 300, "1/300: where overhead cranes start to give trouble"],
  ["embankment", "Embankment, road or yard", 300, 0, "judged on the settlement left after construction; tilt is not checked"],
  ["custom", "My own limits", 50, 500, ""],
];
export const bearingLimit = (key) => (key === "embankment" ? 1.5 : 3);
export const structureOf = (key) => STRUCTURES.find((s) => s[0] === key) || STRUCTURES[0];
const limitsFor = (key) => { const s = structureOf(key); return { preset: s[0], total: s[2], tilt: s[3], fos: bearingLimit(s[0]), fosPile: 2.5 }; };

/** Starting points for a new project. */
export const TEMPLATES = {
  building: {
    name: "Building on pad footings", waterTable: 3, limits: limitsFor("frame-pads"),
    layers: [layerFrom("fill", 1.5), layerFrom("stiffClay", 6), layerFrom("sand", 8), layerFrom("rock", 4)],
    loads: padGrid({ nx: 4, ny: 3, sx: 6, sy: 6, B: 3, P: 900, Df: 1.5 }),
  },
  foundation: {
    name: "Building on a raft", waterTable: 2, limits: limitsFor("frame-raft"),
    layers: [layerFrom("fill", 2), layerFrom("stiffClay", 8), layerFrom("denseSand", 10)],
    loads: [loadFrom("building", { name: "Tower", B: 20, L: 30, storeys: 8, Df: 2, net: true, rigid: true }), loadFrom("pad", { name: "Neighbouring footing", x: 16, B: 3, L: 3, P: 900, Df: 1 })],
  },
  strips: {
    name: "House on strip footings", waterTable: 2, limits: limitsFor("masonry"),
    layers: [layerFrom("stiffClay", 5), layerFrom("hardClay", 6), layerFrom("denseSand", 4)],
    loads: [loadFrom("strip", { name: "Front wall", x: -4, L: 12, w: 45, Df: 0.9 }), loadFrom("strip", { name: "Spine wall", x: 0, L: 12, w: 52, Df: 0.9 }), loadFrom("strip", { name: "Rear wall", x: 4, L: 12, w: 45, Df: 0.9 })],
  },
  piles: {
    name: "Pile group through soft clay", waterTable: 1, limits: limitsFor("bridge"),
    layers: [layerFrom("softClay", 8), layerFrom("stiffClay", 10), layerFrom("hardClay", 10), layerFrom("denseSand", 8)],
    loads: [loadFrom("pilegroup", { name: "Pier pile cap", B: 6, L: 9, Lp: 18, Q: 10000, nPiles: 15, pileD: 0.6 })],
  },
  tank: {
    name: "Storage tank", waterTable: 1.5, limits: limitsFor("tank"),
    layers: [layerFrom("fill", 2), layerFrom("stiffClay", 6), layerFrom("denseSand", 12)],
    loads: [loadFrom("circle", { name: "Tank", R: 15, q: 120 })],
  },
  embankment: {
    name: "Embankment on clay", waterTable: 1, limits: limitsFor("embankment"),
    layers: [layerFrom("sand", 1), layerFrom("firmClay", 5), layerFrom("stiffClay", 4), layerFrom("denseSand", 6)],
    loads: [loadFrom("embankment", { H: 4, crest: 14, slope: 8, L: 100 })],
  },
  drains: {
    // a preload on very soft clay: the settlement is wanted, and wanted quickly
    name: "Staged embankment with wick drains", waterTable: 0.5, limits: { preset: "custom", total: 2000, tilt: 0, fos: 1.3, fosPile: 2.5 }, life: 30, t: 2,
    layers: [layerFrom("fill", 1), { ...layerFrom("marineClay", 10), drains: { ...DRAINS, on: true, spacing: 1.5 } }, layerFrom("denseSand", 5)],
    loads: [loadFrom("embankment", { name: "Stage 1", H: 2, crest: 20, slope: 4, L: 120 }), loadFrom("embankment", { name: "Stage 2", H: 2, crest: 12, slope: 4, L: 120, t0: 0.5 })],
  },
  blank: {
    name: "New settlement project", waterTable: 2, limits: limitsFor("frame-pads"),
    layers: [layerFrom("sand", 3), layerFrom("stiffClay", 5), layerFrom("denseSand", 6)],
    loads: [loadFrom("pad", { B: 3, L: 3, P: 900, Df: 1 })],
  },
};

export const DEFAULTS = {
  type: "settlement",
  method: "boussinesq",
  subLayers: null, // null: refine until the answer converges
  t: 1,            // years: the time the plan and the cards show
  life: 50,        // years: design life, the right-hand end of the time axis
  grid: { n: 41, margin: null },
  section: "x",    // the cross-section runs along x (through the query point's y) or along y
  limits: limitsFor("frame-pads"),
  query: { x: 0, y: 0 },
  // the loop with CSI SAFE: units of the tables, tolerance (%), number of soil properties, the rounds so far and the last springs
  safe: { units: "kN-m", tol: 5, zones: 5, kase: null, step: null, rounds: [], k: null },
};

const clone = (o) => JSON.parse(JSON.stringify(o));

/** A project with every field it needs, from whatever was saved. */
export function complete(p = {}) {
  const tpl = TEMPLATES[p.template] || TEMPLATES.embankment;
  const out = { ...clone(DEFAULTS), ...clone(tpl), ...clone(p) };
  delete out.template;
  out.type = "settlement";
  out.grid = { ...DEFAULTS.grid, ...(p.grid || {}) };
  out.query = { x: 0, y: 0, ...(out.query || {}) };
  out.limits = { ...DEFAULTS.limits, ...(out.limits || {}) };
  if (p.limits && p.limits.fos === undefined) out.limits.fos = bearingLimit(out.limits.preset);
  out.safe = { ...clone(DEFAULTS.safe), ...(out.safe || {}) };
  // a layer saved before strengths existed takes them from the typical soil it started from
  const strength = (l) => (l.phi === undefined && l.su === undefined && STRENGTH[l.preset] ? { phi: STRENGTH[l.preset][0], c: STRENGTH[l.preset][1], su: STRENGTH[l.preset][2] } : {});
  out.layers = (out.layers || []).map((l) => ({ ...LAYER_DEFAULTS, ...strength(l), ...l, drains: { ...DRAINS, ...(l.drains || {}) } }));
  out.loads = (out.loads || []).map((l) => ({ ...loadFrom(l.type || "rect"), ...l }));
  if (!out.name) out.name = tpl.name;
  return out;
}

export const depthOf = (p) => (p.layers || []).reduce((a, l) => a + (+l.thickness || 0), 0);

/** A line that says what a load is, for tables and the report. */
export function describeLoad(l) {
  const n = (v, d = 2) => +(+v || 0).toFixed(d);
  const turn = +l.angle ? `, turned ${n(l.angle, 1)}°` : "";
  switch (l.type) {
    case "pad": return `${n(l.B)} × ${n(l.L)} m, ${n(l.P, 0)} kN${turn}`;
    case "strip": return `${n(l.B)} m wide, ${n(l.L)} m long, ${n(l.w, 0)} kN/m${turn}`;
    case "building": return `${n(l.B)} × ${n(l.L)} m, ${n(l.storeys, 0)} storeys at ${n(l.perStorey, 1)} kPa${+l.extra ? ` + ${n(l.extra, 1)} kPa` : ""}${turn}`;
    case "circle": return `radius ${n(l.R)} m`;
    case "ring": return `radius ${n(l.Ri)} to ${n(l.R)} m`;
    case "polygon": return `${parsePoints(l.pts).length} corners`;
    case "field": return `${(l.cells || []).length} cells of ${n(l.size)} m, ${n(loadForce(l) / 1000, 1)} MN in all`;
    case "embankment": return `crest ${n(l.crest)} m, sides ${n(l.slope)} m, ${n(l.H)} m high, ${n(l.L)} m long along ${l.axis}`;
    case "pilegroup": { const e = equivalentRaft(l); return `${n(l.nPiles, 0)} ${l.install === "driven" ? "driven" : "bored"} piles of ${n(l.pileD)} m, ${n(l.B)} × ${n(l.L)} m group, ${n(l.Lp, 1)} m ${l.pileType === "end" ? "end-bearing" : "friction"} piles, ${n(l.Q, 0)} kN; equivalent raft ${n(e.B)} × ${n(e.L)} m at ${n(e.zf)} m${turn}`; }
    default: return `${n(l.B)} × ${n(l.L)} m${turn}`;
  }
}

/** Things worth telling the user before they trust a result. */
export function checks(p) {
  const out = [];
  const D = depthOf(p);
  if (!p.layers.length) out.push({ level: "critical", text: "Add at least one soil layer." });
  if (!p.loads.some((l) => l.on !== false)) out.push({ level: "warning", text: "There are no loads switched on, so nothing settles." });
  p.layers.forEach((l, i) => {
    const n = l.name || `Layer ${i + 1}`;
    if (!(+l.thickness > 0)) out.push({ level: "critical", text: `${n}: the thickness must be more than zero.` });
    if (!(+l.gamma > 0) || !(+l.gammaSat > 0)) out.push({ level: "critical", text: `${n}: the unit weights must be more than zero.` });
    else if (!(+l.gammaSat >= +l.gamma)) out.push({ level: "warning", text: `${n}: the saturated unit weight is lower than the unit weight above the water table.` });
    if (+l.gammaSat > 0 && +l.gammaSat <= 9.81) out.push({ level: "warning", text: `${n}: the saturated unit weight is no more than water's, so the soil would float.` });
    if (+l.nu >= 0.5) out.push({ level: "warning", text: `${n}: Poisson's ratio is taken as 0.49 at most.` });
    if (!(+l.E > 0) && !l.consolidating) out.push({ level: "warning", text: `${n}: no stiffness and no consolidation, so this layer adds no settlement.` });
    if (+l.E > 0 && +l.E + (+l.Einc || 0) * (+l.thickness || 0) <= 0) out.push({ level: "critical", text: `${n}: the stiffness falls to zero within the layer.` });
    if (l.consolidating) {
      if (l.model === "mv") {
        if (!(+l.mv > 0)) out.push({ level: "warning", text: `${n}: mv is zero, so the layer does not consolidate.` });
      } else {
        if (+l.Cr > +l.Cc) out.push({ level: "warning", text: `${n}: Cr is larger than Cc. Recompression is normally 5 to 10 times stiffer.` });
        if (!(+l.e0 > 0)) out.push({ level: "critical", text: `${n}: the initial void ratio e0 must be more than zero.` });
      }
      if (!(+l.cv > 0) && !(l.drains && l.drains.on)) out.push({ level: "warning", text: `${n}: no cv, so consolidation is taken as immediate.` });
      if (l.drains && l.drains.on && (!(+l.drains.spacing > 0) || !(+l.drains.ch > 0) || !(+l.drains.dw > 0))) out.push({ level: "warning", text: `${n}: the wick drains need a spacing, a diameter and ch to do anything.` });
      if (l.drains && l.drains.on && +l.drains.dw >= +l.drains.spacing) out.push({ level: "warning", text: `${n}: the drains are as wide as their spacing.` });
    }
    if (l.preset === "loess") out.push({ level: "warning", text: `${n}: loess can collapse when it is wetted under load. That is not part of this analysis.` });
    if (l.preset === "peat") out.push({ level: "warning", text: `${n}: peat creeps a great deal and its properties change as it compresses. Treat the result as a first estimate.` });
  });
  if (+p.waterTable > D) out.push({ level: "warning", text: "The water table is below the bottom of the soil profile." });
  const ob = (z) => initialStress(p.layers, +p.waterTable || 0, z).total;
  p.loads.forEach((l, i) => {
    if (l.on === false) return;
    const n = l.name || `Load ${i + 1}`;
    if (l.type === "polygon" && parsePoints(l.pts).length < 3) out.push({ level: "critical", text: `${n}: a shape needs at least three corners, one "x, y" per line.` });
    if (l.type === "field" && !(l.cells || []).length) out.push({ level: "critical", text: `${n}: no soil pressures have been brought in from SAFE yet.` });
    if (l.type === "ring" && !(+l.Ri < +l.R)) out.push({ level: "critical", text: `${n}: the inner radius must be smaller than the outer radius.` });
    if (["pad", "strip", "rect", "building", "pilegroup"].includes(l.type) && (!(+l.B > 0) || !(+l.L > 0))) out.push({ level: "critical", text: `${n}: the width and length must be more than zero.` });
    if (l.type === "circle" && !(+l.R > 0)) out.push({ level: "critical", text: `${n}: the radius must be more than zero.` });
    if (l.type === "pilegroup") {
      const e = equivalentRaft(l);
      if (e.zf >= D) out.push({ level: "critical", text: `${n}: the equivalent raft is at ${+e.zf.toFixed(1)} m, below the bottom of the soil profile (${+D.toFixed(1)} m). Add the soil below the piles.` });
    } else if (+l.Df >= D && D > 0 && l.type !== "embankment") out.push({ level: "critical", text: `${n}: it is founded below the bottom of the soil profile.` });
    const q = grossPressure(l), qa = appliedPressure(l, ob);
    if (l.net && qa < 0) out.push({ level: "warning", text: `${n}: it weighs less than the soil dug out for it (${+q.toFixed(0)} kPa against ${+(q - qa).toFixed(0)} kPa), so the ground heaves.` });
    if (q > 1000 && l.type !== "pilegroup") out.push({ level: "warning", text: `${n}: ${+q.toFixed(0)} kPa is a very high bearing pressure. Look at the bearing safety first.` });
  });
  if (!(+p.limits.total > 0)) out.push({ level: "warning", text: "Set a settlement limit to judge the result against." });
  return out;
}

/** Checks that need the answer at the query point. */
export function resultChecks(p, res) {
  const out = [];
  if (!res) return out;
  const bad = res.rows.find((r) => !Number.isFinite(r.sImm) || !Number.isFinite(r.sCons));
  if (bad) out.push({ level: "critical", text: `The numbers for ${bad.name} do not work out. Check its inputs.` });
  if (res.converged === false) out.push({ level: "warning", text: `The settlement was still changing by ${(res.change * 100).toFixed(1)}% when the sub-layers were refined to ${res.subLayers} per layer. Split thick layers in two.` });
  const last = res.rows[res.rows.length - 1];
  if (last && last.sv0 > 0 && Math.abs(last.dsig) > 0.2 * last.sv0) {
    const l = p.layers[last.layer];
    const soft = l.consolidating || (+l.E > 0 && +l.E < 100000);
    if (soft) out.push({ level: "warning", text: `At the bottom of the profile the loads still add ${(100 * last.dsig / last.sv0).toFixed(0)}% to the stress in the ground. Unless rock or a very stiff layer starts there, add the soil below: it settles too.` });
  }
  if (res.rows.some((r) => r.svf <= 0)) out.push({ level: "warning", text: "Unloading takes the effective stress to zero somewhere: the soil there would lift, and the heave shown is only a rough guide." });
  return out;
}
