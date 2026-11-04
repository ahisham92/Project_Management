// Typical soil and rock parameters for a first look. They are starting values for
// minimal input, not design values: every one is shown and can be overwritten
// with site data. gamma = bulk unit weight above water, gsat = saturated, kN/m3.
// Undrained strength su (kPa) at the top of the layer, increasing by suGrad per m.

export const PRESETS = {
  softClay:   { name: "Soft clay",            gamma: 16.5, gsat: 17,   c: 2,  phi: 22, su: 20,  suGrad: 1.5, clay: true },
  firmClay:   { name: "Firm clay",            gamma: 18,   gsat: 18.5, c: 5,  phi: 24, su: 50,  suGrad: 1,   clay: true },
  stiffClay:  { name: "Stiff clay",           gamma: 19.5, gsat: 20,   c: 10, phi: 26, su: 100, suGrad: 0,   clay: true },
  silt:       { name: "Silt",                 gamma: 18,   gsat: 19,   c: 2,  phi: 28, su: 0,   suGrad: 0,   clay: false },
  looseSand:  { name: "Loose sand",           gamma: 17,   gsat: 19,   c: 0,  phi: 30, su: 0,   suGrad: 0,   clay: false },
  sand:       { name: "Medium dense sand",    gamma: 18,   gsat: 20,   c: 0,  phi: 34, su: 0,   suGrad: 0,   clay: false },
  denseSand:  { name: "Dense sand / gravel",  gamma: 19,   gsat: 21,   c: 0,  phi: 38, su: 0,   suGrad: 0,   clay: false },
  fill:       { name: "Compacted fill",       gamma: 19,   gsat: 20.5, c: 2,  phi: 32, su: 0,   suGrad: 0,   clay: false },
  claySilt:   { name: "Compacted clay fill",  gamma: 19,   gsat: 19.5, c: 8,  phi: 25, su: 75,  suGrad: 0,   clay: true },
  rockfill:   { name: "Rock fill / quarry run", gamma: 19, gsat: 21,   c: 0,  phi: 40, su: 0,   suGrad: 0,   clay: false },
  weakRock:   { name: "Weathered rock",       gamma: 22,   gsat: 23,   c: 30, phi: 35, su: 0,   suGrad: 0,   clay: false },
  // rock masses by the generalised Hoek-Brown criterion (Hoek, Carranza-Torres and Corkum 2002)
  rockHB:     { name: "Rock mass (Hoek-Brown)", gamma: 25, gsat: 25.5, c: 0, phi: 0, su: 0, suGrad: 0, clay: false, hb: true, GSI: 45, mi: 10, sci: 25, D: 0 },
  weakRockHB: { name: "Weak rock, mudstone (Hoek-Brown)", gamma: 23, gsat: 23.5, c: 0, phi: 0, su: 0, suGrad: 0, clay: false, hb: true, GSI: 30, mi: 7, sci: 8, D: 0 },
  armourRock: { name: "Armour rock layer",    gamma: 16.4, gsat: 20,   c: 0,  phi: 45, su: 0,   suGrad: 0,   clay: false },
  underlayer: { name: "Underlayer rock",      gamma: 17,   gsat: 20.5, c: 0,  phi: 42, su: 0,   suGrad: 0,   clay: false },
  concreteUnits: { name: "Concrete unit layer", gamma: 12.5, gsat: 17.5, c: 0, phi: 45, su: 0,  suGrad: 0,   clay: false },
};

export const PRESET_KEYS = ["softClay", "firmClay", "stiffClay", "silt", "looseSand", "sand", "denseSand", "fill", "claySilt", "rockfill", "weakRock", "rockHB", "weakRockHB"];

/** A soil as the engine sees it in a given state: drained (effective) or undrained (total). */
export function asMaterial(soil, undrained) {
  if (soil.hb) return { name: soil.name, gamma: soil.gamma, gsat: soil.gsat, kind: "hb", ...hoekBrown(soil), c: 0, phi: 0 };
  if (undrained && soil.clay && soil.su > 0) {
    return { name: soil.name, gamma: soil.gamma, gsat: soil.gsat, kind: "undrained", su: soil.su, suGrad: soil.suGrad || 0, suMax: soil.suMax || 0, phi: 0, c: 0 };
  }
  return { name: soil.name, gamma: soil.gamma, gsat: soil.gsat, kind: "drained", c: soil.c, phi: soil.phi };
}

/** A soil from a project entry: a preset plus whatever the user typed over it. */
export function soilFrom(spec) {
  const base = PRESETS[spec?.preset] || PRESETS.sand;
  const out = { ...base, preset: spec?.preset || "sand" };
  for (const k of ["gamma", "gsat", "c", "phi", "su", "suGrad", "suMax", "GSI", "mi", "sci", "D"]) {
    const v = spec?.[k];
    if (v !== undefined && v !== null && v !== "" && Number.isFinite(+v)) out[k] = +v;
  }
  // an undrained strength typed in means the layer is checked undrained in the short term
  if (spec?.su !== undefined && spec.su !== null && spec.su !== "" && +spec.su > 0) out.clay = true;
  if (spec?.clay !== undefined) out.clay = !!spec.clay;
  if (spec?.name) out.name = String(spec.name).slice(0, 40);
  return out;
}

// ---------------------------------------------------------------- Hoek-Brown

/**
 * Generalised Hoek-Brown constants of a rock mass (Hoek, Carranza-Torres and Corkum
 * 2002): GSI, mi, intact strength sci (MPa) and disturbance D. Stresses come out in kPa.
 */
export function hoekBrown({ GSI, mi, sci, D = 0 }) {
  const g = Math.max(5, Math.min(100, +GSI || 0)), d = Math.max(0, Math.min(1, +D || 0));
  const mb = (+mi || 1) * Math.exp((g - 100) / (28 - 14 * d));
  const s = Math.exp((g - 100) / (9 - 3 * d));
  const a = 0.5 + (Math.exp(-g / 15) - Math.exp(-20 / 3)) / 6;
  return { GSI: g, mi: +mi, sci: +sci, D: d, mb, s, a, sigci: Math.max(1, +sci || 0) * 1000 };
}

/**
 * Shear strength of a Hoek-Brown rock mass on a plane with effective normal stress sn
 * (kPa), as the tangent to the envelope there: { c, tanphi, tau, s3 }. Balmer (1952):
 * with k = dsigma1/dsigma3, sn = s3 + (s1 - s3) / (k + 1), tau = (s1 - s3) sqrt(k) / (k + 1),
 * and the tangent friction angle has sin(phi) = (k - 1) / (k + 1).
 */
export function hbTangent(hb, sn) {
  const { mb, s, a, sigci } = hb;
  const t3 = -s * sigci / mb;                    // sigma3 where the envelope meets tension
  const at = (s3) => {
    const base = Math.max(1e-12, mb * s3 / sigci + s);
    const d = sigci * Math.pow(base, a);          // sigma1 - sigma3
    const k = 1 + a * mb * Math.pow(base, a - 1);
    return { s3, d, k, sn: s3 + d / (k + 1), tau: d * Math.sqrt(k) / (k + 1) };
  };
  const target = Math.max(0, sn);
  let lo = t3 * (1 - 1e-9), hi = Math.max(target, 1);
  while (at(hi).sn < target) hi *= 2;
  for (let i = 0; i < 200; i++) {
    const m = (lo + hi) / 2;
    if (m <= lo || m >= hi) break;
    if (at(m).sn < target) lo = m; else hi = m;
  }
  const r = at((lo + hi) / 2);
  const tanphi = (r.k - 1) / (2 * Math.sqrt(r.k));
  return { tanphi, c: r.tau - target * tanphi, tau: r.tau, s3: r.s3 };
}

/**
 * The Mohr-Coulomb fit of Hoek et al. (2002) over sigma3 from the tensile strength to
 * sigma3max, with sigma3max for slopes from the rock-mass strength and the slope height H
 * (sigma'3max / sigma'cm = 0.72 (sigma'cm / gamma H)^-0.91). For the record and for comparison.
 */
export function hbEquivalent(hb, gamma, H) {
  const { mb, s, a, sigci } = hb;
  const scm = sigci * ((mb + 4 * s - a * (mb - 8 * s)) * Math.pow(mb / 4 + s, a - 1)) / (2 * (1 + a) * (2 + a));
  const s3max = 0.72 * scm * Math.pow(scm / (gamma * Math.max(1, H)), -0.91);
  const s3n = s3max / sigci;
  const q = Math.pow(s + mb * s3n, a - 1);
  const sinphi = 6 * a * mb * q / (2 * (1 + a) * (2 + a) + 6 * a * mb * q);
  const c = sigci * ((1 + 2 * a) * s + (1 - a) * mb * s3n) * q / ((1 + a) * (2 + a) * Math.sqrt(1 + 6 * a * mb * q / ((1 + a) * (2 + a))));
  return { c, phi: Math.asin(sinphi) * 180 / Math.PI, s3max, scm };
}
