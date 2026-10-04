// The lifecycle: the berth's whole design life played through the 3D twin in a few minutes.
//
// marinetwin.js builds the scene (the Revit model, the terminal, the sky and the sea) and hands it
// over here. The run itself comes from lifecycle.json (marine_life.py): month by month, the
// weather, each fender, wall bay, deck bay and bollard wearing, the issues they raise, the repairs
// and closures, and what the berth handled and lost. This plays it on the model: parts change
// colour as they wear, a warning floats over each issue, crews and barriers turn up where work
// is done or an area is closed, ships stop coming when the berth cannot take them.
//
// Three ways to watch: do nothing, fix as you go, or decide each issue yourself (the run stops
// and asks: fix it and pay, close the area and lose its share every day, or wait). Any run can be
// saved as a video: the view and its captions are drawn onto one canvas and recorded in the
// browser, MP4 where the browser can (Chrome, Edge, Safari), WebM otherwise.

const POLICIES = [['nothing', 'Do nothing'], ['fix', 'Fix as you go'], ['game', 'You decide']];
const PACES = [[120, '2 min'], [300, '5 min'], [600, '10 min']];     // seconds the whole design life takes
const DAY_SECONDS = 30;          // a day and a night on screen, whatever the pace: the light, not the calendar
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

const esc = (text) => String(text).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const big = (n) => (Math.abs(n) >= 1e6 ? `${(n / 1e6).toFixed(n >= 1e7 ? 1 : 2)}M` : Math.abs(n) >= 1e4 ? `${Math.round(n / 1e3)}k` : Math.round(n).toLocaleString());
// A part's state each month: worn 0-99, +1000 being repaired, +2000 closed off, +10000 × its open issue's stage.
const decode = (code) => {
  const rest = code % 10000;
  return { stage: Math.floor(code / 10000), closed: rest >= 2000, repairing: rest % 2000 >= 1000, worn: rest % 1000 };
};
const money = (usd) => (usd >= 1e9 ? `$${(usd / 1e9).toFixed(1)}B` : usd >= 1e6 ? `$${(usd / 1e6).toFixed(1)}M` : usd >= 1e3 ? `$${Math.round(usd / 1e3)}k` : `$${Math.round(usd)}`);

export async function startLife(ctx) {
  const { THREE, view, scene, camera, controls, renderer, frame, site, rng, focus, radius, water, sky, sunLight, hemi, REAL, twin } = ctx;
  const rates = JSON.parse(view.dataset.rates || '{}');
  const runs = {};                       // nothing and fix, fetched once; the game, again after each answer
  let choices = [];
  let policy = 'fix';
  let run = null;
  let simM = 0;
  let playing = true;
  let pace = 300;
  let asking = null;                     // the issue the game is asking about
  let endedAt = 0;

  async function fetchRun(p) {
    const answer = await fetch(view.dataset.life, {
      method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ policy: p, choices: p === 'game' ? choices : [], rates }),
    });
    if (!answer.ok) throw new Error(`the run could not be fetched (${answer.status})`);
    const r = await answer.json();
    // Running totals, for the captions.
    let handled = 0;
    let lost = 0;
    r.cumHandled = r.rows.map((row) => (handled += row[2]));
    r.cumLost = r.rows.map((row) => (lost += row[3]));
    return r;
  }
  runs.fix = await fetchRun('fix');
  run = runs.fix;
  fetchRun('nothing').then((r) => { runs.nothing = r; });
  const life = run.life;
  const total = run.months;
  const units = run.units;
  const value = run.rates.value_per_move;

  // --- the parts on the model ----------------------------------------------------------------
  const byRef = new Map();
  for (const m of ctx.clickable) {
    const e = m.userData.element;
    if (!e) continue;
    for (const key of new Set([e.ref, e.name])) {
      if (!byRef.has(key)) byRef.set(key, []);
      byRef.get(key).push(m);
    }
  }
  const spanX = frame.maxX - frame.minX || 50;
  const xAt = (f) => frame.minX + f * spanX;
  const fenderMat = REAL.rubber;
  const parts = run.parts.map((p, i) => {
    const meshes = [...new Set(p.refs.flatMap((r) => byRef.get(r) || []))];
    let x0 = xAt(p.at[0]);
    let x1 = xAt(p.at[1]);
    if (meshes.length && p.kind !== 'deck' && !(p.kind === 'wall' && meshes.length > 40)) {
      const b = new THREE.Box3();
      for (const m of meshes) b.expandByObject(m);
      x0 = b.min.x; x1 = b.max.x;
    }
    const part = { ...p, index: i, meshes, x0, x1, x: (x0 + x1) / 2, code: -1, flash: 0 };
    if (!meshes.length && p.kind === 'fender') {
      // No fenders in the model: one stands in on the quay face so there is something to wear out.
      const f = ctx.box(2.2, 2.6, 1.6, fenderMat, part.x, frame.top - 2.2, frame.fenderFace + 0.8);
      scene.add(f);
      part.meshes = [f];
      part.own = true;
    }
    if (!meshes.length && (p.kind === 'wall' || p.kind === 'deck')) {
      // Nor this bay: a band on the wall's face or the deck shows how it stands.
      const w = Math.max(x1 - x0 - 0.6, 2);
      const band = p.kind === 'wall'
        ? ctx.box(w, 3.2, 0.25, REAL.steel, part.x, frame.top - 3.4, frame.front + 0.15)
        : ctx.box(w, 0.08, 14, REAL.concrete, part.x, frame.top + 0.05, frame.front + 9);
      scene.add(band);
      part.meshes = [band];
      part.own = true;
    }
    part.z = p.kind === 'fender' ? frame.fenderFace : p.kind === 'wall' ? frame.front : p.kind === 'deck' ? frame.front + 9 : frame.front + 2;
    return part;
  });
  // A mesh shared by several parts (one deck slab followed in three bays) shows the worst of them.
  const meshParts = new Map();
  for (const p of parts) for (const m of p.meshes) {
    if (!meshParts.has(m)) meshParts.set(m, []);
    meshParts.get(m).push(p);
  }
  const asBuilt = { fender: REAL.rubber, wall: REAL.steel, deck: REAL.concrete, bollard: REAL.steel };
  const mats = new Map();
  function wearMaterial(code, kind) {
    const { worn, repairing, closed } = decode(code);
    let key;
    if (repairing) key = 'repair';
    else if (closed) key = 'closed';
    else if (worn < 22) return asBuilt[kind];
    else key = `w${Math.round(worn / 8)}`;
    if (!mats.has(key)) {
      let colour;
      if (key === 'repair') colour = new THREE.Color(0x2a9df4);
      else if (key === 'closed') colour = new THREE.Color(0x5b1010);
      else {
        const f = clamp((Math.round(worn / 8) * 8 - 22) / 70, 0, 1);
        colour = f < 0.5 ? new THREE.Color(0xe8c547).lerp(new THREE.Color(0xf08c1a), f * 2) : new THREE.Color(0xf08c1a).lerp(new THREE.Color(0xc62828), (f - 0.5) * 2);
      }
      mats.set(key, new THREE.MeshStandardMaterial({ color: colour, roughness: 0.75, metalness: kind === 'wall' ? 0.3 : 0.05,
        emissive: key === 'repair' ? 0x0b3d66 : 0x000000 }));
    }
    return mats.get(key);
  }
  const fresh = new THREE.MeshStandardMaterial({ color: 0x43d17a, emissive: 0x1c7a3d, roughness: 0.5 });
  const rank = (code) => { const d = decode(code); return (d.repairing ? 300 : 0) + (d.closed ? 200 : 0) + d.worn; };
  function paintParts(codes, force) {
    const now = performance.now();
    const touched = new Set();
    for (const p of parts) {
      const code = codes[p.index];
      if (code !== p.code || force || p.flash > now || p.flashed) {
        if (p.code >= 0 && decode(code).worn < decode(p.code).worn - 15 && !decode(code).repairing) p.flash = now + 1600;   // just renewed
        p.flashed = p.flash > now;
        p.code = code;
        for (const m of p.meshes) touched.add(m);
      }
    }
    for (const m of touched) {
      const ps = meshParts.get(m);
      const worst = ps.reduce((a, b) => (rank(b.code) > rank(a.code) ? b : a));
      m.material = worst.flash > now ? fresh : wearMaterial(worst.code, worst.kind);
    }
  }

  // --- what floats over the berth: warnings, crews, barriers ---------------------------------
  const labelCache = new Map();
  function label(text, colour) {
    const key = text + colour;
    if (labelCache.has(key)) return labelCache.get(key);
    const c = document.createElement('canvas');
    const g = c.getContext('2d');
    g.font = '600 30px system-ui, sans-serif';
    const w = Math.ceil(g.measureText(text).width) + 74;
    c.width = w; c.height = 52;
    g.font = '600 30px system-ui, sans-serif';
    g.fillStyle = 'rgba(10,18,28,.82)';
    g.beginPath(); g.roundRect(0, 0, w, 52, 12); g.fill();
    g.fillStyle = colour;
    g.beginPath(); g.arc(26, 26, 17, 0, 2 * Math.PI); g.fill();
    g.fillStyle = '#fff'; g.textAlign = 'center'; g.fillText('!', 26, 37);
    g.textAlign = 'left'; g.fillText(text, 52, 36);
    const tex = new THREE.CanvasTexture(c);
    tex.colorSpace = THREE.SRGBColorSpace;
    const out = { tex, aspect: w / 52 };
    labelCache.set(key, out);
    return out;
  }
  // Warnings keep their size on screen however far the drone is: they are what is being watched.
  const MARKER = 0.042;
  const markers = parts.map(() => {
    const s = new THREE.Sprite(new THREE.SpriteMaterial({ depthTest: false, transparent: true, sizeAttenuation: false }));
    s.renderOrder = 10;
    s.visible = false;
    scene.add(s);
    return s;
  });
  const stripe = (() => {
    const c = document.createElement('canvas');
    c.width = 64; c.height = 16;
    const g = c.getContext('2d');
    for (let i = 0; i < 8; i++) { g.fillStyle = i % 2 ? '#ffffff' : '#d32f2f'; g.beginPath(); g.moveTo(i * 8 - 8, 16); g.lineTo(i * 8, 0); g.lineTo(i * 8 + 8, 0); g.lineTo(i * 8, 16); g.fill(); }
    const t = new THREE.CanvasTexture(c);
    t.wrapS = THREE.RepeatWrapping;
    t.colorSpace = THREE.SRGBColorSpace;
    return t;
  })();
  const barriers = parts.map((p) => {
    const len = Math.max(p.x1 - p.x0, 6);
    const mat = new THREE.MeshStandardMaterial({ map: stripe.clone(), roughness: 0.6 });
    mat.map.repeat.set(len / 2, 1);
    mat.map.needsUpdate = true;
    const g = new THREE.Group();
    const rail = new THREE.Mesh(new THREE.BoxGeometry(len, 1.0, 0.3), mat);
    rail.position.y = 1.1;
    g.add(rail);
    for (const dx of [-len / 2, len / 2]) g.add(ctx.box(0.25, 1.4, 0.25, REAL.white, dx, 0.7, 0));
    g.position.set(p.x, frame.top, p.kind === 'deck' ? frame.front + 18 : frame.front + 3);
    g.visible = false;
    scene.add(g);
    return g;
  });
  const coneMat = new THREE.MeshStandardMaterial({ color: 0xff6d00, roughness: 0.5 });
  const crews = parts.map((p) => {
    const g = new THREE.Group();
    g.add(ctx.box(7, 2.2, 2.6, REAL.yellow, 0, 1.6, 0));          // the mobile crane's carrier
    const boom = ctx.box(0.6, 0.6, 12, REAL.yellow, 0, 6, -4);
    boom.rotation.x = 0.7;
    g.add(boom);
    for (const [dx, dz] of [[-6, -3], [6, -3], [-6, 3], [6, 3]]) {
      const c = new THREE.Mesh(new THREE.ConeGeometry(0.35, 0.9, 10), coneMat);
      c.position.set(dx, 0.45, dz);
      g.add(c);
    }
    g.position.set(p.x, frame.top, frame.front + (p.kind === 'deck' ? 10 : 6));
    g.visible = false;
    scene.add(g);
    return g;
  });

  // --- a ship when the berth can take one, the cranes, the rain ------------------------------
  const kind = site.kind;
  const s0 = twin.alongside || twin.next_ship || { type: 'Container', loa: 300, beam: 42, draught: 14 };
  const vessel = ctx.ship(s0.type, s0.loa, s0.beam, s0.draught, rng);
  vessel.traverse((m) => { if (m.isMesh) m.castShadow = true; });
  const berthX = (frame.minX + frame.maxX) / 2;
  vessel.position.set(berthX, 0, frame.fenderFace - s0.beam / 2 - 0.4);
  scene.add(vessel);
  // Ships come and go on screen (the calendar is far too fast to follow each call): in, alongside,
  // out, then the berth empty for a while so its face can be seen.
  const SHIP_CYCLE = 40;
  function shipAt(seconds) {
    const t = seconds % SHIP_CYCLE;
    const away = s0.loa * 1.6 + 150;
    if (t < 4) return berthX - away * (1 - t / 4) ** 2;
    if (t < 26) return berthX;
    if (t < 30) return berthX + away * ((t - 26) / 4) ** 2;
    return null;
  }
  const DROPS = 3500;
  const drops = new Float32Array(DROPS * 6);
  const box = { w: 700, h: 160, d: 500 };
  for (let i = 0; i < DROPS; i++) {
    const x = (rng() - 0.5) * box.w;
    const y = rng() * box.h;
    const z = (rng() - 0.5) * box.d;
    drops.set([x, y, z, x, y - 1.8, z], i * 6);
  }
  const rainGeo = new THREE.BufferGeometry();
  rainGeo.setAttribute('position', new THREE.BufferAttribute(drops, 3));
  const rain = new THREE.LineSegments(rainGeo, new THREE.LineBasicMaterial({ color: 0xaab8c8, transparent: true, opacity: 0.45 }));
  rain.frustumCulled = false;
  scene.add(rain);
  scene.fog = new THREE.Fog(0x9aa6b2, 900, 12000);
  const msl = twin.asset.msl_cd || 0;
  ctx.setTide((when) => msl + 0.9 * Math.sin((2 * Math.PI * when.getTime()) / (12.42 * 3600000)));

  // --- the screen: the controls in the page, the captions drawn so the video has them too ----
  const overlay = document.createElement('div');
  overlay.className = 'mt-live mt-life';
  overlay.innerHTML = `
    <canvas class="mt-life-hud" aria-hidden="true"></canvas>
    <div class="mt-life-card" role="dialog" aria-live="assertive" hidden></div>
    <div class="mt-live-bar">
      <span class="mt-live-cams mt-life-policies" role="group" aria-label="How the berth is looked after">${POLICIES.map(([k, l]) => `<button type="button" data-policy="${k}">${l}</button>`).join('')}</span>
      <button type="button" class="mt-live-play" aria-label="Pause">❚❚</button>
      <span class="mt-live-speeds" role="group" aria-label="How long the ${life} years take">${PACES.map(([s, l]) => `<button type="button" data-pace="${s}">${l}</button>`).join('')}</span>
      <span class="mt-live-track"><input type="range" class="mt-live-scrub" min="0" max="${total}" step="0.1" aria-label="Year of the design life"></span>
      <button type="button" class="mt-life-rec" title="Plays the run from the start and saves it as a video">● Save as video</button>
    </div>`;
  view.appendChild(overlay);
  const $ = (sel) => overlay.querySelector(sel);
  const hudCanvas = $('.mt-life-hud');
  const hud = hudCanvas.getContext('2d');
  const scrub = $('.mt-live-scrub');
  const card = $('.mt-life-card');
  const recButton = $('.mt-life-rec');
  const ticks = document.createElement('div');
  ticks.className = 'mt-live-ticks';
  scrub.insertAdjacentElement('afterend', ticks);
  function drawTicks() {
    ticks.innerHTML = run.events.filter((e) => ['critical', 'fix', 'condemned', 'close'].includes(e.kind)).map((e) =>
      `<i class="k-${e.kind === 'fix' ? 'good' : e.kind === 'close' ? 'warning' : 'critical'}" style="left:${(100 * e.m) / total}%" title="${esc(e.text)}"></i>`).join('');
  }

  function setPace(s) {
    pace = s;
    for (const b of overlay.querySelectorAll('[data-pace]')) b.setAttribute('aria-pressed', String(Number(b.dataset.pace) === s));
  }
  function setPlaying(on) {
    playing = on;
    $('.mt-live-play').textContent = on ? '❚❚' : '▶';
    $('.mt-live-play').setAttribute('aria-label', on ? 'Pause' : 'Play');
  }
  async function setPolicy(p) {
    policy = p;
    for (const b of overlay.querySelectorAll('[data-policy]')) b.setAttribute('aria-pressed', String(b.dataset.policy === p));
    card.hidden = true;
    asking = null;
    if (p === 'game') {
      choices = [];
      runs.game = await fetchRun('game');
    } else if (!runs[p]) {
      runs[p] = await fetchRun(p);
    }
    run = runs[p];
    restart();
  }
  function restart() {
    simM = 0;
    endedAt = 0;
    shownEvents = -1;
    for (const p of parts) { p.code = -1; p.flash = 0; }
    banner = null;
    drawTicks();
    setPlaying(true);
  }
  for (const b of overlay.querySelectorAll('[data-policy]')) b.addEventListener('click', () => { if (!recording) setPolicy(b.dataset.policy); });
  for (const b of overlay.querySelectorAll('[data-pace]')) b.addEventListener('click', () => setPace(Number(b.dataset.pace)));
  $('.mt-live-play').addEventListener('click', () => { if (simM >= total) restart(); else setPlaying(!playing); });
  scrub.addEventListener('input', () => {
    // In a game the future is not written yet: only what has been played can be gone back to.
    simM = clamp(Number(scrub.value), 0, Math.max(run.done - 0.01, 0));
    shownEvents = -1;
    endedAt = 0;
  });
  setPace(300);

  // --- the game: an issue, three answers -------------------------------------------------------
  function ask(issue) {
    asking = issue;
    setPlaying(false);
    if (recording && recording.rec.state === 'recording') recording.rec.pause();
    const o = issue.options;
    const year = Math.floor(issue.m / 12) + 1;
    const worse = o.wait.next ? `It keeps going until it is ${esc(o.wait.next)}.` : 'It stays as it is.';
    card.innerHTML = `
      <p class="mt-life-card-year">Year ${year} · ${MONTHS[issue.m % 12]} ${run.start_year + Math.floor(issue.m / 12)}</p>
      <h3><span class="badge ${issue.stage >= 2 ? 'critical' : 'warning'}">${issue.stage >= 2 ? 'Act' : 'Watch'}</span> ${esc(issue.name)} is ${esc(issue.state)}</h3>
      <p>${esc(issue.text)}</p>
      <div class="mt-life-choices">
        <button type="button" data-act="fix"><b>Fix it and pay</b><small>${esc(o.fix.what)}: ${money(o.fix.price)} = ${o.fix.price_moves.toLocaleString()} ${units}, and ${o.fix.days} days of this part out (${o.fix.lost_moves.toLocaleString()} ${units})</small></button>
        <button type="button" data-act="close"><b>Close the area</b><small>Nothing to pay now; −${Math.round(o.close.per_day).toLocaleString()} ${units} every day until it is fixed</small></button>
        <button type="button" data-act="wait"><b>Wait</b><small>${o.wait.per_day ? `Already costing ${Math.round(o.wait.per_day).toLocaleString()} ${units} a day. ` : 'Nothing lost yet. '}${worse}</small></button>
      </div>`;
    card.hidden = false;
    for (const b of card.querySelectorAll('[data-act]')) b.addEventListener('click', () => answer(issue, b.dataset.act));
    card.querySelector('[data-act]').focus({ preventScroll: true });
  }
  async function answer(issue, act) {
    card.hidden = true;
    choices.push([issue.id, act, issue.m]);
    runs.game = await fetchRun('game');
    run = runs.game;
    asking = null;
    drawTicks();
    say(act === 'fix' ? `${issue.name}: fixed. Paid ${money(issue.options.fix.price)}` : act === 'close' ? `${issue.name}: closed off` : `${issue.name}: left for now`,
      act === 'fix' ? '#43d17a' : act === 'close' ? '#ff8a65' : '#ffd54f');
    if (recording && recording.rec.state === 'paused') recording.rec.resume();
    setPlaying(true);
  }
  // Fix (or close) later something left open: from the month after the one showing, so nothing seen changes.
  async function later(issueId, act) {
    if (policy !== 'game') return;
    const m = Math.min(Math.floor(simM) + 1, run.done);
    choices.push([issueId, act, m]);
    runs.game = await fetchRun('game');
    run = runs.game;
    drawTicks();
    refreshLists(true);
  }

  // --- the captions ----------------------------------------------------------------------------
  let banner = null;
  function say(text, colour) { banner = { text, colour, at: performance.now() }; }
  function at(month) {
    const i = clamp(Math.floor(month), 0, Math.max(run.rows.length - 1, 0));
    return { i, row: run.rows[i], w: run.weather[i], handled: run.cumHandled[i] || 0, lost: run.cumLost[i] || 0 };
  }
  function drawHud(g, W, H, scale) {
    g.clearRect(0, 0, W, H);
    if (!run.rows.length) return;
    const s = scale;
    const { i, row, w, handled, lost } = at(simM);
    const year = simM / 12;
    const spend = row[5];
    const cost = lost + spend / value;
    const panel = (x, y, w2, h2) => { g.fillStyle = 'rgba(10,18,28,.74)'; g.beginPath(); g.roundRect(x, y, w2, h2, 10 * s); g.fill(); };
    g.textBaseline = 'alphabetic';
    // Top left: the year, the way it is looked after, the design life used.
    panel(12 * s, 12 * s, 300 * s, 112 * s);
    g.fillStyle = '#fff';
    g.font = `700 ${34 * s}px system-ui, sans-serif`;
    g.fillText(`YEAR ${Math.min(Math.floor(year) + 1, life)}`, 26 * s, 52 * s);
    g.font = `500 ${14 * s}px system-ui, sans-serif`;
    g.fillStyle = '#cfd8e3';
    g.fillText(`${MONTHS[i % 12]} ${run.start_year + Math.floor(i / 12)} · ${POLICIES.find(([k]) => k === policy)[1]}`, 26 * s, 74 * s);
    const bw = 270 * s;
    g.fillStyle = 'rgba(255,255,255,.18)';
    g.fillRect(26 * s, 88 * s, bw, 8 * s);
    g.fillStyle = row[1] === 0 && run.totals.condemned_year !== null && simM >= run.totals.condemned_year * 12 ? '#e53935' : '#64b5f6';
    g.fillRect(26 * s, 88 * s, bw * clamp(year / life, 0, 1), 8 * s);
    g.fillStyle = '#cfd8e3';
    g.font = `${12 * s}px system-ui, sans-serif`;
    g.fillText(`design life ${life} years`, 26 * s, 114 * s);
    if (w) {
      const words = [w.storm === 2 ? 'GREAT STORM' : w.storm ? 'storm' : w.rain > 3 ? 'rain' : 'fair', `wind ${Math.round(w.wind)} m/s`, `${Math.round(w.temp)} °C`];
      g.textAlign = 'right';
      g.fillText(words.join(' · '), 296 * s, 114 * s);
      g.textAlign = 'left';
    }
    // Top right: the berth's account.
    const rx = W - 312 * s;
    panel(rx, 12 * s, 300 * s, 176 * s);
    const lineAt = (n, k, v, colour, bold) => {
      const y = (40 + n * 24) * s;
      g.font = `${bold ? 700 : 400} ${13.5 * s}px system-ui, sans-serif`;
      g.fillStyle = '#cfd8e3';
      g.fillText(k, rx + 14 * s, y);
      g.textAlign = 'right';
      g.fillStyle = colour || '#fff';
      g.fillText(v, rx + 286 * s, y);
      g.textAlign = 'left';
    };
    const factor = row[1];
    lineAt(0, 'Berth working', `${Math.round(factor * 100)}%`, factor > 0.95 ? '#81c784' : factor > 0.7 ? '#ffd54f' : '#ff7043', true);
    lineAt(1, `${units[0].toUpperCase() + units.slice(1)} handled`, big(handled));
    lineAt(2, 'Lost to issues', `${big(lost)} ${units}`, lost > 0 ? '#ff8a65' : '#fff');
    lineAt(3, 'Repairs', `${money(spend)} = ${big(spend / value)} ${units}`);
    lineAt(4, 'Cost so far', `${big(cost)} ${units}`, '#fff', true);
    lineAt(5, '', `≈ ${money(cost * value)}`, '#cfd8e3');
    const other = policy === 'nothing' ? runs.fix : runs.nothing;
    if (other && other.rows.length) {
      const j = clamp(i, 0, other.rows.length - 1);
      const oc = other.cumLost[j] + other.rows[j][5] / value;
      g.font = `${12 * s}px system-ui, sans-serif`;
      g.fillStyle = Math.abs(oc - cost) < 1 ? '#cfd8e3' : oc > cost ? '#81c784' : '#ff8a65';
      g.fillText(`${policy === 'nothing' ? 'Fixing as you go' : 'Doing nothing'}, by now: ${big(oc)} ${units}`, rx + 14 * s, 180 * s);
    }
    // Lower left: the last few things that happened.
    const recent = run.events.filter((e) => e.m <= i && e.kind !== 'wait').slice(-4);
    const colourOf = { warning: '#ffd54f', critical: '#ff7043', fix: '#81c784', close: '#ff8a65', condemned: '#e53935', weather: '#90caf9', info: '#90caf9' };
    g.font = `${13 * s}px system-ui, sans-serif`;
    recent.forEach((e, n) => {
      const y = H - (78 + (recent.length - 1 - n) * 22) * s;
      const text = `Y${Math.floor(e.m / 12) + 1}  ${e.text}`;
      const tw = Math.min(g.measureText(text).width, W * 0.62);
      g.fillStyle = 'rgba(10,18,28,.66)';
      g.fillRect(12 * s, y - 15 * s, tw + 20 * s, 20 * s);
      g.fillStyle = colourOf[e.kind] || '#fff';
      g.fillRect(12 * s, y - 15 * s, 3 * s, 20 * s);
      g.fillStyle = '#fff';
      g.save(); g.beginPath(); g.rect(12 * s, y - 15 * s, tw + 16 * s, 20 * s); g.clip();
      g.fillText(text, 22 * s, y);
      g.restore();
    });
    // The banner: what just happened, big.
    if (banner) {
      const age = (performance.now() - banner.at) / 1000;
      if (age > 3.2) banner = null;
      else {
        g.globalAlpha = clamp(Math.min(age * 4, (3.2 - age) * 2), 0, 1);
        g.font = `700 ${22 * s}px system-ui, sans-serif`;
        const tw = g.measureText(banner.text).width;
        g.fillStyle = 'rgba(10,18,28,.84)';
        g.beginPath(); g.roundRect(W / 2 - tw / 2 - 20 * s, 132 * s, tw + 40 * s, 44 * s, 10 * s); g.fill();
        g.fillStyle = banner.colour;
        g.textAlign = 'center';
        g.fillText(banner.text, W / 2, 162 * s);
        g.textAlign = 'left';
        g.globalAlpha = 1;
      }
    }
    // At the end: what the run came to.
    if (run.finished && simM >= total - 0.01) {
      const t = run.totals;
      const lines = [
        `${life} years, ${POLICIES.find(([k]) => k === policy)[1].toLowerCase()}`,
        `Cost ${big(t.cost_moves)} ${units} ≈ ${money(t.cost)}`,
        t.condemned_year !== null ? `Berth out of service in year ${Math.round(t.condemned_year)}` : `Service life ${t.service_life >= 100 ? 'over 100' : Math.round(t.service_life)} years`,
      ];
      const ow = 460 * s;
      panel(W / 2 - ow / 2, H / 2 - 70 * s, ow, 128 * s);
      g.textAlign = 'center';
      g.fillStyle = '#fff';
      g.font = `700 ${22 * s}px system-ui, sans-serif`;
      g.fillText(lines[0], W / 2, H / 2 - 34 * s);
      g.font = `500 ${18 * s}px system-ui, sans-serif`;
      g.fillText(lines[1], W / 2, H / 2 - 4 * s);
      g.fillStyle = t.condemned_year !== null ? '#ff7043' : '#81c784';
      g.fillText(lines[2], W / 2, H / 2 + 26 * s);
      g.textAlign = 'left';
    }
  }
  function sizeHud() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    hudCanvas.width = Math.round(view.clientWidth * dpr);
    hudCanvas.height = Math.round(view.clientHeight * dpr);
  }
  sizeHud();
  window.addEventListener('resize', sizeHud);

  // --- the lists under the view ----------------------------------------------------------------
  const log = document.querySelector('.mt-life-log');
  const openList = document.querySelector('.mt-life-open');
  let shownEvents = -1;
  function openNow(month) {
    const open = new Map();
    for (const e of run.events) {
      if (e.m > month) break;
      if (e.issue && (e.kind === 'warning' || e.kind === 'critical')) open.set(e.part, { id: e.issue, text: e.text, m: e.m, closed: false });
      else if (e.kind === 'fix') open.delete(e.part);
      else if (e.kind === 'close' && open.has(e.part)) open.get(e.part).closed = true;
    }
    return [...open.values()];
  }
  function refreshLists(force) {
    const i = Math.floor(simM);
    const upTo = run.events.filter((e) => e.m <= i);
    if (!force && upTo.length === shownEvents) return;
    shownEvents = upTo.length;
    const cls = { fix: 'good', close: 'critical', condemned: 'critical', weather: 'info', info: 'info', wait: 'info' };
    if (log) {
      log.innerHTML = upTo.length ? upTo.slice(-14).reverse().map((e, n) =>
        `<li class="k-${cls[e.kind] || e.kind}" data-m="${e.m}"><time>Year ${Math.floor(e.m / 12) + 1}</time> ${esc(e.text)}</li>`).join('')
        : '<li class="muted">Nothing yet: a new berth.</li>';
      for (const li of log.querySelectorAll('li[data-m]')) li.addEventListener('click', () => { simM = Number(li.dataset.m); shownEvents = -1; });
    }
    if (openList) {
      const open = openNow(i);
      if (policy !== 'game') {
        openList.innerHTML = `<li class="muted">Pick “You decide” on the video to choose for yourself. ${open.length ? `${open.length} issue${open.length > 1 ? 's' : ''} open in this run now.` : ''}</li>`;
      } else {
        openList.innerHTML = open.length ? open.map((o) => `<li><span class="badge ${o.closed ? 'critical' : 'warning'}">${o.closed ? 'Closed' : 'Waiting'}</span> ${esc(o.text)}
            <button type="button" class="btn btn-sm" data-fix="${esc(o.id)}">Fix it now</button>
            ${o.closed ? '' : `<button type="button" class="btn btn-sm btn-ghost" data-close="${esc(o.id)}">Close it</button>`}</li>`).join('')
          : '<li class="muted">Nothing left open.</li>';
        for (const b of openList.querySelectorAll('[data-fix]')) b.addEventListener('click', () => later(b.dataset.fix, 'fix'));
        for (const b of openList.querySelectorAll('[data-close]')) b.addEventListener('click', () => later(b.dataset.close, 'close'));
      }
    }
  }

  // --- saving a video --------------------------------------------------------------------------
  let recording = null;
  const TYPES = ['video/mp4;codecs=avc1.42E01E', 'video/mp4;codecs=avc1', 'video/mp4', 'video/webm;codecs=vp9', 'video/webm'];
  function startRecording() {
    const type = window.MediaRecorder && TYPES.find((t) => MediaRecorder.isTypeSupported(t));
    if (!type) { say('This browser cannot record video', '#ff7043'); return; }
    const out = document.createElement('canvas');
    out.width = 1280; out.height = 720;
    const g = out.getContext('2d');
    const extra = document.createElement('canvas');
    extra.width = out.width; extra.height = out.height;
    const rec = new MediaRecorder(out.captureStream(30), { mimeType: type, videoBitsPerSecond: 8_000_000 });
    const chunks = [];
    rec.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
    rec.onstop = () => {
      const blob = new Blob(chunks, { type: type.split(';')[0] });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = `${view.dataset.file || 'berth'}-${policy === 'game' ? 'your-choices' : policy === 'fix' ? 'fix-as-you-go' : 'do-nothing'}-${life}-years.${type.startsWith('video/mp4') ? 'mp4' : 'webm'}`;
      document.body.appendChild(a);
      a.click();
      setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 4000);
      say(type.startsWith('video/mp4') ? 'Video saved (MP4)' : 'Video saved (WebM: this browser does not record MP4)', '#81c784');
    };
    recording = { rec, out, g, hud: extra.getContext('2d'), type };
    if (policy === 'game') { choices = []; fetchRun('game').then((r) => { runs.game = r; run = r; restart(); rec.start(1000); }); }
    else { restart(); rec.start(1000); }
    recButton.textContent = '■ Stop and save';
    overlay.classList.add('recording');
  }
  function stopRecording() {
    if (!recording) return;
    if (recording.rec.state !== 'inactive') recording.rec.stop();
    recording = null;
    recButton.textContent = '● Save as video';
    overlay.classList.remove('recording');
  }
  recButton.addEventListener('click', () => (recording ? stopRecording() : startRecording()));
  function composite() {
    const { g, out } = recording;
    const src = renderer.domElement;
    // The view, cropped to 16:9, then the captions over it at the video's size.
    const want = out.width / out.height;
    let sw = src.width;
    let sh = src.height;
    if (sw / sh > want) sw = sh * want; else sh = sw / want;
    g.drawImage(src, (src.width - sw) / 2, (src.height - sh) / 2, sw, sh, 0, 0, out.width, out.height);
    drawHud(recording.hud, out.width, out.height, out.height / 620);
    g.drawImage(recording.hud.canvas, 0, 0);
  }

  // --- each frame ------------------------------------------------------------------------------
  const player = { pace: 1, working: true, hs: 0.5, tick };
  let lastReal = performance.now();
  let lastPaint = 0;
  let lastText = 0;
  let lastClock = 0;
  let visualT = 0;
  let droneAngle = 0;
  let free = false;
  renderer.domElement.addEventListener('pointerdown', () => { free = true; });
  function tick(dt) {
    const real = Math.min((performance.now() - lastReal) / 1000, 0.25);
    lastReal = performance.now();
    if (playing && !asking) {
      simM += (real * total) / pace;
      if (simM >= run.done && !run.finished) {
        simM = run.done;
        if (run.pending.length) ask(run.pending[0]);
      } else if (simM >= total) {
        simM = total;
        if (!endedAt) endedAt = performance.now();
        if (recording && performance.now() - endedAt > 3500) stopRecording();
        if (!recording && performance.now() - endedAt > 50) setPlaying(false);
      }
    }
    const { i, row, w } = at(simM);
    if (!row) return;
    const factor = row[1];
    const condemned = run.totals.condemned_year !== null && i >= Math.round(run.totals.condemned_year * 12);
    const stormy = w && w.storm > 0 && (simM % 1) < Math.min(w.storm_days / 30, 1);
    player.pace = playing ? 1 + 3 * factor : 0;
    player.working = factor > 0.05 && !condemned && !stormy;
    visualT += dt * player.pace;

    // The month's parts, a few times a second (and at once when a fix lands).
    const codes = run.states[i];
    if (performance.now() - lastPaint > 150) {
      paintParts(codes, performance.now() - lastPaint > 600);
      lastPaint = performance.now();
      parts.forEach((p, n) => {
        const code = codes[n];
        const { stage, repairing, closed } = decode(code);
        const mk = markers[n];
        mk.visible = stage > 0 && !repairing;
        if (mk.visible) {
          const names = { fender: ['', 'worn', 'damaged', 'failed'], wall: ['', 'corroding', 'over allowance', 'unsafe'], deck: ['', 'cracking', 'spalling', 'delaminated'], bollard: ['', '', '', 'cracked'] };
          const l = label(`${p.name} ${names[p.kind][stage]}${closed ? ' · closed' : ''}`, stage >= 2 ? '#e53935' : '#f9a825');
          if (mk.material.map !== l.tex) { mk.material.map = l.tex; mk.material.needsUpdate = true; }
          mk.scale.set(MARKER * l.aspect, MARKER, 1);
          mk.position.set(p.x, frame.top + 4 + (n % 4) * Math.max(3, spanX / 22), p.z + (p.kind === 'deck' ? 4 : 0));
        }
        barriers[n].visible = closed || (stage >= 3 && p.kind !== 'fender' && !repairing) || condemned;
        crews[n].visible = repairing;
        if (repairing) crews[n].children[1].rotation.y = Math.sin(visualT * 0.5 + n);
      });
    }
    // A ship while the berth can take one; the cranes work it.
    const sx = shipAt(performance.now() / 1000);
    vessel.visible = player.working && factor > 0.3 && sx !== null;
    if (sx !== null) vessel.position.x = sx;
    vessel.position.y = water.position.y;
    vessel.rotation.x = 0.004 * Math.sin(visualT * 0.6);
    site.cranes.forEach((c, n) => {
      const u = c.userData;
      if (u.boom) {
        const up = condemned ? -1.25 : 0;
        u.boom.rotation.x += (up - u.boom.rotation.x) * 0.1;
      }
      if (u.trolley && player.working && vessel.visible) {
        const s = (Math.sin(visualT * 0.35 + c.position.x) + 1) / 2;
        u.trolley.position.z = -28 + 40 * s;
        u.spreader.position.y = -10 - 22 * Math.abs(Math.sin(visualT * 0.7 + c.position.x));
      }
      if (u.top && player.working && vessel.visible) u.top.rotation.y = 0.9 * Math.sin(visualT * 0.18 + c.position.x + n);
    });

    // The weather of the month, and a day going by on screen whatever the calendar's pace.
    if (w) {
      const wet = clamp(w.rain / 7 + (stormy ? 0.6 : 0), 0, 1);
      rain.visible = wet > 0.25;
      rainGeo.setDrawRange(0, Math.round(DROPS * wet) * 2);
      if (rain.visible) {
        const fall = 9 * dt * 3;
        const drift = w.wind * 0.12 * dt * 3;
        for (let k = 0; k < DROPS * 6; k += 6) {
          drops[k + 1] -= fall; drops[k + 4] -= fall; drops[k] += drift; drops[k + 3] += drift * 1.4;
          if (drops[k + 1] < 0) { drops[k + 1] += box.h; drops[k + 4] = drops[k + 1] - 1.8; drops[k + 3] = drops[k]; }
          if (drops[k] > box.w / 2) { drops[k] -= box.w; drops[k + 3] -= box.w; }
        }
        rainGeo.attributes.position.needsUpdate = true;
        rain.position.set(controls.target.x, frame.top, controls.target.z);
      }
      sky.material.uniforms.turbidity.value = 3 + 14 * wet;
      sky.material.uniforms.rayleigh.value = 1.6 - 1.2 * wet;
      water.material.uniforms.distortionScale.value = 1.2 + (stormy ? 6 : w.wind / 6);
      player.hs = stormy ? 2.5 : 0.4 + w.wind / 25;
      scene.fog.far = stormy ? 1600 : 9000 - 5000 * wet;
      scene.fog.near = Math.min(scene.fog.far * 0.3, 900);
      if (performance.now() - lastClock > 120) {
        // A day on screen is mostly daylight with a short night: the berth is what is being watched.
        const phase = (performance.now() / 1000 / DAY_SECONDS) % 1;
        const hour = phase < 0.88 ? 6.5 + (13 * phase) / 0.88 : 19.5 + (11 * (phase - 0.88)) / 0.12;
        const yearNow = run.start_year + Math.floor(i / 12);
        ctx.setClock(Date.UTC(yearNow, i % 12, 15) + (hour - (twin.asset.longitude || 0) / 15) * 3600000);
        sunLight.intensity *= 1 - 0.6 * wet;                        // the sun's light for the hour, dimmed by the cloud
        hemi.intensity *= 1 - 0.3 * wet;
        lastClock = performance.now();
      }
    }
    if (!free) {
      // A drone swinging to and fro over the water, looking at the quay face and the deck behind it.
      droneAngle += dt * 0.05;
      const r = clamp(spanX * 1.05, 120, 900);
      const a = 0.95 * Math.sin(droneAngle);
      camera.position.set(berthX + r * Math.sin(a) * 0.9, frame.top + r * 0.5, frame.fenderFace - r * Math.cos(a) * 0.8);
      controls.target.set((frame.minX + frame.maxX) / 2, frame.top, frame.front + 6);
    }
    // Captions and lists.
    drawHud(hud, hudCanvas.width, hudCanvas.height, hudCanvas.height / 620);
    if (recording && recording.rec.state === 'recording') composite();
    if (performance.now() - lastText > 250) {
      lastText = performance.now();
      if (!scrub.matches(':active')) scrub.value = String(simM);
      // Banners for what just happened.
      for (const e of run.events) {
        if (e.m !== i || e.bannered === run) continue;
        e.bannered = run;
        if (e.kind === 'condemned') say('BERTH OUT OF SERVICE: the front wall is no longer safe', '#ff5252');
        else if (e.kind === 'fix' && policy !== 'game') say(e.text.split('. Paid')[0] + ` · ${money(e.cost)}`, '#81c784');
        else if (e.kind === 'critical' && policy === 'nothing') say(e.text.split('. ')[0], '#ff7043');
        else if (e.kind === 'weather') say('Great storm: berth stopped', '#90caf9');
      }
      refreshLists(false);
    }
  }

  setPolicy('fix');
  ctx.setMoving(true);
  return player;
}
