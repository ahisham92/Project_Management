// The Iris phone app: your connected tools, their updates and questions, and
// the buttons to answer them. Messages are decrypted here with the key each
// tool handed this phone when it was connected.
(function () {
  "use strict";
  const ROOT = window.IRIS.root;
  const C = window.IrisCrypto;
  const $ = (id) => document.getElementById(id);

  let tools = [];
  let current = null;         // the open tool
  let lastId = 0;             // the newest message shown for it
  let readUpto = 0;           // the newest of your messages the tool has fetched
  let mine = [];              // your messages shown: { id, tick }
  let lastSide = "";          // who wrote the newest message shown
  let fastUntil = 0;          // poll every 3 s until then (you just wrote)
  let keys = null;            // its imported key, or null when this phone lacks it
  const questions = new Map(); // question id -> its list item

  // ---- small helpers -------------------------------------------------------

  async function api(path, options) {
    const opts = Object.assign({ headers: {} }, options || {});
    if (opts.json !== undefined) {
      opts.method = opts.method || "POST";
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(opts.json);
    }
    const reply = await fetch(ROOT + path, opts);
    if (reply.status === 401) { location.href = ROOT + "/"; throw new Error("Signed out."); }
    const data = await reply.json().catch(() => ({}));
    if (!reply.ok) throw new Error(data.error || "Something went wrong (" + reply.status + ").");
    return data;
  }

  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function when(seconds) {
    const d = new Date(seconds * 1000);
    const today = new Date().toDateString() === d.toDateString();
    return (today ? "" : d.toLocaleDateString([], { day: "numeric", month: "short" }) + " ") +
      d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  function keyFor(id) {
    try { return localStorage.getItem("iris.key." + id); } catch (e) { return null; }
  }

  function show(section) {
    for (const id of ["empty", "scan", "confirm", "list", "tool"]) $(id).hidden = id !== section;
    if (section !== "tool") document.body.classList.remove("in-chat");
  }

  // ---- connecting a new tool ----------------------------------------------

  // Scanning inside the app: on an iPhone the Home Screen app keeps its own
  // storage, so a code scanned with the Camera app (it opens Safari or Chrome)
  // leaves the key there, not here. Scanning here keeps it where it is used.
  let stream = null;
  let scanning = 0;

  function take(text) {
    let url;
    try { url = new URL(text.trim(), location.href); } catch (e) { return false; }
    const code = url.searchParams.get("c") || "";
    const key = new URLSearchParams(url.hash.slice(1)).get("k") || "";
    if (!code || !key) return false;
    stopScan();
    localStorage.setItem("iris.pending", JSON.stringify({ code: code, key: key, at: Date.now() }));
    pending();
    return true;
  }

  async function startScan() {
    show("scan");
    $("scan-error").textContent = "";
    $("paste-link").value = "";
    if (!navigator.mediaDevices || !window.jsQR) { $("scan-error").textContent = "This browser can't use the camera here. Paste the link instead."; return; }
    try {
      stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" }, audio: false });
    } catch (e) {
      $("scan-error").textContent = "Allow the camera for Iris to scan, or paste the link instead.";
      return;
    }
    const video = $("cam");
    video.srcObject = stream;
    await video.play().catch(() => {});
    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    const run = ++scanning;
    (function frame() {
      if (run !== scanning || !stream) return;
      if (video.readyState >= 2 && video.videoWidth) {
        const w = Math.min(640, video.videoWidth), h = Math.round(video.videoHeight * w / video.videoWidth);
        canvas.width = w; canvas.height = h;
        ctx.drawImage(video, 0, 0, w, h);
        const found = window.jsQR(ctx.getImageData(0, 0, w, h).data, w, h, { inversionAttempts: "dontInvert" });
        if (found && found.data) {
          if (take(found.data)) return;
          $("scan-error").textContent = "That code isn't a connection code. Show the code from Connect your phone.";
        }
      }
      setTimeout(frame, 200);
    })();
  }

  function stopScan() {
    scanning++;
    if (stream) for (const t of stream.getTracks()) t.stop();
    stream = null;
    $("cam").srcObject = null;
  }

  for (const b of document.querySelectorAll("[data-add]")) b.onclick = startScan;
  $("scan-cancel").onclick = () => { stopScan(); home(); };
  $("paste").onsubmit = (e) => {
    e.preventDefault();
    if (!take($("paste-link").value)) $("scan-error").textContent = "That isn't a connection link. Copy it again from Connect your phone on the PC.";
  };

  async function pending() {
    let p = null;
    try { p = JSON.parse(localStorage.getItem("iris.pending") || "null"); } catch (e) { p = null; }
    if (!p || Date.now() - p.at > 10 * 60 * 1000) { localStorage.removeItem("iris.pending"); return false; }
    show("confirm");
    $("confirm-error").textContent = "";
    try {
      const info = await api("/api/me/pair/" + encodeURIComponent(p.code));
      $("confirm-name").textContent = info.name;
      $("confirm-machine").textContent = info.machine ? "on " + info.machine : "";
    } catch (e) {
      localStorage.removeItem("iris.pending");
      $("confirm-name").textContent = "this tool";
      $("confirm-error").textContent = e.message;
      $("confirm-yes").hidden = true;
      return true;
    }
    $("confirm-yes").hidden = false;
    $("confirm-yes").onclick = async () => {
      try {
        const tool = await api("/api/me/pair", { json: { code: p.code } });
        localStorage.setItem("iris.key." + tool.id, p.key);
        localStorage.removeItem("iris.pending");
        await loadTools(tool.id);
        offerNotifications();
      } catch (e) { $("confirm-error").textContent = e.message; }
    };
    $("confirm-no").onclick = () => { localStorage.removeItem("iris.pending"); home(); };
    return true;
  }

  // ---- tools ----------------------------------------------------------------

  // The home screen: every connected tool, the one that spoke last first, with
  // what it said last and how many of its questions wait for an answer.
  async function loadTools(open) {
    tools = (await api("/api/me/tools")).tools;
    if (!tools.length) { current = null; show("empty"); return; }
    const want = open || Number(new URLSearchParams(location.search).get("tool"));
    if (want && tools.some((t) => t.id === want)) {
      history.replaceState({ tool: want }, "", ROOT + "/?tool=" + want);
      if (!current || current.id !== want) await openTool(want, true);
      return;
    }
    if (current) { current = tools.find((t) => t.id === current.id) || null; if (current) { seenLine(); return; } }
    await renderList();
    show("list");
  }

  async function renderList() {
    const list = $("tools");
    const rows = [];
    for (const t of tools) {
      const li = el("li");
      const b = el("button", "tool-row");
      b.onclick = () => go(t.id);
      const shown = t.agent || t.name;
      const mark = el("span", "tool-mark", t.agent ? t.agent[0].toUpperCase() : (t.name.match(/[A-Z0-9]/g) || [t.name[0]]).slice(0, 2).join("").toUpperCase());
      const mid = el("span", "tool-mid");
      const top = el("span", "tool-top");
      top.appendChild(el("span", "tool-row-name", t.agent ? t.agent + " · " + t.name : shown));
      if (t.latest) top.appendChild(el("span", "small muted", when(t.latest.created)));
      mid.appendChild(top);
      const line = el("span", "tool-preview small" + (t.waiting ? " waiting" : " muted"), await preview(t));
      mid.appendChild(line);
      b.appendChild(mark);
      b.appendChild(mid);
      if (t.waiting) b.appendChild(el("span", "badge", String(t.waiting)));
      b.setAttribute("aria-label", shown + (t.waiting ? ", " + t.waiting + " waiting for your answer" : ""));
      li.appendChild(b);
      rows.push(li);
    }
    list.replaceChildren(...rows);
  }

  // What the list shows under a tool's name: its latest message, decrypted here.
  async function preview(t) {
    if (t.waiting) return t.waiting === 1 ? "Waiting for your answer" : t.waiting + " questions waiting for your answer";
    const m = t.latest;
    if (!m) return (t.machine ? "On " + t.machine + ". " : "") + "Nothing yet. Write to it any time.";
    const keyText = keyFor(t.id);
    if (!keyText) return "Connected in another browser: tap Add a connection to connect it here.";
    let v;
    try { v = await C.open(await C.importKey(keyText), m.body); } catch (e) { return ""; }
    const text = m.kind === "command" ? "You pressed " + v.command : (v.text || "");
    return (m.side === "phone" && m.kind !== "command" ? "You: " : "") + text.replace(/\s+/g, " ");
  }

  function go(id) {
    history.pushState({ tool: id }, "", ROOT + "/?tool=" + id);
    openTool(id);
  }

  function home() {
    current = null;
    history.replaceState({}, "", ROOT + "/");
    loadTools().catch(() => {});
  }

  function who(t) { return (t && (t.agent || t.name)) || ""; }

  function seenLine() {
    const ago = Math.max(0, Date.now() / 1000 - current.seen);
    const seen = ago < 120 ? "online" : "last seen " + (ago < 3600 ? Math.round(ago / 60) + " min ago" : when(current.seen));
    $("tool-seen").textContent = (current.agent ? current.name + " · " : "") + seen;
  }

  async function openTool(id) {
    current = tools.find((t) => t.id === id);
    lastId = 0;
    readUpto = 0;
    mine = [];
    lastSide = "";
    lastDay = "";
    questions.clear();
    show("tool");
    document.body.classList.add("in-chat");
    fitViewport();
    $("tool-name").textContent = who(current);
    $("tool-avatar").textContent = (who(current)[0] || "?").toUpperCase();
    $("tool-machine").textContent = current.name + (current.machine ? " on " + current.machine : "");
    seenLine();
    $("notify").value = current.notify;
    $("feed").textContent = "";
    const keyText = keyFor(id);
    keys = keyText ? await C.importKey(keyText) : null;
    chips();
    $("composer").hidden = !keys;
    if (!keys) {
      $("feed").appendChild(el("li", "note", "This app doesn't have the key for this tool (it was connected in another browser). On the PC, open Connect your phone again; then here, go back and tap Add a connection to scan the new code."));
      return;
    }
    const data = await api("/api/me/tools/" + id + "/messages");
    if (!data.messages.length) $("feed").appendChild(el("li", "note", "Say hi to " + who(current) + ". Write below, or tap a quick message."));
    readUpto = data.read_upto || 0;
    await render(data.messages);
    toBottom();
  }

  $("back").onclick = () => { if (history.state && history.state.tool && history.length > 1) history.back(); else home(); };
  window.addEventListener("popstate", () => {
    const id = history.state && history.state.tool;
    if (id && tools.some((t) => t.id === id)) openTool(id); else { current = null; loadTools().catch(() => {}); }
  });

  // The open chat fills the visible screen, above the keyboard: on an iPhone the
  // keyboard shrinks the visual viewport only, so the chat follows its height.
  function fitViewport() {
    const vv = window.visualViewport;
    document.documentElement.style.setProperty("--app-h", (vv ? vv.height : window.innerHeight) + "px");
    if (vv) window.scrollTo(0, 0);
  }
  if (window.visualViewport) {
    window.visualViewport.addEventListener("resize", () => { const end = nearBottom(); fitViewport(); if (end) toBottom(); });
    window.visualViewport.addEventListener("scroll", () => { if (document.body.classList.contains("in-chat")) window.scrollTo(0, 0); });
  }
  window.addEventListener("resize", fitViewport);

  const feedBox = () => $("feed");
  function nearBottom() { const f = feedBox(); return f.scrollHeight - f.scrollTop - f.clientHeight < 60; }
  function toBottom() { const f = feedBox(); f.scrollTop = f.scrollHeight; }

  async function poll() {
    if (!current || !keys || document.hidden) return;
    const data = await api("/api/me/tools/" + current.id + "/messages?after=" + lastId);
    if ((data.read_upto || 0) !== readUpto) { readUpto = data.read_upto || 0; ticks(); }
    if (data.messages.length) {
      const end = nearBottom();
      await render(data.messages);
      if (end) toBottom();
    }
  }

  // ---- the feed -------------------------------------------------------------

  let lastDay = "";

  function dayLabel(seconds) {
    const d = new Date(seconds * 1000), today = new Date();
    const yesterday = new Date(today); yesterday.setDate(today.getDate() - 1);
    if (d.toDateString() === today.toDateString()) return "Today";
    if (d.toDateString() === yesterday.toDateString()) return "Yesterday";
    return d.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" });
  }

  function clock(seconds) {
    return new Date(seconds * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  async function render(messages) {
    const feed = $("feed");
    if (messages.length) for (const n of feed.querySelectorAll(".note:not(.error)")) if (keys) n.remove();
    $("typing") && $("typing").remove();
    for (const m of messages) {
      lastId = Math.max(lastId, m.id);
      let value;
      try { value = await C.open(keys, m.body); } catch (e) { value = { text: "(could not be read: " + e.message + ")" }; }
      if (m.kind === "answer" || m.kind === "closed") settle(m, value);
      if (m.kind === "closed") continue;
      const day = dayLabel(m.created);
      if (day !== lastDay) { feed.appendChild(el("li", "day", day)); lastDay = day; }
      feed.appendChild(item(m, value));
      lastSide = m.side;
    }
    ticks();
  }

  // Your messages carry WhatsApp's ticks: one grey tick once Iris has it, two
  // blue ticks once the tool took it in. When the newest message is yours and
  // was read, a "typing" bubble shows the tool is working on the answer.
  function ticks() {
    for (const m of mine) {
      const read = m.id <= readUpto;
      m.tick.textContent = read ? "✓✓" : "✓";
      m.tick.classList.toggle("read", read);
      m.tick.setAttribute("aria-label", read ? "Read" : "Sent");
    }
    const last = mine.length ? mine[mine.length - 1] : null;
    const old = $("typing");
    const working = current && lastSide === "phone" && last && last.id >= lastId && last.id <= readUpto && Date.now() / 1000 - last.created < 20 * 60;
    if (!working) { if (old) old.remove(); return; }
    if (old) return;
    const li = el("li", "msg tool typing");
    li.id = "typing";
    li.setAttribute("aria-label", who(current) + " is working on it");
    li.appendChild(el("span", "dots", ""));
    li.appendChild(el("span", "small muted", who(current) + " is on it"));
    const end = nearBottom();
    $("feed").appendChild(li);
    if (end) toBottom();
  }

  function item(m, v) {
    const li = el("li", "msg " + m.side + " " + m.kind);
    if (m.kind === "question") li.appendChild(el("div", "label small", "Question"));
    if (m.kind === "answer") li.appendChild(el("div", "label small", "Your answer"));
    const text = m.kind === "command" ? (/stop/i.test(v.command) ? "⏹ " : "▶ ") + v.command : v.text || "";
    li.appendChild(el("div", "msg-text", text));
    const meta = el("span", "meta small", clock(m.created));
    if (m.side === "phone") {
      const tick = el("span", "tick", "✓");
      meta.appendChild(tick);
      mine.push({ id: m.id, tick, created: m.created });
    }
    li.appendChild(meta);
    if (m.kind === "question") {
      questions.set(m.id, li);
      if (v.assumed) li.appendChild(el("div", "small muted", "If you don't answer" + (v.deadline ? " by " + new Date(v.deadline).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "") + ": " + v.assumed));
      if (m.state === "open") li.appendChild(answerBox(m, v));
      else li.appendChild(el("div", "settled small", m.state === "answered" ? "Answered" : "Settled on the PC"));
    }
    return li;
  }

  function answerBox(m, v) {
    const box = el("div", "answer");
    const options = el("div", "row wrap");
    for (const opt of v.options || []) {
      const b = el("button", "option", opt);
      b.type = "button";
      b.onclick = () => answer(m.id, opt, box);
      options.appendChild(b);
    }
    box.appendChild(options);
    const form = el("form", "row");
    const input = el("input");
    input.placeholder = (v.options || []).length ? "Or type an answer" : "Type your answer";
    form.appendChild(input);
    form.appendChild(el("button", "primary", "Send"));
    form.onsubmit = (e) => { e.preventDefault(); if (input.value.trim()) answer(m.id, input.value.trim(), box); };
    box.appendChild(form);
    return box;
  }

  function settle(m, v) {
    const li = questions.get(m.reply_to);
    if (!li) return;
    const box = li.querySelector(".answer");
    if (box) box.remove();
    if (!li.querySelector(".settled")) li.appendChild(el("div", "settled small", m.kind === "answer" ? "Answered: " + v.text : (v.text || "Settled on the PC")));
  }

  async function answer(id, text, box) {
    for (const b of box.querySelectorAll("button, input")) b.disabled = true;
    try {
      await api("/api/me/tools/" + current.id + "/messages", { json: { kind: "answer", reply_to: id, body: await C.seal(keys, { text }) } });
      fastUntil = Date.now() + 10 * 60 * 1000;
      await poll();
      toBottom();
      loadTools();
    } catch (e) {
      for (const b of box.querySelectorAll("button, input")) b.disabled = false;
      toast(e.message);
    }
  }

  // Quick messages above the box: one tap asks what is going on; the tool's own
  // buttons (Sketch ProMax: Resume, Stop) sit at the end.
  const QUICK = ["What is everyone doing?", "Send me an update", "Anything you need from me?"];

  function chips() {
    const row = $("chips");
    row.textContent = "";
    if (!keys) { row.hidden = true; return; }
    for (const text of QUICK) {
      const b = el("button", "chip", text);
      b.type = "button";
      b.onclick = () => send(text);
      row.appendChild(b);
    }
    for (const name of current.commands) {
      const b = el("button", "chip" + (/stop/i.test(name) ? " danger" : " command"), (/stop/i.test(name) ? "⏹ " : "▶ ") + name);
      b.type = "button";
      b.onclick = () => command(name);
      row.appendChild(b);
    }
    row.hidden = false;
  }

  async function command(name) {
    if (/stop/i.test(name) && !confirm(name + " " + current.name + "?")) return;
    try {
      await api("/api/me/tools/" + current.id + "/messages", { json: { kind: "command", body: await C.seal(keys, { command: name }) } });
      fastUntil = Date.now() + 10 * 60 * 1000;
      await poll();
      toBottom();
    } catch (e) { toast("Not sent: " + e.message); }
  }

  let toastTimer = 0;
  function toast(text) {
    const t = $("toast");
    t.textContent = text;
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { t.hidden = true; }, 6000);
  }

  // Writing: the box grows with the text, Enter sends on a keyboard (Shift+Enter for a new line), and the
  // conversation is read every 3 s for a while after, so the answer shows up as soon as it comes.
  const say = $("say");
  const grow = () => { say.style.height = "auto"; say.style.height = Math.min(say.scrollHeight, 120) + "px"; };
  say.addEventListener("input", grow);
  say.addEventListener("focus", () => setTimeout(() => { fitViewport(); toBottom(); }, 300));
  say.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !matchMedia("(pointer: coarse)").matches) { e.preventDefault(); $("composer").requestSubmit(); }
  });

  let sending = false;
  async function send(text) {
    if (!text || sending || !keys) return false;
    sending = true;
    try {
      await api("/api/me/tools/" + current.id + "/messages", { json: { kind: "message", body: await C.seal(keys, { text }) } });
      fastUntil = Date.now() + 10 * 60 * 1000;
      await poll();
      toBottom();
      return true;
    } catch (err) {
      toast("Not sent: " + err.message + " Try again.");
      return false;
    } finally {
      sending = false;
    }
  }

  $("composer").onsubmit = async (e) => {
    e.preventDefault();
    const text = say.value.trim();
    if (!text) return;
    say.value = "";
    grow();
    say.focus(); // the keyboard stays up, as in WhatsApp
    if (!(await send(text))) { say.value = text; grow(); }
  };

  $("notify").onchange = () => api("/api/me/tools/" + current.id + "/notify", { json: { notify: $("notify").value } }).then(() => { current.notify = $("notify").value; });

  $("disconnect").onclick = async () => {
    if (!confirm("Disconnect " + current.name + "? It will stop sending you messages until it is connected again.")) return;
    await api("/api/me/tools/" + current.id, { method: "DELETE" });
    localStorage.removeItem("iris.key." + current.id);
    home();
  };

  // ---- notifications ----------------------------------------------------------
  // The bell (top right, on every screen) turns this phone's notifications on and
  // off. On: permission, a push subscription the site keeps, and a test buzz. Off:
  // the subscription is dropped here and on the site. "Notify me about" in each
  // chat's menu chooses what buzzes for that tool.

  const standalone = matchMedia("(display-mode: standalone)").matches || navigator.standalone;
  const ios = /iphone|ipad|ipod/i.test(navigator.userAgent);

  function pushBlocked() {
    if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window))
      return ios && !standalone ? "On iPhone, notifications work only in the Home Screen app: tap Share, then Add to Home Screen, and open Iris from there."
        : "This browser can't show notifications.";
    if (!window.IRIS.vapid) return "The site can't send notifications yet: on PythonAnywhere run pip install -r requirements.txt, then Reload.";
    if (Notification.permission === "denied") return ios ? "Notifications are blocked for Iris: iPhone Settings › Notifications › Iris › Allow." : "Notifications are blocked for this site in the browser's settings.";
    return "";
  }

  async function pushOn() {
    if (pushBlocked() || Notification.permission !== "granted") return false;
    try {
      const reg = await navigator.serviceWorker.getRegistration(ROOT + "/");
      return !!(reg && await reg.pushManager.getSubscription()) && localStorage.getItem("iris.push") !== "off";
    } catch (e) { return false; }
  }

  async function showBell() {
    const on = await pushOn();
    for (const b of document.querySelectorAll("[data-bell]")) {
      b.textContent = on ? "🔔" : "🔕";
      b.setAttribute("aria-pressed", String(on));
      b.title = on ? "Notifications on: tap to turn off" : "Notifications off: tap to turn on";
      b.classList.toggle("on", on);
    }
  }

  async function subscribe() {
    const reg = await navigator.serviceWorker.register(ROOT + "/sw.js", { scope: ROOT + "/" });
    await navigator.serviceWorker.ready;
    let sub = await reg.pushManager.getSubscription();
    if (!sub) sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: C.fromB64u(window.IRIS.vapid) });
    await api("/api/me/phones", { json: sub.toJSON() });
  }

  async function testPush() {
    const got = await api("/api/me/phones/test", { json: {} });
    if (got.sent) toast("Notifications are on. A test is on its way.");
    else toast("Notifications are on here, but the test didn't go: " + (got.error || "the site couldn't reach your phone's push service."));
  }

  async function toggleBell() {
    const blocked = pushBlocked();
    if (blocked) { toast(blocked); return; }
    try {
      if (await pushOn()) {
        const reg = await navigator.serviceWorker.getRegistration(ROOT + "/");
        const sub = reg && await reg.pushManager.getSubscription();
        if (sub) { await api("/api/me/phones", { method: "DELETE", json: { endpoint: sub.endpoint } }); await sub.unsubscribe(); }
        localStorage.setItem("iris.push", "off");
        toast("Notifications off. Messages still come in here.");
      } else {
        if ((await Notification.requestPermission()) !== "granted") { toast(pushBlocked() || "Notifications weren't allowed."); await showBell(); return; }
        localStorage.removeItem("iris.push");
        await subscribe();
        await testPush();
      }
    } catch (e) { toast("Couldn't change notifications: " + e.message); }
    await showBell();
  }

  for (const b of document.querySelectorAll("[data-bell]")) b.onclick = toggleBell;
  $("test-push").onclick = () => { if (pushBlocked()) toast(pushBlocked()); else testPush().catch((e) => toast(e.message)); };

  async function offerNotifications() {
    const hint = $("hint");
    if (ios && !standalone && "serviceWorker" in navigator) {
      hint.textContent = "To get notifications on iPhone: tap Share, then Add to Home Screen, and open Iris from there.";
      hint.hidden = false;
    }
    // Already allowed and not turned off here: the site gets this phone's subscription again (it may have changed).
    if (!pushBlocked() && Notification.permission === "granted" && localStorage.getItem("iris.push") !== "off") subscribe().catch(() => {});
    await showBell();
  }

  // ---- start ------------------------------------------------------------------

  (async () => {
    if ("serviceWorker" in navigator) navigator.serviceWorker.register(ROOT + "/sw.js", { scope: ROOT + "/" }).catch(() => {});
    if (!(await pending())) await loadTools();
    offerNotifications();
    (function tick() {
      poll().catch(() => {}).finally(() => setTimeout(tick, Date.now() < fastUntil ? 3000 : 8000));
    })();
    setInterval(() => { if (!document.hidden && $("confirm").hidden) loadTools().catch(() => {}); }, 15000);
    document.addEventListener("visibilitychange", () => { if (!document.hidden) { poll().catch(() => {}); loadTools().catch(() => {}); } });
  })();
})();
