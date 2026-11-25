// CDT for the web: the behaviour of the CDT-SDK controls (CDT.Wpf/Controls) for HTML pages.
//
// Plain markup works without this file; with it, the page gets:
//   InfoBar          every flash message: glyph + word + colour, a close button; a success closes itself
//                    (paused under the mouse). CDT.toast(severity, title, message) shows one in the corner.
//   DialogHost       form[data-confirm] / button[data-confirm] ask in a dialog over a dimmed page instead of
//                    the browser's confirm(). CDT.confirm({title, message, ok, danger}) -> Promise<boolean>.
//   NumberBox        every number input: takes sums (6000/4 + 25) and units (250 mm, 0.25 m, 1' 6", 12 kn),
//                    shows what it came to, ↑ / ↓ and PageUp / PageDown step it, Esc puts it back, a bad
//                    value says why under the field. data-unit="mm" names its unit (else "(mm)" in its label).
//   SearchableComboBox  a long <select> (8+ options, or data-cdt="search"): type words in any order.
//   CheckComboBox    <select multiple>: a dropdown of ticks that sums itself up ("A, B", "All", "5 of 9").
//   TokenBox         <select multiple data-cdt="tokens">: the picks as removable chips, typing suggests more.
//   DataGridFilter   tables with 6+ rows (or data-cdt="grid"): click a header to sort; its funnel filters on
//                    the column's values, with counts, a search box and Select all; filters combine.
//   PathBox          file inputs: a drop zone that names what was picked and refuses a wrong kind of file.
//   DropDownButton   [data-cdt-menu] opens the .cdt-popup menu after it.
//   InfoTip          .cdt-infotip[data-tip] (and data-img for a picture) shows its tip on hover and focus.
// Mark anything data-cdt="plain" to leave it as it is.
(function () {
  'use strict';
  if (window.CDT) return;
  const CDT = (window.CDT = {});
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
  const el = (tag, cls, html) => { const e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; };
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const plain = (n) => n.closest('[data-cdt="plain"]');
  const fold = (s) => String(s).toLowerCase().normalize('NFKD').replace(/[̀-ͯ]/g, '');

  // ---- popups: one open at a time, placed under (or over) what opened it ----------------------------
  let open = null;
  function place(pop, anchor, minWidth = true) {
    const r = anchor.getBoundingClientRect();
    if (minWidth) pop.style.minWidth = Math.max(180, r.width) + 'px';
    pop.style.left = '0px'; pop.style.top = '0px';
    const h = pop.offsetHeight, w = pop.offsetWidth;
    const below = window.innerHeight - r.bottom;
    const top = below < h + 8 && r.top > below ? r.top - h - 4 : r.bottom + 4;
    pop.style.top = Math.max(4, top) + 'px';
    pop.style.left = Math.max(8, Math.min(r.left, window.innerWidth - w - 8)) + 'px';
  }
  function show(pop, anchor, onClose) {
    if (open && open.pop !== pop) close();
    pop.hidden = false;
    document.body.appendChild(pop);
    place(pop, anchor);
    open = { pop, anchor, onClose };
    anchor.setAttribute('aria-expanded', 'true');
  }
  function close() {
    if (!open) return;
    const o = open; open = null;
    o.pop.hidden = true;
    o.anchor.setAttribute('aria-expanded', 'false');
    if (o.onClose) o.onClose();
  }
  CDT.closePopup = close;
  document.addEventListener('mousedown', (e) => { if (open && !open.pop.contains(e.target) && !open.anchor.contains(e.target)) close(); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && open) { const a = open.anchor; close(); a.focus(); } });
  window.addEventListener('resize', () => open && place(open.pop, open.anchor));
  document.addEventListener('scroll', (e) => { if (open && !open.pop.contains(e.target)) place(open.pop, open.anchor); }, true);

  // ---- InfoBar ------------------------------------------------------------------------------------------
  const GLYPH = { info: 'i', success: '✓', warning: '!', error: '✕' };
  const WORD = { info: 'Note', success: 'Done', warning: 'Check', error: 'Problem' };
  function infobar(node, severity, title, autoClose) {
    if (node.dataset.cdtDone) return node;
    node.dataset.cdtDone = '1';
    const body = el('div', 'cdt-ib-body');
    while (node.firstChild) body.appendChild(node.firstChild);
    if (title !== false) body.prepend(el('span', 'cdt-ib-title', esc(title || WORD[severity])));
    node.append(el('span', 'cdt-ib-glyph', GLYPH[severity]), body);
    const x = el('button', 'cdt-ib-close', '×');
    x.type = 'button'; x.setAttribute('aria-label', 'Close');
    x.addEventListener('click', () => dismiss(node));
    node.appendChild(x);
    if (autoClose) {
      let left = autoClose, t0 = Date.now(), timer = null;
      const run = () => { t0 = Date.now(); timer = setTimeout(() => dismiss(node), left); };
      node.addEventListener('mouseenter', () => { clearTimeout(timer); left -= Date.now() - t0; });
      node.addEventListener('mouseleave', run);
      run();
    }
    return node;
  }
  function dismiss(node) { node.classList.add('closing'); setTimeout(() => node.remove(), 220); }
  CDT.toast = function (severity, title, message, ms = 6000) {
    let host = document.querySelector('.cdt-toasts');
    if (!host) { host = el('div', 'cdt-toasts'); host.setAttribute('aria-live', 'polite'); document.body.appendChild(host); }
    const n = el('div', 'cdt-infobar ' + severity, esc(message || ''));
    n.setAttribute('role', severity === 'error' ? 'alert' : 'status');
    host.appendChild(infobar(n, severity, title, severity === 'error' ? 0 : ms));
    return n;
  };
  function flashes() {
    for (const f of $$('.flash')) {
      const sev = f.classList.contains('error') ? 'error' : f.classList.contains('notice') ? 'warning' : f.classList.contains('success') ? 'success' : 'info';
      infobar(f, sev, null, sev === 'success' ? 8000 : 0);
    }
    for (const f of $$('.cdt-infobar[data-severity]')) infobar(f, f.dataset.severity, f.dataset.title || null, +f.dataset.autoClose || 0);
  }

  // ---- DialogHost -------------------------------------------------------------------------------------------
  CDT.confirm = function ({ title = 'Are you sure?', message = '', ok = 'OK', cancel = 'Cancel', danger = false } = {}) {
    return new Promise((resolve) => {
      const back = document.activeElement;
      const scrim = el('div', 'cdt-scrim');
      const sheet = el('div', 'cdt-sheet' + (danger ? ' danger' : ''));
      sheet.setAttribute('role', 'alertdialog'); sheet.setAttribute('aria-modal', 'true');
      sheet.innerHTML = `<div class="cdt-sheet-head"><span class="cdt-sheet-glyph">${danger ? '!' : '?'}</span>
        <div><p class="cdt-sheet-title" id="cdt-dlg-t">${esc(title)}</p><p class="cdt-sheet-msg">${esc(message)}</p></div></div>
        <div class="cdt-sheet-foot"><button type="button" class="cdt-btn ghost" data-r="0">${esc(cancel)}</button>
        <button type="button" class="cdt-btn ${danger ? 'danger' : 'primary'}" data-r="1">${esc(ok)}</button></div>`;
      sheet.setAttribute('aria-labelledby', 'cdt-dlg-t');
      scrim.appendChild(sheet);
      document.body.appendChild(scrim);
      const buttons = $$('button', sheet);
      const done = (v) => { scrim.remove(); document.removeEventListener('keydown', key, true); if (back && back.focus) back.focus(); resolve(v); };
      const key = (e) => {
        if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); done(false); }
        if (e.key === 'Tab') {   // keep Tab inside the sheet
          const i = buttons.indexOf(document.activeElement);
          e.preventDefault(); buttons[(i + (e.shiftKey ? buttons.length - 1 : 1)) % buttons.length].focus();
        }
      };
      document.addEventListener('keydown', key, true);
      buttons.forEach((b) => b.addEventListener('click', () => done(b.dataset.r === '1')));
      scrim.addEventListener('mousedown', (e) => { if (e.target === scrim) done(false); });
      buttons[danger ? 0 : 1].focus();
    });
  };
  function confirmText(node) {
    const t = node.dataset.confirm;
    const words = node.dataset.confirmOk || ((node.textContent || '').trim().length < 28 && (node.textContent || '').trim()) || 'OK';
    return { title: node.dataset.confirmTitle || t, message: node.dataset.confirmTitle ? t : '', ok: words,
             danger: node.dataset.confirmDanger !== '0' && /delete|remove|reset|clear|new key/i.test(t + ' ' + words) };
  }
  // Ask before the form goes (and before the ship loader sails): capture, so this runs first.
  document.addEventListener('submit', (ev) => {
    const form = ev.target;
    const who = (ev.submitter && ev.submitter.dataset.confirm != null) ? ev.submitter : form.dataset.confirm != null ? form : null;
    if (!who || form.dataset.cdtConfirmed) { delete form.dataset.cdtConfirmed; return; }
    ev.preventDefault(); ev.stopImmediatePropagation();
    const txt = confirmText(who);
    if (who === form && ev.submitter && !form.dataset.confirmOk) {
      const words = ev.submitter.textContent.trim();
      if (words && words.length < 28) txt.ok = words;
    }
    CDT.confirm(txt).then((yes) => {
      if (!yes) return;
      form.dataset.cdtConfirmed = '1';
      if (form.requestSubmit) form.requestSubmit(ev.submitter || undefined); else form.submit();
    });
  }, true);

  // ---- NumberBox --------------------------------------------------------------------------------------------
  // A unit is a dimension and a factor to the base (m, N, Pa, m/s, kg, s, rad).
  const UNITS = {
    mm: ['L', 1e-3], cm: ['L', 1e-2], m: ['L', 1], km: ['L', 1e3], in: ['L', 0.0254], '"': ['L', 0.0254], ft: ['L', 0.3048], "'": ['L', 0.3048],
    N: ['F', 1], kN: ['F', 1e3], MN: ['F', 1e6], kip: ['F', 4448.2216], tf: ['F', 9806.65],
    Pa: ['P', 1], kPa: ['P', 1e3], MPa: ['P', 1e6], GPa: ['P', 1e9], 'N/mm2': ['P', 1e6], 'N/mm²': ['P', 1e6], psi: ['P', 6894.757], ksi: ['P', 6894757],
    'm/s': ['V', 1], kn: ['V', 0.514444], knots: ['V', 0.514444], 'km/h': ['V', 1 / 3.6], mph: ['V', 0.44704],
    kg: ['M', 1], t: ['M', 1e3], tonnes: ['M', 1e3],
    s: ['T', 1], min: ['T', 60], h: ['T', 3600], d: ['T', 86400], days: ['T', 86400], years: ['T', 31557600], yr: ['T', 31557600],
    deg: ['A', Math.PI / 180], '°': ['A', Math.PI / 180], rad: ['A', 1],
    kNm: ['FL', 1e3], 'kN·m': ['FL', 1e3], 'kN*m': ['FL', 1e3], MNm: ['FL', 1e6],
    'kN/m': ['FpL', 1e3], 'N/m': ['FpL', 1], '%': ['%', 1], 'mV': ['E', 1e-3], V: ['E', 1],
  };
  const UNIT_RE = new RegExp('^(' + Object.keys(UNITS).sort((a, b) => b.length - a.length)
    .map((u) => u.replace(/[.*+?^${}()|[\]\\/]/g, '\\$&')).join('|') + ')(?![a-zA-Z])');
  // Reads the sum in `text`, in the box's unit `unit`; throws a sentence saying what is wrong.
  function evaluate(text, unit) {
    const s = text.replace(/,/g, '.').replace(/[×x](?=\s*[\d(.])/g, '*').replace(/÷/g, '/').replace(/−/g, '-').trim();
    if (!s) return null;
    let i = 0;
    const home = unit && UNITS[unit];
    const ws = () => { while (s[i] === ' ') i++; };
    const fail = (m) => { throw new Error(m); };
    function postfix(v) {
      ws();
      const m = s.slice(i).match(UNIT_RE);
      if (!m) return v;
      const u = UNITS[m[1]];
      if (!home) fail(`This field takes a plain number, not ${m[1]}.`);
      if (u[0] !== home[0]) fail(`${m[1]} is not a ${unit} kind of unit.`);
      i += m[1].length;
      return v * u[1] / home[1];
    }
    function primary() {
      ws();
      if (s[i] === '(') { i++; const v = sum(); ws(); if (s[i] !== ')') fail('A bracket is not closed.'); i++; return postfix(v); }
      if (s[i] === '-') { i++; return -primary(); }
      if (s[i] === '+') { i++; return primary(); }
      const m = s.slice(i).match(/^(\d+\.?\d*|\.\d+)(e[+-]?\d+)?/i);
      if (!m) fail(i >= s.length ? 'The sum stops short.' : `“${s.slice(i, i + 6)}” is not a number.`);
      i += m[0].length;
      let v = postfix(parseFloat(m[0]));
      ws();
      // feet and inches written together: 1' 6"
      if (/^\d/.test(s.slice(i)) && /['"]$/.test(s.slice(0, i).trim())) v += primary();
      return v;
    }
    function power() { let v = primary(); ws(); if (s[i] === '^') { i++; v = Math.pow(v, power()); } return v; }
    function product() { let v = power(); for (;;) { ws(); if (s[i] === '*') { i++; v *= power(); } else if (s[i] === '/') { i++; const d = power(); if (d === 0) fail('That divides by zero.'); v /= d; } else return v; } }
    function sum() { let v = product(); for (;;) { ws(); if (s[i] === '+') { i++; v += product(); } else if (s[i] === '-') { i++; v -= product(); } else return v; } }
    const v = sum();
    ws();
    if (i < s.length) fail(`“${s.slice(i, i + 8)}” is not understood here.`);
    if (!isFinite(v)) fail('That is not a number.');
    return v;
  }
  CDT.evaluate = evaluate;
  function decimalsOf(step) { const t = String(step); return t.includes('.') ? t.split('.')[1].length : 0; }
  function numberbox(input) {
    if (input.dataset.cdtDone || plain(input)) return;
    input.dataset.cdtDone = '1';
    const label = input.closest('label') && input.closest('label').querySelector('.field-label');
    let unit = input.dataset.unit || '';
    if (!unit && label) { const m = label.textContent.match(/\(([^)]+)\)\s*$/); if (m && UNITS[m[1].trim()]) unit = m[1].trim(); }
    const min = input.min !== '' ? +input.min : null, max = input.max !== '' ? +input.max : null;
    const stepAttr = input.getAttribute('step');
    const step = stepAttr && stepAttr !== 'any' ? +stepAttr : 1;
    const decimals = stepAttr && stepAttr !== 'any' ? decimalsOf(stepAttr) : null;
    input.type = 'text';
    input.inputMode = 'decimal';
    input.autocomplete = 'off';
    input.spellcheck = false;
    const box = el('span', 'cdt-number' + (unit ? ' has-unit' : ''));
    input.parentNode.insertBefore(box, input);
    box.appendChild(input);
    if (unit) { box.appendChild(el('span', 'cdt-number-unit', esc(unit))); box.style.setProperty('--unit-w', unit.length + 'ch'); }
    const spin = el('span', 'cdt-spin', '<button type="button" tabindex="-1" aria-label="Up">▲</button><button type="button" tabindex="-1" aria-label="Down">▼</button>');
    box.appendChild(spin);
    const says = el('span', 'cdt-number-says');
    box.after(says);
    let kept = input.value;
    const fmt = (v) => {
      let r = decimals != null ? v.toFixed(decimals) : String(+v.toPrecision(12));
      return r;
    };
    function check(commit) {
      input.classList.remove('cdt-invalid'); says.textContent = ''; says.style.color = '';
      input.setCustomValidity('');
      const raw = input.value.trim();
      if (!raw) return true;
      try {
        const v = evaluate(raw, unit);
        let why = '';
        if (min != null && v < min) why = `At least ${min}${unit ? ' ' + unit : ''}.`;
        if (max != null && v > max) why = `At most ${max}${unit ? ' ' + unit : ''}.`;
        if (why) throw new Error(why);
        const shown = fmt(v);
        if (commit) { input.value = shown; kept = shown; }
        else if (shown !== raw) says.textContent = '= ' + shown + (unit ? ' ' + unit : '');
        return true;
      } catch (e) {
        if (commit || raw.length > 1) { says.textContent = e.message; says.style.color = 'var(--cdt-danger)'; }
        if (commit) { input.classList.add('cdt-invalid'); input.setCustomValidity(e.message); }
        return false;
      }
    }
    function nudge(d) {
      let v = 0; try { v = evaluate(input.value, unit) || 0; } catch (e) { v = +kept || 0; }
      v = Math.round((v + d) / step) * step;
      if (min != null) v = Math.max(min, v); if (max != null) v = Math.min(max, v);
      input.value = fmt(v); check(true);
      input.dispatchEvent(new Event('input', { bubbles: true })); input.dispatchEvent(new Event('change', { bubbles: true }));
    }
    input.addEventListener('input', () => check(false));
    input.addEventListener('blur', () => check(true));
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') check(true);
      else if (e.key === 'Escape') { input.value = kept; check(false); }
      else if (e.key === 'ArrowUp' || e.key === 'ArrowDown') { e.preventDefault(); nudge((e.key === 'ArrowUp' ? 1 : -1) * step); }
      else if (e.key === 'PageUp' || e.key === 'PageDown') { e.preventDefault(); nudge((e.key === 'PageUp' ? 10 : -10) * step); }
    });
    const [up, down] = spin.querySelectorAll('button');
    up.addEventListener('click', () => nudge(step));
    down.addEventListener('click', () => nudge(-step));
    if (input.disabled || input.readOnly) spin.hidden = true;
    input._cdtCommit = () => check(true);
  }
  // A sum still being typed is worked out before the form goes.
  document.addEventListener('submit', (ev) => {
    let ok = true;
    for (const i of $$('input', ev.target)) if (i._cdtCommit && !i._cdtCommit()) ok = false;
    if (!ok) { ev.preventDefault(); ev.stopImmediatePropagation(); const bad = ev.target.querySelector('.cdt-invalid'); if (bad) bad.focus(); }
  }, true);

  // ---- SearchableComboBox -----------------------------------------------------------------------------------
  function optionsOf(select) {
    const out = [];
    for (const o of select.options) out.push({ o, text: o.textContent.trim(), group: o.parentNode.tagName === 'OPTGROUP' ? o.parentNode.label : '' });
    return out;
  }
  // word by word, ignoring spaces and case: "ipe 3" finds "IPE 300"
  function matches(text, q) {
    const t = fold(text), tight = t.replace(/\s+/g, '');
    return fold(q).split(/\s+/).filter(Boolean).every((w) => t.includes(w) || tight.includes(w));
  }
  function highlight(text, q) {
    const words = fold(q).split(/\s+/).filter(Boolean);
    if (!words.length) return esc(text);
    const f = fold(text);
    const marks = new Array(text.length).fill(false);
    for (const w of words) { let k = f.indexOf(w); while (k >= 0) { for (let j = k; j < k + w.length; j++) marks[j] = true; k = f.indexOf(w, k + w.length); } }
    let out = '', on = false;
    for (let j = 0; j < text.length; j++) { if (marks[j] !== on) { out += on ? '</mark>' : '<mark>'; on = marks[j]; } out += esc(text[j]); }
    return out + (on ? '</mark>' : '');
  }
  function face(select, cls) {
    const wrap = el('span', 'cdt-combo ' + (cls || ''));
    select.parentNode.insertBefore(wrap, select);
    const btn = el('button', 'cdt-combo-face');
    btn.type = 'button';
    btn.setAttribute('aria-haspopup', 'listbox'); btn.setAttribute('aria-expanded', 'false');
    const lab = select.closest('label') && select.closest('label').querySelector('.field-label');
    if (lab) btn.setAttribute('aria-label', lab.textContent.trim());
    wrap.append(btn, select);
    select.tabIndex = -1;
    select.setAttribute('aria-hidden', 'true');
    if (select.disabled) btn.disabled = true;
    // a hidden <select> that is required still says so through the face
    select.addEventListener('invalid', () => btn.classList.add('cdt-invalid'));
    return { wrap, btn };
  }
  function searchable(select) {
    if (select.dataset.cdtDone || plain(select)) return;
    select.dataset.cdtDone = '1';
    const { btn } = face(select);
    const paint = () => { const o = select.options[select.selectedIndex]; btn.innerHTML = o ? esc(o.textContent.trim()) : '<span class="cdt-placeholder">Pick one</span>'; };
    paint();
    select.addEventListener('change', paint);
    const pop = el('div', 'cdt-popup'); pop.hidden = true; pop.setAttribute('role', 'listbox');
    const q = el('input', 'cdt-search'); q.type = 'search'; q.placeholder = 'Type to search'; q.setAttribute('aria-label', 'Search');
    const list = el('div');
    pop.append(q, list);
    let rows = [], at = -1;
    function render() {
      list.innerHTML = ''; rows = [];
      let group = null;
      for (const it of optionsOf(select)) {
        if (it.o.hidden) continue;
        if (q.value && !matches(it.text + ' ' + it.group, q.value)) continue;
        if (it.group !== group) { group = it.group; if (group) list.appendChild(el('div', 'cdt-option-group', esc(group))); }
        const r = el('button', 'cdt-option', highlight(it.text, q.value) || '&nbsp;');
        r.type = 'button'; r.tabIndex = -1; r.setAttribute('role', 'option');
        r.setAttribute('aria-selected', String(it.o.selected));
        if (it.o.disabled) r.disabled = true;
        r.addEventListener('click', () => pick(it.o));
        list.appendChild(r); rows.push(r);
      }
      if (!rows.length) list.appendChild(el('div', 'cdt-empty-list', 'Nothing matches “' + esc(q.value) + '”.'));
      at = rows.findIndex((r) => r.getAttribute('aria-selected') === 'true');
      if (q.value || at < 0) at = rows.length ? 0 : -1;
      mark();
    }
    function mark() { rows.forEach((r, k) => r.classList.toggle('active', k === at)); if (rows[at]) rows[at].scrollIntoView({ block: 'nearest' }); }
    function pick(o) {
      const changed = !o.selected;
      o.selected = true;
      close(); btn.focus();
      if (changed) select.dispatchEvent(new Event('change', { bubbles: true }));
      paint();
    }
    function openIt() { q.value = ''; render(); show(pop, btn); q.focus(); }
    btn.addEventListener('click', () => (open && open.pop === pop ? close() : openIt()));
    btn.addEventListener('keydown', (e) => {
      if (['ArrowDown', 'ArrowUp', 'Enter', ' '].includes(e.key)) { e.preventDefault(); openIt(); }
      else if (e.key.length === 1 && /\S/.test(e.key)) { openIt(); q.value = e.key; render(); e.preventDefault(); }
    });
    q.addEventListener('input', render);
    q.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowDown') { e.preventDefault(); at = Math.min(rows.length - 1, at + 1); mark(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); at = Math.max(0, at - 1); mark(); }
      else if (e.key === 'Enter') { e.preventDefault(); if (rows[at]) rows[at].click(); }
      else if (e.key === 'Tab') close();
    });
  }

  // ---- CheckComboBox and TokenBox (both over a <select multiple>) ------------------------------------------
  function summary(select, limit = 2) {
    const all = [...select.options], on = all.filter((o) => o.selected);
    if (!on.length) return '<span class="cdt-placeholder">' + esc(select.dataset.placeholder || 'None') + '</span>';
    if (on.length === all.length && all.length > 1) return esc(select.dataset.allText || 'All');
    if (on.length <= limit) return on.map((o) => esc(o.textContent.trim())).join(', ');
    return `${on.length} of ${all.length}`;
  }
  function checkcombo(select) {
    if (select.dataset.cdtDone || plain(select)) return;
    select.dataset.cdtDone = '1';
    const { btn } = face(select, 'check');
    const paint = () => { btn.innerHTML = summary(select, +select.dataset.summaryLimit || 2); };
    paint();
    const pop = el('div', 'cdt-popup'); pop.hidden = true;
    function render() {
      pop.innerHTML = '';
      const many = select.options.length > 8;
      let q = null;
      if (many) { q = el('input', 'cdt-search'); q.type = 'search'; q.placeholder = 'Type to search'; pop.appendChild(q); }
      const all = el('label', 'cdt-option', '<input type="checkbox"> <b>Select all</b>');
      const allBox = all.querySelector('input');
      pop.appendChild(all);
      const list = el('div'); pop.appendChild(list);
      const boxes = [];
      for (const o of select.options) {
        const r = el('label', 'cdt-option', `<input type="checkbox" ${o.selected ? 'checked' : ''}> <span>${esc(o.textContent.trim())}</span>`);
        const cb = r.querySelector('input');
        cb.addEventListener('change', () => { o.selected = cb.checked; sync(); });
        list.appendChild(r); boxes.push({ r, cb, o });
      }
      function sync() {
        const n = boxes.filter((b) => b.o.selected).length;
        allBox.checked = n === boxes.length; allBox.indeterminate = n > 0 && n < boxes.length;
        paint(); select.dispatchEvent(new Event('change', { bubbles: true }));
      }
      allBox.addEventListener('change', () => { boxes.forEach((b) => { if (!b.r.hidden) { b.o.selected = allBox.checked; b.cb.checked = allBox.checked; } }); sync(); });
      if (q) q.addEventListener('input', () => boxes.forEach((b) => { b.r.hidden = !matches(b.o.textContent, q.value); }));
      const n = boxes.filter((b) => b.o.selected).length;
      allBox.checked = n === boxes.length; allBox.indeterminate = n > 0 && n < boxes.length;
      return q;
    }
    btn.addEventListener('click', () => { if (open && open.pop === pop) { close(); return; } const q = render(); show(pop, btn); (q || pop.querySelector('input')).focus(); });
  }
  function tokenbox(select) {
    if (select.dataset.cdtDone || plain(select)) return;
    select.dataset.cdtDone = '1';
    const box = el('div', 'cdt-tokens');
    select.parentNode.insertBefore(box, select);
    select.hidden = true;
    const input = el('input', 'cdt-token-input');
    input.placeholder = select.dataset.placeholder || 'Type to add';
    input.setAttribute('aria-label', input.placeholder);
    const pop = el('div', 'cdt-popup'); pop.hidden = true;
    let rows = [], at = 0;
    function paint() {
      $$('.cdt-chip', box).forEach((c) => c.remove());
      for (const o of select.options) {
        if (!o.selected) continue;
        const c = el('span', 'cdt-chip', `${esc(o.textContent.trim())}<button type="button" aria-label="Remove ${esc(o.textContent.trim())}">✕</button>`);
        c.querySelector('button').addEventListener('click', (e) => { e.stopPropagation(); o.selected = false; changed(); input.focus(); });
        box.insertBefore(c, input);
      }
    }
    function changed() { paint(); select.dispatchEvent(new Event('change', { bubbles: true })); if (open && open.pop === pop) suggest(); }
    function suggest() {
      pop.innerHTML = ''; rows = [];
      for (const o of select.options) {
        if (o.selected || (input.value && !matches(o.textContent, input.value))) continue;
        const r = el('button', 'cdt-option', highlight(o.textContent.trim(), input.value));
        r.type = 'button'; r.tabIndex = -1;
        r.addEventListener('mousedown', (e) => e.preventDefault());
        r.addEventListener('click', () => { o.selected = true; input.value = ''; changed(); });
        pop.appendChild(r); rows.push(r);
      }
      if (!rows.length) pop.appendChild(el('div', 'cdt-empty-list', input.value ? 'Nothing matches.' : 'All of them are in.'));
      at = 0; rows.forEach((r, k) => r.classList.toggle('active', k === at));
      if (!open || open.pop !== pop) show(pop, box); else place(pop, box);
    }
    box.appendChild(input);
    box.addEventListener('click', () => input.focus());
    input.addEventListener('focus', suggest);
    input.addEventListener('input', suggest);
    input.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); at = Math.max(0, Math.min(rows.length - 1, at + (e.key === 'ArrowDown' ? 1 : -1))); rows.forEach((r, k) => r.classList.toggle('active', k === at)); }
      else if (e.key === 'Enter') { e.preventDefault(); if (rows[at]) rows[at].click(); }
      else if (e.key === 'Backspace' && !input.value) { const on = [...select.options].filter((o) => o.selected); if (on.length) { on[on.length - 1].selected = false; changed(); } }
    });
    input.addEventListener('blur', () => setTimeout(() => { if (open && open.pop === pop && !box.contains(document.activeElement)) close(); }, 100));
    paint();
  }

  // ---- DataGridFilter (and sorting) ---------------------------------------------------------------------------
  const FUNNEL = '<svg viewBox="0 0 12 12" aria-hidden="true"><path fill="currentColor" d="M1 1.5h10L7.2 6v4.2L4.8 11V6z"/></svg>';
  function cellValue(td) { return (td.dataset.sort != null ? td.dataset.sort : td.textContent).replace(/\s+/g, ' ').trim(); }
  function asNumber(s) { const m = s.replace(/,/g, '').match(/^[−-]?\$?\d*\.?\d+(e[+-]?\d+)?/i); return m ? parseFloat(m[0].replace('−', '-').replace('$', '')) : null; }
  function grid(table) {
    if (table.dataset.cdtDone || plain(table)) return;
    const head = table.tHead && table.tHead.rows[table.tHead.rows.length - 1];
    const body = table.tBodies[0];
    if (!head || !body) return;
    const ths = [...head.cells];
    const n = ths.length;
    const all = [...body.rows];
    const data = all.filter((r) => r.cells.length === n && !r.querySelector('th[colspan]'));
    if (!data.length) return;
    if (data.length < 6 && table.dataset.cdt !== 'grid') return;
    if (ths.some((th) => th.colSpan > 1)) return;
    table.dataset.cdtDone = '1';
    const grouped = all.length !== data.length;
    const filters = new Map();   // column -> Set of allowed values
    const bar = el('div', 'cdt-filter-bar'); bar.hidden = true;
    const scroller = table.closest('.table-scroll') || table;
    scroller.parentNode.insertBefore(bar, scroller);
    function apply() {
      let shown = 0;
      for (const r of data) {
        let ok = true;
        for (const [c, set] of filters) if (!set.has(cellValue(r.cells[c]))) { ok = false; break; }
        r.hidden = !ok; if (ok) shown++;
      }
      if (grouped) {   // a group heading shows while any of its rows do
        let headRow = null, any = false;
        const flush = () => { if (headRow) headRow.hidden = !any; };
        for (const r of all) { if (!data.includes(r)) { flush(); headRow = r; any = false; } else if (!r.hidden) any = true; }
        flush();
      }
      ths.forEach((th, c) => { const f = th.querySelector('.cdt-funnel'); if (f) f.classList.toggle('on', filters.has(c)); });
      bar.hidden = !filters.size;
      if (filters.size) {
        bar.innerHTML = `<span>Showing <b>${shown}</b> of ${data.length}</span>` +
          [...filters.keys()].map((c) => `<span class="cdt-chip">${esc(ths[c].textContent.trim())}: ${filters.get(c).size}<button type="button" data-c="${c}" aria-label="Clear this filter">✕</button></span>`).join('') +
          '<button type="button" class="cdt-btn link sm" data-clear>Clear filters</button>';
        bar.querySelectorAll('[data-c]').forEach((b) => b.addEventListener('click', () => { filters.delete(+b.dataset.c); apply(); }));
        bar.querySelector('[data-clear]').addEventListener('click', () => { filters.clear(); apply(); });
      }
    }
    let sortCol = -1, sortDir = 1;
    function sort(c) {
      sortDir = sortCol === c ? -sortDir : 1; sortCol = c;
      const nums = data.every((r) => { const v = cellValue(r.cells[c]); return !v || v === '—' || asNumber(v) != null; });
      const key = (r) => { const v = cellValue(r.cells[c]); return nums ? (asNumber(v) ?? -Infinity) : fold(v); };
      const sorted = [...data].sort((a, b) => { const x = key(a), y = key(b); return (x < y ? -1 : x > y ? 1 : 0) * sortDir; });
      sorted.forEach((r) => body.appendChild(r));
      ths.forEach((th, k) => {
        const a = th.querySelector('.cdt-sort-arrow'); if (a) a.remove();
        th.removeAttribute('aria-sort');
        if (k === c) { th.querySelector('.cdt-th-text').after(el('span', 'cdt-sort-arrow', sortDir > 0 ? '▲' : '▼')); th.setAttribute('aria-sort', sortDir > 0 ? 'ascending' : 'descending'); }
      });
    }
    ths.forEach((th, c) => {
      if (th.dataset.cdt === 'plain' || !th.textContent.trim()) return;
      const values = new Map();
      for (const r of data) { const v = cellValue(r.cells[c]); values.set(v, (values.get(v) || 0) + 1); }
      const text = el('span', 'cdt-th-text');
      while (th.firstChild) text.appendChild(th.firstChild);
      th.appendChild(text);
      if (!grouped) { th.classList.add('cdt-sortable'); th.title = th.title || 'Sort by this column'; th.addEventListener('click', (e) => { if (!e.target.closest('.cdt-funnel')) sort(c); }); }
      // a funnel only where values repeat: a column of unique figures is sorted, not filtered
      if (values.size < 2 || values.size > 60 || values.size === data.length) return;
      const f = el('button', 'cdt-funnel', FUNNEL);
      f.type = 'button'; f.setAttribute('aria-label', 'Filter ' + th.textContent.trim()); f.setAttribute('aria-haspopup', 'true');
      th.appendChild(f);
      f.addEventListener('click', (e) => {
        e.stopPropagation();
        if (open && open.anchor === f) { close(); return; }
        const pop = el('div', 'cdt-popup');
        const q = el('input', 'cdt-search'); q.type = 'search'; q.placeholder = 'Search ' + th.textContent.trim().toLowerCase();
        const allRow = el('label', 'cdt-option', '<input type="checkbox"> <b>Select all</b>');
        const allBox = allRow.querySelector('input');
        const list = el('div');
        const chosen = new Set(filters.get(c) || values.keys());
        const sortedVals = [...values.keys()].sort((a, b) => { const x = asNumber(a), y = asNumber(b); return x != null && y != null ? x - y : fold(a) < fold(b) ? -1 : 1; });
        const boxes = sortedVals.map((v) => {
          const r = el('label', 'cdt-option', `<input type="checkbox" ${chosen.has(v) ? 'checked' : ''}> <span>${esc(v || '(blank)')}</span><span class="cdt-count">${values.get(v)}</span>`);
          const cb = r.querySelector('input');
          cb.addEventListener('change', () => { cb.checked ? chosen.add(v) : chosen.delete(v); tally(); });
          list.appendChild(r);
          return { v, r, cb };
        });
        function tally() { const k = boxes.filter((b) => b.cb.checked).length; allBox.checked = k === boxes.length; allBox.indeterminate = k && k < boxes.length; }
        allBox.addEventListener('change', () => boxes.forEach((b) => { if (!b.r.hidden) { b.cb.checked = allBox.checked; allBox.checked ? chosen.add(b.v) : chosen.delete(b.v); } }));
        q.addEventListener('input', () => boxes.forEach((b) => { b.r.hidden = !matches(b.v, q.value); }));
        const foot = el('div', 'cdt-popup-foot', '<button type="button" class="cdt-btn ghost sm">Cancel</button><button type="button" class="cdt-btn primary sm">Filter</button>');
        const [cancel, ok] = foot.querySelectorAll('button');
        cancel.addEventListener('click', close);
        ok.addEventListener('click', () => { if (chosen.size === values.size) filters.delete(c); else filters.set(c, new Set(chosen)); close(); apply(); });
        q.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') { ev.preventDefault(); ok.click(); } });
        pop.append(q, allRow, list, foot);
        tally();
        show(pop, f, () => pop.remove());
        place(pop, f, false);
        q.focus();
      });
    });
  }

  // ---- PathBox ------------------------------------------------------------------------------------------------
  const DOC = '<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round" d="M6 3h8l4 4v14H6zM14 3v4h4M12 17v-6m-3 3 3-3 3 3"/></svg>';
  function size(n) { return n < 1048576 ? Math.max(1, Math.round(n / 1024)) + ' KB' : (n / 1048576).toFixed(n < 10485760 ? 1 : 0) + ' MB'; }
  function pathbox(input) {
    if (input.dataset.cdtDone || plain(input)) return;
    input.dataset.cdtDone = '1';
    const accept = (input.accept || '').split(',').map((s) => s.trim().toLowerCase()).filter(Boolean);
    const hint = accept.length ? accept.filter((a) => a.startsWith('.')).join(', ').replace(/\./g, '').toUpperCase() || (accept.some((a) => a.startsWith('image')) ? 'images' : '') : '';
    const box = el('label', 'cdt-path');
    input.parentNode.insertBefore(box, input);
    const text = el('span', 'cdt-path-text');
    const btn = el('span', 'cdt-btn sm', 'Browse');
    box.append(el('span', 'cdt-path-glyph', DOC), text, btn, input);
    const idle = () => `Drop ${input.multiple ? 'files' : 'a file'} here or browse${hint ? ' · ' + esc(hint) : ''}`;
    const ok = (f) => !accept.length || accept.some((a) => a.startsWith('.') ? f.name.toLowerCase().endsWith(a) : a.endsWith('/*') ? (f.type || '').startsWith(a.slice(0, -1)) : f.type === a);
    function paint() {
      const fs = [...input.files];
      box.classList.remove('bad');
      input.setCustomValidity('');
      if (!fs.length) { text.innerHTML = idle(); return; }
      const bad = fs.find((f) => !ok(f));
      if (bad) {
        const why = `${bad.name} is not a kind of file this takes${hint ? ' (' + hint + ')' : ''}.`;
        box.classList.add('bad'); text.innerHTML = `<span style="color:var(--cdt-danger)">${esc(why)}</span>`; input.setCustomValidity(why); return;
      }
      text.innerHTML = fs.length === 1 ? `<b>${esc(fs[0].name)}</b> · ${size(fs[0].size)}` : `<b>${fs.length} files</b> · ${size(fs.reduce((a, f) => a + f.size, 0))}`;
    }
    paint();
    input.addEventListener('change', paint);
    box.addEventListener('dragover', (e) => { e.preventDefault(); box.classList.add('drag'); });
    box.addEventListener('dragleave', () => box.classList.remove('drag'));
    box.addEventListener('drop', (e) => {
      e.preventDefault(); box.classList.remove('drag');
      if (!e.dataTransfer.files.length) return;
      const dt = new DataTransfer();
      [...e.dataTransfer.files].slice(0, input.multiple ? 999 : 1).forEach((f) => dt.items.add(f));
      input.files = dt.files;
      input.dispatchEvent(new Event('change', { bubbles: true }));
    });
  }

  // ---- DropDownButton and InfoTip -----------------------------------------------------------------------------
  function dropdown(btn) {
    if (btn.dataset.cdtDone) return;
    btn.dataset.cdtDone = '1';
    const menu = btn.parentNode.querySelector(':scope > .cdt-popup') || document.getElementById(btn.dataset.cdtMenu);
    if (!menu) return;
    menu.hidden = true; menu.setAttribute('role', 'menu');
    btn.setAttribute('aria-haspopup', 'menu'); btn.setAttribute('aria-expanded', 'false');
    const home = menu.parentNode;
    btn.addEventListener('click', () => {
      if (open && open.pop === menu) { close(); return; }
      show(menu, btn, () => home.appendChild(menu));
      const first = menu.querySelector('a, button'); if (first) first.focus();
    });
    menu.addEventListener('click', (e) => { if (e.target.closest('a, button')) setTimeout(close, 0); });
    menu.addEventListener('keydown', (e) => {
      const items = $$('a, button', menu), i = items.indexOf(document.activeElement);
      if (e.key === 'ArrowDown') { e.preventDefault(); items[(i + 1) % items.length].focus(); }
      if (e.key === 'ArrowUp') { e.preventDefault(); items[(i - 1 + items.length) % items.length].focus(); }
    });
  }
  let tip = null;
  function showTip(t) {
    hideTip();
    tip = el('div', 'cdt-tip');
    tip.setAttribute('role', 'tooltip');
    if (t.dataset.img) { const img = el('img'); img.src = t.dataset.img; img.alt = ''; tip.appendChild(img); img.addEventListener('load', () => tip && placeTip(t)); }
    if (t.dataset.tip) tip.appendChild(el('div', '', esc(t.dataset.tip)));
    document.body.appendChild(tip);
    placeTip(t);
  }
  function placeTip(t) {
    const r = t.getBoundingClientRect(), w = tip.offsetWidth, h = tip.offsetHeight;
    tip.style.left = Math.max(8, Math.min(r.left - 8, window.innerWidth - w - 8)) + 'px';
    tip.style.top = (r.bottom + h + 8 > window.innerHeight ? r.top - h - 6 : r.bottom + 6) + 'px';
  }
  function hideTip() { if (tip) tip.remove(); tip = null; }
  document.addEventListener('mouseover', (e) => { const t = e.target.closest && e.target.closest('.cdt-infotip'); if (t) showTip(t); });
  document.addEventListener('mouseout', (e) => { if (e.target.closest && e.target.closest('.cdt-infotip')) hideTip(); });
  document.addEventListener('focusin', (e) => { if (e.target.classList && e.target.classList.contains('cdt-infotip')) showTip(e.target); });
  document.addEventListener('focusout', (e) => { if (e.target.classList && e.target.classList.contains('cdt-infotip')) hideTip(); });

  // ---- FilterChips: a row of one-of buttons that show only the cards or rows they name ------------------------
  function chips(row) {
    if (row.dataset.cdtDone) return;
    row.dataset.cdtDone = '1';
    const target = document.querySelector(row.dataset.cdtFilters);
    if (!target) return;
    const buttons = $$('.cdt-filter-chip', row);
    buttons.forEach((b) => b.addEventListener('click', () => {
      buttons.forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
      for (const item of target.querySelectorAll('[data-chip]')) item.hidden = b.dataset.value !== '' && !item.dataset.chip.split(' ').includes(b.dataset.value);
    }));
  }

  // ---- wiring ---------------------------------------------------------------------------------------------------
  CDT.enhance = function (root = document) {
    if (!document.body.classList.contains('cdt')) return;
    $$('input[type=number]', root).forEach(numberbox);
    $$('select[multiple][data-cdt="tokens"]', root).forEach(tokenbox);
    $$('select[multiple]:not([data-cdt="tokens"])', root).forEach(checkcombo);
    $$('select:not([multiple])', root).filter((s) => s.dataset.cdt === 'search' || s.options.length >= 8).forEach(searchable);
    $$('input[type=file]', root).forEach(pathbox);
    $$('table.table, table[data-cdt="grid"]', root).forEach(grid);
    $$('[data-cdt-menu]', root).forEach(dropdown);
    $$('[data-cdt-filters]', root).forEach(chips);
  };
  const start = () => { flashes(); CDT.enhance(); };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
