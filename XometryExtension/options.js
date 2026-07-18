const enabledInput = document.getElementById("extensionEnabled");
const tokenInput = document.getElementById("xsiApiToken");
const status = document.getElementById("status");

chrome.storage.local.get({ extensionEnabled: true, xsiApiToken: "" }, (stored) => {
    enabledInput.checked = stored.extensionEnabled;
    tokenInput.value = stored.xsiApiToken;
});

document.getElementById("save").addEventListener("click", () => {
    chrome.storage.local.set({
        extensionEnabled: enabledInput.checked,
        xsiApiToken: tokenInput.value.trim()
    }, () => {
        status.textContent = "Salvat";
        setTimeout(() => { status.textContent = ""; }, 1500);
    });
});
