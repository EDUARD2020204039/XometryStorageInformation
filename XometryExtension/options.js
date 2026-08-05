const consent = document.getElementById("data-consent");
const status = document.getElementById("status");

chrome.storage.local.get(["dataConsent"], (result) => {
    consent.checked = result.dataConsent === true;
});

document.getElementById("save").addEventListener("click", () => {
    chrome.storage.local.set({ dataConsent: consent.checked }, () => {
        if (chrome.runtime.lastError) {
            status.textContent = "Setarea nu a putut fi salvata.";
            status.dataset.type = "error";
            return;
        }
        status.textContent = consent.checked
            ? "Transferul securizat este activ."
            : "Transferul catre serviciile HABA este oprit.";
        status.dataset.type = "success";
    });
});
