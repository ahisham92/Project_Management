/* CDT web kit: the behaviour of the CDT SDK's custom controls, for the browser.
 *
 * The SDK's controls are WPF (CDT.Wpf/Controls). These are their web
 * counterparts, built as progressive enhancements over the plain HTML the
 * pages already send, so every page still works with JavaScript off:
 *
 *   InfoBar           .flash          close button; a success becomes a toast that closes itself
 *   DialogHost        onsubmit="return confirm(..)"  an in-page dialog instead of the browser's box
 *   BusyDots          any form submit  the button that sent it shows it is working
 *   ToolTip / InfoTip [title]         a themed tooltip, wrapped at 420px
 *   DropDownButton    [data-cdt-dropdown]  a button that opens a menu (the account menu)
 *   SearchableComboBox  <select> with 8+ options  type to filter word by word, highlighted, grouped, recent first
 *   CheckComboBox     .trade-picker / [data-cdt-checkcombo]  tick several in a dropdown, summed up when closed
 *   NumberBox         <input type=number>  arithmetic, units, ↑/↓ and wheel steps, a preview of what it will commit
 *   DataGridFilter    <table data-cdt-filter>  an Excel-style funnel in each header
 *   ThemeManager      [data-cdt-theme] / [data-cdt-brand]  light, dark, auto; Dar or CDT accent
 *
 * Opt out on any element with data-cdt="off". Nothing here posts anything
 * the page would not have posted without it.
 */
(function () {
  'use strict';

  var root = document.documentElement;
  var reduced = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  function off(el) { return !!(el && el.closest && el.closest('[data-cdt="off"]')); }
  function make(tag, cls, text) {
    var el = document.createElement(tag);
    if (cls) el.className = cls;
    if (text != null) el.textContent = text;
    return el;
  }
  function store(key, value) {
    try {
      if (value === undefined) return localStorage.getItem(key);
      localStorage.setItem(key, value);
    } catch (e) { return null; }
  }

  // --- ThemeManager ---------------------------------------------------------
  // The same 'pm-theme' key app.js and the <head> script use, so the old
  // toggle (signed-out pages) and this menu agree.
  function setTheme(theme) {
    store('pm-theme', theme);
    if (theme === 'system') root.removeAttribute('data-theme'); else root.setAttribute('data-theme', theme);
    var legacy = document.querySelector('[data-theme-toggle]');
    if (legacy) legacy.textContent = { system: 'Auto', light: 'Light', dark: 'Dark' }[theme];
    syncPickers();
  }
  function setBrand(brand) {
    store('cdt-brand', brand);
    if (brand === 'cdt') root.setAttribute('data-brand', 'cdt'); else root.removeAttribute('data-brand');
    syncPickers();
  }
  function syncPickers() {
    var theme = store('pm-theme') || 'system';
    var brand = store('cdt-brand') || 'dar';
    document.querySelectorAll('[data-cdt-theme]').forEach(function (b) {
      b.setAttribute('aria-pressed', String(b.getAttribute('data-cdt-theme') === theme));
    });
    document.querySelectorAll('[data-cdt-brand]').forEach(function (b) {
      b.setAttribute('aria-pressed', String(b.getAttribute('data-cdt-brand') === brand));
    });
  }
  document.addEventListener('click', function (e) {
    var t = e.target.closest('[data-cdt-theme]');
    if (t) { setTheme(t.getAttribute('data-cdt-theme')); return; }
    var b = e.target.closest('[data-cdt-brand]');
    if (b) setBrand(b.getAttribute('data-cdt-brand'));
  });

  // --- DropDownButton -----------------------------------------------------------
  var openMenu = null;
  function closeMenu(focusButton) {
    if (!openMenu) return;
    openMenu.menu.hidden = true;
    openMenu.button.setAttribute('aria-expanded', 'false');
    if (focusButton) openMenu.button.focus();
    openMenu = null;
  }
  function menuRows(menu) { return Array.prototype.slice.call(menu.querySelectorAll('.cdt-menu-row, .cdt-menu .chips button')); }
  document.addEventListener('click', function (e) {
    var button = e.target.closest('[data-cdt-dropdown]');
    if (button) {
      var menu = document.getElementById(button.getAttribute('aria-controls'));
      if (!menu) return;
      var wasOpen = openMenu && openMenu.menu === menu;
      closeMenu();
      if (!wasOpen) {
        menu.hidden = false;
        button.setAttribute('aria-expanded', 'true');
        openMenu = { button: button, menu: menu };
        syncPickers();
      }
      return;
    }
    if (openMenu && !openMenu.menu.contains(e.target)) closeMenu();
  });
  document.addEventListener('keydown', function (e) {
    if (!openMenu) return;
    if (e.key === 'Escape') { closeMenu(true); return; }
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      var rows = menuRows(openMenu.menu);
      var i = rows.indexOf(document.activeElement);
      i = e.key === 'ArrowDown' ? (i + 1) % rows.length : (i <= 0 ? rows.length - 1 : i - 1);
      if (rows[i]) rows[i].focus();
    }
  });

  // --- ToolTip / InfoTip ------------------------------------------------------
  // Plain title attributes, drawn in the theme and wrapped instead of running
  // across the screen. The title goes back on the element when the mouse
  // leaves, so it is never lost to assistive technology.
  var tip = null, tipHost = null, tipTimer = 0;
  function hideTip() {
    clearTimeout(tipTimer);
    if (tipHost && tipHost.hasAttribute('data-cdt-title')) {
      tipHost.setAttribute('title', tipHost.getAttribute('data-cdt-title'));
      tipHost.removeAttribute('data-cdt-title');
    }
    tipHost = null;
    if (tip) tip.hidden = true;
  }
  function placeTip(host) {
    if (!tip) { tip = make('div', 'cdt-tooltip'); tip.setAttribute('role', 'tooltip'); document.body.appendChild(tip); }
    tip.textContent = host.getAttribute('data-cdt-title');
    tip.hidden = false;
    var r = host.getBoundingClientRect();
    var w = tip.offsetWidth, h = tip.offsetHeight;
    var x = Math.min(Math.max(8, r.left + r.width / 2 - w / 2), window.innerWidth - w - 8);
    var y = r.bottom + 8;
    if (y + h > window.innerHeight - 8) y = r.top - h - 8;
    tip.style.left = x + 'px';
    tip.style.top = y + 'px';
  }
  document.addEventListener('mouseover', function (e) {
    var host = e.target.closest && e.target.closest('[title]');
    if (!host || host === tipHost || host instanceof SVGElement || off(host)) return;
    var text = host.getAttribute('title');
    if (!text || !text.trim()) return;
    hideTip();
    tipHost = host;
    host.setAttribute('data-cdt-title', text);
    host.removeAttribute('title');
    tipTimer = setTimeout(function () { if (tipHost === host) placeTip(host); }, 350);
  });
  document.addEventListener('mouseout', function (e) {
    if (tipHost && (!e.relatedTarget || !tipHost.contains(e.relatedTarget))) hideTip();
  });
  document.addEventListener('scroll', hideTip, true);
  document.addEventListener('mousedown', hideTip, true);

  // --- InfoBar ---------------------------------------------------------------
  var toasts = null;
  function closeBar(bar) {
    bar.classList.add('is-closing');
    setTimeout(function () { bar.remove(); }, reduced ? 0 : 200);
  }
  function enhanceBar(bar) {
    if (bar.dataset.cdtBar) return;
    bar.dataset.cdtBar = '1';
    var body = make('div', 'cdt-infobar-body');
    while (bar.firstChild) body.appendChild(bar.firstChild);
    bar.appendChild(body);
    var close = make('button', 'cdt-infobar-close', '✕');
    close.type = 'button';
    close.title = 'Close';
    close.setAttribute('aria-label', 'Close');
    close.addEventListener('click', function () { closeBar(bar); });
    bar.appendChild(close);
    // AutoCloseAfter: a success is a toast, paused while the mouse is on it.
    if (bar.classList.contains('success') && !bar.querySelector('a, form, button:not(.cdt-infobar-close)')) {
      if (!toasts) { toasts = make('div', 'cdt-toasts'); toasts.setAttribute('aria-live', 'polite'); document.body.appendChild(toasts); }
      var strip = bar.parentNode;
      toasts.appendChild(bar);
      if (strip && strip.classList.contains('flashes') && !strip.children.length) strip.remove();
      var left = 6000, started = Date.now(), timer = setTimeout(function () { closeBar(bar); }, left);
      bar.addEventListener('mouseenter', function () { clearTimeout(timer); left -= Date.now() - started; });
      bar.addEventListener('mouseleave', function () { started = Date.now(); timer = setTimeout(function () { closeBar(bar); }, Math.max(1500, left)); });
    }
  }
  /** Show an InfoBar as a toast from code: CDT.toast('Saved', 'success'). */
  function toast(message, severity) {
    var bar = make('div', 'flash ' + (severity || 'success'), message);
    bar.setAttribute('role', severity === 'error' ? 'alert' : 'status');
    if (!toasts) { toasts = make('div', 'cdt-toasts'); document.body.appendChild(toasts); }
    toasts.appendChild(bar);
    enhanceBar(bar);
    if (severity && severity !== 'success') setTimeout(function () { closeBar(bar); }, 8000);
  }

  // --- DialogHost / CdtMessageBox ------------------------------------------
  /** Ask in an in-page dialog. Resolves true for OK. */
  function ask(message, options) {
    options = options || {};
    return new Promise(function (resolve) {
      var danger = options.danger != null ? options.danger : /\b(delete|remove|discard|cannot be undone|reject|clear|erase|wipe|restore)\b/i.test(message);
      var scrim = make('div', 'cdt-scrim');
      var sheet = make('div', 'cdt-sheet' + (danger ? ' danger' : ''));
      sheet.setAttribute('role', 'alertdialog');
      sheet.setAttribute('aria-modal', 'true');
      var body = make('div', 'cdt-sheet-body');
      body.appendChild(make('div', 'cdt-sheet-glyph'));
      var words = make('div');
      var title = make('h2', null, options.title || (danger ? 'Are you sure?' : 'Please confirm'));
      title.id = 'cdt-dialog-title';
      sheet.setAttribute('aria-labelledby', title.id);
      words.appendChild(title);
      words.appendChild(make('p', null, message));
      body.appendChild(words);
      var foot = make('div', 'cdt-sheet-foot');
      var no = make('button', 'btn btn-ghost', options.cancel || 'Cancel');
      var yes = make('button', 'btn ' + (danger ? 'btn-danger-fill' : 'btn-primary'), options.ok || (danger ? guessVerb(message) : 'OK'));
      no.type = yes.type = 'button';
      foot.appendChild(no);
      foot.appendChild(yes);
      sheet.appendChild(body);
      sheet.appendChild(foot);
      scrim.appendChild(sheet);
      var before = document.activeElement;
      document.body.appendChild(scrim);
      (danger ? no : yes).focus();
      function done(answer) {
        scrim.remove();
        document.removeEventListener('keydown', keys, true);
        if (before && before.focus) before.focus();
        resolve(answer);
      }
      function keys(e) {
        if (e.key === 'Escape') { e.preventDefault(); done(false); }
        if (e.key === 'Tab') { // keep Tab inside the dialog
          e.preventDefault();
          (document.activeElement === yes ? no : yes).focus();
        }
      }
      document.addEventListener('keydown', keys, true);
      no.addEventListener('click', function () { done(false); });
      yes.addEventListener('click', function () { done(true); });
      scrim.addEventListener('mousedown', function (e) { if (e.target === scrim) done(false); });
    });
  }
  function guessVerb(message) {
    var m = /^(Delete|Remove|Discard|Reject|Clear|Restore|Erase|Close|Accept|Keep|Withdraw)\b/i.exec(message.trim());
    return m ? m[1].charAt(0).toUpperCase() + m[1].slice(1).toLowerCase() : 'Yes, go ahead';
  }

  // Pages say onsubmit="return confirm('…')". Run that code with confirm()
  // swapped for one that only records the question, then ask it in the dialog
  // and send the form (with the button that was pressed) on OK.
  function questionFrom(code, self, event) {
    var asked = null;
    var result;
    try {
      result = new Function('event', '__ask', 'var confirm = __ask; ' + code).call(self, event, function (m) { asked = String(m); return false; });
    } catch (err) { return { error: true }; }
    return { asked: asked, result: result };
  }
  document.addEventListener('submit', function (e) {
    var form = e.target;
    var code = form.getAttribute('data-cdt-confirm-code');
    if (!code) {
      var inline = form.getAttribute('onsubmit');
      if (!inline || inline.indexOf('confirm(') < 0 || off(form)) return;
      form.setAttribute('data-cdt-confirm-code', inline);
      form.removeAttribute('onsubmit');
      code = inline;
    }
    if (form.dataset.cdtConfirmed) { delete form.dataset.cdtConfirmed; return; }
    var q = questionFrom(code, form, e);
    if (q.error) return; // leave the browser to it
    if (q.asked === null) {
      if (q.result === false) { e.preventDefault(); e.stopImmediatePropagation(); }
      return;
    }
    e.preventDefault();
    e.stopImmediatePropagation();
    var submitter = e.submitter;
    ask(q.asked).then(function (yes) {
      if (!yes) return;
      form.dataset.cdtConfirmed = '1';
      if (form.requestSubmit) form.requestSubmit(submitter && submitter.form === form ? submitter : undefined);
      else form.submit();
    });
  }, true);
  // The browser runs an onsubmit attribute before any listener, so take them
  // off as soon as the page is read (and from anything added later).
  function adoptConfirms(scope) {
    scope.querySelectorAll('form[onsubmit*="confirm("]').forEach(function (form) {
      if (off(form)) return;
      form.setAttribute('data-cdt-confirm-code', form.getAttribute('onsubmit'));
      form.removeAttribute('onsubmit');
    });
    scope.querySelectorAll('[onclick*="return confirm("]').forEach(function (el) {
      if (off(el)) return;
      var code = el.getAttribute('onclick');
      el.removeAttribute('onclick');
      el.addEventListener('click', function (e) {
        if (el.dataset.cdtConfirmed) { delete el.dataset.cdtConfirmed; return; }
        var q = questionFrom(code, el, e);
        if (q.error || q.asked === null) { if (q.result === false) e.preventDefault(); return; }
        e.preventDefault();
        ask(q.asked).then(function (yes) { if (yes) { el.dataset.cdtConfirmed = '1'; el.click(); } });
      });
    });
  }

  // --- BusyDots on the button that sent a form --------------------------------
  // Listened for last, so a form app.js sends by fetch (defaultPrevented) is
  // left alone. The button is not disabled — that would drop its name/value
  // from what is sent — it only stops answering clicks.
  document.addEventListener('submit', function (e) {
    var form = e.target;
    setTimeout(function () {
      if (e.defaultPrevented || off(form) || form.target === '_blank') return;
      var button = e.submitter || form.querySelector('button[type="submit"], button:not([type])');
      if (!button || !button.classList.contains('btn') || button.classList.contains('is-busy')) return;
      button.classList.add('is-busy');
      var dots = make('span', 'cdt-busy');
      dots.setAttribute('aria-hidden', 'true');
      dots.innerHTML = '<i></i><i></i><i></i>';
      button.appendChild(dots);
      button.setAttribute('aria-busy', 'true');
      // A download keeps the page: give the button back.
      setTimeout(function () { unbusy(button); }, 6000);
    }, 0);
  });
  function unbusy(button) {
    button.classList.remove('is-busy');
    button.removeAttribute('aria-busy');
    var d = button.querySelector('.cdt-busy');
    if (d) d.remove();
  }
  window.addEventListener('pageshow', function () { document.querySelectorAll('.btn.is-busy').forEach(unbusy); });

  // --- SearchableComboBox ------------------------------------------------------
  var RECENT = 5;
  function norm(s) { return String(s || '').toLowerCase().replace(/\s+/g, ''); }
  function words(q) { return String(q || '').toLowerCase().split(/\s+/).filter(Boolean); }
  function matches(text, q) {
    var t = norm(text);
    return words(q).every(function (w) { return t.indexOf(w) >= 0; });
  }
  function highlight(text, q) {
    var frag = document.createDocumentFragment();
    var ws = words(q);
    if (!ws.length) { frag.appendChild(document.createTextNode(text)); return frag; }
    var lower = text.toLowerCase();
    var marks = new Array(text.length).fill(false);
    ws.forEach(function (w) {
      var i = lower.indexOf(w);
      if (i < 0) {
        // the word may span spaces ("ipe3" in "IPE 300")
        var compact = '', map = [];
        for (var k = 0; k < lower.length; k++) if (!/\s/.test(lower[k])) { compact += lower[k]; map.push(k); }
        var j = compact.indexOf(w);
        if (j >= 0) for (var m = j; m < j + w.length; m++) marks[map[m]] = true;
        return;
      }
      for (var n = i; n < i + w.length; n++) marks[n] = true;
    });
    var run = '', on = false;
    for (var x = 0; x <= text.length; x++) {
      var flag = x < text.length ? marks[x] : !on;
      if (flag !== on || x === text.length) {
        if (run) {
          var node = on ? make('mark', null, run) : document.createTextNode(run);
          frag.appendChild(node);
        }
        run = '';
        on = flag;
      }
      if (x < text.length) run += text[x];
    }
    return frag;
  }

  function enhanceSelect(select) {
    if (select.dataset.cdtCombo || select.multiple || select.size > 1 || off(select)) return;
    if (select.closest('.cell-form, .heads, td, .pm-hero-form, .marine-hud, .cdt-combo, [data-step-link]')) return;
    if (select.options.length < 8 && !select.hasAttribute('data-cdt-combo')) return;
    select.dataset.cdtCombo = '1';

    var wrap = make('span', 'cdt-combo');
    ['w-sm', 'w-md', 'w-lg', 'flex1', 'submits'].forEach(function (c) { if (select.classList.contains(c)) wrap.classList.add(c); });
    if (select.style.width) wrap.style.width = select.style.width;
    var face = make('button', 'cdt-combo-face');
    face.type = 'button';
    face.setAttribute('aria-haspopup', 'listbox');
    face.setAttribute('aria-expanded', 'false');
    var labelText = select.labels && select.labels[0] ? select.labels[0].textContent.trim() : (select.getAttribute('aria-label') || select.name || '');
    face.setAttribute('aria-label', labelText);
    if (select.id) { face.id = select.id + '-cdt'; }
    var faceText = make('span');
    face.appendChild(faceText);
    select.parentNode.insertBefore(wrap, select);
    wrap.appendChild(select);
    wrap.appendChild(face);
    select.hidden = true;
    select.tabIndex = -1;
    // A label pointing at the select now points at the face.
    if (select.labels) Array.prototype.forEach.call(select.labels, function (l) {
      l.addEventListener('click', function (e) { if (e.target === l) { e.preventDefault(); face.focus(); } });
    });

    function refresh() {
      var opt = select.options[select.selectedIndex];
      var text = opt ? opt.textContent.trim() : '';
      faceText.textContent = text || 'Choose…';
      faceText.classList.toggle('is-placeholder', !opt || opt.value === '');
      face.disabled = select.disabled;
      face.title = text.length > 28 ? text : '';
    }
    // Code that sets select.value keeps the face in step.
    ['value', 'selectedIndex'].forEach(function (prop) {
      var desc = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, prop);
      try {
        Object.defineProperty(select, prop, {
          configurable: true,
          get: function () { return desc.get.call(this); },
          set: function (v) { desc.set.call(this, v); refresh(); }
        });
      } catch (e) { /* old browsers: refresh on change only */ }
    });
    select.addEventListener('change', refresh);
    if (select.form) select.form.addEventListener('reset', function () { setTimeout(refresh, 0); });
    refresh();

    var pop = null, list = null, input = null, items = [], active = -1;
    var recentKey = 'cdt-recent:' + location.pathname.replace(/\/\d+/g, '/#') + ':' + (select.name || select.id);

    function recent() { try { return JSON.parse(store(recentKey) || '[]'); } catch (e) { return []; } }
    function remember(value) {
      if (!value) return;
      var r = recent().filter(function (v) { return v !== value; });
      r.unshift(value);
      store(recentKey, JSON.stringify(r.slice(0, RECENT)));
    }

    function build(q) {
      list.innerHTML = '';
      items = [];
      var opts = Array.prototype.slice.call(select.options);
      var shown = opts.filter(function (o) { return !o.hidden && matches(o.textContent, q); });
      // items that start with the first word come first
      var first = words(q)[0];
      if (first) shown.sort(function (a, b) {
        var sa = norm(a.textContent).indexOf(first) === 0 ? 0 : 1;
        var sb = norm(b.textContent).indexOf(first) === 0 ? 0 : 1;
        return sa - sb;
      });
      function addOpt(o, keyPrefix) {
        var li = make('li', 'cdt-combo-opt');
        li.setAttribute('role', 'option');
        li.id = 'cdt-opt-' + Math.random().toString(36).slice(2);
        li.setAttribute('aria-selected', String(o.selected));
        if (o.disabled) li.setAttribute('aria-disabled', 'true');
        li.appendChild(highlight(o.textContent.trim() || '—', q));
        li._opt = o;
        list.appendChild(li);
        if (!o.disabled) items.push(li);
      }
      if (!q) {
        var r = recent().map(function (v) { return opts.filter(function (o) { return o.value === v; })[0]; }).filter(Boolean);
        if (r.length && opts.length > 12) {
          list.appendChild(make('li', 'cdt-combo-group', 'Recent'));
          r.forEach(function (o) { addOpt(o); });
        }
      }
      var group = null;
      shown.forEach(function (o) {
        var g = o.parentNode.tagName === 'OPTGROUP' ? o.parentNode.label : null;
        if (!q && g && g !== group) list.appendChild(make('li', 'cdt-combo-group', g));
        group = g;
        addOpt(o);
      });
      if (!items.length) list.appendChild(make('li', 'cdt-combo-none', 'Nothing matches “' + q + '”'));
      var sel = items.findIndex(function (li) { return li._opt.selected; });
      setActive(q ? 0 : Math.max(0, sel));
    }
    function setActive(i) {
      if (!items.length) { active = -1; return; }
      active = Math.max(0, Math.min(items.length - 1, i));
      items.forEach(function (li, k) { li.classList.toggle('active', k === active); });
      var li = items[active];
      input.setAttribute('aria-activedescendant', li.id);
      var top = li.offsetTop, bottom = top + li.offsetHeight;
      if (top < list.scrollTop) list.scrollTop = top - 4;
      else if (bottom > list.scrollTop + list.clientHeight) list.scrollTop = bottom - list.clientHeight + 4;
    }
    function choose(li) {
      var o = li._opt;
      var changed = !o.selected;
      o.selected = true;
      remember(o.value);
      close(true);
      refresh();
      if (changed) {
        select.dispatchEvent(new Event('input', { bubbles: true }));
        select.dispatchEvent(new Event('change', { bubbles: true }));
      }
    }
    function open() {
      if (pop || face.disabled) return;
      pop = make('div', 'cdt-combo-pop');
      var search = make('div', 'cdt-combo-search');
      input = make('input');
      input.type = 'text';
      input.placeholder = 'Search…';
      input.setAttribute('aria-label', 'Search ' + labelText);
      input.setAttribute('role', 'combobox');
      input.setAttribute('aria-expanded', 'true');
      input.setAttribute('autocomplete', 'off');
      search.appendChild(input);
      list = make('ul', 'cdt-combo-list');
      list.setAttribute('role', 'listbox');
      list.id = 'cdt-list-' + Math.random().toString(36).slice(2);
      input.setAttribute('aria-controls', list.id);
      pop.appendChild(search);
      pop.appendChild(list);
      wrap.appendChild(pop);
      face.setAttribute('aria-expanded', 'true');
      // open upwards when there is no room below
      var r = face.getBoundingClientRect();
      if (window.innerHeight - r.bottom < 340 && r.top > 340) pop.classList.add('up');
      build('');
      input.focus();
      input.addEventListener('input', function () { build(input.value); });
      input.addEventListener('keydown', function (e) {
        if (e.key === 'ArrowDown') { e.preventDefault(); setActive(active + 1); }
        else if (e.key === 'ArrowUp') { e.preventDefault(); setActive(active - 1); }
        else if (e.key === 'PageDown') { e.preventDefault(); setActive(active + 8); }
        else if (e.key === 'PageUp') { e.preventDefault(); setActive(active - 8); }
        else if (e.key === 'Enter') { e.preventDefault(); if (items[active]) choose(items[active]); }
        else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(true); }
        else if (e.key === 'Tab') { close(false); }
      });
      list.addEventListener('mousedown', function (e) { e.preventDefault(); });
      list.addEventListener('click', function (e) {
        var li = e.target.closest('.cdt-combo-opt');
        if (li && li.getAttribute('aria-disabled') !== 'true') choose(li);
      });
      list.addEventListener('mousemove', function (e) {
        var li = e.target.closest('.cdt-combo-opt');
        var i = items.indexOf(li);
        if (i >= 0 && i !== active) { active = i; items.forEach(function (x, k) { x.classList.toggle('active', k === i); }); }
      });
      setTimeout(function () { document.addEventListener('mousedown', outside, true); }, 0);
    }
    function outside(e) { if (pop && !wrap.contains(e.target)) close(false); }
    function close(focus) {
      if (!pop) return;
      pop.remove();
      pop = null;
      face.setAttribute('aria-expanded', 'false');
      document.removeEventListener('mousedown', outside, true);
      if (focus) face.focus();
    }
    face.addEventListener('click', function () { if (pop) close(true); else open(); });
    face.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp' || e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); }
      else if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) { open(); input.value = e.key; build(e.key); e.preventDefault(); }
    });
  }

  // --- CheckComboBox -----------------------------------------------------------
  // A fieldset of check boxes (the house's .trade-picker) folded into a
  // dropdown that sums up what is ticked: "Civil, Marine", "All", "None",
  // "3 of 7". The boxes stay in the form, so what is sent is unchanged.
  function enhanceChecks(host) {
    if (host.dataset.cdtChecks || off(host)) return;
    var boxes = host.querySelectorAll('input[type="checkbox"]');
    if (boxes.length < 4) return;
    host.dataset.cdtChecks = '1';
    var legend = host.querySelector('legend');
    var holder = host.querySelector('.checks') || host;
    var wrap = make('span', 'cdt-combo');
    var face = make('button', 'cdt-combo-face');
    face.type = 'button';
    face.setAttribute('aria-haspopup', 'true');
    face.setAttribute('aria-expanded', 'false');
    if (legend) face.setAttribute('aria-label', legend.textContent.trim());
    var text = make('span');
    face.appendChild(text);
    var pop = make('div', 'cdt-combo-pop');
    pop.hidden = true;
    var list = make('div', 'cdt-combo-list');
    var foot = make('div', 'cdt-combo-foot');
    var all = make('button', 'btn-link', 'Select all');
    var none = make('button', 'btn-link', 'Clear');
    all.type = none.type = 'button';
    all.className = none.className = 'btn btn-link';
    foot.appendChild(all);
    foot.appendChild(none);
    holder.parentNode.insertBefore(wrap, holder);
    wrap.appendChild(face);
    wrap.appendChild(pop);
    pop.appendChild(list);
    pop.appendChild(foot);
    Array.prototype.forEach.call(holder.querySelectorAll('label, .check'), function (l) {
      if (l.querySelector('input[type="checkbox"]')) { l.classList.add('cdt-combo-opt'); list.appendChild(l); }
    });
    if (holder !== host && !holder.children.length) holder.remove();
    function sum() {
      var on = [];
      boxes.forEach(function (b) { if (b.checked) on.push((b.closest('label') || b.parentNode).textContent.trim()); });
      var t = !on.length ? 'None' : on.length === boxes.length ? 'All (' + boxes.length + ')' : on.length <= 2 ? on.join(', ') : on.length + ' of ' + boxes.length;
      text.textContent = t;
      text.classList.toggle('is-placeholder', !on.length);
    }
    boxes.forEach(function (b) { b.addEventListener('change', sum); });
    all.addEventListener('click', function () { boxes.forEach(function (b) { if (!b.checked) { b.checked = true; b.dispatchEvent(new Event('change', { bubbles: true })); } }); });
    none.addEventListener('click', function () { boxes.forEach(function (b) { if (b.checked) { b.checked = false; b.dispatchEvent(new Event('change', { bubbles: true })); } }); });
    function toggle(show) {
      pop.hidden = !show;
      face.setAttribute('aria-expanded', String(show));
      if (show) {
        var r = face.getBoundingClientRect();
        pop.classList.toggle('up', window.innerHeight - r.bottom < 300 && r.top > 300);
      }
    }
    face.addEventListener('click', function () { toggle(pop.hidden); });
    document.addEventListener('mousedown', function (e) { if (!pop.hidden && !wrap.contains(e.target)) toggle(false); }, true);
    wrap.addEventListener('keydown', function (e) { if (e.key === 'Escape' && !pop.hidden) { e.stopPropagation(); toggle(false); face.focus(); } });
    if (host.form) host.form.addEventListener('reset', function () { setTimeout(sum, 0); });
    sum();
  }

  // --- NumberBox -------------------------------------------------------------
  // Takes arithmetic (6000/4 + 25), reads '.' everywhere, steps with ↑/↓, Page
  // Up/Down (x10), the wheel and its spin buttons (Shift for a tenth), shows
  // what it will commit while you type, and commits on Enter or leaving the
  // field (Esc goes back). The page still receives a plain number.
  function evaluate(text) {
    var s = String(text).trim().replace(/,/g, '.').replace(/[×x]/g, '*').replace(/÷/g, '/');
    if (s === '') return { empty: true };
    if (!/^[0-9.+\-*/()\s eE]+$/.test(s)) return { bad: 'Only numbers and + − × ÷ ( )' };
    // a tiny recursive-descent parser: no eval
    var i = 0;
    function ws() { while (s[i] === ' ') i++; }
    function num() {
      ws();
      var m = /^(\d+\.?\d*|\.\d+)([eE][+\-]?\d+)?/.exec(s.slice(i));
      if (!m) throw 0;
      i += m[0].length;
      return parseFloat(m[0]);
    }
    function factor() {
      ws();
      if (s[i] === '-') { i++; return -factor(); }
      if (s[i] === '+') { i++; return factor(); }
      if (s[i] === '(') { i++; var v = expr(); ws(); if (s[i] !== ')') throw 0; i++; return v; }
      return num();
    }
    function term() { var v = factor(); for (;;) { ws(); if (s[i] === '*') { i++; v *= factor(); } else if (s[i] === '/') { i++; v /= factor(); } else return v; } }
    function expr() { var v = term(); for (;;) { ws(); if (s[i] === '+') { i++; v += term(); } else if (s[i] === '-') { i++; v -= term(); } else return v; } }
    try {
      var v = expr();
      ws();
      if (i !== s.length || !isFinite(v)) throw 0;
      return { value: v, expression: /[+*/()]|.-/.test(s.replace(/^-/, '').replace(/[eE][+\-]/g, '')) };
    } catch (e) { return { bad: 'Not a number' }; }
  }
  function decimalsOf(step) {
    var t = String(step);
    return t.indexOf('.') >= 0 ? t.split('.')[1].length : 0;
  }
  function enhanceNumber(input) {
    if (input.dataset.cdtNumber || off(input)) return;
    if (input.closest('.cell-form, .heads, .tick, td, .pm-hero-form, .marine-hud, [data-step-link]') || input.classList.contains('heads') || input.classList.contains('cell-input')) return;
    input.dataset.cdtNumber = '1';
    var min = input.min !== '' ? parseFloat(input.min) : null;
    var max = input.max !== '' ? parseFloat(input.max) : null;
    var stepAttr = input.getAttribute('step');
    var step = stepAttr && stepAttr !== 'any' ? parseFloat(stepAttr) : 1;
    var decimals = stepAttr === 'any' ? null : decimalsOf(stepAttr || 1);
    var unit = input.getAttribute('data-unit');
    var wrap = make('span', 'cdt-number');
    ['w-sm', 'w-md', 'w-lg', 'flex1'].forEach(function (c) { if (input.classList.contains(c)) wrap.classList.add(c); });
    if (input.style.width) { wrap.style.width = input.style.width; input.style.width = ''; }
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);
    input.type = 'text';
    input.setAttribute('inputmode', 'decimal');
    input.setAttribute('autocomplete', 'off');
    if (unit) {
      wrap.classList.add('has-unit');
      var u = make('span', 'cdt-number-unit', unit);
      wrap.appendChild(u);
      wrap.style.setProperty('--cdt-unit-w', (unit.length * 0.6 + 0.4) + 'em');
    }
    var spin = make('span', 'cdt-number-spin');
    var up = make('button', null, '▲'), down = make('button', null, '▼');
    up.type = down.type = 'button';
    up.tabIndex = down.tabIndex = -1;
    up.setAttribute('aria-label', 'Increase');
    down.setAttribute('aria-label', 'Decrease');
    spin.appendChild(up);
    spin.appendChild(down);
    wrap.appendChild(spin);
    var preview = null, committed = input.value;

    function fmt(v) {
      if (decimals != null) v = parseFloat(v.toFixed(decimals));
      else v = parseFloat(v.toPrecision(12));
      return String(v);
    }
    function check(v) {
      if (min != null && v < min) return 'At least ' + min + (unit ? ' ' + unit : '');
      if (max != null && v > max) return 'At most ' + max + (unit ? ' ' + unit : '');
      return '';
    }
    function show(text, bad) {
      if (!text) { if (preview) { preview.remove(); preview = null; } return; }
      if (!preview) { preview = make('span', 'cdt-number-preview'); wrap.appendChild(preview); }
      preview.textContent = text;
      preview.classList.toggle('bad', !!bad);
    }
    function validate() {
      var r = evaluate(input.value);
      var msg = r.bad || (r.empty ? '' : check(r.value));
      input.setCustomValidity(msg);
      input.setAttribute('aria-invalid', msg ? 'true' : 'false');
      return r;
    }
    function commit() {
      var r = validate();
      if (!r.bad && !r.empty) input.value = fmt(r.value);
      validate();
      show('');
      if (input.value !== committed) {
        committed = input.value;
        input.dispatchEvent(new Event('change', { bubbles: true }));
      }
    }
    function bump(dir, e) {
      if (input.disabled || input.readOnly) return;
      var r = evaluate(input.value);
      var base = r.value != null ? r.value : (min != null ? min : 0);
      var by = step * (e && e.shiftKey ? 0.1 : 1) * (e && e.big ? 10 : 1);
      var v = base + dir * by;
      if (min != null) v = Math.max(min, v);
      if (max != null) v = Math.min(max, v);
      input.value = fmt(v);
      input.dispatchEvent(new Event('input', { bubbles: true }));
      commit();
    }
    input.addEventListener('input', function (e) {
      if (e.isTrusted === false) return;
      var r = validate();
      if (r.bad) show(r.bad, true);
      else if (r.expression) show('= ' + fmt(r.value) + (unit ? ' ' + unit : ''), !!check(r.value));
      else if (!r.empty && check(r.value)) show(check(r.value), true);
      else show('');
    });
    input.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowUp') { e.preventDefault(); bump(1, e); }
      else if (e.key === 'ArrowDown') { e.preventDefault(); bump(-1, e); }
      else if (e.key === 'PageUp') { e.preventDefault(); bump(1, { big: true }); }
      else if (e.key === 'PageDown') { e.preventDefault(); bump(-1, { big: true }); }
      else if (e.key === 'Enter') { commit(); }
      else if (e.key === 'Escape' && input.value !== committed) { e.preventDefault(); input.value = committed; validate(); show(''); }
    });
    input.addEventListener('blur', commit);
    input.addEventListener('wheel', function (e) {
      if (document.activeElement !== input) return;
      e.preventDefault();
      bump(e.deltaY < 0 ? 1 : -1, e);
    }, { passive: false });
    up.addEventListener('click', function (e) { bump(1, e); input.focus(); });
    down.addEventListener('click', function (e) { bump(-1, e); input.focus(); });
    if (input.form) input.form.addEventListener('submit', function () { commit(); }, true);
  }

  // --- DataGridFilter -----------------------------------------------------------
  // <table data-cdt-filter>: a funnel in each header opens the column's values
  // with their counts, a search box and Select all; filters on several
  // columns combine. data-cdt-filter="off" on a <th> leaves that column out.
  function cellText(cell) {
    if (!cell) return '';
    var t = (cell.getAttribute('data-filter') || cell.innerText || '').split('\n')[0].trim();
    return t || '(blank)';
  }
  function enhanceTable(table) {
    if (table.dataset.cdtGrid || off(table)) return;
    var head = table.tHead && table.tHead.rows[table.tHead.rows.length - 1];
    var body = table.tBodies[0];
    if (!head || !body || body.rows.length < 4) return;
    table.dataset.cdtGrid = '1';
    var filters = {}; // column index -> Set of allowed values
    var bar = make('div', 'cdt-filter-bar');
    bar.hidden = true;
    var scroller = table.closest('.table-scroll') || table;
    scroller.parentNode.insertBefore(bar, scroller);

    function rows() { return Array.prototype.filter.call(body.rows, function (r) { return r.cells.length >= head.cells.length - 1; }); }
    function apply() {
      var all = rows(), shown = 0;
      all.forEach(function (r) {
        var ok = Object.keys(filters).every(function (c) { return filters[c].has(cellText(r.cells[c])); });
        r.classList.toggle('cdt-filtered-out', !ok);
        if (ok) shown++;
      });
      var n = Object.keys(filters).length;
      bar.hidden = !n;
      bar.innerHTML = '';
      if (n) {
        bar.appendChild(make('span', null, 'Showing ' + shown + ' of ' + all.length + ' rows'));
        Object.keys(filters).forEach(function (c) {
          var chip = make('span', 'cdt-chip active', head.cells[c].innerText.trim() + ': ' + filters[c].size);
          var x = make('button', 'cdt-chip-x', '✕');
          x.type = 'button';
          x.setAttribute('aria-label', 'Clear this filter');
          x.addEventListener('click', function () { delete filters[c]; mark(); apply(); });
          chip.appendChild(x);
          bar.appendChild(chip);
        });
        var clear = make('button', 'btn btn-link', 'Clear filters');
        clear.type = 'button';
        clear.addEventListener('click', function () { filters = {}; mark(); apply(); });
        bar.appendChild(clear);
      }
    }
    function mark() {
      Array.prototype.forEach.call(head.cells, function (th, i) {
        var f = th.querySelector('.cdt-funnel');
        if (f) { f.classList.toggle('on', !!filters[i]); f.setAttribute('aria-pressed', String(!!filters[i])); }
      });
    }
    Array.prototype.forEach.call(head.cells, function (th, col) {
      if (th.getAttribute('data-cdt-filter') === 'off' || th.colSpan > 1 || !th.innerText.trim()) return;
      var f = make('button', 'cdt-funnel');
      f.type = 'button';
      f.title = 'Filter ' + th.innerText.trim();
      f.setAttribute('aria-label', f.title);
      th.appendChild(f);
      f.addEventListener('click', function (e) { e.preventDefault(); e.stopPropagation(); openFilter(th, col, f); });
    });

    var pop = null, openedAt = 0;
    function closeFilter() { if (pop) { pop.remove(); pop = null; document.removeEventListener('mousedown', away, true); } }
    function away(e) { if (pop && !pop.contains(e.target)) closeFilter(); }
    function openFilter(th, col, f) {
      closeFilter();
      openedAt = Date.now();
      var counts = new Map();
      rows().forEach(function (r) {
        // count among rows the *other* filters let through
        var ok = Object.keys(filters).every(function (c) { return +c === col || filters[c].has(cellText(r.cells[c])); });
        if (!ok) return;
        var v = cellText(r.cells[col]);
        counts.set(v, (counts.get(v) || 0) + 1);
      });
      var values = Array.from(counts.keys()).sort(function (a, b) { return a.localeCompare(b, undefined, { numeric: true }); });
      var chosen = new Set(filters[col] || values);
      pop = make('div', 'cdt-combo-pop cdt-filter-pop');
      var search = make('div', 'cdt-combo-search');
      var input = make('input');
      input.type = 'text';
      input.placeholder = 'Search values…';
      input.setAttribute('aria-label', 'Search the values of ' + th.innerText.trim());
      search.appendChild(input);
      var list = make('div', 'cdt-combo-list');
      var foot = make('div', 'cdt-combo-foot');
      var okB = make('button', 'btn btn-primary btn-sm', 'Apply'), clr = make('button', 'btn btn-ghost btn-sm', 'Clear');
      okB.type = clr.type = 'button';
      foot.appendChild(clr);
      foot.appendChild(okB);
      pop.appendChild(search);
      pop.appendChild(list);
      pop.appendChild(foot);
      function draw() {
        list.innerHTML = '';
        var q = input.value;
        var shown = values.filter(function (v) { return matches(v, q); });
        var allRow = make('label', 'cdt-combo-opt');
        var allBox = make('input');
        allBox.type = 'checkbox';
        allBox.checked = shown.every(function (v) { return chosen.has(v); });
        allRow.appendChild(allBox);
        allRow.appendChild(make('b', null, '(Select all)'));
        allBox.addEventListener('change', function () { shown.forEach(function (v) { if (allBox.checked) chosen.add(v); else chosen.delete(v); }); draw(); });
        list.appendChild(allRow);
        shown.forEach(function (v) {
          var row = make('label', 'cdt-combo-opt');
          var box = make('input');
          box.type = 'checkbox';
          box.checked = chosen.has(v);
          box.addEventListener('change', function () { if (box.checked) chosen.add(v); else chosen.delete(v); allBox.checked = shown.every(function (x) { return chosen.has(x); }); });
          var name = make('span');
          name.style.flex = '1';
          name.appendChild(highlight(v, q));
          row.appendChild(box);
          row.appendChild(name);
          row.appendChild(make('span', 'kit-key', String(counts.get(v))));
          list.appendChild(row);
        });
        if (!shown.length) list.appendChild(make('div', 'cdt-combo-none', 'No values match'));
      }
      input.addEventListener('input', draw);
      input.addEventListener('keydown', function (e) { if (e.key === 'Escape') closeFilter(); if (e.key === 'Enter') okB.click(); });
      okB.addEventListener('click', function () {
        if (chosen.size === values.length) delete filters[col]; else filters[col] = new Set(chosen);
        closeFilter(); mark(); apply();
      });
      clr.addEventListener('click', function () { delete filters[col]; closeFilter(); mark(); apply(); });
      draw();
      document.body.appendChild(pop);
      var r = f.getBoundingClientRect();
      var left = Math.min(r.left, window.innerWidth - pop.offsetWidth - 8);
      var top = r.bottom + 4;
      if (top + pop.offsetHeight > window.innerHeight - 8) top = Math.max(8, r.top - pop.offsetHeight - 4);
      pop.style.left = Math.max(8, left) + 'px';
      pop.style.top = top + 'px';
      input.focus();
      setTimeout(function () { document.addEventListener('mousedown', away, true); }, 0);
    }
    window.addEventListener('scroll', function () { if (pop && Date.now() - openedAt > 400) closeFilter(); }, { passive: true });
  }

  // --- wiring: now, and for whatever the page adds later -----------------------
  function enhance(scope) {
    scope = scope || document;
    adoptConfirms(scope);
    scope.querySelectorAll('.flash').forEach(enhanceBar);
    scope.querySelectorAll('select').forEach(enhanceSelect);
    scope.querySelectorAll('input[type="number"]').forEach(enhanceNumber);
    scope.querySelectorAll('fieldset.trade-picker, [data-cdt-checkcombo]').forEach(enhanceChecks);
    scope.querySelectorAll('table[data-cdt-filter]').forEach(enhanceTable);
  }
  var queued = false;
  var WATCH = 'select, input[type="number"], .flash, table[data-cdt-filter], form[onsubmit], [onclick], fieldset.trade-picker, [data-cdt-checkcombo]';
  function relevant(m) {
    return Array.prototype.some.call(m.addedNodes, function (n) {
      return n.nodeType === 1 && !n.closest('.cdt-combo, .cdt-tooltip, .cdt-scrim, .cdt-filter-pop') && (n.matches(WATCH) || n.querySelector(WATCH));
    });
  }
  new MutationObserver(function (list) {
    if (queued) return;
    if (!list.some(relevant)) return;
    queued = true;
    requestAnimationFrame(function () { queued = false; enhance(document); });
  }).observe(document.body, { childList: true, subtree: true });

  enhance(document);
  syncPickers();
  if (store('cdt-brand') === 'cdt') root.setAttribute('data-brand', 'cdt');

  window.CDT = { ask: ask, toast: toast, setTheme: setTheme, setBrand: setBrand, evaluate: evaluate, enhance: enhance };
})();
