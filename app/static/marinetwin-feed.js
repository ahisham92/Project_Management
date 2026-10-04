// MarineTwin's Real sensors page: copy buttons, a fake logger, and the live list of what arrives.
//
// The fake logger plays the part of the logger in the quay's cabinet. It sends through the same
// address, with the same key, that a real one would, so what it shows working is the real door:
// first the last 24 hours it "kept", then one reading per sensor every few seconds.

(function () {
  const config = JSON.parse(document.getElementById('mt-feed-config').textContent);

  document.querySelectorAll('[data-copy]').forEach((button) => {
    button.addEventListener('click', () => {
      const field = document.getElementById(button.dataset.copy);
      field.select();
      (navigator.clipboard ? navigator.clipboard.writeText(field.value) : Promise.reject())
        .catch(() => document.execCommand('copy'))
        .finally(() => { button.textContent = 'Copied'; setTimeout(() => { button.textContent = 'Copy'; }, 1500); });
    });
  });

  // --- the live list --------------------------------------------------------------------------
  const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const sensorsBody = document.getElementById('mt-feed-sensors');
  const deliveriesBody = document.getElementById('mt-feed-deliveries');
  const when = document.getElementById('mt-feed-when');
  const elementUrl = (id) => config.element.replace(/\/0$/, '/' + id);

  async function refresh() {
    try {
      const answer = await fetch(config.status, { headers: { Accept: 'application/json' }, credentials: 'same-origin' });
      if (!answer.ok) return;
      const feed = await answer.json();
      sensorsBody.innerHTML = feed.fed.length ? feed.fed.map((s) => `<tr>
        <td><a href="${esc(elementUrl(s.element_id))}"><strong>${esc(s.label)}</strong></a></td>
        <td class="small">${esc(s.kind_name)}</td>
        <td class="right tabular">${esc(s.latest)} <span class="small muted">${esc(s.unit)}</span></td>
        <td class="small tabular">${esc(String(s.latest_at || '').replace('T', ' '))}</td>
        <td class="right tabular">${esc(s.count)}</td><td class="small">${esc(s.feed_device)}</td></tr>`).join('')
        : '<tr><td colspan="6" class="muted">No logger has sent anything yet.</td></tr>';
      deliveriesBody.innerHTML = feed.deliveries.length ? feed.deliveries.map((d) => `<tr>
        <td class="small tabular">${esc(d.at.replace('T', ' '))}</td><td class="small">${esc(d.device || '—')}</td>
        <td class="right tabular">${esc(d.written)}</td>
        <td class="small ${d.problems ? 'state-warning' : ''}">${d.problems ? esc(d.first_problem) + (d.problems > 1 ? ` (+${d.problems - 1} more)` : '') : '—'}</td></tr>`).join('')
        : '<tr><td colspan="4" class="muted">None yet.</td></tr>';
      when.textContent = `Refreshes every few seconds. Last checked ${new Date().toLocaleTimeString()}.`;
    } catch (e) { /* the next look will do */ }
  }
  if (sensorsBody) setInterval(refresh, 4000);

  // --- the fake logger ------------------------------------------------------------------------
  const start = document.getElementById('mt-fake-start');
  if (!start) return;
  const stop = document.getElementById('mt-fake-stop');
  const alarm = document.getElementById('mt-fake-alarm');
  const out = document.getElementById('mt-fake-log');
  const channels = config.channels;
  const last = Object.fromEntries(channels.map((c) => [c.sensor, c.start]));
  let timer = null;
  let pending = [];

  const pad = (n) => String(n).padStart(2, '0');
  const stamp = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  const gauss = () => Math.sqrt(-2 * Math.log(1 - Math.random())) * Math.cos(2 * Math.PI * Math.random());
  const round = (v) => Math.round(v * 10000) / 10000;

  function next(c) {
    const v = c.loads ? c.rating * (0.12 + Math.random() * 0.23)
      : last[c.sensor] + 0.3 * (c.start - last[c.sensor]) + gauss() * c.wander;
    last[c.sensor] = round(v);
    return last[c.sensor];
  }

  function say(line) {
    const lines = (out.textContent === 'Waiting to start.' ? [] : out.textContent.split('\n'));
    lines.push(`${new Date().toLocaleTimeString()}  ${line}`);
    out.textContent = lines.slice(-14).join('\n');
  }

  // POST what is pending; a real logger keeps what it could not send and tries again next time.
  async function send(readings, what) {
    try {
      const answer = await fetch(config.endpoint, {
        method: 'POST', credentials: 'omit',
        headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + config.key },
        body: JSON.stringify({ device: config.device, readings }),
      });
      const result = await answer.json().catch(() => ({}));
      if (!answer.ok && !result.written) {
        say(`MarineTwin refused it (${answer.status}): ${result.error || (result.problems || []).join(' ')}`);
        return false;
      }
      say(`sent ${readings.length} ${what}; MarineTwin wrote ${result.written}` +
          (result.problems && result.problems.length ? `, problems: ${result.problems[0]}` : ''));
      refresh();
      return true;
    } catch (e) {
      say('could not reach MarineTwin, keeping the readings to send again');
      return false;
    }
  }

  async function tick() {
    const at = stamp(new Date());
    channels.forEach((c) => pending.push({ sensor: c.sensor, at, value: next(c) }));
    const batch = pending;
    pending = [];
    if (!(await send(batch, batch.length > channels.length ? 'readings, including ones kept back' : 'readings'))) {
      pending = batch.concat(pending);
    }
  }

  start.addEventListener('click', async () => {
    start.disabled = true;
    stop.disabled = false;
    say(`fake logger started: ${channels.length} sensors, sending to ${config.endpoint}`);
    // What the logger kept while nothing was sending: the last 24 hours, hourly.
    const now = new Date();
    now.setSeconds(0, 0);
    const backlog = [];
    for (let h = 24; h > 0; h--) {
      const at = stamp(new Date(now.getTime() - h * 3600e3));
      channels.forEach((c) => backlog.push({ sensor: c.sensor, at, value: next(c) }));
    }
    if (!(await send(backlog, 'readings kept from the last 24 hours'))) pending = backlog;
    if (!stop.disabled) timer = setInterval(tick, 5000);
  });

  stop.addEventListener('click', () => {
    clearInterval(timer);
    timer = null;
    stop.disabled = true;
    start.disabled = false;
    say('fake logger stopped');
  });

  alarm.addEventListener('click', () => {
    // A structural sensor, not a load: a strain or a crack that has jumped stays there, so the
    // alarm is still showing when the Structure step is opened.
    const c = channels.find((x) => x.alarm !== null && !x.loads) || channels[0];
    const value = round(c.lower_worse ? c.alarm - Math.abs(c.alarm) * 0.15 : (c.alarm || 1) * 1.1);
    if (!c.loads) { last[c.sensor] = value; c.start = value; }
    send([{ sensor: c.sensor, at: stamp(new Date()), value, note: 'alarm test from the fake logger' }],
         `alarm reading (${c.sensor} at ${value} ${c.unit})`);
  });
})();
