// MarineTwin's site images: drone orthophotos laid on the map, a date slider through them,
// and a swipe between two flights. The data comes as JSON in data-images:
//   {"images": [{id, name, taken, kind, url, bounds: [[s, w], [n, e]]}], "outline": [[lat, lon]], "focus": [lat, lon] | null}
// The images are oldest first. The swipe clips the upper image at the line, in its own box,
// so it holds while the map pans and zooms.

(function () {
  if (!window.L) return;
  const day = (iso) => (iso ? `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(0, 4)}` : '');

  function draw(root) {
    let data;
    try { data = JSON.parse(root.dataset.images); } catch (err) { return; }
    const el = root.querySelector('.mt-images-map');
    const images = data.images || [];
    const satellite = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
      maxZoom: 21, maxNativeZoom: 19, attribution: 'Imagery &copy; Esri, Maxar, Earthstar Geographics',
    });
    const streets = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 21, maxNativeZoom: 19, attribution: '&copy; OpenStreetMap contributors',
    });
    const map = L.map(el, { layers: [satellite], scrollWheelZoom: false, maxZoom: 21, preferCanvas: true });
    const structure = L.layerGroup();
    for (const p of data.outline || []) {
      L.circleMarker(p, { radius: 2, color: '#ffd400', weight: 1, fillOpacity: 0.9, interactive: false }).addTo(structure);
    }
    L.control.layers({ Satellite: satellite, Map: streets }, (data.outline || []).length ? { 'The structure': structure } : null,
      { position: 'topright' }).addTo(map);
    L.control.scale({ imperial: false }).addTo(map);

    const overlays = images.map((im) => L.imageOverlay(im.url, im.bounds, { interactive: false, className: 'mt-images-overlay' }));
    const date = root.querySelector('.mt-images-date');
    const label = root.querySelector('.mt-images-label');
    const opacity = root.querySelector('.mt-images-opacity');
    const swipe = root.querySelector('.mt-images-swipe');
    const other = root.querySelector('.mt-images-other');
    const note = root.querySelector('.mt-images-note');
    let line = null;
    let frac = 0.5;
    let shownNow = -1;
    let under = -1;

    function clip() {
      const top = shownNow >= 0 ? overlays[shownNow].getElement() : null;
      if (!top) return;
      if (!(swipe && swipe.checked) || under < 0) { top.style.clipPath = ''; return; }
      const box = top.getBoundingClientRect();
      const frame = el.getBoundingClientRect();
      const x = frame.left + frame.width * frac;
      const pct = box.width ? Math.min(100, Math.max(0, ((x - box.left) / box.width) * 100)) : 0;
      top.style.clipPath = `inset(0 0 0 ${pct}%)`;      // the newer flight to the right of the line
      line.style.left = `${frac * 100}%`;
    }

    function show() {
      const i = date ? Number(date.value) : images.length - 1;
      const j = swipe && swipe.checked && other ? Number(other.value) : -1;
      overlays.forEach((o, k) => { if (k !== i && k !== j && map.hasLayer(o)) map.removeLayer(o); });
      if (j >= 0 && j !== i) {
        if (!map.hasLayer(overlays[j])) overlays[j].addTo(map);
        overlays[j].bringToBack();
      }
      if (i >= 0) {
        if (!map.hasLayer(overlays[i])) overlays[i].addTo(map);
        overlays[i].bringToFront();
        overlays[i].setOpacity(opacity ? Number(opacity.value) / 100 : 1);
      }
      if (j >= 0) overlays[j].setOpacity(1);
      shownNow = i;
      under = j >= 0 && j !== i ? j : -1;
      if (label && i >= 0) label.textContent = `${day(images[i].taken)} · ${images[i].name}`;
      if (line) line.hidden = under < 0;
      if (note) {
        note.hidden = under < 0;
        if (under >= 0) {
          note.querySelector('.mt-images-left').textContent = `${day(images[under].taken)}, ${images[under].name}`;
          note.querySelector('.mt-images-right').textContent = `${day(images[i].taken)}, ${images[i].name}`;
        }
      }
      overlays.forEach((o) => { const img = o.getElement(); if (img) img.style.clipPath = ''; });
      clip();
    }

    if (other) {
      line = document.createElement('div');
      line.className = 'mt-images-line';
      line.hidden = true;
      line.innerHTML = '<span></span>';
      el.appendChild(line);
      L.DomEvent.disableClickPropagation(line);
      let dragging = false;
      const move = (ev) => {
        if (!dragging) return;
        const frame = el.getBoundingClientRect();
        frac = Math.min(0.98, Math.max(0.02, (ev.clientX - frame.left) / frame.width));
        clip();
      };
      line.addEventListener('pointerdown', (ev) => { dragging = true; line.setPointerCapture(ev.pointerId); ev.preventDefault(); });
      line.addEventListener('pointermove', move);
      line.addEventListener('pointerup', () => { dragging = false; });
      // Picking a flight to compare with: the older one if the shown one is the latest.
      swipe.addEventListener('change', () => {
        if (swipe.checked && Number(other.value) === Number(date.value)) other.value = String(Math.max(0, Number(date.value) - 1));
        show();
      });
      other.addEventListener('change', () => { swipe.checked = true; show(); });
    }
    if (date) date.addEventListener('input', show);
    if (opacity) opacity.addEventListener('input', show);
    map.on('move zoom zoomend viewreset resize', clip);
    for (const o of overlays) o.on('load', clip);

    if (images.length) {
      const all = L.latLngBounds(images.map((im) => im.bounds).flat());
      map.fitBounds(all, { padding: [10, 10] });
    } else if (data.focus) {
      map.setView(data.focus, 17);
    } else {
      map.setView([8, 3], 3);
    }
    if (!images.length && (data.outline || []).length) structure.addTo(map);
    show();
    root.dataset.ready = '1';
    window.MarineImages = { map, overlays, show, setSwipe(f) { frac = f; clip(); } };
  }

  for (const root of document.querySelectorAll('.mt-images')) {
    const el = root.querySelector('.mt-images-map');
    if (el.offsetWidth || !window.IntersectionObserver) { draw(root); continue; }
    const watch = new IntersectionObserver((seen) => {
      if (seen.some((e) => e.isIntersecting)) { watch.disconnect(); draw(root); }
    });
    watch.observe(el);
  }
})();
