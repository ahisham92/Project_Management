// Talus — from a few inputs to the analysis models of every load case.
//
// The user picks a kind of slope and gives the handful of numbers that define it.
// Everything else (extents, layering, water lines, search limits, load cases and
// their targets) is laid out here. Coordinates are the user's: x to the right,
// y up (levels in m); the engine turns the slope round itself when it must.

import { soilFrom, asMaterial, PRESETS } from "./materials.js";
import { lower, upper, flat, yAt } from "./geometry.js";
import { rockArmour, accropode, toe, runup, overtopping, damageLevels, COEFFS } from "./armour.js";

export const GROUND_S = { A: 1.0, B: 1.2, C: 1.15, D: 1.35, E: 1.4 };

export const BASES = {
  fos: {
    name: "Global factor of safety (USACE EM 1110-2-1902)",
    targets: { static: 1.5, short: 1.3, transient: 1.2, seismic: 1.1 },
    factors: { tanphi: 1, c: 1, su: 1, variable: 1 },
  },
  ec7: {
    name: "Eurocode 7 DA1-C2 / DA3 (M2 factors), EN 1998-5 for seismic",
    targets: { static: 1.0, short: 1.0, transient: 1.0, seismic: 1.0 },
    factors: { tanphi: 1.25, c: 1.25, su: 1.4, variable: 1.3 },
  },
};

export const DEFAULTS = {
  cut: {
    type: "cut", name: "Cut slope",
    geom: { H: 6, cot: 2.5, base: 6, berms: { on: false, rows: [] } },
    soil: { preset: "firmClay" },
    lower: { on: false, depth: 5, preset: "stiffClay" },
    water: { on: true, back: 3, front: 0 },
    load: { q: 10, setback: 1, width: 10 },
    nails: { on: false, rows: 4, length: 8, angle: 15, T: 60, qb: 40 },
    piles: { on: false, x: 3, length: 12, Vp: 300, spacing: 2 },
    seismic: { on: true, ag: 0.15, ground: "B" },
    design: { basis: "fos", method: "mp", targets: null },
    advanced: { slices: 40, noncircular: false, crack: 0 },
  },
  embankment: {
    type: "embankment", name: "Embankment",
    geom: { H: 5, cot: 3, crest: 8, base: 6, berms: { on: false, rows: [] } },
    fill: { preset: "fill" },
    soil: { preset: "firmClay" },
    water: { on: true, level: 4, low: 0 },
    load: { q: 10, setback: 0.5, width: 7 },
    grids: { on: false, n: 1, bottom: 0.25, spacing: 0.5, T: 200, Ci: 0.8 },
    piles: { on: false, x: 3, length: 12, Vp: 300, spacing: 2 },
    seismic: { on: true, ag: 0.15, ground: "C" },
    design: { basis: "fos", method: "mp", targets: null },
    advanced: { slices: 40, noncircular: false, crack: 0 },
  },
  section: {
    type: "section", name: "Any section",
    // points are typed or pasted as "x, y" lines, left to right
    ground: "0, 11.7\n15, 11.7\n30, 5.7\n34, 5.7\n45.4, 0\n80, 0",
    base: -15,
    layers: [
      { soil: { preset: "sand", name: "Upper" }, top: "" },
      { soil: { preset: "firmClay", name: "Lower" }, top: "0, 6\n80, 6" },
      { soil: { preset: "denseSand", name: "Base" }, top: "0, -7\n80, -7" },
    ],
    water: { mode: "line", line: "0, 9\n15, 9\n45.4, 0\n80, 0", ru: 0 },
    load: { q: 10, x1: 1, x2: 14 },
    piles: { on: false, x: 38, length: 15, Vp: 300, spacing: 2 },
    seismic: { on: true, ag: 0.15, ground: "B" },
    design: { basis: "fos", method: "mp", targets: null },
    advanced: { slices: 40, noncircular: false, block: true, crack: 0 },
  },
  revetment: {
    type: "revetment", name: "Rock revetment",
    geom: { crest: 4, toe: -3, cot: 2, berm: 10, base: 6 },
    core: { preset: "rockfill" },
    soil: { preset: "sand" },
    water: { HWL: 1.5, LWL: 0, gw: 10.05 },
    waves: { Hs: 2, Tp: 8, hours: 6, seabed: 0.01, section: "trunk" },
    armour: { type: "rock", rhoR: 2650, rhoC: 2400, rhoW: 1025, P: 0.4, S: null, governing: "max", toeRatio: 0.8 },
    load: { q: 10, setback: 2, width: 8 },
    seismic: { on: true, ag: 0.15, ground: "C" },
    design: { basis: "fos", method: "mp", targets: null },
    advanced: { slices: 40, noncircular: false, crack: 0 },
  },
};

const num = (v, d) => (v === undefined || v === null || v === "" || !Number.isFinite(+v) ? d : +v);

/** A project with every missing value filled from the defaults of its kind. */
export function complete(p) {
  const d = DEFAULTS[p?.type] || DEFAULTS.cut;
  const out = JSON.parse(JSON.stringify(d));
  const merge = (a, b) => {
    for (const k of Object.keys(b || {})) {
      if (b[k] && typeof b[k] === "object" && !Array.isArray(b[k]) && a[k] && typeof a[k] === "object") merge(a[k], b[k]);
      else if (b[k] !== undefined) a[k] = b[k];
    }
  };
  merge(out, p || {});
  out.type = d.type;
  return out;
}

// ---------------------------------------------------------------- benched faces

/**
 * The face as benches, listed from the top down as a person enters them:
 * [{ h: height, cot: slope 1:n, berm: width of the berm at its foot }]. The bottom
 * bench's berm is not used. Without berms it is one bench of height H at 1:cot.
 */
export function benchesOf(p) {
  const b = p.geom?.berms;
  if (b?.on && Array.isArray(b.rows) && b.rows.length) {
    return b.rows.map((r) => ({ h: Math.max(0.1, num(r.h, 1)), cot: Math.max(0.01, num(r.cot, 1.5)), berm: Math.max(0, num(r.berm, 0)) }));
  }
  return [{ h: num(p.geom?.H, 8), cot: Math.max(0.01, num(p.geom?.cot, 1.5)), berm: 0 }];
}

/** Height, horizontal run, and the face as offsets from the toe (0, 0) up to the crest. */
export function faceOf(p) {
  const top = benchesOf(p);
  const up = top.slice().reverse();
  const pts = [[0, 0]];
  let x = 0, y = 0;
  up.forEach((r, i) => {
    x += r.h * r.cot; y += r.h;
    pts.push([x, y]);
    const above = up[i + 1];
    if (above && top[top.length - 2 - i].berm > 0) { x += top[top.length - 2 - i].berm; pts.push([x, y]); }
  });
  return { H: y, run: x, pts, benches: top, overallCot: x / y };
}

/** Horizontal distance from the toe to the face at height y. */
function faceX(face, y) {
  const P = face.pts;
  for (let i = 1; i < P.length; i++) {
    const [x0, y0] = P[i - 1], [x1, y1] = P[i];
    if (y1 > y0 && y <= y1 + 1e-9) return x0 + (x1 - x0) * (y - y0) / (y1 - y0);
  }
  return face.run;
}

/** Seismic coefficients: EN 1998-5 4.1.3.3 (kh = 0.5 ag S ST, kv = 0.5 kh), with ST from Annex A. */
export function seismicCoefficients(p, H, slopeDeg) {
  const s = p.seismic || {};
  if (!s.on || !(num(s.ag, 0) > 0)) return null;
  const ag = num(s.ag, 0);
  const S = s.S ? num(s.S, 1) : GROUND_S[s.ground] ?? 1.2;
  const ST = s.ST ? num(s.ST, 1) : slopeDeg > 15 && H > 30 ? 1.2 : 1.0;
  const kh = s.kh ? num(s.kh, 0) : 0.5 * ag * S * ST;
  const kv = s.kv !== undefined && s.kv !== null && s.kv !== "" ? num(s.kv, 0) : 0.5 * kh;
  return { ag, S, ST, kh, kv, amax: ag * S * ST, basis: s.kh ? "user kh" : "EN 1998-5 4.1.3.3: kh = 0.5 ag S ST, kv = ±0.5 kh" };
}

function targetsOf(p) {
  const base = BASES[p.design?.basis] || BASES.fos;
  return { ...base.targets, ...(p.design?.targets || {}) };
}

function factorsOf(p) {
  return { ...(BASES[p.design?.basis] || BASES.fos).factors };
}

/** A row of piles (or a sheet-pile wall) at x: its shear capacity per metre run. */
function pileRow(p, x, ground) {
  if (!p.piles?.on) return [];
  const V = Math.max(0, num(p.piles.Vp, 0)) / Math.max(0.1, num(p.piles.spacing, 1));
  return V > 0 ? [{ kind: "pile", x, y: yAt(ground, x), length: Math.max(0.5, num(p.piles.length, 10)), V }] : [];
}

// ---------------------------------------------------------------- cut slope

function cutCases(p) {
  const face = faceOf(p);
  const H = face.H, cot = face.overallCot;
  const D = Math.max(1, num(p.geom.base, H));
  const front = Math.max(2 * H, 10), back = Math.max(3 * H, 15);
  const xt = front, xc = front + face.run, xr = xc + back;
  const ground = [[0, 0], ...face.pts.map(([x, y]) => [xt + x, y]), [xr, H]];
  const soil = soilFrom(p.soil);
  const lowerSoil = p.lower?.on ? soilFrom(p.lower) : null;
  const yLower = H - num(p.lower?.depth, 5);
  const layers = (undrained) => {
    const L = [{ top: null, mat: asMaterial(soil, undrained) }];
    if (lowerSoil) L.push({ top: flat(yLower, 0, xr), mat: asMaterial(lowerSoil, undrained) });
    return L;
  };
  // groundwater: at a depth below toe level in front, rising under the face to a
  // depth below the crest at the crest edge, and level behind it (never above ground)
  let piezo = null;
  if (p.water?.on) {
    const yf = -num(p.water.front, 0), yb = Math.max(yf, H - num(p.water.back, H / 2));
    const line = [[0, yf], [xt, yf], [xc, yb], [xr, yb]];
    piezo = lower(line, ground, 0, xr);
  }
  const q = num(p.load?.q, 0);
  const strip = (psi = 1) => q > 0 ? [{ x1: xc + num(p.load.setback, 1), x2: Math.min(xr, xc + num(p.load.setback, 1) + num(p.load.width, 10)), q: q * psi, variable: true }] : [];
  // soil nails / anchors: rows spread evenly up the face, each pointing into the slope
  const reinforcement = [];
  if (p.nails?.on) {
    const rows = Math.max(1, Math.min(20, Math.round(num(p.nails.rows, 4))));
    for (let i = 0; i < rows; i++) {
      const y = H * (i + 0.5) / rows;
      reinforcement.push({ x: xt + faceX(face, y), y, angle: num(p.nails.angle, 15), length: num(p.nails.length, 8),
        T: num(p.nails.T, 60), qb: num(p.nails.qb, 40), kind: "nail", dir: 1 });
    }
  }
  reinforcement.push(...pileRow(p, xt + num(p.piles?.x, 0), ground));
  const base = { ground, bottom: -D, face: { toe: [xt, 0], crest: [xc, H] }, gw: 9.81, factors: factorsOf(p), crack: { depth: num(p.advanced?.crack, 0), water: 0 }, reinforcement };
  const T = targetsOf(p);
  const clayey = soil.clay || lowerSoil?.clay;
  const cases = [
    { key: "long", name: "Long term (drained)", target: T.static, model: { ...base, layers: layers(false), piezo, strips: strip() },
      note: "Effective strength c', φ' with the groundwater line; surcharge on the crest." },
  ];
  if (clayey) cases.push({ key: "short", name: "Short term (undrained)", target: T.short,
    model: { ...base, layers: layers(true), piezo, strips: strip() },
    note: "Right after excavation: clays at their undrained strength su (total stress)." });
  const eq = seismicCoefficients(p, H, Math.atan(1 / cot) * 180 / Math.PI);
  if (eq) cases.push({ key: "seismic", name: "Seismic (pseudo-static)", target: T.seismic, seismic: eq,
    model: { ...base, layers: layers(true), piezo, strips: strip(0.3), seismic: { kh: eq.kh, kv: eq.kv } },
    note: "Earthquake as a steady push kh·W towards the face and ±kv·W vertically; clays undrained; 30% of the surcharge (ψ2)." });
  return { cases, geometry: { ground, H, xt, xc, xr, bottom: -D, layers: layers(false), piezo, lowerY: lowerSoil ? yLower : null, reinforcement, faceDir: -1, benches: face.benches }, extras: {} };
}

// ---------------------------------------------------------------- embankment

function embankmentCases(p) {
  const face = faceOf(p);
  const H = face.H, cot = face.overallCot, B = Math.max(1, num(p.geom.crest, 8));
  const D = Math.max(1, num(p.geom.base, H));
  const front = Math.max(2.5 * H, 12);
  const x1 = front, x2 = x1 + face.run, x3 = x2 + B, x4 = x3 + face.run, xr = x4 + front;
  // the same benched face on both sides
  const left = face.pts.map(([x, y]) => [x1 + x, y]), right = face.pts.slice().reverse().map(([x, y]) => [x4 - x, y]);
  const ground = [[0, 0], ...left, ...right, [xr, 0]];
  const fill = soilFrom(p.fill), found = soilFrom(p.soil);
  const layers = (undrainedFound, undrainedFill = false) => [
    { top: null, mat: asMaterial(fill, undrainedFill) },
    { top: flat(0, 0, xr), mat: asMaterial(found, undrainedFound) },
  ];
  const hw = p.water?.on ? Math.min(H - 0.1, Math.max(0, num(p.water.level, 0))) : 0;
  const lowW = p.water?.on ? Math.min(hw, Math.max(0, num(p.water.low, 0))) : 0;
  // steady seepage: from the water face at hw straight to the land-side toe
  const xw = x1 + faceX(face, hw);
  const seep = hw > 0
    ? upper(lower([[0, hw], [xw, hw], [x4, 0], [xr, 0]], ground, 0, xr), [[0, hw], [xw, hw], [xw + 1e-6, -1e3], [xr, -1e3]], 0, xr)
    : flat(0, 0, xr);
  // after a rapid drawdown the water inside stays put; outside it falls to lowW
  const drawn = hw > 0
    ? upper(lower([[0, hw], [xw, hw], [x4, 0], [xr, 0]], ground, 0, xr), flat(lowW, 0, xr), 0, xr)
    : null;
  const q = num(p.load?.q, 0);
  const strip = (psi = 1) => q > 0 ? [{ x1: x2 + num(p.load.setback, 0.5), x2: Math.min(x3, x2 + num(p.load.setback, 0.5) + num(p.load.width, B)), q: q * psi, variable: true }] : [];
  const land = { toe: [x4, 0], crest: [x3, H] }, waterFace = { toe: [x1, 0], crest: [x2, H] };
  // geogrids across the fill, face to face, from near the base up
  const reinforcement = [];
  if (p.grids?.on) {
    const n = Math.max(1, Math.min(40, Math.round(num(p.grids.n, 1))));
    for (let i = 0; i < n; i++) {
      const y = num(p.grids.bottom, 0.25) + i * Math.max(0.1, num(p.grids.spacing, 0.5));
      if (y >= H - 0.05) break;
      reinforcement.push({ kind: "grid", y, x0: x1 + faceX(face, y), x1: x4 - faceX(face, y), x: x1 + faceX(face, y),
        T: Math.max(0, num(p.grids.T, 200)), Ci: Math.max(0, num(p.grids.Ci, 0.8)) });
    }
  }
  const landPiles = pileRow(p, x4 - num(p.piles?.x, 0), ground), waterPiles = pileRow(p, x1 + num(p.piles?.x, 0), ground);
  const base = { ground, bottom: -D, gw: 9.81, factors: factorsOf(p), crack: { depth: num(p.advanced?.crack, 0), water: 0 } };
  const T = targetsOf(p);
  const cases = [];
  if (found.clay || fill.clay) cases.push({ key: "eoc", name: "End of construction", target: T.short,
    model: { ...base, face: land, reinforcement: [...reinforcement, ...landPiles], layers: layers(true, fill.clay), piezo: flat(0, 0, xr), strips: strip() },
    note: "Just built: clays at undrained strength su, groundwater at original ground." });
  cases.push({ key: "long", name: hw > 0 ? "Long term, steady seepage" : "Long term (drained)", target: T.static,
    model: { ...base, face: land, reinforcement: [...reinforcement, ...landPiles], layers: layers(false), piezo: seep, strips: strip() },
    note: hw > 0 ? "Water held on the left at full level; seepage line straight to the right toe; land-side slope." : "Effective strength c', φ'." });
  if (hw > 0) cases.push({ key: "drawdown", name: "Rapid drawdown", target: T.transient,
    model: { ...base, face: waterFace, reinforcement: [...reinforcement, ...waterPiles], layers: layers(false), piezo: drawn, strips: strip() },
    note: `Water outside drops from ${hw.toFixed(1)} m to ${lowW.toFixed(1)} m faster than the fill drains (pore pressures stay at the steady-state line); water-side slope.` });
  const eq = seismicCoefficients(p, H, Math.atan(1 / cot) * 180 / Math.PI);
  if (eq) cases.push({ key: "seismic", name: "Seismic (pseudo-static)", target: T.seismic, seismic: eq,
    model: { ...base, face: land, reinforcement: [...reinforcement, ...landPiles], layers: layers(true, fill.clay), piezo: seep, strips: strip(0.3), seismic: { kh: eq.kh, kv: eq.kv } },
    note: "Earthquake as kh·W towards the land-side face and ±kv·W; clays undrained; 30% of the surcharge (ψ2)." });
  return { cases, geometry: { ground, H, xr, bottom: -D, layers: layers(false), piezo: seep, x1, x2, x3, x4, faceDir: 1, benches: face.benches, reinforcement: [...reinforcement, ...landPiles] }, extras: {} };
}

// ---------------------------------------------------------------- revetment

/** Armour design for a revetment project (used by the cases and shown on its own). */
export function armourDesign(p) {
  const g = p.geom, w = p.waves, a = p.armour;
  const cot = Math.max(1, num(g.cot, 2));
  const Hs = Math.max(0.1, num(w.Hs, 2)), Tp = Math.max(1, num(w.Tp, 8));
  const HWL = num(p.water.HWL, 1.5), LWL = num(p.water.LWL, 0);
  const h = Math.max(0.5, HWL - num(g.toe, -3));
  const Tm = Tp / 1.2;
  const N = Math.min(7500, Math.max(500, Math.round(num(w.hours, 6) * 3600 / Tm)));
  const common = { Hs, Tp, h, cot, rhoW: num(a.rhoW, 1025) };
  let unit;
  if (a.type === "accropode1" || a.type === "accropode2") {
    unit = accropode({ ...common, rhoC: num(a.rhoC, 2400), unit: a.type, section: w.section || "trunk", seabedSlope: num(w.seabed, 0.01) });
  } else {
    unit = rockArmour({ ...common, rhoR: num(a.rhoR, 2650), P: num(a.P, 0.4), S: a.S ? num(a.S, 2) : damageLevels(cot).start, N, breaking: Hs / h > 0.6, governing: a.governing || "max" });
  }
  const ht = Math.max(0.1, num(a.toeRatio, 0.8) * h);
  const toeRock = toe({ Hs, h, ht, rhoR: num(a.rhoR, 2650), rhoW: num(a.rhoW, 1025) });
  const gammaF = unit.kind === "rock" ? (num(a.P, 0.4) <= 0.15 ? 0.55 : 0.4) : COEFFS[unit.kind].gammaF;
  const ru = runup({ Hs, Tp, cot, gammaF });
  const ot = overtopping({ Hs, Rc: num(g.crest, 4) - HWL, gammaF });
  return { unit, toe: toeRock, runup: ru, overtopping: ot, h, N, HWL, LWL };
}

function revetmentCases(p) {
  const g = p.geom;
  const Zc = num(g.crest, 4), Zt = num(g.toe, -3), cot = Math.max(1, num(g.cot, 2));
  const H = Math.max(0.5, Zc - Zt);
  const D = Math.max(1, num(g.base, 6));
  const design = armourDesign(p);
  const ta = design.unit.thickness, tu = design.unit.underlayer.thickness;
  const front = Math.max(2.5 * H, 15);
  const xt = front, xc = xt + H * cot, xr = xc + Math.max(num(g.berm, 10) + 2 * H, 2.5 * H);
  const ground = [[0, Zt], [xt, Zt], [xc, Zc], [xr, Zc]];
  const sec = Math.sqrt(1 + cot * cot) / cot;           // vertical thickness per normal thickness on the face
  const face = (t) => [[xt - 1e3, Zt - t * sec - 1e3 / cot], [xc + 1e3, Zc - t * sec + 1e3 / cot]];
  const topU = lower(ground, upper(face(ta), flat(Zt, 0, xr), 0, xr), 0, xr);
  const topC = lower(ground, upper(face(ta + tu), flat(Zt, 0, xr), 0, xr), 0, xr);
  const armourMat = design.unit.kind === "rock" ? PRESETS.armourRock : PRESETS.concreteUnits;
  const core = soilFrom(p.core), found = soilFrom(p.soil);
  const layers = (undrained) => [
    { top: null, mat: asMaterial(armourMat, false) },
    { top: topU, mat: asMaterial(PRESETS.underlayer, false) },
    { top: topC, mat: asMaterial(core, undrained) },
    { top: flat(Zt, 0, xr), mat: asMaterial(found, undrained) },
  ];
  const gw = num(p.water.gw, 10.05);
  const HWL = num(p.water.HWL, 1.5), LWL = num(p.water.LWL, 0);
  const Hs = num(p.waves.Hs, 2);
  const still = (z) => flat(z, 0, xr);
  // inside at zi, outside at zo (zo < zi): outside water to the face, the face itself, then zi inland
  const lag = (zi, zo) => upper(flat(zo, 0, xr), lower(still(zi), ground, 0, xr), 0, xr);
  const q = num(p.load?.q, 0);
  const strip = (psi = 1) => q > 0 ? [{ x1: xc + num(p.load.setback, 2), x2: Math.min(xr, xc + num(p.load.setback, 2) + num(p.load.width, 8)), q: q * psi, variable: true }] : [];
  const base = { ground, bottom: Zt - D, gw, face: { toe: [xt, Zt], crest: [xc, Zc] }, factors: factorsOf(p), crack: { depth: 0, water: 0 } };
  const T = targetsOf(p);
  const trough = Math.max(Zt + 0.01, LWL - 0.5 * Hs);
  // How far the water inside lags behind a falling sea depends on how freely the core drains.
  const LAG = { rockfill: 0, denseSand: 0.25, sand: 0.5, looseSand: 0.5, fill: 0.5, weakRock: 0.5 };
  const lagFrac = p.water.inside !== undefined && p.water.inside !== null && p.water.inside !== ""
    ? null : (LAG[core.preset] ?? 1);
  const inside = lagFrac === null ? num(p.water.inside, HWL) : LWL + lagFrac * (HWL - LWL);
  // Hydraulic stability of the armour itself is the armour check; the global cases
  // look at surfaces that go through the armour and underlayer into the core.
  const minDepth = 1.05 * (ta + tu) * sec;
  const cases = [
    { key: "high", name: "High water, steady", target: T.static, minDepth, model: { ...base, layers: layers(false), piezo: still(HWL), strips: strip() },
      note: `Water at HWL ${HWL.toFixed(2)} m inside and out.` },
    { key: "low", name: "Low water, steady", target: T.static, minDepth, model: { ...base, layers: layers(false), piezo: still(LWL), strips: strip() },
      note: `Water at LWL ${LWL.toFixed(2)} m inside and out.` },
    { key: "drawdown", name: "Drawdown under wave trough", target: T.transient, minDepth, model: { ...base, layers: layers(false), piezo: lag(Math.max(inside, trough), trough), strips: strip() },
      note: `Sea at LWL − Hs/2 = ${trough.toFixed(2)} m (low tide plus wave run-down) while the water inside the ${core.name.toLowerCase()} lags at ${Math.max(inside, trough).toFixed(2)} m${lagFrac === null ? " (as entered)" : lagFrac === 1 ? " (does not drain: stays at HWL)" : ""}.` },
  ];
  const eq = seismicCoefficients(p, H, Math.atan(1 / cot) * 180 / Math.PI);
  const mid = (HWL + LWL) / 2;
  if (eq) cases.push({ key: "seismic", name: "Seismic (pseudo-static)", target: T.seismic, minDepth, seismic: eq,
    model: { ...base, layers: layers(true), piezo: still(mid), strips: strip(0.3), seismic: { kh: eq.kh, kv: eq.kv } },
    note: `Earthquake at mean water ${mid.toFixed(2)} m; kh·W towards the sea, ±kv·W; clays undrained; 30% of the surcharge.` });
  return {
    cases,
    geometry: { ground, H, xt, xc, xr, bottom: Zt - D, layers: layers(false), piezo: still(HWL), topU, topC, Zt, Zc, ta, tu, water: { HWL, LWL }, faceDir: -1,
      armour: { kind: design.unit.kind === "rock" ? "rock" : "unit", Dn: design.unit.DnDesign, thickness: ta, toe: [xt, Zt], crest: [xc, Zc] } },
    extras: { armour: design },
  };
}

// ---------------------------------------------------------------- any section

/** Points typed or pasted as "x, y" lines (commas, tabs or spaces), sorted by x. */
export function parsePoints(text) {
  if (Array.isArray(text)) return text.filter((p) => Number.isFinite(+p[0]) && Number.isFinite(+p[1])).map((p) => [+p[0], +p[1]]).sort((a, b) => a[0] - b[0]);
  const pts = [];
  for (const line of String(text || "").split(/[\r\n;]+/)) {
    const nums = line.trim().split(/[\s,]+/).filter(Boolean).map(Number);
    if (nums.length >= 2 && Number.isFinite(nums[0]) && Number.isFinite(nums[1])) pts.push([nums[0], nums[1]]);
  }
  return pts.sort((a, b) => a[0] - b[0]);
}

/** Crest and toe of the face: the highest and lowest ground with the slope between them. */
function faceOfGround(ground) {
  let hi = 0, lo = 0;
  ground.forEach((p, i) => { if (p[1] > ground[hi][1] + 1e-9) hi = i; if (p[1] < ground[lo][1] - 1e-9) lo = i; });
  if (ground[hi][0] < ground[lo][0]) {
    // falls to the right: crest is the last high point before the fall, toe the first low point after it
    let c = hi; while (c + 1 < lo && ground[c + 1][1] >= ground[hi][1] - 1e-6) c++;
    let t = lo; while (t - 1 > c && ground[t - 1][1] <= ground[lo][1] + 1e-6) t--;
    return { crest: ground[c], toe: ground[t] };
  }
  let c = hi; while (c - 1 > lo && ground[c - 1][1] >= ground[hi][1] - 1e-6) c--;
  let t = lo; while (t + 1 < c && ground[t + 1][1] <= ground[lo][1] + 1e-6) t++;
  return { crest: ground[c], toe: ground[t] };
}

function sectionCases(p) {
  let ground = parsePoints(p.ground);
  if (ground.length < 2) ground = parsePoints(DEFAULTS.section.ground);
  const x0 = ground[0][0], x1 = ground[ground.length - 1][0];
  const yMin = Math.min(...ground.map((q) => q[1]));
  const bottom = Math.min(num(p.base, yMin - 10), yMin - 0.5);
  const span = (line) => {
    const pts = parsePoints(line);
    if (!pts.length) return null;
    return [[x0, pts[0][1]], ...pts.filter((q) => q[0] > x0 && q[0] < x1), [x1, pts[pts.length - 1][1]]];
  };
  const specs = (p.layers?.length ? p.layers : DEFAULTS.section.layers).map((L, i) => ({ soil: soilFrom(L.soil), top: i === 0 ? null : span(L.top) }))
    .filter((L, i) => i === 0 || L.top);
  const layers = (undrained) => specs.map((L) => ({ top: L.top, mat: asMaterial(L.soil, undrained) }));
  const mode = p.water?.mode || "none";
  const line = mode === "line" ? span(p.water.line) : null;
  const piezo = line ? line : null;
  const ru = mode === "ru" ? Math.max(0, Math.min(1, num(p.water.ru, 0))) : 0;
  const face = faceOfGround(ground);
  const H = Math.max(0.1, face.crest[1] - face.toe[1]);
  const slopeDeg = Math.atan(H / Math.max(0.01, Math.abs(face.toe[0] - face.crest[0]))) * 180 / Math.PI;
  const q = num(p.load?.q, 0);
  const a = num(p.load?.x1, x0), b = num(p.load?.x2, x0);
  const strip = (psi = 1) => (q > 0 && Math.abs(b - a) > 0 ? [{ x1: Math.min(a, b), x2: Math.max(a, b), q: q * psi, variable: true }] : []);
  const reinforcement = pileRow(p, num(p.piles?.x, (face.crest[0] + face.toe[0]) / 2), ground);
  const base = { ground, bottom, face, gw: 9.81, factors: factorsOf(p), crack: { depth: num(p.advanced?.crack, 0), water: 0 }, ru, reinforcement };
  const T = targetsOf(p);
  const clayey = specs.some((L) => L.soil.clay && L.soil.su > 0);
  const water = piezo ? "the water line" : ru ? `ru = ${ru}` : "no water";
  const cases = [{ key: "long", name: "Long term (drained)", target: T.static, model: { ...base, layers: layers(false), piezo, strips: strip() },
    note: `Effective strength c', φ' with ${water}.` }];
  if (clayey) cases.push({ key: "short", name: "Short term (undrained)", target: T.short, model: { ...base, layers: layers(true), piezo, strips: strip() },
    note: "Layers with an undrained strength at su (with its increase with depth and cap); the others drained." });
  const eq = seismicCoefficients(p, H, slopeDeg);
  if (eq) cases.push({ key: "seismic", name: "Seismic (pseudo-static)", target: T.seismic, seismic: eq,
    model: { ...base, layers: layers(true), piezo, strips: strip(0.3), seismic: { kh: eq.kh, kv: eq.kv } },
    note: "kh·W towards the face and ±kv·W; layers with su undrained; 30% of the surcharge (ψ2)." });
  const faceDir = face.crest[0] < face.toe[0] ? 1 : -1;
  return { cases, geometry: { ground, H, xr: x1, bottom, layers: layers(false), piezo, faceDir, reinforcement }, extras: {} };
}

/** Every load case of a project: [{ key, name, target, model, note, seismic? }] plus the geometry to draw. */
export function buildCases(project) {
  const p = complete(project);
  if (p.type === "embankment") return { project: p, ...embankmentCases(p) };
  if (p.type === "revetment") return { project: p, ...revetmentCases(p) };
  if (p.type === "section") return { project: p, ...sectionCases(p) };
  return { project: p, ...cutCases(p) };
}

export { yAt };
