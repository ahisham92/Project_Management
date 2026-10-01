/* THEMIS start page: the projects on a map (Leaflet, from cdnjs), and the
 * project lists filtered as you type. Without the script, or without the map
 * library, the page shows the places as a plain list instead. */
(function () {
  'use strict';

  // Filter the project tables.
  document.querySelectorAll('[data-filter-for]').forEach(function (box) {
    var area = document.getElementById(box.getAttribute('data-filter-for'));
    if (!area) return;
    box.addEventListener('input', function () {
      var words = box.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
      area.querySelectorAll('tr[data-row-text]').forEach(function (tr) {
        var text = tr.getAttribute('data-row-text');
        tr.hidden = !words.every(function (w) { return text.indexOf(w) >= 0; });
      });
      if (words.length) area.querySelectorAll('details.themis-others').forEach(function (d) { d.open = true; });
    });
  });

  var box = document.getElementById('themis-map');
  if (!box) return;
  var points = JSON.parse(box.getAttribute('data-points') || '[]');
  var unplaced = JSON.parse(box.getAttribute('data-unplaced') || '[]');

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function colour(family) {
    var probe = document.createElement('i');
    probe.className = 'themis-dot themis-kind-' + String(family || '').toLowerCase();
    probe.style.display = 'none';
    document.body.appendChild(probe);
    var c = getComputedStyle(probe).backgroundColor;
    probe.remove();
    return c && c !== 'rgba(0, 0, 0, 0)' ? c : '#2a78d6';
  }

  function start() {
    if (!window.L) return;               // no map library: the list stays
    if (!points.length && !unplaced.length) return;
    box.classList.add('themis-map-on');
    var map = L.map(box, { scrollWheelZoom: false, worldCopyJump: true });
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 18, attribution: '&copy; OpenStreetMap contributors'
    }).addTo(map);
    var layer = L.featureGroup().addTo(map);
    var shown = {};

    function add(p) {
      // Projects at the same place are fanned out a little so each can be clicked.
      var key = p.lat.toFixed(3) + ',' + p.lng.toFixed(3);
      var n = shown[key] = (shown[key] || 0) + 1;
      var angle = n * 2.4, r = n > 1 ? 0.02 * Math.sqrt(n) : 0;
      var at = [p.lat + r * Math.cos(angle), p.lng + r * Math.sin(angle)];
      var where = [p.city, p.country].filter(Boolean).join(', ');
      L.circleMarker(at, {
        radius: p.mine ? 9 : 7, weight: 2, color: '#fff', fillColor: colour(p.family), fillOpacity: 0.95
      }).bindPopup(
        '<strong><a href="' + esc(p.url) + '">' + esc(p.name) + '</a></strong>' +
        (p['package'] ? ' · ' + esc(p['package']) : '') + '<br>' +
        '<span class="small">' + esc(p.family) + (p.code ? ' · ' + esc(p.code) : '') +
        (p.client ? ' · ' + esc(p.client) : '') + '<br>' + esc(where) + ' · ' +
        (p.issued ? 'Issued, REV ' + esc(p.revision) : 'Not issued yet') + '</span>'
      ).bindTooltip(esc(p.name)).addTo(layer);
    }

    function fit() {
      if (layer.getLayers().length) {
        map.fitBounds(layer.getBounds().pad(0.3), { maxZoom: 6 });
      } else {
        map.setView([24, 30], 2);
      }
    }

    points.forEach(add);
    fit();

    // Cities the site's own list does not know: looked up once here, and kept.
    var found = [];
    var queue = unplaced.slice(0, 10);
    function next() {
      var p = queue.shift();
      if (!p) {
        if (found.length) {
          fetch(box.getAttribute('data-save'), {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ points: found }), credentials: 'same-origin'
          }).catch(function () {});
        }
        return;
      }
      var q = 'https://nominatim.openstreetmap.org/search?format=json&limit=1&q=' +
        encodeURIComponent([p.city, p.country].filter(Boolean).join(', '));
      fetch(q, { headers: { 'Accept': 'application/json' } })
        .then(function (r) { return r.json(); })
        .then(function (rows) {
          if (rows && rows[0]) {
            p.lat = parseFloat(rows[0].lat); p.lng = parseFloat(rows[0].lon);
            add(p); fit();
            found.push({ id: p.id, lat: p.lat, lng: p.lng });
          }
        })
        .catch(function () {})
        .then(function () { setTimeout(next, 1100); });   // the service asks for one a second
    }
    next();
  }

  if (window.L) start();
  else window.addEventListener('load', start);
})();
