// Verification: GeoProMax against closed-form solutions and hand calculations.
// The Verification tab runs these in the browser and CI runs them in Node.

import { boussinesqCorner, westergaardCorner, buildRects, deltaSigma, equivalentRaft } from "./stress.js";
import { factors, netUltimate, bearingCheck, pileCapacity, alphaClay } from "./bearing.js";
import { degreeOfConsolidation, computePoint, computeConverged, settlementAt, radialDegree, layerDegree, foundationSummary } from "./settlement.js";

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
  {
    // a footing turned 30°, against the point-load solution integrated in its own axes
    const a = Math.PI / 6, px = 3, py = 2, z = 2.5;
    const u0 = px * Math.cos(a) + py * Math.sin(a), v0 = -px * Math.sin(a) + py * Math.cos(a);
    const ref = integrate(-2, 2, -3, 3, 400, (x, y) => (100 * 3 * z ** 3) / (2 * Math.PI * ((x - u0) ** 2 + (y - v0) ** 2 + z * z) ** 2.5));
    add("Stress", "Footing turned 30°, point off its centre", "Boussinesq point load, integrated", ref, deltaSigma(buildRects([{ type: "rect", x: 0, y: 0, B: 4, L: 6, q: 100, angle: 30 }]), px, py, z), 0.25, "kPa");
  }
  {
    const ring = buildRects([{ type: "ring", x: 0, y: 0, R: 5, Ri: 3, q: 100 }]);
    const axis = (R, z) => 1 - (1 + (R / z) ** 2) ** -1.5;
    add("Stress", "Centre of a ring, radii 3 and 5 m, at 4 m", "outer circle less inner circle", 100 * (axis(5, 4) - axis(3, 4)), deltaSigma(ring, 0, 0, 4), 0.3, "kPa");
    const L = buildRects([{ type: "polygon", q: 100, pts: "0,0\n4,0\n4,2\n2,2\n2,4\n0,4" }]);
    const parts = buildRects([{ type: "rect", x: 2, y: 1, B: 4, L: 2, q: 100 }, { type: "rect", x: 1, y: 3, B: 2, L: 2, q: 100 }]);
    add("Stress", "L-shaped polygon", "the two rectangles it is made of", deltaSigma(parts, 3, 3, 2), deltaSigma(L, 3, 3, 2), 0.05, "kPa");
  }
  {
    // a footing founded 2 m down acts on the soil below it as a surface load does
    const deep = buildRects([{ type: "rect", x: 0, y: 0, B: 2, L: 2, q: 100, Df: 2 }]);
    add("Stress", "Footing founded at 2 m, stress 2 m below it", "4 × 0.0840 × 100", 33.61, deltaSigma(deep, 0, 0, 4), 0.05, "kPa");
    add("Stress", "No stress above the founding level", "0", 0, deltaSigma(deep, 0, 0, 1.5), 1e-9, "kPa");
    const net = buildRects([{ type: "rect", x: 0, y: 0, B: 2, L: 2, q: 100, Df: 2, net: true }], (zz) => 18 * zz);
    add("Stress", "Net pressure takes off the soil dug out", "100 − 18 × 2 = 64 kPa", 0.3361 * 64, deltaSigma(net, 0, 0, 4), 0.05, "kPa");
    const pad = buildRects([{ type: "pad", x: 0, y: 0, B: 2, L: 2, P: 400 }]);
    add("Stress", "Pad footing: 400 kN on 2 × 2 m", "q = P / (B·L) = 100 kPa", 33.61, deltaSigma(pad, 0, 0, 2), 0.05, "kPa");
    const strip = buildRects([{ type: "strip", x: 0, y: 0, B: 2, L: 2000, w: 200 }]);
    add("Stress", "Strip footing, 200 kN/m on 2 m, at 2 m", "q/π·(α + sin α), α = 2·atan(B/2z)", (100 / Math.PI) * (2 * Math.atan(0.5) + Math.sin(2 * Math.atan(0.5))), deltaSigma(strip, 0, 0, 2), 0.05, "kPa");
  }
  {
    const g = { type: "pilegroup", B: 6, L: 9, Lp: 15, pileType: "friction", Q: 18000, Df: 1.5 };
    const e = equivalentRaft(g);
    add("Piles", "Equivalent raft depth, friction piles", "Df + 2/3 of the pile length", 11.5, e.zf, 1e-9, "m");
    add("Piles", "Equivalent raft width, spread at 1 in 4", "B + 2 × (10 / 4)", 11, e.B, 1e-9, "m");
    add("Piles", "Pressure on the equivalent raft", "Q / (B'·L') = 18000 / (11 × 14)", 18000 / 154, buildRects([g])[0].q, 1e-6, "kPa");
    add("Piles", "End-bearing piles: raft at the toe, no spread", "Df + Lp", 16.5, equivalentRaft({ ...g, pileType: "end" }).zf, 1e-9, "m");
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
  {
    // mv method: s = mv·Δσ·H
    const p = { waterTable: 0, subLayers: 4, layers: [clay({ model: "mv", mv: 0.5 })], loads: [wide(80)] };
    add("Settlement", "mv method: 0.5 m²/MN, 80 kPa, 4 m", "mv·Δσ·H", 0.5e-3 * 80 * 4, computePoint(p, 0, 0).primary, 1e-6, "m");
    // stiffness growing with depth: s = (q/k)·ln(1 + k·H/E0)
    const q = { waterTable: 20, subLayers: 64, layers: [{ name: "Sand", thickness: 10, gamma: 18, gammaSat: 20, E: 10000, Einc: 4000, nu: 0, consolidating: false }], loads: [wide(100)] };
    add("Settlement", "Stiffness growing with depth", "(q/k)·ln(1 + k·H/E0)", (100 / 4000) * Math.log(5), computePoint(q, 0, 0).immediate, 1e-5, "m");
    // heave on unloading follows Cr
    const u = { waterTable: 0, subLayers: 1, layers: [clay({ thickness: 4 }), clay({ thickness: 4 })], loads: [wide(-10)] };
    const s0 = 2 * (18 - 9.81);
    add("Settlement", "Heave of the top layer when 10 kPa is taken off", "Cr·H/(1+e0)·log(σ'f/σ'0)", 0.05 * 2 * Math.log10((s0 - 10) / s0), computePoint(u, 0, 0).layers[0].primary, 1e-6, "m");
  }
  {
    const d = { on: true, spacing: 1.5, pattern: "tri", dw: 0.066, ch: 3 };
    const de = 1.05 * 1.5, F = Math.log(de / 0.066) - 0.75;
    add("Consolidation", "Wick drains at 1.5 m, triangular, after 0.5 yr", "1 − exp(−8·ch·t / (de²·F)), Hansbo", 1 - Math.exp((-8 * 3 * 0.5) / (de * de * F)), radialDegree(d, 0.5), 1e-9);
    const l = clay({ thickness: 10, cv: 1, drains: d });
    const Uv = degreeOfConsolidation((1 * 0.5) / 25);
    add("Consolidation", "Drains and vertical flow together", "1 − (1 − Uv)(1 − Ur), Carrillo", 1 - (1 - Uv) * (1 - radialDegree(d, 0.5)), layerDegree(l, 0.5), 1e-9);
  }
  {
    // refining the sub-layers converges on the fine answer
    const p = { waterTable: 1, layers: [clay({ thickness: 12 })], loads: [{ type: "rect", x: 0, y: 0, B: 6, L: 6, q: 120 }] };
    const fine = computePoint(p, 0, 0, { subLayers: 400 }), auto = computeConverged(p, 0, 0);
    add("Convergence", `Sub-layers refined automatically (stopped at ${auto.subLayers})`, "the same layer cut into 400", fine.primary, auto.primary, 0.01 * fine.primary, "m");
  }
  {
    // a rigid square footing: 0.74 of the half-width is where it settles as a flexible one does
    const p = { waterTable: 20, subLayers: 40, layers: [{ name: "Deep elastic soil", thickness: 200, gamma: 18, gammaSat: 20, E: 20000, nu: 0.3, consolidating: false }],
      loads: [{ type: "rect", x: 0, y: 0, B: 4, L: 4, q: 100, rigid: true }] };
    const f = foundationSummary(p, 1, { subLayers: 200 })[0];
    add("Foundations", "Rigid square footing against its flexible centre", "rigid ≈ 0.80 × centre (0.82/1.12, Bowles)", 0.8, f.rigid / f.centre, 0.05);
  }
  {
    // bearing capacity
    const f = factors(30);
    add("Bearing", "Nq at φ = 30°", "e^(π·tanφ)·tan²(45° + φ/2): 18.40", 18.40, f.Nq, 0.01);
    add("Bearing", "Nc at φ = 30°", "(Nq − 1)·cotφ: 30.14", 30.14, f.Nc, 0.01);
    add("Bearing", "Nγ at φ = 30°", "2·(Nq + 1)·tanφ, Vesic (1973): 22.40", 22.40, f.Ng, 0.01);
    add("Bearing", "Long strip on clay at the surface, su = 50 kPa", "(π + 2)·su, Prandtl", 257.08, netUltimate({ su: 50 }, 1, 1e6, 0, 0, 8).qnet, 0.01, "kPa");
    // 2 m square footing 1 m deep on dry sand, φ = 30°, γ = 18: q·Nq·sq·dq + ½·γ·B·Nγ·sγ − q
    const hand = 18 * 18.4011 * 1.57735 * 1.14434 + 0.5 * 18 * 2 * 22.4025 * 0.6 - 18;
    const p = { waterTable: 50, layers: [{ name: "Sand", thickness: 20, gamma: 18, gammaSat: 20, E: 30000, nu: 0.3, consolidating: false, phi: 30, c: 0 }] };
    const b = bearingCheck(p, { type: "pad", x: 0, y: 0, B: 2, L: 2, P: 1200, Df: 1 });
    add("Bearing", "Square footing on sand: net ultimate pressure", "q·Nq·sq·dq + ½·γ·B·Nγ·sγ − q by hand", hand, b.qult, 0.5, "kPa");
    add("Bearing", "The same footing: safety factor under 1200 kN", "net ultimate / (P/B² − γ·D)", hand / (300 - 18), b.fos, 0.005);
  }
  {
    // piles: a 0.6 m bored pile, 10 m long from the surface
    const d = 0.6, L = 10, per = Math.PI * d, area = (Math.PI * d * d) / 4;
    // clay with su = 80 kPa all the way, γ = 18, dry: α changes with depth as su/σ'v falls
    const cl = { waterTable: 50, layers: [{ name: "Clay", thickness: 30, gamma: 18, gammaSat: 18, consolidating: true, su: 80, phi: 0, c: 0 }] };
    let shaft = 0;
    for (let i = 0; i < 2000; i++) { const z = (L * (i + 0.5)) / 2000; shaft += alphaClay(80, 18 * z) * 80 * per * (L / 2000); }
    const a = pileCapacity(cl, 0, L, d, "bored");
    add("Piles", "Shaft of a bored pile in clay, su = 80 kPa", "Σ α·su·π·d·Δz, α from su/σ'v (API)", shaft, a.shaft, 0.005 * shaft, "kN");
    add("Piles", "Toe of the same pile", "9·su·π·d²/4", 9 * 80 * area, a.base, 0.01, "kN");
    // dry sand, φ' = 35°: fs = 0.7·σ'v·tan35°, limited to 115 kPa; qb = half of min(50·σ'v, 12 MPa) for a bored pile
    const sd = { waterTable: 50, layers: [{ name: "Sand", thickness: 30, gamma: 18, gammaSat: 20, consolidating: false, phi: 35, c: 0 }] };
    const b = pileCapacity(sd, 0, L, d, "bored");
    add("Piles", "Shaft of a bored pile in sand, φ' = 35°", "½·K·γ·L²·tanδ·π·d, K = 0.7", 0.5 * 0.7 * 18 * L * L * Math.tan((35 * Math.PI) / 180) * per, b.shaft, 0.005 * b.shaft, "kN");
    add("Piles", "Toe of the same pile", "½·Nq·σ'v·π·d²/4, Nq = 50", 0.5 * 50 * 180 * area, b.base, 0.01, "kN");
  }
  return out;
}
