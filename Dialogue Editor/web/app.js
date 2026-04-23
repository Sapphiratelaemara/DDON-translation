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
            reviewerMode: true,      // Crowdin-style reviewer mode - always enabled
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
    
    // Save panel visibility states
    const commentsPanel = document.getElementById('panel-comments');
    const historyPanel = document.getElementById('panel-history');
    const aiPanel = document.getElementById('panel-ai');
    const refsPanel = document.getElementById('panel-references');
    const archetypePanel = document.getElementById('panel-archetype');
    
    const toSave = {
        currentTab: state.currentTab,
        reviewer: {
            currentIdx: state.reviewer.currentIdx,
            mode: state.reviewer.mode,
            lastFolder: state.reviewer.lastFolder,
            // Don't save fullQueue - it should always be fetched from backend to avoid stale data
            showTranslated: showTranslated
            // reviewerMode is always true now
        },
        search: state.search || {},
        panels: {
            comments: commentsPanel ? !commentsPanel.classList.contains('collapsed') : true,
            history: historyPanel ? !historyPanel.classList.contains('collapsed') : true,
            ai: aiPanel ? !aiPanel.classList.contains('collapsed') : true,
            references: refsPanel ? !refsPanel.classList.contains('collapsed') : true,
            archetype: archetypePanel ? !archetypePanel.classList.contains('collapsed') : true
        }
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
        
        // Reviewer mode is always enabled
        
        // Load initial data
        await loadDashboard();
        await loadSettings();
        
        // Load saved queue structure to populate category dropdown
        const queueStructure = await eel.get_queue_structure()();
        state.reviewer.queueStructure = queueStructure;
        populateCategorySelector(queueStructure);
        console.log('[INIT] Loaded queue structure:', queueStructure);
        
        // Restore show filter dropdown
        const showFilterSelect = document.getElementById('show-filter');
        if (showFilterSelect && state.reviewer.showFilter) {
            showFilterSelect.value = state.reviewer.showFilter;
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
        // Restore tab first (before any other operations that might switch tabs)
        console.log('[INIT] currentTab before restore:', state.currentTab);
        if (state.currentTab && state.currentTab !== 'dashboard') {
            console.log('[INIT] Restoring to tab:', state.currentTab);
            switchTab(state.currentTab);
        } else {
            console.log('[INIT] No saved tab, switching to dashboard');
            switchTab('dashboard');
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
        // Save state and sync on exit
        window.addEventListener('beforeunload', () => {
            saveState();
            // Trigger sync flush - fire-and-forget, browser may kill it
            try {
                eel.shutdown_app()();
            } catch (e) {}
        });
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
            // Show modal to switch to Editor
            if (firstCategory) {
                const itemCount = queueStructure[firstCategory].count;
                console.log('[pollBatchScanCompletion] Found', itemCount, 'items in category:', firstCategory);
                openConfirmModal('SCAN COMPLETE', `Found ${itemCount} items. Switch to Editor?`, (confirmed) => {
                    if (confirmed) {
                        state.reviewer.mode = 'review';
                        switchTab('editor');
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

    // Add Unapproved Entries option first
    const unapprovedOption = document.createElement('option');
    unapprovedOption.value = "Unapproved Entries";
    unapprovedOption.innerText = "Unapproved Entries";
    select.appendChild(unapprovedOption);
    console.log('[populateCategorySelector] Added Unapproved Entries option');

    // Always show Manual Translation
    if (queueStructure["Manual Translation"]) {
        const manualOption = document.createElement('option');
        manualOption.value = "Manual Translation";
        const count = queueStructure["Manual Translation"].count;
        manualOption.innerText = count > 0 ? `Manual Translation (${count})` : "Manual Translation";
        select.appendChild(manualOption);
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

// Separate flag for category switching to avoid conflict with load queue processing
let isProcessingCategorySwitch = false;

async function switchCategory(categoryDisplayName) {
    console.log('[switchCategory] Switching to category:', categoryDisplayName);
    if (!categoryDisplayName) return;

    // Prevent duplicate category switches
    if (isProcessingCategorySwitch) {
        console.log('[switchCategory] Category switch already in progress, skipping');
        return;
    }
    isProcessingCategorySwitch = true;

    try {
        // Wait a bit to ensure any pending load operations complete
        await new Promise(resolve => setTimeout(resolve, 50));

        // Clear both caches to prevent stale cache hits when switching categories
        await eel.clear_prefetch_cache()();
        await eel.clear_gloss_cache()();
        console.log('[switchCategory] Caches cleared');

        // Handle different category types
        if (categoryDisplayName === "Unapproved Entries") {
            console.log('[switchCategory] Loading unapproved entries');
            const res = await eel.get_unapproved_entries_with_comments()();
            if (res && res.ok) {
                // Convert to queue format with comment count
                state.reviewer.fullQueue = res.entries.map((item, idx) => ({
                    id: item.entry.id,
                    speaker: item.entry.speaker || "Unknown",
                    jp: item.entry.source_text,
                    en: item.entry.translated_text,
                    category: "UNAPPROVED",
                    path: item.entry.file_path,
                    row: item.entry.row_index,
                    entry_type: item.entry.entry_type,
                    comment_count: item.comment_count
                }));
                console.log('[switchCategory] Loaded unapproved entries, count:', state.reviewer.fullQueue.length);
            } else {
                console.error('[switchCategory] Failed to load unapproved entries:', res?.error);
                state.reviewer.fullQueue = [];
            }
        } else if (categoryDisplayName === "Manual Translation") {
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
        if (state.reviewer.fullQueue.length > 0) {
            console.log('[switchCategory] Item at idx 0:', state.reviewer.fullQueue[0]);
            await loadItemAtIdx(0);
        } else {
            console.log('[switchCategory] Queue is empty, skipping item load');
        }
    } finally {
        isProcessingCategorySwitch = false;
        console.log('[switchCategory] Reset isProcessingCategorySwitch flag');
    }
}

function updateThemeIcon(colors) {
    const icon = document.querySelector('.theme-icon');
    if (icon) {
        const isDark = colors.bg === '#1a1a2e';
        icon.textContent = isDark ? 'light_mode' : 'dark_mode';
    }
}

function applyTheme(colors) {
    const root = document.documentElement;
    for (const [key, value] of Object.entries(colors)) {
        if (value !== undefined && value !== null) {
            root.style.setProperty(`--color-${key}`, value);
        }
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
    
    // Show/hide panel toggles - only in editor
    const panelToggles = document.querySelector('.panel-toggles');
    if (panelToggles) {
        panelToggles.classList.toggle('hidden', tabId !== 'editor');
    }
    
    if (tabId === 'editor') {
        // Only clear gloss cache (prefetch cache persists across tab switches)
        eel.clear_gloss_cache()().then(() => {
            console.log('[switchTab] Gloss cache cleared');
            
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
                        state.reviewer.currentIdx = 0;
                        state.reviewer.currentItem = null;  // Reset to force reload
                        renderRowSidebar();
                        if (state.reviewer.fullQueue.length > 0) {
                            loadItemAtIdx(0);
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
            switchTab('editor');
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
    const aiPanel = document.getElementById('panel-ai'); // AI Assistant panel
    const commentsPanel = document.getElementById('panel-comments');
    const historyPanel = document.getElementById('panel-history');
    const nonAiPanels = sidebarRight?.querySelectorAll('#panel-references, #panel-archetype');
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
        // Check if Comments or History panels are visible
        const commentsVisible = commentsPanel && !commentsPanel.classList.contains('collapsed');
        const historyVisible = historyPanel && !historyPanel.classList.contains('collapsed');
        // Right sidebar collapsed if no panels visible
        const rightCollapsed = !anyContextVisible && !aiVisible && !commentsVisible && !historyVisible;
        // Update footer
        footer?.classList.toggle('with-right-collapsed', rightCollapsed);
        // Update main workspace margin
        mainWorkspace?.classList.toggle('no-right-sidebar', rightCollapsed);
        // Update right sidebar collapse state
        sidebarRight.classList.toggle('collapsed', rightCollapsed);
    }
    
    // COMMENTS and HISTORY panel toggles - declare before use
    const btnToggleComments = document.getElementById('btn-toggle-comments');
    const btnToggleHistory = document.getElementById('btn-toggle-history');
    
    // Initialize: restore panel visibility from saved state
    const savedPanels = state.panels || {};
    
    // Restore References and Archetype panels (controlled by btnToggleRefs)
    const refsCollapsed = savedPanels.references === false;
    const archetypeCollapsed = savedPanels.archetype === false;
    if (nonAiPanels) {
        nonAiPanels.forEach(p => {
            if (p.id === 'panel-references') p.classList.toggle('collapsed', refsCollapsed);
            if (p.id === 'panel-archetype') p.classList.toggle('collapsed', archetypeCollapsed);
        });
    }
    // Update btnToggleRefs active state based on any non-AI panel being visible
    if (btnToggleRefs) {
        const anyNonAiVisible = nonAiPanels && Array.from(nonAiPanels).some(p => !p.classList.contains('collapsed'));
        btnToggleRefs.classList.toggle('active', anyNonAiVisible);
    }
    
    // Restore AI panel
    const aiCollapsed = savedPanels.ai === false;
    if (aiPanel) aiPanel.classList.toggle('collapsed', aiCollapsed);
    if (btnToggleAi) btnToggleAi.classList.toggle('active', !aiCollapsed);
    
    // Restore Comments panel
    const commentsCollapsed = savedPanels.comments === false;
    if (commentsPanel) commentsPanel.classList.toggle('collapsed', commentsCollapsed);
    if (btnToggleComments) btnToggleComments.classList.toggle('active', !commentsCollapsed);
    
    // Restore History panel
    const historyCollapsed = savedPanels.history === false;
    if (historyPanel) historyPanel.classList.toggle('collapsed', historyCollapsed);
    if (btnToggleHistory) btnToggleHistory.classList.toggle('active', !historyCollapsed);
    
    updateRightSidebarState();
    if (btnToggleRefs && nonAiPanels) {
        btnToggleRefs.onclick = () => {
            const anyVisible = Array.from(nonAiPanels).some(p => !p.classList.contains('collapsed'));
            const willCollapse = anyVisible; // If any visible, collapse all
            nonAiPanels.forEach(p => p.classList.toggle('collapsed', willCollapse));
            btnToggleRefs.classList.toggle('active', !willCollapse);
            updateRightSidebarState();
            saveState();
        };
    }
    
    // AI_ASSISTANT toggle = AI panel only (within sidebar)
    if (btnToggleAi && aiPanel) {
        btnToggleAi.onclick = () => {
            const willCollapse = !aiPanel.classList.contains('collapsed');
            aiPanel.classList.toggle('collapsed', willCollapse);
            btnToggleAi.classList.toggle('active', !willCollapse);
            updateRightSidebarState();
            saveState();
        };
    }
    
    if (btnToggleComments) btnToggleComments.classList.add('active');
    if (btnToggleHistory) btnToggleHistory.classList.add('active');
    
    if (btnToggleComments && commentsPanel) {
        btnToggleComments.onclick = () => {
            const willCollapse = !commentsPanel.classList.contains('collapsed');
            commentsPanel.classList.toggle('collapsed', willCollapse);
            btnToggleComments.classList.toggle('active', !willCollapse);
            updateRightSidebarState();
            saveState();
        };
    }
    
    if (btnToggleHistory && historyPanel) {
        btnToggleHistory.onclick = () => {
            const willCollapse = !historyPanel.classList.contains('collapsed');
            historyPanel.classList.toggle('collapsed', willCollapse);
            btnToggleHistory.classList.toggle('active', !willCollapse);
            updateRightSidebarState();
            saveState();
        };
    }
    
    // Show/hide panel toggles based on tab - ensure correct state for current tab
    if (panelToggles) {
        const shouldShow = state.currentTab === 'editor';
        panelToggles.classList.toggle('hidden', !shouldShow);
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
    setupToggle('editor-in-universe', 'in_universe');
    setupToggle('dash-preview-mode', 'preview_mode');
}

async function loadDashboard() {
    try {
        const data = await eel.get_dashboard_data()();
        if (!data) return;
        document.getElementById('stat-folders').innerText = (data.folders || []).length;
        document.getElementById('stat-files').innerText = data.file_count || 0;

        const iu = document.getElementById('editor-in-universe');
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
let isProcessingLoadQueue = false;

async function processLoadQueue() {
    if (isProcessingLoadQueue || loadQueue.length === 0) {
        return;
    }

    isProcessingLoadQueue = true;
    const { idx, resolve } = loadQueue.shift();

    console.log(`[processLoadQueue] Processing load request for idx=${idx}, queue length=${loadQueue.length}, currentIdx=${state.reviewer.currentIdx}`);

    try {
        await loadItemAtIdxInternal(idx);
        resolve();
    } catch (e) {
        console.error('[processLoadQueue] Error:', e);
        resolve();
    }

    isProcessingLoadQueue = false;

    // Process next request in queue
    if (loadQueue.length > 0) {
        processLoadQueue();
    }
}

async function loadItemAtIdx(idx) {
    console.log(`[loadItemAtIdx] Called with idx=${idx}, queue length=${loadQueue.length}, isProcessing=${isProcessingLoadQueue}`);
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
                const sidebarCounter = document.getElementById('sidebar-queue-count');
                if (sidebarCounter) sidebarCounter.innerText = '0 / 0';
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
                const sidebarCounter = document.getElementById('sidebar-queue-count');
                if (sidebarCounter) sidebarCounter.innerText = '0 / 0';
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
        
        // Suppress input events while loading new item text
        if (enEditor && enEditor._setSkipInputHandling) enEditor._setSkipInputHandling(true);
        if (jpEditor && jpEditor._setSkipInputHandling) jpEditor._setSkipInputHandling(true);
        
        if (enEditor) enEditor.innerText = '';
        if (jpEditor) jpEditor.innerText = '';
        
        if (enEditor) enEditor.innerText = (item.en || '').replace(/★/g, '');
        
        // Re-enable input events after loading
        if (enEditor && enEditor._setSkipInputHandling) enEditor._setSkipInputHandling(false);
        if (jpEditor && jpEditor._setSkipInputHandling) jpEditor._setSkipInputHandling(false);
        
        // Ensure editor has focus so Enter key works immediately
        if (enEditor) enEditor.focus();
        
        const sidebarCounter = document.getElementById('sidebar-queue-count');
        if (sidebarCounter) sidebarCounter.innerText = `${idx + 1} / ${items.length}`;
        
        // Use cached lore context if available, otherwise fetch it
        if (cached && cached.lore_context) {
            populateSourceWithLoreHighlightsFromCache(item.jp, item.en || '', cached.lore_context);
        } else {
            await populateSourceWithLoreHighlights(item.jp, item.en || '');
        }

        updateReviewerCounters();
        syncLineCounters();
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

        // Update Crowdin-style translation status and history
        if (item.id) {
            updateTranslationStatusBadge(item.id);
            loadTranslationHistory(item.id);
            loadTranslationComments(item.id);
        }
    } catch (e) {
        console.error('[loadItemAtIdx] Error:', e);
    }
}

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
    bind('show-filter', 'onchange', renderRowSidebar);
    bind('filter-speaker', 'onchange', renderRowSidebar);
    bind('filter-entry-type', 'onchange', renderRowSidebar);
    bind('btn-clear-filters', 'onclick', clearFilters);
    bind('btn-apply-filters', 'onclick', () => {
        renderRowSidebar();
        document.getElementById('filter-dropdown').style.display = 'none';
    });

    // Crowdin-style reviewer mode controls (always enabled)
    bind('btn-approve', 'onclick', approveCurrentTranslation);
    bind('btn-reject', 'onclick', rejectCurrentTranslation);
    bind('btn-add-comment', 'onclick', addTranslationComment);

    // Comment character counter
    const commentInput = document.getElementById('comment-input');
    const charCounter = document.getElementById('comment-char-counter');
    if (commentInput && charCounter) {
        const MAX_COMMENT_LEN = 5000;
        const WARNING_THRESHOLD = 4000;
        
        function updateCharCounter() {
            const len = commentInput.value.length;
            charCounter.textContent = `${len} / ${MAX_COMMENT_LEN}`;
            
            charCounter.classList.remove('warning', 'error');
            if (len >= MAX_COMMENT_LEN) {
                charCounter.classList.add('error');
            } else if (len >= WARNING_THRESHOLD) {
                charCounter.classList.add('warning');
            }
        }
        
        commentInput.addEventListener('input', updateCharCounter);
        commentInput.addEventListener('focus', updateCharCounter);
    }

    // In-universe toggle
    const setupToggle = (id, key) => {
        const el = document.getElementById(id);
        if (el) el.onchange = async () => { await eel.save_config_field(key, el.checked)(); };
    };
    setupToggle('reviewer-in-universe', 'in_universe');

    const ed = document.getElementById('en-editor');
    if (ed) {
        let skipCursorRestore = false;
        let skipInputHandling = false;  // Flag to skip input event during undo/redo
        
        ed.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                console.log(`[Enter key] pressed, target=${e.target?.id}, activeElement=${document.activeElement?.id}`);
                
                // CRITICAL: Set flag BEFORE any DOM changes so input event knows Enter was pressed
                ed._justPressedEnter = true;
                console.log(`[Enter key] _justPressedEnter flag set to true`);
                
                // Log DOM structure before Enter
                let domDump = '';
                for (let i = 0; i < ed.childNodes.length; i++) {
                    const n = ed.childNodes[i];
                    if (n.nodeType === Node.TEXT_NODE) domDump += `TEXT(${n.length}) `;
                    else if (n.nodeName === 'BR') domDump += 'BR ';
                    else domDump += `${n.nodeName} `;
                }
                console.log(`[Enter key] DOM before: ${domDump}`);
                console.log(`[Enter key] innerText="${ed.innerText.substring(0,60)}"`);
                e.preventDefault();
                const selection = window.getSelection();
                console.log(`[Enter key] rangeCount=${selection.rangeCount}, isCollapsed=${selection.isCollapsed}`);
                if (selection.rangeCount > 0) {
                    console.log(`[Enter key] Processing - range found`);
                    const range = selection.getRangeAt(0);
                    console.log(`[Enter key] Range: startContainer=${range.startContainer?.nodeName}, startOffset=${range.startOffset}, endContainer=${range.endContainer?.nodeName}, endOffset=${range.endOffset}`);
                    
                    // Get the text node and offset where cursor is
                    const textNode = range.startContainer;
                    const offset = range.startOffset;
                    let br;
                    
                    // Insert BR at cursor position
                    if (textNode.nodeType === Node.TEXT_NODE) {
                        br = document.createElement('br');
                        
                        if (offset === textNode.length) {
                            // Cursor at end of text node - insert BR and text node with zero-width space
                            if (textNode.nextSibling) {
                                textNode.parentNode.insertBefore(br, textNode.nextSibling);
                            } else {
                                textNode.parentNode.appendChild(br);
                            }
                            // Create text node with zero-width space (invisible, makes line navigable)
                            const zwspNode = document.createTextNode('\u200B');
                            if (br.nextSibling) {
                                br.parentNode.insertBefore(zwspNode, br.nextSibling);
                            } else {
                                br.parentNode.appendChild(zwspNode);
                            }
                            // Position cursor in the zero-width space node
                            range.setStart(zwspNode, 0);
                            console.log(`[Enter key] BR and ZWSP text node inserted, cursor positioned`);
                        } else {
                            // Cursor in middle of text - split the node
                            const afterText = textNode.textContent.substring(offset);
                            textNode.textContent = textNode.textContent.substring(0, offset);
                            const afterNode = document.createTextNode(afterText);
                            textNode.parentNode.insertBefore(br, textNode.nextSibling);
                            textNode.parentNode.insertBefore(afterNode, br.nextSibling);
                        }
                        
                        // Position cursor after the BR - browser will handle creating text node if needed
                        range.setStartAfter(br);
                        console.log(`[Enter key] BR inserted, cursor positioned after BR`);
                    } else {
                        // Fallback for non-text containers
                        br = document.createElement('br');
                        range.deleteContents();
                        range.insertNode(br);
                        range.setStartAfter(br);
                    }
                    console.log(`[Enter key] BR inserted, nextSibling=${br.nextSibling?.nodeName}, nodeType=${br.nextSibling?.nodeType}`);
                    // Log actual text content of each node
                    for (let i = 0; i < ed.childNodes.length; i++) {
                        const n = ed.childNodes[i];
                        if (n.nodeType === Node.TEXT_NODE) {
                            console.log(`[Enter key] Node ${i}: TEXT(${n.length})="${n.textContent.replace(/\n/g, '\\n').substring(0,30)}"`);
                        }
                    }
                    
                    // Log DOM immediately after BR insertion
                    let domDumpAfterBR = '';
                    for (let i = 0; i < ed.childNodes.length; i++) {
                        const n = ed.childNodes[i];
                        if (n === br) domDumpAfterBR += `**NEW_BR** `;
                        else if (n.nodeType === Node.TEXT_NODE) domDumpAfterBR += `TEXT(${n.length}) `;
                        else if (n.nodeName === 'BR') domDumpAfterBR += 'BR ';
                        else domDumpAfterBR += `${n.nodeName} `;
                    }
                    console.log(`[Enter key] DOM after BR insert: ${domDumpAfterBR}`);
                    // Set the range without focus() which might interfere
                    range.collapse(true);
                    selection.removeAllRanges();
                    selection.addRange(range);
                    
                    // Force reflow to ensure visual cursor update
                    void ed.offsetHeight;
                    
                    console.log(`[Enter key] innerText RIGHT AFTER cursor set: "${ed.innerText.substring(0,80).replace(/\n/g, '\\n')}"`);
                    
                    // IMMEDIATE verification - get fresh selection right after setting it
                    const freshSel = window.getSelection();
                    const freshRange = freshSel.rangeCount > 0 ? freshSel.getRangeAt(0) : null;
                    const freshNodeIndex = Array.from(ed.childNodes).indexOf(freshRange?.endContainer);
                    console.log(`[Enter key] FRESH cursor check - nodeIndex=${freshNodeIndex}, endOffset=${freshRange?.endOffset}, text="${freshRange?.endContainer?.textContent?.substring(0,20)}"`);
                    
                    // Dump DOM for debugging
                    let domAtCalc = '';
                    for (let i = 0; i < ed.childNodes.length; i++) {
                        const n = ed.childNodes[i];
                        if (n.nodeType === Node.TEXT_NODE) domAtCalc += `TEXT(${n.length}) `;
                        else if (n.nodeName === 'BR') domAtCalc += 'BR ';
                        else domAtCalc += `${n.nodeName} `;
                    }
                    console.log(`[Enter key] DOM at calc time: ${domAtCalc}`);
                    
                    // Calculate what the offset SHOULD be right now
                    let expectedOffset = 0;
                    for (let i = 0; i < freshNodeIndex; i++) {
                        const n = ed.childNodes[i];
                        if (n.nodeType === Node.TEXT_NODE) expectedOffset += n.length;
                        else if (n.nodeName === 'BR') expectedOffset += 1;
                    }
                    if (freshRange?.endContainer.nodeType === Node.TEXT_NODE) {
                        expectedOffset += freshRange.endOffset;
                    }
                    console.log(`[Enter key] Expected cursor offset should be: ${expectedOffset}`);
                    
                    // Manually trigger what the input event would do
                    saveUndoState('Enter-key');
                    syncLineCounters();
                    
                    // Update line count display
                    const cc = document.getElementById('char-count');
                    if (cc && ed) {
                        const lines = ed.innerText.split('\n');
                        const maxLines = state.maxLines || 5;
                        const lineCount = lines.length;
                        cc.innerText = `${lineCount} / ${maxLines} lines`;
                        cc.style.color = lineCount > maxLines ? '#ff4444' : 'var(--accent-color)';
                    }
                    
                    // Schedule scan after a short delay so cursor position is preserved
                    setTimeout(() => {
                        scanAnachronisms(ed.innerText);
                    }, 50);
                    
                    const finalLines = ed.innerText.split('\n');
                    console.log(`[Enter key] DONE - ${finalLines.length} lines, line 0="${finalLines[0]?.substring(0,30)}", line 1="${finalLines[1]?.substring(0,30)}", line 2="${finalLines[2]?.substring(0,30)}"`);
                } else {
                    console.log(`[Enter key] SKIPPED - no range in selection`);
                }
                
                // Log DOM structure after Enter
                finalDom = '';
                for (let i = 0; i < ed.childNodes.length; i++) {
                    const n = ed.childNodes[i];
                    if (n.nodeType === Node.TEXT_NODE) finalDom += `TEXT(${n.length}) `;
                    else if (n.nodeName === 'BR') finalDom += 'BR ';
                    else finalDom += `${n.nodeName} `;
                }
                console.log(`[Enter key] DOM after: ${finalDom}`);
            }
        });

        ed.addEventListener('input', async () => { 
            console.log(`[input event] fired, _justPressedEnter=${ed._justPressedEnter}, skipInputHandling=${skipInputHandling}`);
            // Skip input handling during undo/redo
            if (skipInputHandling) {
                console.log(`[input event] SKIPPED due to skipInputHandling`);
                return;
            }
            
            // If Enter was just pressed, handle it specially
            if (ed._justPressedEnter) {
                console.log(`[input event] Handling Enter press`);
                ed._justPressedEnter = false;
                saveUndoState('input-justPressedEnter');
                syncLineCounters();
                // Update line count display
                const cc = document.getElementById('char-count');
                if (cc && ed) {
                    const lines = ed.innerText.split('\n');
                    const maxLines = state.maxLines || 5;
                    const lineCount = lines.length;
                    cc.innerText = `${lineCount} / ${maxLines} lines`;
                    cc.style.color = lineCount > maxLines ? '#ff4444' : 'var(--accent-color)';
                }
                // Schedule scan after a short delay so cursor position is preserved
                setTimeout(() => {
                    scanAnachronisms(ed.innerText);
                }, 50);
                return;
            }
            
            saveUndoState('input-normal');
            syncLineCounters();
            // Only update counters - NOT the scan which would reset cursor during rapid edits
            const cc = document.getElementById('char-count');
            if (cc && ed) {
                const lines = ed.innerText.split('\n');
                const maxLines = state.maxLines || 5;
                const lineCount = lines.length;
                cc.innerText = `${lineCount} / ${maxLines} lines`;
                cc.style.color = lineCount > maxLines ? '#ff4444' : 'var(--accent-color)';
            }
            // Re-scan for anachronisms as user types
            const jpText = document.getElementById('jp-source')?.innerText || '';
            populateLoreContext(jpText, ed.innerText, state.reviewer.currentIdx);
            // Don't update source window highlights on every keystroke - let scanAnachronisms handle that
        });
        ed.addEventListener('scroll', syncCounterScroll);
        ed.addEventListener('mousemove', handleMouseMove);
        ed.addEventListener('mouseleave', hideTooltip);
        ed.addEventListener('click', handleEditorClick);
        ed.addEventListener('paste', handlePaste);
        
        // Store the skip flags on the element for other functions to access
        ed._skipCursorRestore = () => skipCursorRestore;
        ed._skipInputHandling = () => skipInputHandling;
        ed._setSkipInputHandling = (val) => { skipInputHandling = val; };
    }
    
    // Initialize speaker, archetype, and entry type controls
    initMetadataControls();
    
    // Initialize preset dropdowns
    loadLimitPresets();

    // Filter button toggle
    const filterRowsBtn = document.getElementById('btn-filter-rows');
    if (filterRowsBtn) {
        filterRowsBtn.onclick = () => {
            const dropdown = document.getElementById('filter-dropdown');
            if (dropdown) {
                dropdown.style.display = dropdown.style.display === 'none' ? 'block' : 'none';
            }
        };
    }

    // Category selector
    const categorySelect = document.getElementById('category-select');
    if (categorySelect) {
        categorySelect.onchange = async () => {
            console.log('[categorySelect.onchange] Selected category:', categorySelect.value);
            await switchCategory(categorySelect.value);
        };
    }

    // Archetype save button
    const saveMetaBtn = document.getElementById('btn-save-meta');
    if (saveMetaBtn) {
        saveMetaBtn.onclick = async () => {
            const archSelect = document.getElementById('archetype-select');
            const noteInput = document.getElementById('speaker-note');
            const speakerValue = document.getElementById('speaker-value');
            if (speakerValue && archSelect && noteInput) {
                const speaker = speakerValue.innerText;
                const archetype = archSelect.value;
                const note = noteInput.value;
                await eel.save_speaker_archetype(speaker, archetype, note)();
                console.log('[btn-save-meta] Saved archetype:', archetype, 'for speaker:', speaker);
            }
        };
    }
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
    saveUndoState('applyFix');
    const text = document.getElementById('en-editor').innerText;
    const speaker = document.getElementById('speaker-value')?.textContent || '';
    const entryType = document.getElementById('entry-type-select')?.value || '';

    // Save to in-memory state only (not to CSV yet)
    item.en = text;
    // Update the item in the fullQueue as well
    const queueItem = state.reviewer.fullQueue?.find(i => i.id === item.id);
    if (queueItem) queueItem.en = text;

    // Save to history (without writing to CSV)
    const nickname = state.settings.lastConfig?.sync_nickname || 'reviewer';
    console.log('[applyFix] Saving history with nickname:', nickname, 'item.path:', item.path, 'item.id:', item.id);
    try {
        const res = await eel.save_translation_history(item.id, item.jp, text, speaker, entryType, nickname, item.path, item.row)();
        console.log('[applyFix] Save result:', res);
    } catch (e) {
        console.error('[applyFix] Save error:', e);
    }
    // Reload history to show the new entry
    console.log('[applyFix] Reloading history for item:', item.id);
    await loadTranslationHistory(item.id);

    const btn = document.getElementById('btn-apply');
    const prev = btn.innerHTML;
    btn.innerHTML = '✓ SAVED';

    // Check if auto-approve is enabled
    const autoApprove = document.getElementById('auto-approve-toggle')?.checked;
    if (autoApprove) {
        // Auto-approve will write to CSV
        await approveCurrentTranslation();
    }

    // Check if in-universe language is enabled - if NOT enabled, skip anachronism highlighting
    const inUniverseEnabled = document.getElementById('editor-in-universe')?.checked;
    if (!inUniverseEnabled) {
        console.log(`[renderHighlights] In-universe language disabled - skipping anachronism highlights`);
        setTimeout(() => {
            btn.innerHTML = prev;
            nextItem();
        }, 400);
        return;
    }

    setTimeout(() => {
        btn.innerHTML = prev;
        nextItem();
    }, 400);
}

async function rewrapEditor() {
    const text = document.getElementById('en-editor').innerText;
    saveUndoState('rewrapEditor');
    const limit = state.standardLimit;
    const rewrapped = await eel.rewrap_text(text, limit)();
    if (rewrapped !== undefined && rewrapped !== null) {
        const ed = document.getElementById('en-editor');
        if (ed) {
            // Skip input event handling while updating after rewrap
            if (ed._setSkipInputHandling) ed._setSkipInputHandling(true);
            ed.innerText = rewrapped;
            if (ed._setSkipInputHandling) ed._setSkipInputHandling(false);
            updateReviewerCounters();
            syncLineCounters();
        }
    }
}

async function replaceDashes(target) {
    const ed = document.getElementById('en-editor');
    saveUndoState('replaceDashes');
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
    const ed = document.getElementById('en-editor');
    const ctr = document.getElementById('line-counters');
    if (!ed || !ctr) return;
    
    const virtualTags = ['<n>', '</n>', '<w>', '</w>', '<p>', '</p>', '<b>', '</b>', '<i>', '</i>'];
    
    const text = ed.innerText;
    const lines = text ? text.split('\n') : [];
    const limit = state.standardLimit || 50;
    ctr.innerHTML = '';
    for (let i = 0; i < lines.length; i++) {
        let lineText = lines[i] || '';
        
        // Remove virtual tags
        for (const tag of virtualTags) {
            lineText = lineText.replaceAll(tag, '');
        }
        lineText = lineText.replace(/\n/g, '').replace(/\r/g, '');
        // Remove zero-width space used for cursor positioning
        lineText = lineText.replace(/\u200B/g, '');
        
        // Count characters (including spaces)
        const charCount = lineText.length;
        
        const s = document.createElement('span');
        s.innerText = charCount;
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
    // Count all lines including empty ones
    const lineCount = lines.length;
    
    // Update header to show line count vs max lines
    const cc = document.getElementById('char-count');
    if (cc) {
        cc.innerText = `${lineCount} / ${maxLines} lines`;
        cc.style.color = lineCount > maxLines ? '#ff4444' : 'var(--accent-color)';
    }

    // Scan for anachronisms
    await scanAnachronisms(ed.innerText);
}

function updatePreview(loadIdx) {
    const ed = document.getElementById('en-editor');
    const container = document.getElementById('preview-container');
    if (!ed || !container) return;
    
    const boxType = document.getElementById('preview-box-type')?.value || 'dialogue';
    const text = ed.innerText || '';
    
    // Generate preview image
    eel.generate_preview_image(boxType, text)().then(result => {
        // Only check index if loadIdx was provided (skip check for preview setting changes)
        if (loadIdx !== undefined && state.reviewer.currentIdx !== loadIdx) {
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
let highlightGeneration = 0;   // Counter to prevent race conditions in async highlight rendering
let isUserTyping = false;      // Track if user is actively typing right now

let anachronismDebounceTimer = null;
const ANACHRONISM_DEBOUNCE_MS = 300; // Wait 300ms after typing stops

async function scanAnachronisms(text) {
    if (!text) {
        state.reviewer.anachRanges = [];
        hoveredAnachronism = null;
        renderHighlights(text, highlightGeneration);
        return;
    }
    
    // Clear any pending debounce
    if (anachronismDebounceTimer) {
        clearTimeout(anachronismDebounceTimer);
    }
    
    // Mark that user is typing
    isUserTyping = true;
    
    // Debounce the anachronism scan to prevent cursor flickering
    anachronismDebounceTimer = setTimeout(async () => {
        // Mark that we're done typing
        isUserTyping = false;
        
        // Capture current generation to detect if this render is stale
        const generation = ++highlightGeneration;
        
        try {
            const hits = await eel.scan_anachronisms(text)();
            // Only update if we're still rendering this generation and not typing anymore
            if (generation === highlightGeneration && !isUserTyping) {
                state.reviewer.anachRanges = hits || [];
                renderHighlights(text, generation);
            }
        } catch(e) {
            console.error('[scanAnachronisms]', e);
            if (generation === highlightGeneration && !isUserTyping) {
                state.reviewer.anachRanges = [];
                renderHighlights(text, generation);
            }
        }
    }, ANACHRONISM_DEBOUNCE_MS);
}

function renderHighlights(text, generation) {
    // TEMPORARILY DISABLED to test Enter key functionality
    // TODO: Re-enable after fixing cursor issues
    return;
    
    const ed = document.getElementById('en-editor');
    if (!ed) return;
    
    // Skip if user is currently typing - wait for next debounce cycle
    if (isUserTyping) {
        return;
    }
    
    // Skip if this is a stale render (newer render is in progress)
    if (generation !== undefined && generation !== highlightGeneration) {
        return;
    }
    
    // Also check if the text has changed since this render was started
    const currentText = ed.innerText;
    if (currentText !== text) {
        return;
    }
    
    // Check if we should skip cursor restoration (e.g., after Enter key)
    const shouldSkipRestore = ed._skipCursorRestore && ed._skipCursorRestore();
    
    // Save cursor position
    const selection = window.getSelection();
    const range = selection.rangeCount > 0 ? selection.getRangeAt(0).cloneRange() : null;
    const cursorOffset = (shouldSkipRestore || !range) ? null : getCaretOffset(ed, range);
    
    // DEBUG: Log cursor position
    console.log(`[renderHighlights] text="${text.substring(0,20)}...", cursorOffset=${cursorOffset}, shouldSkip=${shouldSkipRestore}`);
    
    // Escape HTML tags to make them visible as text, but preserve newlines initially
    let html = text.replace(/</g, '&lt;').replace(/>/g, '&gt;');
    
    // Convert newlines to BR tags BEFORE applying highlights
    // This ensures empty lines are properly represented as <br> elements
    html = html.replace(/\n/g, '<br>');
    
    // Apply anachronism highlights using position-based approach
    if (state.reviewer.anachRanges && state.reviewer.anachRanges.length > 0) {
        // Sort by length (longer first) to handle multi-word phrases first
        const sortedRanges = [...state.reviewer.anachRanges].sort((a, b) => b[0].length - a[0].length);
        
        for (const [word, suggestion, is_ddon] of sortedRanges) {
            const escapedWord = word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
            // Use word boundary for single words, but not for multi-word phrases
            const useWordBoundary = !word.includes(' ');
            const regex = new RegExp(useWordBoundary ? `\\b${escapedWord}\\b` : escapedWord, 'gi');
            
            // Replace all occurrences, but skip those already inside span tags or br tags
            let match;
            const regexObj = new RegExp(regex);
            let lastIndex = 0;
            let newHtml = '';
            
            while ((match = regexObj.exec(html)) !== null) {
                // Add text before this match
                newHtml += html.substring(lastIndex, match.index);
                
                // Check if we're inside a span tag or adjacent to a BR
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
    if (!range || !range.endContainer) return null;
    
    // Manually count characters from start of element to cursor position
    // using the same logic as restoreCursor() to ensure consistency
    try {
        let currentOffset = 0;
        let found = false;
        
        function traverse(node) {
            if (found) return;
            
            if (node.nodeType === Node.TEXT_NODE) {
                const isTarget = node === range.endContainer;
                const textPreview = node.nodeValue.substring(0, 30).replace(/\n/g, '\\n');
                console.log(`[getCaretOffset] TEXT: len=${node.length}, current=${currentOffset}, target=${isTarget}, text="${textPreview}"`);
                if (isTarget) {
                    // This is the target text node
                    currentOffset += range.endOffset;
                    found = true;
                    console.log(`[getCaretOffset] FOUND at final offset ${currentOffset}`);
                    return;
                }
                currentOffset += node.length;
            } else if (node.nodeType === Node.ELEMENT_NODE) {
                // Handle BR elements as single character line breaks
                if (node.nodeName === 'BR') {
                    console.log(`[getCaretOffset] BR: current=${currentOffset} -> ${currentOffset + 1}`);
                    currentOffset += 1;
                } else if (node.nodeName === 'SPAN' || node.nodeName === 'DIV') {
                    // Traverse children
                    for (let i = 0; i < node.childNodes.length && !found; i++) {
                        traverse(node.childNodes[i]);
                    }
                } else {
                    // Other elements - traverse children
                    for (let i = 0; i < node.childNodes.length && !found; i++) {
                        traverse(node.childNodes[i]);
                    }
                }
            }
        }
        
        traverse(element);
        
        if (found) {
            console.log(`[getCaretOffset] Found at offset ${currentOffset}`);
            return currentOffset;
        }
        
        // Fallback: use the original range-based method if our traversal fails
        console.log(`[getCaretOffset] Traversal failed, using fallback`);
        const preCaretRange = range.cloneRange();
        preCaretRange.selectNodeContents(element);
        preCaretRange.setEnd(range.endContainer, range.endOffset);
        const fallbackOffset = preCaretRange.toString().length;
        console.log(`[getCaretOffset] Fallback returned ${fallbackOffset}`);
        return fallbackOffset;
    } catch (e) {
        console.error('[getCaretOffset] Error:', e);
        return null;
    }
}

function restoreCursor(element, offset) {
    if (offset === null) return;
    
    const text = element.innerText || '';
    const clampedOffset = Math.min(Math.max(0, offset), text.length);
    
    console.log(`[restoreCursor] requested=${offset}, clamped=${clampedOffset}, textLength=${text.length}, text="${text.substring(0,30)}"`);
    
    const range = document.createRange();
    const selection = window.getSelection();
    
    let currentOffset = 0;
    let found = false;
    
    // Traverse DOM nodes counting text content, handling BR tags as newlines
    function traverse(node) {
        if (found) return;
        
        if (node.nodeType === Node.TEXT_NODE) {
            const nodeLength = node.length;
            
            if (currentOffset + nodeLength >= clampedOffset) {
                // Found the node containing our target offset
                const posInNode = clampedOffset - currentOffset;
                console.log(`[restoreCursor] Found TEXT node at currentOffset=${currentOffset}, nodeLength=${nodeLength}, posInNode=${posInNode}, nodeText="${node.nodeValue.substring(0,20)}"`);
                range.setStart(node, posInNode);
                range.collapse(true);
                found = true;
                return;
            }
            currentOffset += nodeLength;
        } else if (node.nodeType === Node.ELEMENT_NODE) {
            // Handle BR elements as single character line breaks
            if (node.nodeName === 'BR') {
                currentOffset += 1; // BR counts as one character (equivalent to \n)
                if (currentOffset >= clampedOffset && !found) {
                    // Position cursor right before or after the BR
                    if (currentOffset - 1 === clampedOffset) {
                        // Cursor position is just before the BR - position after previous text node
                        found = true;
                        return;
                    } else {
                        // Cursor position is at or after the BR
                        const next = node.nextSibling;
                        if (next) {
                            if (next.nodeType === Node.TEXT_NODE) {
                                range.setStart(next, 0);
                            } else {
                                range.setStart(node, 0);
                            }
                        } else {
                            range.setStart(node, 0);
                        }
                        range.collapse(true);
                        found = true;
                        return;
                    }
                }
            } else if (node.nodeName === 'SPAN') {
                // Process text content within span (the highlights)
                console.log(`[restoreCursor] Entering SPAN, currentOffset=${currentOffset}`);
                for (let i = 0; i < node.childNodes.length && !found; i++) {
                    traverse(node.childNodes[i]);
                }
                // If we found the position inside this span, stop here
                if (found) {
                    console.log(`[restoreCursor] Found inside SPAN`);
                    return;
                }
            } else {
                // Other elements - traverse children
                for (let i = 0; i < node.childNodes.length && !found; i++) {
                    traverse(node.childNodes[i]);
                }
            }
        }
    }
    
    traverse(element);
    
    // Only update selection if we found a valid position
    if (found && range.startContainer) {
        try {
            selection.removeAllRanges();
            selection.addRange(range);
            console.log(`[restoreCursor] SUCCESS - positioned at node offset ${range.startOffset}`);
        } catch (e) {
            console.error('[restoreCursor] Failed to set range:', e);
        }
    } else if (currentOffset >= clampedOffset && text.length > 0) {
        // Cursor at end - try to position at end of last child
        let lastNode = element.lastChild;
        while (lastNode && lastNode.nodeType !== Node.TEXT_NODE) {
            if (lastNode.nodeType !== Node.ELEMENT_NODE) break;
            lastNode = lastNode.lastChild;
        }
        if (lastNode && lastNode.nodeType === Node.TEXT_NODE) {
            range.setStart(lastNode, lastNode.length);
            range.collapse(true);
            selection.removeAllRanges();
            selection.addRange(range);
            console.log(`[restoreCursor] END fallback - positioned at end of text node`);
        }
    }
    
    // Verify final cursor position
    const finalSelection = window.getSelection();
    if (finalSelection.rangeCount > 0) {
        const finalRange = finalSelection.getRangeAt(0);
        console.log(`[restoreCursor] FINAL - endContainer nodeType=${finalRange.endContainer.nodeType}, endOffset=${finalRange.endOffset}`);
    }
}

function restoreCursorAbsolute(element, offset) {
    if (offset === null) return;
    
    const selection = window.getSelection();
    const text = element.innerText || '';
    const clampedOffset = Math.min(offset, text.length);
    
    // Use Selection API to position cursor by selecting from start to offset
    // This works even if DOM structure changes because it uses text content
    const range = document.createRange();
    
    // Find the text node that contains the offset
    let currentOffset = 0;
    let targetNode = null;
    let targetOffset = 0;
    
    function traverse(node) {
        if (targetNode) return;
        
        if (node.nodeType === Node.TEXT_NODE) {
            const nodeLength = node.length;
            if (currentOffset + nodeLength >= clampedOffset) {
                targetNode = node;
                targetOffset = clampedOffset - currentOffset;
            } else {
                currentOffset += nodeLength;
            }
        } else {
            for (let i = 0; i < node.childNodes.length; i++) {
                traverse(node.childNodes[i]);
                if (targetNode) return;
            }
        }
    }
    
    traverse(element);
    
    if (targetNode) {
        range.setStart(targetNode, targetOffset);
        range.collapse(true);
        selection.removeAllRanges();
        selection.addRange(range);
    } else {
        // Fallback: set cursor at end of last text node
        const textNodes = [];
        function collectTextNodes(node) {
            if (node.nodeType === Node.TEXT_NODE) {
                textNodes.push(node);
            } else {
                for (let i = 0; i < node.childNodes.length; i++) {
                    collectTextNodes(node.childNodes[i]);
                }
            }
        }
        collectTextNodes(element);
        
        if (textNodes.length > 0) {
            const lastNode = textNodes[textNodes.length - 1];
            range.setStart(lastNode, lastNode.length);
            range.collapse(true);
            selection.removeAllRanges();
            selection.addRange(range);
        }
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

function hideTooltip() {
    const tooltip = document.getElementById('anach-tooltip');
    if (tooltip) {
        tooltip.style.display = 'none';
    }
    hoveredAnachronism = null;
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
    scanAnachronisms(document.getElementById('en-editor').innerText);
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

function initMetadataControls() {
    // Initialize speaker, archetype, and entry type controls
    console.log('[initMetadataControls] Initializing...');

    // Populate archetype dropdown with archetypes from config
    const archSelect = document.getElementById('archetype-select');
    if (archSelect) {
        eel.get_full_config()().then(config => {
            if (config && config.archetypes) {
                archSelect.innerHTML = '<option>(none)</option>';
                Object.entries(config.archetypes).sort(([a], [b]) => a.localeCompare(b)).forEach(([key, data]) => {
                    const opt = document.createElement('option');
                    opt.value = key;
                    opt.innerText = data.name || key;
                    archSelect.appendChild(opt);
                });
                console.log('[initMetadataControls] Populated archetype dropdown');
            }
        });
    }

    // Populate entry type dropdown with entry types from review items
    const entTypeSelect = document.getElementById('entry-type-select');
    if (entTypeSelect) {
        eel.get_all_items_in_queue()().then(items => {
            if (items && items.length > 0) {
                const entryTypes = new Set();
                items.forEach(item => {
                    if (item.entry_type) {
                        entryTypes.add(item.entry_type);
                    }
                });
                const sortedTypes = Array.from(entryTypes).sort();
                if (sortedTypes.length > 0) {
                    entTypeSelect.innerHTML = '';
                    sortedTypes.forEach(type => {
                        const opt = document.createElement('option');
                        opt.value = type;
                        opt.innerText = type;
                        entTypeSelect.appendChild(opt);
                    });
                    console.log('[initMetadataControls] Populated entry type dropdown:', sortedTypes);
                } else {
                    entTypeSelect.innerHTML = '<option value="">(none)</option>';
                    console.log('[initMetadataControls] No entry types found in items');
                }
            } else {
                entTypeSelect.innerHTML = '<option value="">(none)</option>';
                console.log('[initMetadataControls] No items in queue');
            }
        });
    }

    console.log('[initMetadataControls] Initialized');
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
    } catch (e) {
        console.error('[loadLimitPresets] Error:', e);
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

async function replaceAnachronism(word, suggestion, position = null) {
    const ed = document.getElementById('en-editor');
    if (!ed) return;
    saveUndoState('replaceAnachronism');

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
    
    // Check prefetch cache first
    let res = null;
    const category = state.reviewer.currentCategory || 'default';
    const cached = await eel.get_prefetch_cache(category, loadIdx)();
    
    if (cached && cached.deepl_suggestion) {
        console.log(`[fetchDeepLSuggestion] Using cached DeepL suggestion for idx=${loadIdx}`);
        res = cached.deepl_suggestion;
    } else {
        // Fetch fresh if not cached
        el.value = 'Consulting DeepL…';
        const startTime = Date.now();
        res = await eel.get_deepl_suggestion(text)();
        const elapsed = Date.now() - startTime;
        console.log(`[fetchDeepLSuggestion] Fetched fresh for idx=${loadIdx}, elapsed=${elapsed}ms`);
    }
    
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
                    syncLineCounters();
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
        
        // Wire up click handlers to insert into editor
        box.querySelectorAll('.lore-source-span').forEach(span => {
            span.onclick = async () => {
                const suggestion = span.getAttribute('data-suggestion');
                const ed = document.getElementById('en-editor');
                if (ed && suggestion) {
                    ed.innerText += suggestion;
                    updateReviewerCounters();
                    syncLineCounters();
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
                    syncLineCounters();
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
                    syncLineCounters();
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
    try {
        // Check prefetch cache first
        let matches = null;
        const loreCategory = state.reviewer.currentCategory || 'default';
        const loreCached = await eel.get_prefetch_cache(loreCategory, loadIdx)();
        
        if (loreCached && loreCached.lore_context) {
            console.log(`[populateLoreContext] Using cached lore_context for idx=${loadIdx}`);
            matches = loreCached.lore_context;
        } else {
            // Fetch fresh if not cached
            matches = await eel.get_lore_context(jpText)();
        }
        
        // Only update if we're still on the same item
        if (state.reviewer.currentIdx !== loadIdx) {
            console.log(`[populateLoreContext] Skipped update - navigation occurred (${loadIdx} → ${state.reviewer.currentIdx})`);
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
                    // Quote-aware split: don't split on delimiters inside quotes
                    const suggestions = [];
                    let current = '';
                    let inQuotes = false;
                    for (let i = 0; i < m.en.length; i++) {
                        const char = m.en[i];
                        if (char === '"' && (i === 0 || m.en[i-1] !== '\\')) {
                            inQuotes = !inQuotes;
                            current += char;
                        } else if (/[,\;|\n\/]/.test(char) && !inQuotes) {
                            if (current.trim()) {
                                suggestions.push(current.trim());
                            }
                            current = '';
                        } else {
                            current += char;
                        }
                    }
                    if (current.trim()) {
                        suggestions.push(current.trim());
                    }
                    
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
                        dragonArt.src = 'data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAxNiAxNiIgZmlsbD0iI2U4YzZhYSI+PHBhdGggZD0iTTEwLjUgMy41Yy0uNSAwLTEgLjUtMS0xIDAgMCAuNS41IDEgMSAxczEuNSAxIDEgMSAxLS41IDEtMS0xem0tNSAwdjFoMnYxaC0yem0zIDJ2MWgxdjFoLTF6bS00IDJ2MWgxdjFoLTF6bTcgMmMtMSAwLTIuNS0xLTIuNS0yLjUgMC0xLjUgMS41LTIuNSAyLjUtMi41czIuNSAxIDIuNSAyLjVjMCAxLjUtMS41IDIuNS0yLjUgMi41em0tOCAxYzAgMS41IDEuNSAyLjUgMi41IDIuNXMyLjUtMSAyLjUtMi41YzAtMS41LTEuNS0yLjUtMi41LTIuNXptMTEuNSAwYzAgMS41IDEuNSAyLjUgMi41IDIuNXMyLjUtMSAyLjUtMi41YzAtMS41LTEuNS0yLjUtMi41LTIuNXoiLz48L3N2Zz4=';
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
        const anachHits = state.reviewer.anachRanges || [];
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
    console.log(`[populateAdjacentContext] Called with path=${path}, rowIdx=${rowIdx}, loadIdx=${loadIdx}`);
    try {
        const adjCtx = await eel.get_adjacent_context(path, rowIdx)();
        console.log(`[populateAdjacentContext] Received adjCtx:`, adjCtx);
        console.log(`[populateAdjacentContext] adjCtx.prev:`, adjCtx?.prev);
        console.log(`[populateAdjacentContext] adjCtx.next:`, adjCtx?.next);
        
        // Only update if we're still on the same item
        if (state.reviewer.currentIdx !== loadIdx) return;
        
        if (prevEl) {
            prevEl.innerHTML = adjCtx && adjCtx.prev
                ? `<span class="adj-arrow">▲</span><span class="adj-jp">${escHtml(adjCtx.prev.jp)}</span><br><span class="adj-en">${escHtml(adjCtx.prev.en)}</span>`
                : '<span class="adj-arrow">▲</span>—';
        }
        if (nextEl) {
            nextEl.innerHTML = adjCtx && adjCtx.next
                ? `<span class="adj-arrow">▼</span><span class="adj-jp">${escHtml(adjCtx.next.jp)}</span><br><span class="adj-en">${escHtml(adjCtx.next.en)}</span>`
                : '<span class="adj-arrow">▼</span>—';
        }
    } catch (e) { console.error('[populateAdjacentContext]', e); }
}

function insertIntoEditor(text) {
    const ed = document.getElementById('en-editor');
    if (!ed) return;
    
    // Focus the editor
    ed.focus();
    
    // Get selection in the editor
    const selection = window.getSelection();
    let range = selection.getRangeAt(0);
    
    // Check if selection is within the editor
    if (!ed.contains(range.commonAncestorContainer)) {
        // Selection is not in editor, insert at end
        range = document.createRange();
        range.selectNodeContents(ed);
        range.collapse(false);
        selection.removeAllRanges();
        selection.addRange(range);
    }
    
    // Insert text
    range.deleteContents();
    range.insertNode(document.createTextNode(text));
    
    // Move cursor after inserted text
    range.setStartAfter(range.endContainer);
    range.setEndAfter(range.endContainer);
    selection.removeAllRanges();
    selection.addRange(range);
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
    
    const showFilter = document.getElementById('show-filter')?.value || 'all';
    const speakerFilter = document.getElementById('filter-speaker')?.value;
    const entryTypeFilter = document.getElementById('filter-entry-type')?.value;
    
    if (!state.reviewer.fullQueue || !state.reviewer.fullQueue.length) {
        ul.innerHTML = '<li style="padding: 8px; color: var(--text-muted);">No items loaded</li>';
        return;
    }
    
    // Update filter dropdowns when queue changes
    populateFilterDropdowns();
    
    // Filter items based on criteria
    let itemsToShow = state.reviewer.fullQueue.map((item, idx) => ({ item, idx }));
    
    // Apply show filter
    if (showFilter === 'untranslated') {
        itemsToShow = itemsToShow.filter(({ item }) => !item.en);
    } else if (showFilter === 'untranslated-first') {
        // Sort: untranslated first, then translated
        itemsToShow.sort((a, b) => {
            const aUntranslated = !a.item.en;
            const bUntranslated = !b.item.en;
            if (aUntranslated && !bUntranslated) return -1;
            if (!aUntranslated && bUntranslated) return 1;
            return a.idx - b.idx; // Keep original order within groups
        });
    }
    
    // Apply speaker and entry type filters
    if (speakerFilter) {
        itemsToShow = itemsToShow.filter(({ item }) => item.speaker === speakerFilter);
    }
    if (entryTypeFilter) {
        itemsToShow = itemsToShow.filter(({ item }) => item.entry_type === entryTypeFilter);
    }
    
    itemsToShow.forEach(({ item, idx }) => {
        const li = document.createElement('li');
        const rowNum = `<span class="row-num">[${String(idx + 1).padStart(3, '0')}]</span>`;
        const jpText = (item.jp || '').slice(0, 35);
        const enText = item.en ? `<span class="row-en">${item.en}</span>` : '';
        const commentIndicator = item.comment_count > 0 ? `<span class="row-comment-indicator" title="${item.comment_count} comment${item.comment_count > 1 ? 's' : ''}">💬</span>` : '';
        li.innerHTML = `${rowNum}<div class="row-text"><span class="row-jp">${jpText}</span>${enText}</div>${commentIndicator}`;
        if (item.en) li.classList.add('translated');
        if (state.reviewer.currentIdx === idx) li.classList.add('active');
        li.onclick = () => loadItemAtIdx(idx);
        ul.appendChild(li);
    });
}

function populateFilterDropdowns() {
    // Populate speaker filter dropdown from current queue
    const speakerSelect = document.getElementById('filter-speaker');
    const entryTypeSelect = document.getElementById('filter-entry-type');
    if (!speakerSelect || !entryTypeSelect || !state.reviewer.fullQueue) return;
    
    // Get unique speakers and entry types
    const speakers = new Set();
    const entryTypes = new Set();
    state.reviewer.fullQueue.forEach(item => {
        if (item.speaker) speakers.add(item.speaker);
        if (item.entry_type) entryTypes.add(item.entry_type);
    });
    
    // Save current selection
    const currentSpeaker = speakerSelect.value;
    const currentEntryType = entryTypeSelect.value;
    
    // Repopulate speakers
    speakerSelect.innerHTML = '<option value="">All speakers</option>';
    [...speakers].sort().forEach(speaker => {
        const option = document.createElement('option');
        option.value = speaker;
        option.innerText = speaker;
        speakerSelect.appendChild(option);
    });
    speakerSelect.value = currentSpeaker;
    
    // Repopulate entry types
    entryTypeSelect.innerHTML = '<option value="">All types</option>';
    [...entryTypes].sort().forEach(type => {
        const option = document.createElement('option');
        option.value = type;
        option.innerText = type;
        entryTypeSelect.appendChild(option);
    });
    entryTypeSelect.value = currentEntryType;
}

function clearFilters() {
    document.getElementById('show-filter').value = 'all';
    document.getElementById('filter-speaker').value = '';
    document.getElementById('filter-entry-type').value = '';
    renderRowSidebar();
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
                    saveUndoState('paste');
                    if (ed._setSkipInputHandling) ed._setSkipInputHandling(true);
                    ed.innerText = text;
                    if (ed._setSkipInputHandling) ed._setSkipInputHandling(false);
                    updateReviewerCounters();
                    syncLineCounters();
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

        // GitHub Sync Settings
        setVal('opt-github-repo', config.github_repo || '');
        setVal('opt-github-token', config.github_token || '');
        setVal('opt-sync-nickname', config.sync_nickname || '');
        setVal('opt-sync-language', config.sync_language || 'English');
        setCheck('opt-sync-auto', config.sync_auto || false);
        
        // Update sync status display
        updateSyncStatusDisplay();

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
        setVal('color-dark-accent-fill', darkTheme.accent_fill || '#00C853');
        setVal('color-dark-accent-text', darkTheme.accent_text || '#000000');
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
        setVal('color-dark-mask-015', darkTheme.mask_015 || 'rgba(0, 0, 0, 0.15)');
        setVal('color-dark-mask-025', darkTheme.mask_025 || 'rgba(0, 0, 0, 0.25)');
        setVal('color-dark-mask-03', darkTheme.mask_03 || 'rgba(0, 0, 0, 0.3)');
        setVal('color-dark-mask-05', darkTheme.mask_05 || 'rgba(0, 0, 0, 0.5)');
        setVal('color-dark-mask-08', darkTheme.mask_08 || 'rgba(0, 0, 0, 0.8)');
        
        // Theme color channels
        setVal('color-dark-theme-backgrounds-color', darkTheme.theme_backgrounds_color || '245, 247, 248');
        setVal('color-dark-theme-primaries-color', darkTheme.theme_primaries_color || '67, 160, 71');
        setVal('color-dark-theme-blacks', darkTheme.theme_blacks || '0, 0, 0');
        setVal('color-dark-theme-whites', darkTheme.theme_whites || '255, 255, 255');
        setVal('color-dark-theme-grays', darkTheme.theme_grays || '38, 50, 56');
        setVal('color-dark-theme-typeface-color', darkTheme.theme_typeface_color || '38, 50, 56');
        setVal('color-dark-theme-cards-color', darkTheme.theme_cards_color || '38, 50, 56');
        
        // Theme colors
        setVal('color-dark-theme-level-1-bg', darkTheme.theme_level_1_bg || '#f5f7f8');
        setVal('color-dark-theme-level-2-bg', darkTheme.theme_level_2_bg || '#ffffff');
        setVal('color-dark-theme-level-3-bg', darkTheme.theme_level_3_bg || '#ffffff');
        setVal('color-dark-theme-primary', darkTheme.theme_primary || '#43a047');
        setVal('color-dark-theme-link-hover', darkTheme.theme_link_hover || '#5bbb60');
        setVal('color-dark-theme-border-color', darkTheme.theme_border_color || 'rgba(38, 50, 56, 0.1)');
        setVal('color-dark-theme-dark-border-color', darkTheme.theme_dark_border_color || 'rgba(0, 0, 0, 0.12)');
        setVal('color-dark-theme-shimmer', darkTheme.theme_shimmer || '#eceff1');
        setVal('color-dark-theme-icons-color', darkTheme.theme_icons_color || 'rgba(38, 50, 56, 1)');
        setVal('color-dark-theme-primary-green-50', darkTheme.theme_primary_green_50 || '#e8f5e9');
        setVal('color-dark-theme-primary-green-100', darkTheme.theme_primary_green_100 || '#c8e6c9');
        setVal('color-dark-theme-primary-blue-600', darkTheme.theme_primary_blue_600 || '#1e88e5');
        setVal('color-dark-theme-primary-blue-gray', darkTheme.theme_primary_blue_gray || '#eceff1');
        setVal('color-dark-theme-dark', darkTheme.theme_dark || 'rgba(38, 50, 56, 1)');
        setVal('color-dark-theme-gray-005', darkTheme.theme_gray_005 || 'rgba(38, 50, 56, 0.05)');
        setVal('color-dark-theme-gray-01', darkTheme.theme_gray_01 || 'rgba(38, 50, 56, 0.1)');
        setVal('color-dark-theme-gray-02', darkTheme.theme_gray_02 || 'rgba(38, 50, 56, 0.2)');
        setVal('color-dark-theme-gray-03', darkTheme.theme_gray_03 || 'rgba(38, 50, 56, 0.3)');
        setVal('color-dark-theme-white-005', darkTheme.theme_white_005 || 'rgba(255, 255, 255, 0.05)');
        setVal('color-dark-theme-white-012', darkTheme.theme_white_012 || 'rgba(255, 255, 255, 0.12)');
        setVal('color-dark-theme-white', darkTheme.theme_white || 'rgba(255, 255, 255, 1)');
        setVal('color-dark-theme-black', darkTheme.theme_black || 'rgba(0, 0, 0, 1)');
        setVal('color-dark-theme-danger', darkTheme.theme_danger || '#dc5242');
        setVal('color-dark-theme-danger-hover-color', darkTheme.theme_danger_hover_color || '#e4796d');
        setVal('color-dark-theme-danger-bg', darkTheme.theme_danger_bg || 'rgba(220, 82, 66, 0.5)');
        setVal('color-dark-theme-danger-bg-level-1', darkTheme.theme_danger_bg_level_1 || 'rgba(220, 82, 66, 0.1)');
        setVal('color-dark-theme-danger-bg-level-2', darkTheme.theme_danger_bg_level_2 || 'rgba(220, 82, 66, 0.2)');
        setVal('color-dark-theme-info', darkTheme.theme_info || '#1e88e5');
        setVal('color-dark-theme-info-bg', darkTheme.theme_info_bg || 'rgba(30, 136, 229, 0.1)');
        setVal('color-dark-theme-info-link', darkTheme.theme_info_link || '#166dba');
        setVal('color-dark-theme-warning', darkTheme.theme_warning || '#c79d1c');
        setVal('color-dark-theme-warning-bg', darkTheme.theme_warning_bg || 'rgba(199, 157, 28, 0.2)');
        setVal('color-dark-theme-warning-link', darkTheme.theme_warning_link || '#9a7a16');
        setVal('color-dark-theme-success', darkTheme.theme_success || '#6dae02');
        setVal('color-dark-theme-success-bg', darkTheme.theme_success_bg || 'rgba(109, 174, 2, 0.1)');
        setVal('color-dark-theme-success-link', darkTheme.theme_success_link || '#4d7c01');
        setVal('color-dark-theme-btn-hover-bg', darkTheme.theme_btn_hover_bg || 'rgba(38, 50, 56, 0.05)');
        setVal('color-dark-theme-btn-active-bg', darkTheme.theme_btn_active_bg || 'rgba(38, 50, 56, 0.1)');
        setVal('color-dark-theme-btn-disabled-bg', darkTheme.theme_btn_disabled_bg || 'rgba(38, 50, 56, 0.05)');
        setVal('color-dark-theme-primary-btn-hover-bg', darkTheme.theme_primary_btn_hover_bg || '#4caf50');
        setVal('color-dark-theme-primary-btn-active-bg', darkTheme.theme_primary_btn_active_bg || '#388e3c');
        setVal('color-dark-theme-danger-btn-bg', darkTheme.theme_danger_btn_bg || '#c63625');
        setVal('color-dark-theme-danger-btn-hover-bg', darkTheme.theme_danger_btn_hover_bg || '#dc5242');
        setVal('color-dark-theme-danger-btn-border', darkTheme.theme_danger_btn_border || '#9b2a1d');
        setVal('color-dark-theme-warning-btn-bg', darkTheme.theme_warning_btn_bg || '#c79d1c');
        setVal('color-dark-theme-warning-btn-hover-bg', darkTheme.theme_warning_btn_hover_bg || '#e1b42b');
        setVal('color-dark-theme-warning-btn-border', darkTheme.theme_warning_btn_border || '#c79d1c');
        setVal('color-dark-theme-warning-btn-hover-border', darkTheme.theme_warning_btn_hover_border || '#e1b42b');
        setVal('color-dark-theme-tab-active-bg', darkTheme.theme_tab_active_bg || 'rgba(67, 160, 71, 0.2)');
        setVal('color-dark-theme-tab-active-color', darkTheme.theme_tab_active_color || '#347c37');
        setVal('color-dark-theme-tag-color', darkTheme.theme_tag_color || '#787459');
        setVal('color-dark-theme-tag-color-hover', darkTheme.theme_tag_color_hover || '#4C482E');
        setVal('color-dark-theme-tag-bg', darkTheme.theme_tag_bg || '#FAF6D8');
        setVal('color-dark-theme-tag-bg-hover', darkTheme.theme_tag_bg_hover || '#F8F0C0');
        setVal('color-dark-theme-special-light-color', darkTheme.theme_special_light_color || '#770000');
        setVal('color-dark-theme-special-light-bg', darkTheme.theme_special_light_bg || '#F0F0FF');
        setVal('color-dark-theme-find-replace-highlight-bg', darkTheme.theme_find_replace_highlight_bg || '#F5D87D');

        // Load light theme colors
        setVal('color-light-bg', lightTheme.bg || '#ffffff');
        setVal('color-light-fg', lightTheme.fg || '#000000');
        setVal('color-light-list-bg', lightTheme.list_bg || '#eaf0f7');
        setVal('color-light-btn-bg', lightTheme.btn_bg || '#ebe6ff');
        setVal('color-light-log-bg', lightTheme.log_bg || '#dbffd9');
        setVal('color-light-log-fg', lightTheme.log_fg || '#2d2d2d');
        setVal('color-light-label', lightTheme.label || '#475569');
        setVal('color-light-button-text', lightTheme.button_text || '#1e293b');
        setVal('color-light-accent', lightTheme.accent || '#9ab8f5');
        setVal('color-light-accent-fill', lightTheme.accent_fill || '#9ab8f5');
        setVal('color-light-accent-text', lightTheme.accent_text || '#000000');
        setVal('color-light-run-bg', lightTheme.run_bg || '#0cf000');
        setVal('color-light-border', lightTheme.border || '#000000');
        setVal('color-light-header-bg', lightTheme.header_bg || '#ffffff');
        setVal('color-light-panel-bg', lightTheme.panel_bg || '#eaf0f7');
        setVal('color-light-tab-inactive', lightTheme.tab_inactive || '#657b9a');
        setVal('color-light-glow', lightTheme.glow || '#3b82f6');
        setVal('color-light-lore', lightTheme.lore || '#3b82f6');
        setVal('color-light-lore-hover', lightTheme.lore_hover || '#79b4fb');
        setVal('color-light-anach', lightTheme.anach || '#fb634d');
        setVal('color-light-tooltip', lightTheme.tooltip || '#fcf34b');
        setVal('color-light-mask-015', lightTheme.mask_015 || 'rgba(0, 0, 0, 0.08)');
        setVal('color-light-mask-025', lightTheme.mask_025 || 'rgba(0, 0, 0, 0.12)');
        setVal('color-light-mask-03', lightTheme.mask_03 || 'rgba(0, 0, 0, 0.15)');
        setVal('color-light-mask-05', lightTheme.mask_05 || 'rgba(0, 0, 0, 0.2)');
        setVal('color-light-mask-08', lightTheme.mask_08 || 'rgba(0, 0, 0, 0.3)');
        
        // Theme color channels
        setVal('color-light-theme-backgrounds-color', lightTheme.theme_backgrounds_color || '245, 247, 248');
        setVal('color-light-theme-primaries-color', lightTheme.theme_primaries_color || '67, 160, 71');
        setVal('color-light-theme-blacks', lightTheme.theme_blacks || '0, 0, 0');
        setVal('color-light-theme-whites', lightTheme.theme_whites || '255, 255, 255');
        setVal('color-light-theme-grays', lightTheme.theme_grays || '38, 50, 56');
        setVal('color-light-theme-typeface-color', lightTheme.theme_typeface_color || '38, 50, 56');
        setVal('color-light-theme-cards-color', lightTheme.theme_cards_color || '38, 50, 56');
        
        // Theme colors
        setVal('color-light-theme-level-1-bg', lightTheme.theme_level_1_bg || '#f5f7f8');
        setVal('color-light-theme-level-2-bg', lightTheme.theme_level_2_bg || '#ffffff');
        setVal('color-light-theme-level-3-bg', lightTheme.theme_level_3_bg || '#ffffff');
        setVal('color-light-theme-primary', lightTheme.theme_primary || '#43a047');
        setVal('color-light-theme-link-hover', lightTheme.theme_link_hover || '#5bbb60');
        setVal('color-light-theme-border-color', lightTheme.theme_border_color || 'rgba(38, 50, 56, 0.1)');
        setVal('color-light-theme-dark-border-color', lightTheme.theme_dark_border_color || 'rgba(0, 0, 0, 0.12)');
        setVal('color-light-theme-shimmer', lightTheme.theme_shimmer || '#eceff1');
        setVal('color-light-theme-icons-color', lightTheme.theme_icons_color || 'rgba(38, 50, 56, 1)');
        setVal('color-light-theme-primary-green-50', lightTheme.theme_primary_green_50 || '#e8f5e9');
        setVal('color-light-theme-primary-green-100', lightTheme.theme_primary_green_100 || '#c8e6c9');
        setVal('color-light-theme-primary-blue-600', lightTheme.theme_primary_blue_600 || '#1e88e5');
        setVal('color-light-theme-primary-blue-gray', lightTheme.theme_primary_blue_gray || '#eceff1');
        setVal('color-light-theme-dark', lightTheme.theme_dark || 'rgba(38, 50, 56, 1)');
        setVal('color-light-theme-gray-005', lightTheme.theme_gray_005 || 'rgba(38, 50, 56, 0.05)');
        setVal('color-light-theme-gray-01', lightTheme.theme_gray_01 || 'rgba(38, 50, 56, 0.1)');
        setVal('color-light-theme-gray-02', lightTheme.theme_gray_02 || 'rgba(38, 50, 56, 0.2)');
        setVal('color-light-theme-gray-03', lightTheme.theme_gray_03 || 'rgba(38, 50, 56, 0.3)');
        setVal('color-light-theme-white-005', lightTheme.theme_white_005 || 'rgba(255, 255, 255, 0.05)');
        setVal('color-light-theme-white-012', lightTheme.theme_white_012 || 'rgba(255, 255, 255, 0.12)');
        setVal('color-light-theme-white', lightTheme.theme_white || 'rgba(255, 255, 255, 1)');
        setVal('color-light-theme-black', lightTheme.theme_black || 'rgba(0, 0, 0, 1)');
        setVal('color-light-theme-danger', lightTheme.theme_danger || '#dc5242');
        setVal('color-light-theme-danger-hover-color', lightTheme.theme_danger_hover_color || '#e4796d');
        setVal('color-light-theme-danger-bg', lightTheme.theme_danger_bg || 'rgba(220, 82, 66, 0.5)');
        setVal('color-light-theme-danger-bg-level-1', lightTheme.theme_danger_bg_level_1 || 'rgba(220, 82, 66, 0.1)');
        setVal('color-light-theme-danger-bg-level-2', lightTheme.theme_danger_bg_level_2 || 'rgba(220, 82, 66, 0.2)');
        setVal('color-light-theme-info', lightTheme.theme_info || '#1e88e5');
        setVal('color-light-theme-info-bg', lightTheme.theme_info_bg || 'rgba(30, 136, 229, 0.1)');
        setVal('color-light-theme-info-link', lightTheme.theme_info_link || '#166dba');
        setVal('color-light-theme-warning', lightTheme.theme_warning || '#c79d1c');
        setVal('color-light-theme-warning-bg', lightTheme.theme_warning_bg || 'rgba(199, 157, 28, 0.2)');
        setVal('color-light-theme-warning-link', lightTheme.theme_warning_link || '#9a7a16');
        setVal('color-light-theme-success', lightTheme.theme_success || '#6dae02');
        setVal('color-light-theme-success-bg', lightTheme.theme_success_bg || 'rgba(109, 174, 2, 0.1)');
        setVal('color-light-theme-success-link', lightTheme.theme_success_link || '#4d7c01');
        setVal('color-light-theme-btn-hover-bg', lightTheme.theme_btn_hover_bg || 'rgba(38, 50, 56, 0.05)');
        setVal('color-light-theme-btn-active-bg', lightTheme.theme_btn_active_bg || 'rgba(38, 50, 56, 0.1)');
        setVal('color-light-theme-btn-disabled-bg', lightTheme.theme_btn_disabled_bg || 'rgba(38, 50, 56, 0.05)');
        setVal('color-light-theme-primary-btn-hover-bg', lightTheme.theme_primary_btn_hover_bg || '#4caf50');
        setVal('color-light-theme-primary-btn-active-bg', lightTheme.theme_primary_btn_active_bg || '#388e3c');
        setVal('color-light-theme-danger-btn-bg', lightTheme.theme_danger_btn_bg || '#c63625');
        setVal('color-light-theme-danger-btn-hover-bg', lightTheme.theme_danger_btn_hover_bg || '#dc5242');
        setVal('color-light-theme-danger-btn-border', lightTheme.theme_danger_btn_border || '#9b2a1d');
        setVal('color-light-theme-warning-btn-bg', lightTheme.theme_warning_btn_bg || '#c79d1c');
        setVal('color-light-theme-warning-btn-hover-bg', lightTheme.theme_warning_btn_hover_bg || '#e1b42b');
        setVal('color-light-theme-warning-btn-border', lightTheme.theme_warning_btn_border || '#c79d1c');
        setVal('color-light-theme-warning-btn-hover-border', lightTheme.theme_warning_btn_hover_border || '#e1b42b');
        setVal('color-light-theme-tab-active-bg', lightTheme.theme_tab_active_bg || 'rgba(67, 160, 71, 0.2)');
        setVal('color-light-theme-tab-active-color', lightTheme.theme_tab_active_color || '#347c37');
        setVal('color-light-theme-tag-color', lightTheme.theme_tag_color || '#787459');
        setVal('color-light-theme-tag-color-hover', lightTheme.theme_tag_color_hover || '#4C482E');
        setVal('color-light-theme-tag-bg', lightTheme.theme_tag_bg || '#FAF6D8');
        setVal('color-light-theme-tag-bg-hover', lightTheme.theme_tag_bg_hover || '#F8F0C0');
        setVal('color-light-theme-special-light-color', lightTheme.theme_special_light_color || '#770000');
        setVal('color-light-theme-special-light-bg', lightTheme.theme_special_light_bg || '#F0F0FF');
        setVal('color-light-theme-find-replace-highlight-bg', lightTheme.theme_find_replace_highlight_bg || '#F5D87D');
    }

    async function saveColorSettings() {
        const darkTheme = {
            bg: document.getElementById('color-dark-bg')?.value,
            fg: document.getElementById('color-dark-fg')?.value,
            list_bg: document.getElementById('color-dark-list-bg')?.value,
            btn_bg: document.getElementById('color-dark-btn-bg')?.value,
            log_bg: document.getElementById('color-dark-log-bg')?.value,
            log_fg: document.getElementById('color-dark-log-fg')?.value,
            label: document.getElementById('color-dark-label')?.value,
            button_text: document.getElementById('color-dark-button-text')?.value,
            accent: document.getElementById('color-dark-accent')?.value,
            accent_fill: document.getElementById('color-dark-accent-fill')?.value,
            accent_text: document.getElementById('color-dark-accent-text')?.value,
            run_bg: document.getElementById('color-dark-run-bg')?.value,
            border: document.getElementById('color-dark-border')?.value,
            header_bg: document.getElementById('color-dark-header-bg')?.value,
            panel_bg: document.getElementById('color-dark-panel-bg')?.value,
            tab_inactive: document.getElementById('color-dark-tab-inactive')?.value,
            glow: document.getElementById('color-dark-glow')?.value,
            lore: document.getElementById('color-dark-lore')?.value,
            lore_hover: document.getElementById('color-dark-lore-hover')?.value,
            anach: document.getElementById('color-dark-anach')?.value,
            tooltip: document.getElementById('color-dark-tooltip')?.value,
            mask_015: document.getElementById('color-dark-mask-015')?.value,
            mask_025: document.getElementById('color-dark-mask-025')?.value,
            mask_03: document.getElementById('color-dark-mask-03')?.value,
            mask_05: document.getElementById('color-dark-mask-05')?.value,
            mask_08: document.getElementById('color-dark-mask-08')?.value,
            // Theme color channels
            theme_backgrounds_color: document.getElementById('color-dark-theme-backgrounds-color')?.value,
            theme_primaries_color: document.getElementById('color-dark-theme-primaries-color')?.value,
            theme_blacks: document.getElementById('color-dark-theme-blacks')?.value,
            theme_whites: document.getElementById('color-dark-theme-whites')?.value,
            theme_grays: document.getElementById('color-dark-theme-grays')?.value,
            theme_typeface_color: document.getElementById('color-dark-theme-typeface-color')?.value,
            theme_cards_color: document.getElementById('color-dark-theme-cards-color')?.value,
            // Theme colors
            theme_level_1_bg: document.getElementById('color-dark-theme-level-1-bg')?.value,
            theme_level_2_bg: document.getElementById('color-dark-theme-level-2-bg')?.value,
            theme_level_3_bg: document.getElementById('color-dark-theme-level-3-bg')?.value,
            theme_primary: document.getElementById('color-dark-theme-primary')?.value,
            theme_link_hover: document.getElementById('color-dark-theme-link-hover')?.value,
            theme_border_color: document.getElementById('color-dark-theme-border-color')?.value,
            theme_dark_border_color: document.getElementById('color-dark-theme-dark-border-color')?.value,
            theme_shimmer: document.getElementById('color-dark-theme-shimmer')?.value,
            theme_icons_color: document.getElementById('color-dark-theme-icons-color')?.value,
            theme_primary_green_50: document.getElementById('color-dark-theme-primary-green-50')?.value,
            theme_primary_green_100: document.getElementById('color-dark-theme-primary-green-100')?.value,
            theme_primary_blue_600: document.getElementById('color-dark-theme-primary-blue-600')?.value,
            theme_primary_blue_gray: document.getElementById('color-dark-theme-primary-blue-gray')?.value,
            theme_dark: document.getElementById('color-dark-theme-dark')?.value,
            theme_gray_005: document.getElementById('color-dark-theme-gray-005')?.value,
            theme_gray_01: document.getElementById('color-dark-theme-gray-01')?.value,
            theme_gray_02: document.getElementById('color-dark-theme-gray-02')?.value,
            theme_gray_03: document.getElementById('color-dark-theme-gray-03')?.value,
            theme_white_005: document.getElementById('color-dark-theme-white-005')?.value,
            theme_white_012: document.getElementById('color-dark-theme-white-012')?.value,
            theme_white: document.getElementById('color-dark-theme-white')?.value,
            theme_black: document.getElementById('color-dark-theme-black')?.value,
            theme_danger: document.getElementById('color-dark-theme-danger')?.value,
            theme_danger_hover_color: document.getElementById('color-dark-theme-danger-hover-color')?.value,
            theme_danger_bg: document.getElementById('color-dark-theme-danger-bg')?.value,
            theme_danger_bg_level_1: document.getElementById('color-dark-theme-danger-bg-level-1')?.value,
            theme_danger_bg_level_2: document.getElementById('color-dark-theme-danger-bg-level-2')?.value,
            theme_info: document.getElementById('color-dark-theme-info')?.value,
            theme_info_bg: document.getElementById('color-dark-theme-info-bg')?.value,
            theme_info_link: document.getElementById('color-dark-theme-info-link')?.value,
            theme_warning: document.getElementById('color-dark-theme-warning')?.value,
            theme_warning_bg: document.getElementById('color-dark-theme-warning-bg')?.value,
            theme_warning_link: document.getElementById('color-dark-theme-warning-link')?.value,
            theme_success: document.getElementById('color-dark-theme-success')?.value,
            theme_success_bg: document.getElementById('color-dark-theme-success-bg')?.value,
            theme_success_link: document.getElementById('color-dark-theme-success-link')?.value,
            theme_btn_hover_bg: document.getElementById('color-dark-theme-btn-hover-bg')?.value,
            theme_btn_active_bg: document.getElementById('color-dark-theme-btn-active-bg')?.value,
            theme_btn_disabled_bg: document.getElementById('color-dark-theme-btn-disabled-bg')?.value,
            theme_primary_btn_hover_bg: document.getElementById('color-dark-theme-primary-btn-hover-bg')?.value,
            theme_primary_btn_active_bg: document.getElementById('color-dark-theme-primary-btn-active-bg')?.value,
            theme_danger_btn_bg: document.getElementById('color-dark-theme-danger-btn-bg')?.value,
            theme_danger_btn_hover_bg: document.getElementById('color-dark-theme-danger-btn-hover-bg')?.value,
            theme_danger_btn_border: document.getElementById('color-dark-theme-danger-btn-border')?.value,
            theme_warning_btn_bg: document.getElementById('color-dark-theme-warning-btn-bg')?.value,
            theme_warning_btn_hover_bg: document.getElementById('color-dark-theme-warning-btn-hover-bg')?.value,
            theme_warning_btn_border: document.getElementById('color-dark-theme-warning-btn-border')?.value,
            theme_warning_btn_hover_border: document.getElementById('color-dark-theme-warning-btn-hover-border')?.value,
            theme_tab_active_bg: document.getElementById('color-dark-theme-tab-active-bg')?.value,
            theme_tab_active_color: document.getElementById('color-dark-theme-tab-active-color')?.value,
            theme_tag_color: document.getElementById('color-dark-theme-tag-color')?.value,
            theme_tag_color_hover: document.getElementById('color-dark-theme-tag-color-hover')?.value,
            theme_tag_bg: document.getElementById('color-dark-theme-tag-bg')?.value,
            theme_tag_bg_hover: document.getElementById('color-dark-theme-tag-bg-hover')?.value,
            theme_special_light_color: document.getElementById('color-dark-theme-special-light-color')?.value,
            theme_special_light_bg: document.getElementById('color-dark-theme-special-light-bg')?.value,
            theme_find_replace_highlight_bg: document.getElementById('color-dark-theme-find-replace-highlight-bg')?.value,
        };

        const lightTheme = {
            bg: document.getElementById('color-light-bg')?.value,
            fg: document.getElementById('color-light-fg')?.value,
            list_bg: document.getElementById('color-light-list-bg')?.value,
            btn_bg: document.getElementById('color-light-btn-bg')?.value,
            log_bg: document.getElementById('color-light-log-bg')?.value,
            log_fg: document.getElementById('color-light-log-fg')?.value,
            label: document.getElementById('color-light-label')?.value,
            button_text: document.getElementById('color-light-button-text')?.value,
            accent: document.getElementById('color-light-accent')?.value,
            accent_fill: document.getElementById('color-light-accent-fill')?.value,
            accent_text: document.getElementById('color-light-accent-text')?.value,
            run_bg: document.getElementById('color-light-run-bg')?.value,
            border: document.getElementById('color-light-border')?.value,
            header_bg: document.getElementById('color-light-header-bg')?.value,
            panel_bg: document.getElementById('color-light-panel-bg')?.value,
            tab_inactive: document.getElementById('color-light-tab-inactive')?.value,
            glow: document.getElementById('color-light-glow')?.value,
            lore: document.getElementById('color-light-lore')?.value,
            lore_hover: document.getElementById('color-light-lore-hover')?.value,
            anach: document.getElementById('color-light-anach')?.value,
            tooltip: document.getElementById('color-light-tooltip')?.value,
            mask_015: document.getElementById('color-light-mask-015')?.value,
            mask_025: document.getElementById('color-light-mask-025')?.value,
            mask_03: document.getElementById('color-light-mask-03')?.value,
            mask_05: document.getElementById('color-light-mask-05')?.value,
            mask_08: document.getElementById('color-light-mask-08')?.value,
            // Theme color channels
            theme_backgrounds_color: document.getElementById('color-light-theme-backgrounds-color')?.value,
            theme_primaries_color: document.getElementById('color-light-theme-primaries-color')?.value,
            theme_blacks: document.getElementById('color-light-theme-blacks')?.value,
            theme_whites: document.getElementById('color-light-theme-whites')?.value,
            theme_grays: document.getElementById('color-light-theme-grays')?.value,
            theme_typeface_color: document.getElementById('color-light-theme-typeface-color')?.value,
            theme_cards_color: document.getElementById('color-light-theme-cards-color')?.value,
            // Theme colors
            theme_level_1_bg: document.getElementById('color-light-theme-level-1-bg')?.value,
            theme_level_2_bg: document.getElementById('color-light-theme-level-2-bg')?.value,
            theme_level_3_bg: document.getElementById('color-light-theme-level-3-bg')?.value,
            theme_primary: document.getElementById('color-light-theme-primary')?.value,
            theme_link_hover: document.getElementById('color-light-theme-link-hover')?.value,
            theme_border_color: document.getElementById('color-light-theme-border-color')?.value,
            theme_dark_border_color: document.getElementById('color-light-theme-dark-border-color')?.value,
            theme_shimmer: document.getElementById('color-light-theme-shimmer')?.value,
            theme_icons_color: document.getElementById('color-light-theme-icons-color')?.value,
            theme_primary_green_50: document.getElementById('color-light-theme-primary-green-50')?.value,
            theme_primary_green_100: document.getElementById('color-light-theme-primary-green-100')?.value,
            theme_primary_blue_600: document.getElementById('color-light-theme-primary-blue-600')?.value,
            theme_primary_blue_gray: document.getElementById('color-light-theme-primary-blue-gray')?.value,
            theme_dark: document.getElementById('color-light-theme-dark')?.value,
            theme_gray_005: document.getElementById('color-light-theme-gray-005')?.value,
            theme_gray_01: document.getElementById('color-light-theme-gray-01')?.value,
            theme_gray_02: document.getElementById('color-light-theme-gray-02')?.value,
            theme_gray_03: document.getElementById('color-light-theme-gray-03')?.value,
            theme_white_005: document.getElementById('color-light-theme-white-005')?.value,
            theme_white_012: document.getElementById('color-light-theme-white-012')?.value,
            theme_white: document.getElementById('color-light-theme-white')?.value,
            theme_black: document.getElementById('color-light-theme-black')?.value,
            theme_danger: document.getElementById('color-light-theme-danger')?.value,
            theme_danger_hover_color: document.getElementById('color-light-theme-danger-hover-color')?.value,
            theme_danger_bg: document.getElementById('color-light-theme-danger-bg')?.value,
            theme_danger_bg_level_1: document.getElementById('color-light-theme-danger-bg-level-1')?.value,
            theme_danger_bg_level_2: document.getElementById('color-light-theme-danger-bg-level-2')?.value,
            theme_info: document.getElementById('color-light-theme-info')?.value,
            theme_info_bg: document.getElementById('color-light-theme-info-bg')?.value,
            theme_info_link: document.getElementById('color-light-theme-info-link')?.value,
            theme_warning: document.getElementById('color-light-theme-warning')?.value,
            theme_warning_bg: document.getElementById('color-light-theme-warning-bg')?.value,
            theme_warning_link: document.getElementById('color-light-theme-warning-link')?.value,
            theme_success: document.getElementById('color-light-theme-success')?.value,
            theme_success_bg: document.getElementById('color-light-theme-success-bg')?.value,
            theme_success_link: document.getElementById('color-light-theme-success-link')?.value,
            theme_btn_hover_bg: document.getElementById('color-light-theme-btn-hover-bg')?.value,
            theme_btn_active_bg: document.getElementById('color-light-theme-btn-active-bg')?.value,
            theme_btn_disabled_bg: document.getElementById('color-light-theme-btn-disabled-bg')?.value,
            theme_primary_btn_hover_bg: document.getElementById('color-light-theme-primary-btn-hover-bg')?.value,
            theme_primary_btn_active_bg: document.getElementById('color-light-theme-primary-btn-active-bg')?.value,
            theme_danger_btn_bg: document.getElementById('color-light-theme-danger-btn-bg')?.value,
            theme_danger_btn_hover_bg: document.getElementById('color-light-theme-danger-btn-hover-bg')?.value,
            theme_danger_btn_border: document.getElementById('color-light-theme-danger-btn-border')?.value,
            theme_warning_btn_bg: document.getElementById('color-light-theme-warning-btn-bg')?.value,
            theme_warning_btn_hover_bg: document.getElementById('color-light-theme-warning-btn-hover-bg')?.value,
            theme_warning_btn_border: document.getElementById('color-light-theme-warning-btn-border')?.value,
            theme_warning_btn_hover_border: document.getElementById('color-light-theme-warning-btn-hover-border')?.value,
            theme_tab_active_bg: document.getElementById('color-light-theme-tab-active-bg')?.value,
            theme_tab_active_color: document.getElementById('color-light-theme-tab-active-color')?.value,
            theme_tag_color: document.getElementById('color-light-theme-tag-color')?.value,
            theme_tag_color_hover: document.getElementById('color-light-theme-tag-color-hover')?.value,
            theme_tag_bg: document.getElementById('color-light-theme-tag-bg')?.value,
            theme_tag_bg_hover: document.getElementById('color-light-theme-tag-bg-hover')?.value,
            theme_special_light_color: document.getElementById('color-light-theme-special-light-color')?.value,
            theme_special_light_bg: document.getElementById('color-light-theme-special-light-bg')?.value,
            theme_find_replace_highlight_bg: document.getElementById('color-light-theme-find-replace-highlight-bg')?.value,
        };

        await eel.save_config_field('custom_dark_theme', darkTheme)();
        await eel.save_config_field('custom_light_theme', lightTheme)();
        
        // Apply the new colors immediately from the saved values
        const darkMode = state.settings.lastConfig?.dark_mode || false;
        const currentTheme = darkMode ? darkTheme : lightTheme;
        applyTheme(currentTheme);
        updateThemeIcon(currentTheme);
    }

    // Add change event listeners
    // Color picker change handlers
    document.querySelectorAll('input[type="color"]').forEach(input => {
        input.addEventListener('input', saveColorSettings);
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
            await loadColorSettings();
            const themeColors = await eel.get_theme_colors()();
            applyTheme(themeColors);
            updateThemeIcon(themeColors);
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
    
    // --- GitHub Sync ---
    const btnSyncPush = document.getElementById('btn-sync-push');
    if (btnSyncPush) btnSyncPush.onclick = async () => {
        btnSyncPush.innerText = 'PUSHING...';
        const res = await eel.sync_push()();
        btnSyncPush.innerText = 'PUSH TO GITHUB';
        openAlertModal(res.ok ? 'SUCCESS' : 'ERROR', res.message || res.error);
        updateSyncStatusDisplay();
    };
    
    const btnSyncPull = document.getElementById('btn-sync-pull');
    if (btnSyncPull) btnSyncPull.onclick = async () => {
        btnSyncPull.innerText = 'PULLING...';
        const res = await eel.sync_pull()();
        btnSyncPull.innerText = 'PULL FROM GITHUB';
        openAlertModal(res.ok ? 'SUCCESS' : 'ERROR', res.message || res.error);
        updateSyncStatusDisplay();
    };
    
    const btnSyncTest = document.getElementById('btn-sync-test');
    if (btnSyncTest) btnSyncTest.onclick = async () => {
        const status = await eel.get_sync_status()();
        openAlertModal(status.ok && status.configured ? 'CONFIGURED' : 'NOT CONFIGURED', 
            `Repo: ${status.repo || 'N/A'}<br>Language: ${status.language}<br>Auto: ${status.auto_sync ? 'ON' : 'OFF'}`);
    };
    
    // Sync settings auto-save on blur
    const setupSyncBlur = (id, key) => {
        const el = document.getElementById(id);
        if (el) el.onblur = async () => { 
            await eel.save_config_field(key, el.value.trim())();
            updateSyncStatusDisplay();
        };
    };
    setupSyncBlur('opt-github-repo', 'github_repo');
    setupSyncBlur('opt-github-token', 'github_token');
    setupSyncBlur('opt-sync-nickname', 'sync_nickname');
    
    const syncLanguage = document.getElementById('opt-sync-language');
    if (syncLanguage) syncLanguage.onchange = async () => {
        await eel.save_config_field('sync_language', syncLanguage.value)();
        updateSyncStatusDisplay();
    };
    
    const syncAuto = document.getElementById('opt-sync-auto');
    if (syncAuto) syncAuto.onchange = async () => {
        await eel.save_config_field('sync_auto', syncAuto.checked)();
        updateSyncStatusDisplay();
    };
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
        switchTab('editor');
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
    switchTab('editor');
    loadItemAtIdx(0);
}

// =============================================================================
// KEYBOARD SHORTCUTS
// =============================================================================
const undoStack = [];
const redoStack = [];
const MAX_UNDO = 50;

function saveUndoState(caller = 'unknown') {
    const ed = document.getElementById('en-editor');
    if (!ed) return;
    
    // Log DOM structure at time of save
    let domDump = '';
    for (let i = 0; i < ed.childNodes.length; i++) {
        const n = ed.childNodes[i];
        if (n.nodeType === Node.TEXT_NODE) domDump += `TEXT(${n.length}) `;
        else if (n.nodeName === 'BR') domDump += 'BR ';
        else domDump += `${n.nodeName} `;
    }
    console.log(`[saveUndoState] DOM: ${domDump}`);
    
    // Save both text and cursor position
    const selection = window.getSelection();
    const range = selection.rangeCount > 0 ? selection.getRangeAt(0) : null;
    const nodeIndex = range ? Array.from(ed.childNodes).indexOf(range.endContainer) : -1;
    console.log(`[saveUndoState] caller=${caller}, nodeIndex=${nodeIndex}, endContainer=${range?.endContainer?.nodeName}, text="${range?.endContainer?.textContent?.substring(0,20)}"`);
    const cursorOffset = range ? getCaretOffset(ed, range.cloneRange()) : null;
    console.log(`[saveUndoState] calculated cursorOffset=${cursorOffset}`);
    
    undoStack.push({
        text: ed.innerText,
        cursorOffset: cursorOffset
    });
    
    if (undoStack.length > MAX_UNDO) undoStack.shift();
    redoStack.length = 0; // Clear redo stack on new action
}

function undo() {
    if (undoStack.length === 0) return;
    const ed = document.getElementById('en-editor');
    if (!ed) return;
    
    // Save current state for redo (with cursor position)
    const selection = window.getSelection();
    const range = selection.rangeCount > 0 ? selection.getRangeAt(0).cloneRange() : null;
    const cursorOffset = range ? getCaretOffset(ed, range) : null;
    
    console.log(`[undo] Current text length: ${ed.innerText.length}, cursor at: ${cursorOffset}`);
    
    redoStack.push({
        text: ed.innerText,
        cursorOffset: cursorOffset
    });
    
    const previous = undoStack.pop();
    console.log(`[undo] Restoring text length: ${previous.text.length}, cursor to: ${previous.cursorOffset}`);
    
    // Disable input event handling during restore
    if (ed._setSkipInputHandling) ed._setSkipInputHandling(true);
    
    // Restore text (this would normally trigger input event)
    ed.innerText = previous.text;
    
    // Restore cursor position - add small delay to ensure DOM is updated
    setTimeout(() => {
        try {
            if (previous.cursorOffset !== null) {
                console.log(`[undo] About to restore cursor to offset ${previous.cursorOffset}`);
                restoreCursor(ed, previous.cursorOffset);
                
                // Get actual position after restore
                const selection2 = window.getSelection();
                const range2 = selection2.rangeCount > 0 ? selection2.getRangeAt(0).cloneRange() : null;
                const finalCursorPos = range2 ? getCaretOffset(ed, range2) : null;
                console.log(`[undo] Final cursor position after restore: ${finalCursorPos} (requested: ${previous.cursorOffset})`);
            }
        } finally {
            // Re-enable input event handling (inside try-finally to ensure it happens)
            if (ed._setSkipInputHandling) ed._setSkipInputHandling(false);
            
            // Manually update display - but don't call updateReviewerCounters() as it triggers scan
            syncLineCounters();
            
            // Update line count display only
            const cc = document.getElementById('char-count');
            if (cc) {
                const lines = ed.innerText.split('\n');
                const maxLines = state.maxLines || 5;
                const lineCount = lines.length;
                cc.innerText = `${lineCount} / ${maxLines} lines`;
                cc.style.color = lineCount > maxLines ? '#ff4444' : 'var(--accent-color)';
            }
            
            // Schedule anachronism scan a bit later so it doesn't interfere with cursor
            setTimeout(() => {
                scanAnachronisms(ed.innerText);
            }, 50);
        }
    }, 0);
}

function redo() {
    if (redoStack.length === 0) return;
    const ed = document.getElementById('en-editor');
    if (!ed) return;
    
    // Save current state for undo (with cursor position)
    const selection = window.getSelection();
    const range = selection.rangeCount > 0 ? selection.getRangeAt(0).cloneRange() : null;
    const cursorOffset = range ? getCaretOffset(ed, range) : null;
    
    undoStack.push({
        text: ed.innerText,
        cursorOffset: cursorOffset
    });
    
    const next = redoStack.pop();
    console.log(`[redo] Restoring text length: ${next.text.length}, cursor to: ${next.cursorOffset}`);
    
    // Disable input event handling during restore
    if (ed._setSkipInputHandling) ed._setSkipInputHandling(true);
    
    // Restore text (this would normally trigger input event)
    ed.innerText = next.text;
    
    // Restore cursor position - add small delay to ensure DOM is updated
    setTimeout(() => {
        try {
            if (next.cursorOffset !== null) {
                console.log(`[redo] About to restore cursor to offset ${next.cursorOffset}`);
                restoreCursor(ed, next.cursorOffset);
                
                // Get actual position after restore
                const selection2 = window.getSelection();
                const range2 = selection2.rangeCount > 0 ? selection2.getRangeAt(0).cloneRange() : null;
                const finalCursorPos = range2 ? getCaretOffset(ed, range2) : null;
                console.log(`[redo] Final cursor position after restore: ${finalCursorPos} (requested: ${next.cursorOffset})`);
            }
        } finally {
            // Re-enable input event handling (inside try-finally to ensure it happens)
            if (ed._setSkipInputHandling) ed._setSkipInputHandling(false);
            
            // Manually update display - but don't call updateReviewerCounters() as it triggers scan
            syncLineCounters();
            
            // Update line count display only
            const cc = document.getElementById('char-count');
            if (cc) {
                const lines = ed.innerText.split('\n');
                const maxLines = state.maxLines || 5;
                const lineCount = lines.length;
                cc.innerText = `${lineCount} / ${maxLines} lines`;
                cc.style.color = lineCount > maxLines ? '#ff4444' : 'var(--accent-color)';
            }
            
            // Schedule anachronism scan a bit later so it doesn't interfere with cursor
            setTimeout(() => {
                scanAnachronisms(ed.innerText);
            }, 50);
        }
    }, 0);
}

function initShortcuts() {
    window.addEventListener('keydown', e => {
        if (state.currentTab !== 'editor') return;
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

async function updateSyncStatusDisplay() {
    const display = document.getElementById('sync-status-display');
    if (!display) return;
    
    try {
        const status = await eel.get_sync_status()();
        if (status.ok) {
            const configured = status.configured ? 'YES' : 'NO';
            const repo = status.repo || '(not set)';
            const lang = status.language || 'English';
            const auto = status.auto_sync ? 'ON' : 'OFF';
            display.innerHTML = `Status: ${configured}<br>Repo: ${repo}<br>Language: ${lang}<br>Auto-sync: ${auto}`;
        } else {
            display.innerHTML = 'Error loading sync status';
        }
    } catch (e) {
        display.innerHTML = 'Sync not available';
    }
}
function escAttr(s) { return escHtml(s); }

// =============================================================================
// CROWDIN-STYLE TRANSLATION MANAGEMENT
// =============================================================================

function togglePanel(panelId) {
    const panel = document.getElementById(panelId)?.closest('.kl-panel');
    if (panel) {
        const isHidden = panel.style.display === 'none';
        panel.style.display = isHidden ? '' : 'none';
        console.log(`[togglePanel] ${panelId}: ${isHidden ? 'shown' : 'hidden'}`);
    }
}

async function updateTranslationStatusBadge(entryId) {
    const badge = document.getElementById('translation-status');
    if (!badge) return;
    
    try {
        const res = await eel.get_translation_status(entryId)();
        if (res && res.ok) {
            const status = res.status || 'untranslated';
            badge.innerText = status.charAt(0).toUpperCase() + status.slice(1);
            badge.className = `kl-status-badge status-${status}`;
        } else {
            badge.innerText = 'Untranslated';
            badge.className = 'kl-status-badge status-untranslated';
        }
    } catch (e) {
        console.error('[updateTranslationStatusBadge] Error:', e);
        badge.innerText = 'Untranslated';
        badge.className = 'kl-status-badge status-untranslated';
    }
}

async function approveCurrentTranslation() {
    const item = state.reviewer.currentItem;
    if (!item) {
        openAlertModal('ERROR', 'No item selected to approve.');
        return;
    }

    try {
        // First save the translation to CSV
        const text = document.getElementById('en-editor').innerText;
        await eel.apply_fix(item.id, text, false)();

        // Then approve it
        const nickname = state.settings.lastConfig?.sync_nickname || 'reviewer';
        const res = await eel.approve_translation(item.id, nickname)();
        if (res && res.ok) {
            await updateTranslationStatusBadge(item.id);
            await loadTranslationHistory(item.id);
            // Move to next item after approval
            setTimeout(() => nextItem(), 400);
        } else {
            openAlertModal('ERROR', res?.error || 'Failed to approve translation.');
        }
    } catch (e) {
        console.error('[approveCurrentTranslation] Error:', e);
        openAlertModal('ERROR', 'Error approving translation.');
    }
}

async function rejectCurrentTranslation() {
    const item = state.reviewer.currentItem;
    if (!item) {
        openAlertModal('ERROR', 'No item selected to reject.');
        return;
    }
    
    try {
        const res = await eel.reject_translation(item.id, 'reviewer', 'Translation needs improvement')();
        if (res && res.ok) {
            await updateTranslationStatusBadge(item.id);
            await loadTranslationHistory(item.id);
        } else {
            openAlertModal('ERROR', res?.error || 'Failed to reject translation.');
        }
    } catch (e) {
        console.error('[rejectCurrentTranslation] Error:', e);
        openAlertModal('ERROR', 'Error rejecting translation.');
    }
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

async function loadTranslationHistory(entryId) {
    const historyContainer = document.getElementById('translation-history');
    const historyPanel = document.getElementById('panel-history');
    console.log('[loadTranslationHistory] entryId:', entryId, 'container:', !!historyContainer, 'panel collapsed:', historyPanel?.classList.contains('collapsed'));
    if (!historyContainer) return;

    try {
        const res = await eel.get_translation_history(entryId)();
        console.log('[loadTranslationHistory] response:', res);
        if (res && res.ok && res.history && res.history.length > 0) {
            // Show all history entries except comments and approve/reject (old log entries)
            const filteredHistory = res.history.filter(h => h.action !== 'comment' && h.action !== 'approve' && h.action !== 'reject');
            console.log('[loadTranslationHistory] Showing', filteredHistory.length, 'entries (excluding comments, approve, reject)');
            if (filteredHistory.length > 0) {
                // Use full history to check for approve/reject actions after each translate
                const fullHistory = res.history || [];
                console.log('[loadTranslationHistory] Full history length:', fullHistory.length);
                console.log('[loadTranslationHistory] Full history actions:', JSON.stringify(fullHistory.map(h => ({ action: h.action, time: h.timestamp }))));

                historyContainer.innerHTML = filteredHistory.map((h, idx) => {
                    const actionLabel = h.action === 'translate' ? 'Edit' : h.action;
                    // For translate entries, check if there was an approve/reject action after this entry with matching text
                    let statusBadge = '';
                    let displayUser = h.user;
                    if (h.action === 'translate') {
                        const entryTimestamp = new Date(h.timestamp).getTime();
                        // Find the first approve/reject action after this translate entry with matching text
                        const laterAction = fullHistory.find(log =>
                            (log.action === 'approve' || log.action === 'reject') &&
                            new Date(log.timestamp).getTime() > entryTimestamp &&
                            log.new_value === h.new_value
                        );
                        console.log('[loadTranslationHistory] For entry at', new Date(h.timestamp).toLocaleString(), 'laterAction:', laterAction?.action);
                        if (laterAction) {
                            // Show approver's name instead of translator's name
                            displayUser = laterAction.user;
                            if (laterAction.action === 'approve') {
                                statusBadge = `<span class="kl-history-status-inline status-approve">APPROVED</span>`;
                            } else {
                                statusBadge = `<span class="kl-history-status-inline status-reject">REJECTED</span>`;
                            }
                        } else {
                            // No matching approve/reject after this entry, check if it's the latest
                            const latestTranslate = filteredHistory.filter(e => e.action === 'translate').sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp))[0];
                            if (latestTranslate && new Date(latestTranslate.timestamp).getTime() === entryTimestamp) {
                                // This is the latest entry, show current status
                                if (res.status === 'approved') {
                                    statusBadge = `<span class="kl-history-status-inline status-approve">APPROVED</span>`;
                                } else if (res.status === 'rejected') {
                                    statusBadge = `<span class="kl-history-status-inline status-reject">REJECTED</span>`;
                                } else {
                                    statusBadge = `<span class="kl-history-status-inline status-unapproved">UNAPPROVED</span>`;
                                }
                            }
                        }
                    }
                    return `
                    <div class="kl-history-item" data-history-idx="${idx}" data-text="${escapeHtml(h.new_value || '')}" style="cursor: pointer;">
                        <div class="kl-history-header">
                            <span class="kl-history-action action-${h.action}">${actionLabel}</span>
                            ${statusBadge}
                            <span class="kl-history-user">by ${displayUser}</span>
                            <span class="kl-history-time">${new Date(h.timestamp).toLocaleString()}</span>
                        </div>
                        ${h.new_value ? `<div class="kl-history-text">${escapeHtml(h.new_value)}</div>` : ''}
                    </div>
                    `;
                }).join('');

                // Scroll to bottom to show most recent entries
                historyContainer.scrollTop = historyContainer.scrollHeight;

                // Add click handlers to history items
                historyContainer.querySelectorAll('.kl-history-item').forEach(item => {
                    item.addEventListener('click', () => {
                        const text = item.getAttribute('data-text');
                        if (text) {
                            const editor = document.getElementById('en-editor');
                            if (editor) {
                                editor.innerText = text;
                                console.log('[loadTranslationHistory] Pasted history text into editor');
                            }
                        }
                    });
                });

                // Auto-load latest history entry into editor when in unapproved entries queue
                if (state.reviewer.currentCategory === 'Unapproved Entries') {
                    const latestTranslateEntry = filteredHistory.filter(h => h.action === 'translate').sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp))[0];
                    if (latestTranslateEntry && latestTranslateEntry.new_value) {
                        const editor = document.getElementById('en-editor');
                        if (editor) {
                            editor.innerText = latestTranslateEntry.new_value;
                            console.log('[loadTranslationHistory] Auto-loaded latest history text into editor for unapproved entries queue');
                        }
                    }
                }

                console.log('[loadTranslationHistory] Updated innerHTML, content length:', historyContainer.innerHTML.length);
            } else {
                console.log('[loadTranslationHistory] No non-comment history found');
                historyContainer.innerHTML = '<div class="kl-history-empty">No translation history available</div>';
            }
        } else {
            console.log('[loadTranslationHistory] No history found');
            historyContainer.innerHTML = '<div class="kl-history-empty">No history available</div>';
        }
    } catch (e) {
        console.error('[loadTranslationHistory] Error:', e);
        historyContainer.innerHTML = '<div class="kl-history-empty">Error loading history</div>';
    }
}

async function addTranslationComment() {
    const item = state.reviewer.currentItem;
    if (!item) {
        openAlertModal('ERROR', 'No item selected.');
        return;
    }
    
    const input = document.getElementById('comment-input');
    if (!input || !input.value.trim()) return;
    
    try {
        const nickname = state.settings.lastConfig?.sync_nickname || 'reviewer';
        const res = await eel.add_translation_comment(item.id, nickname, input.value.trim())();
        if (res && res.ok) {
            input.value = '';
            await loadTranslationComments(item.id);
        } else {
            openAlertModal('ERROR', res?.error || 'Failed to add comment.');
        }
    } catch (e) {
        console.error('[addTranslationComment] Error:', e);
        openAlertModal('ERROR', 'Error adding comment.');
    }
}

async function loadTranslationComments(entryId) {
    const commentsContainer = document.querySelector('#translation-comments .kl-comments-list');
    if (!commentsContainer) return;
    
    try {
        const res = await eel.get_translation_comments(entryId)();
        if (res && res.ok && res.comments && res.comments.length > 0) {
            commentsContainer.innerHTML = res.comments.map(c => `
                <div class="kl-comment">
                    <div class="kl-comment-header">
                        <span class="kl-comment-user">${escHtml(c.user)}</span>
                        <span class="kl-comment-time">${new Date(c.timestamp).toLocaleString()}</span>
                    </div>
                    <div class="kl-comment-text">${escHtml(c.text)}</div>
                </div>
            `).join('');
        } else {
            commentsContainer.innerHTML = '<div class="kl-history-empty">No comments</div>';
        }
    } catch (e) {
        console.error('[loadTranslationComments] Error:', e);
        commentsContainer.innerHTML = '<div class="kl-history-empty">Error loading comments</div>';
    }
}

// Note: Event listeners for reviewer mode are initialized in initReviewerActions()
