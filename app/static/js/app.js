(() => {
  "use strict";

  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const loginUsername = document.getElementById("username");
  loginUsername?.addEventListener("input", () => {
    loginUsername.value = loginUsername.value.toLowerCase();
  });
  document.getElementById("toggleLoginPassword")?.addEventListener("click", event => {
    const password = document.getElementById("password");
    if (!password) return;
    const show = password.type === "password";
    password.type = show ? "text" : "password";
    event.currentTarget.textContent = show ? "Masquer" : "Afficher";
    event.currentTarget.setAttribute("aria-pressed", String(show));
    password.focus();
  });
  function showToast(message, error = false) {
    const toastElement = document.getElementById("appToast");
    const messageElement = document.getElementById("appToastMessage");
    if (!toastElement || !messageElement) return;
    messageElement.textContent = message;
    toastElement.classList.toggle("text-bg-danger", error);
    toastElement.classList.toggle("text-bg-dark", !error);
    if (window.bootstrap?.Toast) {
      bootstrap.Toast.getOrCreateInstance(toastElement, { delay: error ? 5000 : 1800 }).show();
    } else {
      toastElement.classList.add("show");
      setTimeout(() => toastElement.classList.remove("show"), error ? 5000 : 1800);
    }
  }

  async function apiFetch(url, options = {}) {
    const response = await fetch(url, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrfToken,
        ...(options.headers || {}),
      },
    });
    const payload = await response.json().catch(() => ({ ok: false, error: "Réponse serveur invalide." }));
    if (response.status === 401) {
      if (!window.__sessionRedirectInProgress) {
        window.__sessionRedirectInProgress = true;
        const returnPath = `${window.location.pathname}${window.location.search}`;
        window.location.assign(`/auth/login?next=${encodeURIComponent(returnPath)}`);
      }
      throw new Error("Votre session a expiré. Reconnexion en cours…");
    }
    if (!response.ok || payload.ok === false) {
      const error = new Error(payload.error || `Erreur HTTP ${response.status}`);
      error.payload = payload;
      throw error;
    }
    return payload;
  }

  const allInputs = () => Array.from(document.querySelectorAll(".value-input"));

  function updateCellVisual(input, payload) {
    const cell = input.closest(".value-cell");
    if (!cell) return;
    ["unverified", "verified", "anomaly", "not_applicable"].forEach(status => cell.classList.remove(`status-${status}`));
    cell.classList.add(`status-${payload.status}`);
    cell.classList.toggle("is-corrected", Boolean(payload.corrected));
    input.dataset.status = payload.status;
    input.dataset.raw = payload.raw_value;
    input.dataset.display = payload.display_value;
    input.dataset.dirty = "false";
    cell.querySelectorAll("[data-set-status]").forEach(button => {
      button.setAttribute("aria-pressed", String(button.dataset.setStatus === payload.status));
    });
    if (document.activeElement !== input) input.value = payload.display_value;
  }

  async function saveCell(input, forcedStatus = null) {
    if (!input) return;
    const cell = input.closest(".value-cell");
    const value = input.dataset.dirty === "true" ? input.value : input.dataset.raw;
    const status = forcedStatus || (input.dataset.dirty === "true" ? "verified" : input.dataset.status || "unverified");
    cell?.classList.add("is-saving");
    const indicator = cell?.querySelector(".save-indicator");
    if (indicator) indicator.textContent = "…";
    try {
      const payload = await apiFetch(`/dsf/api/values/${input.dataset.valueId}`, {
        method: "PATCH",
        body: JSON.stringify({ value, status }),
      });
      updateCellVisual(input, payload);
      if (indicator) {
        indicator.textContent = "Enregistré";
        setTimeout(() => { indicator.textContent = ""; }, 1400);
      }
      const progress = document.getElementById("dsfProgressText");
      const bar = document.getElementById("dsfProgressBar");
      if (progress) progress.textContent = payload.progress;
      if (bar) bar.style.width = `${payload.progress}%`;
    } catch (error) {
      if (indicator) indicator.textContent = "Erreur";
      showToast(error.message, true);
      input.focus();
      throw error;
    } finally {
      cell?.classList.remove("is-saving");
    }
  }

  allInputs().forEach(input => {
    input.dataset.display = input.value;
    input.dataset.dirty = "false";
    input.addEventListener("focus", () => {
      input.value = input.dataset.raw;
      input.select();
    });
    input.addEventListener("input", () => { input.dataset.dirty = "true"; });
    input.addEventListener("blur", async () => {
      if (input.dataset.dirty === "true") {
        await saveCell(input).catch(() => {});
      } else {
        input.value = input.dataset.display;
      }
    });
    input.addEventListener("keydown", async event => {
      if (event.key === "Enter") {
        event.preventDefault();
        await saveCell(input).catch(() => {});
        const inputs = allInputs();
        const next = inputs[inputs.indexOf(input) + 1];
        next?.focus();
      } else if (event.key === "F2") {
        event.preventDefault();
        input.select();
      } else if (!event.altKey && (event.key === "ArrowUp" || event.key === "ArrowDown")) {
        const row = input.closest("tr");
        const cell = input.closest("td");
        const targetRow = event.key === "ArrowUp" ? row?.previousElementSibling : row?.nextElementSibling;
        const target = targetRow?.children[cell?.cellIndex]?.querySelector(".value-input");
        if (target) { event.preventDefault(); target.focus(); }
      } else if (!event.altKey && event.key === "ArrowLeft" && input.selectionStart === 0) {
        const inputs = allInputs(); const previous = inputs[inputs.indexOf(input) - 1];
        if (previous) { event.preventDefault(); previous.focus(); }
      } else if (!event.altKey && event.key === "ArrowRight" && input.selectionStart === input.value.length) {
        const inputs = allInputs(); const next = inputs[inputs.indexOf(input) + 1];
        if (next) { event.preventDefault(); next.focus(); }
      }
    });
  });

  document.querySelectorAll("[data-set-status]").forEach(button => {
    button.addEventListener("mousedown", event => event.preventDefault());
    button.addEventListener("click", async () => {
      const input = button.closest(".value-cell")?.querySelector(".value-input");
      await saveCell(input, button.dataset.setStatus).catch(() => {});
    });
  });

  document.querySelectorAll(".verify-row").forEach(button => {
    button.addEventListener("click", async () => {
      const inputs = Array.from(button.closest("tr")?.querySelectorAll(".value-input") || []);
      button.disabled = true;
      try {
        for (const input of inputs) await saveCell(input, "verified");
        showToast("Ligne vérifiée.");
      } catch (_) {
        // Le message détaillé est déjà affiché par saveCell.
      } finally {
        button.disabled = false;
      }
    });
  });

  const fichePage = document.getElementById("fichePage");
  const layoutBody = document.body;
  const sidebarToggle = document.getElementById("toggleFicheSidebar");
  const headerToggle = document.getElementById("toggleAppHeader");
  const focusToggle = document.getElementById("toggleFocusMode");
  const layoutStorageKey = "dsf_control_layout";

  function persistLayout() {
    if (!fichePage) return;
    sessionStorage.setItem(layoutStorageKey, JSON.stringify({
      sidebarCollapsed: layoutBody.classList.contains("sidebar-collapsed"),
      headerCollapsed: layoutBody.classList.contains("header-collapsed"),
      focusMode: layoutBody.classList.contains("focus-mode"),
    }));
  }

  function syncLayoutControls() {
    const sidebarCollapsed = layoutBody.classList.contains("sidebar-collapsed");
    const headerCollapsed = layoutBody.classList.contains("header-collapsed");
    const focusMode = layoutBody.classList.contains("focus-mode");
    sidebarToggle?.setAttribute("aria-expanded", String(!sidebarCollapsed));
    headerToggle?.setAttribute("aria-expanded", String(!headerCollapsed));
    focusToggle?.setAttribute("aria-pressed", String(focusMode));
    focusToggle?.classList.toggle("btn-primary", !focusMode);
    focusToggle?.classList.toggle("btn-success", focusMode);
    const focusLabel = focusToggle?.querySelector(".toggle-label");
    if (focusLabel) focusLabel.textContent = focusMode ? "Quitter le plein écran" : "Agrandir le tableau";
  }

  if (fichePage) {
    try {
      const savedLayout = JSON.parse(sessionStorage.getItem(layoutStorageKey) || "{}");
      layoutBody.classList.toggle("sidebar-collapsed", Boolean(savedLayout.sidebarCollapsed));
      layoutBody.classList.toggle("header-collapsed", Boolean(savedLayout.headerCollapsed));
      layoutBody.classList.toggle("focus-mode", Boolean(savedLayout.focusMode));
    } catch (_) {
      sessionStorage.removeItem(layoutStorageKey);
    }
    syncLayoutControls();
  }

  sidebarToggle?.addEventListener("click", () => {
    layoutBody.classList.toggle("sidebar-collapsed");
    layoutBody.classList.remove("focus-mode");
    syncLayoutControls();
    persistLayout();
  });

  headerToggle?.addEventListener("click", () => {
    layoutBody.classList.toggle("header-collapsed");
    layoutBody.classList.remove("focus-mode");
    syncLayoutControls();
    persistLayout();
  });

  focusToggle?.addEventListener("click", () => {
    const activate = !layoutBody.classList.contains("focus-mode");
    layoutBody.classList.toggle("focus-mode", activate);
    layoutBody.classList.toggle("sidebar-collapsed", activate);
    layoutBody.classList.toggle("header-collapsed", activate);
    syncLayoutControls();
    persistLayout();
  });

  function nextPendingFicheUrl(dsfId, ficheCode) {
    const rows = Array.from(document.querySelectorAll(".fiche-nav-row"));
    const currentIndex = rows.findIndex(row =>
      row.querySelector(".sidebar-validate-fiche")?.dataset.ficheCode === ficheCode
    );
    if (currentIndex < 0) return `/dsf/${dsfId}`;
    const followingRows = rows.slice(currentIndex + 1).concat(rows.slice(0, currentIndex));
    const nextRow = followingRows.find(row => {
      const action = row.querySelector(".sidebar-validate-fiche");
      return action && !action.disabled;
    });
    return nextRow?.querySelector(".fiche-nav-item")?.href || `/dsf/${dsfId}`;
  }

  function continueAfterFicheValidation(dsfId, ficheCode) {
    window.location.assign(nextPendingFicheUrl(dsfId, ficheCode));
  }

  async function ficheAction(action) {
    if (!fichePage) return;
    const labels = {
      validate: "Confirmez-vous avoir comparé toute cette fiche avec la DSF papier ?",
      "not-provided": "Confirmez-vous que cette fiche n'est pas renseignée dans la DSF papier ?",
      reopen: "Rouvrir cette fiche annulera les vérifications appliquées par sa validation globale. Continuer ?",
    };
    if (action !== "validate" && !window.confirm(labels[action])) return;
    const endpoint = `/dsf/api/${fichePage.dataset.dsfId}/fiches/${fichePage.dataset.ficheCode}/${action}`;
    const submitAction = acknowledgeAnomalies => apiFetch(endpoint, {
      method: "POST",
      body: JSON.stringify({
        acknowledge_anomalies: acknowledgeAnomalies,
      }),
    });
    try {
      await submitAction(false);
      if (action === "validate") continueAfterFicheValidation(
        fichePage.dataset.dsfId,
        fichePage.dataset.ficheCode
      );
      else window.location.reload();
    } catch (error) {
      if (action === "validate" && error.payload?.requires_confirmation) {
        const issues = (error.payload.issues || []).slice(0, 5);
        const details = issues.length ? `\n\n${issues.map(issue => `• ${issue}`).join("\n")}` : "";
        const remaining = Math.max(0, (error.payload.anomaly_count || 0) - issues.length);
        const more = remaining ? `\n• ... et ${remaining} autre(s) anomalie(s)` : "";
        const confirmed = window.confirm(
          `${error.payload.anomaly_count || "Une ou plusieurs"} anomalie(s) ont été détectées.${details}${more}\n\n` +
          "Avez-vous examiné ces anomalies et souhaitez-vous valider cette fiche malgré tout ? " +
          "Les anomalies resteront signalées et cette décision sera enregistrée dans l'historique."
        );
        if (!confirmed) return;
        try {
          await submitAction(true);
          continueAfterFicheValidation(
            fichePage.dataset.dsfId,
            fichePage.dataset.ficheCode
          );
        } catch (confirmationError) {
          showToast(confirmationError.message, true);
        }
        return;
      }
      showToast(error.message, true);
    }
  }
  document.querySelectorAll(".action-fiche").forEach(button => button.addEventListener("click", () => ficheAction(button.dataset.action)));

  async function validateSidebarFiche(button) {
    const ficheName = button.dataset.ficheName;
    const originalHtml = button.innerHTML;
    const submit = acknowledgeAnomalies => apiFetch(
      `/dsf/api/${button.dataset.dsfId}/fiches/${button.dataset.ficheCode}/validate`,
      {
        method: "POST",
        body: JSON.stringify({ acknowledge_anomalies: acknowledgeAnomalies }),
      }
    );
    button.disabled = true;
    button.textContent = "Validation…";
    try {
      await submit(false);
      continueAfterFicheValidation(button.dataset.dsfId, button.dataset.ficheCode);
    } catch (error) {
      if (error.payload?.requires_confirmation) {
        const issues = (error.payload.issues || []).slice(0, 5);
        const details = issues.length ? `\n\n${issues.map(issue => `• ${issue}`).join("\n")}` : "";
        const remainingIssues = Math.max(0, (error.payload.anomaly_count || 0) - issues.length);
        const more = remainingIssues ? `\n• ... et ${remainingIssues} autre(s) anomalie(s)` : "";
        const confirmed = window.confirm(
          `${error.payload.anomaly_count || "Une ou plusieurs"} anomalie(s) ont été détectées.${details}${more}\n\n` +
          `Avez-vous examiné ces anomalies et souhaitez-vous valider la fiche « ${ficheName} » malgré tout ? ` +
          "Les anomalies resteront signalées et votre décision sera inscrite dans l'historique."
        );
        if (!confirmed) return;
        await submit(true);
        continueAfterFicheValidation(button.dataset.dsfId, button.dataset.ficheCode);
        return;
      }
      showToast(error.message, true);
    } finally {
      button.disabled = false;
      button.innerHTML = originalHtml;
    }
  }

  document.querySelectorAll(".sidebar-validate-fiche:not(:disabled)").forEach(button => {
    button.addEventListener("click", () => {
      validateSidebarFiche(button).catch(error => showToast(error.message, true));
    });
  });

  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && layoutBody.classList.contains("focus-mode")) {
      layoutBody.classList.remove("focus-mode", "sidebar-collapsed", "header-collapsed");
      syncLayoutControls();
      persistLayout();
      return;
    }
    if (event.altKey && event.key === "ArrowRight" && document.getElementById("nextFicheLink")) {
      event.preventDefault();
      window.location.href = document.getElementById("nextFicheLink").href;
      return;
    }
    if (event.altKey && event.key === "ArrowLeft" && document.getElementById("previousFicheLink")) {
      event.preventDefault();
      window.location.href = document.getElementById("previousFicheLink").href;
      return;
    }
    if (event.ctrlKey && event.key.toLowerCase() === "s") {
      event.preventDefault();
      const active = document.activeElement?.classList.contains("value-input") ? document.activeElement : null;
      if (active) saveCell(active).then(() => showToast("Valeur enregistrée.")).catch(() => {});
      else showToast("Toutes les modifications visibles sont enregistrées.");
    }
    if (event.ctrlKey && event.key.toLowerCase() === "f" && document.getElementById("variableSearch")) {
      event.preventDefault();
      document.getElementById("variableSearch").focus();
    }
    if (event.key.toLowerCase() === "v" && fichePage && !["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName)) {
      event.preventDefault();
      ficheAction("validate");
    }
  });

  const variableSearch = document.getElementById("variableSearch");
  const variableResults = document.getElementById("variableSearchResults");
  let searchTimer;
  variableSearch?.addEventListener("input", () => {
    clearTimeout(searchTimer);
    const term = variableSearch.value.trim();
    if (term.length < 2) { variableResults.classList.add("d-none"); return; }
    searchTimer = setTimeout(async () => {
      try {
        const payload = await apiFetch(`/dsf/api/${fichePage.dataset.dsfId}/search?q=${encodeURIComponent(term)}`);
        variableResults.innerHTML = payload.results.length
          ? payload.results.map(item => `<a class="search-result" href="${item.url}"><small>${escapeHtml(item.fiche_name)}</small>${escapeHtml(item.variable_name)}</a>`).join("")
          : '<div class="p-3 small text-secondary">Aucune variable trouvée.</div>';
        variableResults.classList.remove("d-none");
      } catch (error) { showToast(error.message, true); }
    }, 220);
  });

  function escapeHtml(value) {
    const element = document.createElement("div");
    element.textContent = value;
    return element.innerHTML;
  }

  const instantSearch = document.getElementById("instantDsfSearch");
  instantSearch?.addEventListener("input", () => {
    const term = instantSearch.value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
    document.querySelectorAll("#dsfRows tr[data-search]").forEach(row => {
      const haystack = row.dataset.search.normalize("NFD").replace(/[\u0300-\u036f]/g, "");
      row.classList.toggle("d-none", !haystack.includes(term));
    });
  });

  document.getElementById("sessionSelector")?.addEventListener("change", event => {
    const url = new URL(window.location.href);
    url.searchParams.set("session_id", event.target.value);
    url.searchParams.delete("q");
    window.location.href = url.toString();
  });

  document.getElementById("adminSessionSelector")?.addEventListener("change", event => {
    const url = new URL(window.location.href);
    url.searchParams.set("session_id", event.target.value);
    url.searchParams.delete("q");
    window.location.href = url.toString();
  });

  const adminSearch = document.getElementById("adminDsfSearch");
  adminSearch?.addEventListener("input", () => {
    const term = adminSearch.value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
    document.querySelectorAll("#adminDsfRows tr[data-search]").forEach(row => {
      const haystack = row.dataset.search.normalize("NFD").replace(/[\u0300-\u036f]/g, "");
      row.classList.toggle("d-none", !haystack.includes(term));
    });
  });

  document.querySelector(".bulk-assignment-form")?.addEventListener("submit", event => {
    const select = event.currentTarget.querySelector("select[name=user_id]");
    const username = select?.selectedOptions[0]?.textContent || "ce contrôleur";
    if (!window.confirm(`Affecter toutes les DSF encore libres de ce classeur à ${username} ? Cette affectation sera définitive.`)) {
      event.preventDefault();
    }
  });

  const logoRotator = document.querySelector("[data-logo-rotator]");
  const partnerLogos = Array.from(logoRotator?.querySelectorAll("[data-partner-logo]") || []);
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (partnerLogos.length > 1 && !reducedMotion) {
    let logoIndex = Math.max(0, partnerLogos.findIndex(item => item.classList.contains("is-featured")));
    let logoTimer = null;
    const rotateLogo = () => {
      partnerLogos[logoIndex].classList.remove("is-featured");
      partnerLogos[logoIndex].removeAttribute("aria-current");
      logoIndex = (logoIndex + 1) % partnerLogos.length;
      partnerLogos[logoIndex].classList.add("is-featured");
      partnerLogos[logoIndex].setAttribute("aria-current", "true");
    };
    const startRotation = () => {
      if (!logoTimer && !document.hidden) logoTimer = window.setInterval(rotateLogo, 3600);
    };
    const stopRotation = () => {
      window.clearInterval(logoTimer);
      logoTimer = null;
    };
    partnerLogos[logoIndex].setAttribute("aria-current", "true");
    logoRotator.addEventListener("mouseenter", stopRotation);
    logoRotator.addEventListener("mouseleave", startRotation);
    logoRotator.addEventListener("focusin", stopRotation);
    logoRotator.addEventListener("focusout", startRotation);
    document.addEventListener("visibilitychange", () => document.hidden ? stopRotation() : startRotation());
    startRotation();
  }

  if (window.location.hash.startsWith("#value-")) {
    const target = document.querySelector(window.location.hash);
    target?.scrollIntoView({ behavior: "smooth", block: "center" });
    target?.querySelector(".value-input")?.focus();
  }
})();
