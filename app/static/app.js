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

  // Delegated from the document rather than bound per chart: a live refresh
  // replaces <main>, and charts bound at load would take their handlers with
  // them and stop answering the mouse.
  function hideTip(chart) {
    if (!chart) return;
    var tip = chart.querySelector('.chart-tip');
    if (tip) tip.hidden = true;
    var crosshair = chart.querySelector('.crosshair');
    if (crosshair) crosshair.setAttribute('visibility', 'hidden');
  }

  var overChart = null;

  document.addEventListener('mousemove', function (event) {
    var node = event.target;
    var chart = node && node.closest ? node.closest('.chart') : null;
    if (chart !== overChart) {
      hideTip(overChart);
      overChart = chart;
    }
    if (!chart) return;

    var tip = chart.querySelector('.chart-tip');
    if (!tip) return;

    var hit = node.closest('.hit');
    if (!hit || !hit.dataset.tip) {
      hideTip(chart);
      return;
    }

    var payload;
    try {
      payload = JSON.parse(hit.dataset.tip);
    } catch (err) {
      return;
    }
    renderTip(tip, payload);
    tip.hidden = false;
    place(chart, tip, event);

    var crosshair = chart.querySelector('.crosshair');
    if (crosshair && hit.dataset.x) {
      crosshair.setAttribute('x1', hit.dataset.x);
      crosshair.setAttribute('x2', hit.dataset.x);
      crosshair.setAttribute('visibility', 'visible');
    }
  });

  // --- print ---------------------------------------------------------------
  // The browser's own print dialog is the PDF writer; "Save as PDF" is offered
  // as a destination in every current browser.

  // Printing one chart on its own: the card is marked, the page is told only
  // to print what is marked, and both marks come off again afterwards.
  function unmarkPrint() {
    document.body.classList.remove('print-one');
    document.querySelectorAll('.print-keep').forEach(function (card) {
      card.classList.remove('print-keep');
    });
  }

  document.addEventListener('click', function (event) {
    var chart = event.target.closest('[data-print-chart]');
    if (chart) {
      var card = chart.closest('.card');
      if (!card) return;
      unmarkPrint();
      card.classList.add('print-keep');
      document.body.classList.add('print-one');
      window.print();
      return;
    }
    // A whole-page print always starts from a clean slate, in case a browser
    // never told us the last one had finished.
    if (event.target.closest('[data-print]')) {
      unmarkPrint();
      window.print();
    }
  });

  window.addEventListener('afterprint', unmarkPrint);

  // ?print=1 opens the print dialog on arrival. It is how the assistant hands
  // somebody a PDF of a tab — a link they click, rather than a file it had to
  // render itself.
  if (/[?&]print=1\b/.test(window.location.search)) {
    window.addEventListener('load', function () {
      window.setTimeout(function () { unmarkPrint(); window.print(); }, 350);
    });
  }

  // A folded panel is not on the paper unless it is opened first, and closing
  // it again afterwards leaves the screen as it was.
  var unfolded = [];
  var printing = false;
  window.addEventListener('beforeprint', function () {
    printing = true;
    unfolded = [];
    document.querySelectorAll('details.panel:not([open])').forEach(function (panel) {
      panel.open = true;
      unfolded.push(panel);
    });
  });
  window.addEventListener('afterprint', function () {
    unfolded.forEach(function (panel) { panel.open = false; });
    unfolded = [];
    // A toggle event arrives after the task that caused it, so the flag is
    // dropped a beat later or the folding back up would be recorded.
    window.setTimeout(function () { printing = false; }, 0);
  });

  // --- folded panels -------------------------------------------------------
  // Which details someone has open is their own preference, so it is kept in
  // their browser and put back on the next visit — and after a live refresh,
  // which replaces <main> and would otherwise fold everything up again.

  function panelKey(panel) {
    return 'pm-panel-' + (panel.dataset.panel || '');
  }

  function restorePanels() {
    document.querySelectorAll('details.panel[data-panel]').forEach(function (panel) {
      // One the page itself opened — the panel a form was just submitted from —
      // stays open whatever this browser remembers.
      if (panel.hasAttribute('data-keep-open')) return;
      try {
        var kept = window.localStorage.getItem(panelKey(panel));
        if (kept !== null) panel.open = kept === 'open';
      } catch (err) { /* private browsing; the default stands */ }
    });
  }

  // A panel the page itself opened is marked, and the mark says two things:
  // leave it open, and do not record a state nobody chose. Browsers fire a
  // toggle event for a <details open> as it is parsed, so without this every
  // server-opened panel would be remembered as the viewer's preference.
  document.addEventListener('click', function (event) {
    var summary = event.target.closest && event.target.closest('.panel-summary');
    if (summary && summary.parentNode) summary.parentNode.removeAttribute('data-keep-open');
  }, true);

  document.addEventListener('toggle', function (event) {
    var panel = event.target;
    if (!panel.matches || !panel.matches('details.panel[data-panel]')) return;
    if (printing || panel.hasAttribute('data-keep-open')) return;
    try {
      window.localStorage.setItem(panelKey(panel), panel.open ? 'open' : 'shut');
    } catch (err) { /* nothing to remember it with */ }
  }, true);

  restorePanels();

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
      var value = data[name];

      // A list means a group of check boxes — the trades an item sits with.
      if (Array.isArray(value)) {
        var boxes = field.length === undefined ? [field] : field;
        Array.prototype.forEach.call(boxes, function (box) {
          box.checked = value.indexOf(Number(box.value)) !== -1;
        });
        return;
      }
      field.value = value === null || value === undefined ? '' : value;
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

  // --- editing a cell where it stands --------------------------------------
  // The short fields — owner, trades, what an item affects, its date — are
  // links to the item's full form. Here a click becomes the control itself,
  // dropped into the cell and saved in the background: nothing reloads, and
  // nothing else on the item is touched. Without this the link still works.
  //
  // The controls come from one template per field at the foot of the page.
  // Rendering a copy into every row would repeat the owner list and the trade
  // boxes hundreds of times over a long register.

  var VALUE_OF = {
    owner: function (form) { return form.elements.owner_code.value || '—'; },
    impact: function (form) {
      var select = form.elements.impact;
      return select.value === 'none' ? '—' : select.options[select.selectedIndex].text;
    },
    due: function (form) { return form.elements.due_date.value || '—'; },
  };

  function fillCell(control, cell, kind) {
    var value = cell.dataset.value || '';
    if (kind === 'trades') {
      var chosen = value ? value.split(',') : [];
      control.querySelectorAll('input[name=trade_ids]').forEach(function (box) {
        box.checked = chosen.indexOf(box.value) !== -1;
      });
      return;
    }
    var field = control.matches('input, select') ? control : control.querySelector('input, select');
    if (field) field.value = value;
  }

  function closeCell(form, html, state) {
    var cell = form.parentNode;
    if (!cell) return;
    cell.innerHTML = html;
    if (state) {
      cell.className = cell.className.replace(/\bimpact-\S*/g, '').trim() + ' ' + state;
    }
    cell.classList.add('cell-saved');
    window.setTimeout(function () { cell.classList.remove('cell-saved'); }, 1400);
  }

  function restoreCell(form) {
    // Puts a cell back exactly as it was, with none of the saved flash — the
    // change did not happen.
    var cell = form.parentNode;
    if (cell) cell.innerHTML = form.dataset.was;
  }

  function openCell(link) {
    var kind = link.dataset.cell;
    var template = document.getElementById('cell-' + kind);
    if (!template) return false;

    var cell = link.parentNode;
    var form = document.createElement('form');
    form.method = 'post';
    form.action = link.dataset.action;
    form.className = 'cell-form';
    form.dataset.itemId = link.dataset.item;
    form.dataset.cell = kind;
    form.dataset.was = cell.innerHTML;
    // A page showing deliverables and minuted items together has a task 5 and
    // an item 5. The prefix keeps one save from rewriting the other's badge.
    form.dataset.rows = link.dataset.rows || '';

    ['back:return', 'mode:mode', 'date:data_date'].forEach(function (pair) {
      var from = pair.split(':')[0];
      if (!link.dataset[from]) return;
      var hidden = document.createElement('input');
      hidden.type = 'hidden';
      hidden.name = pair.split(':')[1];
      hidden.value = link.dataset[from];
      form.appendChild(hidden);
    });

    var control = template.content.firstElementChild.cloneNode(true);
    fillCell(control, link, kind);
    form.appendChild(control);

    var save = document.createElement('button');
    save.type = 'submit';
    save.className = 'btn btn-ghost btn-sm save-inline';
    save.textContent = 'Save';
    form.appendChild(save);

    cell.innerHTML = '';
    cell.appendChild(form);
    var first = form.querySelector('select, input:not([type=hidden])');
    if (first) {
      first.focus({ preventScroll: true });
      // A select is what the click was aiming at, so open it straight away.
      if (first.tagName === 'SELECT' && first.showPicker) {
        try { first.showPicker(); } catch (err) { /* not allowed here */ }
      }
    }
    return true;
  }

  function saveCell(form) {
    form.classList.add('saving');
    fetch(form.action, {
      method: 'POST',
      body: new FormData(form),
      headers: { Accept: 'application/json' },
      credentials: 'same-origin',
    }).then(function (response) {
      if (response.status === 400) {
        // The server refused it — a link onto itself, say, or one that would
        // close a loop. Put the cell back and give the reason.
        return response.json().then(function (result) {
          restoreCell(form);
          say(result.error || 'That change was not accepted');
          return null;
        });
      }
      if (!response.ok) throw new Error(response.status);
      return response.json();
    }).then(function (result) {
      if (result === null) return;
      // A schedule change can move other lines with it, so the answer says
      // which rows to redraw rather than the page reloading to find out.
      if (result.moved) {
        redrawPlan(result.moved, form);
        window.dispatchEvent(new Event('pm:saved'));
        return;
      }
      // A dependency changed: the diagram and every line's float follow from
      // it, so both are redrawn from what the server sent back.
      if (result.network_html !== undefined) {
        redrawLinks(result, form);
        window.dispatchEvent(new Event('pm:saved'));
        return;
      }
      // A progress row: the bar, the badge and the variance all follow the
      // figure that was just recorded, so the server sends them back drawn.
      if (result.progress_html !== undefined) {
        var where = form.dataset.rows || '';
        var task = form.dataset.itemId;
        closeCell(form, cellLink(form, result.progress_html), '');
        replaceHtml(where + 'status-' + task, result.status_html);
        replaceHtml(where + 'variance-' + task, result.variance_html);
        replaceHtml(where + 'actions-' + task, result.actions_html);
        window.dispatchEvent(new Event('pm:saved'));
        return;
      }

      var kind = form.dataset.cell;
      var id = form.dataset.itemId;
      var state = '';
      var html;

      if (kind === 'trades') {
        html = result.trade_html;
      } else {
        var reader = VALUE_OF[kind];
        html = reader ? reader(form) : form.dataset.was;
        if (kind === 'impact') state = 'impact-' + form.elements.impact.value;
      }
      closeCell(form, cellLink(form, html), state);

      // The badge reads on the date and on whether the item is closed.
      var status = document.getElementById((form.dataset.rows || '') + 'status-' + id);
      if (status && result.status_html) status.innerHTML = result.status_html;
    }).catch(function () {
      // Something went wrong out of sight; post it properly so the change is
      // never quietly lost.
      form.submit();
    });
  }

  function redrawPlan(rows, form) {
    var editedId = form.dataset.itemId;
    rows.forEach(function (row) {
      setPlanCell('start-' + row.id, 'plan-start', row.start, row.start, form);
      setPlanCell('duration-' + row.id, 'plan-duration', row.duration + 'd', row.duration, form);
      setPlanCell('submission-' + row.id, 'plan-submission', row.submission, row.submission, form);
      if (row.team !== undefined) {
        setPlanCell('team-' + row.id, 'plan-team', row.team, row.team_id, form);
      }

      var slack = document.getElementById('float-' + row.id);
      if (slack) {
        slack.innerHTML = row.critical
          ? '<span class="badge critical"><span aria-hidden="true">■</span> critical</span>'
          : row.float + 'd';
      }
      var line = document.getElementById('task-' + row.id);
      if (line) {
        line.classList.toggle('is-critical', !!row.critical);
        if (String(row.id) !== String(editedId)) line.classList.add('cell-saved');
        window.setTimeout(function () { line.classList.remove('cell-saved'); }, 1600);
      }
    });
    // The bars and the network are drawn on the server, so they are fetched
    // again rather than redrawn by hand.
    refreshCharts();
  }

  function setPlanCell(id, kind, label, value, form) {
    var cell = document.getElementById(id);
    if (!cell) return;

    var link = cell.querySelector('.cell-open');
    if (link) {
      link.textContent = label;
      link.dataset.value = value;
    } else if (form && cell.contains(form)) {
      // The cell being edited: put its link back, or it could never be
      // clicked again without reloading the page.
      cell.innerHTML = '';
      cell.appendChild(planLink(kind, form, label, value));
    } else {
      cell.textContent = label;
    }
    cell.classList.add('cell-saved');
    window.setTimeout(function () { cell.classList.remove('cell-saved'); }, 1600);
  }

  function planLink(kind, form, label, value) {
    var link = document.createElement('a');
    link.className = 'cell-open';
    link.dataset.cell = kind;
    link.dataset.item = form.dataset.itemId;
    link.dataset.action = form.action;
    link.dataset.value = value;
    if (form.elements.mode) link.dataset.mode = form.elements.mode.value;
    link.href = window.location.href;
    link.title = 'Click to change';
    link.textContent = label;
    return link;
  }

  function refreshCharts() {
    fetch(window.location.href, { credentials: 'same-origin' })
      .then(function (r) { return r.text(); })
      .then(function (html) {
        var fresh = new DOMParser().parseFromString(html, 'text/html');
        ['.chart'].forEach(function (selector) {
          var now = document.querySelectorAll(selector);
          var next = fresh.querySelectorAll(selector);
          for (var i = 0; i < now.length && i < next.length; i++) {
            now[i].replaceWith(next[i]);
          }
        });
      }).catch(function () { /* the chart simply stays as it was */ });
  }

  function redrawLinks(result, form) {
    // A change to either end sends the whole row back; the other two cells are
    // put back as links here.
    if (form && !result.link_html) {
      var kind = form.dataset.cell;
      var field = form.elements.lag_days || form.elements.kind;
      var label = field
        ? (kind === 'link-lag' ? field.value + 'd' : field.options[field.selectedIndex].text)
        : '';
      closeCell(form, cellLink(form, label), '');
    }

    (result.rows || []).forEach(function (row) {
      var slack = document.getElementById('float-' + row.id);
      if (slack) {
        slack.innerHTML = row.critical
          ? '<span class="badge critical"><span aria-hidden="true">■</span> critical</span>'
          : row.float + 'd';
      }
      var line = document.getElementById('task-' + row.id);
      if (line) line.classList.toggle('is-critical', !!row.critical);
    });

    // When an end of a link changed, its row carries new WBS numbers, so the
    // server sends the row back drawn rather than it being patched by hand.
    if (result.link_html && form) {
      var row = document.getElementById('link-' + form.dataset.itemId);
      if (row) {
        var holder = document.createElement('tbody');
        holder.innerHTML = result.link_html.trim();
        var fresh = holder.querySelector('tr');
        if (fresh) {
          row.replaceWith(fresh);
          fresh.classList.add('cell-saved');
          window.setTimeout(function () { fresh.classList.remove('cell-saved'); }, 1600);
        }
      }
    }

    var diagram = document.getElementById('network');
    if (diagram && result.network_html) diagram.innerHTML = result.network_html;

    // A link does not only change the diagram: it moves dates, and with them
    // the bars, the float, the tiles and the count of paths. The page is
    // brought into line rather than each of those being patched by hand — and
    // the promise is handed back, so anything to be said lands after the swap
    // instead of being wiped by it.
    return refreshPage().catch(function () { /* the diagram is already right */ });
  }

  // Making a dependency, from the form under the diagram or the one in a
  // deliverable's panel: posted where it stands, and everything it moves is
  // redrawn rather than the page being loaded again.
  document.addEventListener('submit', function (event) {
    var form = event.target.closest('form[data-live-link]');
    if (!form || !window.fetch) return;

    event.preventDefault();
    fetch(form.action, {
      method: 'POST', body: new FormData(form),
      headers: { Accept: 'application/json' }, credentials: 'same-origin',
    }).then(function (r) { return r.json().then(function (body) { return [r.ok, body]; }); })
      .then(function (answer) {
        if (!answer[0]) {
          say((answer[1] && answer[1].error) || 'That link was not accepted');
          return;
        }
        form.reset();
        redrawLinks(answer[1], null);
        window.dispatchEvent(new Event('pm:saved'));
      }).catch(function () { form.submit(); });
  });

  // Removing a dependency takes the row with it, and redraws what it changed.
  document.addEventListener('submit', function (event) {
    var form = event.target.closest('form[data-live-remove]');
    if (!form || !window.fetch) return;

    event.preventDefault();
    fetch(form.action, {
      method: 'POST',
      body: new FormData(form),
      headers: { Accept: 'application/json' },
      credentials: 'same-origin',
    }).then(function (response) {
      if (!response.ok) throw new Error(response.status);
      return response.json();
    }).then(function (result) {
      var row = document.getElementById(form.dataset.row);
      if (row) row.remove();
      redrawLinks(result, null);
      window.dispatchEvent(new Event('pm:saved'));
    }).catch(function () { form.submit(); });
  });

  // "Simplify" reorders the boxes to untangle the lines; "Tidy up" forgets
  // where they were put by hand. Both redraw the diagram where it stands.
  document.addEventListener('click', function (event) {
    var button = event.target.closest('[data-relayout]');
    if (!button || !window.fetch) return;
    var form = button.closest('form');
    if (!form) return;

    event.preventDefault();
    button.disabled = true;
    fetch(form.action, {
      method: 'POST', headers: { Accept: 'application/json' }, credentials: 'same-origin',
    }).then(function (r) { return r.ok ? r.json() : Promise.reject(); })
      .then(function (result) {
        return Promise.resolve(redrawLinks(result, null)).then(function () {
          if (result.note) say(result.note, 'success');
          window.dispatchEvent(new Event('pm:saved'));
          button.disabled = false;
        });
      }).catch(function () { form.submit(); });
  });

  // --- dragging a box on the dependency diagram ----------------------------
  // The automatic layout puts boxes in the order the work runs, which is the
  // right starting point but leaves arrows crossing on a busy programme. A box
  // can be dragged anywhere, and stays where it is put.

  var dragging = null;

  function svgPoint(svg, event) {
    var box = svg.getBoundingClientRect();
    var view = svg.viewBox.baseVal;
    var scale = view && view.width ? view.width / box.width : 1;
    return { x: (event.clientX - box.left) * scale, y: (event.clientY - box.top) * scale };
  }

  function redrawEdges(node) {
    var svg = node.ownerSVGElement;
    var net = svg.querySelector('.net');
    if (!net) return;
    var w = Number(net.dataset.boxW || 54);
    var h = Number(net.dataset.boxH || 26);

    svg.querySelectorAll('.net-edge').forEach(function (edge) {
      var from = svg.querySelector('.net-node[data-node="' + edge.dataset.from + '"]');
      var to = svg.querySelector('.net-node[data-node="' + edge.dataset.to + '"]');
      if (!from || !to) return;
      var x1 = Number(from.dataset.x), y1 = Number(from.dataset.y);
      var x2 = Number(to.dataset.x), y2 = Number(to.dataset.y);
      // A link that waits on the other line's start leaves the left edge, as
      // the server draws it; one that waits on its finish leaves the right.
      var kind = edge.dataset.kind || 'FS';
      var side = (kind === 'SS' || kind === 'SF') ? x1 : x1 + w;
      var bend = Math.max(24, Math.abs(x2 - side) / 2);
      edge.setAttribute('d', 'M' + side + ',' + (y1 + h / 2)
        + ' C' + (side + bend) + ',' + (y1 + h / 2)
        + ' ' + (x2 - bend) + ',' + (y2 + h / 2)
        + ' ' + x2 + ',' + (y2 + h / 2));
    });
  }

  // --- one deliverable, in a panel -----------------------------------------
  // The link is a real link to the deliverable's own page, so it works with no
  // JavaScript; with it, the same markup opens beside the schedule instead.

  var openTask = null;

  function panelParts() {
    return {
      panel: document.getElementById('task-panel'),
      veil: document.getElementById('panel-veil'),
    };
  }

  function closePanel() {
    var parts = panelParts();
    if (!parts.panel) return;
    parts.panel.hidden = true;
    parts.panel.innerHTML = '';
    if (parts.veil) parts.veil.hidden = true;
    openTask = null;
  }

  function showPanel(html) {
    var parts = panelParts();
    if (!parts.panel) return false;
    parts.panel.innerHTML = html;
    parts.panel.hidden = false;
    if (parts.veil) parts.veil.hidden = false;
    parts.panel.scrollTop = 0;
    return true;
  }

  function loadPanel(taskId, url) {
    return fetch(url, {
      credentials: 'same-origin', headers: { Accept: 'application/json' },
    }).then(function (r) { return r.ok ? r.json() : Promise.reject(); })
      .then(function (result) {
        if (!showPanel(result.panel_html)) throw new Error('no panel');
        openTask = taskId;
      });
  }

  document.addEventListener('click', function (event) {
    if (event.target.closest('[data-panel-close]') || event.target.id === 'panel-veil') {
      closePanel();
      return;
    }

    var opener = event.target.closest ? event.target.closest('.open-task') : null;
    if (!opener || !window.fetch || !document.getElementById('task-panel')) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey) return;   // let it open elsewhere

    event.preventDefault();
    loadPanel(opener.dataset.task, opener.href)
      .catch(function () { window.location.href = opener.href; });
  });

  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && openTask !== null) closePanel();
  });

  // A change made in the panel moves dates and links, so the panel is rebuilt
  // from the server along with everything else.
  window.addEventListener('pm:saved', function () {
    if (openTask === null) return;
    var url = document.body.dataset.pulseUrl;
    if (!url) return;
    loadPanel(openTask, url.replace(/\/pulse$/, '/schedule/' + openTask))
      .catch(function () { /* the panel keeps what it had */ });
  });

  // Clicking a line on the diagram removes the dependency it stands for.
  document.addEventListener('click', function (event) {
    var edge = event.target.closest ? event.target.closest('.net-edge') : null;
    if (!edge || !edge.dataset.link || !window.fetch) return;

    var svg = edge.ownerSVGElement;
    var base = linksUrl(svg);
    if (!base) return;

    event.preventDefault();
    if (!window.confirm('Remove this dependency?')) return;
    fetch(base + '/' + edge.dataset.link + '/delete', {
      method: 'POST', headers: { Accept: 'application/json' }, credentials: 'same-origin',
    }).then(function (r) { return r.ok ? r.json() : Promise.reject(); })
      .then(function (result) {
        var row = document.getElementById('link-' + edge.dataset.link);
        if (row) row.remove();
        redrawLinks(result, null);
        window.dispatchEvent(new Event('pm:saved'));
      }).catch(function () { window.location.reload(); });
  });

  // --- drawing a link on the diagram ---------------------------------------
  // Dragging the box moves it; dragging the little plug on its right edge
  // draws a new dependency onto whatever box it is dropped on.

  var drawing = null;

  function linksUrl(svg) {
    var net = svg && svg.querySelector('.net');
    return (net && net.dataset.links) || '';
  }

  function draftLine(svg, from, to) {
    var line = svg.querySelector('.net-draft');
    if (!line) {
      line = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      line.setAttribute('class', 'net-draft');
      line.setAttribute('fill', 'none');
      svg.appendChild(line);
    }
    line.setAttribute('d', 'M' + from.x + ',' + from.y + ' L' + to.x + ',' + to.y);
  }

  function clearDraft(svg) {
    var line = svg && svg.querySelector('.net-draft');
    if (line) line.remove();
  }

  document.addEventListener('pointerdown', function (event) {
    var plug = event.target.closest('.net-plug');
    if (plug) {
      var host = plug.closest('.net-node');
      var board = host.ownerSVGElement;
      if (!linksUrl(board)) return;
      drawing = {
        svg: board,
        from: host,
        at: {
          x: Number(host.dataset.x) + Number(board.querySelector('.net').dataset.boxW || 54),
          y: Number(host.dataset.y) + Number(board.querySelector('.net').dataset.boxH || 26) / 2,
        },
      };
      host.classList.add('linking');
      event.preventDefault();
      return;
    }

    var node = event.target.closest('.net-node.movable');
    if (!node) return;

    var svg = node.ownerSVGElement;
    var at = svgPoint(svg, event);
    dragging = {
      node: node,
      grabX: at.x - Number(node.dataset.x),
      grabY: at.y - Number(node.dataset.y),
      moved: false,
    };
    node.classList.add('dragging');
    event.preventDefault();
  });

  document.addEventListener('pointermove', function (event) {
    if (drawing) {
      draftLine(drawing.svg, drawing.at, svgPoint(drawing.svg, event));
      var over = event.target.closest ? event.target.closest('.net-node') : null;
      drawing.svg.querySelectorAll('.net-node.target').forEach(function (n) {
        n.classList.remove('target');
      });
      if (over && over !== drawing.from) over.classList.add('target');
      return;
    }
    if (!dragging) return;
    var node = dragging.node;
    var at = svgPoint(node.ownerSVGElement, event);
    var x = Math.max(0, Math.round(at.x - dragging.grabX));
    var y = Math.max(0, Math.round(at.y - dragging.grabY));

    node.dataset.x = x;
    node.dataset.y = y;
    node.setAttribute('transform', 'translate(' + x + ',' + y + ')');
    dragging.moved = true;
    redrawEdges(node);
  });

  document.addEventListener('pointerup', function (event) {
    if (drawing) {
      var svg = drawing.svg;
      var source = drawing.from;
      var onto = event.target.closest ? event.target.closest('.net-node') : null;
      source.classList.remove('linking');
      svg.querySelectorAll('.net-node.target').forEach(function (n) {
        n.classList.remove('target');
      });
      clearDraft(svg);
      var where = linksUrl(svg);
      drawing = null;
      if (!onto || onto === source || !where) return;

      var made = new FormData();
      made.append('predecessor_id', source.dataset.node);
      made.append('successor_id', onto.dataset.node);
      made.append('kind', 'FS');
      made.append('lag_days', '0');
      fetch(where, {
        method: 'POST', body: made,
        headers: { Accept: 'application/json' }, credentials: 'same-origin',
      }).then(function (r) { return r.json().then(function (body) { return [r.ok, body]; }); })
        .then(function (answer) {
          if (!answer[0]) {
            say((answer[1] && answer[1].error) || 'That link was not accepted');
            return;
          }
          redrawLinks(answer[1], null);
          window.dispatchEvent(new Event('pm:saved'));
        }).catch(function () { window.location.reload(); });
      return;
    }
    if (!dragging) return;
    var node = dragging.node;
    var moved = dragging.moved;
    node.classList.remove('dragging');
    dragging = null;
    if (!moved) return;                        // a plain click, not a drag

    var url = document.body.dataset.pulseUrl;
    if (!url) return;
    var save = url.replace(/\/pulse$/, '/schedule/layout/' + node.dataset.node);
    var body = new FormData();
    body.append('x', node.dataset.x);
    body.append('y', node.dataset.y);
    fetch(save, {
      method: 'POST', body: body,
      headers: { Accept: 'application/json' }, credentials: 'same-origin',
    }).then(function () { window.dispatchEvent(new Event('pm:saved')); })
      .catch(function () { /* it stays where it was dropped until the next load */ });
  });

  function replaceHtml(id, html) {
    var node = document.getElementById(id);
    if (node && typeof html === 'string') node.innerHTML = html;
  }

  function say(message, category) {
    // The same strip the server flashes into, so a refused change reads the
    // way every other message on the page does.
    var wrap = document.querySelector('main .wrap');
    if (!wrap) return window.alert(message);
    var strip = wrap.querySelector('.flashes');
    if (!strip) {
      strip = document.createElement('div');
      strip.className = 'flashes';
      wrap.insertBefore(strip, wrap.firstChild);
    }
    var note = document.createElement('div');
    note.className = 'flash ' + (category || 'error');
    note.setAttribute('role', category === 'success' ? 'status' : 'alert');
    note.textContent = message;
    strip.appendChild(note);
    strip.scrollIntoView({ block: 'nearest' });
    window.setTimeout(function () { note.remove(); }, 8000);
  }

  function cellLink(form, label) {
    // The cell goes back to being a link, carrying what it now holds.
    var kind = form.dataset.cell;
    var value = kind === 'trades'
      ? Array.prototype.filter.call(form.elements.trade_ids.length ? form.elements.trade_ids : [form.elements.trade_ids],
                                    function (box) { return box.checked; })
          .map(function (box) { return box.value; }).join(',')
      : (form.elements.owner_code || form.elements.impact || form.elements.due_date
         || form.elements.status_key || form.elements.actual_pct
         || form.elements.lag_days || form.elements.kind).value;
    var link = document.createElement('a');
    link.className = 'cell-open';
    link.dataset.cell = kind;
    link.dataset.item = form.dataset.itemId;
    link.dataset.action = form.action;
    link.dataset.value = value;
    link.href = window.location.href;
    link.title = 'Click to change';
    link.innerHTML = label;
    var back = form.elements['return'];
    if (back) link.dataset.back = back.value;
    return link.outerHTML;
  }

  document.addEventListener('click', function (event) {
    var link = event.target.closest('.cell-open');
    if (link && openCell(link)) event.preventDefault();
  });

  document.addEventListener('change', function (event) {
    var form = event.target.closest('form.cell-form');
    if (form) saveCell(form);
  });

  document.addEventListener('submit', function (event) {
    var form = event.target.closest('form.cell-form');
    if (form && window.fetch) {
      event.preventDefault();
      saveCell(form);
    }
  });

  // --- date picker ---------------------------------------------------------
  // A calendar for the date fields. Written here rather than using the
  // browser's own <input type="date">, whose displayed order follows the
  // machine's locale — the reason 1 September once read 09/01. The field stays
  // an ordinary text box, so a date can still be typed, and everything reads
  // dd/mm/yyyy on every machine.

  var MONTHS = ['January', 'February', 'March', 'April', 'May', 'June',
                'July', 'August', 'September', 'October', 'November', 'December'];
  var DAYS = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su'];
  var calendar = null;
  var target = null;
  var view = null;                          // the month on show

  function parseTyped(text) {
    var parts = String(text || '').split(/\D+/).filter(Boolean);
    if (parts.length !== 3) return null;
    var year = Number(parts[2]);
    if (year < 100) year += 2000;
    var date = new Date(year, Number(parts[1]) - 1, Number(parts[0]));
    return isNaN(date.getTime()) ? null : date;
  }

  function format(date) {
    var day = String(date.getDate()).padStart(2, '0');
    var month = String(date.getMonth() + 1).padStart(2, '0');
    return day + '/' + month + '/' + date.getFullYear();
  }

  function sameDay(a, b) {
    return a && b && a.getFullYear() === b.getFullYear()
      && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
  }

  function grid(month, chosen) {
    var first = new Date(month.getFullYear(), month.getMonth(), 1);
    var lead = (first.getDay() + 6) % 7;      // weeks start on Monday
    var start = new Date(first);
    start.setDate(1 - lead);
    var today = new Date();

    var cells = '';
    for (var i = 0; i < 42; i++) {
      var day = new Date(start.getFullYear(), start.getMonth(), start.getDate() + i);
      var classes = ['cal-day'];
      if (day.getMonth() !== month.getMonth()) classes.push('outside');
      if (sameDay(day, today)) classes.push('today');
      if (sameDay(day, chosen)) classes.push('chosen');
      cells += '<button type="button" class="' + classes.join(' ') + '" data-date="'
        + format(day) + '"'
        + (sameDay(day, chosen) ? ' aria-current="date"' : '') + '>' + day.getDate() + '</button>';
    }
    return cells;
  }

  function draw() {
    var chosen = parseTyped(target && target.value);
    calendar.innerHTML =
      '<div class="cal-head">'
      + '<button type="button" class="cal-nav" data-step="-1" aria-label="Previous month">‹</button>'
      + '<span class="cal-month">' + MONTHS[view.getMonth()] + ' ' + view.getFullYear() + '</span>'
      + '<button type="button" class="cal-nav" data-step="1" aria-label="Next month">›</button>'
      + '</div>'
      + '<div class="cal-week">' + DAYS.map(function (d) { return '<span>' + d + '</span>'; }).join('') + '</div>'
      + '<div class="cal-grid">' + grid(view, chosen) + '</div>'
      + '<div class="cal-foot">'
      + '<button type="button" class="btn btn-ghost btn-sm" data-date="' + format(new Date()) + '">Today</button>'
      + '<button type="button" class="btn btn-ghost btn-sm" data-clear>Clear</button>'
      + '</div>';
  }

  function closeCalendar() {
    if (calendar) calendar.hidden = true;
    target = null;
  }

  function openCalendar(input) {
    if (!calendar) {
      calendar = document.createElement('div');
      calendar.className = 'calendar';
      calendar.hidden = true;
      document.body.appendChild(calendar);
    }
    target = input;
    view = parseTyped(input.value) || new Date();
    view = new Date(view.getFullYear(), view.getMonth(), 1);
    draw();

    var box = input.getBoundingClientRect();
    calendar.hidden = false;
    // Flip above the field when there is no room below it.
    var below = window.innerHeight - box.bottom;
    var top = below > calendar.offsetHeight + 8 || box.top < calendar.offsetHeight
      ? box.bottom + 4
      : box.top - calendar.offsetHeight - 4;
    calendar.style.top = (top + window.scrollY) + 'px';
    calendar.style.left = Math.max(
      8, Math.min(box.left + window.scrollX, window.scrollX + window.innerWidth - calendar.offsetWidth - 8)
    ) + 'px';
  }

  document.addEventListener('focusin', function (event) {
    var field = event.target.closest('[data-datepicker]');
    if (field) openCalendar(field);
    else if (calendar && !event.target.closest('.calendar')) closeCalendar();
  });

  document.addEventListener('click', function (event) {
    if (event.target.closest('[data-datepicker]')) return;
    var inside = event.target.closest('.calendar');
    if (!inside) {
      closeCalendar();
      return;
    }

    var step = event.target.closest('[data-step]');
    if (step) {
      view = new Date(view.getFullYear(), view.getMonth() + Number(step.dataset.step), 1);
      draw();
      return;
    }
    if (event.target.closest('[data-clear]') && target) {
      target.value = '';
      target.dispatchEvent(new Event('change', { bubbles: true }));
      closeCalendar();
      return;
    }
    var day = event.target.closest('[data-date]');
    if (day && target) {
      target.value = day.dataset.date;
      target.dispatchEvent(new Event('change', { bubbles: true }));
      closeCalendar();
    }
  });

  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') closeCalendar();
  });

  window.addEventListener('resize', closeCalendar);

  // --- keeping the page live -----------------------------------------------
  // Somebody else's edit should appear without anyone pressing refresh. The
  // page asks the server for a short token every few seconds; when it differs
  // from the one the page was drawn with, the page fetches itself again and
  // swaps in the new content. Every handler here is bound to the document, so
  // replacing the page body leaves them all working.
  //
  // Checking pauses while the tab is in the background, and while something is
  // being edited — nobody's typing should be pulled out from under them.

  var PULSE_MS = 15000;
  var pulseTimer = null;

  function busyEditing() {
    if (document.querySelector('form.cell-form')) return true;      // a cell is open
    var here = document.activeElement;
    if (!here) return false;
    return /^(INPUT|SELECT|TEXTAREA)$/.test(here.tagName) || here.isContentEditable;
  }

  function swapPage(html) {
    var fresh = new DOMParser().parseFromString(html, 'text/html');
    var next = fresh.querySelector('main');
    var here = document.querySelector('main');
    if (!next || !here) return false;

    // An open deliverable panel is carried across the swap, so a live refresh
    // does not shut it under the reader; pm:saved refreshes its contents.
    var showing = document.getElementById('task-panel');
    var wasOpen = showing && !showing.hidden ? showing.innerHTML : '';

    var offset = window.scrollY;
    here.replaceWith(next);
    if (wasOpen) showPanel(wasOpen);
    restorePanels();                 // the fresh page folds up by default
    window.scrollTo(0, offset);
    document.body.dataset.pulse = fresh.body.dataset.pulse || '';
    if (fresh.title) document.title = fresh.title;
    return true;
  }

  function refreshPage() {
    return fetch(window.location.href, {
      credentials: 'same-origin',
      headers: { 'X-Requested-With': 'live' },
    }).then(function (response) {
      if (!response.ok) throw new Error(response.status);
      return response.text();
    }).then(swapPage);
  }

  function checkPulse() {
    var url = document.body.dataset.pulseUrl;
    if (!url || document.hidden || busyEditing()) return;

    fetch(url, { credentials: 'same-origin', headers: { Accept: 'application/json' } })
      .then(function (response) { return response.ok ? response.json() : null; })
      .then(function (result) {
        if (!result || result.v === document.body.dataset.pulse) return;
        if (busyEditing()) return;             // they started while we asked
        return refreshPage();
      })
      .catch(function () { /* a missed check is not worth saying anything about */ });
  }

  function startPulse() {
    if (!document.body.dataset.pulseUrl || pulseTimer) return;
    pulseTimer = window.setInterval(checkPulse, PULSE_MS);
  }

  document.addEventListener('visibilitychange', function () {
    if (!document.hidden) checkPulse();       // catch up the moment they come back
  });
  startPulse();

  // The page's own edits move it on, so the next check does not read them as
  // somebody else's and redraw over the top.
  window.addEventListener('pm:saved', function () {
    var url = document.body.dataset.pulseUrl;
    if (!url) return;
    fetch(url, { credentials: 'same-origin', headers: { Accept: 'application/json' } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (result) { if (result) document.body.dataset.pulse = result.v; })
      .catch(function () { /* the next check will settle it */ });
  });

  // --- Carmen --------------------------------------------------------------
  // A chat that reads the project and proposes changes. The same code runs the
  // Assistant tab and the pop-up that sits on every other page, because they
  // are the same conversation in two shapes — one initialiser, taking whichever
  // container it is given.

  function startCarmen(chat) {
    if (!chat || chat.dataset.started) return;
    chat.dataset.started = '1';

    var wrap = chat.closest('[data-carmen]') || document;
    var form = wrap.querySelector('[data-chat-form]');
    var log = chat;
    var asking = false;
    var lastChat = null;

    // The list of conversations is server-rendered, so it is refreshed rather
    // than rebuilt here — one shape of the truth, not two.
    var refreshing = null;
    function threadsSoon() {
      var side = document.querySelector('.chat-list');
      if (!side || !window.fetch || !chat.dataset.here) return;
      window.clearTimeout(refreshing);
      refreshing = window.setTimeout(function () {
        fetch(window.location.href, { credentials: 'same-origin' })
          .then(function (r) { return r.ok ? r.text() : Promise.reject(); })
          .then(function (html) {
            var fresh = new DOMParser().parseFromString(html, 'text/html')
              .querySelector('.chat-list');
            if (fresh) side.innerHTML = fresh.innerHTML;
          }).catch(function () { /* the list is one reload away */ });
      }, 400);
    }

    function line(kind, html) {
      var row = document.createElement('div');
      row.className = 'chat-line ' + kind;
      row.innerHTML = html;
      log.appendChild(row);
      log.scrollTop = log.scrollHeight;
      return row;
    }

    function words(text) {
      // The model writes plain text. Paragraphs and simple lists are all that
      // is honoured; anything else is shown as it was written.
      var safe = document.createElement('div');
      safe.textContent = String(text || '');
      return safe.innerHTML
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .split(/\n{2,}/).map(function (part) {
          if (/^\s*[-*•]\s/m.test(part)) {
            var items = part.split(/\n/).filter(Boolean).map(function (item) {
              return '<li>' + item.replace(/^\s*[-*•]\s?/, '') + '</li>';
            }).join('');
            return '<ul class="guide-list">' + items + '</ul>';
          }
          return '<p>' + part.replace(/\n/g, '<br>') + '</p>';
        }).join('');
    }

    function staging(answer, row) {
      if (!answer.staged || !answer.staged.length || !chat.dataset.canWrite) return;

      var list = answer.staged.map(function (change) {
        var said = document.createElement('span');
        said.textContent = change.says || change.kind;
        return '<li>' + said.innerHTML + '</li>';
      }).join('');

      var box = document.createElement('div');
      box.className = 'chat-staged';
      box.innerHTML =
        '<p class="field-label">Waiting for you — nothing has changed yet</p>' +
        '<ul class="guide-list">' + list + '</ul>' +
        '<div class="inline-form" style="margin-top:8px">' +
        '<button type="button" class="btn btn-primary btn-sm" data-apply>Apply ' +
        answer.staged.length + ' change' + (answer.staged.length === 1 ? '' : 's') + '</button>' +
        '<button type="button" class="btn btn-ghost btn-sm" data-discard>Discard</button>' +
        '</div>';
      row.appendChild(box);
      log.scrollTop = log.scrollHeight;

      box.querySelector('[data-discard]').addEventListener('click', function () {
        box.innerHTML = '<p class="small muted" style="margin:0">Discarded — nothing changed.</p>';
      });
      box.querySelector('[data-apply]').addEventListener('click', function (event) {
        var button = event.target;
        button.disabled = true;
        button.textContent = 'Applying…';
        fetch(chat.dataset.apply, {
          method: 'POST',
          credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
          body: JSON.stringify({ actions: answer.staged, chat_id: answer.chat_id }),
        }).then(function (response) {
          return response.json().then(function (result) { return [response.ok, result]; });
        }).then(function (pair) {
          if (!pair[0] || !pair[1].ok) {
            button.disabled = false;
            button.textContent = 'Try again';
            say((pair[1] && pair[1].error) || 'That could not be applied');
            return;
          }
          var done = document.createElement('span');
          done.textContent = pair[1].note || 'Done';
          box.innerHTML = '<p class="small" style="margin:0"><strong>Applied.</strong> ' +
            done.innerHTML + ' The tabs it touched are already showing it.</p>';
          window.dispatchEvent(new Event('pm:saved'));
        }).catch(function () {
          button.disabled = false;
          button.textContent = 'Try again';
          say('That could not be applied');
        });
      });
    }

    function linksFrom(answer, row) {
      if (!answer.links || !answer.links.length) return;

      // Asked to be taken somewhere, go there. That is the difference between
      // an assistant and a search box.
      var going = answer.links.filter(function (link) {
        return link.kind === 'open_view' && link.go && !link.printable;
      })[0];

      var box = document.createElement('div');
      box.className = 'inline-form';
      box.style.marginTop = '8px';
      answer.links.forEach(function (link) {
        var anchor = document.createElement('a');
        anchor.className = 'btn btn-ghost btn-sm';
        anchor.href = link.url;
        if (link.kind === 'presentation') anchor.textContent = 'Download the deck';
        else if (link.kind === 'document') anchor.textContent = link.says || 'Download';
        else anchor.textContent = link.says || 'Open';
        box.appendChild(anchor);
      });
      row.appendChild(box);

      if (going) {
        window.setTimeout(function () { window.location.href = going.url; }, 700);
      }
    }

    // Files waiting to go up with the next question.
    var attached = [];

    function drawAttached() {
      var tray = wrap.querySelector('[data-attached]');
      if (!tray) return;
      tray.innerHTML = '';
      tray.hidden = attached.length === 0;
      attached.forEach(function (file, index) {
        var chip = document.createElement('span');
        chip.textContent = '📎 ' + file.name;
        var drop = document.createElement('button');
        drop.type = 'button';
        drop.setAttribute('aria-label', 'Remove ' + file.name);
        drop.textContent = '✕';
        drop.addEventListener('click', function () {
          attached.splice(index, 1);
          drawAttached();
        });
        chip.appendChild(drop);
        tray.appendChild(chip);
      });
    }

    var picker = wrap.querySelector('[data-attach]');
    if (picker) {
      picker.addEventListener('change', function () {
        Array.prototype.slice.call(picker.files || []).forEach(function (file) {
          if (attached.length < 4) attached.push(file);
        });
        picker.value = '';
        drawAttached();
      });
    }

    function send(question) {
      if (asking || (!question && !attached.length)) return;
      asking = true;
      var going = attached.slice();
      attached = [];
      drawAttached();
      line('you', words(question) + going.map(function (file) {
        var chip = document.createElement('span');
        chip.className = 'chat-file';
        chip.textContent = '📎 ' + file.name;
        return chip.outerHTML;
      }).join(''));
      var waiting = line('assistant thinking', '<p class="muted">' +
        (going.length ? 'Reading what you attached…' : 'Reading the project…') + '</p>');

      // A question with a file goes up as a form; one without stays JSON.
      var body, headers;
      if (going.length) {
        body = new FormData();
        body.append('question', question);
        if (chat.dataset.thread) body.append('thread_id', chat.dataset.thread);
        going.forEach(function (file) { body.append('files', file); });
        headers = { Accept: 'application/json' };
      } else {
        body = JSON.stringify({ question: question, thread_id: chat.dataset.thread || null });
        headers = { 'Content-Type': 'application/json', Accept: 'application/json' };
      }

      fetch(chat.dataset.ask, {
        method: 'POST',
        credentials: 'same-origin',
        headers: headers,
        // The conversation lives on the server now, so what goes up is which
        // thread this belongs to rather than a transcript the page has been
        // carrying around all afternoon.
        body: body,
      }).then(function (response) {
        return response.json().then(function (result) { return [response.ok, result]; });
      }).then(function (pair) {
        var answer = pair[1] || {};
        lastChat = answer.chat_id || null;
        if (answer.thread_id) {
          var fresh = !chat.dataset.thread;
          chat.dataset.thread = answer.thread_id;
          // The first question in a new conversation puts it in the list on the
          // left, and in the address bar, so a reload lands back in it.
          if (fresh && window.history && window.history.replaceState && chat.dataset.here) {
            window.history.replaceState({}, '', chat.dataset.here + '?thread=' + answer.thread_id);
            threadsSoon();
          }
        }
        waiting.classList.remove('thinking');
        if (!answer.ok) {
          waiting.classList.add('trouble');
          waiting.innerHTML = words(answer.error || 'That did not work');
          return;
        }
        // Drawn on the server, so the answer that arrives live and the same
        // answer read back out of the conversation tomorrow look the same.
        waiting.innerHTML = answer.html || words(answer.text);
        if (answer.used && answer.used.length) {
          var used = document.createElement('p');
          used.className = 'small muted chat-used';
          used.textContent = 'Read: ' + answer.used.join(', ');
          waiting.appendChild(used);
        }
        linksFrom(answer, waiting);
        staging(answer, waiting);
        threadsSoon();
      }).catch(function () {
        waiting.classList.remove('thinking');
        waiting.classList.add('trouble');
        waiting.innerHTML = '<p>Carmen could not be reached.</p>';
      }).then(function () {
        asking = false;
        var box = form && form.elements.question;
        if (box) { box.disabled = false; box.focus(); }
        log.scrollTop = log.scrollHeight;
      });
    }

    if (form) {
      form.addEventListener('submit', function (event) {
        event.preventDefault();
        var box = form.elements.question;
        var question = (box.value || '').trim();
        if ((!question && !attached.length) || asking) return;
        box.value = '';
        send(question);
      });

      // The box grows with the question rather than scrolling inside three
      // lines, which is what makes typing up a meeting into it bearable.
      var box = form.elements.question;
      if (box && box.tagName === 'TEXTAREA') {
        var grow = function () {
          box.style.height = 'auto';
          box.style.height = Math.min(box.scrollHeight, 240) + 'px';
        };
        box.addEventListener('input', grow);
        form.addEventListener('submit', function () {
          window.setTimeout(function () { box.style.height = 'auto'; }, 0);
        });
      }

      // Enter sends; shift-enter is a new line, the way every chat works.
      form.addEventListener('keydown', function (event) {
        if (event.key === 'Enter' && !event.shiftKey && event.target.name === 'question') {
          event.preventDefault();
          if (form.requestSubmit) form.requestSubmit();
          else form.dispatchEvent(new Event('submit'));
        }
      });
    }

    wrap.addEventListener('click', function (event) {
      var chip = event.target.closest('.chat-suggestion');
      if (chip) {
        event.preventDefault();
        send(chip.textContent.trim());
        return;
      }
      if (event.target.closest('[data-chat-clear]')) {
        // Starting again is a new conversation, not an erased one: what was
        // said stays on the left where somebody can go back to it.
        chat.dataset.thread = '';
        var keep = log.querySelector('.chat-line');
        log.innerHTML = '';
        if (keep) log.appendChild(keep);
      }
    });

    chat.send = send;
  }

  document.querySelectorAll('[data-carmen] [data-chat]').forEach(startCarmen);

  // The pop-up: the same chat, on every other page. It starts shut on every
  // page and opens when somebody asks for it — a chat box that reappears in the
  // corner of every tab because it was opened once is not a feature.
  (function () {
    var panel = document.getElementById('carmen-popup');
    if (!panel) return;

    var button = document.getElementById('carmen-open');

    function show(open) {
      panel.hidden = !open;
      // A class rather than a :has() rule, so hiding the launcher works the
      // same in every browser that can run the rest of this file.
      document.body.classList.toggle('carmen-open', open);
      if (button) button.setAttribute('aria-expanded', open ? 'true' : 'false');
      if (open) {
        startCarmen(panel.querySelector('[data-chat]'));
        var box = panel.querySelector('textarea[name=question]');
        if (box && !box.disabled) box.focus();
      } else if (button) {
        button.focus();
      }
    }

    if (button) button.addEventListener('click', function () { show(panel.hidden); });
    panel.addEventListener('click', function (event) {
      if (event.target.closest('[data-carmen-close]')) show(false);
    });
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && !panel.hidden) show(false);
    });
  })();

  // --- moving a row up or down ---------------------------------------------
  // Minuted items and the attendance roster both keep an order that means
  // something — an item's number is its position, and the roster's order is the
  // order the exported minutes list people in. Loading the page again to show
  // two rows swapped loses where you were reading, so the row moves where it
  // stands.

  (function () {
    function listOf(form) {
      return form.closest('[data-live-list]');
    }

    function prefixes(list) {
      // Every item row carries a hidden edit row behind it, so a list says
      // which rows travel together rather than the code assuming one each.
      return (list.getAttribute('data-live-list') || 'item').split(',');
    }

    function ends(list) {
      // ▲ on the first row and ▼ on the last have nothing to do, so they are
      // off. The page renders them that way — this only keeps it true after a
      // move, when the server has not been asked for a new page.
      var lead = prefixes(list)[0];
      var rows = list.querySelectorAll('tr[id^="' + lead + '-"]');
      rows.forEach(function (row, index) {
        var up = row.querySelector('[data-move="up"]');
        var down = row.querySelector('[data-move="down"]');
        if (up) up.disabled = index === 0;
        if (down) down.disabled = index === rows.length - 1;
      });
    }

    function reorder(list, order) {
      // Laid out in the order the server gave back rather than by swapping two
      // siblings: the order and any numbers are positional, and guessing at
      // them here is how a page ends up disagreeing with the database.
      var carried = prefixes(list);
      order.forEach(function (line) {
        carried.forEach(function (prefix) {
          var row = document.getElementById(prefix + '-' + line.id);
          if (row) list.appendChild(row);
        });
        var cell = list.querySelector('#' + carried[0] + '-' + line.id + ' [data-ref]');
        if (cell && line.ref !== undefined) cell.textContent = line.ref || '—';
      });
    }

    document.addEventListener('submit', function (event) {
      var form = event.target.closest('form[data-live-move]');
      if (!form || !window.fetch) return;
      var list = listOf(form);
      if (!list) return;

      event.preventDefault();
      var row = form.closest('tr');
      var moving = form.querySelectorAll('button');
      moving.forEach(function (b) { b.disabled = true; });

      fetch(form.action, {
        method: 'POST', body: new FormData(form),
        headers: { Accept: 'application/json' }, credentials: 'same-origin',
      }).then(function (r) { return r.json().then(function (body) { return [r.ok, body]; }); })
        .then(function (answer) {
          if (!answer[0]) {
            say((answer[1] && answer[1].error) || 'That row did not move');
            ends(list);
            return;
          }
          reorder(list, answer[1].order || []);
          row.classList.add('just-moved');
          window.setTimeout(function () { row.classList.remove('just-moved'); }, 700);
          ends(list);
          window.dispatchEvent(new Event('pm:saved'));
        }).catch(function () { form.submit(); });
    });
  })();

  // --- staffing a week -----------------------------------------------------
  //
  // The number of engineers on a trade in a week is the one figure on the
  // resources tab somebody sets rather than reads. It saves as it is typed —
  // after a pause, so a three-key number is one save and not three — and the
  // week's own total comes back with the answer, because the total is the sum
  // of its trades and typing in one column moves it.
  //
  // The hours never change. Setting a week short is a decision about who is
  // available, not about what the work is worth, so what moves is the load
  // each of those engineers is carrying — which the box says on hover.

  (function () {
    var waiting = {};

    function mark(box, state) {
      ['saving', 'saved', 'trouble'].forEach(function (word) {
        box.classList.toggle(word, word === state);
      });
      if (state === 'saved') {
        window.setTimeout(function () { box.classList.remove('saved'); }, 1200);
      }
    }

    function redraw(row, week) {
      if (!row || !week) return;
      var total = row.querySelector('[data-week-people]');
      if (total) total.textContent = week.people;
      var asked = row.querySelector('[data-week-wanted]');
      if (asked) {
        asked.textContent = 'of ' + week.wanted;
        asked.hidden = !week.by_hand;
      }
      row.querySelectorAll('.heads').forEach(function (box) {
        var cell = (week.trades || {})[box.dataset.trade];
        if (!cell) return;
        box.classList.toggle('by-hand', !!cell.by_hand);
        box.dataset.wanted = cell.wanted;
        box.title = cell.each_hours + ' h each — the plan asks for ' + cell.wanted;
        // Only rewrite the value when it is not the box being typed in, or a
        // number being edited would jump under the cursor.
        if (document.activeElement !== box) box.value = cell.people;
      });
    }

    function save(box) {
      var row = box.closest('tr');
      var body = new FormData();
      body.append('week', box.dataset.week);
      body.append('trade_id', box.dataset.trade);
      body.append('engineers', box.value);
      body.append('wanted', box.dataset.wanted || '');
      mark(box, 'saving');

      fetch(box.dataset.staff, {
        method: 'POST', body: body,
        headers: { Accept: 'application/json' }, credentials: 'same-origin',
      }).then(function (r) { return r.json().then(function (data) { return [r.ok, data]; }); })
        .then(function (answer) {
          if (!answer[0] || !answer[1].ok) {
            mark(box, 'trouble');
            return;
          }
          mark(box, 'saved');
          redraw(row, answer[1].week);
          var peak = document.querySelector('[data-peak-people]');
          if (peak) peak.textContent = answer[1].peak_people;
          var mean = document.querySelector('[data-average-people]');
          if (mean) mean.textContent = answer[1].average_people;
          window.dispatchEvent(new Event('pm:saved'));
        }).catch(function () { mark(box, 'trouble'); });
    }

    function later(box) {
      var key = box.dataset.week + ':' + box.dataset.trade;
      window.clearTimeout(waiting[key]);
      waiting[key] = window.setTimeout(function () { save(box); }, 500);
    }

    document.addEventListener('input', function (event) {
      if (event.target.classList && event.target.classList.contains('heads')) later(event.target);
    });
    // Leaving the box, or pressing Enter, saves at once rather than waiting out
    // the pause — somebody who has moved on has finished with it.
    document.addEventListener('change', function (event) {
      if (!event.target.classList || !event.target.classList.contains('heads')) return;
      var key = event.target.dataset.week + ':' + event.target.dataset.trade;
      window.clearTimeout(waiting[key]);
      save(event.target);
    });
    document.addEventListener('keydown', function (event) {
      if (event.key !== 'Enter' || !event.target.classList) return;
      if (!event.target.classList.contains('heads')) return;
      event.preventDefault();
      event.target.blur();
    });
  })();

  // --- the register --------------------------------------------------------
  //
  // Two things: the number a document is about to be given, shown as the
  // deliverable and the kind are chosen rather than after the fact, and the
  // title and status edited where they are read.
  //
  // Seeing the number before pressing the button is the whole point of having
  // a convention. A number produced by a rule nobody can watch working is just
  // a number somebody has to check.

  (function () {
    var form = document.getElementById('raise-document');
    if (!form) return;
    var box = document.getElementById('next-number');
    if (!box) return;
    var touched = false;
    var asking = null;

    // Somebody who types their own number has a reason — a document that
    // already went out under one. Stop rewriting it from that point on.
    box.addEventListener('input', function () { touched = true; });

    function ask() {
      if (touched) return;
      var task = form.elements.task_id;
      var kind = form.elements.kind_id;
      if (!task || !kind || !task.value || !kind.value) { box.value = ''; return; }

      var query = new URLSearchParams({ task_id: task.value, kind_id: kind.value });
      form.querySelectorAll('input[type=checkbox][name^=trade_]:checked').forEach(function (tick) {
        query.append('trade_ids', tick.name.slice('trade_'.length));
      });

      if (asking) asking.abort();
      asking = new AbortController();
      fetch(form.dataset.numbers + '?' + query.toString(),
            { credentials: 'same-origin', signal: asking.signal })
        .then(function (r) { return r.json(); })
        .then(function (answer) { if (!touched) box.value = answer.number || ''; })
        .catch(function () { /* the box simply stays empty until it is asked again */ });
    }

    form.addEventListener('change', function (event) {
      if (event.target.matches('[data-number-part], input[name^=trade_]')) ask();
    });
    ask();
  })();

  // A document's title and status, edited in the row. The same shape as the
  // progress cells: click, change, saved — with the number and the issue date
  // coming back, because issuing something stamps the day it went out.
  (function () {
    function close(cell, html) { cell.innerHTML = html; }

    document.addEventListener('click', function (event) {
      var link = event.target.closest('a.cell-open[data-doc]');
      if (!link) return;
      event.preventDefault();

      var template = document.getElementById('doc-' + link.dataset.doc);
      if (!template) return;
      var cell = link.parentNode;
      var was = cell.innerHTML;
      var control = template.content.firstElementChild.cloneNode(true);
      control.value = link.dataset.value || '';

      cell.innerHTML = '';
      cell.appendChild(control);
      control.focus({ preventScroll: true });

      function give_up() { close(cell, was); }

      control.addEventListener('keydown', function (key) {
        if (key.key === 'Escape') give_up();
        if (key.key === 'Enter' && control.tagName !== 'SELECT') { key.preventDefault(); control.blur(); }
      });

      var saving = false;
      function save() {
        if (saving) return;
        saving = true;
        var body = new FormData();
        body.append('field', link.dataset.doc);
        body.append('value', control.value);
        fetch(link.dataset.action, {
          method: 'POST', body: body,
          headers: { Accept: 'application/json' }, credentials: 'same-origin',
        }).then(function (r) { return r.json().then(function (d) { return [r.ok, d]; }); })
          .then(function (answer) {
            if (!answer[0] || !answer[1].ok) {
              give_up();
              if (answer[1] && answer[1].trouble) window.alert(answer[1].trouble);
              return;
            }
            var row = cell.closest('tr');
            var made = answer[1].document;
            close(cell, was);
            var again = cell.querySelector('[data-field], [data-status]');
            if (again && link.dataset.doc === 'title') again.textContent = made.title;
            if (again && link.dataset.doc === 'status') {
              var pill = again.querySelector('.badge') || again;
              pill.textContent = made.status_name;
            }
            var mark = cell.querySelector('a.cell-open');
            if (mark) mark.dataset.value = link.dataset.doc === 'title' ? made.title : made.status;
            // Issuing something stamps the day it went out, so the date beside
            // it changes without anybody having typed a date.
            var when = row && row.querySelector('[data-issued]');
            if (when) when.textContent = made.issued_date || made.planned_date || '—';
            cell.classList.add('cell-saved');
            window.setTimeout(function () { cell.classList.remove('cell-saved'); }, 1400);
            window.dispatchEvent(new Event('pm:saved'));
          }).catch(function () { give_up(); });
      }

      control.addEventListener('change', save);
      control.addEventListener('blur', function () {
        if (!saving) window.setTimeout(save, 0);
      });
    });
  })();

  // --- confirmations -------------------------------------------------------
  // Destructive buttons ask once before submitting.

  document.addEventListener('submit', function (event) {
    var message = event.target.getAttribute('data-confirm');
    if (message && !window.confirm(message)) event.preventDefault();
  });
})();
