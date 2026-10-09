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

  const chartModeButtons = Array.from(document.querySelectorAll("[data-chart-mode]"));
  const chartViews = Array.from(document.querySelectorAll("[data-chart-view]"));
  const chartHeading = document.querySelector("[data-chart-heading]");
  const chartDescription = document.querySelector("[data-chart-description]");

  function applyChartMode(mode) {
    const selectedMode = mode === "weight" ? "weight" : "money";
    chartModeButtons.forEach((control) => {
      const active = control.dataset.chartMode === selectedMode;
      control.classList.toggle("active", active);
      control.setAttribute("aria-pressed", String(active));
    });
    chartViews.forEach((view) => {
      view.hidden = view.dataset.chartView !== selectedMode;
    });
    if (chartHeading) {
      chartHeading.textContent = selectedMode === "weight" ? "Gramos facturados por mes" : "Facturación mensual";
    }
    if (chartDescription) {
      chartDescription.textContent = selectedMode === "weight"
        ? "Pesos iniciales y finales de los boletines filtrados"
        : "Valor total de metales de los boletines filtrados";
    }
    localStorage.setItem("dashboard-chart-mode", selectedMode);
  }

  if (chartModeButtons.length && chartViews.length) {
    chartModeButtons.forEach((control) => {
      control.addEventListener("click", () => applyChartMode(control.dataset.chartMode));
    });
    applyChartMode(localStorage.getItem("dashboard-chart-mode") || "money");
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
    const initialAssets = document.querySelector("#layout-initial-assets");
    const savedStyle = document.querySelector("#saved-layout-style");
    const textTools = layoutEditor.querySelector("[data-layout-text-tools]");
    const textEnabled = layoutEditor.querySelector("[data-layout-text-enabled]");
    const textValue = layoutEditor.querySelector("[data-layout-text-value]");
    const imageTools = layoutEditor.querySelector("[data-layout-image-tools]");
    const imageForm = layoutEditor.querySelector("[data-layout-image-form]");
    const imageIdInput = layoutEditor.querySelector("[data-layout-image-id]");
    const imageInput = layoutEditor.querySelector("[data-layout-image-input]");
    const imageStatus = layoutEditor.querySelector("[data-layout-image-status]");
    const imageRemove = layoutEditor.querySelector("[data-layout-image-remove]");
    const modeControls = document.querySelectorAll("[data-layout-mode]");
    const defaults = {
      x: 0,
      y: 0,
      scale: 1,
      font_size: 0,
      width: 0,
      height: 0,
      text_align: "",
      nowrap: false,
      hidden: false,
      text_override: null,
    };
    let state = {};
    let assets = {};
    let selectedElement = null;
    let dragState = null;
    let characterMode = false;
    const textEditable = new WeakSet();
    const originalMarkup = new WeakMap();
    const originalText = new WeakMap();
    const originalSources = new WeakMap();
    const originalElementStyles = new WeakMap();
    const originalCellStyles = new WeakMap();
    const originalColumnStyles = new WeakMap();
    const originalRowStyles = new WeakMap();

    try {
      const parsed = JSON.parse(initialState?.textContent || "{}");
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        state = parsed;
      }
    } catch (_error) {
      state = {};
    }
    try {
      const parsed = JSON.parse(initialAssets?.textContent || "{}");
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        assets = parsed;
      }
    } catch (_error) {
      assets = {};
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
        width: numberValue(raw.width, defaults.width),
        height: numberValue(raw.height, defaults.height),
        text_align: ["left", "center", "right"].includes(raw.text_align) ? raw.text_align : "",
        nowrap: Boolean(raw.nowrap),
        hidden: Boolean(raw.hidden),
        text_override: Object.prototype.hasOwnProperty.call(raw, "text_override") && typeof raw.text_override === "string"
          ? raw.text_override
          : null,
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

    const elementStyleProperties = [
      "transform",
      "transform-origin",
      "font-size",
      "white-space",
      "overflow-wrap",
      "word-break",
      "text-align",
      "display",
      "width",
      "height",
      "min-width",
      "min-height",
    ];
    const cellStyleProperties = ["width", "height", "min-width", "min-height"];
    const columnStyleProperties = ["width", "min-width"];
    const rowStyleProperties = ["height", "min-height"];

    function captureStyles(element, properties) {
      return Object.fromEntries(properties.map((property) => [
        property,
        {
          value: element.style.getPropertyValue(property),
          priority: element.style.getPropertyPriority(property),
        },
      ]));
    }

    function restoreStyles(element, snapshot, properties) {
      properties.forEach((property) => {
        const original = snapshot?.[property];
        if (original?.value) {
          element.style.setProperty(property, original.value, original.priority);
        } else {
          element.style.removeProperty(property);
        }
      });
    }

    function isTextEditable(element) {
      return element.tagName !== "IMG"
        && (textEditable.has(element)
          || Array.from(element.children).every((child) => child.tagName === "BR"));
    }

    function elementText(element) {
      return Array.from(element.childNodes).map((node) => {
        if (node.nodeType === Node.TEXT_NODE) return node.textContent;
        if (node.nodeName === "BR") return "\n";
        return elementText(node);
      }).join("");
    }

    function hasCharacterSettings(elementId) {
      return Object.keys(state).some((key) => key.startsWith(`char-${elementId}-`));
    }

    function renderCharacters(element) {
      if (element.hasAttribute("data-layout-character") || !isTextEditable(element)) return;
      const parentId = element.dataset.layoutId;
      if (!characterMode && !hasCharacterSettings(parentId)) return;
      const text = elementText(element);
      const fragment = document.createDocumentFragment();
      let word = null;
      Array.from(text).forEach((character, index) => {
        if (character === "\n") {
          fragment.appendChild(document.createElement("br"));
          word = null;
          return;
        }
        const glyph = document.createElement("span");
        glyph.dataset.layoutId = `char-${parentId}-${index}`;
        glyph.dataset.layoutParent = parentId;
        glyph.dataset.layoutCharacter = "";
        glyph.dataset.layoutLabel = `Carácter ${index + 1}: ${character === " " ? "espacio" : character}`;
        glyph.textContent = character;
        if (/\s/.test(character)) {
          word = null;
          fragment.appendChild(glyph);
        } else {
          if (!word) {
            word = document.createElement("span");
            word.dataset.layoutWord = "";
            fragment.appendChild(word);
          }
          word.appendChild(glyph);
        }
        registerElement(glyph);
        if (state[glyph.dataset.layoutId]) applySettings(glyph, state[glyph.dataset.layoutId]);
      });
      element.replaceChildren(fragment);
    }

    function excelColumnNumber(column) {
      return Array.from(column).reduce((number, letter) => number * 26 + letter.charCodeAt(0) - 64, 0);
    }

    function cellGeometry(element) {
      if (element.hasAttribute("data-layout-character")) {
        return { cell: null, column: null, row: null };
      }
      const cell = element.closest("[data-cell]");
      const match = cell?.dataset.cell?.match(/^([A-Z]+)(\d+)$/);
      const table = cell?.closest("table");
      if (!cell || !match || !table) {
        return { cell, column: null, row: cell?.closest("tr") || null };
      }
      const columnIndex = excelColumnNumber(match[1]) - 1;
      return {
        cell,
        column: table.querySelectorAll("colgroup col")[columnIndex] || null,
        row: cell.closest("tr"),
      };
    }

    function clearElementStyles(element) {
      restoreStyles(element, originalElementStyles.get(element), elementStyleProperties);
      const { cell, column, row } = cellGeometry(element);
      if (cell) {
        restoreStyles(cell, originalCellStyles.get(cell), cellStyleProperties);
      }
      if (textEditable.has(element) && originalMarkup.has(element)) {
        element.innerHTML = originalMarkup.get(element);
      }
      if (originalSources.has(element)) {
        element.setAttribute("src", originalSources.get(element));
      }
    }

    function applySettings(element, settings) {
      clearElementStyles(element);
      const elementId = element.dataset.layoutId;
      if (element.tagName === "IMG" && assets[elementId]?.url) {
        element.setAttribute("src", assets[elementId].url);
      }
      if (!settings) {
        renderCharacters(element);
        return;
      }
      const values = normalizedSettings(settings);
      if (values.text_override !== null && isTextEditable(element)) {
        element.textContent = values.text_override;
        element.style.setProperty("white-space", "pre-wrap", "important");
      }
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
      const { cell, column, row } = cellGeometry(element);
      if (cell) {
        if (values.width > 0) {
          cell.style.setProperty("width", `${values.width}px`, "important");
          cell.style.setProperty("min-width", `${values.width}px`, "important");
          column?.style.setProperty("width", `${values.width}px`, "important");
          column?.style.setProperty("min-width", `${values.width}px`, "important");
        }
        if (values.height > 0) {
          cell.style.setProperty("height", `${values.height}px`, "important");
          cell.style.setProperty("min-height", `${values.height}px`, "important");
          row?.style.setProperty("height", `${values.height}px`, "important");
          row?.style.setProperty("min-height", `${values.height}px`, "important");
          element.style.setProperty("display", "block", "important");
          element.style.setProperty("min-height", `${values.height}px`, "important");
        }
      } else {
        if (values.width > 0) {
          element.style.setProperty("width", `${values.width}px`, "important");
        }
        if (values.height > 0) {
          element.style.setProperty("height", `${values.height}px`, "important");
        }
      }
      if (values.hidden) {
        element.style.setProperty("display", "none", "important");
      }
      renderCharacters(element);
    }

    function elementForId(elementId) {
      return Array.from(preview?.querySelectorAll("[data-layout-id]") || []).find(
        (element) => element.dataset.layoutId === elementId,
      );
    }

    function refreshGeometry() {
      editableElements.forEach((element) => {
        const { column, row } = cellGeometry(element);
        if (column) restoreStyles(column, originalColumnStyles.get(column), columnStyleProperties);
        if (row) restoreStyles(row, originalRowStyles.get(row), rowStyleProperties);
      });
      editableElements.forEach((element) => {
        const values = normalizedSettings(state[element.dataset.layoutId]);
        const { column, row } = cellGeometry(element);
        if (values.width > 0 && column) column.style.setProperty("width", `${values.width}px`, "important");
        if (values.height > 0 && row) row.style.setProperty("height", `${values.height}px`, "important");
      });
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

    function registerElement(element) {
      originalMarkup.set(element, element.innerHTML);
      originalText.set(element, elementText(element));
      if (isTextEditable(element)) textEditable.add(element);
      originalElementStyles.set(element, captureStyles(element, elementStyleProperties));
      if (element.tagName === "IMG") {
        originalSources.set(element, element.getAttribute("src") || "");
      }
      const { cell, column, row } = cellGeometry(element);
      if (cell && !originalCellStyles.has(cell)) {
        originalCellStyles.set(cell, captureStyles(cell, cellStyleProperties));
      }
      if (column && !originalColumnStyles.has(column)) {
        originalColumnStyles.set(column, captureStyles(column, columnStyleProperties));
      }
      if (row && !originalRowStyles.has(row)) {
        originalRowStyles.set(row, captureStyles(row, rowStyleProperties));
      }
    }

    const editableElements = Array.from(preview?.querySelectorAll("[data-layout-id]") || []);
    editableElements.forEach(registerElement);

    function refreshElementOptions() {
      if (!elementSelect) return;
      elementSelect.replaceChildren(new Option("Sin selección", ""));
      const parentId = selectedElement?.dataset.layoutParent || selectedElement?.dataset.layoutId;
      const characters = characterMode && parentId
        ? Array.from(elementForId(parentId)?.querySelectorAll("[data-layout-character]") || [])
        : [];
      [...editableElements, ...characters].forEach((element) => {
        const option = document.createElement("option");
        option.value = element.dataset.layoutId;
        option.textContent = elementLabel(element);
        elementSelect.appendChild(option);
      });
      elementSelect.value = selectedElement?.dataset.layoutId || "";
    }
    refreshElementOptions();

    if (savedStyle) {
      savedStyle.textContent = "";
    }
    editableElements.forEach((element) => {
      const elementId = element.dataset.layoutId;
      if (state[elementId] || assets[elementId] || hasCharacterSettings(elementId)) {
        applySettings(element, state[elementId]);
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
      const canEditText = Boolean(selectedElement && isTextEditable(selectedElement));
      if (textTools) {
        textTools.hidden = !canEditText;
      }
      if (canEditText && textEnabled && textValue) {
        const customText = settings.text_override !== null;
        textEnabled.checked = customText;
        textValue.disabled = !customText;
        textValue.value = customText
          ? settings.text_override
          : originalText.get(selectedElement) || "";
      }

      const isImage = selectedElement?.tagName === "IMG";
      if (imageTools) {
        imageTools.hidden = !isImage;
      }
      if (isImage) {
        const elementId = selectedElement.dataset.layoutId;
        if (imageIdInput) {
          imageIdInput.value = elementId;
        }
        if (imageStatus) {
          imageStatus.textContent = assets[elementId]
            ? `Reemplazo activo: ${assets[elementId].filename || "imagen personalizada"}`
            : "Se está usando la imagen original de la plantilla.";
        }
        if (imageRemove) {
          imageRemove.hidden = !assets[elementId];
        }
      }
    }

    function selectElement(element) {
      if (!element || !preview?.contains(element)) {
        return;
      }
      selectedElement?.classList.remove("layout-selected");
      selectedElement = element;
      selectedElement.classList.add("layout-selected");
      refreshElementOptions();
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
      refreshGeometry();
      updateInspector(state[elementId]);
      syncState();
    }

    preview?.addEventListener("pointerdown", (event) => {
      const directElement = event.target.closest("[data-layout-id]");
      const cell = event.target.closest("[data-cell]");
      let element = directElement || cell?.querySelector("[data-layout-id]");
      if (!characterMode && element?.hasAttribute("data-layout-character")) {
        element = elementForId(element.dataset.layoutParent);
      }
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

    textEnabled?.addEventListener("change", () => {
      if (!selectedElement || !isTextEditable(selectedElement)) {
        return;
      }
      updateSelected({
        text_override: textEnabled.checked
          ? textValue?.value ?? originalText.get(selectedElement) ?? ""
          : null,
      });
    });

    textValue?.addEventListener("input", () => {
      if (!selectedElement || !textEnabled?.checked || !isTextEditable(selectedElement)) {
        return;
      }
      const elementId = selectedElement.dataset.layoutId;
      const settings = normalizedSettings(state[elementId]);
      state[elementId] = normalizedSettings({ ...settings, text_override: textValue.value });
      applySettings(selectedElement, state[elementId]);
      syncState();
    });

    imageForm?.addEventListener("submit", async (event) => {
      if (!selectedElement || selectedElement.tagName !== "IMG" || !imageInput?.files?.length) {
        return;
      }
      event.preventDefault();
      const elementId = selectedElement.dataset.layoutId;
      if (imageIdInput) {
        imageIdInput.value = elementId;
      }
      const submit = imageForm.querySelector("button[type='submit']");
      if (submit) {
        submit.disabled = true;
      }
      if (imageStatus) {
        imageStatus.textContent = "Subiendo y guardando la imagen...";
      }
      try {
        const response = await fetch(imageForm.action, {
          method: "POST",
          body: new FormData(imageForm),
          credentials: "same-origin",
          headers: { "X-Requested-With": "fetch" },
        });
        const result = await response.json().catch(() => ({}));
        if (!response.ok || !result.url) {
          throw new Error(result.message || "No se pudo guardar la imagen.");
        }
        assets[elementId] = { url: result.url, filename: result.filename };
        applySettings(selectedElement, state[elementId]);
        updateInspector(normalizedSettings(state[elementId]));
        imageInput.value = "";
      } catch (error) {
        if (imageStatus) {
          imageStatus.textContent = error.message || "No se pudo guardar la imagen.";
        }
      } finally {
        if (submit) {
          submit.disabled = false;
        }
      }
    });

    imageRemove?.addEventListener("click", async () => {
      if (!selectedElement || selectedElement.tagName !== "IMG") {
        return;
      }
      const elementId = selectedElement.dataset.layoutId;
      imageRemove.disabled = true;
      if (imageStatus) {
        imageStatus.textContent = "Restaurando la imagen original...";
      }
      try {
        const response = await fetch("/editor-plantillas/imagen/eliminar", {
          method: "POST",
          body: new URLSearchParams({
            slug: imageForm?.querySelector("input[name='slug']")?.value || "",
            element_id: elementId,
          }),
          credentials: "same-origin",
          headers: { "X-Requested-With": "fetch" },
        });
        if (!response.ok) {
          throw new Error("No se pudo restaurar la imagen original.");
        }
        delete assets[elementId];
        applySettings(selectedElement, state[elementId]);
        updateInspector(normalizedSettings(state[elementId]));
      } catch (error) {
        if (imageStatus) {
          imageStatus.textContent = error.message || "No se pudo restaurar la imagen original.";
        }
      } finally {
        imageRemove.disabled = false;
      }
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
      if (!selectedElement.hasAttribute("data-layout-character")) {
        const prefix = `char-${selectedElement.dataset.layoutId}-`;
        Object.keys(state).filter((key) => key.startsWith(prefix)).forEach((key) => delete state[key]);
      }
      applySettings(selectedElement, null);
      refreshGeometry();
      updateInspector(defaults);
      syncState();
    });

    modeControls.forEach((control) => {
      control.addEventListener("change", () => {
        if (!control.checked) return;
        const parentId = selectedElement?.dataset.layoutParent || selectedElement?.dataset.layoutId;
        selectedElement?.classList.remove("layout-selected");
        characterMode = control.value === "character";
        layoutEditor.dataset.selectionMode = control.value;
        editableElements.forEach((element) => applySettings(element, state[element.dataset.layoutId]));
        refreshGeometry();
        const parent = elementForId(parentId);
        if (parent) selectElement(parent);
        else refreshElementOptions();
      });
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
