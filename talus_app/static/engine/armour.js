// Talus — revetment armour: rock (Hudson, Van der Meer) and single-layer
// interlocking concrete units (Accropode I and II), toe, underlayer, run-up and
// overtopping. Every coefficient is listed in COEFFS with its source so a
// checker can see where each number comes from; all of them can be overridden.

export const G = 9.81;

export const COEFFS = {
  hudsonRock: { breaking: 2.0, nonBreaking: 4.0, src: "Hudson (1959); KD for rough angular rock, 2 layers, random, trunk, with H = Hs (Rock Manual 2007, Section 5.2.2.2; CEM VI-5-22)" },
  accropode1: { trunk: 15, head: 11.5, ns: 2.7, kDelta: 1.29, ks: 0.341, phi: 0.62, gammaF: 0.46, src: "CLI design-stage values: KD 15 trunk / 11.5 head, valid for armour slopes 4:3 to 3:2 and seabed slopes up to 3% (CLI; TU Delft breakwater units database). Layer coefficient 1.29, shape coefficient V = 0.341 H^3." },
  accropode2: { trunk: 16, head: 12.3, ns: 2.8, kDelta: 1.29, ks: 0.341, phi: 0.62, gammaF: 0.46, src: "CLI design-stage values for Accropode II: KD 16 trunk / 12.3 head (CLI)." },
  vdm1988: { pl: 6.2, s: 1.0, src: "Van der Meer (1988), deep water, Tm (Rock Manual 2007 Eqs 5.136-5.137)" },
  vdmShallow: { pl: 8.4, s: 1.3, src: "Van Gent et al. (2003) modification of Van der Meer for shallow foreshores, Tm-1,0 and H2% (Rock Manual 2007 Eqs 5.139-5.140)" },
  toe: { src: "Van der Meer (1998) toe formula: Hs/(Delta Dn50) = (2 + 6.2 (ht/h)^2.7) Nod^0.15" },
  runup: { src: "EurOtop (2018) Eqs 5.2-5.6, mean values" },
  overtopping: { src: "EurOtop (2018) Eq 6.5, mean value approach for rubble mound slopes" },
};

/** Damage levels S for a two-layer rock armour (Van der Meer 1988). */
export function damageLevels(cot) {
  if (cot <= 1.5) return { start: 2, moderate: 4, failure: 8 };
  if (cot <= 2) return { start: 2, moderate: 5, failure: 8 };
  if (cot <= 3) return { start: 2, moderate: 7, failure: 12 };
  return { start: 3, moderate: 10, failure: 17 };
}

/** EN 13383 standard gradings, with the effective mean mass range M_em (kg). */
export const GRADINGS = [
  { name: "LMA 5-40", lo: 5, hi: 40, mem: [10, 20] },
  { name: "LMA 10-60", lo: 10, hi: 60, mem: [20, 35] },
  { name: "LMA 15-120", lo: 15, hi: 120, mem: [45, 70] },
  { name: "LMA 40-200", lo: 40, hi: 200, mem: [80, 120] },
  { name: "LMA 60-300", lo: 60, hi: 300, mem: [120, 190] },
  { name: "HMA 300-1000", lo: 300, hi: 1000, mem: [540, 690] },
  { name: "HMA 1000-3000", lo: 1000, hi: 3000, mem: [1700, 2100] },
  { name: "HMA 3000-6000", lo: 3000, hi: 6000, mem: [4200, 4800] },
  { name: "HMA 6000-10000", lo: 6000, hi: 10000, mem: [7500, 8500] },
  { name: "HMA 10000-15000", lo: 10000, hi: 15000, mem: [12000, 13000] },
];

/** Accropode unit volumes commonly produced (m3). */
export const UNIT_SIZES = [0.75, 1, 1.5, 2, 2.5, 3, 4, 5, 6, 7, 8, 9, 10, 12, 14, 16, 18, 20, 22, 24, 26, 28];

/** Smallest standard grading whose lower M_em limit is at least m (kg). */
export function gradingFor(m) {
  return GRADINGS.find((g) => g.mem[0] >= m) || null;
}

/** Underlayer grading for an armour of mean mass m: aims for m/10, within m/15 to m/7. */
export function underlayerFor(m) {
  const lo = m / 15, hi = m / 7;
  const fits = GRADINGS.filter((g) => (g.mem[0] + g.mem[1]) / 2 >= lo && (g.mem[0] + g.mem[1]) / 2 <= hi);
  if (fits.length) {
    return fits.reduce((a, b) => (Math.abs(Math.log((a.mem[0] + a.mem[1]) / 2 / (m / 10))) <= Math.abs(Math.log((b.mem[0] + b.mem[1]) / 2 / (m / 10))) ? a : b));
  }
  return GRADINGS.find((g) => g.mem[0] >= m / 15) || null;
}

/** Wave steepness, surf similarity and periods used by the formulae. */
export function waveParams(w) {
  const tana = 1 / w.cot;
  const Tm = w.Tm || w.Tp / 1.2;            // mean period (JONSWAP Tp/Tm about 1.2)
  const Tm10 = w.Tm10 || w.Tp / 1.1;        // spectral period Tm-1,0
  const som = 2 * Math.PI * w.Hs / (G * Tm * Tm);
  const s10 = 2 * Math.PI * w.Hs / (G * Tm10 * Tm10);
  return { tana, Tm, Tm10, som, s10, xim: tana / Math.sqrt(som), xi10: tana / Math.sqrt(s10) };
}

/** Van der Meer stability number (deep water 1988, or shallow 2003 form). */
export function vanDerMeerNs(w, P, S, N, shallow, H2) {
  const { tana, xim, xi10 } = waveParams(w);
  const c = shallow ? COEFFS.vdmShallow : COEFFS.vdm1988;
  const xi = shallow ? xi10 : xim;
  const hRatio = shallow ? 1 / (H2 || 1.4) : 1;
  const base = Math.pow(S / Math.sqrt(N), 0.2) * hRatio;
  const pl = c.pl * Math.pow(P, 0.18) * base * Math.pow(xi, -0.5);
  const su = c.s * Math.pow(P, -0.13) * base * Math.sqrt(w.cot) * Math.pow(xi, P);
  const xicr = Math.pow((c.pl / c.s) * Math.pow(P, 0.31) * Math.sqrt(tana), 1 / (P + 0.5));
  const plunging = w.cot >= 4 || xi < xicr;
  return { Ns: plunging ? pl : su, plunging, xi, xicr, pl, su };
}

/**
 * Rock armour design.
 * a = { Hs, Tp, h (depth at toe), cot, rhoR, rhoW, P, S, N, breaking, H2, governing: "max"|"vdm"|"hudson", kt, porosity }
 */
export function rockArmour(a) {
  const D = a.rhoR / a.rhoW - 1;
  const shallow = a.h < 3 * a.Hs;
  const S = a.S ?? damageLevels(a.cot).start;
  const N = a.N ?? 3000;
  const KD = a.KD ?? (a.breaking ? COEFFS.hudsonRock.breaking : COEFFS.hudsonRock.nonBreaking);
  const NsH = Math.cbrt(KD * a.cot);
  const vdm = vanDerMeerNs(a, a.P, S, N, shallow, a.H2);
  const DnH = a.Hs / (D * NsH), DnV = a.Hs / (D * vdm.Ns);
  const gov = a.governing || "max";
  const Dn = gov === "hudson" ? DnH : gov === "vdm" ? DnV : Math.max(DnH, DnV);
  const M = a.rhoR * Dn ** 3;
  const grading = gradingFor(M);
  const mDesign = grading ? (grading.mem[0] + grading.mem[1]) / 2 : M;
  const DnDesign = Math.cbrt(mDesign / a.rhoR);
  const kt = a.kt ?? 1.0;
  const t = 2 * kt * DnDesign;
  const under = underlayerFor(mDesign);
  const DnU = under ? Math.cbrt((under.mem[0] + under.mem[1]) / 2 / a.rhoR) : Math.cbrt(mDesign / 10 / a.rhoR);
  const warnings = [];
  const wp = waveParams(a);
  if (a.cot < 1.5) warnings.push("Rock armour steeper than 1:1.5 is outside Van der Meer's tested range.");
  if (wp.som < 0.005 || wp.som > 0.06) warnings.push("Wave steepness is outside Van der Meer's tested range (0.005-0.06).");
  if (N > 7500) warnings.push("More than 7500 waves: Van der Meer is capped at N = 7500 (damage stabilises).");
  if (!grading) warnings.push("Required mass is above the heaviest EN 13383 grading: consider concrete units.");
  return {
    kind: "rock", D, shallow, S, N, KD,
    hudson: { Ns: NsH, Dn50: DnH, M50: a.rhoR * DnH ** 3 },
    vdm: { ...vdm, Dn50: DnV, M50: a.rhoR * DnV ** 3, formula: shallow ? "Van Gent et al. (2003)" : "Van der Meer (1988)" },
    governing: gov, Dn50: Dn, M50: M, grading, mDesign, DnDesign,
    thickness: t, layers: 2, porosity: a.porosity ?? 0.37,
    underlayer: { grading: under, Dn50: DnU, thickness: 2 * DnU },
    perSquareMetre: { volume: t, tonnes: t * (1 - (a.porosity ?? 0.37)) * a.rhoR / 1000 },
    waves: wp, warnings,
  };
}

/**
 * Accropode (I or II) design.
 * a = { Hs, Tp, h, cot, rhoC, rhoW, unit: "accropode1"|"accropode2", section: "trunk"|"head", seabedSlope }
 */
export function accropode(a) {
  const c = COEFFS[a.unit || "accropode1"];
  const D = a.rhoC / a.rhoW - 1;
  const KD = a.section === "head" ? c.head : c.trunk;
  // CLI's design stability numbers (2.7 for Accropode, 2.8 for Accropode II) are
  // Hudson with these KD at a 4:3 slope, and CLI applies them unchanged from 4:3
  // to 3:2, so the slope is not allowed to reduce the unit size.
  const Ns = Math.cbrt(KD * 4 / 3);
  const Dn = a.Hs / (D * Ns);
  const V = Dn ** 3;
  const size = UNIT_SIZES.find((s) => s >= V) || null;
  const Vd = size || V;
  const Dd = Math.cbrt(Vd);
  const Hu = Math.cbrt(Vd / c.ks);
  const T = c.kDelta * Dd;
  const units100 = 100 * c.phi / (Dd * Dd);
  const under = underlayerFor(Vd * a.rhoC);
  const DnU = under ? Math.cbrt((under.mem[0] + under.mem[1]) / 2 / 2650) : Math.cbrt(Vd * a.rhoC / 10 / 2650);
  const warnings = [];
  if (a.cot < 4 / 3 - 0.005) warnings.push("Slope steeper than 4:3: outside CLI's range for interlocking units.");
  if (a.cot > 1.5 + 1e-6) warnings.push("Slope flatter than 3:2: interlocking units lose interlock on gentle slopes (CLI range 4:3 to 3:2).");
  if ((a.seabedSlope ?? 0) > 0.03) warnings.push("Seabed steeper than 3%: CLI coefficients do not apply as given; ask CLI for a reduced KD.");
  if (a.h && a.Hs / a.h > 0.6) warnings.push("Depth-limited breaking waves at the toe: check with CLI for breaking-wave coefficients.");
  if (!size) warnings.push("Required volume is above the listed unit sizes.");
  return {
    kind: a.unit || "accropode1", D, KD, Ns, Dn, V, size: Vd, DnDesign: Dd, height: Hu, thickness: T,
    layers: 1, mass: Vd * a.rhoC / 1000, units100,
    perSquareMetre: { volume: T, units: units100 / 100, concrete: units100 / 100 * Vd },
    underlayer: { grading: under, Dn50: DnU, thickness: 2 * DnU },
    interlock: {
      slopeOk: a.cot >= 4 / 3 - 0.005 && a.cot <= 1.5 + 0.005,
      placement: "Single layer, each unit keyed against two units below; random attitude, no two flat faces parallel. Place to the CLI grid for the packing density above.",
    },
    warnings, src: c.src,
  };
}

/** Toe rock (Van der Meer 1998). ht = water depth above the toe, h = depth at the toe. */
export function toe(a) {
  const D = a.rhoR / a.rhoW - 1;
  const r = Math.min(0.9, Math.max(0.4, a.ht / a.h));
  const Nod = a.Nod ?? 0.5;
  const Ns = (2 + 6.2 * r ** 2.7) * Nod ** 0.15;
  const Dn = a.Hs / (D * Ns);
  const M = a.rhoR * Dn ** 3;
  const grading = gradingFor(M);
  const warnings = [];
  if (a.ht / a.h < 0.4 || a.ht / a.h > 0.9) warnings.push("Toe depth ratio ht/h outside 0.4-0.9: the formula is applied at the nearest limit.");
  return { Ns, Dn50: Dn, M50: M, grading, Nod, ratio: a.ht / a.h, warnings };
}

/** Run-up exceeded by 2% of waves (EurOtop 2018). */
export function runup(a) {
  const { xi10 } = waveParams(a);
  const gf = a.gammaF ?? 0.55, gb = a.gammaB ?? 1, gbeta = a.gammaBeta ?? 1;
  const gfs = xi10 > 1.8 ? Math.min(1, gf + (xi10 - 1.8) * (1 - gf) / 8.2) : gf;
  const r1 = 1.65 * gb * gf * gbeta * xi10;
  const r2 = 1.0 * gfs * gbeta * (4 - 1.5 / Math.sqrt(gb * xi10));
  const ratio = Math.max(0, Math.min(r1, r2));
  return { Ru2: ratio * a.Hs, ratio, xi10, gammaF: gf };
}

/** Mean overtopping discharge (l/s per m) for a crest freeboard Rc (EurOtop 2018). */
export function overtopping(a) {
  const gf = a.gammaF ?? 0.55, gbeta = a.gammaBeta ?? 1;
  const q = Math.sqrt(G * a.Hs ** 3) * 0.09 * Math.exp(-Math.pow(1.5 * Math.max(0, a.Rc) / (a.Hs * gf * gbeta), 1.3));
  return { q: q * 1000, Rc: a.Rc };
}

/** Veneer check: the armour layer sliding on its underlayer (infinite slope, dry). */
export function veneer(cot, phiInterface) {
  const F = Math.tan(phiInterface * Math.PI / 180) * cot;
  return { F, phi: phiInterface };
}
