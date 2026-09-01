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

  // --- confirmations -------------------------------------------------------
  // Destructive buttons ask once before submitting.

  document.addEventListener('submit', function (event) {
    var message = event.target.getAttribute('data-confirm');
    if (message && !window.confirm(message)) event.preventDefault();
  });
})();
