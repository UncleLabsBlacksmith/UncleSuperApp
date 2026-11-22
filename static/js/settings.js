/* Uncle Super App — Settings page */
(function () {
  const keyInput = document.getElementById("id_api_key");
  const toggle = document.getElementById("toggleKey");
  const testBtn = document.getElementById("testKey");
  const result = document.getElementById("keyResult");
  const esc = window.ModelFmt.esc;

  toggle && toggle.addEventListener("click", () => {
    const show = keyInput.type === "password";
    keyInput.type = show ? "text" : "password";
    toggle.textContent = show ? "ซ่อน" : "แสดง";
  });

  testBtn && testBtn.addEventListener("click", async () => {
    testBtn.disabled = true;
    testBtn.textContent = "กำลังทดสอบ…";
    result.hidden = false;
    result.className = "key-result";
    result.textContent = "กำลังตรวจสอบกับ OpenRouter…";
    try {
      const fd = new FormData();
      fd.append("api_key", keyInput.value);
      const r = await fetch(APP.testKeyUrl, { method: "POST", body: fd, headers: { "X-CSRFToken": APP.csrf }, credentials: "same-origin" });
      const d = await r.json();
      result.classList.add(d.ok ? "ok" : "err");
      if (d.ok) {
        const parts = [`✓ ${esc(d.message)}`];
        if (d.label) parts.push(`label: <code>${esc(d.label)}</code>`);
        if (d.usage !== undefined && d.usage !== null) parts.push(`ใช้ไปแล้ว: $${Number(d.usage).toFixed(4)}`);
        parts.push(d.limit === null || d.limit === undefined ? "วงเงิน: ไม่จำกัด" : `คงเหลือ: $${Number(d.limit_remaining ?? 0).toFixed(2)} / $${d.limit}`);
        if (d.is_free_tier) parts.push("Free tier");
        result.innerHTML = parts.join(" · ");
      } else {
        result.innerHTML = `✕ ${esc(d.message || "ใช้งานไม่ได้")}`;
      }
    } catch (e) {
      result.classList.add("err");
      result.textContent = "✕ เกิดข้อผิดพลาด: " + e;
    } finally {
      testBtn.disabled = false;
      testBtn.textContent = "ทดสอบคีย์";
    }
  });

  // เลือกโมเดลเริ่มต้นจากรายการ
  const modelInput = document.getElementById("id_default_model");
  const picker = new ModelPicker({
    url: APP.modelsUrl,
    current: modelInput.value,
    onSelect: (m) => { modelInput.value = m.id; },
  });
  document.getElementById("openPicker").addEventListener("click", () => { picker.current = modelInput.value; picker.open(); });
})();
