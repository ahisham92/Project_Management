/* The section editor: the section laid out on a page the way it is issued,
   edited in place, with a ribbon of commands as in Word.

   Each paragraph is one block on the page carrying its level (PART, article,
   paragraph A., 1., a., 1), an editor's note or a table), its condition and
   its id; the numbers are worked out as you type. Fields (cross-references,
   project words, choices in the text) sit in the text as small shaded boxes
   and are kept as they are written, {ref:033000} and so on. On saving, the
   paragraphs go back as they are, with their ids, so nothing has to be
   matched up again. */
(function () {
  "use strict";
  var root = document.querySelector("[data-se]");
  if (!root) return;
  var form = document.getElementById("spec-edit-form");
  var data = JSON.parse(document.getElementById("se-data").textContent);
  var flow = root.querySelector("[data-flow]");
  var page = root.querySelector("[data-page]");
  var canvas = root.querySelector("[data-canvas]");
  var nav = root.querySelector("[data-nav]");
  var statusBar = root.querySelector("[data-status]");
  var plain = root.querySelector("[data-plain]");
  var textarea = plain.querySelector("textarea");
  var findBar = root.querySelector("[data-find]");
  var dialog = document.querySelector("[data-dialog]");

  var LEVELS = ["PRT", "ART", "PR1", "PR2", "PR3", "PR4"];
  var NBS = !!data.nbs;
  var MARK = { PRT: "#", ART: "##", PR1: "-", PR2: "--", PR3: "---", PR4: "----", CMT: "//" };
  var LEVEL_OF = {}; Object.keys(MARK).forEach(function (k) { LEVEL_OF[MARK[k]] = k; });
  var STYLES = [
    { level: "PRT", name: NBS ? "Heading" : "Part", sample: NBS ? "General" : "PART 1 - GENERAL" },
    { level: "ART", name: NBS ? "Clause" : "Article", sample: NBS ? "110 Scope" : "1.1 SUMMARY" },
    { level: "PR1", name: "Paragraph", sample: NBS ? "• Text" : "A. Text" },
    { level: "PR2", name: "Sub-paragraph", sample: NBS ? "– Text" : "1. Text" },
    { level: "PR3", name: "Item", sample: NBS ? "· Text" : "a. Text" },
    { level: "PR4", name: "Sub-item", sample: NBS ? "· Text" : "1) Text" },
    { level: "CMT", name: "Editor's note", sample: "Note" }
  ];
  var STYLE_NAME = {}; STYLES.forEach(function (s) { STYLE_NAME[s.level] = s.name; });
  STYLE_NAME.TBL = "Table";
  var TOKEN = /\{ref:\s*([^}]+?)\s*\}|\{\{\s*([A-Za-z0-9_]+)\s*\}\}|\{([A-Za-z0-9_]+)\s*(!?=)\s*([^:{}]+?)\s*:\s?([^{}]*)\}/g;
  var varLabel = {}; data.variables.forEach(function (v) { varLabel[v.key] = v.label; });
  var optByKey = {}; data.options.forEach(function (o) { optByKey[o.key] = o; });
  var sectionTitle = {}; data.sections.forEach(function (s) { sectionTitle[s.number.toLowerCase()] = s.title; });

  var here = null;          // the paragraph the caret is in
  var savedRange = null;    // where the caret was before a dialog took the focus
  var undo = [], redo = [], lastSnap = 0;
  var dirty = false, zoom = 1, spell = true;

  // --- small helpers -------------------------------------------------------------------

  function esc(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  function letter(n, upper) {
    var out = "";
    while (n > 0) { var rem = (n - 1) % 26; out = String.fromCharCode(65 + rem) + out; n = Math.floor((n - 1) / 26); }
    return upper ? out : out.toLowerCase();
  }
  function paras() { return Array.prototype.slice.call(flow.children); }
  function textOf(p) { return p.querySelector(".se-text"); }
  function norm(s) { return String(s || "").replace(/\s+/g, " ").trim().toLowerCase(); }
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  // --- the text of a paragraph, with its fields ----------------------------------------

  var ONE_TOKEN = new RegExp("^(?:" + TOKEN.source + ")$");
  function tokenHTML(raw) {
    var m = ONE_TOKEN.exec(raw);
    if (!m || m[0] !== raw) return esc(raw);
    var cls, label, title;
    if (m[1] !== undefined) {
      var t = m[1].trim();
      cls = "se-ref";
      if (t.charAt(0) === "#") label = "→ ¶ " + t.slice(1);
      else if (t.indexOf("/") > 0) label = "→ " + t.split("/")[1] + ", Section " + t.split("/")[0];
      else if (/^[0-9]/.test(t) || sectionTitle[t.toLowerCase()]) {
        label = "Section " + t + (sectionTitle[t.toLowerCase()] ? " “" + sectionTitle[t.toLowerCase()] + "”" : "");
      } else label = "→ Article " + t;
      title = "Cross-reference, written out as it stands when issued: " + raw;
      return '<span class="se-tok ' + cls + '" contenteditable="false" data-raw="' + esc(raw) + '" title="' + esc(title) + '">' + esc(label) + "</span>";
    }
    if (m[2] !== undefined) {
      title = "Filled in for each project: " + (varLabel[m[2]] || m[2]);
      return '<span class="se-tok se-var" contenteditable="false" data-raw="' + esc(raw) + '" title="' + esc(title) + '">[' + esc(varLabel[m[2]] || m[2]) + "]</span>";
    }
    title = "Issued only when " + m[3] + " " + (m[4] === "=" ? "is" : "is not") + " " + m[5];
    return '<span class="se-tok se-choice" contenteditable="false" data-raw="' + esc(raw) + '" title="' + esc(title) + '"><b>' +
      esc(m[3] + m[4] + m[5]) + "</b>" + esc(m[6]) + "</span>";
  }
  function textHTML(text) {
    var out = "", last = 0, m;
    TOKEN.lastIndex = 0;
    while ((m = TOKEN.exec(text))) {
      out += esc(text.slice(last, m.index)) + tokenHTML(m[0]);
      last = TOKEN.lastIndex;
    }
    return out + esc(text.slice(last));
  }
  function readText(node) {
    var out = "";
    for (var i = 0; i < node.childNodes.length; i++) {
      var n = node.childNodes[i];
      if (n.nodeType === 3) out += n.nodeValue;
      else if (n.nodeType === 1) {
        if (n.hasAttribute("data-raw")) out += n.getAttribute("data-raw");
        else if (n.tagName === "BR") out += " ";
        else out += readText(n);
      }
    }
    return out.replace(/ /g, " ").replace(/​/g, "");
  }
  function condChip(when) {
    var c = el("span", "se-cond");
    c.contentEditable = "false";
    c.setAttribute("data-raw", "");
    c.title = "Only for projects where this holds. Click to change.";
    c.textContent = "only if " + when;
    return c;
  }
  function setText(t, text, when) {
    t.innerHTML = textHTML(text);
    if (when) t.insertBefore(condChip(when), t.firstChild);
  }

  // --- tables ---------------------------------------------------------------------------

  function rowsOf(text) {
    return String(text || "").split("\n").filter(function (l) { return l.trim(); }).map(function (l) {
      return l.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map(function (c) { return c.trim(); });
    });
  }
  function tableText(p) {
    return Array.prototype.map.call(p.querySelectorAll("tr"), function (tr) {
      return "| " + Array.prototype.map.call(tr.children, function (td) {
        return readText(td).replace(/\|/g, "/").replace(/\s+/g, " ").trim();
      }).join(" | ") + " |";
    }).join("\n");
  }
  function cell(text) {
    var td = el("td");
    td.contentEditable = "true";
    td.spellcheck = spell;
    td.innerHTML = textHTML(text || "");
    return td;
  }

  // --- paragraphs -----------------------------------------------------------------------

  function makePara(n) {
    var p = el("div", "se-p se-" + n.level);
    p.dataset.id = n.id || "";
    p.dataset.level = n.level;
    p.dataset.when = n.when || "";
    var num = el("span", "se-num");
    num.contentEditable = "false";
    p.appendChild(num);
    if (n.level === "TBL") {
      var table = el("table"), body = el("tbody");
      var rows = rowsOf(n.text);
      if (!rows.length) rows = [["", ""], ["", ""]];
      rows.forEach(function (r) {
        var tr = el("tr");
        r.forEach(function (c) { tr.appendChild(cell(c)); });
        body.appendChild(tr);
      });
      table.appendChild(body);
      p.appendChild(table);
    } else {
      var t = el("div", "se-text");
      t.contentEditable = "true";
      t.spellcheck = spell;
      t.dataset.empty = n.level === "CMT" ? "A note to whoever edits this; never issued" : "Type here";
      setText(t, n.text || "", n.when);
      p.appendChild(t);
    }
    return p;
  }
  function paraOf(node) {
    while (node && node !== flow) {
      if (node.nodeType === 1 && node.classList.contains("se-p")) return node;
      node = node.parentNode;
    }
    return null;
  }
  function collect() {
    return paras().map(function (p) {
      var level = p.dataset.level;
      var text = level === "TBL" ? tableText(p) : readText(textOf(p)).replace(/\s+/g, " ").trim();
      return { id: p.dataset.id || "", level: level, text: text, when: p.dataset.when || "" };
    });
  }
  function render(nodes, focusIndex, atEnd) {
    if (!nodes.length) nodes = [{ id: "", level: NBS ? "ART" : "PRT", text: "", when: "" }];
    // Built aside and swapped in whole, so a failure never leaves half a section.
    var built = document.createDocumentFragment();
    nodes.forEach(function (n) { built.appendChild(makePara(n)); });
    here = null;
    flow.innerHTML = "";
    flow.appendChild(built);
    renumber();
    if (focusIndex != null) focusPara(paras()[Math.max(0, Math.min(focusIndex, nodes.length - 1))], atEnd);
  }

  function renumber() {
    var counters = [0, 0, 0, 0, 0, 0], lastDepth = 0;
    paras().forEach(function (p) {
      var level = p.dataset.level, d = LEVELS.indexOf(level), label = "";
      if (d >= 0) {
        counters[d]++;
        for (var k = d + 1; k < LEVELS.length; k++) counters[k] = 0;
        var c = counters[d];
        if (NBS) label = { PRT: "", ART: "", PR1: "•", PR2: "–", PR3: "·", PR4: "·" }[level];
        else label = { PRT: "PART " + c + " -", ART: (counters[0] || 1) + "." + c, PR1: letter(c, true) + ".",
                       PR2: c + ".", PR3: letter(c, false) + ".", PR4: c + ")" }[level];
        p.style.setProperty("--in", Math.max(d - 1, 0));
        lastDepth = d;
      } else {
        p.style.setProperty("--in", Math.max(lastDepth, 1));
        label = level === "CMT" ? "Note" : "";
      }
      p.querySelector(".se-num").textContent = label;
      p.dataset.label = label;
    });
    buildNav();
    showStatus();
  }

  // --- the caret --------------------------------------------------------------------------

  function focusPara(p, atEnd) {
    if (!p) return;
    var target = p.dataset.level === "TBL" ? p.querySelector("td") : textOf(p);
    if (!target) return;
    target.focus();
    var r = document.createRange();
    r.selectNodeContents(target);
    r.collapse(!atEnd);
    var sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(r);
    setHere(p);
    if (p.scrollIntoView) {
      var box = p.getBoundingClientRect(), view = canvas.getBoundingClientRect();
      if (box.top < view.top || box.bottom > view.bottom) p.scrollIntoView({ block: "center" });
    }
  }
  function caretIn(t) {
    var sel = window.getSelection();
    if (!sel.rangeCount) return null;
    var r = sel.getRangeAt(0);
    return t.contains(r.startContainer) ? r : null;
  }
  function textAround(t) {
    var r = caretIn(t);
    if (!r) return null;
    var before = document.createRange(), after = document.createRange();
    before.selectNodeContents(t); before.setEnd(r.startContainer, r.startOffset);
    after.selectNodeContents(t); after.setStart(r.endContainer, r.endOffset);
    var b = el("div"), a = el("div");
    b.appendChild(before.cloneContents()); a.appendChild(after.cloneContents());
    return { before: readText(b), after: readText(a), collapsed: r.collapsed };
  }
  function setHere(p) {
    if (here === p) return;
    if (here) {
      here.classList.remove("se-here");
      tidy(here);
    }
    here = p;
    if (here) here.classList.add("se-here");
    var inTable = !!(here && here.dataset.level === "TBL");
    root.querySelector(".se-tab-table").hidden = !inTable;
    if (!inTable && currentTab() === "table") showTab("home");
    markStyle();
    markNav();
    showStatus();
  }
  // A field typed by hand ({ref:...}) becomes a field box once the caret leaves it.
  function tidy(p) {
    if (!p || !p.isConnected || p.dataset.level === "TBL") return;
    var t = textOf(p);
    var text = readText(t);
    var hasTyped = false;
    var ANY = new RegExp(TOKEN.source);
    Array.prototype.forEach.call(t.childNodes, function (n) {
      if (n.nodeType === 3 && ANY.test(n.nodeValue)) hasTyped = true;
    });
    if (hasTyped) setText(t, text, p.dataset.when);
  }
  function insertAtCaret(html, isText) {
    restoreRange();
    if (isText) document.execCommand("insertText", false, html);
    else document.execCommand("insertHTML", false, html);
    changed();
  }
  function keepRange() {
    var sel = window.getSelection();
    savedRange = sel.rangeCount && paraOf(sel.getRangeAt(0).startContainer) ? sel.getRangeAt(0).cloneRange() : null;
  }
  function restoreRange() {
    if (!savedRange) return;
    var holder = savedRange.startContainer.nodeType === 1 ? savedRange.startContainer : savedRange.startContainer.parentNode;
    var editable = holder.closest ? holder.closest("[contenteditable=true]") : null;
    if (editable) editable.focus();
    var sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(savedRange);
    savedRange = null;
  }

  // --- undo -------------------------------------------------------------------------------

  function snapshot() {
    return { nodes: collect(), at: here ? paras().indexOf(here) : 0 };
  }
  function saveUndo() {
    var s = snapshot();
    var top = undo[undo.length - 1];
    if (top && JSON.stringify(top.nodes) === JSON.stringify(s.nodes)) return;
    undo.push(s);
    if (undo.length > 200) undo.shift();
    redo = [];
    lastSnap = Date.now();
    showTools();
  }
  function stepBack(from, to) {
    var now = snapshot();
    var s = from.pop();
    if (!s) return;
    if (JSON.stringify(s.nodes) === JSON.stringify(now.nodes)) { s = from.pop(); if (!s) { return; } }
    to.push(now);
    render(s.nodes, s.at, true);
    changed(true);
  }
  function changed(noSnap) {
    dirty = true;
    showStatus();
    showTools();
  }

  // --- commands ---------------------------------------------------------------------------

  function nextLevel(level) {
    if (level === "PRT") return "ART";
    if (level === "ART") return "PR1";
    if (level === "CMT" || level === "TBL") {
      var p = here, prior = p;
      while (prior && LEVELS.indexOf(prior.dataset.level) < 0) prior = prior.previousElementSibling;
      return prior ? nextLevel(prior.dataset.level) : "PR1";
    }
    return level;
  }
  function newPara(after, level, text, when) {
    var p = makePara({ id: "", level: level, text: text || "", when: when || "" });
    if (after) after.parentNode.insertBefore(p, after.nextSibling);
    else flow.insertBefore(p, flow.firstChild);
    return p;
  }
  function setLevel(p, level) {
    if (!p || p.dataset.level === "TBL" || p.dataset.level === level) return;
    saveUndo();
    var n = { id: p.dataset.id, level: level, text: readText(textOf(p)), when: p.dataset.when };
    var fresh = makePara(n);
    p.parentNode.replaceChild(fresh, p);
    here = null;
    renumber();
    focusPara(fresh, true);
    changed();
  }
  function shift(p, by) {
    if (!p) return;
    var d = LEVELS.indexOf(p.dataset.level);
    if (d < 0) return;
    var to = Math.max(0, Math.min(LEVELS.length - 1, d + by));
    if (to !== d) setLevel(p, LEVELS[to]);
  }
  function move(p, by) {
    if (!p) return;
    var other = by < 0 ? p.previousElementSibling : p.nextElementSibling;
    if (!other) return;
    saveUndo();
    if (by < 0) flow.insertBefore(p, other); else flow.insertBefore(other, p);
    renumber();
    focusPara(p, true);
    changed();
  }
  function removePara(p) {
    if (!p) return;
    saveUndo();
    var next = p.nextElementSibling || p.previousElementSibling;
    p.remove();
    here = null;
    if (!paras().length) next = newPara(null, NBS ? "ART" : "PRT");
    renumber();
    focusPara(next, false);
    changed();
  }
  function splitHere(p) {
    var t = textOf(p);
    var around = textAround(t);
    if (!around) return;
    saveUndo();
    var sel = window.getSelection(), r = sel.getRangeAt(0);
    r.deleteContents();
    if (!around.before.trim() && around.after.trim()) {
      // At the start of a paragraph: an empty one opens above, as in Word.
      newPara(p.previousElementSibling, p.dataset.level);
      renumber();
      focusPara(p, false);
      changed();
      return;
    }
    var tail = document.createRange();
    tail.setStart(r.startContainer, r.startOffset);
    tail.setEnd(t, t.childNodes.length);
    var frag = tail.extractContents();
    var level = around.after.trim() ? p.dataset.level : nextLevel(p.dataset.level);
    var fresh = newPara(p, level);
    var ft = textOf(fresh);
    ft.innerHTML = "";
    Array.prototype.forEach.call(frag.querySelectorAll ? frag.querySelectorAll(".se-cond") : [], function (c) { c.remove(); });
    ft.appendChild(frag);
    renumber();
    focusPara(fresh, false);
    changed();
  }
  function joinWith(first, second) {
    // The second paragraph's words go on the end of the first; the first keeps its id.
    if (!first || !second || first.dataset.level === "TBL" || second.dataset.level === "TBL") return false;
    saveUndo();
    var a = textOf(first), b = textOf(second);
    var mark = document.createRange();
    mark.selectNodeContents(a);
    mark.collapse(false);
    var join = document.createTextNode("");
    a.appendChild(join);
    Array.prototype.slice.call(b.childNodes).forEach(function (n) {
      if (!(n.nodeType === 1 && n.classList.contains("se-cond"))) a.appendChild(n);
    });
    second.remove();
    here = null;
    renumber();
    a.focus();
    var r = document.createRange();
    r.setStart(join, 0);
    r.collapse(true);
    var sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(r);
    setHere(first);
    changed();
    return true;
  }
  function upper(p) {
    if (!p || p.dataset.level === "TBL") return;
    saveUndo();
    var t = textOf(p);
    var walker = document.createTreeWalker(t, NodeFilter.SHOW_TEXT, null);
    var all = [], n;
    while ((n = walker.nextNode())) if (!n.parentNode.closest("[data-raw]")) all.push(n);
    var text = all.map(function (x) { return x.nodeValue; }).join("");
    var toUpper = text !== text.toUpperCase();
    all.forEach(function (x) {
      x.nodeValue = toUpper ? x.nodeValue.toUpperCase() : x.nodeValue.charAt(0).toUpperCase() + x.nodeValue.slice(1).toLowerCase();
    });
    changed();
  }

  // Pasted text: one paragraph a line, taking its level from its marks or its
  // typed number (A., 1., a., 1), 1.2, PART 1 -) when it came from Word.
  function parseLine(line, fallback) {
    var when = "", level = fallback, m;
    if ((m = /^(#{1,2}|-{1,4}|\/\/)\s*(.*)$/.exec(line))) { level = LEVEL_OF[m[1]]; line = m[2]; }
    else if ((m = /^PART\s+\d+\s*[-–—.]*\s*(.*)$/i.exec(line))) { level = "PRT"; line = m[1]; }
    else if ((m = /^\d+\.\d+\s+(.*)$/.exec(line))) { level = "ART"; line = m[1]; }
    else if ((m = /^[A-Z]\.\s+(.*)$/.exec(line))) { level = "PR1"; line = m[1]; }
    else if ((m = /^\d+\.\s+(.*)$/.exec(line))) { level = "PR2"; line = m[1]; }
    else if ((m = /^[a-z]\.\s+(.*)$/.exec(line))) { level = "PR3"; line = m[1]; }
    else if ((m = /^\d+\)\s+(.*)$/.exec(line))) { level = "PR4"; line = m[1]; }
    else if ((m = /^[•·–\-*]\s+(.*)$/.exec(line))) { line = m[1]; }
    var c = /^\{if\s+([^}]*)\}\s*/i.exec(line);
    if (c) { when = c[1].trim(); line = line.slice(c[0].length); }
    return { level: level, text: line.trim(), when: when };
  }
  function paste(p, text) {
    var lines = text.replace(/\r\n?/g, "\n").split("\n").map(function (l) { return l.trim(); }).filter(Boolean);
    if (!lines.length) return;
    if (lines.length === 1) { document.execCommand("insertText", false, lines[0].replace(/\t/g, " ")); changed(); return; }
    saveUndo();
    var t = textOf(p);
    var r = window.getSelection().getRangeAt(0);
    r.deleteContents();
    var tail = document.createRange();
    tail.setStart(r.startContainer, r.startOffset);
    tail.setEnd(t, t.childNodes.length);
    var frag = tail.extractContents();
    var first = parseLine(lines[0], p.dataset.level);
    t.appendChild(document.createTextNode(first.text));
    var after = p, level = p.dataset.level;
    lines.slice(1).forEach(function (line) {
      var n = parseLine(line, level);
      level = n.level;
      after = newPara(after, n.level, n.text, n.when);
    });
    textOf(after).appendChild(frag);
    renumber();
    focusPara(after, true);
    changed();
  }

  // --- tables -------------------------------------------------------------------------------

  function tdHere() {
    var sel = window.getSelection();
    var node = sel.rangeCount ? sel.getRangeAt(0).startContainer : document.activeElement;
    node = node && node.nodeType === 3 ? node.parentNode : node;
    return node && node.closest ? node.closest("td") : null;
  }
  function tableCmd(cmd) {
    var td = tdHere();
    if (!td) return;
    var tr = td.parentNode, table = tr.closest("table"), i = Array.prototype.indexOf.call(tr.children, td);
    saveUndo();
    if (cmd === "row-above" || cmd === "row-below") {
      var fresh = el("tr");
      for (var k = 0; k < tr.children.length; k++) fresh.appendChild(cell(""));
      tr.parentNode.insertBefore(fresh, cmd === "row-above" ? tr : tr.nextSibling);
      fresh.children[i].focus();
    } else if (cmd === "col-left" || cmd === "col-right") {
      Array.prototype.forEach.call(table.querySelectorAll("tr"), function (row) {
        var ref = row.children[i];
        row.insertBefore(cell(""), cmd === "col-left" ? ref : (ref ? ref.nextSibling : null));
      });
    } else if (cmd === "row-delete") {
      if (table.querySelectorAll("tr").length > 1) tr.remove(); else removePara(paraOf(table));
    } else if (cmd === "col-delete") {
      if (tr.children.length > 1) Array.prototype.forEach.call(table.querySelectorAll("tr"), function (row) { if (row.children[i]) row.children[i].remove(); });
      else removePara(paraOf(table));
    }
    changed();
  }

  // --- dialogs ------------------------------------------------------------------------------

  function ask(title, fields, okLabel, done) {
    keepRange();
    dialog.querySelector("[data-dialog-title]").textContent = title;
    var box = dialog.querySelector("[data-dialog-fields]");
    box.innerHTML = "";
    fields.forEach(function (f) { box.appendChild(f); });
    dialog.querySelector("[data-dialog-ok]").textContent = okLabel || "Insert";
    dialog.returnValue = "";
    dialog.onclose = function () {
      if (dialog.returnValue === "ok") done(box);
      else restoreRange();
      dialog.onclose = null;
    };
    if (dialog.showModal) dialog.showModal(); else dialog.setAttribute("open", "");
    var first = box.querySelector("select, input");
    if (first) first.focus();
  }
  function field(label, control, hint) {
    var f = el("label", "field");
    f.appendChild(el("span", "field-label", label));
    f.appendChild(control);
    if (hint) f.appendChild(el("span", "field-hint", hint));
    return f;
  }
  function select(name, items, value) {
    var s = el("select");
    s.name = name;
    items.forEach(function (it) {
      var o = el("option", null, it[1]);
      o.value = it[0];
      if (it[0] === value) o.selected = true;
      s.appendChild(o);
    });
    return s;
  }
  function input(name, value, placeholder) {
    var i = el("input");
    i.type = "text"; i.name = name; i.value = value || ""; i.placeholder = placeholder || "";
    return i;
  }
  function inTextOnly() {
    if (!here || here.dataset.level === "TBL" && !tdHere()) { say("Put the caret in a paragraph first."); return false; }
    return true;
  }

  function askRef() {
    if (!inTextOnly()) return;
    var articles = paras().filter(function (p) { return p.dataset.level === "ART"; }).map(function (p) {
      var t = readText(textOf(p)).trim();
      return [t.toUpperCase(), (p.dataset.label ? p.dataset.label + " " : "") + t];
    });
    var kind = select("kind", [["section", "Another section"], ["article", "An article of this section"],
                               ["other", "An article of another section"]], "section");
    var sec = select("section", data.sections.map(function (s) { return [s.number, s.number + " " + s.title]; }));
    var art = select("article", articles.length ? articles : [["", "This section has no articles yet"]]);
    var title = input("title", "", "e.g. CURING");
    var fSec = field("Section", sec), fArt = field("Article", art), fTitle = field("Article title in that section", title,
      "As it is headed there; the reference follows it if it is renumbered.");
    function show() {
      fSec.hidden = kind.value === "article";
      fArt.hidden = kind.value !== "article";
      fTitle.hidden = kind.value !== "other";
    }
    kind.addEventListener("change", show);
    show();
    ask("Insert a cross-reference", [field("Refer to", kind), fSec, fArt, fTitle], "Insert", function () {
      var raw = kind.value === "section" ? "{ref:" + sec.value + "}" :
                kind.value === "article" ? "{ref:" + art.value + "}" :
                "{ref:" + sec.value + "/" + title.value.trim().toUpperCase() + "}";
      if (/\{ref:\/?\}$/.test(raw) || /\/\}$/.test(raw)) return;
      insertAtCaret(tokenHTML(raw) + "&nbsp;");
    });
  }
  function askWord() {
    if (!inTextOnly()) return;
    if (!data.variables.length) { say("There are no project words yet: add them on the Options page."); return; }
    var s = select("word", data.variables.map(function (v) { return [v.key, v.label + "  ({{" + v.key + "}})"]; }));
    ask("Insert a project word", [field("Word", s, "Filled in with each project's own, wherever the text uses it.")], "Insert", function () {
      insertAtCaret(tokenHTML("{{" + s.value + "}}") + "&nbsp;");
    });
  }
  function optionPicker(onPick) {
    var groups = {};
    data.options.forEach(function (o) { (groups[o.group || "Other"] = groups[o.group || "Other"] || []).push(o); });
    var s = el("select");
    Object.keys(groups).forEach(function (g) {
      var og = el("optgroup"); og.label = g;
      groups[g].forEach(function (o) { var op = el("option", null, o.label); op.value = o.key; og.appendChild(op); });
      s.appendChild(og);
    });
    s.addEventListener("change", function () { onPick(s.value); });
    return s;
  }
  function askChoice() {
    if (!inTextOnly()) return;
    var values = select("value", []);
    var opt = optionPicker(function (key) { fill(key); });
    function fill(key) {
      values.innerHTML = "";
      ((optByKey[key] || {}).choices || []).forEach(function (c) { var o = el("option", null, c); o.value = c; values.appendChild(o); });
    }
    fill(opt.value);
    var words = input("words", "", "The words issued for that answer");
    ask("Insert a choice in the text", [field("Question", opt), field("Answer", values), field("Words", words,
      "Issued only for projects with that answer; for the words MasterSpec puts in [brackets]. Insert one for each answer.")],
      "Insert", function () {
        if (!words.value.trim()) return;
        insertAtCaret(tokenHTML("{" + opt.value + "=" + values.value + ": " + words.value.replace(/[{}]/g, "") + "}") + "&nbsp;");
      });
  }
  function askCondition() {
    var p = here;
    if (!p) { say("Put the caret in a paragraph first."); return; }
    var now = input("when", p.dataset.when, "e.g. leed=v4.1 & structures=Buildings");
    var opt = optionPicker(function (key) { fill(key); });
    var op = select("op", [["=", "is"], ["!=", "is not"]], "=");
    var choices = el("div", "se-choices");
    function fill(key) {
      choices.innerHTML = "";
      ((optByKey[key] || {}).choices || []).forEach(function (c) {
        var l = el("label"), b = el("input");
        b.type = "checkbox"; b.value = c;
        l.appendChild(b); l.appendChild(document.createTextNode(c));
        choices.appendChild(l);
      });
    }
    fill(opt.value);
    var add = el("button", "btn btn-ghost btn-sm", "Add to the condition");
    add.type = "button";
    add.addEventListener("click", function () {
      var picked = Array.prototype.filter.call(choices.querySelectorAll("input"), function (b) { return b.checked; })
        .map(function (b) { return b.value; });
      if (!picked.length) return;
      var part = opt.value + op.value + picked.join("|");
      now.value = now.value.trim() ? now.value.trim() + " & " + part : part;
    });
    var clear = el("button", "btn btn-ghost btn-sm", "No condition");
    clear.type = "button";
    clear.addEventListener("click", function () { now.value = ""; });
    var row = el("div", "inline-form");
    row.appendChild(add); row.appendChild(clear);
    ask("Only for some projects", [
      el("p", "small muted", "This paragraph, and whatever sits under it, is issued only for projects whose answers meet the condition."),
      field("Question", opt), field("Answer", op), choices, row, field("Condition", now)], "Set", function () {
        saveUndo();
        p.dataset.when = now.value.trim().replace(/[{}]/g, "");
        var t = textOf(p);
        if (t) setText(t, readText(t), p.dataset.when);
        changed();
        focusPara(p, true);
      });
  }
  function askTable() {
    var rows = input("rows", "3"), cols = input("cols", "3");
    rows.type = cols.type = "number"; rows.min = cols.min = "1"; rows.max = "60"; cols.max = "12";
    ask("Insert a table", [field("Rows", rows), field("Columns", cols)], "Insert", function () {
      saveUndo();
      var r = Math.max(1, Math.min(60, +rows.value || 3)), c = Math.max(1, Math.min(12, +cols.value || 3));
      var lines = [];
      for (var i = 0; i < r; i++) lines.push("|" + new Array(c + 1).join("  |"));
      var p = newPara(here, "TBL", lines.join("\n"));
      renumber();
      focusPara(p, false);
      changed();
    });
  }
  function wordCount() {
    var text = collect().map(function (n) { return n.level === "CMT" ? "" : n.text.replace(/[|{}]/g, " "); }).join(" ");
    var words = (text.match(/\S+/g) || []).length;
    var nodes = collect();
    ask("Word count", [el("p", null, words.toLocaleString() + " words, " + text.replace(/\s/g, "").length.toLocaleString() +
      " characters, " + nodes.filter(function (n) { return n.level !== "CMT"; }).length + " paragraphs and " +
      nodes.filter(function (n) { return n.level === "CMT"; }).length + " editor's notes (not counted in the words).")], "Close", function () {});
  }

  // --- find and replace -------------------------------------------------------------------

  var findWhat = findBar.querySelector("[data-find-what]");
  var findWith = findBar.querySelector("[data-find-with]");
  var findCase = findBar.querySelector("[data-find-case]");
  var findSaid = findBar.querySelector("[data-find-said]");
  function textNodes(container) {
    var walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT, {
      acceptNode: function (n) { return n.parentNode.closest("[data-raw]") ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT; }
    });
    var out = [], n;
    while ((n = walker.nextNode())) out.push(n);
    return out;
  }
  function editablesOf(p) { return p.dataset.level === "TBL" ? Array.prototype.slice.call(p.querySelectorAll("td")) : [textOf(p)]; }
  function findNext() {
    var what = findWhat.value;
    if (!what) return false;
    var all = [];
    paras().forEach(function (p) { if (!(root.classList.contains("se-hide-notes") && p.dataset.level === "CMT")) all = all.concat(editablesOf(p)); });
    var sel = window.getSelection();
    var startAt = 0, fromOffset = 0;
    if (sel.rangeCount) {
      var r = sel.getRangeAt(0);
      all.forEach(function (e, i) { if (e.contains(r.endContainer)) { startAt = i; fromOffset = -1; } });
    }
    for (var k = 0; k <= all.length; k++) {
      var i = (startAt + k) % all.length;
      var nodes = textNodes(all[i]);
      var joined = nodes.map(function (n) { return n.nodeValue; }).join("");
      var hay = findCase.checked ? joined : joined.toLowerCase();
      var needle = findCase.checked ? what : what.toLowerCase();
      var from = 0;
      if (k === 0 && fromOffset === -1 && sel.rangeCount) {
        var rr = sel.getRangeAt(0), pos = 0;
        nodes.forEach(function (n) {
          if (n === rr.endContainer) from = pos + rr.endOffset;
          pos += n.nodeValue.length;
        });
      }
      var at = hay.indexOf(needle, from);
      if (at >= 0) {
        var range = document.createRange(), pos2 = 0, setStart = false;
        nodes.forEach(function (n) {
          var len = n.nodeValue.length;
          if (!setStart && at < pos2 + len) { range.setStart(n, at - pos2); setStart = true; }
          if (setStart && at + what.length <= pos2 + len && !range._end) { range.setEnd(n, at + what.length - pos2); range._end = true; }
          pos2 += len;
        });
        all[i].focus();
        sel.removeAllRanges();
        sel.addRange(range);
        setHere(paraOf(all[i]));
        var box = all[i].getBoundingClientRect(), view = canvas.getBoundingClientRect();
        if (box.top < view.top || box.bottom > view.bottom) all[i].scrollIntoView({ block: "center" });
        findSaid.textContent = "";
        return true;
      }
    }
    findSaid.textContent = "Not found.";
    return false;
  }
  function replaceOne() {
    var sel = window.getSelection();
    var picked = sel.rangeCount ? sel.toString() : "";
    var same = findCase.checked ? picked === findWhat.value : picked.toLowerCase() === findWhat.value.toLowerCase();
    if (picked && same) {
      saveUndo();
      document.execCommand("insertText", false, findWith.value);
      changed();
    }
    findNext();
  }
  function replaceAll() {
    var what = findWhat.value;
    if (!what) return;
    saveUndo();
    var count = 0;
    var flags = findCase.checked ? "g" : "gi";
    var re = new RegExp(what.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), flags);
    paras().forEach(function (p) {
      editablesOf(p).forEach(function (e) {
        textNodes(e).forEach(function (n) {
          var m = n.nodeValue.match(re);
          if (m) { count += m.length; n.nodeValue = n.nodeValue.replace(re, function () { return findWith.value; }); }
        });
      });
    });
    findSaid.textContent = count ? "Replaced " + count + "." : "Not found.";
    if (count) changed();
  }

  // --- ribbon, navigation and status ---------------------------------------------------------

  function currentTab() {
    var on = root.querySelector(".se-tab-on");
    return on ? on.dataset.tab : "home";
  }
  function showTab(name) {
    Array.prototype.forEach.call(root.querySelectorAll(".se-tab"), function (t) {
      var on = t.dataset.tab === name;
      t.classList.toggle("se-tab-on", on);
      t.setAttribute("aria-selected", on ? "true" : "false");
    });
    Array.prototype.forEach.call(root.querySelectorAll(".se-panel"), function (p) { p.hidden = p.dataset.panel !== name; });
  }
  function buildStyles() {
    var box = root.querySelector("[data-styles]");
    STYLES.forEach(function (s) {
      var b = el("button", "se-style");
      b.type = "button";
      b.dataset.level = s.level;
      b.title = s.name + " (" + (s.level === "CMT" ? "never issued" : s.level) + ")";
      var sample = el("span", null, s.sample);
      if (s.level === "PRT" || s.level === "ART") sample.style.fontWeight = "bold";
      if (s.level === "CMT") { sample.style.fontStyle = "italic"; sample.style.color = "#6b4e00"; }
      b.appendChild(sample);
      b.appendChild(el("small", null, s.name));
      b.addEventListener("mousedown", function (e) { e.preventDefault(); });
      b.addEventListener("click", function () { if (here) setLevel(here, s.level); });
      box.appendChild(b);
    });
  }
  function markStyle() {
    Array.prototype.forEach.call(root.querySelectorAll(".se-style"), function (b) {
      b.classList.toggle("se-on", !!here && b.dataset.level === here.dataset.level);
    });
  }
  var navTimer = null;
  function buildNav() {
    clearTimeout(navTimer);
    navTimer = setTimeout(function () {
      nav.innerHTML = "";
      paras().forEach(function (p) {
        if (p.dataset.level !== "PRT" && p.dataset.level !== "ART") return;
        var a = el("a", p.dataset.level === "PRT" ? "se-nav-part" : "");
        a.href = "#";
        a.textContent = (p.dataset.label ? p.dataset.label + " " : "") + readText(textOf(p)).trim().slice(0, 60);
        if (p.dataset.level === "ART") a.style.paddingLeft = "24px";
        a._para = p;
        a.addEventListener("click", function (e) {
          e.preventDefault();
          p.scrollIntoView({ block: "start" });
          focusPara(p, true);
        });
        nav.appendChild(a);
      });
      markNav();
    }, 120);
  }
  function markNav() {
    var head = here;
    while (head && head.dataset.level !== "ART" && head.dataset.level !== "PRT") head = head.previousElementSibling;
    Array.prototype.forEach.call(nav.children, function (a) { a.classList.toggle("se-nav-here", a._para === head); });
  }
  function showStatus(message) {
    var all = paras();
    var bits = [];
    if (plain.hidden) {
      if (here) {
        bits.push("Paragraph " + (all.indexOf(here) + 1) + " of " + all.length);
        bits.push(STYLE_NAME[here.dataset.level] + (here.dataset.label && here.dataset.level !== "CMT" ? " " + here.dataset.label : ""));
        if (here.dataset.when) bits.push("only if " + here.dataset.when);
      } else bits.push(all.length + " paragraphs");
    } else bits.push("Plain text");
    statusBar.innerHTML = "";
    bits.forEach(function (b) { statusBar.appendChild(el("span", null, b)); });
    var state = el("span", dirty ? "se-dirty" : "", dirty ? "Not saved yet" : "Saved");
    statusBar.appendChild(state);
    if (message) statusBar.appendChild(el("span", null, message));
  }
  var sayTimer = null;
  function say(message) {
    showStatus(message);
    clearTimeout(sayTimer);
    sayTimer = setTimeout(function () { showStatus(); }, 5000);
  }
  function showTools() {
    var u = root.querySelector('[data-cmd="undo"]'), r = root.querySelector('[data-cmd="redo"]');
    if (u) u.disabled = !undo.length;
    if (r) r.disabled = !redo.length;
  }
  function setZoom(z) {
    zoom = Math.max(0.5, Math.min(2, Math.round(z * 100) / 100));
    page.style.setProperty("--z", zoom);
    root.querySelector("[data-zoom]").textContent = Math.round(zoom * 100) + "%";
  }
  function heading() {
    var title = (form.querySelector("[data-se-title]") || {}).value || "";
    var numberField = form.querySelector('input[name="number"]');
    var number = numberField ? numberField.value : data.number;
    root.querySelector("[data-sct]").textContent = NBS ? number + " " + title : "SECTION " + number + " - " + title;
    root.querySelector("[data-eos]").textContent = "END OF SECTION " + number;
  }

  // --- plain text, both ways --------------------------------------------------------------

  function toText(nodes) {
    var lines = [];
    nodes.forEach(function (n) {
      if (n.level === "TBL") { rowsOf(n.text).forEach(function (r) { lines.push("| " + r.join(" | ") + " |"); }); return; }
      if (!n.text) return;
      if (n.level === "PRT" && lines.length) lines.push("");
      lines.push(MARK[n.level] + " " + (n.when ? "{if " + n.when + "} " : "") + n.text);
    });
    return lines.join("\n") + (lines.length ? "\n" : "");
  }
  function fromText(text) {
    var out = [], table = null;
    text.replace(/\r\n/g, "\n").split("\n").forEach(function (raw) {
      var line = raw.trim();
      if (!line) { table = null; return; }
      if (line.charAt(0) === "|") {
        if (!table) { table = []; out.push({ id: "", level: "TBL", text: "", when: "" }); }
        table.push(line);
        out[out.length - 1].text = table.join("\n");
        return;
      }
      table = null;
      var m = /^(#{1,2}|-{1,4}|\/\/)\s*(.*)$/.exec(line);
      if (!m) {
        var last = out[out.length - 1];
        if (last && last.level !== "TBL") last.text = (last.text + " " + line).trim();
        else out.push({ id: "", level: "PR1", text: line, when: "" });
        return;
      }
      var rest = m[2], when = "";
      var c = /^\{if\s+([^}]*)\}\s*/i.exec(rest);
      if (c) { when = c[1].trim(); rest = rest.slice(c[0].length); }
      out.push({ id: "", level: LEVEL_OF[m[1]], text: rest.trim(), when: when });
    });
    return out;
  }
  function keepIds(fresh, old) {
    var used = {};
    fresh.forEach(function (n) {
      for (var i = 0; i < old.length; i++) {
        var o = old[i];
        if (!used[i] && o.id && o.level === n.level && norm(o.text) === norm(n.text)) { n.id = o.id; used[i] = true; return; }
      }
    });
    return fresh;
  }
  function toPlain() {
    textarea.value = toText(collect());
    plain.hidden = false;
    canvas.hidden = true;
    nav.hidden = true;
    root.querySelector(".se-ribbon").hidden = true;
    form.querySelector('input[name="mode"]').value = "text";
    textarea.focus();
    showStatus();
  }
  function toPage() {
    var before = collect();
    saveUndo();
    render(keepIds(fromText(textarea.value), before), 0, false);
    plain.hidden = true;
    canvas.hidden = false;
    nav.hidden = !root.querySelector('[data-toggle="nav"]').checked;
    root.querySelector(".se-ribbon").hidden = false;
    form.querySelector('input[name="mode"]').value = "page";
    showStatus();
  }

  // --- wiring -----------------------------------------------------------------------------

  var COMMANDS = {
    undo: function () { stepBack(undo, redo); },
    redo: function () { stepBack(redo, undo); },
    indent: function () { shift(here, 1); },
    outdent: function () { shift(here, -1); },
    up: function () { move(here, -1); },
    down: function () { move(here, 1); },
    below: function () {
      if (!here) return;
      saveUndo();
      var p = newPara(here, nextLevel(here.dataset.level));
      renumber(); focusPara(p, false); changed();
    },
    duplicate: function () {
      if (!here) return;
      saveUndo();
      var n = collect()[paras().indexOf(here)];
      var p = makePara({ id: "", level: n.level, text: n.text, when: n.when });
      here.parentNode.insertBefore(p, here.nextSibling);
      renumber(); focusPara(p, true); changed();
    },
    remove: function () { removePara(here); },
    find: function () { findBar.hidden = false; findWhat.focus(); findWhat.select(); },
    "find-close": function () { findBar.hidden = true; },
    "find-next": findNext,
    "replace-one": replaceOne,
    "replace-all": replaceAll,
    upper: function () { upper(here); },
    table: askTable,
    note: function () {
      saveUndo();
      var p = newPara(here, "CMT");
      renumber(); focusPara(p, false); changed();
    },
    ref: askRef,
    word: askWord,
    choice: askChoice,
    condition: askCondition,
    count: wordCount,
    "zoom-in": function () { setZoom(zoom + 0.1); },
    "zoom-out": function () { setZoom(zoom - 0.1); },
    "zoom-reset": function () { setZoom(1); },
    "zoom-width": function () { setZoom((canvas.clientWidth - 40) / 794); },
    plain: toPlain,
    page: toPage,
    "row-above": function () { tableCmd("row-above"); },
    "row-below": function () { tableCmd("row-below"); },
    "col-left": function () { tableCmd("col-left"); },
    "col-right": function () { tableCmd("col-right"); },
    "row-delete": function () { tableCmd("row-delete"); },
    "col-delete": function () { tableCmd("col-delete"); }
  };

  root.addEventListener("mousedown", function (e) {
    // Ribbon buttons keep the caret where it is.
    if (e.target.closest(".se-btn, .se-style") && !e.target.closest("label")) e.preventDefault();
  });
  root.addEventListener("click", function (e) {
    var tab = e.target.closest(".se-tab");
    if (tab) { showTab(tab.dataset.tab); return; }
    var b = e.target.closest("[data-cmd]");
    if (b && COMMANDS[b.dataset.cmd]) { e.preventDefault(); COMMANDS[b.dataset.cmd](); return; }
    var sym = e.target.closest("[data-char]");
    if (sym) { if (here && here.dataset.level !== "TBL" || tdHere()) insertAtCaret(sym.dataset.char, true); return; }
    var chip = e.target.closest(".se-cond");
    if (chip) { setHere(paraOf(chip)); askCondition(); return; }
    var tok = e.target.closest(".se-tok");
    if (tok) {
      // A field is kept whole: click it to see what it is; Backspace takes it out.
      say(tok.title);
    }
  });
  root.addEventListener("change", function (e) {
    var t = e.target.dataset ? e.target.dataset.toggle : null;
    if (!t) return;
    var on = e.target.checked;
    if (t === "spell") {
      spell = on;
      Array.prototype.forEach.call(root.querySelectorAll("[contenteditable=true]"), function (x) { x.spellcheck = on; });
    }
    if (t === "notes") root.classList.toggle("se-hide-notes", !on);
    if (t === "conds") root.classList.toggle("se-hide-conds", !on);
    if (t === "fields") root.classList.toggle("se-plain-fields", !on);
    if (t === "nav") root.classList.toggle("se-no-nav", !on);
    if (t === "marks") root.classList.toggle("se-marks", on);
  });

  document.addEventListener("selectionchange", function () {
    var sel = window.getSelection();
    if (!sel.rangeCount) return;
    var p = paraOf(sel.getRangeAt(0).startContainer);
    if (p) setHere(p);
  });
  flow.addEventListener("focusin", function (e) { var p = paraOf(e.target); if (p) setHere(p); });

  flow.addEventListener("input", function () {
    if (Date.now() - lastSnap > 1500) { var s = undo.length; saveUndo(); if (undo.length === s) lastSnap = Date.now(); }
    changed();
    var p = here;
    if (p && (p.dataset.level === "PRT" || p.dataset.level === "ART")) buildNav();
  });
  flow.addEventListener("beforeinput", function () {
    if (Date.now() - lastSnap > 1500) saveUndo();
  });

  flow.addEventListener("paste", function (e) {
    var p = paraOf(e.target);
    if (!p) return;
    e.preventDefault();
    var text = (e.clipboardData || window.clipboardData).getData("text/plain") || "";
    if (p.dataset.level === "TBL") { document.execCommand("insertText", false, text.replace(/\s+/g, " ")); changed(); return; }
    paste(p, text);
  });
  flow.addEventListener("drop", function (e) { e.preventDefault(); });

  flow.addEventListener("keydown", function (e) {
    var p = paraOf(e.target);
    if (!p) return;
    var mod = e.ctrlKey || e.metaKey;
    if (p.dataset.level === "TBL") {
      var td = e.target.closest("td");
      if (e.key === "Tab" && td) {
        e.preventDefault();
        var cells = Array.prototype.slice.call(p.querySelectorAll("td"));
        var i = cells.indexOf(td) + (e.shiftKey ? -1 : 1);
        if (i >= cells.length) { tableCmd("row-below"); cells = Array.prototype.slice.call(p.querySelectorAll("td")); }
        var next = cells[Math.max(0, i)];
        if (next) { next.focus(); var r = document.createRange(); r.selectNodeContents(next); r.collapse(false); var s = window.getSelection(); s.removeAllRanges(); s.addRange(r); }
      } else if (e.key === "Enter") {
        e.preventDefault();
        if (e.ctrlKey || e.shiftKey) {
          saveUndo(); var q = newPara(p, nextLevel("TBL")); renumber(); focusPara(q, false); changed();
        }
      }
      return;
    }
    var t = textOf(p);
    if (e.key === "Enter") { e.preventDefault(); splitHere(p); return; }
    if (e.key === "Tab") { e.preventDefault(); shift(p, e.shiftKey ? -1 : 1); return; }
    if (e.altKey && (e.key === "ArrowUp" || e.key === "ArrowDown")) { e.preventDefault(); move(p, e.key === "ArrowUp" ? -1 : 1); return; }
    if (mod && e.shiftKey && (e.key === "K" || e.key === "k")) { e.preventDefault(); removePara(p); return; }
    var around;
    if (e.key === "Backspace" && (around = textAround(t)) && around.collapsed && !around.before) {
      e.preventDefault();
      var prev = p.previousElementSibling;
      if (!readText(t).trim()) {
        if (prev || p.nextElementSibling) { removePara(p); if (prev) focusPara(prev, true); }
      } else if (prev && prev.dataset.level !== "TBL") joinWith(prev, p);
      return;
    }
    if (e.key === "Delete" && (around = textAround(t)) && around.collapsed && !around.after) {
      e.preventDefault();
      var nextP = p.nextElementSibling;
      if (nextP && nextP.dataset.level !== "TBL") joinWith(p, nextP);
      return;
    }
    if ((e.key === "ArrowUp" || e.key === "ArrowDown") && !e.shiftKey) {
      var sel = window.getSelection();
      if (!sel.rangeCount) return;
      var r = sel.getRangeAt(0).cloneRange();
      var rect = r.getClientRects()[0] || r.getBoundingClientRect();
      var box = t.getBoundingClientRect();
      var line = parseFloat(getComputedStyle(t).lineHeight) || 20;
      var edge = e.key === "ArrowUp" ? (!rect.height || rect.top - box.top < line * 0.8) : (!rect.height || box.bottom - rect.bottom < line * 0.8);
      if (!readText(t)) edge = true;
      if (edge) {
        var to = e.key === "ArrowUp" ? p.previousElementSibling : p.nextElementSibling;
        if (to) { e.preventDefault(); focusPara(to, e.key === "ArrowUp"); }
      }
    }
  });

  document.addEventListener("keydown", function (e) {
    if (!root.isConnected) return;
    var mod = e.ctrlKey || e.metaKey;
    if (!mod) {
      if (e.key === "Escape" && !findBar.hidden) findBar.hidden = true;
      return;
    }
    var k = e.key.toLowerCase();
    var inEditor = !!paraOf(e.target) || e.target === document.body;
    if (k === "s") { e.preventDefault(); var stay = document.querySelector('button[name="stay"]'); if (stay) stay.click(); return; }
    if (k === "f" || k === "h") { e.preventDefault(); COMMANDS.find(); if (k === "h") findWith.focus(); return; }
    if (!inEditor || !plain.hidden) return;
    if (k === "z" && !e.shiftKey) { e.preventDefault(); COMMANDS.undo(); }
    else if (k === "y" || (k === "z" && e.shiftKey)) { e.preventDefault(); COMMANDS.redo(); }
    else if (k === "b" || k === "i" || k === "u") {
      e.preventDefault();
      say("Bold, italics and underlining come from the house styles: choose the paragraph's style instead.");
    }
  });
  findWhat.addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); findNext(); } });
  findWith.addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); replaceOne(); } });

  form.addEventListener("input", function (e) {
    if (e.target.matches("[data-se-title], input[name=number]")) heading();
    if (!paraOf(e.target)) { dirty = true; showStatus(); }
  });
  form.addEventListener("submit", function () {
    if (form.querySelector('input[name="mode"]').value === "page") {
      var sent = collect().filter(function (n) {
        return n.level === "TBL" ? rowsOf(n.text).some(function (r) { return r.some(Boolean); }) : n.text;
      });
      form.querySelector('input[name="nodes"]').value = JSON.stringify({ count: sent.length, nodes: sent });
    }
    dirty = false;
  });
  window.addEventListener("beforeunload", function (e) {
    if (dirty) { e.preventDefault(); e.returnValue = ""; }
  });

  buildStyles();
  heading();
  render(data.nodes, null);
  if (window.innerWidth > 900 && canvas.clientWidth && canvas.clientWidth < 834) setZoom((canvas.clientWidth - 40) / 794);
  showTools();
  showStatus();
  root.classList.add("se-ready");
})();
