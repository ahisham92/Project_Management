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
    for (const id of ["empty", "confirm", "list", "tool"]) $(id).hidden = id !== section;
  }

  // ---- connecting a new tool ----------------------------------------------

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
      const mark = el("span", "tool-mark", (t.name.match(/[A-Z0-9]/g) || [t.name[0]]).slice(0, 2).join("").toUpperCase());
      const mid = el("span", "tool-mid");
      const top = el("span", "tool-top");
      top.appendChild(el("span", "tool-row-name", t.name));
      if (t.latest) top.appendChild(el("span", "small muted", when(t.latest.created)));
      mid.appendChild(top);
      const line = el("span", "tool-preview small" + (t.waiting ? " waiting" : " muted"), await preview(t));
      mid.appendChild(line);
      b.appendChild(mark);
      b.appendChild(mid);
      if (t.waiting) b.appendChild(el("span", "badge", String(t.waiting)));
      b.setAttribute("aria-label", t.name + (t.waiting ? ", " + t.waiting + " waiting for your answer" : ""));
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
    if (!keyText) return "Connect it again to read its messages here.";
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

  function seenLine() {
    const ago = Math.max(0, Date.now() / 1000 - current.seen);
    $("tool-seen").textContent = "Last heard from " + (ago < 120 ? "just now" : ago < 3600 ? Math.round(ago / 60) + " min ago" : when(current.seen));
  }

  async function openTool(id) {
    current = tools.find((t) => t.id === id);
    lastId = 0;
    questions.clear();
    show("tool");
    window.scrollTo(0, 0);
    $("tool-name").textContent = current.name;
    $("tool-machine").textContent = current.machine ? "On " + current.machine : "";
    seenLine();
    $("notify").value = current.notify;
    $("feed").textContent = "";
    const keyText = keyFor(id);
    keys = keyText ? await C.importKey(keyText) : null;
    const commands = $("commands");
    commands.textContent = "";
    for (const name of current.commands) {
      const b = el("button", /stop/i.test(name) ? "danger" : "", name);
      b.onclick = () => command(name);
      commands.appendChild(b);
    }
    commands.hidden = !keys || !current.commands.length;
    $("composer").hidden = !keys;
    if (!keys) {
      const li = el("li", "note", "This phone does not have the key for this tool, so its messages cannot be read here. Connect it again from the tool's settings.");
      $("feed").appendChild(li);
      return;
    }
    const data = await api("/api/me/tools/" + id + "/messages");
    if (!data.messages.length) $("feed").appendChild(el("li", "note", "Nothing here yet. Write below to send " + current.name + " a message; it reads it the next time it checks in."));
    await render(data.messages);
    window.scrollTo(0, document.body.scrollHeight);
  }

  $("back").onclick = () => { if (history.state && history.state.tool && history.length > 1) history.back(); else home(); };
  window.addEventListener("popstate", () => {
    const id = history.state && history.state.tool;
    if (id && tools.some((t) => t.id === id)) openTool(id); else { current = null; loadTools().catch(() => {}); }
  });

  async function poll() {
    if (!current || !keys || document.hidden) return;
    const data = await api("/api/me/tools/" + current.id + "/messages?after=" + lastId);
    if (data.messages.length) {
      const atBottom = window.innerHeight + window.scrollY >= document.body.scrollHeight - 40;
      await render(data.messages);
      if (atBottom) window.scrollTo(0, document.body.scrollHeight);
    }
  }

  // ---- the feed -------------------------------------------------------------

  async function render(messages) {
    if (messages.length) for (const n of $("feed").querySelectorAll(".note:not(.error)")) if (keys) n.remove();
    for (const m of messages) {
      lastId = Math.max(lastId, m.id);
      let value;
      try { value = await C.open(keys, m.body); } catch (e) { value = { text: "(could not be read: " + e.message + ")" }; }
      if (m.kind === "answer" || m.kind === "closed") settle(m, value);
      if (m.kind === "closed") continue;
      $("feed").appendChild(item(m, value));
    }
  }

  function item(m, v) {
    const li = el("li", "msg " + m.side + " " + m.kind);
    const head = el("div", "msg-head small muted");
    head.textContent = ({ update: "Update", question: "Question", answer: "You answered", command: "You pressed", message: "You" })[m.kind] + " · " + when(m.created);
    li.appendChild(head);
    li.appendChild(el("div", "msg-text", m.kind === "command" ? v.command : v.text || ""));
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
      await poll();
      loadTools();
    } catch (e) {
      for (const b of box.querySelectorAll("button, input")) b.disabled = false;
      alertLine(e.message);
    }
  }

  async function command(name) {
    if (/stop/i.test(name) && !confirm(name + " " + current.name + "?")) return;
    await api("/api/me/tools/" + current.id + "/messages", { json: { kind: "command", body: await C.seal(keys, { command: name }) } });
    await poll();
  }

  function alertLine(text) {
    const li = el("li", "note error", text);
    $("feed").appendChild(li);
  }

  $("composer").onsubmit = async (e) => {
    e.preventDefault();
    const text = $("say").value.trim();
    if (!text) return;
    $("say").value = "";
    await api("/api/me/tools/" + current.id + "/messages", { json: { kind: "message", body: await C.seal(keys, { text }) } });
    await poll();
  };

  $("notify").onchange = () => api("/api/me/tools/" + current.id + "/notify", { json: { notify: $("notify").value } });

  $("disconnect").onclick = async () => {
    if (!confirm("Disconnect " + current.name + "? It will stop sending you messages until it is connected again.")) return;
    await api("/api/me/tools/" + current.id, { method: "DELETE" });
    localStorage.removeItem("iris.key." + current.id);
    home();
  };

  // ---- notifications ----------------------------------------------------------

  const standalone = matchMedia("(display-mode: standalone)").matches || navigator.standalone;
  const ios = /iphone|ipad|ipod/i.test(navigator.userAgent);

  function offerNotifications() {
    const hint = $("hint");
    if (!("serviceWorker" in navigator) || !window.IRIS.vapid) return;
    if (ios && !standalone) {
      hint.textContent = "To get notifications on iPhone: tap Share, then Add to Home Screen, and open Iris from there.";
      hint.hidden = false;
      return;
    }
    if (!("PushManager" in window) || Notification.permission === "denied") return;
    $("bell").hidden = Notification.permission === "granted";
    if (Notification.permission === "granted") subscribe();
  }

  async function subscribe() {
    const reg = await navigator.serviceWorker.register(ROOT + "/sw.js", { scope: ROOT + "/" });
    await navigator.serviceWorker.ready;
    let sub = await reg.pushManager.getSubscription();
    if (!sub) sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: C.fromB64u(window.IRIS.vapid) });
    await api("/api/me/phones", { json: sub.toJSON() });
  }

  $("bell").onclick = async () => {
    if ((await Notification.requestPermission()) === "granted") {
      $("bell").hidden = true;
      await subscribe();
      await api("/api/me/phones/test", { json: {} });
    }
  };

  // ---- start ------------------------------------------------------------------

  (async () => {
    if ("serviceWorker" in navigator) navigator.serviceWorker.register(ROOT + "/sw.js", { scope: ROOT + "/" }).catch(() => {});
    if (!(await pending())) await loadTools();
    offerNotifications();
    setInterval(() => poll().catch(() => {}), 8000);
    setInterval(() => { if (!document.hidden && $("confirm").hidden) loadTools().catch(() => {}); }, 15000);
    document.addEventListener("visibilitychange", () => { if (!document.hidden) { poll().catch(() => {}); loadTools().catch(() => {}); } });
  })();
})();
