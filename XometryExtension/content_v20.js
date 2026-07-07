// Xometry Price Calculator Extension (v2.44)
// Content Script v20 - Thickness Normalization

(function () {
    let latestAgentGeoStatus = null;
    let latestAgentGeoSource = null;

    function log(msg) {
        // Log to browser console so user can see it
        console.log("%c[XomExt] " + msg, "color: #1890ff; font-weight: bold;");
        try { chrome.runtime.sendMessage({ type: 'LOG', message: msg }); } catch (e) { }
    }

    log("Extension v2.56 Loaded (content_v20.js)");

    const DENSITIES = {
        'aluminium': 2.7, 'aluminum': 2.7, 'al-': 2.7, 'al ': 2.7, 'aw-': 2.7, '6082': 2.7, '7075': 2.8, '6061': 2.7,
        'steel': 7.85, 'st37': 7.85, 'st52': 7.85, 's235': 7.85, 's355': 7.85, '1.0038': 7.85, '1.7225': 7.85, '42crmo4': 7.85,
        'stainless': 7.9, '1.4301': 7.9, '304': 7.9, '316': 8.0, '1.4404': 8.0,
        'brass': 8.5, 'copper': 8.96, 'titanium': 4.5,
        'pom': 1.41, 'abs': 1.04, 'nylon': 1.15, 'pa6': 1.13, 'peek': 1.32
    };

    function getInternalMaterial(xometryMatString) {
        if (!xometryMatString) return null;
        const s = xometryMatString.toLowerCase();
        if (s.includes("stainless") || s.includes("inox") || s.includes("1.4301") || s.includes("304") || s.includes("316")) return "Inox";
        if (s.includes("steel") || s.includes("s235") || s.includes("st37") || s.includes("1.0038")) return "Otel";
        if (s.includes("alum") || s.includes("6082") || s.includes("6061") || s.includes("aw-")) return "Aluminiu";
        return "Unknown";
    }

    function debounce(func, wait) {
        let timeout;
        return function (...args) {
            clearTimeout(timeout);
            timeout = setTimeout(() => func.apply(this, args), wait);
        };
    }

    function extractPartId(text) {
        const match = String(text || '').match(/Part ID:\s*([A-Z]{1,4}-[A-Z]{1,4}\d+|\d+)/i);
        return match ? match[1].trim().toUpperCase() : null;
    }

    function partIdNumber(partId) {
        const match = String(partId || '').match(/(\d+)/);
        return match ? match[1] : '';
    }

    async function scanForCards() {
        if (!document.getElementById('xom-grand-total-box')) {
            const box = document.createElement('div');
            box.id = 'xom-grand-total-box';
            box.className = 'xom-grand-total-box';

            // Header with Minimize
            const header = `
                <div class="xom-grand-total-label" style="display:flex; justify-content:space-between; align-items:center; cursor:pointer; user-select:none;" title="Click to Minimize">
                <span>GRAND TOTAL <span style="font-size:9px; opacity:0.5;">v2.56</span></span>
                <span id="xom-minimize-icon" style="font-weight:bold; font-size:14px;">−</span>
            </div>
            `;

            // Content Wrapper
            const content = `
                <div id="xom-grand-total-content">
                    <div class="xom-grand-total-value" id="xom-grand-total">0.00 €</div>
                    <div style="margin-top:4px; text-align:center;">
                        <button id="xom-copy-all-btn" style="cursor:pointer; font-size:10px; padding:2px 6px; border:1px solid #ccc; background:#fff; border-radius:3px;">📋 Copy All</button>
                    </div>
                    <div style="margin-top:2px; text-align:center;">
                        <button id="xom-copy-sheet-btn" style="cursor:pointer; font-size:10px; padding:2px 6px; border:1px solid #ccc; background:#fff; border-radius:3px;">📄 Copy Sheet</button>
                    </div>
                </div>
                `;

            // Minimized Placeholder
            const minimizedPlaceholder = `
                <div class="xom-minimized-placeholder" title="Click to Expand">
                    €
                </div>
                `;

            box.innerHTML = header + content + minimizedPlaceholder;
            document.body.appendChild(box);

            // Add listeners
            setTimeout(() => {
                const label = box.querySelector('.xom-grand-total-label');
                const placeholder = box.querySelector('.xom-minimized-placeholder');

                // Load saved state
                try {
                    if (localStorage.getItem('xom_gt_minimized') === 'true') {
                        box.classList.add('xom-minimized');
                    }
                } catch (e) { }

                // Minimize Action
                label.onclick = (e) => {
                    e.stopPropagation();
                    box.classList.add('xom-minimized');
                    localStorage.setItem('xom_gt_minimized', 'true');
                };

                // Maximize Action (click anywhere on box when minimized, or specifically placeholder)
                box.onclick = (e) => {
                    if (box.classList.contains('xom-minimized')) {
                        box.classList.remove('xom-minimized');
                        localStorage.setItem('xom_gt_minimized', 'false');
                    }
                };

                const cab = document.getElementById('xom-copy-all-btn');
                if (cab) {
                    cab.onclick = (e) => { e.stopPropagation(); copyAllParts(false); };
                }
                const csb = document.getElementById('xom-copy-sheet-btn');
                if (csb) {
                    csb.onclick = (e) => { e.stopPropagation(); copyAllParts(true); };
                }

            }, 100);
        }

        const cards = document.querySelectorAll('.ant-card-body');
        for (const card of cards) { await processCard(card); }
        recalculateTotals();
        injectDownloadOverlayRibbon();
        injectWalkthrough();
        checkHistoryAndInject();
        injectRulesButton();
    }

    async function processCard(card) {
        const text = card.textContent;
        if (!text.includes("Part ID:")) return;

        const partId = extractPartId(text) || "unknown";

        // Prevent re-processing the same part (fixes Overwriting Manual Thickness changes)
        if (card.dataset.xomProcessed === partId) return;
        card.dataset.xomProcessed = partId;

        if (!card.dataset.xomDebugged) {
            log(`Processing Part ${partId} `);
            card.dataset.xomDebugged = 'true';
        }

        const offerId = window.location.href.match(/\/offers\/(\d+)/)?.[1] || 'default';
        let qty = 1;

        // 1. Get clean text by REMOVING the Part ID completely.
        const textWithoutPartId = card.innerText.split(partId).join('');

        // 2. Parse quantity from the cleaned text
        const qtyMatch = textWithoutPartId.match(/([\d.,]+)\s*(?:piece|pc|buc|stk|pz)/i);

        if (qtyMatch) {
            const raw = qtyMatch[1].replace(/[.,]/g, '');
            qty = parseInt(raw, 10);
        }

        processCalculations(card, text, partId, offerId);

        if (!card.querySelector('.xom-price-row')) {
            injectPriceInputs(card, offerId, partId, qty);
        }

        // Inject Analysis Control
        injectAnalysisControl(card, partId);
        if (latestAgentGeoStatus) {
            injectGeoControl(card, latestAgentGeoStatus, latestAgentGeoSource, offerId, partId);
        }
    }

    function processCalculations(card, text, partId, offerId) {
        const dimMatch = text.match(/(\d+(?:[.,]\d+)?)\s*[xX]\s*(\d+(?:[.,]\d+)?)\s*[xX]\s*(\d+(?:[.,]\d+)?)/);
        if (!dimMatch) return;

        // Raw dimensions with full precision
        const l = parseFloat(dimMatch[1].replace(',', '.'));
        const w = parseFloat(dimMatch[2].replace(',', '.'));
        const h = parseFloat(dimMatch[3].replace(',', '.'));

        let density = 2.7;
        let matKey = "Default (Alu)";
        let rawMat = "Unknown";
        const fullText = card.innerText;
        const matMatch = fullText.match(/Material:\s*([^\n\r]+)/i);
        if (matMatch) {
            rawMat = matMatch[1].trim();
            for (const [key, val] of Object.entries(DENSITIES)) {
                if (rawMat.toLowerCase().includes(key)) {
                    density = val; matKey = key; break;
                }
            }
        } else {
            for (const [key, val] of Object.entries(DENSITIES)) {
                if (fullText.toLowerCase().includes(key)) {
                    density = val; matKey = key; rawMat = key; break;
                }
            }
        }

        // Weight: Use raw thickness for accuracy
        const vol = (l / 10) * (w / 10) * (h / 10);
        const weight = (vol * density) / 1000;
        injectRawWeight(card, dimMatch[0], weight, density, matKey);
        // Pass raw strings for L and W to helper
        injectCopyDimButton(card, dimMatch[0], l, w, dimMatch[1], dimMatch[2]);

        const lowerText = fullText.toLowerCase();

        // Surface Area
        const hasPainting = lowerText.includes("powder coating") ||
            lowerText.includes("painting") ||
            lowerText.includes("vopsire") ||
            lowerText.includes("coating");
        const hasAnodising = lowerText.includes("anodising") || lowerText.includes("anodizing");

        if (hasPainting || hasAnodising) {
            let label = "";
            let areaRaw = l * w * 2; // sq mm
            if (hasPainting) {
                let val = areaRaw / 1000000;
                label = `${val.toFixed(4)} m²`;
                log(`Part ${partId}: Painting detected -> ${label} `);
            } else {
                let val = areaRaw / 10000;
                label = `${val.toFixed(3)} dm²`;
                log(`Part ${partId}: Anodising detected -> ${label} `);
            }
            injectSurfaceArea(card, label, partId);
        }

        const isSheet = lowerText.includes("sheet") || lowerText.includes("laser cutting");
        if (isSheet && rawMat) {
            const internalMat = getInternalMaterial(rawMat);
            if (internalMat && internalMat !== "Unknown") {
                const nums = [l, w, h].sort((a, b) => a - b);
                const thickness = nums[0]; // min
                const defW = nums[1];
                const defL = nums[2];
                const normalizedThickness = parseFloat(thickness.toFixed(1));

                injectDimensionsControl(card, defL, defW, normalizedThickness, (newL, newW, newT) => {
                    log(`Part ${partId} Update Dims: ${newL}x${newW}x${newT}`);

                    // Stock check primarily cares about thickness
                    checkStockAndInject(card, dimMatch[0], internalMat, newT, density);

                    // Recalculate Weight using exact new dimensions
                    // Volume (mm3) = L * W * T
                    // Weight (kg) = Vol * Density (g/cm3) / 1000000
                    const newWeight = (newL * newW * newT * density) / 1000000;
                    injectRawWeight(card, dimMatch[0], newWeight, density, matKey);
                }, offerId, partId);

                if (!card.querySelector('.xom-stock-row')) {
                    checkStockAndInject(card, dimMatch[0], internalMat, normalizedThickness, density);
                }
            }
        }
    }

    function injectSurfaceArea(card, labelText, partId) {
        if (card.querySelector('.xom-surface-area')) return;
        let targetNode = null;
        const walker = document.createTreeWalker(card, NodeFilter.SHOW_TEXT, null, false);
        let node;
        while (node = walker.nextNode()) {
            if (node.textContent.toLowerCase().includes("finish:")) {
                targetNode = node;
                break;
            }
        }
        if (targetNode) {
            const span = document.createElement('span');
            span.className = 'xom-surface-area';

            // "Wet Area" text (no icon or bold per original request? or maybe it was just simple text)
            // Reverting to style from previous step
            span.innerHTML = `&nbsp;&nbsp;💧 Wet Area: <b>${labelText}</b>`;
            Object.assign(span.style, { color: '#0050b3', marginLeft: '10px', backgroundColor: '#e6f7ff', padding: '2px 5px', borderRadius: '4px', border: '1px solid #91d5ff' });
            targetNode.parentElement.appendChild(span);
        }
    }

    function injectDimensionsControl(card, defL, defW, defT, onUpdate, offerId, partId) {
        if (card.querySelector('.xom-thickness-ctrl')) return;

        const row = document.createElement('div');
        row.className = 'xom-thickness-ctrl';

        // Compact inputs style
        const inputStyle = 'width:50px; padding:2px; font-size:12px; border:1px solid #d9d9d9; border-radius:4px; text-align:center;';

        row.innerHTML = `
            <span style="font-size:1.1em; margin-right:4px;" title="Dimensions (LxWxK)">📏</span>
            <input type="number" step="0.1" class="xom-dim-l" value="${defL}" style="${inputStyle}" title="Length">
            <span style="margin:0 2px; color:#999;">x</span>
            <input type="number" step="0.1" class="xom-dim-w" value="${defW}" style="${inputStyle}" title="Width">
            <span style="margin:0 2px; color:#999;">x</span>
            <input type="number" step="0.1" class="xom-dim-t" value="${defT}" style="${inputStyle}; font-weight:bold; color:#1890ff;" title="Thickness">
            <button style="cursor:pointer; margin-left:4px; border:1px solid #d9d9d9; background:#fafafa; border-radius:4px; padding:2px 6px;" title="Update">↻</button>
        `;

        Object.assign(row.style, { marginTop: '4px', display: 'flex', alignItems: 'center', width: 'fit-content', padding: '3px 6px', border: '1px solid #d9d9d9', borderRadius: '4px', backgroundColor: '#fafafa' });

        const inpL = row.querySelector('.xom-dim-l');
        const inpW = row.querySelector('.xom-dim-w');
        const inpT = row.querySelector('.xom-dim-t');
        const btn = row.querySelector('button');

        // Storage Key
        const storageKey = `dims:${offerId}:${partId}`;

        const trigger = (save = true) => {
            const l = parseFloat(inpL.value) || defL;
            const w = parseFloat(inpW.value) || defW;
            const t = parseFloat(inpT.value) || defT;

            onUpdate(l, w, t);

            // Visual feedback
            [inpL, inpW, inpT].forEach(i => {
                i.style.borderColor = '#52c41a';
                setTimeout(() => i.style.borderColor = '#d9d9d9', 500);
            });

            // Save to storage
            if (save && chrome.runtime?.id) {
                try {
                    chrome.storage.local.set({ [storageKey]: { l, w, t } });
                } catch (e) { }
            }
        };

        // Load saved dims
        if (chrome.runtime?.id) {
            chrome.storage.local.get([storageKey], (res) => {
                if (chrome.runtime.lastError) return;
                const saved = res[storageKey];
                if (saved && saved.l && saved.w && saved.t) {
                    inpL.value = saved.l;
                    inpW.value = saved.w;
                    inpT.value = saved.t;
                    // Trigger update immediately so weight is correct on load
                    trigger(false); // don't re-save what we just loaded
                    log(`[Dims] Loaded saved dimensions for ${partId}: ${saved.l}x${saved.w}x${saved.t}`);
                }
            });
        }

        btn.onclick = (e) => { e.stopPropagation(); trigger(true); };

        // Add Enter listener to all inputs
        [inpL, inpW, inpT].forEach(input => {
            input.onclick = (e) => e.stopPropagation();
            input.onkeydown = (e) => { if (e.key === 'Enter') trigger(true); };
        });

        row.onclick = (e) => e.stopPropagation();

        const priceRow = card.querySelector('.xom-price-row');
        if (priceRow) card.insertBefore(row, priceRow);
        else card.appendChild(row);
    }


    function checkStockAndInject(card, dimText, material, thickness, density) {
        try {
            if (!chrome.runtime?.id) return;
            chrome.runtime.sendMessage({ type: 'CHECK_STOCK', material: material, thickness: thickness }, (res) => {
                if (chrome.runtime.lastError) return;

                let label = "Err", color = "red", bg = "#fff1f0", border = "#ffa39e", tooltip = "Error";
                let debugUrl = `http://86.123.232.23:2222/show_all?material=${material}&grosime=${thickness}`;

                if (res && res.success && res.data) {
                    const count = res.data.count || (res.data.items ? res.data.items.length : 0);
                    if (count > 0) {
                        label = `Stoc: ${count}`; color = "#389e0d"; bg = "#f6ffed"; border = "#b7eb8f";
                        let lines = res.data.items.slice(0, 5).map(i => {
                            const wKg = (i.lungime * i.latime * thickness * density) / 1000000;
                            return `<div style='display:flex; justify-content:space-between; width:220px'>
                                      <span>${i.lungime}x${i.latime} <b>(${i.cantitate_disponibila}pz)</b></span> 
                                      <span style='color:#666'>${wKg.toFixed(2)}kg</span>
                                    </div>`;
                        }).join('');
                        tooltip = `<div style="font-weight:bold; border-bottom:1px solid #ddd; margin-bottom:4px; padding-bottom:2px">${material} ${thickness}mm</div>
                                   ${lines}
                                   <div style="border-top:1px solid #eee; margin-top:4px; pt:2px; font-size:10px; color:#1890ff; text-align:center; cursor:pointer">
                                      Click to see all results...
                                   </div>`;
                    } else {
                        label = `Stoc: 0`; color = "#8c8c8c"; bg = "#fafafa"; border = "#d9d9d9";
                        tooltip = `No stock found for ${material} ${thickness}mm.<br><span style='font-size:10px; color:#1890ff'>Click to check manually</span>`;
                    }
                } else {
                    if (res && res.error) tooltip = res.error;
                }
                injectStockRow(card, dimText, label, color, bg, border, tooltip, debugUrl);
            });
        } catch (e) { }
    }

    function injectStockRow(card, dimText, label, color, bg, border, tooltip, url) {
        if (card.querySelector('.xom-stock-row')) card.querySelector('.xom-stock-row').remove();
        let target = findInsertTarget(card, dimText);
        const row = document.createElement('div');
        row.className = 'xom-stock-row';
        row.innerHTML = `<span style="font-size:1.1em">🏭</span> <b style="margin-left:4px">${label}</b>`;
        Object.assign(row.style, { color: color, backgroundColor: bg, border: `1px solid ${border}`, padding: '2px 8px', borderRadius: '4px', marginTop: '4px', display: 'flex', width: 'fit-content', fontSize: '12px', position: 'relative', cursor: 'pointer' });
        row.addEventListener('click', (e) => { e.stopPropagation(); window.open(url, '_blank'); });
        const tt = document.createElement('div');
        tt.innerHTML = tooltip;
        Object.assign(tt.style, { position: 'absolute', bottom: '115%', left: '0', bgcolor: 'white', border: '1px solid #bbb', padding: '8px', display: 'none', minWidth: '240px', zIndex: '10000', backgroundColor: 'white', boxShadow: '0 3px 6px rgba(0,0,0,0.2)', borderRadius: '4px' });
        row.appendChild(tt);
        row.onmouseenter = () => tt.style.display = 'block';
        row.onmouseleave = () => tt.style.display = 'none';
        if (target) target.parentNode.insertBefore(row, target.nextSibling);
        else { const priceRow = card.querySelector('.xom-price-row'); if (priceRow) card.insertBefore(row, priceRow); else card.appendChild(row); }
    }

    function injectRawWeight(card, dimText, weight, density, matKey) {
        if (card.querySelector('.xom-raw-weight-row')) card.querySelector('.xom-raw-weight-row').remove();
        let target = findInsertTarget(card, dimText);
        if (target && target.nextElementSibling && target.nextElementSibling.classList.contains('xom-stock-row')) target = target.nextElementSibling;
        const row = document.createElement('div');
        row.className = 'xom-raw-weight-row';
        row.innerHTML = `📦 Raw: <b>${weight.toFixed(3)} kg</b> <span title="${density} (${matKey})">[?]</span>`;
        Object.assign(row.style, { color: '#722ed1', backgroundColor: '#f9f0ff', border: '1px solid #d3adf7', padding: '2px 8px', borderRadius: '4px', marginTop: '4px', width: 'fit-content' });
        if (target) target.parentNode.insertBefore(row, target.nextSibling);
        else { const priceRow = card.querySelector('.xom-price-row'); if (priceRow) card.insertBefore(row, priceRow); else card.appendChild(row); }
    }

    const AnalysisService = {
        callbacks: {}, // partId -> onData function

        init: function () {
            // Global listener for updates from Background
            chrome.runtime.onMessage.addListener((msg) => {
                if (msg.type === 'ANALYSIS_UPDATE') {
                    const { partId, data } = msg;
                    log(`[Content] Received Analysis Update for ${partId}`);
                    if (this.callbacks[partId]) {
                        this.callbacks[partId](data);
                    }
                }
                if (msg.type === 'ANALYSIS_DEBUG') {
                    console.log(`%c[BG-Relay] ${msg.message}`, "color: #faad14");
                }
            });
        },

        connect: function (partId, onData) {
            this.callbacks[partId] = onData;
            // Tell background to open WS
            if (!chrome.runtime?.id) return;
            chrome.runtime.sendMessage({ action: 'CONNECT_WS', partId: partId });
        },

        trigger: function (partId, onSuccess, onError) {
            if (!chrome.runtime?.id) return;
            chrome.runtime.sendMessage({ action: 'TRIGGER_ANALYSIS', partId: partId }, (res) => {
                if (chrome.runtime.lastError) {
                    onError(chrome.runtime.lastError.message);
                    return;
                }
                if (res && res.success) onSuccess(res.data);
                else onError(res ? res.error : "Unknown Error");
            });
        }
    };
    // Initialize Listener
    AnalysisService.init();

    function injectAnalysisControl(card, partId) {
        if (card.querySelector('.xom-analyze-row')) return;

        const row = document.createElement('div');
        row.className = 'xom-analyze-row';
        row.innerHTML = `<button class="xom-analyze-btn">🧠 Analyze</button> 
                         <span class="xom-analyze-status" style="margin-left:8px; font-size:12px; color:#666;"></span>`;
        Object.assign(row.style, { marginTop: '6px', marginBottom: '6px' });

        const btn = row.querySelector('button');
        Object.assign(btn.style, {
            cursor: 'pointer', border: '1px solid #1890ff', backgroundColor: '#e6f7ff',
            color: '#0050b3', borderRadius: '4px', padding: '2px 8px', fontSize: '12px'
        });

        const handleUpdate = (data) => {
            // "analysis_complete" received
            const price = data.price !== null ? data.price + '€' : 'N/A';
            const bends = data.bends ?? '?';
            const obs = data.observations || 'None';

            btn.textContent = '✅ Analysis Done';
            btn.disabled = false; // Optional: let them click again?
            btn.style.cursor = 'default';
            btn.style.backgroundColor = '#f6ffed';
            btn.style.borderColor = '#b7eb8f';
            btn.style.color = '#389e0d';

            // Show notification toast
            BackendUI.setStatus(`Done: ${partId}`, 'success', `Price: ${price}`);

            // Update Status Span with details
            const status = row.querySelector('.xom-analyze-status');
            status.innerHTML = `<b>${price}</b> | Bends: ${bends} | <span title="${obs}">Obs ℹ️</span>`;
        };

        // Auto-connect WS
        AnalysisService.connect(partId, handleUpdate);

        btn.onclick = (e) => {
            e.stopPropagation();
            if (btn.disabled) return;

            // Re-ensure connection and callback just in case
            AnalysisService.connect(partId, handleUpdate);

            btn.textContent = '⏳ Analyzing...';
            btn.disabled = true;
            Object.assign(btn.style, { cursor: 'wait', backgroundColor: '#f5f5f5', color: '#999', borderColor: '#d9d9d9' });

            AnalysisService.trigger(partId,
                (res) => {
                    log(`Analysis triggered for ${partId}`);
                    // Add timeout to reset button if no response in 30s
                    setTimeout(() => {
                        if (btn.textContent.includes('Analyzing')) {
                            btn.textContent = '❌ Timeout';
                            btn.disabled = false;
                            btn.style.cursor = 'pointer';
                            row.querySelector('.xom-analyze-status').textContent = 'Server silent > 30s';
                        }
                    }, 30000);
                },
                (err) => {
                    btn.textContent = '❌ Error';
                    btn.disabled = false;
                    btn.style.cursor = 'pointer';
                    row.querySelector('.xom-analyze-status').textContent = err;
                }
            );
        };

        const stockRow = card.querySelector('.xom-stock-row');
        if (stockRow) {
            stockRow.parentNode.insertBefore(row, stockRow.nextSibling);
        } else {
            const priceRow = card.querySelector('.xom-price-row');
            if (priceRow) card.insertBefore(row, priceRow);
            else card.appendChild(row);
        }
    }

    function textForGeoMatch(item) {
        return [
            item?.part_name,
            item?.partName,
            item?.target_path,
            item?.targetPath,
            item?.reason,
            item?.status
        ].filter(Boolean).join(' ').toLowerCase();
    }

    function partNameFromCard(card) {
        const text = card.innerText || '';
        const lines = text.split('\n').map(line => line.trim()).filter(Boolean);
        const partIdIndex = lines.findIndex(line => line.includes('Part ID:'));
        if (partIdIndex >= 0 && lines[partIdIndex + 1]) return lines[partIdIndex + 1];
        if (partIdIndex > 0) return lines[partIdIndex - 1];
        const strong = card.querySelector('strong, b, .ant-typography-strong');
        return strong ? strong.innerText.trim() : '';
    }

    function findGeoItemForPart(items, card, partId) {
        const indexed = (items || [])
            .map((item, index) => ({ item, index }))
            .filter(entry => entry.item && (entry.item.target_path || entry.item.targetPath));

        if (!indexed.length) return null;

        const numericPartId = partIdNumber(partId);
        const tokens = [
            partId,
            numericPartId,
            `part${partId}`,
            `part-${partId}`,
            `part_${partId}`,
            numericPartId ? `part${numericPartId}` : '',
            numericPartId ? `part-${numericPartId}` : '',
            numericPartId ? `part_${numericPartId}` : ''
        ]
            .filter(Boolean)
            .map(token => String(token).toLowerCase());
        const byPartId = indexed.find(entry => {
            const text = textForGeoMatch(entry.item);
            return tokens.some(token => text.includes(token));
        });
        if (byPartId) return byPartId;

        const partName = partNameFromCard(card).toLowerCase();
        if (partName && partName !== 'n/a') {
            const cleanName = partName.replace(/\.[a-z0-9]+$/i, '');
            const byName = indexed.find(entry => {
                const text = textForGeoMatch(entry.item);
                return text.includes(partName) || (cleanName.length > 3 && text.includes(cleanName));
            });
            if (byName) return byName;
        }

        return indexed.length === 1 ? indexed[0] : null;
    }

    function injectGeoControl(card, geoStatus, agentSource, offerId, partId) {
        let row = card.querySelector('.xom-geo-row');
        const matched = findGeoItemForPart(geoStatus?.geo_items || [], card, partId);
        const targetPath = matched?.item?.target_path || matched?.item?.targetPath;
        const geoExists = matched?.item?.geo_exists;

        if (!matched || !targetPath || geoExists !== true || !agentSource || !offerId || offerId === 'unknown') {
            if (row) row.remove();
            return;
        }

        if (!row) {
            row = document.createElement('div');
            row.className = 'xom-geo-row';
            const analyzeRow = card.querySelector('.xom-analyze-row');
            if (analyzeRow) {
                analyzeRow.parentNode.insertBefore(row, analyzeRow.nextSibling);
            } else {
                const priceRow = card.querySelector('.xom-price-row');
                if (priceRow) card.insertBefore(row, priceRow);
                else card.appendChild(row);
            }
        }

        const url = `${agentSource.replace(/\/$/, '')}/api/agents/geo/${encodeURIComponent(offerId)}/files/${matched.index}/view`;
        const fileName = targetPath.split(/[\\/]/).pop() || 'part.geo';
        row.innerHTML = '';

        const link = document.createElement('a');
        link.className = 'xom-geo-btn';
        link.href = url;
        link.target = '_blank';
        link.rel = 'noreferrer';
        link.textContent = `GEO: ${fileName}`;
        link.title = targetPath;
        row.appendChild(link);
    }

    function injectCopyDimButton(card, dimText, l, w, rawL, rawW) {
        if (card.querySelector('.xom-copy-dim-btn')) return;

        const createBtn = () => {
            const btn = document.createElement('span');
            btn.className = 'xom-copy-dim-btn';
            btn.innerHTML = '📋';
            btn.title = 'Copy Dimensions (L{tab}W)';
            Object.assign(btn.style, {
                cursor: 'pointer', marginLeft: '10px', fontSize: '14px',
                verticalAlign: 'middle', userSelect: 'none',
                border: '1px solid #eee', borderRadius: '4px',
                padding: '2px 4px', backgroundColor: '#fff'
            });

            btn.onclick = (e) => {
                e.stopPropagation();
                const val = `${Math.round(l)}\t${Math.round(w)}`;
                navigator.clipboard.writeText(val).then(() => {
                    const original = btn.innerHTML;
                    btn.innerHTML = '✅';
                    setTimeout(() => btn.innerHTML = original, 1000);
                });
            };
            return btn;
        };

        const partialSearch = (rawL && rawW) ? `${rawL}x${rawW}` : null;
        let container = findInsertTarget(card, dimText);
        // If not found, try partial
        if (!container && partialSearch) container = findInsertTarget(card, partialSearch);

        if (container) {
            const walker = document.createTreeWalker(card, NodeFilter.SHOW_TEXT, null, false);
            let node;
            while (node = walker.nextNode()) {
                const txt = node.textContent;
                if (txt.includes(dimText) || (partialSearch && txt.includes(partialSearch))) {
                    const btn = createBtn();
                    if (node.nextSibling) node.parentNode.insertBefore(btn, node.nextSibling);
                    else node.parentNode.appendChild(btn);
                    return;
                }
            }
            // Fallback
            const btn = createBtn();
            btn.style.float = 'right';
            container.appendChild(btn);
        }
    }

    function findInsertTarget(card, dimText) {
        const walker = document.createTreeWalker(card, NodeFilter.SHOW_TEXT, null, false);
        let node;
        while (node = walker.nextNode()) {
            if (node.textContent.includes(dimText)) {
                let container = node.parentElement;
                while (container && container.tagName !== 'DIV' && container !== card) container = container.parentElement;
                return container;
            }
        }
        return null;
    }

    function injectPriceInputs(card, offerId, partId, qty) {
        const row = document.createElement('div');
        row.className = 'xom-price-row';
        row.innerHTML = `<div style="display:flex; flex-direction:column;"><label>Price</label><input type="number" step="0.01" class="xom-price-input"></div><div style="display:flex; flex-direction:column; flex:1;"><label>Notes</label><input type="text" class="xom-obs-input" placeholder="Ex: 100 mat + 50 finish"></div><div style="display:flex; flex-direction:column; align-items:flex-end;"><label>Total</label><span class="xom-line-total">0.00 €</span></div>`;
        card.appendChild(row);
        const pi = row.querySelector('.xom-price-input');
        const ni = row.querySelector('.xom-obs-input');
        const key = `offer:${offerId}:part:${partId}`;
        try {
            if (chrome.runtime?.id) {
                chrome.storage.local.get([key], r => {
                    if (chrome.runtime.lastError) return;
                    if (r[key]) { pi.value = r[key].unit_price || ''; ni.value = r[key].notes || ''; updateLineTotal(row, pi.value, qty); }
                });
            }
        } catch (e) { }

        const calculateFromNotes = (text) => {
            if (!text.includes('+')) return null;
            // Split by + and extract the first number from each segment
            const parts = text.split('+');
            let sum = 0;
            let found = false;

            for (const part of parts) {
                // regex to find the first floating point number in the string
                const match = part.match(/(\d+(?:[.,]\d+)?)/);
                if (match) {
                    const val = parseFloat(match[1].replace(',', '.'));
                    if (!isNaN(val)) {
                        sum += val;
                        found = true;
                    }
                }
            }
            return found ? sum.toFixed(2) : null;
        };

        const save = (isNoteInput = false) => {
            if (isNoteInput) {
                const calcPrice = calculateFromNotes(ni.value);
                if (calcPrice !== null) {
                    pi.value = calcPrice;
                }
            }

            try {
                if (chrome.runtime?.id) {
                    chrome.storage.local.set({ [key]: { unit_price: pi.value, notes: ni.value, updated: new Date().toISOString() } });
                } else {
                    console.warn("[XomExt] Context invalidated, cannot save to storage. Please refresh.");
                }
            } catch (e) { }

            updateLineTotal(row, pi.value, qty);
            recalculateTotals();
        };

        pi.oninput = () => save(false);
        ni.oninput = () => save(true);
    }

    function updateLineTotal(row, price, qty) { row.querySelector('.xom-line-total').textContent = ((parseFloat(price) || 0) * qty).toFixed(2) + " €"; }
    function recalculateTotals() {
        let total = 0;
        document.querySelectorAll('.xom-line-total').forEach(e => {
            total += parseFloat(e.textContent) || 0;
        });
        const gt = document.getElementById('xom-grand-total');
        if (gt) gt.textContent = total.toFixed(2) + " €";

        // Update Minimized Placeholder
        const mp = document.querySelector('.xom-minimized-placeholder');
        if (mp) {
            if (total > 0) {
                mp.textContent = total.toFixed(2) + " €";
            } else {
                mp.textContent = "€";
            }
        }
    }

    const debouncedScan = debounce(scanForCards, 500);
    setInterval(scanForCards, 2000);
    new MutationObserver(() => debouncedScan()).observe(document.body, { childList: true, subtree: true });

    // --- Backend Integration ---

    // UI for Backend
    const BackendUI = {
        ensureButton: function () {
            const isOfferPage = /\/offers\/\d+/.test(location.href);
            const container = document.getElementById('xom-backend-container');

            if (!isOfferPage) {
                if (container) container.remove();
                return;
            }

            if (container) return;

            const newContainer = document.createElement('div');
            newContainer.id = 'xom-backend-container';
            Object.assign(newContainer.style, {
                position: 'fixed', bottom: '20px', left: '20px',
                zIndex: 9999, display: 'flex', gap: '8px', alignItems: 'center'
            });

            const btn = document.createElement('button');
            btn.id = 'xom-backend-btn';
            btn.innerHTML = '📤 Send to Backend';
            Object.assign(btn.style, {
                padding: '10px 15px',
                backgroundColor: '#1890ff', color: 'white',
                border: 'none', borderRadius: '4px', cursor: 'pointer',
                boxShadow: '0 2px 8px rgba(0,0,0,0.2)', fontWeight: 'bold'
            });
            btn.onclick = () => startScraping();

            newContainer.appendChild(btn);
            document.body.appendChild(newContainer);

            this.checkScrapedStatus();
        },

        checkScrapedStatus: function () {
            try {
                if (!chrome.runtime?.id) return;
                const offerId = buildOffer().offer_id;
                if (!offerId || offerId === "unknown") return;

                // 1. Check Local
                chrome.storage.local.get(['scraped_' + offerId], (res) => {
                    if (chrome.runtime.lastError) return;

                    const cachedVal = res['scraped_' + offerId];
                    if (cachedVal) {
                        if (typeof cachedVal !== 'boolean') {
                            this.addBackendLink(offerId, cachedVal);
                            return;
                        }
                    }

                    // 2. Check Server
                    chrome.runtime.sendMessage({ action: "CHECK_OFFER", offerId: offerId }, (resp) => {
                        if (chrome.runtime.lastError) return;

                        if (resp && resp.exists) {
                            const intId = resp.internalId;
                            const save = {};
                            save['scraped_' + offerId] = intId;
                            chrome.storage.local.set(save);
                            this.addBackendLink(offerId, intId);
                        }
                    });
                });
            } catch (e) { }
        },

        addBackendLink: function (offerId, internalId) {
            const container = document.getElementById('xom-backend-container');
            if (container && !document.getElementById('xom-backend-link')) {
                const linkId = internalId || offerId;
                const link = document.createElement('a');
                link.id = 'xom-backend-link';
                link.href = `http://86.123.232.23:10000/offer/${linkId}`;
                link.target = '_blank';
                link.innerHTML = `🔗 Open Backend (#${linkId})`;
                Object.assign(link.style, {
                    backgroundColor: '#52c41a', color: 'white',
                    padding: '10px 15px', borderRadius: '4px',
                    textDecoration: 'none', fontWeight: 'bold',
                    boxShadow: '0 2px 8px rgba(0,0,0,0.2)', fontSize: '13px'
                });
                container.appendChild(link);
            }
        },

        setStatus: function (msg, type = 'info', detail = '') {
            const container = document.getElementById('xom-backend-container');
            if (!container) return;

            let status = document.getElementById('xom-backend-status');
            if (!status) {
                status = document.createElement('span');
                status.id = 'xom-backend-status';
                status.style.padding = '5px 10px';
                status.style.borderRadius = '4px';
                status.style.fontSize = '12px';
                container.appendChild(status);
            }

            status.innerHTML = `<b>${msg}</b> ${detail ? '(' + detail + ')' : ''}`;
            if (type === 'success') {
                status.style.backgroundColor = '#f6ffed';
                status.style.color = '#389e0d';
                status.style.border = '1px solid #b7eb8f';
            } else if (type === 'error') {
                status.style.backgroundColor = '#fff1f0';
                status.style.color = '#cf1322';
                status.style.border = '1px solid #ffa39e';
            } else {
                status.style.backgroundColor = '#e6f7ff';
                status.style.color = '#096dd9';
                status.style.border = '1px solid #91d5ff';
            }
            setTimeout(() => { if (status) status.remove(); }, 5000);
        },

        showAgentGeo: function (geoStatus, agentSource) {
            const container = document.getElementById('xom-backend-container');
            if (!container || !geoStatus) return;
            latestAgentGeoStatus = geoStatus;
            latestAgentGeoSource = agentSource || latestAgentGeoSource;

            let badge = document.getElementById('xom-agent-geo');
            if (!badge) {
                badge = document.createElement('span');
                badge.id = 'xom-agent-geo';
                Object.assign(badge.style, {
                    padding: '10px 12px',
                    borderRadius: '4px',
                    fontSize: '13px',
                    fontWeight: 'bold',
                    boxShadow: '0 2px 8px rgba(0,0,0,0.12)'
                });
                container.appendChild(badge);
            }

            const items = geoStatus.geo_items || [];
            const readyItems = items.filter(item => (item.target_path || item.targetPath) && item.geo_exists === true);
            const failedItems = items.filter(item => item.geo_exists === false);
            const first = readyItems[0];
            if (geoStatus.ok && first) {
                badge.textContent = 'GEO gata';
                badge.title = JSON.stringify(readyItems, null, 2);
                badge.style.backgroundColor = '#f6ffed';
                badge.style.color = '#237804';
                badge.style.border = '1px solid #b7eb8f';
            } else if (failedItems.length) {
                badge.textContent = 'GEO in asteptare';
                badge.title = failedItems.map(item => item.reason || item.status || 'GEO nu exista inca').join('\n');
                badge.style.backgroundColor = '#fffbe6';
                badge.style.color = '#ad6800';
                badge.style.border = '1px solid #ffe58f';
            } else if (geoStatus.status && geoStatus.status !== 'not_found') {
                badge.textContent = `SheetMetal agent: ${geoStatus.status}`;
                badge.title = 'Agentul a vazut oferta, dar nu exista inca un .geo inregistrat.';
                badge.style.backgroundColor = '#fffbe6';
                badge.style.color = '#ad6800';
                badge.style.border = '1px solid #ffe58f';
            } else {
                badge.textContent = 'SheetMetal agent: fara .geo';
                badge.title = 'Oferta nu are inca rezultat in XometryAnaliza.';
                badge.style.backgroundColor = '#f5f5f5';
                badge.style.color = '#595959';
                badge.style.border = '1px solid #d9d9d9';
            }

            const offerId = geoStatus.offer_id || buildOffer().offer_id;
            document.querySelectorAll('.ant-card-body').forEach(card => {
                const partId = extractPartId(card.textContent || '');
                if (partId) {
                    injectGeoControl(card, geoStatus, latestAgentGeoSource, offerId, partId);
                }
            });
        }
    };

    function startScraping() {
        const data = buildOffer();
        log(`Sending offer ${data.offer_id} to backend...`);
        BackendUI.setStatus("Sending...", "info");

        // Fix: background.js expects action='scrapingComplete' and payload in 'offerData'
        chrome.runtime.sendMessage({ action: "scrapingComplete", offerData: data }, (response) => {
            if (chrome.runtime.lastError) {
                BackendUI.setStatus("Error", "error", chrome.runtime.lastError.message);
                return;
            }
            // Background sends { ok: true/false, internalId: ... } or { success: ... } - checking both for safety
            if (response && (response.success || response.ok)) {
                // Server might return 'id' or 'internalId' or just 'success'
                console.log("[XomExt] Backend Save Response:", response);
                const intId = response.internalId || response.id || response.offer_id;
                BackendUI.setStatus("Saved!", "success", intId ? `ID: ${intId}` : '');
                BackendUI.addBackendLink(data.offer_id, intId);
                const save = {};
                save['scraped_' + data.offer_id] = intId;
                chrome.storage.local.set(save);
            } else {
                BackendUI.setStatus("Failed", "error", response ? response.error : "Unknown");
            }
        });
    }

    function refreshAgentGeo() {
        try {
            const data = buildOffer();
            if (!data || !data.offer_id || data.offer_id === "unknown") return;
            chrome.runtime.sendMessage({ action: "GET_AGENT_GEO", offerId: data.offer_id }, (response) => {
                if (chrome.runtime.lastError || !response || !response.success) return;
                BackendUI.showAgentGeo(response.data, response.source);
            });
        } catch (e) { }
    }

    function buildOffer() {
        const offerId = window.location.href.match(/\/offers\/(\d+)/)?.[1] || "unknown";

        let jobId = null;
        const h1 = document.querySelector('h1');
        if (h1) {
            const match = h1.textContent.match(/(RFQ-[\d-]+|J-[\d-]+)/);
            if (match) jobId = match[1];
        }
        // Fallback for Job ID
        if (!jobId) {
            const titleEl = document.querySelector('._title_1a29i_1');
            if (titleEl) {
                const match = titleEl.textContent.match(/(RFQ-[\d-]+|J-[\d-]+)/);
                if (match) jobId = match[1];
            }
        }

        // If still null, use text content but sanitize
        if (!jobId && h1) jobId = h1.textContent.trim();
        if (!jobId) jobId = document.title || "Unknown Job";

        const parts = [];
        document.querySelectorAll('.ant-card-body').forEach(card => {
            if (card.innerText.includes("Part ID:")) {
                const p = parsePartCard(card);
                if (p) parts.push(p);
            }
        });

        // Ensure we send valid strings
        return {
            offer_id: offerId,
            job_name: jobId,
            title: jobId, // duplicate for backend safety
            url: window.location.href,
            page_text: (document.body?.innerText || '').slice(0, 10000),
            parts: parts
        };
    }

    function parsePartCard(card) {
        try {
            const text = card.innerText;
            const partId = extractPartId(text);
            if (!partId) return null;

            // Image
            const imgEl = card.querySelector('img');
            const thumb_url = imgEl ? imgEl.src : "N/A";

            // Part Name / File Name (usually bold or near the top)
            // Strategy: Look for the line before "Part ID" or the first strong/b tag
            let partName = "N/A";
            const nameEl = card.querySelector('strong, b, .ant-typography-strong'); // frequent classes
            if (nameEl) partName = nameEl.innerText;
            else {
                // Fallback: splitting text
                const lines = text.split('\n').map(l => l.trim()).filter(l => l);
                // Usually line 0 or 1 is the name
                if (lines.length > 0) partName = lines[0];
            }
            if (partName.includes("Part ID")) partName = "Part " + partId; // fallback if parsing failed

            // Dimensions (look for pattern like 100.0x50.0x20.0)
            const dimMatch = text.match(/(\d+(?:[.,]\d+)?)\s*[xX]\s*(\d+(?:[.,]\d+)?)\s*[xX]\s*(\d+(?:[.,]\d+)?)/);
            let l = 0, w = 0, h = 0;
            let dimString = "N/A";
            if (dimMatch) {
                l = parseFloat(dimMatch[1].replace(',', '.'));
                w = parseFloat(dimMatch[2].replace(',', '.'));
                h = parseFloat(dimMatch[3].replace(',', '.'));
                dimString = `${l}x${w}x${h}`;
            }

            // Material
            let material = "Unknown";
            const matMatch = text.match(/Material:\s*([^\n\r]+)/i);
            if (matMatch) material = matMatch[1].trim();

            let process = "Unknown";
            const processMatch = text.match(/Process:\s*([^\n\r]+)/i);
            if (processMatch) process = processMatch[1].trim();

            const finish = "Standard";

            // Quantity
            const qtyMatch = text.match(/(\d+)\s*(?:pieces|parts|buc|stk)/i);
            let qty = 1;
            if (qtyMatch) qty = parseInt(qtyMatch[1], 10);


            return {
                part_id: partId,
                part_name: partName, // New field for backend
                thumb_url: thumb_url, // New field
                material: material,
                process: process,
                thickness: h, // approximate
                quantity: qty,
                dimensions: { l, w, h },
                dim_string: dimString // New field
            };

        } catch (e) { return null; }
    }

    setInterval(() => BackendUI.ensureButton(), 2000);
    setInterval(() => refreshAgentGeo(), 5000);

    // --- Download Features ---
    function injectDownloadOverlayRibbon() {
        if (document.getElementById('xom-dl-ribbon')) return;
        const div = document.createElement('div');
        div.id = 'xom-dl-ribbon';
        Object.assign(div.style, {
            position: 'fixed', bottom: '25%', right: '0', display: 'flex', flexDirection: 'column', gap: '5px', zIndex: 9998,
            alignItems: 'flex-end', paddingRight: '10px' // offset from edge
        });

        const createBtn = (icon, text, color, id) => {
            const container = document.createElement('div');
            Object.assign(container.style, {
                display: 'flex', justifyContent: 'flex-end', overflow: 'hidden',
                transition: 'width 0.3s ease', width: '40px', // start minimized
                backgroundColor: color, borderRadius: '4px 0 0 4px',
                boxShadow: '0 2px 5px rgba(0,0,0,0.2)', cursor: 'pointer',
                whiteSpace: 'nowrap'
            });

            const b = document.createElement('button');
            b.id = id;
            b.innerHTML = `<span style="font-size:16px; min-width:30px; display:inline-block; text-align:center;">${icon}</span><span style="margin-left:4px; padding-right:10px;">${text}</span>`;
            Object.assign(b.style, {
                display: 'flex', alignItems: 'center', padding: '6px 5px',
                backgroundColor: 'transparent', color: 'white', border: 'none',
                fontSize: '13px', fontWeight: 'bold', cursor: 'pointer', width: '100%'
            });

            container.appendChild(b);

            container.onmouseenter = () => container.style.width = '140px';
            container.onmouseleave = () => container.style.width = '40px';

            b.containerRef = container;
            return b;
        };

        const zipBtn = createBtn('⬇', 'ZIP Job', '#1890ff', 'xom-btn-zip');
        zipBtn.onclick = (e) => {
            e.stopPropagation();
            const links = Array.from(document.querySelectorAll('a[href*="download_zip"]'));
            let downloadLink = null;
            downloadLink = links.find(a => a.innerText.toLowerCase().includes('all job files'));
            // Support for RFQ "All Drawings.zip"
            if (!downloadLink) {
                downloadLink = links.find(a => a.innerText.toLowerCase().includes('all drawings'));
            }
            if (!downloadLink) {
                downloadLink = links.find(a => {
                    const card = a.closest('.ant-card-body');
                    if (card && !card.innerText.includes('Part ID:')) return true;
                    return false;
                });
            }
            if (!downloadLink) {
                downloadLink = links.find(a => {
                    const t = a.innerText.toLowerCase();
                    return t.includes('all') || t.includes('files') || t.includes('tot');
                });
            }
            if (downloadLink) {
                const url = downloadLink.href;
                let currentJobId = "Unknown";

                // Try H1 first
                const h1 = document.querySelector('h1');
                if (h1) {
                    const text = h1.textContent;
                    // Match: "Job J-123", "J-123", "RFQ-123-456", "RFQ-123"
                    const match = text.match(/(RFQ-[\d-]+|J-[\d-]+)/);
                    if (match) currentJobId = match[1];
                }

                // Fallback: Try specific class for RFQ title if H1 failed or didn't match
                if (currentJobId === "Unknown") {
                    const titleEl = document.querySelector('._title_1a29i_1'); // Class from user snippet
                    if (titleEl) {
                        const match = titleEl.textContent.match(/(RFQ-[\d-]+|J-[\d-]+)/);
                        if (match) currentJobId = match[1];
                    }
                }

                const filename = `Doc ${currentJobId}.zip`;

                const iconSpan = zipBtn.querySelector('span'); // first span is icon
                const originalIcon = iconSpan.innerHTML;
                iconSpan.innerHTML = '⏳';
                zipBtn.containerRef.style.width = '140px'; // Force expand during loading

                chrome.runtime.sendMessage({
                    action: 'DOWNLOAD_FILE', // Fix: background.js expects 'action', not 'type'
                    url: url,
                    filename: filename
                }, (response) => {
                    setTimeout(() => {
                        iconSpan.innerHTML = originalIcon;
                        if (!zipBtn.containerRef.matches(':hover')) zipBtn.containerRef.style.width = '40px';
                        if (!response || !response.success) {
                            alert("Download failed to start.");
                        }
                    }, 2000);
                });
            } else {
                alert("Could not find 'All Job files' download link.");
            }
        };

        const pdfBtn = createBtn('📄', 'Save Page', '#f5222d', 'xom-btn-pdf');
        pdfBtn.onclick = (e) => {
            e.stopPropagation();
            const oldTitle = document.title;
            let currentJobId = "Unknown";
            const h1 = document.querySelector('h1');
            if (h1) {
                const match = h1.textContent.match(/Job\s+(J-[\d-]+)/);
                if (match) currentJobId = match[1];
                else {
                    const match2 = h1.textContent.match(/J-[\d-]+/);
                    if (match2) currentJobId = match2[0];
                }
            }
            document.title = `DataJob: ${currentJobId}`;
            window.print();
            setTimeout(() => { document.title = oldTitle; }, 1000);
        };

        div.appendChild(zipBtn.containerRef);
        div.appendChild(pdfBtn.containerRef);
        document.body.appendChild(div);

        const style = document.createElement('style');
        style.type = 'text/css';
        style.innerHTML = `@keyframes spin { 100% { -webkit-transform: rotate(360deg); transform:rotate(360deg); } }`;
        document.head.appendChild(style);
    }

    // --- Walkthrough ---
    function injectWalkthrough() {
        if (localStorage.getItem('xom_walkthrough_seen_2_51')) return;

        // Container
        const div = document.createElement('div');
        Object.assign(div.style, {
            position: 'fixed', bottom: '20px', right: '20px', width: '300px',
            backgroundColor: 'white', padding: '15px', borderRadius: '8px',
            boxShadow: '0 4px 12px rgba(0,0,0,0.3)', zIndex: 10001,
            borderLeft: '5px solid #1890ff', fontFamily: 'Arial, sans-serif'
        });

        const h3 = document.createElement('h3');
        h3.innerText = 'Extensions Updated! (v2.55)';
        Object.assign(h3.style, { margin: '0 0 10px 0', color: '#1890ff' });

        const ul = document.createElement('ul');
        ul.innerHTML = `
             <li><b>📜 Rules:</b> New "Rules" button for guidelines!</li>
             <li><b>🕒 History:</b> Auto-check for similar previous jobs.</li>
             <li><b>⬇ RFQ:</b> Support for "All Drawings.zip".</li>
             <li><b>📏 Smart Dims:</b> Inputs persist across reloads!</li>
        `;
        Object.assign(ul.style, { margin: '0 0 10px 20px', padding: '0', fontSize: '13px', color: '#333' });

        const btnContainer = document.createElement('div');
        btnContainer.style.textAlign = 'right';

        const btn = document.createElement('button');
        btn.innerText = 'Got it!';
        Object.assign(btn.style, {
            background: '#1890ff', color: 'white', border: 'none',
            padding: '5px 10px', borderRadius: '4px', cursor: 'pointer'
        });

        // Robust Listener
        btn.onclick = (e) => {
            e.stopPropagation();
            try {
                div.remove();
                localStorage.setItem('xom_walkthrough_seen_2_51', 'true');
            } catch (err) {
                console.error(err);
                div.style.display = 'none'; // Fallback
            }
        };

        btnContainer.appendChild(btn);
        div.appendChild(h3);
        div.appendChild(ul);
        div.appendChild(btnContainer);

        document.body.appendChild(div);
    }

    // --- Job History & Rules ---

    function checkHistoryAndInject() {
        if (document.getElementById('xom-history-indicator')) return;

        let jobId = null;
        let h1 = document.querySelector('h1');

        // Strategy 1: H1
        if (h1) {
            const match = h1.textContent.match(/(RFQ-[\d-]+|J-[\d-]+)/);
            if (match) jobId = match[1];
        }

        // Strategy 2: Specific Title Class (fallback)
        if (!jobId) {
            const titleEl = document.querySelector('._title_1a29i_1');
            if (titleEl) {
                const match = titleEl.textContent.match(/(RFQ-[\d-]+|J-[\d-]+)/);
                if (match) jobId = match[1];
                if (!h1) h1 = titleEl; // Use this as anchor if H1 missing
            }
        }

        if (!jobId || !h1) return;

        // Prevent infinite loop if already checked for this ID
        if (h1.dataset.xomHistoryChecked === jobId) return;

        // Mark as checked immediately to stop further calls
        h1.dataset.xomHistoryChecked = jobId;

        // Log for debugging user issues
        console.log("[XomExt] Checking history for ID:", jobId);

        if (chrome.runtime?.id) {
            const currentOfferId = window.location.href.match(/\/offers\/(\d+)/)?.[1];
            chrome.runtime.sendMessage({
                action: 'CHECK_HISTORY',
                jobId: jobId,
                excludeOfferId: currentOfferId
            }, (res) => {
                if (chrome.runtime.lastError) return;
                if (res && res.success && res.count > 0) {
                    injectHistoryUI(h1, res.count, res.items);
                } else {
                    console.log("[XomExt] No history found for", jobId);
                }
            });
        }
    }

    function injectHistoryUI(h1, count, items) {
        const span = document.createElement('span');
        span.id = 'xom-history-indicator';
        span.innerHTML = `🕒 <b>${count}</b> similar job(s) found!`;
        Object.assign(span.style, {
            fontSize: '14px', color: '#722ed1', backgroundColor: '#f9f0ff',
            border: '1px solid #d3adf7', borderRadius: '4px', padding: '2px 8px',
            marginLeft: '10px', cursor: 'pointer', verticalAlign: 'middle', display: 'inline-block'
        });

        // Tooltip for details
        let tooltipList = items.map(i => {
            const label = i.title || i.job_name || "Job " + i.offer_id;
            const url = BackendUI ? 'http://86.123.232.23:10000/offer/' + (i.id || i.offer_id) : '#';
            return `<div><a href="${url}" target="_blank" style="display:block; padding:2px 0;">${label}</a></div>`;
        }).join('');

        // Simple click to show alert or strict tooltip
        span.title = `Found ${count} previous offers.`;

        const listDiv = document.createElement('div');
        listDiv.innerHTML = `<div style="border-bottom:1px solid #eee; margin-bottom:4px"><b>Previous Jobs:</b></div>${tooltipList}`;
        Object.assign(listDiv.style, {
            position: 'absolute', display: 'none', backgroundColor: 'white',
            border: '1px solid #ccc', padding: '10px', borderRadius: '4px',
            boxShadow: '0 2px 8px rgba(0,0,0,0.15)', zIndex: 1000,
            marginTop: '5px', minWidth: '200px', whiteSpace: 'normal',
            textAlign: 'left'
        });

        span.appendChild(listDiv);

        let timeout;
        span.onmouseenter = () => {
            clearTimeout(timeout);
            listDiv.style.display = 'block';
        };
        span.onmouseleave = () => {
            timeout = setTimeout(() => {
                listDiv.style.display = 'none';
            }, 300);
        };

        h1.appendChild(span);
    }

    function injectRulesButton() {
        const gtBox = document.getElementById('xom-grand-total-content');
        if (!gtBox || document.getElementById('xom-rules-btn')) return;

        const div = document.createElement('div');
        div.style.marginTop = '2px';
        div.style.textAlign = 'center';

        const btn = document.createElement('button');
        btn.id = 'xom-rules-btn';
        btn.innerText = '📜 Rules';
        Object.assign(btn.style, {
            cursor: 'pointer', fontSize: '10px', padding: '2px 6px',
            border: '1px solid #ccc', background: '#fff', borderRadius: '3px',
            color: '#d46b08', borderColor: '#ffbb96'
        });

        btn.onclick = (e) => {
            e.stopPropagation();
            showRulesModal();
        };

        div.appendChild(btn);
        gtBox.appendChild(div);
    }

    function showRulesModal() {
        if (document.getElementById('xom-rules-modal')) return;

        const overlay = document.createElement('div');
        overlay.id = 'xom-rules-modal';
        Object.assign(overlay.style, {
            position: 'fixed', top: 0, left: 0, width: '100vw', height: '100vh',
            backgroundColor: 'rgba(0,0,0,0.5)', zIndex: 11000,
            display: 'flex', justifyContent: 'center', alignItems: 'center'
        });

        const card = document.createElement('div');
        Object.assign(card.style, {
            backgroundColor: 'white', width: '600px', maxHeight: '80vh',
            borderRadius: '8px', padding: '20px', overflowY: 'auto',
            boxShadow: '0 4px 12px rgba(0,0,0,0.3)', fontFamily: 'Arial, sans-serif'
        });

        card.innerHTML = `
            <div style="display:flex; justify-content:space-between; margin-bottom:15px;">
                <h2 style="margin:0; color:#1890ff;">⚙️ Xometry Extension Rules</h2>
                <button id="xom-rules-close" style="background:none; border:none; font-size:20px; cursor:pointer;">✖</button>
            </div>
            <div style="font-size:14px; line-height:1.6; color:#333;">
                <p><b>1. RFQ Documentation:</b> Always check "All Drawings.zip" or "All Job Files". Verification is key.</p>
                <p><b>2. Material Stock:</b> Be careful with 3.035mm thickness (Sheet vs Plate). Check stock for closest standard (3mm, 4mm, etc.).</p>
                <p><b>3. History Check:</b> If "History Found" appears, check previous offers for price consistency.</p>
                <p><b>4. Complex Geometry:</b> If warnings appear (Red Flags), add extra buffer to lead time.</p>
                <hr>
                <p><i>(This list can be updated in future versions)</i></p>
            </div>
        `;

        overlay.appendChild(card);
        document.body.appendChild(overlay);

        document.getElementById('xom-rules-close').onclick = () => overlay.remove();
        overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };
    }

})();
