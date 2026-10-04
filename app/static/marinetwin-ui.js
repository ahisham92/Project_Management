// MarineTwin's page furniture, shared by every page:
//
// - The voyage: Triton's loading bar, a container ship sailing to the quay as the work goes from 0 to
//   100%. It shows over the page whenever MarineTwin moves to another page or sends a form (the
//   simulation, an upload), creeping on while the server works, and inside the 3D view while it builds
//   (marinetwin.js drives that one through window.MarineVoyage).
// - Section tabs: a page's long sections, each a <section class="mt-panel" data-tab="Name">, become
//   tabs so only one shows at a time. The open tab is kept in the address (#name), so a link or a
//   reload comes back to it. Without JavaScript every section simply shows, one after the other.

(function () {
  const SHIP = `<svg class="ship" viewBox="0 0 64 26" aria-hidden="true">
  <path class="hull" d="M2 15h58l-5 8H8z"/><path class="boot" d="M5.2 20h52.6l-2 3H8z"/>
  <rect class="bridge" x="6" y="5" width="7" height="10" rx="1"/><rect class="win" x="7" y="7" width="5" height="1.6"/>
  <rect class="funnel" x="8" y="1.5" width="3" height="3.5"/>
  <g class="boxes"><rect x="16" y="10" width="8" height="5" fill="#e0583a"/><rect x="25" y="10" width="8" height="5" fill="#f2b033"/>
  <rect x="34" y="10" width="8" height="5" fill="#2f9e6e"/><rect x="43" y="10" width="8" height="5" fill="#1e8fc0"/>
  <rect x="20" y="5" width="8" height="5" fill="#1e8fc0"/><rect x="29" y="5" width="8" height="5" fill="#e0583a"/>
  <rect x="38" y="5" width="8" height="5" fill="#f2b033"/></g>
  <path class="line" d="M60 14.5Q67 13 74.5 9.5M56 15Q66 14.5 74 10.5"/></svg>`;

  // One voyage bar in `host`. set(f, text) points it at f (0..1); it moves one per cent at a time,
  // catching up quickly when the work jumps and creeping on (never to 100%) while it waits.
  function voyage(host, text) {
    const box = document.createElement('div');
    box.className = 'mt-voyage-box';
    box.innerHTML = `<div class="mt-voyage"><span class="sea"><i>${SHIP}</i></span><span class="quay" aria-hidden="true"><b></b></span></div>
      <p class="mt-voyage-text"><span class="mt-voyage-what"></span> <strong class="mt-voyage-pct tabular">0%</strong></p>`;
    host.appendChild(box);
    const bar = box.querySelector('.sea i');
    const what = box.querySelector('.mt-voyage-what');
    const pct = box.querySelector('.mt-voyage-pct');
    box.setAttribute('role', 'progressbar');
    box.setAttribute('aria-valuemin', '0');
    box.setAttribute('aria-valuemax', '100');
    let shown = 0;
    let target = 0;
    let creep = 0;
    let last = performance.now();
    let frame = null;
    what.textContent = text || 'Loading';
    function paint() {
      const p = Math.floor(shown * 100 + 1e-6);
      bar.style.width = `${Math.max(shown * 100, 1)}%`;
      pct.textContent = `${p}%`;
      box.setAttribute('aria-valuenow', String(p));
      box.querySelector('.mt-voyage').classList.toggle('moored', shown >= 0.9995);
    }
    function tick(now) {
      const dt = Math.min((now - last) / 1000, 0.25);
      last = now;
      if (target > shown) shown = Math.min(target, shown + Math.max(0.25 * dt, (target - shown) * Math.min(1, 4 * dt)));
      else if (creep > shown && target < 1) shown = Math.min(creep, shown + (creep - shown) * 0.35 * dt + 0.004 * dt);
      paint();
      frame = shown < Math.max(target, creep) - 1e-4 ? requestAnimationFrame(tick) : null;
    }
    function go() { if (!frame) { last = performance.now(); frame = requestAnimationFrame(tick); } }
    paint();
    return {
      element: box,
      set(f, words, ahead = 0) {
        target = Math.max(target, Math.min(f, 1));
        creep = Math.max(creep, Math.min(target + ahead, 0.97));
        if (words) what.textContent = words;
        go();
      },
      done(words) {
        this.set(1, words);
        return new Promise((resolve) => {
          const wait = () => (shown >= 0.9995 ? setTimeout(resolve, 350) : requestAnimationFrame(wait));
          wait();
        });
      },
      remove() { box.remove(); },
    };
  }
  window.MarineVoyage = voyage;

  // Over the page while the next one comes: a card at the top that sails on as the server works.
  let leaving = null;
  function sail(words) {
    if (leaving) return;
    const veil = document.createElement('div');
    veil.className = 'mt-voyage-veil';
    document.body.appendChild(veil);
    const v = voyage(veil, words);
    v.set(0.12, words, 0.8);
    leaving = { veil, v };
  }
  window.addEventListener('pageshow', () => {
    // Back to a page the browser kept: take the voyage away.
    if (leaving) { leaving.veil.remove(); leaving = null; }
  });
  const ours = (url) => url.origin === location.origin && url.pathname.startsWith('/marinetwin');
  document.addEventListener('click', (ev) => {
    const a = ev.target.closest('a[href]');
    if (!a || ev.defaultPrevented || ev.button !== 0 || ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey) return;
    if (a.target || a.hasAttribute('download')) return;
    const url = new URL(a.href, location.href);
    if (!ours(url) || /\.(csv|json|ifc|glb|gltf)$/i.test(url.pathname) || url.pathname.endsWith('/model')) return;
    if (url.pathname === location.pathname && url.search === location.search && url.hash) return;
    sail(a.dataset.voyage || 'Loading ' + (a.textContent.trim() || 'the page').replace(/\s+/g, ' ').slice(0, 40).toLowerCase());
  });
  // The voyage stops and says what went wrong, with a way back to the page.
  function wrecked(text) {
    if (!leaving) sail('');
    const { veil, v } = leaving;
    leaving.slow = true;
    v.element.classList.add('mt-voyage-failed');
    v.element.querySelector('.mt-voyage-what').textContent = text;
    v.element.querySelector('.mt-voyage-pct').textContent = '';
    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'btn btn-ghost btn-sm';
    close.textContent = 'Close';
    close.addEventListener('click', () => { veil.remove(); leaving = null; });
    v.element.appendChild(close);
    close.focus();
  }
  const WHY = {
    413: 'The file is too big for the server to take.',
    502: 'The server stopped while reading the model. Try again; if it happens again, export fewer categories from Revit.',
    504: 'The server took too long reading the model. Export fewer categories from Revit and try again.',
  };

  // Back to the same page (only the #section differs) the browser would just scroll: load it again.
  function arrive(to) {
    const u = new URL(to, location.href);
    if (u.pathname === location.pathname && u.search === location.search) {
      history.replaceState(null, '', u.href);
      location.reload();
    } else location.href = u.href;
  }

  // A file upload goes through the page so the voyage shows the bytes actually sent (to 80%),
  // then creeps on while the server reads the model, and says so if it fails.
  function upload(form) {
    const words = form.dataset.voyage || 'Uploading';
    sail(words);
    const { v } = leaving;
    const xhr = new XMLHttpRequest();
    xhr.open('POST', form.action);
    xhr.setRequestHeader('X-MarineTwin-Xhr', '1');
    xhr.timeout = 15 * 60 * 1000;
    xhr.upload.addEventListener('progress', (e) => {
      if (!e.lengthComputable) return;
      const f = e.loaded / e.total;
      const mb = (n) => (n / 1048576).toFixed(n < 10485760 ? 1 : 0);
      if (f < 1) v.set(0.02 + 0.78 * f, `${words}: ${mb(e.loaded)} of ${mb(e.total)} MB sent`);
      else v.set(0.8, 'Uploaded. The server is reading the model', 0.17);
    });
    xhr.addEventListener('load', () => {
      let to = null;
      try { to = JSON.parse(xhr.responseText).redirect; } catch (e) { /* not ours */ }
      if (xhr.status < 400 && to) { v.done('Done').then(() => arrive(to)); return; }
      if (xhr.status < 400) { document.open(); document.write(xhr.responseText); document.close(); return; }
      wrecked(WHY[xhr.status] || `The server could not finish (error ${xhr.status}). Nothing was changed; try again, and tell the admin if it keeps happening.`);
    });
    xhr.addEventListener('error', () => wrecked('The connection dropped during the upload. Check the network and try again.'));
    xhr.addEventListener('timeout', () => wrecked('No answer from the server after 15 minutes. Try again, or export a smaller model.'));
    xhr.send(new FormData(form));
  }

  document.addEventListener('submit', (ev) => {
    const form = ev.target;
    if (ev.defaultPrevented || form.method.toLowerCase() !== 'post') return;
    const file = form.querySelector('input[type=file]');
    if (file && file.files.length && window.FormData && window.XMLHttpRequest) {
      ev.preventDefault();
      upload(form);
      return;
    }
    // Let a confirm() in onsubmit say no first.
    setTimeout(() => { if (!ev.defaultPrevented) sail(form.dataset.voyage || 'Working on it'); }, 0);
  });

  // A page that takes long to come back after a form is still on its way; after a while say so,
  // so it never looks stuck without a word.
  setInterval(() => {
    if (!leaving || leaving.slow) return;
    leaving.since = leaving.since || Date.now();
    if (Date.now() - leaving.since > 45000) {
      leaving.slow = true;
      const what = leaving.v.element.querySelector('.mt-voyage-what');
      what.textContent += ' (still working; a big model can take a minute or two)';
    }
  }, 5000);

  // On a phone the steps scroll sideways: bring the one the person is on into view.
  for (const flow of document.querySelectorAll('.mt-flow')) {
    const here = flow.querySelector('.mt-step.here');
    if (here && flow.scrollWidth > flow.clientWidth) flow.scrollLeft = here.offsetLeft - flow.offsetLeft - 16;
  }

  // Section tabs.
  for (const holder of document.querySelectorAll('.mt-panels')) {
    const panels = [...holder.querySelectorAll(':scope > .mt-panel')];
    if (panels.length < 2) continue;
    const slug = (p) => p.dataset.slug || p.dataset.tab.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
    const nav = document.createElement('div');
    nav.className = 'mt-subtabs';
    nav.setAttribute('role', 'tablist');
    const buttons = panels.map((p) => {
      const b = document.createElement('button');
      b.type = 'button';
      b.setAttribute('role', 'tab');
      b.innerHTML = p.dataset.tab + (p.dataset.count ? ` <span class="mt-count">${p.dataset.count}</span>` : '');
      if (p.dataset.state) b.classList.add('mt-tab-' + p.dataset.state);
      nav.appendChild(b);
      return b;
    });
    holder.prepend(nav);
    holder.classList.add('mt-tabbed');
    function show(i, remember) {
      panels.forEach((p, k) => { p.hidden = k !== i; buttons[k].setAttribute('aria-selected', String(k === i)); });
      if (remember) history.replaceState(null, '', '#' + slug(panels[i]));
      // Maps and the 3D view size themselves when they first become visible.
      window.dispatchEvent(new Event('resize'));
    }
    buttons.forEach((b, i) => b.addEventListener('click', () => show(i, true)));
    const wanted = panels.findIndex((p) => '#' + slug(p) === location.hash);
    // A section holding a form with an error, or one marked open, comes first.
    const open = panels.findIndex((p) => p.dataset.open === '1');
    show(wanted >= 0 ? wanted : open >= 0 ? open : 0, false);
  }
})();
