let currentConfig = {}, selectedBackup = null, T = {}; 
let backupPolling = null;
let timerInterval = null;

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
    loadBackups();
    initListeners();
    startTimer();
    backupPolling = setInterval(loadBackups, 15000);
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
    if (diff < 60) el.innerText = `${diff} ${T.AGO_SEC || 'sec. ago'}`;
    else el.innerText = `${Math.floor(diff / 60)} ${T.AGO_MIN || 'min. ago'}`;
}

async function loadLanguage(lang) {
    T = await api(`/api/locales/${lang}`);
    currentConfig.lang = lang;
    document.querySelectorAll('[data-i18n]').forEach(el => { if(T[el.dataset.i18n]) el.innerText = T[el.dataset.i18n]; });
    document.querySelectorAll('[data-i18n-placeholder]').forEach(el => { if(T[el.dataset.i18nPlaceholder]) el.placeholder = T[el.dataset.i18nPlaceholder]; });
    document.title = T.APP_TITLE || "WC3 Manager";
    updateUI();
    loadBackups();
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

    document.getElementById('renameBackupBtn').onclick = () => {
        if (!selectedBackup) return;
        document.getElementById('inputRename').value = selectedBackup;
        openModal('renameModal');
    };

    document.getElementById('settingsBtn').onclick = () => {
        document.getElementById('intervalSlider').value = currentConfig.interval || 5;
        document.getElementById('intervalValue').innerText = currentConfig.interval || 5;
        openModal('intervalModal');
    };

    document.getElementById('intervalSlider').oninput = (e) => {
        document.getElementById('intervalValue').innerText = e.target.value;
    };

    document.getElementById('settingsPathBtn').onclick = () => selectPath();

    document.getElementById('launchBtn').onclick = async () => {
        const r = await api('/api/launch', {});
        if(r.error) showAlert(T.ERROR_TITLE||'Error', r.error);
    };

    document.getElementById('profileBtn').onclick = () => {
        document.getElementById('inputProfile').value=currentConfig.profile||'';
        document.getElementById('inputPassword').value=currentConfig.password||'';

        const closeBtn = document.getElementById('profileModalClose');
        const titleEl = document.getElementById('profileModalTitle');

        // Если профиль УЖЕ верифицирован (есть хеш)
        if (currentConfig.hash) {
            closeBtn.style.display = 'block'; // Показываем крестик
            titleEl.innerText = T.PROFILE_MODAL_TITLE || "Profile Setup"; // Меняем заголовок (без Step 1)
        } else {
            closeBtn.style.display = 'none';
            titleEl.innerText = T.STEP1_TITLE || "Step 1: Profile Setup";
        }

        openModal('profileModal');
    };

    document.getElementById('deleteBackupBtn').onclick = () => showConfirm(T.CONFIRM_TITLE, (T.DELETE_CONFIRM||'Delete?').replace('{name}', selectedBackup), async () => {
        await api('/api/backups/delete', {filename: selectedBackup});
        closeModal('confirmModal');
        selectedBackup=null;
        document.getElementById('actionCard').style.display='none';
        document.getElementById('emptyState').style.display='block';
        loadBackups();
    });

    document.getElementById('restoreBackupBtn').onclick = () => showConfirm(T.CONFIRM_TITLE, (T.RESTORE_CONFIRM||'Restore?').replace('{name}', selectedBackup), async () => {
        const r = await api('/api/backups/restore', {filename: selectedBackup});
        closeModal('confirmModal');
        if(r.error) showAlert(T.ERROR_TITLE||'Error', r.error);
        else showAlert(T.SUCCESS||'Success', T.RESTORE_SUCCESS||'Restored!');
    });

    // Закрытие модалок по клику на оверлей
    document.querySelectorAll('.modal-overlay').forEach(o => o.onclick = e => {
        if(e.target === o) {
            // Запрещаем закрывать профиль кликом по фону, если он ЕЩЕ НЕ НАСТРОЕН
            if (o.id === 'profileModal' && !currentConfig.hash) return;
            // Запрещаем закрывать окно пути кликом по фону, если он ЕЩЕ НЕ НАСТРОЕН
            if (o.id === 'pathModal' && !currentConfig.bat_path) return;

            o.style.display='none';
        }
    });
}

function selectPath() {
    api('/api/select_path', {}).then(cfg => {
        if (!cfg.error && cfg.bat_path) {
            // Обновляем весь конфиг из ответа (бэкенд возвращает обновленный конфиг)
            currentConfig = cfg;
            checkSetup(); // Это закроет окно пути и разблокирует интерфейс
        }
    });
}

async function loadConfig() {
    currentConfig = await api('/api/config');
    checkSetup();
}

function updateUI() {
    const pathD = document.getElementById('pathDisplay');
    pathD.innerText = currentConfig.bat_path ? `${T.PATH_LABEL||'Path:'} ${currentConfig.bat_path}` : (T.PATH_NOT_SET||'Path not set');
    document.getElementById('launchBtn').disabled = !currentConfig.bat_path;
    updateTimerUI();
}

function checkSetup() {
    const isProfileValid = currentConfig.profile && currentConfig.hash;
    const isPathSet = !!currentConfig.bat_path;

    const closeBtn = document.getElementById('profileModalClose');
    const titleEl = document.getElementById('profileModalTitle');

    if (!isProfileValid) {
        // Профиль НЕ настроен: скрываем крестик, заголовок = Шаг 1
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

    // Проверка пустых полей с текстом из локализации
    if (!profile || !password) {
        showAlert(T.ERROR_TITLE || "Error", T.ERR_EMPTY_FIELDS || "Empty fields");
        return;
    }

    btn.innerText = T.VERIFYING || "Verifying...";
    btn.disabled = true;

    try {
        const verifyRes = await api('/api/verify_password', {profile, password});

        if (verifyRes && verifyRes.status === 'success' && verifyRes.hash) {
            // Успех: обновляем конфиг в памяти и закрываем окно
            currentConfig.profile = profile;
            currentConfig.password = password;
            currentConfig.hash = verifyRes.hash;
            checkSetup();
        } else {
            // Ошибка: берем ключ ошибки из бэкенда и ищем перевод в T
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

    if (!newName) {
        showAlert(T.ERROR_TITLE || "Error", T.ERR_RENAME_EMPTY || "Empty!");
        return;
    }
    if (newName === selectedBackup) {
        showAlert(T.ERROR_TITLE || "Error", T.ERR_RENAME_SAME || "Same name!");
        return;
    }

    const res = await api('/api/backups/rename', {old_filename: selectedBackup, new_filename: newName});

    if (res.status === 'success') {
        closeModal('renameModal');
        selectedBackup = null;
        document.getElementById('actionCard').style.display = 'none';
        document.getElementById('emptyState').style.display = 'block';
        loadBackups(); // Обновляем список
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

async function loadBackups() {
    const data = await api('/api/backups');
    if (data.last_parse_time) currentConfig.last_parse_time = data.last_parse_time;
    const backups = data.backups || [];

    const list = document.getElementById('backupList');
    list.innerHTML = '';
    if (backups.length === 0) {
        list.innerHTML = `<div style="padding:15px; text-align:center; color:var(--text-muted);">${T.NO_BACKUPS||'No backups'}</div>`;
    } else {
        backups.forEach(b => {
            const d = document.createElement('div'); d.className='backup-item';
            d.innerHTML = `<div class="file-name">📄 ${b.name}</div><div class="file-date">📅 ${b.date}</div>`;
            d.onclick = () => selectBackup(b.name, b.date, d);
            list.appendChild(d);
        });
    }
    if (selectedBackup) {
        document.querySelectorAll('.backup-item').forEach(el => {
            if (el.querySelector('.file-name').innerText.includes(selectedBackup)) el.classList.add('active');
        });
        document.getElementById('emptyState').style.display = 'none';
        document.getElementById('actionCard').style.display = 'block';
        document.getElementById('selectedBackupName').innerText = selectedBackup;
    }
}

function selectBackup(name, date, el) {
    document.querySelectorAll('.backup-item').forEach(e => e.classList.remove('active'));
    el.classList.add('active');
    selectedBackup = name;
    document.getElementById('emptyState').style.display = 'none';
    document.getElementById('actionCard').style.display = 'block';
    document.getElementById('selectedBackupName').innerText = name;
    document.getElementById('selectedBackupDate').innerText = date;
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