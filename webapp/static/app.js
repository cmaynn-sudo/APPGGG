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

  document.querySelectorAll("[data-folder-upload-form]").forEach((form) => {
    form.addEventListener("submit", async (event) => {
      const input = form.querySelector("[data-folder-input]");
      const status = form.parentElement.querySelector("[data-upload-status]");
      if (!input || !input.files || !input.files.length || !window.fetch || !window.FormData) {
        return;
      }

      event.preventDefault();
      const payload = new FormData();
      Array.from(form.elements).forEach((field) => {
        if (!field.name || field.type === "file" || field.type === "submit") {
          return;
        }
        payload.append(field.name, field.value);
      });
      Array.from(input.files).forEach((file) => {
        payload.append(input.name, file, file.webkitRelativePath || file.name);
      });

      const submit = form.querySelector("button[type='submit']");
      if (submit) {
        submit.disabled = true;
        submit.textContent = "Subiendo...";
      }
      if (status) {
        status.textContent = `${input.files.length} archivo(s) seleccionados.`;
      }

      try {
        const response = await fetch(form.action, {
          method: "POST",
          body: payload,
          credentials: "same-origin",
        });
        if (response.redirected) {
          window.location.assign(response.url);
          return;
        }
        if (!response.ok) {
          throw new Error("No se pudo subir la carpeta.");
        }
        window.location.assign("/entregas");
      } catch (error) {
        if (status) {
          status.textContent = error.message || "No se pudo subir la carpeta.";
        }
        if (submit) {
          submit.disabled = false;
          submit.textContent = "Subir carpeta";
        }
      }
    });
  });
})();
