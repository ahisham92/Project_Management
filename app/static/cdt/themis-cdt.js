/* THEMIS's web port of the CDT SDK's WPF controls (CDT.Wpf, Dar Structural
 * Computational Design). The SDK draws them in WPF; this draws the same
 * controls, with the same behaviour and the same theme tokens, in the browser,
 * on THEMIS pages only (body.themis-app). Each part is named after the control
 * it ports:
 *
 *   ThemeManager      Light / Dark / Auto and the Dar / CDT brand, switched live
 *   DialogHost        a dialog inside the page, on the CDT scrim, in place of
 *                     the browser's confirm() and alert()
 *   InfoBar           flash messages as glyph + word + colour, closable; a
 *                     success one is a toast that closes itself (paused under
 *                     the mouse), as InfoBar.AutoCloseAfter
 *   BusyDots          the header's "Saving…" while answers go in the background
 *   DataGridFilter    sort chevrons and an Excel-style funnel on each column of
 *                     THEMIS's tables, values with counts, search, Select all
 *   SearchableComboBox  long lists searchable word by word, matches
 *                     highlighted, the last five choices pinned under Recent
 *   StepIndicator     the steps of a multi-step form, done ones ticked
 *   ToggleSwitch      settings that hold an issue, as switches
 *   Kbd               keyboard hints on the question cards: 1–9 pick, Enter
 *                     goes on
 *   ToolTip           the implicit themed tooltip, wrapped at 420px
 *   Avatar            the signed-in person's initials
 *
 * No library, no build step: plain script, loaded deferred.
 */
(function () {
  "use strict";
  var body = document.body;
  if (!body || !body.classList.contains("themis-app")) return;
  var root = document.documentElement;

  function el(tag, cls, html) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html != null) e.innerHTML = html;
    return e;
  }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function store(key, value) {
    try {
      if (arguments.length > 1) { if (value == null) localStorage.removeItem(key); else localStorage.setItem(key, value); return value; }
      return localStorage.getItem(key);
    } catch (e) { return null; }
  }
  var reduced = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;

  var CDT = window.CDT = {};

  // --- ThemeManager: theme and brand ------------------------------------------------

  var THEMES = [["system", "Auto"], ["light", "Light"], ["dark", "Dark"]];
  var BRANDS = [["dar", "Dar"], ["cdt", "CDT"]];
  function applyTheme(t) {
    store("pm-theme", t);
    if (t === "system") root.removeAttribute("data-theme"); else root.setAttribute("data-theme", t);
    var old = document.querySelector("[data-theme-toggle]");
    if (old) old.textContent = { system: "Auto", light: "Light", dark: "Dark" }[t];
    paintBar();
  }
  function applyBrand(b) {
    store("cdt-brand", b === "dar" ? null : b);
    if (b === "dar") root.removeAttribute("data-cdt-brand"); else root.setAttribute("data-cdt-brand", b);
    paintBar();
  }
  CDT.applyTheme = applyTheme;
  CDT.applyBrand = applyBrand;
  var bar = null;
  function segmented(items, current, label, onPick, extra) {
    var seg = el("div", "cdt-segmented " + (extra || ""));
    seg.setAttribute("role", "group");
    seg.setAttribute("aria-label", label);
    items.forEach(function (it) {
      var b = el("button", null, esc(it[1]));
      b.type = "button";
      b.setAttribute("data-value", it[0]);
      b.setAttribute("aria-pressed", it[0] === current ? "true" : "false");
      b.addEventListener("click", function () { onPick(it[0]); });
      seg.appendChild(b);
    });
    // Arrow keys move between the segments, as in CDT.SegmentedList.
    seg.addEventListener("keydown", function (e) {
      if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
      var bs = Array.prototype.slice.call(seg.children), i = bs.indexOf(document.activeElement);
      if (i < 0) return;
      e.preventDefault();
      var to = bs[(i + (e.key === "ArrowRight" ? 1 : bs.length - 1)) % bs.length];
      to.focus(); to.click();
    });
    return seg;
  }
  function paintBar() {
    if (!bar) return;
    var t = store("pm-theme") || "system", b = root.getAttribute("data-cdt-brand") || "dar";
    Array.prototype.forEach.call(bar.querySelectorAll(".cdt-theme-seg button"), function (x) { x.setAttribute("aria-pressed", x.getAttribute("data-value") === t ? "true" : "false"); });
    Array.prototype.forEach.call(bar.querySelectorAll(".cdt-brand-seg button"), function (x) { x.setAttribute("aria-pressed", x.getAttribute("data-value") === b ? "true" : "false"); });
  }
  function themeBar() {
    var old = document.querySelector(".topbar [data-theme-toggle]");
    if (!old) return;
    bar = el("div", "cdt-themebar");
    bar.appendChild(segmented(THEMES, store("pm-theme") || "system", "Theme", applyTheme, "cdt-theme-seg"));
    bar.appendChild(segmented(BRANDS, root.getAttribute("data-cdt-brand") || "dar", "Brand", applyBrand, "cdt-brand-seg"));
    bar.querySelector(".cdt-theme-seg").title = "Theme: follow the system, or always light or dark";
    bar.querySelector(".cdt-brand-seg").title = "Colours: Dar teal or CDT blue";
    old.hidden = true;
    old.parentNode.insertBefore(bar, old);
    paintBar();
  }

  // --- Avatar -------------------------------------------------------------------

  function avatar() {
    var who = document.querySelector(".topbar .whoami");
    if (!who || who.querySelector(".cdt-avatar")) return;
    var name = (who.textContent || "").trim().split("\n")[0].trim();
    var initials = name.split(/\s+/).filter(Boolean).slice(0, 2).map(function (w) { return w[0]; }).join("").toUpperCase();
    if (!initials) return;
    var a = el("span", "cdt-avatar", esc(initials));
    a.setAttribute("aria-hidden", "true");
    who.insertBefore(a, who.firstChild);
  }

  // --- InfoBar and toasts ------------------------------------------------------------

  var SEVERITY = {
    success: ["success", "✓", "Done"], error: ["error", "!", "Error"], notice: ["warning", "!", "Note"],
    warning: ["warning", "!", "Warning"], info: ["info", "i", "Info"]
  };
  function severityOf(flash) {
    for (var k in SEVERITY) if (flash.classList.contains(k)) return SEVERITY[k];
    return SEVERITY.info;
  }
  function infobar(flash) {
    if (flash.classList.contains("cdt-infobar") || flash.closest(".cdt-sheet")) return;
    var s = severityOf(flash);
    var msg = el("div", "cdt-infobar-msg");
    while (flash.firstChild) msg.appendChild(flash.firstChild);
    var text = (msg.textContent || "").trim();
    // A message that already starts with the word keeps it once.
    var title = new RegExp("^" + s[2] + "\\b", "i").test(text) ? "" : s[2];
    if (title) msg.insertBefore(el("span", "cdt-infobar-title", esc(title)), msg.firstChild);
    var glyph = el("span", "cdt-infobar-glyph", s[1]);
    glyph.setAttribute("aria-hidden", "true");
    var close = el("button", "cdt-infobar-close", "×");
    close.type = "button";
    close.title = "Close";
    close.setAttribute("aria-label", "Close this message");
    close.addEventListener("click", function () { flash.remove(); });
    flash.classList.add("cdt-infobar");
    flash.setAttribute("data-severity", s[0]);
    flash.appendChild(glyph); flash.appendChild(msg); flash.appendChild(close);
  }
  var toasts = null;
  function toastHost() {
    if (!toasts) { toasts = el("div", "cdt-toasts"); toasts.setAttribute("aria-live", "polite"); body.appendChild(toasts); }
    return toasts;
  }
  // A toast closes itself after a while, the clock paused under the mouse.
  function autoClose(node, ms) {
    var left = ms, started = Date.now(), timer = null;
    function run() { started = Date.now(); timer = setTimeout(function () { node.remove(); }, left); }
    node.addEventListener("mouseenter", function () { clearTimeout(timer); left -= Date.now() - started; });
    node.addEventListener("mouseleave", run);
    run();
  }
  CDT.toast = function (message, severity, ms) {
    var f = el("div", "flash " + (severity || "info"), message);
    f.setAttribute("role", severity === "error" ? "alert" : "status");
    infobar(f);
    toastHost().appendChild(f);
    autoClose(f, ms || (severity === "error" ? 9000 : 5000));
    return f;
  };
  function flashes() {
    Array.prototype.forEach.call(document.querySelectorAll("main .flashes > .flash"), function (f) {
      var plain = f.classList.contains("success") && !f.querySelector("a, button, form");
      infobar(f);
      // A plain "done" needs no room on the page: it becomes a toast.
      if (plain) { toastHost().appendChild(f); autoClose(f, 6000); }
    });
    var host = document.querySelector("main .flashes");
    if (host && !host.children.length) host.remove();
  }

  // --- DialogHost: confirm and alert inside the page ----------------------------------------

  var dialogOpen = false;
  CDT.confirm = function (message, opts) {
    opts = opts || {};
    return new Promise(function (resolve) {
      var danger = opts.danger != null ? opts.danger : /\b(delete|remove|take .* out|throw away|reject|close the idc|out of the)/i.test(message);
      var scrim = el("div", "cdt-scrim");
      var sheet = el("div", "cdt-sheet");
      sheet.setAttribute("role", "alertdialog");
      sheet.setAttribute("aria-modal", "true");
      sheet.setAttribute("data-kind", danger ? "danger" : "accent");
      var title = opts.title || (danger ? "Are you sure?" : "Confirm");
      sheet.innerHTML = '<div class="cdt-sheet-head"><span class="cdt-sheet-glyph" aria-hidden="true">' + (danger ? "!" : "?") + "</span>" +
        '<div><h2 id="cdt-dlg-t">' + esc(title) + '</h2><p id="cdt-dlg-m">' + esc(message) + "</p></div></div>" +
        '<div class="cdt-sheet-actions">' +
        (opts.alert ? "" : '<button type="button" class="btn btn-ghost" data-no>' + esc(opts.no || "Cancel") + "</button>") +
        '<button type="button" class="btn ' + (danger && !opts.alert ? "cdt-btn-danger" : "btn-primary") + '" data-yes>' + esc(opts.yes || (opts.alert ? "OK" : danger ? "Yes, go ahead" : "OK")) + "</button></div>";
      sheet.setAttribute("aria-labelledby", "cdt-dlg-t");
      sheet.setAttribute("aria-describedby", "cdt-dlg-m");
      scrim.appendChild(sheet);
      var back = document.activeElement;
      body.appendChild(scrim);
      dialogOpen = true;
      function done(v) {
        dialogOpen = false;
        document.removeEventListener("keydown", keys, true);
        scrim.remove();
        if (back && back.focus) try { back.focus({ preventScroll: true }); } catch (e) { /* gone */ }
        resolve(v);
      }
      // Tab stays inside the sheet; Esc is the negative answer; Enter the
      // default (Cancel for a dangerous one, so a stray Enter never deletes).
      function keys(e) {
        if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); done(false); return; }
        if (e.key === "Tab") {
          var bs = sheet.querySelectorAll("button"), first = bs[0], last = bs[bs.length - 1];
          if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
          else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
        }
      }
      document.addEventListener("keydown", keys, true);
      sheet.querySelector("[data-yes]").addEventListener("click", function () { done(true); });
      var no = sheet.querySelector("[data-no]");
      if (no) no.addEventListener("click", function () { done(false); });
      scrim.addEventListener("mousedown", function (e) { if (e.target === scrim) done(false); });
      (danger && no ? no : sheet.querySelector("[data-yes]")).focus();
    });
  };
  CDT.alert = function (message, title) { return CDT.confirm(message, { alert: true, title: title || "Note" }); };
  window.alert = function (message) { CDT.alert(String(message)); };

  // Submit a form again once its question is answered, with no second ask.
  CDT.resubmit = function (form, submitter) {
    form._cdtOk = true;
    var native = window.confirm;
    window.confirm = function () { return true; };
    try {
      if (form.requestSubmit) form.requestSubmit(submitter && submitter.form === form ? submitter : undefined);
      else form.submit();
    } finally {
      window.confirm = native;
      setTimeout(function () { form._cdtOk = false; }, 0);
    }
  };
  // Every form that asked with the browser's confirm() asks with the dialog
  // instead: its own inline check is run with confirm() standing in to catch
  // the question, so whatever the page worked out (a count, a name) is asked.
  function adoptConfirms(scope) {
    Array.prototype.forEach.call((scope || document).querySelectorAll("form[onsubmit]"), function (f) {
      var src = f.getAttribute("onsubmit") || "";
      if (!/confirm\(|alert\(/.test(src) || f._cdtCheck) return;
      f._cdtCheck = f.onsubmit;
      f.onsubmit = null;
      f.removeAttribute("onsubmit");
    });
  }
  window.addEventListener("submit", function (e) {
    var form = e.target;
    if (!(form instanceof HTMLFormElement) || form._cdtOk) return;
    var asked = null, verdict = true;
    if (form._cdtCheck) {
      var native = window.confirm, nativeAlert = window.alert, warned = null;
      window.confirm = function (m) { asked = String(m); return true; };
      window.alert = function (m) { warned = String(m); };
      try { verdict = form._cdtCheck.call(form, e); } finally { window.confirm = native; window.alert = nativeAlert; }
      if (warned) { e.preventDefault(); e.stopImmediatePropagation(); CDT.alert(warned); return; }
      if (verdict === false && asked == null) { e.preventDefault(); e.stopImmediatePropagation(); return; }
    }
    if (asked == null) {
      var holder = (e.submitter && e.submitter.getAttribute("data-confirm")) ? e.submitter : form;
      asked = holder.getAttribute && holder.getAttribute("data-confirm");
    }
    if (asked == null) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    var submitter = e.submitter;
    CDT.confirm(asked).then(function (ok) { if (ok) CDT.resubmit(form, submitter); });
  }, true);

  // --- BusyDots: answers saving in the background ---------------------------------

  var activity = null, inflight = 0, settle = null, failed = false;
  function activityPill() {
    if (activity) return activity;
    var spot = document.querySelector(".topbar .spacer");
    if (!spot) return null;
    activity = el("span", "cdt-activity");
    activity.setAttribute("role", "status");
    activity.setAttribute("aria-live", "polite");
    activity.hidden = true;
    spot.parentNode.insertBefore(activity, spot.nextSibling);
    return activity;
  }
  function showActivity() {
    var a = activityPill();
    if (!a) return;
    clearTimeout(settle);
    if (inflight > 0) {
      a.className = "cdt-activity is-busy";
      a.innerHTML = '<span class="cdt-busy" aria-hidden="true"><i></i><i></i><i></i></span> Saving…';
      a.hidden = false;
      return;
    }
    a.className = "cdt-activity" + (failed ? " is-bad" : "");
    a.innerHTML = '<span class="cdt-status-dot" data-state="' + (failed ? "error" : "ok") + '" aria-hidden="true"></span> ' + (failed ? "Not saved: check you are signed in" : "All changes saved");
    settle = setTimeout(function () { a.hidden = true; failed = false; }, failed ? 8000 : 2500);
  }
  if (window.fetch) {
    var nativeFetch = window.fetch;
    window.fetch = function (input, init) {
      var method = ((init && init.method) || (input && input.method) || "GET").toUpperCase();
      var p = nativeFetch.apply(this, arguments);
      if (method === "GET" || method === "HEAD") return p;
      inflight++; showActivity();
      return p.then(function (r) {
        inflight--; if (!r.ok && r.status !== 400) failed = true; showActivity(); return r;
      }, function (err) {
        inflight--; failed = true; showActivity(); throw err;
      });
    };
  }

  // --- ToolTip ----------------------------------------------------------------------

  var tip = null, tipFor = null;
  function hideTip() { if (tip) { tip.remove(); tip = null; tipFor = null; } }
  function showTip(target) {
    var text = target.getAttribute("data-cdt-tip");
    if (!text) return;
    hideTip();
    tipFor = target;
    tip = el("div", "cdt-tip");
    tip.setAttribute("role", "tooltip");
    tip.textContent = text;
    body.appendChild(tip);
    var r = target.getBoundingClientRect(), t = tip.getBoundingClientRect();
    var top = r.bottom + 8, left = Math.min(Math.max(8, r.left + r.width / 2 - t.width / 2), window.innerWidth - t.width - 8);
    if (top + t.height > window.innerHeight - 8) top = r.top - t.height - 8;
    tip.style.top = top + "px"; tip.style.left = left + "px";
  }
  function tipOf(target) {
    var t = target.closest && target.closest("[title], [data-cdt-tip]");
    if (!t || t.closest("svg") || t.closest(".cdt-sheet") || !t.closest(".themis-app")) return null;
    if (t.hasAttribute("title")) {
      var text = t.getAttribute("title");
      t.removeAttribute("title");
      if (!text) return null;
      t.setAttribute("data-cdt-tip", text);
      // An icon-only control keeps its tooltip as its accessible name.
      if (!t.getAttribute("aria-label") && !(t.textContent || "").trim()) t.setAttribute("aria-label", text);
    }
    return t;
  }
  var tipTimer = null;
  document.addEventListener("mouseover", function (e) {
    var t = tipOf(e.target);
    if (t === tipFor) return;
    clearTimeout(tipTimer);
    if (!t) { hideTip(); return; }
    tipTimer = setTimeout(function () { showTip(t); }, 350);
  });
  document.addEventListener("focusin", function (e) { var t = tipOf(e.target); if (t && e.target.matches(":focus-visible")) showTip(t); });
  document.addEventListener("focusout", hideTip);
  document.addEventListener("scroll", hideTip, true);
  document.addEventListener("mousedown", function () { clearTimeout(tipTimer); hideTip(); });

  // --- DataGridFilter: sort and filter THEMIS's tables -----------------------------------

  var FUNNEL = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 5h18l-7 8v6l-4 2v-8z"/></svg>';
  function cellText(td) { return td ? (td.textContent || "").replace(/\s+/g, " ").trim() : ""; }
  function asNumber(s) {
    var m = /^-?[\d,]*\.?\d+$/.test(s.replace(/\s/g, "")) ? parseFloat(s.replace(/[,\s]/g, "")) : NaN;
    return m;
  }
  var popOpen = null;
  function closePop() { if (popOpen) { popOpen.remove(); popOpen = null; } }
  document.addEventListener("mousedown", function (e) { if (popOpen && !popOpen.contains(e.target) && !(e.target.closest && e.target.closest(".cdt-funnel, .cdt-combo"))) closePop(); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && popOpen) { closePop(); } });

  function grid(table) {
    if (table._cdtGrid) return;
    var head = table.tHead, tb = table.tBodies[0];
    if (!head || !tb || head.rows.length !== 1) return;
    var rows = Array.prototype.slice.call(tb.rows);
    if (rows.length < 4) return;
    if (rows.some(function (r) { return Array.prototype.some.call(r.cells, function (c) { return c.colSpan > 1 || c.rowSpan > 1; }); })) return;
    table._cdtGrid = true;
    table.classList.add("cdt-grid");
    var filters = {}, sortCol = -1, sortDir = 0;
    var status = el("div", "cdt-grid-status");
    status.hidden = true;
    var host = table.closest(".table-scroll") || table;
    host.parentNode.insertBefore(status, host.nextSibling);
    function apply() {
      var shown = 0;
      rows.forEach(function (r) {
        var ok = Object.keys(filters).every(function (c) {
          var f = filters[c], t = cellText(r.cells[c]);
          return f.values ? f.values[t] : t.toLowerCase().indexOf(f.text) >= 0;
        });
        r.classList.toggle("cdt-filtered", !ok);
        r.style.display = ok ? "" : "none";
        if (ok && !r.hidden) shown++;
      });
      var n = Object.keys(filters).length;
      Array.prototype.forEach.call(head.rows[0].cells, function (th, i) {
        var f = th.querySelector(".cdt-funnel");
        if (f) { f.classList.toggle("is-on", !!filters[i]); f.setAttribute("aria-pressed", filters[i] ? "true" : "false"); }
      });
      status.hidden = !n;
      status.innerHTML = n ? "Showing " + shown + " of " + rows.length + ' rows <button type="button" class="btn btn-ghost btn-sm">Clear the filters</button>' : "";
      var clear = status.querySelector("button");
      if (clear) clear.addEventListener("click", function () { filters = {}; apply(); });
    }
    function sortBy(i) {
      sortDir = sortCol === i ? (sortDir === 1 ? -1 : sortDir === -1 ? 0 : 1) : 1;
      sortCol = sortDir ? i : -1;
      var order = rows.slice();
      if (sortDir) {
        var numeric = rows.every(function (r) { var t = cellText(r.cells[i]); return !t || t === "—" || !isNaN(asNumber(t)); });
        order.sort(function (a, b) {
          var x = cellText(a.cells[i]), y = cellText(b.cells[i]);
          if (numeric) { x = asNumber(x); y = asNumber(y); x = isNaN(x) ? -Infinity : x; y = isNaN(y) ? -Infinity : y; return (x - y) * sortDir; }
          return x.localeCompare(y, undefined, { numeric: true, sensitivity: "base" }) * sortDir;
        });
      }
      order.forEach(function (r) { tb.appendChild(r); });
      Array.prototype.forEach.call(head.rows[0].cells, function (th, k) {
        if (th.classList.contains("cdt-th")) th.setAttribute("aria-sort", k === sortCol ? (sortDir === 1 ? "ascending" : "descending") : "none");
      });
    }
    function funnel(i, th, btn) {
      closePop();
      var counts = {}, list = [];
      rows.forEach(function (r) { if (r.hidden) return; var t = cellText(r.cells[i]); if (!(t in counts)) { counts[t] = 0; list.push(t); } counts[t]++; });
      list.sort(function (a, b) { return a.localeCompare(b, undefined, { numeric: true }); });
      var pop = el("div", "cdt-pop");
      pop.setAttribute("role", "dialog");
      pop.setAttribute("aria-label", "Filter " + cellText(th));
      var many = list.length > 60, cur = filters[i];
      var picked = {};
      list.forEach(function (v) { picked[v] = !cur || (cur.values ? !!cur.values[v] : true); });
      pop.innerHTML = '<input type="search" placeholder="' + (many ? "Rows containing…" : "Search the values") + '" aria-label="Search">' +
        (many ? "" : '<div class="cdt-pop-list"></div>') +
        '<div class="cdt-pop-foot"><button type="button" class="btn btn-ghost btn-sm" data-clear>Clear</button><button type="button" class="btn btn-primary btn-sm" data-ok>Apply</button></div>';
      var q = pop.querySelector("input"), box = pop.querySelector(".cdt-pop-list");
      if (cur && cur.text) q.value = cur.text;
      function draw() {
        if (!box) return;
        var words = q.value.toLowerCase().trim();
        var vis = list.filter(function (v) { return !words || v.toLowerCase().indexOf(words) >= 0; });
        var all = vis.every(function (v) { return picked[v]; });
        box.innerHTML = '<label class="cdt-pop-row cdt-pop-all"><input type="checkbox" data-all' + (all ? " checked" : "") + "> Select all</label>" +
          vis.map(function (v) {
            return '<label class="cdt-pop-row"><input type="checkbox" data-v="' + esc(v) + '"' + (picked[v] ? " checked" : "") + "> <span>" + esc(v || "(blank)") + '</span><span class="cdt-count">' + counts[v] + "</span></label>";
          }).join("");
        box.querySelector("[data-all]").addEventListener("change", function (e) { vis.forEach(function (v) { picked[v] = e.target.checked; }); draw(); });
        Array.prototype.forEach.call(box.querySelectorAll("[data-v]"), function (c) {
          c.addEventListener("change", function () { picked[c.getAttribute("data-v")] = c.checked; });
        });
      }
      draw();
      q.addEventListener("input", draw);
      q.addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); pop.querySelector("[data-ok]").click(); } });
      pop.querySelector("[data-clear]").addEventListener("click", function () { delete filters[i]; apply(); closePop(); btn.focus(); });
      pop.querySelector("[data-ok]").addEventListener("click", function () {
        if (many) { var t = q.value.toLowerCase().trim(); if (t) filters[i] = { text: t }; else delete filters[i]; }
        else if (list.every(function (v) { return picked[v]; })) delete filters[i];
        else { var vals = {}; list.forEach(function (v) { if (picked[v]) vals[v] = true; }); filters[i] = { values: vals }; }
        apply(); closePop(); btn.focus();
      });
      body.appendChild(pop);
      var r = btn.getBoundingClientRect();
      pop.style.top = (r.bottom + window.scrollY + 4) + "px";
      pop.style.left = Math.max(8, Math.min(r.left + window.scrollX - 8, window.scrollX + document.documentElement.clientWidth - pop.offsetWidth - 8)) + "px";
      popOpen = pop;
      q.focus();
    }
    Array.prototype.forEach.call(head.rows[0].cells, function (th, i) {
      var label = cellText(th);
      if (!label || th.querySelector("a, button, input, select")) return;
      th.classList.add("cdt-th");
      th.setAttribute("aria-sort", "none");
      var wrap = el("span", "cdt-th-in");
      var s = el("button", "cdt-th-sort");
      s.type = "button";
      while (th.firstChild) s.appendChild(th.firstChild);
      s.addEventListener("click", function () { sortBy(i); });
      var f = el("button", "cdt-funnel", FUNNEL);
      f.type = "button";
      f.setAttribute("aria-label", "Filter " + label);
      f.setAttribute("data-cdt-tip", "Filter by " + label.toLowerCase());
      f.addEventListener("click", function (e) { e.stopPropagation(); if (popOpen && popOpen._for === f) { closePop(); return; } funnel(i, th, f); popOpen._for = f; });
      wrap.appendChild(s); wrap.appendChild(f);
      th.appendChild(wrap);
    });
  }
  function grids(scope) {
    Array.prototype.forEach.call((scope || document).querySelectorAll("main table"), function (t) {
      if (t.closest(".spec-doc, .spec-text, .spec-book, [contenteditable], .cdt-pop") || t.hasAttribute("data-no-grid")) return;
      grid(t);
    });
  }

  // --- SearchableComboBox ---------------------------------------------------------------

  function words(s) { return s.toLowerCase().replace(/\s+/g, " ").trim().split(" ").filter(Boolean); }
  function squash(s) { return s.toLowerCase().replace(/\s+/g, ""); }
  // "ipe 3" finds "IPE 300": every word found, spaces and case ignored.
  function matches(text, ws) { var t = squash(text); return ws.every(function (w) { return t.indexOf(w) >= 0; }); }
  function highlight(text, ws) {
    var out = esc(text);
    ws.forEach(function (w) {
      var re = new RegExp("(" + w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").split("").join("\\s*") + ")", "ig");
      out = out.replace(re, "<mark>$1</mark>");
    });
    return out;
  }
  function combo(sel) {
    if (sel._cdtCombo || sel.multiple || sel.size > 1 || sel.closest(".cdt-combo")) return;
    var opts = Array.prototype.slice.call(sel.options);
    var hasGroups = !!sel.querySelector("optgroup");
    if (opts.length < 9 && !hasGroups && !sel.hasAttribute("data-cdt-search")) return;
    if (sel.offsetParent === null && !sel.closest("[hidden], details")) return;   // hidden by the page's own script
    sel._cdtCombo = true;
    var key = "cdt-recent:" + (sel.name || sel.id || "");
    var wrap = el("div", "cdt-combo");
    var face = el("button", "cdt-combo-face");
    face.type = "button";
    face.setAttribute("aria-haspopup", "listbox");
    face.setAttribute("aria-expanded", "false");
    var lab = sel.getAttribute("aria-label") || (sel.closest("label") && (sel.closest("label").querySelector(".field-label") || {}).textContent) || sel.name;
    if (lab) face.setAttribute("aria-label", String(lab).trim());
    face.innerHTML = '<span class="cdt-combo-text"></span>';
    sel.parentNode.insertBefore(wrap, sel);
    wrap.appendChild(face);
    wrap.appendChild(sel);
    sel.classList.add("cdt-combo-native");
    sel.tabIndex = -1;
    sel.setAttribute("aria-hidden", "true");
    function paint() {
      var o = sel.options[sel.selectedIndex];
      face.querySelector(".cdt-combo-text").textContent = o ? o.text : "";
      face.disabled = sel.disabled;
    }
    paint();
    sel.addEventListener("change", paint);
    var pop = null, active = -1, shown = [];
    function recent() { try { return JSON.parse(store(key) || "[]"); } catch (e) { return []; } }
    function remember(v) {
      if (!v) return;
      var r = recent().filter(function (x) { return x !== v; });
      r.unshift(v);
      store(key, JSON.stringify(r.slice(0, 5)));
    }
    function close() { if (!pop) return; pop.remove(); pop = null; wrap.classList.remove("is-open"); face.setAttribute("aria-expanded", "false"); }
    function choose(o) {
      if (o.disabled) return;
      var changed = sel.value !== o.value;
      sel.value = o.value;
      remember(o.value);
      paint(); close(); face.focus();
      if (changed) { sel.dispatchEvent(new Event("input", { bubbles: true })); sel.dispatchEvent(new Event("change", { bubbles: true })); }
    }
    function draw(q) {
      var ws = words(q).map(squash), list = pop.querySelector(".cdt-pop-list"), html = "", group = null, n = 0;
      shown = [];
      var all = Array.prototype.slice.call(sel.options).filter(function (o) { return !o.hidden; });
      var hits = all.filter(function (o) { return !ws.length || matches(o.text, ws); });
      // Items that start with the first word come first.
      if (ws.length) hits.sort(function (a, b) { return (squash(b.text).indexOf(ws[0]) === 0) - (squash(a.text).indexOf(ws[0]) === 0); });
      var rec = ws.length ? [] : recent().map(function (v) { return all.filter(function (o) { return o.value === v && v; })[0]; }).filter(Boolean);
      function row(o) {
        var i = shown.length; shown.push(o);
        return '<div class="cdt-combo-opt" role="option" id="' + sel.name + "-o" + i + '" data-i="' + i + '" aria-selected="' + (o.selected ? "true" : "false") + '"' + (o.disabled ? ' aria-disabled="true"' : "") + ">" +
          "<span>" + (ws.length ? highlight(o.text, ws) : esc(o.text) || "&nbsp;") + "</span></div>";
      }
      if (rec.length) { html += '<div class="cdt-combo-group">Recent</div>'; rec.forEach(function (o) { html += row(o); }); }
      hits.forEach(function (o) {
        var g = o.parentNode.tagName === "OPTGROUP" ? o.parentNode.label : "";
        if (!ws.length && g !== group) { group = g; if (g) html += '<div class="cdt-combo-group">' + esc(g) + "</div>"; else if (rec.length) html += '<div class="cdt-combo-group">All</div>'; }
        html += row(o); n++;
      });
      if (!n) html += '<div class="cdt-combo-none">Nothing matches “' + esc(q) + "”.</div>";
      list.innerHTML = html;
      active = -1;
      for (var i = 0; i < shown.length; i++) if (shown[i].selected && !rec.length) { active = i; break; }
      if (ws.length && shown.length) active = 0;
      mark();
    }
    function mark() {
      Array.prototype.forEach.call(pop.querySelectorAll(".cdt-combo-opt"), function (r) { r.classList.toggle("is-active", +r.getAttribute("data-i") === active); });
      var a = pop.querySelector(".cdt-combo-opt.is-active");
      var q = pop.querySelector("input");
      if (a) { q.setAttribute("aria-activedescendant", a.id); a.scrollIntoView({ block: "nearest" }); } else q.removeAttribute("aria-activedescendant");
    }
    function open() {
      if (pop) { close(); return; }
      closePop();
      pop = el("div", "cdt-pop");
      pop.innerHTML = '<input type="search" placeholder="Type to search" aria-label="Search" role="combobox" aria-expanded="true" aria-autocomplete="list"><div class="cdt-pop-list" role="listbox"></div>';
      wrap.appendChild(pop);
      wrap.classList.add("is-open");
      face.setAttribute("aria-expanded", "true");
      var q = pop.querySelector("input");
      draw("");
      q.focus();
      q.addEventListener("input", function () { draw(q.value); });
      q.addEventListener("keydown", function (e) {
        var step = { ArrowDown: 1, ArrowUp: -1, PageDown: 8, PageUp: -8 }[e.key];
        if (step) { e.preventDefault(); active = Math.max(0, Math.min(shown.length - 1, active + step)); mark(); }
        else if (e.key === "Enter") { e.preventDefault(); if (shown[active]) choose(shown[active]); }
        else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(); face.focus(); }
        else if (e.key === "Tab") close();
      });
      pop.addEventListener("mousedown", function (e) {
        var r = e.target.closest(".cdt-combo-opt");
        if (r) { e.preventDefault(); choose(shown[+r.getAttribute("data-i")]); }
      });
    }
    face.addEventListener("click", open);
    face.addEventListener("keydown", function (e) {
      if (e.key === "ArrowDown" || e.key === "Enter" || e.key === " " || (e.key.length === 1 && /\S/.test(e.key) && !e.ctrlKey && !e.metaKey)) {
        e.preventDefault(); open();
        if (e.key.length === 1 && e.key !== " ") { var q = pop.querySelector("input"); q.value = e.key; draw(q.value); }
      }
    });
    document.addEventListener("mousedown", function (e) { if (pop && !wrap.contains(e.target)) close(); });
    // The page's own scripts can reset the select (a form reset, a choice
    // filled in for you): the face follows.
    var form = sel.form;
    if (form) form.addEventListener("reset", function () { setTimeout(paint, 0); });
  }
  function combos(scope) {
    Array.prototype.forEach.call((scope || document).querySelectorAll("main select"), combo);
  }

  // --- StepIndicator for the numbered cards of a form -------------------------------------

  function stepper() {
    var form = document.querySelector("main form.themis-form");
    if (!form) return;
    var cards = Array.prototype.filter.call(form.querySelectorAll(":scope > .card"), function (c) { return c.querySelector(".spec-n"); });
    if (cards.length < 3) return;
    var ol = el("ol", "cdt-steps");
    ol.setAttribute("aria-label", "Steps");
    cards.forEach(function (c, i) {
      c.id = c.id || "cdt-step-" + (i + 1);
      var h = c.querySelector("h2").cloneNode(true);
      var n = h.querySelector(".spec-n"); if (n) n.remove();
      var li = el("li");
      li.innerHTML = '<a href="#' + c.id + '">' + esc(h.textContent.trim()) + "</a>";
      ol.appendChild(li);
    });
    var barEl = el("div", "cdt-steps-bar");
    barEl.appendChild(ol);
    form.insertBefore(barEl, form.firstChild);
    function filled(c) {
      var any = false, bad = false;
      Array.prototype.forEach.call(c.querySelectorAll("input:not([type=hidden]), select, textarea"), function (i) {
        if (i.disabled) return;
        if (i.required && !i.value.trim()) bad = true;
        if ((i.type === "radio" || i.type === "checkbox") ? i.checked : (i.value || "").trim()) any = true;
      });
      return any && !bad;
    }
    // A step is ticked once it has been worked through: passed, or
    // touched, and filled in. Defaults alone tick nothing.
    var now = 0, seen = {};
    function paint() {
      for (var k = 0; k < now; k++) seen[k] = true;
      Array.prototype.forEach.call(ol.children, function (li, i) {
        li.classList.toggle("is-done", !!seen[i] && filled(cards[i]) && i !== now);
        li.classList.toggle("is-now", i === now);
        if (i === now) li.setAttribute("aria-current", "step"); else li.removeAttribute("aria-current");
      });
    }
    function touched(e) { var i = cards.indexOf(e.target.closest(".card")); if (i >= 0) seen[i] = true; paint(); }
    form.addEventListener("input", touched);
    form.addEventListener("change", touched);
    form.addEventListener("focusin", function (e) { var c = e.target.closest(".card"); var i = cards.indexOf(c); if (i >= 0) { now = i; paint(); } });
    if ("IntersectionObserver" in window) {
      var io = new IntersectionObserver(function (es) {
        es.forEach(function (en) { if (en.isIntersecting && !form.contains(document.activeElement)) { now = cards.indexOf(en.target); paint(); } });
      }, { rootMargin: "-30% 0px -60% 0px" });
      cards.forEach(function (c) { io.observe(c); });
    }
    paint();
  }

  // --- ToggleSwitch: the settings that hold an issue ---------------------------------------

  function switches(scope) {
    Array.prototype.forEach.call((scope || document).querySelectorAll('main input[type=checkbox][name^="need_"], main input[type=checkbox][name="hold_issue"], main [data-cdt-switch] input[type=checkbox]'), function (c) {
      var l = c.closest("label");
      if (l) l.classList.add("cdt-switch");
    });
  }

  // --- Kbd on the question cards: 1–9 pick, Enter goes on --------------------------------

  function visibleCard() {
    return document.querySelector("form[data-card]:not([hidden])") ||
      document.querySelector(".spec-decide-q.is-card");
  }
  function choicesOf(card) {
    if (!card) return [];
    return Array.prototype.filter.call(card.querySelectorAll(".spec-pill, .spec-decide-choice"), function (l) {
      return l.offsetParent !== null && !l.closest("[data-split-rows]");
    }).slice(0, 9);
  }
  function kbd(text) { var k = el("kbd", "cdt-kbd", esc(text)); k.setAttribute("aria-hidden", "true"); return k; }
  function decorateCards() {
    var card = visibleCard();
    choicesOf(card).forEach(function (l, i) {
      if (l.querySelector(".cdt-choice-key")) return;
      var k = kbd(String(i + 1)); k.classList.add("cdt-choice-key");
      l.appendChild(k);
    });
    // One line under the choices says the keys: 1–9 picks, Enter goes on.
    if (card && choicesOf(card).length && !card.querySelector(".cdt-keys-hint")) {
      var hint = el("p", "cdt-keys-hint");
      hint.setAttribute("aria-hidden", "true");
      hint.appendChild(kbd("1")); hint.appendChild(document.createTextNode("–")); hint.appendChild(kbd(String(Math.min(9, choicesOf(card).length))));
      hint.appendChild(document.createTextNode(" picks an answer"));
      hint.appendChild(kbd("Enter")); hint.appendChild(document.createTextNode(" goes on"));
      var at = card.querySelector(".spec-pills, .spec-decide-choices");
      if (at) at.parentNode.insertBefore(hint, at.nextSibling);
    }
  }
  var cardsWatched = false;
  function watchCards() {
    var panel = document.querySelector("[data-card-nav]") || document.querySelector(".spec-decide");
    if (!panel && !document.querySelector("[data-story], .spec-scene")) return;
    if (cardsWatched) return;
    cardsWatched = true;
    var pending = false;
    new MutationObserver(function () {
      if (pending) return;
      pending = true;
      requestAnimationFrame(function () { pending = false; decorateCards(); });
    }).observe(document.querySelector("main"), { childList: true, subtree: true, attributes: true, attributeFilter: ["hidden", "class"] });
    decorateCards();
  }
  document.addEventListener("keydown", function (e) {
    if (dialogOpen || popOpen || e.ctrlKey || e.metaKey || e.altKey || e.defaultPrevented) return;
    var t = e.target;
    if (/^(TEXTAREA|SELECT)$/.test(t.tagName) || t.isContentEditable) return;
    if (t.tagName === "INPUT" && !/^(radio|checkbox)$/.test(t.type)) return;
    var card = visibleCard();
    if (!card) return;
    if (/^[1-9]$/.test(e.key)) {
      var l = choicesOf(card)[+e.key - 1];
      if (!l) return;
      var input = l.querySelector('input[type=radio], input[type=checkbox]') || l.querySelector("input");
      if (!input || input.disabled) return;
      e.preventDefault();
      if (input.type === "text") { input.focus(); return; }
      input.focus({ preventScroll: true });
      input.click();
    } else if (e.key === "Enter" && !/^(BUTTON|A|SUMMARY)$/.test(t.tagName)) {
      var next = document.querySelector("[data-card-next]:not([disabled]), [data-brief-next]:not([disabled])");
      if (next && next.offsetParent !== null) { e.preventDefault(); next.click(); }
    }
  });

  // --- start ---------------------------------------------------------------------------

  function enhance(scope) {
    adoptConfirms(scope);
    switches(scope);
    combos(scope);
    grids(scope);
  }
  function start() {
    themeBar();
    avatar();
    flashes();
    stepper();
    enhance(document);
    watchCards();
    // Pages that bring parts in later (the story's cards, a panel opened)
    // get the same controls.
    var main = document.querySelector("main"), queued = false;
    if (main && "MutationObserver" in window) {
      new MutationObserver(function (ms) {
        var fresh = ms.some(function (m) { return m.addedNodes.length; });
        if (!fresh || queued) return;
        queued = true;
        setTimeout(function () {
          queued = false;
          enhance(main);
          Array.prototype.forEach.call(main.querySelectorAll(".flash:not(.cdt-infobar)"), infobar);
        }, 60);
      }).observe(main, { childList: true, subtree: true });
    }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
})();
