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
  armourRock: { name: "Armour rock layer",    gamma: 16.4, gsat: 20,   c: 0,  phi: 45, su: 0,   suGrad: 0,   clay: false },
  underlayer: { name: "Underlayer rock",      gamma: 17,   gsat: 20.5, c: 0,  phi: 42, su: 0,   suGrad: 0,   clay: false },
  concreteUnits: { name: "Concrete unit layer", gamma: 12.5, gsat: 17.5, c: 0, phi: 45, su: 0,  suGrad: 0,   clay: false },
};

export const PRESET_KEYS = ["softClay", "firmClay", "stiffClay", "silt", "looseSand", "sand", "denseSand", "fill", "claySilt", "rockfill", "weakRock"];

/** A soil as the engine sees it in a given state: drained (effective) or undrained (total). */
export function asMaterial(soil, undrained) {
  if (undrained && soil.clay && soil.su > 0) {
    return { name: soil.name, gamma: soil.gamma, gsat: soil.gsat, kind: "undrained", su: soil.su, suGrad: soil.suGrad || 0, phi: 0, c: 0 };
  }
  return { name: soil.name, gamma: soil.gamma, gsat: soil.gsat, kind: "drained", c: soil.c, phi: soil.phi };
}

/** A soil from a project entry: a preset plus whatever the user typed over it. */
export function soilFrom(spec) {
  const base = PRESETS[spec?.preset] || PRESETS.sand;
  const out = { ...base, preset: spec?.preset || "sand" };
  for (const k of ["gamma", "gsat", "c", "phi", "su", "suGrad"]) {
    const v = spec?.[k];
    if (v !== undefined && v !== null && v !== "" && Number.isFinite(+v)) out[k] = +v;
  }
  if (spec?.clay !== undefined) out.clay = !!spec.clay;
  return out;
}
