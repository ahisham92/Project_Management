/* Specs Writer: a bar with a percentage whenever something loads.

   Forms that send files go by XMLHttpRequest, so the bar shows how much of
   the upload has gone; the server's answer (a redirect, which it turns into
   {"go": url} when asked with the X-Specs-Progress header) is then followed,
   so its messages show as they always have. The library file load
   (form[data-progress-begin]) is sent to that address instead and then read
   in a few sections per call, the bar showing sections read of the total.

   Downloads that take time (issuing, a section's .docx or PDF, the library
   file) are fetched: while the server builds the file the bar says what it is
   doing, with no percentage; once the file comes, the percentage is of its
   Content-Length. A download the server holds back (a redirect to the check)
   goes there instead.

   Without this file (or without fetch) every form and link works as before. */
(function () {
  "use strict";

  if (!window.XMLHttpRequest || !window.FormData) return;
  var HEADER = "X-Specs-Progress";

  // --- the bar --------------------------------------------------------------------

  var box, whatEl, pcEl, fillEl, detailEl, closeEl, ticking = null, hideTimer = null;

  function build() {
    if (box) return;
    box = document.createElement("div");
    box.className = "spec-progress";
    box.setAttribute("role", "status");
    box.setAttribute("aria-live", "polite");
    box.innerHTML =
      '<div class="spec-progress-head"><span class="spec-progress-what"></span>' +
      '<span class="spec-progress-pc"></span>' +
      '<button type="button" class="spec-progress-close" aria-label="Close" hidden>&times;</button></div>' +
      '<div class="spec-progress-track" role="progressbar" aria-valuemin="0" aria-valuemax="100">' +
      '<div class="spec-progress-fill"></div></div>' +
      '<div class="spec-progress-detail"></div>';
    whatEl = box.querySelector(".spec-progress-what");
    pcEl = box.querySelector(".spec-progress-pc");
    fillEl = box.querySelector(".spec-progress-fill");
    detailEl = box.querySelector(".spec-progress-detail");
    closeEl = box.querySelector(".spec-progress-close");
    closeEl.addEventListener("click", hide);
    document.body.appendChild(box);
  }

  // fraction: 0..1, or null while the server works and nothing can be measured.
  function show(what, fraction, detail) {
    build();
    clearTimeout(hideTimer);
    box.hidden = false;
    box.classList.remove("spec-progress-failed", "spec-progress-done");
    closeEl.hidden = true;
    whatEl.textContent = what;
    detailEl.textContent = detail || "";
    var track = fillEl.parentNode;
    if (fraction === null || fraction === undefined || isNaN(fraction)) {
      box.classList.add("spec-progress-busy");
      pcEl.textContent = "";
      fillEl.style.width = "";
      track.removeAttribute("aria-valuenow");
    } else {
      var pc = Math.max(0, Math.min(100, Math.floor(fraction * 100)));
      box.classList.remove("spec-progress-busy");
      pcEl.textContent = pc + "%";
      fillEl.style.width = pc + "%";
      track.setAttribute("aria-valuenow", String(pc));
    }
  }

  function fail(message) {
    stopTicking();
    build();
    show(message, null, "");
    box.classList.remove("spec-progress-busy");
    box.classList.add("spec-progress-failed");
    box.setAttribute("role", "alert");
    closeEl.hidden = false;
    fillEl.style.width = "100%";
    release();
  }

  function finished(message) {
    stopTicking();
    show(message, 1, "");
    box.classList.add("spec-progress-done");
    closeEl.hidden = false;
    release();
    hideTimer = setTimeout(hide, 4000);
  }

  function hide() {
    stopTicking();
    if (box) { box.hidden = true; box.setAttribute("role", "status"); }
  }

  // While the server works: what it is doing, and for how long so far.
  function busy(what) {
    stopTicking();
    var started = Date.now();
    show(what, null, "");
    ticking = setInterval(function () {
      var s = Math.round((Date.now() - started) / 1000);
      if (s >= 2) detailEl.textContent = s + " s";
    }, 1000);
  }
  function stopTicking() { if (ticking) { clearInterval(ticking); ticking = null; } }

  function size(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return Math.round(bytes / 1024) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  }

  // --- going where the server says -----------------------------------------------

  function go(url) {
    var to = new URL(url, location.href);
    // The same page with another #: the browser would only scroll, so it is
    // loaded again, for its messages.
    if (to.pathname === location.pathname && to.search === location.search) {
      try { history.replaceState(null, "", to.href); } catch (e) { /* ignore */ }
      location.reload();
    } else {
      location.assign(to.href);
    }
  }

  function json(text) {
    try { return JSON.parse(text); } catch (e) { return null; }
  }

  // The buttons of the form in use, held while it is sent.
  var held = [];
  function hold(form) {
    held = Array.prototype.filter.call(form.elements, function (el) {
      return (el.type === "submit" || el.tagName === "BUTTON") && !el.disabled;
    });
    held.forEach(function (el) { el.disabled = true; });
    form.setAttribute("data-sending", "");
  }
  function release() {
    held.forEach(function (el) { el.disabled = false; });
    held = [];
    var sending = document.querySelectorAll("form[data-sending]");
    for (var i = 0; i < sending.length; i++) sending[i].removeAttribute("data-sending");
  }

  // --- forms that send files -----------------------------------------------------

  function chosenFiles(form) {
    var names = [];
    Array.prototype.forEach.call(form.elements, function (el) {
      if (el.type === "file" && !el.disabled && el.files) {
        for (var i = 0; i < el.files.length; i++) names.push(el.files[i].name);
      }
    });
    return names;
  }

  function formData(form, submitter) {
    var data;
    try { data = new FormData(form, submitter || undefined); }
    catch (e) {
      data = new FormData(form);
      if (submitter && submitter.name) data.append(submitter.name, submitter.value);
    }
    return data;
  }

  function send(url, data, names, then) {
    var xhr = new XMLHttpRequest();
    var what = names.length === 1 ? "Sending " + names[0] : "Sending " + names.length + " files";
    xhr.open("POST", url);
    xhr.setRequestHeader(HEADER, "1");
    xhr.upload.addEventListener("progress", function (e) {
      if (e.lengthComputable) show(what, e.loaded / e.total, size(e.loaded) + " of " + size(e.total));
    });
    xhr.upload.addEventListener("load", function () { then.sent(); });
    xhr.addEventListener("load", function () {
      stopTicking();
      var answer = /json/.test(xhr.getResponseHeader("Content-Type") || "") ? json(xhr.responseText) : null;
      if (xhr.status >= 200 && xhr.status < 300 && answer) return then.answer(answer);
      if (xhr.status >= 200 && xhr.status < 300 && xhr.responseURL) return go(xhr.responseURL);
      fail(xhr.status === 413 ? "That file is too big to send here."
           : "The server could not take it (" + xhr.status + "). Nothing was changed by this page; try again.");
    });
    xhr.addEventListener("error", function () {
      fail("The connection dropped while sending. Check the network and try again.");
    });
    show(what, 0, "");
    xhr.send(data);
  }

  // The library file: sent, then read in a few sections per call.
  function stepLoad(stepUrl, total) {
    var tries = 0;
    function next() {
      var xhr = new XMLHttpRequest();
      xhr.open("POST", stepUrl);
      xhr.setRequestHeader(HEADER, "1");
      xhr.addEventListener("load", function () {
        var answer = json(xhr.responseText);
        if (xhr.status >= 200 && xhr.status < 300 && answer) {
          tries = 0;
          if (answer.total) {
            show("Loading the library", answer.done / answer.total,
                 answer.done + " of " + answer.total + " sections read" +
                 (answer.finished ? ". Done." : ""));
          }
          if (answer.go) return go(answer.go);
          return next();
        }
        fail("Loading stopped: the server answered " + xhr.status +
             ". Sections read so far are in the library; load the file again to finish.");
      });
      xhr.addEventListener("error", function () {
        if (++tries <= 2) return setTimeout(next, 1500 * tries);
        fail("The connection dropped while loading. Sections read so far are in the library; load the file again to finish.");
      });
      xhr.send();
    }
    show("Loading the library", 0, "0 of " + total + " sections read");
    next();
  }

  // Listened for on window, after the page's own submit handlers (a Remove that
  // asks first, say), so a form they stopped is left alone.
  window.addEventListener("submit", function (e) {
    var form = e.target;
    if (e.defaultPrevented || !form || form.tagName !== "FORM") return;
    if ((form.getAttribute("method") || "get").toLowerCase() !== "post") return;
    if (form.hasAttribute("data-sending")) { e.preventDefault(); return; }
    var names = chosenFiles(form);
    if (!names.length) return;
    var submitter = e.submitter || null;
    var url = (submitter && submitter.getAttribute("formaction")) || form.action;
    var begin = form.getAttribute("data-progress-begin");
    e.preventDefault();
    var data = formData(form, submitter);
    hold(form);
    if (begin) {
      send(begin, data, names, {
        sent: function () { busy("Checking the library file"); },
        answer: function (a) {
          if (a.step) return stepLoad(a.step, a.total || 0);
          if (a.go) return go(a.go);
          fail("The server did not say what to do next. Try again.");
        }
      });
      return;
    }
    send(url, data, names, {
      sent: function () { busy(names.length === 1 ? "Reading " + names[0] : "Reading " + names.length + " files"); },
      answer: function (a) {
        if (a.go) return go(a.go);
        fail("The server did not say what to do next. Try again.");
      }
    });
  });

  // --- downloads ----------------------------------------------------------------

  var DOWNLOADS = /^\/specs\/(sets\/\d+\/export|sets\/\d+\/sections\/\d+\/docx|library\/\d+\/docx|library\/file|template)$/;

  function building(url, link) {
    if (link.getAttribute("data-download")) return link.getAttribute("data-download");
    var fmt = url.searchParams.get("fmt");
    var whole = /\/export$/.test(url.pathname);
    if (/\/library\/file$/.test(url.pathname)) return "Packing the library file…";
    if (/\/template$/.test(url.pathname)) return "Fetching the template…";
    if (fmt === "pdf") return whole ? "Building the PDF of every section…" : "Building the PDF…";
    if (fmt === "tracked") return whole ? "Writing every section with tracked changes…" : "Writing the tracked changes…";
    return whole ? "Writing every section as .docx…" : "Writing the .docx…";
  }

  function fileName(disposition, fallback) {
    var m = /filename\*\s*=\s*UTF-8''([^;]+)/i.exec(disposition);
    if (m) { try { return decodeURIComponent(m[1].replace(/"/g, "")); } catch (e) { /* below */ } }
    m = /filename\s*=\s*"([^"]*)"/i.exec(disposition) || /filename\s*=\s*([^;]+)/i.exec(disposition);
    return m ? m[1].trim() : fallback;
  }

  function save(blob, name) {
    var href = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = href;
    a.download = name;
    a.style.display = "none";
    document.body.appendChild(a);
    a.click();
    setTimeout(function () { URL.revokeObjectURL(href); a.remove(); }, 60000);
  }

  var fetching = false;

  function download(url, link) {
    if (fetching) return;
    fetching = true;
    busy(building(url, link));
    fetch(url.href, { credentials: "same-origin", headers: (function () { var h = {}; h[HEADER] = "1"; return h; })() })
      .then(function (res) {
        var type = res.headers.get("Content-Type") || "";
        if (res.ok && /json/.test(type)) {
          return res.json().then(function (a) {
            if (a && a.go) { hide(); return go(a.go); }
            fail("The server did not send the file. Try again.");
          });
        }
        var disposition = res.headers.get("Content-Disposition") || "";
        if (!res.ok) return fail("The file could not be made (the server answered " + res.status + ").");
        if (!/attachment/i.test(disposition)) { hide(); location.assign(url.href); return; }
        var name = fileName(disposition, "download");
        var total = parseInt(res.headers.get("Content-Length") || "0", 10) || 0;
        stopTicking();
        var what = "Downloading " + name;
        if (!res.body || !res.body.getReader) {
          show(what, null, total ? size(total) : "");
          return res.blob().then(function (blob) { save(blob, name); finished("Downloaded " + name); });
        }
        var reader = res.body.getReader(), parts = [], got = 0;
        show(what, total ? 0 : null, total ? "0 of " + size(total) : "");
        function pump() {
          return reader.read().then(function (r) {
            if (r.done) {
              save(new Blob(parts, { type: type || "application/octet-stream" }), name);
              finished("Downloaded " + name + " (" + size(got) + ")");
              return;
            }
            parts.push(r.value);
            got += r.value.length;
            // A proxy that compresses the file makes the bytes outrun the
            // length it declared: kept under 100% until the last one.
            show(what, total ? Math.min(got / total, 0.99) : null,
                 total ? size(Math.min(got, total)) + " of " + size(total) : size(got));
            return pump();
          });
        }
        return pump();
      })
      .catch(function () {
        fail("The download was cut off. Check the network and try again.");
      })
      .then(function () { fetching = false; });
  }

  // Back to this page from the browser's memory: nothing is being sent now.
  window.addEventListener("pageshow", function (e) { if (e.persisted) { hide(); release(); fetching = false; } });

  document.addEventListener("click", function (e) {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    var link = e.target.closest && e.target.closest("a[href]");
    if (!link || link.hasAttribute("download") || link.getAttribute("aria-disabled") === "true") return;
    if (link.target && link.target !== "_self") return;
    var url;
    try { url = new URL(link.href, location.href); } catch (err) { return; }
    if (url.origin !== location.origin) return;
    if (!link.hasAttribute("data-download") && !DOWNLOADS.test(url.pathname)) return;
    if (!window.fetch || !window.URL || !URL.createObjectURL) return;
    e.preventDefault();
    download(url, link);
  });
})();
