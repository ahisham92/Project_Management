// Verification: GeoProMax against closed-form solutions and hand calculations.
// The Verification tab runs these in the browser and CI runs them in Node.

import { boussinesqCorner, westergaardCorner, buildRects, deltaSigma } from "./stress.js";
import { degreeOfConsolidation, computePoint, settlementAt } from "./settlement.js";

// Numerical integration of a point-load solution over a rectangle (midpoint rule).
function integrate(x1, x2, y1, y2, n, kernel) {
  let s = 0;
  const dx = (x2 - x1) / n, dy = (y2 - y1) / n;
  for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) s += kernel(x1 + dx * (i + 0.5), y1 + dy * (j + 0.5)) * dx * dy;
  return s;
}

function osterbergHalf(a, b, z, q) {
  const a1 = Math.atan((a + b) / z) - Math.atan(b / z), a2 = Math.atan(b / z);
  return (q / Math.PI) * (((a + b) / a) * (a1 + a2) - (b / a) * a2);
}

const wide = (q) => ({ type: "rect", x: 0, y: 0, B: 1e5, L: 1e5, q });
const clay = (o = {}) => ({ name: "Clay", thickness: 4, gamma: 18, gammaSat: 18, E: 0, nu: 0.3, consolidating: true,
  Cc: 0.3, Cr: 0.05, e0: 1.0, OCR: 1, POP: 0, cv: 2, Ca: 0.01, drainage: "double", ...o });

/** Every check: {group, name, reference, expected, got, tol, unit, pass}. */
export function runChecks() {
  const out = [];
  const add = (group, name, reference, expected, got, tol, unit = "") =>
    out.push({ group, name, reference, expected, got, tol, unit, pass: Math.abs(got - expected) <= tol });

  // --- stress distribution
  add("Stress", "Corner of a rectangle, m = n = 1", "Newmark (1935) chart: 0.1752", 0.1752, boussinesqCorner(1, 1, 1), 5e-4);
  add("Stress", "Corner of a rectangle, m = n = 2", "Newmark (1935) chart: 0.2325", 0.2325, boussinesqCorner(2, 2, 1), 5e-4);
  add("Stress", "Corner of a rectangle, m = n = 0.5", "Newmark (1935) chart: 0.0840", 0.0840, boussinesqCorner(0.5, 0.5, 1), 5e-4);
  add("Stress", "Centre of a 2 × 2 m square at 2 m, q = 100", "4 × 0.0840 × 100", 33.61, deltaSigma(buildRects([{ type: "rect", x: 0, y: 0, B: 2, L: 2, q: 100 }]), 0, 0, 2), 0.05, "kPa");
  {
    const px = 5, py = 1, z = 3;
    const ref = integrate(-2, 2, -3, 3, 400, (x, y) => {
      const R2 = (x - px) ** 2 + (y - py) ** 2 + z * z;
      return (100 * 3 * z ** 3) / (2 * Math.PI * R2 ** 2.5);
    });
    add("Stress", "Point outside a 4 × 6 m rectangle", "Boussinesq point load, integrated", ref, deltaSigma(buildRects([{ type: "rect", x: 0, y: 0, B: 4, L: 6, q: 100 }]), px, py, z), 0.02, "kPa");
  }
  {
    const c = buildRects([{ type: "circle", x: 0, y: 0, R: 3, q: 100 }]);
    add("Stress", "Centre of a circle, z = R", "q[1 − (1 + (R/z)²)^−1.5]", 100 * (1 - 0.5 ** 1.5), deltaSigma(c, 0, 0, 3), 0.3, "kPa");
    add("Stress", "Centre of a circle, z = 2R", "q[1 − (1 + (R/z)²)^−1.5]", 100 * (1 - 0.8 ** 1.5), deltaSigma(c, 0, 0, 6), 0.3, "kPa");
  }
  {
    const e = buildRects([{ type: "embankment", x: 0, y: 0, crest: 10, slope: 6, H: 4, gamma: 20, L: 4000, axis: "y" }]);
    add("Stress", "Centre of a long embankment at 5 m", "Osterberg (1957)", 2 * osterbergHalf(6, 5, 5, 80), deltaSigma(e, 0, 0, 5), 0.4, "kPa");
  }
  for (const nu of [0, 0.3]) {
    const eta2 = (1 - 2 * nu) / (2 - 2 * nu), eta = Math.sqrt(eta2);
    const ref = integrate(0, 1, 0, 1, 500, (x, y) => eta / (2 * Math.PI * (eta2 + x * x + y * y) ** 1.5));
    add("Stress", `Westergaard corner, m = n = 1, ν = ${nu}`, "Westergaard point load, integrated", ref, westergaardCorner(1, 1, 1, nu), 3e-4);
  }

  // --- consolidation
  add("Consolidation", "U at Tv = 0.197", "Terzaghi: 50%", 0.5, degreeOfConsolidation(0.197), 2e-3);
  add("Consolidation", "U at Tv = 0.848", "Terzaghi: 90%", 0.9, degreeOfConsolidation(0.848), 2e-3);
  {
    const p = { waterTable: 0, subLayers: 1, layers: [clay()], loads: [wide(50)] };
    const s0 = 2 * (18 - 9.81);
    add("Settlement", "Normally consolidated clay, 4 m, Δσ = 50 kPa", "Cc·H/(1+e0)·log(σ'f/σ'0)", 0.3 * 2 * Math.log10((s0 + 50) / s0), computePoint(p, 0, 0).primary, 1e-4, "m");
    p.layers = [clay({ OCR: 2 })];
    const r = computePoint(p, 0, 0);
    add("Settlement", "Over-consolidated clay, OCR = 2", "Cr then Cc past σ'p", 2 * (0.05 * Math.log10(2) + 0.3 * Math.log10((s0 + 50) / (2 * s0))), r.primary, 1e-4, "m");
    add("Settlement", "Primary consolidation at t50 (Hdr = 2 m, cv = 2 m²/yr)", "half the final settlement", 0.5 * r.primary, settlementAt(r, (0.197 * 4) / 2).primary, 1e-3, "m");
    p.layers = [clay({ OCR: 10 })];
    add("Settlement", "Heavily over-consolidated clay stays on Cr", "Cr·H/(1+e0)·log(σ'f/σ'0)", 0.05 * 2 * Math.log10((s0 + 50) / s0), computePoint(p, 0, 0).primary, 1e-4, "m");
  }
  {
    const p = { waterTable: 10, layers: [{ name: "Sand", thickness: 5, gamma: 19, gammaSat: 20, E: 20000, nu: 0, consolidating: false }], loads: [wide(100)] };
    add("Settlement", "Elastic layer under a wide load (ν = 0)", "Δσ·H / E", 0.025, computePoint(p, 0, 0).immediate, 1e-5, "m");
    p.layers[0].nu = 0.3;
    add("Settlement", "Elastic layer under a wide load (ν = 0.3)", "Δσ·H / M, M = E(1−ν)/((1+ν)(1−2ν))", 100 * 5 / (20000 * 0.7 / (1.3 * 0.4)), computePoint(p, 0, 0).immediate, 1e-5, "m");
  }
  {
    // Creep: after t95 the settlement grows by Cα/(1+ep)·H per log cycle.
    const p = { waterTable: 0, subLayers: 1, layers: [clay({ cv: 10 })], loads: [wide(50)] };
    const r = computePoint(p, 0, 0);
    const t95 = (1.129 * 4) / 10;
    const ep = 1 - r.rows[0].de;
    add("Settlement", "Secondary compression, one log cycle after t95", "Cα·H/(1+ep)", (0.01 * 4) / (1 + ep), settlementAt(r, 10 * t95).secondary, 2e-4, "m");
  }
  {
    // Two stages on a wide area add up to one load of their sum.
    const one = { waterTable: 0, subLayers: 4, layers: [clay()], loads: [wide(60)] };
    const two = { ...one, loads: [{ ...wide(30), t0: 0 }, { ...wide(30), t0: 2 }] };
    add("Settlement", "Two stages end where one load of their sum does", "same final σ'", computePoint(one, 0, 0).primary, settlementAt(computePoint(two, 0, 0), 500).primary, 1e-6, "m");
  }
  return out;
}
