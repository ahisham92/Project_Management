// MarineTwin: extreme events drawn as they happen.
//
// When an event strikes (in the live port when the clock reaches it, on the Risks page when it is
// picked) its effect plays at the place it hits: an explosion and the fire after it, a missile
// coming in, the ground shaking, a crane toppling into the water, a ship striking the quay, a
// slick spreading, the sea over the apron, soldiers at the gate... The area it closes is fenced
// off with barriers, AREA CLOSED signs and flashing beacons. What plays once (a blast, a fall)
// runs in real seconds whatever the speed of the clock, so it can be watched; what lasts (fire,
// smoke, the wreck, the cordon) stays while the area is closed. Everything is removed when the
// event ends or another situation is picked.
//
// Particles (flame, smoke, spray, dust) are two point clouds drawn with a small shader, one added
// for light and one blended for smoke, each a fixed pool reused round and round: a fire costs
// no more than a handful of draw calls however long it burns.

import * as THREE from 'three';

const UP = new THREE.Vector3(0, 1, 0);
const rand = (a, b) => a + Math.random() * (b - a);
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const smooth = (u) => { const x = clamp(u, 0, 1); return x * x * (3 - 2 * x); };

// --- particles -------------------------------------------------------------------------------
function particlePool(n, additive) {
  const pos = new Float32Array(n * 3);
  const tint = new Float32Array(n * 4);
  const size = new Float32Array(n);
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  geo.setAttribute('tint', new THREE.BufferAttribute(tint, 4));
  geo.setAttribute('size', new THREE.BufferAttribute(size, 1));
  const mat = new THREE.ShaderMaterial({
    uniforms: { scale: { value: 500 } },
    vertexShader: `attribute float size; attribute vec4 tint; varying vec4 vTint; uniform float scale;
      void main() { vTint = tint; vec4 mv = modelViewMatrix * vec4(position, 1.0);
        gl_PointSize = size * scale / max(1.0, -mv.z); gl_Position = projectionMatrix * mv; }`,
    fragmentShader: `varying vec4 vTint;
      void main() { vec2 d = gl_PointCoord - 0.5; float r = length(d) * 2.0; if (r > 1.0) discard;
        gl_FragColor = vec4(vTint.rgb, vTint.a * (1.0 - r * r)); }`,
    transparent: true, depthWrite: false, blending: additive ? THREE.AdditiveBlending : THREE.NormalBlending,
  });
  const points = new THREE.Points(geo, mat);
  points.frustumCulled = false;
  points.renderOrder = additive ? 4 : 3;
  // Per particle: velocity, age, life, size from and to, colour from and to, drag, rise, and the
  // level it cannot fall below (the water, the deck).
  const P = Array.from({ length: n }, () => ({ v: new THREE.Vector3(), age: 1, life: 0, s0: 0, s1: 0, c0: [0, 0, 0, 0], c1: [0, 0, 0, 0], drag: 0, rise: 0, floor: -Infinity }));
  let next = 0;
  let live = 0;
  return {
    points, mat,
    spawn(at, v, life, s0, s1, c0, c1, drag = 0.5, rise = 0, floor = -Infinity) {
      const i = next;
      next = (next + 1) % n;
      const p = P[i];
      pos[i * 3] = at.x; pos[i * 3 + 1] = at.y; pos[i * 3 + 2] = at.z;
      p.v.copy(v); p.age = 0; p.life = life; p.s0 = s0; p.s1 = s1; p.c0 = c0; p.c1 = c1; p.drag = drag; p.rise = rise; p.floor = floor;
      live = n;
    },
    update(dt, wind) {
      if (!live) return;
      let any = 0;
      for (let i = 0; i < n; i++) {
        const p = P[i];
        if (p.age >= p.life) { if (size[i]) { size[i] = 0; tint[i * 4 + 3] = 0; } continue; }
        any++;
        p.age += dt;
        const u = Math.min(1, p.age / p.life);
        p.v.y += p.rise * dt;
        p.v.multiplyScalar(Math.max(0, 1 - p.drag * dt));
        pos[i * 3] += (p.v.x + wind.x * u) * dt;
        pos[i * 3 + 1] = Math.max(p.floor, pos[i * 3 + 1] + p.v.y * dt);
        pos[i * 3 + 2] += (p.v.z + wind.z * u) * dt;
        size[i] = p.s0 + (p.s1 - p.s0) * u;
        for (let k = 0; k < 4; k++) tint[i * 4 + k] = p.c0[k] + (p.c1[k] - p.c0[k]) * u;
      }
      live = any;
      geo.attributes.position.needsUpdate = geo.attributes.tint.needsUpdate = geo.attributes.size.needsUpdate = true;
    },
    clear() { for (const p of P) p.age = p.life = 1; live = n; },
  };
}

// A sign's face, drawn once: AREA CLOSED in white on red, as on a road closure.
function signTexture(words) {
  const canvas = document.createElement('canvas');
  canvas.width = 256;
  canvas.height = 128;
  const c = canvas.getContext('2d');
  c.fillStyle = '#c62828'; c.fillRect(0, 0, 256, 128);
  c.strokeStyle = '#fff'; c.lineWidth = 8; c.strokeRect(8, 8, 240, 112);
  c.fillStyle = '#fff'; c.font = 'bold 40px sans-serif'; c.textAlign = 'center'; c.textBaseline = 'middle';
  const lines = words.split('\n');
  lines.forEach((l, i) => c.fillText(l, 128, 64 + (i - (lines.length - 1) / 2) * 44));
  const t = new THREE.CanvasTexture(canvas);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

// An oil slick: dark, uneven, with a rainbow sheen at its edges.
function slickTexture() {
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 256;
  const c = canvas.getContext('2d');
  for (let i = 0; i < 40; i++) {
    const x = 128 + rand(-70, 70);
    const y = 128 + rand(-70, 70);
    const r = rand(25, 70);
    const g = c.createRadialGradient(x, y, 0, x, y, r);
    g.addColorStop(0, 'rgba(8,8,10,0.85)');
    g.addColorStop(0.7, 'rgba(30,25,40,0.5)');
    g.addColorStop(0.9, 'rgba(90,60,120,0.18)');
    g.addColorStop(1, 'rgba(0,0,0,0)');
    c.fillStyle = g;
    c.beginPath(); c.arc(x, y, r, 0, Math.PI * 2); c.fill();
  }
  return new THREE.CanvasTexture(canvas);
}

// --- the effects -------------------------------------------------------------------------------
// ctx: { scene, camera, renderer, site, frame, view, ship, vehicle, box, REAL, tide(), seaAt(x, z),
//        atSea(x, z, margin), apron(): [[x, z] × 4] quads of the apron and yard, gate(): {x, z} }
export function eventEffects(ctx) {
  const { scene, camera, renderer, site, view } = ctx;
  const glow = particlePool(2600, true);
  const smoke = particlePool(2600, false);
  scene.add(glow.points, smoke.points);
  // Two lights for flashes and fires, made now (adding lights later recompiles every material).
  const flash = new THREE.PointLight(0xffc070, 0, 900, 1.4);
  const fireLight = new THREE.PointLight(0xff7a2a, 0, 300, 1.6);
  scene.add(flash, fireLight);
  const wind = new THREE.Vector3(3, 0, 1.5);
  const root = new THREE.Group();
  scene.add(root);
  const banner = document.createElement('div');
  banner.className = 'mt-event-banner';
  banner.hidden = true;
  view.appendChild(banner);

  let on = null;                // the event shown: { key, age, tickers, restore, shake }
  const tmp = new THREE.Vector3();

  // A fire at a point (or following a ship): flames, the glow of them and a smoke column.
  function fire(at, scale = 1, opts = {}) {
    const where = typeof at === 'function' ? at : () => at;
    let acc = 0;
    let accS = 0;
    const smokeCol = opts.toxic ? [0.75, 0.82, 0.25] : opts.white ? [0.85, 0.85, 0.85] : [0.12, 0.11, 0.1];
    return (dt, age) => {
      const p = where();
      if (!p) return;
      const k = opts.grow ? clamp(age / opts.grow, 0.15, 1) : 1;
      acc += dt * 90 * scale * k * (opts.toxic ? 0.2 : 1);
      accS += dt * 22 * scale * k;
      for (; acc > 1; acc--) {
        tmp.set(p.x + rand(-4, 4) * scale, p.y + rand(0, 2), p.z + rand(-4, 4) * scale);
        glow.spawn(tmp, new THREE.Vector3(rand(-1, 1), rand(4, 9) * Math.sqrt(scale), rand(-1, 1)), rand(0.5, 1.1), 5.5 * scale, 1.5 * scale,
          [1, rand(0.55, 0.8), 0.2, 0.9], [0.9, 0.25, 0.05, 0], 0.2, 2);
      }
      for (; accS > 1; accS--) {
        tmp.set(p.x + rand(-3, 3) * scale, p.y + (opts.toxic ? 1 : 5 * scale), p.z + rand(-3, 3) * scale);
        const g = rand(0.85, 1.15);
        const up = opts.toxic ? rand(0.3, 1) : rand(3, 6) * Math.sqrt(scale);
        smoke.spawn(tmp, new THREE.Vector3(rand(-0.6, 0.6) * (opts.toxic ? 4 : 1), up, rand(-0.6, 0.6) * (opts.toxic ? 4 : 1)), rand(9, 16), 6 * scale, 34 * scale,
          [smokeCol[0] * g, smokeCol[1] * g, smokeCol[2] * g, opts.toxic ? 0.35 : 0.6], [smokeCol[0] + 0.2, smokeCol[1] + 0.2, smokeCol[2] + 0.2, 0], 0.15, opts.toxic ? 0 : 0.25);
      }
      if (!opts.toxic) {
        fireLight.position.copy(p).setY(p.y + 8);
        fireLight.intensity = Math.max(fireLight.intensity * 0.5, (600 + 300 * Math.random()) * scale);
      }
    };
  }

  // A blast: the flash, a ball of fire, the shock ring on the ground, debris thrown out, and the
  // dark cloud rising after it. `scale` 1 is a car bomb; 2.5 a warhead or a ship's cargo going up.
  function explosion(at, scale = 1) {
    flash.position.copy(at).setY(at.y + 12);
    flash.intensity = 60000 * scale;
    for (let i = 0; i < 320 * scale; i++) {
      const d = new THREE.Vector3(rand(-1, 1), rand(0.1, 1.3), rand(-1, 1)).normalize().multiplyScalar(rand(6, 22) * Math.sqrt(scale));
      glow.spawn(at, d, rand(0.6, 1.6), rand(14, 26) * scale, 4 * scale, [1, rand(0.45, 0.7), 0.15, 0.8], [0.8, 0.15, 0.02, 0], 1.6, 4);
    }
    // Sparks and burning bits flung out.
    for (let i = 0; i < 120 * scale; i++) {
      const d = new THREE.Vector3(rand(-1, 1), rand(0.4, 1.5), rand(-1, 1)).normalize().multiplyScalar(rand(20, 45) * Math.sqrt(scale));
      glow.spawn(at, d, rand(1, 2.2), 1.6, 0.6, [1, 0.8, 0.4, 1], [1, 0.3, 0.05, 0], 0.3, -9.8, at.y);
    }
    for (let i = 0; i < 120 * scale; i++) {
      const d = new THREE.Vector3(rand(-1, 1), rand(0.3, 1.4), rand(-1, 1)).normalize().multiplyScalar(rand(4, 14) * Math.sqrt(scale));
      smoke.spawn(at.clone().add(new THREE.Vector3(0, 4, 0)), d, rand(6, 14), 10 * scale, 45 * scale, [0.1, 0.09, 0.08, 0.85], [0.35, 0.33, 0.32, 0], 0.6, 1.2);
    }
    // The ring of dust along the ground.
    for (let i = 0; i < 90 * scale; i++) {
      const a = (i / (90 * scale)) * Math.PI * 2;
      smoke.spawn(at.clone().setY(at.y + 1), new THREE.Vector3(Math.cos(a), 0, Math.sin(a)).multiplyScalar(rand(18, 28) * Math.sqrt(scale)), rand(3, 5), 5 * scale, 16 * scale,
        [0.55, 0.5, 0.42, 0.6], [0.6, 0.56, 0.5, 0], 1.4, 0.1);
    }
    // Debris: chunks thrown out on high arcs, landing about the area and lying there.
    const n = Math.round(36 * scale);
    const geo = new THREE.BoxGeometry(1, 1, 1);
    const mat = new THREE.MeshStandardMaterial({ color: 0x2a2826, roughness: 0.9 });
    const chunks = new THREE.InstancedMesh(geo, mat, n);
    chunks.castShadow = true;
    chunks.frustumCulled = false;
    root.add(chunks);
    const bits = Array.from({ length: n }, () => ({
      p: at.clone().setY(at.y + 2), v: new THREE.Vector3(rand(-1, 1), rand(0.8, 1.6), rand(-1, 1)).multiplyScalar(rand(10, 28) * Math.sqrt(scale)),
      r: new THREE.Euler(rand(0, 3), rand(0, 3), rand(0, 3)), s: rand(0.5, 1.8) * Math.sqrt(scale), w: rand(-6, 6),
    }));
    const m = new THREE.Matrix4();
    const q = new THREE.Quaternion();
    const floor = at.y - 0.2;
    return (dt) => {
      flash.intensity *= Math.max(0, 1 - dt * 5);
      for (const [i, b] of bits.entries()) {
        if (b.p.y > floor + b.s / 2 || b.v.y > 0) {
          b.v.y -= 9.8 * dt;
          b.p.addScaledVector(b.v, dt);
          b.r.x += b.w * dt; b.r.y += b.w * dt * 0.7;
          if (b.p.y < floor + b.s / 2) { b.p.y = floor + b.s / 2; b.v.set(0, 0, 0); }
        }
        chunks.setMatrixAt(i, m.compose(b.p, q.setFromEuler(b.r), tmp.set(b.s, b.s * 0.6, b.s * 0.8)));
      }
      chunks.instanceMatrix.needsUpdate = true;
    };
  }

  // A scorch mark (and a crater: its rim of broken concrete) on the deck.
  function scorch(at, r, crater = false) {
    const disc = new THREE.Mesh(new THREE.CircleGeometry(r, 32), new THREE.MeshBasicMaterial({ color: 0x0b0a09, transparent: true, opacity: 0.8, depthWrite: false }));
    disc.rotation.x = -Math.PI / 2;
    disc.position.copy(at).setY(at.y + 0.12);
    disc.renderOrder = 2;
    root.add(disc);
    if (crater) {
      const pit = new THREE.Mesh(new THREE.CircleGeometry(r * 0.45, 24), new THREE.MeshBasicMaterial({ color: 0x000000 }));
      pit.rotation.x = -Math.PI / 2;
      pit.position.copy(at).setY(at.y + 0.15);
      root.add(pit);
      const n = 40;
      const rim = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1), new THREE.MeshStandardMaterial({ color: 0x77736c, roughness: 1 }), n);
      const m = new THREE.Matrix4();
      for (let i = 0; i < n; i++) {
        const a = (i / n) * Math.PI * 2 + rand(-0.1, 0.1);
        const d = r * rand(0.45, 0.7);
        const s = rand(1, 2.6);
        m.compose(tmp.set(at.x + Math.cos(a) * d, at.y + s * 0.3, at.z + Math.sin(a) * d), new THREE.Quaternion().setFromEuler(new THREE.Euler(rand(0, 1), a, rand(0, 1))), new THREE.Vector3(s, s * 0.6, s));
        rim.setMatrixAt(i, m);
      }
      rim.castShadow = true;
      root.add(rim);
    }
  }

  // Cracks across the deck: dark jagged lines in the area.
  function cracks(centre, r, count, y) {
    const segs = [];
    // Cracks only on the deck: a start over the water is tried again, and a crack stops at the edge.
    const onDeck = (x, z) => !ctx.inlandOf || ctx.inlandOf(x, z) > 1.5;
    for (let c = 0; c < count; c++) {
      let x;
      let z;
      let tries = 0;
      do { x = centre.x + rand(-r, r); z = centre.z + rand(-r, r); } while (!onDeck(x, z) && ++tries < 20);
      if (!onDeck(x, z)) continue;
      let a = rand(0, Math.PI * 2);
      for (let k = 0; k < 14; k++) {
        const l = rand(2, 6);
        if (!onDeck(x + Math.cos(a) * l, z + Math.sin(a) * l)) break;
        segs.push([x, z, a, l]);
        x += Math.cos(a) * l; z += Math.sin(a) * l;
        a += rand(-0.7, 0.7);
      }
    }
    if (!segs.length) return;
    const im = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 0.1, 0.35), new THREE.MeshBasicMaterial({ color: 0x050505 }), segs.length);
    const m = new THREE.Matrix4();
    segs.forEach(([x, z, a, l], i) => {
      m.compose(tmp.set(x + Math.cos(a) * l / 2, y + 0.14, z + Math.sin(a) * l / 2), new THREE.Quaternion().setFromAxisAngle(UP, -a), new THREE.Vector3(l, 1, rand(0.6, 1.6)));
      im.setMatrixAt(i, m);
    });
    root.add(im);
  }

  // Cranes near a point, nearest first.
  const cranesNear = (p, within = Infinity, rail = true) => site.cranes
    .filter((c) => (!rail || c.userData.trolley) && Math.hypot(c.position.x - p.x, c.position.z - p.z) < within)
    .sort((a, b) => Math.hypot(a.position.x - p.x, a.position.z - p.z) - Math.hypot(b.position.x - p.x, b.position.z - p.z));

  // A crane going over: about its seaward legs, into the water, with a splash; it stays there.
  function topple(crane, delay = 0, final = -1.62) {
    const u = crane.userData;
    on.restore.push(() => { crane.rotation.order = 'XYZ'; crane.rotation.x = 0; crane.position.y = u.baseY; u.fallen = false; if (u.boom) u.boom.rotation.x = 0; });
    u.baseY = crane.position.y;
    crane.rotation.order = 'YXZ';
    u.fallen = true;
    let t = -delay;
    let splashed = false;
    const tip = new THREE.Vector3();
    return (dt) => {
      t += dt;
      if (t < 0) return;
      // Slow at first, then faster as it goes over, as a falling thing does.
      const a = Math.min(-final, 0.36 * t * t);
      crane.rotation.x = -a;
      crane.position.y = u.baseY - Math.max(0, a - 1.2) * 9;
      if (u.boom) u.boom.rotation.x = Math.min(1.5, a);        // the boom folds back against the legs as it goes
      if (!splashed && a > 1.25) {
        splashed = true;
        crane.localToWorld(tip.set(0, 44, -30));
        const water = ctx.tide();
        for (let i = 0; i < 420; i++) {
          const at = tip.clone().add(new THREE.Vector3(rand(-14, 14), 0, rand(-14, 14))).setY(water + 0.5);
          smoke.spawn(at, new THREE.Vector3(rand(-6, 6), rand(8, 26), rand(-6, 6)), rand(1.5, 3.5), rand(3, 6), rand(8, 14),
            [0.92, 0.95, 0.98, 0.85], [0.85, 0.9, 0.95, 0], 0.4, -9.8, water);
        }
        on.shake = Math.max(on.shake, 1.2);
        on.shakeAmp = Math.max(on.shakeAmp, 0.6);
      }
    };
  }

  function tilt(crane, rz, rx = 0) {
    const was = [crane.rotation.order, crane.rotation.x, crane.rotation.z, crane.position.y];
    on.restore.push(() => { [crane.rotation.order, crane.rotation.x, crane.rotation.z, crane.position.y] = was; crane.userData.fallen = false; });
    crane.rotation.order = 'YXZ';
    crane.rotation.z = rz;
    crane.rotation.x = rx;
    crane.position.y -= 1.2;
    crane.userData.fallen = true;
  }

  // Blacken a thing (a crane hit by a blast or a fire): its materials swapped for burnt ones.
  const BURNT = new THREE.MeshStandardMaterial({ color: 0x2b2522, roughness: 1 });
  function burn(object) {
    const swaps = [];
    object.traverse((m) => { if (m.isMesh && !m.isInstancedMesh) { swaps.push([m, m.material]); m.material = BURNT; } });
    on.restore.push(() => { for (const [m, mat] of swaps) m.material = mat; });
  }

  // A ship of the model's own, for the events that bring one (a striker, a wreck).
  function aShip(type, loa, beam) {
    const s = ctx.ship(type, loa, beam, 12, Math.random, 'LR');
    s.traverse((m) => { if (m.isMesh) m.castShadow = true; });
    root.add(s);
    return s;
  }
  // The ship the live port shows nearest a point (alongside or about), or null.
  function shipNear(p, within) {
    let best = null;
    let d = within;
    scene.traverse((o) => {
      if (!o.userData || !o.userData.bridge || !o.visible || o.parent !== scene) return;
      const e = Math.hypot(o.position.x - p.x, o.position.z - p.z);
      if (e < d) { d = e; best = o; }
    });
    return best;
  }

  // People, many at once (gathered at the gate, soldiers at a checkpoint).
  function crowd(spots, colour, placards = false) {
    const n = spots.length;
    const body = new THREE.InstancedMesh(new THREE.CylinderGeometry(0.3, 0.26, 1.4, 6), new THREE.MeshStandardMaterial({ color: colour, roughness: 0.8 }), n);
    const head = new THREE.InstancedMesh(new THREE.SphereGeometry(0.24, 8, 6), new THREE.MeshStandardMaterial({ color: 0x6d4c41, roughness: 0.6 }), n);
    const m = new THREE.Matrix4();
    spots.forEach(([x, y, z], i) => {
      body.setMatrixAt(i, m.makeTranslation(x, y + 0.7, z));
      head.setMatrixAt(i, m.makeTranslation(x, y + 1.6, z));
    });
    root.add(body, head);
    if (placards) {
      const k = Math.ceil(n / 3);
      const boards = new THREE.InstancedMesh(new THREE.BoxGeometry(1.3, 0.9, 0.06), new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.7 }), k);
      const sticks = new THREE.InstancedMesh(new THREE.BoxGeometry(0.06, 1.4, 0.06), new THREE.MeshStandardMaterial({ color: 0x8d6e63 }), k);
      const colours = [0xffffff, 0xffeb3b, 0xef5350];
      const c = new THREE.Color();
      for (let i = 0; i < k; i++) {
        const [x, y, z] = spots[i * 3];
        const a = rand(-0.4, 0.4);
        boards.setMatrixAt(i, m.compose(tmp.set(x + 0.3, y + 2.7, z), new THREE.Quaternion().setFromAxisAngle(UP, a), new THREE.Vector3(1, 1, 1)));
        boards.setColorAt(i, c.setHex(colours[i % 3]));
        sticks.setMatrixAt(i, m.makeTranslation(x + 0.3, y + 1.9, z));
      }
      root.add(boards, sticks);
      return { body, head, boards };
    }
    return { body, head };
  }

  // An armoured vehicle: an eight-wheeled hull in olive drab with a turret and gun.
  const OLIVE = new THREE.MeshStandardMaterial({ color: 0x7a7d3c, roughness: 0.8 });   // light enough to read on dark paving
  const TYRE = new THREE.MeshStandardMaterial({ color: 0x151515, roughness: 0.9 });
  function armour(x, y, z, heading) {
    const g = new THREE.Group();
    g.add(ctx.box(7.5, 2.0, 2.9, OLIVE, 0, 1.9, 0));
    g.add(ctx.box(2.2, 0.9, 2.9, OLIVE, 3.4, 1.4, 0));
    g.add(ctx.box(2.4, 0.9, 2.0, OLIVE, -0.6, 3.3, 0));
    g.add(ctx.box(3.2, 0.25, 0.25, OLIVE, 1.8, 3.4, 0));
    for (const wx of [-2.7, -0.9, 0.9, 2.7]) for (const wz of [-1.4, 1.4]) {
      const w = new THREE.Mesh(new THREE.CylinderGeometry(0.6, 0.6, 0.5, 12), TYRE);
      w.rotation.x = Math.PI / 2;
      w.position.set(wx, 0.6, wz);
      g.add(w);
    }
    g.position.set(x, y, z);
    g.rotation.y = heading;
    root.add(g);
    return g;
  }

  // A small boat (a fire boat, the bomb-disposal team's RIB, a skimmer, a tug).
  function boat(x, z, heading, colour = 0xd84315, len = 14) {
    const g = new THREE.Group();
    g.add(ctx.box(len, 1.6, len * 0.32, new THREE.MeshStandardMaterial({ color: colour, roughness: 0.6 }), 0, 0.4, 0));
    g.add(ctx.box(len * 0.3, 2.2, len * 0.24, ctx.REAL.white, -len * 0.1, 2.2, 0));
    g.position.set(x, ctx.tide(), z);
    g.rotation.y = heading;
    root.add(g);
    return g;
  }

  // A jet of water from a fire boat or a fire engine, arcing onto the fire.
  function hose(from, to) {
    let acc = 0;
    return (dt) => {
      const a = typeof from === 'function' ? from() : from;
      const b = typeof to === 'function' ? to() : to;
      if (!a || !b) return;
      acc += dt * 60;
      const d = b.clone().sub(a);
      const T = 2.2;
      const v = new THREE.Vector3(d.x / T, (d.y + 0.5 * 9.8 * T * T) / T, d.z / T);
      for (; acc > 1; acc--) smoke.spawn(a, v.clone().add(new THREE.Vector3(rand(-0.6, 0.6), rand(-0.6, 0.6), rand(-0.6, 0.6))), T, 0.8, 3, [0.9, 0.95, 1, 0.7], [0.9, 0.95, 1, 0.1], 0, -9.8);
    };
  }

  // Flashing lights on the emergency vehicles and the cordon.
  const BLUE = new THREE.MeshStandardMaterial({ color: 0x1e5bff, emissive: 0x1e5bff, emissiveIntensity: 0 });
  const RED_LAMP = new THREE.MeshStandardMaterial({ color: 0xff3b1e, emissive: 0xff3b1e, emissiveIntensity: 0 });
  const AMBER = new THREE.MeshStandardMaterial({ color: 0xffa000, emissive: 0xffa000, emissiveIntensity: 0 });
  function emergency(x, y, z, heading, kind) {
    const g = new THREE.Group();
    const paint = new THREE.MeshStandardMaterial({ color: kind === 'fire' ? 0xc62828 : 0xf5f5f5, roughness: 0.4 });
    if (kind === 'fire') {
      g.add(ctx.box(9, 3, 2.5, paint, 0, 1.9, 0));
      g.add(ctx.box(6, 0.4, 0.6, ctx.REAL.steel, -1, 3.6, 0));
    } else {
      g.add(ctx.box(4.6, 1.2, 1.9, paint, 0, 0.9, 0));
      g.add(ctx.box(2.4, 0.7, 1.7, ctx.REAL.glass, -0.2, 1.8, 0));
      g.add(ctx.box(4.6, 0.3, 1.92, new THREE.MeshStandardMaterial({ color: 0x1565c0 }), 0, 0.9, 0));
    }
    g.add(ctx.box(0.5, 0.3, 0.5, BLUE, kind === 'fire' ? 3.8 : -0.2, kind === 'fire' ? 3.6 : 2.3, -0.5));
    g.add(ctx.box(0.5, 0.3, 0.5, kind === 'fire' ? RED_LAMP : BLUE, kind === 'fire' ? 3.8 : -0.2, kind === 'fire' ? 3.6 : 2.3, 0.5));
    g.position.set(x, y, z);
    g.rotation.y = heading;
    root.add(g);
    return g;
  }

  // --- the cordon -------------------------------------------------------------------------------
  // Round the edge of the closed area (cells of 10 m): red and white water-filled barriers end to
  // end, AREA CLOSED signs on posts facing out at intervals, and amber beacons flashing on them.
  function cordon(cells, CELL, y) {
    const edges = [];
    for (const key of cells) {
      const [x, z] = key.split(',').map(Number);
      // [x0, z0, x1, z1, outward normal]
      if (!cells.has(`${x},${z - 1}`)) edges.push([x * CELL, z * CELL, (x + 1) * CELL, z * CELL, [0, -1]]);
      if (!cells.has(`${x},${z + 1}`)) edges.push([x * CELL, (z + 1) * CELL, (x + 1) * CELL, (z + 1) * CELL, [0, 1]]);
      if (!cells.has(`${x - 1},${z}`)) edges.push([x * CELL, z * CELL, x * CELL, (z + 1) * CELL, [-1, 0]]);
      if (!cells.has(`${x + 1},${z}`)) edges.push([(x + 1) * CELL, z * CELL, (x + 1) * CELL, (z + 1) * CELL, [1, 0]]);
    }
    if (!edges.length) return;
    const PER = 5;
    const blocks = new THREE.InstancedMesh(new THREE.BoxGeometry(1.9, 0.9, 0.55), new THREE.MeshStandardMaterial({ roughness: 0.6 }), edges.length * PER);
    const m = new THREE.Matrix4();
    const q = new THREE.Quaternion();
    const c = new THREE.Color();
    let i = 0;
    for (const [x0, z0, x1, z1] of edges) {
      const a = Math.atan2(z1 - z0, x1 - x0);
      q.setFromAxisAngle(UP, -a);
      for (let k = 0; k < PER; k++) {
        const u = (k + 0.5) / PER;
        blocks.setMatrixAt(i, m.compose(tmp.set(x0 + (x1 - x0) * u, y + 0.45, z0 + (z1 - z0) * u), q, new THREE.Vector3(1, 1, 1)));
        blocks.setColorAt(i, c.setHex(k % 2 ? 0xf5f5f5 : 0xd32f2f));
        i++;
      }
    }
    blocks.castShadow = true;
    root.add(blocks);
    // Signs: no more than about 60 round the edge, evenly spaced.
    const step = Math.max(1, Math.ceil(edges.length / 60));
    const chosen = edges.filter((_, k) => k % step === 0);
    const posts = new THREE.InstancedMesh(new THREE.CylinderGeometry(0.1, 0.1, 4.4, 6), ctx.REAL.steel, chosen.length);
    const boards = new THREE.InstancedMesh(new THREE.PlaneGeometry(4, 2), new THREE.MeshBasicMaterial({ map: signTexture('AREA\nCLOSED'), side: THREE.DoubleSide }), chosen.length);
    const lamps = new THREE.InstancedMesh(new THREE.SphereGeometry(0.28, 10, 8), AMBER, chosen.length);
    chosen.forEach(([x0, z0, x1, z1, n], k) => {
      const x = (x0 + x1) / 2 + n[0] * 1.2;
      const z = (z0 + z1) / 2 + n[1] * 1.2;
      posts.setMatrixAt(k, m.makeTranslation(x, y + 2.2, z));
      boards.setMatrixAt(k, m.compose(tmp.set(x, y + 3.2, z), q.setFromAxisAngle(UP, Math.atan2(n[0], n[1])), new THREE.Vector3(1, 1, 1)));
      lamps.setMatrixAt(k, m.makeTranslation(x, y + 4.6, z));
    });
    root.add(posts, boards, lamps);
  }

  // The flood: a sheet of sea over the apron and the yard, rising to `depth` over `secs`.
  const FLOOD = new THREE.MeshStandardMaterial({ color: 0x3a5a66, roughness: 0.15, metalness: 0.3, transparent: true, opacity: 0.78, depthWrite: false });
  function flood(depth, secs, delay = 0) {
    const v = [];
    for (const q of ctx.apron()) {
      const [a, b, c, d] = q;
      for (const [x, z] of [a, b, c, a, c, d]) v.push(x, 0, z);
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(v, 3));
    geo.computeVertexNormals();
    const sheet = new THREE.Mesh(geo, FLOOD);
    FLOOD.side = THREE.DoubleSide;
    sheet.renderOrder = 1;
    sheet.visible = false;
    root.add(sheet);
    const top = ctx.frame.top;
    return (dt, age) => {
      const u = smooth((age - delay) / secs);
      sheet.visible = u > 0.01;
      sheet.position.y = top + 0.05 + depth * u;
    };
  }

  // Spray bursting over the quay wall where the waves hit.
  function spray(points, rate) {
    let acc = 0;
    return (dt) => {
      acc += dt * rate;
      for (; acc > 1; acc--) {
        const p = points[Math.floor(Math.random() * points.length)];
        for (let k = 0; k < 14; k++) {
          smoke.spawn(tmp.set(p.x + rand(-6, 6), ctx.tide() + 1, p.z + rand(-6, 6)), new THREE.Vector3(rand(-2, 2) + p.in.x * 6, rand(10, 20), rand(-2, 2) + p.in.z * 6),
            rand(1.6, 2.6), 2.5, 9, [0.93, 0.96, 1, 0.8], [0.9, 0.93, 0.97, 0], 0.3, -9.8, ctx.tide());
        }
      }
    };
  }

  // Lightning: a jagged bolt from the cloud to the crane, flickering, with the flash.
  function lightning(target) {
    const pts = [];
    let p = target.clone().add(new THREE.Vector3(rand(-60, 60), 420, rand(-60, 60)));
    for (let k = 0; k < 18; k++) {
      const q = p.clone().lerp(target, 1 / (18 - k)).add(new THREE.Vector3(rand(-8, 8), 0, rand(-8, 8)));
      if (k === 17) q.copy(target);
      pts.push(p, q);
      p = q;
    }
    const bolt = new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineBasicMaterial({ color: 0xe8f0ff }));
    root.add(bolt);
    let t = 0;
    return (dt) => {
      t += dt;
      const lit = (t < 0.12) || (t > 0.2 && t < 0.3) || (t > 0.45 && t < 0.52) || (t > 3.0 && t < 3.08);
      bolt.visible = lit;
      flash.position.copy(target).setY(target.y + 30);
      flash.intensity = lit ? 120000 : flash.intensity * Math.max(0, 1 - dt * 8);
      if (t < 0.6 && Math.random() < 0.5) {
        for (let k = 0; k < 6; k++) glow.spawn(target, new THREE.Vector3(rand(-8, 8), rand(-2, 8), rand(-8, 8)), rand(0.3, 0.8), 1.5, 0.3, [0.8, 0.9, 1, 1], [0.6, 0.7, 1, 0], 1, -9.8);
      }
    };
  }

  // A missile from high over the sea onto the point, its exhaust and smoke trail behind it.
  function missile(target, then) {
    const g = new THREE.Group();
    const body = new THREE.Mesh(new THREE.CylinderGeometry(0.6, 0.6, 7, 10), new THREE.MeshStandardMaterial({ color: 0x9e9e9e, metalness: 0.6, roughness: 0.4 }));
    const nose = new THREE.Mesh(new THREE.ConeGeometry(0.6, 2, 10), body.material);
    nose.position.y = 4.5;
    g.add(body, nose);
    root.add(g);
    // It comes in from beyond the target as the camera sees it, so that it is in the picture as it
    // dives, whichever way the camera looks.
    const away = new THREE.Vector3(target.x - camera.position.x, 0, target.z - camera.position.z);
    if (away.lengthSq() < 1) away.set(1, 0, 0);
    away.normalize();
    const side = new THREE.Vector3(-away.z, 0, away.x);
    const from = target.clone().addScaledVector(away, 1600).addScaledVector(side, 300).add(new THREE.Vector3(0, 700, 0));
    const mid = target.clone().lerp(from, 0.45).add(new THREE.Vector3(0, 160, 0));
    const curve = new THREE.QuadraticBezierCurve3(from, mid, target);
    const T = 4.0;
    let t = 0;
    let done = false;
    const was = new THREE.Vector3();
    return (dt) => {
      if (done) return;
      t += dt;
      const u = Math.min(1, t / T);
      const p = curve.getPoint(u * u * 0.4 + u * 0.6);
      was.copy(g.position);
      g.position.copy(p);
      const dir = p.clone().sub(was);
      if (dir.lengthSq() > 1e-6) g.quaternion.setFromUnitVectors(UP, dir.normalize());
      for (let k = 0; k < 6; k++) {
        smoke.spawn(p, new THREE.Vector3(rand(-1, 1), rand(-1, 1), rand(-1, 1)), rand(3, 6), 4, 16, [0.9, 0.9, 0.9, 0.7], [0.8, 0.8, 0.8, 0], 0.4, 0.3);
        glow.spawn(p, new THREE.Vector3(rand(-2, 2), rand(-2, 2), rand(-2, 2)), 0.4, 10, 2, [1, 0.9, 0.6, 1], [1, 0.4, 0.1, 0], 1, 0);
      }
      if (u >= 1) { done = true; g.visible = false; then(); }
    };
  }

  // A marker on the water or the deck: a ring and a post with a sign (scour, corrosion found, UXO).
  function marker(at, words, colour, r = 30) {
    const ring = new THREE.Mesh(new THREE.TorusGeometry(r, 0.6, 8, 48), new THREE.MeshStandardMaterial({ color: colour, emissive: colour, emissiveIntensity: 0.4 }));
    ring.rotation.x = Math.PI / 2;
    ring.position.copy(at);
    root.add(ring);
    const post = new THREE.Mesh(new THREE.CylinderGeometry(0.15, 0.15, 6, 6), ctx.REAL.steel);
    post.position.copy(at).setY(at.y + 3);
    const sign = new THREE.Mesh(new THREE.PlaneGeometry(6, 3), new THREE.MeshBasicMaterial({ map: signTexture(words), side: THREE.DoubleSide }));
    sign.position.copy(at).setY(at.y + 7);
    sign.lookAt(camera.position.x, at.y + 7, camera.position.z);
    root.add(post, sign);
  }

  // --- what each event does -------------------------------------------------------------------
  // info: { centre (on the deck), deck, cells, CELL, whole, down: the cranes it stops, closed:
  //         the berths it closes, fresh: whether it is striking now (else long since) }
  function stage(key, info) {
    const { centre, deck } = info;
    const T = on.tickers;
    const sea = ctx.seaAt(centre.x, centre.z);
    const seaward = (d) => new THREE.Vector3(centre.x + sea.sea[0] * d, deck, centre.z + sea.sea[1] * d);
    const inland = (d, s = 0) => new THREE.Vector3(centre.x - sea.sea[0] * d + sea.along[0] * s, deck, centre.z - sea.sea[1] * d + sea.along[1] * s);
    const quayHeading = Math.atan2(-sea.along[1], sea.along[0]);
    const near = info.down.filter((c) => c.userData.trolley).length ? info.down.filter((c) => c.userData.trolley)
      .sort((a, b) => Math.hypot(a.position.x - centre.x, a.position.z - centre.z) - Math.hypot(b.position.x - centre.x, b.position.z - centre.z)) : cranesNear(centre, 150);
    const trucksAt = (n, kind) => {
      for (let k = 0; k < n; k++) emergency(...inland(70 + k * 6, -30 + k * 14).toArray(), quayHeading + (k % 2 ? 0.3 : -0.2), kind);
    };
    const once = (fn) => { if (info.fresh) fn(); };
    switch (key) {
      case 'terrorist_attack': {
        const at = inland(25);
        if (info.fresh) T.push(explosion(at, 1.4));
        scorch(at, 16);
        T.push(fire(at, 1.8, { grow: 4 }), fire(inland(32, 14), 1.1, { grow: 8 }), fire(inland(18, -12), 0.9, { grow: 6 }));
        once(() => { on.shake = 1.0; on.shakeAmp = 1.2; });
        if (near[0]) burn(near[0]);
        trucksAt(2, 'police');
        trucksAt(1, 'fire');
        break;
      }
      case 'war_direct': {
        const at = inland(20);
        const hit = () => {
          T.push(explosion(at, 2.6));
          on.shake = 2.0; on.shakeAmp = 2.2;
          if (near[0]) T.push(topple(near[0], 0.6));
          if (near[1]) tilt(near[1], 0.12, -0.08);
        };
        // The crater, the burnt cranes and the fires come with the impact, not before it.
        const after = () => {
          scorch(at, 26, true);
          for (const c of near.slice(0, 2)) burn(c);
          T.push(fire(at, 1.6, { grow: 5 }), fire(inland(45, 20), 1.0, { grow: 10 }), fire(inland(8, -30), 0.8));
        };
        if (info.fresh) T.push(missile(at, () => { hit(); after(); }));
        else { if (near[0]) T.push(topple(near[0], 0, -1.62)); if (near[1]) tilt(near[1], 0.12, -0.08); after(); }
        break;
      }
      case 'sabotage': {
        const at = inland(10, 8);
        if (info.fresh) { T.push(explosion(at, 0.6)); on.shake = 0.6; on.shakeAmp = 0.5; }
        scorch(at, 8);
        T.push(fire(at, 0.5));
        trucksAt(1, 'police');
        break;
      }
      case 'quake_moderate':
      case 'quake_major':
      case 'liquefaction': {
        const big = key === 'quake_major';
        once(() => { on.shake = big ? 12 : key === 'liquefaction' ? 6 : 8; on.shakeAmp = big ? 2.4 : key === 'liquefaction' ? 1.0 : 1.4; on.sway = true; });
        cracks(centre, key === 'liquefaction' ? 80 : 160, big ? 26 : key === 'liquefaction' ? 14 : 8, deck);
        if (big || key === 'liquefaction') {
          // Settled ground: cranes in the area leaning on their sunk legs.
          const lean = (big ? cranesNear(centre, 400) : near).slice(0, big ? 4 : 3);
          lean.forEach((c, k) => tilt(c, (k % 2 ? -1 : 1) * rand(0.05, 0.1), rand(-0.05, 0.03)));
        }
        if (key === 'liquefaction') {
          // Sand boils: grey-brown sand and water pushed up through the paving.
          const im = new THREE.InstancedMesh(new THREE.CircleGeometry(1, 16), new THREE.MeshBasicMaterial({ color: 0x7d6e58, transparent: true, opacity: 0.85, depthWrite: false }), 30);
          const m = new THREE.Matrix4();
          for (let i = 0; i < 30; i++) {
            const r = rand(1.5, 5);
            im.setMatrixAt(i, m.compose(tmp.set(centre.x + rand(-90, 90), deck + 0.13, centre.z + rand(-60, 60)), new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), -Math.PI / 2), new THREE.Vector3(r, r, 1)));
          }
          root.add(im);
        }
        if (big) T.push(fire(inland(140, 60), 0.6), fire(inland(120, -220), 0.5));
        break;
      }
      case 'crane_collapse': {
        const c = near[0] || cranesNear(centre)[0];
        if (c) T.push(topple(c, info.fresh ? 1.5 : 0));
        trucksAt(2, 'police');
        break;
      }
      case 'ship_strike':
      case 'ship_collision': {
        const victim = key === 'ship_collision' ? (shipNear(centre, 220) || null) : null;
        const s = aShip('container ship', 240, 34);
        // The striker comes in from the sea at an angle, far too fast, and stops in the wall (or the
        // other ship's side).
        const stopAt = victim ? new THREE.Vector3(victim.position.x + sea.sea[0] * (victim.userData.beam / 2 + 118), 0, victim.position.z + sea.sea[1] * (victim.userData.beam / 2 + 118))
          : seaward(122);
        const heading = Math.atan2(sea.sea[1], -sea.sea[0]) + (victim ? 0 : 0.35);        // bow towards the land
        const dir = new THREE.Vector3(-sea.sea[0], 0, -sea.sea[1]).applyAxisAngle(UP, victim ? 0 : 0.35);
        const start = stopAt.clone().addScaledVector(dir, -700);
        s.rotation.order = 'YXZ';
        s.rotation.y = heading;
        let t = info.fresh ? 0 : 99;
        let hit = false;
        T.push((dt) => {
          t += dt;
          const u = clamp(t / 9, 0, 1);
          s.position.copy(start).lerp(stopAt, 1 - (1 - u) ** 1.2);
          s.position.y = ctx.tide();
          if (u >= 1) {
            s.rotation.z = Math.min(0.06, (t - 9) * 0.02);
            if (!hit) {
              hit = true;
              on.shake = 1.5; on.shakeAmp = 1.2;
              const bow = stopAt.clone().addScaledVector(dir, 120).setY(deck);
              for (let i = 0; i < 160; i++) smoke.spawn(bow, new THREE.Vector3(rand(-8, 8), rand(2, 12), rand(-8, 8)), rand(2, 4), 3, 12, [0.55, 0.52, 0.48, 0.7], [0.6, 0.58, 0.55, 0], 0.8, -4);
              if (victim) on.restore.push(() => { victim.rotation.z = 0; });
            }
          }
          if (victim) victim.rotation.z = hit ? -0.05 : 0;
        });
        if (!victim) {
          // Broken fenders and rubble at the wall.
          const bits = new THREE.InstancedMesh(new THREE.BoxGeometry(2, 1.2, 1.5), new THREE.MeshStandardMaterial({ color: 0x1d1d1f }), 10);
          const m = new THREE.Matrix4();
          for (let i = 0; i < 10; i++) bits.setMatrixAt(i, m.compose(tmp.set(centre.x + sea.sea[0] * rand(4, 20) + sea.along[0] * rand(-25, 25), ctx.tide() + 0.2, centre.z + sea.sea[1] * rand(4, 20) + sea.along[1] * rand(-25, 25)), new THREE.Quaternion().setFromEuler(new THREE.Euler(rand(0, 1), rand(0, 3), 0)), new THREE.Vector3(1, 1, 1)));
          root.add(bits);
          cracks(centre, 25, 5, deck);
        }
        break;
      }
      case 'mooring_breakaway': {
        const s = shipNear(centre, 400);
        if (s) {
          // Her lines parted, she drifts off the berth and swings, the tugs too late for now.
          let t = info.fresh ? 0 : 300;
          const off = new THREE.Vector3();
          const turn = { y: 0 };
          const set = new THREE.Vector3(NaN, 0, 0);
          let setRot = NaN;
          const undo = () => {
            // The live port puts her back at her berth each frame; the still view does not.
            if (s.position.distanceToSquared(set) < 1e-8) s.position.sub(off);
            if (Math.abs(s.rotation.y - setRot) < 1e-9) s.rotation.y -= turn.y;
          };
          on.restore.push(undo);
          T.push((dt) => {
            t += dt;
            undo();
            const d = Math.min(220, 0.004 * t * t + 0.4 * t);
            off.set(sea.sea[0] * d + sea.along[0] * d * 0.4, 0, sea.sea[1] * d + sea.along[1] * d * 0.4);
            turn.y = Math.min(0.5, d / 400);
            s.position.add(off);
            s.rotation.y += turn.y;
            set.copy(s.position);
            setRot = s.rotation.y;
          });
        }
        break;
      }
      case 'channel_blocked': {
        // A ship aground across the channel, listing, with tugs standing by.
        let at = null;
        for (const d of [450, 600, 800, 350, 1000]) {
          const p = seaward(d);
          if (!ctx.atSea || ctx.atSea(p.x, p.z, 160)) { at = p; break; }
        }
        if (at) {
          const s = aShip('container ship', 260, 36);
          s.position.set(at.x, ctx.tide() - 3, at.z);
          s.rotation.order = 'YXZ';
          s.rotation.y = Math.atan2(-sea.along[1], sea.along[0]) + 1.3;
          s.rotation.x = 0.16;
          T.push(() => { s.position.y = ctx.tide() - 3; });
          boat(at.x + sea.along[0] * 170, at.z + sea.along[1] * 170, quayHeading, 0xc62828, 26);
          boat(at.x - sea.along[0] * 160 + sea.sea[0] * 40, at.z - sea.along[1] * 160 + sea.sea[1] * 40, quayHeading + 2, 0xc62828, 26);
        }
        break;
      }
      case 'fire_apron': {
        const at = inland(40);
        T.push(fire(at, 1.4, { grow: 10 }), fire(inland(46, 10), 0.8, { grow: 20 }));
        scorch(at, 10);
        trucksAt(2, 'fire');
        T.push(hose(inland(68, -30).setY(deck + 4), at.clone().setY(deck + 3)));
        break;
      }
      case 'fire_vessel':
      case 'dg_explosion': {
        // The ship alongside in the closed area; when the live port has none there, a burning ship of
        // the event's own is moored at the closed berth, so the fire is where the cordon is.
        let s = shipNear(centre, 150);
        if (!s) {
          s = aShip('container ship', 200, 32);
          const d = (ctx.inlandOf ? ctx.inlandOf(centre.x, centre.z) : 10) + 16 + 3;
          s.position.set(centre.x + sea.sea[0] * d, ctx.tide(), centre.z + sea.sea[1] * d);
          // Her side towards the sea is her local -z, where the fire boats lie.
          const seawardSide = sea.along[1] * sea.sea[0] - sea.along[0] * sea.sea[1] > 0;
          s.rotation.y = quayHeading + (seawardSide ? 0 : Math.PI);
          T.push(() => { s.position.y = ctx.tide(); });
        }
        const onShip = (dx) => () => (s && s.visible ? s.localToWorld(new THREE.Vector3(dx, s.userData.deck + 14, 0)) : null);   // on top of her deck cargo
        if (key === 'dg_explosion') {
          const at = s ? onShip(-10)() : inland(30);
          if (info.fresh) { T.push(explosion(at, 2.4)); on.shake = 1.8; on.shakeAmp = 1.8; }
          for (const c of near.slice(0, 2)) burn(c);
          if (near[0]) tilt(near[0], 0.1, 0.06);
          T.push(fire(s ? onShip(-10) : at, 1.6, { grow: 2 }), fire(inland(30), 0.9), fire(s ? onShip(20) : inland(40, 20), 1.2, { toxic: true }));
        } else {
          const p = s ? [onShip(-0.1 * s.userData.loa), onShip(0.12 * s.userData.loa)] : [() => seaward(20)];
          T.push(...p.map((f, k) => fire(f, k ? 1.3 : 1.9, { grow: 5 })));
          // Fire boats off her seaward side, their monitors on the fire.
          if (s) {
            const fb = (k) => () => s.localToWorld(new THREE.Vector3((k - 0.5) * 60, 0, -(s.userData.beam / 2 + 40)));
            const boats = [0, 1].map((k) => { const pos = fb(k)(); return boat(pos.x, pos.z, s.rotation.y, 0xc62828, 22); });
            T.push(() => boats.forEach((b, k) => { const pos = fb(k)(); b.position.set(pos.x, ctx.tide(), pos.z); }));
            boats.forEach((b, k) => T.push(hose(() => b.position.clone().setY(ctx.tide() + 6), p[k % p.length])));
          }
        }
        trucksAt(2, 'fire');
        break;
      }
      case 'hazmat_leak': {
        const at = inland(60, 10);
        T.push(fire(at, 2.2, { toxic: true }));
        // The leaking box, and a pool of what came out of it.
        const box = ctx.box(12, 2.6, 2.4, new THREE.MeshStandardMaterial({ color: 0xf9a825 }), at.x, deck + 1.3, at.z);
        box.rotation.y = quayHeading;
        root.add(box);
        const pool = new THREE.Mesh(new THREE.CircleGeometry(9, 24), new THREE.MeshBasicMaterial({ color: 0x9ccc65, transparent: true, opacity: 0.7, depthWrite: false }));
        pool.rotation.x = -Math.PI / 2;
        pool.position.copy(at).setY(deck + 0.13);
        root.add(pool);
        trucksAt(2, 'fire');
        break;
      }
      case 'oil_spill': {
        const slick = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), new THREE.MeshBasicMaterial({ map: slickTexture(), transparent: true, depthWrite: false }));
        slick.rotation.x = -Math.PI / 2;
        slick.renderOrder = 2;
        const at = seaward((ctx.inlandOf ? Math.max(0, ctx.inlandOf(centre.x, centre.z)) : 10) + 90);   // in the basin off the closed berths
        root.add(slick);
        const boom = new THREE.Mesh(new THREE.TorusGeometry(1, 0.012, 6, 64), new THREE.MeshStandardMaterial({ color: 0xff8f00 }));
        boom.rotation.x = Math.PI / 2;
        root.add(boom);
        boat(at.x + sea.along[0] * 200, at.z + sea.along[1] * 200, quayHeading, 0x2e7d32, 18);
        let t = info.fresh ? 0 : 400;
        T.push((dt) => {
          t += dt;
          const r = 60 + Math.min(420, t * 1.5);
          slick.scale.set(r * 2.2, r * 1.6, 1);
          slick.position.set(at.x, ctx.tide() + 0.08, at.z);
          slick.rotation.z = quayHeading;
          boom.scale.set(r * 1.25, r * 1.25, r * 1.25);
          boom.position.set(at.x, ctx.tide() + 0.2, at.z);
        });
        break;
      }
      case 'great_storm':
      case 'storm_surge':
      case 'tsunami':
      case 'flood_rain': {
        const pts = [];
        for (const q of ctx.apron()) {
          const [a, b] = q;
          for (let u = 0; u <= 1; u += 0.04) {
            const x = a[0] + (b[0] - a[0]) * u;
            const z = a[1] + (b[1] - a[1]) * u;
            const s2 = ctx.seaAt(x, z);
            pts.push({ x: x + s2.sea[0] * 3, z: z + s2.sea[1] * 3, in: new THREE.Vector3(-s2.sea[0], 0, -s2.sea[1]) });
          }
        }
        if (key === 'tsunami') {
          // The wave: a long wall of water coming in from the sea, breaking on the quay, then the sea
          // pouring over the apron and the yard.
          const wall = new THREE.Mesh(new THREE.BoxGeometry(5000, 9, 40), new THREE.MeshStandardMaterial({ color: 0x2f5866, roughness: 0.3, transparent: true, opacity: 0.92 }));
          const crest = new THREE.Mesh(new THREE.BoxGeometry(5000, 1.6, 14), new THREE.MeshStandardMaterial({ color: 0xe8f1f4, roughness: 0.6 }));
          const g = new THREE.Group();
          g.add(wall, crest);
          crest.position.set(0, 5, -8);
          const f = ctx.frame;
          root.add(g);
          let t = info.fresh ? 0 : 99;
          const burst = spray(pts, 600);
          T.push((dt) => {
            t += dt;
            const u = clamp(t / 14, 0, 1);
            g.visible = u < 1;
            g.position.set((f.minX + f.maxX) / 2, ctx.tide() + 3, f.fenderFace - 900 * (1 - u));
            if (u > 0.93 && u < 1) burst(dt);
          });
          T.push(flood(2.2, 6, info.fresh ? 13 : 0));
          if (info.fresh) T.push((dt, age) => { if (age > 13 && age < 13.2) { on.shake = 3; on.shakeAmp = 0.8; } });
        } else {
          if (key !== 'flood_rain') T.push(spray(pts, key === 'great_storm' ? 40 : 25));
          T.push(flood(key === 'storm_surge' ? 0.8 : key === 'flood_rain' ? 0.35 : 0.45, info.fresh ? 20 : 0.01));
          on.rain = key === 'flood_rain' ? 40 : 0;
        }
        break;
      }
      case 'grid_failure': {
        // The substation by the gate gone: sparking and smoking.
        const g = ctx.gate();
        const sub = ctx.box(12, 6, 8, ctx.REAL.shed, g.x + 30, deck + 3, g.z);
        root.add(sub);
        const at = new THREE.Vector3(g.x + 30, deck + 6, g.z);
        T.push(fire(at, 0.3), (dt) => {
          if (Math.random() < dt * 2) for (let k = 0; k < 30; k++) glow.spawn(at, new THREE.Vector3(rand(-8, 8), rand(2, 10), rand(-8, 8)), rand(0.3, 0.7), 1, 0.2, [1, 1, 0.8, 1], [1, 0.6, 0.2, 0], 1, -9.8);
        });
        on.text = 'GRID FAILURE · no supply to the terminal: electric cranes stopped, yard dark at night';
        break;
      }
      case 'cyber':
        on.text = 'CYBER ATTACK · terminal operating system locked by ransomware · cranes, gates and planning stopped';
        break;
      case 'labour_strike': {
        const g = ctx.gate();
        const spots = [];
        for (let i = 0; i < 140; i++) spots.push([g.x + rand(-28, 28), deck, g.z + rand(-10, 10)]);
        crowd(spots, 0x37474f, true);
        on.text = 'STRIKE · dockers and drivers out: no machine is being worked';
        break;
      }
      case 'forced_occupation': {
        const g = ctx.gate();
        armour(g.x - 14, deck, g.z, quayHeading);
        armour(g.x + 14, deck, g.z + 4, quayHeading + 0.2);
        const soldiers = [];
        for (let i = 0; i < 40; i++) soldiers.push([g.x + rand(-30, 30), deck, g.z + rand(-14, 14)]);
        // On the quay, by the cranes: vehicles and soldiers at points along the apron.
        // They stand on the pale strip at the quay's edge, in front of the cranes, where they show.
        for (let k = -3; k <= 3; k++) {
          const p = inland(12, k * 70);
          armour(p.x, deck, p.z, quayHeading + (k % 2) * 0.4);
          const q = inland(5, k * 70 + 14);
          for (let i = 0; i < 14; i++) soldiers.push([q.x + rand(-6, 6), deck, q.z + rand(-3, 3)]);
        }
        crowd(soldiers, 0x6b6e35);
        on.text = 'PORT OCCUPIED · armed forces at the gate and on the quay; all work stopped';
        break;
      }
      case 'lightning': {
        const c = near[0] || cranesNear(centre)[0];
        if (c) {
          const top = c.localToWorld(new THREE.Vector3(0, 62, 28));
          if (info.fresh) T.push(lightning(top));
          T.push(fire(c.localToWorld(new THREE.Vector3(0, 40, 34)), 0.3));
          burn(c);
        }
        break;
      }
      case 'uxo': {
        // A wartime bomb found by the divers on the bed by the wall: buoys round it, the
        // bomb-disposal boat over it, the quay above evacuated (the cordon).
        const at = seaward(40);
        const n = 16;
        const buoys = new THREE.InstancedMesh(new THREE.SphereGeometry(1.2, 12, 8), new THREE.MeshStandardMaterial({ color: 0xff6f00, emissive: 0x552200 }), n);
        const m = new THREE.Matrix4();
        T.push(() => {
          for (let i = 0; i < n; i++) {
            const a = (i / n) * Math.PI * 2;
            buoys.setMatrixAt(i, m.makeTranslation(at.x + Math.cos(a) * 45, ctx.tide() + 0.3, at.z + Math.sin(a) * 45));
          }
          buoys.instanceMatrix.needsUpdate = true;
        });
        root.add(buoys);
        boat(at.x + 10, at.z - 6, quayHeading + 0.6, 0x263238, 10);
        const bomb = new THREE.Mesh(new THREE.CapsuleGeometry(0.4, 1.6, 4, 10), new THREE.MeshStandardMaterial({ color: 0x5d4037, roughness: 1 }));
        bomb.rotation.z = Math.PI / 2;
        bomb.position.set(at.x, -12, at.z);
        root.add(bomb);
        marker(at.clone().setY(ctx.tide() + 0.2), 'DANGER\nUXO', 0xff3d00, 12);
        trucksAt(2, 'police');
        break;
      }
      case 'extreme_heat':
        view.classList.add('mt-heat');
        on.restore.push(() => view.classList.remove('mt-heat'));
        break;
      case 'scour':
        marker(seaward(6).setY(ctx.tide() + 0.2), 'SCOUR\nAT TOE', 0xff6d00, 30);
        break;
      case 'alwc': {
        // Orange corrosion along the wall at low water, where the divers found it.
        const band = new THREE.Mesh(new THREE.PlaneGeometry(180, 2.5), new THREE.MeshBasicMaterial({ color: 0xd2691e, transparent: true, opacity: 0.85, side: THREE.DoubleSide }));
        band.position.set(centre.x + sea.sea[0] * 1.5, 0.3, centre.z + sea.sea[1] * 1.5);
        band.rotation.y = Math.atan2(sea.sea[0], sea.sea[1]);
        root.add(band);
        marker(seaward(12).setY(ctx.tide() + 0.2), 'CORROSION\nFOUND', 0xd2691e, 20);
        break;
      }
      default:
        break;
    }
  }

  function show(key, info) {
    clear();
    if (!key || !info) return;
    on = { key, age: 0, tickers: [], restore: [], shake: 0, shakeAmp: 0, sway: false, text: '', rain: 0 };
    stage(key, info);
    if (info.cells && info.cells.size) cordon(info.cells, info.CELL, info.deck);
    banner.hidden = !on.text;
    banner.textContent = on.text;
  }

  function clear() {
    if (on) for (const r of on.restore.reverse()) r();
    on = null;
    root.traverse((m) => { if (m.geometry && m !== root) m.geometry.dispose(); });
    root.clear();
    glow.clear();
    smoke.clear();
    flash.intensity = fireLight.intensity = 0;
    banner.hidden = true;
    banner.textContent = '';
  }

  // Each frame, in real seconds: the effects, the particles, the flashing lights, and the shaking.
  const offset = new THREE.Vector3();
  function tick(dt) {
    const h = renderer.domElement.height;
    glow.mat.uniforms.scale.value = smoke.mat.uniforms.scale.value = camera.projectionMatrix.elements[5] * h / 2;
    offset.set(0, 0, 0);
    if (on) {
      on.age += dt;
      for (const t of on.tickers) t(dt, on.age);
      fireLight.intensity *= 0.9;
      AMBER.emissiveIntensity = Math.floor(on.age * 2.5) % 2 ? 3 : 0.2;
      BLUE.emissiveIntensity = Math.floor(on.age * 4) % 2 ? 4 : 0;
      RED_LAMP.emissiveIntensity = Math.floor(on.age * 4) % 2 ? 0 : 4;
      if (on.shake > 0) {
        on.shake -= dt;
        const a = on.shakeAmp * Math.min(1, on.shake);
        offset.set(rand(-a, a), rand(-a, a) * 0.6, rand(-a, a));
        if (on.sway) for (const c of site.cranes) if (!c.userData.fallen) c.rotation.z = Math.sin(on.age * 9 + c.position.x) * 0.012 * a;
      } else if (on.sway) {
        on.sway = false;
        for (const c of site.cranes) if (!c.userData.fallen) c.rotation.z = 0;
      }
    }
    glow.update(dt, wind);
    smoke.update(dt, wind);
  }

  return {
    show, clear, tick,
    shake: () => offset,
    active: () => (on ? on.key : null),
    age: () => (on ? on.age : -1),
    rain: () => (on ? on.rain : 0),
  };
}
