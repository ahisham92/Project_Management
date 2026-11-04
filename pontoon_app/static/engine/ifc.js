// IFC4 export of the designed marina arm, for Revit (Insert → Link IFC, or Open IFC).
//
// Every element is a real IFC class with a solid: walkway and finger pontoons as IfcSlab,
// guide piles as IfcPile (with IfcReinforcingBar for precast piles), the gangway as IfcBeam,
// pile guide frames as IfcMember, module joint rods as IfcMechanicalFastener, deck mesh as
// IfcReinforcingMesh, mooring chains as IfcMember on a swept disk and anchor blocks as
// IfcFooting. Each carries
// the design results it came from in a property set (PT_Design), plus the standard
// Pset_ sets Revit maps to parameters, and MarineTwin's MT_Common so the model can
// be tracked in MarineTwin as built. Units: metres; elevations to Chart Datum.

import { layoutGeometry } from "./geometry.js";

const CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_$";
/** A 22-character IFC GlobalId, deterministic from a text so re-exports keep element identity. */
export function guid(text) {
  // FNV-1a 128-bit-ish: four 32-bit lanes
  let h = [0x811c9dc5, 0x01000193, 0x9e3779b9, 0x7f4a7c15];
  for (let i = 0; i < text.length; i++) {
    const c = text.charCodeAt(i);
    h = h.map((v, k) => Math.imul(v ^ (c + k * 31), 16777619 + k * 2) >>> 0);
  }
  const bits = h.map((v) => v.toString(2).padStart(32, "0")).join(""); // 128 bits
  // IFC compressed GUID: the first character carries 2 bits, the other 21 carry 6 each
  let out = CHARS[parseInt(bits.slice(0, 2), 2)];
  for (let i = 0; i < 21; i++) out += CHARS[parseInt(bits.slice(2 + i * 6, 8 + i * 6), 2)];
  return out;
}

const s = (t) => `'${String(t ?? "").replace(/\\/g, "\\\\").replace(/'/g, "''").replace(/[^\x20-\x7e]/g, (ch) => `\\X2\\${ch.charCodeAt(0).toString(16).toUpperCase().padStart(4, "0")}\\X0\\`)}'`;
const n = (v) => { const x = Number(v); if (!Number.isFinite(x)) return "0."; const t = (+x.toFixed(6)).toString(); return t.includes(".") || t.includes("e") ? t : t + "."; };

export function exportIFC(r, { author = "", now = new Date() } = {}) {
  const lines = [];
  let id = 0;
  const add = (txt) => { id++; lines.push(`#${id}=${txt};`); return `#${id}`; };
  const p = r.project, geo = layoutGeometry(r, "HAT");
  const pname = p.name || "Pontoon";

  // --- context, units, project
  const origin = add("IFCCARTESIANPOINT((0.,0.,0.))");
  const zAxis = add("IFCDIRECTION((0.,0.,1.))"), xAxis = add("IFCDIRECTION((1.,0.,0.))");
  const world = add(`IFCAXIS2PLACEMENT3D(${origin},${zAxis},${xAxis})`);
  const ctx = add(`IFCGEOMETRICREPRESENTATIONCONTEXT($,'Model',3,1.E-05,${world},$)`);
  const body = add(`IFCGEOMETRICREPRESENTATIONSUBCONTEXT('Body','Model',*,*,*,*,${ctx},$,.MODEL_VIEW.,$)`);
  const uLen = add("IFCSIUNIT(*,.LENGTHUNIT.,$,.METRE.)");
  const uArea = add("IFCSIUNIT(*,.AREAUNIT.,$,.SQUARE_METRE.)");
  const uVol = add("IFCSIUNIT(*,.VOLUMEUNIT.,$,.CUBIC_METRE.)");
  const uAng = add("IFCSIUNIT(*,.PLANEANGLEUNIT.,$,.RADIAN.)");
  const uForce = add("IFCSIUNIT(*,.FORCEUNIT.,.KILO.,.NEWTON.)");
  const units = add(`IFCUNITASSIGNMENT((${uLen},${uArea},${uVol},${uAng},${uForce}))`);
  const person = add(`IFCPERSON($,${s(author || "Engineer")},$,$,$,$,$,$)`);
  const org = add(`IFCORGANIZATION($,'AHM',$,$,$)`);
  const po = add(`IFCPERSONANDORGANIZATION(${person},${org},$)`);
  const appOrg = add(`IFCORGANIZATION($,'AHM Pontoon',$,$,$)`);
  const app = add(`IFCAPPLICATION(${appOrg},'1.0','Pontoon','Pontoon')`);
  const own = add(`IFCOWNERHISTORY(${po},${app},$,.ADDED.,$,$,$,${Math.floor(now.getTime() / 1000)})`);
  const project = add(`IFCPROJECT(${s(guid("project:" + pname))},${own},${s(pname)},'Floating pontoon designed to AS 3962',$,$,$,(${ctx}),${units})`);
  // --- spatial structure: site, the marina as a building, one level at Chart Datum
  const sitePl = add(`IFCLOCALPLACEMENT($,${world})`);
  const site = add(`IFCSITE(${s(guid("site:" + pname))},${own},'Site',$,$,${sitePl},$,$,.ELEMENT.,$,$,0.,$,$)`);
  const bldPl = add(`IFCLOCALPLACEMENT(${sitePl},${world})`);
  const bld = add(`IFCBUILDING(${s(guid("bld:" + pname))},${own},${s(pname)},'Marina arm',$,${bldPl},$,$,.ELEMENT.,$,$,$)`);
  const stPl = add(`IFCLOCALPLACEMENT(${bldPl},${world})`);
  const storey = add(`IFCBUILDINGSTOREY(${s(guid("lvl:" + pname))},${own},'Chart Datum',$,$,${stPl},$,$,.ELEMENT.,0.)`);
  add(`IFCRELAGGREGATES(${s(guid("agg1:" + pname))},${own},$,$,${project},(${site}))`);
  add(`IFCRELAGGREGATES(${s(guid("agg2:" + pname))},${own},$,$,${site},(${bld}))`);
  add(`IFCRELAGGREGATES(${s(guid("agg3:" + pname))},${own},$,$,${bld},(${storey}))`);

  // --- materials
  const mats = {};
  const material = (name) => (mats[name] ||= add(`IFCMATERIAL(${s(name)},$,$)`));

  const placement = (x, y, z) => {
    const pt = add(`IFCCARTESIANPOINT((${n(x)},${n(y)},${n(z)}))`);
    return add(`IFCLOCALPLACEMENT(${stPl},${add(`IFCAXIS2PLACEMENT3D(${pt},$,$)`)})`);
  };
  const extrude = (profile, depth, dir = zAxis) => {
    const solid = add(`IFCEXTRUDEDAREASOLID(${profile},${add(`IFCAXIS2PLACEMENT3D(${origin},$,$)`)},${dir},${n(depth)})`);
    const rep = add(`IFCSHAPEREPRESENTATION(${body},'Body','SweptSolid',(${solid}))`);
    return add(`IFCPRODUCTDEFINITIONSHAPE($,$,(${rep}))`);
  };
  const rectProfile = (name, xd, yd) => {
    const c = add(`IFCAXIS2PLACEMENT2D(${add("IFCCARTESIANPOINT((0.,0.))")},$)`);
    return add(`IFCRECTANGLEPROFILEDEF(.AREA.,${s(name)},${c},${n(xd)},${n(yd)})`);
  };
  const props = (owner, setName, entries) => {
    const ps = entries.filter(([, v]) => v !== undefined && v !== null && v !== "").map(([k, v]) => {
      const val = typeof v === "number" ? `IFCREAL(${n(v)})` : typeof v === "boolean" ? `IFCBOOLEAN(${v ? ".T." : ".F."})` : `IFCLABEL(${s(v)})`;
      return add(`IFCPROPERTYSINGLEVALUE(${s(k)},$,${val},$)`);
    });
    if (!ps.length) return;
    const set = add(`IFCPROPERTYSET(${s(guid(`${setName}:${owner.key}`))},${own},${s(setName)},$,(${ps.join(",")}))`);
    add(`IFCRELDEFINESBYPROPERTIES(${s(guid(`rel:${setName}:${owner.key}`))},${own},$,$,(${owner.ref}),${set})`);
  };
  const contained = [], byMat = {};
  const element = (cls, key, name, desc, pl, shape, tail, matName) => {
    const ref = add(`${cls}(${s(guid(key))},${own},${s(name)},${s(desc)},$,${pl},${shape},${s(name)}${tail})`);
    contained.push(ref);
    (byMat[matName] ||= []).push(ref);
    return { ref, key };
  };

  const sweptDisk = (pts, radius) => {
    const ptRefs = pts.map(([x, y, z]) => add(`IFCCARTESIANPOINT((${n(x)},${n(y)},${n(z)}))`));
    const poly = add(`IFCPOLYLINE((${ptRefs.join(",")}))`);
    const solid = add(`IFCSWEPTDISKSOLID(${poly},${n(radius)},$,$,$)`);
    const rep = add(`IFCSHAPEREPRESENTATION(${body},'Body','AdvancedSweptSolid',(${solid}))`);
    return add(`IFCPRODUCTDEFINITIONSHAPE($,$,(${rep}))`);
  };
  const worldPl = () => add(`IFCLOCALPLACEMENT(${stPl},${add(`IFCAXIS2PLACEMENT3D(${origin},$,$)`)})`);
  const fb = r.floats, ps = r.piles.ps || {};
  const conn = r.connections;
  const govRatio = (group) => Math.max(0, ...r.checks.filter((c) => c.group === group && c.ratio !== null && Number.isFinite(c.ratio)).map((c) => c.ratio));
  const pontoonMat = { concrete: "Concrete, reinforced, EPS core", attenuator: "Concrete, reinforced, EPS core", framed: `${p.section.frame || "aluminium"} frame on HDPE floats`, modular: "HDPE modular cubes" }[p.type];

  for (const it of geo.items) {
    if (it.kind === "walkway" || it.kind === "finger") {
      const L = it.x1 - it.x0, W = it.y1 - it.y0, H = it.z1 - it.z0;
      const pl = placement((it.x0 + it.x1) / 2, (it.y0 + it.y1) / 2, it.z0);
      const desc = it.kind === "finger" ? "Floating finger pontoon" : it.landingKind ? `Gangway landing pontoon${it.landingKind !== p.type ? " (concrete)" : ""}` : "Floating walkway pontoon";
      const e = element("IFCSLAB", `${it.kind}:${it.name}:${pname}`, it.name, desc, pl, extrude(rectProfile(it.name, L, W), H), ",.FLOOR.", it.landingKind === "concrete" && p.type !== "concrete" ? "Concrete, reinforced, EPS core" : pontoonMat);
      const f = it.kind === "walkway" ? fb.walkway : fb.finger;
      props(e, "Pset_SlabCommon", [["Reference", it.name], ["IsExternal", true], ["LoadBearing", true]]);
      props(e, "PT_Design", [
        ["PT_Type", r.kindName], ["PT_Length", L], ["PT_Width", W], ["PT_Depth", H], ["PT_DeadLoad_kN_per_m", f.sec.w],
        ["PT_DraftDead_m", f.ini.T], ["PT_FreeboardDead_m", f.freeboardDL], ["PT_GM_m", f.GM], ["PT_TiltStability_deg", f.tilt],
        ["PT_DesignRatio", govRatio(f.name)], ["PT_Standard", "AS 3962; AS/NZS 1170; AS 3600"], ["PT_WaterLevel", "HAT + SLR"],
      ]);
      // deck mesh of a concrete pontoon, and the joint rods at the module's far end
      if ((p.type === "concrete" || p.type === "attenuator" || it.landingKind === "concrete") && (it.kind === "walkway" || p.type !== "framed")) {
        const cov = (+p.section.meshCover || 30) / 1000;
        const plm = placement((it.x0 + it.x1) / 2, (it.y0 + it.y1) / 2, it.z1 - cov - 0.008);
        const mesh = add(`IFCREINFORCINGMESH(${s(guid(`mesh:${it.name}:${pname}`))},${own},${s(`Mesh ${it.name}`)},'Deck mesh, top',$,${plm},${extrude(rectProfile("mesh", L - 2 * cov, W - 2 * cov), 0.016)},${s(`SL${Math.round((+p.section.mesh || 252) / 10) * 10 >= 250 ? "82" : "72"}`)},$,$,$,$,$,$,$,$,$,.NOTDEFINED.)`);
        contained.push(mesh); (byMat["Reinforcing mesh, galvanised"] ||= []).push(mesh);
        props({ ref: mesh, key: `mesh:${it.name}` }, "PT_Design", [["PT_MeshArea_mm2_per_m", +p.section.mesh || 252], ["PT_Cover_mm", +p.section.meshCover || 30], ["PT_Standard", "AS/NZS 4671; AS 3600"]]);
      }
      if (conn && it.kind === "walkway") {
        const j = conn.joint, along = it.along === "y";
        for (let k = 0; k < 2 * j.perSide; k++) {
          const side = k < j.perSide ? -1 : 1, idx = k % j.perSide;
          const off = side * (j.z / 2 - idx * 0.15);
          const x = along ? (it.x0 + it.x1) / 2 + off : it.x1, y = along ? it.y1 : (it.y0 + it.y1) / 2 + off;
          const c2 = add(`IFCAXIS2PLACEMENT2D(${add("IFCCARTESIANPOINT((0.,0.))")},$)`);
          const prof = add(`IFCCIRCLEPROFILEDEF(.AREA.,'Rod',${c2},${n(j.rod.d / 2000)})`);
          const dir = along ? add("IFCDIRECTION((0.,1.,0.))") : xAxis;
          const plr = placement(along ? x : x - 0.3, along ? y - 0.3 : y, it.z0 + (it.z1 - it.z0) * 0.6);
          const rod = add(`IFCMECHANICALFASTENER(${s(guid(`rod:${it.name}:${k}:${pname}`))},${own},${s(`Joint rod ${it.name}-${k + 1}`)},${s(`M${j.rod.d} ${j.rod.name}`)},$,${plr},${extrude(prof, 0.65, dir)},$,${n(j.rod.d / 1000)},0.65,.THREADEDROD.)`);
          contained.push(rod); (byMat[j.rod.name] ||= []).push(rod);
        }
      }
      props(e, "MT_Common", [["MT_Kind", "pontoon"], ["MT_Material", p.type === "framed" ? "aluminium" : p.type === "modular" ? "hdpe" : "concrete"], ["MT_Zone", "splash"], ["MT_DesignUR", govRatio(f.name)]]);
    } else if (it.kind === "pile") {
      const len = it.top - it.toe, pl = placement(it.x, it.y, it.toe);
      const c = add(`IFCAXIS2PLACEMENT2D(${add("IFCCARTESIANPOINT((0.,0.))")},$)`);
      let prof, matName;
      if (ps.kind === "steel") { prof = add(`IFCCIRCLEHOLLOWPROFILEDEF(.AREA.,${s(ps.desc)},${c},${n(ps.D / 2)},${n(+p.piles.t / 1000)})`); matName = "Steel, " + (p.piles.grade || ""); }
      else if (ps.kind === "concrete" && p.piles.concrete.shape !== "round") { prof = add(`IFCRECTANGLEPROFILEDEF(.AREA.,${s(ps.desc)},${c},${n(ps.D)},${n(ps.D)})`); matName = `Concrete f'c ${p.piles.concrete.fc} MPa`; }
      else { prof = add(`IFCCIRCLEPROFILEDEF(.AREA.,${s(ps.desc)},${c},${n(ps.D / 2)})`); matName = ps.kind === "timber" ? `Timber ${p.piles.timber.grade}` : `Concrete f'c ${p.piles.concrete.fc} MPa`; }
      const e = element("IFCPILE", `pile:${it.name}:${pname}`, it.name, "Pontoon guide pile", pl, extrude(prof, len), ",.DRIVEN.,.NOTDEFINED.", matName);
      props(e, "Pset_PileCommon", [["Reference", it.name]]);
      props(e, "PT_Design", [
        ["PT_Section", ps.desc], ["PT_TopLevel_mCD", it.top], ["PT_ToeLevel_mCD", it.toe], ["PT_SeabedLevel_mCD", it.bed],
        ["PT_Embedment_m", r.piles.Lreq], ["PT_DesignMoment_kNm", r.piles.gov.Mmax], ["PT_MomentCapacity_kNm", ps.phiM],
        ["PT_DesignLateral_kN", r.piles.govGeo.H], ["PT_LateralResistance_kN", r.piles.govGeo.brom.Hu], ["PT_PhiG", r.piles.phiG],
        ["PT_CorrosionLoss_mm", ps.loss], ["PT_DesignRatio", govRatio("Piles")], ["PT_Standard", "AS 2159; AS 4100 / AS 3600 / AS 1720.1; AS 3962"],
      ]);
      if (ps.kind === "concrete") {
        const c = p.piles.concrete, nb = +c.bars, db = +c.db / 1000, cov = (+c.cover + 12) / 1000 + db / 2;
        const round = c.shape === "round", b = +c.b / 1000;
        for (let k = 0; k < nb; k++) {
          let bx, by;
          if (round) { const a = (2 * Math.PI * k) / nb, R = b / 2 - cov; bx = R * Math.cos(a); by = R * Math.sin(a); }
          else { const per = Math.max(1, Math.round(nb / 4)), side = Math.floor(k / per) % 4, t = per > 1 ? (k % per) / per : 0, h = b / 2 - cov; const pos = -h + t * 2 * h; [bx, by] = [[pos, -h], [h, pos], [-pos, h], [-h, -pos]][side]; }
          const bar = add(`IFCREINFORCINGBAR(${s(guid(`bar:${it.name}:${k}:${pname}`))},${own},${s(`${it.name} N${c.db} bar ${k + 1}`)},'Longitudinal',$,${worldPl()},${sweptDisk([[it.x + bx, it.y + by, it.toe + 0.05], [it.x + bx, it.y + by, it.top - 0.05]], db / 2)},$,'D500N',${n(db)},${n(Math.PI * db * db / 4)},${n(len - 0.1)},.MAIN.,.TEXTURED.)`);
          contained.push(bar); (byMat["Reinforcing steel D500N"] ||= []).push(bar);
        }
      }
      props(e, "MT_Common", [["MT_Kind", "pile"], ["MT_Material", ps.kind], ["MT_Zone", "splash"], ["MT_WallThickness", ps.kind === "steel" ? +p.piles.t : undefined], ["MT_DesignUR", govRatio("Piles")]]);
    } else if (it.kind === "guide") {
      const L = it.x1 - it.x0, W = it.y1 - it.y0;
      const pl = placement((it.x0 + it.x1) / 2, (it.y0 + it.y1) / 2, it.z0);
      const e = element("IFCMEMBER", `guide:${it.name}:${pname}`, it.name, `Pile guide frame, SHS ${it.shs.b} × ${it.shs.t} C350L0 HDG, UHMWPE rollers`, pl, extrude(rectProfile(it.name, L, W), it.z1 - it.z0), ",.MEMBER.", "Steel C350L0, hot-dip galvanised");
      props(e, "PT_Design", [["PT_Pile", it.pile], ["PT_Section", `SHS ${it.shs.b} x ${it.shs.t}`], ["PT_GuideForce_kN", r.guides.H], ["PT_ArmMoment_kNm", r.guides.M], ["PT_RollerClearance_mm", r.guides.gap * 1000], ["PT_Standard", "AS 4100"]]);
    } else if (it.kind === "chain") {
      const e = element("IFCMEMBER", `chain:${it.name}:${pname}`, it.name, `Mooring chain Ø${it.d} studless R3`, worldPl(), sweptDisk(it.pts, it.d / 1000), ",.MEMBER.", "Steel chain grade R3");
      props(e, "PT_Design", [["PT_ChainDiameter_mm", it.d], ["PT_Length_m", r.piles.chainLen], ["PT_DesignTension_kN", r.piles.gov.T], ["PT_MBL_kN", r.piles.mbl], ["PT_Standard", "DNV-OS-E302; AS 3962"]]);
    } else if (it.kind === "anchor") {
      const sd = it.side, pl = placement(it.x, it.y, it.z);
      const e = element("IFCFOOTING", `anchor:${it.name}:${pname}`, it.name, "Concrete anchor block", pl, extrude(rectProfile(it.name, sd, sd), sd), ",.PAD_FOOTING.", "Concrete N32");
      props(e, "PT_Design", [["PT_Side_m", sd], ["PT_SubmergedWeight_kN", r.piles.block.Wsub], ["PT_Friction", r.piles.block.mu]]);
    } else if (it.kind === "gangway") {
      const run = it.x1 - it.x0, rise = it.z1 - it.z0, len = Math.hypot(run, rise);
      const dir = add(`IFCDIRECTION((${n(run / len)},0.,${n(rise / len)}))`);
      const pl = placement(it.x0, it.y || 0, it.z0);
      // profile in the plane normal to the gangway: width across (y), 0.15 m deep
      const prof = rectProfile("Gangway", 0.15, it.w);
      const e = element("IFCBEAM", `gangway:${it.name}:${pname}`, it.name, "Gangway (truss)", pl, extrude(prof, len, dir), ",.BEAM.", "Aluminium 6000 series");
      const gd = r.gangwayDesign;
      props(e, "PT_Design", [["PT_Length_m", len], ["PT_ClearWidth_m", it.w], ["PT_SlopeAtLAT", `1:${(1 / r.gangway.slope).toFixed(2)}`], ["PT_Chords", gd?.desc], ["PT_TrussDepth_m", gd?.h], ["PT_ChordForce_kN", gd?.Nchord], ["PT_LiveDeflection_mm", gd ? gd.dLive * 1000 : undefined], ["PT_Frequency_Hz", gd?.f1], ["PT_Standard", "AS 3962 Cl 3.6, 4.5; AS/NZS 1664.1 / AS 4100"]]);
    }
  }
  add(`IFCRELCONTAINEDINSPATIALSTRUCTURE(${s(guid("cont:" + pname))},${own},$,$,(${contained.join(",")}),${storey})`);
  Object.entries(byMat).forEach(([m, refs], i) => add(`IFCRELASSOCIATESMATERIAL(${s(guid(`mat${i}:${m}:${pname}`))},${own},$,$,(${refs.join(",")}),${material(m)})`));
  // project facts for MarineTwin
  props({ ref: project, key: "project" }, "MT_Project", [["MT_AssetName", pname], ["MT_AssetType", "Marina pontoon"], ["MT_VerticalDatum", "CD"], ["MT_DesignLife", +p.site.life]]);

  const iso = now.toISOString().slice(0, 19);
  return `ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('ViewDefinition [ReferenceView_V1.2]'),'2;1');
FILE_NAME(${s(pname + ".ifc")},'${iso}',(${s(author || "")}),('AHM'),'Pontoon','Pontoon','');
FILE_SCHEMA(('IFC4'));
ENDSEC;
DATA;
${lines.join("\n")}
ENDSEC;
END-ISO-10303-21;
`;
}
