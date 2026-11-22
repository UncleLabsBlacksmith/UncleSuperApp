/* Uncle Super App — shared helpers: markdown, charts, SSE streaming, sidebar
 * Developed by Uncle Engineer — https://uncle-engineer.com/
 */
(function () {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  function toast(msg, kind = "success", ms = 3000) {
    let box = document.getElementById("toasts");
    if (!box) { box = document.createElement("div"); box.id = "toasts"; box.className = "toasts"; document.body.appendChild(box); }
    const t = document.createElement("div");
    t.className = `toast toast-${kind}`; t.textContent = msg; box.appendChild(t);
    setTimeout(() => t.classList.add("hide"), ms); setTimeout(() => t.remove(), ms + 700);
  }
  function csrf() { return (window.PAGE && PAGE.csrf) || ""; }
  async function postJSON(url, data) {
    try {
      const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() }, body: JSON.stringify(data || {}), credentials: "same-origin" });
      const d = await r.json().catch(() => ({}));
      return { ok: r.ok && d.ok !== false, status: r.status, ...d };
    } catch (e) { return { ok: false, error: String(e) }; }
  }
  function copyText(text, btn) {
    const done = () => { if (btn) { const t = btn.textContent; btn.textContent = "คัดลอกแล้ว ✓"; setTimeout(() => (btn.textContent = t), 1400); } };
    if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(text).then(done);
    else { const ta = document.createElement("textarea"); ta.value = text; document.body.appendChild(ta); ta.select(); document.execCommand("copy"); ta.remove(); done(); }
  }
  const fmtBytes = (n) => (n < 1024 ? n + " B" : n < 1048576 ? (n / 1024).toFixed(0) + " KB" : (n / 1048576).toFixed(1) + " MB");

  // ------------------------------------------------------------------ charts
  const PALETTE = ["#3da5ff", "#34d399", "#fbbf24", "#f472b6", "#a78bfa", "#fb923c", "#22d3ee", "#f87171", "#a3e635", "#e879f9"];
  const fmtNum = (v) => {
    if (typeof v !== "number") return v;
    const a = Math.abs(v);
    if (a >= 1e9) return (v / 1e9).toFixed(2).replace(/\.?0+$/, "") + "B";
    if (a >= 1e6) return (v / 1e6).toFixed(2).replace(/\.?0+$/, "") + "M";
    if (a >= 1e4) return (v / 1e3).toFixed(1).replace(/\.0$/, "") + "K";
    return v.toLocaleString(undefined, { maximumFractionDigits: 2 });
  };
  function chartConfig(spec) {
    let type = spec.type || "bar";
    const horizontal = type === "horizontalBar";
    const area = type === "area";
    if (horizontal) type = "bar";
    if (area) type = "line";
    const round = type === "pie" || type === "doughnut";
    const datasets = (spec.datasets || []).map((ds, i) => {
      const color = PALETTE[i % PALETTE.length];
      const base = { label: ds.label, data: ds.data };
      if (round) return { ...base, backgroundColor: ds.data.map((_, j) => PALETTE[j % PALETTE.length]), borderColor: "#12151c", borderWidth: 2 };
      if (type === "line") return { ...base, borderColor: color, backgroundColor: color + (area ? "40" : "22"), fill: area, tension: 0.3, pointRadius: spec.labels && spec.labels.length > 40 ? 0 : 3, borderWidth: 2.2 };
      if (type === "scatter") return { ...base, backgroundColor: color + "aa", pointRadius: 3.5 };
      return { ...base, backgroundColor: (spec.datasets.length === 1 ? color : color) + "dd", borderRadius: 5, maxBarThickness: 46 };
    });
    const grid = { color: "rgba(255,255,255,.06)" }, ticks = { color: "#8b92a5", font: { family: "Inter, 'IBM Plex Sans Thai', sans-serif", size: 11 } };
    return {
      type, data: { labels: spec.labels || [], datasets },
      options: {
        responsive: true, maintainAspectRatio: false, indexAxis: horizontal ? "y" : "x",
        animation: { duration: 500 },
        plugins: {
          legend: { display: round || datasets.length > 1, position: round ? "right" : "top", labels: { color: "#b9bfcc", boxWidth: 12, font: ticks.font } },
          tooltip: { callbacks: { label: (c) => `${c.dataset.label ? c.dataset.label + ": " : ""}${typeof c.raw === "number" ? c.raw.toLocaleString(undefined, { maximumFractionDigits: 2 }) : c.raw && c.raw.y !== undefined ? `(${c.raw.x}, ${c.raw.y})` : c.raw}` } },
        },
        scales: round ? {} : {
          x: { grid, ticks: { ...ticks, callback: horizontal ? (v) => fmtNum(v) : function (v) { const l = this.getLabelForValue(v); return typeof l === "string" && l.length > 16 ? l.slice(0, 15) + "…" : l; } }, stacked: !!spec.stacked, title: { display: !!spec.x_label && type === "scatter", text: spec.x_label, color: "#8b92a5" } },
          y: { grid, ticks: { ...ticks, callback: horizontal ? function (v) { const l = this.getLabelForValue(v); return l && l.length > 22 ? l.slice(0, 21) + "…" : l; } : (v) => fmtNum(v) }, stacked: !!spec.stacked, beginAtZero: true },
        },
      },
    };
  }
  function renderChart(container, spec) {
    const card = document.createElement("div");
    card.className = "chart-card";
    card.innerHTML = `<div class="chart-head"><div><b>${esc(spec.title || "กราฟ")}</b>${spec.source ? `<div class="muted small">${esc(spec.source)}</div>` : ""}</div>
      <button type="button" class="icon-btn xs" title="ดาวน์โหลดเป็นรูป PNG" data-dl><svg viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/></svg></button></div>
      <div class="chart-box"><canvas></canvas></div>`;
    container.appendChild(card);
    if (typeof Chart === "undefined") { $(".chart-box", card).innerHTML = '<div class="muted small">โหลด Chart.js ไม่สำเร็จ</div>'; return card; }
    const chart = new Chart($("canvas", card), chartConfig(spec));
    $("[data-dl]", card).addEventListener("click", () => {
      const a = document.createElement("a");
      a.href = chart.toBase64Image("image/png", 1); a.download = (spec.title || "chart").replace(/[\\/:*?"<>|]/g, "_") + ".png"; a.click();
    });
    return card;
  }
  function renderResults(el, res) {
    if (!res) return;
    const { metrics = [], charts = [], tables = [] } = res;
    if (!metrics.length && !charts.length && !tables.length) return;
    const wrap = document.createElement("div");
    wrap.className = "an-results";
    if (metrics.length) {
      wrap.insertAdjacentHTML("beforeend", `<div class="kpi-grid">${metrics.map((m) => `<div class="kpi"><span class="kpi-label">${esc(m.label)}</span><span class="kpi-value">${esc(m.display)}</span></div>`).join("")}</div>`);
    }
    if (charts.length) {
      const grid = document.createElement("div");
      grid.className = "chart-grid" + (charts.length === 1 ? " single" : "");
      wrap.appendChild(grid);
      charts.forEach((c) => renderChart(grid, c));
    }
    tables.forEach((t) => {
      wrap.insertAdjacentHTML("beforeend", `<div class="result-table"><div class="chart-head"><b>${esc(t.title || "ตารางสรุป")}</b><span class="muted small">${t.total_groups} กลุ่ม${t.total_groups > t.rows.length ? ` (แสดง ${t.rows.length})` : ""}</span></div>
        <div class="table-scroll"><table class="table"><thead><tr>${t.header.map((h) => `<th>${esc(h)}</th>`).join("")}</tr></thead>
        <tbody>${t.rows.map((r) => `<tr>${r.map((v, i) => `<td class="${i ? "num" : ""}">${v === null ? "—" : esc(typeof v === "number" ? v.toLocaleString(undefined, { maximumFractionDigits: 2 }) : v)}</td>`).join("")}</tr>`).join("")}</tbody></table></div></div>`);
    });
    el.prepend(wrap);
  }

  // ---------------------------------------------------------------- markdown
  const hasMd = typeof marked !== "undefined" && typeof DOMPurify !== "undefined";
  if (hasMd) marked.setOptions({ gfm: true, breaks: true });
  function renderMarkdown(el, text, opts = {}) {
    if (!hasMd) { el.textContent = text; return; }
    el.innerHTML = DOMPurify.sanitize(marked.parse(text || ""));
    // ```chart {json}``` → กราฟ
    $$("pre code.language-chart", el).forEach((code) => {
      const pre = code.closest("pre");
      try {
        const spec = JSON.parse(code.textContent);
        const holder = document.createElement("div"); holder.className = "chart-grid single";
        pre.replaceWith(holder);
        if (opts.final !== false) renderChart(holder, spec); else holder.innerHTML = '<div class="muted small">กำลังสร้างกราฟ…</div>';
      } catch (_) { if (opts.final !== false) pre.classList.add("bad-chart"); }
    });
    if (typeof hljs !== "undefined") $$("pre code", el).forEach((b) => { try { hljs.highlightElement(b); } catch (_) {} });
    $$("pre", el).forEach((pre) => {
      if (pre.querySelector(".code-bar")) return;
      const code = pre.querySelector("code");
      const lang = ((code && code.className.match(/language-(\S+)/)) || [])[1] || "code";
      const bar = document.createElement("div"); bar.className = "code-bar";
      bar.innerHTML = `<span>${esc(lang)}</span><button class="code-copy" type="button">คัดลอก</button>`;
      bar.querySelector("button").addEventListener("click", (e) => copyText((code || pre).innerText, e.target));
      pre.prepend(bar);
    });
    if (opts.citations) {
      // [1] [2][3] → ลิงก์ไปยังแหล่งที่มา
      const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
      const nodes = []; while (walker.nextNode()) { const n = walker.currentNode; if (/\[\d{1,2}\]/.test(n.nodeValue) && !n.parentElement.closest("code,pre,a")) nodes.push(n); }
      nodes.forEach((n) => {
        const span = document.createElement("span");
        span.innerHTML = esc(n.nodeValue).replace(/\[(\d{1,2})\]/g, (m, d) => `<a class="cite" href="#" data-cite="${d}">${d}</a>`);
        n.replaceWith(span);
      });
    }
  }

  // --------------------------------------------------------------------- SSE
  async function streamSSE(url, body, onEvent, signal) {
    const resp = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() }, body: JSON.stringify(body), signal, credentials: "same-origin" });
    if (!resp.ok || !(resp.headers.get("content-type") || "").includes("event-stream")) {
      let msg = `HTTP ${resp.status}`;
      try { msg = (await resp.json()).error || msg; } catch (_) {}
      throw new Error(msg);
    }
    const reader = resp.body.getReader(), dec = new TextDecoder("utf-8");
    let buf = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
        const line = chunk.split("\n").find((l) => l.startsWith("data:"));
        if (!line) continue;
        try { onEvent(JSON.parse(line.slice(5))); } catch (e) { if (!(e instanceof SyntaxError)) throw e; }
      }
    }
  }

  // ----------------------------------------------------------------- sidebar
  function bindSidebar(list, apiBase, getCurrentId, indexUrl, labels = {}) {
    if (!list) return;
    list.addEventListener("click", async (e) => {
      const li = e.target.closest(".conv-item"); if (!li) return;
      const id = li.dataset.id;
      if (e.target.closest("[data-rename]")) {
        e.preventDefault();
        const link = $(".conv-link", li);
        const title = prompt("ชื่อใหม่", link.textContent.trim()); if (!title) return;
        const r = await postJSON(`${apiBase}${id}/rename/`, { title });
        if (r.ok) { link.textContent = r.title; link.title = r.title; }
      } else if (e.target.closest("[data-delete]")) {
        e.preventDefault();
        if (!confirm(labels.confirmDelete || "ลบรายการนี้พร้อมไฟล์ทั้งหมด? ไม่สามารถกู้คืนได้")) return;
        const r = await postJSON(`${apiBase}${id}/delete/`);
        if (r.ok) { li.remove(); if (String(id) === String(getCurrentId())) location.href = indexUrl; }
      }
    });
  }
  function sidebarItem(id, title, href) {
    return `<li class="conv-item active" data-id="${id}"><a href="${href}" class="conv-link" title="${esc(title)}">${esc(title)}</a>
      <div class="conv-actions"><button class="icon-btn xs" data-rename title="เปลี่ยนชื่อ"><svg viewBox="0 0 24 24"><path d="M12 20h9M16.5 3.5a2.1 2.1 0 1 1 3 3L7 19l-4 1 1-4z"/></svg></button>
      <button class="icon-btn xs danger" data-delete title="ลบ"><svg viewBox="0 0 24 24"><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/></svg></button></div></li>`;
  }
  function autosize(ta, max = 220) { const f = () => { ta.style.height = "auto"; ta.style.height = Math.min(ta.scrollHeight, max) + "px"; }; ta.addEventListener("input", f); return f; }
  function fileIcon(name) {
    const e = (name.split(".").pop() || "").toLowerCase();
    const map = { pdf: ["PDF", "#f87171"], xlsx: ["XLS", "#34d399"], xlsm: ["XLS", "#34d399"], csv: ["CSV", "#34d399"], tsv: ["TSV", "#34d399"], docx: ["DOC", "#60a5fa"], pptx: ["PPT", "#fb923c"], png: ["IMG", "#c084fc"], jpg: ["IMG", "#c084fc"], jpeg: ["IMG", "#c084fc"], webp: ["IMG", "#c084fc"], gif: ["IMG", "#c084fc"] };
    const [label, color] = map[e] || ["TXT", "#94a3b8"];
    return `<span class="file-ico" style="--c:${color}">${label}</span>`;
  }

  window.Convo = { $, $$, esc, toast, postJSON, copyText, fmtBytes, renderChart, renderResults, renderMarkdown, streamSSE, bindSidebar, sidebarItem, autosize, fileIcon };
})();
