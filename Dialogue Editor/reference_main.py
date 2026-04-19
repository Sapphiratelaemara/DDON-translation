/**
 * Dialogue Editor | Core App Controller
 * Full Feature Parity with Tkinter build
 */

// =============================================================================
// STATE
// =============================================================================
let state = loadState();

function loadState() {
    const saved = localStorage.getItem('dialogueEditorState');
    const defaults = {
        currentTab: 'dashboard',
        reviewer: {
            currentIdx: 0,
            mode: 'translate',
            lastFolder: '',
            fullQueue: null,  // Will be fetched from backend when needed
            showTranslated: false,
            anachRanges: [],         // Track anachronism ranges for Tab replacement
        },
        search: {
            results: [],
            sentToEditor: [],
        },
    };
    if (!saved) return defaults;
    try {
        return { ...defaults, ...JSON.parse(saved) };
    } catch {
        return defaults;
    }
}

function saveState() {
    const showTranslated = document.getElementById('show-translated-rows')?.checked || false;
    const toSave = {
        currentTab: state.currentTab,
        reviewer: {
            currentIdx: state.reviewer.currentIdx,
            mode: state.reviewer.mode,
            lastFolder: state.reviewer.lastFolder,
            // Don't save fullQueue - it should always be fetched from backend to avoid stale data
            showTranslated: showTranslated,
        },
        search: state.search,
    };
    localStorage.setItem('dialogueEditorState', JSON.stringify(toSave));
}

let originalState = {
    currentTab: 'dashboard',
    reviewer: {
        currentItem: null,
        fullQueue: [],
        currentIdx: 0,
        chatHistory: [],
        mode: 'review',   // 'review' | 'translate'
    },
    settings: {
        tagSearch: '',
        lastConfig: null,
        selectedTag: null,
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
    maxLines: 5,           // max lines allowed in translation box
};

// =============================================================================
// INIT
// =============================================================================
window.onload = async () => {
    try {
        // Initialize theme
        const themeColors = await eel.get_theme_colors()();
        applyTheme(themeColors);
        updateThemeIcon(themeColors);

        // Initialize state
        state.standardLimit = await eel.get_standard_limit()();
        state.maxLines = 5; // Default value

        // Load config early for tag highlighting
        const config = await eel.get_full_config()();
        if (config) {
            if (!state.settings) state.settings = {};
            state.settings.lastConfig = config;
        }

        // Initialize UI
        initTabs();
        initSettingsNav();
        initSettingsActions();
        initReviewerActions();
        initDashboardActions();
        initSearchActions();
        initChatActions();
        initModals();
        initShortcuts();
        initPreviewActions();
        
        // Load initial data
        await loadDashboard();
        await loadSettings();
        
        // Restore show translated toggle
        const showTranslatedToggle = document.getElementById('show-translated-rows');
        if (showTranslatedToggle && state.reviewer.showTranslated !== undefined) {
            showTranslatedToggle.checked = state.reviewer.showTranslated;
        }
        // Restore search results if they exist
        if (state.search.results && state.search.results.length > 0) {
            renderSearchResults(state.search.results);
            const statusEl = document.getElementById('search-status');
            if (statusEl) {
                const n = state.search.results.length;
                statusEl.innerText = `Found ${n} result${n !== 1 ? 's' : ''} (restored).`;
            }
        }
        // Restore search results sent to editor if they exist
        if (state.search.sentToEditor && state.search.sentToEditor.length > 0) {
            await eel.clear_queue()();
            const items = state.search.sentToEditor.map(r => ({
                speaker: r.speaker || 'Unknown', jp: r.jp, en: r.en,
                category: r.category || 'SEARCH_RESULT', path: r.path, row: r.row,
            }));
            await eel.bulk_inject(items)();
            state.reviewer.fullQueue = await eel.get_all_items_in_queue()() || [];
            console.log(`[INIT] Restored ${items.length} search results to editor queue.`);
        }
        if (state.currentTab && state.currentTab !== 'dashboard') {
            switchTab(state.currentTab);
        }
        // Save state on exit
        window.addEventListener('beforeunload', saveState);
    } catch (e) {
        console.error('[INIT] Error:', e);
    }
};

async function initAIModels() {
    try {
        const config = await eel.get_full_config()();
        const models = config.openrouter_models || [];
        const selected = config.selected_openrouter_model || 'openrouter/auto';
        const reviewerSel = document.getElementById('ai-model-select');
        if (reviewerSel) {
            reviewerSel.innerHTML = '';
            // Use saved models or fallback
            const modelList = models.length ? models : ['openrouter/auto'];
            modelList.forEach(m => {
                const opt = document.createElement('option');
                opt.value = opt.innerText = m;
                if (m === selected) opt.selected = true;
                reviewerSel.appendChild(opt);
            });
            reviewerSel.onchange = async () => {
                await eel.save_config_field('selected_openrouter_model', reviewerSel.value)();
            };
        }
    } catch (e) { console.error('[initAIModels]', e); }
}

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
    const bar = document.getElementById('main-progress');
    const text = document.getElementById('progress-text');
    if (bar) bar.style.width = `${pct}%`;
    if (text) text.innerText = `${Math.round(pct)}%`;
}

async function pollBatchScanCompletion() {
    console.log('[pollBatchScanCompletion] Starting polling...');
    let pollCount = 0;
    const pollInterval = setInterval(async () => {
        pollCount++;
        console.log(`[pollBatchScanCompletion] Poll #${pollCount}`);
        const isComplete = await eel.is_batch_scan_complete()();
        console.log(`[pollBatchScanCompletion] isComplete: ${isComplete}`);
        if (isComplete) {
            clearInterval(pollInterval);
            console.log('[pollBatchScanCompletion] Scan complete, loading queue structure...');
            log_to_js('[SYSTEM] Scan complete. Loading results...');
            // Load queue structure
            const queueStructure = await eel.get_queue_structure()();
            console.log('[pollBatchScanCompletion] Queue structure:', queueStructure);
            state.reviewer.queueStructure = queueStructure;
            // Select first category with items, preferring batch categories over Manual Translation
            let firstCategory = null;
            // First check batch categories for items
            for (const [displayName, data] of Object.entries(queueStructure)) {
                if (displayName !== "Manual Translation" && data.count > 0) {
                    firstCategory = displayName;
                    break;
                }
            }
            // If no batch categories have items, use Manual Translation
            if (!firstCategory && queueStructure["Manual Translation"] && queueStructure["Manual Translation"].count > 0) {
                firstCategory = "Manual Translation";
            }
            console.log('[pollBatchScanCompletion] First category:', firstCategory);
            // Set current category before populating selector
            state.reviewer.currentCategory = firstCategory || null;
            // Populate category selector
            populateCategorySelector(queueStructure);
            // Show modal to switch to Review Editor
            if (firstCategory) {
                const itemCount = queueStructure[firstCategory].count;
                console.log('[pollBatchScanCompletion] Found', itemCount, 'items in category:', firstCategory);
                openConfirmModal('SCAN COMPLETE', `Found ${itemCount} items. Switch to Review Editor?`, (confirmed) => {
                    if (confirmed) {
                        state.reviewer.mode = 'review';
                        switchTab('reviewer');
                    }
                });
            } else {
                openInputModal('SCAN COMPLETE', 'No issues found.', '', (val) => {});
            }
        }
    }, 500); // Poll every 500ms
}

function populateCategorySelector(queueStructure) {
    const select = document.getElementById('category-select');
    console.log('[populateCategorySelector] select element:', select);
    if (!select) return;
    select.innerHTML = '<option value="">Select category...</option>';
    console.log('[populateCategorySelector] Queue structure:', queueStructure);
    // Always show Manual Translation first
    if (queueStructure["Manual Translation"]) {
        const option = document.createElement('option');
        option.value = "Manual Translation";
        const count = queueStructure["Manual Translation"].count;
        option.innerText = count > 0 ? `Manual Translation (${count})` : "Manual Translation";
        select.appendChild(option);
        console.log('[populateCategorySelector] Added Manual Translation option');
    }
    // Then show batch categories
    for (const [displayName, data] of Object.entries(queueStructure)) {
        if (displayName !== "Manual Translation" && data.count > 0) {
            const option = document.createElement('option');
            option.value = displayName;
            option.innerText = `${displayName} (${data.count})`;
            select.appendChild(option);
            console.log('[populateCategorySelector] Added option:', displayName);
        }
    }
    // Set current selection
    if (state.reviewer.currentCategory) {
        select.value = state.reviewer.currentCategory;
        console.log('[populateCategorySelector] Set current category to:', state.reviewer.currentCategory);
    }
    console.log('[populateCategorySelector] Final select value:', select.value);
}

async function switchCategory(categoryDisplayName) {
    console.log('[switchCategory] Switching to category:', categoryDisplayName);
    if (!categoryDisplayName) return;
    state.reviewer.currentCategory = categoryDisplayName;
    
    // Set mode to review to use the loaded fullQueue instead of fetching from backend
    state.reviewer.mode = 'review';
    
    // Clear load queue to prevent stale data from previous category loads
    loadQueue = [];
    isProcessingQueue = false;
    
    // Wait a bit to ensure any pending load operations complete
    await new Promise(resolve => setTimeout(resolve, 50));
    
    // Clear both caches to prevent stale cache hits when switching categories
    await eel.clear_prefetch_cache()();
    await eel.clear_gloss_cache()();
    console.log('[switchCategory] Caches cleared');
    
    // Manual Translation uses get_all_items_in_queue, other categories use get_items_for_category
    if (categoryDisplayName === "Manual Translation") {
        console.log('[switchCategory] Loading manual translation items');
        state.reviewer.fullQueue = await eel.get_all_items_in_queue()();
        console.log('[switchCategory] Loaded manual translation items, count:', state.reviewer.fullQueue.length);
    } else {
        console.log('[switchCategory] Loading category items for:', categoryDisplayName);
        state.reviewer.fullQueue = await eel.get_items_for_category(categoryDisplayName)();
        console.log('[switchCategory] Loaded category items, count:', state.reviewer.fullQueue.length);
        console.log('[switchCategory] First item in queue:', state.reviewer.fullQueue[0]);
    }
    
    state.reviewer.currentIdx = 0;
    state.reviewer.currentItem = null;
    renderRowSidebar();
    console.log('[switchCategory] About to load item at idx 0, queue length:', state.reviewer.fullQueue.length);
    console.log('[switchCategory] Item at idx 0:', state.reviewer.fullQueue[0]);
    await loadItemAtIdx(0);
}

// =============================================================================
// THEME SYSTEM
// =============================================================================
function applyTheme(colors) {
    const root = document.documentElement;
    Object.entries(colors).forEach(([key, value]) => {
        root.style.setProperty(`--color-${key}`, value);
    });
}

function updateThemeIcon(colors) {
    const icon = document.querySelector('.theme-icon');
    if (icon) {
        const isDark = colors.bg === '#1a1a2e';
        icon.textContent = isDark ? 'light_mode' : 'dark_mode';
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
    saveState();
    
    // Show/hide panel toggles - only in reviewer
    const panelToggles = document.querySelector('.panel-toggles');
    if (panelToggles) {
        panelToggles.classList.toggle('hidden', tabId !== 'reviewer');
    }
    
    if (tabId === 'reviewer') {
        // Clear both caches to prevent stale cache hits when switching to reviewer tab
        Promise.all([
            eel.clear_prefetch_cache()(),
            eel.clear_gloss_cache()
        ]).then(() => {
            console.log('[switchTab] Caches cleared');
            
            // Refresh limits from backend to ensure current preset values
            Promise.all([
                eel.get_standard_limit()(),
                eel.get_wall_limit()()
            ]).then(([standardLimit, wallLimit]) => {
                state.standardLimit = standardLimit;
                state.maxLines = wallLimit;
                updateReviewerCounters();
                
                // If we have a category selected, fetch items for that category
                if (state.reviewer.currentCategory) {
                    console.log('[switchTab] Fetching items for category:', state.reviewer.currentCategory);
                    // Manual Translation uses get_all_items_in_queue, other categories use get_items_for_category
                    if (state.reviewer.currentCategory === "Manual Translation") {
                        eel.get_all_items_in_queue()().then(items => {
                            console.log('[switchTab] Got manual translation items, count:', items.length);
                            state.reviewer.fullQueue = items || [];
                            state.reviewer.currentIdx = 0;
                            state.reviewer.currentItem = null;
                            renderRowSidebar();
                            loadItemAtIdx(0);
                        });
                    } else {
                        eel.get_items_for_category(state.reviewer.currentCategory)().then(items => {
                            console.log('[switchTab] Got items for category:', state.reviewer.currentCategory, 'count:', items.length);
                            state.reviewer.fullQueue = items || [];
                            state.reviewer.currentIdx = 0;
                            state.reviewer.currentItem = null;
                            renderRowSidebar();
                            loadItemAtIdx(0);
                        });
                    }
                } else {
                    // No category selected - fetch all items (for restored search results or manual mode)
                    console.log('[switchTab] No category selected, fetching all items');
                    eel.get_all_items_in_queue()().then(items => {
                        console.log('[switchTab] Got all items, count:', items.length);
                        state.reviewer.fullQueue = items || [];
                        if (state.reviewer.currentIdx >= state.reviewer.fullQueue.length) {
                            state.reviewer.currentIdx = 0;
                        }
                        renderRowSidebar();
                        if (!state.reviewer.currentItem && state.reviewer.fullQueue.length > 0) {
                            loadItemAtIdx(state.reviewer.currentIdx);
                        }
                    });
                }
            });
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
        const pChar = document.getElementById('dash-preset-char')?.value || 'Standard';
        const pWall = document.getElementById('dash-preset-wall')?.value || 'Standard';

        log_to_js('\n[SYSTEM] Initialising scan…');
        update_progress(0);
        await eel.start_batch_scan(pChar, pWall)();
        
        // Start polling for completion
        pollBatchScanCompletion();

        // Update local limits reference based on new selection
        state.standardLimit = await eel.get_standard_limit()();
    };

    // NEW: Translate CSV bind
    const btnTranslate = document.getElementById('btn-translate-csv');
    if (btnTranslate) btnTranslate.onclick = async () => {
        btnTranslate.innerText = 'LOADING...';
        // Clear previous queue first
        await eel.clear_queue()();
        const res = await eel.load_csv_for_translation()();
        btnTranslate.innerText = '✏ TRANSLATE CSV';

        if (res && res.error) {
            openAlertModal('ERROR', `Error loading CSV: ${res.error}`);
        } else if (res > 0) {
            log_to_js(`[SYSTEM] Loaded CSV with ${res} translatable lines.`);
            state.standardLimit = await eel.get_standard_limit()();
            state.reviewer.mode = 'translate';
            // Fetch the queue from Python before switching tabs
            state.reviewer.fullQueue = await eel.get_all_items_in_queue()() || [];
            state.reviewer.currentItem = null;
            state.reviewer.currentIdx = 0;
            saveState();
            switchTab('reviewer');
        } else if (res === 0) {
            openAlertModal('INFO', 'No translatable lines found in selected CSV.');
        }
    };

    const btnCalc = document.getElementById('btn-calc-progress');
    if (btnCalc) btnCalc.onclick = async () => {
        btnCalc.innerText = 'CALCULATING…';
        btnCalc.disabled = true;
        try {
            const res = await eel.calculate_project_stats()();
            document.getElementById('stat-total-lines').innerText = res.total ?? '--';
            document.getElementById('stat-percent').innerText = `${res.percent ?? 0}%`;
        } finally {
            btnCalc.innerText = 'CALCULATE';
            btnCalc.disabled = false;
        }
    };

    // Theme toggle functionality
    const btnTheme = document.getElementById('btn-theme-toggle');
    if (btnTheme) btnTheme.onclick = async () => {
        const themeColors = await eel.toggle_dark_mode()();
        applyTheme(themeColors);
        updateThemeIcon(themeColors);
    };
    
    // Settings button
    const btnSettings = document.getElementById('btn-settings');
    if (btnSettings) btnSettings.onclick = () => switchTab('settings');

    // Panel toggle functionality - only in reviewer
    const btnToggleRefs = document.getElementById('btn-toggle-refs');
    const btnToggleAi = document.getElementById('btn-toggle-ai');
    const sidebarRight = document.querySelector('.kl-sidebar-right');
    const aiPanel = document.querySelector('.kl-panel.kl-flex-1'); // AI Assistant panel
    const panelToggles = document.querySelector('.panel-toggles');
    const footer = document.querySelector('.kl-footer');
    
    const mainWorkspace = document.querySelector('.kl-main-workspace');
    
    function updateRightSidebarState() {
        if (!sidebarRight) return;
        // Check if any non-AI panels are visible (regardless of kl-flex-1)
        const allPanels = sidebarRight.querySelectorAll('.kl-panel');
        const anyContextVisible = Array.from(allPanels).some(p => p !== aiPanel && !p.classList.contains('collapsed'));
        // Check if AI panel is visible
        const aiVisible = !aiPanel?.classList.contains('collapsed');
        // Right sidebar collapsed if no panels visible
        const rightCollapsed = !anyContextVisible && !aiVisible;
        // Update footer
        footer?.classList.toggle('with-right-collapsed', rightCollapsed);
        // Update main workspace margin
        mainWorkspace?.classList.toggle('no-right-sidebar', rightCollapsed);
        // Update right sidebar collapse state
        sidebarRight.classList.toggle('collapsed', rightCollapsed);
    }
    
    // Initialize: panels visible = buttons active
    if (btnToggleRefs) btnToggleRefs.classList.add('active');
    if (btnToggleAi) btnToggleAi.classList.add('active');
    updateRightSidebarState();
    
    // CONTEXT toggle = non-AI panels (References + Archetype Notes)
    const nonAiPanels = sidebarRight?.querySelectorAll('.kl-panel:not(.kl-flex-1)');
    if (btnToggleRefs && nonAiPanels) {
        btnToggleRefs.onclick = () => {
            const anyVisible = Array.from(nonAiPanels).some(p => !p.classList.contains('collapsed'));
            const willCollapse = anyVisible; // If any visible, collapse all
            nonAiPanels.forEach(p => p.classList.toggle('collapsed', willCollapse));
            btnToggleRefs.classList.toggle('active', !willCollapse);
            updateRightSidebarState();
        };
    }
    
    // AI_ASSISTANT toggle = AI panel only (within sidebar)
    if (btnToggleAi && aiPanel) {
        btnToggleAi.onclick = () => {
            const willCollapse = !aiPanel.classList.contains('collapsed');
            aiPanel.classList.toggle('collapsed', willCollapse);
            btnToggleAi.classList.toggle('active', !willCollapse);
            // When AI is collapsed, give all context panels a specific class to expand
            if (nonAiPanels) {
                nonAiPanels.forEach(p => p.classList.toggle('kl-context-expanded', willCollapse));
            }
            updateRightSidebarState();
        };
    }
    
    // Show/hide panel toggles based on tab
    if (panelToggles) {
        panelToggles.classList.add('hidden');
    }

    // Folder management with file dialog
    const btnAddFolder = document.getElementById('btn-dash-add-folder');
    if (btnAddFolder) btnAddFolder.onclick = async () => {
        const folderPath = await eel.pick_directory()();
        if (folderPath && folderPath.trim()) {
            await eel.add_folder(folderPath.trim())();
            loadDashboard();
        }
    };

    const btnRemFolder = document.getElementById('btn-dash-rem-folder');
    if (btnRemFolder) btnRemFolder.onclick = () => {
        const list = document.getElementById('dash-folder-list');
        const sel = list ? list.querySelector('li.selected') : null;
        if (!sel) return openAlertModal('ERROR', 'Select a folder first.');
        const index = Array.from(list.children).indexOf(sel);
        openConfirmModal('REMOVE FOLDER', `Remove "${sel.innerText}"?`, async (confirmed) => {
            if (confirmed) {
                await eel.remove_folder(index)();
                loadDashboard();
            }
        });
    };

    // Trigger management
    const bindTriggerActions = () => {
        const addBtn = document.getElementById('btn-dash-add-trigger');
        const remBtn = document.getElementById('btn-dash-rem-trigger');
        if (addBtn) addBtn.onclick = async () => {
            openInputModal('ADD TRIGGER', 'Enter trigger keyword:', '', async (val) => {
                if (val && val.trim()) {
                    await eel.add_trigger(val.trim())();
                    loadDashboard();
                }
            });
        };
        if (remBtn) remBtn.onclick = () => {
            const list = document.getElementById('dash-trigger-list');
            const sel = list ? list.querySelector('li.selected') : null;
            if (!sel) return openAlertModal('ERROR', 'Select a trigger first.');
            const index = Array.from(list.children).indexOf(sel);
            openConfirmModal('REMOVE TRIGGER', `Remove "${sel.innerText}"?`, async (confirmed) => {
                if (confirmed) {
                    await eel.remove_trigger(index)();
                    loadDashboard();
                }
            });
        };
    };
    bindTriggerActions();

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
        document.getElementById('stat-files').innerText = data.file_count || 0;

        const iu = document.getElementById('dash-in-universe');
        if (iu) iu.checked = !!data.in_universe;
        const pm = document.getElementById('dash-preview-mode');
        if (pm) pm.checked = !!data.preview_mode;

        // NEW: Populate Presets
        const pChar = document.getElementById('dash-preset-char');
        const pWall = document.getElementById('dash-preset-wall');
        if (pChar) {
            pChar.innerHTML = '';
            (data.presets || []).forEach(p => {
                const opt = document.createElement('option');
                opt.value = opt.innerText = p;
                if (p === data.selected_preset) opt.selected = true;
                pChar.appendChild(opt);
            });
        }
        if (pWall) {
            pWall.innerHTML = '';
            (data.wall_presets || []).forEach(p => {
                const opt = document.createElement('option');
                opt.value = opt.innerText = p;
                if (p === data.wall_preset) opt.selected = true;
                pWall.appendChild(opt);
            });
        }

        renderDashList(data.folders || [], 'dash-folder-list');
        renderDashList(data.triggers || [], 'dash-trigger-list');

        if (data.last_stats && data.last_stats.total > 0) {
            document.getElementById('stat-total-lines').innerText = data.last_stats.total;
            document.getElementById('stat-percent').innerText = `${data.last_stats.percent}%`;
        }
    } catch (e) { console.error('[loadDashboard]', e); }
}

function renderDashList(items, listId) {
    const list = document.getElementById(listId);
    if (!list) return;
    list.innerHTML = '';
    items.forEach(item => {
        const li = document.createElement('li');
        li.innerText = item;
        li.onclick = () => {
            list.querySelectorAll('li').forEach(el => el.classList.remove('selected'));
            li.classList.add('selected');
        };
        list.appendChild(li);
    });
}

// =============================================================================
// REVIEWER — NAVIGATION
// =============================================================================
// Request queue to process load requests sequentially
let loadQueue = [];
let isProcessingQueue = false;

async function processLoadQueue() {
    if (isProcessingQueue || loadQueue.length === 0) {
        return;
    }
    
    isProcessingQueue = true;
    const { idx, resolve } = loadQueue.shift();
    
    console.log(`[processLoadQueue] Processing load request for idx=${idx}, queue length=${loadQueue.length}, currentIdx=${state.reviewer.currentIdx}`);
    
    try {
        await loadItemAtIdxInternal(idx);
        resolve();
    } catch (e) {
        console.error('[processLoadQueue] Error:', e);
        resolve();
    }
    
    isProcessingQueue = false;
    
    // Process next request in queue
    if (loadQueue.length > 0) {
        processLoadQueue();
    }
}

async function loadItemAtIdx(idx) {
    console.log(`[loadItemAtIdx] Called with idx=${idx}, queue length=${loadQueue.length}, isProcessing=${isProcessingQueue}`);
    return new Promise((resolve) => {
        loadQueue.push({ idx, resolve });
        console.log(`[loadItemAtIdx] Added to queue, new queue length=${loadQueue.length}`);
        processLoadQueue();
    });
}

async function loadItemAtIdxInternal(idx) {
    console.log(`[loadItemAtIdxInternal] START called with idx=${idx}, mode=${state.reviewer.mode}`);
    try {
        let item;
        let items;
        
        // In review mode, use already-loaded fullQueue from category selection
        // In translate mode, fetch from backend
        if (state.reviewer.mode === 'review') {
            // Use already-loaded queue from category selection
            items = state.reviewer.fullQueue;
            console.log(`[loadItemAtIdxInternal] Review mode: items.length=${items?.length}, items=${!!items}`);
            if (!items || !items.length) {
                console.log('[loadItemAtIdxInternal] Early return: queue empty');
                document.getElementById('review-status').innerText = 'QUEUE: EMPTY';
                return;
            }
            idx = Math.max(0, Math.min(idx, items.length - 1));
            state.reviewer.currentIdx = idx;
            item = items[idx];
            state.reviewer.currentItem = item;
            console.log(`[loadItemAtIdxInternal] Loading item at idx=${idx}, jp="${item.jp?.substring(0, 30)}..."`);
        } else {
            // Translate mode - fetch from backend
            try {
                items = await eel.get_all_items_in_queue()();
                state.reviewer.fullQueue = items || [];
            } catch (e) { console.error('[loadItemAtIdx] queue fetch', e); }

            items = state.reviewer.fullQueue;
            if (!items.length) {
                document.getElementById('review-status').innerText = 'QUEUE: EMPTY';
                return;
            }
            idx = Math.max(0, Math.min(idx, items.length - 1));
            state.reviewer.currentIdx = idx;
            item = items[idx];
            state.reviewer.currentItem = item;
        }

        // Store the current index for async operations to check against
        const loadIdx = idx;

        // Check prefetch cache for this item (use current category)
        const category = state.reviewer.currentCategory || 'default';
        const cached = await eel.get_prefetch_cache(category, idx)();
        if (cached) {
            console.log(`[loadItemAtIdxInternal] Using cached data for category=${category}, idx=${idx}`);
        }

        // Header - populate display elements (legacy) or dropdowns (Kinetic Logic)
        const speakerNameEl = document.getElementById('speaker-name');
        const speakerValue = document.getElementById('speaker-value');
        if (speakerNameEl) speakerNameEl.innerText = item.speaker || '—';
        if (speakerValue) speakerValue.innerText = item.speaker || '—';
        
        // Load saved archetype and note for this speaker
        const archetypeSelect = document.getElementById('archetype-select');
        const noteInput = document.getElementById('speaker-note');
        if (item.speaker) {
            // Fetch saved speaker config from backend
            const speakerArchetype = await eel.get_speaker_archetype(item.speaker)();
            const speakerNote = await eel.get_speaker_note(item.speaker)();
            if (archetypeSelect) archetypeSelect.value = speakerArchetype || '';
            if (noteInput) noteInput.value = speakerNote || '';
            
            // Update sidebar speaker note
            const sidebarNote = document.getElementById('sidebar-speaker-note');
            if (sidebarNote) sidebarNote.innerText = speakerNote || '';
            
            // Fetch and display archetype notes
            const archetypeNotes = await eel.get_archetype_notes(speakerArchetype || '')();
            const notesPanel = document.getElementById('archetype-notes');
            if (notesPanel) notesPanel.innerText = archetypeNotes || '(no notes)';
        } else {
            if (archetypeSelect) archetypeSelect.value = '';
            if (noteInput) noteInput.value = '';
            const notesPanel = document.getElementById('archetype-notes');
            if (notesPanel) notesPanel.innerText = '(no speaker)';
            const sidebarNote = document.getElementById('sidebar-speaker-note');
            if (sidebarNote) sidebarNote.innerText = '';
        }
        
        const entryTypeEl = document.getElementById('entry-type-parity');
        const entryTypeSelect = document.getElementById('entry-type-select');
        if (entryTypeEl) entryTypeEl.innerText = item.category || '—';
        if (entryTypeSelect) entryTypeSelect.value = item.category || 'Dialogue';
        
        // Clear editor before setting new text to prevent stale data
        const enEditor = document.getElementById('en-editor');
        const jpEditor = document.getElementById('jp-editor');
        if (enEditor) enEditor.innerText = '';
        if (jpEditor) jpEditor.innerText = '';
        
        if (enEditor) enEditor.innerText = (item.en || '').replace(/★/g, '');
        document.getElementById('review-status').innerText = `QUEUE: ${idx + 1} / ${items.length}`;
        
        // Use cached lore context if available, otherwise fetch it
        if (cached && cached.lore_context) {
            populateSourceWithLoreHighlightsFromCache(item.jp, item.en || '', cached.lore_context);
        } else {
            await populateSourceWithLoreHighlights(item.jp, item.en || '');
        }

        updateReviewerCounters();
        await syncLineCounters();
        renderRowSidebar();

        // Ensure preview profiles are loaded before first preview render
        if (!state.preview || !state.preview.profiles || Object.keys(state.preview.profiles).length === 0) {
            await loadPreviewProfiles();
        }

        // Use cached data if available, otherwise fetch it
        if (cached && cached.anachronisms) {
            populateLoreContextFromCache(item.jp, item.en, cached.anachronisms, loadIdx);
        } else {
            populateLoreContext(item.jp, item.en, loadIdx);
        }
        
        // Other async enrichments - fire-and-forget with index-based cancellation
        fetchDeepLSuggestion(item.jp, loadIdx);
        populateGloss(item.jp, loadIdx);
        populateAdjacentContext(item.path, item.row, loadIdx);
        updatePreview(loadIdx);
        
        // Trigger prefetching of next entries
        eel.start_prefetch(category, items, idx, 3)();
    } catch (e) {
        console.error('[loadItemAtIdx] Error:', e);
    }
}

function initReviewerActions() {
    const bind = (id, ev, fn) => { const el = document.getElementById(id); if (el) el[ev] = fn; };

    // Category selector
    const categorySelect = document.getElementById('category-select');
    if (categorySelect) {
        categorySelect.onchange = async () => {
            console.log('[categorySelect.onchange] Selected category:', categorySelect.value);
            await switchCategory(categorySelect.value);
        };
    }

    // Sidebar tabs
    document.querySelectorAll('.side-tab').forEach(tab => {
        tab.onclick = () => {
            const sideId = tab.getAttribute('data-side');
            document.querySelectorAll('.side-tab').forEach(t => t.classList.toggle('active', t === tab));
            document.querySelectorAll('.side-pane').forEach(p => p.classList.toggle('active', p.id === `side-${sideId}`));
        };
    });

    bind('btn-apply', 'onclick', applyFix);
    bind('btn-prev', 'onclick', nextItem);
    bind('btn-rewrap', 'onclick', rewrapEditor);
    bind('btn-dash-em', 'onclick', () => replaceDashes('—'));
    bind('btn-dash-triple', 'onclick', () => replaceDashes('...'));
    bind('show-translated-rows', 'onchange', () => { renderRowSidebar(); saveState(); });

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
        
        ed.addEventListener('input', async () => { 
            saveUndoState();
            updateReviewerCounters(); 
            await syncLineCounters();
            // Re-scan for anachronisms as user types
            const jpText = document.getElementById('jp-source')?.innerText || '';
            populateLoreContext(jpText, ed.innerText, state.reviewer.currentIdx);
            // Update source window tag colors dynamically
            const jpSource = document.getElementById('jp-source');
            if (jpSource && jpSource._originalJp) {
                populateSourceWithLoreHighlights(jpSource._originalJp, ed.innerText);
            }
        });
        ed.addEventListener('scroll', syncCounterScroll);
        ed.addEventListener('keydown', handleTabKey);
        ed.addEventListener('mousemove', handleMouseMove);
        ed.addEventListener('mouseleave', hideTooltip);
        ed.addEventListener('click', handleEditorClick);
        ed.addEventListener('paste', handlePaste);
        
        // Store the skip flag on the element for renderHighlights to access
        ed._skipCursorRestore = () => skipCursorRestore;
    }
    
    // Initialize speaker, archetype, and entry type controls
    initMetadataControls();
    
    // Initialize preset dropdowns
    loadLimitPresets();
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

function handlePaste(e) {
    e.preventDefault();
    saveUndoState();
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

function hideTooltip() {
    const tooltip = document.getElementById('anach-tooltip');
    if (tooltip) {
        tooltip.style.display = 'none';
    }
    hoveredAnachronism = null;
}

function showAnachronismModal(word, suggestion, defn, example, is_ddon = false) {
    // Create modal if it doesn't exist
    let modal = document.getElementById('anach-modal');
    if (!modal) {
        modal = document.createElement('div');
        modal.id = 'anach-modal';
        modal.style.cssText = `
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.7);
            display: none;
            justify-content: center;
            align-items: center;
            z-index: 10000;
        `;
        document.body.appendChild(modal);
        
        // Add click outside to close
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                modal.style.display = 'none';
            }
        });
    }
    
    // Create modal content
    const content = document.createElement('div');
    content.style.cssText = `
        background: var(--bg-color, #1e1e1e);
        border: 1px solid var(--accent-color, #4a9eff);
        border-radius: 8px;
        padding: 20px;
        max-width: 500px;
        max-height: 80vh;
        overflow-y: auto;
        color: var(--text-color, #e0e0e0);
        font-family: 'Inter', sans-serif;
        word-wrap: break-word;
        overflow-wrap: break-word;
        white-space: normal;
    `;
    
    const ddonText = is_ddon ? ' <span style="color: #e8c56a;">★ Used in DD1</span>' : '';
    let html = `
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
            <h3 style="margin: 0; font-size: 16px; color: var(--accent-color, #4a9eff);">
                <span style="text-decoration: line-through; opacity: 0.7;">${escHtml(word)}</span> → ${escHtml(suggestion)}${ddonText}
            </h3>
            <button onclick="document.getElementById('anach-modal').style.display='none'" 
                    style="background: none; border: none; color: var(--text-color, #e0e0e0); font-size: 20px; cursor: pointer;">&times;</button>
        </div>
    `;
    
    if (defn) {
        html += `
            <div style="margin-bottom: 12px;">
                <strong style="color: var(--accent-color, #4a9eff);">Definition:</strong>
                <p style="margin: 5px 0 0 0; line-height: 1.5;">${escHtml(defn)}</p>
            </div>
        `;
    }
    
    if (example) {
        // Convert **text** to <strong>text</strong> for bolding
        const formattedExample = escHtml(example).replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
        html += `
            <div>
                <strong style="color: var(--accent-color, #4a9eff);">Example:</strong>
                <p style="margin: 5px 0 0 0; line-height: 1.5; font-style: italic;">"${formattedExample}"</p>
            </div>
        `;
    }
    
    content.innerHTML = html;
    modal.innerHTML = '';
    modal.appendChild(content);
    modal.style.display = 'flex';
}

async function loadLimitPresets() {
    try {
        const presets = await eel.get_all_presets()();
        const charSelect = document.getElementById('char-limit-preset');
        const lineSelect = document.getElementById('line-limit-preset');
        
        if (charSelect && presets.char_presets) {
            charSelect.innerHTML = '';
            Object.entries(presets.char_presets).forEach(([name, value]) => {
                const opt = document.createElement('option');
                opt.value = value;
                opt.text = name;
                charSelect.appendChild(opt);
            });
            // Select current preset
            const selectedValue = presets.char_presets[presets.selected_char];
            if (selectedValue) charSelect.value = selectedValue;
            
            // Handle change
            charSelect.onchange = async () => {
                await eel.save_config_field('selected_preset', charSelect.options[charSelect.selectedIndex].text)();
                state.standardLimit = parseInt(charSelect.value);
                updateReviewerCounters();
            };
        }
        
        if (lineSelect && presets.line_presets) {
            lineSelect.innerHTML = '';
            Object.entries(presets.line_presets).forEach(([name, value]) => {
                const opt = document.createElement('option');
                opt.value = value;
                opt.text = name;
                lineSelect.appendChild(opt);
            });
            // Select current preset
            const selectedValue = presets.line_presets[presets.selected_line];
            if (selectedValue) lineSelect.value = selectedValue;
            
            // Handle change
            lineSelect.onchange = async () => {
                await eel.save_config_field('wall_preset', lineSelect.options[lineSelect.selectedIndex].text)();
                state.maxLines = parseInt(lineSelect.value);
                updateReviewerCounters();
            };
        }
    } catch (e) { console.error('[loadLimitPresets]', e); }
}

// Speaker, Archetype, Entry Type controls
async function initMetadataControls() {
    // Load dropdown options
    await loadArchetypes();
    await loadEntryTypes();
    
    // Archetype dropdown - update notes panel on change
    const archetypeSelect = document.getElementById('archetype-select');
    if (archetypeSelect) {
        archetypeSelect.onchange = async () => {
            const archetypeKey = archetypeSelect.value;
            const notesPanel = document.getElementById('archetype-notes');
            if (notesPanel) {
                const notes = await eel.get_archetype_notes(archetypeKey)();
                notesPanel.innerText = notes || '(no notes)';
            }
        };
    }
    
    // Speaker save button
    const btnSaveMeta = document.getElementById('btn-save-meta');
    if (btnSaveMeta) {
        btnSaveMeta.onclick = async () => {
            const speaker = state.reviewer.currentItem?.speaker || '';
            const archetype = document.getElementById('archetype-select')?.value || '';
            const note = document.getElementById('speaker-note')?.value || '';
            
            if (speaker) {
                await eel.save_speaker_archetype(speaker, archetype, note)();
                // Update sidebar note
                const sidebarNote = document.getElementById('sidebar-speaker-note');
                if (sidebarNote) sidebarNote.innerText = note || '';
                btnSaveMeta.innerText = 'Saved!';
                setTimeout(() => btnSaveMeta.innerText = 'Save', 500);
            }
        };
    }
    
    // Entry type save button
    const btnSaveType = document.getElementById('btn-save-type');
    if (btnSaveType) {
        btnSaveType.onclick = async () => {
            const entryType = document.getElementById('entry-type-select')?.value || '';
            const item = state.reviewer.currentItem;
            if (item && entryType) {
                const result = await eel.save_entry_type_to_csv(item.id, entryType)();
                if (result.ok) {
                    btnSaveType.innerText = 'Saved!';
                    setTimeout(() => btnSaveType.innerText = 'Save Type', 500);
                } else {
                    openAlertModal('ERROR', 'Error saving entry type: ' + (result.error || 'Unknown'));
                }
            }
        };
    }
}

async function loadArchetypes() {
    try {
        const archetypes = await eel.get_archetypes_list()();
        const select = document.getElementById('archetype-select');
        if (select && archetypes) {
            select.innerHTML = '';
            archetypes.forEach(a => {
                const opt = document.createElement('option');
                opt.value = a.key;
                opt.innerText = a.name;
                select.appendChild(opt);
            });
        }
    } catch (e) { console.error('[loadArchetypes]', e); }
}

async function loadEntryTypes() {
    try {
        const types = await eel.get_entry_types_list()();
        const select = document.getElementById('entry-type-select');
        if (select && types) {
            select.innerHTML = '';
            types.forEach(t => {
                const opt = document.createElement('option');
                opt.value = t.key;
                opt.innerText = t.name;
                select.appendChild(opt);
            });
        }
    } catch (e) { console.error('[loadEntryTypes]', e); }
}

async function nextItem() {
    const total = state.reviewer.fullQueue.length;
    if (total === 0) return;
    const next = state.reviewer.currentIdx + 1;
    saveState();
    if (next < total) {
        loadItemAtIdx(next);
    } else {
        // Try fetching another item from Python's rolling queue (review mode)
        const item = await eel.get_next_review_item()();
        if (item) {
            // refresh full list and move to new end
            await loadItemAtIdx(next);
        } else {
            openAlertModal('INFO', 'End of queue reached.');
        }
    }
}

function prevItem() {
    if (state.reviewer.currentIdx > 0) {
        saveState();
        loadItemAtIdx(state.reviewer.currentIdx - 1);
    }
}

async function applyFix() {
    const item = state.reviewer.currentItem;
    if (!item) return;
    saveUndoState();
    const text = document.getElementById('en-editor').innerText;
    const force = document.getElementById('force-save-toggle').checked;

    const res = await eel.apply_fix(item.id, text, force)();
    if (res && res.ok) {
        const btn = document.getElementById('btn-apply');
        const prev = btn.innerHTML;
        btn.innerHTML = '✓ SAVED';
        setTimeout(() => { btn.innerHTML = prev; nextItem(); }, 400);
        // Update local copy so the sidebar shows the saved value
        state.reviewer.fullQueue[state.reviewer.currentIdx].en = text;
        renderRowSidebar();
    } else {
        const msg = (res && res.error) ? res.error : 'Save failed — unknown error.';
        openAlertModal('ERROR', `[SAVE ERROR]\n${msg}`);
    }
}

async function rewrapEditor() {
    const text = document.getElementById('en-editor').innerText;
    saveUndoState();
    const limit = state.standardLimit;
    const rewrapped = await eel.rewrap_text(text, limit)();
    if (rewrapped !== undefined && rewrapped !== null) {
        document.getElementById('en-editor').innerText = rewrapped;
        updateReviewerCounters();
        await syncLineCounters();
    }
}

async function replaceDashes(target) {
    const ed = document.getElementById('en-editor');
    saveUndoState();
    const fixed = ed.innerText.replace(/[-\u2013\u2014\u2015]{2,}/g, target);
    if (target === '...') {
        ed.innerText = fixed.replace(/\.\.\.(\w)/g, '... $1');
    } else {
        ed.innerText = fixed;
    }
    updateReviewerCounters();
    await syncLineCounters();
}

// =============================================================================
// REVIEWER — COUNTERS / PREVIEW
// =============================================================================
async function syncLineCounters() {
    const ed = document.getElementById('en-editor');
    const ctr = document.getElementById('line-counters');
    if (!ed || !ctr) return;
    
    // For contenteditable, count lines by splitting innerText by newlines
    const text = ed.innerText;
    const lines = text ? text.split('\n') : [];
    const limit = state.standardLimit || 50;
    
    // Only show counters for actual lines (dynamic spawning)
    ctr.innerHTML = '';
    
    for (let i = 0; i < lines.length; i++) {
        const s = document.createElement('span');
        // Use backend to get simulated length with tag mapping
        const charCount = await eel.get_simulated_len(lines[i] || '')();
        s.innerText = charCount;
        // Color code based on configured limit
        if (charCount > limit) s.style.color = '#ff6b6b';
        else if (charCount > limit * 0.8) s.style.color = '#ffa502';
        else s.style.color = 'var(--accent-color)';
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

    const lines = ed.innerText.split('\n');
    const maxLines = state.maxLines || 5;
    const lineCount = lines.length;
    
    // Update header to show line count vs max lines
    const cc = document.getElementById('char-count');
    if (cc) {
        cc.innerText = `${lineCount} / ${maxLines} lines`;
        cc.style.color = lineCount > maxLines ? '#ff4444' : 'var(--accent-color)';
    }

    // Scan for anachronisms
    await scanAnachronisms(ed.innerText);

    updatePreview(state.reviewer.currentIdx);
}

function updatePreview(loadIdx) {
    const ed = document.getElementById('en-editor');
    const container = document.getElementById('preview-container');
    if (!ed || !container) return;
    
    const boxType = document.getElementById('preview-box-type')?.value || 'dialogue';
    const text = ed.innerText || '';
    
    console.log(`[updatePreview] Starting for loadIdx=${loadIdx}, currentIdx=${state.reviewer.currentIdx}`);
    const startTime = Date.now();
    
    // Generate preview image
    eel.generate_preview_image(boxType, text)().then(result => {
        const elapsed = Date.now() - startTime;
        console.log(`[updatePreview] Completed for loadIdx=${loadIdx}, currentIdx=${state.reviewer.currentIdx}, elapsed=${elapsed}ms`);
        
        // Only check index if loadIdx was provided (skip check for preview setting changes)
        if (loadIdx !== undefined && state.reviewer.currentIdx !== loadIdx) {
            console.log(`[updatePreview] Skipped update because currentIdx=${state.reviewer.currentIdx} != loadIdx=${loadIdx}`);
            return;
        }
        
        if (result && result.image) {
            // Display just the image with text overlay directly
            // Crop values: [x1, y1] for position offset, [x2, y2] for window size
            const crop = result.crop || [0, 0, result.width, result.height];
            const [x1, y1, x2, y2] = crop;
            
            // Position image based on x1,y1 (position offset)
            // Set container size based on x2,y2 (window size)
            container.style.width = `${x2}px`;
            container.style.height = `${y2}px`;
            container.innerHTML = `<img src="${result.image}" style="
                position: absolute;
                left: -${x1}px;
                top: -${y1}px;
                width: ${result.width}px;
                height: ${result.height}px;
            ">`;
        } else {
            // Fallback - show text only
            container.innerText = text || '(no preview available)';
            container.style.width = '';
            container.style.height = '';
        }
    }).catch(error => {
        console.error('[updatePreview] Failed to generate preview:', error);
        if (loadIdx === undefined || state.reviewer.currentIdx === loadIdx) {
            container.innerText = text || '(preview error)';
            container.style.width = '';
            container.style.height = '';
        }
    });
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
    
    // Escape HTML tags to make them visible as text
    let html = text.replace(/</g, '&lt;').replace(/>/g, '&gt;');
    
    // Apply anachronism highlights using position-based approach
    if (state.reviewer.anachRanges && state.reviewer.anachRanges.length > 0) {
        // Sort by length (longer first) to handle multi-word phrases first
        const sortedRanges = [...state.reviewer.anachRanges].sort((a, b) => b[0].length - a[0].length);
        
        for (const [word, suggestion, is_ddon] of sortedRanges) {
            const escapedWord = word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
            // Use word boundary for single words, but not for multi-word phrases
            const useWordBoundary = !word.includes(' ');
            const regex = new RegExp(useWordBoundary ? `\\b${escapedWord}\\b` : escapedWord, 'gi');
            
            // Replace all occurrences, but skip those already inside span tags
            let match;
            const regexObj = new RegExp(regex);
            let lastIndex = 0;
            let newHtml = '';
            
            while ((match = regexObj.exec(html)) !== null) {
                // Add text before this match
                newHtml += html.substring(lastIndex, match.index);
                
                // Check if we're inside a span tag
                const before = html.substring(0, match.index);
                const openSpanCount = (before.match(/<span/g) || []).length;
                const closeSpanCount = (before.match(/<\/span>/g) || []).length;
                
                if (openSpanCount > closeSpanCount) {
                    // Already inside a span, don't replace
                    newHtml += match[0];
                } else {
                    // Not inside a span, add highlight
                    const className = is_ddon ? "anach-highlight anach-ddon" : "anach-highlight";
                    newHtml += `<span class="${className}" data-word="${escAttr(word)}" data-suggestion="${escAttr(suggestion)}" data-is-ddon="${is_ddon}">${match[0]}</span>`;
                }
                
                lastIndex = match.index + match[0].length;
            }
            
            // Add remaining text
            newHtml += html.substring(lastIndex);
            html = newHtml;
        }
    }
    
    ed.innerHTML = html;
    if (cursorOffset !== null) restoreCursor(ed, cursorOffset);
}

function getCaretOffset(element, range) {
    // Get the plain text content
    const text = element.innerText || '';
    
    // Traverse the DOM to calculate the character offset
    let offset = 0;
    let found = false;
    
    function traverse(node) {
        if (found) return;
        
        if (node === range.endContainer) {
            offset += range.endOffset;
            found = true;
            return;
        }
        
        if (node.nodeType === Node.TEXT_NODE) {
            offset += node.length;
        } else {
            for (let i = 0; i < node.childNodes.length; i++) {
                traverse(node.childNodes[i]);
                if (found) return;
            }
        }
    }
    
    traverse(element);
    
    // If we didn't find the exact node, fall back to range.toString()
    if (!found) {
        const preCaretRange = range.cloneRange();
        preCaretRange.selectNodeContents(element);
        preCaretRange.setEnd(range.endContainer, range.endOffset);
        offset = preCaretRange.toString().length;
    }
    
    // Check if cursor is at the end of the text
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
        // Get the position of this specific occurrence in the text using Range API
        let position = -1;
        
        try {
            const range = document.createRange();
            range.selectNodeContents(ed);
            const textRange = document.createRange();
            textRange.setStartBefore(target);
            textRange.setEndAfter(target);
            
            // Get the text before the target
            const preRange = document.createRange();
            preRange.setStart(ed, 0);
            preRange.setEndBefore(target);
            position = preRange.toString().length;
            
        } catch (err) {
            position = -1;
        }
        
        hoveredAnachronism = [word, suggestion, position];
        ed.style.cursor = 'pointer';
        
        // Show tooltip with definition
        if (tooltip && suggestion) {
            let tooltipHtml = `<span class="tooltip-word">${word}</span> <span class="tooltip-arrow">→</span> ${suggestion}`;
            
            // Store the current word to check later in the async callback
            const currentWord = word;
            
            // Fetch definition and example for the suggestion (archaic word)
            eel.get_definition(suggestion)().then(result => {
                // Only update tooltip if we're still hovering over the same word
                if (hoveredAnachronism && hoveredAnachronism[0] === currentWord && tooltip.style.display !== 'none') {
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
    const text = textarea.innerText;
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

function replaceAnachronism(word, suggestion, position = null) {
    const ed = document.getElementById('en-editor');
    if (!ed) return;
    saveUndoState();
    
    const text = ed.innerText;
    
    // Strip star icon from text when searching (word may be followed by " ★")
    const textClean = text.replace(/ ★/g, '');
    
    // Use provided position if available, otherwise find first occurrence
    let idx;
    if (position !== null && position >= 0) {
        idx = position;
    } else {
        idx = textClean.toLowerCase().indexOf(word.toLowerCase());
    }
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
    
    // Trigger async rescan without blocking UI
    // This runs in the background and will update highlights when complete
    scanAnachronisms(ed.innerText);
}

function handleTabKey(e) {
    if (e.key !== 'Tab') return;
    
    const ed = document.getElementById('en-editor');
    if (!ed) return;
    
    // Prioritize hovered anachronism
    if (hoveredAnachronism) {
        const [word, suggestion, position] = hoveredAnachronism;
        replaceAnachronism(word, suggestion, position);
        e.preventDefault();
        return;
    }
    
    // For contenteditable, cursor position check is complex - skip for now
    // Tab key only works on hover for contenteditable approach
}

// =============================================================================
// PREVIEW CONTROLS
// =============================================================================
function initPreviewActions() {
    // Initialize preview state
    state.preview = { profiles: {}, currentType: 'dialogue' };
    
    // Load profiles
    loadPreviewProfiles();
    
    // Box type change
    const boxType = document.getElementById('preview-box-type');
    if (boxType) boxType.onchange = () => {
        console.log('[initPreviewActions] Box type changed to:', boxType.value);
        state.preview.currentType = boxType.value;
        syncPreviewControls();
        updatePreview(undefined); // Pass undefined to skip index check
    };

    // Font size change
    const fontSize = document.getElementById('preview-font-size');
    if (fontSize) fontSize.onchange = () => {
        savePreviewProfile();
        updatePreview();
    };

    // Spacing change
    const spacing = document.getElementById('preview-spacing');
    if (spacing) spacing.onchange = () => {
        savePreviewProfile();
        updatePreview();
    };

    // Calibration toggle
    const calibrateBtn = document.getElementById('btn-preview-calibrate');
    const calibPanel = document.getElementById('preview-calibration');
    if (calibrateBtn && calibPanel) {
        calibrateBtn.onclick = () => {
            const isVisible = calibPanel.style.display !== 'none';
            calibPanel.style.display = isVisible ? 'none' : 'block';
            calibrateBtn.innerText = isVisible ? 'Calibrate' : 'Hide';
            if (!isVisible) syncPreviewControls();
        };
    }

    // Calibration input changes
    ['crop-x1', 'crop-y1', 'crop-x2', 'crop-y2', 'text-x', 'text-y'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.onchange = () => { savePreviewProfile(); updatePreview(); };
    });
    
    // Calibration apply buttons
    document.getElementById('btn-apply-crop')?.addEventListener('click', () => {
        savePreviewProfile();
        updatePreview();
    });
    
    document.getElementById('btn-apply-text')?.addEventListener('click', () => {
        savePreviewProfile();
        updatePreview();
    });
    
    document.getElementById('btn-apply-color')?.addEventListener('click', () => {
        savePreviewProfile();
        updatePreview();
    });

    // Add/remove preview types
    const addBtn = document.getElementById('btn-add-preview-type');
    if (addBtn) addBtn.onclick = () => {
        openInputModal('ADD PREVIEW TYPE', 'Enter new preview type name:', '', (name) => {
            if (name && name.trim()) {
                // Add to backend
                eel.add_preview_type(name.trim())().then(() => {
                    loadPreviewProfiles();
                });
            }
        });
    };

    const removeBtn = document.getElementById('btn-remove-preview-type');
    if (removeBtn) removeBtn.onclick = () => {
        const selected = boxType?.value;
        if (selected && !['dialogue', 'choice', 'questlog', 'tutorial'].includes(selected)) {
            openConfirmModal('REMOVE PREVIEW TYPE', `Remove preview type "${selected}"?`, (confirmed) => {
                if (confirmed) {
                    eel.remove_preview_type(selected)().then(() => {
                        loadPreviewProfiles();
                    });
                }
            });
        }
    };
}

async function loadPreviewProfiles() {
    try {
        const profiles = await eel.get_preview_profiles()();
        
        // Initialize state.preview if it doesn't exist
        if (!state.preview) {
            state.preview = {};
        }
        state.preview.profiles = profiles || {};
        
        const boxType = document.getElementById('preview-box-type');
        if (boxType && profiles) {
            // Get existing options to avoid duplicates
            const existingOptions = new Set();
            Array.from(boxType.options).forEach(opt => existingOptions.add(opt.value));
            
            // Add new profiles that don't already exist
            Object.keys(profiles).forEach(key => {
                if (!existingOptions.has(key)) {
                    const option = document.createElement('option');
                    option.value = key;
                    option.innerText = key;
                    boxType.appendChild(option);
                }
            });
            
            // Select dialogue by default if it exists
            if (profiles['dialogue']) {
                boxType.value = 'dialogue';
            }
            syncPreviewControls();
        }
    } catch (error) {
        console.error('Failed to load preview profiles:', error);
    }
}

function syncPreviewControls() {
    const boxType = document.getElementById('preview-box-type')?.value;
    const profile = state.preview.profiles?.[boxType];
    
    if (!profile) return;
    
    // Update font size and spacing controls
    const fontSize = document.getElementById('preview-font-size');
    const spacing = document.getElementById('preview-spacing');
    
    if (fontSize) fontSize.value = profile.font_sz || 12;
    if (spacing) spacing.value = profile.line_spacing || 1;
    
    // Update calibration controls
    const cropX1 = document.getElementById('crop-x1');
    const cropY1 = document.getElementById('crop-y1');
    const cropX2 = document.getElementById('crop-x2');
    const cropY2 = document.getElementById('crop-y2');
    const textX = document.getElementById('text-x');
    const textY = document.getElementById('text-y');
    const textColor = document.getElementById('text-color');
    
    if (cropX1) cropX1.value = profile.crop?.[0] || 0;
    if (cropY1) cropY1.value = profile.crop?.[1] || 0;
    if (cropX2) cropX2.value = profile.crop?.[2] || 200;
    if (cropY2) cropY2.value = profile.crop?.[3] || 60;
    if (textX) textX.value = profile.text_x || 0;
    if (textY) textY.value = profile.text_y || 0;
    if (textColor) textColor.value = profile.fg || '#ffffff';
}

// Helper: adjust number input by delta
function adjustNum(id, delta) {
    const el = document.getElementById(id);
    if (!el) return;
    const current = parseInt(el.value, 10) || 0;
    el.value = current + delta;
    // Trigger change to update preview
    el.dispatchEvent(new Event('change'));
}

function savePreviewProfile() {
    const boxType = document.getElementById('preview-box-type')?.value;
    if (!boxType) return;
    
    const fontSize = document.getElementById('preview-font-size');
    const spacing = document.getElementById('preview-spacing');
    const cropX1 = document.getElementById('crop-x1');
    const cropY1 = document.getElementById('crop-y1');
    const cropX2 = document.getElementById('crop-x2');
    const cropY2 = document.getElementById('crop-y2');
    const textX = document.getElementById('text-x');
    const textY = document.getElementById('text-y');
    const textColor = document.getElementById('text-color');
    
    const profile = {
        font_sz: parseInt(fontSize?.value) || 12,
        line_spacing: parseInt(spacing?.value) || 1,
        crop: [
            parseInt(cropX1?.value) || 0,
            parseInt(cropY1?.value) || 0,
            parseInt(cropX2?.value) || 200,
            parseInt(cropY2?.value) || 60
        ],
        text_x: parseInt(textX?.value) || 0,
        text_y: parseInt(textY?.value) || 0,
        fg: textColor?.value || '#ffffff'
    };
    
    eel.save_preview_profile(boxType, profile)();
}

// =============================================================================
// REVIEWER — DEEPL + LORE + ADJACENT
// =============================================================================
async function fetchDeepLSuggestion(text, loadIdx) {
    const el = document.getElementById('deepl-text');
    if (!el || !text) return;
    console.log(`[fetchDeepLSuggestion] Starting for loadIdx=${loadIdx}, currentIdx=${state.reviewer.currentIdx}`);
    el.value = 'Consulting DeepL…';
    const startTime = Date.now();
    const res = await eel.get_deepl_suggestion(text)();
    const elapsed = Date.now() - startTime;
    console.log(`[fetchDeepLSuggestion] Completed for loadIdx=${loadIdx}, currentIdx=${state.reviewer.currentIdx}, elapsed=${elapsed}ms`);
    
    // Only update if we're still on the same item
    if (state.reviewer.currentIdx === loadIdx) {
        el.value = res || '—';
    } else {
        console.log(`[fetchDeepLSuggestion] Skipped update because currentIdx=${state.reviewer.currentIdx} != loadIdx=${loadIdx}`);
    }
    
    // Add click-to-paste functionality
    el.onclick = () => {
        const suggestion = el.value.trim();
        if (!suggestion || suggestion === 'Consulting DeepL…' || suggestion === '—') return;
        
        const editor = document.getElementById('en-editor');
        if (!editor) return;
        
        const current = editor.innerText.trim();
        if (current) {
            openConfirmModal('OVERWRITE TEXT', 'Overwrite current English text with DeepL suggestion?', (confirmed) => {
                if (confirmed) {
                    editor.innerText = suggestion;
                    updateReviewerCounters();
                }
            });
            return;
        }
        
        editor.innerText = suggestion;
        updateReviewerCounters();
        syncLineCounters();
        
        // Re-scan for anachronisms after DeepL paste
        scanAnachronisms(suggestion);
    };
}

async function populateGloss(jpText, loadIdx) {
    const box = document.getElementById('gloss-box');
    if (!box) return;
    if (!jpText) {
        box.innerHTML = '<em style="opacity:0.5">No text</em>';
        return;
    }
    box.innerHTML = '<em style="opacity:0.5">analysing…</em>';
    console.log(`[populateGloss] Starting for loadIdx=${loadIdx}, jpText="${jpText?.slice(0, 30)}..."`);
    const startTime = Date.now();
    try {
        const tokens = await eel.get_gloss(jpText)();
        const elapsed = Date.now() - startTime;
        console.log(`[populateGloss] Completed for loadIdx=${loadIdx}, ${tokens?.length || 0} tokens, elapsed=${elapsed}ms`);
        
        // Only update if we're still on the same item
        if (state.reviewer.currentIdx !== loadIdx) {
            console.log(`[populateGloss] Skipped update because currentIdx=${state.reviewer.currentIdx} != loadIdx=${loadIdx}`);
            return;
        }
        if (!tokens || !tokens.length) {
            box.innerHTML = '<em style="opacity:0.5">No gloss available</em>';
            return;
        }
        
        // POS colors matching old implementation
        const POS_COLORS = {
            noun:    '#6fb3ff',
            verb:    '#7ddb8a',
            adj:     '#e8c56a',  // Swapped with lore gold
            adv:     '#a78bfa',
            particle:'#aaaaaa',
            aux:     '#aaaaaa',
            other:   '#cccccc',
        };
        
        // Render as inline flow like old Tkinter version
        let html = '';
        tokens.forEach((t, i) => {
            const surface = t.surface || '';
            const cands = t.candidates || [];
            
            if (!cands.length || !surface.trim()) {
                // Non-glossable spacer — render plain
                html += `<span style="color:var(--tab-inactive)">${escHtml(surface)}</span>`;
                return;
            }
            
            // Color by POS; lore terms get gold tint (swapped with adj)
            const baseFg = t.is_lore ? '#f0b429' : (POS_COLORS[t.pos] || POS_COLORS.other);
            const hasMulti = cands.length > 1;
            const tooltip = t.is_lore ? '★ ' + cands.join(', ') : cands.join(', ');
            
            // surface[candidate] format with optional breathing room
            const insertStr = `${surface}[${cands[0]}]${hasMulti ? '  ' : ''}`;
            
            html += `<span class="gloss-span" 
                data-candidate="${escHtml(cands[0])}"
                style="color:${baseFg};${hasMulti ? 'text-decoration:underline;' : ''}cursor:pointer;"
                title="${escHtml(tooltip)}">${escHtml(insertStr)}</span>`;
        });
        
        box.innerHTML = html;
        
        // Wire up click handlers to insert into editor
        box.querySelectorAll('.gloss-span').forEach(span => {
            span.onclick = async () => {
                const candidate = span.getAttribute('data-candidate');
                const ed = document.getElementById('en-editor');
                if (ed && candidate) {
                    ed.innerText += candidate;
                    updateReviewerCounters();
                    await syncLineCounters();
                }
            };
        });
    } catch (e) {
        console.error('[populateGloss]', e);
        box.innerHTML = '<em style="opacity:0.5">Gloss error</em>';
    }
}

async function populateSourceWithLoreHighlightsFromCache(jpText, enText, loreMatches) {
    const box = document.getElementById('jp-source');
    if (!box) return;
    if (!jpText) {
        box.innerText = '';
        return;
    }
    
    box._originalJp = jpText;
    box.innerText = jpText;
    
    if (!loreMatches || !loreMatches.length) {
        return;
    }
    
    // Use the same logic as populateSourceWithLoreHighlights but with cached matches
    try {
        const markers = [];
        for (const loreMatch of loreMatches) {
            // Handle both tuple format [jp, en] and object format {jp, en, is_lore}
            let jp, en, is_lore;
            if (Array.isArray(loreMatch)) {
                [jp, en] = loreMatch;
                is_lore = false; // Default to false for old cache format
            } else {
                jp = loreMatch.jp;
                en = loreMatch.en;
                is_lore = loreMatch.is_lore || false;
            }
            if (!jp || !en) continue;
            const marker = `__LORE_${markers.length}__`;
            markers.push({ marker, jp, suggestion: en, allSuggestions: [en], is_lore });
        }
        
        let markedText = jpText;
        for (const { marker, jp } of markers) {
            markedText = markedText.replace(jp, marker);
        }
        
        let html = escHtml(markedText);
        
        for (const { marker, jp, suggestion, allSuggestions, is_lore } of markers) {
            const escapedMarker = escHtml(marker);
            const spanHtml = `<span class="lore-source-span" 
                data-suggestion="${escHtml(suggestion)}"
                data-all-suggestions="${escHtml(allSuggestions.join(' | '))}"
                style="color:#6fb3ff;text-decoration:underline;cursor:pointer;"
                title="">${escHtml(jp)}</span>`;
            html = html.replaceAll(escapedMarker, spanHtml);
        }
        
        box.innerHTML = html;
        
        // Wire up click handlers
        box.querySelectorAll('.lore-source-span').forEach(span => {
            span.onclick = async () => {
                const suggestion = span.getAttribute('data-suggestion');
                const ed = document.getElementById('en-editor');
                if (ed && suggestion) {
                    ed.innerText += suggestion;
                    updateReviewerCounters();
                    await syncLineCounters();
                    const jpText = document.getElementById('jp-source')?.innerText || '';
                    scanAnachronisms(ed.innerText);
                    const jpSource = document.getElementById('jp-source');
                    if (jpSource && jpSource._originalJp) {
                        populateSourceWithLoreHighlights(jpSource._originalJp, ed.innerText);
                    }
                }
            };
            
            // Add mouseover handler for custom tooltip
            span.onmouseover = (e) => {
                const tooltip = document.getElementById('anach-tooltip');
                const allSuggestions = span.getAttribute('data-all-suggestions');
                const suggestion = span.getAttribute('data-suggestion');
                if (tooltip && allSuggestions) {
                    let tooltipHtml = `<span class="tooltip-word">${span.innerText}</span> <span class="tooltip-arrow">→</span> ${allSuggestions}`;
                    tooltip.innerHTML = tooltipHtml;
                    tooltip.style.display = 'block';
                    const rect = box.getBoundingClientRect();
                    const tooltipX = e.clientX - rect.left + 15;
                    const tooltipY = e.clientY - rect.top + 20;
                    tooltip.style.left = tooltipX + 'px';
                    tooltip.style.top = tooltipY + 'px';
                }
            };
            
            // Add mouseout handler to hide tooltip
            span.onmouseout = () => {
                const tooltip = document.getElementById('anach-tooltip');
                if (tooltip) {
                    tooltip.style.display = 'none';
                }
            };
        });
    } catch (e) {
        console.error('[populateSourceWithLoreHighlightsFromCache]', e);
    }
}

function populateLoreContextFromCache(jpText, enText, anachHits, loadIdx) {
    const box = document.getElementById('lore-box');
    if (!box) return;
    
    // Only update if we're still on the same item
    if (state.reviewer.currentIdx !== loadIdx) {
        console.log(`[populateLoreContextFromCache] Skipped because currentIdx=${state.reviewer.currentIdx} != loadIdx=${loadIdx}`);
        return;
    }
    
    box.innerHTML = '';
    
    // Show anachronisms from cache
    if (anachHits && anachHits.length > 0) {
        const anachHeader = document.createElement('div');
        anachHeader.className = 'lore-header';
        anachHeader.innerText = 'Possible Anachronisms:';
        anachHeader.style.cssText = 'font-size: 9px; font-weight: 700; color: var(--accent-color); margin-bottom: 6px; margin-top: 8px;';
        box.appendChild(anachHeader);
        
        // Create flex container for anachronism hits (match main function layout)
        const anachContainer = document.createElement('div');
        anachContainer.style.cssText = 'display: flex; flex-wrap: wrap; gap: 8px;';
        
        anachHits.forEach(([word, suggestion, is_ddon]) => {
            const row = document.createElement('div');
            row.className = 'lore-row anach-row';
            row.style.cssText = 'flex: 0 0 auto; color: #ff6b6b; font-size: 10px; cursor: pointer;';
            const suggestionSpan = document.createElement('span');
            suggestionSpan.style.cssText = 'color: var(--accent-color);';
            suggestionSpan.innerText = escHtml(suggestion || '...');
            
            // Add star icon for DD1-sourced words
            if (is_ddon) {
                const starSpan = document.createElement('span');
                starSpan.innerText = ' ★';
                starSpan.style.cssText = 'color: #e8c56a;';
                suggestionSpan.appendChild(starSpan);
            }
            
            // Fetch definition and example for hover tooltip and click handler
            if (suggestion) {
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
                        let titleText = defn || "";
                        if (example) {
                            titleText += `\nExample: "${example}"`;
                        }
                        suggestionSpan.title = titleText;
                        
                        // Store full data for click handler
                        row._fullDefn = defn;
                        row._fullExample = example;
                        row._word = word;
                        row._suggestion = suggestion;
                        row._is_ddon = is_ddon;
                    }
                }).catch(err => {
                    console.error('[get_definition]', err);
                });
                
                // Add click handler to show full definition in modal
                row.addEventListener('click', () => {
                    showAnachronismModal(row._word, row._suggestion, row._fullDefn, row._fullExample, row._is_ddon);
                });
            }
            
            row.innerHTML = `<span style="text-decoration: line-through; opacity: 0.7;">${escHtml(word)}</span> → `;
            row.appendChild(suggestionSpan);
            anachContainer.appendChild(row);
        });
        
        box.appendChild(anachContainer);
    }
    
    if (!anachHits?.length) {
        box.innerHTML = '<em style="opacity:0.5">No references found.</em>';
    }
}

async function populateSourceWithLoreHighlights(jpText, enText = '') {
    const box = document.getElementById('jp-source');
    if (!box) return;
    if (!jpText) {
        box.innerText = '';
        return;
    }
    
    // Store original Japanese text for dynamic updates
    box._originalJp = jpText;
    
    // Set plain text immediately for instant feedback
    box.innerText = jpText;
    
    try {
        const matches = await eel.get_lore_context(jpText)();
        
        if (!matches || !matches.length) {
            box.innerText = jpText;
            return;
        }
        
        // Split multi-suggestion strings (comma, semicolon, pipe, newline, slash)
        const splitSuggestions = (en) => {
            const suggestions = en.split(/[,;\|\n/]/).map(s => s.trim()).filter(s => s);
            // Filter out headers like "less common:"
            return suggestions.filter(s => !/^(less|lesser|lesson)\s+common:?$/i.test(s));
        };
        
        // Use marker approach: replace terms with unique markers, then escape, then replace markers with spans
        const markers = [];
        const tagMarkers = [];
        let markedText = jpText;
        
        // First, mark tags (before lore terms to avoid HTML contamination)
        const tagRegex = /<([^>]+)>/g;
        markedText = markedText.replace(tagRegex, (match, content) => {
            const marker = `__TAG_MARKER_${tagMarkers.length}__`;
            tagMarkers.push({
                marker,
                tag: match
            });
            return marker;
        });
        
        // Then mark lore terms
        for (const m of matches) {
            const jp = m.jp;
            const en = m.en;
            const suggestions = splitSuggestions(en);
            const firstSuggestion = suggestions[0] || en;
            
            const marker = `__LORE_MARKER_${markers.length}__`;
            markers.push({
                marker,
                jp,
                suggestion: firstSuggestion,
                allSuggestions: suggestions,
                is_lore: m.is_lore
            });
            
            const escapedJp = jp.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
            const regex = new RegExp(escapedJp, 'g');
            markedText = markedText.replace(regex, marker);
        }
        
        // Escape the marked text
        let html = escHtml(markedText);
        
        // Replace lore markers with actual spans
        for (const {marker, jp, suggestion, allSuggestions, is_lore} of markers) {
            const escapedMarker = escHtml(marker);
            const spanHtml = `<span class="lore-source-span" 
                data-suggestion="${escHtml(suggestion)}"
                data-all-suggestions="${escHtml(allSuggestions.join(' | '))}"
                style="color:#6fb3ff;text-decoration:underline;cursor:pointer;"
                title="">${escHtml(jp)}</span>`;
            html = html.replaceAll(escapedMarker, spanHtml);
        }
        
        // Replace tag markers with actual spans
        for (const {marker, tag} of tagMarkers) {
            const escapedMarker = escHtml(marker);
            const tagExists = enText.includes(tag);
            const tagColor = tagExists ? '#7ddb8a' : '#e94560';
            const spanHtml = `<span class="tag-source-span" 
                data-tag="${tag}"
                style="color:${tagColor};text-decoration:underline;cursor:pointer;"
                title="${tagExists ? 'Tag already in translation' : 'Click to insert ' + escHtml(tag)}">${escHtml(tag)}</span>`;
            html = html.replaceAll(escapedMarker, spanHtml);
        }
        
        box.innerHTML = html;
        
        // Wire up click handlers to insert into editor
        box.querySelectorAll('.lore-source-span').forEach(span => {
            span.onclick = async () => {
                const suggestion = span.getAttribute('data-suggestion');
                const ed = document.getElementById('en-editor');
                if (ed && suggestion) {
                    ed.innerText += suggestion;
                    updateReviewerCounters();
                    await syncLineCounters();
                    // Re-scan for anachronisms as user types
                    const jpText = document.getElementById('jp-source')?.innerText || '';
                    scanAnachronisms(ed.innerText);
                    // Update source window tag colors dynamically
                    const jpSource = document.getElementById('jp-source');
                    if (jpSource && jpSource._originalJp) {
                        populateSourceWithLoreHighlights(jpSource._originalJp, ed.innerText);
                    }
                }
            };
            
            // Add mouseover handler for custom tooltip
            span.onmouseover = (e) => {
                const tooltip = document.getElementById('anach-tooltip');
                const allSuggestions = span.getAttribute('data-all-suggestions');
                if (tooltip && allSuggestions) {
                    let tooltipHtml = `<span class="tooltip-word">${span.innerText}</span> <span class="tooltip-arrow">→</span> ${allSuggestions}`;
                    tooltip.innerHTML = tooltipHtml;
                    tooltip.style.display = 'block';
                    const rect = box.getBoundingClientRect();
                    const tooltipX = e.clientX - rect.left + 15;
                    const tooltipY = e.clientY - rect.top + 20;
                    tooltip.style.left = tooltipX + 'px';
                    tooltip.style.top = tooltipY + 'px';
                }
            };
            
            // Add mouseout handler to hide tooltip
            span.onmouseout = () => {
                const tooltip = document.getElementById('anach-tooltip');
                if (tooltip) {
                    tooltip.style.display = 'none';
                }
            };
        });
        
        // Wire up click handlers for tags
        box.querySelectorAll('.tag-source-span').forEach(span => {
            span.onclick = async () => {
                const tag = span.getAttribute('data-tag');
                const ed = document.getElementById('en-editor');
                if (ed && tag) {
                    ed.innerText += tag;
                    updateReviewerCounters();
                    await syncLineCounters();
                    // Re-highlight source window to update tag colors
                    const jpSource = document.getElementById('jp-source');
                    if (jpSource && jpSource._originalJp) {
                        populateSourceWithLoreHighlights(jpSource._originalJp, ed.innerText);
                    }
                }
            };
        });
    } catch (e) {
        console.error('[populateSourceWithLoreHighlights]', e);
        box.innerText = jpText;
    }
}

async function populateLoreContext(jpText, enText, loadIdx) {
    const box = document.getElementById('lore-box');
    if (!box) return;
    box.innerHTML = '<em style="opacity:0.5">Loading…</em>';
    console.log(`[populateLoreContext] Starting for loadIdx=${loadIdx}, jpText="${jpText?.slice(0, 30)}..."`);
    const startTime = Date.now();
    try {
        // Get lore context and anachronisms in parallel
        const [matches, anachHits] = await Promise.all([
            eel.get_lore_context(jpText)(),
            enText ? eel.scan_anachronisms(enText)() : []
        ]);
        const elapsed = Date.now() - startTime;
        console.log(`[populateLoreContext] Completed for loadIdx=${loadIdx}, ${matches?.length || 0} lore matches, ${anachHits?.length || 0} anachronisms, elapsed=${elapsed}ms`);
        
        // Only update if we're still on the same item
        if (state.reviewer.currentIdx !== loadIdx) {
            console.log(`[populateLoreContext] Skipped update because currentIdx=${state.reviewer.currentIdx} != loadIdx=${loadIdx}`);
            return;
        }
        
        box.innerHTML = '';
        
        // Show lore references first
        if (matches && matches.length > 0) {
            const loreHeader = document.createElement('div');
            loreHeader.className = 'lore-header';
            loreHeader.innerText = 'References:';
            loreHeader.style.cssText = 'font-size: 9px; font-weight: 700; color: var(--tab-inactive); margin-bottom: 6px; margin-top: 4px;';
            box.appendChild(loreHeader);
            
            // Create flex container for lore references
            const loreContainer = document.createElement('div');
            loreContainer.style.cssText = 'display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 8px;';
            
            matches.forEach(m => {
                if (!m.is_lore) {
                    // Strip angle brackets from tag name and quotes from value before comparing
                    const enValue = m.en.trim().replace(/^"|"$/g, '');
                    const jpValue = m.jp.trim().replace(/^<|>$/g, '').replace(/^<|>$/g, ''); // Remove angle brackets
                    if (jpValue === enValue) {
                        return; // Skip tags where name equals value
                    }
                }
                
                const row = document.createElement('div');
                row.className = 'lore-row';
                row.style.cssText = 'flex: 0 0 auto; font-size: 10px;';
                if (m.is_lore) {
                    // Clickable lore terms — insert into editor on click
                    const suggestions = m.en.split(/\s*[,;|\n\/]\s*/).filter(s => s.trim());
                    const jpSpan = document.createElement('span');
                    jpSpan.className = 'lore-jp';
                    jpSpan.innerText = m.jp + ':  ';
                    row.appendChild(jpSpan);
                    suggestions.forEach((sug, i) => {
                        const a = document.createElement('span');
                        a.className = 'lore-en';
                        a.innerText = sug;
                        a.title = 'Click to insert';
                        a.onclick = () => insertIntoEditor(sug);
                        row.appendChild(a);
                        if (i < suggestions.length - 1) {
                            row.appendChild(document.createTextNode(' | '));
                        }
                    });

                    // Add dragon emoji for Cecily
                    if (suggestions.some(s => s.toLowerCase() === 'cecily')) {
                        const dragonArt = document.createElement('img');
                        dragonArt.src = 'data:image/webp;base64,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';
                        dragonArt.style.cssText = 'width: 16px; height: 16px; margin: 0 0 0 8px; vertical-align: middle;';
                        row.appendChild(dragonArt);
                    }
                } else {
                    // Tag display entry
                    row.innerHTML = `<span class="lore-tag">${escHtml(m.jp)}</span> = <span class="lore-tag-val">"${escHtml(m.en)}"</span>`;
                }
                loreContainer.appendChild(row);
            });
            
            box.appendChild(loreContainer);
        }
        
        // Show anachronisms at the bottom if any
        if (anachHits && anachHits.length > 0) {
            const anachHeader = document.createElement('div');
            anachHeader.className = 'lore-header';
            anachHeader.innerText = 'Possible Anachronisms:';
            anachHeader.style.cssText = 'font-size: 9px; font-weight: 700; color: var(--accent-color); margin-bottom: 6px; margin-top: 8px;';
            box.appendChild(anachHeader);
            
            // Create flex container for anachronism hits
            const anachContainer = document.createElement('div');
            anachContainer.style.cssText = 'display: flex; flex-wrap: wrap; gap: 8px;';
            
            anachHits.forEach(([word, suggestion, is_ddon]) => {
                const row = document.createElement('div');
                row.className = 'lore-row anach-row';
                row.style.cssText = 'flex: 0 0 auto; color: #ff6b6b; font-size: 10px; cursor: pointer;';
                const suggestionSpan = document.createElement('span');
                suggestionSpan.style.cssText = 'color: var(--accent-color);';
                suggestionSpan.innerText = escHtml(suggestion || '...');
                
                // Add star icon for DD1-sourced words
                if (is_ddon) {
                    const starSpan = document.createElement('span');
                    starSpan.innerText = ' ★';
                    starSpan.style.cssText = 'color: #e8c56a;';
                    suggestionSpan.appendChild(starSpan);
                }
                
                // Fetch definition and example for hover tooltip and click handler
                if (suggestion) {
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
                            let titleText = defn || "";
                            if (example) {
                                titleText += `\nExample: "${example}"`;
                            }
                            suggestionSpan.title = titleText;
                            
                            // Store full data for click handler
                            row._fullDefn = defn;
                            row._fullExample = example;
                            row._word = word;
                            row._suggestion = suggestion;
                            row._is_ddon = is_ddon;
                        }
                    }).catch(err => {
                        console.error('[get_definition]', err);
                    });
                    
                    // Add click handler to show full definition in modal
                    row.addEventListener('click', () => {
                        showAnachronismModal(row._word, row._suggestion, row._fullDefn, row._fullExample, row._is_ddon);
                    });
                }
                
                row.innerHTML = `<span style="text-decoration: line-through; opacity: 0.7;">${escHtml(word)}</span> → `;
                row.appendChild(suggestionSpan);
                anachContainer.appendChild(row);
            });
            
            box.appendChild(anachContainer);
        }
        
        if (!matches?.length && !anachHits?.length) {
            box.innerHTML = '<em style="opacity:0.5">No references found.</em>';
        }
    } catch (e) {
        box.innerHTML = '<em style="opacity:0.5">Error loading context.</em>';
        console.error('[populateLoreContext]', e);
    }
}

async function populateAdjacentContext(path, rowIdx, loadIdx) {
    const prevEl = document.getElementById('ctx-prev');
    const nextEl = document.getElementById('ctx-next');
    if (!prevEl && !nextEl) return;
    try {
        const ctx = await eel.get_adjacent_context(path, rowIdx)();
        
        // Only update if we're still on the same item
        if (state.reviewer.currentIdx !== loadIdx) return;
        
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
    } catch (e) { console.error('[populateAdjacentContext]', e); }
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
    const mainWorkspace = document.querySelector('.kl-main-workspace');
    const footer = document.querySelector('.kl-footer');
    if (!sidebar) return;
    // Show sidebar in both translate and review modes
    sidebar.style.display = 'flex';
    mainWorkspace?.classList.remove('no-left-sidebar');
    footer?.classList.remove('no-left-sidebar');
    
    const ul = document.getElementById('row-list-ul');
    if (!ul) return;
    ul.innerHTML = '';
    
    const showAll = document.getElementById('show-translated-rows')?.checked;
    if (!state.reviewer.fullQueue || !state.reviewer.fullQueue.length) {
        ul.innerHTML = '<li style="padding: 8px; color: var(--text-muted);">No items loaded</li>';
        return;
    }
    state.reviewer.fullQueue.forEach((item, idx) => {
        if (!showAll && item.en) return;
        const li = document.createElement('li');
        const rowNum = `<span class="row-num">[${String(idx + 1).padStart(3, '0')}]</span>`;
        const jpText = (item.jp || '').slice(0, 35);
        const enText = item.en ? `<span class="row-en">${item.en}</span>` : '';
        li.innerHTML = `${rowNum}<div class="row-text"><span class="row-jp">${jpText}</span>${enText}</div>`;
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
    const btn = document.getElementById('btn-chat-send');
    const input = document.getElementById('chat-input');

    const send = async () => {
        const msg = input ? input.value.trim() : '';
        if (!msg) return;
        
        appendChatMsg('user', msg);
        if (input) input.value = '';
        state.reviewer.chatHistory.push({ role: 'user', content: msg });

        appendChatMsg('assistant', 'Generating...');
        try {
            // Get current item data for lore context
            const currentItem = state.reviewer.currentItem;
            const currentJp = currentItem?.jp || '';
            const speaker = currentItem?.speaker || '';
            const archetypeKey = document.getElementById('archetype-select')?.value || '';
            
            const resp = await eel.send_ai_chat(msg, state.reviewer.chatHistory, currentJp, speaker, archetypeKey)();
            
            // Replace the spinner with the real response
            const history = document.getElementById('chat-history');
            if (history) {
                const last = history.querySelector('.msg.assistant:last-child');
                if (last) last.innerText = resp || '(empty response)';
            }
            state.reviewer.chatHistory.push({ role: 'assistant', content: resp || '' });
        } catch (error) {
            const history = document.getElementById('chat-history');
            if (history) {
                const last = history.querySelector('.msg.assistant:last-child');
                if (last) last.innerText = `Error: ${error.message || 'Unknown error'}`;
            }
        }
    };

    if (btn) btn.onclick = send;
    if (input) input.onkeydown = e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } };
    
    // AI Action buttons (Kinetic Logic layout) - send instantly
    const btnTranslate = document.getElementById('btn-ai-translate');
    const btnRephrase = document.getElementById('btn-ai-rephrase');
    const btnArchaize = document.getElementById('btn-ai-archaize');
    const btnCheck = document.getElementById('btn-ai-check');

    // Get button prompts from config
    const getPrompt = async (type) => {
        const config = await eel.get_full_config()();
        const prompts = config?.ai_button_prompts || {};
        return prompts[type] || `Translate: {text}`;
    };

    if (btnTranslate) btnTranslate.onclick = async () => {
        const jp = state.reviewer.currentItem?.jp || '';
        if (input && jp) {
            const promptTemplate = await getPrompt('translate');
            input.value = promptTemplate.replace('{text}', jp);
            send();
        }
    };

    if (btnRephrase) btnRephrase.onclick = async () => {
        const en = document.getElementById('en-editor')?.innerText || '';
        if (input && en) {
            const promptTemplate = await getPrompt('rephrase');
            input.value = promptTemplate.replace('{text}', en);
            send();
        }
    };

    if (btnArchaize) btnArchaize.onclick = async () => {
        const en = document.getElementById('en-editor')?.innerText || '';
        if (input && en) {
            const promptTemplate = await getPrompt('archaize');
            input.value = promptTemplate.replace('{text}', en);
            send();
        }
    };

    if (btnCheck) btnCheck.onclick = async () => {
        const jp = state.reviewer.currentItem?.jp || '';
        const en = document.getElementById('en-editor')?.innerText || '';
        if (input && (jp || en)) {
            const promptTemplate = await getPrompt('check');
            input.value = promptTemplate.replace('{text}', en);
            send();
        }
    };
    
    // Add Context button - inserts current and adjacent entries as context
    const btnAddContext = document.getElementById('btn-add-context');
    if (btnAddContext) {
        btnAddContext.onclick = async () => {
            const item = state.reviewer.currentItem;
            if (!item || !input) return;
            
            const jp = item.jp || '';
            const en = document.getElementById('en-editor')?.innerText || '';
            
            // Fetch adjacent context
            let contextText = `\n[Context - The following shows the dialogue sequence around the current entry I'm working on]\n`;
            try {
                const ctx = await eel.get_adjacent_context(item.path, item.row)();
                if (ctx && ctx.prev) {
                    contextText += `Previous (the line before current):\nJP: ${ctx.prev.jp}\nEN: ${ctx.prev.en}\n\n`;
                }
                contextText += `Current (the line I need help with):\nJP: ${jp}\nEN: ${en}\n`;
                if (ctx && ctx.next) {
                    contextText += `\nNext (the line after current):\nJP: ${ctx.next.jp}\nEN: ${ctx.next.en}\n`;
                }
            } catch (e) {
                // Fallback to just current entry
                contextText += `Current (the line I need help with):\nJP: ${jp}\nEN: ${en}\n`;
            }
            
            input.value = (input.value || '') + contextText;
            input.scrollTop = input.scrollHeight;
        };
    }
    
    // Right-click context menu for chat history
    setupChatContextMenu();
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

function setupChatContextMenu() {
    const history = document.getElementById('chat-history');
    if (!history) return;
    
    // Create context menu
    const menu = document.createElement('div');
    menu.id = 'chat-context-menu';
    menu.style.cssText = `
        position: absolute;
        display: none;
        background: rgba(30, 30, 30, 0.95);
        border: 1px solid var(--border-color);
        border-radius: 4px;
        padding: 4px 0;
        z-index: 1000;
        min-width: 180px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.5);
    `;
    document.body.appendChild(menu);
    
    // Menu items
    const items = [
        { label: 'Copy to input', action: 'copy' },
        { label: 'Copy to translation box', action: 'paste' },
        { label: 'Resend message', action: 'resend' }
    ];
    
    items.forEach(item => {
        const div = document.createElement('div');
        div.innerText = item.label;
        div.style.cssText = `
            padding: 6px 12px;
            cursor: pointer;
            font-size: 12px;
            color: var(--fg-color);
        `;
        div.onmouseover = () => div.style.background = 'rgba(255,255,255,0.1)';
        div.onmouseout = () => div.style.background = 'transparent';
        div.onclick = async () => {
            const text = menu._selectedText;
            if (!text) return;
            
            if (item.action === 'copy') {
                const input = document.getElementById('chat-input');
                if (input) input.value = text;
            } else if (item.action === 'paste') {
                const ed = document.getElementById('en-editor');
                if (ed) {
                    ed.innerText = text;
                    updateReviewerCounters();
                    await syncLineCounters();
                }
            } else if (item.action === 'resend') {
                const input = document.getElementById('chat-input');
                if (input) {
                    input.value = text;
                    // Trigger send by simulating button click
                    const btn = document.getElementById('btn-chat-send');
                    if (btn) btn.click();
                }
            }
            menu.style.display = 'none';
        };
        menu.appendChild(div);
    });
    
    // Right-click handler
    history.addEventListener('contextmenu', (e) => {
        const msg = e.target.closest('.msg');
        if (!msg) return;
        
        e.preventDefault();
        menu._selectedText = msg.innerText;
        menu.style.display = 'block';
        menu.style.left = e.pageX + 'px';
        menu.style.top = e.pageY + 'px';
    });
    
    // Hide on click elsewhere
    document.addEventListener('click', () => {
        menu.style.display = 'none';
    });
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

        // 1. API Keys & Global Paths
        setVal('opt-deepl-key', config.deepl_api_key || '');
        setVal('opt-or-key', config.openrouter_api_key || '');
        setVal('opt-path-bible', config.bible_path || '');
        setVal('opt-path-gloss', config.glossary_path || '');
        setVal('opt-path-assets', config.assets_path || '');

        // 2. Simple Lists (Using your helper)
        renderSettingsList('set-folder-list', config.folders || [], 'folders');
        renderSettingsList('set-trigger-list', config.triggers || [], 'triggers');

        // 3. Complex Mapping Sections (The "Missing" Entries)
        renderSettingsTags(config.tag_map || {});
        renderSettingsPresets(config.presets || {});
        renderSettingsWall(config.wall_presets || {});

        // 4. Advanced Sections
        renderSettingsRules(config.replace_rules || []);
        renderSettingsArchetypes(config.archetypes || {});

        // AI Prompts
        setVal('opt-ai-system-prompt', config.ai_system_prompt || '');
        const buttonPrompts = config.ai_button_prompts || {};
        setVal('opt-ai-prompt-translate', buttonPrompts.translate || 'Translate: {text}');
        setVal('opt-ai-prompt-rephrase', buttonPrompts.rephrase || 'Rephrase this: {text}');
        setVal('opt-ai-prompt-archaize', buttonPrompts.archaize || 'Make this more archaic: {text}');
        setVal('opt-ai-prompt-check', buttonPrompts.check || 'Check this for errors: {text}');

    } catch (e) { console.error('[loadSettings] Error:', e); }
}

// =============================================================================
// SETTINGS — ACTIONS (full parity with options_module.py)
// =============================================================================
function initSettingsActions() {
    // --- PATH PICKERS ---
    async function pickBiblePath() {
        const path = await eel.pick_file("Select Bible File", [["Text Files", "*.txt"], ["Log Files", "*.log"], ["All Files", "*.*"]])();
        if (path) {
            document.getElementById('opt-path-bible').value = path;
            await eel.save_config_field('bible_path', path)();
        }
    }

    async function pickGlossPath() {
        const path = await eel.pick_file("Select Glossary File", [["CSV Files", "*.csv"], ["All Files", "*.*"]])();
        if (path) {
            document.getElementById('opt-path-gloss').value = path;
            await eel.save_config_field('glossary_path', path)();
        }
    }

    async function pickAssetsPath() {
        const path = await eel.pick_directory()();
        if (path) {
            document.getElementById('opt-path-assets').value = path;
            await eel.save_config_field('assets_path', path)();
        }
    }

    // --- FOLDERS & TRIGGERS ---
    async function addFolder() {
        const path = await eel.pick_directory()();
        if (path) {
            const updated = await eel.update_config_list('folders', 'add', path)();
            renderSettingsList('set-folder-list', updated, 'folders');
            loadDashboard(); // Refresh dash stats too
        }
    }

    async function addTrigger() {
        openInputModal('ADD TRIGGER', 'Enter new trigger string:', '', async (trig) => {
            if (trig) {
                const updated = await eel.update_config_list('triggers', 'add', trig)();
                renderSettingsList('set-trigger-list', updated, 'triggers');
            }
        });
    }

    // --- RULES MODAL ---
    function openRuleModal(index = -1) {
        state.settings.editingRuleIdx = index;
        const rule = index >= 0 ? state.settings.lastConfig.replace_rules[index] : { find: '', replace: '', flags: 'I' };

        setVal('rule-find', rule.find);
        setVal('rule-replace', rule.replace);
        document.getElementById('modal-rule').style.display = 'flex';
    }

    async function saveRule() {
        const ruleData = {
            find: document.getElementById('rule-find').value,
            replace: document.getElementById('rule-replace').value,
            flags: 'I' // Default parity
        };

        await eel.save_replace_rule(ruleData, state.settings.editingRuleIdx >= 0 ? state.settings.editingRuleIdx : null)();
        closeModals();
        loadSettings(); // Refresh the list
    }

    // --- ARCHETYPE MODAL ---
    function editArchetype(key) {
        const arch = state.settings.lastConfig.archetypes[key] || {};
        state.settings.editingArchKey = key;

        setVal('arch-key', key);
        setVal('arch-name', arch.name || '');
        setVal('arch-professions', (arch.professions || []).join(', '));
        setVal('arch-notes', arch.notes || '');

        document.getElementById('modal-archetype').style.display = 'flex';
    }

    async function saveArchetype() {
        const key = document.getElementById('arch-key').value;
        const data = {
            name: document.getElementById('arch-name').value,
            professions: parseCSVField('arch-professions'),
            notes: document.getElementById('arch-notes').value
        };

        await eel.save_archetype_data(key, data)();
        closeModals();
        loadSettings();
    }
    // --- COLOR CUSTOMIZATION ---
    async function loadColorSettings() {
        const config = state.settings.lastConfig || {};
        const darkTheme = config.custom_dark_theme || {};
        const lightTheme = config.custom_light_theme || {};

        // Load dark theme colors
        setVal('color-dark-bg', darkTheme.bg || '#11131c');
        setVal('color-dark-fg', darkTheme.fg || '#C3F5FF');
        setVal('color-dark-list-bg', darkTheme.list_bg || '#1d1f29');
        setVal('color-dark-btn-bg', darkTheme.btn_bg || '#1d1f29');
        setVal('color-dark-log-bg', darkTheme.log_bg || '#0c0e17');
        setVal('color-dark-log-fg', darkTheme.log_fg || '#C3F5FF');
        setVal('color-dark-label', darkTheme.label || '#C3F5FF');
        setVal('color-dark-button-text', darkTheme.button_text || '#C3F5FF');
        setVal('color-dark-accent', darkTheme.accent || '#00C853');
        setVal('color-dark-run-bg', darkTheme.run_bg || '#00C853');
        setVal('color-dark-border', darkTheme.border || 'rgba(195, 245, 255, 0.1)');
        setVal('color-dark-header-bg', darkTheme.header_bg || '#0c0e17');
        setVal('color-dark-panel-bg', darkTheme.panel_bg || 'rgba(29, 31, 41, 0.6)');
        setVal('color-dark-tab-inactive', darkTheme.tab_inactive || 'rgba(195, 245, 255, 0.4)');
        setVal('color-dark-glow', darkTheme.glow || 'rgba(0, 200, 83, 0.5)');
        setVal('color-dark-lore', darkTheme.lore || '#6fb3ff');
        setVal('color-dark-lore-hover', darkTheme.lore_hover || '#a8d4ff');
        setVal('color-dark-anach', darkTheme.anach || '#ffd700');
        setVal('color-dark-tooltip', darkTheme.tooltip || '#ff8800');

        // Load light theme colors
        setVal('color-light-bg', lightTheme.bg || '#F8FAFC');
        setVal('color-light-fg', lightTheme.fg || '#0F172A');
        setVal('color-light-list-bg', lightTheme.list_bg || '#FFFFFF');
        setVal('color-light-btn-bg', lightTheme.btn_bg || '#E2E8F0');
        setVal('color-light-log-bg', lightTheme.log_bg || '#1E293B');
        setVal('color-light-log-fg', lightTheme.log_fg || '#F1F5F9');
        setVal('color-light-label', lightTheme.label || '#475569');
        setVal('color-light-button-text', lightTheme.button_text || '#1E293B');
        setVal('color-light-accent', lightTheme.accent || '#2563EB');
        setVal('color-light-run-bg', lightTheme.run_bg || '#059669');
        setVal('color-light-border', lightTheme.border || '#CBD5E1');
        setVal('color-light-header-bg', lightTheme.header_bg || '#FFFFFF');
        setVal('color-light-panel-bg', lightTheme.panel_bg || '#F1F5F9');
        setVal('color-light-tab-inactive', lightTheme.tab_inactive || '#94A3B8');
        setVal('color-light-glow', lightTheme.glow || '#3B82F6');
        setVal('color-light-lore', lightTheme.lore || '#3b82f6');
        setVal('color-light-lore-hover', lightTheme.lore_hover || '#60a5fa');
        setVal('color-light-anach', lightTheme.anach || '#d97706');
        setVal('color-light-tooltip', lightTheme.tooltip || '#d97706');
    }

    async function saveColorSettings() {
        const darkTheme = {
            bg: document.getElementById('color-dark-bg').value,
            fg: document.getElementById('color-dark-fg').value,
            list_bg: document.getElementById('color-dark-list-bg').value,
            btn_bg: document.getElementById('color-dark-btn-bg').value,
            log_bg: document.getElementById('color-dark-log-bg').value,
            log_fg: document.getElementById('color-dark-log-fg').value,
            label: document.getElementById('color-dark-label').value,
            button_text: document.getElementById('color-dark-button-text').value,
            accent: document.getElementById('color-dark-accent').value,
            run_bg: document.getElementById('color-dark-run-bg').value,
            border: document.getElementById('color-dark-border').value,
            header_bg: document.getElementById('color-dark-header-bg').value,
            panel_bg: document.getElementById('color-dark-panel-bg').value,
            tab_inactive: document.getElementById('color-dark-tab-inactive').value,
            glow: document.getElementById('color-dark-glow').value,
            lore: document.getElementById('color-dark-lore').value,
            lore_hover: document.getElementById('color-dark-lore-hover').value,
            anach: document.getElementById('color-dark-anach').value,
            tooltip: document.getElementById('color-dark-tooltip').value,
        };

        const lightTheme = {
            bg: document.getElementById('color-light-bg').value,
            fg: document.getElementById('color-light-fg').value,
            list_bg: document.getElementById('color-light-list-bg').value,
            btn_bg: document.getElementById('color-light-btn-bg').value,
            log_bg: document.getElementById('color-light-log-bg').value,
            log_fg: document.getElementById('color-light-log-fg').value,
            label: document.getElementById('color-light-label').value,
            button_text: document.getElementById('color-light-button-text').value,
            accent: document.getElementById('color-light-accent').value,
            run_bg: document.getElementById('color-light-run-bg').value,
            border: document.getElementById('color-light-border').value,
            header_bg: document.getElementById('color-light-header-bg').value,
            panel_bg: document.getElementById('color-light-panel-bg').value,
            tab_inactive: document.getElementById('color-light-tab-inactive').value,
            glow: document.getElementById('color-light-glow').value,
            lore: document.getElementById('color-light-lore').value,
            lore_hover: document.getElementById('color-light-lore-hover').value,
            anach: document.getElementById('color-light-anach').value,
            tooltip: document.getElementById('color-light-tooltip').value,
        };

        await eel.save_config_field('custom_dark_theme', darkTheme)();
        await eel.save_config_field('custom_light_theme', lightTheme)();
        
        // Apply the new colors immediately
        const darkMode = state.settings.lastConfig?.dark_mode || false;
        const themeColors = await eel.get_theme_colors()();
        applyTheme(themeColors);
        updateThemeIcon(themeColors);
    }

    // Add change event listeners
    // Color picker change handlers
    document.querySelectorAll('input[type="color"]').forEach(input => {
        input.addEventListener('change', saveColorSettings);
    });

    // Theme subtab switching
    document.querySelectorAll('.theme-subtab').forEach(tab => {
        tab.addEventListener('click', function() {
            const theme = this.dataset.theme;
            
            // Update active state
            document.querySelectorAll('.theme-subtab').forEach(t => t.classList.remove('active'));
            this.classList.add('active');
            
            // Show/hide theme sections
            document.getElementById('theme-dark').style.display = theme === 'dark' ? 'block' : 'none';
            document.getElementById('theme-light').style.display = theme === 'light' ? 'block' : 'none';
        });
    });

    // Reset to defaults button
    const btnResetColors = document.getElementById('btn-reset-colors');
    if (btnResetColors) {
        btnResetColors.onclick = async () => {
            await eel.save_config_field('custom_dark_theme', {})();
            await eel.save_config_field('custom_light_theme', {})();
            await loadSettings();
            const themeColors = await eel.get_theme_colors()();
            applyTheme(themeColors);
            updateThemeIcon(themeColors);
        };
    }

    // Load colors when settings are loaded
    const originalLoadSettings = window.loadSettings;
    if (originalLoadSettings) {
        window.loadSettings = async function(...args) {
            await originalLoadSettings.apply(this, args);
            await loadColorSettings();
        };
    }

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

    // --- Path fields: save on blur ---
    const pathFields = [
        ['opt-path-bible', 'bible_path'],
        ['opt-path-gloss', 'glossary_path'],
        ['opt-path-assets', 'assets_path'],
        ['opt-deepl-lang', 'deepl_target_lang'],
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
    keyBlur('opt-or-key', 'openrouter_api_key');

    // --- Test buttons ---
    const btnTestDeepl = document.getElementById('btn-test-deepl');
    if (btnTestDeepl) btnTestDeepl.onclick = async () => {
        const key = document.getElementById('opt-deepl-key')?.value?.trim();
        if (!key) return openAlertModal('ERROR', 'Enter a DeepL API key first.');
        btnTestDeepl.innerText = 'Testing…';
        const res = await eel.test_deepl(key)();
        btnTestDeepl.innerText = 'TEST';
        if (res && res.text) openAlertModal('SUCCESS', `✓ DeepL OK — "${res.text}"`);
        else openAlertModal('ERROR', `✗ DeepL Error: ${res?.error || 'Unknown'}`);
    };

    const btnTestOR = document.getElementById('btn-test-or');
    if (btnTestOR) btnTestOR.onclick = async () => {
        const key = document.getElementById('opt-or-key')?.value?.trim();
        if (!key) return openAlertModal('ERROR', 'Enter an OpenRouter key first.');
        btnTestOR.innerText = 'Testing…';
        const res = await eel.test_openrouter(key)();
        btnTestOR.innerText = 'TEST';
        if (res && res.text) openAlertModal('SUCCESS', `✓ OpenRouter OK — "${res.text}"`);
        else openAlertModal('ERROR', `✗ OpenRouter Error: ${res?.error || 'Unknown'}`);
    };

    // --- Refresh models ---
    const btnRefresh = document.getElementById('btn-refresh-models');
    if (btnRefresh) btnRefresh.onclick = async () => {
        const key = document.getElementById('opt-or-key')?.value?.trim();
        const freeOnly = !document.getElementById('opt-show-paid')?.checked;
        if (!key) return openAlertModal('ERROR', 'Enter an OpenRouter key first.');
        btnRefresh.innerText = 'Fetching…';
        const models = await eel.fetch_models(key, freeOnly)();
        btnRefresh.innerText = 'REFRESH MODELS';
        if (models && models.length) {
            renderModelSelector(models, models[0]);
            openAlertModal('SUCCESS', `Updated — found ${models.length} model(s).`);
        } else { openAlertModal('INFO', 'No models returned.'); }
    };

    // --- PATH PICKERS ---
    const btnPickBible = document.getElementById('btn-pick-bible');
    if (btnPickBible) btnPickBible.onclick = pickBiblePath;

    const btnPickGloss = document.getElementById('btn-pick-gloss');
    if (btnPickGloss) btnPickGloss.onclick = pickGlossPath;

    const btnPickAssets = document.getElementById('btn-pick-assets');
    if (btnPickAssets) btnPickAssets.onclick = pickAssetsPath;

    // --- Folders (settings tab) ---
    const btnAddFolder = document.getElementById('btn-add-folder');
    if (btnAddFolder) btnAddFolder.onclick = async () => {
        const path = await eel.pick_directory()();
        if (path && path.trim()) { 
            await eel.add_list_item('folders', path.trim())(); 
            loadSettings(); 
        }
    };
    const btnDelFolder = document.getElementById('btn-del-folder');
    if (btnDelFolder) btnDelFolder.onclick = () => {
        const sel = state.settings.selectedFolder;
        if (!sel) return openAlertModal('ERROR', 'Select a folder first.');
        openConfirmModal('REMOVE FOLDER', `Remove "${sel}"?`, async (confirmed) => {
            if (confirmed) { await eel.remove_list_item('folders', sel)(); loadSettings(); }
        });
    };

    const btnAddTag = document.getElementById('btn-add-tag');
    if (btnAddTag) btnAddTag.onclick = () => openTagDialog(null);
    
    const btnDelTag = document.getElementById('btn-del-tag');
    if (btnDelTag) btnDelTag.onclick = () => {
        const key = state.settings.selectedTag;
        if (!key) return openAlertModal('ERROR', 'Select a tag first.');
        openConfirmModal('DELETE TAG', `Delete tag <${key}>?`, async (confirmed) => {
            if (confirmed) {
                await eel.delete_map_setting('tag_map', key)();
                loadSettings();
            }
        });
    };

    // Tag search
    const tagSearch = document.getElementById('tag-search');
    if (tagSearch) tagSearch.oninput = () => {
        state.settings.tagSearch = tagSearch.value.toLowerCase();
        if (state.settings.lastConfig)
            renderSettingsTags(state.settings.lastConfig.tag_map || {}, state.settings.tagSearch || '');
    };

    // --- Presets ---
    const btnAddLimit = document.getElementById('btn-add-limit');
    if (btnAddLimit) btnAddLimit.onclick = () => {
        openInputModal('ADD PRESET', 'Format: Name:Limit (e.g. Wide:80)', '', (res) => {
            if (!res || !res.includes(':')) return;
            const [name, val] = res.split(':');
            const limit = parseInt(val.trim());
            if (isNaN(limit)) return openAlertModal('ERROR', 'Limit must be a number.');
            eel.update_map_setting('presets', name.trim(), limit)().then(() => loadSettings());
        });
    };
    const btnEditLimit = document.getElementById('btn-edit-limit');
    if (btnEditLimit) btnEditLimit.onclick = async () => {
        const key = state.settings.selectedPreset;
        if (!key) return openAlertModal('ERROR', 'Select a preset first.');
        const currentVal = state.settings.lastConfig?.presets?.[key];
        openInputModal('EDIT PRESET', `Edit preset "${key}" (current: ${currentVal}):`, `${key}:${currentVal}`, async (res) => {
            if (!res || !res.includes(':')) return;
            const [name, val] = res.split(':');
            const limit = parseInt(val.trim());
            if (isNaN(limit)) return openAlertModal('ERROR', 'Limit must be a number.');
            await eel.delete_map_setting('presets', key)();
            await eel.update_map_setting('presets', name.trim(), limit)();
            loadSettings();
        });
    };
    const btnDelLimit = document.getElementById('btn-del-limit');
    if (btnDelLimit) btnDelLimit.onclick = () => {
        const key = state.settings.selectedPreset;
        if (!key) return openAlertModal('ERROR', 'Select a preset first.');
        openConfirmModal('DELETE PRESET', `Delete preset "${key}"?`, async (confirmed) => {
            if (confirmed) {
                await eel.delete_map_setting('presets', key)();
                loadSettings();
            }
        });
    };

    // --- Wall presets ---
    const btnAddWall = document.getElementById('btn-add-wall');
    if (btnAddWall) btnAddWall.onclick = () => {
        openInputModal('ADD WALL PRESET', 'Format: Name:MaxLines (e.g. Standard:7)', '', (res) => {
            if (!res || !res.includes(':')) return;
            const [name, val] = res.split(':');
            const lines = parseInt(val.trim());
            if (isNaN(lines)) return openAlertModal('ERROR', 'Max lines must be a whole number.');
            eel.update_map_setting('wall_presets', name.trim(), lines)().then(() => loadSettings());
        });
    };
    const btnEditWall = document.getElementById('btn-edit-wall');
    if (btnEditWall) btnEditWall.onclick = async () => {
        const key = state.settings.selectedWall;
        if (!key) return openAlertModal('ERROR', 'Select a wall preset first.');
        const currentVal = state.settings.lastConfig?.wall_presets?.[key];
        openInputModal('EDIT WALL PRESET', `Edit wall preset "${key}" (current: ${currentVal}):`, `${key}:${currentVal}`, async (res) => {
            if (!res || !res.includes(':')) return;
            const [name, val] = res.split(':');
            const lines = parseInt(val.trim());
            if (isNaN(lines)) return openAlertModal('ERROR', 'Max lines must be a whole number.');
            await eel.delete_map_setting('wall_presets', key)();
            await eel.update_map_setting('wall_presets', name.trim(), lines)();
            loadSettings();
        });
    };
    const btnDelWall = document.getElementById('btn-del-wall');
    if (btnDelWall) btnDelWall.onclick = () => {
        const key = state.settings.selectedWall;
        if (!key) return openAlertModal('ERROR', 'Select a wall preset first.');
        openConfirmModal('DELETE WALL PRESET', `Delete wall preset "${key}"?`, async (confirmed) => {
            if (confirmed) {
                await eel.delete_map_setting('wall_presets', key)();
                loadSettings();
            }
        });
    };

    // --- Rules ---
    const btnAddRule = document.getElementById('btn-add-rule');
    if (btnAddRule) btnAddRule.onclick = () => openRuleModal(-1, null);
    const btnDelRule = document.getElementById('btn-del-rule');
    if (btnDelRule) btnDelRule.onclick = () => {
        const idx = state.settings.selectedRule;
        if (idx === null || idx < 0) return openAlertModal('ERROR', 'Select a rule first.');
        const rules = [...(state.settings.lastConfig?.replace_rules || [])];
        openConfirmModal('DELETE RULE', `Delete rule "${rules[idx]?.find || ''}"?`, async (confirmed) => {
            if (confirmed) {
                rules.splice(idx, 1);
                await eel.save_replace_rules(rules)();
                state.settings.selectedRule = null;
                loadSettings();
            }
        });
    };

    // --- Triggers ---
    const btnAddTrig = document.getElementById('btn-add-trigger');
    if (btnAddTrig) btnAddTrig.onclick = async () => {
        openInputModal('ADD TRIGGER', 'Add trigger keyword:', '', async (val) => {
            if (val && val.trim()) { await eel.add_list_item('triggers', val.trim())(); loadSettings(); }
        });
    };
    const btnDelTrig = document.getElementById('btn-del-trigger');
    if (btnDelTrig) btnDelTrig.onclick = async () => {
        const sel = state.settings.selectedTrigger;
        if (!sel) return openAlertModal('ERROR', 'Select a trigger first.');
        await eel.remove_list_item('triggers', sel)();
        loadSettings();
    };

    // --- Archetypes ---
    const btnAddArch = document.getElementById('btn-add-archetype');
    if (btnAddArch) btnAddArch.onclick = () => openArchetypeModal(null, null);
    const btnResetArch = document.getElementById('btn-reset-archetypes');
    if (btnResetArch) btnResetArch.onclick = () => {
        openConfirmModal('RESET ARCHETYPES', 'Replace all archetypes with built-in defaults? Custom archetypes will be lost.', async (confirmed) => {
            if (confirmed) {
                const res = await eel.reset_archetypes_to_defaults()();
                if (res && !res.error) { openAlertModal('SUCCESS', 'Archetypes reset to defaults.'); loadSettings(); }
                else openAlertModal('ERROR', `Error: ${res?.error || 'Unknown'}`);
            }
        });
    };

    // --- Regex sandbox (live) ---
    const runSandbox = async () => {
        const pattern = document.getElementById('regex-pattern')?.value || '';
        const repl = document.getElementById('regex-replace')?.value || '';
        const input = document.getElementById('regex-input')?.value || '';
        const out = document.getElementById('regex-output');
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

function renderSettingsTags(tagMap, searchTerm = '') {
    const el = document.getElementById('tag-list');
    if (!el) return;
    const filteredMap = searchTerm 
        ? Object.fromEntries(Object.entries(tagMap).filter(([key, val]) => 
            key.toLowerCase().includes(searchTerm) || val.toLowerCase().includes(searchTerm)
          ))
        : tagMap;
    el.innerHTML = '';
    Object.entries(filteredMap).forEach(([key, val]) => {
        const div = document.createElement('div');
        div.className = 'mapping-item';
        if (state.settings.selectedTag === key) div.classList.add('selected');
        div.innerHTML = `
            <span class="tag-key">${key}</span>
            <span class="tag-arrow">-></span>
            <span class="tag-val">${val}</span>
            <button class="btn-secondary sm" onclick="editTagMapping('${key}', '${val}')">EDIT</button>
        `;
        div.onclick = (e) => {
            if (e.target.tagName === 'BUTTON') return;
            el.querySelectorAll('.mapping-item').forEach(el => el.classList.remove('selected'));
            div.classList.add('selected');
            state.settings.selectedTag = key;
        };
        el.appendChild(div);
    });
}

async function deleteMapping(section, key) {
    openConfirmModal('DELETE MAPPING', `Delete "${key}" from ${section}?`, async (confirmed) => {
        if (confirmed) {
            await eel.delete_map_setting(section, key)();
            loadSettings();
        }
    });
}

async function editTagMapping(key, currentValue) {
    openInputModal('EDIT TAG', `Edit value for "${key}":`, currentValue, async (newValue) => {
        if (newValue === null || newValue === currentValue) return;
        await eel.update_map_setting('tag_map', key, newValue)();
        loadSettings();
    });
}

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
            rule.whole_word ? 'WORD' : '',
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
    Object.entries(archetypes).sort(([a], [b]) => a.localeCompare(b)).forEach(([key, data]) => {
        const row = document.createElement('div');
        row.className = 'archetype-row';
        row.innerHTML = `
            <div class="arch-key">${escHtml(key)}</div>
            <div class="arch-name">${escHtml(data.name || '')}</div>
            <div class="arch-notes">${escHtml((data.notes || '').slice(0, 80))}${(data.notes || '').length > 80 ? '…' : ''}</div>
            <button class="btn-secondary sm arch-edit" data-key="${escAttr(key)}">EDIT</button>
            <button class="btn-secondary sm arch-del"  data-key="${escAttr(key)}">DEL</button>`;
        row.querySelector('.arch-edit').onclick = () => openArchetypeModal(key, data);
        row.querySelector('.arch-del').onclick = () => {
            openConfirmModal('DELETE ARCHETYPE', `Delete archetype "${key}"?`, async (confirmed) => {
                if (confirmed) {
                    await eel.delete_archetype(key)();
                    loadSettings();
                }
            });
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
    
    // Also update the reviewer page AI model dropdown
    const reviewerSel = document.getElementById('ai-model-select');
    if (reviewerSel) {
        reviewerSel.innerHTML = '';
        (models.length ? models : ['openrouter/auto']).forEach(m => {
            const opt = document.createElement('option');
            opt.value = opt.innerText = m;
            if (m === selected) opt.selected = true;
            reviewerSel.appendChild(opt);
        });
        reviewerSel.onchange = async () => {
            await eel.save_config_field('selected_openrouter_model', reviewerSel.value)();
        };
    }
}

// Helper: render settings list
function renderSettingsList(containerId, items, configKey) {
    const list = document.getElementById(containerId);
    if (!list) return;
    list.innerHTML = '';
    items.forEach(item => {
        const li = buildSelectableLi(item, () => { 
            if (configKey === 'folders') state.settings.selectedFolder = item;
            else if (configKey === 'triggers') state.settings.selectedTrigger = item;
        }, list);
        list.appendChild(li);
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

    // Input modal
    document.getElementById('btn-input-cancel')?.addEventListener('click',
        () => document.getElementById('modal-input').classList.remove('active'));

    // Close on backdrop click
    document.querySelectorAll('.modal').forEach(modal => {
        modal.addEventListener('click', e => {
            if (e.target === modal) modal.classList.remove('active');
        });
    });
}

let inputModalCallback = null;

function openInputModal(title, message, defaultValue = '', callback) {
    const modal = document.getElementById('modal-input');
    const titleEl = document.getElementById('input-modal-title');
    const messageEl = document.getElementById('input-modal-message');
    const field = document.getElementById('input-modal-field');
    
    titleEl.innerText = title;
    messageEl.innerText = message;
    field.value = defaultValue;
    inputModalCallback = callback;
    
    modal.classList.add('active');
    field.focus();
    field.select();
}

document.getElementById('btn-input-save')?.addEventListener('click', () => {
    const field = document.getElementById('input-modal-field');
    if (inputModalCallback) {
        inputModalCallback(field.value);
        inputModalCallback = null;
    }
    document.getElementById('modal-input').classList.remove('active');
});

let confirmModalCallback = null;

function openConfirmModal(title, message, callback) {
    const modal = document.getElementById('modal-confirm');
    const titleEl = document.getElementById('confirm-modal-title');
    const messageEl = document.getElementById('confirm-modal-message');
    
    titleEl.innerText = title;
    messageEl.innerText = message;
    confirmModalCallback = callback;
    
    modal.classList.add('active');
}

document.getElementById('btn-confirm-cancel')?.addEventListener('click', () => {
    if (confirmModalCallback) {
        confirmModalCallback(false);
        confirmModalCallback = null;
    }
    document.getElementById('modal-confirm').classList.remove('active');
});

document.getElementById('btn-confirm-ok')?.addEventListener('click', () => {
    if (confirmModalCallback) {
        confirmModalCallback(true);
        confirmModalCallback = null;
    }
    document.getElementById('modal-confirm').classList.remove('active');
});

function openAlertModal(title, message) {
    const modal = document.getElementById('modal-alert');
    const titleEl = document.getElementById('alert-modal-title');
    const messageEl = document.getElementById('alert-modal-message');
    
    titleEl.innerText = title;
    messageEl.innerText = message;
    
    modal.classList.add('active');
}

document.getElementById('btn-alert-ok')?.addEventListener('click', () => {
    document.getElementById('modal-alert').classList.remove('active');
});

function openRuleModal(idx, rule) {
    state.settings.editingRuleIdx = idx;
    setVal('rule-find', rule?.find ?? '');
    setVal('rule-replace', rule?.replace ?? '');
    setVal('rule-speakers', (rule?.speakers || []).join(', '));
    setVal('rule-types', (rule?.entry_types || []).join(', '));
    setCheck('rule-case', rule?.case_sensitive || false);
    setCheck('rule-word', rule?.whole_word || false);
    document.getElementById('modal-rule').classList.add('active');
    document.getElementById('rule-find')?.focus();
}

async function saveRule() {
    const find = document.getElementById('rule-find')?.value?.trim();
    if (!find) return openAlertModal('ERROR', 'Find pattern is required.');

    const rule = {
        find,
        replace: document.getElementById('rule-replace')?.value ?? '',
        case_sensitive: document.getElementById('rule-case')?.checked || false,
        whole_word: document.getElementById('rule-word')?.checked || false,
        speakers: parseCSVField('rule-speakers'),
        entry_types: parseCSVField('rule-types'),
    };

    const rules = [...(state.settings.lastConfig?.replace_rules || [])];
    const idx = state.settings.editingRuleIdx;
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
    setVal('arch-key', key ?? '');
    setVal('arch-name', data?.name ?? '');
    setVal('arch-professions', (data?.professions || []).join(', '));
    setVal('arch-pawn-map', data?.pawn_map ?? '');
    setVal('arch-notes', data?.notes ?? '');
    document.getElementById('modal-archetype').classList.add('active');
    document.getElementById('arch-key')?.focus();
}

async function saveArchetype() {
    const key = document.getElementById('arch-key')?.value?.trim();
    const name = document.getElementById('arch-name')?.value?.trim();
    if (!key || !name) return openAlertModal('ERROR', 'Key and Name are required.');
    const profs = parseCSVField('arch-professions');
    const pawn = document.getElementById('arch-pawn-map')?.value?.trim() ?? '';
    const notes = document.getElementById('arch-notes')?.value?.trim() ?? '';

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
    const defaultVal = existingKey ? `${existingKey} : ` : '';
    openInputModal(existingKey ? 'EDIT TAG' : 'ADD TAG', prompt_str.replace(/\n/g, ' '), defaultVal, async (res) => {
        if (!res || !res.includes(':')) return;
        const [tagRaw, valueRaw] = res.split(':', 2);
        const tag = tagRaw.trim();
        const value = valueRaw.trim();
        if (!tag) return;
        await eel.update_map_setting('tag_map', tag, value)();
        loadSettings();
    });
}

// =============================================================================
// SEARCH
// =============================================================================
function initSearchActions() {
    const btnSearch = document.getElementById('btn-db-search');
    const btnOpenAll = document.getElementById('btn-search-open-all');
    const searchInput = document.getElementById('db-search-input');

    if (btnSearch) btnSearch.onclick = doSearch;
    if (searchInput) searchInput.onkeydown = e => { if (e.key === 'Enter') doSearch(); };

    if (btnOpenAll) btnOpenAll.onclick = async () => {
        if (!state.search.results.length) return;
        // Clear manual translation queue to avoid mixing with batch results
        await eel.clear_queue()();
        const items = state.search.results.map(r => ({
            speaker: r.speaker || 'Unknown', jp: r.jp, en: r.en,
            category: r.category || 'SEARCH_RESULT', path: r.path, row: r.row,
        }));
        await eel.bulk_inject(items)();
        state.reviewer.mode = 'translate';
        // Set current category to Manual Translation for search results
        state.reviewer.currentCategory = "Manual Translation";
        // Save search results that were sent to editor for restoration
        state.search.sentToEditor = state.search.results;
        // Refresh queue structure to update category counts
        const queueStructure = await eel.get_queue_structure()();
        state.reviewer.queueStructure = queueStructure;
        populateCategorySelector(queueStructure);
        // Re-fetch full queue from Python (bulk_inject updated it server-side)
        state.reviewer.fullQueue = await eel.get_all_items_in_queue()() || [];
        switchTab('reviewer');
    };

    // Field selector — wire search-on-enter on the select too
    const fieldSel = document.getElementById('db-search-field');
    if (fieldSel) fieldSel.onkeydown = e => { if (e.key === 'Enter') doSearch(); };
}

async function doSearch() {
    const query = document.getElementById('db-search-input')?.value?.trim();
    const field = document.getElementById('db-search-field')?.value;
    const statusEl = document.getElementById('search-status');

    if (!query) return;
    if (statusEl) statusEl.innerText = 'Searching…';

    const fieldCol = field === 'all' ? null : parseInt(field);
    const results = await eel.perform_search(query, fieldCol)();
    state.search.results = results || [];
    renderSearchResults(state.search.results);
    if (statusEl) {
        const n = state.search.results.length;
        statusEl.innerText = `Found ${n} result${n !== 1 ? 's' : ''}.`;
    }
}

function renderSearchResults(results) {
    const body = document.getElementById('search-results-body');
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
            <td>${escHtml((res.en || '').replace(/\n/g, ' '))}</td>`;
        tr.style.cursor = 'pointer';
        tr.onclick = () => openSearchHitInReviewer(res, idx);
        body.appendChild(tr);
    });
    if (bulkBox) bulkBox.style.display = results.length > 0 ? 'block' : 'none';
}

async function openSearchHitInReviewer(res) {
    const item = {
        speaker: res.speaker || 'Unknown', jp: res.jp || res.match, en: res.en,
        category: res.category || 'SEARCH_RESULT', path: res.path, row: res.row,
    };
    await eel.bulk_inject([item])();
    state.reviewer.mode = 'translate';
    // Set current category to Manual Translation for search results
    state.reviewer.currentCategory = "Manual Translation";
    state.reviewer.fullQueue = await eel.get_all_items_in_queue()() || [];
    switchTab('reviewer');
    loadItemAtIdx(0);
}

// =============================================================================
// KEYBOARD SHORTCUTS
// =============================================================================
const undoStack = [];
const redoStack = [];
const MAX_UNDO = 50;

function saveUndoState() {
    const ed = document.getElementById('en-editor');
    if (!ed) return;
    undoStack.push(ed.innerText);
    if (undoStack.length > MAX_UNDO) undoStack.shift();
    redoStack.length = 0; // Clear redo stack on new action
}

function undo() {
    if (undoStack.length === 0) return;
    const ed = document.getElementById('en-editor');
    if (!ed) return;
    redoStack.push(ed.innerText);
    const previous = undoStack.pop();
    ed.innerText = previous;
    updateReviewerCounters();
    syncLineCounters();
    const jpText = document.getElementById('jp-source')?.innerText || '';
    populateLoreContext(jpText, ed.innerText, state.reviewer.currentIdx);
}

function redo() {
    if (redoStack.length === 0) return;
    const ed = document.getElementById('en-editor');
    if (!ed) return;
    undoStack.push(ed.innerText);
    const next = redoStack.pop();
    ed.innerText = next;
    updateReviewerCounters();
    syncLineCounters();
    const jpText = document.getElementById('jp-source')?.innerText || '';
    populateLoreContext(jpText, ed.innerText, state.reviewer.currentIdx);
}

function initShortcuts() {
    window.addEventListener('keydown', e => {
        if (state.currentTab !== 'reviewer') return;
        if (e.ctrlKey) {
            if (e.key === 'Enter') { e.preventDefault(); applyFix(); }
            if (e.key === 'ArrowRight') { e.preventDefault(); nextItem(); }
            if (e.key === 'ArrowLeft') { e.preventDefault(); prevItem(); }
            if (e.key === 'r' || e.key === 'R') { e.preventDefault(); rewrapEditor(); }
            if (e.key === 'd' || e.key === 'D') {
                e.preventDefault();
                replaceDashes(e.shiftKey ? '...' : '—');
            }
            if (e.key === 'z' || e.key === 'Z') {
                if (e.shiftKey) {
                    e.preventDefault();
                    redo();
                } else {
                    e.preventDefault();
                    undo();
                }
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
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}
function escAttr(s) { return escHtml(s); }
