(() => {
  const panel = document.querySelector("#article-picker");
  const button = panel?.querySelector(".picker-toggle");
  if (!panel || !button) return;

  const apply = (collapsed) => {
    panel.classList.toggle("collapsed", collapsed);
    button.setAttribute("aria-expanded", String(!collapsed));
    button.title = collapsed ? "記事一覧を開く" : "記事一覧を折り畳む";
    const icon = button.querySelector("span");
    if (icon) icon.textContent = collapsed ? "▶" : "◀";
  };

  apply(localStorage.getItem("article-picker-collapsed") === "true");
  button.addEventListener("click", () => {
    const collapsed = !panel.classList.contains("collapsed");
    localStorage.setItem("article-picker-collapsed", String(collapsed));
    apply(collapsed);
  });

  const search = panel.querySelector("#article-search");
  const rows = [...panel.querySelectorAll(".picker-item-row")];
  search?.addEventListener("input", () => {
    const query = search.value.trim().toLocaleLowerCase("ja");
    rows.forEach((row) => {
      row.hidden = query !== "" && !row.dataset.search.includes(query);
    });
  });
})();
