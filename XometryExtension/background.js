// Xometry Extension v2.10 - Background Service Worker
console.log("[BG] Service Worker Loaded");
// Handles HTTP requests to Stock API and Local Logger

const API_BASE = "http://127.0.0.1:2222/api";
const API_KEY = "";
const LOG_SERVER = "http://127.0.0.1:3333";
const BACKEND_URLS = [
    "http://192.168.2.23:10000",
    "http://86.123.232.23:10000",
    "http://127.0.0.1:10000"
];
const BACKEND_URL = BACKEND_URLS[0];
const AGENT_URLS = [
    "http://192.168.2.23:4468",
    "http://86.123.232.23:4468",
    "http://127.0.0.1:4468"
];

async function fetchBackend(path, options = {}) {
    const { timeout = 10000, ...fetchOptions } = options;
    let lastError = "Backend unavailable";

    for (const baseUrl of BACKEND_URLS) {
        const url = /^https?:\/\//i.test(path)
            ? path
            : `${baseUrl}${path.startsWith("/") ? path : `/${path}`}`;
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), timeout);
        try {
            const resp = await fetch(url, {
                ...fetchOptions,
                signal: controller.signal
            });
            clearTimeout(timeoutId);
            return { resp, baseUrl, url };
        } catch (e) {
            clearTimeout(timeoutId);
            lastError = `${baseUrl}: ${e.message}`;
            logToLocalServer(`Backend fallback: ${lastError}`);
        }
    }

    throw new Error(lastError);
}

// --- WebSocket Analysis Manager (Background) ---
const AnalysisManager = {
    sockets: {},

    connect: function (partId, tabId) {
        if (this.sockets[partId]) {
            this.sockets[partId].tabId = tabId;
        }

        const wsUrl = `ws://86.123.232.23:10000/ws/${partId}`;
        logToLocalServer(`[BG-WS] Connecting to ${wsUrl}`);

        // Helper to send debug to content script
        const broadcastDebug = (msg) => {
            if (tabId) {
                chrome.tabs.sendMessage(tabId, { type: 'ANALYSIS_DEBUG', message: msg })
                    .catch(() => { });
            }
        };

        if (this.sockets[partId]) {
            broadcastDebug(`[BG] Re-using existing connection for ${partId}`);
            return;
        }

        try {
            const ws = new WebSocket(wsUrl);
            ws.tabId = tabId;
            broadcastDebug(`[BG] Opening WS to ${wsUrl}`);

            ws.onopen = () => {
                logToLocalServer(`[BG-WS] Connected for ${partId}`);
                broadcastDebug(`[BG] WS Connected! Waiting for data...`);
            };

            ws.onmessage = (event) => {
                broadcastDebug(`[BG] Rx Raw: ${event.data.substring(0, 100)}`); // Log first 100 chars
                try {
                    const msg = JSON.parse(event.data);
                    // Log the parsed type to see what we are getting
                    broadcastDebug(`[BG] Rx Type: ${msg.type}`);

                    if (msg.type === 'analysis_complete') {
                        logToLocalServer(`[BG-WS] Analysis Complete for ${partId}`);
                        if (ws.tabId) {
                            chrome.tabs.sendMessage(ws.tabId, {
                                type: 'ANALYSIS_UPDATE',
                                partId: partId,
                                data: msg.data
                            });
                        }
                    }
                } catch (e) {
                    logToLocalServer(`[BG-WS] Parse Error: ${e}`);
                    broadcastDebug(`[BG] Parse Error: ${e}`);
                }
            };

            ws.onerror = (e) => {
                logToLocalServer(`[BG-WS] Error: ${e}`);
                broadcastDebug(`[BG] WS Error`);
            };

            ws.onclose = (e) => {
                logToLocalServer(`[BG-WS] Closed for ${partId}`);
                broadcastDebug(`[BG] WS Closed: Code ${e.code}`);
                delete this.sockets[partId];
            };

            this.sockets[partId] = ws;
        } catch (e) {
            logToLocalServer(`[BG-WS] Setup Error: ${e.message}`);
            broadcastDebug(`[BG] Setup Error: ${e.message}`);
        }
    }
};


chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    console.log("Msg received:", request.type || request.action); // verbose

    if (request.action === 'DOWNLOAD_FILE') {
        console.log(`[BG] Downloading ${request.filename} from ${request.url}`);
        chrome.downloads.download({
            url: request.url,
            filename: request.filename,
            conflictAction: 'uniquify'
        }, (id) => {
            if (chrome.runtime.lastError) {
                console.error(`[BG] Download failed: ${chrome.runtime.lastError.message}`);
                sendResponse({ success: false, error: chrome.runtime.lastError.message });
            } else {
                console.log(`[BG] Download started with ID ${id}`);
                sendResponse({ success: true, id: id });
            }
        });
        return true;
    }

    if (request.type === 'CHECK_STOCK') {
        checkStock(request.material, request.thickness)
            .then(data => sendResponse({ success: true, data: data }))
            .catch(err => sendResponse({ success: false, error: err.message }));
        return true;
    }

    if (request.type === 'LOG') {
        logToLocalServer(request.message);
        return false; // Sync handling ok
    }

    // New Backend Integration
    if (request.action === "scrapingComplete") {
        postToBackend(request.offerData)
            .then(sendResponse)
            .catch(e => { console.error(e); sendResponse({ ok: false, error: String(e) }); });
        return true;
    }

    if (request.action === "downloadDocumentation") {
        downloadDocumentation(request.payload)
            .then(sendResponse)
            .catch(e => {
                console.error("Download Error:", e);
                sendResponse({ success: false, error: String(e) });
            });
        return true;
    }

    if (request.action === "CHECK_OFFER") {
        console.log("Processing CHECK_OFFER for " + request.offerId);
        checkOfferExists(request.offerId)
            .then(result => {
                console.log("Sending response for " + request.offerId + ": " + JSON.stringify(result));
                sendResponse(result); // result is { exists: bool, internalId: int }
            })
            .catch(e => {
                console.error("Error in CHECK_OFFER:", e);
                sendResponse({ exists: false, error: String(e) });
            });
        return true;
    }

    if (request.action === "GET_AGENT_GEO") {
        getAgentGeo(request.offerId)
            .then(result => sendResponse(result))
            .catch(e => sendResponse({ success: false, error: String(e) }));
        return true;
    }

    if (request.action === "GET_DOSAR_STATUS") {
        getDosarStatus(request.offerData || {})
            .then(result => sendResponse(result))
            .catch(e => sendResponse({ success: false, error: String(e) }));
        return true;
    }

    if (request.action === "CREATE_DOSAR") {
        createDosar(request.offerData || {})
            .then(result => sendResponse(result))
            .catch(e => sendResponse({ success: false, error: String(e) }));
        return true;
    }

    if (request.action === 'TRIGGER_ANALYSIS') {
        triggerAnalysis(request.partId)
            .then(res => sendResponse(res))
            .catch(err => sendResponse({ success: false, error: err.message }));
        return true;
    }

    if (request.action === 'CONNECT_WS') {
        // sender.tab.id exists if message from content script
        if (sender.tab && sender.tab.id) {
            AnalysisManager.connect(request.partId, sender.tab.id);
            sendResponse({ success: true });
        }
        return true;
    }
    if (request.action === 'CHECK_HISTORY') {
        checkJobHistory(request.jobId, request.excludeOfferId)
            .then(res => sendResponse(res))
            .catch(err => sendResponse({ success: false, error: err.message }));
        return true;
    }
});

async function logToLocalServer(message) {
    // Always log to background console for user debugging
    console.log("[BG] " + message);
    try {
        await fetch(LOG_SERVER, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: message,
                timestamp: new Date().toISOString()
            })
        });
    } catch (e) {
        // Silent fail if log server is down
        // console.warn("Log server unreachable:", e);
    }
}

async function checkJobHistory(jobIdString, excludeOfferId) {
    // jobIdString ex: "HJO-33079-1972" -> root: "HJO-33079"
    const rootMatch = jobIdString.match(/(HJO-\d+|J-\d+|RFQ-\d+)/);
    const rootId = rootMatch ? rootMatch[1] : jobIdString;

    logToLocalServer(`Checking History for Root: ${rootId}, Excluding: ${excludeOfferId}`);

    const url = "/api/offers";
    try {
        const { resp } = await fetchBackend(url, { method: 'GET', timeout: 10000 });

        if (!resp.ok) throw new Error(`Fetch error: ${resp.status}`);

        const offers = await resp.json();

        // Filter for matches
        const matches = offers.filter(o => {
            const name = o.title || o.job_name;
            const isMatch = name && name.includes(rootId);

            // Debug exclusion
            const isExcluded = excludeOfferId && (String(o.offer_id) === String(excludeOfferId) || String(o.id) === String(excludeOfferId));

            if (isMatch && excludeOfferId) {
                logToLocalServer(`[Exclusion Check] Offer: ${o.offer_id} (ID: ${o.id}) vs Exclude: ${excludeOfferId} -> Excluded? ${isExcluded}`);
            }

            return isMatch && !isExcluded;
        });

        logToLocalServer(`Found ${matches.length} history items for ${rootId}`);
        return { success: true, count: matches.length, items: matches.slice(0, 5) }; // Limit to 5 recent

    } catch (e) {
        logToLocalServer(`History Check Error: ${e.message}`);
        return { success: false, error: e.message };
    }
}

async function checkStock(material, thickness) {
    // Log intent
    logToLocalServer(`Checking Stock: ${material} ${thickness}mm`);

    const url = new URL(`${API_BASE}/blanks`);
    url.searchParams.append("material", material);
    url.searchParams.append("grosime", thickness);
    url.searchParams.append("limit", "50");

    try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 5000);

        const response = await fetch(url.toString(), {
            method: 'GET',
            headers: {
                'X-Api-Key': API_KEY,
                'Accept': 'application/json'
            },
            signal: controller.signal
        });

        clearTimeout(timeoutId);

        if (!response.ok) {
            logToLocalServer(`Stock API Error Status: ${response.status}`);
            throw new Error(`API Error: ${response.status}`);
        }

        const data = await response.json();
        logToLocalServer(`Stock API Success. Count: ${data.count || 0}`);
        return data;

    } catch (error) {
        return { error: error.message, count: 0, items: [] };
    }
}

// Backend Integration Implementations

async function getAgentGeo(offerId) {
    let lastError = "Analysis service unavailable";
    for (const baseUrl of AGENT_URLS) {
        const url = `${baseUrl}/api/agents/geo/${encodeURIComponent(offerId)}`;
        try {
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 5000);
            const resp = await fetch(url, { method: "GET", signal: controller.signal });
            clearTimeout(timeoutId);
            const data = await resp.json();
            if (resp.ok) return { success: true, data, source: baseUrl };
            lastError = `${baseUrl}: HTTP ${resp.status}`;
        } catch (e) {
            lastError = `${baseUrl}: ${e.message}`;
        }
    }
    return { success: false, error: lastError };
}

function partIdsForDosar(offerData) {
    return (offerData.parts || [])
        .map(part => part && part.part_id)
        .filter(Boolean)
        .join(",");
}

async function getDosarStatus(offerData) {
    const offerId = offerData.offer_id;
    if (!offerId || offerId === "unknown") return { success: false, error: "Missing offer_id" };

    const url = new URL(`${BACKEND_URL}/api/xometry/dosar/${encodeURIComponent(offerId)}`);
    if (offerData.job_name || offerData.title) url.searchParams.set("job_id", offerData.job_name || offerData.title);
    const partIds = partIdsForDosar(offerData);
    if (partIds) url.searchParams.set("part_ids", partIds);

    try {
        const { resp, baseUrl } = await fetchBackend(`${url.pathname}${url.search}`, { method: "GET", timeout: 10000 });
        const data = await resp.json();
        if (!resp.ok) return { success: false, error: data.detail || `HTTP ${resp.status}` };
        return { success: true, data, source: baseUrl };
    } catch (e) {
        return { success: false, error: e.message };
    }
}

async function createDosar(offerData) {
    const offerId = offerData.offer_id;
    if (!offerId || offerId === "unknown") return { success: false, error: "Missing offer_id" };

    try {
        const { resp, baseUrl } = await fetchBackend(`/api/xometry/dosar/${encodeURIComponent(offerId)}/create`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(offerData),
            timeout: 30000
        });
        const data = await resp.json();
        if (!resp.ok) return { success: false, error: data.detail || `HTTP ${resp.status}`, data };
        return { success: true, data, source: baseUrl };
    } catch (e) {
        return { success: false, error: e.message };
    }
}

async function postToBackend(payload) {
    const url = "/api/scrape";
    logToLocalServer(`POST -> backend ${url}`);

    try {
        const { resp } = await fetchBackend(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
            timeout: 10000
        });

        let data = null;
        try { data = await resp.json(); } catch { }

        if (!resp.ok) {
            const errText = `Server Error ${resp.status}: ${resp.statusText}`;
            logToLocalServer(errText);
            return { ok: false, status: resp.status, error: errText };
        }

        if (data) {
            return { ...data, ok: true };
        }
        return { ok: resp.ok, status: resp.status };
    } catch (e) {
        const msg = `Network Error: ${e.message}`;
        logToLocalServer(msg);
        return { ok: false, error: msg };
    }
}

async function downloadDocumentation(payload) {
    const { offerId, downloadUrl, fileName } = payload;
    // Uses the backend to perform the download/store logic
    const url = "/api/download-docs";
    logToLocalServer(`Download Request: ${fileName} from ${downloadUrl}`);

    try {
        const { resp } = await fetchBackend(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                offer_id: offerId,
                download_url: downloadUrl,
                file_name: fileName,
                page_type: "job" // Assumption
            }),
            timeout: 30000
        });

        let data = null;
        try { data = await resp.json(); } catch { }
        return data ?? { success: resp.ok, status: resp.status };
    } catch (e) {
        logToLocalServer(`Download API Error: ${e.message}`);
        throw e;
    }
}

async function checkOfferExists(offerId) {
    const url = "/api/offers";
    logToLocalServer(`Checking existence via list: ${url} for ${offerId}`);
    try {
        const { resp } = await fetchBackend(url, {
            method: 'GET',
            timeout: 10000
        });

        if (!resp.ok) {
            logToLocalServer(`List fetch error: ${resp.status}`);
            return { exists: false };
        }

        const offers = await resp.json();
        // Look for the Xometry Offer ID in the list
        // items have "id" (internal) and "offer_id" (external)
        const match = offers.find(o => String(o.offer_id) === String(offerId));

        if (match) {
            logToLocalServer(`Found match! XomID: ${offerId} -> IntID: ${match.id}`);
            return { exists: true, internalId: match.id };
        } else {
            logToLocalServer(`No match found for ${offerId}`);
            return { exists: false };
        }
    } catch (e) {
        logToLocalServer(`Check error: ${e.message}`);
        return { exists: false };
    }
}

async function triggerAnalysis(partId) {
    const url = "/api/extension/analyze";
    logToLocalServer(`Triggering Analysis for Part ${partId}`);

    // Broadcast debug helper (needs to find a tabId, let's try to query active)
    // Actually, we can't easily get the tabId here without passing it. 
    // Let's assume the user will look at the background console or we rely on the content script's callback which *is* logged.
    // Wait, the content script's callback `onSuccess` / `onError` is called.
    // Let's verify `content_v20.js` logs this.

    try {
        // Ensure part_id is a number (integer) for the backend
        const numericPartId = parseInt(partId, 10);

        const { resp } = await fetchBackend(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ part_id: numericPartId }),
            timeout: 30000
        });

        if (!resp.ok) {
            throw new Error(`Server error: ${resp.status}`);
        }

        const data = await resp.json();
        return { success: true, data: data };
    } catch (e) {
        logToLocalServer(`Analysis Trigger Error: ${e.message}`);
        return { success: false, error: e.message };
    }
}
