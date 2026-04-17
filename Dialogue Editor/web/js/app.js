/**
 * Dialogue Editor | Core App Controller
 * Full Feature Parity with Tkinter build
 */

// =============================================================================
// STATE
// =============================================================================
let state = {
    currentTab: 'dashboard',
    reviewer: {
        currentItem: null,
        fullQueue:   [],
        currentIdx:  0,
        chatHistory: [],
        mode:        'review',   // 'review' | 'translate'
        anachRanges: [],         // Track anachronism ranges for Tab replacement
    },
    settings: {
        tagSearch:    '',
        lastConfig:   null,
        selectedTag:  null,
        selectedPreset: null,
        selectedWall: null,
        selectedFolder: null,
        selectedTrigger: null,
        selectedRule: null,
        selectedArchetype: null,
        editingRuleIdx: -1,
        editingArchKey: null,
    },
    search: {
        results: [],
    },
    standardLimit: 50,   // loaded from backend on init
};

// =============================================================================
// INIT
// =============================================================================
window.onload = async () => {
    console.log('[SYSTEM] App Initialized.');
    initTabs();
    initSettingsNav();
    initSettingsActions();
    initReviewerActions();
    initDashboardActions();
    initSearchActions();
    initChatActions();
    initModals();
    initShortcuts();
    await loadDashboard();
    // Pre-fetch the standard limit so counters show the right number
    try { state.standardLimit = await eel.get_standard_limit()(); } catch(e) {}
};

// =============================================================================
// EEL CALLBACKS (called by Python)
// =============================================================================
eel.expose(log_to_js);
function log_to_js(msg) {
    const box = document.getElementById('main-log');
    if (box) { box.innerHTML += '\n' + msg; box.scrollTop = box.scrollHeight; }
}

eel.expose(update_progress);
function update_progress(pct) {
    const bar  = document.getElementById('main-progress');
    const text = document.getElementById('progress-text');
    if (bar)  bar.style.width  = `${pct}%`;
    if (text) text.innerText   = `${Math.round(pct)}%`;
}

eel.expose(scan_done);
function scan_done(count) {
    log_to_js(`[SYSTEM] Scan complete. ${count} item(s) found.`);
    update_progress(100);
    if (count > 0) {
        openInputModal('SCAN COMPLETE', `Found ${count} items. Switch to Review Editor?`, '', (val) => {
            if (val) {
                state.reviewer.mode = 'review';
                switchTab('reviewer');
            }
        });
    } else {
        openInputModal('SCAN COMPLETE', 'No issues found.', '', (val) => {});
    }
}

// =============================================================================
// TAB SYSTEM
// =============================================================================
function initTabs() {
    document.querySelectorAll('.tab-btn').forEach(tab => {
        tab.onclick = () => switchTab(tab.getAttribute('data-tab'));
    });
}

function switchTab(tabId) {
    document.querySelectorAll('.tab-btn').forEach(b =>
        b.classList.toggle('active', b.getAttribute('data-tab') === tabId));
    document.querySelectorAll('.tab-content').forEach(p =>
        p.classList.toggle('active', p.id === `tab-${tabId}`));
    state.currentTab = tabId;
    if (tabId === 'search') {
        initSearchActions();
    }
    if (tabId === 'reviewer') {
        renderRowSidebar();
        if (!state.reviewer.currentItem) loadItemAtIdx(0);
        // Initialize in-universe toggle state
        eel.get_full_config()().then(config => {
            const iu = document.getElementById('reviewer-in-universe');
            if (iu && config) iu.checked = !!config.in_universe;
        });
    }
    if (tabId === 'settings') loadSettings();
    if (tabId === 'dashboard') loadDashboard();
}

// =============================================================================
// DASHBOARD
// =============================================================================
function initDashboardActions() {
    const btnScan = document.getElementById('btn-start-scan');
    if (btnScan) btnScan.onclick = async () => {
        log_to_js('\n[SYSTEM] Initialising scan…');
        update_progress(0);
        await eel.start_batch_scan()();
    };

    const btnCalc = document.getElementById('btn-calc-progress');
    if (btnCalc) btnCalc.onclick = async () => {
        btnCalc.innerText = 'CALCULATING…';
        btnCalc.disabled  = true;
        try {
            const res = await eel.calculate_project_stats()();
            document.getElementById('stat-total-lines').innerText = res.total ?? '--';
            document.getElementById('stat-percent').innerText     = `${res.percent ?? 0}%`;
        } finally {
            btnCalc.innerText = 'CALCULATE';
            btnCalc.disabled  = false;
        }
    };

    const bindListActions = (section, listId, addBtnId, remBtnId) => {
        const addBtn = document.getElementById(addBtnId);
        const remBtn = document.getElementById(remBtnId);
        if (addBtn) addBtn.onclick = async () => {
            const val = prompt(`Add to ${section}:`);
            if (val && val.trim()) { await eel.add_list_item(section, val.trim())(); loadDashboard(); }
        };
        if (remBtn) remBtn.onclick = async () => {
            const list = document.getElementById(listId);
            const sel  = list ? list.querySelector('li.selected') : null;
            if (!sel) return alert('Select an item first.');
            if (confirm(`Remove "${sel.innerText}"?`)) {
                await eel.remove_list_item(section, sel.innerText.trim())();
                loadDashboard();
            }
        };
    };

    bindListActions('folders',  'dash-folder-list',  'btn-dash-add-folder',  'btn-dash-rem-folder');
    bindListActions('triggers', 'dash-trigger-list', 'btn-dash-add-trigger', 'btn-dash-rem-trigger');

    const setupToggle = (id, key) => {
        const el = document.getElementById(id);
        if (el) el.onchange = async () => { await eel.save_config_field(key, el.checked)(); };
    };
    setupToggle('dash-in-universe', 'in_universe');
    setupToggle('dash-preview-mode', 'preview_mode');
}

async function loadDashboard() {
    try {
        const data = await eel.get_dashboard_data()();
        if (!data) return;
        document.getElementById('stat-folders').innerText = (data.folders || []).length;
        document.getElementById('stat-files').innerText   = data.file_count || 0;
        const iu = document.getElementById('dash-in-universe');
        if (iu) iu.checked = !!data.in_universe;
        const pm = document.getElementById('dash-preview-mode');
        if (pm) pm.checked = !!data.preview_mode;
        renderDashList(data.folders  || [], 'dash-folder-list');
        renderDashList(data.triggers || [], 'dash-trigger-list');
        // Show cached stats if available
        if (data.last_stats && data.last_stats.total > 0) {
            document.getElementById('stat-total-lines').innerText = data.last_stats.total;
            document.getElementById('stat-percent').innerText     = `${data.last_stats.percent}%`;
        }
    } catch(e) { console.error('[loadDashboard]', e); }
}

function renderDashList(items, listId) {
    const list = document.getElementById(listId);
    if (!list) return;
    list.innerHTML = '';
    items.forEach(item => {
        const li = document.createElement('li');
        li.innerText = item;
        li.onclick   = () => {
            list.querySelectorAll('li').forEach(el => el.classList.remove('selected'));
            li.classList.add('selected');
        };
        list.appendChild(li);
    });
}

// =============================================================================
// REVIEWER — NAVIGATION
// =============================================================================
function initReviewerActions() {
    const bind = (id, ev, fn) => { const el = document.getElementById(id); if (el) el[ev] = fn; };

    // Sidebar tabs
    document.querySelectorAll('.side-tab').forEach(tab => {
        tab.onclick = () => {
            const sideId = tab.getAttribute('data-side');
            document.querySelectorAll('.side-tab').forEach(t => t.classList.toggle('active', t === tab));
            document.querySelectorAll('.side-pane').forEach(p => p.classList.toggle('active', p.id === `side-${sideId}`));
        };
    });

    bind('btn-apply',       'onclick',  applyFix);
    bind('btn-skip',        'onclick',  nextItem);
    bind('btn-prev',        'onclick',  prevItem);
    bind('btn-rewrap',      'onclick',  rewrapEditor);
    bind('btn-dash-em',     'onclick',  () => replaceDashes('—'));
    bind('btn-dash-triple', 'onclick',  () => replaceDashes('...'));
    bind('show-translated-rows', 'onchange', renderRowSidebar);

    // In-universe toggle
    const setupToggle = (id, key) => {
        const el = document.getElementById(id);
        if (el) el.onchange = async () => { await eel.save_config_field(key, el.checked)(); };
    };
    setupToggle('reviewer-in-universe', 'in_universe');

    const ed = document.getElementById('en-editor');
    if (ed) {
        let skipCursorRestore = false;
        
        ed.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                const selection = window.getSelection();
                if (selection.rangeCount > 0) {
                    const range = selection.getRangeAt(0);
                    const br = document.createElement('br');
                    range.deleteContents();
                    range.insertNode(br);
                    // Create a text node with a space after br to ensure cursor can be placed
                    const textNode = document.createTextNode(' ');
                    br.parentNode.insertBefore(textNode, br.nextSibling);
                    range.setStart(textNode, 1);
                    range.setEnd(textNode, 1);
                    selection.removeAllRanges();
                    selection.addRange(range);
                    // Trigger input event to update highlights
                    ed.dispatchEvent(new Event('input', { bubbles: true }));
                }
            }
        });
        
        ed.addEventListener('input',  () => { 
            updateReviewerCounters(); 
            syncLineCounters();
            scanAnachronisms(ed.innerText);
        });
        ed.addEventListener('scroll', syncCounterScroll);
        ed.addEventListener('mousemove', handleMouseMove);
        ed.addEventListener('mouseleave', hideTooltip);
        ed.addEventListener('click', handleEditorClick);
        ed.addEventListener('paste', handlePaste);
        
        // Store the skip flag on the element for renderHighlights to access
        ed._skipCursorRestore = () => skipCursorRestore;
    }
}

function handlePaste(e) {
    e.preventDefault();
    const text = (e.clipboardData || window.clipboardData).getData('text/plain');
    if (!text) return;
    
    const selection = window.getSelection();
    if (selection.rangeCount > 0) {
        const range = selection.getRangeAt(0);
        range.deleteContents();
        range.insertNode(document.createTextNode(text));
        range.collapse(false);
        selection.removeAllRanges();
        selection.addRange(range);
    }
    
    updateReviewerCounters();
    syncLineCounters();
}

function handleEditorClick(e) {
    if (e.target.classList.contains('anach-highlight')) {
        const word = e.target.getAttribute('data-word');
        const suggestion = e.target.getAttribute('data-suggestion');
        if (word && suggestion) {
            replaceAnachronism(word, suggestion);
            hideTooltip();
        }
    }
}

function hideTooltip() {
    const tooltip = document.getElementById('anach-tooltip');
    if (tooltip) {
        tooltip.style.display = 'none';
    }
    hoveredAnachronism = null;
}

async function loadItemAtIdx(idx) {
    try {
        const items = await eel.get_all_items_in_queue()();
        state.reviewer.fullQueue = items || [];
    } catch(e) { console.error('[loadItemAtIdx] queue fetch', e); }

    const items = state.reviewer.fullQueue;
    if (!items.length) {
        document.getElementById('review-status').innerText = 'QUEUE: EMPTY';
        return;
    }
    idx = Math.max(0, Math.min(idx, items.length - 1));
    state.reviewer.currentIdx  = idx;
    const item = items[idx];
    state.reviewer.currentItem = item;

    // Header
    document.getElementById('speaker-name').innerText     = item.speaker || '—';
    document.getElementById('entry-type-parity').innerText = item.category || '—';
    document.getElementById('jp-source').innerText        = item.jp || '';
    document.getElementById('en-editor').innerText        = item.en || '';
    document.getElementById('review-status').innerText    = `QUEUE: ${idx + 1} / ${items.length}`;

    updateReviewerCounters();
    syncLineCounters();
    renderRowSidebar();

    // Async enrichments (don't block render)
    fetchDeepLSuggestion(item.jp);
    populateLoreContext(item.jp);
    populateAdjacentContext(item.path, item.row);
    updatePreview();
}

async function nextItem() {
    const total = state.reviewer.fullQueue.length;
    if (total === 0) return;
    const next = state.reviewer.currentIdx + 1;
    if (next < total) {
        loadItemAtIdx(next);
    } else {
        // Try fetching another item from Python's rolling queue (review mode)
        const item = await eel.get_next_review_item()();
        if (item) {
            // refresh full list and move to new end
            await loadItemAtIdx(next);
        } else {
            alert('End of queue reached.');
        }
    }
}

function prevItem() {
    if (state.reviewer.currentIdx > 0) loadItemAtIdx(state.reviewer.currentIdx - 1);
}

async function applyFix() {
    const item  = state.reviewer.currentItem;
    if (!item) return;
    const text  = document.getElementById('en-editor').innerText;
    const force = document.getElementById('force-save-toggle').checked;

    const res = await eel.apply_fix(item.id, text, force)();
    if (res && res.ok) {
        const btn = document.getElementById('btn-apply');
        const prev = btn.innerText;
        btn.innerText = '✓ SAVED';
        setTimeout(() => { btn.innerText = prev; nextItem(); }, 400);
        // Update local copy so the sidebar shows the saved value
        state.reviewer.fullQueue[state.reviewer.currentIdx].en = text;
        renderRowSidebar();
    } else {
        const msg = (res && res.error) ? res.error : 'Save failed — unknown error.';
        alert(`[SAVE ERROR]\n${msg}`);
    }
}

async function rewrapEditor() {
    const text = document.getElementById('en-editor').innerText;
    const limit = state.standardLimit;
    const rewrapped = await eel.rewrap_text(text, limit)();
    if (rewrapped !== undefined && rewrapped !== null) {
        document.getElementById('en-editor').innerText = rewrapped;
        updateReviewerCounters();
        syncLineCounters();
    }
}

function replaceDashes(target) {
    const ed   = document.getElementById('en-editor');
    const fixed = ed.innerText.replace(/[-\u2013\u2014\u2015]{2,}/g, target);
    if (target === '...') {
        ed.innerText = fixed.replace(/\.\.\.(\w)/g, '... $1');
    } else {
        ed.innerText = fixed;
    }
    updateReviewerCounters();
    syncLineCounters();
}

// =============================================================================
// REVIEWER — COUNTERS / PREVIEW
// =============================================================================
function syncLineCounters() {
    const ed   = document.getElementById('en-editor');
    const ctr  = document.getElementById('line-counters');
    if (!ed || !ctr) return;
    
    // For contenteditable, count lines by splitting innerText by newlines
    const text = ed.innerText;
    const lines = text ? text.split('\n') : [];
    
    ctr.innerHTML = '';
    const displayLines = Math.max(lines.length || 1, 5);
    for (let i = 1; i <= displayLines; i++) {
        const s = document.createElement('span');
        s.innerText = i;
        ctr.appendChild(s);
    }
}

function syncCounterScroll() {
    const ed  = document.getElementById('en-editor');
    const ctr = document.getElementById('line-counters');
    if (ed && ctr) ctr.scrollTop = ed.scrollTop;
}

async function updateReviewerCounters() {
    const ed = document.getElementById('en-editor');
    if (!ed) return;

    // Per-line simulated lengths
    const lines  = ed.innerText.split('\n');
    const ctrEl  = document.getElementById('line-counters');
    if (ctrEl) {
        // Re-render with colour coding
        ctrEl.innerHTML = '';
        for (let i = 0; i < Math.max(lines.length, 5); i++) {
            const s   = document.createElement('span');
            const len = await eel.get_simulated_len(lines[i] || '')();
            s.innerText    = len || (i < lines.length ? 0 : '');
            s.style.color  = len > state.standardLimit ? '#ff5555' : 'var(--accent-color)';
            ctrEl.appendChild(s);
        }
    }

    // Total char count display
    const fullLen = await eel.get_simulated_len(ed.innerText)();
    const cc = document.getElementById('char-count');
    if (cc) {
        cc.innerText    = `${fullLen} / ${state.standardLimit}`;
        cc.style.color  = fullLen > state.standardLimit ? '#ff4444' : 'var(--accent-color)';
    }

    // Scan for anachronisms
    await scanAnachronisms(ed.innerText);

    updatePreview();
}

function updatePreview() {
    const ed = document.getElementById('en-editor');
    const pv = document.getElementById('preview-text');
    if (ed && pv) pv.innerText = ed.innerText;
}

// =============================================================================
// ANACHRONISMS
// =============================================================================
let hoveredAnachronism = null; // Track anachronism under mouse

async function scanAnachronisms(text) {
    if (!text) {
        state.reviewer.anachRanges = [];
        hoveredAnachronism = null;
        renderHighlights(text);
        return;
    }
    try {
        const hits = await eel.scan_anachronisms(text)();
        state.reviewer.anachRanges = hits || [];
        renderHighlights(text);
    } catch(e) {
        console.error('[scanAnachronisms]', e);
        state.reviewer.anachRanges = [];
        renderHighlights(text);
    }
}

function renderHighlights(text) {
    const ed = document.getElementById('en-editor');
    if (!ed) return;
    
    // Check if we should skip cursor restoration (e.g., after Enter key)
    const shouldSkipRestore = ed._skipCursorRestore && ed._skipCursorRestore();
    
    // Save cursor position
    const selection = window.getSelection();
    const range = selection.rangeCount > 0 ? selection.getRangeAt(0).cloneRange() : null;
    const cursorOffset = (shouldSkipRestore || !range) ? null : getCaretOffset(ed, range);
    
    if (!state.reviewer.anachRanges || state.reviewer.anachRanges.length === 0) {
        ed.innerHTML = escapeHtml(text);
        if (cursorOffset !== null) restoreCursor(ed, cursorOffset);
        return;
    }
    
    // Escape the text first
    let html = escapeHtml(text);
    
    // Then apply highlights using regex with word boundaries
    for (const [word, suggestion, is_ddon] of state.reviewer.anachRanges) {
        // Escape regex special characters in the word
        const escapedWord = word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        const regex = new RegExp(`\\b${escapedWord}\\b`, 'gi');
        html = html.replace(regex, (match) => {
            // Preserve the original case of the matched word
            const originalWord = word;
            const className = is_ddon ? "anach-highlight anach-ddon" : "anach-highlight";
            const starIcon = is_ddon ? ' ★' : '';
            return `<span class="${className}" data-word="${escAttr(originalWord)}" data-suggestion="${escAttr(suggestion)}" data-is-ddon="${is_ddon}">${match}${starIcon}</span>`;
        });
    }
    
    ed.innerHTML = html;
    if (cursorOffset !== null) restoreCursor(ed, cursorOffset);
}

function getCaretOffset(element, range) {
    const preCaretRange = range.cloneRange();
    preCaretRange.selectNodeContents(element);
    preCaretRange.setEnd(range.endContainer, range.endOffset);
    const offset = preCaretRange.toString().length;
    
    // Check if cursor is at the end of the text
    const text = element.innerText || '';
    
    // Only use heuristics if offset is 0 but text exists AND range is at the end of the element
    if (offset === 0 && text.length > 0) {
        // Check if range is at the end of the element
        if (range.endContainer === element && range.endOffset === element.childNodes.length) {
            return text.length;
        }
        // Check if range is at the end of the last text node
        if (range.endContainer.nodeType === Node.TEXT_NODE) {
            const parent = range.endContainer.parentNode;
            if (parent === element.lastChild || parent === element) {
                const nodeLength = range.endContainer.length;
                if (range.endOffset === nodeLength) {
                    return text.length;
                }
            }
        }
    }
    
    return offset;
}

function restoreCursor(element, offset) {
    if (offset === null) return;
    
    const range = document.createRange();
    const selection = window.getSelection();
    
    let currentOffset = 0;
    let found = false;
    
    function traverse(node) {
        if (found) return;
        
        if (node.nodeType === Node.TEXT_NODE) {
            const nodeLength = node.length;
            if (currentOffset + nodeLength >= offset) {
                range.setStart(node, offset - currentOffset);
                range.collapse(true);
                found = true;
            } else {
                currentOffset += nodeLength;
            }
        } else {
            for (let i = 0; i < node.childNodes.length; i++) {
                traverse(node.childNodes[i]);
                if (found) return;
            }
        }
    }
    
    traverse(element);
    
    if (found) {
        selection.removeAllRanges();
        selection.addRange(range);
    }
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function getWordAtPosition(text, position) {
    // Find word at the given character position
    const before = text.substring(0, position);
    const after = text.substring(position);
    
    const beforeWords = before.split(/\b/);
    const afterWords = after.split(/\b/);
    
    if (beforeWords.length > 1) {
        return beforeWords[beforeWords.length - 1];
    }
    return '';
}

function handleMouseMove(e) {
    const ed = document.getElementById('en-editor');
    const tooltip = document.getElementById('anach-tooltip');
    if (!ed) return;
    
    // Check if mouse is over a highlight span
    const target = e.target;
    if (target.classList.contains('anach-highlight')) {
        const word = target.getAttribute('data-word');
        const suggestion = target.getAttribute('data-suggestion');
        hoveredAnachronism = [word, suggestion];
        ed.style.cursor = 'pointer';
        
        // Show tooltip
        if (tooltip && suggestion) {
            let tooltipHtml = `<span class="tooltip-word">${word}</span> <span class="tooltip-arrow">→</span> ${suggestion}`;
            
            // Fetch definition and example for the suggestion (archaic word)
            eel.get_definition(suggestion)().then(result => {
                if (result) {
                    // Handle both tuple format (new) and string format (legacy)
                    let defn, example;
                    if (Array.isArray(result)) {
                        defn = result[0];
                        example = result[1];
                    } else {
                        defn = result;
                        example = "";
                    }
                    if (defn) {
                        tooltipHtml += `<br><span class="tooltip-definition">${defn}</span>`;
                    }
                    if (example) {
                        tooltipHtml += `<br><span class="tooltip-example">"${example}"</span>`;
                    }
                    tooltip.innerHTML = tooltipHtml;
                }
            }).catch(err => {
                console.error('[get_definition]', err);
            });
            
            tooltip.innerHTML = tooltipHtml;
            tooltip.style.display = 'block';
            
            // Position tooltip near cursor
            const rect = ed.getBoundingClientRect();
            const tooltipX = e.clientX - rect.left + 15;
            const tooltipY = e.clientY - rect.top + 20;
            tooltip.style.left = tooltipX + 'px';
            tooltip.style.top = tooltipY + 'px';
        }
        return;
    }
    
    hoveredAnachronism = null;
    ed.style.cursor = 'text';
    
    // Hide tooltip
    if (tooltip) {
        tooltip.style.display = 'none';
    }
}

function getCaretCoordinates(textarea, x, y) {
    // Approximate character position from coordinates
    const text = textarea.value;
    const lineHeight = parseInt(window.getComputedStyle(textarea).lineHeight) || 20;
    const charWidth = parseInt(window.getComputedStyle(textarea).fontSize) || 14;
    
    const line = Math.floor(y / lineHeight);
    const lines = text.split('\n');
    
    if (line >= lines.length) return text.length;
    
    let position = 0;
    for (let i = 0; i < line; i++) {
        position += lines[i].length + 1; // +1 for newline
    }
    
    const charInLine = Math.floor(x / charWidth);
    position += Math.min(charInLine, lines[line].length);
    
    return position;
}

function replaceAnachronism(word, suggestion) {
    if (!suggestion) return;
    
    const ed = document.getElementById('en-editor');
    if (!ed) return;
    
    const text = ed.innerText;
    
    // Strip star icon from text when searching (word may be followed by " ★")
    const textClean = text.replace(/ ★/g, '');
    
    // Replace first occurrence (contenteditable doesn't have selectionStart/End like textarea)
    let idx = textClean.toLowerCase().indexOf(word.toLowerCase());
    if (idx === -1) return;
    
    const before = textClean.substring(0, idx);
    const after = textClean.substring(idx + word.length);
    const matched = textClean.substring(idx, idx + word.length);

    // Preserve capitalization
    let replacement = suggestion;
    const firstAlphaOrig = matched.match(/[a-zA-Z]/);
    const firstAlphaIdx = suggestion.match(/[a-zA-Z]/)?.index;

    if (firstAlphaOrig && firstAlphaOrig[0] === firstAlphaOrig[0].toUpperCase() && firstAlphaIdx !== undefined) {
        replacement = suggestion.substring(0, firstAlphaIdx) + 
                      suggestion[firstAlphaIdx].toUpperCase() + 
                      suggestion.substring(firstAlphaIdx + 1);
    }

    ed.innerText = before + replacement + after;
    updateReviewerCounters();
    syncLineCounters();
    
    // Re-scan for anachronisms after replacement
    scanAnachronisms(ed.innerText);
}

function handleTabKey(e) {
    if (e.key !== 'Tab') return;
    
    const ed = document.getElementById('en-editor');
    if (!ed) return;
    
    // Prioritize hovered anachronism
    if (hoveredAnachronism) {
        const [word, suggestion] = hoveredAnachronism;
        replaceAnachronism(word, suggestion);
        e.preventDefault();
        return;
    }
    
    // For contenteditable, cursor position check is complex - skip for now
    // Tab key only works on hover for contenteditable approach
}

// =============================================================================
// REVIEWER — DEEPL + LORE + ADJACENT
// =============================================================================
async function fetchDeepLSuggestion(text) {
    const el = document.getElementById('deepl-text');
    if (!el || !text) return;
    el.innerText = 'Consulting DeepL…';
    const res = await eel.get_deepl_suggestion(text)();
    el.innerText = res || '—';
    
    // Add click-to-paste functionality
    el.onclick = () => {
        const suggestion = el.innerText.trim();
        if (!suggestion || suggestion === 'Consulting DeepL…' || suggestion === '—') return;
        
        const editor = document.getElementById('en-editor');
        if (!editor) return;
        
        const current = editor.innerText.trim();
        if (current && !confirm('Overwrite current English text with DeepL suggestion?')) return;
        
        editor.innerText = suggestion;
        updateReviewerCounters();
        syncLineCounters();
        
        // Re-scan for anachronisms after DeepL paste
        scanAnachronisms(suggestion);
    };
}

async function populateLoreContext(jpText) {
    const box = document.getElementById('lore-box');
    if (!box) return;
    box.innerHTML = '<em style="opacity:0.5">Loading…</em>';
    try {
        const matches = await eel.get_lore_context(jpText)();
        if (!matches || !matches.length) {
            box.innerHTML = '<em style="opacity:0.5">No references found.</em>';
            return;
        }
        box.innerHTML = '';
        matches.forEach(m => {
            const row = document.createElement('div');
            row.className = 'lore-row';
            if (m.is_lore) {
                // Clickable lore terms — insert into editor on click
                const suggestions = m.en.split(/\s*[,;|\n\/]\s*/).filter(s => s.trim());
                const jpSpan = document.createElement('span');
                jpSpan.className = 'lore-jp';
                jpSpan.innerText = m.jp + ':  ';
                row.appendChild(jpSpan);
                suggestions.forEach((sug, i) => {
                    const a = document.createElement('span');
                    a.className   = 'lore-en';
                    a.innerText   = sug;
                    a.title       = 'Click to insert';
                    a.onclick     = () => insertIntoEditor(sug);
                    row.appendChild(a);
                    if (i < suggestions.length - 1) {
                        row.appendChild(document.createTextNode(' | '));
                    }
                });
            } else {
                // Tag display entry
                row.innerHTML = `<span class="lore-tag">${m.jp}</span> = <span class="lore-tag-val">"${m.en}"</span>`;
            }
            box.appendChild(row);
        });
    } catch(e) {
        box.innerHTML = '<em style="opacity:0.5">Error loading context.</em>';
        console.error('[populateLoreContext]', e);
    }
}

async function populateAdjacentContext(path, rowIdx) {
    const prevEl = document.getElementById('ctx-prev');
    const nextEl = document.getElementById('ctx-next');
    if (!prevEl && !nextEl) return;
    try {
        const ctx = await eel.get_adjacent_context(path, rowIdx)();
        if (prevEl) {
            prevEl.innerHTML = ctx && ctx.prev
                ? `<span class="adj-arrow">▲</span><span class="adj-jp">${escHtml(ctx.prev.jp)}</span><br><span class="adj-en">${escHtml(ctx.prev.en)}</span>`
                : '<span class="adj-arrow">▲</span>—';
        }
        if (nextEl) {
            nextEl.innerHTML = ctx && ctx.next
                ? `<span class="adj-arrow">▼</span><span class="adj-jp">${escHtml(ctx.next.jp)}</span><br><span class="adj-en">${escHtml(ctx.next.en)}</span>`
                : '<span class="adj-arrow">▼</span>—';
        }
    } catch(e) { console.error('[populateAdjacentContext]', e); }
}

function insertIntoEditor(text) {
    const ed = document.getElementById('en-editor');
    if (!ed) return;
    const selection = window.getSelection();
    if (selection.rangeCount > 0) {
        const range = selection.getRangeAt(0);
        range.deleteContents();
        range.insertNode(document.createTextNode(text));
    } else {
        ed.innerText += text;
    }
    ed.focus();
    updateReviewerCounters();
    syncLineCounters();
}

// =============================================================================
// REVIEWER — ROW SIDEBAR
// =============================================================================
function renderRowSidebar() {
    const sidebar = document.getElementById('row-sidebar');
    if (!sidebar) return;
    if (state.reviewer.mode !== 'translate') {
        sidebar.style.display = 'none';
        return;
    }
    sidebar.style.display = 'flex';
    const ul      = document.getElementById('row-list-ul');
    if (!ul) return;
    ul.innerHTML  = '';
    const showAll = document.getElementById('show-translated-rows')?.checked;
    state.reviewer.fullQueue.forEach((item, idx) => {
        if (!showAll && item.en) return;
        const li = document.createElement('li');
        li.innerText = `${item.row}: ${(item.jp || '').slice(0, 40)}`;
        if (item.en) li.classList.add('translated');
        if (state.reviewer.currentIdx === idx) li.classList.add('active');
        li.onclick = () => loadItemAtIdx(idx);
        ul.appendChild(li);
    });
}

// =============================================================================
// AI CHAT
// =============================================================================
function initChatActions() {
    const btn   = document.getElementById('btn-chat-send');
    const input = document.getElementById('chat-input');

    const send = async () => {
        const msg = input ? input.value.trim() : '';
        if (!msg) return;
        appendChatMsg('user', msg);
        if (input) input.value = '';
        state.reviewer.chatHistory.push({ role: 'user', content: msg });

        appendChatMsg('assistant', '⏳ Generating…');
        const resp = await eel.send_ai_chat(msg, state.reviewer.chatHistory)();
        // Replace the spinner with the real response
        const history = document.getElementById('chat-history');
        if (history) {
            const last = history.querySelector('.msg.assistant:last-child');
            if (last) last.innerText = resp || '(empty response)';
        }
        state.reviewer.chatHistory.push({ role: 'assistant', content: resp || '' });
    };

    if (btn)   btn.onclick  = send;
    if (input) input.onkeydown = e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } };
}

function appendChatMsg(role, text) {
    const history = document.getElementById('chat-history');
    if (!history) return;
    const div = document.createElement('div');
    div.className = `msg ${role}`;
    div.innerText = text;
    history.appendChild(div);
    history.scrollTop = history.scrollHeight;
}

// =============================================================================
// SETTINGS — NAVIGATION
// =============================================================================
function initSettingsNav() {
    document.querySelectorAll('.settings-nav-btn').forEach(btn => {
        btn.onclick = () => {
            const sec = btn.getAttribute('data-section');
            document.querySelectorAll('.settings-nav-btn').forEach(b => b.classList.toggle('active', b === btn));
            document.querySelectorAll('.settings-section').forEach(s => s.classList.toggle('active', s.id === `section-${sec}`));
        };
    });
}

async function loadSettings() {
    try {
        const config = await eel.get_full_config()();
        if (!config) return;
        state.settings.lastConfig = config;

        // API Keys
        setVal('opt-deepl-key',    config.deepl_api_key      || '');
        setVal('opt-deepl-lang',   config.deepl_target_lang  || 'EN-US');
        setVal('opt-or-key',       config.openrouter_api_key || '');
        setVal('opt-path-bible',   config.bible_path         || '');
        setVal('opt-path-gloss',   config.glossary_path      || '');
        setVal('opt-path-assets',  config.assets_path        || '');

        // All list sections
        renderSettingsFolders(config.folders   || []);
        renderSettingsTags(config.tag_map || {}, config.tag_display || {});
        renderSettingsPresets(config.presets      || {});
        renderSettingsWall(config.wall_presets    || {});

        // AI Prompts
        setVal('opt-ai-system-prompt', config.ai_system_prompt || '');
        const buttonPrompts = config.ai_button_prompts || {};
        setVal('opt-ai-prompt-translate', buttonPrompts.translate || 'Translate: {text}');
        setVal('opt-ai-prompt-rephrase', buttonPrompts.rephrase || 'Rephrase this: {text}');
        setVal('opt-ai-prompt-archaize', buttonPrompts.archaize || 'Make this more archaic: {text}');
        setVal('opt-ai-prompt-check', buttonPrompts.check || 'Check this for errors: {text}');
        renderSettingsRules(config.replace_rules  || []);
        renderSettingsTriggers(config.triggers    || []);
        renderSettingsArchetypes(config.archetypes || {});
        renderModelSelector(config.openrouter_models || [], config.selected_openrouter_model || 'openrouter/auto');

        // Update state.standardLimit
        const firstPreset = Object.values(config.presets || {Standard: 50})[0];
        state.standardLimit = firstPreset;

    } catch(e) { console.error('[loadSettings]', e); }
}

// =============================================================================
// SETTINGS — ACTIONS (full parity with options_module.py)
// =============================================================================
function initSettingsActions() {

    // --- Path fields: save on blur ---
    const pathFields = [
        ['opt-path-bible',   'bible_path'],
        ['opt-path-gloss',   'glossary_path'],
        ['opt-path-assets',  'assets_path'],
        ['opt-deepl-lang',   'deepl_target_lang'],
    ];
    pathFields.forEach(([id, key]) => {
        const el = document.getElementById(id);
        if (el) el.onblur = async () => { await eel.save_config_field(key, el.value.trim())(); };
    });

    // --- API key fields: save on blur ---
    const keyBlur = (id, key) => {
        const el = document.getElementById(id);
        if (el) el.onblur = async () => { await eel.save_config_field(key, el.value.trim())(); };
    };
    keyBlur('opt-deepl-key', 'deepl_api_key');
    keyBlur('opt-or-key',    'openrouter_api_key');

    // --- AI System Prompt: save on button click ---
    const btnSaveAiSystem = document.getElementById('btn-save-ai-system-prompt');
    if (btnSaveAiSystem) {
        btnSaveAiSystem.onclick = async () => {
            const el = document.getElementById('opt-ai-system-prompt');
            if (el) {
                await eel.save_config_field('ai_system_prompt', el.value)();
                alert('AI System Prompt saved!');
            }
        };
    }

    // --- AI Button Prompts: save on button click ---
    const btnSaveAiButton = document.getElementById('btn-save-ai-button-prompts');
    if (btnSaveAiButton) {
        btnSaveAiButton.onclick = async () => {
            const prompts = {
                translate: document.getElementById('opt-ai-prompt-translate')?.value || 'Translate: {text}',
                rephrase: document.getElementById('opt-ai-prompt-rephrase')?.value || 'Rephrase this: {text}',
                archaize: document.getElementById('opt-ai-prompt-archaize')?.value || 'Make this more archaic: {text}',
                check: document.getElementById('opt-ai-prompt-check')?.value || 'Check this for errors: {text}'
            };
            await eel.save_config_field('ai_button_prompts', prompts)();
            alert('AI Button Prompts saved!');
        };
    }

    // --- Test buttons ---
    const btnTestDeepl = document.getElementById('btn-test-deepl');
    if (btnTestDeepl) btnTestDeepl.onclick = async () => {
        const key = document.getElementById('opt-deepl-key')?.value?.trim();
        if (!key) return alert('Enter a DeepL API key first.');
        btnTestDeepl.innerText = 'Testing…';
        const res = await eel.test_deepl(key)();
        btnTestDeepl.innerText = 'TEST';
        if (res && res.text) alert(`✓ DeepL OK — "${res.text}"`);
        else alert(`✗ DeepL Error: ${res?.error || 'Unknown'}`);
    };

    const btnTestOR = document.getElementById('btn-test-or');
    if (btnTestOR) btnTestOR.onclick = async () => {
        const key = document.getElementById('opt-or-key')?.value?.trim();
        if (!key) return alert('Enter an OpenRouter key first.');
        btnTestOR.innerText = 'Testing…';
        const res = await eel.test_openrouter(key)();
        btnTestOR.innerText = 'TEST';
        if (res && res.text) alert(`✓ OpenRouter OK — "${res.text}"`);
        else alert(`✗ OpenRouter Error: ${res?.error || 'Unknown'}`);
    };

    // --- Refresh models ---
    const btnRefresh = document.getElementById('btn-refresh-models');
    if (btnRefresh) btnRefresh.onclick = async () => {
        const key     = document.getElementById('opt-or-key')?.value?.trim();
        const freeOnly = !document.getElementById('opt-show-paid')?.checked;
        if (!key) return alert('Enter an OpenRouter key first.');
        btnRefresh.innerText = 'Fetching…';
        const models = await eel.fetch_models(key, freeOnly)();
        btnRefresh.innerText = 'REFRESH MODELS';
        if (models && models.length) {
            renderModelSelector(models, models[0]);
            alert(`Updated — found ${models.length} model(s).`);
        } else { alert('No models returned.'); }
    };

    // --- Folders (settings tab) ---
    const btnAddFolder = document.getElementById('btn-add-folder');
    if (btnAddFolder) btnAddFolder.onclick = async () => {
        const val = prompt('Enter folder path:');
        if (val && val.trim()) { await eel.add_list_item('folders', val.trim())(); loadSettings(); }
    };
    const btnDelFolder = document.getElementById('btn-del-folder');
    if (btnDelFolder) btnDelFolder.onclick = async () => {
        const sel = state.settings.selectedFolder;
        if (!sel) return alert('Select a folder first.');
        if (confirm(`Remove "${sel}"?`)) { await eel.remove_list_item('folders', sel)(); loadSettings(); }
    };

    // --- Tags ---
    const btnAddTag = document.getElementById('btn-add-tag');
    if (btnAddTag) btnAddTag.onclick = () => openTagDialog(null);
    const btnDelTag = document.getElementById('btn-del-tag');
    if (btnDelTag) btnDelTag.onclick = async () => {
        const key = state.settings.selectedTag;
        if (!key) return alert('Select a tag first.');
        if (confirm(`Delete tag <${key}>?`)) {
            await eel.delete_map_setting('tag_map', key)();
            loadSettings();
        }
    };

    // Tag search
    const tagSearch = document.getElementById('tag-search');
    if (tagSearch) tagSearch.oninput = () => {
        state.settings.tagSearch = tagSearch.value.toLowerCase();
        if (state.settings.lastConfig)
            renderSettingsTags(state.settings.lastConfig.tag_map || {}, state.settings.lastConfig.tag_display || {});
    };

    // --- Presets ---
    const btnAddLimit = document.getElementById('btn-add-limit');
    if (btnAddLimit) btnAddLimit.onclick = () => {
        const res = prompt('Format: Name:Limit (e.g. Wide:80)');
        if (!res || !res.includes(':')) return;
        const [name, val] = res.split(':');
        const limit = parseInt(val.trim());
        if (isNaN(limit)) return alert('Limit must be a number.');
        eel.update_map_setting('presets', name.trim(), limit)().then(() => loadSettings());
    };
    const btnDelLimit = document.getElementById('btn-del-limit');
    if (btnDelLimit) btnDelLimit.onclick = async () => {
        const key = state.settings.selectedPreset;
        if (!key) return alert('Select a preset first.');
        await eel.delete_map_setting('presets', key)();
        loadSettings();
    };

    // --- Wall presets ---
    const btnAddWall = document.getElementById('btn-add-wall');
    if (btnAddWall) btnAddWall.onclick = () => {
        const res = prompt('Format: Name:MaxLines (e.g. Standard:7)');
        if (!res || !res.includes(':')) return;
        const [name, val] = res.split(':');
        const lines = parseInt(val.trim());
        if (isNaN(lines)) return alert('Max lines must be a whole number.');
        eel.update_map_setting('wall_presets', name.trim(), lines)().then(() => loadSettings());
    };
    const btnDelWall = document.getElementById('btn-del-wall');
    if (btnDelWall) btnDelWall.onclick = async () => {
        const key = state.settings.selectedWall;
        if (!key) return alert('Select a wall preset first.');
        await eel.delete_map_setting('wall_presets', key)();
        loadSettings();
    };

    // --- Rules ---
    const btnAddRule = document.getElementById('btn-add-rule');
    if (btnAddRule) btnAddRule.onclick = () => openRuleModal(-1, null);
    const btnDelRule = document.getElementById('btn-del-rule');
    if (btnDelRule) btnDelRule.onclick = async () => {
        const idx = state.settings.selectedRule;
        if (idx === null || idx < 0) return alert('Select a rule first.');
        const rules = (state.settings.lastConfig?.replace_rules || []);
        if (confirm(`Delete rule "${rules[idx]?.find || ''}"?`)) {
            rules.splice(idx, 1);
            await eel.save_replace_rules(rules)();
            state.settings.selectedRule = null;
            loadSettings();
        }
    };

    // --- Triggers ---
    const btnAddTrig = document.getElementById('btn-add-trigger');
    if (btnAddTrig) btnAddTrig.onclick = async () => {
        const val = prompt('Add trigger keyword:');
        if (val && val.trim()) { await eel.add_list_item('triggers', val.trim())(); loadSettings(); }
    };
    const btnDelTrig = document.getElementById('btn-del-trigger');
    if (btnDelTrig) btnDelTrig.onclick = async () => {
        const sel = state.settings.selectedTrigger;
        if (!sel) return alert('Select a trigger first.');
        await eel.remove_list_item('triggers', sel)();
        loadSettings();
    };

    // --- Archetypes ---
    const btnAddArch = document.getElementById('btn-add-archetype');
    if (btnAddArch) btnAddArch.onclick = () => openArchetypeModal(null, null);
    const btnResetArch = document.getElementById('btn-reset-archetypes');
    if (btnResetArch) btnResetArch.onclick = async () => {
        if (!confirm('Replace all archetypes with built-in defaults? Custom archetypes will be lost.')) return;
        const res = await eel.reset_archetypes_to_defaults()();
        if (res && !res.error) { alert('Archetypes reset to defaults.'); loadSettings(); }
        else alert(`Error: ${res?.error || 'Unknown'}`);
    };

    // --- Regex sandbox (live) ---
    const runSandbox = async () => {
        const pattern = document.getElementById('regex-pattern')?.value || '';
        const repl    = document.getElementById('regex-replace')?.value || '';
        const input   = document.getElementById('regex-input')?.value   || '';
        const out     = document.getElementById('regex-output');
        if (!out) return;
        const res = await eel.test_regex(pattern, repl, input)();
        out.innerText = res.error ? `ERROR: ${res.error}` : (res.text ?? '');
    };
    ['regex-pattern', 'regex-replace', 'regex-input'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.addEventListener('input', runSandbox);
    });
}

// =============================================================================
// SETTINGS — RENDER HELPERS
// =============================================================================

function renderSettingsFolders(folders) {
    const list = document.getElementById('folder-list');
    if (!list) return;
    list.innerHTML = '';
    folders.forEach(f => {
        const li = document.createElement('li');
        li.innerText = f;
        li.onclick = () => {
            list.querySelectorAll('li').forEach(el => el.classList.remove('selected'));
            li.classList.add('selected');
            state.settings.selectedFolder = f;
        };
        list.appendChild(li);
    });
}

function renderSettingsTags(tagMap, tagDisplay) {
    const list = document.getElementById('tag-list');
    if (!list) return;
    list.innerHTML = '';
    const query = state.settings.tagSearch || '';
    Object.entries(tagMap).forEach(([tag, len]) => {
        if (query && !tag.toLowerCase().includes(query) &&
            !(tagDisplay[tag] || '').toLowerCase().includes(query)) return;
        const display = tagDisplay[tag] ? ` (${tagDisplay[tag]})` : '';
        const li = document.createElement('li');
        li.innerHTML = `<span><strong>${escHtml(tag)}</strong>${escHtml(display)} : ${len} chars</span>
                        <button class="btn-secondary sm tag-edit-btn" data-tag="${escAttr(tag)}">EDIT</button>`;
        li.querySelector('.tag-edit-btn').onclick = (e) => { e.stopPropagation(); openTagDialog(tag); };
        li.onclick = () => {
            list.querySelectorAll('li').forEach(el => el.classList.remove('selected'));
            li.classList.add('selected');
            state.settings.selectedTag = tag;
        };
        list.appendChild(li);
    });
}

function renderSettingsPresets(presets) {
    const list = document.getElementById('limit-list');
    if (!list) return;
    list.innerHTML = '';
    Object.entries(presets).forEach(([name, val]) => {
        const li = buildSelectableLi(`${name} : ${val} chars`, () => { state.settings.selectedPreset = name; }, list);
        list.appendChild(li);
    });
}

function renderSettingsWall(wall) {
    const list = document.getElementById('wall-list');
    if (!list) return;
    list.innerHTML = '';
    Object.entries(wall).forEach(([name, val]) => {
        const li = buildSelectableLi(`${name} : ${val} lines`, () => { state.settings.selectedWall = name; }, list);
        list.appendChild(li);
    });
}

function renderSettingsRules(rules) {
    const list = document.getElementById('rule-list');
    if (!list) return;
    list.innerHTML = '';
    rules.forEach((rule, idx) => {
        const flags = [
            rule.case_sensitive ? 'CASE' : '',
            rule.whole_word     ? 'WORD' : '',
            rule.speakers?.length ? `SPK:${rule.speakers.join(',')}` : '',
            rule.entry_types?.length ? `TYPE:${rule.entry_types.join(',')}` : '',
        ].filter(Boolean).join(' ');
        const li = document.createElement('li');
        li.className = 'rule-item';
        li.innerHTML = `
            <div class="rule-find">${escHtml(rule.find || '')} → ${escHtml(rule.replace ?? '')}</div>
            <div class="rule-flags">${escHtml(flags)}</div>
            <button class="btn-secondary sm" data-idx="${idx}">EDIT</button>`;
        li.querySelector('button').onclick = (e) => { e.stopPropagation(); openRuleModal(idx, rule); };
        li.onclick = () => {
            list.querySelectorAll('li').forEach(el => el.classList.remove('selected'));
            li.classList.add('selected');
            state.settings.selectedRule = idx;
        };
        list.appendChild(li);
    });
}

function renderSettingsTriggers(triggers) {
    const list = document.getElementById('trigger-list');
    if (!list) return;
    list.innerHTML = '';
    triggers.forEach(t => {
        const li = buildSelectableLi(t, () => { state.settings.selectedTrigger = t; }, list);
        list.appendChild(li);
    });
}

function renderSettingsArchetypes(archetypes) {
    const grid = document.getElementById('archetype-grid');
    if (!grid) return;
    grid.innerHTML = '';
    Object.entries(archetypes).sort(([a],[b]) => a.localeCompare(b)).forEach(([key, data]) => {
        const row = document.createElement('div');
        row.className = 'archetype-row';
        row.innerHTML = `
            <div class="arch-key">${escHtml(key)}</div>
            <div class="arch-name">${escHtml(data.name || '')}</div>
            <div class="arch-notes">${escHtml((data.notes || '').slice(0, 80))}${(data.notes||'').length > 80 ? '…' : ''}</div>
            <button class="btn-secondary sm arch-edit" data-key="${escAttr(key)}">EDIT</button>
            <button class="btn-secondary sm arch-del"  data-key="${escAttr(key)}">DEL</button>`;
        row.querySelector('.arch-edit').onclick = () => openArchetypeModal(key, data);
        row.querySelector('.arch-del').onclick  = async () => {
            if (confirm(`Delete archetype "${key}"?`)) {
                await eel.delete_archetype(key)();
                loadSettings();
            }
        };
        grid.appendChild(row);
    });
}

function renderModelSelector(models, selected) {
    // Inject or update a <select> after the refresh button
    let sel = document.getElementById('or-model-select');
    if (!sel) {
        const anchor = document.getElementById('btn-refresh-models');
        if (!anchor) return;
        sel = document.createElement('select');
        sel.id = 'or-model-select';
        sel.className = 'settings-select';
        sel.style.marginTop = '10px';
        sel.style.width = '100%';
        anchor.parentElement.appendChild(sel);
        sel.onchange = async () => {
            await eel.save_config_field('selected_openrouter_model', sel.value)();
        };
    }
    sel.innerHTML = '';
    (models.length ? models : ['openrouter/auto']).forEach(m => {
        const opt = document.createElement('option');
        opt.value = opt.innerText = m;
        if (m === selected) opt.selected = true;
        sel.appendChild(opt);
    });
}

// Helper: build a selectable <li> with single-selection tracking
function buildSelectableLi(text, onSelect, list) {
    const li = document.createElement('li');
    li.innerText = text;
    li.onclick = () => {
        list.querySelectorAll('li').forEach(el => el.classList.remove('selected'));
        li.classList.add('selected');
        if (onSelect) onSelect();
    };
    return li;
}

// =============================================================================
// MODALS
// =============================================================================
function initModals() {
    // Rule modal
    document.getElementById('btn-rule-cancel')?.addEventListener('click',
        () => document.getElementById('modal-rule').classList.remove('active'));
    document.getElementById('btn-rule-save')?.addEventListener('click', saveRule);

    // Archetype modal
    document.getElementById('btn-arch-cancel')?.addEventListener('click',
        () => document.getElementById('modal-archetype').classList.remove('active'));
    document.getElementById('btn-arch-save')?.addEventListener('click', saveArchetype);

    // Close on backdrop click
    document.querySelectorAll('.modal').forEach(function(modal) {
        modal.addEventListener('click', function(e) {
            if (e.target === modal) {
                modal.classList.remove('active');
            }
        });
    });
}

function openRuleModal(idx, rule) {
    state.settings.editingRuleIdx = idx;
    setVal('rule-find',     rule?.find     ?? '');
    setVal('rule-replace',  rule?.replace  ?? '');
    setVal('rule-speakers', (rule?.speakers || []).join(', '));
    setVal('rule-types',    (rule?.entry_types || []).join(', '));
    setCheck('rule-case',   rule?.case_sensitive || false);
    setCheck('rule-word',   rule?.whole_word     || false);
    document.getElementById('modal-rule').classList.add('active');
    document.getElementById('rule-find')?.focus();
}

async function saveRule() {
    const find    = document.getElementById('rule-find')?.value?.trim();
    if (!find) return alert('Find pattern is required.');

    const rule = {
        find,
        replace:        document.getElementById('rule-replace')?.value ?? '',
        case_sensitive: document.getElementById('rule-case')?.checked  || false,
        whole_word:     document.getElementById('rule-word')?.checked  || false,
        speakers:       parseCSVField('rule-speakers'),
        entry_types:    parseCSVField('rule-types'),
    };

    const rules = [...(state.settings.lastConfig?.replace_rules || [])];
    const idx   = state.settings.editingRuleIdx;
    if (idx >= 0 && idx < rules.length) {
        rules[idx] = rule;
    } else {
        rules.push(rule);
    }
    await eel.save_replace_rules(rules)();
    document.getElementById('modal-rule').classList.remove('active');
    state.settings.editingRuleIdx = -1;
    loadSettings();
}

function openArchetypeModal(key, data) {
    state.settings.editingArchKey = key;
    setVal('arch-key',         key          ?? '');
    setVal('arch-name',        data?.name   ?? '');
    setVal('arch-professions', (data?.professions || []).join(', '));
    setVal('arch-pawn-map',    data?.pawn_map ?? '');
    setVal('arch-notes',       data?.notes  ?? '');
    document.getElementById('modal-archetype').classList.add('active');
    document.getElementById('arch-key')?.focus();
}

async function saveArchetype() {
    const key   = document.getElementById('arch-key')?.value?.trim();
    const name  = document.getElementById('arch-name')?.value?.trim();
    if (!key || !name) return alert('Key and Name are required.');
    const profs = parseCSVField('arch-professions');
    const pawn  = document.getElementById('arch-pawn-map')?.value?.trim() ?? '';
    const notes = document.getElementById('arch-notes')?.value?.trim()    ?? '';

    // If key was renamed, delete the old key first
    const oldKey = state.settings.editingArchKey;
    if (oldKey && oldKey !== key) await eel.delete_archetype(oldKey)();

    await eel.save_archetype(key, name, notes)();
    // Also persist professions and pawn_map via update_map_setting
    if (profs.length) await eel.update_map_setting('archetypes', key,
        { name, professions: profs, pawn_map: pawn, notes })();

    document.getElementById('modal-archetype').classList.remove('active');
    state.settings.editingArchKey = null;
    loadSettings();
}

// =============================================================================
// TAG DIALOG (inline prompt, like Tkinter's simpledialog)
// =============================================================================
async function openTagDialog(existingKey) {
    const prompt_str = existingKey
        ? `Editing tag: ${existingKey}\nFormat:  TagName : Display Text  (e.g.  PLAYER_NAME : Arisen)\nOr:  TagName : 12  (manual char count)`
        : 'Format:  TagName : Display Text  (e.g.  PLAYER_NAME : Arisen)\nOr:  TagName : 12  (manual char count)';
    const res = prompt(prompt_str, existingKey ? `${existingKey} : ` : '');
    if (!res || !res.includes(':')) return;
    const [tagRaw, valueRaw] = res.split(':', 2);
    const tag   = tagRaw.trim();
    const value = valueRaw.trim();
    if (!tag) return;
    await eel.update_map_setting('tag_map', tag, value)();
    loadSettings();
}

// =============================================================================
// SEARCH
// =============================================================================
function initSearchActions() {
    const btnSearch  = document.getElementById('btn-db-search');
    const btnOpenAll = document.getElementById('btn-search-open-all');
    const searchInput = document.getElementById('db-search-input');

    if (btnSearch) btnSearch.onclick = doSearch;
    if (searchInput) searchInput.onkeydown = e => { if (e.key === 'Enter') doSearch(); };

    if (btnOpenAll) btnOpenAll.onclick = async () => {
        if (!state.search.results.length) return;
        const items = state.search.results.map(r => ({
            speaker: 'Unknown', jp: r.match, en: r.en,
            category: 'SEARCH_RESULT', path: r.path, row: r.row,
        }));
        await eel.bulk_inject(items)();
        state.reviewer.mode = 'translate';
        // Re-fetch full queue from Python (bulk_inject updated it server-side)
        state.reviewer.fullQueue = await eel.get_all_items_in_queue()() || [];
        switchTab('reviewer');
    };

    // Field selector — wire search-on-enter on the select too
    const fieldSel = document.getElementById('db-search-field');
    if (fieldSel) {
        fieldSel.onkeydown = e => { if (e.key === 'Enter') doSearch(); };
    }
}

async function doSearch() {
    const query = document.getElementById('db-search-input')?.value?.trim();
    const field = document.getElementById('db-search-field')?.value;
    const statusEl = document.getElementById('search-status');

    if (!query) return;
    if (statusEl) statusEl.innerText = 'Searching…';

    let fieldCol = null;
    if (field === 'custom') {
        fieldCol = state.search.customFieldIndex ? parseInt(state.search.customFieldIndex) : null;
        if (isNaN(fieldCol)) {
            if (statusEl) statusEl.innerText = 'Please enter a valid column number.';
            return;
        }
    } else if (field !== 'all') {
        fieldCol = parseInt(field);
    }

    const results  = await eel.perform_search(query, fieldCol)();
    state.search.results = results || [];
    renderSearchResults(state.search.results);
    if (statusEl) {
        const n = state.search.results.length;
        statusEl.innerText = `Found ${n} result${n !== 1 ? 's' : ''}.`;
    }
}

function renderSearchResults(results) {
    const body    = document.getElementById('search-results-body');
    const bulkBox = document.getElementById('search-bulk-box');
    if (!body) return;
    body.innerHTML = '';
    results.forEach((res, idx) => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>${escHtml(res.file)}</td>
            <td>${res.row}</td>
            <td>col ${res.col}</td>
            <td>${escHtml((res.match || '').replace(/\n/g, ' '))}</td>
            <td>${escHtml((res.en   || '').replace(/\n/g, ' '))}</td>`;
        tr.style.cursor = 'pointer';
        tr.onclick = () => openSearchHitInReviewer(res, idx);
        body.appendChild(tr);
    });
    if (bulkBox) bulkBox.style.display = results.length > 0 ? 'block' : 'none';
}

async function openSearchHitInReviewer(res) {
    const item = {
        speaker: 'Unknown', jp: res.jp || res.match, en: res.en,
        category: 'SEARCH_RESULT', path: res.path, row: res.row,
    };
    await eel.bulk_inject([item])();
    state.reviewer.mode     = 'translate';
    state.reviewer.fullQueue = await eel.get_all_items_in_queue()() || [];
    switchTab('reviewer');
    loadItemAtIdx(0);
}

// =============================================================================
// KEYBOARD SHORTCUTS
// =============================================================================
function initShortcuts() {
    window.addEventListener('keydown', e => {
        if (state.currentTab !== 'reviewer') return;
        if (e.ctrlKey) {
            if (e.key === 'Enter') { e.preventDefault(); applyFix(); }
            if (e.key === 'ArrowRight') { e.preventDefault(); nextItem(); }
            if (e.key === 'ArrowLeft')  { e.preventDefault(); prevItem(); }
            if (e.key === 'r' || e.key === 'R') { e.preventDefault(); rewrapEditor(); }
            if (e.key === 'd' || e.key === 'D') {
                e.preventDefault();
                replaceDashes(e.shiftKey ? '...' : '—');
            }
        }
    });
}

// =============================================================================
// UTILITY
// =============================================================================
function setVal(id, val) {
    const el = document.getElementById(id);
    if (el) el.value = val;
}
function setCheck(id, val) {
    const el = document.getElementById(id);
    if (el) el.checked = val;
}
function parseCSVField(id) {
    const v = document.getElementById(id)?.value || '';
    return v.split(',').map(s => s.trim()).filter(Boolean);
}
function escHtml(s) {
    return String(s || '')
        .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
        .replace(/"/g,'&quot;');
}
function escAttr(s) {
    return escHtml(s);
}
