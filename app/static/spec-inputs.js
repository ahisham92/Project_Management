/* THEMIS: the project's inputs at a glance, drawn as the works being built,
   and answered there.

   The page carries the data (#spec-scene-data): stations, each with its
   questions and answers, and the chapters of the questions' story as stages.
   The plant is drawn in isometric 3D the way it works: cement, sand, stone,
   water and admixtures go into the mixer, a truck takes the mix to the pump,
   the pump fills the formwork the cage was lowered into, and cubes go to the
   lab. Each material moves once its stage is answered.

   Clicking a station zooms in and opens its questions to answer or change
   there (the station's form, fetched from the server and saved back to it).
   The stages open in turn: a stage is locked until every question before it
   is answered, a suggestion counting once the engineer accepts it, and Next
   and "Play the story" stop there.

   Everything is drawn in the browser as SVG, with no library; the page shows
   the same summary as tables for reading without this file. */
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
  // On the check the same works carry the findings, each at its station.
  var checks = root.getAttribute("data-mode") === "checks";
  var playWords = playBtn.textContent;
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
      return out;
    },
    sand: function (x, y) { return heap(x, y, 1.9, 1.7, "#e2c27a", "#b8913e", false); },
    gravel: function (x, y) { return heap(x, y, 1.8, 1.8, "#a7a59f", "#6e6b66", true); },
    water: function (x, y) {
      return cyl(x, y, 0, 1.1, 2.6, "#4f8fd1") +
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
      return out;
    },
    // The moulds for the project's elements (a footing, a column, a wall, a
    // slab on its props), with what the levels before have put in: the cage
    // once the steel is settled, concrete once the pour is, curing water after.
    formwork: function (x, y, st) {
      st = st || {};
      var ply = "#d9b47a", ply2 = "#cfa96f", wet = "#a9a9a6", steel = st.bar || "#7a3e1d";
      var out = box(x, y, 0, 3.4, 2.4, 0.15, "#c8a36a");
      out += box(x, y, 0.15, 3.4, 0.12, 1.2, ply) + box(x, y, 0.15, 0.12, 2.4, 1.2, ply);
      if (st.steel) {
        for (var a = 0; a <= 5; a++) out += line(P(x + 0.4 + a * 0.52, y + 0.3, 0.35), P(x + 0.4 + a * 0.52, y + 2.1, 0.35), steel, 1.2);
        for (var b = 0; b <= 3; b++) out += line(P(x + 0.3, y + 0.4 + b * 0.55, 0.45), P(x + 3.1, y + 0.4 + b * 0.55, 0.45), shade(steel, -0.2), 1.2);
      }
      if (st.pt) for (var t = 0; t < 2; t++) out += '<path d="M' + pts([P(x + 0.2, y + 0.8 + t * 0.8, 0.9)]) + " Q" + pts([P(x + 1.7, y + 0.8 + t * 0.8, 0.2)]) + " " + pts([P(x + 3.2, y + 0.8 + t * 0.8, 0.9)]) + '" fill="none" stroke="' + (st.pt === "Unbonded" ? "#222" : "#8d99a6") + '" stroke-width="2"/>';
      if (st.poured) out += box(x + 0.12, y + 0.12, 0.15, 3.16, 2.16, 0.95, wet, "spec-scene-fill");
      out += box(x + 3.28, y, 0.15, 0.12, 2.4, 1.2, ply2) + box(x, y + 2.28, 0.15, 3.4, 0.12, 1.2, ply2);
      for (var i = 0; i < 3; i++) out += line(P(x + 0.6 + i, y - 0.2, 0.6), P(x + 0.6 + i, y - 1.0, 0), "#8a6d4b", 2);
      var el = st.elements || [];
      function has(re) { return el.some(function (e) { return re.test(e); }); }
      // A column's mould, standing on its kicker, propped both ways.
      if (has(/column|pier/)) {
        var cx = x + 4.4, cy = y + 0.4;
        if (st.steel) for (var k = 0; k < 4; k++) out += line(P(cx + 0.15 + (k % 2) * 0.4, cy + 0.15 + (k > 1 ? 0.4 : 0), 0), P(cx + 0.15 + (k % 2) * 0.4, cy + 0.15 + (k > 1 ? 0.4 : 0), 3.6), steel, 1.3);
        out += box(cx, cy, 0, 0.7, 0.7, st.poured ? 3.0 : 0, wet);
        out += box(cx, cy, 0, 0.7, 0.08, 3.0, ply) + box(cx, cy, 0, 0.08, 0.7, 3.0, ply);
        if (!st.poured) out += box(cx + 0.62, cy, 0, 0.08, 0.7, 3.0, ply2) + box(cx, cy + 0.62, 0, 0.7, 0.08, 3.0, ply2);
        else out += box(cx, cy, 0, 0.7, 0.7, 3.0, wet, "spec-scene-fill");
        out += line(P(cx + 0.35, cy + 0.7, 2.2), P(cx + 0.35, cy + 2.0, 0), "#8a6d4b", 2) + line(P(cx + 0.7, cy + 0.35, 2.2), P(cx + 2.0, cy + 0.35, 0), "#8a6d4b", 2);
      }
      // A wall's two faces of panels, walers across, the steel between.
      if (has(/wall/)) {
        var wx = x, wy = y + 3.4;
        if (st.steel) for (var m = 0; m <= 6; m++) out += line(P(wx + 0.2 + m * 0.5, wy + 0.3, 0), P(wx + 0.2 + m * 0.5, wy + 0.3, 2.6), steel, 1.1);
        out += box(wx, wy, 0, 3.4, 0.12, 2.4, ply);
        out += st.poured ? box(wx, wy + 0.12, 0, 3.4, 0.4, 2.3, wet, "spec-scene-fill") : "";
        out += box(wx, wy + 0.55, 0, 3.4, 0.12, 2.4, ply2);
        for (var n = 0; n < 2; n++) out += box(wx - 0.1, wy + 0.67, 0.6 + n * 1.2, 3.6, 0.1, 0.12, "#8a6d4b");
      }
      // A slab or deck: the soffit on its props.
      if (has(/slab|deck|beam|floor|topping/)) {
        var sx = x + 4.2, sy = y + 3.2;
        for (var r = 0; r < 4; r++) out += line(P(sx + 0.3 + (r % 2) * 2.4, sy + 0.3 + (r > 1 ? 1.6 : 0), 0), P(sx + 0.3 + (r % 2) * 2.4, sy + 0.3 + (r > 1 ? 1.6 : 0), 2.2), "#9a9a9a", 1.6);
        out += box(sx, sy, 2.2, 3.0, 2.2, 0.1, ply);
        if (st.steel) for (var q = 0; q <= 4; q++) out += line(P(sx + 0.3 + q * 0.6, sy + 0.2, 2.45), P(sx + 0.3 + q * 0.6, sy + 2.0, 2.45), steel, 1.1);
        if (st.poured) out += box(sx, sy, 2.3, 3.0, 2.2, 0.25, wet, "spec-scene-fill");
        out += box(sx, sy + 2.1, 2.3, 3.0, 0.1, 0.3, ply2);
      }
      if (st.cured) {
        for (var d = 0; d < 7; d++) {
          var w = P(x + 0.5 + (d % 4) * 0.8, y + 0.6 + Math.floor(d / 4) * 1.0, 1.9);
          out += '<circle class="spec-scene-drop" style="animation-delay:' + (d * 0.23).toFixed(2) + 's" cx="' + w[0].toFixed(1) + '" cy="' + w[1].toFixed(1) + '" r="1.8" fill="#4f8fd1"/>';
        }
      }
      return out;
    },
    // The cage, in the colour of the project's bars (uncoated, epoxy-coated,
    // galvanized, stainless, GFRP), with a second for a second kind.
    rebar: function (x, y, st) {
      var out = "", kinds = (st && st.kinds) || ["Uncoated"];
      kinds.slice(0, 2).forEach(function (kind, n) {
        var c = BAR[kind] || BAR.Uncoated, ox = x + n * 3.6;
        out += box(ox - 0.2, y - 0.2, 0, 0.3, 2.8, 0.2, "#6b4b2a") + box(ox + 2.9, y - 0.2, 0, 0.3, 2.8, 0.2, "#6b4b2a");
        for (var i = 0; i <= 6; i++) {
          out += line(P(ox + i * 0.5, y, 0.2), P(ox + i * 0.5, y + 2.4, 0.2), c, 1.6);
          out += line(P(ox + i * 0.5, y, 1.4), P(ox + i * 0.5, y + 2.4, 1.4), c, 1.6);
          out += line(P(ox + i * 0.5, y, 0.2), P(ox + i * 0.5, y, 1.4), shade(c, 0.15), 1.2);
        }
        for (var j = 0; j <= 4; j++) {
          out += line(P(ox, y + j * 0.6, 0.2), P(ox + 3, y + j * 0.6, 0.2), shade(c, 0.15), 1.3);
          out += line(P(ox, y + j * 0.6, 1.4), P(ox + 3, y + j * 0.6, 1.4), shade(c, 0.15), 1.3);
        }
      });
      return out;
    },
    // Post-tensioning: a slab's tendons draped in their profile between the
    // anchorages, the jack at one end.
    tendons: function (x, y, st) {
      var bonded = !(st && st.pt === "Unbonded"), duct = bonded ? "#8d99a6" : "#222831";
      var out = box(x, y, 0, 4.0, 2.6, 0.5, "#c8c6c0");
      for (var i = 0; i < 4; i++) {
        var yy = y + 0.4 + i * 0.6;
        out += '<path d="M' + pts([P(x - 0.2, yy, 0.9)]) + " Q" + pts([P(x + 2, yy, 0.45)]) + " " + pts([P(x + 4.2, yy, 0.9)]) + '" fill="none" stroke="' + duct + '" stroke-width="2.4"/>';
        out += box(x + 4.0, yy - 0.15, 0.7, 0.1, 0.3, 0.3, "#555");
      }
      out += box(x + 4.15, y + 0.2, 0.6, 0.9, 0.5, 0.5, "#d03b3b") + line(P(x + 5.05, y + 0.45, 0.85), P(x + 5.8, y + 0.45, 0.85), "#d03b3b", 2);
      return out;
    },
    // The precast yard: units stacked on bearers, the casting bed with its
    // strands when they are prestressed, the gantry over them.
    precast: function (x, y, st) {
      var out = "", pre = st && /prestress/i.test(st.kind || "");
      out += box(x, y, 0, 6.0, 1.2, 0.3, "#b8b5ae");
      if (pre) for (var s = 0; s < 3; s++) out += line(P(x - 0.4, y + 0.3 + s * 0.3, 0.32), P(x + 6.4, y + 0.3 + s * 0.3, 0.32), "#5a5a5a", 1);
      for (var i = 0; i < 4; i++) {
        out += box(x + 0.5, y + 2.0, i * 0.45, 0.2, 2.2, 0.15, "#6b4b2a");
        out += box(x + 0.2, y + 2.0, 0.15 + i * 0.45, 4.6, 2.2, 0.3, i % 2 ? "#b0aea8" : "#c2c0ba");
      }
      out += box(x - 0.6, y - 0.4, 0, 0.3, 0.3, 3.6, "#e0a32a") + box(x + 6.3, y - 0.4, 0, 0.3, 0.3, 3.6, "#e0a32a") +
        box(x - 0.6, y - 0.4, 3.6, 7.2, 0.3, 0.3, "#e0a32a") + line(P(x + 2.5, y - 0.25, 3.6), P(x + 2.5, y - 0.25, 1.4), "#333", 1);
      return out;
    },
    // The brief: the drawing board where the project is decided, its sheets out.
    decide: function (x, y) {
      var out = "";
      [[0, 0], [2.4, 0], [0, 1.6], [2.4, 1.6]].forEach(function (c) { out += box(x + c[0], y + c[1], 0, 0.15, 0.15, 1.1, "#6b6b6b"); });
      out += box(x - 0.1, y - 0.1, 1.1, 2.8, 2.0, 0.12, "#e9e4d6");
      out += box(x + 0.2, y + 0.2, 1.22, 1.3, 0.9, 0.02, "#ffffff") + box(x + 1.4, y + 0.9, 1.22, 1.1, 0.8, 0.02, "#dfeaf6");
      var a = P(x + 0.4, y + 0.4, 1.25), b = P(x + 1.3, y + 0.9, 1.25);
      out += line(a, b, "#2a78d6", 1) + line(P(x + 0.4, y + 0.9, 1.25), P(x + 1.3, y + 0.4, 1.25), "#2a78d6", 1);
      out += box(x + 3.0, y + 0.2, 0, 0.6, 0.6, 1.6, "#c49a62") + cyl(x + 3.3, y + 0.5, 1.6, 0.25, 0.3, "#2a78d6");
      return out;
    },
    // The concrete pump, its boom reaching over the formwork (st.to).
    pour: function (x, y, st) {
      var out = box(x, y, 0, 1.4, 2.8, 1.2, "#e0a32a") + box(x + 0.2, y + 2.0, 1.2, 1.0, 0.8, 0.6, "#e0a32a");
      out += cyl(x + 0.7, y + 0.5, 1.2, 0.35, 0.5, "#c78d1f");
      var to = st && st.to ? st.to : [x + 5, y + 1];
      var b0 = P(x + 0.7, y + 0.5, 1.8), b1 = P((x + to[0]) / 2, (y + to[1]) / 2, 6.2), b2 = P(to[0], to[1], 4.0), b3 = P(to[0], to[1], 1.4);
      out += line(b0, b1, "#e0a32a", 3.2) + line(b1, b2, "#e0a32a", 2.6) + line(b2, b3, "#555", 1.6);
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
      if (data.site && data.site.bridge) return "";
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
  // Where each station stands on the site: given as across (u) and back to
  // front (v) on the screen, turned into metres. The plant is laid out the way
  // the concrete goes: the silo, heaps, water and admixtures feed the mixer, a
  // truck takes the mix down the road to the pump, the pump fills the formwork
  // the cage was lowered into, and cubes from the pour go to the lab.
  var SCREEN = {
    decide: [-27, 3], office: [-19, 3], documents: [-12, 4], shoring: [-5, 3],
    cement: [5, 3], water: [11, 5.5], admixtures: [16, 9], store: [21, 3], sand: [1, 10], gravel: [6, 12], mixer: [12, 14],
    formwork: [-2, 24], rebar: [8, 24], tendons: [-13, 31], precast: [-20, 14], pour: [-10, 21],
    frame: [-25, 21], membrane: [-21, 32], bridge: [-6, 36], lab: [9, 35], repair: [20, 30], other: [24, 22]
  };
  // What the project builds, standing at the front of the site: the building,
  // the quay on the sea, the bridge over its river.
  // In metres: where each stands, and how far it reaches.
  var SEA = 41;                     // the shore: the sea is beyond x = SEA
  var WORKS = { building: [29, 29, 8, 7], span: [10, 36, 13, 6], quay: [SEA - 2, 13, 12, 6] };
  var BAR = { Uncoated: "#7a3e1d", "Epoxy-coated": "#3f8f3a", Galvanized: "#a9b0b6", "Stainless steel": "#d5d8dc", "GFRP bars": "#e3c13b" };
  var PLACE = {};
  Object.keys(SCREEN).forEach(function (id) { var u = SCREEN[id][0], v = SCREEN[id][1]; PLACE[id] = [(u + v) / 2, (v - u) / 2]; });
  var BRIDGE_AT = PLACE.bridge;
  var PIN = { decide: 2.4, tendons: 1.6, precast: 4.2, office: 3.4, documents: 2.2, shoring: 3.6, cement: 8.6, sand: 2.4, gravel: 2.4, water: 3.2, admixtures: 2.0,
    store: 3.2, mixer: 5.6, formwork: 1.8, rebar: 2.0, pour: 2.4, frame: 5.0, membrane: 1.4, bridge: 2.8, lab: 2.6, repair: 3.2, other: 1.8 };
  var MID = { decide: [1.3, 0.9], tendons: [2, 1.3], precast: [3, 1.5], office: [1.6, 1.1], documents: [1.3, 0.8], shoring: [1.7, 0.8], cement: [0, 0], sand: [0, 0], gravel: [0, 0], water: [0, 0],
    admixtures: [0.6, 0.6], store: [1.5, 1.2], mixer: [1.4, 1.2], formwork: [1.7, 1.2], rebar: [1.5, 1.2], pour: [0.7, 1.4],
    frame: [1.6, 1.3], membrane: [1.8, 1.3], bridge: [2.2, 1.2], lab: [1.5, 1.1], repair: [1.6, 0.25], other: [1.4, 1] };
  // The plant itself is always drawn, whether or not its station asks anything.
  var PLANT = ["cement", "sand", "gravel", "water", "admixtures", "mixer", "formwork", "rebar", "pour", "lab"];
  // The order of the story, for a station this project does not ask about.
  var RANK = { decide: 0, office: 1, documents: 2, shoring: 3, formwork: 4, rebar: 5, tendons: 5, precast: 5,
    cement: 6, sand: 6, gravel: 6, water: 6, admixtures: 6, store: 6, mixer: 7, pour: 8, lab: 9,
    frame: 10, membrane: 11, bridge: 12, repair: 13, other: 14 };
  // Stations the project's decisions put on the site, asked about or not.
  function wanted(id) {
    var site = data.site || {};
    return { frame: site.steel, precast: !!site.precast, tendons: !!site.pt, shoring: site.shoring, bridge: site.bridge }[id];
  }

  // --- the project's state, and redrawing it -----------------------------------------

  var byId, order, centre, whole;
  function index() {
    byId = {};
    data.stations.forEach(function (s) { byId[s.id] = s; });
    order = [];
    data.chapters.forEach(function (c) { c.stations.forEach(function (id) { order.push(id); }); });
    if (checks) {
      var f = data.flags.stations;
      Object.keys(f).forEach(function (id) {
        if (!byId[id] && PLACE[id]) { byId[id] = { id: id, name: data.flags.names[id] || id, what: "", questions: [], needed: 0, suggested: 0, answered: 0, stage: -1 }; }
      });
      var flagged = Object.keys(RANK).sort(function (a, b) { return RANK[a] - RANK[b]; }).filter(function (id) { return f[id] && byId[id]; });
      order = flagged.length ? flagged : order;
    }
  }
  function findings(id) { return checks ? (data.flags.stations[id] || []) : []; }
  // A stage is done once every question in it is answered (a suggestion counting
  // once accepted). A station the project does not ask about is done once
  // everything before it in the story is.
  function done(id) {
    var s = byId[id];
    if (s) return s.stage < data.open_stage;
    return data.stations.every(function (o) { return RANK[o.id] > RANK[id] || o.stage < data.open_stage; });
  }
  function openCount(s) { return s.needed + s.suggested; }
  function stateOf(s) { return s.needed ? "needed" : s.suggested ? "suggested" : "answered"; }
  function esc(t) { return String(t == null ? "" : t).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  var still = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // A material moving along a path: the pipe or belt, and grains of it going
  // along while its stage is done; dashed and still while it is not.
  function flow(points, color, active, kind) {
    var d = "M" + points.map(function (p) { return p[0].toFixed(1) + "," + p[1].toFixed(1); }).join(" L");
    var out = '<g class="spec-scene-flow' + (active ? " is-on" : "") + '">' +
      '<path d="' + d + '" fill="none" stroke="' + (kind === "belt" ? "#4a4a4a" : kind === "lift" ? "rgba(90,90,90,.7)" : shade(color, -0.25)) +
      '" stroke-width="' + (kind === "belt" ? 4.5 : kind === "lift" ? 1 : 3) + '" stroke-linecap="round" stroke-linejoin="round"' +
      (active ? "" : ' stroke-dasharray="5 5" opacity=".45"') + (active && kind === "belt" ? ' class="spec-scene-belt"' : "") + "/>";
    if (active && !still) {
      var n = kind === "lift" ? 1 : kind === "cubes" ? 3 : 6, dur = kind === "lift" ? 5 : kind === "cubes" ? 6 : 3;
      for (var i = 0; i < n; i++) {
        var begin = "-" + (dur * i / n).toFixed(2) + "s";
        var grain = kind === "cubes" ? '<rect x="-3" y="-3" width="6" height="6" fill="' + color + '" stroke="rgba(0,0,0,.3)" stroke-width=".5">'
          : kind === "lift" ? '<rect x="-9" y="-5" width="18" height="10" fill="none" stroke="' + color + '" stroke-width="2">'
          : '<circle r="' + (kind === "belt" ? 2.6 : 2.2) + '" fill="' + color + '" stroke="rgba(255,255,255,.7)" stroke-width=".6">';
        out += grain + '<animateMotion dur="' + dur + 's" begin="' + begin + '" repeatCount="indefinite" path="' + d + '"/>' +
          (kind === "cubes" || kind === "lift" ? "</rect>" : "</circle>");
      }
    }
    return out + "</g>";
  }
  var W = P;
  // The part of a ground polygon beyond x = v (the sea).
  function clip(poly, v) {
    var out = [];
    for (var i = 0; i < poly.length; i++) {
      var a = poly[i], b = poly[(i + 1) % poly.length], ia = a[0] >= v, ib = b[0] >= v;
      if (ia) out.push(a);
      if (ia !== ib) { var t = (v - a[0]) / (b[0] - a[0]); out.push([v, a[1] + (b[1] - a[1]) * t]); }
    }
    return out;
  }
  function has(site, re) { return (site.elements || []).some(function (e) { return re.test(e); }); }
  var CONC = "#bdbcb6";
  var BUILD = {
    // A frame of three floors: its foundations (on piles when it has them),
    // columns, slabs and a core wall, as its elements say.
    building: function (x, y, site, built) {
      var out = "", piles = has(site, /pile/), cols = has(site, /column/) || !site.elements.length, walls = has(site, /wall/);
      if (piles) for (var p = 0; p < 6; p++) out += cyl(x + 0.6 + (p % 3) * 3, y + 0.6 + Math.floor(p / 3) * 4, -0.1, 0.25, 0.1, "#8d8a80");
      out += box(x - 0.3, y - 0.3, 0, 7.6, 5.6, 0.5, "#a9a7a0");
      for (var f = 0; f < 3; f++) {
        var z = 0.5 + f * 3;
        if (cols) for (var c = 0; c < 6; c++) out += box(x + 0.3 + (c % 3) * 3, y + 0.3 + Math.floor(c / 3) * 4.2, z, 0.4, 0.4, 2.7, CONC);
        if (walls) out += box(x + 5.4, y + 1.6, z, 1.4, 1.6, 2.7, shade(CONC, -0.06));
        if (f < 2 || !site.steel) out += box(x, y, z + 2.7, 7.0, 5.0, 0.3, shade(CONC, 0.08));
      }
      if (site.steel) {
        var z2 = 6.5 + 2.7;
        for (var s2 = 0; s2 < 6; s2++) out += box(x + 0.35 + (s2 % 3) * 3, y + 0.35 + Math.floor(s2 / 3) * 4.2, z2 - 2.7 + 0.3, 0.25, 0.25, 2.6, "#365e8c");
        out += box(x, y, z2 + 0.2, 7.0, 0.25, 0.3, "#4673a6") + box(x, y + 4.75, z2 + 0.2, 7.0, 0.25, 0.3, "#4673a6");
        out += '<polygon points="' + pts([P(x, y, z2 + 0.5), P(x + 7, y, z2 + 0.5), P(x + 7, y + 5, z2 + 0.5), P(x, y + 5, z2 + 0.5)]) + '" fill="#8d99a6" opacity=".85"/>';
      }
      // Crane rails on corbels along the frame, the travelling crane across them.
      if (site.cranes) {
        out += box(x, y + 0.05, 6.2, 7.0, 0.35, 0.35, "#555") + box(x, y + 4.6, 6.2, 7.0, 0.35, 0.35, "#555");
        out += box(x + 3.2, y - 0.1, 6.55, 0.6, 5.2, 0.55, "#e0a32a") + box(x + 3.25, y + 2.2, 6.0, 0.5, 0.6, 0.5, "#555");
      }
      return out;
    },
    // A quay on its piles at the sea's edge: fenders on its face, bollards on
    // its deck, the quay wall behind, and crane rails with the crane on them.
    quay: function (x, y, site) {
      var out = "";
      for (var p = 0; p < 10; p++) out += box(x + 2.5 + (p % 5) * 2.2, y + 0.4 + Math.floor(p / 5) * 3.4, -1.6, 0.4, 0.4, 3.4, "#9a9890");
      if (has(site, /quay/)) out += box(x, y - 0.6, 0, 2.2, 5.6, 1.8, shade(CONC, -0.1));
      out += box(x, y, 1.8, 12, 4.4, 0.5, CONC);
      for (var f = 0; f < 4; f++) out += box(x + 3 + f * 2.4, y + 4.4, 1.0, 0.8, 0.25, 1.0, "#222831");
      for (var b = 0; b < 3; b++) out += cyl(x + 3.4 + b * 3.4, y + 3.9, 2.3, 0.15, 0.35, "#333");
      if (site.cranes) {
        out += line(P(x, y + 0.6, 2.32), P(x + 12, y + 0.6, 2.32), "#555", 1.4) + line(P(x, y + 3.2, 2.32), P(x + 12, y + 3.2, 2.32), "#555", 1.4);
        out += crane(x + 5, y + 0.6, 2.3, 2.6);
      }
      return out;
    },
    // A bridge: piers up from the river on their piles, the deck across.
    span: function (x, y, site) {
      var out = '<polygon class="spec-scene-river" points="' + pts([P(x - 2, y + 2.2, 0), P(x + 11, y + 2.2, 0), P(x + 11, y + 4.6, 0), P(x - 2, y + 4.6, 0)]) + '"/>';
      [0.6, 4.6, 8.6].forEach(function (px) {
        out += box(x + px - 0.4, y + 2.6, 0, 1.4, 1.4, 0.5, "#a9a7a0") + box(x + px, y + 3.0, 0.5, 0.6, 0.6, 2.8, CONC);
      });
      out += box(x - 1.4, y + 2.4, 3.3, 11.6, 1.8, 0.45, shade(CONC, 0.06));
      out += box(x - 1.4, y + 2.4, 3.75, 11.6, 0.1, 0.4, "#8a8f96") + box(x - 1.4, y + 4.1, 3.75, 11.6, 0.1, 0.4, "#8a8f96");
      return out;
    }
  };
  // A gantry crane on its rails: legs, the beam across, the hoist and its hook.
  function crane(x, y, z, gauge) {
    gauge = gauge || 2.6;
    var c = "#e0a32a", out = "";
    out += box(x, y, z, 0.3, 0.3, 5.5, c) + box(x, y + gauge, z, 0.3, 0.3, 5.5, c) + box(x + 2.4, y, z, 0.3, 0.3, 5.5, c) + box(x + 2.4, y + gauge, z, 0.3, 0.3, 5.5, c);
    out += box(x, y - 2.5, z + 5.5, 0.4, gauge + 4.5, 0.5, c) + box(x + 2.3, y - 2.5, z + 5.5, 0.4, gauge + 4.5, 0.5, c);
    out += box(x + 0.6, y + gauge + 0.8, z + 5.2, 1.5, 0.8, 0.4, "#555") + line(P(x + 1.35, y + gauge + 1.2, z + 5.2), P(x + 1.35, y + gauge + 1.2, z + 2.6), "#333", 1);
    return out;
  }

  function draw() {
    index();
    var minX = 1e9, minY = 1e9, maxX = -1e9, maxY = -1e9;
    function grow(p, pad) { minX = Math.min(minX, p[0] - pad); maxX = Math.max(maxX, p[0] + pad); minY = Math.min(minY, p[1] - pad); maxY = Math.max(maxY, p[1] + pad); }
    var site = data.site || {};
    var shown = Object.keys(PLACE).filter(function (id) { return byId[id] || PLANT.indexOf(id) >= 0 || wanted(id); });
    var works = Object.keys(WORKS).filter(function (k) { return k === "building" ? site.building : k === "quay" ? site.marine : site.bridge; });
    // A bridge project's questions stand on the bridge it builds.
    PLACE.bridge = site.bridge ? [WORKS.span[0] + 4.6, WORKS.span[1] + 2.4] : BRIDGE_AT;
    PIN.bridge = site.bridge ? 4.4 : 2.8;
    var gx0 = 1e9, gy0 = 1e9, gx1 = -1e9, gy1 = -1e9;
    shown.forEach(function (id) {
      gx0 = Math.min(gx0, PLACE[id][0]); gy0 = Math.min(gy0, PLACE[id][1]);
      gx1 = Math.max(gx1, PLACE[id][0]); gy1 = Math.max(gy1, PLACE[id][1]);
    });
    works.forEach(function (k) {
      var w = WORKS[k];
      gx0 = Math.min(gx0, w[0] - 2); gy0 = Math.min(gy0, w[1] - 2); gx1 = Math.max(gx1, w[0] + w[2]); gy1 = Math.max(gy1, w[1] + w[3]);
    });
    if (site.marine) gx1 = Math.max(gx1, SEA + 10);
    gx0 = Math.floor(gx0 - 3); gy0 = Math.floor(gy0 - 3); gx1 = Math.ceil(gx1 + 6); gy1 = Math.ceil(gy1 + 5);
    [[gx0, gy0], [gx1, gy0], [gx1, gy1], [gx0, gy1]].forEach(function (c) { grow(P(c[0], c[1], 0), 4); });

    var parts = [];
    parts.push('<polygon class="spec-scene-ground" points="' + pts([P(gx0, gy0, 0), P(gx1, gy0, 0), P(gx1, gy1, 0), P(gx0, gy1, 0)]) + '"/>');
    for (var g = gx0; g <= gx1; g += 2) parts.push(line(P(g, gy0, 0), P(g, gy1, 0), "var(--scene-grid)", 0.5));
    for (var h = gy0; h <= gy1; h += 2) parts.push(line(P(gx0, h, 0), P(gx1, h, 0), "var(--scene-grid)", 0.5));
    // A marine project's site runs down to the sea.
    if (site.marine) {
      var sea = clip([[gx0, gy0], [gx1, gy0], [gx1, gy1], [gx0, gy1]], SEA);
      if (sea.length) {
        parts.push('<polygon class="spec-scene-sea" points="' + pts(sea.map(function (c) { return P(c[0], c[1], 0); })) + '"/>');
        for (var wv = 0; wv < 12; wv++) {
          var wp = P(SEA + 2 + (wv % 4) * 2.2, gy0 + 3 + Math.floor(wv / 4) * ((gy1 - gy0 - 6) / 2) + (wv % 2) * 1.5, 0);
          parts.push('<path class="spec-scene-wave" style="animation-delay:' + (wv * 0.35).toFixed(2) + 's" d="M' + (wp[0] - 12).toFixed(1) + "," + wp[1].toFixed(1) + ' q6,-4 12,0 t12,0" fill="none"/>');
        }
      }
    }
    // The way through the site, level by level, from the brief to the last station.
    var walk = [];
    order.forEach(function (id) { if (PLACE[id] && shown.indexOf(id) >= 0) { var at = PLACE[id], mid = MID[id] || [0, 0]; walk.push(P(at[0] + mid[0], at[1] + mid[1] + 1.6, 0)); } });
    if (walk.length > 1) {
      var reached = 0;
      order.forEach(function (id, i) { if (byId[id] && byId[id].stage <= data.open_stage) reached = i; });
      parts.push('<polyline class="spec-scene-walk" points="' + pts(walk) + '"/>');
      parts.push('<polyline class="spec-scene-walk is-done" points="' + pts(walk.slice(0, reached + 1)) + '"/>');
    }

    var m = PLACE.mixer, pump = PLACE.pour, form = PLACE.formwork, cage = PLACE.rebar, lab = PLACE.lab;
    var fc = [form[0] + 1.7, form[1] + 1.2];           // the middle of the formwork
    // The haul road from under the mixer to the pump.
    var tA = [m[0] + 1.4, m[1] + 1.2], tB = [pump[0] + 2.6, pump[1] - 0.6];
    parts.push('<polyline class="spec-scene-road" points="' + pts([P(tA[0], tA[1] - 3, 0), P(tA[0], tA[1] + 1.5, 0), P(tB[0], tB[1] + 1, 0)]) + '"/>');

    var mixed = done("mixer");
    var bar = BAR[(site.rebar || [])[0]] || BAR.Uncoated;
    var st = { formwork: { steel: done("rebar"), poured: done("pour"), cured: done("pour"), elements: site.elements || [], bar: bar, pt: done("tendons") && site.pt },
      pour: { to: fc }, rebar: { kinds: site.rebar }, tendons: { pt: site.pt }, precast: { kind: site.precast } };
    var drawOrder = shown.slice().sort(function (a, b) { return (PLACE[a][0] + PLACE[a][1]) - (PLACE[b][0] + PLACE[b][1]); });
    centre = {};
    var truckAt = tA[0] + tA[1];
    var truckDrawn = false;
    function truck() {
      var dA = P(tA[0], tA[1] + 0.5, 0), dB = P(tB[0], tB[1], 0);
      return '<g class="spec-scene-truck' + (mixed ? " is-on" : "") + '" style="--tx:' + (dB[0] - dA[0]).toFixed(0) + "px;--ty:" + (dB[1] - dA[1]).toFixed(0) + 'px">' +
        box(tA[0] - 0.5, tA[1] - 2.2, 0.2, 1.0, 2.2, 0.4, "#5a5a5a") + cyl(tA[0], tA[1] - 1.3, 0.6, 0.55, 1.1, "#e8e8e8", mixed ? "" : "") +
        box(tA[0] - 0.5, tA[1], 0.2, 1.0, 1.0, 1.0, "#2a78d6") + "</g>";
    }
    drawOrder.forEach(function (id) {
      if (!truckDrawn && PLACE[id][0] + PLACE[id][1] > truckAt) { parts.push(truck()); truckDrawn = true; }
      var s = byId[id], at = PLACE[id], mid = MID[id] || [0, 0];
      var art = DRAW[id](at[0], at[1], st[id]);
      if (!s) { parts.push('<g class="spec-scene-prop">' + art + "</g>"); return; }
      var pin = P(at[0] + mid[0], at[1] + mid[1], PIN[id] + 0.8), foot = P(at[0] + mid[0], at[1] + mid[1], 0);
      centre[id] = [(pin[0] + foot[0]) / 2, (pin[1] + foot[1]) / 2 + 10];
      grow(pin, 40); grow(foot, 70);
      var state = checks ? (findings(id).length ? "needed" : "answered") : stateOf(s);
      var left = checks ? findings(id).length : openCount(s);
      var mark = s.locked && !checks
        ? '<path d="M' + (pin[0] - 4.5) + "," + (pin[1] - 1) + "h9v7h-9z M" + (pin[0] - 2.8) + "," + (pin[1] - 1) + "v-2.5a2.8,2.8 0 0 1 5.6,0v2.5" + '" fill="none" stroke="#fff" stroke-width="1.6"/>'
        : '<text x="' + pin[0] + '" y="' + (pin[1] + 4) + '" text-anchor="middle">' + (left ? left : "✓") + "</text>";
      var words = checks ? s.name + ": " + (left ? left + " finding" + (left === 1 ? "" : "s") + " to settle" : "nothing open") :
        s.name + ": " + s.questions.length + " questions, " + (s.locked ? "locked until the stage before is answered" :
        s.needed ? s.needed + " need an answer" : s.suggested ? s.suggested + " suggested to accept" : "all answered");
      parts.push('<g class="spec-scene-st spec-in-' + state + (s.locked && !checks ? " is-locked" : "") + (s.stage === data.open_stage && !checks ? " is-now" : "") +
        (id === current ? " is-on" : "") + '" data-id="' + id + '" tabindex="0" role="button" aria-label="' + esc(words) + '">' +
        '<ellipse class="spec-scene-halo" cx="' + foot[0] + '" cy="' + foot[1] + '" rx="70" ry="35"/>' + art +
        line(foot, pin, "var(--scene-pin-line)", 0.8) +
        '<g class="spec-scene-pin"><circle cx="' + pin[0] + '" cy="' + pin[1] + '" r="11"/>' + mark + "</g>" +
        '<text class="spec-scene-label" x="' + pin[0] + '" y="' + (pin[1] - 16) + '" text-anchor="middle">' + esc(s.name) + "</text></g>");
    });
    if (!truckDrawn) parts.push(truck());
    // What the project builds: drawn faint until the pour is answered, then in
    // concrete; the steel frame on it once that is.
    var built = done("pour");
    works.forEach(function (k) {
      var w = WORKS[k];
      parts.push('<g class="spec-scene-works' + (built ? " is-built" : "") + '">' + BUILD[k](w[0], w[1], site, built) + "</g>");
      grow(P(w[0], w[1], 12), 30); grow(P(w[0] + w[2], w[1] + w[3], 0), 30);
      grow(P(w[0] + w[2], w[1], 0), 30); grow(P(w[0], w[1] + w[3], 0), 30);
    });

    // How the materials go, each moving once its stage is answered.
    var mt = [m[0] + 1.4, m[1] + 1.2, 5.1];             // the mixer's charging hopper
    var c = PLACE.cement, wt = PLACE.water, ad = PLACE.admixtures, sd = PLACE.sand, gv = PLACE.gravel;
    var flows = [
      flow([W(c[0] + 1.1, c[1] + 0.2, 7.6), W(mt[0] - 0.4, mt[1] - 0.6, mt[2] + 0.5)], "#c9ccd1", done("cement")),
      flow([W(wt[0] + 1.1, wt[1], 0.4), W(m[0] - 0.4, wt[1], 0.4), W(m[0] - 0.4, m[1] + 0.6, 0.4), W(m[0] - 0.4, m[1] + 0.6, 5.6), W(mt[0] - 0.3, mt[1], 5.6)], "#4f8fd1", done("water")),
      flow([W(ad[0] + 0.5, ad[1] + 0.5, 1.3), W(ad[0] + 0.5, ad[1] + 0.5, 6.2), W(mt[0] + 0.3, mt[1] - 0.2, 6.2), W(mt[0] + 0.3, mt[1] - 0.2, 5.3)], "#e27a3a", done("admixtures")),
      flow([W(sd[0] + 1.6, sd[1] - 0.2, 0.4), W(mt[0] - 0.3, mt[1] + 0.6, mt[2] + 0.2)], "#e2c27a", done("sand"), "belt"),
      flow([W(gv[0] + 1.5, gv[1] - 0.3, 0.4), W(mt[0] + 0.2, mt[1] + 0.8, mt[2] + 0.2)], "#8f8c86", done("gravel"), "belt"),
      flow([W(tA[0], tA[1], 2.0), W(tA[0], tA[1] - 0.6, 1.6)], "#9b9b97", mixed),
      flow([W(pump[0] + 0.7, pump[1] + 0.5, 1.8), W((pump[0] + fc[0]) / 2, (pump[1] + fc[1]) / 2, 6.2), W(fc[0], fc[1], 4.0), W(fc[0], fc[1], 1.4)], "#8d8d89", done("pour")),
      flow([W(cage[0] + 1.5, cage[1] + 1.2, 1.6), W(cage[0] + 1.5, cage[1] + 1.2, 6), W(fc[0], fc[1], 6), W(fc[0], fc[1], 1.2)], "#9a532a", done("rebar"), "lift"),
      flow([W(form[0] + 3.5, form[1] + 2.0, 0.25), W(lab[0] + 1.5, form[1] + 2.0, 0.25), W(lab[0] + 1.5, lab[1] + 2.4, 0.25)], "#a9a9a6", done("pour"), "cubes")
    ];
    parts.push('<g class="spec-scene-flows">' + flows.join("") + "</g>");
    svg.innerHTML = parts.join("");
    whole = [minX, minY, maxX - minX, maxY - minY];
    stageText();
    levels();
  }

  // --- zooming ----------------------------------------------------------------------

  var view = null, anim = null;
  function setView(v) { view = v; svg.setAttribute("viewBox", v.map(function (n) { return n.toFixed(1); }).join(" ")); }
  function zoomTo(target) {
    if (anim) cancelAnimationFrame(anim);
    if (still || !view) { setView(target); return; }
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
    var shift = window.innerWidth > 900 ? w * 0.22 : 0;
    return [c[0] - w / 2 + shift, c[1] - h / 2, w, h];
  }

  // --- the stage the project is at ---------------------------------------------------

  var stageEl = root.querySelector("[data-stage]");
  function stageText() {
    if (!stageEl) return;
    if (checks) {
      var n = data.flags.total, at = Object.keys(data.flags.stations).length;
      stageEl.classList.toggle("is-done", !n);
      stageEl.textContent = n ? n + " finding" + (n === 1 ? "" : "s") + " to settle, at " + at + " part" + (at === 1 ? "" : "s") + " of the works." : "Nothing on the check is open.";
      return;
    }
    var n = data.chapters.length, c = data.chapters[data.open_stage];
    stageEl.classList.toggle("is-done", !c);
    var next = data.chapters[data.open_stage + 1];
    stageEl.textContent = !c ? "Every stage is answered." :
      "Level " + (data.open_stage + 1) + " of " + n + ", " + c.name + ": " + (c.slug === "deciding" ? "decide the brief first." : (c.needed + c.suggested) + " to answer or accept.") +
      (next ? " Next: " + next.name + "." : "");
  }
  // The levels as a row above the picture: done, the one open now, locked.
  var levelsEl = root.querySelector("[data-levels]");
  function levels() {
    if (!levelsEl) return;
    levelsEl.innerHTML = data.chapters.map(function (c, i) {
      var state = c.locked ? "locked" : i === data.open_stage ? "now" : "done";
      var left = c.needed + c.suggested;
      return '<li class="spec-level is-' + state + '"><button type="button" data-level="' + i + '" title="' + esc(c.lead || "") + '">' +
        '<span class="spec-level-n">' + (state === "done" ? "✓" : state === "locked" ? "🔒︎" : c.level) + "</span>" +
        '<span class="spec-level-name">' + esc(c.name) + "</span>" + (state === "now" && left ? '<span class="spec-level-left">' + left + "</span>" : "") + "</button></li>";
    }).join("");
  }
  if (levelsEl) levelsEl.addEventListener("click", function (e) {
    var b = e.target.closest("[data-level]");
    if (!b) return;
    var c = data.chapters[+b.getAttribute("data-level")];
    if (c && c.stations.length) open(firstOpen(c));
  });
  function firstOpen(c) {
    return c.stations.filter(function (id) { return openCount(byId[id]); })[0] || c.stations[0];
  }
  function hold(why) {
    if (stageEl) {
      stageEl.textContent = why;
      stageEl.classList.add("is-held");
      setTimeout(function () { stageEl.classList.remove("is-held"); stageText(); }, 4000);
    }
  }

  // --- the panel: the station's questions, answered there ---------------------------

  var current = null, loading = 0;
  var stationUrl = root.getAttribute("data-station-url");
  function chapterOf(id) {
    for (var i = 0; i < data.chapters.length; i++) if (data.chapters[i].stations.indexOf(id) >= 0) return data.chapters[i];
    return null;
  }
  function load(id, note) {
    var mine = ++loading;
    if (!note) body.innerHTML = '<p class="small muted">Loading…</p>';
    fetch(stationUrl.replace("STATION", encodeURIComponent(id)), { credentials: "same-origin" })
      .then(function (r) { if (!r.ok) throw r; return r.text(); })
      .then(function (html) {
        if (mine !== loading) return;
        body.innerHTML = (note || "") + html;
        if (!note) panel.scrollTop = 0;
      })
      .catch(function () { if (mine === loading) body.innerHTML = '<p class="small muted">Could not load this station\'s questions. The summary below has them, and Details answers them.</p>'; });
  }
  function showFindings(id) {
    var s = byId[id], list = findings(id);
    body.innerHTML = "<h2>" + esc(s.name) + '</h2><p class="small muted">' + esc(s.what || "") + "</p>" +
      (list.length ? '<p class="small"><strong>' + list.length + " to settle</strong> here. Each opens on the check below.</p>" +
        '<ul class="spec-scene-flags">' + list.map(function (f) {
          return '<li class="spec-scene-flag spec-sev-' + esc(f.severity) + '"><span class="small muted">' + esc(f.group) + (f.section ? " · " + esc(f.section) : "") + "</span>" +
            '<a href="' + esc(f.url) + '" data-flag>' + esc(f.text) + "</a></li>";
        }).join("") + "</ul>"
        : '<p class="small">Nothing open here.</p>');
    panel.scrollTop = 0;
  }
  function open(id, fromPlay) {
    var s = byId[id];
    if (!s) return;
    current = id;
    if (!fromPlay) stop();
    Array.prototype.forEach.call(svg.querySelectorAll(".spec-scene-st"), function (g) { g.classList.toggle("is-on", g.getAttribute("data-id") === id); });
    svg.classList.add("is-zoomed");
    panel.hidden = false;
    if (checks) showFindings(id); else load(id);
    var c = chapterOf(id);
    caption.textContent = (c && !checks ? "Level " + c.level + " · " : "") + s.name + (s.locked && !checks ? " · locked" : "");
    zoomTo(viewFor(id));
  }
  function close() {
    current = null;
    loading++;
    panel.hidden = true;
    svg.classList.remove("is-zoomed");
    Array.prototype.forEach.call(svg.querySelectorAll(".spec-scene-st"), function (g) { g.classList.remove("is-on"); });
    caption.textContent = "";
    zoomTo(whole);
  }
  // Next goes on through the story, but not into a stage that is still locked.
  function move(by) {
    var i = current ? order.indexOf(current) : -1;
    var next = order[(i + by + order.length) % order.length];
    if (by > 0 && byId[next].locked && !checks) {
      var c = data.chapters[data.open_stage];
      hold(c.slug === "deciding" ? "Decide the brief first: the next level opens once it is confirmed." :
        "Answer the " + (c.needed + c.suggested) + " left in " + c.name + " first: the next level opens once it is done.");
      if (current !== firstOpen(c)) open(firstOpen(c), !!timer);
      return false;
    }
    open(next, !!timer);
    return true;
  }

  // Saving from the panel: the answers go to the project, the picture and the
  // summary below are redrawn from what was saved.
  var summaryUrl = window.location.pathname;
  function refreshSummary() {
    fetch(summaryUrl, { credentials: "same-origin" }).then(function (r) { return r.ok ? r.text() : ""; }).then(function (html) {
      if (!html) return;
      var doc = new DOMParser().parseFromString(html, "text/html");
      ["[data-totals]", "[data-summary]"].forEach(function (sel) {
        var fresh = doc.querySelector(sel), old = document.querySelector(sel);
        if (fresh && old) old.innerHTML = fresh.innerHTML;
      });
    }).catch(function () {});
  }
  body.addEventListener("submit", function (e) {
    var form = e.target.closest("[data-station-form]");
    if (!form || !window.fetch || !window.FormData) return;
    e.preventDefault();
    var id = current, wasStage = data.open_stage;
    var btn = form.querySelector("[type=submit]");
    var label = btn ? btn.textContent : "";
    if (btn) { btn.disabled = true; btn.textContent = "Saving…"; }
    fetch(form.action, { method: "POST", body: new FormData(form), credentials: "same-origin", headers: { "X-Requested-With": "fetch" } })
      .then(function (r) {
        var type = r.headers.get("Content-Type") || "";
        if (!r.ok || type.indexOf("json") < 0) throw r;
        return r.json();
      })
      .then(function (resp) {
        data = resp.scene;
        draw();
        if (view) setView(view);
        var note = resp.messages.map(function (m) { return '<div class="flash ' + esc(m.kind) + '">' + (m.html != null ? m.html : esc(m.text)) + "</div>"; }).join("");
        var c = data.chapters[data.open_stage];
        if (data.open_stage > wasStage) {
          note += '<div class="flash success spec-scene-opened"><strong>' + esc(data.chapters[wasStage].name) + " is done.</strong> " +
            (c ? 'The next level is open: <button type="button" class="btn btn-primary btn-sm" data-go-stage="' + esc(firstOpen(c)) + '">Go to ' + esc(c.name) + " →</button>" : "Every stage is answered.") + "</div>";
        }
        load(id, note);
        refreshSummary();
      })
      .catch(function () {
        if (btn) { btn.disabled = false; btn.textContent = label; }
        var bad = form.querySelector("[data-save-note]");
        if (bad) { bad.textContent = "Could not save. Check you are still signed in, then try again."; bad.classList.add("spec-scene-bad"); }
      });
  });
  // The question controls, as on Details: typing an answer of your own picks
  // it; "different for some elements" shows a row for each.
  body.addEventListener("input", function (e) {
    var box = e.target.closest("[data-pick-free]");
    if (!box) return;
    var pick = box.parentNode.querySelector("input[type=radio]");
    if (pick && box.value) pick.checked = true;
  });
  body.addEventListener("change", function (e) {
    var bar = e.target.closest("[data-split]");
    if (bar && bar.nextElementSibling) bar.nextElementSibling.hidden = e.target.value !== "1";
  });
  body.addEventListener("click", function (e) {
    var go = e.target.closest("[data-go-stage]");
    if (go) { e.preventDefault(); open(go.getAttribute("data-go-stage")); }
  });

  // --- playing the story ------------------------------------------------------------

  var timer = null;
  function stop() {
    if (!timer) return;
    clearInterval(timer); timer = null;
    playBtn.textContent = playWords;
  }
  function play() {
    if (timer) { stop(); return; }
    playBtn.textContent = "❚❚ Pause";
    timer = setInterval(function () {
      if (current === order[order.length - 1]) { stop(); close(); return; }
      if (!move(1)) stop();
    }, 6000);
    if (!current) open(order[0], true); else if (!move(1)) stop();
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
    if (/^(INPUT|TEXTAREA|SELECT|BUTTON)$/.test(e.target.tagName) || e.target.isContentEditable) return;
    if (e.key === "ArrowRight") { move(1); } else if (e.key === "ArrowLeft") { move(-1); } else if (e.key === "Escape") { stop(); close(); }
  });
  playBtn.addEventListener("click", play);
  root.querySelector("[data-next]").addEventListener("click", function () { move(1); });
  root.querySelector("[data-prev]").addEventListener("click", function () { move(-1); });
  root.querySelector("[data-whole]").addEventListener("click", function () { stop(); close(); });
  root.querySelector("[data-close]").addEventListener("click", function () { stop(); close(); });

  draw();
  setView(whole);
  svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
  root.classList.add("is-live");
  // Opened at a station (#st-id, as a save without scripts comes back to).
  var at = (window.location.hash.match(/^#st-(\w+)$/) || [])[1];
  if (at && byId[at]) open(at);
})();

// The panel explaining a question, as on Details: what it means, a drawing,
// and what the project's codes say.
(function () {
  var panel = document.getElementById("spec-explain");
  if (!panel || !window.fetch) return;
  var body = panel.querySelector("[data-explain-body]"), current = "";
  function open(key) {
    if (current === key && !panel.hidden) return;
    current = key;
    panel.hidden = false;
    body.innerHTML = '<p class="small muted">Loading…</p>';
    fetch(panel.getAttribute("data-url").replace("KEY", encodeURIComponent(key)), { credentials: "same-origin" })
      .then(function (r) { if (!r.ok) throw r; return r.text(); })
      .then(function (html) { if (current === key) { body.innerHTML = html; body.scrollTop = 0; } })
      .catch(function () { body.innerHTML = '<p class="small muted">Could not load this question\'s explanation.</p>'; });
  }
  function close() { panel.hidden = true; current = ""; }
  document.addEventListener("click", function (e) {
    var t = e.target.closest && e.target.closest("[data-explain]");
    if (t) { e.preventDefault(); e.stopPropagation(); open(t.getAttribute("data-explain")); return; }
    if (e.target.closest && e.target.closest("[data-explain-close]")) close();
  }, true);
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && !panel.hidden) { e.stopPropagation(); close(); } }, true);
})();
