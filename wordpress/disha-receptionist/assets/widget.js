/* Disha Receptionist chat widget: bubble + panel, or inline via [disha_chat]. Talks only to this WordPress site's
   /wp-json/disha/v1/* routes; the site key stays on the server. */
(function () {
  "use strict";
  var C = window.DishaConfig || {};
  if (!C.chatUrl) return;

  var store = {
    get: function (k, s) { try { return (s ? sessionStorage : localStorage).getItem(k); } catch (e) { return null; } },
    set: function (k, v, s) { try { (s ? sessionStorage : localStorage).setItem(k, v); } catch (e) {} }
  };

  // anonymous visitor id: the same conversation continues across pages
  var vid = store.get("disha_vid");
  if (!vid) {
    vid = "v" + Date.now().toString(36) + Math.random().toString(36).slice(2, 10);
    store.set("disha_vid", vid);
  }
  var history = [];
  try { history = JSON.parse(store.get("disha_history", true) || "[]"); } catch (e) { history = []; }
  var lastId = parseInt(store.get("disha_last_id", true) || "0", 10) || 0;
  var muted = store.get("disha_muted", true) === "1";
  var busy = false, pollTimer = null;

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  // small, safe markdown: escape first, then **bold**, links, bullet lines, line breaks
  function md(s) {
    var h = esc(s);
    h = h.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    h = h.replace(/(https?:\/\/[^\s<)]+)/g, '<a href="$1" target="_blank" rel="noopener">$1</a>');
    h = h.replace(/^\s*[-*•]\s+(.*)$/gm, "• $1");
    return h.replace(/\n/g, "<br>");
  }

  function el(tag, cls, html) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html != null) e.innerHTML = html;
    return e;
  }

  // ---------- build the panel
  function buildPanel(inline) {
    var panel = el("div", "disha-panel" + (inline ? " disha-panel--inline" : ""));
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-label", "Chat with Disha");
    var head = el("div", "disha-head");
    head.innerHTML =
      '<img class="disha-avatar" alt="" src="' + esc(C.avatar) + '">' +
      '<div class="disha-title"><strong>Disha</strong><span>DhishaAI receptionist</span></div>';
    if (C.voiceUrl) {
      var voice = el("a", "disha-voice", "Talk to Disha");
      voice.href = C.voiceUrl; voice.target = "_blank"; voice.rel = "noopener";
      head.appendChild(voice);
    }
    if (!inline) {
      var close = el("button", "disha-close", "&times;");
      close.type = "button"; close.setAttribute("aria-label", "Close chat");
      close.onclick = function () { toggle(false); };
      head.appendChild(close);
    }
    var log = el("div", "disha-log");
    log.setAttribute("aria-live", "polite");
    var form = el("form", "disha-form");
    var input = el("input", "disha-input");
    input.type = "text"; input.placeholder = "Type your question…"; input.maxLength = 1000;
    input.setAttribute("aria-label", "Your message");
    var send = el("button", "disha-send", '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 20l18-8L3 4v6l12 2-12 2z"/></svg>');
    send.type = "submit"; send.setAttribute("aria-label", "Send");
    form.appendChild(input); form.appendChild(send);
    panel.appendChild(head); panel.appendChild(log); panel.appendChild(form);
    form.onsubmit = function (e) { e.preventDefault(); ask(input.value); input.value = ""; };
    return { panel: panel, log: log, input: input };
  }

  var ui = [];   // all mounted panels (bubble and/or inline) show the same conversation

  function addBubble(who, text, save) {
    ui.forEach(function (u) {
      var row = el("div", "disha-msg disha-msg--" + who);
      row.innerHTML = md(text);
      u.log.appendChild(row);
      u.log.scrollTop = u.log.scrollHeight;
    });
    if (save) {
      history.push({ who: who, text: text });
      history = history.slice(-40);
      store.set("disha_history", JSON.stringify(history), true);
    }
  }

  function typing(on) {
    ui.forEach(function (u) {
      var t = u.log.querySelector(".disha-typing");
      if (on && !t) {
        t = el("div", "disha-msg disha-msg--bot disha-typing", "<span></span><span></span><span></span>");
        u.log.appendChild(t); u.log.scrollTop = u.log.scrollHeight;
      } else if (!on && t) { t.remove(); }
    });
  }

  function chips() {
    if (!C.chips || !C.chips.length || history.some(function (m) { return m.who === "me"; })) return;
    ui.forEach(function (u) {
      var box = el("div", "disha-chips");
      C.chips.forEach(function (q) {
        var b = el("button", "disha-chip", esc(q));
        b.type = "button";
        b.onclick = function () { ask(q); };
        box.appendChild(b);
      });
      u.log.appendChild(box);
    });
  }

  function render() {
    ui.forEach(function (u) { u.log.innerHTML = ""; });
    addBubble("bot", C.greeting || "Hi! How can I help?", false);
    history.forEach(function (m) { addBubble(m.who, m.text, false); });
    chips();
  }

  function setLast(id) {
    if (id && id > lastId) { lastId = id; store.set("disha_last_id", String(id), true); }
  }

  function ask(text) {
    text = (text || "").trim();
    if (!text || busy) return;
    ui.forEach(function (u) { var c = u.log.querySelector(".disha-chips"); if (c) c.remove(); });
    addBubble("me", text, true);
    busy = true; typing(true);
    fetch(C.chatUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ visitor_id: vid, text: text })
    })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (res) {
        typing(false);
        if (!res.ok) { addBubble("bot", (res.d && (res.d.error || res.d.message)) || "Sorry, something went wrong. Please try again.", false); return; }
        // only a real reply moves the "seen up to" marker; while a counsellor owns the chat, polling picks up
        // their messages (including any written just before this one)
        if (res.d.reply) setLast(res.d.last_id);
        muted = !!res.d.muted;
        store.set("disha_muted", muted ? "1" : "0", true);
        if (res.d.reply) addBubble("bot", res.d.reply, true);
        else if (muted) addBubble("bot", "A counsellor is looking at your message and will reply here shortly.", true);
        if (muted) startPolling();
      })
      .catch(function () { typing(false); addBubble("bot", "I couldn't connect just now. Please check your internet and try again.", false); })
      .then(function () { busy = false; });
  }

  // after a handoff, counsellor replies arrive by polling
  function poll() {
    var url = C.messagesUrl + (C.messagesUrl.indexOf("?") < 0 ? "?" : "&") +
      "visitor_id=" + encodeURIComponent(vid) + "&after=" + lastId;
    fetch(url).then(function (r) { return r.json(); }).then(function (d) {
      (d.messages || []).forEach(function (m) {
        addBubble(m.from === "counsellor" ? "human" : "bot", m.text, true);
      });
      setLast(d.last_id);
      muted = !!d.muted;
      store.set("disha_muted", muted ? "1" : "0", true);
      if (!muted) stopPolling();
    }).catch(function () {});
  }
  function startPolling() { if (!pollTimer) pollTimer = setInterval(poll, 6000); }
  function stopPolling() { clearInterval(pollTimer); pollTimer = null; }

  // ---------- floating bubble
  var launcher, floating;
  function toggle(open) {
    if (!floating) return;
    var show = open == null ? !floating.panel.classList.contains("is-open") : open;
    floating.panel.classList.toggle("is-open", show);
    launcher.setAttribute("aria-expanded", show ? "true" : "false");
    store.set("disha_open", show ? "1" : "0", true);
    if (show) setTimeout(function () { floating.input.focus(); }, 50);
  }

  function mount() {
    var inlines = document.querySelectorAll("[data-disha-inline]");
    for (var i = 0; i < inlines.length; i++) {
      var u = buildPanel(true);
      inlines[i].appendChild(u.panel);
      ui.push(u);
    }
    if (C.bubble && !inlines.length) {
      floating = buildPanel(false);
      launcher = el("button", "disha-launcher",
        '<img alt="" src="' + esc(C.avatar) + '"><span>' + esc(C.label || "Chat with Disha") + "</span>");
      launcher.type = "button";
      launcher.setAttribute("aria-expanded", "false");
      launcher.onclick = function () { toggle(); };
      var wrap = el("div", "disha-root");
      wrap.appendChild(floating.panel); wrap.appendChild(launcher);
      document.body.appendChild(wrap);
      ui.push(floating);
    }
    if (!ui.length) return;
    render();
    if (floating && store.get("disha_open", true) === "1") toggle(true);
    if (muted) startPolling();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount);
  else mount();
})();
