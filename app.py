import os
import sys
import json
import time
import socket
import ctypes
import hashlib
import importlib
import threading
import subprocess
import webbrowser
import datetime
import zlib

import requests
import urllib3
from scapy.all import AsyncSniffer, IP, IPv6, TCP
from scapy.arch.windows import get_windows_if_list
from flask import Flask, render_template, request, jsonify
from bs4 import BeautifulSoup
from apscheduler.schedulers.background import BackgroundScheduler
from waitress import serve

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

TARGET_DOMAIN = "shuen.ddns.net"

# ==========================================
# Configuration and Paths
# ==========================================
def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

APP_PATH = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, 'frozen', False) else __file__))
CONFIG_FILE = os.path.join(APP_PATH, 'config.json')
BACKUP_DIR = os.path.join(APP_PATH, 'backups')
LOG_DIR = os.path.join(APP_PATH, 'logs')

app = Flask(__name__,
            template_folder=resource_path('templates'),
            static_folder=resource_path('static'))

sys.path.insert(0, resource_path('locales'))

# ==========================================
# Admin Check & Local Network Hook (Scapy)
# ==========================================
last_heartbeat_time = 0
sniffer_thread = None
hook_active = False

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

def parse_one_packet(data):
    """Парсит одну команду протокола WC3."""
    if len(data) < 4 or data[0] != 0xF6:
        return None, 0
    
    cmd = data[1]
    try:
        if cmd == 0x01 or cmd == 0x02:
            slen = int.from_bytes(data[2:4], 'little')
            s = data[4:4+slen].decode('utf-8', errors='replace')
            term = 1 if len(data) > 4+slen and data[4+slen] == 0 else 0
            return {"cmd": "set_profile" if cmd == 1 else "set_password", "value": s}, 4 + slen + term
        elif cmd == 0x03:
            val = int.from_bytes(data[4:8], 'little')
            return {"cmd": "set_id", "value": val}, 8
        elif cmd == 0x05:
            return {"cmd": "flush"}, 4
        elif cmd == 0x06:
            val = data[4] if len(data) > 4 else 0
            return {"cmd": "event_06", "value": val}, 5
        elif cmd == 0x07:
            tlen = int.from_bytes(data[2:4], 'little')
            offset = 4
            klen = int.from_bytes(data[offset:offset+2], 'little')
            offset += 2
            key = data[offset:offset+klen].decode('utf-8', errors='replace')
            offset += klen
            vlen = int.from_bytes(data[offset:offset+2], 'little')
            offset += 2
            val = data[offset:offset+vlen].decode('utf-8', errors='replace')
            return {"cmd": "set_value", "key": key, "value": val}, 4 + tlen
        elif cmd == 0x08:
            return {"cmd": "finalize"}, 4
    except:
        pass
    return None, 0

def parse_all_packets(data):
    """Разбивает поток байтов на отдельные пакеты и парсит их."""
    res = []
    offset = 0
    while offset < len(data):
        if data[offset] == 0xF6:
            p, consumed = parse_one_packet(data[offset:])
            if p and consumed > 0:
                res.append(p)
                offset += consumed
            else:
                offset += 1
        else:
            offset += 1
    return res

def safe_payload_repr(payload):
    # 1. Пробуем декодировать кастомный протокол WC3
    parsed = parse_all_packets(payload)
    if parsed:
        return json.dumps(parsed, ensure_ascii=False)
    
    # 2. Пытаемся распаковать zlib (если данные сжаты)
    try:
        decompressed = zlib.decompress(payload)
        return safe_payload_repr(decompressed)
    except:
        pass
    
    try:
        decompressed = zlib.decompress(payload, -15)
        return safe_payload_repr(decompressed)
    except:
        pass

    # 3. Если это просто читаемый текст
    try:
        decoded = payload.decode('utf-8', errors='strict')
        if all(c.isprintable() or c in '\n\r\t' for c in decoded):
            return decoded
    except:
        pass

    # 4. Fallback на HEX
    return payload.hex()

def packet_handler(packet):
    global last_heartbeat_time
    if packet.haslayer(TCP):
        tcp_layer = packet[TCP]
        payload = bytes(tcp_layer.payload)
        payload_size = len(payload)
        
        if payload_size > 0:
            dst_ip = "Unknown"
            if packet.haslayer(IP):
                dst_ip = packet[IP].dst
            elif packet.haslayer(IPv6):
                dst_ip = packet[IPv6].dst
            
            if payload_size == 4:
                last_heartbeat_time = time.time()
            else:
                now = datetime.datetime.now()
                date_str = now.strftime("%d.%m.%Y")
                time_str = now.strftime("%H:%M:%S")
                log_file = os.path.join(LOG_DIR, f"{date_str}.log")
                
                payload_repr = safe_payload_repr(payload)
                log_entry = f"[{time_str}] IP: {dst_ip}:{tcp_layer.dport} | Size: {payload_size} bytes | Data: {payload_repr}\n"
                
                try:
                    with open(log_file, 'a', encoding='utf-8') as f:
                        f.write(log_entry)
                except Exception:
                    pass

def get_active_interface_name():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        my_ip = s.getsockname()[0]
        s.close()

        for iface in get_windows_if_list():
            if my_ip in iface.get('ips', []):
                return iface['name']
    except Exception:
        pass
    return None

def start_sniffer():
    global sniffer_thread, hook_active
    if hook_active:
        return
        
    iface_name = get_active_interface_name()
    if not iface_name:
        return

    try:
        target_ip = socket.gethostbyname(TARGET_DOMAIN)
    except socket.gaierror:
        return

    bpf_filter = f"dst host {target_ip} and tcp"
    
    try:
        sniffer_thread = AsyncSniffer(iface=iface_name, filter=bpf_filter, prn=packet_handler, store=0)
        sniffer_thread.start()
        hook_active = True
    except Exception:
        pass

def stop_sniffer():
    global sniffer_thread, hook_active
    if sniffer_thread and hook_active:
        try:
            sniffer_thread.stop()
        except:
            pass
        hook_active = False

# ==========================================
# App Logic and Helpers
# ==========================================
def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError:
            pass
    return {"profile": "", "password": "", "bat_path": "", "lang": "en", "interval": 5, "hash": "", "last_parse_time": 0}

def save_config(config):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4)

def ensure_dirs():
    if not os.path.exists(BACKUP_DIR):
        os.makedirs(BACKUP_DIR)
    if not os.path.exists(LOG_DIR):
        os.makedirs(LOG_DIR)

def get_latest_backup():
    ensure_dirs()
    files = [f for f in os.listdir(BACKUP_DIR) if f.endswith('.json')]
    if not files:
        return None
    files.sort(key=lambda x: os.path.getmtime(os.path.join(BACKUP_DIR, x)), reverse=True)
    with open(os.path.join(BACKUP_DIR, files[0]), 'r', encoding='utf-8') as f:
        return json.load(f)

def extract_id(data):
    if isinstance(data, dict):
        for k in ['id', 'Id', 'ID', 'userId', 'account']:
            if k in data:
                return str(data[k])
    return str(int(time.time()))

# ==========================================
# Remote Server Communication
# ==========================================
def get_remote_data_raw(profile):
    try:
        r = requests.get(
            "https://shuen.ddns.net/DzAPI_ServerData.php",
            params={"profile": profile, "action": "view"},
            timeout=15, verify=False
        )
        if "profile not exist" in r.text:
            return None
        textarea = BeautifulSoup(r.text, 'html.parser').find('textarea')
        return textarea.text.strip() if textarea else None
    except Exception:
        return None

def post_remote_data(profile, password, data):
    try:
        data_str = json.dumps(data, indent=4) if isinstance(data, dict) else str(data)
        payload = {
            'json': (None, data_str),
            'profile': (None, profile),
            'password': (None, password),
            'submit': (None, 'Save')
        }
        r = requests.post(
            "https://shuen.ddns.net/DzAPI_ServerData.php",
            files=payload,
            verify=False,
            timeout=15
        )
        return r.status_code == 200, r.text
    except Exception as e:
        return False, str(e)

def parse_and_backup():
    config = load_config()
    if not config.get('profile') or not config.get('hash'):
        return
    try:
        raw_data = get_remote_data_raw(config['profile'])
        if raw_data:
            remote = json.loads(raw_data)
            if remote != get_latest_backup():
                bid = extract_id(remote)
                fn = f"backup_{bid}.json" if not os.path.exists(os.path.join(BACKUP_DIR, f"backup_{bid}.json")) else f"backup_{bid}_{int(time.time())}.json"
                with open(os.path.join(BACKUP_DIR, fn), 'w', encoding='utf-8') as f:
                    json.dump(remote, f, indent=4)
            config['last_parse_time'] = int(time.time())
            save_config(config)
    except Exception:
        pass

# ==========================================
# Scheduler Setup
# ==========================================
scheduler = BackgroundScheduler(daemon=True)
scheduler.add_job(parse_and_backup, 'interval', minutes=load_config().get('interval', 5), id='parse_job')
scheduler.start()

def restart_scheduler(interval):
    scheduler.reschedule_job('parse_job', trigger='interval', minutes=interval)

# ==========================================
# API Routes
# ==========================================
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/favicon.ico')
def favicon():
    return '', 204

@app.route('/api/config', methods=['GET', 'POST'])
def handle_config():
    if request.method == 'POST':
        data, cfg = request.json, load_config()
        for k in ['profile', 'password', 'bat_path', 'lang', 'interval']:
            if k in data:
                cfg[k] = data[k]
        save_config(cfg)
        if 'interval' in data:
            restart_scheduler(cfg['interval'])
        return jsonify({"status": "success"})
    return jsonify(load_config())

@app.route('/api/available_locales')
def available_locales():
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
        r = tk.Tk()
        r.withdraw()
        r.attributes('-topmost', True)
        fp = filedialog.askopenfilename(title="Select KKWE - Launch 1.27.bat", filetypes=[("Batch", "*.bat")])
        r.destroy()
        if fp:
            cfg = load_config()
            cfg['bat_path'] = fp
            save_config(cfg)

    t = threading.Thread(target=dlg)
    t.start()
    t.join()
    return jsonify(load_config())

@app.route('/api/launch', methods=['POST'])
def launch_bat():
    cfg = load_config()
    if not cfg.get('bat_path') or not os.path.exists(cfg['bat_path']):
        return jsonify({"error": "Path not set"}), 400
    try:
        creation_flags = 0
        if sys.platform == "win32":
            creation_flags = subprocess.CREATE_NEW_CONSOLE
            
        subprocess.Popen(
            [cfg['bat_path']], 
            cwd=os.path.dirname(cfg['bat_path']), 
            env=os.environ.copy(),
            creationflags=creation_flags
        )
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
        "backups": [{"name": f, "date": time.strftime('%d.%m.%Y %H:%M:%S', time.localtime(os.path.getmtime(os.path.join(BACKUP_DIR, f))))} for f in files],
        "last_parse_time": cfg.get('last_parse_time', 0)
    })

@app.route('/api/backups/read', methods=['GET'])
def read_backup():
    fn = request.args.get('file')
    if not fn or '..' in fn:
        return jsonify({"error": "Invalid file"}), 400
    fp = os.path.join(BACKUP_DIR, fn)
    if not os.path.exists(fp):
        return jsonify({"error": "Not found"}), 404
    try:
        with open(fp, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return jsonify({"data": data})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/backups/rename', methods=['POST'])
def rename_backup():
    data = request.json
    old_name = data.get('old_filename')
    new_name = data.get('new_filename')

    if not old_name or not new_name:
        return jsonify({"error": "MISSING_FIELDS"}), 400
    if not new_name.endswith('.json'):
        new_name += '.json'
    if old_name == new_name:
        return jsonify({"error": "ERR_RENAME_SAME"})

    old_path = os.path.join(BACKUP_DIR, old_name)
    new_path = os.path.join(BACKUP_DIR, new_name)

    if not os.path.exists(old_path):
        return jsonify({"error": "NOT_FOUND"}), 404
    if os.path.exists(new_path):
        return jsonify({"error": "ERR_RENAME_EXISTS"})

    try:
        os.rename(old_path, new_path)
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/backups/delete', methods=['POST'])
def delete_backup():
    fp = os.path.join(BACKUP_DIR, request.json.get('filename', ''))
    if os.path.exists(fp):
        os.remove(fp)
        return jsonify({"status": "success"})
    return jsonify({"error": "Not found"}), 404

@app.route('/api/backups/restore', methods=['POST'])
def restore_backup():
    fn, cfg = request.json.get('filename'), load_config()
    fp = os.path.join(BACKUP_DIR, fn)
    if not os.path.exists(fp):
        return jsonify({"error": "Not found"}), 404
    if not cfg.get('profile') or not cfg.get('password'):
        return jsonify({"error": "No credentials"}), 400
    
    with open(fp, 'r', encoding='utf-8') as f:
        data = json.load(f)
    try:
        if post_remote_data(cfg['profile'], cfg['password'], data)[0]:
            return jsonify({"status": "success"})
        return jsonify({"error": "Failed to save"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/check_profile', methods=['GET'])
def check_profile():
    profile = request.args.get('profile')
    if not profile:
        return jsonify({"exists": True})
    try:
        if get_remote_data_raw(profile) is None:
            return jsonify({"exists": False})
        return jsonify({"exists": True})
    except:
        return jsonify({"exists": True})

@app.route('/api/verify_password', methods=['POST'])
def verify_password():
    profile = request.json.get('profile')
    password = request.json.get('password')

    if not profile or not password:
        return jsonify({"error": "ERR_EMPTY_FIELDS"})

    try:
        original_raw = get_remote_data_raw(profile)
        if original_raw is None:
            return jsonify({"error": "ERR_PROFILE_NOT_EXIST"})

        try:
            original_data = json.loads(original_raw)
        except:
            original_data = original_raw

        dummy_data = {"MapLevel": "123"}
        success, save_text = post_remote_data(profile, password, dummy_data)
        if not success:
            return jsonify({"error": "ERR_SAVE_DUMMY"})

        check_raw = get_remote_data_raw(profile)
        try:
            check_data = json.loads(check_raw) if check_raw else None
            if check_data != dummy_data:
                return jsonify({"error": "ERR_DUMMY_MISMATCH"})
        except:
            return jsonify({"error": "ERR_DUMMY_MISMATCH"})

        restore_success, restore_text = post_remote_data(profile, password, original_data)
        if not restore_success:
            return jsonify({"error": "ERR_RESTORE_DATA"})

        h = hashlib.sha256(f"{profile}{password}".encode()).hexdigest()
        cfg = load_config()
        cfg['profile'] = profile
        cfg['password'] = password
        cfg['hash'] = h
        save_config(cfg)

        return jsonify({"status": "success", "hash": h})
    except Exception:
        return jsonify({"error": "ERR_VERIFY_EXCEPTION"})

# ==========================================
# Hook & Logs API Routes
# ==========================================
@app.route('/api/hook/status')
def hook_status():
    online = (time.time() - last_heartbeat_time) < 5 if last_heartbeat_time > 0 else False
    return jsonify({"running": hook_active, "is_admin": is_admin(), "online": online})

@app.route('/api/hook/toggle', methods=['POST'])
def hook_toggle():
    if not is_admin():
        return jsonify({"error": "NEED_ADMIN"}), 403
    if hook_active:
        stop_sniffer()
    else:
        start_sniffer()
    return jsonify({"status": "success", "running": hook_active})

@app.route('/api/hook/elevate', methods=['POST'])
def hook_elevate():
    if not is_admin():
        try:
            params = " ".join(sys.argv[1:])
            if not getattr(sys, 'frozen', False):
                params = f'"{os.path.abspath(__file__)}" ' + params
            ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
            threading.Timer(1.0, os._exit, args=[0]).start()
            return jsonify({"status": "success"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    return jsonify({"status": "success"})

@app.route('/api/logs', methods=['GET'])
def list_logs():
    ensure_dirs()
    files = [f for f in os.listdir(LOG_DIR) if f.endswith('.log')]
    files.sort(key=lambda x: os.path.getmtime(os.path.join(LOG_DIR, x)), reverse=True)
    return jsonify({
        "logs": [{"name": f, "date": time.strftime('%d.%m.%Y %H:%M:%S', time.localtime(os.path.getmtime(os.path.join(LOG_DIR, f))))} for f in files]
    })

@app.route('/api/logs/read', methods=['GET'])
def read_log():
    fn = request.args.get('file')
    if not fn or '..' in fn:
        return jsonify({"error": "Invalid file"}), 400
    fp = os.path.join(LOG_DIR, fn)
    if not os.path.exists(fp):
        return jsonify({"error": "Not found"}), 404
    try:
        with open(fp, 'r', encoding='utf-8') as f:
            return jsonify({"content": f.read()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ==========================================
# Main Entry Point
# ==========================================
if __name__ == '__main__':
    ensure_dirs()
    
    if is_admin():
        start_sniffer()

    webbrowser.open('http://127.0.0.1:5000')
    
    serve(app, host='127.0.0.1', port=5000)