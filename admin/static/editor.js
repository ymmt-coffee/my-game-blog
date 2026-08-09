(() => {
  const form = document.querySelector("form.editor");
  if (!form) return;
  const status = document.querySelector("#save-status");
  const tab = document.querySelector("#tab-id");
  const token = document.querySelector('meta[name="csrf-token"]').content;
  const typeSelect = form.elements.article_type;
  const updateTypeFields = () => {
    document.querySelectorAll("[data-play-time]").forEach((item) => {
      item.hidden = typeSelect.value !== "play_note";
    });
  };
  typeSelect.addEventListener("change", updateTypeFields);
  updateTypeFields();
  tab.value = sessionStorage.getItem("article-tab-id") || crypto.randomUUID().replaceAll("-", "");
  sessionStorage.setItem("article-tab-id", tab.value);
  let timer = null;
  let firstChange = 0;
  let saving = false;

  const payload = () => ({
    title: form.elements.title.value,
    description: form.elements.description.value,
    article_type: form.elements.article_type.value,
    play_time: form.elements.play_time?.value || "",
    body: form.elements.body.value,
    expected_hash: form.elements.expected_hash.value,
    revision: Number(form.elements.revision.value),
    tab_id: tab.value,
  });

  const autosave = async () => {
    if (saving || form.dataset.conflict === "true") return;
    saving = true;
    status.textContent = "自動保存中";
    try {
      const response = await fetch(`/api/articles/${form.dataset.articleId}/autosave`, {
        method: "POST", headers: {"Content-Type": "application/json", "X-CSRF-Token": token},
        body: JSON.stringify(payload()),
      });
      const result = await response.json();
      if (response.status === 409) {
        status.textContent = "競合・保存停止";
        form.dataset.conflict = "true";
      } else if (!response.ok) {
        status.textContent = "自動保存失敗";
      } else {
        status.textContent = "自動保存済み";
        firstChange = 0;
      }
    } catch (_) { status.textContent = "自動保存失敗"; }
    finally { saving = false; }
  };

  form.addEventListener("input", () => {
    status.textContent = "未保存";
    if (!firstChange) firstChange = Date.now();
    clearTimeout(timer);
    const maxWait = Math.max(0, 30000 - (Date.now() - firstChange));
    timer = setTimeout(autosave, Math.min(2000, maxWait));
  });
  form.addEventListener("submit", () => { status.textContent = "保存中"; });
})();
