(() => {
  const root = document.documentElement;
  const button = document.querySelector("[data-theme-toggle]");
  const themeLabel = document.querySelector("[data-theme-label]");

  function applyTheme(theme) {
    root.dataset.theme = theme;
    localStorage.setItem("recepcion-theme", theme);
    if (button) {
      button.setAttribute("aria-label", theme === "dark" ? "Cambiar a modo claro" : "Cambiar a modo oscuro");
    }
    if (themeLabel) {
      themeLabel.textContent = theme === "dark" ? "Cambiar a modo claro" : "Cambiar a modo oscuro";
    }
  }

  applyTheme(localStorage.getItem("recepcion-theme") || "light");
  if (button) {
    button.addEventListener("click", () => {
      applyTheme(root.dataset.theme === "dark" ? "light" : "dark");
    });
  }

  document.querySelectorAll("[data-history-upload-form], [data-folder-upload-form]").forEach((form) => {
    form.addEventListener("submit", async (event) => {
      const input = form.querySelector("[data-upload-input], [data-folder-input]");
      const status = form.querySelector("[data-upload-status]") || form.parentElement.querySelector("[data-upload-status]");
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
        const label = submit.querySelector("span");
        if (label) {
          label.textContent = "Importando...";
        } else {
          submit.textContent = "Importando...";
        }
      }
      if (status) {
        const totalBytes = Array.from(input.files).reduce((sum, file) => sum + file.size, 0);
        const totalMb = (totalBytes / (1024 * 1024)).toFixed(1);
        status.textContent = `${input.files.length} archivo(s), ${totalMb} MB. No cierres esta pestaña.`;
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
          const label = submit.querySelector("span");
          const idleLabel = submit.dataset.idleLabel || "Subir carpeta";
          if (label) {
            label.textContent = idleLabel;
          } else {
            submit.textContent = idleLabel;
          }
        }
      }
    });
  });
})();
