// The parts of a marina beyond the floats and the piles' bending: what joins the pontoons,
// what holds them to the piles, the gangway, earthquake, serviceability and durability
// (AS 4997), and pontoons held by chains instead of piles.
//
// Every function returns checks in the same shape as analyse.js, each with its clause and
// the working with the numbers substituted.

import * as C from "./codes.js";
import { G, waterplane, initial } from "./hydro.js";
import { beamWinkler } from "./fe.js";
import { section } from "./model.js";
import { sectionDefaults } from "./project.js";

const fx = (v, d = 2) => (Number.isFinite(v) ? (+v.toFixed(d)).toString() : "–");
const mm = (m) => `${Math.round(m * 1000)} mm`;

export function check(group, name, value, limit, { unit = "", sense = "max", src = "", working = [], note = "", key } = {}) {
  let ratio = null, pass = true;
  if (limit !== null && limit !== undefined && Number.isFinite(value)) {
    if (sense === "max") { ratio = limit > 0 ? value / limit : value > 0 ? Infinity : 0; pass = value <= limit * (1 + 1e-9); }
    else { ratio = value > 0 ? limit / value : Infinity; pass = value >= limit * (1 - 1e-9); }
  } else if (!Number.isFinite(value)) pass = false;
  return { key: key || `${group}:${name}`, group, name, value, limit, unit, sense, ratio, pass, src, working, note };
}

// ------------------------------------------------------------------ steel helpers

/** SHS b × t (mm), cold-formed C350L0: section properties and AS 4100 capacities (kN, kN·m). */
export function shs(b, t, le = 0) {
  const fy = 350, bi = b - 2 * t;
  const A = b * b - bi * bi, I = (b ** 4 - bi ** 4) / 12, Z = I / (b / 2), S = (b ** 3 - bi ** 3) / 4;
  const r = Math.sqrt(I / A);
  // AS 4100 Table 5.2, cold-formed RHS flange supported on both edges: λsp = 30, λsy = 40
  const lsF = (bi / t) * Math.sqrt(fy / 250);
  const lep = 30, ley = 40;
  const Zc = Math.min(S, 1.5 * Z);
  const Ze = lsF <= lep ? Zc : lsF <= ley ? Z + ((ley - lsF) / (ley - lep)) * (Zc - Z) : Z * (ley / lsF);
  // Cl 6.2.4 form factor: effective width of each wall be = b(λey/λe) ≤ b (λey = 40 for CF RHS walls)
  const be = Math.min(bi, bi * (ley / Math.max(lsF, 1e-9)));
  const kf = (A - 4 * (bi - be) * t) / A;
  let ac = 1, ln = 0;
  if (le > 0) {
    const ab = -0.5; // AS 4100 Table 6.3.3(A): cold-formed hollow sections (stress-relieved) αb = −0.5
    ln = (le / r) * Math.sqrt(kf) * Math.sqrt(fy / 250);
    const aa = (2100 * (ln - 13.5)) / (ln * ln - 15.3 * ln + 2050);
    const lam = ln + aa * ab, eta = Math.max(0, 0.00326 * (lam - 13.5));
    const xi = ((lam / 90) ** 2 + 1 + eta) / (2 * (lam / 90) ** 2);
    ac = Math.min(1, xi * (1 - Math.sqrt(Math.max(0, 1 - (90 / (xi * lam)) ** 2))));
  }
  return {
    b, t, A, I, Z, Ze, r, fy, kf, alphaC: ac, lambdaN: ln, mass: (A / 1e6) * 7850,
    phiMs: (0.9 * fy * Ze) / 1e6, phiNt: (0.9 * fy * A) / 1e3, phiNc: (0.9 * ac * kf * fy * A) / 1e3,
    phiVv: (0.9 * 0.6 * fy * 2 * (b - 2 * t) * t) / 1e3, EI: (200000 * I) / 1e9,
  };
}

/** Threaded rod or bolt, AS 4100 Cl 9.3.2: φNtf = 0.8 As fuf, φVf = 0.8 × 0.62 fuf Ac (threads in the plane). */
export function boltCapacity(d, grade = "A4-70") {
  const g = C.BOLT.grades[grade] || C.BOLT.grades["A4-70"];
  const row = C.BOLT.sizes.find((r) => r[0] === d) || C.BOLT.sizes[2];
  const [, As, Ac] = row;
  return { d, grade, name: g.name, fuf: g.fuf, As, Ac, phiNtf: (C.BOLT.phi * As * g.fuf) / 1e3, phiVf: (C.BOLT.phi * 0.62 * g.fuf * Ac) / 1e3 };
}
/** Smallest rod (from the AS 1275 list) that carries tension N and shear V with the Cl 9.3.2.3 interaction. */
function sizeRod(N, V, grade) {
  for (const [d] of C.BOLT.sizes) {
    const b = boltCapacity(d, grade);
    const u = (V / b.phiVf) ** 2 + (N / b.phiNtf) ** 2;
    if (u <= 1) return { ...b, u };
  }
  const b = boltCapacity(C.BOLT.sizes[C.BOLT.sizes.length - 1][0], grade);
  return { ...b, u: (V / b.phiVf) ** 2 + (N / b.phiNtf) ** 2 };
}

// ------------------------------------------------------------------ connections

/**
 * Module-to-module joints of the main walkway and finger-to-walkway joints.
 * In plan the arm spans between guide piles under the across-arm load; the joints are taken
 * at the worst place, over a pile (M = wL²/8 of a span between piles, an upper bound for a
 * continuous arm), with the along-arm force shared by the two lines of rods.
 */
export function connections(p, lay, floats, loads, berth, nPiles) {
  const checks = [], cn = p.connections;
  const grade = cn.grade, perSide = Math.max(1, +cn.rodsPerSide || 2), edge = 0.15;
  const ulsY = Math.max(...loads.map((L) => L.dirs.Y.total)), ulsX = Math.max(...loads.map((L) => L.dirs.X.total));
  const span = lay.walkLen / Math.max(1, nPiles - 1);
  const wY = ulsY / lay.walkLen;                     // kN/m across the arm
  const Mj = (wY * span * span) / 8;                 // kN·m in plan at a joint
  const z = Math.max(0.3, lay.walkW - 2 * edge);     // lever arm between the two lines of rods
  const Nx = ulsX / 2;                               // along-arm force through a joint
  const Trod = Mj / z / perSide + Nx / (2 * perSide);
  const Vh = (wY * span) / 2 / (2 * perSide);        // horizontal shear per rod
  const Vv = (1.5 * C.DECK_LIVE.point) / (2 * perSide); // 4.5 kN at the joint, 1.5 × Q (AS/NZS 1170.0 Cl 4.2.2)
  const V = Math.hypot(Vh, Vv);
  const rod = cn.rodD ? { ...boltCapacity(+cn.rodD, grade) } : sizeRod(Trod, V, grade);
  const u = (V / rod.phiVf) ** 2 + (Trod / rod.phiNtf) ** 2;
  const modular = p.type === "modular";
  checks.push(check("Connections", "Walkway module joint: rod tension and shear", Math.sqrt(u), 1, {
    unit: "", src: C.BOLT.src,
    working: [
      `In plan: across-arm load w = ${fx(ulsY, 1)} kN / ${fx(lay.walkLen, 1)} m = ${fx(wY, 3)} kN/m; ${nPiles} piles, span ${fx(span, 2)} m`,
      `Joint moment M* = w L² / 8 = ${fx(Mj, 2)} kN·m (joint over a pile, simply supported span: an upper bound for the continuous arm)`,
      `Along the arm N* = ${fx(ulsX, 1)} / 2 = ${fx(Nx, 2)} kN; two lines of ${perSide} rods ${fx(z, 2)} m apart`,
      `Rod tension N*tf = M*/(z·n) + N*/(2n) = ${fx(Mj, 2)}/(${fx(z, 2)}×${perSide}) + ${fx(Nx, 2)}/${2 * perSide} = ${fx(Trod, 2)} kN`,
      `Rod shear: horizontal wL/2/(2n) = ${fx(Vh, 2)} kN, vertical 1.5 × 4.5 kN/(2n) = ${fx(Vv, 2)} kN → V*f = ${fx(V, 2)} kN`,
      `M${rod.d} ${rod.name}: As ${rod.As} mm², Ac ${rod.Ac} mm², φNtf = 0.8 As fuf = ${fx(rod.phiNtf, 1)} kN, φVf = 0.8 × 0.62 fuf Ac = ${fx(rod.phiVf, 1)} kN`,
      `(V*/φVf)² + (N*/φNtf)² = ${fx(u, 3)} ≤ 1.0 (AS 4100 Cl 9.3.2.3); reported as its square root`,
    ],
    note: modular ? "Modular cubes are joined by the supplier's connector pins; use these actions to choose the pin and the number of connector rows." : "",
  }));
  // finger joints: cantilever from the walkway, worst of berthing on the tip and the moored boat's
  // beam-on wind and current shared along the finger
  const kf = +p.fender.k || 400;
  const Fb = 1.25 * Math.sqrt(2 * berth.E * kf);
  const boatX = Math.max(...loads.map((L) => L.combo.wind * (L.parts.windX / Math.max(1, L.parts.shelter * lay.sides)) + L.combo.current * (L.parts.boatCurX / Math.max(1, L.parts.shelter * lay.sides))));
  const Mb = Fb * lay.fingerL, Mw = boatX * lay.fingerL / 2;
  const Mf = Math.max(Mb, Mw);
  const zf = Math.max(0.3, lay.fingerW - 2 * 0.1);
  // rods per side at the finger root: as given, more (up to 6) when the largest rod is not enough
  let nF = perSide, Tf, Vf, rodF, uf;
  for (;;) {
    Tf = Mf / zf / nF; Vf = Math.max(Fb, boatX) / (2 * nF);
    rodF = cn.rodD ? { ...boltCapacity(+cn.rodD, grade) } : sizeRod(Tf, Vf, grade);
    uf = (Vf / rodF.phiVf) ** 2 + (Tf / rodF.phiNtf) ** 2;
    if (uf <= 1 || cn.rodD || nF >= 6) break;
    nF++;
  }
  checks.push(check("Connections", "Finger root joint: rod tension and shear", Math.sqrt(uf), 1, {
    unit: "", src: `${C.BOLT.src}; AS 3962 Cl 4.9`,
    working: [
      `Berthing on the finger tip: F = 1.25 √(2 E k) = 1.25 √(2 × ${fx(berth.E, 2)} × ${fx(kf, 0)}) = ${fx(Fb, 2)} kN → M = F L = ${fx(Mb, 2)} kN·m (finger and walkway taken as rigid: conservative)`,
      `Moored boat beam-on to the finger: wind + current ${fx(boatX, 2)} kN spread along it → M = ${fx(Mw, 2)} kN·m`,
      `Root moment ${fx(Mf, 2)} kN·m; two lines of ${nF} rods${nF > perSide ? ` (raised from ${perSide} so the rods fit)` : ""} ${fx(zf, 2)} m apart: N*tf = ${fx(Tf, 2)} kN, V*f = ${fx(Vf, 2)} kN`,
      `M${rodF.d} ${rodF.name}: φNtf ${fx(rodF.phiNtf, 1)} kN, φVf ${fx(rodF.phiVf, 1)} kN; interaction ${fx(uf, 3)}`,
    ],
    note: "Fingers are usually stiffened at the root with knee braces or a corner plate; these rods are the minimum connection.",
  }));
  return { checks, joint: { Mj, Nx, Trod, V, rod, perSide, z, span }, finger: { Fb, Mf, Tf, Vf, rod: rodF, z: zf, perSide: nF } };
}

/** Pile guide frame: two SHS arms cantilevered from the pontoon face around the pile, rollers on the pile. */
export function pileGuides(p, piles, floats) {
  const checks = [], D = piles.ps.D;
  const gap = +p.connections.guideGap || 0.05;   // clearance each side between roller and pile
  const a = D + 2 * gap + 0.15;                   // lever from the pontoon face to the far roller line
  const H = Math.max(...piles.results.map((r) => r.H));
  const M = (H / 2) * a;                          // each arm takes half, cantilever
  let pick = null;
  for (const [b, t] of C.SHS) { const s = shs(b, t); if (s.phiMs >= M && s.phiVv >= H / 2) { pick = s; break; } }
  pick ||= shs(...C.SHS[C.SHS.length - 1]);
  checks.push(check("Connections", "Pile guide arm bending", M, pick.phiMs, {
    unit: "kN·m", src: "AS 4100 Cl 5.1, 5.2 (cold-formed SHS C350L0)",
    working: [
      `Largest guide force H* = ${fx(H, 2)} kN (every pile case, berthing included)`,
      `Two SHS arms around a ${mm(D)} pile with ${mm(gap)} roller clearance each side: lever a = D + 2·gap + 0.15 = ${fx(a, 3)} m`,
      `M* = (H*/2)·a = ${fx(M, 2)} kN·m per arm; SHS ${pick.b} × ${pick.t}: Ze ${fx(pick.Ze / 1e3, 1)} × 10³ mm³, φMs = ${fx(pick.phiMs, 2)} kN·m, φVv = ${fx(pick.phiVv, 1)} kN`,
    ],
  }));
  checks.push(check("Connections", "Pile guide arm shear", H / 2, pick.phiVv, { unit: "kN", src: "AS 4100 Cl 5.11 (two webs)" }));
  // the frame is bolted to the pontoon: four rods, lever 0.3 m
  const rod = sizeRod(M / 0.3 / 2, H / 4, p.connections.grade);
  checks.push(check("Connections", "Pile guide anchor rods", Math.sqrt((H / 4 / rod.phiVf) ** 2 + (M / 0.3 / 2 / rod.phiNtf) ** 2), 1, {
    unit: "", src: C.BOLT.src,
    working: [`Four rods per arm base, 0.3 m apart: tension M*/0.3/2 = ${fx(M / 0.6, 2)} kN, shear H*/4 = ${fx(H / 4, 2)} kN → M${rod.d} ${rod.name}`],
  }));
  return { checks, H, a, M, shs: pick, gap, rod, roller: { force: H, note: "UHMWPE or polyurethane rollers rated for H* at the guide" } };
}

// ------------------------------------------------------------------ gangway

/** Gangway: two side trusses, simply supported, AS 3962 Cl 4.5 live loads. */
export function gangwayDesign(p, lay, floats, gangway, gw) {
  const g = p.gangway;
  const L = gangway.length, w = lay.gangwayW + 0.1;
  const live = C.GANGWAY_LIVE[p.access === "restricted" ? "restricted" : "unrestricted"];
  const dead = +g.dead || C.GANGWAY_SLS.deadKPa;
  const qG = dead * w, qQ = live.udl * w;          // kN/m, whole gangway
  const Mstar = Math.max((1.2 * qG + 1.5 * qQ) * L * L / 8, 1.2 * qG * L * L / 8 + 1.5 * live.point * L / 4, 1.35 * qG * L * L / 8);
  const panel = +g.panel || 1.0;
  const alu = g.material !== "steel";
  const truss = (h, b, t) => {
    const checks = [];
    const Mtruss = Mstar / 2, Nchord = Mtruss / h;
    let chord, phiNt, phiNc, desc, E;
    if (alu) {
      // AS/NZS 1664.1: 6061-T6, tension φFty A; compression with a column curve (Cl 3.4.7, simplified: Euler with φc)
      const A = C.ALUMINIUM, bi = b - 2 * t;
      const Ar = b * b - bi * bi, I = (b ** 4 - bi ** 4) / 12, r = Math.sqrt(I / Ar);
      const slend = (panel * 1000) / r, Fe = (Math.PI ** 2 * A.E) / (slend * slend);
      const Fc = Math.min(A.fty, Fe * 0.877);
      chord = { b, t, A: Ar, I, r, slend };
      phiNt = (A.phiY * A.fty * Ar) / 1e3; phiNc = (A.phiC * Fc * Ar) / 1e3; E = A.E;
      desc = `SHS ${b} × ${t} 6061-T6 aluminium chords`;
    } else {
      const s = shs(b, t, panel * 1000);
      chord = s; phiNt = s.phiNt; phiNc = s.phiNc; E = 200000;
      desc = `SHS ${s.b} × ${s.t} C350L0 steel chords`;
    }
    const Itruss = 2 * chord.A * (h * 1000 / 2) ** 2 * 0.8; // mm⁴ per truss, 0.8 for shear deformation of the web
    const EI = (E * Itruss) / 1e9 * 2;                       // kN·m², both trusses
    const dLive = (5 * qQ * L ** 4) / (384 * EI);
    const m = (qG / G) * 1000;                               // kg/m
    const f1 = (Math.PI / (2 * L * L)) * Math.sqrt((EI * 1000) / m);
    const work = [
      `Span ${fx(L, 2)} m, ${fx(w, 2)} m wide, two side trusses ${fx(h, 2)} m deep, ${desc}, panels ${fx(panel, 2)} m`,
      `G = ${fx(dead, 2)} kPa → ${fx(qG, 2)} kN/m; Q = ${live.udl} kPa → ${fx(qQ, 2)} kN/m, or ${live.point} kN (AS 3962 Cl 4.5)`,
      `M* = max[(1.2G + 1.5Q)L²/8, 1.2GL²/8 + 1.5PL/4, 1.35GL²/8] = ${fx(Mstar, 2)} kN·m; per truss ${fx(Mtruss, 2)} kN·m → chord force ${fx(Nchord, 2)} kN`,
    ];
    checks.push(check("Gangway", "Bottom chord tension", Nchord, phiNt, { unit: "kN", src: alu ? "AS/NZS 1664.1 Cl 3.4.1" : "AS 4100 Cl 7.2", working: [...work, `φNt = ${fx(phiNt, 1)} kN`] }));
    checks.push(check("Gangway", "Top chord compression between panel points", Nchord, phiNc, {
      unit: "kN", src: alu ? "AS/NZS 1664.1 Cl 3.4.7 (column)" : "AS 4100 Cl 6.3.3 (αb = −0.5)",
      working: [`Effective length = panel ${fx(panel, 2)} m (deck cross-members restrain the chord); φNc = ${fx(phiNc, 1)} kN`],
    }));
    checks.push(check("Gangway", "Live load deflection", dLive, L / C.GANGWAY_SLS.deflection, {
      unit: "m", src: C.GANGWAY_SLS.src,
      working: [`I per truss = 2 A (h/2)² × 0.8 = ${fx(Itruss / 1e12, 5)} m⁴; EI both trusses = ${fx(EI, 0)} kN·m²`, `δ = 5 q L⁴ / 384 EI = ${fx(dLive * 1000, 1)} mm ≤ L/${C.GANGWAY_SLS.deflection} = ${fx((L / C.GANGWAY_SLS.deflection) * 1000, 1)} mm`],
    }));
    checks.push(check("Gangway", "First vertical frequency", f1, C.GANGWAY_SLS.frequency, {
      unit: "Hz", sense: "min", src: C.GANGWAY_SLS.src,
      working: [`f1 = (π / 2L²) √(EI/m), m = ${fx(m, 0)} kg/m → ${fx(f1, 2)} Hz`],
    }));
    return { checks, h, Nchord, phiNt, phiNc, dLive, f1, desc, chord, ok: checks.every((c) => c.pass) };
  };
  // chord and depth: as given, or the lightest SHS (then a deeper truss, to 1.5 m) that passes
  const h0 = +g.depth || 1.1;
  let T;
  if (+g.chord > 0) T = truss(h0, +g.chord, +g.chordT || (alu ? 6 : 5));
  else {
    const sizes = C.SHS.filter(([b]) => b <= 150);
    const depths = +g.depth > 0 ? [h0] : [1.1, 1.2, 1.3, 1.4, 1.5];
    outer: for (const h of depths) for (const [b, t] of sizes) { T = truss(h, b, t); if (T.ok) break outer; }
    T.auto = true;
  }
  const checks = T.checks, h = T.h;
  const { Nchord, phiNt, phiNc, dLive, f1, desc, chord } = T;
  // the landing on the pontoon: the gangway reaction at the end of a module, with the flotation
  // load on the deck. The landing module is widened (0.1 m steps) until it keeps the reserve.
  const walk = floats.walkway;
  // AS 3962 Cl 4.7.3: the flotation load is applied on the deck and on the gangway
  const acc = C.FLOTATION[p.access] || C.FLOTATION.unrestricted;
  const qF = acc.flotation * w, R = (qG + qF) * L / 2;
  const landingAt = (B, kind = p.type) => {
    const sec = B === lay.walkW && kind === p.type ? walk.sec : section(kind, kind === p.type ? p.section : sectionDefaults("concrete"), B);
    const ini = initial(sec.rects, sec.w, sec.zg, gw * sec.cover);
    const kW = gw * sec.cover * waterplane(sec.rects, ini.T).b;
    const qf = acc.flotation * B;
    const r = beamWinkler({ L: lay.moduleL, EI: sec.EI, k: kW, n: 60 }, [{ x: 0, P: R }], () => qf);
    return { B, kind, sec, T: ini.T, kW, qf, sink: r.w[0], top: sec.top - ini.T - r.w[0] };
  };
  const given = +p.gangway.landingWidth > 0;
  const widen = (kind, Bmax) => {
    let l = landingAt(lay.walkW, kind);
    while (l.top < C.FREEBOARD.reserve && l.B < Bmax) l = landingAt(Math.round((l.B + 0.1) * 10) / 10, kind);
    return l;
  };
  let land;
  if (given) land = landingAt(+p.gangway.landingWidth, p.gangway.landingKind || p.type);
  else {
    land = widen(p.type, 8);
    // a light framed or modular walkway is usually landed on a concrete landing pontoon
    if (land.top < C.FREEBOARD.reserve && p.type !== "concrete" && p.type !== "attenuator") land = widen("concrete", 8);
  }
  checks.push(check("Gangway", "Flotation reserve at the landing", land.top, C.FREEBOARD.reserve, {
    unit: "m", sense: "min", src: "AS 3962 Cl 4.7.1(b) with the gangway reaction (Cl 4.5)",
    working: [
      `Reaction on the pontoon end with the flotation load on the gangway (Cl 4.7.3): R = (G + ${acc.flotation} kPa × w)·L/2 = (${fx(qG, 2)} + ${fx(qF, 2)}) × ${fx(L, 2)} / 2 = ${fx(R, 2)} kN`,
      `${land.kind !== p.type ? "Concrete landing pontoon" : "Landing module"} ${fx(land.B, 1)} m wide${land.B > lay.walkW ? ` (walkway ${fx(lay.walkW, 1)} m, widened${given ? "" : " until it keeps the reserve"})` : ""} × ${fx(lay.moduleL, 1)} m: draft ${fx(land.T, 4)} m, k = ${fx(land.kW, 1)} kN/m², EI ${fx(land.sec.EI, 0)} kN·m²`,
      `On the water with the flotation load ${fx(land.qf, 2)} kN/m and R at its end: end sinkage ${fx(land.sink * 1000, 1)} mm`,
      `Top of flotation at the landing: ${fx(land.sec.top, 3)} − ${fx(land.T, 4)} − ${fx(land.sink, 4)} = ${fx(land.top, 4)} m`,
    ],
  }));
  const sink = land.sink;
  return { checks, auto: !!T.auto, L, w, h, Mstar, Nchord, phiNt, phiNc, dLive, f1, R, sink, desc, chord, landing: { B: land.B, kind: land.kind, top: land.top, sec: land.sec, T: land.T } };
}

// ------------------------------------------------------------------ earthquake (AS 1170.4)

export function seismicBasis(p) {
  const lives = [5, 25, 50, 100];
  const life = lives.find((l) => +p.site.life <= l) || 100;
  const P = C.RETURN_PERIOD_EQ[life][Math.min(4, Math.max(1, +p.site.importance || 2))];
  const kp = C.kpOf(P), Z = +p.seismic.Z || 0;
  const kpZ = Math.max(C.EQ.kpZmin, kp * Z);
  return { P, kp, Z, kpZ, site: p.seismic.site || "De", Sp: +p.seismic.Sp || C.EQ.Sp, mu: +p.seismic.mu || C.EQ.mu };
}
/** Design spectrum Cd(T) = Ch(T) kpZ Sp/μ (AS 1170.4 Cl 6.2, 7.2). */
export const designCoefficient = (b, T) => C.spectralShape(b.site, T) * b.kpZ * b.Sp / b.mu;

// ------------------------------------------------------------------ AS 4997: life, durability

export function as4997(p, lay, floats) {
  const checks = [], advice = [];
  const cat = C.DESIGN_LIFE[p.design.category || "small"] || C.DESIGN_LIFE.small;
  const info = (c) => { if (c.pass) c.ratio = null; return c; };
  checks.push(info(check("Design basis", "Design working life", +p.site.life, cat.life, {
    unit: "years", sense: "min", src: C.DESIGN_LIFE.src,
    working: [`Category: ${cat.name} → design working life ${cat.life} years; this design uses ${p.site.life} years`],
  })));
  if (p.type === "concrete" || p.type === "attenuator") {
    const cov = +p.section.meshCover || 30, fc = +p.section.fc || 40;
    checks.push(info(check("Design basis", "Shell concrete strength for tidal/splash exposure", fc, C.DURABILITY.concreteShell.minFc, {
      unit: "MPa", sense: "min", src: C.DURABILITY.concreteShell.src,
    })));
    if (cov < 65) advice.push({ src: "AS 4997 Section 6", text: `Concrete shell cover ${cov} mm is below the AS 3600 Table 4.10.3.2 value for exposure C2 (65 mm). Thin pontoon shells rely on dense high-strength concrete and galvanised or stainless mesh instead; state that durability basis on the drawings.` });
  }
  return { checks, advice, category: cat };
}

// ------------------------------------------------------------------ chain moorings

/** Catenary of a chain from a fairlead h above the seabed carrying horizontal tension H (kN), submerged weight w (kN/m). */
export function catenary(h, H, w) {
  const s = Math.sqrt(h * h + (2 * h * H) / w);       // suspended length to the touch-down point
  const x = H > 0 ? (H / w) * Math.asinh((s * w) / H) : 0; // its horizontal projection
  return { s, x, T: H + w * h, V: w * s };
}

/** Chains crossed under the walkway at each mooring point, anchored by concrete blocks. */
export function mooringDesign(p, lay, floats, loads, levels, gw) {
  const m = p.mooring, checks = [], life = +p.site.life || 25;
  const n = Math.max(2, Math.ceil(lay.walkLen / Math.max(2, +m.spacing || 12)) + 1);
  const T = floats.walkway.ini.T;
  const angle = ((+m.angle || 45) * Math.PI) / 180; // chains in plan, to the arm
  const loss = C.CHAIN.corrosion * life;
  const submerged = 1 - 1025 / 7850;
  const cases = loads.map((L) => {
    const Hy = L.dirs.Y.total / n, Hx = L.dirs.X.total / n;
    // one chain of the crossed pair takes the load: its horizontal tension resolves both components
    const H = Math.max(Hy / Math.sin(angle), Hx / Math.cos(angle));
    const h = L.level - T - (+p.site.seabed);
    return { combo: L.combo, level: L.level, h, H, Hx, Hy };
  });
  const sizes = m.chainD ? [+m.chainD] : C.CHAIN.sizes;
  let pick = null;
  for (const d of sizes) {
    const dEnd = d - loss, w = (C.CHAIN.mass(d) * G * submerged) / 1000;
    const mbl = C.CHAIN.mbl(Math.max(1, dEnd));
    const rows = cases.map((c) => ({ ...c, ...catenary(c.h, c.H, w) }));
    const gov = rows.reduce((a, r) => (r.T > a.T ? r : a), rows[0]);
    pick = { d, dEnd, w, mbl, rows, gov };
    if (mbl / gov.T >= C.CHAIN.fos) break;
  }
  const { d, dEnd, w, mbl, rows, gov } = pick;
  const grounded = Math.max(5, 0.3 * gov.s);
  const chainLen = Math.ceil((Math.max(...rows.map((r) => r.s)) + grounded) * 2) / 2;
  const radius = Math.max(...rows.map((r) => r.x)) + grounded;
  checks.push(check("Moorings", "Chain tension (MBL / FOS)", gov.T, mbl / C.CHAIN.fos, {
    unit: "kN", src: C.CHAIN.src,
    working: [
      `${n} mooring points along ${fx(lay.walkLen, 1)} m, each with two chains crossed at ${fx((angle * 180) / Math.PI, 0)}° to the arm`,
      `Governing: ${gov.combo.name}, level ${fx(gov.level, 2)} m CD; fairlead under the pontoon ${fx(gov.h, 2)} m above the seabed`,
      `Per point: across ${fx(gov.Hy, 2)} kN, along ${fx(gov.Hx, 2)} kN → chain horizontal tension H = max(Hy/sin α, Hx/cos α) = ${fx(gov.H, 2)} kN`,
      `Chain Ø${d} mm studless R3, ${fx(C.CHAIN.mass(d), 1)} kg/m, submerged w = ${fx(w, 3)} kN/m; corrosion ${fx(C.CHAIN.corrosion, 2)} mm/yr × ${life} yr → Ø${fx(dEnd, 1)} mm at end of life`,
      `Catenary to touch-down: s = √(h² + 2hH/w) = ${fx(gov.s, 2)} m, T = H + wh = ${fx(gov.T, 2)} kN`,
      `MBL(Ø${fx(dEnd, 1)}) = 0.0223 d²(44 − 0.08d) = ${fx(mbl, 0)} kN; MBL / ${C.CHAIN.fos} = ${fx(mbl / C.CHAIN.fos, 1)} kN`,
    ],
  }));
  checks.push(check("Moorings", "Chain lies on the seabed at the anchor", chainLen - gov.s, 0, {
    unit: "m", sense: "min", src: "Catenary: horizontal pull only at the anchor block",
    working: [`Chain length ${fx(chainLen, 1)} m (longest suspended length + ${fx(grounded, 1)} m on the bed); anchor ${fx(radius, 1)} m from the fairlead in plan`],
  }));
  // dead-weight anchor block: slides on the seabed
  const mu = C.ANCHOR.mu[p.piles.soil.type === "clay" ? "clay" : "sand"];
  const Wsub = (C.ANCHOR.fos * gov.H) / mu;
  const vol = Wsub / (C.ANCHOR.gammaC - gw);
  const side = Math.ceil(Math.cbrt(vol) * 10) / 10;
  checks.push(check("Moorings", "Anchor block sliding", gov.H, (mu * (side ** 3) * (C.ANCHOR.gammaC - gw)) / C.ANCHOR.fos, {
    unit: "kN", src: C.ANCHOR.src,
    working: [`Required submerged weight W' = FOS·H/μ = ${C.ANCHOR.fos} × ${fx(gov.H, 2)} / ${mu} = ${fx(Wsub, 1)} kN`, `Concrete block ${fx(side, 1)} m cube (${fx(side ** 3 * C.ANCHOR.gammaC / G, 1)} t in air)`],
  }));
  // the hanging chain is weight on the pontoon
  const walk = floats.walkway, sec = walk.sec;
  const b = waterplane(sec.rects, walk.ini.T).b * sec.cover;
  const hMax = levels.MAX - T - (+p.site.seabed);
  const Vstatic = 2 * w * hMax * n / lay.walkLen;     // kN/m along the walkway
  const dT = Vstatic / (gw * b);
  const reserve = walk.checks.find((c) => c.name.startsWith("Reserve buoyancy"));
  const resid = (reserve?.value ?? 0) - dT;
  checks.push(check("Moorings", "Reserve buoyancy with the hanging chains", resid, C.FREEBOARD.reserve, {
    unit: "m", sense: "min", src: "AS 3962 Cl 4.7.1(b) with the chain weight",
    working: [`Two chains per point hanging ${fx(hMax, 2)} m at the maximum level: ${fx(2 * w * hMax, 2)} kN per point → ${fx(Vstatic, 3)} kN/m`, `Extra draft ${fx(dT * 1000, 1)} mm; reserve ${fx(reserve?.value ?? 0, 4)} − ${fx(dT, 4)} = ${fx(resid, 4)} m`],
  }));
  // horizontal stiffness of the crossed pair at a quarter of the governing load (for the sway period)
  const H0 = Math.max(0.5, gov.H / 4);
  const xOf = (H) => chainLen - catenary(gov.h, H, w).s + catenary(gov.h, H, w).x;
  const dH = H0 * 0.05, kc = dH / (xOf(H0 + dH) - xOf(H0));
  const stiffness = 2 * kc * n; // both chains of each pair, all points
  return { type: "chains", n, d, dEnd, w, mbl, rows, gov, chainLen, radius, grounded, block: { side, Wsub, mu }, checks, stiffness, angle, Vstatic };
}
