// Talus — the verification suite. The same checks run in CI (node --test) and on
// the app's Verification page, so anybody challenging a number can rerun them.
//
// Closed-form checks are solved by hand here, independently of the engine's
// slicing, and must agree to tight tolerances. Published benchmarks must fall
// within the spread that the reference software itself reports.

import { prepare, buildSlices, factors, valueOf } from "./lem.js";
import { criticalCircle, circleSlip } from "./search.js";
import { arcY, mirror } from "./geometry.js";
import { rockArmour, accropode, toe, vanDerMeerNs, waveParams } from "./armour.js";
import { newmark } from "./analyse.js";

const D = Math.PI / 180;

/** Planar wedge through the toe of a 1:1 slope (crest on the right in the user frame). */
function wedgeModel(extra = {}) {
  return {
    ground: [[-20, 0], [0, 0], [10, 10], [30, 10]], bottom: -20,
    layers: [{ mat: { name: "soil", gamma: 20, gsat: 20, c: 5, phi: 30 } }],
    face: { toe: [0, 0], crest: [10, 10] }, ...extra,
  };
}
const WEDGE = mirror([[0, 0], [20, 10]]);   // slip plane from toe (0,0) to (20,10), engine frame
const TH = Math.atan(0.5), WW = 20 * 50, LL = Math.sqrt(500);

/** The circle's ground crossings (engine frame) found by fine bisection. */
function crossings(groundFn, circle) {
  const xs = [];
  const f = (x) => groundFn(x) - arcY(circle, x);
  const a = circle.xc - circle.R + 1e-9, b = circle.xc + circle.R - 1e-9, N = 4000;
  let x0 = a, f0 = f(a);
  for (let i = 1; i <= N; i++) {
    const x1 = a + (b - a) * i / N, f1 = f(x1);
    if (Number.isFinite(f0) && Number.isFinite(f1) && (f0 <= 0) !== (f1 <= 0)) {
      let lo = x0, hi = x1;
      for (let k = 0; k < 80; k++) { const m = (lo + hi) / 2; if ((f(m) <= 0) === (f0 <= 0)) lo = m; else hi = m; }
      xs.push((lo + hi) / 2);
    }
    x0 = x1; f0 = f1;
  }
  return xs;
}

export const CHECKS = [
  {
    id: "wedge-static", group: "Closed form",
    title: "Planar wedge (Culmann): force equilibrium is exact",
    source: "F = (c L + W cos θ tan φ) / (W sin θ) for a rigid block on one plane",
    run() {
      const P = prepare(wedgeModel());
      const r = factors(P, buildSlices(P, WEDGE, { n: 30 }), null);
      const exact = (5 * LL + WW * Math.cos(TH) * Math.tan(30 * D)) / (WW * Math.sin(TH));
      return { expected: exact, rows: [["Janbu simplified", r.janbu], ["Spencer", valueOf(r, "spencer")], ["Morgenstern-Price", valueOf(r, "mp")]], tol: 1e-9 };
    },
  },
  {
    id: "wedge-seismic", group: "Closed form",
    title: "Planar wedge with horizontal seismic load kh = 0.15",
    source: "F = (c L + W (cos θ − kh sin θ) tan φ) / (W (sin θ + kh cos θ))",
    run() {
      const kh = 0.15;
      const P = prepare(wedgeModel({ seismic: { kh, kv: 0 } }));
      const r = factors(P, buildSlices(P, WEDGE, { n: 30 }), null, ["janbu"]);
      const exact = (5 * LL + WW * (Math.cos(TH) - kh * Math.sin(TH)) * Math.tan(30 * D)) / (WW * (Math.sin(TH) + kh * Math.cos(TH)));
      return { expected: exact, rows: [["Janbu simplified", r.janbu]], tol: 1e-9 };
    },
  },
  {
    id: "wedge-surcharge-anchor", group: "Closed form",
    title: "Planar wedge with crest surcharge and an anchor",
    source: "Block equilibrium along and across the plane with q = 20 kPa over the wedge top and a 100 kN/m anchor at 15° below horizontal",
    run() {
      const q = 20, T = 100, psi = 15 * D;
      // anchor head on the face at (5,5), pointing into the slope
      const P = prepare(wedgeModel({
        strips: [{ x1: 10, x2: 20, q }],
        reinforcement: [{ x: 5, y: 5, angle: 15, length: 40, bond: 10, T, kind: "anchor" }],
      }));
      const r = factors(P, buildSlices(P, WEDGE, { n: 30 }), null, ["janbu"]);
      // by hand, in the user frame: the block moves down the plane towards -x
      const W = WW + q * 10;
      const t = [-Math.cos(TH), -Math.sin(TH)];       // direction of movement
      const nrm = [-Math.sin(TH), Math.cos(TH)];      // normal into the block
      const Tv = [T * Math.cos(psi), -T * Math.sin(psi)]; // into the slope (to +x), downwards
      const drive = W * (-t[1]) + (Tv[0] * t[0] + Tv[1] * t[1]);
      const N = W * nrm[1] - (Tv[0] * nrm[0] + Tv[1] * nrm[1]);
      const exact = (5 * LL + N * Math.tan(30 * D)) / drive;
      return { expected: exact, rows: [["Janbu simplified", r.janbu]], tol: 1e-9 };
    },
  },
  {
    id: "phi0-circle", group: "Closed form",
    title: "Undrained clay (φ = 0) on a given circle: F = su L R / (W d)",
    source: "Moment equilibrium about the centre; arc length and weight moment integrated independently (400 000 strips)",
    run() {
      const su = 40, g = 18;
      const P = prepare({
        ground: [[-30, 0], [0, 0], [20, 10], [60, 10]], bottom: -30,
        layers: [{ mat: { name: "clay", gamma: g, gsat: g, kind: "undrained", su, phi: 0 } }],
        face: { toe: [0, 0], crest: [20, 10] },
      });
      const user = { xc: 8, yc: 22, R: 25 };
      const gU = (x) => (x < 0 ? 0 : x < 20 ? x / 2 : 10);
      const [xa, xb] = (() => { const xs = crossings(gU, user); return [xs[0], xs[xs.length - 1]]; })();
      let M = 0;
      const N = 400000, h = (xb - xa) / N;
      for (let i = 0; i < N; i++) {
        const x = xa + (i + 0.5) * h;
        M += g * Math.max(0, gU(x) - arcY(user, x)) * h * (x - user.xc);
      }
      const a1 = Math.atan2(xa - user.xc, user.yc - arcY(user, xa)), a2 = Math.atan2(xb - user.xc, user.yc - arcY(user, xb));
      const exact = su * user.R * (a2 - a1) * user.R / Math.abs(M);
      const c = { xc: -user.xc, yc: user.yc, R: user.R };
      const cut = buildSlices(P, circleSlip(P, c, -xb, -xa, 400), { n: 400 });
      const r = factors(P, cut, c);
      return { expected: exact, rows: [["Ordinary", r.ordinary], ["Bishop simplified", r.bishop], ["Spencer", valueOf(r, "spencer")], ["Morgenstern-Price", valueOf(r, "mp")]], tol: 1e-4 };
    },
  },
  {
    id: "archimedes", group: "Closed form",
    title: "Submerged slope: water above and pore pressure below equal buoyant weight",
    source: "Hydrostatic water on a closed boundary is buoyancy: γsat with water ≡ (γsat − γw) dry. Exact for force equilibrium; rigorous methods within 0.2% (their interslice assumption sees the water forces)",
    run() {
      const gw = 9.81, gs = 20;
      const ground = [[-30, 0], [0, 0], [20, 10], [60, 10]];
      const base = { ground, bottom: -30, face: { toe: [0, 0], crest: [20, 10] } };
      const wet = prepare({ ...base, layers: [{ mat: { name: "s", gamma: 18, gsat: gs, c: 5, phi: 30 } }], piezo: [[-30, 15], [60, 15]], gw });
      const dry = prepare({ ...base, layers: [{ mat: { name: "s", gamma: gs - gw, gsat: gs - gw, c: 5, phi: 30 } }] });
      const user = { xc: 8, yc: 22, R: 25 };
      const gU = (x) => (x < 0 ? 0 : x < 20 ? x / 2 : 10);
      const xs = crossings(gU, user);
      const c = { xc: -user.xc, yc: user.yc, R: user.R };
      const at = (P) => factors(P, buildSlices(P, circleSlip(P, c, -xs[xs.length - 1], -xs[0], 60), { n: 60 }), c);
      const a = at(wet), b = at(dry);
      return {
        expected: b.janbu, rows: [["Janbu simplified (exact)", a.janbu]], tol: 1e-9,
        also: [
          { label: "Bishop simplified", value: a.bishop, expected: b.bishop, tol: 2e-3 },
          { label: "Spencer", value: valueOf(a, "spencer"), expected: valueOf(b, "spencer"), tol: 2e-3 },
          { label: "Morgenstern-Price", value: valueOf(a, "mp"), expected: valueOf(b, "mp"), tol: 2e-3 },
        ],
      };
    },
  },
  {
    id: "infinite-slope", group: "Closed form",
    title: "Dry sand slope: critical F tends to tan φ / tan β",
    source: "Infinite slope, c = 0: F = tan φ / tan β (the search must find the shallow surface)",
    run() {
      const phi = 32, cot = 2;
      const P = prepare({
        ground: [[0, 0], [20, 0], [60, 20], [80, 20]], bottom: -10,
        layers: [{ mat: { name: "sand", gamma: 18, gsat: 20, c: 0, phi } }],
        face: { toe: [20, 0], crest: [60, 20] },
      });
      const r = criticalCircle(P, { method: "mp", minDepth: 0.3 });
      return { expected: Math.tan(phi * D) * cot, rows: [["Morgenstern-Price (search)", r.F]], tol: 0.03, oneSided: true };
    },
  },
  {
    id: "acads-1a", group: "Published",
    title: "ACADS 1(a) simple slope (Giam & Donald 1989)",
    source: "c' = 3 kPa, φ' = 19.6°, γ = 20 kN/m³, 2:1 slope 10 m high. Referee F = 1.00; GeoStudio M-P 0.991; Slide Bishop 0.987, Spencer 0.986",
    run() {
      const P = prepare({
        ground: [[20, 25], [30, 25], [50, 35], [70, 35]], bottom: 20,
        layers: [{ mat: { name: "soil", gamma: 20, gsat: 20, c: 3, phi: 19.6 } }],
        face: { toe: [30, 25], crest: [50, 35] },
      });
      const r = criticalCircle(P, { method: "mp" });
      return { expected: 0.991, rows: [["Morgenstern-Price", valueOf(r.results, "mp")], ["Spencer", valueOf(r.results, "spencer")], ["Bishop simplified", r.results.bishop]], tol: 0.012 };
    },
  },
  {
    id: "hudson", group: "Armour",
    title: "Hudson: rock armour mass by hand",
    source: "M50 = ρr Hs³ / (KD Δ³ cot α); Hs 2 m, cot α 2, KD 4, ρr 2650, ρw 1025",
    run() {
      const a = rockArmour({ Hs: 2, Tp: 8, h: 10, cot: 2, rhoR: 2650, rhoW: 1025, P: 0.4, S: 2, N: 3000, governing: "hudson" });
      const Dl = 2650 / 1025 - 1;
      return { expected: 2650 * 8 / (4 * Dl ** 3 * 2), rows: [["Talus M50 (kg)", a.hudson.M50]], tol: 1e-9 };
    },
  },
  {
    id: "vdm", group: "Armour",
    title: "Van der Meer (1988) deep water, plunging and surging",
    source: "Hs/(ΔDn50) = 6.2 P^0.18 (S/√N)^0.2 ξm^-0.5 (plunging), 1.0 P^-0.13 (S/√N)^0.2 √cot α ξm^P (surging)",
    run() {
      const w = { Hs: 2, Tp: 8, cot: 2 };
      const { xim, tana } = waveParams(w);
      const P = 0.4, S = 2, N = 3000;
      const pl = 6.2 * P ** 0.18 * (S / Math.sqrt(N)) ** 0.2 * xim ** -0.5;
      const su = 1.0 * P ** -0.13 * (S / Math.sqrt(N)) ** 0.2 * Math.sqrt(2) * xim ** P;
      const xicr = (6.2 * P ** 0.31 * Math.sqrt(tana)) ** (1 / (P + 0.5));
      const r = vanDerMeerNs(w, P, S, N, false);
      return { expected: xim < xicr ? pl : su, rows: [["Talus Ns", r.Ns]], tol: 1e-12 };
    },
  },
  {
    id: "accropode", group: "Armour",
    title: "Accropode: design stability number 2.7 (CLI)",
    source: "Ns = (KD cot α)^(1/3) with KD = 15 at 4:3 gives 2.71; CLI design value Ns = 2.7",
    run() {
      const a = accropode({ Hs: 4, Tp: 10, h: 12, cot: 4 / 3, rhoC: 2400, rhoW: 1025, unit: "accropode1" });
      return { expected: 2.7, rows: [["Talus Ns", a.Ns]], tol: 0.01 };
    },
  },
  {
    id: "toe", group: "Armour",
    title: "Toe rock (Van der Meer 1998)",
    source: "Hs/(ΔDn50) = (2 + 6.2 (ht/h)^2.7) Nod^0.15, ht/h = 0.7, Nod = 0.5",
    run() {
      const t = toe({ Hs: 2, h: 10, ht: 7, rhoR: 2650, rhoW: 1025, Nod: 0.5 });
      return { expected: (2 + 6.2 * 0.7 ** 2.7) * 0.5 ** 0.15, rows: [["Talus Ns", t.Ns]], tol: 1e-12 };
    },
  },
  {
    id: "newmark", group: "Seismic",
    title: "Newmark displacement, Jibson (2007)",
    source: "log D = 0.215 + log[(1 − ky/amax)^2.341 (ky/amax)^−1.438]; ky/amax = 0.5 gives D = 0.877 cm",
    run() {
      return { expected: Math.pow(10, 0.215 + Math.log10(0.5 ** 2.341 * 0.5 ** -1.438)), rows: [["Talus D (cm)", newmark(0.1, 0.2).D]], tol: 1e-12 };
    },
  },
];

/** Runs one check: [{ label, value, expected, error, pass }]. */
export function runCheck(check) {
  const r = check.run();
  const rows = r.rows.map(([label, value]) => {
    const err = (value - r.expected) / r.expected;
    const pass = r.oneSided ? err >= -1e-9 && err <= r.tol : Math.abs(err) <= r.tol;
    return { label, value, expected: r.expected, error: err, tol: r.tol, pass };
  });
  for (const a of r.also || []) {
    const err = (a.value - a.expected) / a.expected;
    rows.push({ label: a.label, value: a.value, expected: a.expected, error: err, tol: a.tol, pass: Math.abs(err) <= a.tol });
  }
  return rows;
}
