/* Uncle Super App — Data Analyst
 * Developed by Uncle Engineer — https://uncle-engineer.com/
 */
(function () {
  const { $, $$, esc, toast, renderMarkdown, renderResults, streamSSE, bindSidebar, sidebarItem, autosize, fileIcon, fmtBytes, copyText } = window.Convo;
  const scroller = $("#chatScroll"), inner = $("#chatInner"), input = $("#input"), form = $("#composer"), sendBtn = $("#sendBtn");
  const fileInput = $("#fileInput");
  let sessionId = PAGE.sessionId;
  let currentModel = PAGE.currentModel;
  let files = JSON.parse($("#anFiles").textContent || "[]");
  const savedResults = JSON.parse($("#anResults").textContent || "{}");
  let controller = null;

  const scrollBottom = (force) => { if (force || scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 200) scroller.scrollTop = scroller.scrollHeight; };

  // ---------- render history ----------
  $$(".msg-assistant").forEach((m) => {
    const c = $(".msg-content", m); const raw = c.textContent; c.dataset.raw = raw;
    renderMarkdown(c, raw);
    const res = savedResults[m.dataset.msgId];
    if (res) renderResults($(".msg-body", m).insertBefore(document.createElement("div"), c), res);
  });
  inner.addEventListener("click", (e) => {
    const b = e.target.closest("[data-copy]");
    if (b) { const c = b.closest(".msg-body").querySelector(".msg-content"); copyText(c.dataset.raw || c.innerText, b); }
  });
  scrollBottom(true);

  // ---------- model picker ----------
  const picker = new ModelPicker({ url: PAGE.modelsUrl, current: currentModel, onSelect: (m) => setModel(m.id) });
  function setModel(id) {
    currentModel = id; picker.current = id;
    const m = picker.get(id);
    $("#modelName").textContent = m ? m.name : id; $("#modelId").textContent = id;
    const tag = $("#modelTag");
    tag.textContent = m && m.is_free ? "FREE" : ""; tag.className = "model-tag" + (m && m.is_free ? " free" : "");
    const hasImg = files.some((f) => f.kind === "image");
    const vision = m && (m.input_modalities || []).includes("image");
    $("#visionHint").textContent = hasImg && m && !vision ? "⚠ โมเดลนี้อ่านรูปภาพไม่ได้ — เลือกโมเดลที่มีป้าย 👁 vision" : "";
  }
  $("#modelBtn").addEventListener("click", () => picker.open());
  picker.load().then(() => setModel(currentModel)).catch(() => {});

  // ---------- files ----------
  function renderFiles() {
    $("#fileBar").hidden = !files.length;
    $("#fileChips").innerHTML = files.map((f) => {
      let meta = fmtBytes(f.size);
      if (f.kind === "table") meta = (f.meta.sheets || []).map((s) => `${s.name.replace(/^ชีต /, "")}: ${s.rows.toLocaleString()} แถว × ${s.columns.length} คอลัมน์`).join(" · ");
      else if (f.kind === "text") meta = `${(f.meta.chars || 0).toLocaleString()} ตัวอักษร${f.meta.pages ? ` · ${f.meta.pages} หน้า` : ""}`;
      const warn = (f.meta.warnings || []).length ? `<span class="warn-dot" title="${esc(f.meta.warnings.join("\n"))}">!</span>` : "";
      return `<div class="file-chip" data-id="${f.id}" title="${esc(f.name)}">${fileIcon(f.name)}<div class="fc-text"><b>${esc(f.name)}</b><span>${esc(meta)}</span></div>${warn}<button type="button" class="icon-btn xs" data-remove title="เอาไฟล์ออก">×</button></div>`;
    }).join("");
    if (picker.models.length) setModel(currentModel);
  }
  renderFiles();
  $("#fileChips").addEventListener("click", async (e) => {
    const b = e.target.closest("[data-remove]"); if (!b) return;
    const chip = b.closest(".file-chip");
    if (!confirm("เอาไฟล์นี้ออกจากการวิเคราะห์?")) return;
    const r = await Convo.postJSON(`${PAGE.apiBase}files/${chip.dataset.id}/delete/`);
    if (r.ok) { files = files.filter((f) => String(f.id) !== chip.dataset.id); renderFiles(); }
  });

  async function upload(list) {
    const arr = [...list];
    if (!arr.length) return;
    const tooBig = arr.filter((f) => f.size > PAGE.maxMb * 1048576);
    if (tooBig.length) toast(`${tooBig.map((f) => f.name).join(", ")} ใหญ่เกิน ${PAGE.maxMb} MB`, "error");
    const ok = arr.filter((f) => f.size <= PAGE.maxMb * 1048576);
    if (!ok.length) return;
    const fd = new FormData();
    ok.forEach((f) => fd.append("files", f, f.name));
    if (sessionId) fd.append("session_id", sessionId);
    const t = toastProgress(`กำลังอัปโหลดและอ่าน ${ok.length} ไฟล์…`);
    try {
      const r = await fetch(PAGE.uploadUrl, { method: "POST", body: fd, headers: { "X-CSRFToken": PAGE.csrf }, credentials: "same-origin" });
      const d = await r.json().catch(() => ({ error: `HTTP ${r.status}` }));
      t.remove();
      (d.errors || []).forEach((e) => toast(e, "error", 6000));
      if (d.error && !d.files) return toast(d.error, "error");
      if (!d.files || !d.files.length) return;
      if (!sessionId) {
        sessionId = d.session_id;
        history.replaceState(null, "", d.url);
        const list = $("#sessList"); const emp = $(".conv-empty", list); if (emp) emp.remove();
        $$(".conv-item", list).forEach((li) => li.classList.remove("active"));
        list.insertAdjacentHTML("afterbegin", sidebarItem(d.session_id, d.session_title, d.url));
      }
      files = files.concat(d.files);
      const hero = $("#hero"); if (hero) hero.remove();
      renderFiles();
      input.placeholder = "ถามอะไรก็ได้เกี่ยวกับข้อมูล เช่น สาขาไหนยอดขายโตเร็วที่สุด";
      if (!$$(".msg").length) $("#suggestRow").hidden = false;
      toast(`อัปโหลดแล้ว ${d.files.length} ไฟล์ — พร้อมวิเคราะห์`);
      input.focus();
    } catch (err) { t.remove(); toast(String(err), "error"); }
  }
  function toastProgress(msg) {
    let box = document.getElementById("toasts");
    if (!box) { box = document.createElement("div"); box.id = "toasts"; box.className = "toasts"; document.body.appendChild(box); }
    const el = document.createElement("div"); el.className = "toast"; el.innerHTML = `<span class="spinner"></span> ${esc(msg)}`; box.appendChild(el); return el;
  }
  fileInput.addEventListener("change", () => { upload(fileInput.files); fileInput.value = ""; });
  ["#addFileBtn", "#attachBtn"].forEach((s) => $(s).addEventListener("click", () => fileInput.click()));
  const big = $("#bigDrop"); if (big) big.addEventListener("click", () => fileInput.click());
  // ลากวางได้ทั้งหน้า
  const overlay = $("#dropOverlay"); let dragDepth = 0;
  document.addEventListener("dragenter", (e) => { if ([...(e.dataTransfer?.types || [])].includes("Files")) { dragDepth++; overlay.hidden = false; } });
  document.addEventListener("dragleave", () => { dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) overlay.hidden = true; });
  document.addEventListener("dragover", (e) => e.preventDefault());
  document.addEventListener("drop", (e) => { e.preventDefault(); dragDepth = 0; overlay.hidden = true; if (e.dataTransfer.files.length) upload(e.dataTransfer.files); });

  // ---------- ask ----------
  const resize = autosize(input);
  input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); form.requestSubmit(); } });
  $$("#suggestRow .chip").forEach((c) => c.addEventListener("click", () => { input.value = c.dataset.prompt; form.requestSubmit(); }));
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (controller) { controller.abort(); return; }
    const q = input.value.trim(); if (!q) return;
    if (!files.length) { toast("อัปโหลดไฟล์ก่อนเริ่มวิเคราะห์", "error"); fileInput.click(); return; }
    ask(q);
  });

  function addMsg(role, text) {
    const w = document.createElement("div"); w.className = `msg msg-${role}`;
    const avatar = role === "assistant" ? '<div class="msg-avatar"><svg viewBox="0 0 32 32"><path d="M10 9v8a6 6 0 0 0 12 0V9" stroke="currentColor" stroke-width="3.2" fill="none" stroke-linecap="round"/></svg></div>' : "";
    w.innerHTML = `${avatar}<div class="msg-body">${role === "assistant" ? `<div class="msg-meta">${esc(currentModel)}</div><div class="an-slot"></div><div class="an-status"><span class="spinner"></span> <span>กำลังเริ่ม…</span></div>` : ""}<div class="msg-content ${role === "assistant" ? "md" : ""}"></div>${role === "assistant" ? '<div class="msg-tools"><button class="tool-btn" data-copy>คัดลอกข้อความ</button></div>' : ""}</div>`;
    if (role === "user") $(".msg-content", w).textContent = text;
    inner.appendChild(w); scrollBottom(true);
    return w;
  }

  async function ask(q) {
    input.value = ""; resize(); $("#suggestRow").hidden = true;
    addMsg("user", q);
    const bot = addMsg("assistant");
    const content = $(".msg-content", bot), status = $(".an-status", bot);
    controller = new AbortController();
    sendBtn.classList.add("stop"); input.disabled = true;
    let full = "", raf = null;
    const paint = (final) => { raf = null; renderMarkdown(content, full, { final }); content.dataset.raw = full; scrollBottom(); };
    try {
      await streamSSE(PAGE.askUrl, { session_id: sessionId, message: q, model: currentModel }, (ev) => {
        if (ev.type === "status") $("span:last-child", status).textContent = ev.text;
        else if (ev.type === "results") { renderResults($(".an-slot", bot), ev); scrollBottom(); }
        else if (ev.type === "delta") { full += ev.content; status.hidden = true; if (!raf) raf = requestAnimationFrame(() => paint(false)); }
        else if (ev.type === "error") content.insertAdjacentHTML("beforeend", `<div class="err-box">⚠ ${esc(ev.message)}</div>`);
      }, controller.signal);
      if (raf) cancelAnimationFrame(raf);
      if (full) paint(true);
    } catch (err) {
      if (err.name !== "AbortError") content.insertAdjacentHTML("beforeend", `<div class="err-box">⚠ ${esc(err.message || err)}</div>`);
      else if (full) paint(true);
    } finally {
      status.hidden = true; controller = null;
      sendBtn.classList.remove("stop"); input.disabled = false; input.focus();
      const li = $(`#sessList [data-id="${sessionId}"]`); if (li && li !== li.parentElement.firstElementChild) li.parentElement.prepend(li);
    }
  }

  bindSidebar($("#sessList"), PAGE.apiBase + "sessions/", () => sessionId, PAGE.indexUrl, { confirmDelete: "ลบการวิเคราะห์นี้พร้อมไฟล์ทั้งหมด?" });
})();
