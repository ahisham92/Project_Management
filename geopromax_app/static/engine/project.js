// A GeoProMax project: the inputs only. Everything shown is worked out again
// from these, in the browser.

/** Typical soils to start a layer from. Every value can be changed after. */
export const PRESETS = {
  softClay:   { name: "Soft clay",            gamma: 16, gammaSat: 17, E: 3000,   nu: 0.35, consolidating: true,  Cc: 0.45, Cr: 0.06, e0: 1.40, OCR: 1.0, cv: 1.5, Ca: 0.012 },
  firmClay:   { name: "Firm clay",            gamma: 18, gammaSat: 19, E: 8000,   nu: 0.30, consolidating: true,  Cc: 0.25, Cr: 0.04, e0: 0.90, OCR: 2.0, cv: 3,   Ca: 0.006 },
  stiffClay:  { name: "Stiff clay",           gamma: 19, gammaSat: 20, E: 25000,  nu: 0.25, consolidating: true,  Cc: 0.15, Cr: 0.03, e0: 0.65, OCR: 4.0, cv: 6,   Ca: 0.002 },
  organic:    { name: "Organic clay",         gamma: 14, gammaSat: 15, E: 1500,   nu: 0.35, consolidating: true,  Cc: 0.90, Cr: 0.12, e0: 2.50, OCR: 1.0, cv: 0.8, Ca: 0.030 },
  silt:       { name: "Silt",                 gamma: 18, gammaSat: 19, E: 10000,  nu: 0.30, consolidating: true,  Cc: 0.15, Cr: 0.03, e0: 0.80, OCR: 1.5, cv: 20,  Ca: 0.004 },
  looseSand:  { name: "Loose sand",           gamma: 17, gammaSat: 19, E: 10000,  nu: 0.30, consolidating: false },
  sand:       { name: "Medium dense sand",    gamma: 18, gammaSat: 20, E: 30000,  nu: 0.30, consolidating: false },
  denseSand:  { name: "Dense sand and gravel", gamma: 19, gammaSat: 21, E: 60000, nu: 0.25, consolidating: false },
  fill:       { name: "Compacted fill",       gamma: 18, gammaSat: 20, E: 15000,  nu: 0.30, consolidating: false },
  rock:       { name: "Weathered rock",       gamma: 22, gammaSat: 23, E: 200000, nu: 0.20, consolidating: false },
};
export const PRESET_KEYS = Object.keys(PRESETS);

const CLAY_DEFAULTS = { Cc: 0.3, Cr: 0.05, e0: 1.0, OCR: 1, POP: 0, cv: 2, Ca: 0.01, drainage: "double" };

export function layerFrom(key, thickness = 3) {
  const p = PRESETS[key] || PRESETS.sand;
  return { ...CLAY_DEFAULTS, ...p, preset: key, thickness, POP: 0, drainage: "double" };
}

export const LOAD_TYPES = [
  ["rect", "Rectangle"],
  ["circle", "Circle"],
  ["embankment", "Embankment"],
];

export function loadFrom(type, at = {}) {
  const base = { on: true, t0: 0, x: 0, y: 0, ...at };
  if (type === "circle") return { name: "Tank", type, R: 10, q: 120, ...base };
  if (type === "embankment") return { name: "Embankment", type, crest: 12, slope: 6, H: 3, gamma: 20, L: 80, axis: "y", ...base };
  return { name: "Footing", type: "rect", B: 10, L: 20, q: 80, ...base };
}

/** Starting points for a new project. */
export const TEMPLATES = {
  embankment: {
    name: "Embankment on soft clay",
    waterTable: 1,
    layers: [layerFrom("sand", 1), layerFrom("softClay", 6), layerFrom("firmClay", 4), layerFrom("denseSand", 6)],
    loads: [loadFrom("embankment", { H: 4, crest: 14, slope: 8, L: 100 })],
    query: { x: 0, y: 0 },
  },
  foundation: {
    name: "Raft foundation",
    waterTable: 2,
    layers: [layerFrom("fill", 2), layerFrom("firmClay", 8), layerFrom("sand", 10)],
    loads: [loadFrom("rect", { name: "Raft", B: 20, L: 30, q: 100 }), loadFrom("rect", { name: "Neighbouring footing", x: 22, B: 6, L: 6, q: 150 })],
    query: { x: 0, y: 0 },
  },
  tank: {
    name: "Storage tank",
    waterTable: 1.5,
    layers: [layerFrom("sand", 2), layerFrom("softClay", 8), layerFrom("stiffClay", 6), layerFrom("denseSand", 8)],
    loads: [loadFrom("circle", { name: "Tank", R: 15, q: 140 })],
    query: { x: 0, y: 0 },
  },
  blank: {
    name: "New settlement project",
    waterTable: 2,
    layers: [layerFrom("sand", 3), layerFrom("softClay", 5)],
    loads: [loadFrom("rect")],
    query: { x: 0, y: 0 },
  },
};

export const DEFAULTS = {
  type: "settlement",
  method: "boussinesq",
  subLayers: 10,
  t: 1,          // years: the time the plan and the cards show
  life: 50,      // years: design life, the right-hand end of the time axis
  grid: { n: 41, margin: null },
  section: "x",  // the cross-section runs along x (through the query point's y) or along y
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
  out.layers = (out.layers || []).map((l) => ({ ...CLAY_DEFAULTS, ...l }));
  out.loads = (out.loads || []).map((l) => ({ ...loadFrom(l.type || "rect"), ...l }));
  if (!out.name) out.name = tpl.name;
  return out;
}

export const depthOf = (p) => (p.layers || []).reduce((a, l) => a + (+l.thickness || 0), 0);

/** Things worth telling the user before they trust a result. */
export function checks(p) {
  const out = [];
  if (!p.layers.length) out.push({ level: "critical", text: "Add at least one soil layer." });
  if (!p.loads.some((l) => l.on !== false)) out.push({ level: "warning", text: "There are no loads switched on, so nothing settles." });
  p.layers.forEach((l, i) => {
    const n = l.name || `Layer ${i + 1}`;
    if (!(+l.thickness > 0)) out.push({ level: "critical", text: `${n}: the thickness must be more than zero.` });
    if (!(+l.gammaSat >= +l.gamma)) out.push({ level: "warning", text: `${n}: the saturated unit weight is lower than the unit weight above the water table.` });
    if (!(+l.E > 0) && !l.consolidating) out.push({ level: "warning", text: `${n}: no stiffness and no consolidation, so this layer adds no settlement.` });
    if (l.consolidating) {
      if (+l.Cr > +l.Cc) out.push({ level: "warning", text: `${n}: Cr is larger than Cc. Recompression is normally 5 to 10 times stiffer.` });
      if (!(+l.cv > 0)) out.push({ level: "warning", text: `${n}: no cv, so consolidation is taken as immediate.` });
      if (!(+l.e0 > 0)) out.push({ level: "critical", text: `${n}: the initial void ratio e0 must be more than zero.` });
    }
  });
  if (+p.waterTable > depthOf(p)) out.push({ level: "warning", text: "The water table is below the bottom of the soil profile." });
  return out;
}
