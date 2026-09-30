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

  const layoutEditor = document.querySelector("[data-layout-editor]");
  if (layoutEditor) {
    const preview = layoutEditor.querySelector("[data-layout-preview]");
    const canvas = layoutEditor.querySelector("[data-layout-canvas]");
    const controls = layoutEditor.querySelector("[data-layout-controls]");
    const selectionLabel = layoutEditor.querySelector("[data-layout-selection-label]");
    const elementSelect = layoutEditor.querySelector("[data-layout-element-select]");
    const resetElementButton = layoutEditor.querySelector("[data-layout-reset-element]");
    const scaleOutput = layoutEditor.querySelector("[data-layout-scale-output]");
    const layoutInput = document.querySelector("[data-layout-json]");
    const zoomControl = document.querySelector("[data-layout-zoom]");
    const templateControl = document.querySelector("[data-layout-template-select]");
    const initialState = document.querySelector("#layout-initial-state");
    const savedStyle = document.querySelector("#saved-layout-style");
    const defaults = {
      x: 0,
      y: 0,
      scale: 1,
      font_size: 0,
      text_align: "",
      nowrap: false,
    };
    let state = {};
    let selectedElement = null;
    let dragState = null;

    try {
      const parsed = JSON.parse(initialState?.textContent || "{}");
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        state = parsed;
      }
    } catch (_error) {
      state = {};
    }

    function numberValue(value, fallback) {
      const number = Number(value);
      return Number.isFinite(number) ? number : fallback;
    }

    function normalizedSettings(raw = {}) {
      return {
        x: numberValue(raw.x, defaults.x),
        y: numberValue(raw.y, defaults.y),
        scale: numberValue(raw.scale, defaults.scale),
        font_size: numberValue(raw.font_size, defaults.font_size),
        text_align: ["left", "center", "right"].includes(raw.text_align) ? raw.text_align : "",
        nowrap: Boolean(raw.nowrap),
      };
    }

    Object.keys(state).forEach((elementId) => {
      state[elementId] = normalizedSettings(state[elementId]);
    });

    function syncState() {
      if (layoutInput) {
        layoutInput.value = JSON.stringify(state);
      }
    }

    function clearElementStyles(element) {
      [
        "transform",
        "transform-origin",
        "font-size",
        "white-space",
        "overflow-wrap",
        "word-break",
        "text-align",
      ].forEach((property) => element.style.removeProperty(property));
    }

    function applySettings(element, settings) {
      clearElementStyles(element);
      if (!settings) {
        return;
      }
      const values = normalizedSettings(settings);
      element.style.setProperty(
        "transform",
        `translate(${values.x}px, ${values.y}px) scale(${values.scale})`,
        "important",
      );
      element.style.setProperty("transform-origin", "center center", "important");
      if (values.font_size > 0) {
        element.style.setProperty("font-size", `${values.font_size}px`, "important");
      }
      if (values.nowrap) {
        element.style.setProperty("white-space", "nowrap", "important");
        element.style.setProperty("overflow-wrap", "normal", "important");
        element.style.setProperty("word-break", "normal", "important");
      }
      if (values.text_align) {
        element.style.setProperty("text-align", values.text_align, "important");
      }
    }

    function elementForId(elementId) {
      return Array.from(preview?.querySelectorAll("[data-layout-id]") || []).find(
        (element) => element.dataset.layoutId === elementId,
      );
    }

    function elementLabel(element) {
      const base = element.dataset.layoutLabel || element.dataset.layoutId;
      const content = (element.textContent || "").replace(/\s+/g, " ").trim();
      if (!content || content === base) {
        return base;
      }
      const summary = content.length > 42 ? `${content.slice(0, 39)}...` : content;
      return `${base} · ${summary}`;
    }

    const editableElements = Array.from(preview?.querySelectorAll("[data-layout-id]") || []);
    if (elementSelect) {
      editableElements.forEach((element) => {
        const option = document.createElement("option");
        option.value = element.dataset.layoutId;
        option.textContent = elementLabel(element);
        elementSelect.appendChild(option);
      });
    }

    if (savedStyle) {
      savedStyle.textContent = "";
    }
    Object.entries(state).forEach(([elementId, settings]) => {
      const element = elementForId(elementId);
      if (element) {
        applySettings(element, settings);
      }
    });
    syncState();

    function updateInspector(settings) {
      if (!controls) {
        return;
      }
      controls.querySelectorAll("[data-layout-control]").forEach((control) => {
        const name = control.dataset.layoutControl;
        if (control.type === "checkbox") {
          control.checked = Boolean(settings[name]);
        } else {
          control.value = settings[name] ?? "";
        }
      });
      if (scaleOutput) {
        scaleOutput.value = `${Math.round(settings.scale * 100)}%`;
        scaleOutput.textContent = `${Math.round(settings.scale * 100)}%`;
      }
    }

    function selectElement(element) {
      if (!element || !preview?.contains(element)) {
        return;
      }
      selectedElement?.classList.remove("layout-selected");
      selectedElement = element;
      selectedElement.classList.add("layout-selected");
      const label = elementLabel(element);
      if (selectionLabel) {
        selectionLabel.textContent = label;
        selectionLabel.title = element.dataset.layoutId;
      }
      if (elementSelect) {
        elementSelect.value = element.dataset.layoutId;
      }
      if (controls) {
        controls.disabled = false;
      }
      if (resetElementButton) {
        resetElementButton.disabled = false;
      }
      updateInspector(normalizedSettings(state[element.dataset.layoutId]));
    }

    function updateSelected(changes) {
      if (!selectedElement) {
        return;
      }
      const elementId = selectedElement.dataset.layoutId;
      const settings = normalizedSettings(state[elementId]);
      state[elementId] = normalizedSettings({ ...settings, ...changes });
      applySettings(selectedElement, state[elementId]);
      updateInspector(state[elementId]);
      syncState();
    }

    preview?.addEventListener("pointerdown", (event) => {
      const directElement = event.target.closest("[data-layout-id]");
      const cell = event.target.closest("[data-cell]");
      const element = directElement || cell?.querySelector("[data-layout-id]");
      if (!element || !preview.contains(element)) {
        return;
      }
      event.preventDefault();
      selectElement(element);
      const settings = normalizedSettings(state[element.dataset.layoutId]);
      dragState = {
        pointerId: event.pointerId,
        startX: event.clientX,
        startY: event.clientY,
        x: settings.x,
        y: settings.y,
      };
      element.setPointerCapture?.(event.pointerId);
    });

    document.addEventListener("pointermove", (event) => {
      if (!dragState || event.pointerId !== dragState.pointerId || !selectedElement) {
        return;
      }
      const zoom = numberValue(zoomControl?.value, 1);
      updateSelected({
        x: Math.round((dragState.x + (event.clientX - dragState.startX) / zoom) * 10) / 10,
        y: Math.round((dragState.y + (event.clientY - dragState.startY) / zoom) * 10) / 10,
      });
    });

    function endDrag(event) {
      if (dragState && event.pointerId === dragState.pointerId) {
        dragState = null;
      }
    }
    document.addEventListener("pointerup", endDrag);
    document.addEventListener("pointercancel", endDrag);

    controls?.querySelectorAll("[data-layout-control]").forEach((control) => {
      const eventName = control.tagName === "SELECT" || control.type === "checkbox" ? "change" : "input";
      control.addEventListener(eventName, () => {
        const name = control.dataset.layoutControl;
        const value = control.type === "checkbox"
          ? control.checked
          : name === "text_align"
            ? control.value
            : numberValue(control.value, defaults[name]);
        updateSelected({ [name]: value });
      });
    });

    layoutEditor.querySelectorAll("[data-layout-nudge-x]").forEach((button) => {
      button.addEventListener("click", () => {
        if (!selectedElement) {
          return;
        }
        const settings = normalizedSettings(state[selectedElement.dataset.layoutId]);
        updateSelected({
          x: settings.x + numberValue(button.dataset.layoutNudgeX, 0),
          y: settings.y + numberValue(button.dataset.layoutNudgeY, 0),
        });
      });
    });

    resetElementButton?.addEventListener("click", () => {
      if (!selectedElement) {
        return;
      }
      delete state[selectedElement.dataset.layoutId];
      clearElementStyles(selectedElement);
      updateInspector(defaults);
      syncState();
    });

    zoomControl?.addEventListener("change", () => {
      preview?.style.setProperty("--editor-zoom", zoomControl.value);
      canvas?.style.setProperty("--editor-zoom", zoomControl.value);
    });

    templateControl?.addEventListener("change", () => {
      templateControl.form?.submit();
    });

    elementSelect?.addEventListener("change", () => {
      const element = elementForId(elementSelect.value);
      if (element) {
        selectElement(element);
      }
    });

    document.addEventListener("keydown", (event) => {
      if (!selectedElement || !["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(event.key)) {
        return;
      }
      if (["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement?.tagName)) {
        return;
      }
      event.preventDefault();
      const step = event.shiftKey ? 10 : 1;
      const settings = normalizedSettings(state[selectedElement.dataset.layoutId]);
      updateSelected({
        x: settings.x + (event.key === "ArrowLeft" ? -step : event.key === "ArrowRight" ? step : 0),
        y: settings.y + (event.key === "ArrowUp" ? -step : event.key === "ArrowDown" ? step : 0),
      });
    });
  }
})();
