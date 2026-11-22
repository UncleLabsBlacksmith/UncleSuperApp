/* Uncle Super App — RAG (ถามจากเอกสาร)
 * Developed by Uncle Engineer — https://uncle-engineer.com/
 */
(function () {
  const { $, $$, esc, toast, postJSON, renderMarkdown, streamSSE, bindSidebar, sidebarItem, autosize, fileIcon, fmtBytes, copyText } = window.Convo;
  const scroller = $("#chatScroll"), inner = $("#chatInner"), input = $("#input"), form = $("#composer"), sendBtn = $("#sendBtn");
  let chatId = PAGE.chatId, currentModel = PAGE.currentModel, embedModel = PAGE.embedModel;
  let docs = JSON.parse($("#ragDocs").textContent || "[]");
  const savedSources = JSON.parse($("#ragSources").textContent || "{}");
  let controller = null, pollTimer = null;
  const scrollBottom = (f) => { if (f || scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 200) scroller.scrollTop = scroller.scrollHeight; };

  // ---------- sources ----------
  function renderSources(slot, sources, mode, note) {
    if (!sources || !sources.length) {
      slot.innerHTML = '<div class="sources empty muted small">ไม่พบข้อความที่เกี่ยวข้องในเอกสาร</div>';
      return;
    }
    slot.innerHTML = `<details class="sources"><summary><svg viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/></svg>แหล่งที่มา ${sources.length} รายการ${mode ? ` <span class="muted small">· ${mode === "hybrid" ? "ค้นหาแบบ hybrid (ความหมาย + คำ)" : "ค้นหาด้วยคำ"}</span>` : ""}</summary>
      ${note ? `<div class="muted small" style="padding:4px 2px">${esc(note)}</div>` : ""}
      <div class="source-list">${sources.map((s) => `<div class="source" data-n="${s.n}">
        <div class="source-head"><span class="source-n">${s.n}</span>${fileIcon(s.doc)}<b>${esc(s.doc)}</b>${s.loc ? `<span class="muted small">${esc(s.loc)}</span>` : ""}
          ${s.similarity !== null && s.similarity !== undefined ? `<span class="pill sm">sim ${s.similarity}</span>` : ""}</div>
        <div class="source-text">${esc(s.text)}</div></div>`).join("")}</div></details>`;
  }
  inner.addEventListener("click", (e) => {
    const cite = e.target.closest(".cite");
    if (cite) {
      e.preventDefault();
      const body = cite.closest(".msg-body");
      const det = $("details.sources", body); if (!det) return;
      det.open = true;
      const src = $(`.source[data-n="${cite.dataset.cite}"]`, det);
      if (src) { src.scrollIntoView({ behavior: "smooth", block: "center" }); src.classList.remove("flash"); void src.offsetWidth; src.classList.add("flash"); src.classList.add("expanded"); }
      return;
    }
    const s = e.target.closest(".source"); if (s && !e.target.closest("a")) s.classList.toggle("expanded");
    const b = e.target.closest("[data-copy]");
    if (b) { const c = b.closest(".msg-body").querySelector(".msg-content"); copyText(c.dataset.raw || c.innerText, b); }
  });
  $$(".msg-assistant").forEach((m) => {
    const c = $(".msg-content", m); const raw = c.textContent; c.dataset.raw = raw;
    renderMarkdown(c, raw, { citations: true });
    renderSources($(".sources-slot", m), savedSources[m.dataset.msgId]);
  });
  scrollBottom(true);

  // ---------- model picker ----------
  const picker = new ModelPicker({ url: PAGE.modelsUrl, current: currentModel, onSelect: (m) => setModel(m.id) });
  function setModel(id) {
    currentModel = id; picker.current = id;
    const m = picker.get(id);
    $("#modelName").textContent = m ? m.name : id; $("#modelId").textContent = id;
    const tag = $("#modelTag"); tag.textContent = m && m.is_free ? "FREE" : ""; tag.className = "model-tag" + (m && m.is_free ? " free" : "");
  }
  $("#modelBtn").addEventListener("click", () => picker.open());
  picker.load().then(() => setModel(currentModel)).catch(() => {});

  // ---------- documents ----------
  function renderDocs() {
    const ready = docs.filter((d) => d.status === "ready");
    $("#docCount").textContent = docs.length ? `${ready.length}/${docs.length} พร้อมใช้ · ${docs.reduce((a, d) => a + (d.chunks || 0), 0).toLocaleString()} ส่วน` : "";
    $("#docList").innerHTML = docs.length ? docs.map((d) => {
      const meta = d.status === "ready" ? `${d.pages ? d.pages + " หน้า · " : ""}${d.chunks} ส่วน · ${fmtBytes(d.size)}`
        : d.status === "processing" ? `${d.progress < 30 ? "กำลังอ่านไฟล์…" : "กำลังทำดัชนี…"} ${d.progress}%` : "ผิดพลาด";
      const warn = (d.warnings || []).length ? `<div class="doc-warn">⚠ ${esc(d.warnings.join(" · "))}</div>` : "";
      return `<div class="doc-item st-${d.status}" data-id="${d.id}">
        ${fileIcon(d.name)}
        <div class="doc-main"><b title="${esc(d.name)}">${esc(d.name)}</b><span class="muted small">${esc(meta)}</span>
          ${d.status === "processing" ? `<div class="bar thin"><i style="width:${Math.max(5, d.progress)}%"></i></div>` : ""}
          ${d.status === "error" ? `<div class="doc-err">${esc(d.error)}</div>` : ""}${warn}
          ${d.status === "ready" && !d.embed_model ? '<span class="pill sm">ค้นด้วยคำเท่านั้น</span>' : ""}</div>
        <button type="button" class="icon-btn xs danger" data-del title="ลบเอกสาร">×</button></div>`;
    }).join("") : '<div class="muted small doc-empty">ยังไม่มีเอกสาร</div>';
    $("#searchMode").innerHTML = chatId ? `Embedding: <code>${esc(embedModel || "—")}</code>` : "";
    if (docs.some((d) => d.status === "processing")) schedulePoll(); else { clearTimeout(pollTimer); pollTimer = null; }
  }
  function schedulePoll() {
    if (pollTimer) return;
    pollTimer = setTimeout(async () => {
      pollTimer = null;
      try {
        const d = await (await fetch(`${PAGE.apiBase}chats/${chatId}/docs/`, { credentials: "same-origin" })).json();
        const wasProcessing = docs.filter((x) => x.status === "processing").map((x) => x.id);
        docs = d.docs;
        docs.filter((x) => wasProcessing.includes(x.id) && x.status !== "processing").forEach((x) => toast(x.status === "ready" ? `“${x.name}” พร้อมใช้แล้ว` : `“${x.name}” ประมวลผลไม่สำเร็จ`, x.status === "ready" ? "success" : "error"));
      } catch (_) {}
      renderDocs();
    }, 2000);
  }
  renderDocs();
  $("#docList").addEventListener("click", async (e) => {
    const b = e.target.closest("[data-del]"); if (!b) return;
    const item = b.closest(".doc-item");
    if (!confirm("ลบเอกสารนี้ออกจากคลัง?")) return;
    const r = await postJSON(`${PAGE.apiBase}docs/${item.dataset.id}/delete/`);
    if (r.ok) { docs = docs.filter((d) => String(d.id) !== item.dataset.id); renderDocs(); }
  });

  const docInput = $("#docInput"), drop = $("#docDrop");
  drop.addEventListener("click", () => docInput.click());
  drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); docInput.click(); } });
  docInput.addEventListener("change", () => { upload(docInput.files); docInput.value = ""; });
  ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("drag"); }));
  ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("drag"); }));
  drop.addEventListener("drop", (e) => upload(e.dataTransfer.files));

  async function upload(list) {
    const arr = [...list].filter((f) => { if (f.size > PAGE.maxMb * 1048576) { toast(`${f.name} ใหญ่เกิน ${PAGE.maxMb} MB`, "error"); return false; } return true; });
    if (!arr.length) return;
    const fd = new FormData();
    arr.forEach((f) => fd.append("files", f, f.name));
    if (chatId) fd.append("chat_id", chatId);
    drop.classList.add("busy");
    try {
      const r = await fetch(PAGE.uploadUrl, { method: "POST", body: fd, headers: { "X-CSRFToken": PAGE.csrf }, credentials: "same-origin" });
      const d = await r.json().catch(() => ({ error: `HTTP ${r.status}` }));
      (d.errors || []).forEach((e) => toast(e, "error", 6000));
      if (!d.docs || !d.docs.length) { if (d.error) toast(d.error, "error"); return; }
      if (!chatId) {
        chatId = d.chat_id;
        history.replaceState(null, "", d.url);
        const lst = $("#chatList"); const emp = $(".conv-empty", lst); if (emp) emp.remove();
        $$(".conv-item", lst).forEach((li) => li.classList.remove("active"));
        lst.insertAdjacentHTML("afterbegin", sidebarItem(d.chat_id, d.chat_title, d.url));
        $("#settingsBtn").hidden = false;
        input.placeholder = "ถามจากเอกสาร เช่น เงื่อนไขการรับประกันมีอะไรบ้าง";
        const hp = $("#hero p"); if (hp) hp.textContent = "กำลังทำดัชนีเอกสาร… เมื่อพร้อมแล้วพิมพ์คำถามได้เลย AI จะตอบพร้อมอ้างอิงแหล่งที่มา";
      }
      docs = docs.concat(d.docs);
      renderDocs();
      toast(`อัปโหลด ${d.docs.length} ไฟล์ — กำลังทำดัชนี`);
    } catch (err) { toast(String(err), "error"); } finally { drop.classList.remove("busy"); }
  }

  // ---------- ask ----------
  const resize = autosize(input);
  input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); form.requestSubmit(); } });
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (controller) { controller.abort(); return; }
    const q = input.value.trim(); if (!q) return;
    if (!docs.length) { toast("อัปโหลดเอกสารก่อน", "error"); docInput.click(); return; }
    if (!docs.some((d) => d.status === "ready")) { toast("เอกสารยังทำดัชนีไม่เสร็จ รอสักครู่", "error"); return; }
    ask(q);
  });
  function addMsg(role, text) {
    const hero = $("#hero"); if (hero) hero.remove();
    const w = document.createElement("div"); w.className = `msg msg-${role}`;
    const avatar = role === "assistant" ? '<div class="msg-avatar"><svg viewBox="0 0 32 32"><path d="M10 9v8a6 6 0 0 0 12 0V9" stroke="currentColor" stroke-width="3.2" fill="none" stroke-linecap="round"/></svg></div>' : "";
    w.innerHTML = `${avatar}<div class="msg-body">${role === "assistant" ? `<div class="msg-meta">${esc(currentModel)}</div><div class="an-status"><span class="spinner"></span> <span>กำลังค้นหา…</span></div>` : ""}<div class="msg-content ${role === "assistant" ? "md" : ""}"></div>${role === "assistant" ? '<div class="sources-slot"></div><div class="msg-tools"><button class="tool-btn" data-copy>คัดลอก</button></div>' : ""}</div>`;
    if (role === "user") $(".msg-content", w).textContent = text;
    inner.appendChild(w); scrollBottom(true); return w;
  }
  async function ask(q) {
    input.value = ""; resize();
    addMsg("user", q);
    const bot = addMsg("assistant"), content = $(".msg-content", bot), status = $(".an-status", bot);
    controller = new AbortController(); sendBtn.classList.add("stop"); input.disabled = true;
    let full = "", raf = null;
    const paint = () => { raf = null; renderMarkdown(content, full, { citations: true }); content.dataset.raw = full; scrollBottom(); };
    try {
      await streamSSE(PAGE.askUrl, { chat_id: chatId, message: q, model: currentModel }, (ev) => {
        if (ev.type === "status") $("span:last-child", status).textContent = ev.text;
        else if (ev.type === "sources") renderSources($(".sources-slot", bot), ev.sources, ev.mode, ev.note);
        else if (ev.type === "delta") { full += ev.content; status.hidden = true; if (!raf) raf = requestAnimationFrame(paint); }
        else if (ev.type === "error") content.insertAdjacentHTML("beforeend", `<div class="err-box">⚠ ${esc(ev.message)}</div>`);
      }, controller.signal);
      if (raf) cancelAnimationFrame(raf);
      if (full) paint();
    } catch (err) {
      if (err.name !== "AbortError") content.insertAdjacentHTML("beforeend", `<div class="err-box">⚠ ${esc(err.message || err)}</div>`);
      else if (full) paint();
    } finally {
      status.hidden = true; controller = null; sendBtn.classList.remove("stop"); input.disabled = false; input.focus();
    }
  }

  // ---------- settings ----------
  const modal = $("#settingsModal");
  let embedModels = null;
  $("#settingsBtn").addEventListener("click", async () => {
    modal.classList.add("open");
    if (!embedModels) {
      try {
        const d = await (await fetch(PAGE.embedModelsUrl, { credentials: "same-origin" })).json();
        embedModels = d.models || [];
        const sel = $("#embedSelect");
        sel.innerHTML = embedModels.map((m) => `<option value="${esc(m.id)}" ${m.id === embedModel ? "selected" : ""} ${!d.can_use_paid && !m.is_free ? "disabled" : ""}>${esc(m.name)} — ${m.is_free ? "ฟรี" : "$" + m.price + "/1M tokens"}</option>`).join("");
        if (!embedModels.some((m) => m.id === embedModel)) sel.insertAdjacentHTML("afterbegin", `<option value="${esc(embedModel)}" selected>${esc(embedModel)}</option>`);
      } catch (_) { $("#embedSelect").innerHTML = `<option>${esc(embedModel)}</option>`; }
    }
  });
  modal.querySelectorAll("[data-close]").forEach((el) => el.addEventListener("click", () => modal.classList.remove("open")));
  $("#topk").addEventListener("input", (e) => { $("#topkOut").textContent = e.target.value; });
  $("#saveSettings").addEventListener("click", async () => {
    const em = $("#embedSelect").value;
    if (em !== embedModel && docs.length && !confirm("เปลี่ยนโมเดล embedding จะสร้างดัชนีเอกสารทั้งหมดใหม่ (มีค่าใช้จ่ายเล็กน้อย) ต่อเลยไหม?")) return;
    const r = await postJSON(`${PAGE.apiBase}chats/${chatId}/settings/`, { embed_model: em, top_k: Number($("#topk").value) });
    if (!r.ok) return toast(r.error || "บันทึกไม่สำเร็จ", "error");
    embedModel = r.embed_model; modal.classList.remove("open");
    toast(r.reindexed ? `บันทึกแล้ว — กำลังสร้างดัชนีใหม่ ${r.reindexed} เอกสาร` : "บันทึกแล้ว");
    if (r.reindexed) { docs.forEach((d) => { if (d.status !== "error") { d.status = "processing"; d.progress = 30; } }); }
    renderDocs();
  });

  // mobile: toggle docs panel
  $("#docsToggle").addEventListener("click", () => document.body.classList.toggle("docs-open"));
  $("#docsClose").addEventListener("click", () => document.body.classList.remove("docs-open"));

  bindSidebar($("#chatList"), PAGE.apiBase + "chats/", () => chatId, PAGE.indexUrl, { confirmDelete: "ลบแชทนี้พร้อมเอกสารทั้งหมด?" });
})();
