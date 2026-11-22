/* Uncle Super App — Chat (streaming via OpenRouter)
 * Developed by Uncle Engineer — https://uncle-engineer.com/
 */
(function () {
  const $ = (s) => document.querySelector(s);
  const { fmtPrice, fmtCtx, esc } = window.ModelFmt;

  const scroller = $("#chatScroll");
  const inner = $("#chatInner");
  const input = $("#input");
  const form = $("#composer");
  const sendBtn = $("#sendBtn");
  const convList = $("#convList");

  let conversationId = APP.conversationId;
  let currentModel = APP.currentModel;
  let controller = null;

  // ---------- Markdown ----------
  const hasMd = typeof marked !== "undefined";
  if (hasMd) marked.setOptions({ gfm: true, breaks: true });
  function renderMarkdown(el, text) {
    if (hasMd && typeof DOMPurify !== "undefined") {
      el.innerHTML = DOMPurify.sanitize(marked.parse(text));
      if (typeof hljs !== "undefined") el.querySelectorAll("pre code").forEach((b) => { try { hljs.highlightElement(b); } catch (_) {} });
      addCodeCopy(el);
    } else {
      el.textContent = text;
    }
  }
  function addCodeCopy(el) {
    el.querySelectorAll("pre").forEach((pre) => {
      if (pre.querySelector(".code-copy")) return;
      const code = pre.querySelector("code");
      const lang = ((code && code.className.match(/language-(\S+)/)) || [])[1] || "code";
      const bar = document.createElement("div");
      bar.className = "code-bar";
      bar.innerHTML = `<span>${esc(lang)}</span><button class="code-copy" type="button">คัดลอก</button>`;
      bar.querySelector("button").addEventListener("click", (e) => copyText((code || pre).innerText, e.target));
      pre.prepend(bar);
    });
  }
  function copyText(text, btn) {
    const done = () => { if (btn) { const t = btn.textContent; btn.textContent = "คัดลอกแล้ว ✓"; setTimeout(() => (btn.textContent = t), 1400); } };
    if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(text).then(done);
    else { const ta = document.createElement("textarea"); ta.value = text; document.body.appendChild(ta); ta.select(); document.execCommand("copy"); ta.remove(); done(); }
  }

  // render ข้อความที่โหลดมาจาก server
  document.querySelectorAll(".msg-content.md").forEach((el) => { const raw = el.textContent; el.dataset.raw = raw; renderMarkdown(el, raw); });
  inner.addEventListener("click", (e) => {
    const b = e.target.closest("[data-copy]");
    if (b) { const c = b.closest(".msg-body").querySelector(".msg-content"); copyText(c.dataset.raw || c.innerText, b); }
  });
  const scrollBottom = (force) => {
    const near = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 160;
    if (force || near) scroller.scrollTop = scroller.scrollHeight;
  };
  scrollBottom(true);

  // ---------- Model picker ----------
  const picker = new ModelPicker({ url: APP.modelsUrl, current: currentModel, onSelect: (m) => setModel(m.id) });
  function setModel(id) {
    currentModel = id;
    picker.current = id;
    const m = picker.get(id);
    $("#modelName").textContent = m ? m.name : id;
    $("#modelId").textContent = id;
    const tag = $("#modelTag");
    if (m && m.is_free) { tag.textContent = "FREE"; tag.className = "model-tag free"; }
    else if (m && !m.is_variable) { tag.textContent = `$${fmtPrice(m.prompt_price)} / $${fmtPrice(m.completion_price)}`; tag.className = "model-tag"; }
    else { tag.textContent = ""; tag.className = "model-tag"; }
    const btn = $("#modelBtn");
    btn.classList.toggle("locked", !!(m && !picker.canUsePaid && !m.is_free));
  }
  $("#modelBtn").addEventListener("click", () => picker.open());
  picker.load().then(() => setModel(currentModel)).catch(() => {});

  $("#setDefaultBtn").addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    const r = await postJSON(APP.defaultModelUrl, { model: currentModel });
    if (r.ok) { btn.classList.add("starred"); toast("ตั้งเป็นโมเดลเริ่มต้นแล้ว"); }
    else toast(r.error || "ไม่สำเร็จ", "error");
  });

  // ---------- Composer ----------
  const autosize = () => { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 220) + "px"; };
  input.addEventListener("input", autosize);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); form.requestSubmit(); }
  });
  document.querySelectorAll(".chip").forEach((c) => c.addEventListener("click", () => { input.value = c.dataset.prompt; autosize(); input.focus(); }));
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (controller) { controller.abort(); return; }
    const text = input.value.trim();
    if (text) send(text);
  });

  function addMessage(role, text, meta) {
    const hero = $("#hero"); if (hero) hero.remove();
    const wrap = document.createElement("div");
    wrap.className = `msg msg-${role}`;
    const avatar = role === "assistant" ? `<div class="msg-avatar"><svg viewBox="0 0 32 32"><path d="M10 9v8a6 6 0 0 0 12 0V9" stroke="currentColor" stroke-width="3.2" fill="none" stroke-linecap="round"/></svg></div>` : "";
    wrap.innerHTML = `${avatar}<div class="msg-body">${role === "assistant" ? `<div class="msg-meta">${esc(meta || "")}</div>` : ""}<div class="msg-content ${role === "assistant" ? "md" : ""}"></div>${role === "assistant" ? '<div class="msg-tools"><button class="tool-btn" data-copy>คัดลอก</button></div>' : ""}</div>`;
    const content = wrap.querySelector(".msg-content");
    if (role === "assistant") { content.innerHTML = '<span class="typing"><i></i><i></i><i></i></span>'; }
    else content.textContent = text;
    inner.appendChild(wrap);
    scrollBottom(true);
    return { wrap, content, meta: wrap.querySelector(".msg-meta") };
  }

  function setBusy(busy) {
    sendBtn.classList.toggle("stop", busy);
    sendBtn.title = busy ? "หยุด" : "ส่ง";
    input.disabled = busy;
  }

  async function send(text) {
    input.value = ""; autosize();
    addMessage("user", text);
    const m = picker.get(currentModel);
    const bot = addMessage("assistant", "", m ? m.name : currentModel);
    controller = new AbortController();
    setBusy(true);

    let full = "", raf = null, usage = null;
    const paint = () => { raf = null; renderMarkdown(bot.content, full); bot.content.dataset.raw = full; scrollBottom(); };

    try {
      const resp = await fetch(APP.sendUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": APP.csrf },
        body: JSON.stringify({ message: text, model: currentModel, conversation_id: conversationId }),
        signal: controller.signal,
        credentials: "same-origin",
      });
      if (!resp.ok || !(resp.headers.get("content-type") || "").includes("event-stream")) {
        let msg = `HTTP ${resp.status}`;
        try { msg = (await resp.json()).error || msg; } catch (_) {}
        throw new Error(msg);
      }
      const reader = resp.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buf = "";
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let idx;
        while ((idx = buf.indexOf("\n\n")) >= 0) {
          const chunk = buf.slice(0, idx); buf = buf.slice(idx + 2);
          const line = chunk.split("\n").find((l) => l.startsWith("data:"));
          if (!line) continue;
          let ev; try { ev = JSON.parse(line.slice(5)); } catch (_) { continue; }
          if (ev.type === "meta") onMeta(ev);
          else if (ev.type === "delta") { full += ev.content; if (!raf) raf = requestAnimationFrame(paint); }
          else if (ev.type === "usage") usage = ev;
          else if (ev.type === "error") showError(bot, ev.message);
        }
      }
      if (raf) cancelAnimationFrame(raf);
      if (full) paint();
      else if (!bot.wrap.classList.contains("msg-error")) showError(bot, "โมเดลไม่ได้ส่งคำตอบกลับมา");
      if (usage && usage.completion_tokens) bot.meta.textContent += ` · ${usage.completion_tokens} tokens`;
      bumpQuota();
    } catch (err) {
      if (err.name === "AbortError") {
        if (full) { paint(); bot.meta.textContent += " · หยุดแล้ว"; } else showError(bot, "ยกเลิกแล้ว");
        bumpQuota();
      } else showError(bot, err.message || String(err));
    } finally {
      controller = null;
      setBusy(false);
      input.focus();
    }
  }

  function showError(bot, msg) {
    bot.wrap.classList.add("msg-error");
    const prev = bot.content.dataset.raw || "";
    if (prev) renderMarkdown(bot.content, prev); else bot.content.innerHTML = "";
    bot.content.insertAdjacentHTML("beforeend", `<div class="err-box">⚠ ${esc(msg)}</div>`);
  }

  function bumpQuota() { const q = $("#quotaUsed"); if (q) q.textContent = String(Number(q.textContent) + 1); }

  function onMeta(ev) {
    if (ev.is_new || !conversationId) {
      conversationId = ev.conversation_id;
      history.replaceState(null, "", APP.convUrl + conversationId + "/");
      document.title = ev.title + " · Uncle Super App";
      const empty = convList.querySelector(".conv-empty"); if (empty) empty.remove();
      convList.querySelectorAll(".conv-item").forEach((li) => li.classList.remove("active"));
      convList.insertAdjacentHTML("afterbegin", convItemHTML(ev.conversation_id, ev.title, true));
    } else {
      const li = convList.querySelector(`[data-id="${conversationId}"]`);
      if (li && li !== convList.firstElementChild) convList.prepend(li);
    }
  }
  function convItemHTML(id, title, active) {
    return `<li class="conv-item ${active ? "active" : ""}" data-id="${id}">
      <a href="${APP.convUrl}${id}/" class="conv-link" title="${esc(title)}">${esc(title)}</a>
      <div class="conv-actions">
        <button class="icon-btn xs" data-rename title="เปลี่ยนชื่อ"><svg viewBox="0 0 24 24"><path d="M12 20h9M16.5 3.5a2.1 2.1 0 1 1 3 3L7 19l-4 1 1-4z"/></svg></button>
        <button class="icon-btn xs danger" data-delete title="ลบ"><svg viewBox="0 0 24 24"><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/></svg></button>
      </div></li>`;
  }

  // ---------- Sidebar actions ----------
  convList.addEventListener("click", async (e) => {
    const li = e.target.closest(".conv-item"); if (!li) return;
    const id = li.dataset.id;
    if (e.target.closest("[data-rename]")) {
      e.preventDefault();
      const link = li.querySelector(".conv-link");
      const title = prompt("ชื่อแชทใหม่", link.textContent.trim());
      if (!title) return;
      const r = await postJSON(`${APP.apiConvUrl}${id}/rename/`, { title });
      if (r.ok) { link.textContent = r.title; link.title = r.title; }
    } else if (e.target.closest("[data-delete]")) {
      e.preventDefault();
      if (!confirm("ลบแชทนี้? ไม่สามารถกู้คืนได้")) return;
      const r = await postJSON(`${APP.apiConvUrl}${id}/delete/`, {});
      if (r.ok) {
        li.remove();
        if (String(id) === String(conversationId)) window.location.href = APP.convUrl.replace(/c\/$/, "");
      }
    }
  });

  async function postJSON(url, data) {
    try {
      const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json", "X-CSRFToken": APP.csrf }, body: JSON.stringify(data), credentials: "same-origin" });
      const d = await r.json().catch(() => ({}));
      return { ok: r.ok && d.ok !== false, ...d };
    } catch (e) { return { ok: false, error: String(e) }; }
  }

  function toast(msg, kind = "success") {
    let box = document.getElementById("toasts");
    if (!box) { box = document.createElement("div"); box.id = "toasts"; box.className = "toasts"; document.body.appendChild(box); }
    const t = document.createElement("div");
    t.className = `toast toast-${kind}`; t.textContent = msg; box.appendChild(t);
    setTimeout(() => t.classList.add("hide"), 2500); setTimeout(() => t.remove(), 3200);
  }

  input.focus();
})();
