/* Uncle Super App — Video Generator (Single / Series, Prompt & Leave)
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
  function toast(msg, kind = "success") {
    let box = document.getElementById("toasts");
    if (!box) { box = document.createElement("div"); box.id = "toasts"; box.className = "toasts"; document.body.appendChild(box); }
    const t = document.createElement("div");
    t.className = `toast toast-${kind}`; t.textContent = msg; box.appendChild(t);
    setTimeout(() => t.classList.add("hide"), 3500); setTimeout(() => t.remove(), 4200);
  }
  async function postJSON(url, data) {
    try {
      const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json", "X-CSRFToken": VG.csrf }, body: JSON.stringify(data || {}), credentials: "same-origin" });
      const d = await r.json().catch(() => ({}));
      return { ok: r.ok && d.ok !== false, ...d };
    } catch (e) { return { ok: false, error: String(e) }; }
  }
  const fmtUsd = (v) => (v === null || v === undefined || !isFinite(v) ? "—" : v < 0.1 ? "$" + v.toFixed(3) : "$" + v.toFixed(2));

  // ---------- ไอคอนดูคำแปลไทย (กด = แสดง, กดซ้ำ / กดที่อื่น / Esc = ซ่อน) ----------
  const TH = (() => {
    const KEY = "vg:th";
    let saved = store.get(KEY, {});
    const mem = new Map(), inflight = new Map();
    const hash = (t) => { let x = 5381; for (let i = 0; i < t.length; i++) x = ((x << 5) + x + t.charCodeAt(i)) | 0; return (x >>> 0).toString(36) + "_" + t.length; };
    const get = (t) => (t ? mem.get(t.trim()) || saved[hash(t.trim())] || null : null);
    function set(t, th) {
      if (!t || !th) return;
      t = t.trim(); mem.set(t, th); saved[hash(t)] = th;
      const keys = Object.keys(saved); if (keys.length > 300) keys.slice(0, keys.length - 300).forEach((k) => delete saved[k]);
      store.set(KEY, saved);
    }
    const bubble = document.createElement("div");
    bubble.className = "th-bubble"; bubble.hidden = true; bubble.setAttribute("role", "dialog");
    document.body.appendChild(bubble);
    let current = null;
    function sourceText(icon) {
      const scope = icon.closest("[data-th-scope]") || document;
      const el = scope.querySelector(icon.dataset.thTarget);
      if (!el) return "";
      return (el.matches("textarea,input") ? el.value : el.textContent).trim();
    }
    function place(icon) {
      const r = icon.getBoundingClientRect(), b = bubble.getBoundingClientRect();
      let left = Math.min(Math.max(8, r.left + r.width / 2 - b.width / 2), window.innerWidth - b.width - 8);
      let top = r.bottom + 8;
      if (top + b.height > window.innerHeight - 8) top = Math.max(8, r.top - b.height - 8);
      bubble.style.left = left + "px"; bubble.style.top = top + "px";
    }
    const head = '<div class="th-head"><span class="th-label">คำแปลภาษาไทย</span><button type="button" class="th-close" aria-label="ปิด">×</button></div>';
    function render(icon, html) { bubble.innerHTML = head + `<div class="th-body">${html}</div>`; bubble.hidden = false; place(icon); }
    async function show(icon) {
      current = icon; icon.classList.add("on"); icon.setAttribute("aria-expanded", "true");
      const text = sourceText(icon);
      if (!text) return render(icon, '<span class="muted">ยังไม่มี prompt ให้แปล</span>');
      const cached = get(text);
      if (cached) return render(icon, esc(cached));
      render(icon, '<span class="spinner"></span> กำลังแปล…');
      if (!inflight.has(text)) {
        inflight.set(text, postJSON(VG.translateUrl, { texts: [text], scene_ids: [Number(icon.dataset.sceneId) || null], version_ids: [Number(icon.dataset.versionId) || null] })
          .then((r) => { if (r.ok && r.translations && r.translations[0]) set(text, r.translations[0]); else r.ok = false; return r; })
          .finally(() => inflight.delete(text)));
      }
      const r = await inflight.get(text);
      if (current !== icon) return;
      if (r.ok) render(icon, esc(r.translations[0]));
      else render(icon, `<span class="th-err">แปลไม่สำเร็จ${r.error ? ": " + esc(r.error) : ""}</span><div class="th-retry"><button type="button" class="btn btn-ghost btn-sm" data-th-retry>ลองอีกครั้ง</button></div>`);
    }
    function hide() { if (current) { current.classList.remove("on"); current.setAttribute("aria-expanded", "false"); } current = null; bubble.hidden = true; }
    document.addEventListener("click", (e) => {
      const ic = e.target.closest(".th-tip");
      if (ic) {
        e.preventDefault(); e.stopPropagation();
        if (current === ic && !bubble.hidden) hide(); else show(ic);
        return;
      }
      if (bubble.contains(e.target)) {
        if (e.target.closest(".th-close")) hide();
        else if (e.target.closest("[data-th-retry]") && current) show(current);
        return;  // กดในกล่องคำแปล (เช่น เลือกข้อความ) ไม่ต้องปิด
      }
      if (!bubble.hidden) hide();  // กดที่อื่น = ปิด
    }, true);
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !bubble.hidden) hide(); });
    // เลื่อนหน้าจอ / ย่อขยายหน้าต่าง: ให้กล่องคำแปลตามไอคอน (ซ่อนถ้าไอคอนออกนอกจอหรือถูกซ่อน)
    const follow = (e) => {
      if (!current || bubble.hidden || (e && bubble.contains(e.target))) return;
      const r = current.getBoundingClientRect();
      if (!current.isConnected || (!r.width && !r.height) || r.bottom < 0 || r.top > window.innerHeight) hide(); else place(current);
    };
    window.addEventListener("scroll", follow, true);
    window.addEventListener("resize", () => follow());
    // คำแปลที่บันทึกไว้แล้วจาก server
    $$(".th-tip[data-th]").forEach((ic) => { if (ic.dataset.th) set(sourceText(ic), ic.dataset.th); });
    return { get, set };
  })();
  const thIcon = (target) => `<button type="button" class="th-tip" data-th-target="${target}" aria-label="ดูคำแปลภาษาไทย"><svg viewBox="0 0 24 24"><path d="M3 5h9M7.5 3v2M5.5 5c.5 3.5 3 6.5 6 8M10 5c-.8 3.8-3.5 6.8-7 8.2"/><path d="M13 21l4-9 4 9M14.4 18h5.2"/></svg><span>TH</span></button>`;

  // ---------- คำอธิบายสำหรับโพสต์ (ใช้ทั้งหน้าสร้างและหน้าผลงาน) ----------
  // เลือกภาษา ไทย / English / ไทย+English · เก็บประวัติทุกเวอร์ชัน (AI เขียน + แก้ไขเอง) ให้กลับมาเลือกได้
  const caption = (() => {
    const modal = $("#captionModal");
    if (!modal) return null;
    const LANG_KEY = "vg:capLang";
    const LANG_LABEL = { th: "ไทย", en: "English", both: "ไทย + EN" };
    let bodyFn = null, lang = store.get(LANG_KEY, "th"), cache = {}, seq = 0, history = [], histLoaded = false, dirty = false;
    const langBtns = $$("#capLang button");
    const markLang = () => langBtns.forEach((b) => b.classList.toggle("active", b.dataset.value === lang));
    const scope = () => { const b = bodyFn ? bodyFn() : {}; return { project_id: b.project_id || null, idea: b.idea || "" }; };
    const tagsOf = () => $("#capTags").value.split(/\s+/).filter(Boolean);
    function meta(d) {
      const el = $("#capMeta");
      if (!d || !d.created_at) { el.textContent = ""; return; }
      el.textContent = `${d.source === "edited" ? "✎ แก้ไขเอง" : "✨ AI เขียน"} · ${d.created_at}` + (dirty ? " · มีการแก้ไขที่ยังไม่บันทึก" : "");
    }
    const fill = (d) => { $("#capTitle").value = d.title || ""; $("#capDesc").value = d.description || ""; $("#capTags").value = (d.hashtags || []).join(" "); dirty = false; meta(d); };
    const busy = (on) => {
      const hist = !$("#capHist").hidden;  // เปิดดูประวัติอยู่ = ไม่ต้องโชว์ฟอร์ม
      $("#capLoading").hidden = !on || hist; $("#capBody").hidden = on || hist; $("#capRegen").disabled = on; $("#capSave").disabled = on;
    };
    // เก็บสิ่งที่ผู้ใช้แก้ไว้ในภาษานั้น ก่อนสลับไปภาษาอื่น (ยังไม่บันทึกลงประวัติจนกว่าจะกด "บันทึกเวอร์ชันนี้")
    const keepEdits = () => {
      if (dirty && cache[lang]) cache[lang] = { ...cache[lang], title: $("#capTitle").value, description: $("#capDesc").value, hashtags: tagsOf(), _dirty: true };
    };
    ["#capTitle", "#capDesc", "#capTags"].forEach((id) => $(id).addEventListener("input", () => { if (!dirty) { dirty = true; meta(cache[lang]); } }));

    // ---- ประวัติ ----
    function setCount() { $("#capHistCount").textContent = history.length; }
    function addHistory(item) { history = [item, ...history.filter((h) => h.id !== item.id)]; setCount(); if (!$("#capHist").hidden) renderHistory(); }
    async function loadHistory() {
      const sc = scope();
      try {
        const r = await fetch(VG.captionsUrl + (sc.project_id ? `?project=${sc.project_id}` : ""), { credentials: "same-origin" }).then((x) => x.json());
        if (r.ok) { history = r.items || []; histLoaded = true; setCount(); if (!$("#capHist").hidden) renderHistory(); }
      } catch (_) {}
    }
    function renderHistory() {
      const box = $("#capHistList");
      if (!histLoaded) { box.innerHTML = '<div class="muted small cap-hist-empty"><span class="spinner"></span> กำลังโหลด…</div>'; return; }
      if (!history.length) { box.innerHTML = '<div class="muted small cap-hist-empty">ยังไม่มีประวัติ — ทุกครั้งที่ AI เขียน หรือกด "บันทึกเวอร์ชันนี้" จะถูกเก็บไว้ที่นี่</div>'; return; }
      const cur = cache[lang] && cache[lang].id;
      box.innerHTML = history.map((h) => `
        <div class="cap-item${h.id === cur ? " current" : ""}" data-id="${h.id}" role="button" tabindex="0">
          <div class="cap-item-top">
            <span class="cap-badge lang-${esc(h.lang)}">${esc(LANG_LABEL[h.lang] || h.lang)}</span>
            <span class="cap-badge src-${esc(h.source)}">${h.source === "edited" ? "✎ แก้ไขเอง" : "✨ AI"}</span>
            <span class="muted small">${esc(h.created_at)}</span>
            ${h.id === cur ? '<span class="cap-cur">กำลังแสดง</span>' : ""}
            <button type="button" class="cap-del" data-del="${h.id}" title="ลบเวอร์ชันนี้" aria-label="ลบ">×</button>
          </div>
          <div class="cap-item-title">${esc(h.title || "(ไม่มีชื่อ)")}</div>
          <div class="cap-item-desc">${esc((h.description || "").replace(/\s+/g, " ").trim())}</div>
          ${!scope().project_id && h.idea ? `<div class="cap-item-idea muted small">ไอเดีย: ${esc(h.idea)}</div>` : ""}
        </div>`).join("");
    }
    function showHistory(on) {
      $("#capHist").hidden = !on; $("#capHistBtn").setAttribute("aria-expanded", on ? "true" : "false");
      $("#capHistBtn").classList.toggle("on", on);
      if (on) { $("#capBody").hidden = true; $("#capLoading").hidden = true; $("#capActions").hidden = true; renderHistory(); if (!histLoaded) loadHistory(); }
      else { $("#capActions").hidden = false; busy($("#capLoading").dataset.busy === "1"); }
    }
    function useItem(h) {
      keepEdits();
      lang = h.lang in LANG_LABEL ? h.lang : "th"; store.set(LANG_KEY, lang); markLang();
      cache[lang] = h; seq++; $("#capLoading").dataset.busy = "0"; busy(false); fill(h); showHistory(false);
    }
    $("#capHistBtn").addEventListener("click", () => { keepEdits(); showHistory($("#capHist").hidden); });
    $("#capHistBack").addEventListener("click", () => showHistory(false));
    $("#capHistList").addEventListener("click", async (e) => {
      const del = e.target.closest("[data-del]");
      if (del) {
        e.stopPropagation();
        if (!confirm("ลบคำอธิบายเวอร์ชันนี้ออกจากประวัติ?")) return;
        const id = Number(del.dataset.del);
        const r = await postJSON(`${VG.captionBase}${id}/delete/`, {});
        if (!r.ok) return toast(r.error || "ลบไม่สำเร็จ", "error");
        history = history.filter((h) => h.id !== id); setCount();
        Object.keys(cache).forEach((k) => { if (cache[k] && cache[k].id === id) cache[k] = { ...cache[k], id: null }; });
        return renderHistory();
      }
      const it = e.target.closest(".cap-item");
      if (it) { const h = history.find((x) => x.id === Number(it.dataset.id)); if (h) useItem(h); }
    });
    $("#capHistList").addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target.classList.contains("cap-item")) e.target.click(); });

    // ---- เขียน / บันทึก ----
    async function generate() {
      const my = ++seq, want = lang;
      $("#capLoading").dataset.busy = "1"; busy(true);
      const r = await postJSON(VG.assistDescUrl, { action: "caption", caption_lang: want, ...bodyFn() });
      if (my !== seq) return;  // ผู้ใช้สลับภาษา / เลือกจากประวัติระหว่างรอ
      $("#capLoading").dataset.busy = "0"; busy(false);
      if (!r.ok) { toast(r.error || "AI เขียนคำอธิบายไม่สำเร็จ", "error"); if (cache[want]) fill(cache[want]); return; }
      cache[want] = r; fill(r);
      if (r.id) addHistory(r);
    }
    $("#capSave").addEventListener("click", async (e) => {
      const btn = e.currentTarget, sc = scope();
      btn.disabled = true;
      const r = await postJSON(VG.captionSaveUrl, { ...sc, lang, title: $("#capTitle").value, description: $("#capDesc").value, hashtags: tagsOf() });
      btn.disabled = false;
      if (!r.ok) return toast(r.error || "บันทึกไม่สำเร็จ", "error");
      cache[lang] = r; dirty = false; meta(r); addHistory(r);
      toast("บันทึกเวอร์ชันนี้ไว้ในประวัติแล้ว");
    });
    function showLang() {
      markLang();
      const c = cache[lang];
      if (c && c.description) { seq++; $("#capLoading").dataset.busy = "0"; busy(false); fill(c); if (c._dirty) { dirty = true; meta(c); } }
      else generate();
    }
    langBtns.forEach((b) => b.addEventListener("click", () => {
      if (b.dataset.value === lang && $("#capHist").hidden) return;
      keepEdits(); lang = b.dataset.value; store.set(LANG_KEY, lang);
      if (!$("#capHist").hidden) showHistory(false);
      showLang();
    }));
    const copy = (text, btn) => {
      const done = () => { if (btn) { const t = btn.textContent; btn.textContent = "คัดลอกแล้ว ✓"; setTimeout(() => (btn.textContent = t), 1300); } };
      if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(text).then(done);
      else { const ta = document.createElement("textarea"); ta.value = text; document.body.appendChild(ta); ta.select(); document.execCommand("copy"); ta.remove(); done(); }
    };
    const close = () => { keepEdits(); modal.classList.remove("open"); };
    modal.querySelectorAll("[data-close-caption]").forEach((el) => el.addEventListener("click", close));
    modal.querySelectorAll("[data-copy-field]").forEach((b) => b.addEventListener("click", () => copy($("#" + b.dataset.copyField).value, b)));
    $("#capCopyAll").addEventListener("click", (e) => copy(`${$("#capTitle").value}\n\n${$("#capDesc").value}\n\n${$("#capTags").value}`, e.currentTarget));
    $("#capRegen").addEventListener("click", generate);
    return {
      // saved = คำอธิบายล่าสุดของแต่ละภาษา {th: {...}, en: {...}} (หน้าผลงาน) · หน้าสร้างให้ AI เขียนใหม่ทุกครั้งที่เปิด
      open(fn, saved) {
        bodyFn = fn; modal.classList.add("open");
        if (saved !== undefined) cache = Object.assign({}, saved || {}, cache);
        else cache = {};
        histLoaded = false; history = []; setCount(); showHistory(false);
        loadHistory();
        showLang();
      },
    };
  })();

  if (VG.page === "project") return projectPage();

  // =====================================================================
  // Create page
  // =====================================================================
  let models = [], musicModels = [], canUsePaid = true, role = "";
  let model = null;
  let firstFrame = null;
  const S = Object.assign({
    mode: "single", type: "Product advertisement", style: "", aspect: "16:9", res: "", duration: 0, sceneDur: 0, total: 60,
    audio: "ambient", lang: "th", continuity: false, music: false, musicModel: "", musicVol: 25, modelId: "",
  }, store.get("vg:state", {}));
  const prefill = JSON.parse(($("#vgPrefill") || {}).textContent || "null");

  // ---------- price estimate ----------
  const RES_H = { "360p": 360, "480p": 480, "720p": 720, "768p": 768, "1080p": 1080, "1k": 1080, "2k": 1440, "4k": 2160 };
  function dims(res, aspect) {
    const h = RES_H[String(res || "720p").toLowerCase()] || 720;
    const m = String(aspect || "16:9").match(/^([\d.]+):([\d.]+)$/);
    const a = m ? parseFloat(m[1]) : 16, b = m ? parseFloat(m[2]) : 9;
    return a >= b ? [Math.round(h * a / b), h] : [h, Math.round(h * b / a)];
  }
  function pricePerSecond(m, res, audioOn, aspect) {
    if (!m) return null;
    const want = String(res || "").toLowerCase();
    let best = null;
    for (const [key, raw] of Object.entries(m.pricing || {})) {
      const k = key.toLowerCase(), val = parseFloat(raw);
      if (!isFinite(val) || /reference|input|continuation|long_|minimum|megapixel|image/.test(k)) continue;
      const isToken = k.startsWith("video_tokens"), isTime = k.includes("second");
      if (!isToken && !isTime) continue;
      const rm = k.match(/_(\d+p|\dk)(?:_|$)/);
      let score = 0;
      if (rm) { if (want && rm[1] === want) score += 3; else continue; } else score += 1;
      if (k.includes("without_audio")) score += audioOn ? -3 : 2;
      else if (k.includes("with_audio")) score += audioOn ? 2 : -3;
      let pps;
      if (isToken) { const [w, h] = dims(res, aspect); pps = val * (w * h * 24 / 1024); }
      else pps = k.includes("cents") ? val / 100 : val;
      if (!best || score > best.score) best = { score, pps, estimated: isToken };
    }
    return best;
  }

  // ---------- model picker ----------
  const picker = {
    modal: $("#vidModelModal"), list: $("#vidModelList"), count: $("#vidModelCount"),
    search: $("#vidModelSearch"), sort: $("#vidModelSort"), prov: $("#vidProviderFilter"),
    state: { q: "", filter: "all", sort: "popular", provider: "" },
    open() { this.modal.classList.add("open"); this.render(); setTimeout(() => this.search.focus(), 50); },
    close() { this.modal.classList.remove("open"); },
    pps(m) { const res = m.resolutions.includes(S.res) ? S.res : (m.resolutions.includes("720p") ? "720p" : m.resolutions[0]); const p = pricePerSecond(m, res, S.audio !== "silent", S.aspect); return p ? p.pps : null; },
    filtered() {
      const { q, filter, sort, provider } = this.state;
      let arr = models.filter((m) => (filter !== "audio" || m.audio) && (filter !== "frame" || m.frames.includes("first_frame"))
        && (!provider || m.provider === provider) && (!q || m.name.toLowerCase().includes(q) || m.id.toLowerCase().includes(q)));
      const by = {
        price_asc: (a, b) => (this.pps(a) ?? Infinity) - (this.pps(b) ?? Infinity),
        price_desc: (a, b) => (this.pps(b) ?? -1) - (this.pps(a) ?? -1),
        newest: (a, b) => b.created - a.created,
        longest: (a, b) => Math.max(...b.durations) - Math.max(...a.durations),
        name: (a, b) => a.name.localeCompare(b.name),
      }[sort];
      return by ? [...arr].sort(by) : arr;
    },
    render() {
      const arr = this.filtered();
      this.count.textContent = `แสดง ${arr.length} จาก ${models.length} โมเดลวิดีโอ` + (canUsePaid ? "" : ` · บัญชี ${role} ใช้ไม่ได้`);
      if (!arr.length) { this.list.innerHTML = '<div class="empty">ไม่พบโมเดลที่ตรงกับเงื่อนไข</div>'; return; }
      this.list.innerHTML = arr.map((m) => {
        const p = this.pps(m);
        const d = m.durations;
        const dur = d.length > 4 ? `${d[0]}–${d[d.length - 1]}s` : d.join(", ") + "s";
        const caps = (m.audio ? '<span class="badge badge-dim">🔊 เสียง</span>' : "") + (m.frames.includes("first_frame") ? '<span class="badge badge-dim">🖼 ภาพเริ่มต้น</span>' : "");
        return `<div class="model-row ${model && m.id === model.id ? "selected" : ""} ${canUsePaid ? "" : "locked"}" data-id="${esc(m.id)}" title="${esc(m.description)}">
          <div class="mr-main"><div class="mr-name">${esc(m.name)} ${caps}</div><div class="mr-id">${esc(m.id)}</div></div>
          <div class="mr-ctx">${dur}</div><div class="mr-price"><span class="price">${p === null ? '<span class="muted">—</span>' : `≈<b>${fmtUsd(p)}</b>/s`}</span></div></div>`;
      }).join("");
    },
  };
  picker.modal.querySelectorAll("[data-close-modal]").forEach((el) => el.addEventListener("click", () => picker.close()));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && picker.modal.classList.contains("open")) picker.close(); });
  picker.search.addEventListener("input", () => { picker.state.q = picker.search.value.trim().toLowerCase(); picker.render(); });
  picker.sort.addEventListener("change", () => { picker.state.sort = picker.sort.value; picker.render(); });
  picker.prov.addEventListener("change", () => { picker.state.provider = picker.prov.value; picker.render(); });
  $$("#vidModelFilter button").forEach((b) => b.addEventListener("click", () => {
    $$("#vidModelFilter button").forEach((x) => x.classList.remove("active")); b.classList.add("active");
    picker.state.filter = b.dataset.filter; picker.render();
  }));
  picker.list.addEventListener("click", (e) => {
    const row = e.target.closest(".model-row");
    if (!row || row.classList.contains("locked")) return;
    selectModel(row.dataset.id); picker.close();
  });
  $("#vgModelBtn").addEventListener("click", () => picker.open());

  // ---------- generic segmented helpers ----------
  function segmented(el, values, current, labelFn) {
    el.innerHTML = values.map((v) => `<button type="button" data-value="${esc(v)}" class="${String(v) === String(current) ? "active" : ""}">${esc(labelFn ? labelFn(v) : v)}</button>`).join("");
  }
  function bindChoice(el, onPick) {
    el.addEventListener("click", (e) => {
      const b = e.target.closest("button[data-value]");
      if (!b) return;
      $$("button", el).forEach((x) => x.classList.remove("active")); b.classList.add("active");
      onPick(b.dataset.value);
    });
  }
  function ratioBox(v) {
    const m = String(v).match(/^([\d.]+):([\d.]+)$/);
    if (!m) return "";
    let w = parseFloat(m[1]), h = parseFloat(m[2]); const s = 18 / Math.max(w, h);
    return `<span class="ratio-shape" style="width:${(w * s).toFixed(1)}px;height:${(h * s).toFixed(1)}px"></span>`;
  }

  // ---------- model selection → render capability-driven controls ----------
  function selectModel(id) {
    model = models.find((m) => m.id === id);
    if (!model) return;
    S.modelId = id;
    $("#vgModelName").textContent = model.name;
    $("#vgModelId").textContent = model.id;
    $("#vgCaps").innerHTML = [
      model.audio ? '<span class="cap ok">🔊 สร้างเสียงได้</span>' : model.audio_unknown ? '<span class="cap">🔊 ไม่ระบุว่าสร้างเสียงได้</span>' : '<span class="cap no">🔇 ไม่มีเสียง</span>',
      model.frames.includes("first_frame") ? '<span class="cap ok">🖼 ภาพเริ่มต้น</span>' : '<span class="cap no">ไม่รับภาพเริ่มต้น</span>',
      `<span class="cap">⏱ ${model.durations.length > 4 ? model.durations[0] + "–" + model.durations[model.durations.length - 1] : model.durations.join(", ")} วินาที</span>`,
    ].join("");

    const ars = model.aspect_ratios.length ? model.aspect_ratios : ["16:9"];
    if (!ars.includes(S.aspect)) S.aspect = ars.includes("16:9") ? "16:9" : ars[0];
    $("#vgAspect").innerHTML = ars.map((v) => `<button type="button" class="ratio-btn ${v === S.aspect ? "active" : ""}" data-value="${esc(v)}">${ratioBox(v)}<span>${esc(v)}</span></button>`).join("");

    $("#vgResField").hidden = !model.resolutions.length;
    if (model.resolutions.length && !model.resolutions.includes(S.res)) S.res = model.resolutions.includes("720p") ? "720p" : model.resolutions[0];
    segmented($("#vgRes"), model.resolutions, S.res);

    const near = (want) => model.durations.reduce((a, b) => (Math.abs(b - want) < Math.abs(a - want) ? b : a), model.durations[0]);
    if (!model.durations.includes(S.duration)) S.duration = near(8);
    if (!model.durations.includes(S.sceneDur)) S.sceneDur = near(5);
    segmented($("#vgDuration"), model.durations, S.duration);
    segmented($("#vgSceneDur"), model.durations, S.sceneDur);

    const audioOk = model.audio || model.audio_unknown;
    $$("#vgAudio button").forEach((b) => { b.disabled = !audioOk && b.dataset.value !== "silent"; });
    if (!audioOk) S.audio = "silent";
    $$("#vgAudio button").forEach((b) => b.classList.toggle("active", b.dataset.value === S.audio));
    $("#vgAudioNote").textContent = !audioOk ? "โมเดลนี้สร้างวิดีโอแบบไม่มีเสียง — ถ้าต้องการเสียง เลือกโมเดลที่มีป้าย 🔊" :
      S.audio === "voice" ? "โมเดลจะพยายามพูดตามบทที่เขียนไว้ — ความชัดของภาษาไทยขึ้นกับโมเดล (Veo 3.1 / Seedance ทำได้ดี)" : "";

    const frameOk = model.frames.includes("first_frame");
    $("#vgFrameField").hidden = !frameOk;
    $("#vgContField").hidden = S.mode !== "series" || !frameOk;
    if (!frameOk) S.continuity = false;
    $("#vgContinuity").checked = !!S.continuity;
    $("#vgSeedField").hidden = !model.seed;
    refresh();
  }

  bindChoice($("#vgAspect"), (v) => { S.aspect = v; refresh(); });
  bindChoice($("#vgRes"), (v) => { S.res = v; refresh(); });
  bindChoice($("#vgDuration"), (v) => { S.duration = Number(v); refresh(); });
  bindChoice($("#vgSceneDur"), (v) => { S.sceneDur = Number(v); refresh(); });
  bindChoice($("#vgAudio"), (v) => { S.audio = v; selectModel(S.modelId); });
  bindChoice($("#vgLang"), (v) => { S.lang = v; refresh(); });
  $("#vgType").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    $$("#vgType button").forEach((x) => x.classList.remove("active")); b.classList.add("active"); S.type = b.dataset.value; save();
  });
  $("#vgStyle").addEventListener("change", (e) => { S.style = e.target.value; save(); });
  $("#vgTotal").addEventListener("input", (e) => { S.total = Math.max(1, Number(e.target.value) || 0); $$("#vgTotalPreset button").forEach((x) => x.classList.toggle("active", Number(x.dataset.v) === S.total)); refresh(); });
  $("#vgTotalPreset").addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; S.total = Number(b.dataset.v); $("#vgTotal").value = S.total; $$("#vgTotalPreset button").forEach((x) => x.classList.toggle("active", x === b)); refresh(); });
  $("#vgContinuity").addEventListener("change", (e) => { S.continuity = e.target.checked; refresh(); });
  $("#vgMusic").addEventListener("change", (e) => { S.music = e.target.checked; refresh(); });
  $("#vgMusicModel").addEventListener("change", (e) => { S.musicModel = e.target.value; save(); });
  $("#vgMusicVol").addEventListener("input", (e) => { S.musicVol = Number(e.target.value); $("#vgMusicVolOut").textContent = S.musicVol + "%"; save(); });

  // mode switch
  $("#vgMode").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-mode]"); if (!b) return;
    S.mode = b.dataset.mode; applyMode(); selectModel(S.modelId);
  });
  function applyMode() {
    $$("#vgMode button").forEach((x) => x.classList.toggle("active", x.dataset.mode === S.mode));
    $$("[data-show]").forEach((el) => { el.hidden = el.dataset.show !== S.mode; });
    if (S.mode === "series") $("#vgMusicOpts").hidden = !S.music;
  }

  function sceneCountTarget() { return Math.max(1, Math.min(VG.maxScenes, Math.round(S.total / (S.sceneDur || 5)))); }

  function refresh() {
    applyMode();
    $("#vgLangField").hidden = S.audio !== "voice";
    $$("[data-voice]").forEach((el) => { el.hidden = S.audio !== "voice"; });
    $$(".scene-narr").forEach((el) => { el.hidden = S.audio !== "voice"; });
    $("#vgMusicOpts").hidden = S.mode !== "series" || !S.music;
    $("#vgMusicPromptField").hidden = S.mode !== "series" || !S.music;
    const n = sceneCountTarget();
    $("#vgSceneCalc").innerHTML = `= <b>${n} ฉาก</b> × ${S.sceneDur} วินาที = ${n * S.sceneDur} วินาที` + (Math.round(S.total / (S.sceneDur || 5)) > VG.maxScenes ? ` (จำกัดสูงสุด ${VG.maxScenes} ฉาก)` : "");
    const editorN = $$(".scene-card").length;
    $("#vgSceneCount").textContent = editorN;
    $("#vgSceneWarn").textContent = editorN && editorN !== n ? `(ตั้งไว้ ${n} ฉาก — จะใช้ตามที่อยู่ในรายการนี้)` : "";
    renumberScenes();
    updateEstimate();
    save();
  }
  function save() { store.set("vg:state", S); }

  function updateEstimate() {
    const el = $("#vgEstimate");
    if (!model) { el.textContent = ""; return; }
    const p = pricePerSecond(model, S.res, S.audio !== "silent", S.aspect);
    const n = S.mode === "series" ? ($$(".scene-card").length || sceneCountTarget()) : 1;
    const dur = S.mode === "series" ? S.sceneDur : S.duration;
    const seconds = n * dur;
    const cost = p ? p.pps * seconds + (S.mode === "series" && S.music ? 0.04 : 0) : null;
    el.dataset.cost = cost ?? "";
    el.innerHTML = `<div><b>${seconds} วินาที</b>${S.mode === "series" ? ` · ${n} ฉาก` : ""} · ${esc(S.aspect)}${S.res ? " · " + esc(S.res) : ""} · ${S.audio === "silent" ? "เงียบ" : S.audio === "voice" ? "เสียงพูด" + (S.lang === "en" ? " EN" : " TH") : "เสียงบรรยากาศ"}</div>
      <div class="muted small">ค่าใช้จ่ายโดยประมาณ <b class="accent">${p ? (p.estimated ? "≈" : "") + fmtUsd(cost) : "ไม่ทราบ"}</b>${S.mode === "series" && S.music ? " (รวมเพลง)" : ""}</div>`;
  }

  // ---------- first frame ----------
  const frameDrop = $("#vgFrameDrop"), frameInput = $("#vgFrameInput");
  function setFrame(f) {
    if (!f) return;
    if (!["image/png", "image/jpeg", "image/webp"].includes(f.type)) return toast("รองรับเฉพาะ PNG / JPG / WEBP", "error");
    if (f.size > 8 * 1024 * 1024) return toast("ไฟล์ใหญ่เกิน 8 MB", "error");
    firstFrame = f;
    $("#vgFrameLabel").innerHTML = `<div class="frame-preview"><img src="${URL.createObjectURL(f)}" alt=""><span>${esc(f.name)}</span><button type="button" data-clear>×</button></div>`;
  }
  frameDrop.addEventListener("click", (e) => {
    if (e.target.closest("[data-clear]")) { e.stopPropagation(); firstFrame = null; $("#vgFrameLabel").innerHTML = "<b>เลือกภาพ</b> หรือลากมาวาง · PNG/JPG/WEBP"; return; }
    frameInput.click();
  });
  frameInput.addEventListener("change", () => { setFrame(frameInput.files[0]); frameInput.value = ""; });
  ["dragenter", "dragover"].forEach((ev) => frameDrop.addEventListener(ev, (e) => { e.preventDefault(); frameDrop.classList.add("drag"); }));
  ["dragleave", "drop"].forEach((ev) => frameDrop.addEventListener(ev, (e) => { e.preventDefault(); frameDrop.classList.remove("drag"); }));
  frameDrop.addEventListener("drop", (e) => setFrame(e.dataTransfer.files[0]));

  // ---------- scene editor ----------
  const sceneList = $("#vgScenes");
  function addScene(sc = {}, focus = false) {
    const card = document.createElement("div");
    card.className = "scene-card";
    card.setAttribute("data-th-scope", "");
    if (sc.prompt && sc.prompt_th) TH.set(sc.prompt, sc.prompt_th);
    card.innerHTML = `<div class="scene-card-head"><b class="scene-no"></b><span class="muted small scene-time"></span>${thIcon(".scene-prompt")}<span class="scene-summary muted small">${esc(sc.summary || "")}</span>
        <div class="scene-tools"><button type="button" class="btn btn-ai xs" data-scene-ai title="ให้ AI ช่วยคิด/ปรับ prompt ของฉากนี้">✨ AI</button><button type="button" class="icon-btn xs" data-move="-1" title="เลื่อนขึ้น">↑</button><button type="button" class="icon-btn xs" data-move="1" title="เลื่อนลง">↓</button><button type="button" class="icon-btn xs danger" data-remove title="ลบฉาก">×</button></div></div>
      <textarea class="input textarea scene-prompt" rows="3" placeholder="Prompt ของฉากนี้ (ภาษาอังกฤษจะได้ผลดีที่สุด)">${esc(sc.prompt || "")}</textarea>
      <input class="input sm scene-narr" placeholder="บทพูดของฉากนี้" value="${esc(sc.narration || "")}" ${S.audio === "voice" ? "" : "hidden"}>`;
    sceneList.appendChild(card);
    if (focus) $(".scene-prompt", card).focus();
  }
  function renumberScenes() {
    $$(".scene-card").forEach((c, i) => {
      $(".scene-no", c).textContent = `ฉาก ${i + 1}`;
      $(".scene-time", c).textContent = `${i * S.sceneDur}s – ${(i + 1) * S.sceneDur}s`;
    });
  }
  sceneList.addEventListener("click", async (e) => {
    const card = e.target.closest(".scene-card"); if (!card) return;
    const aiBtn = e.target.closest("[data-scene-ai]");
    if (aiBtn) {
      const cards = $$(".scene-card"), i = cards.indexOf(card);
      const instr = prompt(`ให้ AI ปรับฉาก ${i + 1} อย่างไร? (เว้นว่าง = ให้ AI เขียน/ปรับให้ดีขึ้น)`, "");
      if (instr === null) return;
      aiBtn.disabled = true; aiBtn.textContent = "…";
      const r = await postJSON(VG.assistSceneUrl, {
        index: i, total: cards.length, duration: S.sceneDur, audio_mode: S.audio, language: S.lang,
        idea: $("#vgIdea").value, style_guide: $("#vgStyleGuide").value, video_type: S.type, style: $("#vgStyle").selectedOptions[0].value,
        prev_prompt: i > 0 ? $(".scene-prompt", cards[i - 1]).value : "", next_prompt: i + 1 < cards.length ? $(".scene-prompt", cards[i + 1]).value : "",
        prompt: $(".scene-prompt", card).value, narration: $(".scene-narr", card).value, instruction: instr,
      });
      aiBtn.disabled = false; aiBtn.textContent = "✨ AI";
      if (!r.ok) return toast(r.error || "AI ช่วยคิดไม่สำเร็จ", "error");
      $(".scene-prompt", card).value = r.prompt;
      TH.set(r.prompt, r.prompt_th);
      if (r.narration) $(".scene-narr", card).value = r.narration;
      if (r.note) $(".scene-summary", card).textContent = r.note;
      card.classList.remove("flash-card"); void card.offsetWidth; card.classList.add("flash-card");
      saveDraft();
      return;
    }
    if (e.target.closest("[data-remove]")) { card.remove(); refresh(); }
    const mv = e.target.closest("[data-move]");
    if (mv) {
      const sib = mv.dataset.move === "-1" ? card.previousElementSibling : card.nextElementSibling;
      if (sib) mv.dataset.move === "-1" ? sceneList.insertBefore(card, sib) : sceneList.insertBefore(sib, card);
      renumberScenes();
    }
  });
  $("#vgAddScene").addEventListener("click", () => {
    if ($$(".scene-card").length >= VG.maxScenes) return toast(`สูงสุด ${VG.maxScenes} ฉาก`, "error");
    addScene({}, true); refresh();
  });

  // ---------- เมนูช่วยคิด description ----------
  const descMenu = $("#vgDescMenu"), descBtn = $("#vgDescBtn"), descStatus = $("#vgDescStatus");
  descBtn.addEventListener("click", (e) => { e.stopPropagation(); descMenu.hidden = !descMenu.hidden; });
  document.addEventListener("click", (e) => { if (!e.target.closest(".menu-wrap")) descMenu.hidden = true; });
  const descBody = () => ({
    mode: S.mode, idea: $("#vgIdea").value.trim(), title: $("#vgTitle").value.trim(), video_type: S.type,
    style: $("#vgStyle").selectedOptions[0].textContent, aspect_ratio: S.aspect,
    seconds: S.mode === "series" ? ($$(".scene-card").length || sceneCountTarget()) * S.sceneDur : S.duration,
    scenes: S.mode === "series" ? $$(".scene-card").map((c) => $(".scene-prompt", c).value.trim()).filter(Boolean)
      : [$("#vgPrompt").value.trim()].filter(Boolean),
  });
  descMenu.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-desc]"); if (!b) return;
    descMenu.hidden = true;
    const action = b.dataset.desc;
    if (action === "caption") return caption.open(descBody);
    const before = $("#vgIdea").value;
    descBtn.disabled = true; descBtn.classList.add("loading");
    descStatus.hidden = false; descStatus.innerHTML = `<span class="spinner"></span> ${action === "ideas" ? "AI กำลังคิดไอเดีย…" : "AI กำลังขยายไอเดีย…"}`;
    const r = await postJSON(VG.assistDescUrl, { action, ...descBody() });
    descBtn.disabled = false; descBtn.classList.remove("loading");
    if (!r.ok) { descStatus.hidden = true; return toast(r.error || "AI ช่วยคิดไม่สำเร็จ", "error"); }
    if (action === "expand") {
      $("#vgIdea").value = r.description;
      descStatus.innerHTML = `✓ AI ขยายไอเดียแล้ว · <a href="#" data-undo>ย้อนกลับ</a>`;
      $("[data-undo]", descStatus).addEventListener("click", (ev) => { ev.preventDefault(); $("#vgIdea").value = before; descStatus.hidden = true; saveDraft(); });
      saveDraft();
    } else {
      descStatus.textContent = "เลือกไอเดียที่ชอบ (คลิกเพื่อใช้)";
      $("#vgIdeas").innerHTML = r.ideas.map((it, i) => `<button type="button" class="idea-card" data-i="${i}"><b>${esc(it.title)}</b><span>${esc(it.description)}</span></button>`).join("");
      $("#vgIdeas").dataset.ideas = JSON.stringify(r.ideas);
    }
  });
  $("#vgIdeas").addEventListener("click", (e) => {
    const c = e.target.closest(".idea-card"); if (!c) return;
    const it = JSON.parse($("#vgIdeas").dataset.ideas || "[]")[Number(c.dataset.i)];
    if (!it) return;
    $("#vgIdea").value = it.description;
    if (!$("#vgTitle").value.trim()) $("#vgTitle").value = it.title;
    $("#vgIdeas").innerHTML = ""; descStatus.hidden = true;
    saveDraft(); toast("ใช้ไอเดียนี้แล้ว — กด \"ให้ AI ช่วยคิด Prompt\" ต่อได้เลย");
  });

  // ---------- AI assist ----------
  $("#vgAssist").addEventListener("click", async () => {
    const idea = $("#vgIdea").value.trim();
    if (!idea) { $("#vgIdea").focus(); return toast("พิมพ์ไอเดียวิดีโอก่อน", "error"); }
    if (S.mode === "series" && $$(".scene-card").some((c) => $(".scene-prompt", c).value.trim()) && !confirm("แทนที่ฉากที่มีอยู่ด้วยฉากใหม่จาก AI?")) return;
    const btn = $("#vgAssist");
    btn.disabled = true; btn.classList.add("loading");
    const old = btn.lastChild.textContent; btn.lastChild.textContent = "AI กำลังคิด…";
    const body = {
      mode: S.mode, idea, video_type: S.type, style: $("#vgStyle").selectedOptions[0].value, aspect_ratio: S.aspect,
      audio_mode: S.audio, language: S.lang, duration: S.duration, scene_duration: S.sceneDur, scene_count: sceneCountTarget(),
    };
    const r = await postJSON(VG.assistUrl, body);
    btn.disabled = false; btn.classList.remove("loading"); btn.lastChild.textContent = old;
    if (!r.ok) return toast(r.error || "AI ช่วยคิดไม่สำเร็จ", "error");
    if (r.title) $("#vgTitle").value = r.title;
    if (S.mode === "single") {
      $("#vgPrompt").value = r.prompt || "";
      TH.set(r.prompt, r.prompt_th);
      $("#vgNarr").value = r.narration || "";
      const tip = $("#vgTip"); tip.hidden = !r.tips; tip.textContent = "💡 " + (r.tips || "");
    } else {
      $("#vgStyleGuide").value = r.style_guide || "";
      $("#vgMusicPrompt").value = r.music_prompt || "";
      sceneList.innerHTML = "";
      (r.scenes || []).forEach((sc) => addScene(sc));
      $("#vgTip").hidden = true;
    }
    refresh();
    toast("AI เขียน prompt ให้แล้ว — ตรวจ/แก้ได้ก่อนกดสร้าง");
  });

  // ---------- generate ----------
  $("#vgGenerate").addEventListener("click", async () => {
    if (!model) return picker.open();
    let scenes;
    if (S.mode === "single") {
      const prompt = $("#vgPrompt").value.trim();
      if (!prompt) { $("#vgPrompt").focus(); return toast("ใส่ prompt หรือกด \"ให้ AI ช่วยคิด Prompt\" ก่อน", "error"); }
      scenes = [{ prompt, prompt_th: TH.get(prompt) || "", narration: $("#vgNarr").value.trim() }];
    } else {
      scenes = $$(".scene-card").map((c) => { const p = $(".scene-prompt", c).value.trim(); return { prompt: p, prompt_th: TH.get(p) || "", narration: $(".scene-narr", c).value.trim() }; }).filter((s) => s.prompt);
      if (!scenes.length) return toast("ยังไม่มีฉาก — กด \"ให้ AI ช่วยคิด Prompt\" หรือ \"+ เพิ่มฉาก\"", "error");
      if (S.music && !$("#vgMusicPrompt").value.trim()) return toast("ใส่ prompt เพลงประกอบ หรือปิดตัวเลือกเพลง", "error");
    }
    const cost = parseFloat($("#vgEstimate").dataset.cost);
    const seconds = scenes.length * (S.mode === "series" ? S.sceneDur : S.duration);
    if (!confirm(`เริ่มสร้างวิดีโอ ${seconds} วินาที${S.mode === "series" ? ` (${scenes.length} ฉาก)` : ""}\nค่าใช้จ่ายโดยประมาณ ${isFinite(cost) ? fmtUsd(cost) : "ไม่ทราบ"} (คิดจากเครดิต OpenRouter ของคุณ)\n\nงานจะรันเบื้องหลัง ปิดหน้านี้ได้เลย`)) return;

    const data = {
      mode: S.mode, title: $("#vgTitle").value.trim(), idea: $("#vgIdea").value.trim(), model: model.id,
      style_guide: $("#vgStyleGuide").value.trim(), music_prompt: $("#vgMusicPrompt").value.trim(), scenes,
      config: {
        aspect_ratio: S.aspect, resolution: S.res, duration: S.mode === "series" ? S.sceneDur : S.duration,
        audio_mode: S.audio, language: S.lang, video_type: S.type, style: $("#vgStyle").selectedOptions[0].textContent,
        seed: $("#vgSeed").value, continuity: S.continuity, music: S.music, music_model: S.musicModel,
        music_volume: S.musicVol / 100, estimate: isFinite(cost) ? cost : null,
      },
    };
    const fd = new FormData();
    fd.append("data", JSON.stringify(data));
    if (firstFrame) fd.append("first_frame", firstFrame, firstFrame.name);
    const btn = $("#vgGenerate"); btn.disabled = true; btn.classList.add("loading");
    try { if ("Notification" in window && Notification.permission === "default") Notification.requestPermission(); } catch (_) {}
    try {
      const r = await fetch(VG.createUrl, { method: "POST", body: fd, headers: { "X-CSRFToken": VG.csrf }, credentials: "same-origin" });
      const d = await r.json().catch(() => ({ error: `HTTP ${r.status}` }));
      if (!r.ok || !d.ok) throw new Error(d.error || "สร้างงานไม่สำเร็จ");
      store.set("vg:draft", null);
      window.location.href = d.url;
    } catch (err) {
      toast(err.message || String(err), "error");
      btn.disabled = false; btn.classList.remove("loading");
    }
  });

  // ---------- draft autosave (กันข้อมูลหายถ้าเผลอปิดหน้า) ----------
  function saveDraft() {
    store.set("vg:draft", {
      idea: $("#vgIdea").value, title: $("#vgTitle").value, prompt: $("#vgPrompt").value, narration: $("#vgNarr").value,
      style_guide: $("#vgStyleGuide").value, music_prompt: $("#vgMusicPrompt").value,
      scenes: $$(".scene-card").map((c) => ({ prompt: $(".scene-prompt", c).value, narration: $(".scene-narr", c).value })),
    });
  }
  document.addEventListener("input", (e) => { if (e.target.closest(".vg-layout")) saveDraft(); });
  function loadDraft(d) {
    if (!d) return;
    $("#vgIdea").value = d.idea || ""; $("#vgTitle").value = d.title || "";
    $("#vgPrompt").value = d.prompt || ""; $("#vgNarr").value = d.narration || "";
    $("#vgStyleGuide").value = d.style_guide || ""; $("#vgMusicPrompt").value = d.music_prompt || "";
    sceneList.innerHTML = ""; (d.scenes || []).forEach((s) => addScene(s));
  }

  // ---------- init ----------
  if (prefill) {
    const c = prefill.config || {};
    Object.assign(S, {
      mode: prefill.mode, modelId: prefill.model, aspect: c.aspect_ratio || S.aspect, res: c.resolution || S.res,
      audio: c.audio_mode || S.audio, lang: c.language || S.lang, continuity: !!c.continuity, music: !!c.music,
      musicModel: c.music_model || S.musicModel, musicVol: Math.round((c.music_volume || 0.25) * 100),
    });
    if (prefill.mode === "series") { S.sceneDur = c.duration; S.total = c.duration * prefill.scenes.length; } else S.duration = c.duration;
    loadDraft({
      idea: prefill.idea, title: prefill.title, style_guide: prefill.style_guide, music_prompt: prefill.music_prompt,
      prompt: prefill.mode === "single" ? (prefill.scenes[0] || {}).prompt : "", narration: prefill.mode === "single" ? (prefill.scenes[0] || {}).narration : "",
      scenes: prefill.mode === "series" ? prefill.scenes : [],
    });
    if (c.seed) $("#vgSeed").value = c.seed;
  } else loadDraft(store.get("vg:draft", null));

  $$("#vgType button").forEach((x) => x.classList.toggle("active", x.dataset.value === S.type));
  if (S.style) $("#vgStyle").value = S.style;
  $("#vgTotal").value = S.total;
  $$("#vgTotalPreset button").forEach((x) => x.classList.toggle("active", Number(x.dataset.v) === S.total));
  $$("#vgLang button").forEach((x) => x.classList.toggle("active", x.dataset.value === S.lang));
  $("#vgMusic").checked = !!S.music;
  $("#vgMusicVol").value = S.musicVol; $("#vgMusicVolOut").textContent = S.musicVol + "%";
  applyMode();

  fetch(VG.modelsUrl, { credentials: "same-origin" }).then((r) => r.json()).then((d) => {
    if (d.error) throw new Error(d.error);
    models = d.models || []; musicModels = d.music_models || []; canUsePaid = d.can_use_paid; role = d.role;
    picker.prov.innerHTML = '<option value="">ทุกผู้ให้บริการ</option>' + [...new Set(models.map((m) => m.provider))].sort().map((p) => `<option>${esc(p)}</option>`).join("");
    musicModels.sort((a, b) => (b.id.includes("clip") - a.id.includes("clip")));
    $("#vgMusicModel").innerHTML = musicModels.length
      ? musicModels.map((m) => `<option value="${esc(m.id)}" ${m.id === S.musicModel ? "selected" : ""}>${esc(m.name)}${m.id.includes("clip") ? " — คลิป 30 วิ (วนซ้ำให้ยาวพอ)" : m.id.includes("pro") ? " — เพลงเต็ม" : ""}</option>`).join("")
      : '<option value="google/lyria-3-clip-preview">google/lyria-3-clip-preview</option>';
    if (!S.musicModel || !musicModels.some((m) => m.id === S.musicModel)) S.musicModel = $("#vgMusicModel").value;
    if (!canUsePaid) {
      $("#roleBanner").hidden = false;
      $("#roleBannerText").textContent = `บัญชีประเภท ${role} ใช้ Video Generator ไม่ได้ เพราะไม่มีโมเดลวิดีโอฟรี — ติดต่อผู้ดูแลเพื่ออัปเกรดเป็น Pro`;
      $("#vgGenerate").disabled = true;
    }
    const initial = models.find((m) => m.id === S.modelId) || models.find((m) => m.id === "google/veo-3.1-lite") || models.find((m) => m.audio) || models[0];
    if (initial) selectModel(initial.id);
  }).catch((err) => {
    $("#vgModelName").textContent = "โหลดรายชื่อโมเดลไม่สำเร็จ";
    picker.list.innerHTML = `<div class="empty error">${esc(err.message || err)}</div>`;
  });

  // =====================================================================
  // Project page — ติดตามสถานะแบบ polling (ปิดหน้าไปแล้วกลับมาก็เห็นสถานะล่าสุด)
  // =====================================================================
  function projectPage() {
    const start = Date.now();
    let lastSig = "";
    async function tick() {
      let d;
      try { d = await (await fetch(VG.statusUrl, { credentials: "same-origin" })).json(); } catch (_) { return setTimeout(tick, 8000); }
      const sig = d.status + "|" + d.scenes.map((s) => s.status).join(",");
      $("#vpStatus").textContent = d.status_label;
      $("#vpStatus").className = `status-pill st-${d.status}`;
      $("#vpBar").style.width = Math.max(4, d.progress) + "%";
      const mins = Math.floor((Date.now() - start) / 60000);
      $("#vpProgressText").textContent = d.status === "music" ? "กำลังสร้างเพลงประกอบ…" : d.status === "stitching" ? "กำลังรวมคลิปเป็นวิดีโอเดียว…"
        : `สร้างแล้ว ${d.done} / ${d.total} ฉาก` + (mins ? ` · เปิดดูมา ${mins} นาที` : "");
      $("#vpSceneSummary").textContent = `(${d.done}/${d.total} เสร็จ)`;
      d.scenes.forEach((s) => {
        const card = $(`.vp-scene[data-scene-id="${s.id}"]`); if (!card) return;
        if (card.dataset.status !== s.status) {
          card.dataset.status = s.status; card.className = `vp-scene st-${s.status}`;
          const pill = $("[data-role=status]", card); pill.textContent = s.status_label; pill.className = `status-pill sm st-${s.status}`;
          if (s.url && !$("video", card)) $(".vp-scene-media", card).innerHTML = `<video src="${s.url}" controls playsinline preload="metadata"></video>`;
        }
        const err = $("[data-role=error]", card); err.hidden = !s.error; err.textContent = s.error || "";
      });
      if (!d.is_active) {
        if (VG.active) { toast(`วิดีโอ${d.status_label}`); setTimeout(() => location.reload(), 900); }
        return;
      }
      lastSig = sig;
      setTimeout(tick, 5000);
    }
    if (VG.active) tick();

    // ---------- แก้ไขทีละฉาก / ประวัติเวอร์ชัน ----------
    $$(".vp-scene").forEach((card) => {
      const cost = $(".se-cost", card);
      if (cost && VG.perScene) cost.textContent = ` (≈${fmtUsd(VG.perScene)})`;
    });
    $("#vpScenes").addEventListener("click", async (e) => {
      const btn = e.target.closest("[data-act]"); if (!btn) return;
      const card = btn.closest(".vp-scene"); const sid = card.dataset.sceneId;
      const edit = $("[data-role=edit]", card), hist = $("[data-role=history]", card);
      const act = btn.dataset.act;
      if (act === "edit") { edit.hidden = !edit.hidden; if (!edit.hidden) { hist && (hist.hidden = true); $(".se-prompt", edit).focus(); } }
      else if (act === "cancel") edit.hidden = true;
      else if (act === "history") { hist.hidden = !hist.hidden; if (!hist.hidden) edit.hidden = true; }
      else if (act === "copy-prompt") {
        $(".se-prompt", edit).value = $(".ver-prompt", btn.closest(".ver")).textContent.trim();
        hist.hidden = true; edit.hidden = false; $(".se-prompt", edit).focus();
        toast("นำ prompt เวอร์ชันเก่ามาใส่แล้ว — แก้ต่อหรือกดสร้างใหม่ได้");
      } else if (act === "ai") {
        btn.disabled = true; btn.classList.add("loading");
        const narr = $(".se-narr", edit);
        const r = await postJSON(VG.apiRoot + "assist-scene/", {
          scene_id: Number(sid), prompt: $(".se-prompt", edit).value, narration: narr ? narr.value : "",
          instruction: $(".se-instr", edit).value,
        });
        btn.disabled = false; btn.classList.remove("loading");
        if (!r.ok) return toast(r.error || "AI ช่วยคิดไม่สำเร็จ", "error");
        $(".se-prompt", edit).value = r.prompt;
        TH.set(r.prompt, r.prompt_th);
        if (narr && r.narration) narr.value = r.narration;
        const note = $(".se-note", edit); note.hidden = !r.note; note.textContent = "💡 " + (r.note || "");
      } else if (act === "regen") {
        const prompt = $(".se-prompt", edit).value.trim();
        if (!prompt) return toast("prompt ว่าง", "error");
        if (!confirm(`สร้างฉาก ${Number(card.dataset.index) + 1} ใหม่${VG.perScene ? ` (ประมาณ ${fmtUsd(VG.perScene)})` : ""}?\nคลิปเดิมจะถูกเก็บไว้ในประวัติ${document.querySelectorAll(".vp-scene").length > 1 ? " และระบบจะรวมวิดีโอใหม่ให้อัตโนมัติ" : ""}`)) return;
        btn.disabled = true;
        const narr = $(".se-narr", edit);
        const r = await postJSON(`${VG.apiRoot}scenes/${sid}/regenerate/`, { prompt, prompt_th: TH.get(prompt) || "", narration: narr ? narr.value : "" });
        if (!r.ok) { btn.disabled = false; return toast(r.error || "ไม่สำเร็จ", "error"); }
        if (window.__vgCheckBadge) window.__vgCheckBadge();
        location.reload();
      } else if (act === "restore") {
        if (!confirm("กลับไปใช้เวอร์ชันนี้? เวอร์ชันปัจจุบันจะถูกเก็บไว้ในประวัติแทน")) return;
        const r = await postJSON(`${VG.apiRoot}versions/${btn.dataset.versionId}/restore/`);
        if (!r.ok) return toast(r.error || "ไม่สำเร็จ", "error");
        if (window.__vgCheckBadge) window.__vgCheckBadge();
        location.reload();
      }
    });

    $("#vpCaption").addEventListener("click", () => {
      const saved = JSON.parse(($("#vpCaptionData") || {}).textContent || "null") || {};
      caption.open(() => ({ project_id: VG.id }), saved);
    });

    $("#vpCancel").addEventListener("click", async () => {
      if (!confirm("ยกเลิกงานนี้? ฉากที่เสร็จแล้วจะยังเก็บไว้ (ฉากที่ส่งไปแล้วอาจยังถูกคิดเงินจาก OpenRouter)")) return;
      const r = await postJSON(VG.apiBase + "cancel/"); if (r.ok) location.reload(); else toast(r.error || "ไม่สำเร็จ", "error");
    });
    $("#vpRetry").addEventListener("click", async () => {
      const r = await postJSON(VG.apiBase + "retry/");
      if (r.ok) { if (window.__vgCheckBadge) window.__vgCheckBadge(); location.reload(); } else toast(r.error || "ไม่สำเร็จ", "error");
    });
    $("#vpDelete").addEventListener("click", async () => {
      if (!confirm("ลบงานนี้พร้อมไฟล์วิดีโอทั้งหมด? ไม่สามารถกู้คืนได้")) return;
      const r = await postJSON(VG.apiBase + "delete/"); if (r.ok) location.href = r.url; else toast(r.error || "ลบไม่สำเร็จ", "error");
    });
    $("#vpRename").addEventListener("click", async () => {
      const t = prompt("ชื่องานใหม่", $("#vpTitle").textContent.trim()); if (!t) return;
      const r = await postJSON(VG.apiBase + "rename/", { title: t });
      if (r.ok) { $("#vpTitle").textContent = r.title; const li = $(`#vidList [data-id="${VG.id}"] .conv-link`); if (li) li.lastChild.textContent = r.title; }
    });
  }
})();
