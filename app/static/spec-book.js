/* The specification read as a book (templates/specs/book.html).
 *
 * The page sends the text once, as one flow of blocks — a heading, a
 * paragraph, a table — each section after the other. This cuts that flow into
 * pages the size of the issued A4 page and shows them two to a spread, the
 * first page alone on the right as a book opens, and turns them like leaves.
 *
 * Cutting. Each section's blocks are laid out once in a hidden column the width
 * of the page's text and measured, then packed page by page: a block that does
 * not fit what is left of a page goes whole to the next; a heading goes with
 * the start of what follows it; only a paragraph taller than a whole page (or
 * a table, row by row, as Word does) is split between pages. Each page is then
 * checked against its real layout and anything that still overflows moves on.
 * Each section starts on a page of its own and counts its own pages for the
 * footer, as each issued section is a document of its own. Everything is done
 * at full size and the book scaled afterwards, so zooming does not move a line;
 * the pages are cut again only when the browser's own zoom changes (the text
 * then renders a hair differently).
 *
 * Turning. The pages are kept aside and a spread shows clones of them. To turn
 * forward, a leaf is laid over the right-hand page — its front the page being
 * read, its back the next left-hand page — and rotated 180° about the spine
 * while the next right-hand page waits underneath. Backward is the mirror.
 * Narrow screens show one page at a time and slide. With reduced motion asked
 * for, pages change at once.
 */
(function () {
  'use strict';

  var root = document.querySelector('[data-book]');
  if (!root) return;
  var source = root.querySelector('[data-bk-source]');
  var stage = root.querySelector('[data-bk-stage]');
  var viewport = root.querySelector('[data-bk-viewport]');
  var headTemplate = root.querySelector('[data-bk-head]');
  var where = root.querySelector('[data-bk-where]');
  var jump = root.querySelector('[data-bk-jump]');
  var zoomPick = root.querySelector('[data-bk-zoom]');
  var bar = root.querySelector('.bk-bar');
  if (!source || !stage || !viewport || !source.querySelector('.bk-sec')) return;

  var PAGE_W = 794;
  var PAGE_H = 1123;
  var MARGIN = 96;           // one inch
  var LINE = 18.4;           // a line of 12 pt Times, single spaced
  var NARROW = 900;          // below this, one page at a time
  var SLIDE_GAP = 40;
  var HEADING = /(^|\s)bk-(SCT|PRT|ART)(\s|$)/;
  var reduced = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : null;

  var pages = [];            // every page in order, kept aside; a spread shows clones
  var firstPageOf = {};      // section row id -> index of its first page
  var at = 0;                // the page being read (in a spread, either of the two)
  var mode = '';             // 'spread' or 'single'
  var zoom = 'fit';
  var book = null;
  var busy = null;           // the turn under way: calling it finishes it at once
  var cutAt = 0;             // the browser zoom the pages were cut at

  try { zoom = localStorage.getItem('pm-book-zoom') || 'fit'; } catch (e) { /* private window */ }
  if (zoomPick) {
    if (!zoomPick.querySelector('option[value="' + zoom + '"]')) zoom = 'fit';
    zoomPick.value = zoom;
  }

  // Every block numbered once, so the place being read survives cutting again.
  Array.prototype.forEach.call(source.querySelectorAll('.bk-b'), function (b, i) {
    b.setAttribute('data-k', String(i));
  });

  function make(tag, cls) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    return e;
  }

  // --- cutting the flow into pages ---------------------------------------------

  function blankPage(sec) {
    var page = make('div', 'bk-page bk-paper');
    page.setAttribute('data-row', sec.getAttribute('data-row'));
    if (headTemplate) {
      var head = headTemplate.cloneNode(true);
      head.hidden = false;
      head.removeAttribute('data-bk-head');
      page.appendChild(head);
    }
    page.appendChild(make('div', 'bk-body'));
    var foot = make('div', 'bk-foot');
    var line = make('div', 'bk-foot-line');
    var title = make('span');
    title.textContent = sec.getAttribute('data-title') || '';
    line.appendChild(title);
    line.appendChild(make('span', 'bk-folio'));
    foot.appendChild(line);
    var code = sec.getAttribute('data-code');
    if (code) {
      var second = make('div', 'bk-foot-code');
      second.textContent = code;
      foot.appendChild(second);
    }
    page.appendChild(foot);
    return page;
  }

  function sizeOf(b) {
    b._h = b.getBoundingClientRect().height;
    b._pad = parseFloat(window.getComputedStyle(b).paddingTop) || 0;
  }

  // The first word that runs past the foot of the page, as a place in the text.
  function cutPlace(t, limit) {
    var walker = document.createTreeWalker(t, NodeFilter.SHOW_TEXT, null);
    var range = document.createRange();
    var seen = false;
    var node;
    while ((node = walker.nextNode())) {
      range.selectNodeContents(node);
      var whole = range.getBoundingClientRect();
      if (whole.height && whole.bottom <= limit) { seen = seen || /\S/.test(node.nodeValue); continue; }
      var words = /\S+/g;
      var m;
      while ((m = words.exec(node.nodeValue))) {
        range.setStart(node, m.index);
        range.setEnd(node, m.index + m[0].length);
        var rects = range.getClientRects();
        if (rects.length && rects[0].bottom > limit + 0.5) {
          return seen ? { node: node, offset: m.index } : null;
        }
        seen = true;
      }
    }
    return null;
  }

  // A block that runs past the foot of the page split in two; returns the rest.
  function split(b, limit) {
    var rest;
    if (b.classList.contains('bk-TBL')) {
      var rows = b.querySelectorAll('tr');
      var cut = -1;
      for (var r = 0; r < rows.length; r++) {
        if (rows[r].getBoundingClientRect().bottom > limit + 0.5) { cut = r; break; }
      }
      if (cut <= 0) return null;
      rest = b.cloneNode(false);
      var table = b.querySelector('table').cloneNode(false);
      var tbody = make('tbody');
      table.appendChild(tbody);
      rest.appendChild(table);
      for (var k = cut; k < rows.length; k++) tbody.appendChild(rows[k]);
    } else {
      var t = b.querySelector('.bk-t');
      var place = t && cutPlace(t, limit);
      if (!place) return null;
      var range = document.createRange();
      range.setStart(place.node, place.offset);
      range.setEnd(t, t.childNodes.length);
      var tail = range.extractContents();
      rest = b.cloneNode(false);
      var restText = t.cloneNode(false);
      restText.appendChild(tail);
      rest.appendChild(restText);
      b.classList.add('bk-cut');
    }
    rest.classList.remove('bk-cut');
    rest.classList.add('bk-cont');
    rest._h = null;
    return rest;
  }

  function layOut(sec, host, column, room) {
    var queue = Array.prototype.map.call(sec.children, function (b) { return b.cloneNode(true); });
    queue.forEach(function (b) { column.appendChild(b); });
    queue.forEach(sizeOf);                       // one layout for the whole section
    column.textContent = '';

    var page = null;
    var body = null;
    var used = 0;
    var i = 0;

    function measureAlone(b) {
      column.appendChild(b);
      sizeOf(b);
      column.removeChild(b);
    }

    function close() {
      if (!page) return;
      // What the sums missed: anything that still overflows moves on.
      var back = [];
      while (body.children.length > 1 && body.scrollHeight > body.clientHeight + 1) {
        var last = body.lastElementChild;
        body.removeChild(last);
        last._h = null;
        back.unshift(last);
      }
      if (back.length) Array.prototype.splice.apply(queue, [i, 0].concat(back));
      host.removeChild(page);
    }

    function open() {
      close();
      page = blankPage(sec);
      host.appendChild(page);
      body = page.querySelector('.bk-body');
      used = 0;
      pages.push(page);
    }

    open();
    while (i < queue.length) {
      var b = queue[i];
      if (b._h == null) measureAlone(b);
      var empty = !body.firstChild;
      var h = empty ? b._h - b._pad : b._h;
      var need = h;
      if (HEADING.test(b.className)) {
        // A heading is not left at the foot of a page: it goes with the
        // headings under it and the first lines of what follows them.
        var j = i + 1;
        while (j < queue.length && HEADING.test(queue[j].className)) {
          if (queue[j]._h == null) measureAlone(queue[j]);
          need += queue[j]._h;
          j++;
        }
        if (j < queue.length) {
          if (queue[j]._h == null) measureAlone(queue[j]);
          need += Math.min(queue[j]._h, queue[j]._pad + 2 * LINE);
        }
      }
      if (used + need <= room + 0.5) {
        body.appendChild(b);
        used += h;
        i++;
        continue;
      }
      // It does not fit what is left. Only a paragraph taller than a page, or a
      // table, is split; anything else goes whole to the next page.
      var tall = b._h - b._pad > room;
      var table = b.classList.contains('bk-TBL');
      var left = room - used;
      if (!empty && !((tall || table) && left > 3 * LINE + b._pad)) {
        open();
        continue;
      }
      body.appendChild(b);
      var limit = body.getBoundingClientRect().bottom;
      if (b.getBoundingClientRect().bottom <= limit + 0.5) {  // it fitted after all
        used += h;
        i++;
        continue;
      }
      var rest = split(b, limit);
      if (!rest && !empty) {                       // nothing of it fits here
        body.removeChild(b);
        open();
        continue;
      }
      i++;
      if (rest) queue.splice(i, 0, rest);
      used = room;
      if (i < queue.length) open();
    }
    close();
  }

  function keyOf(index) {
    var page = pages[index];
    var first = page && page.querySelector('[data-k]');
    return first ? first.getAttribute('data-k') : null;
  }

  function pageOfKey(key) {
    if (key == null) return -1;
    for (var i = 0; i < pages.length; i++) {
      if (pages[i].querySelector('[data-k="' + key + '"]')) return i;
    }
    return -1;
  }

  function paginate() {
    var keep = keyOf(at);
    var host = make('div', 'bk-host');
    host.setAttribute('aria-hidden', 'true');
    root.appendChild(host);

    // Where the text starts: an inch down, or below a header of many lines.
    var first = source.querySelector('.bk-sec');
    var sample = blankPage(first);
    host.appendChild(sample);
    var head = sample.querySelector('.bk-head');
    var top = MARGIN;
    if (head) {
      var below = head.getBoundingClientRect().bottom - sample.getBoundingClientRect().top;
      top = Math.max(MARGIN, Math.ceil(below + 12));
    }
    root.style.setProperty('--bk-top', top + 'px');
    var room = sample.querySelector('.bk-body').getBoundingClientRect().height;
    host.removeChild(sample);

    var measure = make('div', 'bk-page bk-paper bk-measure');
    var column = make('div', 'bk-body');
    measure.appendChild(column);
    host.appendChild(measure);

    pages = [];
    firstPageOf = {};
    Array.prototype.forEach.call(source.querySelectorAll('.bk-sec'), function (sec) {
      var from = pages.length;
      firstPageOf[sec.getAttribute('data-row')] = from;
      layOut(sec, host, column, room);
      var count = pages.length - from;
      for (var p = from; p < pages.length; p++) {
        pages[p].querySelector('.bk-folio').textContent =
          (sec.getAttribute('data-number') || '') + ' - Page ' + (p - from + 1) + ' of ' + count;
      }
    });
    root.removeChild(host);
    cutAt = window.devicePixelRatio || 1;

    var again = pageOfKey(keep);
    at = Math.max(0, Math.min(again >= 0 ? again : at, pages.length - 1));
  }

  // --- showing them --------------------------------------------------------------

  function valid(i) { return i >= 0 && i < pages.length; }
  function spreadOf(i) { return Math.floor((i + 1) / 2); }
  function shown(i) {
    if (mode === 'single') return [i];
    var s = spreadOf(i);
    return [2 * s - 1, 2 * s];
  }

  function fill(slot, index) {
    slot.textContent = '';
    if (valid(index)) slot.appendChild(pages[index].cloneNode(true));
    slot.classList.toggle('bk-blank', !valid(index));
  }

  function edge(side, label) {
    var e = make('button', 'bk-edge bk-edge-' + side);
    e.type = 'button';
    e.setAttribute('aria-label', label);
    e.title = label;
    e.addEventListener('click', function () { step(side === 'r' ? 1 : -1); });
    return e;
  }

  function build() {
    if (busy) busy();
    viewport.textContent = '';
    book = make('div', 'bk-book bk-' + mode);
    if (mode === 'spread') {
      book.appendChild(make('div', 'bk-slot bk-slot-l'));
      book.appendChild(make('div', 'bk-slot bk-slot-r'));
    } else {
      book.appendChild(make('div', 'bk-slot bk-slot-c'));
    }
    book.appendChild(edge('l', 'Previous page'));
    book.appendChild(edge('r', 'Next page'));
    viewport.appendChild(book);
    render();
  }

  function render() {
    if (!book) return;
    var show = shown(at);
    if (mode === 'spread') {
      fill(book.querySelector('.bk-slot-l'), show[0]);
      fill(book.querySelector('.bk-slot-r'), show[1]);
    } else {
      fill(book.querySelector('.bk-slot-c'), show[0]);
    }
    update();
  }

  function update() {
    var show = shown(at).filter(valid);
    var n = pages.length;
    if (where) {
      where.textContent = show.length > 1
        ? 'Page ' + (show[0] + 1) + '–' + (show[1] + 1) + ' of ' + n
        : 'Page ' + (show[0] + 1) + ' of ' + n;
    }
    var atStart = show[0] === 0;
    var atEnd = show[show.length - 1] === n - 1;
    Array.prototype.forEach.call(root.querySelectorAll('[data-bk-go]'), function (b) {
      var go = b.getAttribute('data-bk-go');
      b.disabled = (go === 'first' || go === 'prev') ? atStart : atEnd;
    });
    if (book) {
      book.querySelector('.bk-edge-l').hidden = atStart;
      book.querySelector('.bk-edge-r').hidden = atEnd;
      // In a spread the edges sit on the outer margins of the two pages.
      book.querySelector('.bk-edge-l').style.left = (mode === 'spread' && !valid(shown(at)[0])) ? PAGE_W + 'px' : '0';
    }
    if (jump && valid(at)) {
      var page = pages[show[show.length - 1]] || pages[at];
      jump.value = page.getAttribute('data-row');
    }
    try { history.replaceState(history.state, '', '#page-' + (at + 1)); } catch (e) { /* file: or sandboxed */ }
  }

  function moving() { return !(reduced && reduced.matches); }

  function fold(a, b) {
    var forward = b > a;
    var left = book.querySelector('.bk-slot-l');
    var right = book.querySelector('.bk-slot-r');
    var leaf = make('div', 'bk-leaf ' + (forward ? 'bk-leaf-fwd' : 'bk-leaf-bwd'));
    var front = make('div', 'bk-face bk-face-front');
    var back = make('div', 'bk-face bk-face-back');
    fill(front, forward ? 2 * a : 2 * a - 1);
    fill(back, forward ? 2 * b - 1 : 2 * b);
    front.appendChild(make('div', 'bk-shade'));
    back.appendChild(make('div', 'bk-shade'));
    leaf.appendChild(front);
    leaf.appendChild(back);
    // Underneath: the page the leaf uncovers is already there.
    if (forward) fill(right, 2 * b); else fill(left, 2 * b - 1);
    book.appendChild(leaf);
    book.classList.add('bk-folding');
    leaf.getBoundingClientRect();                  // start from flat

    var done = false;
    var timer = null;
    function finish() {
      if (done) return;
      done = true;
      window.clearTimeout(timer);
      busy = null;
      if (leaf.parentNode) leaf.parentNode.removeChild(leaf);
      book.classList.remove('bk-folding');
      if (forward) fill(left, 2 * b - 1); else fill(right, 2 * b);
    }
    leaf.addEventListener('transitionend', function (event) {
      if (event.target === leaf && event.propertyName === 'transform') finish();
    });
    busy = finish;
    window.requestAnimationFrame(function () {
      window.requestAnimationFrame(function () { if (!done) leaf.classList.add('bk-turn'); });
    });
    timer = window.setTimeout(finish, turnMs() + 400);
  }

  function slide(from, to) {
    var forward = to > from;
    var old = book.querySelector('.bk-slot-c');
    var next = make('div', 'bk-slot bk-slot-c');
    var d = PAGE_W + SLIDE_GAP;
    fill(next, to);
    book.classList.add('bk-sliding');
    next.style.transform = 'translateX(' + (forward ? d : -d) + 'px)';
    book.insertBefore(next, old.nextSibling);
    next.getBoundingClientRect();

    var done = false;
    var timer = null;
    function finish() {
      if (done) return;
      done = true;
      window.clearTimeout(timer);
      busy = null;
      if (old.parentNode) old.parentNode.removeChild(old);
      next.style.transform = '';
      book.classList.remove('bk-sliding');
    }
    busy = finish;
    window.requestAnimationFrame(function () {
      if (done) return;
      next.style.transform = 'translateX(0)';
      old.style.transform = 'translateX(' + (forward ? -d : d) + 'px)';
    });
    next.addEventListener('transitionend', function (event) {
      if (event.target === next) finish();
    });
    timer = window.setTimeout(finish, 720);
  }

  function turnMs() {
    var v = window.getComputedStyle(root).getPropertyValue('--bk-turn');
    return parseFloat(v) || 750;
  }

  function go(target) {
    if (!pages.length || !book) return;
    target = Math.max(0, Math.min(target, pages.length - 1));
    if (busy) busy();
    var from = at;
    if (mode === 'spread') {
      var a = spreadOf(from);
      var b = spreadOf(target);
      at = target;
      if (a === b) { update(); return; }
      if (moving()) { fold(a, b); update(); } else render();
    } else {
      if (from === target) return;
      at = target;
      if (moving()) { slide(from, target); update(); } else render();
    }
  }

  function step(dir) {
    if (mode === 'spread') {
      var s = spreadOf(at) + dir;
      go(dir > 0 ? 2 * s - 1 : Math.max(2 * s - 1, 0));
    } else {
      go(at + dir);
    }
  }

  // --- size ------------------------------------------------------------------------

  function fit() {
    var m = window.innerWidth < NARROW ? 'single' : 'spread';
    if (m !== mode) { mode = m; build(); }
    var wide = mode === 'spread' ? 2 * PAGE_W : PAGE_W;
    var cs = window.getComputedStyle(stage);
    var roomW = stage.clientWidth - (parseFloat(cs.paddingLeft) || 0) - (parseFloat(cs.paddingRight) || 0);
    var fromTop = stage.getBoundingClientRect().top + window.pageYOffset;
    var roomH = window.innerHeight - fromTop - 2 * (parseFloat(cs.paddingTop) || 0) - 16;
    if (roomH < window.innerHeight * 0.55) {
      // Too far down the page to count on: fit what is below the toolbar.
      roomH = window.innerHeight - (bar ? bar.getBoundingClientRect().height : 0) - 72;
    }
    var scale = 1;
    if (zoom === 'fit') {
      scale = mode === 'spread' ? Math.min(roomW / wide, roomH / PAGE_H, 1.5) : Math.min(roomW / wide, 1.25);
    } else if (zoom === 'width') {
      scale = Math.min(roomW / wide, 2);
    } else {
      scale = parseFloat(zoom) || 1;
    }
    scale = Math.max(scale, 0.2);
    viewport.style.width = (wide * scale) + 'px';
    viewport.style.height = (PAGE_H * scale) + 'px';
    book.style.transform = 'scale(' + scale + ')';
  }

  // --- the controls ----------------------------------------------------------------

  Array.prototype.forEach.call(root.querySelectorAll('[data-bk-go]'), function (b) {
    b.addEventListener('click', function () {
      var go_ = b.getAttribute('data-bk-go');
      if (go_ === 'first') go(0);
      else if (go_ === 'last') go(pages.length - 1);
      else step(go_ === 'next' ? 1 : -1);
    });
  });

  if (jump) {
    jump.addEventListener('change', function () {
      var p = firstPageOf[jump.value];
      if (p != null) go(p);
    });
  }

  if (zoomPick) {
    zoomPick.addEventListener('change', function () {
      zoom = zoomPick.value;
      try { localStorage.setItem('pm-book-zoom', zoom); } catch (e) { /* private window */ }
      fit();
    });
  }

  document.addEventListener('keydown', function (event) {
    if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) return;
    var t = event.target;
    if (t && (t.isContentEditable || /^(INPUT|SELECT|TEXTAREA)$/.test(t.tagName))) return;
    if (t && t.closest && t.closest('dialog, [role="dialog"], .carmen')) return;
    var k = event.key;
    if (k === 'ArrowRight' || k === 'PageDown') step(1);
    else if (k === 'ArrowLeft' || k === 'PageUp') step(-1);
    else if (k === 'Home') go(0);
    else if (k === 'End') go(pages.length - 1);
    else return;
    event.preventDefault();
  });

  var touch = null;
  stage.addEventListener('touchstart', function (event) {
    if (event.touches.length !== 1) { touch = null; return; }
    touch = { x: event.touches[0].clientX, y: event.touches[0].clientY };
  }, { passive: true });
  stage.addEventListener('touchend', function (event) {
    if (!touch || !event.changedTouches.length) return;
    var dx = event.changedTouches[0].clientX - touch.x;
    var dy = event.changedTouches[0].clientY - touch.y;
    touch = null;
    if (Math.abs(dx) > 50 && Math.abs(dx) > 1.5 * Math.abs(dy)) step(dx < 0 ? 1 : -1);
  }, { passive: true });

  var waiting = null;
  window.addEventListener('resize', function () {
    window.clearTimeout(waiting);
    waiting = window.setTimeout(function () {
      if ((window.devicePixelRatio || 1) !== cutAt) {
        if (busy) busy();
        paginate();
        build();
      }
      fit();
    }, 150);
  });

  // --- open the book ---------------------------------------------------------------

  function start() {
    paginate();
    var hash = /^#page-(\d+)$/.exec(window.location.hash);
    var row = root.getAttribute('data-start-row');
    if (hash) at = Math.min(Math.max(parseInt(hash[1], 10) - 1, 0), pages.length - 1);
    else if (row && firstPageOf[row] != null) at = firstPageOf[row];
    else at = 0;
    fit();                                          // builds the book for the width
    render();
  }

  var fonts = document.fonts && document.fonts.ready;
  if (fonts && typeof fonts.then === 'function') fonts.then(start, start);
  else start();
})();
