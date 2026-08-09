(() => {
  const select = document.querySelector('select[name="article_type"]');
  if (!select) return;
  const update = () => {
    document.querySelectorAll("[data-template-help]").forEach((item) => {
      item.hidden = item.dataset.templateHelp !== select.value;
    });
    document.querySelectorAll("[data-play-time]").forEach((item) => {
      item.hidden = select.value !== "play_note";
      const input = item.querySelector("input");
      if (input) input.required = select.value === "play_note";
    });
  };
  select.addEventListener("change", update);
  update();
})();
