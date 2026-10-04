// The live port: the next two days at the berth, played back through the 3D twin like a camera.
//
// marinetwin.js builds the scene (the Revit model, the terminal, the sky and the sea) and hands it
// over here. This plays the timeline from live.json on it: ships taking the pilot, berthing with
// their tugs and sailing; the cranes (or ramp gangs, unloaders) working, stopping in gusts,
// breaking down; tractors and people on the apron; rain, mist, waves and the tide; day and night
// from the real sun. It runs at 10× by default, faster to watch a whole day go by, and says when
// the berth is losing time and why.

const SPEEDS = [1, 10, 60, 600];
const CAMERAS = [['quay', 'Quay camera'], ['crane', 'Crane camera'], ['drone', 'Drone'], ['free', 'Free']];
const CYCLE = 110;            // seconds a crane takes for one move, ship to quay and back
const RATE = 3600 / CYCLE;    // moves an hour, per crane
const VISUAL_PACE = 20;       // above this, things move no faster on screen: a timelapse, not a blur

const esc = (text) => String(text).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const ease = (u) => (u < 0.5 ? 2 * u * u : 1 - (-2 * u + 2) ** 2 / 2);
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

export async function startLive(ctx) {
  const { THREE, view, scene, camera, controls, frame, site, rng, focus, radius, water, sky, sunLight, hemi, REAL } = ctx;
  const plan = await (await fetch(view.dataset.live, { credentials: 'same-origin' })).json();
  const startMs = Date.parse(plan.start);
  const hourOf = (iso) => (Date.parse(iso) - startMs) / 3600000;
  const total = plan.hours.length - 1;
  let simH = clamp(hourOf(plan.now), 0, total - 0.01);
  const realStart = Date.now() - simH * 3600000;       // the real instant of the timeline's start, for the sun
  let speed = 10;
  let playing = true;
  const centre = (frame.minX + frame.maxX) / 2;
  const kind = site.kind;

  // --- the timeline, read at any moment --------------------------------------------------
  function at(h) {
    const i = clamp(Math.floor(h), 0, total);
    const a = plan.hours[i];
    const b = plan.hours[Math.min(i + 1, total)];
    const f = clamp(h - i, 0, 1);
    const mix = (k) => a[k] + (b[k] - a[k]) * f;
    return { hour: a, wind: mix('wind'), gust: mix('gust'), hs: mix('hs'), tide: mix('tide'), rain: mix('rain'), visibility: mix('visibility') };
  }
  ctx.setTide((when) => at((when.getTime() - realStart) / 3600000).tide);
  const calls = plan.calls.map((c) => ({ ...c, from: hourOf(c.eta), to: hourOf(c.etd) }));
  const events = plan.events.map((e) => ({ ...e, h: hourOf(e.at) }));

  // --- ships and their tugs ----------------------------------------------------------------
  const APPROACH = 1.5;   // hours from the pilot to all fast
  const ANCHOR = 6;       // hours a ship is seen waiting off the port before that
  for (const c of calls) {
    c.mesh = ctx.ship(c.type, c.loa, c.beam, c.draught, rng);
    c.mesh.traverse((m) => { if (m.isMesh) m.castShadow = true; });
    c.mesh.visible = false;
    scene.add(c.mesh);
    const berth = new THREE.Vector3(centre, 0, frame.fenderFace - c.beam / 2 - 0.4);
    c.berth = berth;
    c.inbound = new THREE.CatmullRomCurve3([
      new THREE.Vector3(centre - 1700, 0, berth.z - 650), new THREE.Vector3(centre - 800, 0, berth.z - 300),
      new THREE.Vector3(centre - 220, 0, berth.z - 45), new THREE.Vector3(centre - 40, 0, berth.z - 6), berth.clone()]);
    c.outbound = new THREE.CatmullRomCurve3([
      berth.clone(), new THREE.Vector3(centre + 60, 0, berth.z - 10), new THREE.Vector3(centre + 300, 0, berth.z - 70),
      new THREE.Vector3(centre + 900, 0, berth.z - 330), new THREE.Vector3(centre + 1800, 0, berth.z - 650)]);
    c.anchorage = new THREE.Vector3(centre - 1900, 0, berth.z - 950 - (calls.indexOf(c) % 2) * 160);
  }
  const tugMat = new THREE.MeshStandardMaterial({ color: 0xc62828, roughness: 0.5 });
  const tugs = [0, 1].map(() => {
    const g = new THREE.Group();
    g.add(ctx.box(28, 4, 9, tugMat, 0, 1, 0));
    g.add(ctx.box(9, 5, 7, REAL.white, -2, 5, 0));
    g.visible = false;
    scene.add(g);
    return g;
  });

  // --- the other berths along the quay ------------------------------------------------------
  // Each has its own line of ships, one after another: in from the sea, alongside while its own
  // cranes work it (stopping in gusts like the rest), then out to sea, and a gap before the next.
  const SHIP_NAMES = ['Maersk Elba', 'CMA CGM Thalia', 'MSC Rania', 'ONE Harmony', 'Hapag Lisbon', 'Evergreen Lyra',
    'COSCO Pride', 'Zim Atlantic', 'Yang Ming Unity', 'HMM Oslo', 'Grande Abidjan', 'Arkas Lagos'];
  const shipType = kind === 'roro' ? 'ro-ro' : kind === 'bulk' ? 'bulk carrier' : kind === 'general_cargo' ? 'general cargo' : 'container ship';
  const others = (site.berths || []).filter((b) => !b.main).map((b, i) => {
    const loa = Math.min(b.length - 30, 180 + rng() * 170);
    if (loa < 120) return null;
    const beam = Math.round(loa * 0.14);
    const mesh = ctx.ship(shipType, loa, beam, 12, rng);
    mesh.traverse((m) => { if (m.isMesh) m.castShadow = true; });
    mesh.visible = false;
    scene.add(mesh);
    const leg = b.leg;
    const t = b.mid - leg.from;
    // `along` metres along the leg from its start, `out` metres out to sea from the fender line.
    const P = (along, out) => new THREE.Vector3(leg.a[0] + leg.dir[0] * along - leg.land[0] * out, 0, leg.a[1] + leg.dir[1] * along - leg.land[1] * out);
    const berth = P(t, beam / 2 + 2);
    const stay = 8 + rng() * 16;
    const gap = 1 + rng() * 7;
    return {
      b, mesh, berth, beam, loa, stay, name: SHIP_NAMES[i % SHIP_NAMES.length],
      period: stay + gap + 2 * APPROACH, offset: rng() * (stay + gap + 2 * APPROACH),
      rot: Math.atan2(-leg.dir[1], leg.dir[0]), alongside: false,
      inbound: new THREE.CatmullRomCurve3([P(t - 1500, 700), P(t - 700, 300), P(t - 200, beam / 2 + 45), P(t - 40, beam / 2 + 8), berth.clone()]),
      outbound: new THREE.CatmullRomCurve3([berth.clone(), P(t + 60, beam / 2 + 12), P(t + 300, beam / 2 + 80), P(t + 900, 330), P(t + 1700, 650)]),
    };
  }).filter(Boolean);
  const otherOf = new Map(others.map((o) => [o.b, o]));
  let busy = 0;          // berths with a ship alongside, the main one included
  function placeOthers(h, tide) {
    let alongside = 0;
    for (const o of others) {
      const ph = (((h + o.offset) % o.period) + o.period) % o.period;
      let pos = null;
      let ahead = null;
      o.alongside = false;
      if (ph < APPROACH) {
        const u = ease(ph / APPROACH);
        pos = o.inbound.getPointAt(u); ahead = o.inbound.getTangentAt(Math.min(u, 0.999));
      } else if (ph < APPROACH + o.stay) {
        pos = o.berth; o.alongside = true; alongside++;
      } else if (ph < 2 * APPROACH + o.stay) {
        const u = ease((ph - APPROACH - o.stay) / APPROACH);
        pos = o.outbound.getPointAt(u); ahead = o.outbound.getTangentAt(Math.min(u, 0.999));
      }
      o.mesh.visible = !!pos;
      if (!pos) continue;
      o.mesh.position.set(pos.x, tide, pos.z);
      o.mesh.rotation.y = ahead ? Math.atan2(-ahead.z, ahead.x) : o.rot;
    }
    return alongside;
  }

  function placeShips(h, tide) {
    let alongside = null;
    let moving = null;
    let waiting = null;
    for (const c of calls) {
      const m = c.mesh;
      let pos = null;
      let ahead = null;
      if (h >= c.from && h < c.to) {
        pos = c.berth; alongside = c;
      } else if (h >= c.from - APPROACH && h < c.from) {
        const u = ease((h - (c.from - APPROACH)) / APPROACH);
        pos = c.inbound.getPointAt(u); ahead = c.inbound.getTangentAt(Math.min(u, 0.999)); moving = { c, u, inbound: true };
      } else if (h >= c.to && h < c.to + APPROACH) {
        const u = ease((h - c.to) / APPROACH);
        pos = c.outbound.getPointAt(u); ahead = c.outbound.getTangentAt(Math.min(u, 0.999)); moving = { c, u, inbound: false };
      } else if (h >= c.from - APPROACH - ANCHOR && h < c.from - APPROACH) {
        pos = c.anchorage; waiting = c;
      }
      m.visible = !!pos;
      if (!pos) continue;
      m.position.set(pos.x, tide, pos.z);
      if (ahead) {
        // Coming in it turns to lie alongside; going out it straightens up towards the sea.
        const heading = Math.atan2(-ahead.z, ahead.x);
        const settle = moving && moving.inbound ? clamp((moving.u - 0.75) / 0.25, 0, 1) : moving ? 1 - clamp(moving.u / 0.3, 0, 1) : 0;
        m.rotation.y = heading * (1 - settle);
      } else {
        m.rotation.y = pos === c.anchorage ? 0.35 : 0;
      }
    }
    // Two tugs on the ship coming in or going out, near the berth.
    const near = moving && (moving.inbound ? moving.u > 0.45 : moving.u < 0.55);
    tugs.forEach((tug, i) => {
      tug.visible = !!near;
      if (!near) return;
      const m = moving.c.mesh;
      const along = (i ? 0.38 : -0.38) * moving.c.loa;
      const off = new THREE.Vector3(along, 0, -moving.c.beam / 2 - 12).applyAxisAngle(new THREE.Vector3(0, 1, 0), m.rotation.y);
      tug.position.set(m.position.x + off.x, tide, m.position.z + off.z);
      tug.rotation.y = m.rotation.y + (i ? 0.5 : -0.5);
    });
    return { alongside, moving, waiting };
  }

  // --- the cranes ----------------------------------------------------------------------------
  const boxMat = new THREE.MeshStandardMaterial({ color: 0x1e8fc0, roughness: 0.7 });
  for (const [i, c] of site.cranes.entries()) {
    const u = c.userData;
    u.offset = i * 0.37;
    if (u.trolley) {
      if (!u.trolley.parent) c.add(u.trolley);
      const carried = ctx.box(11.8, 2.55, 2.4, boxMat.clone(), 0, -1.6, 0);
      carried.material.color.setHex(ctx.BOX_COLOURS[i % ctx.BOX_COLOURS.length]);
      carried.visible = false;
      u.spreader.add(carried);
      u.carried = carried;
    }
  }
  function workCranes(states, mainShip, visualT, gust) {
    site.cranes.forEach((c, i) => {
      const u = c.userData;
      // A crane at another berth works that berth's ship, and stops in gusts over the limit.
      const other = u.berth ? otherOf.get(u.berth) : null;
      const state = u.berth ? (gust >= plan.limits.crane_stop_gust ? 'stopped' : 'working') : states[i] ? states[i].state : 'working';
      const alongside = u.berth ? (other && other.alongside ? other : null) : u.idle ? null : mainShip;
      const working = state === 'working' && !!alongside;
      if (u.boom) {
        const up = state === 'stowed' ? -1.25 : 0;
        u.boom.rotation.x += (up - u.boom.rotation.x) * 0.1;
        u.boom.position.z = state === 'stowed' ? (u.gauge || 30) - 4 : 0;
      }
      if (u.trolley) {
        let z = 10;
        let y = -10;
        let carrying = false;
        if (working) {
          const p = (visualT / CYCLE + u.offset) % 1;
          const reach = -28 - (alongside.beam - 32) * 0.4;
          if (p < 0.2) { z = reach; y = -10 - 22 * (p / 0.2); }
          else if (p < 0.3) { z = reach; y = -32 + 22 * ((p - 0.2) / 0.1); carrying = true; }
          else if (p < 0.5) { z = reach + (12 - reach) * ease((p - 0.3) / 0.2); carrying = true; }
          else if (p < 0.6) { z = 12; y = -10 - 28 * ((p - 0.5) / 0.1); carrying = true; }
          else if (p < 0.7) { z = 12; y = -38 + 28 * ((p - 0.6) / 0.1); }
          else if (p < 0.9) { z = 12 + (reach - 12) * ease((p - 0.7) / 0.2); }
          else { z = reach; }
        }
        u.trolley.position.z += (z - u.trolley.position.z) * (working ? 1 : 0.05);
        u.spreader.position.y += (y - u.spreader.position.y) * (working ? 1 : 0.05);
        if (u.carried) u.carried.visible = carrying;
        u.trolley.visible = state !== 'stowed';
      }
      if (u.top) {
        u.top.rotation.y = working ? 0.9 * Math.sin(visualT / CYCLE * 2 * Math.PI + i) : u.top.rotation.y * 0.98;
      }
    });
  }

  // --- people on the apron -----------------------------------------------------------------
  const PEOPLE = 70;
  const bodies = new THREE.InstancedMesh(new THREE.CylinderGeometry(0.28, 0.24, 1.3, 6), new THREE.MeshStandardMaterial({ color: 0xff7a00, roughness: 0.6, emissive: 0x331800 }), PEOPLE);
  const heads = new THREE.InstancedMesh(new THREE.SphereGeometry(0.22, 8, 6), new THREE.MeshStandardMaterial({ color: 0xf5f5f5, roughness: 0.4 }), PEOPLE);
  bodies.castShadow = heads.castShadow = true;
  scene.add(bodies, heads);
  const people = Array.from({ length: PEOPLE }, (_, i) => ({
    x: frame.minX + rng() * (frame.maxX - frame.minX), z: frame.front + 4 + rng() * 45, tx: 0, tz: 0, wait: rng() * 60,
    lasher: i < 24, walk: 1.1 + rng() * 0.5,
  }));
  const pm = new THREE.Matrix4();
  function movePeople(dt, alongside) {
    for (const [i, p] of people.entries()) {
      if (p.wait > 0) { p.wait -= dt; } else {
        const dx = p.tx - p.x;
        const dz = p.tz - p.z;
        const d = Math.hypot(dx, dz);
        if (d < 0.5) {
          // A new errand: lashers go to the ship's side while one is in, the rest about the apron.
          if (p.lasher && alongside) {
            p.tx = alongside.berth.x + (rng() - 0.5) * alongside.loa * 0.8; p.tz = frame.front + 2 + rng() * 4;
          } else {
            p.tx = frame.minX - 20 + rng() * (frame.maxX - frame.minX + 40); p.tz = frame.front + 4 + rng() * 50;
          }
          p.wait = 5 + rng() * 40;
        } else {
          const step = Math.min(d, p.walk * dt);
          p.x += (dx / d) * step; p.z += (dz / d) * step;
        }
      }
      pm.makeTranslation(p.x, frame.top + 0.65, p.z); bodies.setMatrixAt(i, pm);
      pm.makeTranslation(p.x, frame.top + 1.5, p.z); heads.setMatrixAt(i, pm);
    }
    bodies.instanceMatrix.needsUpdate = heads.instanceMatrix.needsUpdate = true;
  }

  // --- rain, mist, cloud and wind ----------------------------------------------------------
  const DROPS = 6000;
  const drops = new Float32Array(DROPS * 6);
  const box = { w: 700, h: 160, d: 500 };
  for (let i = 0; i < DROPS; i++) {
    const x = (rng() - 0.5) * box.w;
    const y = rng() * box.h;
    const z = (rng() - 0.5) * box.d;
    drops.set([x, y, z, x, y - 1.6, z], i * 6);
  }
  const rainGeo = new THREE.BufferGeometry();
  rainGeo.setAttribute('position', new THREE.BufferAttribute(drops, 3));
  const rain = new THREE.LineSegments(rainGeo, new THREE.LineBasicMaterial({ color: 0xaab8c8, transparent: true, opacity: 0.45 }));
  rain.frustumCulled = false;
  scene.add(rain);
  scene.fog = new THREE.Fog(0x9aa6b2, 600, 12000);
  // A windsock at the end of the quay.
  const sock = new THREE.Group();
  sock.add(ctx.box(0.3, 9, 0.3, REAL.steel, 0, 4.5, 0));
  const cone = new THREE.Mesh(new THREE.ConeGeometry(0.9, 4.5, 12, 1, true), new THREE.MeshStandardMaterial({ color: 0xff6d00, side: THREE.DoubleSide, roughness: 0.6 }));
  cone.rotation.z = Math.PI / 2;
  const sockPivot = new THREE.Group();
  sockPivot.position.y = 9;
  cone.position.x = 2.4;
  sockPivot.add(cone);
  sock.add(sockPivot);
  sock.position.set(frame.maxX + 15, frame.top, frame.front + 3);
  scene.add(sock);

  function weather(w, dt, pace) {
    const wet = clamp(w.rain / 6, 0, 1);
    rainGeo.setDrawRange(0, Math.round(DROPS * clamp(w.rain / 8, 0, 1)) * 2);
    rain.visible = w.rain > 0.05;
    if (rain.visible) {
      const fall = 9 * dt * Math.min(pace, 3);
      const drift = w.wind * 0.12 * dt * Math.min(pace, 3);
      for (let i = 0; i < DROPS * 6; i += 6) {
        drops[i + 1] -= fall; drops[i + 4] -= fall; drops[i] += drift; drops[i + 3] += drift * 1.4;
        if (drops[i + 1] < 0) { drops[i + 1] += box.h; drops[i + 4] = drops[i + 1] - 1.6; drops[i + 3] = drops[i]; }
        if (drops[i] > box.w / 2) { drops[i] -= box.w; drops[i + 3] -= box.w; }
      }
      rainGeo.attributes.position.needsUpdate = true;
      rain.position.set(controls.target.x, frame.top, controls.target.z);
    }
    scene.fog.far = 1500 + w.visibility * 1200;
    scene.fog.near = Math.min(scene.fog.far * 0.3, 900);
    sky.material.uniforms.turbidity.value = 3 + 14 * wet;
    sky.material.uniforms.rayleigh.value = 1.6 - 1.2 * wet;
    water.material.uniforms.distortionScale.value = 1.2 + w.hs * 2.8;
    // The sock fills and lifts with the wind, and swings a little.
    sockPivot.rotation.z = -clamp(1.2 - w.wind / 12, 0, 1.2);
    sockPivot.rotation.y = 0.4 + 0.15 * Math.sin(Date.now() / 900);
    cone.scale.setScalar(0.8 + clamp(w.wind / 25, 0, 0.4));
  }

  // --- the screen: a camera's caption, the controls and the berth's state ----------------
  const overlay = document.createElement('div');
  overlay.className = 'mt-live';
  overlay.innerHTML = `
    <div class="mt-live-cam"><span class="mt-live-rec">● REC</span> <span class="mt-live-camname"></span><div class="mt-live-clock tabular"></div></div>
    <div class="mt-live-state" aria-live="polite"></div>
    <div class="mt-live-alert" hidden></div>
    <div class="mt-live-bar">
      <button type="button" class="mt-live-play" aria-label="Pause">❚❚</button>
      <span class="mt-live-speeds" role="group" aria-label="Speed">${SPEEDS.map((s) => `<button type="button" data-speed="${s}">${s}×</button>`).join('')}</span>
      <span class="mt-live-track"><input type="range" class="mt-live-scrub" min="0" max="${total}" step="0.01" aria-label="Time in the next two days"></span>
      <span class="mt-live-cams" role="group" aria-label="Camera">${CAMERAS.map(([k, label]) => `<button type="button" data-cam="${k}">${label}</button>`).join('')}</span>
    </div>`;
  view.appendChild(overlay);
  const $ = (sel) => overlay.querySelector(sel);
  const scrub = $('.mt-live-scrub');
  // The day's events as ticks along the scrubber.
  const ticks = document.createElement('div');
  ticks.className = 'mt-live-ticks';
  for (const e of events) {
    const tick = document.createElement('i');
    tick.className = 'k-' + e.kind;
    tick.style.left = `${(100 * e.h) / total}%`;
    tick.title = e.text;
    ticks.appendChild(tick);
  }
  scrub.insertAdjacentElement('afterend', ticks);

  function setSpeed(s) {
    speed = s;
    for (const b of overlay.querySelectorAll('[data-speed]')) b.setAttribute('aria-pressed', String(Number(b.dataset.speed) === s));
  }
  setSpeed(10);
  $('.mt-live-play').addEventListener('click', () => {
    playing = !playing;
    $('.mt-live-play').textContent = playing ? '❚❚' : '▶';
    $('.mt-live-play').setAttribute('aria-label', playing ? 'Pause' : 'Play');
  });
  for (const b of overlay.querySelectorAll('[data-speed]')) b.addEventListener('click', () => setSpeed(Number(b.dataset.speed)));
  scrub.addEventListener('input', () => { simH = Number(scrub.value); refreshLog(true); });

  // The log below the view, newest first, up to the moment shown.
  const log = document.querySelector('.mt-live-log');
  let shownEvents = -1;
  function refreshLog(force) {
    const upTo = events.filter((e) => e.h <= simH);
    if (!log || (!force && upTo.length === shownEvents)) return;
    shownEvents = upTo.length;
    const fmt = (e) => new Date(realStart + e.h * 3600000).toLocaleString([], { weekday: 'short', hour: '2-digit', minute: '2-digit' });
    const coming = events.filter((e) => e.h > simH).slice(0, 3);
    log.innerHTML = (upTo.length ? upTo.slice(-12).reverse().map((e) => `<li class="k-${e.kind}"><time>${esc(fmt(e))}</time> ${esc(e.text)}</li>`).join('') : '<li class="muted">Nothing logged yet.</li>')
      + (coming.length ? `<li class="mt-live-next"><strong>Coming up</strong></li>` + coming.map((e) => `<li class="k-${e.kind} mt-live-later"><time>${esc(fmt(e))}</time> ${esc(e.text)}</li>`).join('') : '');
    for (const li of log.querySelectorAll('li')) {
      const e = [...upTo, ...coming].find((x) => li.textContent.includes(x.text));
      if (e) li.addEventListener('click', () => { simH = Math.max(0, e.h - 0.05); refreshLog(true); });
    }
  }

  // Cameras.
  let cam = 'drone';
  let droneAngle = 0;
  function setCamera(k) {
    cam = k;
    for (const b of overlay.querySelectorAll('[data-cam]')) b.setAttribute('aria-pressed', String(b.dataset.cam === k));
    $('.mt-live-camname').textContent = { quay: 'CAM 1 · QUAY', crane: 'CAM 2 · CRANE', drone: 'CAM 3 · DRONE', free: 'FREE VIEW' }[k];
    const crane = site.cranes[1] || site.cranes[0];
    if (k === 'quay') {
      // On a mast at the end of the quay, looking along the berth and the ship.
      camera.position.set(frame.minX - 70, frame.top + 24, frame.front + 14);
      controls.target.set(centre + 30, frame.top + 4, frame.fenderFace - 22);
    } else if (k === 'crane' && crane) {
      camera.position.set(crane.position.x + 6, frame.top + 52, crane.position.z + 34);
      controls.target.set(crane.position.x + 4, 0, frame.fenderFace - 28);
    } else if (k === 'free') {
      camera.position.copy(focus).add(new THREE.Vector3(radius * 0.8, radius * 0.95, -radius * 1.25));
      controls.target.copy(focus);
    }
    controls.update();
  }
  for (const b of overlay.querySelectorAll('[data-cam]')) b.addEventListener('click', () => setCamera(b.dataset.cam));
  // Taking hold of the view leaves the drone to it.
  ctx.renderer.domElement.addEventListener('pointerdown', () => { if (cam === 'drone') setCamera('free'); });
  setCamera('drone');

  // --- each frame --------------------------------------------------------------------------
  const player = { pace: 1, working: false, hs: 0.5, tick };
  let visualT = 0;
  let lastText = 0;
  let lastClock = 0;
  let lastReal = performance.now();
  function tick(dt) {
    // The clock runs on real time, not frames: a slow graphics card shows fewer frames, not a slower day.
    const real = Math.min((performance.now() - lastReal) / 1000, 1);
    lastReal = performance.now();
    if (playing) {
      simH += (real * speed) / 3600;
      if (simH >= total) { simH = 0; refreshLog(true); }          // the two days again
    }
    const pace = playing ? Math.min(speed, VISUAL_PACE) : 0;
    player.pace = pace;
    visualT += dt * pace;
    const w = at(simH);
    player.hs = w.hs;
    const now = realStart + simH * 3600000;
    // The sky and the lights follow the real sun; a few times a second is plenty.
    if (performance.now() - lastClock > 120 || !playing) {
      ctx.setClock(now);                                          // sets the sun's light for the hour...
      const wet = clamp(w.rain / 6, 0, 1);                        // ...which cloud and rain then dim
      sunLight.intensity *= 1 - 0.65 * wet;
      hemi.intensity *= 1 - 0.3 * wet;
      lastClock = performance.now();
    }
    const tide = w.tide;
    const { alongside, moving, waiting } = placeShips(simH, tide);
    const states = w.hour.equipment;
    const working = !!alongside && states.some((s) => s.state === 'working');
    player.working = working;
    busy = placeOthers(simH, tide) + (alongside ? 1 : 0);
    workCranes(states, alongside, visualT, w.gust);
    movePeople(dt * Math.min(pace, 4), alongside);
    weather(w, dt, pace);
    if (cam === 'drone') {
      droneAngle += dt * 0.025;
      const r = Math.max(radius * 1.4, 320);
      camera.position.set(centre + r * Math.sin(droneAngle), frame.top + r * 0.55, frame.fenderFace - 40 - r * Math.cos(droneAngle) * 0.9);
      controls.target.set(centre, frame.top, frame.fenderFace - 20);
    }
    if (performance.now() - lastText > 250) {
      lastText = performance.now();
      text(now, w, alongside, moving, waiting, states);
      if (!scrub.matches(':active')) scrub.value = String(simH);
      refreshLog(false);
    }
  }

  function movesDone(c) {
    let done = 0;
    for (let h = Math.floor(c.from); h < Math.min(simH, c.to); h++) {
      const span = Math.min(h + 1, simH, c.to) - Math.max(h, c.from);
      if (span <= 0) continue;
      const n = plan.hours[clamp(h, 0, total)].equipment.filter((s) => s.state === 'working').length;
      done += n * RATE * span;
    }
    return Math.min(c.moves, Math.round(done));
  }

  function text(now, w, alongside, moving, waiting, states) {
    const when = new Date(now);
    $('.mt-live-clock').textContent = when.toLocaleString([], { weekday: 'short', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', second: speed <= 10 ? '2-digit' : undefined });
    const chip = (label, value, bad) => `<span class="mt-chip${bad ? ' bad' : ''}"><small>${label}</small> ${value}</span>`;
    const L = plan.limits;
    let ship = 'Berth empty';
    if (alongside) ship = `${esc(alongside.name)} alongside · ${movesDone(alongside).toLocaleString()} of ${alongside.moves.toLocaleString()} ${esc(plan.units)}`;
    else if (moving) ship = `${esc(moving.c.name)} ${moving.inbound ? 'berthing' : 'sailing'}`;
    else if (waiting) {
      const due = new Date(realStart + waiting.from * 3600000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      ship = `${esc(waiting.name)} at anchor, ${waiting.held ? 'held by the weather' : 'due alongside ' + due}`;
    }
    $('.mt-live-state').innerHTML =
      `<div>${ship}</div>` +
      (others.length ? `<div class="small">${busy} of ${others.length + 1} berths with a ship alongside</div>` : '') +
      `<div class="mt-chips">${chip('wind', `${w.wind.toFixed(0)} m/s`, w.wind >= L.berthing_wind)}${chip('gusts', `${w.gust.toFixed(0)} m/s`, w.gust >= L.crane_stop_gust)}` +
      `${chip('waves', `${w.hs.toFixed(1)} m`, w.hs >= L.berthing_hs)}${chip('rain', w.rain > 0.05 ? `${w.rain.toFixed(1)} mm/h` : 'dry', w.rain > 4)}` +
      `${chip('tide', `${w.tide >= 0 ? '+' : ''}${w.tide.toFixed(2)} mCD`)}</div>` +
      `<div class="mt-chips">${states.map((s) => `<span class="mt-chip st-${s.state}" title="${esc(s.why)}">${esc(s.name)} ${esc(s.state)}</span>`).join('')}</div>`;
    // Lost time, said plainly.
    const idle = states.filter((s) => s.state !== 'working');
    let alert = '';
    if (alongside && idle.length) {
      alert = `Downtime: ${idle.map((s) => `${s.name} ${s.why || s.state}`).join('; ')}`;
    } else if (waiting && waiting.held) {
      alert = `Downtime: ${waiting.name} waiting at anchor, no berthing in this wind and sea`;
    } else if (alongside && !states.some((s) => s.state === 'working')) {
      alert = 'Downtime: nothing working the ship';
    }
    const box = $('.mt-live-alert');
    box.hidden = !alert;
    box.textContent = alert;
  }

  refreshLog(true);
  ctx.setMoving(true);
  return player;
}
