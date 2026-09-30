// The check page: one group of items in view at a time, as the project page
// does its steps (spec-steps.js).
//
// Loaded (synchronously) straight after the opening tag of the [data-check-flow]
// wrapper, so the wrapper is marked before the groups under it are drawn. The
// class it adds, spec-check-js, is what hides the groups not in view (the rules
// are written into the page, one per group); without JavaScript nothing is
// hidden and every group shows, one under another.
//
// The group in view comes from the address: #group-<key> (where Keep all and
// Remove all come back to), #language, or #item-<key> (where Keep, Amend and
// Remove come back to: the group that holds that item, once the page is read).
// Otherwise it is the first group with anything open. The bar and the Back and
// Next buttons switch groups without a reload; each switch is a history entry.
(function () {
  'use strict';

  var me = document.currentScript;
  var flow = me && me.parentNode && me.parentNode.hasAttribute &&
             me.parentNode.hasAttribute('data-check-flow') ? me.parentNode
             : document.querySelector('[data-check-flow]');
  if (!flow) return;
  var GROUPS = (flow.getAttribute('data-groups') || '').split(/\s+/).filter(Boolean);
  if (!GROUPS.length) return;

  // The group the address names: a key, '' while an item's group is not known
  // yet (the page is still being read), or null when it names none.
  function fromHash(ready) {
    var hash = decodeURIComponent(location.hash || '');
    var m = /^#group-([a-z_]+)$/.exec(hash);
    if (m && GROUPS.indexOf(m[1]) >= 0) return m[1];
    if (hash === '#language' && GROUPS.indexOf('language') >= 0) return 'language';
    if (/^#item-[\w-]+$/.test(hash)) {
      var item = document.getElementById(hash.slice(1));
      var panel = item && item.closest('[data-group]');
      if (panel && flow.contains(panel)) return panel.getAttribute('data-group');
      return ready ? null : '';
    }
    return null;
  }

  function first() {
    var g = flow.getAttribute('data-first');
    return GROUPS.indexOf(g) >= 0 ? g : GROUPS[0];
  }

  function show(group) {
    flow.setAttribute('data-current', group);
    var links = flow.querySelectorAll('[data-group-link]');
    for (var i = 0; i < links.length; i++) {
      if (links[i].getAttribute('data-group-link') === group) {
        links[i].setAttribute('aria-current', 'true');
        strip(links[i]);
      } else links[i].removeAttribute('aria-current');
    }
  }

  // On a phone the bar is one line that scrolls sideways: the group in view is kept in it.
  function strip(link) {
    var bar = link.parentNode;
    if (!bar || bar.scrollWidth <= bar.clientWidth) return;
    var left = link.offsetLeft - bar.offsetLeft, right = left + link.offsetWidth;
    if (left < bar.scrollLeft + 16) bar.scrollLeft = Math.max(0, left - 16);
    else if (right > bar.scrollLeft + bar.clientWidth - 16) bar.scrollLeft = right - bar.clientWidth + 16;
  }

  function under() {
    var top = document.querySelector('.topbar');
    var pos = top && window.getComputedStyle(top).position;
    return top && (pos === 'sticky' || pos === 'fixed') ? top.getBoundingClientRect().bottom : 0;
  }

  // The bar back in sight after a switch made further down (Next at the foot
  // of a long group); left alone when it is already in view.
  function barInSight() {
    var bar = flow.querySelector('.spec-groups');
    if (!bar) return;
    var top = bar.getBoundingClientRect().top;
    if (top < under()) window.scrollTo(0, Math.max(0, window.pageYOffset + top - under() - 8));
  }

  function go(group) {
    if (flow.getAttribute('data-current') === group) { barInSight(); return; }
    show(group);
    try { history.pushState(null, '', '#group-' + group); } catch (e) { /* file:// and the like */ }
    barInSight();
  }

  flow.classList.add('spec-check-js');
  var early = fromHash(false);
  show(early === null ? first() : early);

  // The bar's links and the Back and Next buttons: href="#group-...", switched in place.
  document.addEventListener('click', function (e) {
    var link = e.target.closest && e.target.closest('a[href^="#group-"], a[href="#language"]');
    if (!link || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    var href = link.getAttribute('href');
    var group = href === '#language' ? 'language' : href.slice(7);
    if (GROUPS.indexOf(group) < 0) return;
    e.preventDefault();
    go(group);
  });

  // An item named by the address: its group, and the item itself in view
  // (or the settled list it is folded into).
  function toItem() {
    var hash = location.hash || '';
    if (!/^#item-[\w-]+$/.test(hash)) return;
    var item = document.getElementById(hash.slice(1));
    if (!item) return;
    var shut = item.closest('details:not([open])');
    var target = shut || item;
    var y = target.getBoundingClientRect().top + window.pageYOffset - under() - 12;
    window.scrollTo(0, Math.max(0, y));
  }

  function fromAddress(ready) {
    var g = fromHash(ready);
    show(g === null || g === '' ? first() : g);
  }
  window.addEventListener('popstate', function () { fromAddress(true); });
  window.addEventListener('hashchange', function () {
    fromAddress(true);
    if (/^#item-/.test(location.hash)) toItem(); else toTop();
  });

  // A group's address: the page from the top, with the messages and the bar in view.
  function toTop() {
    var g = fromHash(true);
    if (g && !/^#item-/.test(location.hash)) window.scrollTo(0, 0);
  }

  // A field the browser will not submit, in a group out of view: that group.
  document.addEventListener('invalid', function (e) {
    var panel = e.target.closest && e.target.closest('[data-group]');
    if (panel && flow.contains(panel)) go(panel.getAttribute('data-group'));
  }, true);

  document.addEventListener('DOMContentLoaded', function () {
    fromAddress(true);
    toItem();
    toTop();
  });
  window.addEventListener('load', function () {
    if (/^#item-/.test(location.hash)) { toItem(); return; }
    toTop();
    window.requestAnimationFrame(function () { setTimeout(toTop, 0); });
  });
})();

// Amend opens the paragraph's box in place instead of reloading the page with
// ?amend=<key>, and Cancel closes it again. Without this file the links do the
// same by going to the server.
(function () {
  function box(key) { return document.getElementById('amend-' + key); }

  function open(key) {
    var form = box(key);
    if (!form) return false;
    var details = form.closest('details');
    if (details) details.open = true;
    form.hidden = false;
    var first = form.querySelector('textarea');
    if (first) {
      first.focus();
      first.setSelectionRange(first.value.length, first.value.length);
    }
    return true;
  }

  document.addEventListener('click', function (event) {
    var link = event.target.closest('.spec-amend-open, .spec-amend-cancel');
    if (!link) return;
    var key = link.getAttribute('data-key');
    var form = box(key);
    if (!form) return;
    event.preventDefault();
    if (link.classList.contains('spec-amend-cancel')) {
      form.hidden = true;
      form.reset();
      var opener = form.parentNode.querySelector('.spec-amend-open');
      if (opener) opener.focus();
    } else if (form.hidden) {
      open(key);
    } else {
      form.hidden = true;
    }
  });

  // A box that grows with its text, so a long paragraph is read whole.
  function fit(area) {
    area.style.height = 'auto';
    area.style.height = (area.scrollHeight + 2) + 'px';
  }
  document.addEventListener('input', function (event) {
    if (event.target.matches('.spec-amend-text')) fit(event.target);
  });
  new MutationObserver(function (changes) {
    changes.forEach(function (c) {
      if (c.attributeName === 'hidden' && !c.target.hidden) {
        c.target.querySelectorAll('.spec-amend-text').forEach(fit);
      }
    });
  }).observe(document.body, { attributes: true, subtree: true, attributeFilter: ['hidden'] });
  // Loaded at the top of the check (for its groups, below), before the boxes exist.
  function fitOpen() { document.querySelectorAll('.spec-amend:not([hidden]) .spec-amend-text').forEach(fit); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fitOpen);
  else fitOpen();
})();
