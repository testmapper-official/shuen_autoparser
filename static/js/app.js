let currentConfig = {}, selectedBackup = null, selectedLog = null, T = {}; 
let backupPolling = null, timerInterval = null, syncPolling = null;
let currentTab = 'backups';
let isPendingBackup = false;

const api = async (u, d) => {
    try {
        const r = await fetch(u, d ? {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(d)} : {});
        return await r.json();
    } catch(e) {
        return {error: e.message};
    }
};

window.onload = async () => {
    await loadConfig();
    await loadLanguage(currentConfig.lang || 'ru');
    initListeners();
    startTimer();
    
    loadFiles();
    backupPolling = setInterval(loadFiles, 15000);
    checkSyncStatus();
    syncPolling = setInterval(checkSyncStatus, 2000);
    
    document.addEventListener('click', handleTagClicks);
    
    // Предупреждение при закрытии
    window.addEventListener('beforeunload', (e) => {
        if (isPendingBackup) {
            e.preventDefault();
            e.returnValue = '';
        }
    });
};

function startTimer() {
    clearInterval(timerInterval);
    timerInterval = setInterval(updateTimerUI, 1000);
}

function updateTimerUI() {
    if (!currentConfig.last_parse_time || currentConfig.last_parse_time === 0) {
        document.getElementById('lastCheckWidget').style.display = 'none';
        return;
    }
    document.getElementById('lastCheckWidget').style.display = 'block';
    const diff = Math.floor(Date.now() / 1000) - currentConfig.last_parse_time;
    const el = document.getElementById('lastCheckTime');
    if (diff < 60) el.innerText = `${T.LAST_CHECK || 'Last check:'} ${diff} ${T.AGO_SEC || 'sec. ago'}`;
    else el.innerText = `${T.LAST_CHECK || 'Last check:'} ${Math.floor(diff / 60)} ${T.AGO_MIN || 'min. ago'}`;
}

async function loadLanguage(lang) {
    T = await api(`/api/locales/${lang}`);
    currentConfig.lang = lang;
    document.querySelectorAll('[data-i18n]').forEach(el => { if(T[el.dataset.i18n]) el.innerText = T[el.dataset.i18n]; });
    document.querySelectorAll('[data-i18n-placeholder]').forEach(el => { if(T[el.dataset.i18nPlaceholder]) el.placeholder = T[el.dataset.i18nPlaceholder]; });
    document.title = T.APP_TITLE || "WC3 Manager";
    
    const langBtn = document.getElementById('langBtn');
    if (langBtn) langBtn.innerText = lang.toUpperCase();
    
    updateUI();
    updateTabUI();
    loadFiles();
    checkSyncStatus();
}

function initListeners() {
    document.getElementById('langBtn').onclick = async () => {
        const langs = await api('/api/available_locales');
        const list = document.getElementById('langList');
        list.innerHTML = '';
        langs.forEach(l => {
            const btn = document.createElement('button');
            btn.className = 'lang-btn';
            btn.innerText = l.toUpperCase();
            btn.onclick = async () => { await api('/api/config', {lang: l}); await loadLanguage(l); closeModal('langModal'); };
            list.appendChild(btn);
        });
        openModal('langModal');
    };

    document.getElementById('hookBtn').onclick = async () => {
        const btn = document.getElementById('hookBtn');
        const isCurrentlyOn = btn.classList.contains('active');

        if (isCurrentlyOn) {
            const r = await api('/api/sync/toggle', {});
            if (r.error) showAlert(T.ERROR_TITLE||'Error', r.error);
            checkSyncStatus();
            return;
        }

        const statusRes = await api('/api/sync/status');
        if (statusRes.is_admin) {
            const r = await api('/api/sync/toggle', {});
            if (r.error) showAlert(T.ERROR_TITLE||'Error', r.error);
            checkSyncStatus();
        } else {
            showConfirm(T.NEED_ADMIN_TITLE || "Admin Rights Required", T.NEED_ADMIN_MSG || "Restart to request admin?", async () => {
                closeModal('confirmModal');
                showAlert(T.NEED_ADMIN_TITLE, T.RESTARTING_MSG || "Restarting...");
                await api('/api/sync/elevate', {});
                setTimeout(() => window.close(), 1500);
            });
        }
    };

    document.getElementById('renameBackupBtn').onclick = () => {
        if (!selectedBackup) return;
        document.getElementById('inputRename').value = selectedBackup;
        openModal('renameModal');
    };

    document.getElementById('settingsBtn').onclick = () => {
        document.getElementById('intervalSlider').value = currentConfig.interval || 15;
        document.getElementById('intervalValue').innerText = currentConfig.interval || 15;
        openModal('intervalModal');
    };

    document.getElementById('intervalSlider').oninput = (e) => {
        document.getElementById('intervalValue').innerText = e.target.value;
    };

    document.getElementById('settingsPathBtn').onclick = () => selectPath();
    document.getElementById('changePathBtn').onclick = () => selectPath();

    document.getElementById('launchBtn').onclick = async () => {
        const r = await api('/api/launch', {});
        if(r.error) showAlert(T.ERROR_TITLE||'Error', r.error);
    };

    document.getElementById('profileBtn').onclick = () => {
        document.getElementById('inputProfile').value=currentConfig.profile||'';
        document.getElementById('inputPassword').value=currentConfig.password||'';

        const closeBtn = document.getElementById('profileModalClose');
        const titleEl = document.getElementById('profileModalTitle');

        if (currentConfig.hash) {
            closeBtn.style.display = 'flex';
            titleEl.innerText = T.PROFILE_MODAL_TITLE || "Profile Setup";
        } else {
            closeBtn.style.display = 'none';
            titleEl.innerText = T.STEP1_TITLE || "Step 1: Profile Setup";
        }

        openModal('profileModal');
    };
    
    document.getElementById('profileModalClose').onclick = () => {
        if (currentConfig.hash) closeModal('profileModal');
    };

    document.getElementById('deleteBackupBtn').onclick = () => showConfirm(T.CONFIRM_TITLE, (T.DELETE_CONFIRM||'Delete?').replace('{name}', selectedBackup), async () => {
        await api('/api/backups/delete', {filename: selectedBackup});
        closeModal('confirmModal');
        selectedBackup=null;
        document.getElementById('actionCard').style.display='none';
        document.getElementById('emptyState').style.display='block';
        loadFiles();
    });

    document.getElementById('restoreBackupBtn').onclick = () => showConfirm(T.CONFIRM_TITLE, (T.RESTORE_CONFIRM||'Restore?').replace('{name}', selectedBackup), async () => {
        const r = await api('/api/backups/restore', {filename: selectedBackup});
        closeModal('confirmModal');
        if(r.error) showAlert(T.ERROR_TITLE||'Error', r.error);
        else showAlert(T.SUCCESS||'Success', T.RESTORE_SUCCESS||'Restored!');
    });

    document.getElementById('tabBackups').onclick = () => { currentTab = 'backups'; updateTabUI(); loadFiles(); };
    document.getElementById('tabLogs').onclick = () => { currentTab = 'logs'; updateTabUI(); loadFiles(); };

    document.querySelectorAll('.modal-overlay').forEach(o => o.onclick = e => {
        if(e.target === o) {
            if (o.id === 'profileModal' && !currentConfig.hash) return;
            if (o.id === 'pathModal' && !currentConfig.bat_path) return;
            o.style.display='none';
        }
    });
}

function updateTabUI() {
    document.getElementById('tabBackups').classList.toggle('active', currentTab === 'backups');
    document.getElementById('tabLogs').classList.toggle('active', currentTab === 'logs');
    document.getElementById('explorerHeader').innerText = currentTab === 'backups' ? (T.EXPLORER_HEADER || "Backups") : (T.TAB_LOGS || "Logs");
}

function selectPath() {
    api('/api/select_path', {}).then(cfg => {
        if (!cfg.error && cfg.bat_path) {
            currentConfig = cfg;
            checkSetup();
        }
    });
}

async function loadConfig() {
    currentConfig = await api('/api/config');
    checkSetup();
}

function updateUI() {
    const pathText = document.getElementById('pathText');
    pathText.innerText = currentConfig.bat_path || (T.PATH_NOT_SET||'Path not set');
    document.getElementById('launchBtn').disabled = !currentConfig.bat_path;
    updateTimerUI();
}

function checkSetup() {
    const isProfileValid = currentConfig.profile && currentConfig.hash;
    const isPathSet = !!currentConfig.bat_path;
    const closeBtn = document.getElementById('profileModalClose');
    const titleEl = document.getElementById('profileModalTitle');

    if (!isProfileValid) {
        closeBtn.style.display = 'none';
        titleEl.innerText = T.STEP1_TITLE || "Step 1: Profile Setup";
        openModal('profileModal');
        closeModal('pathModal');
        document.getElementById('launchBtn').disabled = true;
    } else if (!isPathSet) {
        closeModal('profileModal');
        openModal('pathModal');
        document.getElementById('launchBtn').disabled = true;
    } else {
        closeModal('profileModal');
        closeModal('pathModal');
        updateUI();
    }
}

async function saveProfile() {
    const profile = document.getElementById('inputProfile').value.trim();
    const password = document.getElementById('inputPassword').value.trim();
    const btn = document.getElementById('saveProfileBtn');

    if (!profile || !password) {
        showAlert(T.ERROR_TITLE || "Error", T.ERR_EMPTY_FIELDS || "Empty fields");
        return;
    }

    btn.innerText = T.VERIFYING || "Verifying...";
    btn.disabled = true;

    try {
        const verifyRes = await api('/api/verify_password', {profile, password});
        if (verifyRes && verifyRes.status === 'success' && verifyRes.hash) {
            currentConfig.profile = profile;
            currentConfig.password = password;
            currentConfig.hash = verifyRes.hash;
            checkSetup();
        } else {
            const errKey = verifyRes.error || "ERR_UNKNOWN";
            const errMsg = T[errKey] || T.ERR_UNKNOWN || "Unknown error";
            showAlert(T.ERROR_TITLE || "Error", errMsg);
        }
    } catch (e) {
        showAlert(T.ERROR_TITLE || "Error", T.ERR_VERIFY_EXCEPTION || "Exception");
    } finally {
        btn.innerText = T.SAVE_BTN || "Save";
        btn.disabled = false;
    }
}

async function renameBackup() {
    const newName = document.getElementById('inputRename').value.trim();
    if (!newName) { showAlert(T.ERROR_TITLE || "Error", T.ERR_RENAME_EMPTY || "Empty!"); return; }
    if (newName === selectedBackup) { showAlert(T.ERROR_TITLE || "Error", T.ERR_RENAME_SAME || "Same name!"); return; }

    const res = await api('/api/backups/rename', {old_filename: selectedBackup, new_filename: newName});
    if (res.status === 'success') {
        closeModal('renameModal');
        selectedBackup = null;
        document.getElementById('actionCard').style.display = 'none';
        document.getElementById('emptyState').style.display = 'block';
        loadFiles();
    } else {
        let errText = res.error || "UNKNOWN_ERROR";
        if (errText === "ERR_RENAME_EXISTS") errText = T.ERR_RENAME_EXISTS || "Already exists!";
        showAlert(T.ERROR_TITLE || "Error", errText);
    }
}

async function saveInterval() {
    const val = parseInt(document.getElementById('intervalSlider').value);
    await api('/api/config', {interval: val});
    currentConfig.interval = val;
    closeModal('intervalModal');
}

async function loadFiles() {
    if (currentTab === 'backups') {
        await loadBackups();
    } else {
        await loadLogs();
    }
}

const fileIconSvg = `<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline></svg>`;
const calendarIconSvg = `<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect><line x1="16" y1="2" x2="16" y2="6"></line><line x1="8" y1="2" x2="8" y2="6"></line><line x1="3" y1="10" x2="21" y2="10"></line></svg>`;

async function loadBackups() {
    const data = await api('/api/backups');
    if (data.last_parse_time) currentConfig.last_parse_time = data.last_parse_time;
    const backups = data.backups || [];
    const allTags = data.all_tags || {};

    const list = document.getElementById('backupList');
    list.innerHTML = '';
    
    if (data.current_exists) {
        const d = document.createElement('div'); d.className='backup-item';
        d.innerHTML = `<div class="file-name">${fileIconSvg} <span>current.json</span> <span class="badge-current">${T.CURRENT_TAG||'Current'}</span></div><div class="file-date">${calendarIconSvg} ${T.NOW||'Real-time'}</div><div class="tag-container" data-file="current.json"></div>`;
        d.onclick = () => selectBackup('current.json', T.NOW||'Real-time', d, true);
        if ('current.json' === selectedBackup) d.classList.add('active');
        list.appendChild(d);
        renderTagsForFile(d.querySelector('.tag-container'), 'current.json', allTags, data.current_tags);
    }

    if (backups.length === 0 && !data.current_exists) {
        list.innerHTML = `<div style="padding:15px; text-align:center; color:var(--text-muted);">${T.NO_BACKUPS||'No backups'}</div>`;
    } else {
        backups.forEach(b => {
            const d = document.createElement('div'); d.className='backup-item';
            const currentBadge = b.is_current ? `<span class="badge-current">${T.CURRENT_TAG||'Current'}</span>` : '';
            d.innerHTML = `<div class="file-name">${fileIconSvg} ${b.name} ${currentBadge}</div><div class="file-date">${calendarIconSvg} ${b.date}</div><div class="tag-container" data-file="${b.name}"></div>`;
            d.onclick = () => selectBackup(b.name, b.date, d, false);
            if (b.name === selectedBackup) d.classList.add('active');
            list.appendChild(d);
            renderTagsForFile(d.querySelector('.tag-container'), b.name, allTags, b.tags);
        });
    }
}

function renderTagsForFile(container, filename, allTags, appliedTagIds) {
    container.innerHTML = '';
    if (filename === 'current.json') return;
    
    (appliedTagIds || []).forEach(tagId => {
        const tag = allTags[tagId];
        if (!tag) return;
        const pill = document.createElement('div');
        pill.className = 'tag-pill';
        pill.style.backgroundColor = tag.color + '33';
        pill.style.border = `1px solid ${tag.color}`;
        pill.style.color = tag.color;
        pill.innerHTML = `<span class="dot-color" style="background:${tag.color}"></span> ${tag.name} <div class="remove-tag" data-action="unassign" data-file="${filename}" data-tag="${tagId}">&times;</div>`;
        container.appendChild(pill);
    });

    const addBtn = document.createElement('div');
    addBtn.className = 'add-tag-btn';
    addBtn.innerHTML = `<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/><line x1="7" y1="7" x2="7.01" y2="7"/></svg>`;
    
    const dropdown = document.createElement('div');
    dropdown.className = 'tag-dropdown';
    
    let ddHtml = '<div class="tag-list">';
    Object.keys(allTags).forEach(id => {
        const t = allTags[id];
        ddHtml += `<div class="tag-option" data-action="assign" data-file="${filename}" data-tag="${id}" style="color:${t.color}"><span class="dot-color" style="background:${t.color}"></span> ${t.name}</div>`;
    });
    ddHtml += '</div>';
    ddHtml += `<div class="tag-create-btn" data-action="manage" data-file="${filename}">⚙️ ${T.MANAGE_TAGS||'Manage Tags'}</div>`;
    dropdown.innerHTML = ddHtml;
    
    addBtn.appendChild(dropdown);
    container.appendChild(addBtn);
}

function handleTagClicks(e) {
    const target = e.target.closest('[data-action]');
    if (!target) return;
    
    const action = target.dataset.action;
    const file = target.dataset.file;
    const tag = target.dataset.tag;
    
    if (action === 'unassign') {
        e.stopPropagation();
        api('/api/tags/unassign', {filename: file, tag_id: tag}).then(() => loadFiles());
    } else if (action === 'assign') {
        e.stopPropagation();
        api('/api/tags/assign', {filename: file, tag_id: tag}).then(() => loadFiles());
    } else if (action === 'manage') {
        e.stopPropagation();
        openTagManagerModal(file);
    }
}

let editingTagId = null;
let tagModalTargetFile = null;

async function openTagManagerModal(filename) {
    tagModalTargetFile = filename;
    editingTagId = null;
    
    const data = await api('/api/backups');
    const allTags = data.all_tags || {};
    
    let m = document.getElementById('tagManagerModal');
    if (!m) {
        m = document.createElement('div');
        m.id = 'tagManagerModal';
        m.className = 'modal-overlay';
        m.innerHTML = `
            <div class="modal">
                <h2>${T.MANAGE_TAGS||'Manage Tags'}</h2>
                <div id="tagListContainer" style="margin-bottom: 20px; max-height: 200px; overflow-y: auto;"></div>
                <hr style="border-color: var(--card-bg); margin: 15px 0;">
                <h3 id="tagFormTitle">${T.CREATE_TAG||'Create Tag'}</h3>
                <label>${T.TAG_NAME||'Tag Name'}</label>
                <input type="text" id="tagInputName" class="text-input">
                <label>${T.TAG_COLOR||'Tag Color'}</label>
                <input type="color" id="tagInputColor" class="color-input" value="#89b4fa">
                <div class="modal-actions">
                    <button class="btn btn-secondary" id="tagCancelBtn" style="display:none;">${T.CANCEL_BTN||'Cancel'}</button>
                    <button class="btn btn-primary" id="tagSaveBtn">${T.CREATE_BTN||'Create'}</button>
                </div>
                <button class="btn btn-secondary" style="margin-top: 15px; width: 100%;" onclick="document.getElementById('tagManagerModal').style.display='none'">${T.CLOSE_BTN||'Close'}</button>
            </div>`;
        document.body.appendChild(m);
        m.onclick = e => { if(e.target === m) m.style.display = 'none'; };
        m.querySelector('#tagSaveBtn').onclick = saveTag;
        m.querySelector('#tagCancelBtn').onclick = () => resetTagForm();
    }
    
    renderTagList(allTags);
    resetTagForm();
    m.style.display = 'flex';
}

function renderTagList(allTags) {
    const container = document.getElementById('tagListContainer');
    container.innerHTML = '';
    Object.keys(allTags).forEach(id => {
        const t = allTags[id];
        const row = document.createElement('div');
        row.style.display = 'flex';
        row.style.alignItems = 'center';
        row.style.justifyContent = 'space-between';
        row.style.padding = '8px';
        row.style.borderBottom = '1px solid var(--card-bg)';
        row.innerHTML = `
            <div style="display: flex; align-items: center; gap: 8px; color: ${t.color}">
                <span class="dot-color" style="background:${t.color}"></span> ${t.name}
            </div>
            <div style="display: flex; gap: 5px;">
                <button class="btn btn-icon" data-action="edit-tag" data-id="${id}" data-name="${t.name}" data-color="${t.color}" style="color: var(--accent-color); padding: 4px;">✎</button>
                <button class="btn btn-icon" data-action="delete-tag" data-id="${id}" style="color: var(--danger-color); padding: 4px;">✕</button>
            </div>
        `;
        container.appendChild(row);
    });
    
    container.querySelectorAll('[data-action="edit-tag"]').forEach(btn => {
        btn.onclick = (e) => {
            e.stopPropagation();
            editingTagId = btn.dataset.id;
            document.getElementById('tagInputName').value = btn.dataset.name;
            document.getElementById('tagInputColor').value = btn.dataset.color;
            document.getElementById('tagFormTitle').innerText = T.EDIT_TAG || 'Edit Tag';
            document.getElementById('tagSaveBtn').innerText = T.SAVE_BTN || 'Save';
            document.getElementById('tagCancelBtn').style.display = 'flex';
        };
    });

    container.querySelectorAll('[data-action="delete-tag"]').forEach(btn => {
        btn.onclick = async (e) => {
            e.stopPropagation();
            await api('/api/tags/delete', {tag_id: btn.dataset.id});
            const data = await api('/api/backups');
            renderTagList(data.all_tags || {});
            loadFiles();
        };
    });
}

function resetTagForm() {
    editingTagId = null;
    document.getElementById('tagInputName').value = '';
    document.getElementById('tagInputColor').value = '#89b4fa';
    document.getElementById('tagFormTitle').innerText = T.CREATE_TAG || 'Create Tag';
    document.getElementById('tagSaveBtn').innerText = T.CREATE_BTN || 'Create';
    document.getElementById('tagCancelBtn').style.display = 'none';
}

async function saveTag() {
    const name = document.getElementById('tagInputName').value.trim();
    const color = document.getElementById('tagInputColor').value;
    if (!name) return;
    
    if (editingTagId) {
        await api('/api/tags/update', {tag_id: editingTagId, name, color});
    } else {
        const res = await api('/api/tags/create', {name, color});
        if (res.tag_id && tagModalTargetFile) {
            await api('/api/tags/assign', {filename: tagModalTargetFile, tag_id: res.tag_id});
        }
    }
    
    const data = await api('/api/backups');
    renderTagList(data.all_tags || {});
    resetTagForm();
    loadFiles();
}

async function loadLogs() {
    const data = await api('/api/logs');
    const logs = data.logs || [];

    const list = document.getElementById('backupList');
    list.innerHTML = '';
    if (logs.length === 0) {
        list.innerHTML = `<div style="padding:15px; text-align:center; color:var(--text-muted);">${T.NO_LOGS||'No logs'}</div>`;
    } else {
        logs.forEach(b => {
            const d = document.createElement('div'); d.className='backup-item';
            d.innerHTML = `<div class="file-name">${fileIconSvg} ${b.name}</div><div class="file-date">${calendarIconSvg} ${b.date}</div>`;
            d.onclick = () => selectLog(b.name, b.date, d);
            if (b.name === selectedLog) d.classList.add('active');
            list.appendChild(d);
        });
    }
}

function showActionCard(name, date, isBackup) {
    document.getElementById('emptyState').style.display = 'none';
    document.getElementById('actionCard').style.display = 'flex';
    document.getElementById('selectedBackupName').innerText = name;
    document.getElementById('selectedBackupDate').innerText = date;
    document.getElementById('backupActions').style.display = isBackup ? 'flex' : 'none';
}

async function selectBackup(name, date, el, isCurrent) {
    document.querySelectorAll('.backup-item').forEach(e => e.classList.remove('active'));
    if (el) el.classList.add('active');
    selectedBackup = name;
    selectedBackupDate = date;
    showActionCard(name, date, true);
    
    document.getElementById('cardContent').innerHTML = '<div style="color:var(--text-muted); padding: 10px;">Loading...</div>';
    const res = isCurrent ? await api('/api/backups/read_current') : await api(`/api/backups/read?file=${encodeURIComponent(name)}`);
    
    if (selectedBackup !== name) return; 

    if (res.error) {
        document.getElementById('cardContent').innerHTML = `<div style="color:var(--danger-color); padding: 10px;">${res.error}</div>`;
        return;
    }
    
    let html = '<table class="json-table"><tbody>';
    for (const key in res.data) {
        let val = res.data[key];
        if (typeof val === 'object' && val !== null) {
            val = `<details><summary>View Object</summary><pre>${JSON.stringify(val, null, 2)}</pre></details>`;
        } else {
            val = String(val).replace(/</g, '&lt;').replace(/>/g, '&gt;');
        }
        html += `<tr><td class="json-key">${key}</td><td class="json-value">${val}</td></tr>`;
    }
    html += '</tbody></table>';
    document.getElementById('cardContent').innerHTML = html;
}

async function selectLog(name, date, el) {
    document.querySelectorAll('.backup-item').forEach(e => e.classList.remove('active'));
    if (el) el.classList.add('active');
    selectedLog = name;
    selectedLogDate = date;
    showActionCard(name, date, false);
    
    document.getElementById('cardContent').innerHTML = '<div style="color:var(--text-muted); padding: 10px;">Loading...</div>';
    const res = await api(`/api/logs/read?file=${encodeURIComponent(name)}`);

    if (selectedLog !== name) return;

    if (res.error) {
        document.getElementById('cardContent').innerHTML = `<div style="color:var(--danger-color); padding: 10px;">${res.error}</div>`;
        return;
    }

    const lines = (res.content || "").split('\n').filter(l => l.trim());
    const groups = {};
    lines.forEach(line => {
        const match = line.match(/^\[(.*?)\] IP: (.*?) \| Size: (.*?) bytes \| Data: (.*)$/);
        if (match) {
            const [_, time, ip, size, data] = match;
            if (!groups[ip]) groups[ip] = [];
            groups[ip].push({ time, size, data });
        }
    });

    let html = '<div class="log-viewer">';
    for (const ip in groups) {
        html += `<details class="log-group" open><summary class="log-group-summary">${ip} <span class="log-count">(${groups[ip].length} packets)</span></summary><div class="log-packets">`;
        groups[ip].forEach(p => {
            let dataHtml = `<code class="log-data">${p.data}</code>`;
            try {
                if (p.data.startsWith('{') || p.data.startsWith('[')) {
                    const jsonData = JSON.parse(p.data);
                    dataHtml = `<details class="log-json"><summary>JSON Data</summary><pre class="json-pre">${JSON.stringify(jsonData, null, 2)}</pre></details>`;
                }
            } catch (e) {}
            html += `<div class="log-packet"><div class="packet-meta"><span class="log-time">[${p.time}]</span><span class="log-size">${p.size} bytes</span></div><div class="packet-data">${dataHtml}</div></div>`;
        });
        html += `</div></details>`;
    }
    html += '</div>';
    document.getElementById('cardContent').innerHTML = html;
}

async function checkSyncStatus() {
    const r = await api('/api/sync/status');
    const btn = document.getElementById('hookBtn');
    const btnText = document.getElementById('hookBtnText');
    const dot = document.getElementById('connDot');
    const text = document.getElementById('connText');
    
    if (r.online) {
        dot.className = 'dot online';
        text.innerText = T.STATUS_ONLINE || 'Online';
    } else {
        dot.className = 'dot offline';
        text.innerText = T.STATUS_OFFLINE || 'Offline';
    }
    
    if (r.running) {
        btnText.innerText = T.SYNC_BTN_ON || "Sync: ON";
        btn.classList.add('active');
    } else {
        btnText.innerText = T.SYNC_BTN_OFF || "Sync: OFF";
        btn.classList.remove('active');
    }

    isPendingBackup = r.pending_backup;
}

const openModal = id => document.getElementById(id).style.display = 'flex';
const closeModal = id => document.getElementById(id).style.display = 'none';

function showConfirm(title, text, cb) {
    document.getElementById('confirmTitle').innerText = title;
    document.getElementById('confirmText').innerText = text;
    document.getElementById('confirmActionBtn').onclick = cb; 
    openModal('confirmModal');
}

function showAlert(title, text) {
    document.getElementById('alertTitle').innerText = title;
    document.getElementById('alertText').innerText = text;
    openModal('alertModal');
}