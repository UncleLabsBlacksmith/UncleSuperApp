/* Uncle Super App — หน้าจัดการผู้ใช้ (เพิ่มผู้ใช้ / ลิงก์รีเซ็ตรหัสผ่าน)
 * Developed by Uncle Engineer — https://uncle-engineer.com/
 */
(function () {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];

  // เปิด/ปิด modal เพิ่มผู้ใช้
  $$("[data-open]").forEach((b) => b.addEventListener("click", () => {
    const m = document.getElementById(b.dataset.open); if (!m) return;
    m.classList.add("open"); setTimeout(() => { const f = $("input:not([type=hidden])", m); if (f) f.focus(); }, 50);
  }));
  $$(".modal [data-close]").forEach((b) => b.addEventListener("click", () => b.closest(".modal").classList.remove("open")));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") $$(".modal.open").forEach((m) => m.classList.remove("open")); });

  // ปิดกล่องลิงก์/รหัสผ่านที่แสดงครั้งเดียว
  $$("[data-dismiss]").forEach((b) => b.addEventListener("click", () => { const el = document.getElementById(b.dataset.dismiss); if (el) el.remove(); }));

  // คัดลอก
  function copy(text, btn) {
    const done = () => { const t = btn.textContent; btn.textContent = "คัดลอกแล้ว ✓"; setTimeout(() => (btn.textContent = t), 1400); };
    if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(text).then(done);
    else { const ta = document.createElement("textarea"); ta.value = text; document.body.appendChild(ta); ta.select(); document.execCommand("copy"); ta.remove(); done(); }
  }
  $$("[data-copy]").forEach((b) => b.addEventListener("click", () => { const el = $(b.dataset.copy); if (el) copy(el.value, b); }));
  $$("input[readonly].mono").forEach((i) => i.addEventListener("focus", () => i.select()));

  // ยืนยันก่อนสร้างลิงก์ใหม่ทับลิงก์เดิม
  $$("form[data-confirm]").forEach((f) => f.addEventListener("submit", (e) => { if (!confirm(f.dataset.confirm)) e.preventDefault(); }));

  // เลื่อนไปที่กล่องลิงก์/รหัสผ่านที่เพิ่งสร้าง
  const issued = $("#issuedLink, #createdUser");
  if (issued) issued.scrollIntoView({ block: "start" });
})();
