// Verification: every part of the engine against an independent closed-form answer.
// The Verification tab runs these in the browser; CI runs the same file in Node.

import { beamWinkler, modes } from "./fe.js";
import { initial, equilibrium, wallSidedGZ, macagnoKt, waveNumber, froudeKrylovX, G } from "./hydro.js";
import { steelCHS, chsProps, concreteSection } from "./members.js";
import { bromsCohesionless, bromsCohesive, pileResponse } from "./geotech.js";
import { regionalSpeed, phiGb, spectralShape, kpOf, minDisplacement, berthingSpeed, gangwayWidth, walkwayWidth } from "./codes.js";
import { catenary, boltCapacity, shs } from "./extras.js";

const rel = (a, b) => Math.abs(a - b) / Math.max(Math.abs(b), 1e-12);

export const CHECKS = [
  {
    name: "Simply supported beam, UDL", ref: "M = qL²/8, δ = 5qL⁴/384EI",
    run() {
      const q = 2, L = 10, EI = 1000;
      const r = beamWinkler({ L, EI, n: 20, supports: [{ x: 0, kind: "pin" }, { x: L, kind: "pin" }] }, [], q);
      const i = r.x.findIndex((x) => Math.abs(x - 5) < 1e-9);
      return [[r.M[i], (q * L * L) / 8, "M (kN·m)"], [r.w[i], (5 * q * L ** 4) / (384 * EI), "δ (m)"]];
    }, tol: 1e-9,
  },
  {
    name: "Cantilever, tip load", ref: "M = PL, δ = PL³/3EI",
    run() {
      const r = beamWinkler({ L: 5, EI: 2000, n: 10, supports: [{ x: 0, kind: "fix" }] }, [{ x: 5, P: 10 }]);
      return [[-r.M[0], 50, "M (kN·m)"], [r.w.at(-1), (10 * 125) / (3 * 2000), "δ (m)"]];
    }, tol: 1e-9,
  },
  {
    name: "Long beam on the water, point load", ref: "Hetényi: w = Pβ/2k, M = P/4β",
    run() {
      const EI = 5000, k = 2000, P = 10, beta = (k / (4 * EI)) ** 0.25;
      const r = beamWinkler({ L: 60, EI, k, n: 240 }, [{ x: 30, P }]);
      const i = r.x.findIndex((x) => Math.abs(x - 30) < 1e-9);
      return [[r.w[i], (P * beta) / (2 * k), "w (m)"], [r.M[i], P / (4 * beta), "M (kN·m)"]];
    }, tol: 1e-5,
  },
  {
    name: "Free-free beam on the water: frequencies", ref: "ω² = (EI(βL)⁴/L⁴ + k)/m, βL = 4.7300, 7.8532",
    run() {
      const L = 20, EI = 1e5, k = 50, m = 2, ms = modes({ L, EI, k, m, n: 40 }, 4);
      const w = (bl) => Math.sqrt((EI * (bl / L) ** 4 + k) / m);
      return [[ms[0].omega, Math.sqrt(k / m), "heave ω"], [ms[1].omega, Math.sqrt(k / m), "pitch ω"], [ms[2].omega, w(4.730041), "1st bending ω"], [ms[3].omega, w(7.853205), "2nd bending ω"]];
    }, tol: 1e-5,
  },
  {
    name: "Box pontoon: draft and GM", ref: "T = w/γB, GM = T/2 + B²/12T − KG",
    run() {
      const B = 2.4, gw = 10.06, w = 9, KG = 0.45, r = initial([{ y0: -B / 2, y1: B / 2, z0: 0, z1: 0.8 }], w, KG, gw);
      const T = w / gw / B;
      return [[r.T, T, "T (m)"], [r.GM, T / 2 + (B * B) / (12 * T) - KG, "GM (m)"]];
    }, tol: 1e-9,
  },
  {
    name: "Heeled box: exact equilibrium = wall-sided formula", ref: "GZ = sin θ (GM + ½BM tan²θ) = e cos θ",
    run() {
      const B = 2.4, D = 0.8, gw = 10.06, w = 9, KG = 0.45, e = 0.08, rects = [{ y0: -B / 2, y1: B / 2, z0: 0, z1: D }];
      const ini = initial(rects, w, KG, gw), eq = equilibrium(rects, w, e, KG, gw);
      return [[wallSidedGZ(ini.GM, ini.BM, eq.theta), e * Math.cos(eq.theta), "GZ (m)"]];
    }, tol: 1e-8,
  },
  {
    name: "Linear wave dispersion", ref: "ω² = gk tanh kh; deep water L = gT²/2π",
    run() {
      const T = 4, k = waveNumber(T, 200), w = (2 * Math.PI) / T, kh = waveNumber(T, 3);
      return [[(2 * Math.PI) / k, (G * T * T) / (2 * Math.PI), "deep L (m)"], [G * kh * Math.tanh(kh * 3), w * w, "ω² at h = 3 m"]];
    }, tol: 1e-9,
  },
  {
    name: "Floating breakwater transmission", ref: "Macagno (1953), Kt → 1 as B, T → 0",
    run() {
      const r = macagnoKt(3, 5, 1e-6, 1e-6), r2 = macagnoKt(3, 5, 4, 1.5);
      const k = r2.k, a = (k * 4 * Math.sinh(k * 5)) / (2 * Math.cosh(k * (5 - 1.5)));
      return [[r.Kt, 1, "Kt (thin)"], [r2.Kt, 1 / Math.sqrt(1 + a * a), "Kt (B 4, T 1.5)"]];
    }, tol: 1e-9,
  },
  {
    name: "Froude–Krylov force, shallow limit", ref: "kB, kh → 0: F → ρg H T · kB/2 · (1 − ...) ≈ ρgH·(kB/2)·T",
    run() {
      const gw = 10.06, H = 0.5, h = 20, B = 0.01, T = 0.5, Tp = 20;
      const k = waveNumber(Tp, h), F = froudeKrylovX(gw, H, Tp, h, B, T);
      // exact integral for small B: ρgH (kB/2)(sinh kh − sinh k(h−T))/(k cosh kh)
      const ex = (gw * H * (k * B) / 2 * (Math.sinh(k * h) - Math.sinh(k * (h - T)))) / (k * Math.cosh(k * h));
      return [[F, ex, "F (kN/m)"]];
    }, tol: 1e-6,
  },
  {
    name: "CHS section properties", ref: "A = π(d² − di²)/4, S = (d³ − di³)/6",
    run() {
      const p = chsProps(457, 12.7), di = 457 - 25.4;
      return [[p.A, (Math.PI / 4) * (457 ** 2 - di ** 2), "A (mm²)"], [p.S, (457 ** 3 - di ** 3) / 6, "S (mm³)"], [p.Z, (Math.PI * (457 ** 4 - di ** 4)) / (32 * 457), "Z (mm³)"]];
    }, tol: 1e-12,
  },
  {
    name: "AS 4100 compact CHS: φMs = 0.9 fy S", ref: "Cl 5.2: λs ≤ 50 → Ze = min(S, 1.5Z)",
    run() {
      const s = steelCHS({ d: 323.9, t: 12.7, grade: "C350" }), p = chsProps(323.9, 12.7);
      return [[s.phiMs, (0.9 * 350 * Math.min(p.S, 1.5 * p.Z)) / 1e6, "φMs (kN·m)"], [s.phiVv, (0.9 * 0.36 * 350 * p.A) / 1e3, "φVv (kN)"]];
    }, tol: 1e-12,
  },
  {
    name: "AS 3600 singly reinforced rectangle", ref: "dn = Ast fsy / (α2 f'c γ b); Mu = Ast fsy (d − γdn/2)",
    run() {
      const fc = 32, b = 300, As = 942, d = 450, a2 = 0.85 - 0.0015 * fc, g = 0.97 - 0.0025 * fc;
      const cs = concreteSection({ shape: { kind: "rect", b, h: 500 }, bars: [{ y: -200, As }], fc }).phiMu(0);
      const dn = (As * 500) / (a2 * fc * g * b), Mu = (As * 500 * (d - (g * dn) / 2)) / 1e6;
      return [[cs.dn, dn, "dn (mm)"], [cs.Mu, Mu, "Mu (kN·m)"], [cs.phi, Math.min(0.85, 1.24 - (13 * dn) / d / 12), "φ"]];
    }, tol: 1e-6,
  },
  {
    name: "Broms, short pile in sand", ref: "Hu = 0.5 γ' D L³ Kp / (e + L)",
    run() {
      const Kp = Math.tan(Math.PI / 4 + (30 * Math.PI) / 360) ** 2;
      const r = bromsCohesionless({ e: 2, L: 3, D: 0.5, gs: 9, phi: 30, My: 1e9 });
      return [[r.Hu, (0.5 * 9 * 0.5 * 27 * Kp) / 5, "Hu (kN)"], [Kp, 3, "Kp at 30°"]];
    }, tol: 1e-9,
  },
  {
    name: "Broms, long pile in sand", ref: "pu = 3Kpγ'Dz; at zero shear f: M = H(e + f) − Kpγ'Df³/2 = My",
    run() {
      const My = 500, e = 5, D = 0.5, gs = 9, Kp = 3, r = bromsCohesionless({ e, L: 50, D, gs, phi: 30, My });
      const f = Math.sqrt((2 * r.Hu) / (3 * Kp * gs * D)); // 1.5 Kp γ D f² = H
      return [[r.Hu * (e + f) - (Kp * gs * D * f ** 3) / 2, My, "M at zero shear (kN·m)"]];
    }, tol: 1e-6,
  },
  {
    name: "Broms, piles in clay", ref: "long: My = Hu(e + 1.5D + 0.5f), f = Hu/9suD; short: Hu(e+1.5D+0.5f) = 2.25Dg²su",
    run() {
      const su = 40, D = 0.6, e = 4, My = 600;
      const L = bromsCohesive({ e, L: 40, D, su, My }), f = L.Hu / (9 * su * D);
      const S = bromsCohesive({ e, L: 4, D, su, My: 1e9 }), fs = S.Hu / (9 * su * D), g = 4 - 1.5 * D - fs;
      return [[L.Hu * (e + 1.5 * D + 0.5 * f), My, "long M (kN·m)"], [S.Hu * (e + 1.5 * D + 0.5 * fs), 2.25 * D * g * g * su, "short moment balance"]];
    }, tol: 1e-6,
  },
  {
    name: "Pile on the ground: equilibrium", ref: "Σ soil reaction = H; free head M = 0",
    run() {
      const r = pileResponse({ e: 5, L: 12, EI: 2e5, soil: { type: "clay", su: 30 }, H: 50, D: 0.5 });
      // ∫ k w dx over the embedded part must balance H
      let R = 0;
      for (let i = 0; i < r.x.length - 1; i++) {
        const x0 = r.x[i], x1 = r.x[i + 1];
        if (x0 >= 5) R += 67 * 30 * ((r.w[i] + r.w[i + 1]) / 2) * (x1 - x0);
      }
      return [[R, 50, "Σ reaction (kN)"], [r.M[0], 0, "head moment"]];
    }, tol: 2e-3,
  },
  {
    name: "AS/NZS 1170.2 regional wind speeds", ref: "Table 3.1(A): V500 A = 45, B1 = 57, C = 69, D = 88 m/s",
    run() { return [[Math.round(regionalSpeed("A2", 500)), 45, "A"], [Math.round(regionalSpeed("B1", 500)), 57, "B1"], [Math.round(regionalSpeed("C", 500)), 69, "C"], [Math.round(regionalSpeed("D", 500)), 88, "D"]]; }, tol: 0,
  },
  {
    name: "AS 2159 φgb table lookup", ref: "Table 4.3.2(C): ARR 2.5 low 0.56, high 0.64",
    run() { return [[phiGb(2.5, false), 0.56, "low"], [phiGb(2.5, true), 0.64, "high"], [phiGb(5, false), 0.40, "ARR 5"]]; }, tol: 0,
  },
  {
    name: "Mooring chain catenary", ref: "h = 5 m, H = 10 kN, w = 0.5 kN/m: s = √(h² + 2hH/w) = 15 m, T = H + wh = 12.5 kN, x = (H/w) asinh(sw/H) = 20 ln 2",
    run() { const c = catenary(5, 10, 0.5); return [[c.s, 15, "s (m)"], [c.T, 12.5, "T (kN)"], [c.x, 20 * Math.LN2, "x (m)"], [c.V, 7.5, "V = ws (kN)"]]; }, tol: 1e-9,
  },
  {
    name: "AS 4100 Cl 9.3.2 rod capacity", ref: "M20 property class 8.8: φNtf = 0.8 × 245 × 830 = 162.7 kN; φVf = 0.8 × 0.62 × 830 × 225 = 92.6 kN",
    run() { const b = boltCapacity(20, "8.8"); return [[b.phiNtf, 162.68, "φNtf (kN)"], [b.phiVf, 92.628, "φVf (kN)"]]; }, tol: 1e-6,
  },
  {
    name: "SHS section properties", ref: "100 × 5 SHS (square tube, sharp corners): A = 100² − 90² = 1900 mm²",
    run() { const s = shs(100, 5); return [[s.A, 1900, "A (mm²)"]]; }, tol: 0.05,
  },
  {
    name: "AS 1170.4 spectral shape and kp", ref: "Table 6.4: continuous at 0.1 s and 1.5 s (to 0.1 %: the Table rounds Ce to 1.874/T²); De at 1.0 s = 1.98; Table 3.1 kp(1/500) = 1.0, kp(1/2500) = 1.8",
    run() {
      const rows = [];
      for (const site of ["Ae", "Be", "Ce", "De", "Ee"]) {
        rows.push([spectralShape(site, 0.1 - 1e-9), spectralShape(site, 0.1 + 1e-9), `${site} at 0.1 s`]);
        rows.push([spectralShape(site, 1.5 - 1e-9), spectralShape(site, 1.5 + 1e-9), `${site} at 1.5 s`]);
      }
      return [...rows, [spectralShape("De", 1.0), 1.98, "De 1.0 s"], [kpOf(500), 1.0, "kp 500"], [kpOf(2500), 1.8, "kp 2500"]];
    }, tol: 1e-3,
  },
  {
    name: "AS 3962:2020 tables", ref: "Table 4.6 (12 m: 12 t), Cl 4.9 (0.3 / 0.2 / 0.15 m/s), Table 3.4 (accessible 61 to 120 berths: 1.8 m), Table 3.3 (over 200 m: 2.4 m)",
    run() {
      return [[minDisplacement(12), 12, "Δ 12 m"], [minDisplacement(22.5), 62, "Δ 22.5 m"], [berthingSpeed(20), 0.3, "V 20 m"], [berthingSpeed(30), 0.2, "V 30 m"], [berthingSpeed(40), 0.15, "V 40 m"],
        [gangwayWidth(8), 1.0, "gangway 8 berths"], [gangwayWidth(100, true), 1.8, "gangway 100 accessible"], [walkwayWidth(250), 2.4, "walkway 250 m"], [walkwayWidth(100, false, 1.8), 1.8, "walkway ≥ gangway"]];
    }, tol: 1e-9,
  },
];

/** Run one check: [{got, want, what, ok}] and overall ok. */
export function runCheck(c) {
  const rows = c.run().map(([got, want, what]) => ({ got, want, what, err: rel(got, want), ok: Math.abs(got - want) <= c.tol * Math.max(Math.abs(want), 1) + 1e-12 }));
  return { name: c.name, ref: c.ref, tol: c.tol, rows, ok: rows.every((r) => r.ok) };
}
export const runAll = () => CHECKS.map(runCheck);
