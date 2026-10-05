// MarineTwin berth plan (marine/berthplan.html): the week's ships on a radar, coming in from sea to
// the berth each is given, waiting at anchor when it is taken, and alongside; and the same plan as a
// timeline, berth by berth. Both follow the time slider; Play runs the week.
(() => {
  const root = document.querySelector('.mt-radar');
  if (!root) return;
  const canvas = root.querySelector('canvas');
  const g = canvas.getContext('2d');
  const slider = root.querySelector('input[type=range]');
  const timeLabel = root.querySelector('.mt-radar-time');
  const playBtn = root.querySelector('.mt-radar-play');
  const card = root.querySelector('.mt-radar-card');
  const gantt = document.querySelector('.mt-gantt');
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  const LINE_COLOURS = ['#4fc3f7', '#ffb74d', '#aed581', '#f06292', '#ba68c8', '#4db6ac', '#ffd54f', '#90a4ae', '#e57373', '#7986cb', '#a1887f', '#81c784'];
  const RANGE_H = 48;               // the outer ring: ships due within two days

  let plan = null;
  let t = 0;
  let playing = false;
  let picked = null;
  let sweep = 0;
  const lineColour = new Map();
  const colourOf = (line) => {
    if (!lineColour.has(line)) lineColour.set(line, LINE_COLOURS[lineColour.size % LINE_COLOURS.length]);
    return lineColour.get(line);
  };
  const flagImgs = new Map();
  const flagImg = (code) => {
    if (!flagImgs.has(code)) {
      const svg = plan.flags[code] || plan.flags[''];
      const img = new Image();
      if (svg) img.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg.replace('<svg ', '<svg xmlns="http://www.w3.org/2000/svg" '))}`;
      flagImgs.set(code, img);
    }
    return flagImgs.get(code);
  };
  const at = (h) => new Date(new Date(plan.start).getTime() + h * 3600e3);
  const when = (h) => { const d = at(h); return `${DAYS[d.getDay()]} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`; };
  const hours = (h) => (h < 1 ? 'none' : h < 48 ? `${Math.round(h)} h` : `${(h / 24).toFixed(1)} days`);

  // Where each berth sits round the inner ring, and where a ship is at time t.
  const berthAngle = (n) => {
    const i = plan.berths.findIndex((b) => b.n === n);
    return -Math.PI / 2 + ((i + 0.5) / plan.berths.length) * Math.PI * 2;
  };
  const jitter = (s) => { let h = 0; for (const ch of s) h = (h * 31 + ch.charCodeAt(0)) % 9973; return (h / 9973 - 0.5); };
  const stateOf = (c) => (t >= c.end_h ? 'gone' : t >= c.begin_h ? 'alongside' : t >= c.eta_h ? 'anchor' : t >= c.eta_h - RANGE_H ? 'coming' : 'far');

  function geometry() {
    const W = canvas.clientWidth;
    const H = canvas.clientHeight;
    const R = Math.min(W, H) / 2 - 18;
    return { W, H, cx: W / 2, cy: H / 2, R, r0: R * 0.2, r1: R * 0.36 };
  }
  function shipPos(c, geo) {
    const a = berthAngle(c.berth) + (c.berths.length > 1 ? (Math.PI / plan.berths.length) : 0);
    const s = stateOf(c);
    let r;
    let ang = a;
    if (s === 'alongside') r = geo.r0 + (geo.r1 - 6 - geo.r0) * 0.78;
    else if (s === 'anchor') { r = geo.r1 + 10; ang = a + jitter(c.ship + c.eta) * (Math.PI / plan.berths.length) * 0.9; }
    else { r = geo.r1 + 18 + ((c.eta_h - t) / RANGE_H) * (geo.R - geo.r1 - 18); ang = a + jitter(c.ship + c.eta) * 0.5; }
    return { x: geo.cx + Math.cos(ang) * r, y: geo.cy + Math.sin(ang) * r, s };
  }

  function draw() {
    if (!plan) return;
    const dpr = window.devicePixelRatio || 1;
    const W = canvas.clientWidth;
    const H = canvas.clientHeight;
    if (canvas.width !== Math.round(W * dpr)) { canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr); }
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    const geo = geometry();
    const { cx, cy, R, r0, r1 } = geo;
    g.fillStyle = '#04130d';
    g.fillRect(0, 0, W, H);
    // The rings: alongside, the anchorage, then hours to arrival.
    g.strokeStyle = 'rgba(80,220,140,.25)';
    g.fillStyle = 'rgba(120,230,160,.6)';
    g.font = '11px system-ui, sans-serif';
    g.lineWidth = 1;
    for (const h of [0, 6, 12, 24, 48]) {
      const r = h === 0 ? r1 : r1 + 18 + (h / RANGE_H) * (R - r1 - 18);
      g.beginPath(); g.arc(cx, cy, r, 0, Math.PI * 2); g.stroke();
      g.fillText(h === 0 ? 'anchorage' : `${h} h`, cx + 4, cy - r - 3);
    }
    for (let k = 0; k < 12; k++) {
      const a = (k / 12) * Math.PI * 2;
      g.beginPath(); g.moveTo(cx + Math.cos(a) * r1, cy + Math.sin(a) * r1); g.lineTo(cx + Math.cos(a) * R, cy + Math.sin(a) * R); g.stroke();
    }
    // The sweep.
    const grad = g.createConicGradient ? g.createConicGradient(sweep - 0.6, cx, cy) : null;
    if (grad) {
      grad.addColorStop(0, 'rgba(80,255,150,0)');
      grad.addColorStop(0.095, 'rgba(80,255,150,.22)');
      grad.addColorStop(0.0955, 'rgba(80,255,150,0)');
      g.fillStyle = grad;
      g.beginPath(); g.arc(cx, cy, R, 0, Math.PI * 2); g.fill();
    }
    // The berths round the inner ring, busy ones in the colour of the ship's line.
    const n = plan.berths.length;
    const span = (Math.PI * 2) / n;
    const busyAt = new Map();
    for (const c of plan.placed) if (stateOf(c) === 'alongside') for (const b of c.berths) busyAt.set(b, c);
    plan.berths.forEach((b, i) => {
      const a0 = -Math.PI / 2 + i * span + 0.03;
      const a1 = a0 + span - 0.06;
      const c = busyAt.get(b.n);
      g.beginPath(); g.arc(cx, cy, r1 - 6, a0, a1); g.arc(cx, cy, r0, a1, a0, true); g.closePath();
      g.fillStyle = c ? colourOf(c.line) + 'cc' : 'rgba(80,220,140,.12)';
      g.fill();
      g.strokeStyle = b.main ? '#fff' : 'rgba(80,220,140,.5)';
      g.stroke();
      const am = (a0 + a1) / 2;
      g.fillStyle = c ? '#04130d' : 'rgba(170,240,200,.9)';
      g.font = '600 11px system-ui, sans-serif';
      g.textAlign = 'center';
      g.textBaseline = 'middle';
      g.fillText(`B${b.n}`, cx + Math.cos(am) * (r0 + r1 - 6) / 2, cy + Math.sin(am) * (r0 + r1 - 6) / 2);
    });
    g.textAlign = 'left';
    g.textBaseline = 'alphabetic';
    g.fillStyle = 'rgba(170,240,200,.85)';
    g.font = '600 12px system-ui, sans-serif';
    g.textAlign = 'center';
    g.fillText('PORT', cx, cy + 4);
    g.textAlign = 'left';
    // The ships.
    for (const c of plan.placed) {
      const s = stateOf(c);
      if (s === 'gone' || s === 'far') continue;
      const p = shipPos(c, geo);
      c._p = p;
      const target = berthAngle(c.berth);
      if (s === 'coming' || s === 'anchor') {
        g.setLineDash([3, 4]);
        g.strokeStyle = s === 'anchor' ? 'rgba(255,193,7,.45)' : 'rgba(120,230,160,.3)';
        g.beginPath(); g.moveTo(p.x, p.y); g.lineTo(cx + Math.cos(target) * (r1 - 6), cy + Math.sin(target) * (r1 - 6)); g.stroke();
        g.setLineDash([]);
      }
      // Brighter just after the sweep has passed.
      const ang = (Math.atan2(p.y - cy, p.x - cx) + Math.PI * 2) % (Math.PI * 2);
      const behind = ((sweep % (Math.PI * 2)) - ang + Math.PI * 2) % (Math.PI * 2);
      const glow = Math.max(0.35, 1 - behind / (Math.PI * 1.6));
      g.globalAlpha = s === 'alongside' ? 1 : glow;
      const size = 4 + Math.min(5, c.loa / 70);
      g.fillStyle = s === 'anchor' ? '#ffc107' : colourOf(c.line);
      g.beginPath(); g.arc(p.x, p.y, size, 0, Math.PI * 2); g.fill();
      if (picked === c) { g.strokeStyle = '#fff'; g.lineWidth = 2; g.beginPath(); g.arc(p.x, p.y, size + 4, 0, Math.PI * 2); g.stroke(); g.lineWidth = 1; }
      const img = flagImg(c.flag || '');
      if (img.complete && img.naturalWidth) g.drawImage(img, p.x + size + 3, p.y - 13, 15, 10);
      if (s !== 'alongside' || picked === c) {
        // Ships alongside are named in the list beside; the radar keeps the berths readable.
        g.fillStyle = '#d8f5e3';
        g.font = '11px system-ui, sans-serif';
        g.fillText(c.ship, p.x + size + 3, p.y + 9);
      }
      g.globalAlpha = 1;
    }
    timeLabel.textContent = when(t);
  }

  function lists() {
    for (const ul of root.querySelectorAll('[data-list]')) {
      const kind = ul.dataset.list;
      const rows = plan.placed.filter((c) => stateOf(c) === kind || (kind === 'coming' && stateOf(c) === 'far'))
        .sort((a, b) => a.eta_h - b.eta_h).slice(0, kind === 'coming' ? 6 : 12);
      ul.innerHTML = rows.length ? rows.map((c) => `<li><button type="button" data-i="${plan.placed.indexOf(c)}">${plan.flags[c.flag || ''] || ''} <b>${esc(c.ship)}</b>
        <small>${kind === 'alongside' ? `${esc(c.berth_name)}, sails ${when(c.end_h)}` : kind === 'anchor' ? `for ${esc(c.berth_name)} at ${when(c.begin_h)}` : `${when(c.eta_h)} → ${esc(c.berth_name)}`}</small></button></li>`).join('')
        : '<li class="muted small">none</li>';
    }
  }

  function show(c) {
    picked = c;
    card.innerHTML = `<div class="mt-radar-ship">${plan.flags[c.flag || ''] || ''}<div><b>${esc(c.ship)}</b><small>${esc(c.flag_name)} flag · ${esc(c.type)} · ${esc(c.line || 'line not given')}</small></div></div>
      <dl class="mt-radar-dl">
        <dt>Size</dt><dd>${Math.round(c.loa)} m long${c.beam ? `, ${c.beam} m beam` : ''}, ${c.draught} m draught</dd>
        <dt>To work</dt><dd>${Number(c.moves).toLocaleString()} · ${c.hours} h alongside</dd>
        <dt>Arrives</dt><dd>${when(c.eta_h)}${c.window ? ' · contracted window' : ''}</dd>
        <dt>Berth</dt><dd><b>${esc(c.berth_name)}</b>, ${when(c.begin_h)} to ${when(c.end_h)}</dd>
        <dt>Waits</dt><dd>${hours(c.wait)} at anchor</dd>
        <dt>Why there</dt><dd>${esc(c.why)}</dd>
      </dl><a class="small" href="${root.dataset.ships}#call-${c.id || ''}">Change her details</a>`;
    draw();
  }

  function buildGantt() {
    if (!gantt) return;
    const H = plan.horizon;
    const days = Math.ceil(H / 24);
    const pct = (h) => `${(100 * h) / H}%`;
    gantt.innerHTML = `<div class="mt-g-head"><span></span><div>${Array.from({ length: days }, (_, d) => `<i style="left:${pct(d * 24)};width:${pct(24)}">${when(d * 24).slice(0, 3)} ${at(d * 24).getDate()}</i>`).join('')}</div></div>`
      + plan.berths.map((b) => `<div class="mt-g-row"><span>${esc(b.name)}<small>${Math.round(b.length)} m · ${b.depth} m</small></span><div>${plan.placed.filter((c) => c.berths.includes(b.n)).map((c) => `
        ${c.wait >= 0.5 ? `<i class="mt-g-wait" style="left:${pct(c.eta_h)};width:${pct(c.wait)}" title="${esc(c.ship)} waiting ${hours(c.wait)}"></i>` : ''}
        <button type="button" class="mt-g-bar" data-i="${plan.placed.indexOf(c)}" style="left:${pct(c.begin_h)};width:${pct(c.end_h - c.begin_h)};--c:${colourOf(c.line)}" title="${esc(c.ship)}: ${esc(c.why)}">${plan.flags[c.flag || ''] || ''}<span>${esc(c.ship)}</span></button>`).join('')}</div></div>`).join('')
      + '<div class="mt-g-now"></div>';
  }
  function moveNow() {
    const line = gantt && gantt.querySelector('.mt-g-now');
    if (!line) return;
    const row = gantt.querySelector('.mt-g-row > div');
    if (!row) return;
    const box = gantt.getBoundingClientRect();
    const r = row.getBoundingClientRect();
    line.style.left = `${r.left - box.left + (r.width * t) / plan.horizon}px`;
  }

  function setTime(h) {
    t = Math.max(0, Math.min(plan.horizon, h));
    slider.value = t;
    lists();
    moveNow();
    draw();
  }

  root.addEventListener('click', (ev) => {
    const btn = ev.target.closest('[data-i]');
    if (btn) { const c = plan.placed[Number(btn.dataset.i)]; setTime(c.begin_h <= t && t < c.end_h ? t : c.begin_h + 0.5); show(c); }
  });
  if (gantt) gantt.addEventListener('click', (ev) => {
    const btn = ev.target.closest('[data-i]');
    if (btn) { const c = plan.placed[Number(btn.dataset.i)]; setTime(c.begin_h + 0.5); show(c); root.scrollIntoView({ behavior: 'smooth', block: 'start' }); }
  });
  canvas.addEventListener('click', (ev) => {
    const r = canvas.getBoundingClientRect();
    const x = ev.clientX - r.left;
    const y = ev.clientY - r.top;
    let best = null;
    let bd = 18 * 18;
    for (const c of plan.placed) {
      if (!c._p || ['gone', 'far'].includes(stateOf(c))) continue;
      const d = (c._p.x - x) ** 2 + (c._p.y - y) ** 2;
      if (d < bd) { bd = d; best = c; }
    }
    if (best) show(best);
  });
  slider.addEventListener('input', () => setTime(Number(slider.value)));
  playBtn.addEventListener('click', () => {
    playing = !playing;
    playBtn.textContent = playing ? 'Pause' : 'Play';
    playBtn.setAttribute('aria-pressed', String(playing));
  });
  window.addEventListener('resize', () => { draw(); moveNow(); });

  let last = performance.now();
  let listTick = 0;
  function frame(now) {
    const dt = Math.min(0.1, (now - last) / 1000);
    last = now;
    sweep = (sweep + dt * 1.6) % (Math.PI * 2);
    if (playing && plan) {
      t += dt * 4;                    // four hours a second: the week in about 40 seconds
      if (t >= plan.horizon) { t = plan.horizon; playing = false; playBtn.textContent = 'Play'; }
      slider.value = t;
      if ((listTick += dt) > 0.5) { listTick = 0; lists(); }
      moveNow();
    }
    draw();
    requestAnimationFrame(frame);
  }

  fetch(root.dataset.plan, { credentials: 'same-origin' }).then((r) => r.json()).then((data) => {
    plan = data;
    slider.max = plan.horizon;
    buildGantt();
    setTime(Math.max(0, Math.min(plan.horizon, plan.now_h)));
    root.dataset.ready = '1';
    requestAnimationFrame(frame);
  });
})();
