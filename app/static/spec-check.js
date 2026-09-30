// The check page: Amend opens the paragraph's box in place instead of reloading
// the page with ?amend=<key>, and Cancel closes it again. Without this file the
// links do the same by going to the server.
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
  document.querySelectorAll('.spec-amend:not([hidden]) .spec-amend-text').forEach(fit);
})();
