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

  document.addEventListener('click', function (event) {
    if (event.target.closest('[data-print]')) window.print();
  });

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
        var task = form.dataset.itemId;
        closeCell(form, cellLink(form, result.progress_html), '');
        replaceHtml('status-' + task, result.status_html);
        replaceHtml('variance-' + task, result.variance_html);
        replaceHtml('actions-' + task, result.actions_html);
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
      var status = document.getElementById('status-' + id);
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

  // --- confirmations -------------------------------------------------------
  // Destructive buttons ask once before submitting.

  document.addEventListener('submit', function (event) {
    var message = event.target.getAttribute('data-confirm');
    if (message && !window.confirm(message)) event.preventDefault();
  });
})();
