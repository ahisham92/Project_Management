/* THEMIS: the project's inputs at a glance, drawn as the works being built.

   The page carries the data (#spec-scene-data): stations, each with its
   questions and answers, and the chapters of the questions' story. Each
   station is drawn in isometric 3D on the site (silos, heaps, the mixer, the
   formwork...), with a pin saying how it stands. Clicking a station zooms in
   and opens its answers with the words of the specification they go into;
   "Play the story" walks through the stations in the story's order.

   Everything here is drawn in the browser as SVG, with no library; the page
   shows the same summary as tables for reading without this file. */
(function () {
  "use strict";

  var root = document.querySelector("[data-scene]");
  var dataEl = document.getElementById("spec-scene-data");
  if (!root || !dataEl || !window.requestAnimationFrame) return;
  var data;
  try { data = JSON.parse(dataEl.textContent); } catch (e) { return; }
  if (!data.stations || !data.stations.length) return;

  var svg = root.querySelector("[data-svg]");
  var panel = root.querySelector("[data-panel]");
  var body = root.querySelector("[data-panel-body]");
  var caption = root.querySelector("[data-caption]");
  var playBtn = root.querySelector("[data-play]");
  var NS = "http://www.w3.org/2000/svg";
  var S = 22;                       // pixels per metre of the drawing
  var C30 = Math.cos(Math.PI / 6), S30 = 0.5;

  // --- the isometric drawing kit --------------------------------------------------

  function P(x, y, z) { return [(x - y) * C30 * S, (x + y) * S30 * S - (z || 0) * S]; }
  function pts(list) { return list.map(function (p) { return p[0].toFixed(1) + "," + p[1].toFixed(1); }).join(" "); }
  function shade(hex, k) {
    var n = parseInt(hex.slice(1), 16), r = n >> 16, g = (n >> 8) & 255, b = n & 255;
    function f(c) { return Math.max(0, Math.min(255, Math.round(k > 0 ? c + (255 - c) * k : c * (1 + k)))); }
    return "#" + ((1 << 24) + (f(r) << 16) + (f(g) << 8) + f(b)).toString(16).slice(1);
  }
  function poly(list, fill, extra) {
    return '<polygon points="' + pts(list) + '" fill="' + fill + '"' + (extra || ' stroke="rgba(0,0,0,.18)" stroke-width=".6"') + "/>";
  }
  // A box standing on (x, y, z), w along x, d along y, h up: the three faces seen.
  function box(x, y, z, w, d, h, color, cls) {
    var top = [P(x, y, z + h), P(x + w, y, z + h), P(x + w, y + d, z + h), P(x, y + d, z + h)];
    var left = [P(x, y + d, z), P(x + w, y + d, z), P(x + w, y + d, z + h), P(x, y + d, z + h)];
    var right = [P(x + w, y, z), P(x + w, y + d, z), P(x + w, y + d, z + h), P(x + w, y, z + h)];
    return '<g' + (cls ? ' class="' + cls + '"' : "") + ">" + poly(left, shade(color, -0.12)) +
      poly(right, shade(color, -0.3)) + poly(top, shade(color, 0.12)) + "</g>";
  }
  // An upright cylinder: its body between two ellipses, its top.
  function cyl(x, y, z, r, h, color, cls) {
    var c0 = P(x, y, z), c1 = P(x, y, z + h);
    var rx = r * S * 1.2247, ry = r * S * 0.7071;   // a circle on the ground, seen isometrically
    var id = "g" + Math.random().toString(36).slice(2, 8);
    return '<g' + (cls ? ' class="' + cls + '"' : "") + '><defs><linearGradient id="' + id + '" x1="0" x2="1">' +
      '<stop offset="0" stop-color="' + shade(color, -0.05) + '"/><stop offset=".55" stop-color="' + shade(color, 0.18) +
      '"/><stop offset="1" stop-color="' + shade(color, -0.35) + '"/></linearGradient></defs>' +
      '<path d="M' + (c0[0] - rx) + "," + c0[1] + " A" + rx + "," + ry + " 0 0 0 " + (c0[0] + rx) + "," + c0[1] +
      " L" + (c1[0] + rx) + "," + c1[1] + " A" + rx + "," + ry + " 0 0 1 " + (c1[0] - rx) + "," + c1[1] + ' Z" fill="url(#' + id + ')" stroke="rgba(0,0,0,.2)" stroke-width=".6"/>' +
      '<ellipse cx="' + c1[0] + '" cy="' + c1[1] + '" rx="' + rx + '" ry="' + ry + '" fill="' + shade(color, 0.22) + '" stroke="rgba(0,0,0,.2)" stroke-width=".6"/></g>';
  }
  // A cone pointing down (a silo's hopper): from radius r at z+h to a point at z.
  function hopper(x, y, z, r, h, color) {
    var c0 = P(x, y, z), c1 = P(x, y, z + h), rx = r * S * 1.2247, ry = r * S * 0.7071;
    return '<path d="M' + (c1[0] - rx) + "," + c1[1] + " L" + c0[0] + "," + c0[1] + " L" + (c1[0] + rx) + "," + c1[1] +
      " A" + rx + "," + ry + ' 0 0 1 ' + (c1[0] - rx) + "," + c1[1] + ' Z" fill="' + shade(color, -0.2) + '" stroke="rgba(0,0,0,.2)" stroke-width=".6"/>';
  }
  // A heap of sand or stone, speckled with its grains.
  function heap(x, y, r, h, color, grain, big) {
    var c = P(x, y, 0), t = P(x, y, h), rx = r * S * 1.2247, ry = r * S * 0.7071, out = [];
    out.push('<path d="M' + (c[0] - rx) + "," + c[1] + " Q" + (c[0] - rx * 0.35) + "," + (t[1] - ry * 0.2) + " " + t[0] + "," + t[1] +
      " Q" + (c[0] + rx * 0.35) + "," + (t[1] - ry * 0.2) + " " + (c[0] + rx) + "," + c[1] +
      " A" + rx + "," + ry + " 0 0 1 " + (c[0] - rx) + "," + c[1] + ' Z" fill="' + color + '" stroke="' + shade(color, -0.3) + '" stroke-width=".8"/>');
    var seed = Math.round(x * 31 + y * 17);
    for (var i = 0; i < (big ? 46 : 90); i++) {
      seed = (seed * 9301 + 49297) % 233280;
      var u = seed / 233280; seed = (seed * 9301 + 49297) % 233280;
      var v = seed / 233280;
      var px = c[0] + (u - 0.5) * rx * 1.8, py = c[1] - v * (c[1] - t[1]) * (1 - Math.abs(u - 0.5) * 1.6) + ry * 0.3 * (u - 0.2);
      out.push('<circle cx="' + px.toFixed(1) + '" cy="' + py.toFixed(1) + '" r="' + (big ? 1.9 : 0.8) + '" fill="' + grain + '"/>');
    }
    return out.join("");
  }
  function line(a, b, color, w, cls) {
    return '<line x1="' + a[0] + '" y1="' + a[1] + '" x2="' + b[0] + '" y2="' + b[1] + '" stroke="' + color + '" stroke-width="' + (w || 1) + '"' + (cls ? ' class="' + cls + '"' : "") + ' stroke-linecap="round"/>';
  }

  // --- the stations ----------------------------------------------------------------
  // Each draws itself at its place on the site; at[] is where its pin stands.

  var DRAW = {
    office: function (x, y) {
      return box(x, y, 0, 3.2, 2.2, 2.2, "#d9d4c7") +
        box(x + 0.6, y - 0.02, 0.9, 0.8, 0.02, 0.7, "#5b8bb5") + box(x + 1.9, y - 0.02, 0.9, 0.8, 0.02, 0.7, "#5b8bb5") +
        box(x - 0.1, y - 0.1, 2.2, 3.4, 2.4, 0.2, "#8a6d4b") +
        line(P(x + 2.8, y + 0.4, 2.4), P(x + 2.8, y + 0.4, 4), "#777", 1.2) +
        '<polygon points="' + pts([P(x + 2.8, y + 0.4, 4), P(x + 2.8, y + 1.4, 3.7), P(x + 2.8, y + 0.4, 3.4)]) + '" fill="#d03b3b"/>';
    },
    documents: function (x, y) {
      var out = box(x, y, 0, 2.6, 1.6, 0.9, "#9a7b55");
      for (var i = 0; i < 5; i++) out += box(x + 0.3 + i * 0.04, y + 0.2, 0.9 + i * 0.09, 1.2, 0.9, 0.08, i % 2 ? "#ffffff" : "#eef1f6");
      out += box(x + 1.6, y + 0.4, 0.9, 0.8, 0.6, 0.6, "#2a78d6");
      return out;
    },
    shoring: function (x, y) {
      var out = box(x, y + 1.6, 0, 3.4, 0.5, 3.0, "#b9b1a3");
      for (var i = 0; i < 3; i++) {
        out += line(P(x + 0.5 + i * 1.2, y - 0.6, 0), P(x + 0.5 + i * 1.2, y + 1.6, 2.6), "#c2742b", 3);
        out += box(x + 0.3 + i * 1.2, y - 0.8, 0, 0.5, 0.4, 0.15, "#6b4b2a");
      }
      out += '<circle cx="' + P(x + 3.6, y + 0.5, 1.6)[0] + '" cy="' + P(x + 3.6, y + 0.5, 1.6)[1] + '" r="3" fill="#0ca30c" class="spec-scene-blink"/>';
      out += line(P(x + 3.6, y + 0.5, 0), P(x + 3.6, y + 0.5, 1.5), "#555", 1.2);
      return out;
    },
    cement: function (x, y) {
      var out = "";
      for (var i = 0; i < 4; i++) out += line(P(x + (i % 2 ? 0.9 : -0.9), y + (i < 2 ? 0.9 : -0.9), 0), P(x + (i % 2 ? 0.7 : -0.7), y + (i < 2 ? 0.7 : -0.7), 2.4), "#6c6c6c", 2);
      out += hopper(x, y, 1.2, 1.3, 1.6, "#c9ccd1") + cyl(x, y, 2.8, 1.3, 5.2, "#c9ccd1");
      out += line(P(x + 1.3, y, 8.0), P(x + 3.4, y + 2.0, 1.2), "#8a8f96", 2.5);
      return out;
    },
    sand: function (x, y) { return heap(x, y, 1.9, 1.7, "#e2c27a", "#b8913e", false); },
    gravel: function (x, y) { return heap(x, y, 1.8, 1.8, "#a7a59f", "#6e6b66", true); },
    water: function (x, y) {
      return cyl(x, y, 0, 1.1, 2.6, "#4f8fd1") + line(P(x + 1.1, y + 0.2, 0.4), P(x + 3.0, y + 2.4, 0.4), "#4f8fd1", 2.5) +
        '<path class="spec-scene-ripple" d="M' + (P(x, y, 2.6)[0] - 10) + "," + P(x, y, 2.6)[1] + ' q5,-3 10,0 t10,0" stroke="#fff" fill="none" stroke-width="1.2"/>';
    },
    admixtures: function (x, y) {
      return cyl(x, y, 0, 0.45, 1.3, "#e27a3a") + cyl(x + 1.2, y + 0.2, 0, 0.45, 1.3, "#8a5cc7") + cyl(x + 0.5, y + 1.3, 0, 0.45, 1.3, "#2f9e8f");
    },
    store: function (x, y) {
      return box(x, y, 0, 3.0, 2.4, 1.9, "#b7a17a") +
        '<polygon points="' + pts([P(x - 0.2, y - 0.2, 1.9), P(x + 3.2, y - 0.2, 1.9), P(x + 3.2, y + 1.2, 2.7), P(x - 0.2, y + 1.2, 2.7)]) + '" fill="#8c4a3a" stroke="rgba(0,0,0,.2)"/>' +
        '<polygon points="' + pts([P(x + 3.2, y - 0.2, 1.9), P(x + 3.2, y + 2.6, 1.9), P(x + 3.2, y + 1.2, 2.7)]) + '" fill="#6e3a2d"/>' +
        box(x + 3.0, y + 0.8, 0, 0.02, 0.9, 1.4, "#5a4a36");
    },
    mixer: function (x, y) {
      var out = "";
      [[0, 0], [2.6, 0], [0, 2.2], [2.6, 2.2]].forEach(function (c) { out += box(x + c[0], y + c[1], 0, 0.25, 0.25, 2.2, "#6b6b6b"); });
      out += box(x, y, 2.2, 2.85, 2.45, 2.0, "#3d6fa8") + hopper(x + 1.4, y + 1.2, 0.9, 0.9, 1.3, "#9aa4ae");
      out += box(x + 0.3, y + 0.3, 4.2, 2.2, 1.8, 0.9, "#2c4f78");
      // The mixer seen through its window on the front face, paddles turning.
      var c = P(x + 2.85, y + 1.22, 3.2);
      out += '<ellipse cx="' + c[0] + '" cy="' + c[1] + '" rx="12" ry="15" transform="rotate(-30 ' + c[0] + " " + c[1] + ')" fill="#dfe6ee" stroke="#1d3b5c" stroke-width="1.5"/>';
      out += '<g class="spec-scene-drum" style="transform-origin:' + c[0] + "px " + c[1] + 'px">' +
        line([c[0] - 9, c[1]], [c[0] + 9, c[1]], "#d03b3b", 2.4) + line([c[0], c[1] - 9], [c[0], c[1] + 9], "#d03b3b", 2.4) + "</g>";
      // The belt bringing sand and stone up from the heaps.
      out += line(P(x - 4.2, y + 2.6, 0.6), P(x + 0.4, y + 1.2, 4.6), "#555", 4, "spec-scene-belt");
      return out;
    },
    formwork: function (x, y) {
      var out = box(x, y, 0, 3.4, 2.4, 0.15, "#c8a36a");
      out += box(x, y, 0.15, 3.4, 0.12, 1.2, "#d9b47a") + box(x, y, 0.15, 0.12, 2.4, 1.2, "#d9b47a");
      out += box(x + 3.28, y, 0.15, 0.12, 2.4, 1.2, "#cfa96f") + box(x, y + 2.28, 0.15, 3.4, 0.12, 1.2, "#cfa96f");
      for (var i = 0; i < 3; i++) out += line(P(x + 0.6 + i, y - 0.2, 0.6), P(x + 0.6 + i, y - 1.0, 0), "#8a6d4b", 2);
      return out;
    },
    rebar: function (x, y) {
      var out = "";
      for (var i = 0; i <= 6; i++) {
        out += line(P(x + i * 0.5, y, 0.2), P(x + i * 0.5, y + 2.4, 0.2), "#7a3e1d", 1.6);
        out += line(P(x + i * 0.5, y, 1.4), P(x + i * 0.5, y + 2.4, 1.4), "#7a3e1d", 1.6);
        out += line(P(x + i * 0.5, y, 0.2), P(x + i * 0.5, y, 1.4), "#9a532a", 1.2);
      }
      for (var j = 0; j <= 4; j++) {
        out += line(P(x, y + j * 0.6, 0.2), P(x + 3, y + j * 0.6, 0.2), "#9a532a", 1.3);
        out += line(P(x, y + j * 0.6, 1.4), P(x + 3, y + j * 0.6, 1.4), "#9a532a", 1.3);
      }
      return out;
    },
    pour: function (x, y) {
      var out = box(x, y, 0, 4.0, 3.0, 0.4, "#a9a9a6");
      out += box(x + 4.6, y - 0.4, 0, 1.4, 2.6, 1.2, "#e0a32a") + box(x + 4.8, y + 1.8, 1.2, 1.0, 0.6, 0.6, "#e0a32a");
      var b0 = P(x + 5.2, y + 0.6, 1.4), b1 = P(x + 4.6, y + 0.4, 5.0), b2 = P(x + 1.6, y + 1.2, 4.2), b3 = P(x + 1.8, y + 1.4, 0.6);
      out += line(b0, b1, "#e0a32a", 3) + line(b1, b2, "#e0a32a", 2.6) + line(b2, b3, "#555", 1.6, "spec-scene-belt");
      return out;
    },
    frame: function (x, y) {
      var out = "";
      [[0, 0], [3, 0], [0, 2.4], [3, 2.4]].forEach(function (c) { out += box(x + c[0], y + c[1], 0, 0.22, 0.22, 4.4, "#365e8c"); });
      out += box(x, y, 2.2, 3.22, 0.22, 0.3, "#4673a6") + box(x, y + 2.4, 2.2, 3.22, 0.22, 0.3, "#4673a6");
      out += box(x, y, 4.4, 3.22, 2.62, 0.18, "#8d99a6") + box(x, y, 2.5, 0.22, 2.62, 0.3, "#4673a6");
      out += line(P(x + 0.2, y + 0.2, 0), P(x + 3, y + 0.2, 2.2), "#365e8c", 1.4);
      return out;
    },
    membrane: function (x, y) {
      return box(x, y, 0, 3.6, 2.6, 0.6, "#a9a9a6") + box(x - 0.05, y - 0.05, 0.6, 3.7, 2.7, 0.08, "#222831") +
        box(x + 1.8, y - 0.05, 0.68, 0.08, 2.7, 0.04, "#e0a32a");
    },
    bridge: function (x, y) {
      return box(x + 0.4, y + 0.8, 0, 0.6, 0.8, 1.8, "#a9a9a6") + box(x + 3.4, y + 0.8, 0, 0.6, 0.8, 1.8, "#a9a9a6") +
        box(x - 0.6, y + 0.6, 1.8, 5.6, 1.2, 0.35, "#b9b9b5") + '<path d="M' + P(x - 1, y + 2.6, 0)[0] + "," + P(x - 1, y + 2.6, 0)[1] + " L" + P(x + 5, y + 2.6, 0)[0] + "," + P(x + 5, y + 2.6, 0)[1] + '" stroke="#4f8fd1" stroke-width="5" opacity=".6"/>';
    },
    lab: function (x, y) {
      var out = box(x, y, 0, 3.0, 2.2, 2.0, "#e9e6df") + box(x + 0.4, y - 0.02, 0.9, 1.0, 0.02, 0.6, "#5b8bb5");
      for (var i = 0; i < 3; i++) for (var j = 0; j < 2; j++) out += box(x + 3.4 + i * 0.45, y + 0.4 + j * 0.45, 0, 0.3, 0.3, 0.3, "#9b9b97");
      out += cyl(x + 4.9, y + 1.6, 0, 0.15, 0.6, "#9b9b97");
      return out;
    },
    repair: function (x, y) {
      var out = box(x, y, 0, 3.2, 0.5, 2.6, "#b5b3ab");
      out += box(x + 0.5, y - 0.02, 0.8, 0.7, 0.02, 0.5, "#8d8a80") + box(x + 1.9, y - 0.02, 1.6, 0.5, 0.02, 0.4, "#8d8a80");
      out += line(P(x + 2.6, y - 1.2, 0), P(x + 2.6, y - 0.1, 2.4), "#c2742b", 2) + line(P(x + 3.1, y - 1.2, 0), P(x + 3.1, y - 0.1, 2.4), "#c2742b", 2);
      return out;
    },
    other: function (x, y) { return box(x, y, 0, 1.6, 1.6, 1.3, "#b08a58") + box(x + 1.8, y + 0.4, 0, 1.0, 1.0, 0.8, "#c49a62"); }
  };
  // Where each station stands on the site, in the order of the story: given
  // as across (u) and back to front (v) on the screen, turned into metres.
  var SCREEN = {
    office: [-17, 3], documents: [-9.5, 4], shoring: [-2, 3.5],
    cement: [5, 5], water: [12, 7], store: [21, 5], admixtures: [19, 12],
    sand: [2, 12.5], gravel: [8, 14.5], mixer: [14, 18.5],
    formwork: [5, 27], rebar: [-3, 28], pour: [-13, 24],
    frame: [-21, 15], membrane: [-19, 34], bridge: [-9, 37], lab: [1, 38], repair: [10, 37.5], other: [19, 32]
  };
  var PLACE = {};
  Object.keys(SCREEN).forEach(function (id) { var u = SCREEN[id][0], v = SCREEN[id][1]; PLACE[id] = [(u + v) / 2, (v - u) / 2]; });
  var PIN = { office: 3.4, documents: 2.2, shoring: 3.6, cement: 8.6, sand: 2.4, gravel: 2.4, water: 3.2, admixtures: 2.0,
    store: 3.2, mixer: 5.3, formwork: 1.8, rebar: 2.0, pour: 5.4, frame: 5.0, membrane: 1.4, bridge: 2.8, lab: 2.6, repair: 3.2, other: 1.8 };
  var MID = { office: [1.6, 1.1], documents: [1.3, 0.8], shoring: [1.7, 0.8], cement: [0, 0], sand: [0, 0], gravel: [0, 0], water: [0, 0],
    admixtures: [0.6, 0.6], store: [1.5, 1.2], mixer: [1.6, 1.3], formwork: [1.7, 1.2], rebar: [1.5, 1.2], pour: [2.6, 1.3],
    frame: [1.6, 1.3], membrane: [1.8, 1.3], bridge: [2.2, 1.2], lab: [2, 1.1], repair: [1.6, 0.25], other: [1.4, 1] };

  // --- drawing the site -----------------------------------------------------------

  var order = [];
  data.chapters.forEach(function (c) { c.stations.forEach(function (id) { order.push(id); }); });
  var byId = {};
  data.stations.forEach(function (s) { byId[s.id] = s; });

  function stateOf(s) { return s.needed ? "needed" : s.suggested ? "suggested" : "answered"; }
  function esc(t) { return String(t == null ? "" : t).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }

  var minX = 1e9, minY = 1e9, maxX = -1e9, maxY = -1e9;
  function grow(p, pad) { minX = Math.min(minX, p[0] - pad); maxX = Math.max(maxX, p[0] + pad); minY = Math.min(minY, p[1] - pad); maxY = Math.max(maxY, p[1] + pad); }
  var used = data.stations.map(function (s) { return s.id; }).filter(function (id) { return PLACE[id]; });
  var gx0 = 1e9, gy0 = 1e9, gx1 = -1e9, gy1 = -1e9;
  used.concat(["mixer", "pour"]).forEach(function (id) {
    gx0 = Math.min(gx0, PLACE[id][0]); gy0 = Math.min(gy0, PLACE[id][1]);
    gx1 = Math.max(gx1, PLACE[id][0]); gy1 = Math.max(gy1, PLACE[id][1]);
  });
  gx0 = Math.floor(gx0 - 3); gy0 = Math.floor(gy0 - 3); gx1 = Math.ceil(gx1 + 7); gy1 = Math.ceil(gy1 + 6);
  [[gx0, gy0], [gx1, gy0], [gx1, gy1], [gx0, gy1]].forEach(function (c) { grow(P(c[0], c[1], 0), 4); });

  var parts = [];
  // The ground and its grid.
  parts.push('<polygon class="spec-scene-ground" points="' + pts([P(gx0, gy0, 0), P(gx1, gy0, 0), P(gx1, gy1, 0), P(gx0, gy1, 0)]) + '"/>');
  for (var g = gx0; g <= gx1; g += 2) parts.push(line(P(g, gy0, 0), P(g, gy1, 0), "var(--scene-grid)", 0.5));
  for (var h = gy0; h <= gy1; h += 2) parts.push(line(P(gx0, h, 0), P(gx1, h, 0), "var(--scene-grid)", 0.5));
  // The haul road from the mixer to the pour, and the truck going back and forth on it.
  var m = PLACE.mixer, q = PLACE.pour;
  var r0 = [m[0] + 1.2, m[1] + 3.6], r1 = [q[0] + 6.6, q[1] + 1.2];
  parts.push('<polyline class="spec-scene-road" points="' + pts([P(r0[0], r0[1], 0), P(r1[0], r1[1], 0)]) + '"/>');
  var ux = r1[0] - r0[0], uy = r1[1] - r0[1], len = Math.sqrt(ux * ux + uy * uy);
  var tA = [r0[0] + ux / len * 1.5, r0[1] + uy / len * 1.5], tB = [r1[0] - ux / len * 3, r1[1] - uy / len * 3];
  var dA = P(tA[0], tA[1], 0), dB = P(tB[0], tB[1], 0);
  parts.push('<g class="spec-scene-truck" style="--tx:' + (dB[0] - dA[0]).toFixed(0) + "px;--ty:" + (dB[1] - dA[1]).toFixed(0) + 'px">' +
    box(tA[0] - 0.5, tA[1] - 0.5, 0.2, 1.0, 1.0, 1.0, "#2a78d6") + box(tA[0] - 0.5, tA[1] - 0.5 - 2.2, 0.2, 1.0, 2.2, 0.4, "#5a5a5a") +
    cyl(tA[0], tA[1] - 1.6, 0.6, 0.55, 1.1, "#e8e8e8") + "</g>");

  // Stations drawn back to front, so nearer ones hide farther ones.
  var drawOrder = data.stations.map(function (s) { return s.id; }).filter(function (id) { return PLACE[id] && DRAW[id]; })
    .sort(function (a, b) { return (PLACE[a][0] + PLACE[a][1]) - (PLACE[b][0] + PLACE[b][1]); });
  var centre = {};
  drawOrder.forEach(function (id) {
    var s = byId[id], at = PLACE[id], mid = MID[id] || [0, 0];
    var pin = P(at[0] + mid[0], at[1] + mid[1], PIN[id] + 0.8), foot = P(at[0] + mid[0], at[1] + mid[1], 0);
    centre[id] = [(pin[0] + foot[0]) / 2, (pin[1] + foot[1]) / 2 + 10];
    grow(pin, 40); grow(foot, 70);
    var st = stateOf(s), open = s.needed || s.suggested;
    parts.push('<g class="spec-scene-st spec-in-' + st + '" data-id="' + id + '" tabindex="0" role="button" aria-label="' +
      esc(s.name + ": " + s.questions.length + " questions, " + (s.needed ? s.needed + " need an answer" : s.suggested ? s.suggested + " suggested" : "all answered")) + '">' +
      '<ellipse class="spec-scene-halo" cx="' + foot[0] + '" cy="' + foot[1] + '" rx="70" ry="35"/>' +
      DRAW[id](at[0], at[1]) +
      line(foot, pin, "var(--scene-pin-line)", 0.8) +
      '<g class="spec-scene-pin"><circle cx="' + pin[0] + '" cy="' + pin[1] + '" r="11"/><text x="' + pin[0] + '" y="' + (pin[1] + 4) + '" text-anchor="middle">' +
      (open ? (s.needed || s.suggested) : "✓") + "</text></g>" +
      '<text class="spec-scene-label" x="' + pin[0] + '" y="' + (pin[1] - 16) + '" text-anchor="middle">' + esc(s.name) + "</text></g>");
  });
  svg.innerHTML = parts.join("");
  var whole = [minX, minY, maxX - minX, maxY - minY];
  svg.setAttribute("viewBox", whole.join(" "));
  svg.setAttribute("preserveAspectRatio", "xMidYMid meet");

  // --- zooming ----------------------------------------------------------------------

  var view = whole.slice(), anim = null;
  var still = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  function setView(v) { view = v; svg.setAttribute("viewBox", v.map(function (n) { return n.toFixed(1); }).join(" ")); }
  function zoomTo(target) {
    if (anim) cancelAnimationFrame(anim);
    if (still) { setView(target); return; }
    var from = view.slice(), t0 = null, D = 750;
    function step(t) {
      if (t0 === null) t0 = t;
      var k = Math.min(1, (t - t0) / D), e = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
      setView(from.map(function (f, i) { return f + (target[i] - f) * e; }));
      if (k < 1) anim = requestAnimationFrame(step);
    }
    anim = requestAnimationFrame(step);
  }
  function viewFor(id) {
    var c = centre[id], w = Math.max(260, Math.min(760, svg.clientWidth * 0.55)), h = w * (svg.clientHeight / Math.max(1, svg.clientWidth) || 0.6);
    // Leave room on the right for the panel when it sits over the picture.
    var shift = panel && window.innerWidth > 900 ? w * 0.22 : 0;
    return [c[0] - w / 2 + shift, c[1] - h / 2, w, h];
  }

  // --- the panel ------------------------------------------------------------------

  var current = null;
  var STATE_WORDS = { answered: "Answered", suggested: "Suggested, not accepted", needed: "Needs your answer" };
  function questionHtml(q) {
    var value = q.split ? q.rows.map(function (r) { return '<div><span class="muted">' + esc(r.element) + ":</span> " + esc(r.value || "—") + "</div>"; }).join("")
      : (q.value ? esc(q.value) : '<span class="muted">—</span>');
    var rows = !q.split && q.rows.length > 1 ? '<div class="small muted">Same for ' + q.rows.map(function (r) { return esc(r.element); }).join(", ") + "</div>" : "";
    var places = q.places.map(function (p) {
      return '<li><a href="' + esc(p.url) + '">' + esc(p.section + " " + p.label) + "</a>" + (p.article ? ' <span class="muted">' + esc(p.article) + "</span>" : "") +
        '<div class="spec-scene-words">' + esc(p.words).replace(/(\[[^\[\]]{1,200}\])/g, "<mark>$1</mark>") + "</div></li>";
    }).join("");
    return '<li class="spec-scene-q spec-in-' + q.state + '"><div class="spec-scene-q-head"><strong>' + esc(q.label) + '</strong><span class="spec-in-chip spec-in-' + q.state + '">' + STATE_WORDS[q.state] + "</span></div>" +
      '<div class="spec-scene-value">' + value + "</div>" + rows +
      (places ? '<details><summary class="small">What the specification says (' + q.sections.join(", ") + ")</summary><ul class=\"spec-scene-places\">" + places + "</ul></details>" : "") + "</li>";
  }
  function mixHtml() {
    var m = data.mix;
    if (!m || !m.rows.length) return "";
    return '<div class="table-scroll"><table class="spec-in-table spec-in-mix"><caption>Each element\'s concrete</caption><thead><tr><th>Element</th>' +
      m.columns.map(function (c) { return "<th>" + esc(c.label) + "</th>"; }).join("") + "</tr></thead><tbody>" +
      m.rows.map(function (r) { return '<tr><th scope="row">' + esc(r.element) + "</th>" + m.columns.map(function (c) { return "<td>" + (r.values[c.key] ? esc(r.values[c.key]) : '<span class="spec-in-miss">to answer</span>') + "</td>"; }).join("") + "</tr>"; }).join("") +
      "</tbody></table></div>";
  }
  function chapterOf(id) {
    for (var i = 0; i < data.chapters.length; i++) if (data.chapters[i].stations.indexOf(id) >= 0) return data.chapters[i];
    return null;
  }
  function open(id, fromPlay) {
    var s = byId[id];
    if (!s) return;
    current = id;
    if (!fromPlay) stop();
    Array.prototype.forEach.call(svg.querySelectorAll(".spec-scene-st"), function (g) { g.classList.toggle("is-on", g.getAttribute("data-id") === id); });
    svg.classList.add("is-zoomed");
    var c = chapterOf(id);
    var needed = s.questions.filter(function (q) { return q.state === "needed"; });
    var rest = s.questions.filter(function (q) { return q.state !== "needed"; });
    body.innerHTML = (c ? '<p class="small muted">Chapter ' + c.number + ": " + esc(c.name) + "</p>" : "") +
      "<h2>" + esc(s.name) + '</h2><p class="small muted">' + esc(s.what) + "</p>" +
      '<p class="small">' + s.questions.length + " question" + (s.questions.length === 1 ? "" : "s") + ": " + s.answered + " answered" +
      (s.suggested ? ", " + s.suggested + " suggested" : "") + (s.needed ? ", <strong>" + s.needed + " need your answer</strong>" : "") + "</p>" +
      (id === "mixer" ? mixHtml() : "") +
      '<ul class="spec-scene-qs">' + needed.concat(rest).map(questionHtml).join("") + "</ul>";
    panel.hidden = false;
    body.scrollTop = 0;
    caption.textContent = (c ? "Chapter " + c.number + " · " : "") + s.name;
    zoomTo(viewFor(id));
  }
  function close() {
    current = null;
    panel.hidden = true;
    svg.classList.remove("is-zoomed");
    Array.prototype.forEach.call(svg.querySelectorAll(".spec-scene-st"), function (g) { g.classList.remove("is-on"); });
    caption.textContent = "";
    zoomTo(whole);
  }
  function move(by) {
    var i = current ? order.indexOf(current) : -1;
    var next = order[(i + by + order.length) % order.length];
    open(next, !!timer);
  }

  // --- playing the story ------------------------------------------------------------

  var timer = null;
  function stop() {
    if (!timer) return;
    clearInterval(timer); timer = null;
    playBtn.textContent = "▶ Play the story";
  }
  function play() {
    if (timer) { stop(); return; }
    playBtn.textContent = "❚❚ Pause";
    timer = setInterval(function () {
      if (current === order[order.length - 1]) { stop(); close(); return; }
      move(1);
    }, 6000);
    if (!current) open(order[0], true); else move(1);
  }

  svg.addEventListener("click", function (e) {
    var g = e.target.closest && e.target.closest(".spec-scene-st");
    if (g) open(g.getAttribute("data-id"));
  });
  svg.addEventListener("keydown", function (e) {
    var g = e.target.closest && e.target.closest(".spec-scene-st");
    if (g && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); open(g.getAttribute("data-id")); }
  });
  root.addEventListener("keydown", function (e) {
    if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
    if (e.key === "ArrowRight") { move(1); } else if (e.key === "ArrowLeft") { move(-1); } else if (e.key === "Escape") { stop(); close(); }
  });
  playBtn.addEventListener("click", play);
  root.querySelector("[data-next]").addEventListener("click", function () { move(1); });
  root.querySelector("[data-prev]").addEventListener("click", function () { move(-1); });
  root.querySelector("[data-whole]").addEventListener("click", function () { stop(); close(); });
  root.querySelector("[data-close]").addEventListener("click", function () { stop(); close(); });
  root.classList.add("is-live");
})();
