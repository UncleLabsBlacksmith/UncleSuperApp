/* Uncle Super App — Model picker (OpenRouter)
 * Developed by Uncle Engineer — https://uncle-engineer.com/
 */
(function () {
  const fmtPrice = (p) => {
    if (p === null || p === undefined) return "แปรผัน";
    if (p === 0) return "0";
    if (p < 0.01) return p.toFixed(4);
    if (p < 1) return p.toFixed(3).replace(/0+$/, "").replace(/\.$/, "");
    return p.toFixed(2).replace(/\.00$/, "");
  };
  const fmtCtx = (n) => {
    if (!n) return "—";
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(1).replace(/\.0$/, "") + "M";
    if (n >= 1000) return Math.round(n / 1000) + "K";
    return String(n);
  };
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const totalPrice = (m) => (m.is_variable ? Infinity : (m.prompt_price || 0) + (m.completion_price || 0));

  class ModelPicker {
    constructor({ url, onSelect, current }) {
      this.url = url;
      this.onSelect = onSelect;
      this.current = current || "";
      this.models = [];
      this.canUsePaid = true;
      this.state = { q: "", filter: "all", sort: "popular", provider: "" };
      this.loaded = null;

      this.modal = document.getElementById("modelModal");
      this.list = document.getElementById("modelList");
      this.count = document.getElementById("modelCount");
      this.search = document.getElementById("modelSearch");
      this.sortSel = document.getElementById("modelSort");
      this.provSel = document.getElementById("providerFilter");

      this.modal.querySelectorAll("[data-close-modal]").forEach((el) => el.addEventListener("click", () => this.close()));
      document.addEventListener("keydown", (e) => { if (e.key === "Escape" && this.isOpen()) this.close(); });
      this.search.addEventListener("input", () => { this.state.q = this.search.value.trim().toLowerCase(); this.render(); });
      this.sortSel.addEventListener("change", () => { this.state.sort = this.sortSel.value; this.render(); });
      this.provSel.addEventListener("change", () => { this.state.provider = this.provSel.value; this.render(); });
      document.querySelectorAll("#priceFilter button").forEach((b) =>
        b.addEventListener("click", () => {
          document.querySelectorAll("#priceFilter button").forEach((x) => x.classList.remove("active"));
          b.classList.add("active");
          this.state.filter = b.dataset.filter;
          this.render();
        })
      );
      this.list.addEventListener("click", (e) => {
        const row = e.target.closest(".model-row");
        if (!row || row.classList.contains("locked")) return;
        const m = this.models.find((x) => x.id === row.dataset.id);
        if (m) { this.current = m.id; this.onSelect && this.onSelect(m); this.close(); }
      });
    }

    load(force = false) {
      if (this.loaded && !force) return this.loaded;
      this.loaded = fetch(this.url + (force ? "?refresh=1" : ""), { credentials: "same-origin" })
        .then((r) => r.json())
        .then((data) => {
          if (data.error) throw new Error(data.error);
          this.models = data.models || [];
          this.canUsePaid = data.can_use_paid;
          this.role = data.role;
          if (!this.canUsePaid) {
            // Member: เริ่มที่ตัวกรอง "ฟรี"
            this.state.filter = "free";
            document.querySelectorAll("#priceFilter button").forEach((x) => x.classList.toggle("active", x.dataset.filter === "free"));
          }
          const providers = [...new Set(this.models.map((m) => m.provider).filter(Boolean))].sort();
          this.provSel.innerHTML = '<option value="">ทุกผู้ให้บริการ</option>' + providers.map((p) => `<option value="${esc(p)}">${esc(p)}</option>`).join("");
          this.render();
          return this.models;
        })
        .catch((err) => {
          this.loaded = null;
          this.list.innerHTML = `<div class="empty error">${esc(err.message || err)}</div>`;
          this.count.textContent = "โหลดไม่สำเร็จ";
          throw err;
        });
      return this.loaded;
    }

    get(id) { return this.models.find((m) => m.id === id); }

    filtered() {
      const { q, filter, sort, provider } = this.state;
      let arr = this.models.filter((m) => {
        if (filter === "free" && !m.is_free) return false;
        if (filter === "paid" && m.is_free) return false;
        if (provider && m.provider !== provider) return false;
        if (q && !(m.name.toLowerCase().includes(q) || m.id.toLowerCase().includes(q))) return false;
        return true;
      });
      const by = {
        price_asc: (a, b) => totalPrice(a) - totalPrice(b) || a.name.localeCompare(b.name),
        price_desc: (a, b) => {
          const pa = a.is_variable ? -1 : totalPrice(a), pb = b.is_variable ? -1 : totalPrice(b);
          return pb - pa || a.name.localeCompare(b.name);
        },
        newest: (a, b) => (b.created || 0) - (a.created || 0),
        context: (a, b) => (b.context_length || 0) - (a.context_length || 0),
        name: (a, b) => a.name.localeCompare(b.name),
      }[sort];
      if (by) arr = [...arr].sort(by);
      return arr;
    }

    render() {
      const arr = this.filtered();
      const freeCount = this.models.filter((m) => m.is_free).length;
      this.count.textContent = `แสดง ${arr.length} จาก ${this.models.length} โมเดล · ฟรี ${freeCount}` + (this.canUsePaid ? "" : ` · บัญชี ${this.role} ใช้ได้เฉพาะโมเดลฟรี`);
      if (!arr.length) { this.list.innerHTML = '<div class="empty">ไม่พบโมเดลที่ตรงกับเงื่อนไข</div>'; return; }
      this.list.innerHTML = arr.slice(0, 400).map((m) => {
        const locked = !this.canUsePaid && !m.is_free;
        const price = m.is_free
          ? '<span class="badge badge-free">FREE</span>'
          : m.is_variable
          ? '<span class="price muted">แปรผันตามโมเดล</span>'
          : `<span class="price"><b>$${fmtPrice(m.prompt_price)}</b><i>/</i><b>$${fmtPrice(m.completion_price)}</b></span>`;
        const vision = (m.input_modalities || []).includes("image") ? '<span class="badge badge-dim" title="รองรับรูปภาพ">👁 vision</span>' : "";
        return `<div class="model-row ${m.id === this.current ? "selected" : ""} ${locked ? "locked" : ""}" data-id="${esc(m.id)}" title="${esc(m.description)}">
          <div class="mr-main">
            <div class="mr-name">${esc(m.name)} ${vision} ${locked ? '<span class="badge badge-lock">🔒 Pro</span>' : ""}</div>
            <div class="mr-id">${esc(m.id)}</div>
          </div>
          <div class="mr-ctx">${fmtCtx(m.context_length)}</div>
          <div class="mr-price">${price}</div>
        </div>`;
      }).join("");
    }

    isOpen() { return this.modal.classList.contains("open"); }
    open() {
      this.modal.classList.add("open");
      this.modal.setAttribute("aria-hidden", "false");
      this.load().then(() => {
        const sel = this.list.querySelector(".selected");
        if (sel) sel.scrollIntoView({ block: "center" });
      }).catch(() => {});
      setTimeout(() => this.search.focus(), 50);
    }
    close() { this.modal.classList.remove("open"); this.modal.setAttribute("aria-hidden", "true"); }
  }

  window.ModelPicker = ModelPicker;
  window.ModelFmt = { fmtPrice, fmtCtx, esc };
})();
