document.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-copy-social]");
  if (!button) return;
  const textarea = document.getElementById(button.dataset.copySocial);
  if (!textarea) return;
  await navigator.clipboard.writeText(textarea.value);
  const original = button.textContent;
  button.textContent = "コピーしました";
  window.setTimeout(() => { button.textContent = original; }, 1200);
});
