/* Specs Writer, one project's page: one step in view at a time.

   Loaded (synchronously) straight after the opening tag of the page's
   [data-spec-flow] wrapper, so the wrapper is marked before anything under it
   is drawn and the page never shows every step first. The class it adds,
   spec-flow-js, is what hides the steps not in view (spec-steps.css); without
   JavaScript nothing is hidden and the page reads top to bottom as before.

   The step in view comes from the address (#step-elements and so on, which the
   server's "Save and next" redirects and other pages link to), or else from
   the wrapper's data-first: Project for a new project, otherwise the first
   step not done. The step bar and the Back links switch it without a reload
   or a jump, and each switch is a history entry, so the browser's Back goes
   to the step before. Every field stays in the page, only hidden, so the one
   form that spans steps 1 to 3 still saves them all. */
(function () {
  "use strict";

  var STEPS = ["project", "elements", "questions", "sections"];
  var me = document.currentScript;
  var flow = me && me.parentNode && me.parentNode.hasAttribute &&
             me.parentNode.hasAttribute("data-spec-flow") ? me.parentNode
             : document.querySelector("[data-spec-flow]");
  if (!flow) return;

  function fromHash() {
    var m = /^#step-([a-z]+)$/.exec(location.hash || "");
    return m && STEPS.indexOf(m[1]) >= 0 ? m[1] : null;
  }

  function first() {
    var step = flow.getAttribute("data-first");
    return STEPS.indexOf(step) >= 0 ? step : "project";
  }

  function show(step) {
    flow.setAttribute("data-current", step);
    var links = flow.querySelectorAll("[data-step-link]");
    for (var i = 0; i < links.length; i++) {
      if (links[i].getAttribute("data-step-link") === step) links[i].setAttribute("aria-current", "step");
      else links[i].removeAttribute("aria-current");
    }
  }

  // The step bar back in sight when a switch is made from further down the
  // page (the Back button at the foot of a long step); left alone otherwise.
  function barInSight() {
    var bar = flow.querySelector(".spec-steps");
    var top = document.querySelector(".topbar");
    var under = top ? top.getBoundingClientRect().bottom : 0;
    if (bar && bar.getBoundingClientRect().top < under) window.scrollTo(0, 0);
  }

  function go(step) {
    if (flow.getAttribute("data-current") === step) return;
    show(step);
    try { history.pushState(null, "", "#step-" + step); } catch (e) { /* file:// and the like */ }
    barInSight();
  }

  flow.classList.add("spec-flow-js");
  show(fromHash() || first());

  // The bar's links and the Back links: href="#step-...", switched in place.
  flow.addEventListener("click", function (e) {
    var link = e.target.closest && e.target.closest('a[href^="#step-"]');
    if (!link || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    var step = link.getAttribute("href").slice(6);
    if (STEPS.indexOf(step) < 0) return;
    e.preventDefault();
    go(step);
  });

  function fromAddress() { show(fromHash() || first()); }
  window.addEventListener("popstate", fromAddress);
  window.addEventListener("hashchange", fromAddress);

  // A field the browser will not submit (the project name left empty, say)
  // may be on a step out of view: that step is brought up so it can be seen.
  document.addEventListener("invalid", function (e) {
    var panel = e.target.closest && e.target.closest("[data-step]");
    if (panel && flow.contains(panel)) go(panel.getAttribute("data-step"));
  }, true);

  // Opened on a step by its address, the browser scrolls down to that step's
  // card: the page is put back at the top, with the bar and the messages in view.
  function toTop() { if (fromHash()) window.scrollTo(0, 0); }

  document.addEventListener("DOMContentLoaded", function () {
    show(flow.getAttribute("data-current") || first());

    // What the last save said (which sections went in, and why) sits just
    // under the step bar, above whichever step is in view.
    var bar = flow.querySelector(".spec-steps");
    var notes = document.querySelector(".flashes");
    if (bar && notes && !flow.contains(notes)) bar.parentNode.insertBefore(notes, bar.nextSibling);

    // Tick all the project's sections, or none.
    var all = flow.querySelector("[data-tick-all]");
    var remove = document.getElementById("sections-remove");
    function ticks() {
      return remove ? Array.prototype.filter.call(remove.elements, function (el) {
        return el.name === "row_id" && el.type === "checkbox";
      }) : [];
    }
    if (all) {
      all.addEventListener("change", function () {
        ticks().forEach(function (box) { box.checked = all.checked; });
      });
    }

    // Taking sections out asks first, naming how many. The ticks sit in the
    // table and join the form by its id (form="sections-remove"), so they are
    // counted through form.elements: a search inside the form would miss them.
    if (remove) {
      remove.addEventListener("submit", function (e) {
        var one = e.submitter && e.submitter.getAttribute("data-take-one");
        var said;
        if (one) {
          said = "Take section " + one + " out of this project? Any amendments made to it here go with it.";
        } else {
          var n = ticks().filter(function (box) { return box.checked; }).length;
          if (!n) {
            e.preventDefault();
            window.alert("Tick the sections to take out first.");
            return;
          }
          said = "Take " + n + " section" + (n === 1 ? "" : "s") + " out of this project? Any amendments made to " +
                 (n === 1 ? "it" : "them") + " here go with " + (n === 1 ? "it" : "them") + ".";
        }
        if (!window.confirm(said)) e.preventDefault();
      });
    }
    toTop();
  });
  window.addEventListener("load", toTop);
})();
