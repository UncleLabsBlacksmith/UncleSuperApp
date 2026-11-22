/* Uncle Super App — Image Generator + Gallery
 * Developed by Uncle Engineer — https://uncle-engineer.com/
 */
(function () {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : d; } catch (_) { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (_) {} },
  };

  async function postJSON(url, data) {
    try {
      const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json", "X-CSRFToken": IMG.csrf }, body: JSON.stringify(data || {}), credentials: "same-origin" });
      const d = await r.json().catch(() => ({}));
      return { ok: r.ok && d.ok !== false, ...d };
    } catch (e) { return { ok: false, error: String(e) }; }
  }
  function toast(msg, kind = "success") {
    let box = document.getElementById("toasts");
    if (!box) { box = document.createElement("div"); box.id = "toasts"; box.className = "toasts"; document.body.appendChild(box); }
    const t = document.createElement("div");
    t.className = `toast toast-${kind}`; t.textContent = msg; box.appendChild(t);
    setTimeout(() => t.classList.add("hide"), 2800); setTimeout(() => t.remove(), 3500);
  }
  const fmtUsd = (p) => (p === null || p === undefined ? "—" : p === 0 ? "ฟรี" : p < 0.01 ? "$" + p.toFixed(4) : "$" + p.toFixed(3).replace(/0$/, ""));

  // =====================================================================
  // Lightbox (ใช้ทั้งหน้า Generator และ Gallery)
  // =====================================================================
  const lb = $("#lightbox");
  let lbTile = null;
  function openLightbox(tile) {
    lbTile = tile;
    const d = tile.dataset;
    $("#lbImg").src = d.full;
    $("#lbPrompt").textContent = d.prompt;
    let params = {};
    try { params = JSON.parse(d.params || "{}"); } catch (_) {}
    $("#lbMeta").innerHTML =
      `<span class="pill mono">${esc(d.model)}</span>` +
      Object.entries(params).map(([k, v]) => `<span class="pill">${esc(k)}: <b>${esc(v)}</b></span>`).join("") +
      `<span class="muted small">${esc(d.date)}</span>`;
    $("#lbDownload").href = d.download;
    $("#lbSession").href = d.session;
    $("#lbSession").hidden = IMG.page === "generate";
    lb.classList.add("open");
    lb.setAttribute("aria-hidden", "false");
  }
  function closeLightbox() { lb.classList.remove("open"); lb.setAttribute("aria-hidden", "true"); lbTile = null; }
  $$("[data-close-lightbox]").forEach((el) => el.addEventListener("click", closeLightbox));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && lb.classList.contains("open")) closeLightbox(); });

  async function deleteImage(tile) {
    if (!confirm("ลบภาพนี้? ไม่สามารถกู้คืนได้")) return false;
    const r = await postJSON(`${IMG.apiUrl}images/${tile.dataset.imageId}/delete/`);
    if (!r.ok) { toast(r.error || "ลบไม่สำเร็จ", "error"); return false; }
    $$(`.img-tile[data-image-id="${tile.dataset.imageId}"]`).forEach((t) => t.remove());
    toast("ลบภาพแล้ว");
    return true;
  }

  function useAsRef(tile) {
    if (IMG.page === "generate" && window.__addGalleryRef) window.__addGalleryRef(Number(tile.dataset.imageId), tile.dataset.full);
    else window.location.href = `${IMG.indexUrl}?ref=${tile.dataset.imageId}`;
  }
  function usePrompt(prompt, model, params) {
    if (IMG.page === "generate" && window.__applyPrompt) window.__applyPrompt(prompt, model, params);
    else window.location.href = `${IMG.indexUrl}?prompt=${encodeURIComponent(prompt)}&model=${encodeURIComponent(model)}`;
  }

  $("#lbRef").addEventListener("click", () => { if (lbTile) { useAsRef(lbTile); closeLightbox(); } });
  $("#lbPromptBtn").addEventListener("click", () => {
    if (!lbTile) return;
    let params = {}; try { params = JSON.parse(lbTile.dataset.params || "{}"); } catch (_) {}
    usePrompt(lbTile.dataset.prompt, lbTile.dataset.model, params); closeLightbox();
  });
  $("#lbDelete").addEventListener("click", async () => { if (lbTile && (await deleteImage(lbTile))) closeLightbox(); });

  document.addEventListener("click", (e) => {
    const tile = e.target.closest(".img-tile");
    if (!tile) return;
    const act = e.target.closest("[data-act]");
    if (act) {
      e.preventDefault();
      if (act.dataset.act === "delete") deleteImage(tile);
      else if (act.dataset.act === "ref") useAsRef(tile);
      return;
    }
    if (e.target.closest("a")) return; // ปุ่มดาวน์โหลด
    openLightbox(tile);
  });

  if (IMG.page !== "generate") return;

  // =====================================================================
  // Image Generator
  // =====================================================================
  const form = $("#igForm");
  const promptEl = $("#igPrompt");
  const feed = $("#igFeed");
  const genBtn = $("#genBtn");
  const advBody = $("#advBody");
  const refThumbs = $("#refThumbs");
  const refInput = $("#refInput");
  const dropzone = $("#dropzone");
  let sessionId = IMG.sessionId;
  let models = [];
  let canUsePaid = true;
  let role = "";
  let model = null;
  let refs = []; // {kind:'file', file, url} | {kind:'gallery', id, url}
  let busy = false;

  // ---------- Model picker ----------
  const picker = {
    modal: $("#imgModelModal"), list: $("#imgModelList"), count: $("#imgModelCount"),
    search: $("#imgModelSearch"), sort: $("#imgModelSort"), prov: $("#imgProviderFilter"),
    state: { q: "", filter: "all", sort: "popular", provider: "" },
    open() { this.modal.classList.add("open"); this.render(); setTimeout(() => this.search.focus(), 50); const s = $(".selected", this.list); if (s) s.scrollIntoView({ block: "center" }); },
    close() { this.modal.classList.remove("open"); },
    filtered() {
      const { q, filter, sort, provider } = this.state;
      let arr = models.filter((m) => {
        if (filter === "edit" && !(m.refs_max > 0)) return false;
        if (filter === "free" && !m.is_free) return false;
        if (provider && m.provider !== provider) return false;
        if (q && !(m.name.toLowerCase().includes(q) || m.id.toLowerCase().includes(q))) return false;
        return true;
      });
      const price = (m, empty) => (m.price === null || m.price === undefined ? empty : m.price);
      const by = {
        price_asc: (a, b) => price(a, Infinity) - price(b, Infinity) || a.name.localeCompare(b.name),
        price_desc: (a, b) => price(b, -1) - price(a, -1) || a.name.localeCompare(b.name),
        newest: (a, b) => (b.created || 0) - (a.created || 0),
        name: (a, b) => a.name.localeCompare(b.name),
      }[sort];
      return by ? [...arr].sort(by) : arr;
    },
    render() {
      const arr = this.filtered();
      this.count.textContent = `แสดง ${arr.length} จาก ${models.length} โมเดลสร้างภาพ` + (canUsePaid ? "" : ` · บัญชี ${role} ใช้ได้เฉพาะโมเดลฟรี`);
      if (!arr.length) { this.list.innerHTML = '<div class="empty">ไม่พบโมเดลที่ตรงกับเงื่อนไข</div>'; return; }
      this.list.innerHTML = arr.map((m) => {
        const locked = !canUsePaid && !m.is_free;
        const refs = m.refs_max > 0 ? `<span class="mono">${m.refs_min ? m.refs_min + "–" : "≤ "}${m.refs_max}</span>` : '<span class="muted">—</span>';
        const price = m.is_free ? '<span class="badge badge-free">FREE</span>'
          : m.price === null ? '<span class="price muted">ไม่ระบุ</span>'
          : `<span class="price">${m.price_variants ? '<i>เริ่ม</i>' : ""}${m.price_estimated ? "≈" : ""}<b>${fmtUsd(m.price)}</b></span>`;
        return `<div class="model-row ${model && m.id === model.id ? "selected" : ""} ${locked ? "locked" : ""}" data-id="${esc(m.id)}" title="${esc(m.description)}">
          <div class="mr-main"><div class="mr-name">${esc(m.name)} ${locked ? '<span class="badge badge-lock">🔒 Pro</span>' : ""}</div><div class="mr-id">${esc(m.id)}</div></div>
          <div class="mr-ctx">${refs}</div><div class="mr-price">${price}</div></div>`;
      }).join("");
    },
  };
  picker.modal.querySelectorAll("[data-close-modal]").forEach((el) => el.addEventListener("click", () => picker.close()));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && picker.modal.classList.contains("open")) picker.close(); });
  picker.search.addEventListener("input", () => { picker.state.q = picker.search.value.trim().toLowerCase(); picker.render(); });
  picker.sort.addEventListener("change", () => { picker.state.sort = picker.sort.value; picker.render(); });
  picker.prov.addEventListener("change", () => { picker.state.provider = picker.prov.value; picker.render(); });
  $$("#imgModelFilter button").forEach((b) => b.addEventListener("click", () => {
    $$("#imgModelFilter button").forEach((x) => x.classList.remove("active")); b.classList.add("active");
    picker.state.filter = b.dataset.filter; picker.render();
  }));
  picker.list.addEventListener("click", (e) => {
    const row = e.target.closest(".model-row");
    if (!row || row.classList.contains("locked")) return;
    selectModel(row.dataset.id); picker.close();
  });
  $("#imgModelBtn").addEventListener("click", () => picker.open());

  fetch(IMG.modelsUrl, { credentials: "same-origin" }).then((r) => r.json()).then((d) => {
    if (d.error) throw new Error(d.error);
    models = d.models || []; canUsePaid = d.can_use_paid; role = d.role;
    const provs = [...new Set(models.map((m) => m.provider).filter(Boolean))].sort();
    picker.prov.innerHTML = '<option value="">ทุกผู้ให้บริการ</option>' + provs.map((p) => `<option>${esc(p)}</option>`).join("");
    if (!canUsePaid && !models.some((m) => m.is_free)) {
      $("#roleBanner").hidden = false;
      $("#roleBannerText").textContent = `บัญชีประเภท ${role} ใช้ได้เฉพาะโมเดลฟรี ซึ่งตอนนี้ OpenRouter ยังไม่มีโมเดลสร้างภาพฟรี — ติดต่อผู้ดูแลเพื่ออัปเกรดเป็น Pro`;
    }
    const usable = (m) => m && (canUsePaid || m.is_free);
    const initial = [IMG.currentModel, store.get("ig:model", "")].map((id) => models.find((m) => m.id === id)).find(usable)
      || models.find((m) => m.id === "google/gemini-2.5-flash-image" && usable(m)) || models.find(usable);
    if (initial) selectModel(initial.id); else picker.render();
  }).catch((err) => {
    picker.list.innerHTML = `<div class="empty error">${esc(err.message || err)}</div>`;
    picker.count.textContent = "โหลดไม่สำเร็จ";
    $("#imgModelName").textContent = "โหลดรายชื่อโมเดลไม่สำเร็จ";
  });

  function selectModel(id, presetParams) {
    model = models.find((m) => m.id === id) || null;
    if (!model) return;
    store.set("ig:model", id);
    $("#imgModelName").textContent = model.name;
    $("#imgModelId").textContent = model.id;
    const tag = $("#imgModelTag");
    tag.className = "model-tag" + (model.is_free ? " free" : "");
    tag.textContent = model.is_free ? "FREE" : model.price !== null ? `${model.price_estimated ? "≈" : ""}${fmtUsd(model.price)}/ภาพ` : "";
    renderParams(presetParams);
    renderRefs();
    updateCost();
  }

  // ---------- Advanced parameters ----------
  const LABELS = {
    aspect_ratio: ["สัดส่วนภาพ (Aspect ratio)", ""],
    resolution: ["ความละเอียด (Resolution)", "ขนาดพิกเซลจริงขึ้นกับผู้ให้บริการ"],
    size: ["ขนาดภาพ (Size)", "เช่น 1024x1024 หรือ 2K — บางโมเดลใช้ร่วมกับ ratio/resolution ไม่ได้"],
    quality: ["คุณภาพ (Quality)", ""],
    n: ["จำนวนภาพ", ""],
    output_format: ["ไฟล์ผลลัพธ์", ""],
    background: ["พื้นหลัง", "transparent ต้องใช้ png หรือ webp"],
    output_compression: ["การบีบอัด (%)", "ใช้กับ jpeg / webp"],
    seed: ["Seed", "ใส่เลขเดิมเพื่อให้ได้ผลใกล้เคียงเดิม (ถ้าโมเดลรองรับ)"],
  };
  const ORDER = ["aspect_ratio", "resolution", "size", "quality", "n", "output_format", "background", "output_compression", "seed"];

  function ratioBox(v) {
    const m = String(v).match(/^([\d.]+):([\d.]+)$/);
    if (!m) return '<span class="ratio-shape auto">A</span>';
    let w = parseFloat(m[1]), h = parseFloat(m[2]);
    const s = 18 / Math.max(w, h); w = Math.max(4, w * s); h = Math.max(4, h * s);
    return `<span class="ratio-shape" style="width:${w.toFixed(1)}px;height:${h.toFixed(1)}px"></span>`;
  }
  function renderParams(preset) {
    if (!model) return;
    const saved = preset || store.get("ig:params", {});
    const spec = model.params || {};
    const keys = ORDER.filter((k) => spec[k]);
    if (!keys.length) { advBody.innerHTML = '<div class="muted small">โมเดลนี้ไม่มีพารามิเตอร์เพิ่มเติม</div>'; return; }
    advBody.innerHTML = keys.map((k) => {
      const d = spec[k], [label, help] = LABELS[k] || [k, ""];
      const val = saved[k] !== undefined ? String(saved[k]) : "";
      let control = "";
      if (k === "aspect_ratio" && d.type === "enum") {
        const def = val && d.values.map(String).includes(val) ? val : d.values.map(String).includes("1:1") ? "1:1" : "";
        control = `<div class="ratio-grid" data-param="${k}" data-kind="choice">` +
          d.values.map((v) => `<button type="button" class="ratio-btn ${String(v) === def ? "active" : ""}" data-value="${esc(v)}">${ratioBox(v)}<span>${esc(v === "auto" ? "อัตโนมัติ" : v)}</span></button>`).join("") + "</div>";
      } else if (d.type === "enum" && d.values.length <= 6 && ["resolution", "quality"].includes(k)) {
        control = `<div class="segmented wrap" data-param="${k}" data-kind="choice"><button type="button" data-value="" class="${val ? "" : "active"}">ค่าเริ่มต้น</button>` +
          d.values.map((v) => `<button type="button" data-value="${esc(v)}" class="${String(v) === val ? "active" : ""}">${esc(v)}</button>`).join("") + "</div>";
      } else if (d.type === "enum") {
        control = `<select class="input select sm" data-param="${k}"><option value="">ค่าเริ่มต้น</option>` +
          d.values.map((v) => `<option ${String(v) === val ? "selected" : ""}>${esc(v)}</option>`).join("") + "</select>";
      } else if (d.type === "range" && k === "n") {
        if ((d.max || 1) <= 1) return "";
        const v = val ? Math.min(d.max, Math.max(d.min || 1, Number(val))) : d.min || 1;
        control = `<div class="stepper" data-param="n"><button type="button" data-step="-1">−</button><input type="number" class="input sm" min="${d.min || 1}" max="${d.max}" value="${v}"><button type="button" data-step="1">+</button><span class="muted small">สูงสุด ${d.max}</span></div>`;
      } else if (d.type === "range") {
        const v = val || "";
        control = `<div class="range-row"><input type="range" data-param="${k}" min="${d.min ?? 0}" max="${d.max ?? 100}" value="${v || d.max || 100}" data-touched="${v ? 1 : 0}"><output>${v || "ค่าเริ่มต้น"}</output></div>`;
      } else if (k === "seed") {
        control = `<div class="input-group"><input type="number" class="input sm" data-param="seed" placeholder="สุ่ม (ไม่กำหนด)" value="${esc(val)}"><button type="button" class="btn btn-ghost sm" data-random-seed>🎲</button></div>`;
      } else {
        control = `<input type="text" class="input sm" data-param="${k}" placeholder="${k === "size" ? "เช่น 1024x1024" : ""}" value="${esc(val)}">`;
      }
      return `<div class="adv-field"><label>${esc(label)}</label>${control}${help ? `<div class="help">${esc(help)}</div>` : ""}</div>`;
    }).join("");
  }
  advBody.addEventListener("click", (e) => {
    const choice = e.target.closest("[data-kind=choice] button");
    if (choice) {
      const group = choice.parentElement;
      const wasActive = choice.classList.contains("active");
      $$("button", group).forEach((b) => b.classList.remove("active"));
      if (!(wasActive && group.classList.contains("ratio-grid"))) choice.classList.add("active"); // คลิกซ้ำ ratio = ยกเลิก
      saveParams(); updateCost(); return;
    }
    const step = e.target.closest("[data-step]");
    if (step) {
      const inp = $("input", step.parentElement);
      inp.value = Math.min(Number(inp.max), Math.max(Number(inp.min), Number(inp.value || 1) + Number(step.dataset.step)));
      saveParams(); updateCost(); return;
    }
    if (e.target.closest("[data-random-seed]")) { $("[data-param=seed]", advBody).value = Math.floor(Math.random() * 2 ** 31); saveParams(); }
  });
  advBody.addEventListener("input", (e) => {
    if (e.target.type === "range") { e.target.dataset.touched = 1; e.target.nextElementSibling.textContent = e.target.value; }
    saveParams(); updateCost();
  });
  function collectParams() {
    const out = {};
    $$("[data-param]", advBody).forEach((el) => {
      const k = el.dataset.param;
      let v = "";
      if (el.dataset.kind === "choice") { const a = $("button.active", el); v = a ? a.dataset.value : ""; }
      else if (k === "n") v = $("input", el).value;
      else if (el.type === "range") v = el.dataset.touched === "1" ? el.value : "";
      else v = el.value.trim();
      if (v !== "" && v !== undefined) out[k] = ["n", "seed", "output_compression"].includes(k) ? Number(v) : v;
    });
    return out;
  }
  function saveParams() { store.set("ig:params", { ...store.get("ig:params", {}), ...collectParams() }); }
  function updateCost() {
    const el = $("#costEst");
    if (!model) { el.textContent = ""; return; }
    const n = collectParams().n || 1;
    if (model.is_free) el.innerHTML = '<span class="badge badge-free">FREE</span>';
    else if (model.price === null) el.textContent = "ราคา: ดูที่ OpenRouter";
    else el.innerHTML = `ค่าใช้จ่ายโดยประมาณ <b>${model.price_variants ? "เริ่ม " : ""}${model.price_estimated ? "≈" : ""}${fmtUsd(model.price * n)}</b>${n > 1 ? ` <span class="muted">(${n} ภาพ)</span>` : ""}`;
  }

  // ---------- Reference images ----------
  function renderRefs() {
    const max = model ? model.refs_max : 0, min = model ? model.refs_min : 0;
    $("#refHint").textContent = !model ? "" : max === 0 ? "· โมเดลนี้ไม่รองรับ" : `· ${refs.length} / ${max}${min ? ` (ต้องมีอย่างน้อย ${min})` : ""}`;
    dropzone.classList.toggle("disabled", !!model && max === 0);
    refThumbs.innerHTML = refs.map((r, i) => `<div class="ref-thumb ${model && i >= max ? "over" : ""}"><img src="${r.url}" alt=""><button type="button" data-remove="${i}" title="เอาออก">×</button>${r.kind === "gallery" ? '<span class="ref-tag">gallery</span>' : ""}</div>`).join("");
  }
  function addFiles(files) {
    const ok = ["image/png", "image/jpeg", "image/webp", "image/gif"];
    for (const f of files) {
      if (!ok.includes(f.type)) { toast(`${f.name}: ไม่ใช่ไฟล์ภาพที่รองรับ`, "error"); continue; }
      if (f.size > 8 * 1024 * 1024) { toast(`${f.name}: ใหญ่เกิน 8 MB`, "error"); continue; }
      refs.push({ kind: "file", file: f, url: URL.createObjectURL(f) });
    }
    if (model && refs.length > model.refs_max) toast(`โมเดลนี้รับภาพอ้างอิงได้สูงสุด ${model.refs_max} ภาพ`, "error");
    renderRefs();
  }
  window.__addGalleryRef = (id, url) => {
    if (refs.some((r) => r.kind === "gallery" && r.id === id)) return;
    refs.push({ kind: "gallery", id, url }); renderRefs();
    toast("เพิ่มเป็นภาพอ้างอิงแล้ว"); promptEl.focus();
  };
  if (IMG.prefillRef) refs.push({ kind: "gallery", id: IMG.prefillRef.id, url: IMG.prefillRef.src });
  renderRefs();

  dropzone.addEventListener("click", () => { if (!dropzone.classList.contains("disabled")) refInput.click(); });
  dropzone.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); refInput.click(); } });
  refInput.addEventListener("change", () => { addFiles(refInput.files); refInput.value = ""; });
  ["dragenter", "dragover"].forEach((ev) => dropzone.addEventListener(ev, (e) => { e.preventDefault(); dropzone.classList.add("drag"); }));
  ["dragleave", "drop"].forEach((ev) => dropzone.addEventListener(ev, (e) => { e.preventDefault(); dropzone.classList.remove("drag"); }));
  dropzone.addEventListener("drop", (e) => addFiles(e.dataTransfer.files));
  document.addEventListener("paste", (e) => {
    const files = [...(e.clipboardData?.items || [])].filter((i) => i.kind === "file").map((i) => i.getAsFile()).filter(Boolean);
    if (files.length) { e.preventDefault(); addFiles(files); }
  });
  refThumbs.addEventListener("click", (e) => {
    const b = e.target.closest("[data-remove]");
    if (!b) return;
    const r = refs.splice(Number(b.dataset.remove), 1)[0];
    if (r && r.kind === "file") URL.revokeObjectURL(r.url);
    renderRefs();
  });

  // ---------- Reuse prompt ----------
  window.__applyPrompt = (prompt, modelId, params) => {
    promptEl.value = prompt;
    if (modelId && models.some((m) => m.id === modelId)) selectModel(modelId, params);
    else if (params) renderParams(params);
    updateCost();
    promptEl.focus();
    window.scrollTo({ top: 0, behavior: "smooth" });
    toast("นำ prompt และการตั้งค่ามาใช้แล้ว");
  };
  feed.addEventListener("click", (e) => {
    const b = e.target.closest("[data-reuse]");
    if (!b) return;
    const card = b.closest(".gen-card");
    let params = {}; try { params = JSON.parse(card.dataset.params || "{}"); } catch (_) {}
    window.__applyPrompt(card.dataset.prompt, card.dataset.model, params);
  });

  // ---------- Generate ----------
  promptEl.addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); form.requestSubmit(); } });
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (busy) return;
    const prompt = promptEl.value.trim();
    if (!model) { picker.open(); return; }
    if (!prompt) { promptEl.focus(); toast("กรุณาพิมพ์ prompt", "error"); return; }
    if (refs.length > model.refs_max) { toast(model.refs_max ? `โมเดลนี้รับภาพอ้างอิงได้สูงสุด ${model.refs_max} ภาพ` : "โมเดลนี้ไม่รองรับภาพอ้างอิง — เอาภาพออกหรือเปลี่ยนโมเดล", "error"); return; }
    if (refs.length < model.refs_min) { toast(`โมเดลนี้ต้องมีภาพอ้างอิงอย่างน้อย ${model.refs_min} ภาพ`, "error"); return; }

    const params = collectParams();
    const fd = new FormData();
    fd.append("prompt", prompt);
    fd.append("model", model.id);
    if (sessionId) fd.append("session_id", sessionId);
    fd.append("params", JSON.stringify(params));
    refs.filter((r) => r.kind === "file").forEach((r) => fd.append("references", r.file, r.file.name));
    fd.append("ref_image_ids", refs.filter((r) => r.kind === "gallery").map((r) => r.id).join(","));

    const empty = $("#igEmpty"); if (empty) empty.remove();
    const n = params.n || 1;
    const ratio = String(params.aspect_ratio || "1:1").match(/^([\d.]+):([\d.]+)$/);
    const ar = ratio ? `${ratio[1]} / ${ratio[2]}` : "1 / 1";
    const pending = document.createElement("article");
    pending.className = "gen-card pending";
    pending.innerHTML = `<header class="gen-head"><p class="gen-prompt">${esc(prompt)}</p><div class="gen-meta"><span class="pill mono">${esc(model.id)}</span><span class="pill"><span class="spinner"></span> กำลังสร้างภาพ… <b class="elapsed">0s</b></span></div></header>
      <div class="gen-images count-${Math.min(n, 4)}">${Array.from({ length: Math.min(n, 4) }, () => `<div class="skeleton" style="aspect-ratio:${ar}"></div>`).join("")}</div>`;
    feed.prepend(pending);
    feed.scrollTop = 0;
    const t0 = Date.now();
    const timer = setInterval(() => { $(".elapsed", pending).textContent = Math.round((Date.now() - t0) / 1000) + "s"; }, 500);
    busy = true; genBtn.disabled = true; genBtn.classList.add("loading");

    try {
      const r = await fetch(IMG.generateUrl, { method: "POST", body: fd, headers: { "X-CSRFToken": IMG.csrf }, credentials: "same-origin" });
      const d = await r.json().catch(() => ({ error: `HTTP ${r.status}` }));
      if (d.html) {
        pending.insertAdjacentHTML("afterend", d.html);
        pending.remove();
        if (d.is_new || !sessionId) addSession(d.session_id, d.session_title);
        else bumpSession(sessionId);
        sessionId = d.session_id;
        if (d.ok) toast("สร้างภาพเสร็จแล้ว"); else toast(d.error || "สร้างภาพไม่สำเร็จ", "error");
      } else {
        pending.classList.add("is-error");
        pending.querySelector(".gen-images").outerHTML = `<div class="err-box">⚠ ${esc(d.error || "เกิดข้อผิดพลาด")}</div>`;
        $(".gen-meta .pill:last-child", pending).remove();
      }
    } catch (err) {
      pending.classList.add("is-error");
      pending.querySelector(".gen-images").outerHTML = `<div class="err-box">⚠ ${esc(err.message || err)}</div>`;
    } finally {
      clearInterval(timer);
      busy = false; genBtn.disabled = false; genBtn.classList.remove("loading");
    }
  });

  // ---------- Sidebar history ----------
  const sessList = $("#sessList");
  function addSession(id, title) {
    history.replaceState(null, "", `${IMG.sessionUrl}${id}/`);
    document.title = `${title} · Image Generator · Uncle Super App`;
    const emptyLi = $(".conv-empty", sessList); if (emptyLi) emptyLi.remove();
    $$(".conv-item", sessList).forEach((li) => li.classList.remove("active"));
    sessList.insertAdjacentHTML("afterbegin", `<li class="conv-item active" data-id="${id}"><a href="${IMG.sessionUrl}${id}/" class="conv-link" title="${esc(title)}">${esc(title)}</a>
      <div class="conv-actions"><button class="icon-btn xs" data-rename title="เปลี่ยนชื่อ"><svg viewBox="0 0 24 24"><path d="M12 20h9M16.5 3.5a2.1 2.1 0 1 1 3 3L7 19l-4 1 1-4z"/></svg></button>
      <button class="icon-btn xs danger" data-delete title="ลบ"><svg viewBox="0 0 24 24"><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/></svg></button></div></li>`);
  }
  function bumpSession(id) { const li = $(`[data-id="${id}"]`, sessList); if (li && li !== sessList.firstElementChild) sessList.prepend(li); }
  sessList.addEventListener("click", async (e) => {
    const li = e.target.closest(".conv-item"); if (!li) return;
    const id = li.dataset.id;
    if (e.target.closest("[data-rename]")) {
      e.preventDefault();
      const link = $(".conv-link", li);
      const title = prompt("ชื่อใหม่", link.textContent.trim());
      if (!title) return;
      const r = await postJSON(`${IMG.apiUrl}sessions/${id}/rename/`, { title });
      if (r.ok) { link.textContent = r.title; link.title = r.title; }
    } else if (e.target.closest("[data-delete]")) {
      e.preventDefault();
      if (!confirm("ลบประวัตินี้พร้อมภาพทั้งหมดในชุดนี้? ไม่สามารถกู้คืนได้")) return;
      const r = await postJSON(`${IMG.apiUrl}sessions/${id}/delete/`);
      if (r.ok) { li.remove(); if (String(id) === String(sessionId)) window.location.href = IMG.indexUrl; }
    }
  });
})();
