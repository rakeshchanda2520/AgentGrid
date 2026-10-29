/* AgentGrid web chat widget. Embed: <script src="https://API/widget.js" data-agent="pk_..." async></script>
   Options: data-api (API origin, defaults to this script's origin), data-open="true" (start open), data-position="left".
   Shadow DOM keeps host-page CSS out; colours come from the tenant's white-label branding. */
(function () {
  "use strict";
  var script = document.currentScript || document.querySelector('script[data-agent]');
  if (!script || window.__agentgridLoaded) return;
  window.__agentgridLoaded = true;
  var KEY = script.getAttribute("data-agent");
  var API = (script.getAttribute("data-api") || new URL(script.src).origin).replace(/\/$/, "");
  var START_OPEN = script.getAttribute("data-open") === "true";
  var LEFT = script.getAttribute("data-position") === "left";
  var store = { get: function (k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
                set: function (k, v) { try { localStorage.setItem(k, v); } catch (e) {} } };
  var visitorKey = "agentgrid_visitor_" + KEY;
  var visitor = store.get(visitorKey);
  if (!visitor) {
    visitor = "v_" + Math.random().toString(36).slice(2) + Date.now().toString(36);
    store.set(visitorKey, visitor);
  }

  var host = document.createElement("div");
  host.id = "agentgrid-widget";
  document.body.appendChild(host);
  var root = host.attachShadow({ mode: "open" });
  var cfg = null, ws = null, retry = 0, pending = null, pendingText = "", state = "BOT_ACTIVE", consented = store.get("agentgrid_consent_" + KEY) === "1";

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  function css(b) {
    var p = b.primary_color || "#172554", a = b.accent_color || "#C19A5B";
    return [
      ":host{all:initial}",
      "*{box-sizing:border-box;font-family:Inter,ui-sans-serif,system-ui,-apple-system,'Segoe UI',sans-serif}",
      ".launcher{position:fixed;bottom:20px;" + (LEFT ? "left" : "right") + ":20px;width:60px;height:60px;border-radius:50%;border:0;cursor:pointer;background:" + p + ";color:#fff;box-shadow:0 10px 30px rgba(23,37,84,.28);display:flex;align-items:center;justify-content:center;z-index:2147483646;transition:transform .2s}",
      ".launcher:hover{transform:translateY(-2px)}.launcher:focus-visible{outline:3px solid " + a + ";outline-offset:3px}",
      ".launcher .dot{position:absolute;top:6px;right:6px;width:12px;height:12px;border-radius:50%;background:" + a + ";border:2px solid #fff}",
      ".panel{position:fixed;bottom:92px;" + (LEFT ? "left" : "right") + ":20px;width:380px;max-width:calc(100vw - 32px);height:600px;max-height:calc(100vh - 120px);background:#FBF7F0;border-radius:18px;box-shadow:0 24px 64px rgba(23,37,84,.22);display:none;flex-direction:column;overflow:hidden;z-index:2147483647;border:1px solid #E2D6C1}",
      ".panel.open{display:flex;animation:in .22s ease-out}@keyframes in{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:none}}",
      "@media (max-width:520px){.panel{inset:0;width:100%;max-width:none;height:100%;max-height:none;border-radius:0}}",
      ".head{background:" + p + ";color:#fff;padding:16px 18px;display:flex;align-items:center;gap:12px}",
      ".avatar{width:38px;height:38px;border-radius:50%;background:" + a + ";color:" + p + ";display:flex;align-items:center;justify-content:center;font-weight:700;font-size:16px;flex:none}",
      ".title{font-weight:650;font-size:15px;line-height:1.2}.sub{font-size:12px;opacity:.85;margin-top:2px;display:flex;align-items:center;gap:6px}",
      ".live{width:8px;height:8px;border-radius:50%;background:#5BE49B}.close{margin-left:auto;background:transparent;border:0;color:#fff;cursor:pointer;font-size:22px;line-height:1;padding:4px 8px;border-radius:8px}.close:hover{background:rgba(255,255,255,.12)}",
      ".body{flex:1;overflow-y:auto;padding:18px 14px;display:flex;flex-direction:column;gap:10px;background:#F3EBDD}",
      ".msg{max-width:84%;padding:10px 13px;border-radius:14px;font-size:14px;line-height:1.45;white-space:pre-wrap;word-wrap:break-word;color:#172554}",
      ".bot{background:#FFFFFF;border:1px solid #E2D6C1;border-bottom-left-radius:4px;align-self:flex-start}",
      ".me{background:" + p + ";color:#fff;border-bottom-right-radius:4px;align-self:flex-end}",
      ".human{background:#FFF8EA;border:1px solid " + a + ";border-bottom-left-radius:4px;align-self:flex-start}",
      ".who{font-size:11px;font-weight:600;color:#8A6A2F;margin-bottom:3px;letter-spacing:.02em}",
      ".src{font-size:11px;color:#4A5578;margin-top:6px;padding-top:6px;border-top:1px dashed #E2D6C1}",
      ".note{align-self:center;font-size:12px;color:#4A5578;background:#EDE3D1;padding:6px 10px;border-radius:999px;text-align:center}",
      ".typing{display:inline-flex;gap:4px}.typing i{width:6px;height:6px;border-radius:50%;background:#8A6A2F;animation:b 1s infinite}.typing i:nth-child(2){animation-delay:.15s}.typing i:nth-child(3){animation-delay:.3s}@keyframes b{0%,80%,100%{opacity:.25}40%{opacity:1}}",
      ".chips{display:flex;flex-wrap:wrap;gap:6px;padding:0 14px 10px;background:#F3EBDD}",
      ".chip{border:1px solid " + p + ";color:" + p + ";background:#fff;border-radius:999px;padding:6px 11px;font-size:12.5px;cursor:pointer}.chip:hover{background:" + p + ";color:#fff}",
      ".consent{font-size:11.5px;color:#4A5578;padding:10px 14px;background:#FBF7F0;border-top:1px solid #E2D6C1}",
      "form{display:flex;gap:8px;padding:12px;border-top:1px solid #E2D6C1;background:#FBF7F0}",
      "textarea{flex:1;resize:none;border:1px solid #E2D6C1;border-radius:12px;padding:10px 12px;font-size:14px;max-height:110px;outline:none;color:#172554;background:#fff}textarea:focus{border-color:" + p + "}",
      ".send{border:0;background:" + p + ";color:#fff;border-radius:12px;padding:0 14px;cursor:pointer;font-weight:600}.send:disabled{opacity:.5;cursor:default}",
      ".foot{display:flex;justify-content:space-between;align-items:center;font-size:11px;color:#4A5578;padding:0 14px 10px;background:#FBF7F0}",
      ".link{background:none;border:0;color:#4A5578;text-decoration:underline;cursor:pointer;font-size:11px;padding:0}",
      ".rate{display:flex;gap:6px;align-self:flex-start}.rate button{border:1px solid #E2D6C1;background:#fff;border-radius:999px;padding:4px 10px;cursor:pointer;font-size:13px}"
    ].join("");
  }

  var panel, body, input, chips, sendBtn, consentEl, subEl;

  function scroll() { body.scrollTop = body.scrollHeight; }

  function cleanText(t) { return (t || "").replace(/\s*\[S\d+\]/g, "").trim(); }

  function addMessage(role, text, citations, author) {
    var wrap = el("div", "msg " + (role === "user" ? "me" : role === "human" ? "human" : "bot"));
    if (role === "human") wrap.appendChild(el("div", "who", author || "Team member"));
    wrap.appendChild(document.createTextNode(cleanText(text)));
    if (citations && citations.length) {
      var seen = {}, names = [];
      citations.forEach(function (c) {
        var n = c.title + (c.page ? " p." + c.page : "");
        if (!seen[n]) { seen[n] = 1; names.push(n); }
      });
      wrap.appendChild(el("div", "src", "Sources: " + names.join(" · ")));
    }
    body.appendChild(wrap);
    scroll();
    return wrap;
  }

  function note(text) { body.appendChild(el("div", "note", text)); scroll(); }

  function showTyping() {
    if (pending) return;
    pending = el("div", "msg bot");
    var t = el("span", "typing");
    t.appendChild(el("i")); t.appendChild(el("i")); t.appendChild(el("i"));
    pending.appendChild(t);
    pendingText = "";
    body.appendChild(pending);
    scroll();
  }

  function clearPending() { if (pending) { pending.remove(); pending = null; pendingText = ""; } }

  function setState(s) {
    if (s === state) return;
    state = s;
    if (s === "PENDING_HUMAN") note("Connecting you with the team…");
    if (s === "HUMAN_ACTIVE") { subEl.lastChild.textContent = " A team member is here"; note("A team member joined the chat"); }
    if (s === "BOT_ACTIVE") subEl.lastChild.textContent = " AI assistant · replies instantly";
    if (s === "RESOLVED") askRating();
  }

  function askRating() {
    var r = el("div", "rate");
    [["👍 Helpful", 5], ["👎 Not really", 1]].forEach(function (x) {
      var b = el("button", "", x[0]);
      b.onclick = function () { if (ws && ws.readyState === 1) ws.send(JSON.stringify({ type: "csat", score: x[1] })); r.replaceWith(el("div", "note", "Thanks for the feedback!")); };
      r.appendChild(b);
    });
    body.appendChild(r);
    scroll();
  }

  function connect() {
    var url = API.replace(/^http/, "ws") + "/ws/widget?key=" + encodeURIComponent(KEY) + "&visitor=" + encodeURIComponent(visitor);
    ws = new WebSocket(url);
    ws.onopen = function () { retry = 0; sendBtn.disabled = false; };
    ws.onmessage = function (ev) {
      var d = JSON.parse(ev.data);
      if (d.type === "hello") {
        if (d.history && d.history.length) {
          body.querySelectorAll(".msg,.note,.rate").forEach(function (n) { n.remove(); });
          d.history.forEach(function (m) { if (m.role !== "system") addMessage(m.role, m.content, m.citations); });
          chips.style.display = "none";
        }
        state = d.state; setState(d.state);
      } else if (d.type === "typing") {
        showTyping();
      } else if (d.type === "token") {
        if (!pending) showTyping();
        pendingText += d.text;
        pending.textContent = cleanText(pendingText);
        scroll();
      } else if (d.type === "message") {
        if (d.message.role === "user") return;
        clearPending();
        addMessage(d.message.role, d.message.content, d.message.citations);
        if (d.state) setState(d.state);
      } else if (d.type === "state") {
        setState(d.state);
      } else if (d.type === "error") {
        clearPending(); note(d.text);
      }
    };
    ws.onclose = function () {
      sendBtn.disabled = true;
      retry = Math.min(retry + 1, 6);
      setTimeout(connect, 500 * Math.pow(2, retry));
    };
  }

  function send(text) {
    text = (text || "").trim();
    if (!text || !ws || ws.readyState !== 1) return;
    addMessage("user", text);
    chips.style.display = "none";
    ws.send(JSON.stringify({ type: "message", text: text, consent: true }));
    if (!consented) { consented = true; store.set("agentgrid_consent_" + KEY, "1"); consentEl.remove(); }
    if (state === "BOT_ACTIVE" || state === "RESOLVED") showTyping();
  }

  function build() {
    var b = cfg.brand || {};
    var style = el("style"); style.textContent = css(b); root.appendChild(style);
    var launcher = el("button", "launcher");
    launcher.setAttribute("aria-label", "Open chat with " + cfg.agent_name);
    launcher.innerHTML = '<svg width="28" height="28" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v8a2.5 2.5 0 0 1-2.5 2.5H10l-4.2 3.6c-.5.4-1.3.1-1.3-.6V16A2.5 2.5 0 0 1 4 13.5z" fill="currentColor"/></svg><span class="dot"></span>';
    panel = el("div", "panel");
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-label", cfg.company + " chat");
    var head = el("div", "head");
    head.appendChild(el("div", "avatar", (cfg.agent_name || "A").charAt(0)));
    var titles = el("div");
    titles.appendChild(el("div", "title", b.widget_title || cfg.company));
    subEl = el("div", "sub");
    subEl.appendChild(el("span", "live"));
    subEl.appendChild(document.createTextNode(" " + cfg.agent_name + " · AI assistant"));
    titles.appendChild(subEl);
    head.appendChild(titles);
    var close = el("button", "close", "×");
    close.setAttribute("aria-label", "Close chat");
    head.appendChild(close);
    body = el("div", "body");
    body.setAttribute("aria-live", "polite");
    chips = el("div", "chips");
    (cfg.quick_replies || []).forEach(function (q) { var c = el("button", "chip", q); c.onclick = function () { send(q); }; chips.appendChild(c); });
    var form = el("form");
    input = el("textarea");
    input.rows = 1;
    input.placeholder = "Type your message…";
    input.setAttribute("aria-label", "Message");
    sendBtn = el("button", "send", "Send");
    sendBtn.type = "submit";
    sendBtn.disabled = true;
    form.appendChild(input); form.appendChild(sendBtn);
    var foot = el("div", "foot");
    var human = el("button", "link", "Talk to a person");
    human.type = "button";
    human.onclick = function () { send("I'd like to talk to a person please"); };
    foot.appendChild(human);
    if (!b.hide_powered_by) foot.appendChild(el("span", "", "Powered by " + (b.product_name || "AgentGrid")));
    consentEl = el("div", "consent", cfg.consent_text);
    panel.appendChild(head); panel.appendChild(body); panel.appendChild(chips);
    if (!consented) panel.appendChild(consentEl);
    panel.appendChild(form); panel.appendChild(foot);
    root.appendChild(launcher); root.appendChild(panel);
    addMessage("assistant", cfg.greeting);

    function toggle(open) {
      panel.classList.toggle("open", open);
      launcher.setAttribute("aria-expanded", String(open));
      if (open) { input.focus(); if (!ws) connect(); }
    }
    launcher.onclick = function () { toggle(!panel.classList.contains("open")); };
    close.onclick = function () { toggle(false); launcher.focus(); };
    panel.addEventListener("keydown", function (e) { if (e.key === "Escape") close.onclick(); });
    form.onsubmit = function (e) { e.preventDefault(); send(input.value); input.value = ""; };
    input.addEventListener("keydown", function (e) { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); form.onsubmit(e); } });
    if (START_OPEN) toggle(true);
    window.AgentGrid = { open: function () { toggle(true); }, close: function () { toggle(false); }, send: function (t) { toggle(true); setTimeout(function () { send(t); }, 400); } };
  }

  fetch(API + "/public/widget/" + encodeURIComponent(KEY) + "/config")
    .then(function (r) { if (!r.ok) throw new Error("AgentGrid: unknown agent key"); return r.json(); })
    .then(function (c) { cfg = c; build(); })
    .catch(function (e) { console.warn(e.message || e); });
})();
