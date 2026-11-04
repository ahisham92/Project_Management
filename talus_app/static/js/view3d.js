// Talus — the slope in 3D: the section extruded, water, the critical slip surface,
// the sliding mass cut out of the ground and moving the way it would fail, armour
// units on a revetment face, surcharge and earthquake. The analysis itself is 2D
// (plane strain); the depth here is for seeing it.
import * as THREE from "three";
import { OrbitControls } from "../vendor/three/OrbitControls.js";
import { yAt, lower, upper, flat } from "../engine/geometry.js";
import { extent, pondPoly, colourOf, fosColour } from "./shapes.js";

const BIG = 1e5;

function shapeOf(poly) {
  const s = new THREE.Shape();
  poly.forEach(([x, y], i) => (i ? s.lineTo(x, y) : s.moveTo(x, y)));
  s.closePath();
  return s;
}

function area(poly) {
  let a = 0;
  for (let i = 0; i < poly.length; i++) {
    const [x1, y1] = poly[i], [x2, y2] = poly[(i + 1) % poly.length];
    a += x1 * y2 - x2 * y1;
  }
  return Math.abs(a) / 2;
}

function prism(poly, z0, z1, material) {
  const geo = new THREE.ExtrudeGeometry(shapeOf(poly), { depth: z1 - z0, bevelEnabled: false, curveSegments: 1 });
  geo.translate(0, 0, z0);
  const m = new THREE.Mesh(geo, material);
  m.castShadow = true; m.receiveShadow = true;
  return m;
}

/** Layer polygons between a ground line and a bottom line over [a, b]. */
function stack(geometry, ground, bottom, a, b, skip) {
  const L = geometry.layers;
  const tops = [];
  let T = ground;
  tops.push(T);
  for (let k = 1; k < L.length; k++) { T = lower(T, L[k].top, a, b); tops.push(T); }
  const out = [];
  L.forEach((layer, k) => {
    const top = upper(tops[k], bottom, a, b);
    const bot = k + 1 < L.length ? upper(tops[k + 1], bottom, a, b) : bottom;
    const poly = [...top, ...bot.slice().reverse()];
    if (area(poly) > 1e-4 && !(skip && skip.test(layer.mat.name))) out.push({ k, name: layer.mat.name, poly });
  });
  return out;
}

/** A merged geometry from several (positions and normals only). */
function merge(geos) {
  const pos = [], nor = [];
  for (const g0 of geos) {
    const g = g0.index ? g0.toNonIndexed() : g0;
    pos.push(...g.attributes.position.array);
    nor.push(...g.attributes.normal.array);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute("normal", new THREE.Float32BufferAttribute(nor, 3));
  return g;
}

/** A schematic single-layer interlocking concrete unit (not CLI's exact shape). */
function interlockingUnit() {
  const parts = [];
  const core = new THREE.CylinderGeometry(0.28, 0.28, 0.62, 8);
  parts.push(core);
  const leg = (rx, ry, rz, dx, dy, dz) => {
    const g = new THREE.CylinderGeometry(0.16, 0.3, 0.5, 8);
    g.rotateX(rx); g.rotateY(ry); g.rotateZ(rz);
    g.translate(dx, dy, dz);
    parts.push(g);
  };
  leg(0, 0, Math.PI / 2, 0.42, 0, 0);
  leg(0, 0, -Math.PI / 2, -0.42, 0, 0);
  leg(Math.PI / 2, 0, 0, 0, 0, 0.42);
  leg(-Math.PI / 2, 0, 0, 0, 0, -0.42);
  return merge(parts);
}

function label(text, colour) {
  const c = document.createElement("canvas");
  c.width = 256; c.height = 96;
  const x = c.getContext("2d");
  x.fillStyle = "rgba(255,255,255,0.92)";
  const r = 22;
  x.beginPath(); x.moveTo(r, 8); x.arcTo(248, 8, 248, 88, r); x.arcTo(248, 88, 8, 88, r); x.arcTo(8, 88, 8, 8, r); x.arcTo(8, 8, 248, 8, r); x.fill();
  x.lineWidth = 5; x.strokeStyle = colour; x.stroke();
  x.fillStyle = colour; x.font = "bold 46px system-ui, sans-serif"; x.textAlign = "center"; x.textBaseline = "middle";
  x.fillText(text, 128, 50);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: t, depthTest: false }));
  s.renderOrder = 10;
  return s;
}

export class View3D {
  constructor(host) {
    this.host = host;
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    host.prepend(this.renderer.domElement);
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(35, 1, 0.1, 5000);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.08;
    this.controls.screenSpacePanning = true;
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x8a7a66, 1.1));
    const sun = new THREE.DirectionalLight(0xffffff, 1.6);
    sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    sun.shadow.bias = -0.0004;
    sun.shadow.normalBias = 0.04;
    this.sun = sun;
    this.scene.add(sun, sun.target);
    this.world = new THREE.Group();
    this.scene.add(this.world);
    this.motion = true;
    this.clock = new THREE.Clock();
    this.fitted = null;
    const ro = new ResizeObserver(() => this.resize());
    ro.observe(host);
    this.resize();
    const loop = () => { this.frame(); this.raf = requestAnimationFrame(loop); };
    loop();
  }

  resize() {
    const w = this.host.clientWidth, h = this.host.clientHeight;
    if (!w || !h) return;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  clear() {
    this.world.traverse((o) => {
      o.geometry?.dispose?.();
      if (o.material) (Array.isArray(o.material) ? o.material : [o.material]).forEach((m) => { m.map?.dispose?.(); m.dispose?.(); });
    });
    this.world.clear();
    this.mass = null;
  }

  /** Builds the scene for a project result and one of its load cases. */
  show(result, c, opt = {}) {
    this.clear();
    const g = result.geometry;
    const e = extent(g);
    const span = e.x1 - e.x0;
    const D = Math.min(Math.max(0.55 * span, 20), 90);
    const band = 0.45 * D;                 // the width of the sliding mass shown, at the front
    const zb = D / 2 - band;               // where the sliding mass starts
    const mats = new Map();
    const matOf = (name, k) => {
      // deeper layers are pushed back a little, so where a layer thins to nothing the one above wins
      if (!mats.has(name)) mats.set(name, new THREE.MeshStandardMaterial({ color: colourOf(name, k), roughness: 0.95, metalness: 0,
        polygonOffset: k > 0, polygonOffsetFactor: k, polygonOffsetUnits: 4 * k }));
      return mats.get(name);
    };
    const slip = c?.surface?.slip;
    const ground = g.ground;
    const skip = opt.armour ? /armour rock layer|concrete unit layer/i : null;
    if (slip) {
      const a = slip[0][0], b = slip[slip.length - 1][0];
      // in the middle band the ground is cut down to the slip surface
      const cutLine = [[e.x0, BIG], [a - 1e-6, BIG], ...slip, [b + 1e-6, BIG], [e.x1, BIG]];
      const cutGround = lower(ground, cutLine, e.x0, e.x1);
      for (const L of stack(g, ground, flat(g.bottom, e.x0, e.x1), e.x0, e.x1, skip)) {
        this.world.add(prism(L.poly, -D / 2, zb, matOf(L.name, L.k)));
      }
      for (const L of stack(g, cutGround, flat(g.bottom, e.x0, e.x1), e.x0, e.x1, skip)) this.world.add(prism(L.poly, zb, D / 2, matOf(L.name, L.k)));
      // the sliding mass, layer by layer, as its own group so it can move
      const mass = new THREE.Group();
      const massStack = stack(g, groundBetween(ground, a, b), slip, a, b, skip);
      const col = fosColour(c.F, c.target);
      const tint = new THREE.Color(col);
      for (const L of massStack) {
        const m = matOf(L.name, L.k).clone();
        m.color.lerp(tint, 0.5);
        m.emissive = tint.clone().multiplyScalar(0.15);
        mass.add(prism(L.poly, zb + 0.02, D / 2 + 0.02, m));
      }
      // the slip surface as a glowing curved sheet
      const sheet = ribbon(slip, zb - 0.05, D / 2 + 0.05);
      const sheetMat = new THREE.MeshBasicMaterial({ color: col, side: THREE.DoubleSide, transparent: true, opacity: 0.55 });
      this.world.add(new THREE.Mesh(sheet, sheetMat));
      const edge = new THREE.Line(new THREE.BufferGeometry().setFromPoints(slip.map(([x, y]) => new THREE.Vector3(x, y, D / 2 + 0.08))), new THREE.LineBasicMaterial({ color: col, linewidth: 2 }));
      this.world.add(edge);
      // F beside the mass
      const mid = slip[Math.floor(slip.length / 2)];
      const tag = label(`F = ${c.F.toFixed(2)}`, col);
      const top = Math.max(...ground.filter(([x]) => x >= a && x <= b).map((p) => p[1]), yAt(ground, a), yAt(ground, b));
      tag.position.set(mid[0], top + 0.12 * span, D / 2 - band / 2);
      const sc = 0.16 * span;
      tag.scale.set(sc, sc * 96 / 256, 1);
      mass.add(tag);
      this.world.add(mass);
      this.mass = { group: mass, ...motionOf(c.surface, massStack) };
    } else {
      for (const L of stack(g, ground, flat(g.bottom, e.x0, e.x1), e.x0, e.x1, skip)) this.world.add(prism(L.poly, -D / 2, D / 2, matOf(L.name, L.k)));
    }
    // outline of the front face for crispness
    const outline = new THREE.LineBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.25 });
    for (const z of [D / 2 + 0.01]) {
      this.world.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(ground.map(([x, y]) => new THREE.Vector3(x, y, z))), outline));
    }
    // water
    const piezo = c?.piezo || g.piezo;
    const pond = pondPoly(g, piezo);
    if (pond) {
      const wm = new THREE.MeshPhysicalMaterial({ color: 0x3a86d6, transparent: true, opacity: 0.38, roughness: 0.15, metalness: 0, depthWrite: false, polygonOffset: true, polygonOffsetFactor: 2, polygonOffsetUnits: 2 });
      const w = prism(pond, -D / 2, D / 2, wm);
      w.castShadow = false;
      this.world.add(w);
    }
    if (piezo) {
      const inside = piezo.map(([x, y]) => [x, Math.min(y, yAt(ground, x) - 0.004 * span - 0.02)]);
      const pm = new THREE.MeshBasicMaterial({ color: 0x2a78d6, transparent: true, opacity: 0.22, side: THREE.DoubleSide, depthWrite: false });
      this.world.add(new THREE.Mesh(ribbon(inside, -D / 2, D / 2), pm));
    }
    // surcharge
    for (const st of c?.strips || []) {
      const om = new THREE.MeshStandardMaterial({ color: 0xeb6834, transparent: true, opacity: 0.55 });
      const y = yAt(ground, (st.x1 + st.x2) / 2);
      const h = Math.max(0.15, 0.012 * span);
      const box = new THREE.Mesh(new THREE.BoxGeometry(st.x2 - st.x1, h, D * 0.96), om);
      box.position.set((st.x1 + st.x2) / 2, y + h / 2 + 0.02, 0);
      this.world.add(box);
      const cone = new THREE.ConeGeometry(0.012 * span, 0.04 * span, 10);
      cone.rotateX(Math.PI);
      for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) {
        const a = new THREE.Mesh(cone, om);
        a.position.set(st.x1 + (st.x2 - st.x1) * (i + 0.5) / 3, y + h + 0.03 * span, -D * 0.3 + D * 0.3 * j);
        this.world.add(a);
      }
    }
    // reinforcement
    for (const r of opt.reinforcement || []) {
      if (r.kind === "grid") {
        // a geogrid sheet across the fill
        const sheet = new THREE.Mesh(new THREE.PlaneGeometry(r.x1 - r.x0, D * 0.98), new THREE.MeshStandardMaterial({ color: 0x1f8a5a, transparent: true, opacity: 0.55, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -2 }));
        sheet.rotation.x = -Math.PI / 2; sheet.position.set((r.x0 + r.x1) / 2, r.y, 0);
        this.world.add(sheet);
        continue;
      }
      if (r.kind === "pile") {
        const pm = new THREE.MeshStandardMaterial({ color: 0x5d5c58, metalness: 0.3, roughness: 0.6 });
        // the heads stand a little proud of the ground so the row can be seen
        const head = Math.max(0.3, 0.012 * span), L = Math.max(0.1, Math.min(r.length, r.y - g.bottom)) + head;
        const geo = new THREE.CylinderGeometry(Math.max(0.15, 0.008 * span), Math.max(0.15, 0.008 * span), L, 12);
        const step = Math.max(1.5, D / 12);
        for (let z = -D / 2 + step / 2; z < D / 2; z += step) { const m = new THREE.Mesh(geo, pm); m.position.set(r.x, r.y + head - L / 2, z); this.world.add(m); }
        continue;
      }
      const a = r.angle * Math.PI / 180;
      const pts = [new THREE.Vector3(r.x, r.y, 0), new THREE.Vector3(r.x + r.dir * r.length * Math.cos(a), r.y - r.length * Math.sin(a), 0)];
      const geo = new THREE.TubeGeometry(new THREE.LineCurve3(pts[0], pts[1]), 2, Math.max(0.05, 0.004 * span), 6);
      const tm = new THREE.MeshStandardMaterial({ color: 0x4a3aa7 });
      for (let z = -D / 2 + 1; z < D / 2; z += Math.max(1.5, D / 14)) { const m = new THREE.Mesh(geo, tm); m.position.z = z; this.world.add(m); }
    }
    // armour units on a revetment face
    if (opt.armour) this.world.add(armourUnits(g, opt.armour, D));
    // earthquake arrow
    this.shake = 0;
    if (c?.seismic) {
      const dir = opt.faceDir || -1;
      const am = new THREE.MeshStandardMaterial({ color: 0xe34948 });
      const len = 0.12 * span;
      const shaft = new THREE.Mesh(new THREE.CylinderGeometry(0.006 * span, 0.006 * span, len, 10), am);
      shaft.rotation.z = Math.PI / 2;
      const head = new THREE.Mesh(new THREE.ConeGeometry(0.016 * span, 0.04 * span, 12), am);
      head.rotation.z = -dir * Math.PI / 2;
      head.position.x = dir * (len / 2 + 0.02 * span);
      const arrow = new THREE.Group();
      arrow.add(shaft, head);
      arrow.position.set((e.x0 + e.x1) / 2, e.y1 + 0.18 * span, 0);
      this.world.add(arrow);
      this.shake = 0.004 * span;
    }
    // camera: fit once per kind of slope, keep the user's view after that
    const key = `${result.project.type}:${Math.round(span)}`;
    const cx = (e.x0 + e.x1) / 2, cy = (e.y0 + e.y1) / 2;
    if (this.fitted !== key) {
      this.fitted = key;
      const R = Math.max(span, D) * 0.95;
      this.controls.target.set(cx, cy, 0);
      this.camera.position.set(cx + R * 0.35, cy + R * 0.45, R * 1.25);
      this.camera.near = R / 200; this.camera.far = R * 20;
      this.camera.updateProjectionMatrix();
    }
    this.sun.position.set(cx + span * 0.4, e.y1 + span, D);
    this.sun.target.position.set(cx, cy, 0);
    const sh = this.sun.shadow.camera;
    this.sun.shadow.normalBias = span / 250; this.sun.shadow.bias = -0.0015;
    sh.left = -span; sh.right = span; sh.top = span; sh.bottom = -span; sh.near = 0.1; sh.far = span * 4;
    sh.updateProjectionMatrix();
    this.clock.start();
  }

  setMotion(on) { this.motion = on; if (!on && this.mass) this.mass.apply(0); }

  frame() {
    const t = this.clock.getElapsedTime();
    if (this.mass && this.motion) {
      // ease out, hold, ease back: the way the mass would go
      const cyc = (t % 4) / 4;
      const s = cyc < 0.45 ? easeInOut(cyc / 0.45) : cyc < 0.7 ? 1 : 1 - easeInOut((cyc - 0.7) / 0.3);
      this.mass.apply(s);
    }
    this.world.position.x = this.motion && this.shake ? Math.sin(t * 18) * this.shake * (0.5 + 0.5 * Math.sin(t * 1.3)) : 0;
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  }

  snapshot() {
    // the slope at rest, not caught mid-way through the failure animation
    if (this.mass) this.mass.apply(0);
    this.world.position.x = 0;
    this.renderer.render(this.scene, this.camera);
    return this.renderer.domElement.toDataURL("image/png");
  }
}

function easeInOut(x) { return x < 0.5 ? 2 * x * x : 1 - Math.pow(-2 * x + 2, 2) / 2; }

/** Ground between two x values, with its end points. */
function groundBetween(ground, a, b) {
  const pts = [[a, yAt(ground, a)]];
  for (const p of ground) if (p[0] > a && p[0] < b) pts.push([...p]);
  pts.push([b, yAt(ground, b)]);
  return pts;
}

/** How the mass moves: rotation about the circle centre, or sliding along the surface. */
function motionOf(surface, massStack) {
  const slip = surface.slip;
  const L = Math.hypot(slip[slip.length - 1][0] - slip[0][0], slip[slip.length - 1][1] - slip[0][1]);
  const travel = 0.12 * L;
  // which way is down: from the higher end of the surface to the lower end
  const hi = slip[0][1] > slip[slip.length - 1][1] ? slip[0] : slip[slip.length - 1];
  const lo = hi === slip[0] ? slip[slip.length - 1] : slip[0];
  if (surface.circle) {
    const { xc, yc, R } = surface.circle;
    const angle = travel / R;
    // rotate so that the high end moves towards the low end
    const sign = Math.sign((hi[0] - xc) * (lo[1] - hi[1]) - (hi[1] - yc) * (lo[0] - hi[0])) || 1;
    return {
      apply(s) {
        const th = sign * angle * s;
        const g = this.group;
        g.position.set(0, 0, 0); g.rotation.set(0, 0, 0);
        g.position.set(xc - (xc * Math.cos(th) - yc * Math.sin(th)), yc - (xc * Math.sin(th) + yc * Math.cos(th)), 0);
        g.rotation.z = th;
      },
    };
  }
  const dx = lo[0] - hi[0], dy = lo[1] - hi[1], n = Math.hypot(dx, dy) || 1;
  return { apply(s) { this.group.position.set(dx / n * travel * s, dy / n * travel * s, 0); this.group.rotation.z = 0; } };
}

/** A strip surface following a polyline across z0..z1. */
function ribbon(poly, z0, z1) {
  const pos = [], idx = [];
  poly.forEach(([x, y], i) => {
    pos.push(x, y, z0, x, y, z1);
    if (i) { const a = 2 * (i - 1); idx.push(a, a + 1, a + 2, a + 1, a + 3, a + 2); }
  });
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.setIndex(idx);
  g.computeVertexNormals();
  return g;
}

/** Instanced rocks or interlocking units laid on the face. */
function armourUnits(g, a, D) {
  const group = new THREE.Group();
  const [xt, yt] = [a.toe[0], a.toe[1]], [xc, yc] = [a.crest[0], a.crest[1]];
  const len = Math.hypot(xc - xt, yc - yt);
  const ux = (xc - xt) / len, uy = (yc - yt) / len;
  let nx = -uy, ny = ux;                      // normal pointing out of the face (upwards)
  if (ny < 0) { nx = -nx; ny = -ny; }
  const Dn = a.Dn, t = a.thickness;
  const rock = a.kind === "rock";
  const step = rock ? Dn * 1.05 : Dn * 1.25;
  const nAlong = Math.max(1, Math.floor(len / step)), nAcross = Math.max(1, Math.floor(D / step));
  const layers = rock ? 2 : 1;
  const total = Math.min(4000, nAlong * nAcross * layers);
  const geo = rock ? new THREE.IcosahedronGeometry(0.62, 0) : interlockingUnit();
  const mat = new THREE.MeshStandardMaterial({ color: rock ? 0x8a8780 : 0xc9cbcf, roughness: rock ? 0.95 : 0.7, flatShading: rock });
  const mesh = new THREE.InstancedMesh(geo, mat, total);
  mesh.castShadow = true; mesh.receiveShadow = true;
  const m = new THREE.Matrix4(), q = new THREE.Quaternion(), e = new THREE.Euler(), s = new THREE.Vector3(), p = new THREE.Vector3();
  const colour = new THREE.Color();
  let rnd = 12345;
  const rand = () => ((rnd = (rnd * 16807) % 2147483647) / 2147483647);
  let n = 0;
  for (let L = 0; L < layers && n < total; L++) {
    for (let i = 0; i < nAlong && n < total; i++) {
      for (let j = 0; j < nAcross && n < total; j++) {
        const sAlong = (i + 0.5 + (j % 2) * 0.5 + (rand() - 0.5) * 0.2) * step;
        if (sAlong > len) continue;
        const depth = rock ? (t / layers) * (layers - L - 0.5) : t * 0.5;
        p.set(xt + ux * sAlong - nx * depth, yt + uy * sAlong - ny * depth, -D / 2 + (j + 0.5 + (rand() - 0.5) * 0.25) * (D / nAcross));
        e.set(rand() * 6.28, rand() * 6.28, rand() * 6.28);
        q.setFromEuler(e);
        const k = rock ? Dn * (0.85 + rand() * 0.35) : Dn * 1.05;
        s.set(k * (rock ? 0.9 + rand() * 0.3 : 1), k * (rock ? 0.8 + rand() * 0.3 : 1), k);
        m.compose(p, q, s);
        mesh.setMatrixAt(n, m);
        const shade = rock ? 0.75 + rand() * 0.3 : 0.92 + rand() * 0.08;
        mesh.setColorAt(n, colour.set(rock ? 0x8a8780 : 0xc9cbcf).multiplyScalar(shade));
        n++;
      }
    }
  }
  mesh.count = n;
  group.add(mesh);
  return group;
}
