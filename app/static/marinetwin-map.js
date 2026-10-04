// MarineTwin's maps: every asset on a world map, and one asset with its elements
// on the satellite picture of its site. Leaflet is vendored under static/vendor/leaflet;
// the map tiles come from OpenStreetMap and the imagery from Esri World Imagery.
//
// Each .marine-map element carries its data as JSON in data-map:
//   {"assets": [{name, lat, lon, state, href, terminal}], "elements": [{name, lat, lon, state, kind}],
//    "focus": [lat, lon] | null}
// Element positions are worked out on the server from the model's coordinates and rotation.

(function () {
  if (!window.L) return;
  const COLOUR = { good: '#0ca30c', warning: '#fab219', critical: '#d03b3b', neutral: '#8a8a80' };
  const WORD = { good: 'Good', warning: 'Watch', critical: 'Act', neutral: 'No data' };
  const escape = (t) => String(t ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  function draw(el) {
    let data;
    try { data = JSON.parse(el.dataset.map); } catch (err) { return; }
    const streets = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19, attribution: '&copy; OpenStreetMap contributors',
    });
    const satellite = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
      maxZoom: 19, attribution: 'Imagery &copy; Esri, Maxar, Earthstar Geographics',
    });
    const map = L.map(el, { layers: [data.elements && data.elements.length ? satellite : streets], scrollWheelZoom: false, worldCopyJump: true });
    L.control.layers({ Map: streets, Satellite: satellite }, null, { position: 'topright' }).addTo(map);
    L.control.scale({ imperial: false }).addTo(map);
    const bounds = [];
    for (const a of data.assets || []) {
      if (a.lat === null || a.lon === null) continue;
      const marker = L.circleMarker([a.lat, a.lon], {
        radius: data.elements ? 7 : 9, color: '#fff', weight: 2, fillColor: COLOUR[a.state] || COLOUR.neutral, fillOpacity: 1,
      }).addTo(map);
      marker.bindPopup(`<strong>${escape(a.name)}</strong><br>${escape(a.terminal || '')}<br>${WORD[a.state] || ''}` +
        (a.href ? `<br><a href="${a.href}">Open the twin →</a>` : ''));
      bounds.push([a.lat, a.lon]);
    }
    for (const e of data.elements || []) {
      L.circleMarker([e.lat, e.lon], {
        radius: e.kind === 'pile' ? 3 : 5, color: '#000', weight: 1, fillColor: COLOUR[e.state] || COLOUR.neutral, fillOpacity: 0.95,
      }).addTo(map).bindTooltip(`${escape(e.name)} · ${WORD[e.state] || ''}`);
      bounds.push([e.lat, e.lon]);
    }
    if (data.focus) map.setView(data.focus, data.zoom || 17);
    else if (bounds.length === 1) map.setView(bounds[0], 12);
    else if (bounds.length) map.fitBounds(bounds, { padding: [30, 30], maxZoom: 17 });
    else map.setView([8, 3], 3);
    el.dataset.ready = '1';
  }

  // A map on a section tab not showing yet is drawn when it first shows: Leaflet needs its size.
  for (const el of document.querySelectorAll('.marine-map')) {
    if (el.offsetWidth || !window.IntersectionObserver) { draw(el); continue; }
    const watch = new IntersectionObserver((seen) => {
      if (seen.some((e) => e.isIntersecting)) { watch.disconnect(); draw(el); }
    });
    watch.observe(el);
  }
})();
