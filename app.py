import os, json, time, ctypes, threading, importlib, hashlib, requests, sys, subprocess
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from flask import Flask, render_template, request, jsonify
from bs4 import BeautifulSoup
from apscheduler.schedulers.background import BackgroundScheduler

# --- ИСПРАВЛЕНИЕ ПУТЕЙ ДЛЯ PYINSTALLER ---
def resource_path(relative_path):
    """ Получает абсолютный путь к ресурсу, работает и в dev-режиме, и в скомпилированном exe """
    try:
        # PyInstaller создает временную папку и пишет путь в _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# Путь для сохраняемых данных (рядом с exe)
APP_PATH = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, 'frozen', False) else __file__))
CONFIG_FILE = os.path.join(APP_PATH, 'config.json')
BACKUP_DIR = os.path.join(APP_PATH, 'backups')

# Инициализация Flask с исправленными путями к шаблонам и статике
app = Flask(__name__,
            template_folder=resource_path('templates'),
            static_folder=resource_path('static'))

# Добавляем путь к локализациям, чтобы importlib находил их внутри exe
sys.path.insert(0, resource_path('locales'))


def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError:
            pass
    return {"profile": "", "password": "", "bat_path": "", "lang": "en", "interval": 5, "hash": "",
            "last_parse_time": 0}


def save_config(config):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f: json.dump(config, f, indent=4)


def ensure_dirs():
    if not os.path.exists(BACKUP_DIR): os.makedirs(BACKUP_DIR)


def get_latest_backup():
    ensure_dirs()
    files = [f for f in os.listdir(BACKUP_DIR) if f.endswith('.json')]
    if not files: return None
    files.sort(key=lambda x: os.path.getmtime(os.path.join(BACKUP_DIR, x)), reverse=True)
    with open(os.path.join(BACKUP_DIR, files[0]), 'r', encoding='utf-8') as f: return json.load(f)


def extract_id(data):
    if isinstance(data, dict):
        for k in ['id', 'Id', 'ID', 'userId', 'account']:
            if k in data: return str(data[k])
    return str(int(time.time()))


def get_remote_data_raw(profile):
    try:
        # ИСПРАВЛЕНО: Передаем параметры через params для автоматического URL-кодирования
        r = requests.get(
            "https://shuen.ddns.net/DzAPI_ServerData.php",
            params={"profile": profile, "action": "view"},
            timeout=15, verify=False
        )
        if "profile not exist" in r.text: return None
        textarea = BeautifulSoup(r.text, 'html.parser').find('textarea')
        return textarea.text.strip() if textarea else None
    except Exception as e:
        print(f"GET Error: {e}")
        return None


def post_remote_data(profile, password, data):
    try:
        data_str = json.dumps(data, indent=4) if isinstance(data, dict) else str(data)

        # ИСПРАВЛЕНО: Имитируем реальную отправку формы из браузера.
        # profile и password передаются как поля формы, а не в URL!
        payload = {
            'json': (None, data_str),
            'profile': (None, profile),
            'password': (None, password),
            'submit': (None, 'Save')
        }

        # ИСПРАВЛЕНО: URL чистый, без параметров ?profile=...&action=edit
        r = requests.post(
            "https://shuen.ddns.net/DzAPI_ServerData.php",
            files=payload,  # requests сам установит Content-Type: multipart/form-data
            verify=False,
            timeout=15
        )
        print(f"[POST] Profile: {profile}, Status: {r.status_code}, Response: {r.text[:200]}")

        # Если сервер вернул 200, мы считаем, что форма отправлена.
        # Реальная проверка пройдет на Шаге 5 (повторный GET-запрос).
        return r.status_code == 200, r.text
    except Exception as e:
        print(f"[POST Error] {e}")
        return False, str(e)


def parse_and_backup():
    config = load_config()
    # ИСПРАВЛЕНО: используем .get() чтобы избежать KeyError
    if not config.get('profile') or not config.get('hash'): return
    try:
        raw_data = get_remote_data_raw(config['profile'])
        if raw_data:
            remote = json.loads(raw_data)
            if remote != get_latest_backup():
                bid = extract_id(remote)
                fn = f"backup_{bid}.json" if not os.path.exists(
                    os.path.join(BACKUP_DIR, f"backup_{bid}.json")) else f"backup_{bid}_{int(time.time())}.json"
                with open(os.path.join(BACKUP_DIR, fn), 'w', encoding='utf-8') as f: json.dump(remote, f, indent=4)
            config['last_parse_time'] = int(time.time())
            save_config(config)
    except Exception as e:
        print(f"Parse error: {e}")


scheduler = BackgroundScheduler(daemon=True)
scheduler.add_job(parse_and_backup, 'interval', minutes=load_config().get('interval', 5), id='parse_job')
scheduler.start()


def restart_scheduler(interval):
    scheduler.reschedule_job('parse_job', trigger='interval', minutes=interval)


@app.route('/')
def index(): return render_template('index.html')


@app.route('/api/config', methods=['GET', 'POST'])
def handle_config():
    if request.method == 'POST':
        data, cfg = request.json, load_config()
        for k in ['profile', 'password', 'bat_path', 'lang', 'interval']:
            if k in data: cfg[k] = data[k]
        save_config(cfg)
        if 'interval' in data: restart_scheduler(cfg['interval'])
        return jsonify({"status": "success"})
    return jsonify(load_config())


@app.route('/api/available_locales')
def available_locales():
    # ИСПРАВЛЕНО: используем resource_path для поиска внутри собранного exe
    locales_dir = resource_path('locales')
    try:
        files = os.listdir(locales_dir)
        return jsonify([f.replace('.py','') for f in files if f.endswith('.py') and not f.startswith('__')])
    except FileNotFoundError:
        return jsonify([])


@app.route('/api/locales/<lang>')
def get_locale(lang):
    try:
        mod = importlib.import_module(f'locales.{lang}')
        return jsonify({k: v for k, v in vars(mod).items() if not k.startswith('__')})
    except:
        return jsonify({}), 404


@app.route('/api/select_path', methods=['POST'])
def select_path():
    def dlg():
        import tkinter as tk
        from tkinter import filedialog
        r = tk.Tk();
        r.withdraw();
        r.attributes('-topmost', True)
        fp = filedialog.askopenfilename(title="Select KKWE - Launch 1.27.bat", filetypes=[("Batch", "*.bat")])
        r.destroy()
        if fp: cfg = load_config(); cfg['bat_path'] = fp; save_config(cfg)

    t = threading.Thread(target=dlg);
    t.start();
    t.join()
    return jsonify(load_config())


@app.route('/api/launch', methods=['POST'])
def launch_bat():
    cfg = load_config()
    if not cfg.get('bat_path') or not os.path.exists(cfg['bat_path']): return jsonify({"error": "Path not set"}), 400
    try:
        subprocess.Popen([cfg['bat_path']], cwd=os.path.dirname(cfg['bat_path']), env=os.environ.copy())
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/backups', methods=['GET'])
def list_backups():
    ensure_dirs()
    files = [f for f in os.listdir(BACKUP_DIR) if f.endswith('.json')]
    files.sort(key=lambda x: os.path.getmtime(os.path.join(BACKUP_DIR, x)), reverse=True)
    cfg = load_config()
    return jsonify({
        "backups": [{"name": f, "date": time.strftime('%d.%m.%Y %H:%M:%S',
                                                      time.localtime(os.path.getmtime(os.path.join(BACKUP_DIR, f))))}
                    for f in files],
        "last_parse_time": cfg.get('last_parse_time', 0)
    })


@app.route('/api/backups/rename', methods=['POST'])
def rename_backup():
    data = request.json
    old_name = data.get('old_filename')
    new_name = data.get('new_filename')

    if not old_name or not new_name: return jsonify({"error": "MISSING_FIELDS"}), 400

    # Принудительно добавляем .json, если пользователь забыл
    if not new_name.endswith('.json'):
        new_name += '.json'

    if old_name == new_name: return jsonify({"error": "ERR_RENAME_SAME"})

    old_path = os.path.join(BACKUP_DIR, old_name)
    new_path = os.path.join(BACKUP_DIR, new_name)

    if not os.path.exists(old_path): return jsonify({"error": "NOT_FOUND"}), 404
    if os.path.exists(new_path): return jsonify({"error": "ERR_RENAME_EXISTS"})

    try:
        os.rename(old_path, new_path)
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/backups/delete', methods=['POST'])
def delete_backup():
    fp = os.path.join(BACKUP_DIR, request.json.get('filename', ''))
    if os.path.exists(fp): os.remove(fp); return jsonify({"status": "success"})
    return jsonify({"error": "Not found"}), 404


@app.route('/api/backups/restore', methods=['POST'])
def restore_backup():
    fn, cfg = request.json.get('filename'), load_config()
    fp = os.path.join(BACKUP_DIR, fn)
    if not os.path.exists(fp): return jsonify({"error": "Not found"}), 404
    if not cfg.get('profile') or not cfg.get('password'): return jsonify({"error": "No credentials"}), 400
    with open(fp, 'r', encoding='utf-8') as f: data = json.load(f)
    try:
        # ИСПРАВЛЕНО: Используем обновленную функцию post_remote_data
        if post_remote_data(cfg['profile'], cfg['password'], data)[0]:
            return jsonify({"status": "success"})
        return jsonify({"error": "Failed to save"}), 500
    except Exception as e: return jsonify({"error": str(e)}), 500


@app.route('/api/check_profile', methods=['GET'])
def check_profile():
    profile = request.args.get('profile')
    if not profile: return jsonify({"exists": True})
    try:
        if get_remote_data_raw(profile) is None: return jsonify({"exists": False})
        return jsonify({"exists": True})
    except:
        return jsonify({"exists": True})


@app.route('/api/verify_password', methods=['POST'])
def verify_password():
    profile = request.json.get('profile')
    password = request.json.get('password')

    # Шаг 1: Проверка ввода
    if not profile or not password: return jsonify({"error": "ERR_EMPTY_FIELDS"})

    try:
        # Шаг 2: Запрос view-формы, сохранение данных
        original_raw = get_remote_data_raw(profile)
        if original_raw is None: return jsonify({"error": "ERR_PROFILE_NOT_EXIST"})

        try:
            original_data = json.loads(original_raw)
        except:
            original_data = original_raw  # Если вдруг там не JSON, сохраним как строку

        # Шаг 4: Запрос edit-формы, замена на структурированные типовые данные
        dummy_data = {"MapLevel": "123"}
        success, save_text = post_remote_data(profile, password, dummy_data)
        if not success:
            return jsonify({"error": "ERR_SAVE_DUMMY"})

        # Шаг 5: Повторный запрос view-формы, сравнение с типовыми данными
        check_raw = get_remote_data_raw(profile)
        try:
            check_data = json.loads(check_raw) if check_raw else None
            if check_data != dummy_data:
                return jsonify({"error": "ERR_DUMMY_MISMATCH"})
        except:
            return jsonify({"error": "ERR_DUMMY_MISMATCH"})

        # Шаг 6: Повторный запрос edit-формы, сохранение оригинальных данных
        restore_success, restore_text = post_remote_data(profile, password, original_data)
        if not restore_success:
            return jsonify({"error": "ERR_RESTORE_DATA"})

        # Шаг 7: Сохранение профиля, пароля и сгенерированного хэша
        h = hashlib.sha256(f"{profile}{password}".encode()).hexdigest()
        cfg = load_config()
        cfg['profile'] = profile
        cfg['password'] = password
        cfg['hash'] = h
        save_config(cfg)

        return jsonify({"status": "success", "hash": h})
    except Exception as e:
        print(f"Verification Exception: {e}")
        return jsonify({"error": "ERR_VERIFY_EXCEPTION"})


if __name__ == '__main__':
    ensure_dirs()

    # Автоматическое открытие браузера при запуске
    import webbrowser

    webbrowser.open('http://127.0.0.1:5000')

    print("Server is launched at http://127.0.0.1:5000. Don't close this window.")

    from waitress import serve

    serve(app, host='127.0.0.1', port=5000)