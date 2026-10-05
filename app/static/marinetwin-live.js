// The live port: the next two days at the berth, played back through the 3D twin like a camera.
//
// marinetwin.js builds the scene (the Revit model, the terminal, the sky and the sea) and hands it
// over here. This plays the timeline from live.json on it: ships taking the pilot, berthing with
// their tugs and sailing; the cranes (or ramp gangs, unloaders) working, stopping in gusts,
// breaking down; tractors and people on the apron; rain, mist, waves and the tide; day and night
// from the real sun. It runs at 10× by default, faster to watch a whole day go by, and says when
// the berth is losing time and why.

const SPEEDS = [1, 10, 60, 600];
const CAMERAS = [['quay', 'Quay camera'], ['crane', 'Crane camera'], ['drone', 'Drone'], ['ship', 'Ship'], ['free', 'Free']];
const CYCLE = 110;            // seconds a crane takes for one move, ship to quay and back
const RATE = 3600 / CYCLE;    // moves an hour, per crane
const VISUAL_PACE = 20;       // above this, things move no faster on screen: a timelapse, not a blur

const esc = (text) => String(text).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const ease = (u) => (u < 0.5 ? 2 * u * u : 1 - (-2 * u + 2) ** 2 / 2);
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
// How full a ship alongside from `from` to `to` is at hour h: discharged from full to the last
// tiers over the first half of her stay, then loaded up again for her next port.
const cargoFill = (h, from, to) => {
  const mid = (from + to) / 2;
  return h < mid ? 1 - 0.85 * clamp((h - from) / Math.max(mid - from, 0.1), 0, 1) : 0.15 + 0.75 * clamp((h - mid) / Math.max(to - mid, 0.1), 0, 1);
};

export async function startLive(ctx) {
  const { THREE, view, scene, camera, controls, frame, site, rng, focus, radius, water, sky, sunLight, hemi, REAL } = ctx;
  const planUrl = (key) => `${view.dataset.live}?scenario=${encodeURIComponent(key)}`;
  let plan = await (await fetch(planUrl(view.dataset.scenario || 'normal'), { credentials: 'same-origin' })).json();
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
  let calls = plan.calls.map((c) => ({ ...c, from: hourOf(c.eta), to: hourOf(c.etd) }));
  let events = plan.events.map((e) => ({ ...e, h: hourOf(e.at) }));

  // --- ships and their tugs ----------------------------------------------------------------
  // A call, as the hours go: up the fairway with the pilot and two tugs towing; stopped abreast
  // of the berth and pushed slowly sideways onto the fenders; the linesmen making her lines fast
  // one by one; worked; her lines let go; pushed off; out to sea. Cargo is worked only once she is
  // all fast and stops before she lets go.
  const T_IN = 1.0;         // h, fairway to abreast of the berth
  const PUSH_IN = 0.6;      // h, pushed in sideways, the last metres at a few centimetres a second
  const LINES_IN = 0.5;     // h, eight lines out and made fast
  const LINES_OUT = 0.3;    // h, lines let go
  const PUSH_OUT = 0.4;     // h, pulled off the berth
  const T_OUT = 1.0;        // h, out to sea
  const ARRIVE = T_IN + PUSH_IN;
  const DEPART = LINES_OUT + PUSH_OUT + T_OUT;
  const LINE_COUNT = 8;
  const ANCHOR = 6;       // hours a ship is seen waiting off the port before that
  // The way in and out of a berth, clear of the ships lying at the berths either side: up the
  // fairway well off the quay, slowing abreast of the berth, then pushed sideways onto the fenders
  // by the tugs; out the same way. `b` is a berth along a traced quay, or null for the model's own.
  function berthPath(b, beam, loa, k = 0) {
    let P;
    let t;
    let bow;
    let rot;
    if (b && b.leg) {
      const leg = b.leg;
      ({ bow, rot } = ctx.shipPose(b));
      t = b.mid - leg.from;
      P = (along, out) => new THREE.Vector3(leg.a[0] + leg.dir[0] * along - leg.land[0] * out, 0, leg.a[1] + leg.dir[1] * along - leg.land[1] * out);
    } else {
      bow = 1; rot = 0; t = 0;
      P = (along, out) => new THREE.Vector3(centre + along, 0, frame.fenderFace - out);
    }
    const off = beam / 2 + 2;
    const abreast = beam + 60;                 // clear of a neighbour's ship, with room for the tugs
    const berth = P(t, off);
    // In up the fairway from astern of the berth, out ahead of it, both well off the quay; where
    // the quay bends round (a basin, a corner) and that would cross land, a route that stays on
    // the water: further out, more square to the quay, or in from the other side.
    const sea = ctx.atSea;
    const routes = [[1700, 900, 800, 380], [1200, 1300, 500, 520], [600, 1400, 250, 600], [200, 1200, 80, 500],
      [-600, 1400, -250, 600], [-1700, 900, -800, 380], [0, 700, 0, 320]];
    const curve = (side, r) => new THREE.CatmullRomCurve3([P(t + side * r[0], r[1]), P(t + side * r[2], r[3]),
      P(t + side * Math.sign(r[2] || 1) * Math.min(Math.abs(r[2]) || 1, loa / 2 + 60), abreast + 10), P(t, abreast)]);
    const pick = (side) => {
      for (const r of routes) {
        const c = curve(side, r);
        if (!sea || sea.clear(c, beam / 2 + 10)) return c;
      }
      return curve(side, routes[routes.length - 1]);
    };
    const inbound = pick(-bow);
    const out = pick(bow);
    const outbound = new THREE.CatmullRomCurve3(out.points.slice().reverse());
    // Anchorages a few hundred metres apart, each berth's well clear of the others', on open water.
    const n = b ? b.n : 0;
    const start = inbound.points[0];
    let anchorage = P(t - bow * 400, 1000 + (n % 3) * 320 + (k % 2) * 160);
    if (sea && !sea(anchorage.x, anchorage.z, 250)) {
      anchorage = null;
      for (const d of [0, 300, 600, 900, 1300]) {
        const a = start.clone().add(P(0, d + (n % 3) * 200 + (k % 2) * 120).sub(P(0, 0)));     // further out to sea
        if (sea(a.x, a.z, 250)) { anchorage = a; break; }
      }
      if (!anchorage) anchorage = start.clone();
    }
    return { berth, rot, abreast: P(t, abreast), inbound, outbound, anchorage };
  }
  // Heading along a path, turned to lie alongside (`settle` from 0 to 1) at the berth.
  const turnTo = (heading, rot, settle) => {
    const d = ((((rot - heading) % (2 * Math.PI)) + 3 * Math.PI) % (2 * Math.PI)) - Math.PI;
    return heading + d * settle;
  };
  // Where a ship is at hour h on a call all fast at A and sailing at D, along `path`.
  function voyage(h, A, D, path) {
    let pos;
    let rot = path.rot;
    let phase;
    let u = 0;
    let lines = 0;
    if (h < A - ARRIVE || h >= D + DEPART) return null;
    if (h < A - PUSH_IN) {
      phase = 'in'; u = ease((h - (A - ARRIVE)) / T_IN);
      pos = path.inbound.getPointAt(u);
      const ahead = path.inbound.getTangentAt(Math.min(u, 0.999));
      rot = turnTo(Math.atan2(-ahead.z, ahead.x), path.rot, clamp((u - 0.7) / 0.3, 0, 1));
    } else if (h < A) {
      phase = 'push-in'; u = ease((h - (A - PUSH_IN)) / PUSH_IN);
      pos = path.abreast.clone().lerp(path.berth, u);
    } else if (h < A + LINES_IN) {
      phase = 'lines-in'; pos = path.berth; lines = Math.min(LINE_COUNT, 1 + Math.floor((LINE_COUNT * (h - A)) / LINES_IN));
    } else if (h < D) {
      phase = 'alongside'; pos = path.berth; lines = LINE_COUNT;
    } else if (h < D + LINES_OUT) {
      phase = 'lines-out'; pos = path.berth; lines = LINE_COUNT - Math.floor((LINE_COUNT * (h - D)) / LINES_OUT);
    } else if (h < D + LINES_OUT + PUSH_OUT) {
      phase = 'push-out'; u = ease((h - D - LINES_OUT) / PUSH_OUT);
      pos = path.berth.clone().lerp(path.abreast, u);
    } else {
      phase = 'out'; u = ease((h - D - LINES_OUT - PUSH_OUT) / T_OUT);
      pos = path.outbound.getPointAt(u);
      const ahead = path.outbound.getTangentAt(Math.min(u, 0.999));
      rot = turnTo(Math.atan2(-ahead.z, ahead.x), path.rot, 1 - clamp(u / 0.3, 0, 1));
    }
    return { pos, rot, phase, u, lines };
  }

  // Mooring lines, from the ship's fairleads to bollards on the quay: head lines, breast lines and
  // springs at each end, as fractions of her length (on board, on the quay). Made fast springs
  // first, then breasts, then head and stern lines; let go in the reverse order.
  const LINES = [[0.47, 0.62], [0.45, 0.57], [0.37, 0.38], [0.26, 0.04], [-0.26, -0.04], [-0.37, -0.38], [-0.45, -0.57], [-0.47, -0.62]];
  const LINE_ORDER = [3, 4, 2, 5, 1, 6, 0, 7];
  // The lines are drawn as ropes (thin cylinders), thick enough to see from the drone.
  const ROPES = 192;
  const ropes = new THREE.InstancedMesh(new THREE.CylinderGeometry(0.22, 0.22, 1, 5), new THREE.MeshStandardMaterial({ color: 0xead27a, roughness: 0.8 }), ROPES);
  ropes.frustumCulled = false;
  scene.add(ropes);
  let ropesUsed = 0;
  const UP = new THREE.Vector3(0, 1, 0);
  const rq = new THREE.Quaternion();
  const ra = new THREE.Vector3();
  const rb = new THREE.Vector3();
  function rope(a, b) {
    if (ropesUsed >= ROPES) return;
    const d = rb.copy(b).sub(a);
    const len = d.length();
    rq.setFromUnitVectors(UP, d.divideScalar(len || 1));
    mm.compose(ra.copy(a).add(b).multiplyScalar(0.5), rq, new THREE.Vector3(1, len, 1));
    ropes.setMatrixAt(ropesUsed++, mm);
  }
  const MEN = 64;
  const menBody = new THREE.InstancedMesh(new THREE.CylinderGeometry(0.3, 0.26, 1.4, 6), new THREE.MeshStandardMaterial({ color: 0xff7a00, emissive: 0x442200 }), MEN);
  const menHead = new THREE.InstancedMesh(new THREE.SphereGeometry(0.24, 8, 6), new THREE.MeshStandardMaterial({ color: 0xffffff }), MEN);
  scene.add(menBody, menHead);
  let menUsed = 0;
  const mm = new THREE.Matrix4();
  function linesman(x, z) {
    if (menUsed >= MEN) return;
    menBody.setMatrixAt(menUsed, mm.makeTranslation(x, frame.top + 0.7, z));
    menHead.setMatrixAt(menUsed, mm.makeTranslation(x, frame.top + 1.6, z));
    menUsed++;
  }
  function moor(mesh, v, tide) {
    const ud = mesh.userData;
    if (!v || !v.lines) return;
    const a = [Math.cos(v.rot), -Math.sin(v.rot)];            // along the ship, bow-wards
    const l = [Math.sin(v.rot), Math.cos(v.rot)];             // towards the quay
    for (const k of LINE_ORDER.slice(0, v.lines)) {
      const [sx, qx] = LINES[k];
      rope(new THREE.Vector3(v.pos.x + a[0] * sx * ud.loa + l[0] * (ud.beam / 2 - 0.5), tide + ud.deck, v.pos.z + a[1] * sx * ud.loa + l[1] * (ud.beam / 2 - 0.5)),
        new THREE.Vector3(v.pos.x + a[0] * qx * ud.loa + l[0] * (ud.beam / 2 + 3.5), frame.top + 0.6, v.pos.z + a[1] * qx * ud.loa + l[1] * (ud.beam / 2 + 3.5)));
    }
    // The linesmen at the bollards of the lines being handled now.
    if (v.phase === 'lines-in' || v.phase === 'lines-out') {
      const now = v.phase === 'lines-in' ? v.lines - 1 : v.lines;
      for (const k of LINE_ORDER.slice(Math.max(0, now - 1), now + 2)) {
        const qx = LINES[k][1];
        linesman(v.pos.x + a[0] * qx * ud.loa + l[0] * (ud.beam / 2 + 4.5), v.pos.z + a[1] * qx * ud.loa + l[1] * (ud.beam / 2 + 4.5));
        linesman(v.pos.x + a[0] * (qx + 0.01) * ud.loa + l[0] * (ud.beam / 2 + 5.5), v.pos.z + a[1] * (qx + 0.01) * ud.loa + l[1] * (ud.beam / 2 + 5.5));
      }
    }
  }
  // Tugs: two on each ship near her berth, towing ahead and astern in the fairway, then on her
  // seaward side pushing her on (or pulling her off) the berth.
  const tugMat = new THREE.MeshStandardMaterial({ color: 0xc62828, roughness: 0.5 });
  const tugs = Array.from({ length: 16 }, () => {
    const g = new THREE.Group();
    g.add(ctx.box(28, 4, 9, tugMat, 0, 1, 0));
    g.add(ctx.box(9, 5, 7, REAL.white, -2, 5, 0));
    g.visible = false;
    scene.add(g);
    return g;
  });
  let tugsUsed = 0;
  function tugsFor(mesh, v, tide) {
    if (!v) return;
    const near = (v.phase === 'in' && v.u > 0.55) || v.phase === 'push-in' || v.phase === 'lines-in' || v.phase === 'lines-out'
      || v.phase === 'push-out' || (v.phase === 'out' && v.u < 0.4);
    if (!near) return;
    const { loa, beam } = mesh.userData;
    const pushing = v.phase !== 'in' && v.phase !== 'out';
    for (const side of [1, -1]) {
      const tug = tugs[tugsUsed++];
      if (!tug) return;
      // In the ship's frame: x along her, z towards the quay.
      const local = pushing ? [side * 0.3 * loa, -(beam / 2 + 14)] : [side * (loa / 2 + 40), 0];
      const off = new THREE.Vector3(local[0], 0, local[1]).applyAxisAngle(new THREE.Vector3(0, 1, 0), v.rot);
      tug.position.set(v.pos.x + off.x, tide, v.pos.z + off.z);
      tug.rotation.y = pushing ? v.rot - Math.PI / 2 : v.rot;
      tug.visible = true;
    }
  }
  function startFrame() {
    for (const t of tugs) t.visible = false;
    tugsUsed = 0;
    menUsed = 0;
    ropesUsed = 0;
  }
  function endFrame() {
    for (let i = ropesUsed; i < ROPES; i++) ropes.setMatrixAt(i, mm.makeScale(0, 0, 0));
    ropes.instanceMatrix.needsUpdate = true;
    for (let i = menUsed; i < MEN; i++) { menBody.setMatrixAt(i, mm.makeScale(0, 0, 0)); menHead.setMatrixAt(i, mm); }
    menBody.instanceMatrix.needsUpdate = menHead.instanceMatrix.needsUpdate = true;
  }

  function shipCalls() {
    const main = site.mainBerth && site.mainBerth.leg ? site.mainBerth : null;
    calls.forEach((c, k) => {
      // No longer than her berth, so she does not overlap the ships at the next ones.
      const loa = main ? Math.min(c.loa, main.length - 20) : c.loa;
      c.mesh = ctx.ship(c.type, loa, c.beam, c.draught, rng, ctx.flagCode(c.name, c.flag));
      c.mesh.traverse((m) => { if (m.isMesh) m.castShadow = true; });
      c.mesh.visible = false;
      scene.add(c.mesh);
      Object.assign(c, berthPath(main, c.beam, loa, k), { shown: loa });
      c.mesh.userData.pick = () => shipCard(c, site.mainBerth, c.mesh);
    });
  }
  shipCalls();

  // --- the other berths along the quay ------------------------------------------------------
  // Each has its own line of ships, one after another: waiting at anchor if the berth or the
  // weather is not ready, in from the sea, alongside while its cranes discharge and then load it
  // (stopping in gusts like the rest), out to sea, and a gap before the next. Storms and fog hold
  // them at anchor or alongside as they hold the main berth's ships; a peak week leaves no gap.
  const SHIP_NAMES = ['Maersk Elba', 'CMA CGM Thalia', 'MSC Rania', 'ONE Harmony', 'Hapag Lisbon', 'Evergreen Lyra',
    'COSCO Pride', 'Zim Atlantic', 'Yang Ming Unity', 'HMM Oslo', 'Grande Abidjan', 'Arkas Lagos'];
  const CARGO_NAMES = ['BBC Rhine', 'Atlantic Pioneer', 'Nordic Steel', 'Spliethoff Sea', 'Jumbo Vision', 'Hansa Coaster'];
  const RORO_NAMES = ['Höegh Trigger', 'Glovis Sky', 'Grande Marocco', 'Morning Lily', 'Neptune Ace', 'Tonsberg'];
  const nameFor = (type, n, k) => {
    const list = /ro-ro/.test(type) ? RORO_NAMES : /general/.test(type) ? CARGO_NAMES : SHIP_NAMES;
    return list[(n * 3 + k) % list.length];
  };
  // A number in [0, 1) for berth n, call k and what it is for: the same every time it is asked.
  const draw = (n, k, what) => { const x = Math.sin(n * 127.1 + k * 311.7 + what * 74.7) * 43758.5453; return x - Math.floor(x); };
  const okAt = (h) => {
    const i = clamp(Math.floor(h), 0, total);
    return plan.hours[i].berthing && (i === 0 || plan.hours[i - 1].berthing);
  };
  function makeOther(b) {
    const types = b.use === 'mixed' ? ['general cargo', 'ro-ro'] : [ctx.berthShipType(b.use)];
    const meshes = types.map((type) => {
      const mesh = ctx.ship(type, b.loa, b.beam, 12, rng, ctx.flagCode(nameFor(type, b.n, 0)));
      mesh.traverse((m) => { if (m.isMesh) m.castShadow = true; });
      mesh.visible = false;
      mesh.userData.type = type;
      mesh.userData.pick = () => { const o = otherOf.get(b); return o && o.ship ? shipCard(o.ship, b, mesh) : null; };
      scene.add(mesh);
      return mesh;
    });
    return { b, meshes, alongside: false, ship: null, ...berthPath(b, b.beam, b.loa) };
  }
  // The calls at a berth over the timeline, for the situation playing.
  function schedule(o) {
    const n = o.b.n;
    const peak = plan.scenario && plan.scenario.key === 'peak';
    const calls = [];
    let t = -draw(n, 0, 1) * 20;
    let gone = -99;
    for (let k = 0; t < total + 12 && k < 40; k++) {
      const stay = 8 + draw(n, k, 2) * 16;
      const gap = peak ? 0.2 + draw(n, k, 3) * 1.2 : 1 + draw(n, k, 3) * 7;
      let arrive = Math.max(t, gone + 0.25);
      while (arrive < total && !okAt(arrive)) arrive += 0.25;       // held at anchor by the weather
      const along = arrive + ARRIVE;
      let sail = along + stay;
      while (sail < total && !okAt(sail)) sail += 0.25;               // held alongside
      const mesh = o.meshes[k % o.meshes.length];
      calls.push({ k, due: t, anchorFrom: Math.max(gone, t - (peak ? 6 : 3)), arrive, along, sail, gone: sail + DEPART,
        held: arrive > t + 0.2, mesh, name: nameFor(mesh.userData.type, n, k), type: mesh.userData.type });
      gone = sail + DEPART;
      t = gone + gap;
    }
    o.calls = calls;
  }
  const others = (site.berths || []).filter((b) => !b.main && b.loa >= 120).map(makeOther);
  for (const o of others) schedule(o);
  const otherOf = new Map(others.map((o) => [o.b, o]));
  let busy = 0;          // berths with a ship alongside, the main one included
  let anchored = 0;      // ships waiting at anchor for the other berths
  function placeOthers(h, tide) {
    let alongside = 0;
    anchored = 0;
    for (const o of others) {
      for (const m of o.meshes) m.visible = false;
      o.alongside = false;
      o.ship = null;
      o.b.state = null;
      const c = o.calls.find((x) => h >= x.anchorFrom && h < x.gone);
      if (!c) continue;
      const v = h >= c.arrive ? voyage(h, c.along, c.sail, o) : null;
      o.ship = c;
      c.mesh.userData.setFlag(ctx.flagCode(c.name, c.flag));        // the model is reused from call to call
      o.phase = v ? v.phase : 'anchor';
      c.stage = o.phase;
      c.mesh.visible = true;
      moor(c.mesh, v, tide);
      tugsFor(c.mesh, v, tide);
      if (!v) {
        anchored++;
        c.mesh.position.set(o.anchorage.x, tide, o.anchorage.z);
        c.mesh.rotation.y = o.rot + 0.4;
        ctx.setFill(c.mesh.userData.stacks, 1);
        continue;
      }
      c.mesh.position.set(v.pos.x, tide, v.pos.z);
      c.mesh.rotation.y = v.rot;
      if (v.phase === 'alongside') {
        o.alongside = true; alongside++;
        o.b.state = h < (c.along + LINES_IN + c.sail) / 2 ? 'discharging' : 'loading';
        o.b.shipKind = c.mesh.userData.kind;
      }
      if (v.phase === 'alongside' || v.phase.startsWith('lines')) o.b.fill = cargoFill(h, c.along + LINES_IN, c.sail);
      ctx.setFill(c.mesh.userData.stacks, v.phase === 'alongside' || v.phase.startsWith('lines') ? o.b.fill : h < c.along ? 1 : 0.9);
    }
    return alongside;
  }
  // A berth set to another use: dressed again, with its own ships for it.
  function redress(b, use) {
    site.dress(b, use);
    const old = otherOf.get(b);
    if (old) {
      for (const m of old.meshes) scene.remove(m);
      const o = makeOther(b);
      schedule(o);
      others[others.indexOf(old)] = o;
      otherOf.set(b, o);
    }
  }

  function placeShips(h, tide) {
    let alongside = null;
    let moving = null;
    let waiting = null;
    let mooring = null;
    for (const c of calls) {
      const m = c.mesh;
      const v = voyage(h, c.from, c.to, c);
      let pos = null;
      if (v) {
        pos = v.pos;
        m.rotation.y = v.rot;
        if (v.phase === 'alongside') alongside = c;
        else if (v.phase === 'lines-in' || v.phase === 'lines-out') mooring = { c, making: v.phase === 'lines-in', lines: v.lines };
        else moving = { c, u: v.u, inbound: v.phase === 'in' || v.phase === 'push-in', pushing: v.phase.startsWith('push') };
      } else if (h >= c.from - ARRIVE - ANCHOR && h < c.from - ARRIVE) {
        pos = c.anchorage; waiting = c;
        m.rotation.y = c.rot + 0.35;
      }
      m.visible = !!pos;
      c.stage = v ? v.phase : pos ? 'anchor' : null;
      moor(m, v, tide);
      tugsFor(m, v, tide);
      if (!pos) continue;
      m.position.set(pos.x, tide, pos.z);
      // Discharged down to the last tiers over the first half of her stay, loaded up again over the second.
      if (v && (v.phase === 'alongside' || v.phase.startsWith('lines'))) {
        const fill = cargoFill(h, c.from + LINES_IN, c.to);
        ctx.setFill(m.userData.stacks, fill);
        if (site.mainBerth) site.mainBerth.fill = fill;
      } else {
        ctx.setFill(m.userData.stacks, h < c.from ? 1 : 0.9);
      }
    }
    return { alongside, moving, waiting, mooring };
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
  function workCranes(states, mainShip, visualT, w) {
    const gust = w.gust;
    const power = w.hour.power !== false;
    const main = site.mainBerth || {};
    site.cranes.forEach((c, i) => {
      const u = c.userData;
      if (u.offset === undefined) u.offset = (i * 0.37) % 1;
      // A crane at another berth works that berth's ship (not a car carrier: that drives off over
      // its ramp), stops in gusts over the limit, and, if it runs on the grid, in a power cut.
      const other = u.berth ? otherOf.get(u.berth) : null;
      let state;
      if (u.berth) {
        state = gust >= plan.limits.crane_stow_gust && !u.mobile ? 'stowed' : gust >= plan.limits.crane_stop_gust ? 'stopped'
          : !power && !u.mobile ? 'down' : 'working';
      } else {
        state = states[i] ? states[i].state : 'working';
      }
      const alongside = u.berth ? (other && other.alongside && other.b.shipKind !== 'roro' ? other.b : null) : u.idle ? null : mainShip;
      const working = state === 'working' && !!alongside;
      const loading = (u.berth ? u.berth.state : main.state) === 'loading';
      // For its card.
      u.state = state === 'working' && !alongside ? 'idle' : state;
      u.why = u.berth ? (state === 'stowed' ? 'on its storm pins: gusts over the stow limit' : state === 'stopped' ? 'wind stop: gusts over the operating limit'
        : state === 'down' ? 'power cut, no grid supply' : '') : (states[i] && states[i].why) || '';
      const call = u.berth ? other && other.ship : mainShip;
      u.shipName = alongside && call ? call.name : '';
      u.doing = working ? (loading ? 'Loading, quay to ship' : 'Discharging, ship to quay') : alongside ? 'Stopped with a ship alongside' : 'Waiting for a ship';
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
          // One move: down into the ship, up, across to the quay, down to the tractor, up, back.
          // Discharging it carries a box on the way to the quay; loading, on the way to the ship.
          const p = (visualT / CYCLE + u.offset) % 1;
          const reach = -28 - ((alongside.beam || 32) - 32) * 0.4;
          if (p < 0.2) { z = reach; y = -10 - 22 * (p / 0.2); }
          else if (p < 0.3) { z = reach; y = -32 + 22 * ((p - 0.2) / 0.1); }
          else if (p < 0.5) { z = reach + (12 - reach) * ease((p - 0.3) / 0.2); }
          else if (p < 0.6) { z = 12; y = -10 - 28 * ((p - 0.5) / 0.1); }
          else if (p < 0.7) { z = 12; y = -38 + 28 * ((p - 0.6) / 0.1); }
          else if (p < 0.9) { z = 12 + (reach - 12) * ease((p - 0.7) / 0.2); }
          else { z = reach; }
          carrying = loading ? p >= 0.6 || p < 0.2 : p >= 0.2 && p < 0.6;
        }
        u.trolley.position.z += (z - u.trolley.position.z) * (working ? 1 : 0.05);
        u.spreader.position.y += (y - u.spreader.position.y) * (working ? 1 : 0.05);
        if (u.carried) u.carried.visible = carrying;
        u.trolley.visible = state !== 'stowed';
      }
      if (u.top) {
        // A mobile crane slews between the ship and the quay, the load on its hook one way.
        const a = visualT / CYCLE * 2 * Math.PI + i;
        u.top.rotation.y = working ? 0.9 * Math.sin(a) : u.top.rotation.y * 0.98;
        if (u.load) u.load.visible = working && (loading ? Math.cos(a) < 0 : Math.cos(a) > 0);
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
      <select class="mt-life-part mt-live-scenario" aria-label="Situation">${(plan.scenarios || []).map((x) => `<option value="${esc(x.key)}" title="${esc(x.words)}">${esc(x.name)}</option>`).join('')}</select>
      ${others.length ? '<button type="button" class="mt-live-berths-btn" aria-pressed="false">Berths</button>' : ''}
    </div>`;
  view.appendChild(overlay);
  const $ = (sel) => overlay.querySelector(sel);
  const scrub = $('.mt-live-scrub');
  // The day's events as ticks along the scrubber.
  const ticks = document.createElement('div');
  ticks.className = 'mt-live-ticks';
  function drawTicks() {
    ticks.replaceChildren();
    for (const e of events) {
      const tick = document.createElement('i');
      tick.className = 'k-' + e.kind;
      tick.style.left = `${(100 * e.h) / total}%`;
      tick.title = e.text;
      ticks.appendChild(tick);
    }
  }
  drawTicks();
  scrub.insertAdjacentElement('afterend', ticks);

  // The situation playing: the same two days with a storm, a power cut, fog... laid over them.
  const situation = $('.mt-live-scenario');
  situation.value = plan.scenario ? plan.scenario.key : 'normal';
  situation.addEventListener('change', async () => {
    const key = situation.value;
    situation.disabled = true;
    try {
      const next = await (await fetch(planUrl(key), { credentials: 'same-origin' })).json();
      for (const c of calls) scene.remove(c.mesh);
      plan = next;
      calls = plan.calls.map((c) => ({ ...c, from: hourOf(c.eta), to: hourOf(c.etd) }));
      events = plan.events.map((e) => ({ ...e, h: hourOf(e.at) }));
      shipCalls();
      for (const o of others) schedule(o);
      drawTicks();
      refreshLog(true);
      const url = new URL(window.location.href);
      if (key === 'normal') url.searchParams.delete('scenario'); else url.searchParams.set('scenario', key);
      window.history.replaceState(null, '', url);
    } finally {
      situation.disabled = false;
    }
  });

  // The berths along the quay: what each is doing now, and what each without crane stoppers is used for.
  const USE_NAMES = (ctx.twin.asset && ctx.twin.asset.berth_use_names) || {};
  const panel = document.createElement('div');
  panel.className = 'mt-berths';
  panel.hidden = true;
  const allBerths = [...(site.berths || [])].sort((a, b) => a.n - b.n);
  panel.innerHTML = `<button type="button" class="close" aria-label="Close">×</button><h3>Berths along the quay</h3><p class="small" style="margin:0 0 6px;opacity:.75">Look takes the drone to a berth; drag to turn about it, double-click to centre anywhere.</p><ol>${allBerths.map((b) => `
    <li data-n="${b.n}"><strong>Berth ${b.n} ${site.quay ? `<button type="button" class="mt-b-look" data-n="${b.n}">Look</button>` : ''}</strong><small>${Math.round(b.length)} m · ${b.main ? 'the berth this line-up is for' : b.sts ? 'crane stoppers: rail-mounted cranes' : 'no crane stoppers'}</small>
      ${b.assignable ? `<label class="small">Used for <select data-n="${b.n}">${Object.entries(USE_NAMES).map(([k, v]) => `<option value="${esc(k)}"${k === b.use ? ' selected' : ''}>${esc(v)}</option>`).join('')}</select></label>` : ''}
      <small class="mt-b-now"></small></li>`).join('')}</ol>`;
  overlay.appendChild(panel);
  const berthsBtn = $('.mt-live-berths-btn');
  const showBerths = (on) => { panel.hidden = !on; if (berthsBtn) berthsBtn.setAttribute('aria-pressed', String(on)); };
  if (berthsBtn) berthsBtn.addEventListener('click', () => showBerths(panel.hidden));
  panel.querySelector('.close').addEventListener('click', () => showBerths(false));
  for (const btn of panel.querySelectorAll('.mt-b-look')) {
    btn.addEventListener('click', () => lookAt(allBerths.find((x) => String(x.n) === btn.dataset.n)));
  }
  for (const sel of panel.querySelectorAll('select[data-n]')) {
    sel.addEventListener('change', async () => {
      const b = allBerths.find((x) => String(x.n) === sel.dataset.n);
      const was = b.use;
      sel.disabled = true;
      try {
        const answer = await fetch(view.dataset.berths, {
          method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ berth: b.n, use: sel.value }),
        });
        if (!answer.ok) throw new Error(`the server answered ${answer.status}`);
        redress(b, sel.value);
      } catch (err) {
        sel.value = was;
        sel.title = 'Not saved: ' + (err.message || err);
      } finally {
        sel.disabled = false;
      }
    });
  }
  const fmtHour = (h) => new Date(realStart + h * 3600000).toLocaleString([], { weekday: 'short', hour: '2-digit', minute: '2-digit' });
  function movingWords(mv) {
    if (mv.pushing) return mv.inbound ? 'being pushed alongside by the tugs' : 'being pulled off the berth by the tugs';
    return mv.inbound ? 'coming in with the pilot and tugs' : 'sailing';
  }
  const PHASE_WORDS = {
    in: 'coming in with the pilot and tugs', 'push-in': 'being pushed alongside by the tugs', 'lines-in': 'making fast her lines',
    'lines-out': 'letting go her lines', 'push-out': 'being pulled off by the tugs', out: 'sailing',
  };
  // A ship's card: what she is, where she is in her call and how much cargo is aboard.
  function shipCard(c, b, mesh) {
    const stage = c.stage === 'alongside' ? `Alongside, ${b && b.state ? b.state : 'working'}`
      : c.stage === 'anchor' ? (c.held && simH >= (c.due ?? 0) ? 'At anchor, held by the weather' : 'At anchor, waiting for the berth')
      : c.stage ? capital(PHASE_WORDS[c.stage] || c.stage) : 'Not in port now';
    const stacks = mesh.userData.stacks;
    const fill = stacks && stacks.userData.total ? stacks.count / stacks.userData.total : b && b.fill !== undefined ? b.fill : null;
    const arrive = c.from ?? c.along;
    const sail = c.to ?? c.sail;
    return {
      kind: c.type.replace('ro-ro', 'car carrier (RoRo)'), title: c.name,
      follow: mesh,
      rows: [['Berth', b ? (b.n !== undefined ? `Berth ${b.n}${b.main ? ' (main)' : ''}` : 'Main berth') : ''], ['Now', stage],
        ['Flag', c.flag_name || ctx.FLAG_NAMES[mesh.userData.flag] || ''],
        ['Length overall', `${Math.round(c.shown || c.loa || mesh.userData.loa)} m`], ['Beam', `${Math.round(c.beam || mesh.userData.beam)} m`],
        ['Draught', c.draught ? `${c.draught} m` : ''], ['Cargo aboard', fill === null ? '' : `${Math.round(fill * 100)}%`],
        ['Alongside from', fmtHour(arrive)], ['Sails', fmtHour(sail)],
        ['Cargo work', c.moves ? `${movesDone(c).toLocaleString()} of ${c.moves.toLocaleString()} ${plan.units}` : '']],
    };
  }
  const capital = (s) => s[0].toUpperCase() + s.slice(1);
  function berthNow(b, mainCall, mainMoving, mainWaiting, mainMooring) {
    if (b.main) {
      if (mainCall) return `${mainCall.name} ${b.state || 'alongside'}`;
      if (mainMooring) return `${mainMooring.c.name} ${mainMooring.making ? 'making fast her lines' : 'letting go her lines'}`;
      if (mainMoving) return `${mainMoving.c.name} ${movingWords(mainMoving)}`;
      if (mainWaiting) return `${mainWaiting.name} at anchor`;
      return 'Empty';
    }
    const o = otherOf.get(b);
    if (!o) return 'Too short for a ship';
    const c = o.ship;
    if (!c) {
      const next = o.calls.find((x) => x.anchorFrom > simH);
      return next ? `Empty; ${next.name} due ${fmtHour(next.arrive)}` : 'Empty';
    }
    const what = c.type.replace('ro-ro', 'car carrier');
    if (simH < c.arrive) return `${c.name} (${what}) at anchor${c.held && simH >= c.due ? ', held by the weather' : ''}`;
    if (o.phase !== 'alongside') return `${c.name} (${what}) ${PHASE_WORDS[o.phase] || ''}`;
    return `${c.name} (${what}) ${c.type === 'ro-ro' ? (b.state === 'discharging' ? 'driving vehicles off' : 'driving vehicles on') : b.state}`;
  }

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
  let prevCam = 'drone';       // the camera before the ship camera, to go back to
  let shipName = '';
  let leaving = false;
  let droneAngle = 0;
  // What the drone circles and the free view turns about: the main berth at first, then whichever
  // berth is picked under Berths, or any spot double-clicked.
  const spot = { x: centre, z: frame.fenderFace - 20, r: Math.max(radius * 1.4, 320) };
  function setCamera(k, keep = false) {
    cam = k;
    for (const b of overlay.querySelectorAll('[data-cam]')) b.setAttribute('aria-pressed', String(b.dataset.cam === k));
    $('.mt-live-camname').textContent = { quay: 'CAM 1 · QUAY', crane: 'CAM 2 · CRANE', drone: 'CAM 3 · DRONE', ship: `CAM 4 · SHIP${shipName ? ' · ' + shipName.toUpperCase() : ''}`, free: 'FREE VIEW · double-click to centre on a spot' }[k];
    const crane = site.cranes[1] || site.cranes[0];
    if (k !== 'ship' && ctx.following()) { leaving = true; ctx.stopFollow(); leaving = false; }
    if (keep) return;                   // the view stays where it is
    if (k === 'ship') {
      // The main berth's ship if one is about (in, alongside, out or at anchor), else the ship
      // nearest the middle of the view.
      const main = calls.find((c) => c.mesh.visible && c.stage && c.stage !== 'anchor') || calls.find((c) => c.mesh.visible);
      let best = main ? { c: main, mesh: main.mesh, b: site.mainBerth } : null;
      if (!best) {
        let d = Infinity;
        for (const o of others) {
          if (!o.ship || !o.ship.mesh.visible) continue;
          const e = o.ship.mesh.position.distanceTo(controls.target);
          if (e < d) { d = e; best = { c: o.ship, mesh: o.ship.mesh, b: o.b }; }
        }
      }
      if (best) ctx.follow(best.mesh, 'orbit', best.c.name);
      else setCamera(prevCam === 'ship' ? 'drone' : prevCam);     // no ship in port to follow
      return;
    }
    if (k === 'quay') {
      // On a mast at the end of the quay, looking along the berth and the ship.
      camera.position.set(frame.minX - 70, frame.top + 24, frame.front + 14);
      controls.target.set(centre + 30, frame.top + 4, frame.fenderFace - 22);
    } else if (k === 'crane' && crane) {
      camera.position.set(crane.position.x + 6, frame.top + 52, crane.position.z + 34);
      controls.target.set(crane.position.x + 4, 0, frame.fenderFace - 28);
    } else if (k === 'free') {
      controls.target.set(spot.x, frame.top, spot.z);
      camera.position.set(spot.x + spot.r * 0.55, frame.top + spot.r * 0.6, spot.z - spot.r * 0.8);
    }
    controls.update();
  }
  // Look at a berth: the drone circles it, and taking hold of the view turns about it.
  function lookAt(b) {
    const p = ctx.quayPoint(site.quay, b.mid, 10);
    Object.assign(spot, { x: p.x, z: p.z, r: Math.max(b.length * 1.1, 280) });
    setCamera('drone');
  }
  // A double-click on the scene moves the centre of the view there, keeping the angle.
  const ground = new THREE.Plane(new THREE.Vector3(0, 1, 0), -frame.top);
  const ray = new THREE.Raycaster();
  ctx.renderer.domElement.addEventListener('dblclick', (ev) => {
    const rect = ctx.renderer.domElement.getBoundingClientRect();
    ray.setFromCamera(new THREE.Vector2(((ev.clientX - rect.left) / rect.width) * 2 - 1, -((ev.clientY - rect.top) / rect.height) * 2 + 1), camera);
    const hit = ray.ray.intersectPlane(ground, new THREE.Vector3());
    if (!hit) return;
    const shift = hit.clone().sub(controls.target);
    controls.target.add(shift);
    camera.position.add(shift);
    Object.assign(spot, { x: hit.x, z: hit.z });
    if (cam !== 'free') setCamera('free', true);
    controls.update();
  });
  for (const b of overlay.querySelectorAll('[data-cam]')) {
    b.addEventListener('click', () => {
      if (b.dataset.cam === 'ship' && cam !== 'ship') prevCam = cam;
      setCamera(b.dataset.cam);
    });
  }
  // Following a ship (from her card, or the Ship camera) is the ship camera; when it stops (Esc,
  // Stop following, her call over) the camera before it comes back.
  view.addEventListener('mt-follow', (ev) => {
    if (ev.detail.on) {
      if (cam !== 'ship') prevCam = cam;
      shipName = ev.detail.name || '';
      setCamera('ship', true);
    } else if (!leaving) {
      shipName = '';
      // The free, quay and crane cameras are where they were (the twin put the view back); the
      // drone carries on circling.
      setCamera(prevCam === 'ship' ? 'drone' : prevCam, true);
    }
  });
  // Taking hold of the view leaves the drone to it.
  ctx.renderer.domElement.addEventListener('pointerdown', () => { if (cam === 'drone') setCamera('free', true); });
  setCamera('drone');

  // --- each frame --------------------------------------------------------------------------
  const player = { pace: 1, working: false, hs: 0.5, tick };
  let visualT = 0;
  let shownEvent = null;
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
    startFrame();
    const { alongside, moving, waiting, mooring } = placeShips(simH, tide);
    const states = w.hour.equipment;
    const working = !!alongside && states.some((s) => s.state === 'working');
    player.working = working;
    busy = placeOthers(simH, tide) + (alongside ? 1 : 0);
    endFrame();
    if (site.mainBerth) {
      site.mainBerth.state = alongside ? (simH < (alongside.from + LINES_IN + alongside.to) / 2 ? 'discharging' : 'loading') : null;
      site.mainBerth.shipKind = alongside ? alongside.mesh.userData.kind : null;
    }
    ctx.setPower(w.hour.power !== false);
    // An extreme event: its damage and the area it closes drawn on the model once it has struck.
    const struck = plan.scenario && plan.scenario.strikes_at != null && simH >= plan.scenario.strikes_at ? plan.scenario.key : null;
    if (struck !== shownEvent && ctx.showEvent) { shownEvent = struck; ctx.showEvent(struck); }
    for (const y of site.yards || []) ctx.setFill(y.mesh, ctx.yardFill(y.berth));
    workCranes(states, alongside, visualT, w);
    movePeople(dt * Math.min(pace, 4), alongside);
    weather(w, dt, pace);
    if (cam === 'drone') {
      droneAngle += dt * 0.025;
      const r = spot.r;
      camera.position.set(spot.x + r * Math.sin(droneAngle), frame.top + r * 0.55, spot.z - 20 - r * Math.cos(droneAngle) * 0.9);
      controls.target.set(spot.x, frame.top, spot.z);
    }
    if (performance.now() - lastText > 250) {
      lastText = performance.now();
      text(now, w, alongside, moving, waiting, states, mooring);
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

  function text(now, w, alongside, moving, waiting, states, mooring) {
    if (!panel.hidden) {
      for (const li of panel.querySelectorAll('li[data-n]')) {
        const b = allBerths.find((x) => String(x.n) === li.dataset.n);
        li.classList.toggle('is-busy', !!b.state);
        li.querySelector('.mt-b-now').textContent = berthNow(b, alongside, moving, waiting, mooring);
      }
    }
    const when = new Date(now);
    $('.mt-live-clock').textContent = when.toLocaleString([], { weekday: 'short', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', second: speed <= 10 ? '2-digit' : undefined });
    const chip = (label, value, bad) => `<span class="mt-chip${bad ? ' bad' : ''}"><small>${label}</small> ${value}</span>`;
    const L = plan.limits;
    let ship = 'Berth empty';
    if (alongside) ship = `${esc(alongside.name)} alongside · ${movesDone(alongside).toLocaleString()} of ${alongside.moves.toLocaleString()} ${esc(plan.units)}`;
    else if (mooring) ship = `${esc(mooring.c.name)} ${mooring.making ? `making fast, ${mooring.lines} of ${LINE_COUNT} lines` : `letting go, ${mooring.lines} lines still out`}`;
    else if (moving) ship = `${esc(moving.c.name)} ${movingWords(moving)}`;
    else if (waiting) {
      const due = new Date(realStart + waiting.from * 3600000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      ship = `${esc(waiting.name)} at anchor, ${waiting.held ? 'held by the weather' : 'due alongside ' + due}`;
    }
    $('.mt-live-state').innerHTML =
      (plan.scenario && plan.scenario.key !== 'normal' ? `<div class="small mt-live-scenario-words"><strong>${esc(plan.scenario.name)}</strong>: ${esc(plan.scenario.words)}</div>` : '') +
      `<div>${ship}</div>` +
      (others.length ? `<div class="small">${busy} of ${others.length + 1} berths with a ship alongside${anchored ? ` · ${anchored} more at anchor` : ''}</div>` : '') +
      (w.hour.power === false ? `<div class="small"><strong>Power cut</strong>: electric cranes stopped, yard lights out</div>` : '') +
      (w.hour.fog ? `<div class="small"><strong>Fog</strong>: no pilotage, ships held</div>` : '') +
      `<div class="mt-chips">${chip('wind', `${w.wind.toFixed(0)} m/s`, w.wind >= L.berthing_wind)}${chip('gusts', `${w.gust.toFixed(0)} m/s`, w.gust >= L.crane_stop_gust)}` +
      `${chip('waves', `${w.hs.toFixed(1)} m`, w.hs >= L.berthing_hs)}${chip('rain', w.rain > 0.05 ? `${w.rain.toFixed(1)} mm/h` : 'dry', w.rain > 4)}` +
      `${chip('tide', `${w.tide >= 0 ? '+' : ''}${w.tide.toFixed(2)} mCD`)}</div>` +
      `<div class="mt-chips">${states.map((s) => `<span class="mt-chip st-${s.state}" title="${esc(s.why)}">${esc(s.name)} ${esc(s.state)}</span>`).join('')}</div>`;
    // Lost time, said plainly.
    const idle = states.filter((s) => s.state !== 'working');
    let alert = '';
    if (alongside && idle.length) {
      alert = `Downtime: ${idle.map((s) => `${s.name} ${s.why || s.state}`).join('; ')}`;
    } else if (waiting && waiting.held && w.hour.fog) {
      alert = `Downtime: ${waiting.name} waiting at anchor, no pilotage in fog`;
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
