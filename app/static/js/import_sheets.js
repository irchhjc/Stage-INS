(() => {
  "use strict";
  const file = document.getElementById("file");
  const select = document.getElementById("sheetName");
  const button = document.getElementById("importSelectedSheet");
  const message = document.getElementById("sheetPreviewMessage");
  const form = document.getElementById("sheetImportForm");
  if (!file || !select || !button || !message || !form) return;
  let version = 0;
  let pending;
  select.addEventListener("change", () => { button.disabled = !select.value; });
  file.addEventListener("change", async () => {
    const current = ++version;
    pending?.abort();
    select.replaceChildren(new Option("Choisir une feuille", ""));
    select.disabled = true;
    button.disabled = true;
    message.classList.remove("text-danger");
    if (!file.files.length) { message.textContent = ""; return; }
    message.textContent = "Lecture des feuilles du classeur…";
    pending = new AbortController();
    const data = new FormData();
    data.append("file", file.files[0]);
    data.append("csrf_token", form.elements.csrf_token.value);
    try {
      const response = await fetch("/import/sheets", {method: "POST", body: data, signal: pending.signal});
      const payload = await response.json().catch(() => null);
      if (current !== version) return;
      if (!response.ok || !payload?.ok) {
        throw new Error(payload?.error || "Lecture impossible. Vérifiez la connexion, la taille du fichier et votre session.");
      }
      for (const name of payload.sheets) select.add(new Option(name, name));
      select.disabled = false;
      message.textContent = `${payload.sheets.length} feuille(s) trouvée(s). Sélectionnez celle à importer.`;
    } catch (error) {
      if (current !== version || error.name === "AbortError") return;
      message.textContent = error.message || "Impossible de lire les feuilles.";
      message.classList.add("text-danger");
    }
  });
  form.addEventListener("submit", event => {
    if (select.disabled || !select.value) { event.preventDefault(); return; }
    button.disabled = true;
    button.textContent = "Import en cours…";
  });
})();
