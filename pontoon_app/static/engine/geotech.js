// The ground around a guide pile.
//   bromsCohesive / bromsCohesionless   ultimate lateral resistance of a free-head pile
//                                       (Broms 1964a, 1964b), short or long, whichever governs
//   requiredEmbedment                   shortest embedment with φg·Hu ≥ H* (AS 2159 Cl 4.3)
//   pileResponse                        elastic pile on a Winkler subgrade (linear nh for sand,
//                                       constant k for clay) for the design moments, the head
//                                       deflection and the pile's stiffness at the pontoon
// kN, m, kPa.

import { beamWinkler } from "./fe.js";

const kp = (phi) => Math.tan(Math.PI / 4 + (phi * Math.PI) / 360) ** 2;

/**
 * Free-head pile in cohesionless soil (Broms 1964b). e is the height of the load above the
 * ground, L the embedment, D the diameter, gs the submerged unit weight, phi in degrees, My the
 * pile's moment capacity (kN·m). Returns the ultimate lateral load and the failure mode.
 *   short:  Hu = 0.5 γ' D L³ Kp / (e + L)
 *   long:   My = Hu (e + 0.544 √(Hu / (γ' D Kp)))
 */
export function bromsCohesionless({ e, L, D, gs, phi, My }) {
  const Kp = kp(phi);
  const Hs = (0.5 * gs * D * L ** 3 * Kp) / (e + L);
  // long pile: solve for Hu (monotonic in Hu)
  const g = (H) => H * (e + (2 / 3) * Math.sqrt(2 / 3) * Math.sqrt(H / (gs * D * Kp))) - My; // 0.5443
  let lo = 0, hi = My / Math.max(e, 1e-6) + 1e6;
  for (let i = 0; i < 200; i++) { const m = (lo + hi) / 2; if (g(m) < 0) lo = m; else hi = m; }
  const Hl = (lo + hi) / 2;
  const f = Math.sqrt(2 / 3) * Math.sqrt(Hl / (gs * D * Kp)); // depth to the maximum moment (long pile)
  return Hs <= Hl ? { Hu: Hs, mode: "short (soil fails)", Kp, Hs, Hl } : { Hu: Hl, mode: "long (pile yields)", Kp, Hs, Hl, f };
}

/**
 * Free-head pile in cohesive soil (Broms 1964a): no resistance over the top 1.5D, then 9 su D.
 *   short:  L = 1.5D + f + g,  f = Hu / (9 su D),  Hu (e + 1.5D + 0.5 f) = 2.25 D g² su
 *   long:   My = Hu (e + 1.5D + 0.5 f)
 */
export function bromsCohesive({ e, L, D, su, My }) {
  const pu = 9 * su * D;
  // short pile: solve the two equations for Hu with f = Hu/pu, g = L − 1.5D − f
  const res = (H) => { const f = H / pu, gg = L - 1.5 * D - f; return gg <= 0 ? -1 : 2.25 * D * gg * gg * su - H * (e + 1.5 * D + 0.5 * f); };
  let lo = 0, hi = pu * Math.max(0, L - 1.5 * D);
  for (let i = 0; i < 200; i++) { const m = (lo + hi) / 2; if (res(m) > 0) lo = m; else hi = m; }
  const Hs = (lo + hi) / 2;
  // long pile: Hu (e + 1.5D + 0.5 Hu/pu) = My → quadratic
  const a = 0.5 / pu, b = e + 1.5 * D, c = -My;
  const Hl = (-b + Math.sqrt(b * b - 4 * a * c)) / (2 * a);
  return Hs <= Hl ? { Hu: Hs, mode: "short (soil fails)", Hs, Hl } : { Hu: Hl, mode: "long (pile yields)", Hs, Hl, f: 1.5 * D + Hl / pu };
}

/**
 * Broms for the soil given. With phiG the soil resistance in the mechanism is factored (su·φg
 * in clay, the passive pressure 3Kpγ'z·φg in sand) and My should be the design moment φMs, so
 * the result is the design lateral resistance Rd (AS 2159 Cl 4.3.1 applied inside the mechanism).
 */
export function broms(soil, args, phiG = 1) {
  if (soil.type === "clay") return bromsCohesive({ ...args, su: +soil.su * phiG });
  // scaling γ' by φg scales the passive pressure 3Kpγ'Dz exactly
  const r = bromsCohesionless({ ...args, gs: +soil.gamma * phiG, phi: +soil.phi });
  return r;
}

/** Shortest embedment L with the design resistance Rd(L) ≥ H* (soil factored by φg, My = φMs). */
export function requiredEmbedment(soil, { e, D, My, phiG, Hstar }) {
  const ok = (L) => broms(soil, { e, L, D, My }, phiG).Hu >= Hstar;
  let hi = 2;
  while (!ok(hi) && hi < 80) hi *= 1.5;
  if (!ok(hi)) return { L: null, reason: "Even a long pile cannot carry the load: the pile yields first. Use a stronger section." };
  let lo = 0.1;
  for (let i = 0; i < 60; i++) { const m = (lo + hi) / 2; if (ok(m)) hi = m; else lo = m; }
  return { L: Math.ceil(hi * 20) / 20 };
}

/** Typical coefficients of horizontal subgrade reaction (Terzaghi 1955; Davisson 1970). */
export const SUBGRADE = {
  nh: { loose: 1400, medium: 4500, dense: 11000 }, // kN/m³, submerged sand (k = nh z)
  clay: (su) => 67 * su,                             // kN/m² per m length (k = 67 su, Davisson)
};
export const sandDensity = (phi) => (phi < 30 ? "loose" : phi < 36 ? "medium" : "dense");

/**
 * Elastic pile: cantilever of free length e above the ground, embedded L, loaded by H at the
 * head (x = 0). Subgrade starts below any scour. Returns moments along the pile, the maximum
 * moment and its depth, the head deflection and the head stiffness H/δ.
 */
export function pileResponse({ e, L, EI, soil, H, D, q = 0, qFrom = 0, qTo = 0 }) {
  const total = e + L;
  const k = (x) => {
    const z = x - e; // depth below the (scoured) ground
    if (z <= 0) return 0;
    if (soil.type === "clay") return SUBGRADE.clay(+soil.su);
    return SUBGRADE.nh[sandDensity(+soil.phi)] * z;
  };
  // the toe needs a tiny restraint against rigid rotation for very short piles in sand; the
  // springs already restrain it once L > 0, so no support is added.
  const n = Math.min(160, Math.max(40, Math.round(total / 0.25)));
  const r = beamWinkler({ L: total, EI, k, n, nodesAt: [e, qFrom, qTo].filter((x) => x > 0 && x < total) }, [{ x: 0, P: H }], q ? (x) => (x >= qFrom && x <= qTo ? q : 0) : null);
  let iMax = 0;
  r.M.forEach((m, i) => { if (Math.abs(m) > Math.abs(r.M[iMax])) iMax = i; });
  const delta = r.w[0];
  // depth of the point of zero deflection below ground ("fixity" as commonly reported)
  return {
    x: r.x, M: r.M, V: r.V, w: r.w,
    Mmax: Math.abs(r.M[iMax]), zMax: r.x[iMax] - e, delta, stiffness: delta ? (H + q * (qTo - qFrom)) / delta : Infinity,
    rigid: L < 2 * relStiffness(EI, soil, D),
  };
}

/** Relative stiffness length T = (EI/nh)^(1/5) for sand, R = (EI/k)^(1/4) for clay. */
export function relStiffness(EI, soil) {
  if (soil.type === "clay") return (EI / SUBGRADE.clay(+soil.su)) ** 0.25;
  return (EI / SUBGRADE.nh[sandDensity(+soil.phi)]) ** 0.2;
}
