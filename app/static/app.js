/* Small progressive enhancements. Everything here is optional: the pages work
   with JavaScript switched off, since all interaction is plain links and forms. */

(function () {
  'use strict';

  // --- theme ---------------------------------------------------------------
  // Cycles system -> light -> dark. The choice is stamped on <html>, which the
  // stylesheet's [data-theme] rules override the OS setting with.
  // Words rather than glyphs: moon and sun symbols are missing from some fonts.
  var LABELS = { system: 'Auto', light: 'Light', dark: 'Dark' };
  var NEXT = { system: 'light', light: 'dark', dark: 'system' };

  function applyTheme(theme) {
    if (theme === 'system') {
      document.documentElement.removeAttribute('data-theme');
    } else {
      document.documentElement.setAttribute('data-theme', theme);
    }
    var button = document.querySelector('[data-theme-toggle]');
    if (button) {
      button.textContent = LABELS[theme];
      button.title = 'Theme: ' + theme + '. Click to switch.';
      button.setAttribute('aria-label', button.title);
    }
  }

  function currentTheme() {
    try {
      return localStorage.getItem('pm-theme') || 'system';
    } catch (err) {
      return 'system';
    }
  }

  document.addEventListener('click', function (event) {
    var button = event.target.closest('[data-theme-toggle]');
    if (!button) return;
    var theme = NEXT[currentTheme()] || 'light';
    try { localStorage.setItem('pm-theme', theme); } catch (err) { /* private mode */ }
    applyTheme(theme);
  });

  applyTheme(currentTheme());

  // --- chart tooltips ------------------------------------------------------
  // Each chart emits invisible hit targets carrying a JSON payload; this turns
  // them into a hover tooltip and, on line charts, a crosshair.

  function renderTip(tip, payload) {
    var rows = (payload.rows || []).map(function (row) {
      return '<div class="tip-row">'
        + '<span class="tip-swatch" style="background:' + row.color + '"></span>'
        + '<span class="ink2">' + row.label + '</span>'
        + '<span class="tip-value">' + row.value + '</span>'
        + '</div>';
    }).join('');
    tip.innerHTML = '<div class="tip-title">' + payload.title + '</div>' + rows;
  }

  function place(chart, tip, event) {
    var box = chart.getBoundingClientRect();
    var x = event.clientX - box.left + 14;
    var y = event.clientY - box.top + 14;
    // Keep the tooltip inside the chart rather than letting it clip.
    if (x + tip.offsetWidth > box.width) x = Math.max(0, event.clientX - box.left - tip.offsetWidth - 14);
    if (y + tip.offsetHeight > box.height) y = Math.max(0, box.height - tip.offsetHeight);
    tip.style.left = x + 'px';
    tip.style.top = y + 'px';
  }

  document.querySelectorAll('.chart').forEach(function (chart) {
    var tip = chart.querySelector('.chart-tip');
    var crosshair = chart.querySelector('.crosshair');
    if (!tip) return;

    chart.addEventListener('mousemove', function (event) {
      var hit = event.target.closest('.hit');
      if (!hit || !hit.dataset.tip) return;

      var payload;
      try {
        payload = JSON.parse(hit.dataset.tip);
      } catch (err) {
        return;
      }
      renderTip(tip, payload);
      tip.hidden = false;
      place(chart, tip, event);

      if (crosshair && hit.dataset.x) {
        crosshair.setAttribute('x1', hit.dataset.x);
        crosshair.setAttribute('x2', hit.dataset.x);
        crosshair.setAttribute('visibility', 'visible');
      }
    });

    chart.addEventListener('mouseleave', function () {
      tip.hidden = true;
      if (crosshair) crosshair.setAttribute('visibility', 'hidden');
    });
  });

  // --- print ---------------------------------------------------------------
  // The browser's own print dialog is the PDF writer; "Save as PDF" is offered
  // as a destination in every current browser.

  document.addEventListener('click', function (event) {
    if (event.target.closest('[data-print]')) window.print();
  });

  // --- edit in place -------------------------------------------------------
  // An "Edit" control is a real link to ?edit=<id>, so the page still works
  // without JavaScript. With it, the form opens where it stands — no round
  // trip, and the page does not jump.
  //
  // The form itself is rendered once, into a <template>, and cloned on demand.
  // Rendering a copy per row would repeat the owner, trade and meeting lists
  // hundreds of times and turn a long register into a megabyte of HTML.

  function fillForm(form, data) {
    Object.keys(data).forEach(function (name) {
      var field = form.elements[name];
      if (!field) return;
      field.value = data[name] === null || data[name] === undefined ? '' : data[name];
    });
    var ref = form.querySelector('[data-item-ref]');
    if (ref) ref.textContent = data.ref || '';
  }

  function buildEditor(host) {
    var template = document.getElementById('editor-template');
    if (!template || !host.dataset.item) return false;

    var data;
    try {
      data = JSON.parse(host.dataset.item);
    } catch (err) {
      return false;                        // fall back to the server-rendered page
    }

    var form = template.content.firstElementChild.cloneNode(true);
    form.setAttribute('action', host.dataset.action);
    fillForm(form, data);
    var cell = host.querySelector('td');
    cell.insertBefore(form, cell.firstChild);
    host.dataset.ready = 'yes';
    return true;
  }

  document.addEventListener('click', function (event) {
    // Cancel inside a cloned form just closes the row it sits in.
    var close = event.target.closest('[data-close-edit]');
    if (close) {
      var open = close.closest('tr');
      if (open) {
        event.preventDefault();
        open.hidden = true;
        var link = document.querySelector('[data-toggle-row="' + open.id + '"]');
        if (link) link.setAttribute('aria-expanded', 'false');
      }
      return;
    }

    var trigger = event.target.closest('[data-toggle-row]');
    if (!trigger) return;

    var host = document.getElementById(trigger.getAttribute('data-toggle-row'));
    if (!host) return;                     // no placeholder: follow the link

    if (!host.dataset.ready && !buildEditor(host)) return;

    event.preventDefault();
    host.hidden = !host.hidden;
    trigger.setAttribute('aria-expanded', String(!host.hidden));
    if (!host.hidden) {
      var first = host.querySelector('input, select, textarea');
      if (first) first.focus({ preventScroll: true });
    }
  });

  // --- confirmations -------------------------------------------------------
  // Destructive buttons ask once before submitting.

  document.addEventListener('submit', function (event) {
    var message = event.target.getAttribute('data-confirm');
    if (message && !window.confirm(message)) event.preventDefault();
  });
})();
