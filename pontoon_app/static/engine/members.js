// Section and member capacities of the piles (and the concrete pontoon shell).
//   steelCHS()      AS 4100 — circular hollow section in bending, shear, compression, combined
//   concreteSection AS 3600 — any section built from rectangles/circles and bars, by strain
//                   compatibility with the rectangular stress block (Cl 8.1.3), so the same
//                   routine gives a square pile, a round or spun hollow pile, and the pontoon box.
//   timberRound()   AS 1720.1 — round timber pile in bending, shear and compression
// Units: N, mm, MPa inside; results returned in kN and kN·m.

import { STEEL, CONCRETE, TIMBER } from "./codes.js";

// ------------------------------------------------------------------ steel CHS

/** Geometric properties of a CHS, outside diameter d and wall t (mm). */
export function chsProps(d, t) {
  const di = d - 2 * t;
  const A = (Math.PI / 4) * (d * d - di * di);
  const I = (Math.PI / 64) * (d ** 4 - di ** 4);
  const Z = (2 * I) / d;
  const S = (d ** 3 - di ** 3) / 6;
  const r = Math.sqrt(I / A);
  return { d, t, di, A, I, Z, S, r };
}

/**
 * AS 4100 checks of a CHS pile. le is the effective length (mm) for compression.
 * Returns capacities and the clause-by-clause working.
 */
export function steelCHS({ d, t, grade = "C350", le = 0 }) {
  const G = STEEL.grades[grade] || STEEL.grades.C350;
  const fy = G.fy(t), p = chsProps(d, t), phi = STEEL.phi;
  // Cl 5.2.2 section slenderness, Table 5.2 (CHS): λep = 50, λey = 120
  const ls = (d / t) * (fy / 250);
  const { lp, ly } = STEEL.chs.flexure;
  const Zc = Math.min(p.S, 1.5 * p.Z);
  let Ze, cls;
  if (ls <= lp) { Ze = Zc; cls = "compact"; }
  else if (ls <= ly) { Ze = p.Z + ((ly - ls) / (ly - lp)) * (Zc - p.Z); cls = "non-compact"; }
  else { Ze = Math.min(p.Z * Math.sqrt(ly / ls), p.Z * (2 * ly / ls) ** 2); cls = "slender"; }
  const Ms = fy * Ze;                         // Cl 5.2.1
  // Cl 5.11.4: CHS shear yield capacity Vw = 0.36 fy Ae (Ae = A for a section that is not slender)
  const Vw = 0.36 * fy * p.A * (cls === "slender" ? Ze / Zc : 1);
  // Cl 6.2.4: form factor from the effective diameter (Table 6.2.4: CHS λey = 82)
  const lsa = ls, lya = STEEL.chs.axial.ly;
  const de = Math.min(d, d * Math.sqrt(lya / lsa), d * (3 * lya / lsa) ** 2);
  const kf = Math.min(1, de / d);
  const Ns = kf * p.A * fy;                   // Cl 6.2.1
  // Cl 6.3.3 column curve; αb = −1.0 cold-formed, −0.5 fabricated (Table 6.3.3(A))
  let ac = 1, ln = 0;
  if (le > 0) {
    const ab = G.formed === "cold" ? -1.0 : -0.5;
    ln = (le / p.r) * Math.sqrt(kf) * Math.sqrt(fy / 250);
    const aa = (2100 * (ln - 13.5)) / (ln * ln - 15.3 * ln + 2050);
    const lam = ln + aa * ab;
    const eta = Math.max(0, 0.00326 * (lam - 13.5));
    const xi = ((lam / 90) ** 2 + 1 + eta) / (2 * (lam / 90) ** 2);
    ac = lam > 0 ? Math.min(1, xi * (1 - Math.sqrt(Math.max(0, 1 - (90 / (xi * lam)) ** 2)))) : 1;
  }
  const Nc = ac * Ns;
  return {
    props: p, fy, ls, cls, Ze, kf, alphaC: ac, lambdaN: ln,
    phiMs: (phi * Ms) / 1e6, phiVv: (phi * Vw) / 1e3, phiNs: (phi * Ns) / 1e3, phiNc: (phi * Nc) / 1e3,
    EI: (STEEL.E * p.I) / 1e9, // kN·m²
    /** Cl 8.3.2 section and 8.4.2.2 member in-plane capacity under axial compression N* (kN). */
    phiMr: (N) => Math.max(0, (phi * Ms) / 1e6 * (1 - N / ((phi * Ns) / 1e3))),
    phiMi: (N) => Math.max(0, (phi * Ms) / 1e6 * (1 - N / ((phi * Nc) / 1e3))),
  };
}

// ------------------------------------------------------------------ concrete

/**
 * Concrete section by strain compatibility.
 *   shape: { kind: "rect", b, h } | { kind: "circle", D, Di } | { kind: "box", B, D, tw, tt, tb }
 *   bars:  [{ y, As }] y measured from the centroid towards the compression face (mm), As mm²
 * Bending about one axis; compression face at +y. Returns φMu at N* (kN, kN·m).
 */
export function concreteSection({ shape, bars, fc }) {
  const a2 = CONCRETE.alpha2(fc), g = CONCRETE.gamma(fc), ecu = CONCRETE.ecu;
  const Es = CONCRETE.Es, fsy = CONCRETE.fsy, ey = fsy / Es;
  // concrete width as a function of y (from the centroid), sampled finely
  const H = shape.kind === "rect" ? shape.h : shape.kind === "circle" ? shape.D : shape.D;
  const width = (y) => {
    if (shape.kind === "rect") return Math.abs(y) <= shape.h / 2 ? shape.b : 0;
    if (shape.kind === "circle") {
      const R = shape.D / 2, Ri = (shape.Di || 0) / 2;
      const o = Math.abs(y) < R ? 2 * Math.sqrt(R * R - y * y) : 0;
      const i = Math.abs(y) < Ri ? 2 * Math.sqrt(Ri * Ri - y * y) : 0;
      return o - i;
    }
    // box: y from mid-depth (symmetrical treatment of deck/base thickness about mid-depth)
    const { B, D, tw, tt, tb } = shape, z = y + D / 2; // z up from the base
    if (z < 0 || z > D) return 0;
    if (z <= tb || z >= D - tt) return B;
    return 2 * tw;
  };
  const top = H / 2;
  const area = (() => { let A = 0; const n = 2000, dy = H / n; for (let i = 0; i < n; i++) A += width(-top + (i + 0.5) * dy) * dy; return A; })();
  // resultant for neutral axis depth dn (from the compression face)
  const forces = (dn) => {
    const yna = top - dn, ystop = top - g * dn; // stress block from the top down to γ dn
    let C = 0, Mc = 0;
    const n = 400, dy = (top - ystop) / n;
    for (let i = 0; i < n; i++) { const y = ystop + (i + 0.5) * dy, f = a2 * fc * width(y) * dy; C += f; Mc += f * y; }
    let Fs = 0, Ms = 0;
    for (const b of bars) {
      const es = (ecu * (b.y - yna)) / dn; // + compression
      let fs = Math.max(-fsy, Math.min(fsy, es * Es));
      // bars inside the stress block displace concrete
      if (b.y > ystop) fs -= a2 * fc;
      Fs += fs * b.As; Ms += fs * b.As * b.y;
    }
    // extreme tension steel depth for kuo
    const dmin = Math.min(...bars.map((b) => b.y));
    return { N: C + Fs, M: Mc + Ms, d0: top - dmin };
  };
  const Nuo = a2 * fc * area + bars.reduce((t, b) => t + b.As, 0) * fsy; // squash load, stress block α2 (Cl 10.6.2.2 uses α1)
  const dnFor = (N) => {
    let lo = 1e-3 * H, hi = 3 * H;
    for (let i = 0; i < 200; i++) { const mid = (lo + hi) / 2; if (forces(mid).N < N) lo = mid; else hi = mid; }
    return (lo + hi) / 2;
  };
  const dn0 = () => dnFor(0);
  /** φMu for axial compression N* (kN). Bisection on dn. */
  function phiMu(Nstar = 0) {
    const dn = dnFor(Nstar * 1e3), r = forces(dn);
    const kuo = dn / r.d0;
    // AS 3600 Table 2.2.2: bending without axial force 0.65 ≤ 1.24 − 13kuo/12 ≤ 0.85; with axial
    // compression φ varies linearly from that value at Nu = 0 to 0.60 at the balanced load Nub.
    let phi = CONCRETE.phiBending(kuo);
    if (Nstar > 0) {
      const db = r.d0 * (ecu / (ecu + ey)), Nub = forces(db).N / 1e3;
      const phi0 = CONCRETE.phiBending(dn0() / r.d0);
      phi = Nstar >= Nub ? 0.6 : 0.6 + (phi0 - 0.6) * (1 - Nstar / Nub);
    }
    return { phiMu: (phi * r.M) / 1e6, Mu: r.M / 1e6, dn, kuo, phi };
  }
  /** AS 3600 Cl 8.2.4: Vuc with kv = 200/(1000 + 1.3 dv) ≤ 0.10 (no shear reinforcement), θv = 36°. */
  function phiVuc(bv, d) {
    const dv = Math.max(0.72 * H, 0.9 * d);
    const kv = Math.min(0.10, 200 / (1000 + 1.3 * dv));
    return (CONCRETE.phiShear * kv * bv * dv * Math.min(8, Math.sqrt(fc))) / 1e3;
  }
  return { area, Nuo: Nuo / 1e3, phiMu, phiVuc, H };
}

/** Bars for common pile sections. */
export function barsSquare(b, cover, n, db, tie = 12) {
  // n bars evenly round the perimeter (n multiple of 4), bending about a principal axis
  const a = b / 2 - cover - tie - db / 2, As = (Math.PI * db * db) / 4, per = Math.max(1, n / 4);
  const pts = [];
  for (let side = 0; side < 4; side++) for (let k = 0; k < per; k++) {
    const s = -a + (2 * a * k) / per;
    const [x, y] = [[s, a], [a, -s], [-s, -a], [-a, s]][side];
    pts.push({ x, y, As });
  }
  return pts;
}
export function barsCircle(D, cover, n, db, tie = 10) {
  const R = D / 2 - cover - tie - db / 2, As = (Math.PI * db * db) / 4;
  return Array.from({ length: n }, (_, i) => { const a = (2 * Math.PI * i) / n + Math.PI / n; return { x: R * Math.cos(a), y: R * Math.sin(a), As }; });
}

// ------------------------------------------------------------------ timber

/** AS 1720.1 round timber pile of diameter D (mm), grade from TIMBER.grades. */
export function timberRound({ D, grade = "F17", phi = TIMBER.phi, k1 = TIMBER.k1 }) {
  const g = TIMBER.grades[grade] || TIMBER.grades.F17;
  const A = (Math.PI * D * D) / 4, Z = (Math.PI * D ** 3) / 32, I = (Math.PI * D ** 4) / 64;
  // Cl 3.2.1 φMd = φ k1 k4 k6 k9 k12 f'b Z, with k4 = k6 = k9 = k12 = 1 (wet use handled by grade choice)
  const phiM = (phi * k1 * g.fb * Z) / 1e6;
  // Cl 3.2.5 φVd = φ k1 k4 k6 f's As, As = 2/3 A for a solid circle? AS 1720.1 uses As = (2/3)·b·d for rectangles;
  // for a circle the shear area is taken as 0.75 A (shear stress 4V/3A at the axis).
  const phiV = (phi * k1 * g.fs * 0.75 * A) / 1e3;
  const phiN = (phi * k1 * g.fc * A) / 1e3; // Cl 3.3.1 with k12 = 1 (short, laterally supported by the ground)
  return { A, Z, I, phiM, phiV, phiN, EI: (g.E * I) / 1e9, grade: g };
}
