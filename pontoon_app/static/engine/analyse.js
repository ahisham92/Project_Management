// The whole design: from a project to every check, with its working.
//
// Every check carries the clause it answers, the value, the limit, the ratio and the
// lines of working with the numbers substituted, so the Report can be followed by hand.

import * as C from "./codes.js";
import { complete, layoutOf, returnPeriod } from "./project.js";
import { section, KIND_NAMES } from "./model.js";
import { initial, equilibrium, above, uprightDraft, immersed, waterplane, waveNumber, froudeKrylovX, macagnoKt, G } from "./hydro.js";
import { beamWinkler, modes } from "./fe.js";
import { steelCHS, concreteSection, barsSquare, barsCircle, timberRound } from "./members.js";
import { broms, requiredEmbedment, pileResponse } from "./geotech.js";
import { connections, pileGuides, gangwayDesign, seismicBasis, designCoefficient, as4997, mooringDesign } from "./extras.js";

const r2 = (v) => Math.round(v * 100) / 100, r3 = (v) => Math.round(v * 1000) / 1000;
const fx = (v, d = 2) => (Number.isFinite(v) ? (+v.toFixed(d)).toString() : "–");
const mm = (m) => `${Math.round(m * 1000)} mm`;

function check(group, name, value, limit, { unit = "", sense = "max", src = "", working = [], note = "", key } = {}) {
  // sense "max": value must not exceed limit; "min": value must reach limit
  let ratio = null, pass = true;
  if (limit !== null && limit !== undefined && Number.isFinite(value)) {
    if (sense === "max") { ratio = limit > 0 ? value / limit : value > 0 ? Infinity : 0; pass = value <= limit * (1 + 1e-9); }
    else { ratio = value > 0 ? limit / value : Infinity; pass = value >= limit * (1 - 1e-9); }
  } else if (!Number.isFinite(value)) pass = false;
  return { key: key || `${group}:${name}`, group, name, value, limit, unit, sense, ratio, pass, src, working, note };
}

// ------------------------------------------------------------------ floating behaviour

function floating(el, p, gw, acc) {
  const sec = el.sec, B = el.B, L = el.L, checks = [];
  const gwE = gw * sec.cover; // floats cover part of the length: buoyancy per metre scales with it
  const w = sec.w, zg = sec.zg;
  const ini = initial(sec.rects, w, zg, gwE);
  const fbDL = sec.deck - ini.T, ftopDL = sec.top - ini.T;
  const out = { el: el.key, name: el.name, B, L, sec, ini, checks };
  out.freeboardDL = fbDL;
  if (ini.sinks) { checks.push(check(el.name, "Floats under dead load", 0, 1, { sense: "min", src: "AS 3962 Cl 4.7", working: ["The dead load exceeds the buoyancy: the pontoon sinks."] })); return out; }

  checks.push(check(el.name, "Freeboard under dead load", fbDL, null, {
    unit: "m", src: "AS 3962 Cl 4.7.1",
    working: [
      `Dead load w = ${fx(w, 3)} kN/m (${sec.breakdown.map(([n, v]) => `${n} ${fx(v, 3)}`).join(" + ")})`,
      `Draft T = w / (γw · b · c) = ${fx(w, 3)} / (${fx(gw, 3)} × ${fx(ini.wp.b, 3)} × ${fx(sec.cover, 2)}) = ${fx(ini.T, 4)} m`,
      `Freeboard F = deck − T = ${fx(sec.deck, 3)} − ${fx(ini.T, 4)} = ${fx(fbDL, 4)} m`,
    ],
  }));
  if (p.design.freeboardSet === "tmr") {
    checks.push(check(el.name, "Freeboard ≥ 375 mm (TMR)", fbDL, C.FREEBOARD.tmr.min, { unit: "m", sense: "min", src: C.FREEBOARD.tmr.src }));
    checks.push(check(el.name, "Freeboard ≤ 500 mm (TMR)", fbDL, C.FREEBOARD.tmr.max, { unit: "m", src: C.FREEBOARD.tmr.src }));
  }
  // Cl 4.7.1(b) flotation load over the whole deck: 50 mm reserve buoyancy
  const qf = acc.flotation, wf = w + qf * B;
  const Tf = uprightDraft(sec.rects, wf, gwE);
  const reserve = Tf.sinks ? -1 : sec.top - Tf.T;
  checks.push(check(el.name, "Reserve buoyancy under flotation load", reserve, C.FREEBOARD.reserve, {
    unit: "m", sense: "min", src: "AS 3962 Cl 4.7.1(b), Table 4.1",
    working: [
      `Flotation load ${fx(qf, 1)} kPa over the full width: w + q·B = ${fx(w, 3)} + ${fx(qf, 1)} × ${fx(B, 2)} = ${fx(wf, 3)} kN/m`,
      `Draft ${fx(Tf.T, 4)} m; top of flotation ${fx(sec.top, 3)} m; reserve = ${fx(reserve, 4)} m ≥ 0.050 m`,
    ],
  }));
  // Cl 4.13 stability load over half the width, at the deck
  const qs = acc.stability, ws = qs * (B / 2);
  const W = w + ws, yg = (ws * (B / 4)) / W, zgS = (w * zg + ws * sec.deck) / W;
  const eq = equilibrium(sec.rects, W, yg, zgS, gwE);
  out.stability = eq;
  const yHi = Math.max(...sec.rects.map((r) => r.y1)), yLo = Math.min(...sec.rects.map((r) => r.y0));
  const lowTop = above([yHi, sec.top], eq.theta, eq.h);           // top of flotation on the loaded side
  const highChine = above([yLo, 0], eq.theta, eq.h);              // underside on the other side
  const deckEdge = above([B / 2, sec.deck], eq.theta, eq.h);
  const tilt = (eq.theta * 180) / Math.PI;
  out.tilt = tilt; out.deckEdge = deckEdge;
  const iniS = initial(sec.rects, W, zgS, gwE);
  const stabWork = [
    `Stability load ${fx(qs, 1)} kPa on half the width: ${fx(qs, 1)} × ${fx(B / 2, 3)} = ${fx(ws, 3)} kN/m at y = B/4 = ${fx(B / 4, 3)} m`,
    `W = ${fx(W, 3)} kN/m, centre of gravity y = ${fx(yg, 4)} m, KG = ${fx(zgS, 4)} m`,
    `Upright: KB = ${fx(iniS.KB, 4)}, BM = I/∇ = ${fx(iniS.wp.I, 4)} / ${fx(iniS.V, 4)} = ${fx(iniS.BM, 4)}, GM = KB + BM − KG = ${fx(iniS.GM, 4)} m`,
    `Exact heeled equilibrium (immersed polygon, buoyancy = weight, B under G): θ = ${fx(tilt, 3)}°`,
    `Small-angle estimate: tan θ = W·y / (W·GM) = ${fx(yg, 4)} / ${fx(iniS.GM, 4)} → ${fx(Math.atan(yg / iniS.GM) * 180 / Math.PI, 3)}°`,
    `Top of flotation on the loaded side is ${fx(lowTop, 4)} m above the water; the far chine is ${fx(-highChine, 4)} m under it`,
  ];
  if (eq.capsized || iniS.GM <= 0) {
    checks.push(check(el.name, "Stable under stability load", 0, 1, { sense: "min", src: "AS 3962 Cl 4.13, Appendix A", working: [...stabWork, "GM ≤ 0 or no equilibrium: unstable."] }));
  } else {
    checks.push(check(el.name, "Freeboard to flotation, stability load", lowTop, C.FREEBOARD.stabilityMin, { unit: "m", sense: "min", src: "AS 3962 Cl 4.13.2.1, Table 4.1", working: stabWork }));
    if (p.design.chine !== false) checks.push(check(el.name, "Opposite chine stays submerged", -highChine, 0, { unit: "m", sense: "min", src: "AS 3962 Cl 4.13.1, 4.13.2.1", working: [`Depth of the far chine below water ${fx(-highChine, 4)} m > 0`] }));
    out.chine = -highChine;
    if (+p.design.tiltLimit > 0) checks.push(check(el.name, "Tilt under stability load (project limit)", tilt, +p.design.tiltLimit, { unit: "°", src: "Project criterion" }));
  }
  out.GM = ini.GM;
  if (!(ini.GM > 0)) {
    checks.push(check(el.name, "Upright stability (GM > 0)", ini.GM, 0, { unit: "m", sense: "min", src: "AS 3962 Cl 4.13.1, Appendix A", working: [`GM = KB + BM − KG = ${fx(ini.KB, 4)} + ${fx(ini.BM, 4)} − ${fx(zg, 4)} = ${fx(ini.GM, 4)} m`] }));
    out.advice = [];
    return out;
  }
  // concentrated 4.5 kN at a corner: rigid roll + beam-on-water pitch/bending
  const P = C.DECK_LIVE.point, kW = gwE * ini.wp.b;
  const lon = beamWinkler({ L, EI: sec.EI, k: kW, n: 60 }, [{ x: L, P }]);
  const wTip = lon.w[lon.w.length - 1];
  const roll = Math.atan((P * (B / 2)) / (w * L * ini.GM));
  const drop = wTip + (B / 2) * Math.tan(roll);
  const corner = ftopDL - drop;
  checks.push(check(el.name, "Freeboard to flotation, 4.5 kN at a corner", corner, C.FREEBOARD.stabilityMin, {
    unit: "m", sense: "min", src: "AS 3962 Cl 4.7.2(c), 4.13.2.1",
    working: [
      `Beam on the water: k = γw·b·c = ${fx(kW, 2)} kN/m², EI = ${fx(sec.EI, 0)} kN·m², L = ${fx(L, 2)} m; end deflection under 4.5 kN = ${fx(wTip * 1000, 1)} mm`,
      `Roll: tan φ = P·(B/2) / (W·GM) = 4.5 × ${fx(B / 2, 3)} / (${fx(w * L, 1)} × ${fx(ini.GM, 3)}) → edge drop ${fx((B / 2) * Math.tan(roll) * 1000, 1)} mm`,
      `Flotation top at the corner: ${fx(ftopDL, 4)} − ${fx(drop, 4)} = ${fx(corner, 4)} m`,
    ],
  }));
  out.advice = [];
  if (fbDL > C.FREEBOARD.responseCheck.freeboard && ini.T < C.FREEBOARD.responseCheck.draft)
    out.advice.push({ src: "AS 3962 Cl 4.13.2.3", text: `${el.name}: freeboard ${mm(fbDL)} with a draft of ${mm(ini.T)}. Check how quickly it responds to cyclic vertical load (people walking, wash).` });
  if (fbDL > C.FREEBOARD.waterAccess)
    out.advice.push({ src: "AS 3962 Cl 5.1.2", text: `${el.name}: freeboard over 500 mm, so provide a way to climb out of the water without help (ladders).` });
  out.GM = ini.GM; out.kW = kW; out.cornerLoad = { wTip, roll, corner };
  return out;
}

// ------------------------------------------------------------------ pontoon structure

function structure(el, p, gw, site, depthHAT) {
  const sec = el.sec, L = el.L, B = el.B, checks = [];
  const kW = gw * sec.cover * waterplane(sec.rects, initial(sec.rects, sec.w, sec.zg, gw * sec.cover).T).b;
  const beam = { L, EI: sec.EI, k: kW, n: 80 };
  const env = (r) => r.M.reduce((a, m) => Math.max(a, Math.abs(m)), 0);
  const envV = (r) => r.V.reduce((a, v) => Math.max(a, Math.abs(v)), 0);
  // live: 3 kPa on either half; 4.5 kN at mid-length and at an end
  const q = C.DECK_LIVE.udl * B;
  const live = [
    beamWinkler(beam, [], (x) => (x <= L / 2 ? q : 0)),
    beamWinkler(beam, [{ x: L / 2, P: C.DECK_LIVE.point }]),
    beamWinkler(beam, [{ x: L / 4, P: C.DECK_LIVE.point }]),
  ];
  const Mlive = Math.max(...live.map(env)), Vlive = Math.max(...live.map(envV));
  // waves: H1 crest-to-trough passing along the pontoon (head seas), phase scanned
  const H1 = C.WAVE_DESIGN.H1overHs * +site.Hs, k = waveNumber(+site.Tp, depthHAT), lam = (2 * Math.PI) / k;
  let Mwave = 0, Vwave = 0, worst = null;
  for (let i = 0; i < 16; i++) {
    const x0 = (lam * i) / 16;
    const r = beamWinkler(beam, [], (x) => kW * (H1 / 2) * Math.cos(k * (x - x0)));
    const m = env(r);
    if (m > Mwave) { Mwave = m; worst = { x0, r }; }
    Vwave = Math.max(Vwave, envV(r));
  }
  const Mstar = Math.max(1.5 * Mlive, 1.5 * Mwave), Vstar = Math.max(1.5 * Vlive, 1.5 * Vwave);
  const out = { el: el.key, Mlive, Mwave, Mstar, Vstar, H1, lam, worst, checks, live };
  const working = [
    `Beam on the water: k = ${fx(kW, 2)} kN/m², EI = ${fx(sec.EI, 0)} kN·m², L = ${fx(L, 2)} m, free ends`,
    `Live (AS 3962 Cl 4.7.2): 3 kPa on half the length, or 4.5 kN at L/2 or L/4 → M = ${fx(Mlive, 2)} kN·m, V = ${fx(Vlive, 2)} kN`,
    `Wave (Cl 4.8.2.2): H1 = 1.67 Hs = ${fx(H1, 3)} m, Tp ${fx(+site.Tp, 1)} s, depth ${fx(depthHAT, 2)} m → λ = ${fx(lam, 2)} m; worst phase M = ${fx(Mwave, 2)} kN·m`,
    `M* = max(1.5 M_live, 1.5 M_wave) = ${fx(Mstar, 2)} kN·m (AS/NZS 1170.0 Cl 4.2.2; AS 3962 Cl 4.2(b) 1.5 × vertical wave effect); V* = ${fx(Vstar, 2)} kN`,
  ];
  if (p.type === "concrete" || p.type === "attenuator" || (el.key === "finger" && sec.parts.kind === "concrete")) {
    const s = { ...p.section, ...(el.sectionOverride || {}) };
    const P = sec.parts, fc = +s.fc || 40, As = (+s.mesh || 252) * B, cov = (+s.meshCover || 30) + 4;
    const shape = { kind: "box", B: B * 1000, D: P.D * 1000, tw: P.tw * 1000, tt: P.td * 1000, tb: P.tb * 1000 };
    const yb = P.D * 500 - cov;
    const cs = concreteSection({ shape, fc, bars: [{ y: yb, As }, { y: -yb, As }] });
    const mu = cs.phiMu(0), vu = cs.phiVuc(2 * P.tw * 1000, P.D * 1000 - cov);
    out.phiMu = mu.phiMu; out.phiVuc = vu;
    checks.push(check(el.name, "Longitudinal bending of the shell", Mstar, mu.phiMu, {
      unit: "kN·m", src: "AS 3600 Cl 8.1, Table 2.2.2",
      working: [...working,
        `Box ${mm(B)} × ${mm(P.D)}, deck ${mm(P.td)}, base ${mm(P.tb)}, walls ${mm(P.tw)}; mesh ${fx(+s.mesh, 0)} mm²/m top and bottom (As = ${fx(As, 0)} mm²), f'c ${fc} MPa`,
        `Strain compatibility, α2 = ${fx(C.CONCRETE.alpha2(fc), 3)}, γ = ${fx(C.CONCRETE.gamma(fc), 3)}: dn = ${fx(mu.dn, 1)} mm, kuo = ${fx(mu.kuo, 3)}, φ = ${fx(mu.phi, 3)}, φMu = ${fx(mu.phiMu, 2)} kN·m`],
    }));
    checks.push(check(el.name, "Longitudinal shear in the walls", Vstar, vu, {
      unit: "kN", src: "AS 3600 Cl 8.2.4 (kv = 200/(1000+1.3dv) ≤ 0.10)",
      working: [`bv = 2 × ${mm(P.tw)}, dv = max(0.72D, 0.9d); φVuc = ${fx(vu, 2)} kN`],
    }));
  } else if (p.type === "framed") {
    const Mr = +p.section.frameMr || 60;
    checks.push(check(el.name, "Frame bending (supplier capacity)", Mstar, Mr, { unit: "kN·m", src: "Supplier's φMb for the frame (AS/NZS 1664 / AS 4100 / AS 1720.1)", working }));
  } else {
    checks.push(check(el.name, "Mat bending (design actions)", Mstar, null, { unit: "kN·m", src: "Supplier to confirm the cube connectors", working }));
  }
  return out;
}

// ------------------------------------------------------------------ environmental loads

function windSpeed(p, Rsls) {
  const R = Rsls || (p.site.basis === "as3962" ? 50 : returnPeriod(p));
  const VR = C.regionalSpeed(p.site.region, R);
  const Mz = C.interp(C.MZCAT_TC2, 3);
  const V = VR * (+p.site.Md || 1) * Mz * (+p.site.Ms || 1) * (+p.site.Mt || 1) * (+p.site.duration || 1);
  return { R, VR, Mz, V, q: 0.0006 * V * V };
}

/** Lateral loads on the arm for one combination, both directions, per arm and per pile. */
function armLoads(p, lay, floats, combo, levels, gw, wind) {
  const v = lay.v, rho = p.water === "fresh" ? C.WATER.fresh : C.WATER.sea;
  const level = levels[combo.level];
  const depth = level - +p.site.seabed;
  const walk = floats.walkway, T = walk.ini.T, F = walk.freeboardDL;
  const Lw = lay.walkLen, nB = lay.perSide, sides = lay.sides;
  const Vc = Math.max(+p.site.current, C.CURRENT_MIN.v);
  const pc = (0.5 * rho * Vc * Vc) / 1000; // kPa per unit CD
  const q = wind.q;
  const lines = [];
  // --- across the arm (Y): boats bow/stern on, all exposed
  const fingerF = floats.finger.freeboardDL;
  const windY = q * (C.CD_WIND.vesselBeam * v.windHead * nB * sides + C.CD_WIND.rectangular * F * Lw);
  const boatCurY = pc * C.CD_CURRENT.vesselBow * v.beam * v.hullDraft * nB * sides;
  const pontoonCurY = Math.max(
    p.site.debris ? pc * C.CD_CURRENT.debris * C.DEBRIS.depthFactor * T * Lw : 0,
    pc * C.CD_CURRENT.squareSharp * T * Lw,
    p.site.debris ? C.DEBRIS.minForce * Lw : 0,
  );
  const Hwave = C.WAVE_DESIGN.H1overHs * +p.site.Hs;
  const fk = froudeKrylovX(gw, Hwave, +p.site.Tp, depth, lay.walkW, T);
  const waveY = Math.max(C.WAVE_MIN.force, fk) * Lw;
  // --- along the arm (X): boats beam on, windward boat full and 20 % on each one behind it
  const shelter = 1 + C.WIND.leeward * (nB - 1);
  const windX = q * (C.CD_WIND.vesselBeam * v.windBeam * shelter * sides + C.CD_WIND.rectangular * F * lay.walkW + C.CD_WIND.rectangular * fingerF * lay.fingerL * 0);
  const keel = v.motor ? 0 : C.CD_CURRENT.vesselBeamKeel * (v.draught - v.hullDraft) * 0.25 * v.L;
  const boatCurX = pc * (C.CD_CURRENT.vesselBeamHull * v.Lwl * v.hullDraft + keel) * shelter * sides;
  const pontoonCurX = pc * C.CD_CURRENT.squareSharp * T * lay.walkW;
  const waveX = Math.max(C.WAVE_MIN.force, froudeKrylovX(gw, Hwave, +p.site.Tp, depth, lay.fingerL, floats.finger.ini.T)) * (lay.fingerW * nB * sides + lay.walkW);
  const dirs = {
    Y: { wind: windY, current: boatCurY + pontoonCurY, wave: waveY },
    X: { wind: windX, current: boatCurX + pontoonCurX, wave: waveX },
  };
  for (const d of Object.values(dirs)) d.total = combo.wind * d.wind + combo.current * d.current + combo.wave * d.wave;
  return { level, depth, Vc, pc, dirs, parts: { windY, boatCurY, pontoonCurY, waveY, windX, boatCurX, pontoonCurX, waveX, fk, Hwave, shelter } };
}

// ------------------------------------------------------------------ piles

function pileSection(pp, life) {
  if (pp.type === "concrete") {
    const c = pp.concrete, fc = +c.fc || 50;
    const shape = c.shape === "round" ? { kind: "circle", D: +c.b, Di: +c.Di || 0 } : { kind: "rect", b: +c.b, h: +c.b };
    const bars = c.shape === "round" ? barsCircle(+c.b, +c.cover, +c.bars, +c.db) : barsSquare(+c.b, +c.cover, +c.bars, +c.db);
    const cs = concreteSection({ shape, bars, fc });
    const mu = cs.phiMu(0);
    const Ec = C.CONCRETE.Ec(fc);
    const I = c.shape === "round" ? (Math.PI / 64) * ((+c.b) ** 4 - (+c.Di || 0) ** 4) : (+c.b) ** 4 / 12;
    const Icr = 0.5 * I; // cracked: half the gross (AS 3600 Cl 6.2.4 style estimate for piles in flexure)
    return {
      kind: "concrete", D: +c.b / 1000, phiM: mu.phiMu, Mn: mu.Mu, phiV: cs.phiVuc(c.shape === "round" ? 0.9 * +c.b : +c.b, 0.85 * +c.b),
      EI: (Ec * Icr) / 1e9, mass: (cs.area / 1e6) * 2.5, desc: `${c.shape === "round" ? "Ø" : ""}${c.b}${c.shape === "round" ? "" : ` × ${c.b}`} mm precast, ${c.bars}N${c.db}, f'c ${fc} MPa, cover ${c.cover} mm`,
      work: [`Strain compatibility (AS 3600 Cl 8.1.3): φMu = ${fx(mu.phiMu, 1)} kN·m (φ = ${fx(mu.phi, 3)}, kuo = ${fx(mu.kuo, 3)})`, `Cover ${c.cover} mm: exposure C2 (tidal/splash) needs 65 mm at f'c 50 MPa (AS 3600 Table 4.10.3.2)`],
      coverOK: +c.cover >= (fc >= 50 ? 65 : 999),
    };
  }
  if (pp.type === "timber") {
    const t = pp.timber, tr = timberRound({ D: +t.D, grade: t.grade, phi: +t.phi || C.TIMBER.phi });
    return {
      kind: "timber", D: +t.D / 1000, phiM: tr.phiM, Mn: tr.phiM / (+t.phi || C.TIMBER.phi), phiV: tr.phiV, EI: tr.EI, mass: (tr.A / 1e6) * 1.1,
      desc: `Ø${t.D} mm round timber, ${t.grade}`, work: [`φMd = φ k1 f'b Z = ${fx(+t.phi || C.TIMBER.phi, 2)} × 1.0 × ${tr.grade.fb} × ${fx(tr.Z / 1e6, 4)}e6 mm³ = ${fx(tr.phiM, 1)} kN·m (AS 1720.1 Cl 3.2.1)`],
    };
  }
  // steel CHS with corrosion loss over the design life (outside face)
  const lifeKey = [5, 25, 50, 75, 100].find((y) => life <= y) || 100;
  const loss = +pp.coating > 0 ? 0 : C.CORROSION.splash[lifeKey];
  const t = Math.max(1, +pp.t - loss), d = +pp.d - 2 * loss;
  const s = steelCHS({ d, t, grade: pp.grade });
  const s0 = steelCHS({ d: +pp.d, t: +pp.t, grade: pp.grade });
  return {
    kind: "steel", D: +pp.d / 1000, phiM: s.phiMs, Mn: s.phiMs / 0.9, phiV: s.phiVv, EI: s0.EI, mass: (s0.props.A / 1e6) * 7.85,
    desc: `CHS ${pp.d} × ${pp.t} ${C.STEEL.grades[pp.grade]?.name || pp.grade}`, steel: s, loss, tEnd: t, dEnd: d,
    work: [
      `Corrosion loss ${fx(loss, 2)} mm on the outside over ${life} years (${+pp.coating > 0 ? "protected by coating/sleeve" : C.CORROSION.src}) → ${fx(d, 1)} × ${fx(t, 2)} mm at end of life`,
      `fy = ${s.fy} MPa; λs = (d/t)(fy/250) = ${fx(s.ls, 1)} → ${s.cls} (AS 4100 Table 5.2: λsp 50, λsy 120); Ze = ${fx(s.Ze / 1e3, 0)} × 10³ mm³`,
      `φMs = 0.9 fy Ze = ${fx(s.phiMs, 1)} kN·m; φVv = 0.9 × 0.36 fy Ae = ${fx(s.phiVv, 1)} kN (AS 4100 Cl 5.11.4)`,
    ],
  };
}

function pileDesign(p, lay, floats, loads, levels, gw, berth, ctx = {}) {
  const pp = p.piles, life = +p.site.life || 25;
  const ps = pileSection(pp, life);
  const n = Math.max(2, Math.ceil(lay.walkLen / Math.max(2, +pp.spacing)) + 1);
  const phiG = C.phiGb(+pp.arr || 2.5, pp.redundancy === "high");
  const scour = +p.site.scour || 0, ground = +p.site.seabed - scour;
  const soil = pp.soil, D = ps.D;
  const rho = p.water === "fresh" ? C.WATER.fresh : C.WATER.sea;
  const cases = [];
  for (const L of loads) {
    const lv = L.level, Fb = floats.walkway.freeboardDL + +pp.guideAbove;
    const e = lv + Fb - ground;       // load at the pontoon's guide, measured from the scoured bed
    const depth = lv - ground;
    // current and waves on the pile itself (AS 3962 Table 4.5 rough circular pile CD 1.4)
    const fc = L.combo.current * (0.5 * rho * L.Vc ** 2 / 1000) * C.CD_CURRENT.pileRough * D; // kN/m
    const Hp = Math.max(...Object.values(L.dirs).map((d) => d.total)) / n;
    const dirKey = L.dirs.X.total > L.dirs.Y.total ? "X" : "Y";
    cases.push({ combo: L.combo, level: lv, e, depth, Hhead: Hp, qPile: fc, dir: dirKey, arm: L });
  }
  // berthing: AS 3962 Cl 4.9, perpendicular strike at the mid-point, attached water mass
  const v = lay.v;
  for (const bc of C.COMBOS.filter((c) => c.berthing)) {
    const lv = levels[bc.level];
    const e = lv + floats.walkway.freeboardDL + +pp.guideAbove - ground;
    cases.push({ combo: bc, level: lv, e, depth: lv - ground, berthing: true });
  }
  // earthquake (AS 1170.4): the arm sways on its piles; G + Eu (AS/NZS 1170.0 Cl 4.2.2(f)), at HAT
  if (ctx.eq) {
    const lv = levels.HAT, e = lv + floats.walkway.freeboardDL + +pp.guideAbove - ground;
    const pileMass = ps.mass + rho / 1000 * Math.PI * D * D / 4 * 2; // t/m: pile + entrained + added water
    const qEq = C.spectralShape(ctx.eq.site, 0.3) * ctx.eq.kpZ * ctx.eq.Sp / ctx.eq.mu * pileMass * G; // plateau value: conservative
    cases.push({ combo: { key: "eq", name: "Earthquake G + Eu (HAT)", level: "HAT", src: "AS/NZS 1170.0 Cl 4.2.2(f); AS 1170.4 Cl 6.2, 7.2" }, level: lv, e, depth: lv - ground, seismic: true, qPile: qEq });
  }
  // embedment: given, or the shortest that carries every case (Broms, φg), at least 3 m
  const My = ps.phiM; // design moment capacity in the Broms mechanism (soil factored by φg)
  let Lreq = 0, embedNotes = [];
  const runBerthing = (c, Lemb) => {
    const unit = pileResponse({ e: c.e, L: Lemb, EI: ps.EI, soil, H: 1, D });
    const kp = unit.stiffness;
    const engaged = Math.max(1, Math.min(n, Math.round(lay.moduleL / Math.max(2, +pp.spacing)) + 1));
    const kf = +p.fender.k || 400;
    const keq = 1 / (1 / kf + 1 / (engaged * kp));
    const Ff = Math.sqrt(2 * berth.E * keq); // kN
    return { kp, engaged, keq, F: Ff, Hpile: (c.combo.berthing * Ff) / engaged };
  };
  const runSeismic = (c, Lemb) => {
    const unit = pileResponse({ e: c.e, L: Lemb, EI: ps.EI, soil, H: 1, D });
    const T = 2 * Math.PI * Math.sqrt(ctx.eq.mass / (n * unit.stiffness));
    const Cd = designCoefficient(ctx.eq, T);
    return { T, Cd, Hpile: (Cd * ctx.eq.mass * G) / n, kp: unit.stiffness };
  };
  const headOnly = (c, Lemb) => (c.berthing ? runBerthing(c, Lemb).Hpile : c.seismic ? runSeismic(c, Lemb).Hpile : c.Hhead);
  const headLoad = (c, Lemb) => headOnly(c, Lemb) + (c.berthing ? 0 : c.qPile * c.depth);
  const leverOf = (c, Lemb) => { const h = headOnly(c, Lemb); return c.berthing ? c.e : (h * c.e + c.qPile * c.depth * (c.depth / 2)) / (h + c.qPile * c.depth); };
  if (+pp.embed > 0) Lreq = +pp.embed;
  else {
    let Lg = 6;
    for (let it = 0; it < 6; it++) {
      let need = 3;
      for (const c of cases) {
        const H = headLoad(c, Lg);
        const r = requiredEmbedment(soil, { e: leverOf(c, Lg), D, My, phiG, Hstar: H });
        if (r.L === null) { embedNotes.push(r.reason); need = Math.max(need, 30); } else need = Math.max(need, r.L);
      }
      need = Math.ceil(need * 2) / 2;
      if (Math.abs(need - Lg) < 1e-9) break;
      Lg = need;
    }
    Lreq = Lg;
  }
  const checks = [];
  const results = cases.map((c) => {
    const H = headLoad(c, Lreq), e = leverOf(c, Lreq);
    const bInfo = c.berthing ? runBerthing(c, Lreq) : null;
    const eInfo = c.seismic ? runSeismic(c, Lreq) : null;
    if (eInfo) c.Hhead = eInfo.Hpile;
    // one solve: the load at the guide plus the pile's own drag over the water column
    const resp = c.berthing
      ? pileResponse({ e: c.e, L: Lreq, EI: ps.EI, soil, H, D })
      : pileResponse({ e: c.e, L: Lreq, EI: ps.EI, soil, H: c.Hhead, D, q: c.qPile, qFrom: c.e - c.depth, qTo: c.e });
    const Mmax = resp.Mmax;
    const g = broms(soil, { e, L: Lreq, D, My }, phiG);
    return { ...c, H, lever: e, resp, Mmax, Vmax: H, bInfo, eInfo, brom: g, geoRatio: H / g.Hu };
  });
  const gov = results.reduce((a, r) => (r.Mmax > a.Mmax ? r : a), results[0]);
  const govGeo = results.reduce((a, r) => (r.geoRatio > a.geoRatio ? r : a), results[0]);
  const govDef = results.reduce((a, r) => (Math.abs(r.resp.delta) > Math.abs(a.resp.delta) ? r : a), results[0]);
  checks.push(check("Piles", "Pile bending", gov.Mmax, ps.phiM, {
    unit: "kN·m", src: ps.kind === "steel" ? "AS 4100 Cl 5.1, 5.2" : ps.kind === "concrete" ? "AS 3600 Cl 8.1, 10.7" : "AS 1720.1 Cl 3.2",
    working: [
      `${ps.desc}; ${n} piles along ${fx(lay.walkLen, 1)} m at ${fx(+pp.spacing, 1)} m centres`,
      `Governing: ${gov.combo.name}. Level ${fx(gov.level, 2)} m CD, scoured bed ${fx(ground, 2)} m, load at the guide e = ${fx(gov.e, 2)} m above the bed`,
      gov.seismic
        ? `Earthquake: arm mass ${fx(ctx.eq.mass, 1)} t on ${n} piles, sway T = ${fx(gov.eInfo.T, 2)} s; Cd = Ch(T)·kpZ·Sp/μ = ${fx(gov.eInfo.Cd, 4)} (site ${ctx.eq.site}, kpZ ${fx(ctx.eq.kpZ, 3)}) → ${fx(gov.eInfo.Hpile, 2)} kN per pile + pile inertia ${fx(gov.qPile, 3)} kN/m`
        : gov.berthing
        ? `Berthing: E = ${fx(berth.E, 2)} kJ, pile stiffness ${fx(gov.bInfo.kp, 1)} kN/m × ${gov.bInfo.engaged} piles in series with the fender ${fx(+p.fender.k, 0)} kN/m → k = ${fx(gov.bInfo.keq, 1)} kN/m; F = √(2Ek) = ${fx(gov.bInfo.F, 2)} kN; per pile × 1.25 = ${fx(gov.H, 2)} kN`
        : `H* per pile = ${fx(gov.Hhead, 2)} kN at the guide + pile drag ${fx(gov.qPile, 3)} kN/m over ${fx(gov.depth, 2)} m`,
      `Elastic pile on a Winkler subgrade (${soil.type === "clay" ? `k = 67 su = ${fx(67 * soil.su, 0)} kN/m²` : `nh for φ' ${soil.phi}°`}), embedded ${fx(Lreq, 2)} m: M* = ${fx(gov.Mmax, 2)} kN·m at ${fx(gov.resp.zMax, 2)} m below the bed`,
      ...ps.work,
    ],
  }));
  checks.push(check("Piles", "Pile shear", gov.Vmax, ps.phiV, { unit: "kN", src: ps.kind === "steel" ? "AS 4100 Cl 5.11.4" : ps.kind === "concrete" ? "AS 3600 Cl 8.2.4" : "AS 1720.1 Cl 3.2.5" }));
  checks.push(check("Piles", "Lateral ground resistance", govGeo.H, govGeo.brom.Hu, {
    unit: "kN", src: "AS 2159 Cl 4.3 (φg), Broms (1964) free-head pile",
    working: [
      `Governing: ${govGeo.combo.name}; H* = ${fx(govGeo.H, 2)} kN at e = ${fx(govGeo.lever, 2)} m above the bed`,
      `φg = φgb = ${fx(phiG, 2)} (ARR ${pp.arr}, ${pp.redundancy} redundancy, no load testing; AS 2159 Table 4.3.2(C)), applied to the soil inside the mechanism; pile at its design capacity φM = ${fx(My, 1)} kN·m`,
      `Broms ${soil.type === "clay" ? `cohesive, φg·su = ${fx(phiG * soil.su, 2)} kPa, 9·φg·su·D below 1.5D` : `cohesionless, φ' = ${soil.phi}°, Kp = ${fx(govGeo.brom.Kp, 3)}, φg·3Kpγ'Dz with γ' = ${soil.gamma} kN/m³`}: short pile Rd = ${fx(govGeo.brom.Hs, 1)} kN, long pile Rd = ${fx(govGeo.brom.Hl, 1)} kN → ${govGeo.brom.mode}`,
      +pp.embed > 0 ? `Embedment ${fx(Lreq, 2)} m as given` : `Shortest embedment that carries every case: ${fx(Lreq, 2)} m (rounded up to 0.5 m, at least 3 m)`,
      ...embedNotes,
    ],
  }));
  // serviceability (AS 4997 Cl 4.3): head deflection at the guide under the SLS environment
  let sls = null;
  if (ctx.sls && ctx.sls.length) {
    sls = ctx.sls.map((L) => {
      const e = L.level + floats.walkway.freeboardDL + +pp.guideAbove - ground, depth = L.level - ground;
      const H = Math.max(L.dirs.X.total, L.dirs.Y.total) / n;
      const q = (0.5 * rho * L.Vc ** 2 / 1000) * C.CD_CURRENT.pileRough * D;
      const resp = pileResponse({ e, L: Lreq, EI: ps.EI, soil, H, D, q, qFrom: e - depth, qTo: e });
      return { combo: L.combo, level: L.level, H, delta: Math.abs(resp.delta), e };
    });
    const g = sls.reduce((a, r) => (r.delta > a.delta ? r : a), sls[0]);
    const lim = +p.design.pileDeflection || C.SLS.pileDeflection;
    checks.push(check("Piles", "Pile deflection at the guide, serviceability", g.delta, lim, {
      unit: "m", src: C.SLS.src,
      working: [`SLS wind at 1/${C.SLS.windR} (V = ${fx(ctx.slsWind.V, 1)} m/s) with unfactored current and waves, ${g.combo.name}`, `H = ${fx(g.H, 2)} kN per pile at e = ${fx(g.e, 2)} m → δ = ${fx(g.delta * 1000, 1)} mm ≤ ${fx(lim * 1000, 0)} mm (project criterion: roller travel and gangway seating)`],
    }));
  }
  if (ps.kind === "concrete") checks.push(check("Piles", "Cover for exposure C2 (tidal/splash)", +pp.concrete.cover, +pp.concrete.fc >= 50 ? 65 : 999, { unit: "mm", sense: "min", src: "AS 3600 Table 4.3, 4.10.3.2", note: +pp.concrete.fc < 50 ? "C2 needs f'c ≥ 50 MPa." : "" }));
  // pile height (AS 3962:2020 Cl 4.14): 1 in 100 ARI level with sea level rise and wave action; the
  // pontoon must not float off the top. Wave action: the crest of the design wave, H1/2 (linear wave).
  const tmrTop = +p.site.HAT + 2.5;
  const crest = 0.5 * C.WAVE_DESIGN.H1overHs * +p.site.Hs;
  const deckMax = levels.MAX + floats.walkway.freeboardDL + crest;
  const pileTop = Math.max(deckMax + 1.0, tmrTop);
  checks.push(check("Piles", "Pile top above the 1 in 100 level with waves", pileTop - deckMax, 0.5, {
    unit: "m", sense: "min", src: "AS 3962 Cl 4.14; TMR Table 5.2 (HAT + 2.5 m)",
    working: [`Maximum level = HAT + sea level rise + storm surge (1 in 100 ARI) = ${fx(levels.MAX, 2)} m CD`, `Wave crest H1/2 = 1.67 × ${fx(+p.site.Hs, 2)} / 2 = ${fx(crest, 2)} m; deck at ${fx(deckMax, 2)} m CD on the crest`, `Pile top set at ${fx(pileTop, 2)} m CD (that + 1.0 m, and not below HAT + 2.5 m = ${fx(tmrTop, 2)} m); guide stays ≥ 0.5 m below the top`],
  }));
  return { type: "piles", ps, n, phiG, Lreq, results, gov, govGeo, govDef, checks, pileTop, toe: ground - Lreq, ground, embedNotes, sls };
}

/** Standard sizes tried, lightest first, when the pile is left to Pontoon to choose. */
export const PILE_CATALOGUE = {
  steel: [[323.9, 9.5], [355.6, 9.5], [355.6, 12.7], [406.4, 9.5], [406.4, 12.7], [457, 12.7], [508, 12.7], [559, 12.7], [610, 12.7], [610, 16], [660, 16], [711, 16], [762, 16], [813, 16], [813, 19], [914, 19], [1016, 19], [1016, 22]]
    .map(([d, t]) => ({ d, t })),
  concrete: [[350, 8, 20], [400, 8, 24], [450, 8, 24], [450, 12, 24], [500, 12, 24], [550, 12, 28], [600, 12, 32]].map(([b, bars, db]) => ({ b, bars, db })),
  timber: [300, 350, 400, 450, 500, 550, 600].map((D) => ({ D })),
};

function sizePiles(p, lay, floats, loads, levels, gw, berth, ctx) {
  const pp = p.piles;
  if (!pp.auto) return pileDesign(p, lay, floats, loads, levels, gw, berth, ctx);
  const list = PILE_CATALOGUE[pp.type] || PILE_CATALOGUE.steel;
  let last = null;
  for (const size of list) {
    const q = { ...p, piles: { ...pp, embed: null } };
    if (pp.type === "concrete") q.piles.concrete = { ...pp.concrete, ...size };
    else if (pp.type === "timber") q.piles.timber = { ...pp.timber, ...size };
    else Object.assign(q.piles, size);
    const r = pileDesign(q, lay, floats, loads, levels, gw, berth, ctx);
    last = { ...r, size, auto: true, tried: list.indexOf(size) + 1 };
    if (r.checks.every((c) => c.pass) && r.Lreq <= 30) return last;
  }
  return { ...last, autoFailed: true };
}

// ------------------------------------------------------------------ dynamics

/** Mass of one arm moving sideways (t): pontoons, boats, and the sway added mass ρπT²/2 per metre of walkway. */
function armMass(lay, floats, gw) {
  const rho = gw / G, T = floats.walkway.ini.T;
  return (floats.walkway.sec.w * lay.walkLen + floats.finger.sec.w * lay.fingerL * (lay.perSide + 1) * lay.sides) / G
    + lay.v.disp * lay.perArm + rho * Math.PI * T * T / 2 * lay.walkLen;
}

function dynamics(p, lay, floats, piles, gw) {
  const walk = floats.walkway, sec = walk.sec, rho = gw / G; // t/m³
  const B = lay.walkW, L = lay.moduleL, kW = walk.kW;
  const m = sec.w / G;                                   // t/m
  const ma = rho * (Math.PI / 8) * B * B;                // 2D heave added mass of a flat-bottomed section (half-cylinder estimate)
  const heave = 2 * Math.PI * Math.sqrt((m + ma) / kW);
  const Ixx = m * (B * B + sec.D * sec.D) / 12;          // roll inertia per metre (uniform)
  const roll = walk.GM > 0 ? 2 * Math.PI * Math.sqrt(Ixx / (m * G * walk.GM)) : Infinity;
  const md = modes({ L, EI: sec.EI, k: kW, m: m + ma, n: 30 }, 6);
  const names = ["Heave", "Pitch", "1st bending", "2nd bending", "3rd bending", "4th bending"];
  const fm = md.map((q, i) => ({ ...q, name: names[i] || `Mode ${i + 1}` }));
  // sway of the arm on its piles (or chains)
  const Marm = armMass(lay, floats, gw);
  if (piles.type === "chains") {
    const sway = 2 * Math.PI * Math.sqrt(Marm / piles.stiffness);
    const Tp = +p.site.Tp;
    const near = [{ n: "heave", T: heave }, { n: "roll", T: roll }, { n: "sway on the chains", T: sway }, ...fm.slice(2, 4).map((q) => ({ n: q.name, T: q.T }))].filter((q) => Math.abs(q.T - Tp) / Tp < 0.2);
    return { heave, roll, ma, m, flex: fm, sway, pile: null, Marm, near, kW };
  }
  const unit = pileResponse({ e: piles.gov.e, L: piles.Lreq, EI: piles.ps.EI, soil: p.piles.soil, H: 1, D: piles.ps.D });
  const sway = 2 * Math.PI * Math.sqrt(Marm / (piles.n * unit.stiffness));
  // the pile itself (cantilever on the subgrade, steel + entrained water)
  const pm = modes({
    L: piles.gov.e + piles.Lreq, EI: piles.ps.EI, m: piles.ps.mass + rho * Math.PI * piles.ps.D ** 2 / 4,
    k: (x) => { const z = x - piles.gov.e; return z <= 0 ? 0 : p.piles.soil.type === "clay" ? 67 * p.piles.soil.su : 4500 * z; }, n: 24,
  }, 3);
  const Tp = +p.site.Tp;
  const near = [{ n: "heave", T: heave }, { n: "roll", T: roll }, ...fm.slice(2, 4).map((q) => ({ n: q.name, T: q.T }))].filter((q) => Math.abs(q.T - Tp) / Tp < 0.2);
  return { heave, roll, ma, m, flex: fm, sway, pile: pm, Marm, near, kW };
}

// ------------------------------------------------------------------ main

export function analyse(input) {
  const p = complete(input);
  const t0 = Date.now();
  const rho = p.water === "fresh" ? C.WATER.fresh : C.WATER.sea;
  const gw = (rho * G) / 1000; // kN/m³
  const acc = C.FLOTATION[p.access] || C.FLOTATION.unrestricted;
  const fingerSection = { ...p.section, ...p.finger };
  const fingerKind = p.type === "attenuator" ? "concrete" : p.type;
  // widths not given: the narrowest (from the code / usual minimum, in 0.1 m steps) that meets
  // every floating check of AS 3962 — the least material that works
  let lay = layoutOf(p);
  const auto = {};
  const widest = p.type === "attenuator" ? 8 : 4;
  const fits = (kind, spec, B, L, name) => floating({ key: "trial", name, B, L, sec: section(kind, spec, B) }, p, gw, acc).checks.every((c) => c.pass);
  if (!(+p.layout.walkwayWidth > 0)) {
    let B = lay.walkW;
    while (B < widest && !fits(p.type, p.section, B, lay.moduleL, "Walkway")) B = Math.round((B + 0.1) * 10) / 10;
    auto.walkwayWidth = B;
  }
  if (!(+p.layout.fingerWidth > 0)) {
    let B = lay.fingerW;
    while (B < 3 && !fits(fingerKind, fingerSection, B, lay.fingerL, "Finger")) B = Math.round((B + 0.1) * 10) / 10;
    auto.fingerWidth = B;
  }
  if (Object.keys(auto).length) lay = { ...layoutOf({ ...p, layout: { ...p.layout, ...auto } }), auto };
  const v = lay.v;
  const els = {
    walkway: { key: "walkway", name: p.type === "attenuator" ? "Attenuator" : "Main walkway", B: lay.walkW, L: lay.moduleL, sec: section(p.type, p.section, lay.walkW) },
    finger: { key: "finger", name: "Finger", B: lay.fingerW, L: lay.fingerL, sec: section(fingerKind, fingerSection, lay.fingerW), sectionOverride: fingerSection },
  };
  const floats = { walkway: floating(els.walkway, p, gw, acc), finger: floating(els.finger, p, gw, acc) };
  const levels = { LAT: +p.site.LAT, HAT: +p.site.HAT + +p.site.slr, MAX: +p.site.HAT + +p.site.slr + +p.site.surge };
  const depthHAT = Math.max(0.5, levels.HAT - +p.site.seabed);
  const struct = { walkway: structure(els.walkway, p, gw, p.site, depthHAT) };
  if (fingerKind === "concrete" || fingerKind === "framed") struct.finger = structure(els.finger, p, gw, p.site, depthHAT);
  // environment
  const wind = windSpeed(p);
  const combos = C.COMBOS.filter((c) => !c.berthing && (!c.when || +p.site.surge > 0));
  const loads = combos.map((combo) => ({ combo, ...armLoads(p, lay, floats, combo, levels, gw, wind) }));
  // berthing energy, AS 3962 Cl 4.9 with PIANC (2002) added mass Cm = 1 + 2D/B, mid-point (Ce = 1)
  const Vb = C.berthingSpeed(v.L);
  const Cm = 1 + (2 * v.hullDraft) / v.beam;
  const berth = { V: Vb, Cm, E: 0.5 * v.disp * Vb * Vb * Cm, disp: v.disp };
  // serviceability environment (AS 4997 Cl 4.3): SLS wind, unfactored current and waves
  const slsWind = windSpeed(p, C.SLS.windR);
  const slsCombos = [
    { key: "slsHAT", name: "SLS: wind (1/25) + current + wave (HAT)", wind: 1, current: 1, wave: 1, level: "HAT", src: C.SLS.src },
    { key: "slsLAT", name: "SLS: wind (1/25) + current + wave (LAT)", wind: 1, current: 1, wave: 1, level: "LAT", src: C.SLS.src },
  ];
  const sls = slsCombos.map((combo) => ({ combo, ...armLoads(p, lay, floats, combo, levels, gw, slsWind) }));
  const eqB = p.seismic.on ? { ...seismicBasis(p), mass: armMass(lay, floats, gw) } : null;
  const chains = p.mooring.type === "chains";
  const piles = chains ? mooringDesign(p, lay, floats, loads, levels, gw) : sizePiles(p, lay, floats, loads, levels, gw, berth, { sls, slsWind, eq: eqB });
  const nOf = (len) => Math.max(2, Math.ceil(len / Math.max(2, +(chains ? p.mooring.spacing : p.piles.spacing))) + 1);
  piles.total = piles.n * lay.arms + (lay.spine ? nOf(lay.spine.len) : 0) + (lay.head ? nOf(lay.head.len) : 0);
  const dyn = dynamics(p, lay, floats, piles, gw);
  const conn = connections(p, lay, floats, loads, berth, piles.n);
  const guides = chains ? null : pileGuides(p, piles, floats);
  // waves behind: transmission (Macagno), compared with AS 3962 Table 4.2 for the 1 in 50 y event
  const att = macagnoKt(+p.site.Tp, depthHAT, lay.walkW, floats.walkway.ini.T);
  const climate = C.WAVE_CLIMATE.factors[p.site.climate || "good"];
  const behind = att.Kt * +p.site.Hs;
  const checks = [
    ...floats.walkway.checks, ...floats.finger.checks,
    ...Object.values(struct).flatMap((s) => s.checks),
    ...piles.checks,
    ...conn.checks, ...(guides ? guides.checks : []),
  ];
  // gangway slope (AS 3962:2020 Cl 3.6.2, Table 3.5): general berths 1:4 at CD; accessible berths 1:8 at
  // worst (CD) and 1:14 for at least 80 % of the time, which is checked at mean sea level as a proxy
  const landing = +p.layout.gangwayLanding;
  const deckLAT = levels.LAT + floats.walkway.freeboardDL;
  const rise = Math.abs(landing - deckLAT);
  const mslDeck = (+p.site.HAT + +p.site.LAT) / 2 + +p.site.slr / 2 + floats.walkway.freeboardDL;
  const riseNeed = (r, n) => Math.ceil(Math.hypot(r * n, r) * 2) / 2;
  const glen = +p.layout.gangwayLength || Math.max(riseNeed(rise, lay.slope), lay.accessible ? riseNeed(Math.abs(landing - mslDeck), C.GANGWAY_SLOPE.accessible80) : 0);
  const gslope = glen > rise ? rise / Math.sqrt(glen * glen - rise * rise) : Infinity;
  checks.push(check("Gangway", "Slope at LAT (CD)", gslope, 1 / lay.slope, {
    unit: "V/H", src: C.GANGWAY_SLOPE.src,
    working: [`Landing ${fx(landing, 2)} m CD, pontoon deck at LAT ${fx(deckLAT, 2)} m CD: rise ${fx(rise, 2)} m`, `Gangway ${fx(glen, 1)} m long → slope 1 : ${fx(1 / gslope, 2)} (limit 1 : ${lay.slope})`, `Clear width ${fx(lay.gangwayW, 1)} m for ${lay.berths} ${lay.accessible ? "accessible" : "general"} berths (Table 3.4)`],
  }));
  if (lay.accessible) {
    const msl = (+p.site.HAT + +p.site.LAT) / 2 + +p.site.slr / 2;
    const riseM = Math.abs(landing - (msl + floats.walkway.freeboardDL));
    const sM = glen > riseM ? riseM / Math.sqrt(glen * glen - riseM * riseM) : Infinity;
    checks.push(check("Gangway", "Slope for 80 % of the time (accessible)", sM, 1 / C.GANGWAY_SLOPE.accessible80, {
      unit: "V/H", src: C.GANGWAY_SLOPE.src,
      working: [`Mean sea level ≈ (HAT + LAT)/2 + SLR/2 = ${fx(msl, 2)} m CD as a proxy for the 80 % level; confirm with the site's tide exceedance curve`, `Rise ${fx(riseM, 2)} m over ${fx(glen, 1)} m → 1 : ${fx(1 / sM, 2)} (limit 1 : ${C.GANGWAY_SLOPE.accessible80})`],
    }));
    checks.push(check("Gangway", "Gangway length (accessible)", glen, C.GANGWAY_SLOPE.accessibleLength, { unit: "m", src: C.GANGWAY_SLOPE.src }));
    checks.push(check("Layout", "Accessible berths within 200 m of the land", lay.totalWalk, C.WALKWAY.accessible.maxLength, { unit: "m", src: C.WALKWAY.src, note: "Total walkway length as the path of travel (conservative)." }));
  }
  const gwy = gangwayDesign(p, lay, floats, { length: glen, rise, slope: gslope }, gw);
  checks.push(...gwy.checks);
  if (lay.shape === "comb") checks.push(check("Layout", "Fairway between arms", lay.fairway, lay.fairwayNeed, {
    unit: "m", sense: "min", src: C.FAIRWAY.src,
    working: [`Arms ${fx(lay.armSpacing, 1)} m apart, walkway ${fx(lay.walkW, 2)} m, boats reach ${fx(0.6 + v.L, 1)} m from it on ${lay.sides === 2 ? "both sides" : "one side"} → clear fairway ${fx(lay.fairway, 2)} m ≥ 1.5 L = ${fx(lay.fairwayNeed, 2)} m`],
  }));
  const a4997 = as4997(p, lay, floats);
  checks.push(...a4997.checks);
  const minLife = check("Design basis", "Design life at least 25 years", +p.site.life, C.MIN_LIFE.years, { unit: "years", sense: "min", src: C.MIN_LIFE.src });
  if (minLife.pass) minLife.ratio = null;
  checks.push(minLife);
  if (p.type === "attenuator") {
    const lim = 0.6 * climate;
    checks.push(check("Waves", "Transmitted wave height (head seas, 1 in 50 y)", behind, lim, {
      unit: "m", src: "AS 3962 Table 4.2; Macagno (1953) transmission",
      working: [`k = ${fx(att.k, 4)} 1/m (λ = ${fx(att.L, 2)} m) in ${fx(depthHAT, 2)} m depth; B = ${fx(lay.walkW, 2)} m, draft ${fx(floats.walkway.ini.T, 3)} m`, `Kt = 1/√(1 + [kB sinh kh / (2 cosh k(h−T))]²) = ${fx(att.Kt, 3)} → Hs behind = ${fx(behind, 3)} m`],
    }));
  }
  const advice = [...(floats.walkway.advice || []), ...(floats.finger.advice || []), ...a4997.advice];
  if (lay.sides === 2 && +p.site.Hs > C.WAVE_CLIMATE.intermediatePiles) advice.push({ src: "AS 3962 Cl 4.8.2.1", text: `Head sea Hs ${fx(+p.site.Hs, 2)} m is over 0.4 m with double-sided berths: consider intermediate mooring piles between the boats.` });
  const hMaxLim = C.WAVE_CLIMATE.maxOverModerate * 0.6 * C.WAVE_CLIMATE.factors.moderate;
  if (C.WAVE_DESIGN.H1overHs * +p.site.Hs > hMaxLim) advice.push({ src: "AS 3962 Table 4.2 Note", text: `Design wave H1 = ${fx(C.WAVE_DESIGN.H1overHs * +p.site.Hs, 2)} m is above 1.5 × the moderate head-sea criterion (${fx(hMaxLim, 2)} m). The berths are outside the Table 4.2 climate; consider an attenuator or breakwater.` });
  if (!v.given && v.dispMin > v.dispHull) advice.push({ src: "AS 3962 Table 4.6", text: `Berthing displacement set by the Table 4.6 minimum (${fx(v.dispMin, 1)} t for ${fx(v.L, 1)} m), above the hull estimate of ${fx(v.dispHull, 1)} t.` });
  if (eqB && !chains) advice.push({ src: "AS 1170.4", text: `Earthquake: kpZ = ${fx(eqB.kpZ, 3)} (1/${eqB.P} years, Z = ${eqB.Z}, site class ${eqB.site}). The floating pontoon itself is isolated by the water; the piles carry the arm's sway inertia.` });
  if (lay.spine || lay.head) advice.push({ src: "Layout", text: `${lay.spine ? "The spine walkway" : "The T-head"} uses the arm's section and pile design. Each arm is taken as restrained by its own piles, with the joints to the ${lay.spine ? "spine" : "head"} able to rotate in plan.` });
  if (dyn.near.length) advice.push({ src: "Dynamics", text: `The wave period ${fx(+p.site.Tp, 1)} s is within 20 % of the ${dyn.near.map((q) => `${q.n} period ${fx(q.T, 2)} s`).join(", ")}. Expect lively motion in that sea.` });
  if (!v.given) advice.push({ src: "Berthing", text: `Vessel displacement estimated at ${fx(v.disp, 1)} t from its length; enter the design vessel's own figure.` });
  if (piles.autoFailed) advice.push({ src: "Piles", text: `No standard ${p.piles.type} pile in the list carries these loads at ${p.piles.spacing} m centres. Close the spacing or choose another pile type.` });
  if (piles.embedNotes && piles.embedNotes.length) advice.push({ src: "Piles", text: piles.embedNotes[0] });
  const worst = checks.filter((c) => c.ratio !== null).reduce((a, c) => (!a || c.ratio > a.ratio ? c : a), null);
  return {
    project: p, kindName: KIND_NAMES[p.type], layout: lay, vessel: v, gw, levels, floats, struct, wind, loads, berth, piles, dyn,
    sls, slsWind, seismic: eqB, connections: conn, guides, gangwayDesign: gwy, as4997: a4997, mooring: chains ? piles : null,
    advice, attenuation: { ...att, behind, climate }, gangway: { length: glen, rise, slope: gslope }, checks,
    pass: checks.every((c) => c.pass), worst, ms: Date.now() - t0,
  };
}
