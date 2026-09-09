(() => {
  const root = document.documentElement;
  const button = document.querySelector("[data-theme-toggle]");

  function applyTheme(theme) {
    root.dataset.theme = theme;
    localStorage.setItem("recepcion-theme", theme);
    if (button) {
      button.textContent = theme === "dark" ? "Modo oscuro" : "Modo claro";
      button.setAttribute("aria-label", theme === "dark" ? "Cambiar a modo claro" : "Cambiar a modo oscuro");
    }
  }

  applyTheme(localStorage.getItem("recepcion-theme") || "light");
  if (button) {
    button.addEventListener("click", () => {
      applyTheme(root.dataset.theme === "dark" ? "light" : "dark");
    });
  }
})();
