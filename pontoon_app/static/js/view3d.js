// Pontoon — the marina arm in 3D: walkway and finger pontoons floating at the chosen
// water level, guide piles down to their toes, the design boats in their berths, the
// gangway, and the sea moving with the design wave. In Modes the walkway module
// deforms with the selected natural mode, animated.
import * as THREE from "three";
import { OrbitControls } from "../vendor/three/OrbitControls.js";
import { layoutGeometry } from "../engine/geometry.js";

const COL = {
  concrete: 0xc9c6bd, deck: 0xb08a5a, float: 0x3b3f45, cube: 0x2a78d6, water: 0x2a78d6, bed: 0xcdb98f,
  steel: 0x5b6470, band: 0xf2c200, boat: 0xf7f7f5, cabin: 0x9fb4c8, gangway: 0xa8adb3, timber: 0x8a6a42, pconcrete: 0xa9a59b,
};

function box(x0, x1, y0, y1, z0, z1, mat) {
  const g = new THREE.BoxGeometry(x1 - x0, y1 - y0, z1 - z0);
  const m = new THREE.Mesh(g, mat);
  m.position.set((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2);
  m.castShadow = true; m.receiveShadow = true;
  return m;
}

function hull(L, B, H, mat) {
  // plan shape: square stern, pointed bow at +x
  const s = new THREE.Shape();
  s.moveTo(-L / 2, -B / 2); s.lineTo(L * 0.15, -B / 2);
  s.quadraticCurveTo(L * 0.42, -B * 0.42, L / 2, 0);
  s.quadraticCurveTo(L * 0.42, B * 0.42, L * 0.15, B / 2);
  s.lineTo(-L / 2, B / 2); s.closePath();
  const g = new THREE.ExtrudeGeometry(s, { depth: H, bevelEnabled: true, bevelThickness: 0.08, bevelSize: 0.08, bevelSegments: 2 });
  return new THREE.Mesh(g, mat);
}

export class View3D {
  constructor(host) {
    this.host = host;
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.shadowMap.enabled = true;
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    host.prepend(this.renderer.domElement);
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(35, 1, 0.1, 5000);
    this.camera.up.set(0, 0, 1);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.08;
    this.controls.screenSpacePanning = true;
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x6d6a60, 1.15));
    const sun = new THREE.DirectionalLight(0xffffff, 1.5);
    sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    sun.shadow.bias = -0.0005;
    this.sun = sun;
    this.scene.add(sun, sun.target);
    this.world = new THREE.Group();
    this.scene.add(this.world);
    this.clock = new THREE.Clock();
    this.fitKey = null;
    this.anim = [];
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
      if (o.material) (Array.isArray(o.material) ? o.material : [o.material]).forEach((m) => m.dispose?.());
    });
    this.world.clear();
    this.anim = [];
  }

  mats() {
    const dark = matchMedia("(prefers-color-scheme: dark)").matches && document.documentElement.getAttribute("data-theme") !== "light" || document.documentElement.getAttribute("data-theme") === "dark";
    const std = (c, o = {}) => new THREE.MeshStandardMaterial({ color: c, roughness: 0.8, metalness: 0.05, ...o });
    return {
      concrete: std(COL.concrete), deck: std(COL.deck), float: std(COL.float, { roughness: 0.6 }), cube: std(COL.cube, { roughness: 0.5 }),
      water: new THREE.MeshStandardMaterial({ color: COL.water, transparent: true, opacity: dark ? 0.55 : 0.42, roughness: 0.15, metalness: 0.1, side: THREE.DoubleSide }),
      bed: std(COL.bed, { roughness: 1 }), steel: std(COL.steel, { metalness: 0.4, roughness: 0.5 }), band: std(COL.band),
      buried: std(COL.steel, { transparent: true, opacity: 0.25 }), boat: std(COL.boat, { roughness: 0.4 }), cabin: std(COL.cabin, { roughness: 0.3 }),
      gangway: std(COL.gangway, { metalness: 0.5, roughness: 0.4 }), timber: std(COL.timber), pconcrete: std(COL.pconcrete),
    };
  }

  /** Water surface, animated with the design wave (true height, period and length). */
  water(x0, x1, y0, y1, z, wave, M) {
    const nx = 80, ny = 30;
    const g = new THREE.PlaneGeometry(x1 - x0, y1 - y0, nx, ny);
    g.translate((x0 + x1) / 2, (y0 + y1) / 2, z);
    const mesh = new THREE.Mesh(g, M.water);
    mesh.receiveShadow = true;
    this.world.add(mesh);
    if (wave && wave.H > 0) {
      const pos = g.attributes.position, base = Float32Array.from(pos.array);
      const k = (2 * Math.PI) / wave.L, w = (2 * Math.PI) / wave.T;
      this.anim.push((t) => {
        for (let i = 0; i < pos.count; i++) pos.array[i * 3 + 2] = base[i * 3 + 2] + (wave.H / 2) * Math.cos(k * base[i * 3 + 1] - w * t);
        pos.needsUpdate = true;
      });
    }
  }

  /** The whole arm at a water level. */
  showLayout(r, levelKey = "HAT") {
    this.clear();
    const M = this.mats();
    const geo = layoutGeometry(r, levelKey), p = r.project, type = p.type;
    const { x0, x1, y0, y1 } = geo.extent;
    this.water(x0 - 10, x1 + 10, y0 - 10, y1 + 10, geo.level, { H: +p.site.Hs, T: +p.site.Tp, L: r.struct.walkway.lam || 10 }, M);
    this.world.add(box(x0 - 10, x1 + 10, y0 - 10, y1 + 10, geo.seabed - 0.3, geo.seabed, M.bed));
    for (const it of geo.items) {
      if (it.kind === "walkway" || it.kind === "finger") this.pontoon(it, r, M, it.kind === "finger" ? r.floats.finger.sec : r.floats.walkway.sec);
      else if (it.kind === "pile") {
        const above = new THREE.Mesh(new THREE.CylinderGeometry(it.D / 2, it.D / 2, it.top - it.bed, 24), it.section.kind === "steel" ? M.steel : it.section.kind === "timber" ? M.timber : M.pconcrete);
        above.rotation.x = Math.PI / 2; above.position.set(it.x, it.y, (it.top + it.bed) / 2); above.castShadow = true;
        const below = new THREE.Mesh(new THREE.CylinderGeometry(it.D / 2, it.D / 2, it.bed - it.toe, 16), M.buried);
        below.rotation.x = Math.PI / 2; below.position.set(it.x, it.y, (it.bed + it.toe) / 2);
        const band = new THREE.Mesh(new THREE.CylinderGeometry(it.D / 2 + 0.01, it.D / 2 + 0.01, 0.3, 24), M.band);
        band.rotation.x = Math.PI / 2; band.position.set(it.x, it.y, it.top - 0.45);
        this.world.add(above, below, band);
      } else if (it.kind === "guide") {
        this.world.add(box(it.x0, it.x1, it.y0, it.y1, it.z0, it.z1, M.steel));
      } else if (it.kind === "chain") {
        const curve = new THREE.CatmullRomCurve3(it.pts.map(([x, y, z]) => new THREE.Vector3(x, y, z)));
        const tube = new THREE.Mesh(new THREE.TubeGeometry(curve, 48, Math.max(0.03, it.d / 1000), 6, false), M.steel);
        this.world.add(tube);
      } else if (it.kind === "anchor") {
        const a = it.side / 2;
        this.world.add(box(it.x - a, it.x + a, it.y - a, it.y + a, it.z, it.z + it.side, M.pconcrete));
      } else if (it.kind === "boat") {
        const h = hull(it.L, it.B, it.motor ? 1.4 : 1.1, M.boat);
        h.rotation.z = it.dir > 0 ? Math.PI / 2 : -Math.PI / 2;
        h.position.set(it.xc, it.yc, it.z - it.draught);
        h.castShadow = true;
        const cab = box(-it.L * 0.25, it.L * 0.12, -it.B * 0.32, it.B * 0.32, 0, it.motor ? 1.3 : 0.7, M.cabin);
        cab.position.z = 1.4 + (it.motor ? 0.65 : 0.35);
        cab.position.x = -it.L * 0.06;
        h.add(cab);
        if (!it.motor) {
          const mast = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.06, it.L * 1.2, 8), M.steel);
          mast.rotation.x = Math.PI / 2; mast.position.set(0, 0, 1.2 + it.L * 0.6);
          h.add(mast);
        }
        this.world.add(h);
      } else if (it.kind === "gangway") {
        const len = Math.hypot(it.x1 - it.x0, it.z1 - it.z0), ang = Math.atan2(it.z1 - it.z0, it.x1 - it.x0);
        const g = new THREE.Group();
        g.add(box(0, len, -it.w / 2 - 0.05, it.w / 2 + 0.05, -0.08, 0.04, M.gangway));
        for (const s of [-1, 1]) g.add(box(0, len, s * (it.w / 2 + 0.05) - 0.025, s * (it.w / 2 + 0.05) + 0.025, 0, 1.0, M.gangway));
        g.position.set(it.x0, it.y || 0, it.z0); g.rotation.y = -ang;
        this.world.add(g);
        this.world.add(box(it.x0 - 4, it.x0, (it.y || 0) - 3, (it.y || 0) + 3, it.z0 - 2, it.z0, M.pconcrete));
      }
    }
    this.fit(geo.extent, `layout:${r.layout.shape}:${r.layout.arms}:${r.layout.walkLen}:${r.layout.fingerL}`, geo.level);
    this.sunAt(geo.extent);
  }

  pontoon(it, r, M, sec) {
    const type = it.landingKind === "concrete" || (it.kind === "finger" && r.project.type === "attenuator") ? "concrete" : r.project.type;
    const alongY = it.kind === "finger" || it.along === "y";
    const P = sec.parts;
    if (type === "framed") {
      const L = it.x1 - it.x0, W = it.y1 - it.y0, across = alongY ? "x" : "y";
      // floats under a frame and deck
      const fl = P.nf, fw = P.fw, gap = P.gap, cov = sec.cover;
      const n = Math.max(1, Math.round(((across === "y" ? L : W) * cov) / 2.4));
      for (let j = 0; j < n; j++) for (let i = 0; i < fl; i++) {
        const a0 = -(across === "y" ? W : L) / 2 + (fl === 1 ? ((across === "y" ? W : L) - fw) / 2 : i * (fw + gap));
        const len = across === "y" ? L : W, seg = len / n, c0 = -len / 2 + j * seg + seg * (1 - cov) / 2;
        const m = across === "y"
          ? box(it.x0 + len / 2 + c0, it.x0 + len / 2 + c0 + seg * cov, (it.y0 + it.y1) / 2 + a0, (it.y0 + it.y1) / 2 + a0 + fw, it.z0, it.z0 + P.fh, M.float)
          : box((it.x0 + it.x1) / 2 + a0, (it.x0 + it.x1) / 2 + a0 + fw, it.y0 + len / 2 + c0, it.y0 + len / 2 + c0 + seg * cov, it.z0, it.z0 + P.fh, M.float);
        this.world.add(m);
      }
      this.world.add(box(it.x0, it.x1, it.y0, it.y1, it.z0 + P.fh, it.z1 - P.deckT, M.steel));
      this.world.add(box(it.x0, it.x1, it.y0, it.y1, it.z1 - P.deckT, it.z1, M.deck));
    } else if (type === "modular") {
      const m = box(it.x0, it.x1, it.y0, it.y1, it.z0, it.z1, M.cube);
      this.world.add(m);
      // the cube joints, drawn as lines on the deck
      const pts = [];
      for (let x = it.x0; x <= it.x1 + 1e-6; x += 0.5) pts.push(x, it.y0, it.z1 + 0.005, x, it.y1, it.z1 + 0.005);
      for (let y = it.y0; y <= it.y1 + 1e-6; y += 0.5) pts.push(it.x0, y, it.z1 + 0.005, it.x1, y, it.z1 + 0.005);
      const g = new THREE.BufferGeometry(); g.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
      this.world.add(new THREE.LineSegments(g, new THREE.LineBasicMaterial({ color: 0x174a87 })));
    } else {
      this.world.add(box(it.x0, it.x1, it.y0, it.y1, it.z0, it.z1, M.concrete));
      // timber walers along the edges
      const t = 0.15;
      if (it.along === "y") {
        this.world.add(box(it.x0 - t, it.x0, it.y0, it.y1, it.z1 - 0.35, it.z1 - 0.05, M.timber));
        this.world.add(box(it.x1, it.x1 + t, it.y0, it.y1, it.z1 - 0.35, it.z1 - 0.05, M.timber));
      } else {
        this.world.add(box(it.x0, it.x1, it.y0 - t, it.y0, it.z1 - 0.35, it.z1 - 0.05, M.timber));
        this.world.add(box(it.x0, it.x1, it.y1, it.y1 + t, it.z1 - 0.35, it.z1 - 0.05, M.timber));
      }
    }
  }

  /** One walkway module deforming with a natural mode (exaggerated, animated). */
  showMode(r, modeIndex) {
    this.clear();
    const M = this.mats();
    const lay = r.layout, sec = r.floats.walkway.sec, T = r.floats.walkway.ini.T, B = lay.walkW, L = lay.moduleL;
    const lv = 0;
    this.water(-L * 0.4, L * 1.4, -B * 3, B * 3, lv, null, M);
    const modes = r.dyn.flex, md = modes[Math.min(modeIndex, modes.length - 1)];
    const isRoll = modeIndex === "roll";
    const nx = 60;
    const g = new THREE.BoxGeometry(L, B, sec.deck, nx, 2, 2);
    g.translate(L / 2, 0, -T + sec.deck / 2);
    const mat = r.project.type === "modular" ? M.cube : r.project.type === "framed" ? M.deck : M.concrete;
    const mesh = new THREE.Mesh(g, mat);
    mesh.castShadow = true;
    this.world.add(mesh);
    const pos = g.attributes.position, base = Float32Array.from(pos.array);
    const amp = 0.08 * L; // drawn amplitude
    const shapeAt = (x) => {
      if (isRoll || !md) return 0;
      const xs = md.x, w = md.shape;
      let i = 0;
      while (i < xs.length - 2 && xs[i + 1] < x) i++;
      const t = (x - xs[i]) / (xs[i + 1] - xs[i] || 1);
      return w[i] + t * (w[i + 1] - w[i]);
    };
    const shape = Array.from({ length: pos.count }, (_, i) => shapeAt(base[i * 3]));
    const period = 1.6; // seconds on screen, whatever the real period
    this.anim.push((t) => {
      const s = Math.sin((2 * Math.PI * t) / period);
      if (isRoll) { mesh.rotation.x = 0.15 * s; return; }
      for (let i = 0; i < pos.count; i++) pos.array[i * 3 + 2] = base[i * 3 + 2] + amp * shape[i] * s;
      pos.needsUpdate = true;
      g.computeVertexNormals();
    });
    this.fit({ x0: -L * 0.1, x1: L * 1.1, y: B * 2 }, `mode:${L}:${B}`, lv);
    this.sunAt({ x0: 0, x1: L, y: B * 2 });
  }

  sunAt(ext) {
    const cx = (ext.x0 + ext.x1) / 2, cy = ext.y0 !== undefined ? (ext.y0 + ext.y1) / 2 : 0, R = Math.max(ext.x1 - ext.x0, ext.y * 2);
    this.sun.position.set(cx - R * 0.3, cy - R * 0.6, R * 0.9);
    this.sun.target.position.set(cx, cy, 0);
    const sh = this.sun.shadow.camera;
    sh.left = -R; sh.right = R; sh.top = R; sh.bottom = -R; sh.near = 0.1; sh.far = R * 4;
    sh.updateProjectionMatrix();
  }

  fit(ext, key, z) {
    if (this.fitKey === key) return;
    this.fitKey = key;
    const cx = (ext.x0 + ext.x1) / 2, cy = ext.y0 !== undefined ? (ext.y0 + ext.y1) / 2 : 0, R = Math.max(ext.x1 - ext.x0, ext.y * 2);
    this.controls.target.set(cx, cy, z);
    this.camera.position.set(cx - R * 0.35, cy - R * 0.85, z + R * 0.5);
    this.camera.near = R / 500; this.camera.far = R * 30;
    this.camera.updateProjectionMatrix();
  }

  frame() {
    const t = this.clock.getElapsedTime();
    for (const f of this.anim) f(t);
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  }

  snapshot() {
    this.renderer.render(this.scene, this.camera);
    return this.renderer.domElement.toDataURL("image/png");
  }
}
