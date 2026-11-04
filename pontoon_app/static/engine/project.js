// A project is the handful of numbers the page asks for. Everything else is
// derived here from AS 3962 so the defaults are a code-compliant starting point:
// pick the boat and the number of berths, and the walkway, fingers, gangway and
// piles are laid out for you. Any derived value can be typed over.

import { BEAM, DRAUGHT, WINDAGE, interp, gangwayWidth, walkwayWidth, WALKWAY, GANGWAY_SLOPE, RETURN_PERIOD, FAIRWAY, minDisplacement } from "./codes.js";

export const KINDS = ["concrete", "framed", "modular", "attenuator"];

/** Narrowest walkway and finger each kind is usually built at (m): stability, not the code minimum, governs. */
export const PRACTICAL = {
  concrete: { walkway: 2.4, finger: 2.0 },
  framed: { walkway: 2.4, finger: 1.0 },
  modular: { walkway: 2.5, finger: 1.5 },
  attenuator: { walkway: 4.0, finger: 2.0 },
};

const SECTION_DEFAULTS = {
  concrete: { D: 1.00, wall: 0.05, deck: 0.09, base: 0.05, fc: 40, density: 24.5, sdl: 0.25, mesh: 252, meshCover: 30 },
  attenuator: { D: 1.80, wall: 0.08, deck: 0.12, base: 0.12, ballast: 0.10, fc: 50, density: 24.5, sdl: 0.25, mesh: 393, meshCover: 40 },
  framed: { frame: "aluminium", deck: "timber", floats: 2, floatW: null, floatH: 0.5, cover: 0.95, frameH: 0.25, sdl: 0.30, frameI: 4.0e-5, frameMr: 60 },
  modular: { cube: 0.4, cubeMass: 7.0, sdl: 0.05, matEI: null },
};

export const DEFAULTS = {
  type: "concrete",
  name: "Marina arm A",
  access: "unrestricted",
  water: "sea",
  vessel: { L: 12, kind: "motor", disp: null },
  layout: { berths: 20, accessible: false, sides: 2, moduleLength: 15, walkwayWidth: null, fingerLength: null, fingerWidth: null, gangwayLanding: 3.5, gangwayLength: null,
    shape: "single", arms: 3, armSpacing: null, headLength: null, spineLength: null },
  site: {
    region: "A2", life: 25, importance: 2, Md: 1.0, Ms: 1.0, Mt: 1.0, duration: 1.0,
    HAT: 2.0, LAT: 0.0, surge: 0.6, slr: 0.4, seabed: -4.0, scour: 0.3,
    current: 1.0, Hs: 0.3, Tp: 2.5, debris: false, climate: "good",
  },
  section: {},
  piles: {
    type: "steel", auto: true, spacing: 12, d: 457, t: 12.7, grade: "G350", coating: 0,
    concrete: { shape: "square", b: 450, fc: 50, bars: 8, db: 24, cover: 65 },
    timber: { D: 400, grade: "F17", phi: 0.75 },
    soil: { type: "sand", phi: 32, gamma: 9, su: 25 },
    arr: 2.5, redundancy: "low", embed: null, guideAbove: 0.0,
  },
  fender: { k: 400 }, // kN/m, pontoon-mounted rubbing strip / fender stiffness
  design: { freeboardSet: "as3962", tiltLimit: null, chine: true, category: "small", pileDeflection: 0.15 },
  mooring: { type: "piles", spacing: 12, chainD: null, angle: 45 },
  seismic: { on: true, Z: 0.08, site: "De", Sp: 1.0, mu: 1.0 },
  connections: { grade: "A4-70", rodsPerSide: 2, rodD: null, guideGap: 0.05 },
  gangway: { material: "aluminium", depth: null, chord: null, chordT: null, panel: 1.0, dead: 0.6, landingWidth: null },
};

/** Fingers are lighter than the walkway they hang off. Concrete fingers: a shallower, thinner shell. */
const FINGER_DEFAULTS = {
  concrete: { D: 0.80, wall: 0.04, deck: 0.075, base: 0.04 },
  attenuator: { D: 0.80, wall: 0.04, deck: 0.075, base: 0.04, ballast: 0 },
  framed: { floats: 1, floatW: null }, modular: {},
};
export const fingerDefaults = (type) => JSON.parse(JSON.stringify(FINGER_DEFAULTS[type]));

const deep = (o) => JSON.parse(JSON.stringify(o));
function merge(base, over) {
  if (over === null || over === undefined) return base;
  if (typeof base !== "object" || base === null || Array.isArray(base)) return over;
  const out = { ...base };
  for (const k of Object.keys(over)) out[k] = merge(base[k], over[k]);
  return out;
}

/** Fill in everything not given. */
export function complete(p = {}) {
  const type = KINDS.includes(p.type) ? p.type : "concrete";
  const base = deep(DEFAULTS);
  base.type = type;
  base.section = deep(SECTION_DEFAULTS[type]);
  const out = merge(base, p);
  out.type = type;
  out.section = merge(deep(SECTION_DEFAULTS[type]), p.section || {});
  out.finger = merge(deep(FINGER_DEFAULTS[type]), p.finger || {});
  return out;
}

export const sectionDefaults = (type) => deep(SECTION_DEFAULTS[type]);

/** The design vessel, with AS 3962 tables filling in what was not given. */
export function vesselOf(p) {
  const L = +p.vessel.L, motor = p.vessel.kind !== "yacht";
  const beam = +p.vessel.beam || interp(BEAM, L);
  // Table 3.1: the 95th percentile draught is the design draught (depth, keel); the average sets the hull estimate
  const draught = +p.vessel.draft || interp(DRAUGHT, L, motor ? 2 : 4);
  const draughtAvg = +p.vessel.draft || interp(DRAUGHT, L, motor ? 1 : 3);
  const windHead = interp(WINDAGE, L, motor ? 1 : 3), windBeam = interp(WINDAGE, L, motor ? 2 : 4);
  // Displacement estimate when the boat's own figure is not given: block coefficient on the
  // waterline hull (Lwl ≈ 0.88 L, hull draught ≈ 0.55 × the AS 3962 Table 3.1 average draught for power
  // boats, 0.35 for yachts whose keel is most of the draught), and not less than the AS 3962:2020
  // Table 4.6 minimum for berthing (Cl 4.9). Replace with the actual figure.
  const Lwl = 0.88 * L, Th = draughtAvg * (motor ? 0.55 : 0.35), Cb = motor ? 0.42 : 0.40;
  const dispHull = Cb * Lwl * beam * Th * 1.026; // t
  const dispMin = minDisplacement(L);
  const dispEst = Math.max(dispHull, dispMin);
  const disp = +p.vessel.disp || dispEst;
  return { L, motor, beam, draught, draughtAvg, windHead, windBeam, disp, dispEst, dispHull, dispMin, given: !!+p.vessel.disp, Lwl, hullDraft: Th };
}

export const SHAPES = {
  single: "One straight arm",
  L: "Arm with a landward walkway (L)",
  T: "Arm with a T-head",
  comb: "Several arms off a spine walkway",
};

/** The layout derived from the berths and the boat (AS 3962 Cl 3.3 to 3.5, Tables 3.2 and 3.3). */
export function layoutOf(p) {
  const v = vesselOf(p), lay = p.layout;
  const shape = SHAPES[lay.shape] ? lay.shape : "single";
  const arms = shape === "comb" ? Math.max(2, Math.min(12, Math.round(+lay.arms || 3))) : 1;
  const berths = Math.max(1, Math.round(+lay.berths || 1));
  const perArm = Math.ceil(berths / arms);
  const sides = +lay.sides === 1 ? 1 : 2;
  // single berths between fingers: berth width = beam + 1.0 m (≤ 20 m) or + 1.5 m (Table 3.2)
  const berthW = v.beam + (v.L > 20 ? 1.5 : 1.0);
  const fingerW = +lay.fingerWidth || Math.max(WALKWAY.fingerWidth, PRACTICAL[p.type].finger);
  const perSide = Math.ceil(perArm / sides);
  const walkLen = perSide * (berthW + fingerW) + fingerW;
  // AS 3962 Cl 3.5 minimum, or the narrowest this kind of pontoon is usually made, if wider
  const accessible = !!lay.accessible;
  const gw = gangwayWidth(berths, accessible);
  const walkW = +lay.walkwayWidth || Math.max(walkwayWidth(walkLen * arms, accessible, gw), PRACTICAL[p.type].walkway);
  const fingerL = +lay.fingerLength || Math.ceil(WALKWAY.fingerLength * v.L * 2) / 2;
  const slope = accessible ? GANGWAY_SLOPE.accessibleMax : GANGWAY_SLOPE.general;
  const moduleL = Math.max(3, +lay.moduleLength || 15);
  const modules = Math.max(1, Math.ceil(walkLen / moduleL));
  const armLen = modules * moduleL;
  // arms side by side: boats on facing sides of the gap need a fairway of 1.5 L between their sterns
  const reach = 0.6 + v.L;                       // boat stern from the walkway edge
  const fairwayNeed = FAIRWAY.factor * v.L;
  const spacingMin = walkW + (sides === 2 ? 2 : 1) * reach + fairwayNeed;
  const armSpacing = shape === "comb" ? (+lay.armSpacing || Math.ceil(spacingMin)) : 0;
  const fairway = shape === "comb" ? armSpacing - walkW - (sides === 2 ? 2 : 1) * reach : null;
  const round = (len) => Math.max(1, Math.ceil(len / moduleL)) * moduleL;
  let spine = null, head = null;
  if (shape === "comb") spine = { len: round(+lay.spineLength || (arms - 1) * armSpacing + walkW) };
  if (shape === "L") spine = { len: round(+lay.spineLength || fingerL + walkW + reach) };
  if (shape === "T") head = { len: round(+lay.headLength || 2 * fingerL + walkW) };
  if (spine) spine.modules = spine.len / moduleL;
  if (head) head.modules = head.len / moduleL;
  return {
    v, shape, arms, perArm, berths, sides, berthW, fingerW, fingerL, perSide, walkLen: armLen, walkNeeded: walkLen, walkW,
    gangwayW: gw, slope, accessible, moduleL, modules, armSpacing, fairway, fairwayNeed, spine, head,
    totalWalk: armLen * arms + (spine ? spine.len : 0) + (head ? head.len : 0),
    totalModules: modules * arms + (spine ? spine.modules : 0) + (head ? head.modules : 0),
    totalFingers: (perSide + 1) * sides * arms,
  };
}

/** Return period (years) for strength wind, from AS/NZS 1170.0 Table F2. */
export function returnPeriod(p) {
  const lives = [5, 25, 50, 100];
  const life = lives.find((l) => +p.site.life <= l) || 100;
  return RETURN_PERIOD[life][Math.min(4, Math.max(1, +p.site.importance || 2))];
}
