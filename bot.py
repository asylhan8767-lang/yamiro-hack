import telebot
from telebot import types
from flask import Flask
import threading
import os
import sqlite3
import time
import zipfile
import subprocess
import shutil
import psutil
import sys
from datetime import datetime, timedelta
from threading import Thread

# ========== КОНФИГ ==========
TOKEN = "8968429505:AAG0gVZyA-13NIcOamQjWEvO6FidTkPA_Ok"
ADMIN_ID = 8826944181  # Новый ID создателя

bot = telebot.TeleBot(TOKEN)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
USERS_DIR = os.path.join(BASE_DIR, "users_projects")
os.makedirs(USERS_DIR, exist_ok=True)

DB_PATH = os.path.join(BASE_DIR, "bothost.db")
BOT_USERNAME = None

# ========== БАЗА ДАННЫХ ==========
def get_db():
    """Создает и возвращает соединение с БД"""
    try:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception as e:
        print(f"❌ Ошибка подключения к БД: {e}")
        return None

def close_db(conn):
    """Безопасно закрывает соединение с БД"""
    if conn:
        try:
            conn.close()
        except:
            pass

def init_db():
    """Инициализация базы данных со всеми таблицами"""
    conn = None
    try:
        conn = get_db()
        if not conn:
            print("❌ Не удалось подключиться к БД")
            return
        
        cursor = conn.cursor()
        
        # Таблица пользователей (без email)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                balance INTEGER DEFAULT 0,
                ref_balance INTEGER DEFAULT 0,
                referrer_id INTEGER DEFAULT NULL,
                bonus_claimed INTEGER DEFAULT 0
            )
        ''')
        
        # Таблица серверов
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS servers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                server_name TEXT,
                tariff TEXT DEFAULT 'Старт',
                status TEXT DEFAULT 'отключена',
                pid INTEGER DEFAULT NULL,
                main_file TEXT DEFAULT NULL,
                files TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                paid_till TEXT,
                auto_renew INTEGER DEFAULT 0,
                language TEXT DEFAULT 'python'
            )
        ''')
        
        # Таблица ожидающих платежей
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS pending_payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount INTEGER,
                status TEXT DEFAULT 'pending',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Системная конфигурация
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS system_config (
                key TEXT PRIMARY KEY,
                value INTEGER
            )
        ''')
        cursor.execute("INSERT OR IGNORE INTO system_config (key, value) VALUES ('server_counter', 0)")
        
        # Промокоды
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS promocodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE,
                bonus INTEGER DEFAULT 0,
                max_activations INTEGER DEFAULT 10,
                used_count INTEGER DEFAULT 0,
                created_by INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Активации промокодов
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS promocode_activations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                promo_code TEXT,
                activated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Удаленные файлы
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS deleted_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                server_id INTEGER,
                user_id INTEGER,
                file_name TEXT,
                file_path TEXT,
                deleted_at TEXT DEFAULT CURRENT_TIMESTAMP,
                restored INTEGER DEFAULT 0
            )
        ''')

        # Обязательные подписки (каналы)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS required_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT,
                invite_link TEXT,
                button_text TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute("INSERT OR IGNORE INTO system_config (key, value) VALUES ('force_sub_enabled', 1)")
        
        conn.commit()
        print("✅ База данных готова!")
        
    except Exception as e:
        print(f"❌ Ошибка инициализации БД: {e}")
    finally:
        close_db(conn)

def init_user(user_id, referrer_id=None):
    """Инициализация пользователя в БД"""
    conn = None
    try:
        conn = get_db()
        if not conn:
            return
        
        cursor = conn.cursor()
        
        # Проверяем существование пользователя
        cursor.execute('SELECT user_id FROM users WHERE user_id = ?', (user_id,))
        if not cursor.fetchone():
            # Создаем пользователя
            cursor.execute('INSERT INTO users (user_id, balance, ref_balance, referrer_id) VALUES (?, 0, 0, ?)', 
                          (user_id, referrer_id))
            
            # Начисляем бонус рефереру
            if referrer_id and referrer_id != user_id:
                cursor.execute('UPDATE users SET ref_balance = ref_balance + 10 WHERE user_id = ?', (referrer_id,))
                try:
                    bot.send_message(referrer_id, f"🎉 Вы получили 10 ⭐ за приглашение!")
                except:
                    pass
            
            conn.commit()
    except Exception as e:
        print(f"❌ Ошибка инициализации пользователя: {e}")
    finally:
        close_db(conn)

# ========== ОБЯЗАТЕЛЬНАЯ ПОДПИСКА ==========
def get_force_sub_enabled():
    """Проверяет, включена ли обязательная подписка"""
    conn = get_db()
    if not conn:
        return True
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM system_config WHERE key = 'force_sub_enabled'")
        row = cursor.fetchone()
        return bool(row[0]) if row else True
    except Exception as e:
        print(f"❌ Ошибка чтения force_sub_enabled: {e}")
        return True
    finally:
        close_db(conn)

def set_force_sub_enabled(value):
    """Включает/выключает обязательную подписку"""
    conn = get_db()
    if not conn:
        return
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE system_config SET value = ? WHERE key = 'force_sub_enabled'", (1 if value else 0,))
        conn.commit()
    except Exception as e:
        print(f"❌ Ошибка записи force_sub_enabled: {e}")
    finally:
        close_db(conn)

def get_required_channels():
    """Возвращает список всех обязательных каналов: [(id, chat_id, invite_link, button_text), ...]"""
    conn = get_db()
    if not conn:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, chat_id, invite_link, button_text FROM required_channels ORDER BY id")
        return cursor.fetchall()
    except Exception as e:
        print(f"❌ Ошибка чтения required_channels: {e}")
        return []
    finally:
        close_db(conn)

def add_required_channel(chat_id, invite_link, button_text):
    """Добавляет обязательный канал"""
    conn = get_db()
    if not conn:
        return
    try:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO required_channels (chat_id, invite_link, button_text) VALUES (?, ?, ?)",
                      (chat_id, invite_link, button_text))
        conn.commit()
    except Exception as e:
        print(f"❌ Ошибка добавления канала: {e}")
    finally:
        close_db(conn)

def delete_required_channel(channel_id):
    """Удаляет обязательный канал по внутреннему id"""
    conn = get_db()
    if not conn:
        return
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM required_channels WHERE id = ?", (channel_id,))
        conn.commit()
    except Exception as e:
        print(f"❌ Ошибка удаления канала: {e}")
    finally:
        close_db(conn)

def is_user_subscribed_all(user_id):
    """
    Проверяет, подписан ли пользователь на все обязательные каналы.
    Если проверка канала не удалась (бот не админ / неверный ID) — пользователь
    считается НЕ подписанным (чтобы гейт реально работал), а админу шлётся
    предупреждение о неверной настройке канала.
    """
    if not get_force_sub_enabled():
        return True
    channels = get_required_channels()
    if not channels:
        return True
    all_ok = True
    for ch_id, chat_id, invite_link, button_text in channels:
        try:
            member = bot.get_chat_member(chat_id, user_id)
            if member.status not in ("member", "administrator", "creator"):
                all_ok = False
        except Exception as e:
            print(f"⚠️ Не удалось проверить подписку на канал {chat_id}: {e}")
            all_ok = False
    return all_ok

def force_sub_keyboard():
    """Клавиатура с кнопками-ссылками на обязательные каналы + кнопка подтверждения"""
    markup = types.InlineKeyboardMarkup(row_width=1)
    for ch_id, chat_id, invite_link, button_text in get_required_channels():
        markup.add(types.InlineKeyboardButton(button_text, url=invite_link))
    markup.add(types.InlineKeyboardButton("✅ Подтвердить", callback_data="check_subscription"))
    return markup

def send_welcome_menu(chat_id, user_id, first_name):
    """Отправляет приветственное сообщение с главным меню (после прохождения проверки подписки)"""
    text = f"""<b>🤖 Привет, {first_name}!</b>

<i>Добро пожаловать в панель управления хостингом SELVER HOST.</i>

<b>⚡️ Здесь ты можешь запустить нового бота или управлять своими текущими проектами.</b>

👇 <i>Выбирай нужное действие на панели ниже:</i>"""
    bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=main_menu_keyboard(user_id))

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def get_server_folder(user_id, server_id):
    """Возвращает путь к папке сервера"""
    folder_path = os.path.join(USERS_DIR, f"user_{user_id}", f"server_{server_id}")
    os.makedirs(folder_path, exist_ok=True)
    return folder_path

def find_all_py_files(target_dir):
    """Поиск всех .py файлов в папке"""
    if not os.path.exists(target_dir):
        return []
    py_files = []
    for root, dirs, files in os.walk(target_dir):
        for file in files:
            if file.lower().endswith('.py'):
                rel = os.path.relpath(os.path.join(root, file), target_dir)
                py_files.append(rel)
    return py_files

def find_all_js_files(target_dir):
    """Поиск всех .js файлов в папке"""
    if not os.path.exists(target_dir):
        return []
    js_files = []
    for root, dirs, files in os.walk(target_dir):
        for file in files:
            if file.lower().endswith('.js'):
                rel = os.path.relpath(os.path.join(root, file), target_dir)
                js_files.append(rel)
    return js_files

def install_requirements(server_path):
    """Устанавливает библиотеки из requirements.txt, если файл есть. Возвращает текст лога установки."""
    req_path = os.path.join(server_path, "requirements.txt")
    if not os.path.exists(req_path):
        return ""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", req_path,
             "--disable-pip-version-check", "--no-input"],
            cwd=server_path, capture_output=True, text=True, timeout=180
        )
        log = (result.stdout or "") + (result.stderr or "")
        return log[-2000:]
    except Exception as e:
        return f"❌ Ошибка установки библиотек: {e}"

# ========== БИБЛИОТЕКИ (пакеты python) ==========
POPULAR_LIBRARIES = [
    ("pyTelegramBotAPI", "telebot"),
    ("aiogram", "aiogram"),
    ("python-telegram-bot", "telegram"),
    ("requests", "requests"),
    ("python-dotenv", "dotenv"),
    ("psutil", "psutil"),
    ("Pillow", "PIL"),
    ("beautifulsoup4", "bs4"),
    ("aiohttp", "aiohttp"),
    ("Flask", "flask"),
    ("FastAPI", "fastapi"),
    ("uvicorn", "uvicorn"),
    ("SQLAlchemy", "sqlalchemy"),
    ("pymongo", "pymongo"),
    ("redis", "redis"),
    ("celery", "celery"),
    ("numpy", "numpy"),
    ("pandas", "pandas"),
    ("matplotlib", "matplotlib"),
    ("opencv-python", "cv2"),
    ("selenium", "selenium"),
    ("schedule", "schedule"),
    ("pytz", "pytz"),
    ("cryptography", "cryptography"),
    ("PyJWT", "jwt"),
    ("qrcode", "qrcode"),
    ("openpyxl", "openpyxl"),
    ("lxml", "lxml"),
    ("colorama", "colorama"),
    ("emoji", "emoji"),
]

# pyTelegramBotAPI и aiogram — разные Telegram-фреймворки, у одного бота
# обычно используется только один из них
TELEGRAM_FRAMEWORK_LIBS = {"pyTelegramBotAPI", "aiogram"}
# библиотеки, которые добавляются автоматически при первом открытии панели
DEFAULT_AUTO_LIBS = ["requests", "python-dotenv"]

def get_requirements_path(server_path):
    """Путь к requirements.txt конкретного сервера"""
    return os.path.join(server_path, "requirements.txt")

def read_requirements(server_path):
    """Считывает requirements.txt сервера построчно (без пустых строк)"""
    req_path = get_requirements_path(server_path)
    if not os.path.exists(req_path):
        return []
    try:
        with open(req_path, "r", encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip()]
    except Exception as e:
        print(f"❌ Ошибка чтения requirements.txt: {e}")
        return []

def write_requirements(server_path, lines):
    """Перезаписывает requirements.txt сервера"""
    req_path = get_requirements_path(server_path)
    try:
        with open(req_path, "w", encoding="utf-8") as f:
            if lines:
                f.write("\n".join(lines) + "\n")
        return True
    except Exception as e:
        print(f"❌ Ошибка записи requirements.txt: {e}")
        return False

def _pkg_base_name(line):
    """Возвращает базовое имя пакета из строки requirements.txt (без версии)"""
    for sep in ("==", ">=", "<=", "~=", ">", "<"):
        if sep in line:
            return line.split(sep)[0].strip()
    return line.strip()

def is_lib_installed(lines, pkg_name):
    """Проверяет, есть ли библиотека в списке строк requirements.txt"""
    pkg_lower = pkg_name.lower()
    for line in lines:
        if _pkg_base_name(line).lower() == pkg_lower:
            return True
    return False

def detect_bot_framework(server_path, main_file):
    """Определяет по коду главного файла, какой Telegram-фреймворк использует бот:
    pyTelegramBotAPI (telebot) или aiogram. Возвращает None, если не определено."""
    if not main_file:
        return None
    file_path = os.path.join(server_path, main_file)
    if not os.path.exists(file_path):
        return None
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except Exception:
        return None

    has_telebot = ("import telebot" in content) or ("from telebot" in content)
    has_aiogram = ("import aiogram" in content) or ("from aiogram" in content)

    if has_telebot and not has_aiogram:
        return "pyTelegramBotAPI"
    if has_aiogram and not has_telebot:
        return "aiogram"
    return None

def pip_install_package(pkg_name):
    """Устанавливает один пакет через pip. Возвращает (успех, лог)"""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", pkg_name,
             "--disable-pip-version-check", "--no-input"],
            capture_output=True, text=True, timeout=120
        )
        log = (result.stdout or "") + (result.stderr or "")
        return result.returncode == 0, log[-1500:]
    except Exception as e:
        return False, f"❌ Ошибка установки {pkg_name}: {e}"

def ensure_server_requirements(server_path, main_file):
    """
    Если у сервера ещё нет requirements.txt — создаёт его, определяет
    используемый Telegram-фреймворк по коду главного файла и добавляет
    несколько популярных библиотек по умолчанию.
    """
    req_path = get_requirements_path(server_path)
    if os.path.exists(req_path):
        return False

    lines = []
    framework = detect_bot_framework(server_path, main_file)
    if framework:
        lines.append(framework)

    for lib in DEFAULT_AUTO_LIBS:
        if not is_lib_installed(lines, lib):
            lines.append(lib)

    write_requirements(server_path, lines)
    return True

def launch_server_process(selected, server_path, log_file):
    """
    Запускает python-файл сервера в неблокирующем (unbuffered) режиме,
    ставит библиотеки из requirements.txt, и проверяет, что процесс не упал
    сразу после старта (частая причина: 'бот не отвечает, лог пустой').
    Возвращает (pid, crashed, error_text). Если crashed=True, процесс уже мёртв
    и error_text содержит хвост лога с ошибкой.
    """
    install_log = install_requirements(server_path)

    with open(log_file, "w", encoding="utf-8") as out:
        if install_log:
            out.write("=== Установка библиотек (requirements.txt) ===\n")
            out.write(install_log + "\n")
            out.write("=== Запуск бота ===\n")
            out.flush()
        # флаг -u отключает буферизацию вывода: print() из бота сразу попадает в лог,
        # а не зависает в буфере, из-за чего лог выглядел "пустым"
        proc = subprocess.Popen([sys.executable, "-u", selected],
                                 stdout=out, stderr=out, cwd=server_path)

    # Короткая пауза, чтобы поймать мгновенный краш (неверный токен, ImportError, синтаксис и т.д.)
    time.sleep(2)
    if proc.poll() is not None:
        try:
            with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                tail = f.read()[-1500:]
        except Exception:
            tail = ""
        return proc.pid, True, tail or "Процесс завершился без вывода ошибки."

    return proc.pid, False, ""

def stop_server_process(server_id, conn=None):
    """Остановка процесса сервера"""
    close_conn = False
    if conn is None:
        conn = get_db()
        close_conn = True
    
    if not conn:
        return False
    
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT pid FROM servers WHERE id = ?", (server_id,))
        row = cursor.fetchone()
        if row and row[0]:
            pid = row[0]
            try:
                proc = psutil.Process(pid)
                if proc.is_running():
                    proc.terminate()
                    proc.wait(timeout=5)
                    if proc.is_running():
                        proc.kill()
            except:
                pass
            cursor.execute("UPDATE servers SET status = 'отключена', pid = NULL WHERE id = ?", (server_id,))
            conn.commit()
    except Exception as e:
        print(f"❌ Ошибка остановки сервера: {e}")
    finally:
        if close_conn:
            close_db(conn)
    return True

def extract_zip_safe(zip_path, target_dir):
    """Безопасная распаковка ZIP архива"""
    try:
        print(f"📦 Распаковка: {zip_path} -> {target_dir}")
        
        if not os.path.exists(zip_path):
            print(f"❌ ZIP не найден: {zip_path}")
            return False
        
        if os.path.getsize(zip_path) == 0:
            print(f"❌ ZIP пустой")
            return False
        
        os.makedirs(target_dir, exist_ok=True)
        
        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(target_dir)
        
        print(f"✅ ZIP распакован")
        return True
        
    except zipfile.BadZipFile:
        print(f"❌ Файл не ZIP архив")
        return False
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return False

def create_stars_invoice(user_id, amount):
    """Создание инвойса для оплаты звездами"""
    try:
        prices = [types.LabeledPrice(label=f"Пополнение на {amount} ⭐", amount=amount)]
        invoice = bot.send_invoice(
            chat_id=user_id,
            title="⭐ Пополнение SELVER HOST",
            description=f"Пополнение баланса на {amount} звезд",
            invoice_payload=f"deposit_{user_id}_{amount}_{int(time.time())}",
            provider_token="",
            currency="XTR",
            prices=prices,
            need_name=False,
            need_phone_number=False,
            need_email=False,
            need_shipping_address=False,
            is_flexible=False
        )
        return invoice
    except Exception as e:
        print(f"❌ Ошибка создания инвойса: {e}")
        return None

# ========== КЛАВИАТУРЫ ==========
def main_menu_keyboard(user_id=None):
    """Главное меню"""
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn1 = types.InlineKeyboardButton("🖥 Создать сервер", callback_data="create_server")
    btn2 = types.InlineKeyboardButton("📋 Мои серверы", callback_data="my_servers")
    btn3 = types.InlineKeyboardButton("👤 Мой профиль", callback_data="my_profile")
    btn4 = types.InlineKeyboardButton("🎫 Активировать промокод", callback_data="activate_promo")
    btn5 = types.InlineKeyboardButton("📢 Наши ресурсы", callback_data="our_resources")
    btn6 = types.InlineKeyboardButton("ℹ️ О проекте", callback_data="about_project")
    markup.add(btn1, btn2, btn3, btn4, btn5, btn6)
    if user_id is not None and user_id == ADMIN_ID:
        markup.add(types.InlineKeyboardButton("👑 Админ-панель", callback_data="admin_panel"))
    return markup

def admin_panel_keyboard():
    """Клавиатура админ-панели (видна только админу)"""
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🔍 Посмотреть сервер", callback_data="admin_getserver"),
        types.InlineKeyboardButton("🖥 Все серверы", callback_data="admin_allservers"),
        types.InlineKeyboardButton("🎫 Создать промокод", callback_data="admin_createpromo"),
        types.InlineKeyboardButton("💰 Выдать баланс", callback_data="admin_givetg"),
        types.InlineKeyboardButton("👥 Пользователи", callback_data="admin_users"),
        types.InlineKeyboardButton("📢 Обязательные подписки", callback_data="admin_forcesub"),
        types.InlineKeyboardButton("⬅️ Главное меню", callback_data="main_menu")
    )
    return markup

def force_sub_admin_keyboard():
    """Клавиатура настроек обязательной подписки для админ-панели"""
    enabled = get_force_sub_enabled()
    markup = types.InlineKeyboardMarkup(row_width=2)
    status_text = "🟢 Жазылым күйі: ҚОСУЛЫ (ВКЛ)" if enabled else "🔴 Жазылым күйі: ӨШІРУЛІ (ВЫКЛ)"
    markup.add(types.InlineKeyboardButton(status_text, callback_data="admin_forcesub_toggle"))

    for ch_id, chat_id, invite_link, button_text in get_required_channels():
        markup.add(
            types.InlineKeyboardButton(button_text, url=invite_link),
            types.InlineKeyboardButton("🗑️ Өшіру", callback_data=f"admin_forcesub_del_{ch_id}")
        )

    markup.add(types.InlineKeyboardButton("➕ Канал қосу", callback_data="admin_forcesub_add"))
    markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="admin_panel"))
    return markup

def force_sub_admin_text():
    return """📢 <b>Міндетті жазылу баптаулары (Настройка обязательной подписки)</b>

Бұл жерде сіз пайдаланушылар ботқа кірмес бұрын тіркелуі тиіс Telegram каналдарын реттей аласыз.

⚠️ <b>МАҢЫЗДЫ:</b> Тексеру жүйесі дұрыс жұмыс істеуі үшін бот бұл каналдарда міндетті түрде Әкімші (Администратор) құқығына ие болуы қажет!"""


def servers_list_keyboard(user_id, conn):
    """Клавиатура со списком серверов"""
    markup = types.InlineKeyboardMarkup(row_width=1)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, server_name, status FROM servers WHERE user_id = ?", (user_id,))
        servers = cursor.fetchall()
        
        for sid, name, status in servers:
            icon = "🟢" if status == "включена" else "🔴"
            markup.add(types.InlineKeyboardButton(f"{icon} {name}", callback_data=f"server_panel_{sid}"))
        
        if len(servers) < 5:
            markup.add(types.InlineKeyboardButton("➕ Создать сервер", callback_data="create_server"))
        markup.add(types.InlineKeyboardButton("⬅️ Главное меню", callback_data="main_menu"))
    except Exception as e:
        print(f"❌ Ошибка создания клавиатуры серверов: {e}")
        markup.add(types.InlineKeyboardButton("⬅️ Главное меню", callback_data="main_menu"))
    return markup

def server_panel_keyboard(server_id):
    """Панель управления сервером"""
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🔌 Запустить/Остановить", callback_data=f"server_power_{server_id}"),
        types.InlineKeyboardButton("🔄 Перезагрузить", callback_data=f"server_restart_{server_id}"),
        types.InlineKeyboardButton("📁 Файлы", callback_data=f"server_files_{server_id}"),
        types.InlineKeyboardButton("📑 Логи", callback_data=f"server_logs_{server_id}"),
        types.InlineKeyboardButton("📦 Библиотеки", callback_data=f"server_libs_{server_id}"),
        types.InlineKeyboardButton("🔧 .env", callback_data=f"server_env_{server_id}"),
        types.InlineKeyboardButton("⏰ Продлить", callback_data=f"server_renew_{server_id}"),
        types.InlineKeyboardButton("🔄 Автопродление", callback_data=f"server_autorenew_{server_id}"),
        types.InlineKeyboardButton("🗑 Удалить сервер", callback_data=f"server_delete_{server_id}")
    )
    markup.add(types.InlineKeyboardButton("⬅️ Назад к списку", callback_data="my_servers"))
    return markup

def files_keyboard(server_id, files_list):
    """Клавиатура файлов"""
    markup = types.InlineKeyboardMarkup(row_width=1)
    for f in files_list[:20]:
        markup.add(types.InlineKeyboardButton(f"📄 {f}", callback_data=f"server_file_action_{server_id}_{f}"))
    markup.add(
        types.InlineKeyboardButton("📤 Загрузить файл", callback_data=f"server_upload_file_{server_id}"),
        types.InlineKeyboardButton("📦 Загрузить ZIP", callback_data=f"server_upload_zip_{server_id}"),
        types.InlineKeyboardButton("🎯 Выбрать основной файл", callback_data=f"server_select_main_{server_id}"),
        types.InlineKeyboardButton("⬅️ Назад", callback_data=f"server_panel_{server_id}")
    )
    return markup

def profile_keyboard():
    """Клавиатура профиля"""
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("⭐ Пополнить баланс", callback_data="deposit_balance"),
        types.InlineKeyboardButton("⬅️ Главное меню", callback_data="main_menu")
    )
    return markup

# ========== КОМАНДЫ ==========
@bot.message_handler(commands=['start'])
def start_cmd(message):
    """Обработчик команды /start"""
    try:
        user_id = message.from_user.id
        first_name = message.from_user.first_name
        
        # Реферальная система
        ref_id = None
        if len(message.text.split()) > 1:
            try:
                ref_id = int(message.text.split()[1])
                if ref_id == user_id:
                    ref_id = None
            except:
                pass
        
        # Инициализация пользователя
        init_user(user_id, ref_id)
        
        # ---------- ПРОВЕРКА ОБЯЗАТЕЛЬНОЙ ПОДПИСКИ ----------
        if not is_user_subscribed_all(user_id):
            text = """⚠️ <b>Обязательная подписка!</b>

Чтобы продолжить пользоваться ботом, вам необходимо сначала подписаться на каналы, указанные ниже.

Выполните условия и нажмите кнопку «✅ Подтвердить»:"""
            try:
                bot.send_message(message.chat.id, text, parse_mode="HTML", reply_markup=force_sub_keyboard())
            except Exception as e:
                # Частая причина: неверный формат ссылки одного из каналов (Telegram отклоняет
                # ВСЁ сообщение с кнопками целиком). Уведомляем админа с точной причиной.
                print(f"❌ Не удалось отправить гейт обязательной подписки: {e}")
                try:
                    bot.send_message(ADMIN_ID,
                        f"⚠️ Гейт обязательной подписки не отправился пользователю {user_id}!\n"
                        f"Похоже, у одного из каналов неверная ссылка (invite_link).\n\nОшибка: {e}")
                except:
                    pass
                bot.send_message(message.chat.id, text, parse_mode="HTML")
            return
        
        # Текст приветствия
        send_welcome_menu(message.chat.id, user_id, first_name)
        
    except Exception as e:
        print(f"❌ Ошибка в start_cmd: {e}")
        try:
            bot.send_message(message.chat.id, "❌ Произошла ошибка. Попробуйте позже.")
        except:
            pass

# ========== ОБРАБОТЧИКИ CALLBACK ==========
# ВАЖНО: pyTelegramBotAPI вызывает только ПЕРВЫЙ подходящий обработчик (в порядке регистрации),
# поэтому "общий" обработчик НЕ должен перехватывать callback_data, которые обрабатываются
# отдельными @bot.callback_query_handler ниже по файлу (admin_renew_, admin_delete_ и т.д.) —
# иначе они никогда не будут вызваны. Это и было причиной "неработающих кнопок" в админке.
_ADMIN_STANDALONE_PREFIXES = (
    "admin_renew_",
    "admin_confirm_delete_", "admin_delete_",
    "admin_cancel_power_", "admin_cancel_tariff_", "admin_cancel_",
    "admin_confirm_power_", "admin_power_",
    "admin_balance_",
    "admin_set_tariff_", "admin_confirm_tariff_", "admin_tariff_",
    "admin_getfiles_",
)

@bot.callback_query_handler(func=lambda call: not call.data.startswith(_ADMIN_STANDALONE_PREFIXES))
def handle_callbacks(call):
    """Главный обработчик callback запросов"""
    try:
        user_id = call.from_user.id
        init_user(user_id)
        
        conn = get_db()
        if not conn:
            bot.answer_callback_query(call.id, "❌ Ошибка подключения к БД!", show_alert=True)
            return
        
        cursor = conn.cursor()

        # ---------- ГЛАВНОЕ МЕНЮ ----------
        if call.data == "main_menu":
            first_name = call.from_user.first_name
            text = f"""<b>🤖 Привет, {first_name}!</b>

<i>Добро пожаловать в панель управления хостингом SELVER HOST.</i>

<b>⚡️ Здесь ты можешь запустить нового бота или управлять своими текущими проектами.</b>

👇 <i>Выбирай нужное действие на панели ниже:</i>"""
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, 
                                parse_mode="HTML", reply_markup=main_menu_keyboard(user_id))
            close_db(conn)
            return

        # ---------- МОЙ ПРОФИЛЬ ----------
        elif call.data == "my_profile":
            try:
                cursor.execute("SELECT balance, ref_balance FROM users WHERE user_id = ?", (user_id,))
                row = cursor.fetchone()
                balance = row[0] if row and row[0] else 0
                ref_balance = row[1] if row and row[1] else 0
                total_balance = balance + ref_balance
                
                cursor.execute("SELECT COUNT(*) FROM servers WHERE user_id = ?", (user_id,))
                servers_count = cursor.fetchone()[0]
                
                global BOT_USERNAME
                if BOT_USERNAME:
                    ref_link = f"https://t.me/{BOT_USERNAME}?start={user_id}"
                else:
                    ref_link = "❌ Ошибка получения ссылки"
                
                text = f"""<b>👤 Ваш профиль</b>

<b>🆔 ID:</b> <code>{user_id}</code>
<b>💳 Баланс:</b> <code>{total_balance} ⭐</code>
<b>🖥 Серверов:</b> <code>{servers_count}/5</code>

<b>🔗 Реферальная ссылка:</b>
<code>{ref_link}</code>

<i>Приглашайте друзей и получайте 10% от их покупок на баланс!</i>"""
                
                bot.edit_message_text(text, call.message.chat.id, call.message.message_id, 
                                    parse_mode="HTML", reply_markup=profile_keyboard())
            except Exception as e:
                print(f"❌ Ошибка в профиле: {e}")
                bot.answer_callback_query(call.id, "❌ Ошибка загрузки профиля!", show_alert=True)
            finally:
                close_db(conn)
            return

        # ---------- НАШИ РЕСУРСЫ ----------
        elif call.data == "our_resources":
            text = """<b>📢 Наши ресурсы:</b>

<i>🆘 Поддержка:</i> @selver_soft
<i>💬 Хостинг чат:</i> https://t.me/selver_hosting
<i>📢 Хостинг канал:</i> https://t.me/selver_hosting_chat"""
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="main_menu"))
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, 
                                parse_mode="HTML", reply_markup=markup)
            close_db(conn)
            return

        # ---------- О ПРОЕКТЕ ----------
        elif call.data == "about_project":
            text = """<b>ℹ️ О проекте SELVER HOST</b>

🚀 <i>SELVER HOST — современный хостинг для Python-ботов 24/7.</i>

📦 <b>Возможности:</b>
• 🖥️ До 5 серверов на аккаунт
• 📂 Загрузка через ZIP и файлы
• 🛠️ Файловый менеджер и .env
• 📋 Логи, автопродление и рефералы

💎 <b>Тарифы в месяц:</b>
• 🔸 Старт — 50 ⭐
• 🔹 Стандарт — 120 ⭐
• 🔥 Про — 300 ⭐

<i>По всем вопросам: @selver_soft</i>"""
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="main_menu"))
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, 
                                parse_mode="HTML", reply_markup=markup)
            close_db(conn)
            return

        # ---------- ПОПОЛНЕНИЕ БАЛАНСА ----------
        elif call.data == "deposit_balance":
            msg = bot.send_message(call.message.chat.id, "⭐ Введите сумму в звёздах (минимум 1):")
            bot.register_next_step_handler(msg, process_deposit)
            close_db(conn)
            return

        # ---------- ОПЛАТА ПОПОЛНЕНИЯ ----------
        elif call.data.startswith("pay_"):
            amount = int(call.data.split("_")[1])
            invoice = create_stars_invoice(user_id, amount)
            if invoice:
                bot.answer_callback_query(call.id, "💳 Счет создан! Оплатите в открывшемся окне.", show_alert=True)
            else:
                bot.answer_callback_query(call.id, "❌ Ошибка создания счета. Попробуйте позже.", show_alert=True)
            close_db(conn)
            return

        # ---------- СОЗДАНИЕ СЕРВЕРА ----------
        elif call.data == "create_server":
            try:
                cursor.execute("SELECT COUNT(*) FROM servers WHERE user_id = ?", (user_id,))
                count = cursor.fetchone()[0]
                if count >= 5:
                    bot.answer_callback_query(call.id, "❌ У вас уже 5 серверов (максимум)!", show_alert=True)
                    close_db(conn)
                    return
                
                cursor.execute("SELECT balance, ref_balance FROM users WHERE user_id = ?", (user_id,))
                bal_row = cursor.fetchone()
                bal = bal_row[0] if bal_row and bal_row[0] else 0
                ref_bal = bal_row[1] if bal_row and bal_row[1] else 0
                total_balance = bal + ref_bal
                
                text = f"""<b>🖥 Создание нового сервера</b>

<i>Выберите тариф для вашего сервера:</i>

<b>🚀 Старт</b> — <code>50 ⭐/мес</code>
<b>⚙️ Стандарт</b> — <code>120 ⭐/мес</code>
<b>💎 Премиум</b> — <code>300 ⭐/мес</code>

<i>Нажмите на тариф для подробной информации</i>

<b>💳 Ваш баланс:</b> <code>{total_balance} ⭐</code>"""
                
                markup = types.InlineKeyboardMarkup(row_width=1)
                markup.add(
                    types.InlineKeyboardButton("🚀 Старт (50 ⭐)", callback_data="tariff_Старт"),
                    types.InlineKeyboardButton("⚙️ Стандарт (120 ⭐)", callback_data="tariff_Стандарт"),
                    types.InlineKeyboardButton("💎 Премиум (300 ⭐)", callback_data="tariff_Про"),
                    types.InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")
                )
                bot.edit_message_text(text, call.message.chat.id, call.message.message_id, 
                                    parse_mode="HTML", reply_markup=markup)
            except Exception as e:
                print(f"❌ Ошибка создания сервера: {e}")
                bot.answer_callback_query(call.id, "❌ Ошибка!", show_alert=True)
            finally:
                close_db(conn)
            return

        # ---------- ИНФОРМАЦИЯ О ТАРИФАХ ----------
        elif call.data.startswith("tariff_"):
            tariff_name = call.data.split("_")[1]
            
            try:
                cursor.execute("SELECT balance, ref_balance FROM users WHERE user_id = ?", (user_id,))
                bal_row = cursor.fetchone()
                bal = bal_row[0] if bal_row and bal_row[0] else 0
                ref_bal = bal_row[1] if bal_row and bal_row[1] else 0
                total_balance = bal + ref_bal
                
                if tariff_name == "Старт":
                    text = f"""<b>🚀 Тариф: Старт</b>

<i>• Цена:</i> <code>50 ⭐/мес</code>
<i>• Процессор:</i> <code>10% CPU</code>
<i>• Память:</i> <code>128 МБ RAM</code>
<i>• Диск:</i> <code>100 МБ</code>

<i>Идеально для маленьких ботов.</i>

<b>💳 Ваш баланс:</b> <code>{total_balance} ⭐</code>"""
                    
                elif tariff_name == "Стандарт":
                    text = f"""<b>⚙️ Тариф: Стандарт</b>

<i>• Цена:</i> <code>120 ⭐/мес</code>
<i>• Процессор:</i> <code>20% CPU</code>
<i>• Память:</i> <code>256 МБ RAM</code>
<i>• Диск:</i> <code>200 МБ</code>

<i>Для средних проектов.</i>

<b>💳 Ваш баланс:</b> <code>{total_balance} ⭐</code>"""
                    
                else:
                    text = f"""<b>💎 Тариф: Премиум</b>

<i>• Цена:</i> <code>300 ⭐/мес</code>
<i>• Процессор:</i> <code>30% CPU</code>
<i>• Память:</i> <code>512 МБ RAM</code>
<i>• Диск:</i> <code>300 МБ</code>

<i>Для серьезных задач.</i>

<b>💳 Ваш баланс:</b> <code>{total_balance} ⭐</code>"""
                
                markup = types.InlineKeyboardMarkup(row_width=2)
                markup.add(
                    types.InlineKeyboardButton("✅ Заказать сервер", callback_data=f"create_tariff_{tariff_name}"),
                    types.InlineKeyboardButton("⬅️ Назад к тарифам", callback_data="create_server")
                )
                bot.edit_message_text(text, call.message.chat.id, call.message.message_id, 
                                    parse_mode="HTML", reply_markup=markup)
            except Exception as e:
                print(f"❌ Ошибка показа тарифа: {e}")
            finally:
                close_db(conn)
            return

        # ---------- СОЗДАНИЕ ТАРИФА И СЕРВЕРА ----------
        elif call.data.startswith("create_tariff_"):
            tariff_name = call.data.split("_")[2]
            
            prices = {"Старт": 50, "Стандарт": 120, "Про": 300}
            price = prices.get(tariff_name, 50)
            
            try:
                cursor.execute("SELECT balance, ref_balance FROM users WHERE user_id = ?", (user_id,))
                row = cursor.fetchone()
                bal, ref_bal = row if row else (0, 0)
                bal = bal or 0
                ref_bal = ref_bal or 0
                total_balance = bal + ref_bal
                
                if total_balance < price:
                    bot.answer_callback_query(call.id, f"❌ Недостаточно средств! Нужно {price} ⭐.", show_alert=True)
                    close_db(conn)
                    return
                
                # Списание средств
                if ref_bal >= price:
                    cursor.execute("UPDATE users SET ref_balance = ref_balance - ? WHERE user_id = ?", (price, user_id))
                else:
                    remaining = price - ref_bal
                    cursor.execute("UPDATE users SET ref_balance = 0, balance = balance - ? WHERE user_id = ?", (remaining, user_id))
                
                # Создание сервера
                cursor.execute('''
                    INSERT INTO servers (user_id, server_name, tariff, status, paid_till, auto_renew) 
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (user_id, f"Сервер #{int(time.time())}", tariff_name, "отключена",
                      (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S"), 0))
                
                server_id = cursor.lastrowid
                conn.commit()
                
                # Создание папки
                server_path = get_server_folder(user_id, server_id)
                if not os.path.exists(server_path):
                    os.makedirs(server_path, exist_ok=True)
                
                bot.answer_callback_query(call.id, f"✅ Сервер #{server_id} создан! Тариф: {tariff_name}", show_alert=True)
                
                # Переход в панель сервера
                call.data = f"server_panel_{server_id}"
                handle_callbacks(call)
            except Exception as e:
                print(f"❌ Ошибка создания сервера: {e}")
                bot.answer_callback_query(call.id, "❌ Ошибка создания сервера!", show_alert=True)
            finally:
                close_db(conn)
            return

        # ---------- МОИ СЕРВЕРЫ ----------
        elif call.data == "my_servers":
            markup = servers_list_keyboard(user_id, conn)
            bot.edit_message_text("📋 Ваши серверы:", call.message.chat.id, call.message.message_id, 
                                reply_markup=markup)
            close_db(conn)
            return

        # ---------- АКТИВАЦИЯ ПРОМОКОДА ----------
        elif call.data == "activate_promo":
            msg = bot.send_message(call.message.chat.id, "🎫 Введите промокод для активации:\n\n<i>Пример: #подарок</i>", parse_mode="HTML")
            bot.register_next_step_handler(msg, process_activate_promo)
            close_db(conn)
            return

        # ---------- ПАНЕЛЬ СЕРВЕРА ----------
        elif call.data.startswith("server_panel_"):
            server_id = int(call.data.split("_")[2])
            try:
                cursor.execute("SELECT server_name, tariff, status, paid_till FROM servers WHERE id = ? AND user_id = ?", 
                              (server_id, user_id))
                row = cursor.fetchone()
                if not row:
                    bot.answer_callback_query(call.id, "❌ Сервер не найден!", show_alert=True)
                    close_db(conn)
                    return
                
                name, tariff, status, paid_till_str = row
                
                tariff_specs = {
                    "Старт": {"emoji": "🚀", "cpu": "10%", "ram": "128 МБ", "disk": "100 МБ", "price": 50},
                    "Стандарт": {"emoji": "⚙️", "cpu": "20%", "ram": "256 МБ", "disk": "200 МБ", "price": 120},
                    "Про": {"emoji": "💎", "cpu": "30%", "ram": "512 МБ", "disk": "300 МБ", "price": 300}
                }
                specs = tariff_specs.get(tariff, {"emoji": "📦", "cpu": "?", "ram": "?", "disk": "?", "price": 0})
                
                days_left = 0
                status_icon = "🟢" if status == "включена" else "🔴"
                status_text = "Работает" if status == "включена" else "Остановлен"
                
                if paid_till_str:
                    try:
                        paid_till = datetime.strptime(paid_till_str, "%Y-%m-%d %H:%M:%S")
                        now = datetime.now()
                        days_left = (paid_till - now).days
                        if days_left < 0:
                            days_left = 0
                    except:
                        days_left = 0
                
                progress_bar = ""
                if days_left > 0 and days_left <= 30:
                    filled = int(days_left / 3)
                    progress_bar = "🟩" * filled + "⬜" * (10 - filled)
                
                text = f"""<b>{specs['emoji']} {name}</b>

<i>📦 Тариф:</i> <code>{tariff}</code>
<i>💰 Цена:</i> <code>{specs['price']} ⭐/мес</code>
<i>🖥 CPU:</i> <code>{specs['cpu']}</code>
<i>💾 RAM:</i> <code>{specs['ram']}</code>
<i>💽 Диск:</i> <code>{specs['disk']}</code>

<i>{status_icon} Статус:</i> <code>{status_text}</code>
<i>⏰ Осталось дней:</i> <code>{days_left}</code>
{progress_bar}

<i>Управляй сервером через кнопки ниже 👇</i>"""
                
                bot.edit_message_text(text, call.message.chat.id, call.message.message_id, 
                                    parse_mode="HTML", reply_markup=server_panel_keyboard(server_id))
            except Exception as e:
                print(f"❌ Ошибка панели сервера: {e}")
            finally:
                close_db(conn)
            return

        # ---------- УПРАВЛЕНИЕ ПИТАНИЕМ ----------
        elif call.data.startswith("server_power_"):
            server_id = int(call.data.split("_")[2])
            try:
                cursor.execute("SELECT status, pid, main_file FROM servers WHERE id = ? AND user_id = ?", 
                              (server_id, user_id))
                row = cursor.fetchone()
                if not row:
                    bot.answer_callback_query(call.id, "❌ Сервер не найден!", show_alert=True)
                    close_db(conn)
                    return
                
                status, pid, main_file = row
                server_path = get_server_folder(user_id, server_id)
                zip_path = os.path.join(server_path, "project.zip")

                if status == "отключена":
                    all_py = find_all_py_files(server_path)
                    if not all_py and os.path.exists(zip_path):
                        if extract_zip_safe(zip_path, server_path):
                            all_py = find_all_py_files(server_path)
                    
                    if not all_py:
                        bot.answer_callback_query(call.id, "❌ Нет файлов! Загрузите ZIP или файлы.", show_alert=True)
                        close_db(conn)
                        return
                    
                    selected = None
                    if main_file and main_file in all_py:
                        selected = os.path.join(server_path, main_file)
                    elif "main.py" in all_py:
                        selected = os.path.join(server_path, "main.py")
                    else:
                        selected = os.path.join(server_path, all_py[0])
                    
                    log_file = os.path.join(server_path, "output.log")
                    pid, crashed, error_text = launch_server_process(selected, server_path, log_file)

                    if crashed:
                        cursor.execute("UPDATE servers SET status = 'отключена', pid = NULL WHERE id = ?", (server_id,))
                        conn.commit()
                        bot.answer_callback_query(call.id, "❌ Бот не смог запуститься!", show_alert=True)
                        bot.send_message(call.message.chat.id,
                            f"❌ Бот не смог запуститься (упал сразу после старта)!\n\n<b>Ошибка:</b>\n<code>{error_text[-800:]}</code>",
                            parse_mode="HTML")
                        close_db(conn)
                        return

                    cursor.execute("UPDATE servers SET status = 'включена', pid = ? WHERE id = ?", (pid, server_id))
                    conn.commit()
                    bot.answer_callback_query(call.id, "✅ Бот запущен и работает!", show_alert=True)
                else:
                    stop_server_process(server_id, conn)
                    bot.answer_callback_query(call.id, "✅ Сервер остановлен!", show_alert=True)
                
                call.data = f"server_panel_{server_id}"
                handle_callbacks(call)
            except Exception as e:
                print(f"❌ Ошибка управления питанием: {e}")
                bot.answer_callback_query(call.id, "❌ Ошибка!", show_alert=True)
            finally:
                close_db(conn)
            return

        # ---------- ПЕРЕЗАГРУЗКА ----------
        elif call.data.startswith("server_restart_"):
            server_id = int(call.data.split("_")[2])
            try:
                cursor.execute("SELECT status, pid, main_file FROM servers WHERE id = ? AND user_id = ?",
                              (server_id, user_id))
                row = cursor.fetchone()
                if not row:
                    bot.answer_callback_query(call.id, "❌ Сервер не найден!", show_alert=True)
                    close_db(conn)
                    return

                status, pid, main_file = row
                server_path = get_server_folder(user_id, server_id)
                zip_path = os.path.join(server_path, "project.zip")

                # Если бот уже работает - сначала останавливаем его
                if status == "включена":
                    stop_server_process(server_id, conn)

                all_py = find_all_py_files(server_path)
                if not all_py and os.path.exists(zip_path):
                    if extract_zip_safe(zip_path, server_path):
                        all_py = find_all_py_files(server_path)

                if not all_py:
                    bot.answer_callback_query(call.id, "❌ Нет файлов! Загрузите ZIP или файлы.", show_alert=True)
                    close_db(conn)
                    return

                selected = None
                if main_file and main_file in all_py:
                    selected = os.path.join(server_path, main_file)
                elif "main.py" in all_py:
                    selected = os.path.join(server_path, "main.py")
                else:
                    selected = os.path.join(server_path, all_py[0])

                log_file = os.path.join(server_path, "output.log")
                new_pid, crashed, error_text = launch_server_process(selected, server_path, log_file)

                if crashed:
                    cursor.execute("UPDATE servers SET status = 'отключена', pid = NULL WHERE id = ?", (server_id,))
                    conn.commit()
                    bot.answer_callback_query(call.id, "❌ Бот не смог перезапуститься!", show_alert=True)
                    bot.send_message(call.message.chat.id,
                        f"❌ Бот не смог запуститься после перезагрузки!\n\n<b>Ошибка:</b>\n<code>{error_text[-800:]}</code>",
                        parse_mode="HTML")
                    close_db(conn)
                    return

                cursor.execute("UPDATE servers SET status = 'включена', pid = ? WHERE id = ?", (new_pid, server_id))
                conn.commit()
                bot.answer_callback_query(call.id, "🔄 Бот перезагружен и работает!", show_alert=True)

                call.data = f"server_panel_{server_id}"
                handle_callbacks(call)
            except Exception as e:
                print(f"❌ Ошибка перезагрузки сервера: {e}")
                bot.answer_callback_query(call.id, "❌ Ошибка при перезагрузке!", show_alert=True)
            finally:
                close_db(conn)
            return

        # ---------- ФАЙЛОВЫЙ МЕНЕДЖЕР ----------
        elif call.data.startswith("server_files_"):
            server_id = int(call.data.split("_")[2])
            try:
                server_path = get_server_folder(user_id, server_id)
                
                # Получаем все файлы
                all_files = [f for f in os.listdir(server_path) if os.path.isfile(os.path.join(server_path, f)) and f != "project.zip"]
                
                # Получаем основной файл из БД
                cursor.execute("SELECT main_file FROM servers WHERE id = ? AND user_id = ?", (server_id, user_id))
                row = cursor.fetchone()
                main_file = row[0] if row else None
                
                files_count = len(all_files)
                
                # Формируем сообщение
                if files_count == 0:
                    text = f"""<b>📁 Файлы сервера #{server_id}</b>

<i>❌ Пока у вас нету никаких файлов!</i>

<i>Загрузите ZIP архив или отдельные файлы через кнопки ниже.</i>"""
                else:
                    files_list = ""
                    py_files = []
                    other_files = []
                    
                    for f in all_files:
                        if f.endswith('.py'):
                            py_files.append(f)
                        else:
                            other_files.append(f)
                    
                    if py_files:
                        files_list += "<b>🐍 Python файлы:</b>\n"
                        for f in py_files:
                            is_main = " ⭐" if f == main_file else ""
                            files_list += f"  • <code>{f}</code>{is_main}\n"
                        files_list += "\n"
                    
                    if other_files:
                        files_list += "<b>📄 Остальные файлы:</b>\n"
                        for f in other_files:
                            files_list += f"  • <code>{f}</code>\n"
                        files_list += "\n"
                    
                    main_info = f"<b>🎯 Основной файл:</b> <code>{main_file if main_file else 'Не выбран'}</code>"
                    
                    text = f"""<b>📁 Файлы сервера #{server_id}</b>

<i>📊 Всего файлов:</i> <code>{files_count}</code>

{files_list}
{main_info}

<i>Управляй файлами через кнопки ниже 👇</i>"""
                
                markup = files_keyboard(server_id, all_files)
                bot.edit_message_text(text, call.message.chat.id, call.message.message_id, 
                                    parse_mode="HTML", reply_markup=markup)
            except Exception as e:
                print(f"❌ Ошибка файлового менеджера: {e}")
            finally:
                close_db(conn)
            return

        # ---------- ОСТАЛЬНЫЕ ОБРАБОТЧИКИ ----------
        elif call.data.startswith("server_file_action_"):
            parts = call.data.split("_")
            server_id = int(parts[3])
            filename = "_".join(parts[4:])
            server_path = get_server_folder(user_id, server_id)
            file_path = os.path.join(server_path, filename)
            
            if not os.path.exists(file_path):
                bot.answer_callback_query(call.id, "❌ Файл не найден!")
                close_db(conn)
                return
            
            text = f"""<b>📄 Файл: {filename}</b>

<i>Выберите действие с файлом:</i>"""
            
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton("📥 Скачать", callback_data=f"server_download_{server_id}_{filename}"),
                types.InlineKeyboardButton("🗑 Удалить", callback_data=f"server_delete_file_{server_id}_{filename}"),
                types.InlineKeyboardButton("⬅️ Назад", callback_data=f"server_files_{server_id}")
            )
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, 
                                parse_mode="HTML", reply_markup=markup)
            close_db(conn)
            return

        # ---------- СКАЧИВАНИЕ ФАЙЛА ----------
        elif call.data.startswith("server_download_"):
            parts = call.data.split("_")
            server_id = int(parts[2])
            filename = "_".join(parts[3:])
            server_path = get_server_folder(user_id, server_id)
            file_path = os.path.join(server_path, filename)
            
            if os.path.exists(file_path):
                with open(file_path, "rb") as f:
                    bot.send_document(call.message.chat.id, f, caption=f"📄 {filename}")
            else:
                bot.answer_callback_query(call.id, "❌ Файл не найден")
            close_db(conn)
            return

        # ---------- УДАЛЕНИЕ ФАЙЛА ----------
        elif call.data.startswith("server_delete_file_"):
            parts = call.data.split("_")
            server_id = int(parts[3])
            filename = "_".join(parts[4:])
            server_path = get_server_folder(user_id, server_id)
            file_path = os.path.join(server_path, filename)
            
            if os.path.exists(file_path):
                os.remove(file_path)
                bot.answer_callback_query(call.id, f"✅ Файл {filename} удалён", show_alert=True)
            else:
                bot.answer_callback_query(call.id, "❌ Файл не найден", show_alert=True)
            
            call.data = f"server_files_{server_id}"
            handle_callbacks(call)
            close_db(conn)
            return

        # ---------- ЗАГРУЗКА ФАЙЛА ----------
        elif call.data.startswith("server_upload_file_"):
            server_id = int(call.data.split("_")[3])
            msg = bot.send_message(call.message.chat.id, "📤 Отправьте файл (не ZIP).")
            bot.register_next_step_handler(msg, lambda m: process_file_upload(m, server_id))
            close_db(conn)
            return

        # ---------- ЗАГРУЗКА ZIP ----------
        elif call.data.startswith("server_upload_zip_"):
            server_id = int(call.data.split("_")[3])
            msg = bot.send_message(call.message.chat.id, "📦 Отправьте ZIP-архив (макс. 20MB).")
            bot.register_next_step_handler(msg, lambda m: process_zip_upload(m, server_id))
            close_db(conn)
            return

        # ---------- ВЫБОР ОСНОВНОГО ФАЙЛА ----------
        elif call.data.startswith("server_select_main_"):
            parts = call.data.split("_")
            server_id = int(parts[3])
            
            server_path = get_server_folder(user_id, server_id)
            files = find_all_py_files(server_path)
            
            if not files:
                bot.answer_callback_query(call.id, "❌ Нет .py файлов на сервере!", show_alert=True)
                close_db(conn)
                return
            
            cursor.execute("SELECT main_file FROM servers WHERE id = ? AND user_id = ?", (server_id, user_id))
            row = cursor.fetchone()
            current_main = row[0] if row else None
            
            if current_main:
                text = f"""<b>🎯 Выбор основного файла</b>

<i>Текущий основной файл:</i> <code>{current_main}</code>

<i>Выберите новый файл для запуска:</i>"""
            else:
                text = f"""<b>🎯 Выбор основного файла</b>

<i>Основной файл не выбран!</i>

<i>Выберите файл для запуска сервера:</i>"""
            
            markup = types.InlineKeyboardMarkup(row_width=1)
            
            for f in files:
                if f == current_main:
                    markup.add(types.InlineKeyboardButton(f"⭐ {f} (основной)", callback_data=f"server_set_main_{server_id}_{f}"))
                else:
                    markup.add(types.InlineKeyboardButton(f"📄 {f}", callback_data=f"server_set_main_{server_id}_{f}"))
            
            markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data=f"server_files_{server_id}"))
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=markup)
            close_db(conn)
            return

        # ---------- УСТАНОВКА ОСНОВНОГО ФАЙЛА ----------
        elif call.data.startswith("server_set_main_"):
            parts = call.data.split("_")
            server_id = int(parts[3])
            main_file = "_".join(parts[4:])
            
            cursor.execute("UPDATE servers SET main_file = ? WHERE id = ? AND user_id = ?", (main_file, server_id, user_id))
            conn.commit()
            
            bot.answer_callback_query(call.id, f"✅ Основной файл: {main_file}", show_alert=True)
            
            call.data = f"server_files_{server_id}"
            handle_callbacks(call)
            close_db(conn)
            return

        # ---------- ЛОГИ ----------
        elif call.data.startswith("server_logs_"):
            server_id = int(call.data.split("_")[2])
            server_path = get_server_folder(user_id, server_id)
            log_file = os.path.join(server_path, "output.log")
            
            if os.path.exists(log_file):
                with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()[-50:]
                logs = "\n".join(lines) if lines else "Логи пусты"
            else:
                logs = "Лог-файл отсутствует. Запустите бота."
            
            text = f"📑 Логи сервера #{server_id}:\n\n{logs[-3000:]}"
            markup = types.InlineKeyboardMarkup()
            markup.add(
                types.InlineKeyboardButton("🔄 Обновить", callback_data=f"server_logs_{server_id}"),
                types.InlineKeyboardButton("⬅️ Назад", callback_data=f"server_panel_{server_id}")
            )
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)
            close_db(conn)
            return

        # ---------- БИБЛИОТЕКИ ----------
        elif call.data.startswith("server_libs_"):
            server_id = int(call.data.split("_")[2])

            cursor.execute("SELECT main_file FROM servers WHERE id = ? AND user_id = ?", (server_id, user_id))
            row = cursor.fetchone()
            if not row:
                bot.answer_callback_query(call.id, "❌ Сервер не найден", show_alert=True)
                close_db(conn)
                return
            main_file = row[0]

            server_path = get_server_folder(user_id, server_id)
            ensure_server_requirements(server_path, main_file)
            lines = read_requirements(server_path)

            installed_count = sum(1 for name, _ in POPULAR_LIBRARIES if is_lib_installed(lines, name))

            text = f"""📦 <b>Библиотеки сервера #{server_id}</b>

✅ Установленные отмечены галочкой
Нажмите на библиотеку для установки/удаления

Автоустановлено {installed_count} популярных библиотек!"""

            markup = types.InlineKeyboardMarkup(row_width=1)
            for name, _ in POPULAR_LIBRARIES:
                mark = "✅" if is_lib_installed(lines, name) else "⬜"
                markup.add(types.InlineKeyboardButton(f"{mark} {name}", callback_data=f"libtoggle_{server_id}_{name}"))
            markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data=f"server_panel_{server_id}"))

            bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                                   parse_mode="HTML", reply_markup=markup)
            close_db(conn)
            return

        # ---------- ПЕРЕКЛЮЧЕНИЕ БИБЛИОТЕКИ (УСТАНОВКА/УДАЛЕНИЕ) ----------
        elif call.data.startswith("libtoggle_"):
            parts = call.data.split("_", 2)
            server_id = int(parts[1])
            lib_name = parts[2]

            cursor.execute("SELECT main_file FROM servers WHERE id = ? AND user_id = ?", (server_id, user_id))
            row = cursor.fetchone()
            if not row:
                bot.answer_callback_query(call.id, "❌ Сервер не найден", show_alert=True)
                close_db(conn)
                return
            main_file = row[0]

            server_path = get_server_folder(user_id, server_id)
            ensure_server_requirements(server_path, main_file)
            lines = read_requirements(server_path)

            if is_lib_installed(lines, lib_name):
                # ---- удаление библиотеки из requirements.txt проекта ----
                lines = [l for l in lines if _pkg_base_name(l).lower() != lib_name.lower()]
                write_requirements(server_path, lines)
                result_text = f"➖ {lib_name} удалена из проекта"
            else:
                # pyTelegramBotAPI и aiogram — взаимоисключающие Telegram-фреймворки:
                # при выборе одного автоматически убираем второй
                if lib_name in TELEGRAM_FRAMEWORK_LIBS:
                    other = (TELEGRAM_FRAMEWORK_LIBS - {lib_name}).pop()
                    lines = [l for l in lines if _pkg_base_name(l).lower() != other.lower()]

                lines.append(lib_name)
                write_requirements(server_path, lines)

                ok, _log = pip_install_package(lib_name)
                result_text = f"✅ {lib_name} установлена" if ok else f"❌ Ошибка установки {lib_name}"

            bot.answer_callback_query(call.id, result_text)

            # обновляем панель библиотек
            call.data = f"server_libs_{server_id}"
            handle_callbacks(call)
            close_db(conn)
            return

        # ---------- .env МЕНЕДЖЕР ----------
        elif call.data.startswith("server_env_"):
            server_id = int(call.data.split("_")[2])
            server_path = get_server_folder(user_id, server_id)
            env_path = os.path.join(server_path, ".env")
            
            if not os.path.exists(env_path):
                with open(env_path, "w") as f:
                    f.write("# Ваши переменные окружения\n")
            
            with open(env_path, "r") as f:
                content = f.read()
            
            text = f"📄 Содержимое .env:\n\n{content[:2000]}"
            markup = types.InlineKeyboardMarkup()
            markup.add(
                types.InlineKeyboardButton("✏️ Редактировать", callback_data=f"server_env_edit_{server_id}"),
                types.InlineKeyboardButton("⬅️ Назад", callback_data=f"server_panel_{server_id}")
            )
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)
            close_db(conn)
            return

        # ---------- РЕДАКТИРОВАНИЕ .env ----------
        elif call.data.startswith("server_env_edit_"):
            server_id = int(call.data.split("_")[3])
            msg = bot.send_message(call.message.chat.id, "✏️ Отправьте новое содержимое .env (текст).")
            bot.register_next_step_handler(msg, lambda m: save_env_file(m, server_id))
            close_db(conn)
            return

        # ---------- ПРОДЛЕНИЕ ----------
        elif call.data.startswith("server_renew_"):
            server_id = int(call.data.split("_")[2])
            try:
                cursor.execute("SELECT tariff, paid_till, status FROM servers WHERE id = ? AND user_id = ?", 
                              (server_id, user_id))
                row = cursor.fetchone()
                if not row:
                    bot.answer_callback_query(call.id, "❌ Сервер не найден", show_alert=True)
                    close_db(conn)
                    return
                
                tariff = row[0]
                paid_till_str = row[1]
                status = row[2]
                
                prices = {"Старт": 50, "Стандарт": 120, "Про": 300}
                price = prices.get(tariff, 50)
                
                cursor.execute("SELECT balance, ref_balance FROM users WHERE user_id = ?", (user_id,))
                bal, ref_bal = cursor.fetchone()
                bal = bal or 0
                ref_bal = ref_bal or 0
                total_balance = bal + ref_bal
                
                days_left = 0
                if paid_till_str:
                    try:
                        paid_till = datetime.strptime(paid_till_str, "%Y-%m-%d %H:%M:%S")
                        now = datetime.now()
                        days_left = (paid_till - now).days
                        if days_left < 0:
                            days_left = 0
                    except:
                        days_left = 0
                
                tariff_emoji = {"Старт": "🚀", "Стандарт": "⚙️", "Про": "💎"}
                emoji = tariff_emoji.get(tariff, "📦")
                status_text = "🟢 Активен" if status == "включена" else "🔴 Остановлен"
                
                text = f"""<b>{emoji} Продление сервера #{server_id}</b>

<i>📦 Тариф:</i> <code>{tariff}</code>
<i>💰 Стоимость:</i> <code>{price} ⭐/мес</code>
<i>⏰ Осталось дней:</i> <code>{days_left}</code>
<i>🟢 Статус:</i> <code>{status_text}</code>

<i>После продления сервер будет работать ещё 30 дней.</i>

<b>💳 Ваш баланс:</b> <code>{total_balance} ⭐</code>"""
                
                markup = types.InlineKeyboardMarkup(row_width=2)
                markup.add(
                    types.InlineKeyboardButton(f"✅ Продлить за {price} ⭐", callback_data=f"do_renew_{server_id}"),
                    types.InlineKeyboardButton("⬅️ Назад", callback_data=f"server_panel_{server_id}")
                )
                bot.edit_message_text(text, call.message.chat.id, call.message.message_id, 
                                    parse_mode="HTML", reply_markup=markup)
            except Exception as e:
                print(f"❌ Ошибка продления: {e}")
            finally:
                close_db(conn)
            return

        # ---------- ВЫПОЛНЕНИЕ ПРОДЛЕНИЯ ----------
        elif call.data.startswith("do_renew_"):
            server_id = int(call.data.split("_")[2])
            try:
                cursor.execute("SELECT tariff, paid_till FROM servers WHERE id = ? AND user_id = ?", 
                              (server_id, user_id))
                row = cursor.fetchone()
                if not row:
                    bot.answer_callback_query(call.id, "❌ Сервер не найден", show_alert=True)
                    close_db(conn)
                    return
                
                tariff = row[0]
                prices = {"Старт": 50, "Стандарт": 120, "Про": 300}
                price = prices.get(tariff, 50)
                
                cursor.execute("SELECT balance, ref_balance FROM users WHERE user_id = ?", (user_id,))
                bal, ref_bal = cursor.fetchone()
                bal = bal or 0
                ref_bal = ref_bal or 0
                total_balance = bal + ref_bal
                
                if total_balance < price:
                    bot.answer_callback_query(call.id, f"❌ Не хватает {price} ⭐! Пополните баланс.", show_alert=True)
                    close_db(conn)
                    return
                
                if ref_bal >= price:
                    cursor.execute("UPDATE users SET ref_balance = ref_balance - ? WHERE user_id = ?", (price, user_id))
                else:
                    remaining = price - ref_bal
                    cursor.execute("UPDATE users SET ref_balance = 0, balance = balance - ? WHERE user_id = ?", (remaining, user_id))
                
                current_paid_till = row[1]
                if current_paid_till:
                    try:
                        old_date = datetime.strptime(current_paid_till, "%Y-%m-%d %H:%M:%S")
                        if old_date > datetime.now():
                            new_date = (old_date + timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
                        else:
                            new_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
                    except:
                        new_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
                else:
                    new_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
                
                cursor.execute("UPDATE servers SET paid_till = ? WHERE id = ?", (new_date, server_id))
                conn.commit()
                
                bot.answer_callback_query(call.id, f"✅ Сервер #{server_id} продлён на 30 дней!", show_alert=True)
                call.data = f"server_panel_{server_id}"
                handle_callbacks(call)
            except Exception as e:
                print(f"❌ Ошибка выполнения продления: {e}")
            finally:
                close_db(conn)
            return

        # ---------- АВТОПРОДЛЕНИЕ ----------
        elif call.data.startswith("server_autorenew_"):
            server_id = int(call.data.split("_")[2])
            try:
                cursor.execute("SELECT auto_renew FROM servers WHERE id = ? AND user_id = ?", (server_id, user_id))
                row = cursor.fetchone()
                if not row:
                    close_db(conn)
                    return
                
                current = row[0] if row[0] else 0
                new_val = 0 if current else 1
                cursor.execute("UPDATE servers SET auto_renew = ? WHERE id = ?", (new_val, server_id))
                conn.commit()
                
                status = "включено" if new_val else "отключено"
                bot.answer_callback_query(call.id, f"🔄 Автопродление {status}", show_alert=True)
                call.data = f"server_panel_{server_id}"
                handle_callbacks(call)
            except Exception as e:
                print(f"❌ Ошибка автопродления: {e}")
            finally:
                close_db(conn)
            return

        # ---------- УДАЛЕНИЕ СЕРВЕРА ----------
        elif call.data.startswith("server_delete_"):
            server_id = int(call.data.split("_")[2])
            markup = types.InlineKeyboardMarkup()
            markup.add(
                types.InlineKeyboardButton("🔴 ДА, УДАЛИТЬ", callback_data=f"server_confirm_delete_{server_id}"),
                types.InlineKeyboardButton("🟢 НЕТ", callback_data=f"server_panel_{server_id}")
            )
            bot.edit_message_text(f"⚠️ Удалить сервер #{server_id}?", 
                                call.message.chat.id, call.message.message_id, 
                                reply_markup=markup)
            close_db(conn)
            return

        # ---------- ПОДТВЕРЖДЕНИЕ УДАЛЕНИЯ ----------
        elif call.data.startswith("server_confirm_delete_"):
            server_id = int(call.data.split("_")[3])
            msg = bot.send_message(call.message.chat.id, f"Введите ID сервера ({server_id}) для окончательного удаления:")
            bot.register_next_step_handler(msg, lambda m: finalize_delete(m, server_id))
            close_db(conn)
            return

        # ---------- ПРОМОКОДЫ ----------
        elif call.data.startswith("delete_promo_"):
            promo_name = call.data.replace("delete_promo_", "")
            markup = types.InlineKeyboardMarkup()
            markup.add(
                types.InlineKeyboardButton("🔴 ДА, УДАЛИТЬ", callback_data=f"confirm_delete_promo_{promo_name}"),
                types.InlineKeyboardButton("🟢 НЕТ", callback_data="main_menu")
            )
            bot.edit_message_text(f"⚠️ Вы уверены, что хотите удалить промокод <b>{promo_name}</b>?", 
                                call.message.chat.id, call.message.message_id, 
                                parse_mode="HTML", reply_markup=markup)
            close_db(conn)
            return

        elif call.data.startswith("confirm_delete_promo_"):
            promo_name = call.data.replace("confirm_delete_promo_", "")
            try:
                conn_promo = get_db()
                cursor_promo = conn_promo.cursor()
                cursor_promo.execute("DELETE FROM promocodes WHERE code = ?", (promo_name,))
                conn_promo.commit()
                close_db(conn_promo)
                
                bot.answer_callback_query(call.id, f"✅ Промокод {promo_name} удалён!", show_alert=True)
                bot.edit_message_text(f"🗑 Промокод <b>{promo_name}</b> успешно удалён!", 
                                    call.message.chat.id, call.message.message_id, 
                                    parse_mode="HTML", reply_markup=main_menu_keyboard(user_id))
            except Exception as e:
                print(f"❌ Ошибка удаления промокода: {e}")
            close_db(conn)
            return

        # ---------- АДМИН-ПАНЕЛЬ (кнопка) ----------
        elif call.data == "admin_panel":
            if user_id != ADMIN_ID:
                bot.answer_callback_query(call.id, "❌ У вас нет прав для этого раздела!", show_alert=True)
                close_db(conn)
                return
            text = "<b>👑 Админ-панель</b>\n\n<i>Выберите действие:</i>"
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                                parse_mode="HTML", reply_markup=admin_panel_keyboard())
            close_db(conn)
            return

        # ---------- АДМИН: ПОСМОТРЕТЬ СЕРВЕР (кнопка = /getserver) ----------
        elif call.data == "admin_getserver":
            if user_id != ADMIN_ID:
                bot.answer_callback_query(call.id, "❌ У вас нет прав для этого раздела!", show_alert=True)
                close_db(conn)
                return
            close_db(conn)
            msg = bot.send_message(call.message.chat.id, "🔍 Введите ID сервера (без #):\n\n<i>Пример: 1</i>", parse_mode="HTML")
            bot.register_next_step_handler(msg, process_getserver)
            return

        # ---------- АДМИН: СОЗДАТЬ ПРОМОКОД (кнопка = /createpromo) ----------
        elif call.data == "admin_createpromo":
            if user_id != ADMIN_ID:
                bot.answer_callback_query(call.id, "❌ У вас нет прав для этого раздела!", show_alert=True)
                close_db(conn)
                return
            close_db(conn)
            msg = bot.send_message(call.message.chat.id, "📝 Введите название промокода (должно начинаться с #):\n\n<i>Пример: #подарок</i>", parse_mode="HTML")
            bot.register_next_step_handler(msg, process_promo_name)
            return

        # ---------- АДМИН: ВЫДАТЬ БАЛАНС (кнопка = /givetg) ----------
        elif call.data == "admin_givetg":
            if user_id != ADMIN_ID:
                bot.answer_callback_query(call.id, "❌ У вас нет прав для этого раздела!", show_alert=True)
                close_db(conn)
                return
            close_db(conn)
            msg = bot.send_message(call.message.chat.id,
                                    "💰 Введите ID пользователя и сумму звёзд через пробел:\n\n<i>Формат: user_id сумма_звезд</i>\n<i>Пример: 123456789 50</i>",
                                    parse_mode="HTML")
            bot.register_next_step_handler(msg, process_givetg)
            return

        # ---------- АДМИН: СПИСОК ПОЛЬЗОВАТЕЛЕЙ (кнопка) ----------
        elif call.data == "admin_users":
            if user_id != ADMIN_ID:
                bot.answer_callback_query(call.id, "❌ У вас нет прав для этого раздела!", show_alert=True)
                close_db(conn)
                return
            try:
                cursor.execute("SELECT user_id, balance FROM users ORDER BY user_id")
                all_users = cursor.fetchall()
                close_db(conn)

                lines = [f"<b>👥 Пользователей всего {len(all_users)}:</b>\n"]
                for row in all_users:
                    uid = row[0]
                    ubalance = row[1] if row[1] is not None else 0
                    try:
                        chat = bot.get_chat(uid)
                        uname = f"@{chat.username}" if chat.username else (chat.first_name or "Без имени")
                    except:
                        uname = "Неизвестно"
                    lines.append(f"{uname} - <code>{uid}</code> — 💰 {ubalance} ⭐")

                text = "\n".join(lines)
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("🗑 Обнулить все балансы", callback_data="admin_resetbalances_confirm"))
                markup.add(types.InlineKeyboardButton("⬅️ Админ-панель", callback_data="admin_panel"))
                bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                                    parse_mode="HTML", reply_markup=markup)
            except Exception as e:
                print(f"❌ Ошибка получения списка пользователей: {e}")
                bot.answer_callback_query(call.id, "❌ Ошибка получения списка!", show_alert=True)
                close_db(conn)
            return

        # ---------- АДМИН: ОБНУЛИТЬ ВСЕ БАЛАНСЫ (подтверждение) ----------
        elif call.data == "admin_resetbalances_confirm":
            if user_id != ADMIN_ID:
                bot.answer_callback_query(call.id, "❌ У вас нет прав для этого раздела!", show_alert=True)
                close_db(conn)
                return
            close_db(conn)
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton("✅ Да, обнулить", callback_data="admin_resetbalances_do"),
                types.InlineKeyboardButton("❌ Отмена", callback_data="admin_users")
            )
            bot.edit_message_text(
                "⚠️ <b>Вы уверены?</b>\n\nЭто действие обнулит баланс АБСОЛЮТНО ВСЕХ пользователей до 0 ⭐.\nЭто необратимо!",
                call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=markup)
            return

        elif call.data == "admin_resetbalances_do":
            if user_id != ADMIN_ID:
                bot.answer_callback_query(call.id, "❌ У вас нет прав для этого раздела!", show_alert=True)
                close_db(conn)
                return
            try:
                cursor.execute("UPDATE users SET balance = 0")
                conn.commit()
                close_db(conn)
                bot.answer_callback_query(call.id, "✅ Все балансы обнулены!")
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("⬅️ Админ-панель", callback_data="admin_panel"))
                bot.edit_message_text("✅ Баланс всех пользователей обнулён до 0 ⭐.",
                                    call.message.chat.id, call.message.message_id, reply_markup=markup)
            except Exception as e:
                print(f"❌ Ошибка обнуления балансов: {e}")
                bot.answer_callback_query(call.id, "❌ Ошибка!", show_alert=True)
                close_db(conn)
            return

        # ---------- АДМИН: ВСЕ СЕРВЕРА ----------
        elif call.data == "admin_allservers":
            if user_id != ADMIN_ID:
                bot.answer_callback_query(call.id, "❌ У вас нет прав для этого раздела!", show_alert=True)
                close_db(conn)
                return
            try:
                cursor.execute("""SELECT s.id, s.server_name, s.tariff, s.status, s.user_id, u.balance
                                   FROM servers s LEFT JOIN users u ON s.user_id = u.user_id
                                   ORDER BY s.id""")
                all_servers = cursor.fetchall()
                close_db(conn)

                if not all_servers:
                    text = "🖥 <b>Серверов нет.</b>\n\nПока никто не создал ни одного сервера."
                else:
                    lines = [f"<b>🖥 Всего серверов: {len(all_servers)}</b>\n"]
                    for srow in all_servers:
                        sid, sname, tariff, status, owner_id, owner_balance = srow
                        owner_balance = owner_balance if owner_balance is not None else 0
                        try:
                            chat = bot.get_chat(owner_id)
                            uname = f"@{chat.username}" if chat.username else (chat.first_name or "Без имени")
                        except:
                            uname = "Неизвестно"
                        status_icon = "🟢" if status == "включена" else "🔴"
                        lines.append(
                            f"🖥 <b>#{sid} {sname}</b>\n"
                            f"👤 Создал: {uname} (<code>{owner_id}</code>)\n"
                            f"💰 Баланс владельца: {owner_balance} ⭐\n"
                            f"📦 Тариф: {tariff}\n"
                            f"{status_icon} Статус: {status}\n"
                        )
                    text = "\n".join(lines)

                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("⬅️ Админ-панель", callback_data="admin_panel"))

                # Telegram ограничивает сообщение 4096 символами — режем на части, если серверов много
                if len(text) <= 4000:
                    bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                                        parse_mode="HTML", reply_markup=markup)
                else:
                    bot.delete_message(call.message.chat.id, call.message.message_id)
                    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
                    for i, chunk in enumerate(chunks):
                        if i == len(chunks) - 1:
                            bot.send_message(call.message.chat.id, chunk, parse_mode="HTML", reply_markup=markup)
                        else:
                            bot.send_message(call.message.chat.id, chunk, parse_mode="HTML")
            except Exception as e:
                print(f"❌ Ошибка получения списка серверов: {e}")
                bot.answer_callback_query(call.id, "❌ Ошибка получения списка!", show_alert=True)
                close_db(conn)
            return

        # ---------- ПРОВЕРКА ПОДПИСКИ (кнопка «✅ Подтвердить») ----------
        elif call.data == "check_subscription":
            close_db(conn)
            if is_user_subscribed_all(user_id):
                first_name = call.from_user.first_name
                try:
                    bot.delete_message(call.message.chat.id, call.message.message_id)
                except:
                    pass
                bot.answer_callback_query(call.id, "✅ Спасибо за подписку!")
                send_welcome_menu(call.message.chat.id, user_id, first_name)
            else:
                text = """❌ <b>Вы подписались не на все каналы!</b>

Пожалуйста, выполните все условия и повторно нажмите кнопку «✅ Подтвердить» ниже:"""
                bot.answer_callback_query(call.id, "❌ Вы подписались не на все каналы!", show_alert=True)
                try:
                    bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                                        parse_mode="HTML", reply_markup=force_sub_keyboard())
                except:
                    pass
            return

        # ---------- АДМИН: НАСТРОЙКИ ОБЯЗАТЕЛЬНОЙ ПОДПИСКИ ----------
        elif call.data == "admin_forcesub":
            if user_id != ADMIN_ID:
                bot.answer_callback_query(call.id, "❌ У вас нет прав для этого раздела!", show_alert=True)
                close_db(conn)
                return
            close_db(conn)
            bot.edit_message_text(force_sub_admin_text(), call.message.chat.id, call.message.message_id,
                                parse_mode="HTML", reply_markup=force_sub_admin_keyboard())
            return

        elif call.data == "admin_forcesub_toggle":
            if user_id != ADMIN_ID:
                bot.answer_callback_query(call.id, "❌ У вас нет прав для этого раздела!", show_alert=True)
                close_db(conn)
                return
            close_db(conn)
            set_force_sub_enabled(not get_force_sub_enabled())
            bot.answer_callback_query(call.id, "✅ Обновлено!")
            bot.edit_message_text(force_sub_admin_text(), call.message.chat.id, call.message.message_id,
                                parse_mode="HTML", reply_markup=force_sub_admin_keyboard())
            return

        elif call.data == "admin_forcesub_add":
            if user_id != ADMIN_ID:
                bot.answer_callback_query(call.id, "❌ У вас нет прав для этого раздела!", show_alert=True)
                close_db(conn)
                return
            close_db(conn)
            msg = bot.send_message(call.message.chat.id,
                "📢 Канал қосу (Шарт 1/3):\n\n"
                "Каналдың ID-ін (мысалы: -100123456789) немесе Юзернеймін (мысалы: @channel_username) жіберіңіз:\n\n"
                "<i>(Бот бұл каналда міндетті түрде Әкімші болуы тиіс)</i>", parse_mode="HTML")
            bot.register_next_step_handler(msg, process_forcesub_step1)
            return

        elif call.data.startswith("admin_forcesub_del_"):
            if user_id != ADMIN_ID:
                bot.answer_callback_query(call.id, "❌ У вас нет прав для этого раздела!", show_alert=True)
                close_db(conn)
                return
            close_db(conn)
            try:
                ch_id = int(call.data.replace("admin_forcesub_del_", ""))
                delete_required_channel(ch_id)
                bot.answer_callback_query(call.id, "🗑️ Канал өшірілді!")
            except:
                bot.answer_callback_query(call.id, "❌ Ошибка!", show_alert=True)
            bot.edit_message_text(force_sub_admin_text(), call.message.chat.id, call.message.message_id,
                                parse_mode="HTML", reply_markup=force_sub_admin_keyboard())
            return

        else:
            close_db(conn)
            try:
                bot.answer_callback_query(call.id)
            except:
                pass

    except Exception as e:
        print(f"❌ Ошибка в handle_callbacks: {e}")
        try:
            bot.answer_callback_query(call.id, "❌ Произошла ошибка!", show_alert=True)
        except:
            pass

# ========== АДМИН-КОМАНДЫ ==========
@bot.message_handler(commands=['getserver'])
def getserver_command(message):
    """Команда для получения информации о сервере (только админ)"""
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "❌ У вас нет прав для использования этой команды.")
        return
    
    msg = bot.send_message(message.chat.id, "🔍 Введите ID сервера (без #):\n\n<i>Пример: 1</i>", parse_mode="HTML")
    bot.register_next_step_handler(msg, process_getserver)

def process_getserver(message):
    """Обработчик ввода ID сервера для админа"""
    try:
        admin_id = message.from_user.id
        server_id = message.text.strip()
        
        if not server_id.isdigit():
            bot.send_message(message.chat.id, "❌ Введите число! Пример: 1")
            return
        
        server_id = int(server_id)
        
        conn = get_db()
        if not conn:
            bot.send_message(message.chat.id, "❌ Ошибка подключения к БД!")
            return
        
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, user_id, server_name, tariff, status, pid, main_file, files, 
                   created_at, paid_till, auto_renew 
            FROM servers WHERE id = ?
        ''', (server_id,))
        server = cursor.fetchone()
        
        if not server:
            bot.send_message(message.chat.id, f"❌ Сервер #{server_id} не найден!")
            close_db(conn)
            return
        
        sid, uid, name, tariff, status, pid, main_file, files, created_at, paid_till, auto_renew = server
        
        cursor.execute("SELECT balance, ref_balance FROM users WHERE user_id = ?", (uid,))
        user_row = cursor.fetchone()
        user_balance = user_row[0] if user_row else 0
        user_ref_balance = user_row[1] if user_row else 0
        total_balance = user_balance + user_ref_balance
        
        try:
            chat = bot.get_chat(uid)
            owner_username = chat.username if chat.username else "Нет username"
            owner_name = chat.first_name if chat.first_name else "Unknown"
        except:
            owner_username = "Неизвестно"
            owner_name = "Неизвестно"
        
        days_left = 0
        paid_till_str = ""
        if paid_till:
            try:
                paid_till_date = datetime.strptime(paid_till, "%Y-%m-%d %H:%M:%S")
                days_left = (paid_till_date - datetime.now()).days
                if days_left < 0:
                    days_left = 0
                paid_till_str = paid_till_date.strftime("%d.%m.%Y %H:%M")
            except:
                days_left = 0
                paid_till_str = "Не указано"
        
        status_icon = "🟢" if status == "включена" else "🔴"
        status_text = "Работает" if status == "включена" else "Остановлен"
        
        bot_status = "❌ Бот отключен"
        if status == "включена" and pid:
            try:
                proc = psutil.Process(pid)
                if proc.is_running():
                    cpu = proc.cpu_percent(interval=0.1)
                    mem = proc.memory_info().rss / (1024 * 1024)
                    if cpu < 10:
                        bot_status = "🟢 Низкая нагрузка"
                    elif cpu < 30:
                        bot_status = "🟡 Средняя нагрузка"
                    else:
                        bot_status = "🔴 Высокая нагрузка"
            except:
                bot_status = "❌ Бот упал"
        
        tariff_emoji = {"Старт": "🚀", "Стандарт": "⚙️", "Про": "💎"}
        emoji = tariff_emoji.get(tariff, "📦")
        
        last_run = "Неизвестно"
        log_file = os.path.join(get_server_folder(uid, sid), "output.log")
        if os.path.exists(log_file):
            try:
                with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
                    if lines:
                        for line in reversed(lines):
                            if "Запуск" in line or "=== Запуск ===" in line or "Восстановлен" in line:
                                last_run = line.strip()[:50]
                                break
            except:
                pass
        
        text = f"""<b>📊 Информация о сервере #{sid}</b>

<b>🆔 ID:</b> <code>{sid}</code>
<b>📌 Название:</b> <code>{name}</code>
<b>👤 Владелец:</b> @{owner_username} (<code>{uid}</code>)
<b>💳 Баланс владельца:</b> <code>{total_balance} ⭐</code>

<b>{emoji} Тариф:</b> <code>{tariff}</code>
<b>{status_icon} Статус:</b> <code>{status_text}</code>
<b>🤖 Состояние бота:</b> <code>{bot_status}</code>
<b>📅 Оплачен до:</b> <code>{paid_till_str}</code>
<b>⏰ Осталось дней:</b> <code>{days_left}</code>

<b>📂 Главный файл:</b> <code>{main_file if main_file else 'Не выбран'}</code>
<b>📦 Файлов:</b> <code>{len(files.split(',')) if files else 0}</code>
<b>🔄 Автопродление:</b> <code>{'✅ Включено' if auto_renew else '❌ Отключено'}</code>
<b>📅 Создан:</b> <code>{created_at[:16] if created_at else 'Неизвестно'}</code>
<b>🔄 Последний запуск:</b> <code>{last_run}</code>"""
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("⏰ Продлить срок", callback_data=f"admin_renew_{sid}"),
            types.InlineKeyboardButton("🗑 Удалить сервер", callback_data=f"admin_delete_{sid}"),
            types.InlineKeyboardButton("🔌 Запустить/Отключить", callback_data=f"admin_power_{sid}"),
            types.InlineKeyboardButton("💰 Изменить баланс", callback_data=f"admin_balance_{sid}"),
            types.InlineKeyboardButton("📦 Изменить тариф", callback_data=f"admin_tariff_{sid}"),
            types.InlineKeyboardButton("📁 Файл алу", callback_data=f"admin_getfiles_{sid}"),
            types.InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")
        )
        
        bot.send_message(message.chat.id, text, parse_mode="HTML", reply_markup=markup)
        close_db(conn)
        
    except Exception as e:
        print(f"❌ Ошибка в getserver: {e}")
        bot.send_message(message.chat.id, f"❌ Ошибка: {e}")

@bot.message_handler(commands=['givetg'])
def give_money(message):
    """Команда для выдачи звезд (только админ)"""
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "❌ Нет прав.")
        return
    try:
        parts = message.text.split()
        if len(parts) < 3:
            bot.reply_to(message, "Формат: /givetg user_id сумма_звезд")
            return
        target_id = int(parts[1])
        amount = int(parts[2])
        init_user(target_id)
        
        conn = get_db()
        if conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, target_id))
            conn.commit()
            close_db(conn)
            bot.reply_to(message, f"✅ Выдано {amount} ⭐ пользователю {target_id}")
            bot.send_message(target_id, f"💰 Баланс пополнен на {amount} ⭐!")
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {e}")

def process_givetg(message):
    """Обработчик ввода user_id и суммы для выдачи баланса (кнопка админ-панели)"""
    if message.from_user.id != ADMIN_ID:
        return
    try:
        parts = message.text.split()
        if len(parts) < 2:
            bot.reply_to(message, "❌ Формат: user_id сумма_звезд\n\nПример: 123456789 50")
            return
        target_id = int(parts[0])
        amount = int(parts[1])
        init_user(target_id)

        conn = get_db()
        if conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, target_id))
            conn.commit()
            close_db(conn)
            bot.reply_to(message, f"✅ Выдано {amount} ⭐ пользователю {target_id}")
            try:
                bot.send_message(target_id, f"💰 Баланс пополнен на {amount} ⭐!")
            except:
                pass
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {e}\n\nФормат: user_id сумма_звезд")

@bot.message_handler(commands=['createpromo'])
def create_promo_command(message):
    """Команда для создания промокода (только админ)"""
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "❌ У вас нет прав для создания промокодов.")
        return
    
    msg = bot.send_message(message.chat.id, "📝 Введите название промокода (должно начинаться с #):\n\n<i>Пример: #подарок</i>", parse_mode="HTML")
    bot.register_next_step_handler(msg, process_promo_name)

def process_promo_name(message):
    """Обработчик ввода названия промокода"""
    user_id = message.from_user.id
    promo_name = message.text.strip()
    
    if not promo_name.startswith('#'):
        bot.send_message(message.chat.id, "❌ Промокод должен начинаться с #!\n\nПопробуйте снова: /createpromo")
        return
    
    if len(promo_name) < 2:
        bot.send_message(message.chat.id, "❌ Промокод слишком короткий!\n\nПопробуйте снова: /createpromo")
        return
    
    conn = get_db()
    if not conn:
        bot.send_message(message.chat.id, "❌ Ошибка подключения к БД!")
        return
    
    cursor = conn.cursor()
    cursor.execute("SELECT code FROM promocodes WHERE code = ?", (promo_name,))
    existing = cursor.fetchone()
    close_db(conn)
    
    if existing:
        show_promo_info(message, promo_name)
        return
    
    conn = get_db()
    if conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO promocodes (code, created_by) VALUES (?, ?)", (promo_name, user_id))
        conn.commit()
        close_db(conn)
    
    msg = bot.send_message(message.chat.id, f"✅ Промокод <b>{promo_name}</b> создан!\n\nТеперь укажите количество активаций (от 1 до 1000):", parse_mode="HTML")
    bot.register_next_step_handler(msg, process_promo_activations, promo_name)

def process_promo_activations(message, promo_name):
    """Обработчик ввода количества активаций"""
    try:
        activations = int(message.text.strip())
        if activations < 1 or activations > 1000:
            bot.send_message(message.chat.id, "❌ Количество активаций должно быть от 1 до 1000!\n\nПопробуйте снова: /createpromo")
            return
    except:
        bot.send_message(message.chat.id, "❌ Введите целое число от 1 до 1000!\n\nПопробуйте снова: /createpromo")
        return
    
    conn = get_db()
    if conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE promocodes SET max_activations = ? WHERE code = ?", (activations, promo_name))
        conn.commit()
        close_db(conn)
    
    msg = bot.send_message(message.chat.id, f"✅ Количество активаций: <b>{activations}</b>\n\nТеперь укажите бонус в ⭐ (сколько звёзд получит активировавший):", parse_mode="HTML")
    bot.register_next_step_handler(msg, process_promo_bonus, promo_name, activations)

def process_promo_bonus(message, promo_name, activations):
    """Обработчик ввода бонуса промокода"""
    try:
        bonus = int(message.text.strip())
        if bonus < 1:
            bot.send_message(message.chat.id, "❌ Бонус должен быть минимум 1 ⭐!\n\nПопробуйте снова: /createpromo")
            return
    except:
        bot.send_message(message.chat.id, "❌ Введите целое число!\n\nПопробуйте снова: /createpromo")
        return
    
    conn = get_db()
    if conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE promocodes SET bonus = ? WHERE code = ?", (bonus, promo_name))
        conn.commit()
        close_db(conn)
    
    text = f"""<b>✅ Промокод успешно создан!</b>

<b>📌 Промокод:</b> <code>{promo_name}</code>
<b>🎁 Бонус:</b> <code>{bonus} ⭐</code>
<b>🔄 Активаций:</b> <code>{activations}</code>

<i>Промокод готов к использованию!</i>"""
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🗑 Удалить промокод", callback_data=f"delete_promo_{promo_name}"),
        types.InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")
    )
    
    bot.send_message(message.chat.id, text, parse_mode="HTML", reply_markup=markup)

def show_promo_info(message, promo_name):
    """Показывает информацию о существующем промокоде"""
    conn = get_db()
    if not conn:
        bot.send_message(message.chat.id, "❌ Ошибка подключения к БД!")
        return
    
    cursor = conn.cursor()
    cursor.execute("SELECT bonus, max_activations, used_count FROM promocodes WHERE code = ?", (promo_name,))
    row = cursor.fetchone()
    close_db(conn)
    
    if not row:
        bot.send_message(message.chat.id, "❌ Промокод не найден!")
        return
    
    bonus, max_act, used = row
    left = max_act - used
    
    text = f"""<b>ℹ️ Информация о промокоде</b>

<b>📌 Промокод:</b> <code>{promo_name}</code>
<b>🎁 Бонус:</b> <code>{bonus} ⭐</code>
<b>🔄 Активировали:</b> <code>{used} человек</code>
<b>📊 Осталось:</b> <code>{left} активаций</code>
<b>📦 Всего:</b> <code>{max_act}</code>"""
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🗑 Удалить промокод", callback_data=f"delete_promo_{promo_name}"),
        types.InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")
    )
    
    bot.send_message(message.chat.id, text, parse_mode="HTML", reply_markup=markup)

# ========== ОБЯЗАТЕЛЬНАЯ ПОДПИСКА: МАСТЕР ДОБАВЛЕНИЯ КАНАЛА ==========
def process_forcesub_step1(message):
    """Шаг 1/3: получаем ID или username канала"""
    if message.from_user.id != ADMIN_ID:
        return
    chat_id = message.text.strip()
    if not chat_id:
        bot.send_message(message.chat.id, "❌ Пустое значение! Попробуйте снова: откройте 📢 Обязательные подписки → ➕ Канал қосу")
        return

    msg = bot.send_message(message.chat.id,
        "📢 Канал сілтемесі (Шарт 2/3):\n\n"
        "Каналға өту сілтемесін жіберіңіз (мысалы: https://t.me/invite_link немесе https://t.me/channel_username):")
    bot.register_next_step_handler(msg, process_forcesub_step2, chat_id)

def normalize_invite_link(raw_link):
    """
    Приводит ссылку канала к формату, который Telegram примет как URL-кнопку.
    Частая причина 'канал не отображается пользователю' — ссылка без http(s)://,
    из-за чего Telegram отклоняет ВСЁ сообщение с кнопками (BUTTON_URL_INVALID),
    и гейт не показывается вообще.
    """
    link = raw_link.strip()
    if link.startswith(("http://", "https://", "tg://")):
        return link
    if link.startswith("@"):
        return f"https://t.me/{link[1:]}"
    if link.startswith("t.me/"):
        return f"https://{link}"
    if link.startswith("+"):
        return f"https://t.me/{link}"
    # похоже на голый username/инвайт-хэш без ссылки
    return f"https://t.me/{link}"

def process_forcesub_step2(message, chat_id):
    """Шаг 2/3: получаем ссылку-приглашение канала"""
    if message.from_user.id != ADMIN_ID:
        return
    raw = message.text.strip()
    if not raw:
        bot.send_message(message.chat.id, "❌ Пустое значение! Попробуйте снова: 📢 Обязательные подписки → ➕ Канал қосу")
        return

    invite_link = normalize_invite_link(raw)

    msg = bot.send_message(message.chat.id,
        "📢 Батырма атауы (Шарт 3/3):\n\n"
        "Пайдаланушыға батырмада көрсетілетін мәтінді жазыңыз (мысалы: 📢 Жазылу / Подписаться 1):")
    bot.register_next_step_handler(msg, process_forcesub_step3, chat_id, invite_link)

def process_forcesub_step3(message, chat_id, invite_link):
    """Шаг 3/3: получаем текст кнопки и сохраняем канал"""
    if message.from_user.id != ADMIN_ID:
        return
    button_text = message.text.strip()
    if not button_text:
        bot.send_message(message.chat.id, "❌ Пустое значение! Попробуйте снова: 📢 Обязательные подписки → ➕ Канал қосу")
        return

    add_required_channel(chat_id, invite_link, button_text)

    # Сразу проверяем, что бот реально имеет доступ к каналу и является в нём админом —
    # без этого проверка подписки пользователей работать не будет.
    warning = ""
    try:
        bot_id = bot.get_me().id
        member = bot.get_chat_member(chat_id, bot_id)
        if member.status not in ("administrator", "creator"):
            warning = "\n\n⚠️ <b>ЕСКЕРТУ:</b> бот бұл каналда әкімші (администратор) емес! Тексеру жұмыс істемейді, каналда ботты Әкімші етіп қосыңыз."
    except Exception as e:
        warning = f"\n\n⚠️ <b>ЕСКЕРТУ:</b> ботты каналда таба алмадым (ID қате не бот каналда мүлде жоқ):\n<code>{e}</code>\n\nID/username-ды тексеріп, ботты каналда Әкімші етіп қосыңыз."

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="admin_forcesub"))
    bot.send_message(message.chat.id, f"✅ Канал сәтті қосылды!{warning}", parse_mode="HTML", reply_markup=markup)

# ========== АДМИН-ОБРАБОТЧИКИ ==========
@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_renew_"))
def admin_renew_callback(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ Нет прав!", show_alert=True)
        return
    
    server_id = int(call.data.split("_")[2])
    msg = bot.send_message(call.message.chat.id, f"📅 Введите количество дней для продления сервера #{server_id}:\n\n<i>Пример: 30</i>", parse_mode="HTML")
    bot.register_next_step_handler(msg, process_admin_renew, server_id)

def process_admin_renew(message, server_id):
    try:
        if message.from_user.id != ADMIN_ID:
            return
        
        days = int(message.text.strip())
        if days < 1:
            bot.send_message(message.chat.id, "❌ Минимум 1 день!")
            return
        
        conn = get_db()
        if not conn:
            bot.send_message(message.chat.id, "❌ Ошибка подключения к БД!")
            return
        
        cursor = conn.cursor()
        cursor.execute("SELECT paid_till FROM servers WHERE id = ?", (server_id,))
        row = cursor.fetchone()
        
        if row and row[0]:
            try:
                old_date = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
                if old_date > datetime.now():
                    new_date = old_date + timedelta(days=days)
                else:
                    new_date = datetime.now() + timedelta(days=days)
            except:
                new_date = datetime.now() + timedelta(days=days)
        else:
            new_date = datetime.now() + timedelta(days=days)
        
        cursor.execute("UPDATE servers SET paid_till = ? WHERE id = ?", (new_date.strftime("%Y-%m-%d %H:%M:%S"), server_id))
        conn.commit()
        close_db(conn)
        
        bot.send_message(message.chat.id, f"✅ Сервер #{server_id} продлён на {days} дней до {new_date.strftime('%d.%m.%Y %H:%M')}!")
        
    except ValueError:
        bot.send_message(message.chat.id, "❌ Введите число!")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_delete_"))
def admin_delete_callback(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ Нет прав!", show_alert=True)
        return
    
    server_id = int(call.data.split("_")[2])
    
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("🔴 ДА, УДАЛИТЬ", callback_data=f"admin_confirm_delete_{server_id}"),
        types.InlineKeyboardButton("🟢 НЕТ", callback_data=f"admin_cancel_{server_id}")
    )
    bot.edit_message_text(f"⚠️ Вы уверены, что хотите удалить сервер #{server_id}?", 
                          call.message.chat.id, call.message.message_id, 
                          parse_mode="HTML", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_confirm_delete_"))
def admin_confirm_delete_callback(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ Нет прав!", show_alert=True)
        return
    
    server_id = int(call.data.split("_")[3])
    
    conn = get_db()
    if not conn:
        bot.edit_message_text(f"❌ Ошибка подключения к БД!", call.message.chat.id, call.message.message_id)
        return
    
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM servers WHERE id = ?", (server_id,))
    row = cursor.fetchone()
    
    if not row:
        bot.edit_message_text(f"❌ Сервер #{server_id} не найден!", call.message.chat.id, call.message.message_id)
        close_db(conn)
        return
    
    user_id = row[0]
    
    stop_server_process(server_id, conn)
    
    server_path = get_server_folder(user_id, server_id)
    if os.path.exists(server_path):
        shutil.rmtree(server_path)
    
    cursor.execute("DELETE FROM servers WHERE id = ?", (server_id,))
    conn.commit()
    close_db(conn)
    
    bot.edit_message_text(f"✅ Сервер #{server_id} успешно удалён!", 
                          call.message.chat.id, call.message.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_cancel_")
                             and not call.data.startswith(("admin_cancel_power_", "admin_cancel_tariff_")))
def admin_cancel_callback(call):
    if call.from_user.id != ADMIN_ID:
        return
    server_id = int(call.data.split("_")[2])
    bot.edit_message_text(f"✅ Отмена удаления сервера #{server_id}", 
                          call.message.chat.id, call.message.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_power_"))
def admin_power_callback(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ Нет прав!", show_alert=True)
        return
    
    server_id = int(call.data.split("_")[2])
    
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("🔴 Да, запустить/отключить", callback_data=f"admin_confirm_power_{server_id}"),
        types.InlineKeyboardButton("🟢 Нет, отмена", callback_data=f"admin_cancel_power_{server_id}")
    )
    bot.edit_message_text(f"⚠️ Вы уверены, что хотите запустить/отключить сервер #{server_id}?", 
                          call.message.chat.id, call.message.message_id, 
                          parse_mode="HTML", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_confirm_power_"))
def admin_confirm_power_callback(call):
    if call.from_user.id != ADMIN_ID:
        return
    
    server_id = int(call.data.split("_")[3])
    
    conn = get_db()
    if not conn:
        bot.edit_message_text(f"❌ Ошибка подключения к БД!", call.message.chat.id, call.message.message_id)
        return
    
    cursor = conn.cursor()
    cursor.execute("SELECT status, user_id, pid, main_file FROM servers WHERE id = ?", (server_id,))
    row = cursor.fetchone()
    
    if not row:
        bot.edit_message_text(f"❌ Сервер #{server_id} не найден!", call.message.chat.id, call.message.message_id)
        close_db(conn)
        return
    
    status, user_id, pid, main_file = row
    server_path = get_server_folder(user_id, server_id)
    
    if status == "отключена":
        all_py = find_all_py_files(server_path)
        if not all_py:
            bot.edit_message_text(f"❌ Нет файлов для запуска сервера #{server_id}!", call.message.chat.id, call.message.message_id)
            close_db(conn)
            return
        
        selected = None
        if main_file and main_file in all_py:
            selected = os.path.join(server_path, main_file)
        elif "main.py" in all_py:
            selected = os.path.join(server_path, "main.py")
        else:
            selected = os.path.join(server_path, all_py[0])
        
        log_file = os.path.join(server_path, "output.log")
        bot.edit_message_text(f"⏳ Запускаю сервер #{server_id}...", call.message.chat.id, call.message.message_id)
        pid, crashed, error_text = launch_server_process(selected, server_path, log_file)

        if crashed:
            cursor.execute("UPDATE servers SET status = 'отключена', pid = NULL WHERE id = ?", (server_id,))
            conn.commit()
            close_db(conn)
            bot.edit_message_text(
                f"❌ Сервер #{server_id} упал сразу после старта!\n\n<b>Ошибка:</b>\n<code>{error_text[-800:]}</code>",
                call.message.chat.id, call.message.message_id, parse_mode="HTML")
            return

        cursor.execute("UPDATE servers SET status = 'включена', pid = ? WHERE id = ?", (pid, server_id))
        conn.commit()
        bot.edit_message_text(f"✅ Сервер #{server_id} запущен!", call.message.chat.id, call.message.message_id)
    else:
        stop_server_process(server_id, conn)
        bot.edit_message_text(f"✅ Сервер #{server_id} остановлен!", call.message.chat.id, call.message.message_id)
    
    close_db(conn)

@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_cancel_power_"))
def admin_cancel_power_callback(call):
    if call.from_user.id != ADMIN_ID:
        return
    server_id = int(call.data.split("_")[3])
    bot.edit_message_text(f"✅ Отмена действия для сервера #{server_id}", 
                          call.message.chat.id, call.message.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_balance_"))
def admin_balance_callback(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ Нет прав!", show_alert=True)
        return
    
    server_id = int(call.data.split("_")[2])
    msg = bot.send_message(call.message.chat.id, f"💰 Введите сумму для изменения баланса владельца сервера #{server_id}:\n\n<i>Пример: +100 или -50</i>", parse_mode="HTML")
    bot.register_next_step_handler(msg, process_admin_balance, server_id)

def process_admin_balance(message, server_id):
    try:
        if message.from_user.id != ADMIN_ID:
            return
        
        amount = int(message.text.strip())
        
        conn = get_db()
        if not conn:
            bot.send_message(message.chat.id, "❌ Ошибка подключения к БД!")
            return
        
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM servers WHERE id = ?", (server_id,))
        row = cursor.fetchone()
        
        if not row:
            bot.send_message(message.chat.id, f"❌ Сервер #{server_id} не найден!")
            close_db(conn)
            return
        
        user_id = row[0]
        cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        conn.commit()
        close_db(conn)
        
        sign = "+" if amount >= 0 else ""
        bot.send_message(message.chat.id, f"✅ Баланс владельца сервера #{server_id} изменён на {sign}{amount} ⭐!")
        
    except ValueError:
        bot.send_message(message.chat.id, "❌ Введите число!")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_getfiles_"))
def admin_getfiles_callback(call):
    """Отправляет админу все файлы сервера одним архивом. Если файлов нет — сообщает об этом."""
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ Нет прав!", show_alert=True)
        return

    try:
        server_id = int(call.data.split("_")[2])
    except (IndexError, ValueError):
        bot.answer_callback_query(call.id, "❌ Ошибка!", show_alert=True)
        return

    conn = get_db()
    if not conn:
        bot.answer_callback_query(call.id, "❌ Ошибка подключения к БД!", show_alert=True)
        return

    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM servers WHERE id = ?", (server_id,))
    row = cursor.fetchone()
    close_db(conn)

    if not row:
        bot.answer_callback_query(call.id, f"❌ Сервер #{server_id} не найден!", show_alert=True)
        return

    owner_id = row[0]
    server_path = get_server_folder(owner_id, server_id)

    all_files = []
    for root, dirs, files in os.walk(server_path):
        for f in files:
            if f in ("output.log",):
                continue
            all_files.append(os.path.join(root, f))

    if not all_files:
        bot.answer_callback_query(call.id, "📁 Файлов нет", show_alert=True)
        bot.send_message(call.message.chat.id, f"📁 У сервера #{server_id} файлов нет.")
        return

    bot.answer_callback_query(call.id, "📦 Собираю файлы...")

    zip_name = f"server_{server_id}_files.zip"
    zip_path = os.path.join(BASE_DIR, zip_name)
    try:
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for fp in all_files:
                arcname = os.path.relpath(fp, server_path)
                zf.write(fp, arcname)

        with open(zip_path, 'rb') as doc:
            bot.send_document(call.message.chat.id, doc, visible_file_name=zip_name,
                               caption=f"📁 Все файлы сервера #{server_id} ({len(all_files)} шт.)")
    except Exception as e:
        print(f"❌ Ошибка сборки файлов сервера #{server_id}: {e}")
        bot.send_message(call.message.chat.id, "❌ Ошибка при получении файлов!")
    finally:
        if os.path.exists(zip_path):
            try:
                os.remove(zip_path)
            except:
                pass

@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_tariff_"))
def admin_tariff_callback(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ Нет прав!", show_alert=True)
        return
    
    server_id = int(call.data.split("_")[2])
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("🚀 Старт", callback_data=f"admin_set_tariff_{server_id}_Старт"),
        types.InlineKeyboardButton("⚙️ Стандарт", callback_data=f"admin_set_tariff_{server_id}_Стандарт"),
        types.InlineKeyboardButton("💎 Премиум", callback_data=f"admin_set_tariff_{server_id}_Про"),
        types.InlineKeyboardButton("⬅️ Назад", callback_data=f"admin_cancel_tariff_{server_id}")
    )
    bot.edit_message_text(f"📦 Выберите новый тариф для сервера #{server_id}:", 
                          call.message.chat.id, call.message.message_id, 
                          parse_mode="HTML", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_set_tariff_"))
def admin_set_tariff_callback(call):
    if call.from_user.id != ADMIN_ID:
        return
    
    parts = call.data.split("_")
    server_id = int(parts[3])
    tariff = parts[4]
    
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("🔴 Да, изменить", callback_data=f"admin_confirm_tariff_{server_id}_{tariff}"),
        types.InlineKeyboardButton("🟢 Нет, отмена", callback_data=f"admin_cancel_tariff_{server_id}")
    )
    bot.edit_message_text(f"⚠️ Вы уверены, что хотите изменить тариф сервера #{server_id} на <b>{tariff}</b>?", 
                          call.message.chat.id, call.message.message_id, 
                          parse_mode="HTML", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_confirm_tariff_"))
def admin_confirm_tariff_callback(call):
    if call.from_user.id != ADMIN_ID:
        return
    
    parts = call.data.split("_")
    server_id = int(parts[3])
    tariff = parts[4]
    
    conn = get_db()
    if conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE servers SET tariff = ? WHERE id = ?", (tariff, server_id))
        conn.commit()
        close_db(conn)
    
    bot.edit_message_text(f"✅ Тариф сервера #{server_id} изменён на <b>{tariff}</b>!", 
                          call.message.chat.id, call.message.message_id, 
                          parse_mode="HTML")

@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_cancel_tariff_"))
def admin_cancel_tariff_callback(call):
    if call.from_user.id != ADMIN_ID:
        return
    server_id = int(call.data.split("_")[3])
    bot.edit_message_text(f"✅ Отмена изменения тарифа сервера #{server_id}", 
                          call.message.chat.id, call.message.message_id)

# ========== ОБРАБОТЧИКИ ПЛАТЕЖЕЙ ==========
@bot.pre_checkout_query_handler(func=lambda query: True)
def handle_pre_checkout_query(pre_checkout_query):
    try:
        bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)
    except Exception as e:
        print(f"❌ Ошибка pre_checkout: {e}")
        bot.answer_pre_checkout_query(pre_checkout_query.id, ok=False, error_message="Произошла ошибка")

@bot.message_handler(content_types=['successful_payment'])
def handle_successful_payment(message):
    try:
        user_id = message.from_user.id
        first_name = message.from_user.first_name
        payment = message.successful_payment
        amount = payment.total_amount
        
        conn = get_db()
        if not conn:
            bot.send_message(user_id, "❌ Ошибка подключения к БД!")
            return
        
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        
        cursor.execute("SELECT referrer_id FROM users WHERE user_id = ?", (user_id,))
        ref_id = cursor.fetchone()
        if ref_id and ref_id[0]:
            ref_bonus = int(amount * 0.1)
            if ref_bonus > 0:
                cursor.execute("UPDATE users SET ref_balance = ref_balance + ? WHERE user_id = ?", (ref_bonus, ref_id[0]))
                try:
                    bot.send_message(ref_id[0], f"🎉 Вы получили {ref_bonus} ⭐ (10% от покупки вашего реферала)!")
                except:
                    pass
        
        conn.commit()
        close_db(conn)
        
        bot.send_message(user_id, f"✅ Оплата прошла успешно! Ваш баланс пополнен на {amount} ⭐.")
        
        text = f"""<b>🤖 Привет, {first_name}!</b>

<i>Добро пожаловать в панель управления хостингом JakeHost.</i>

<b>⚡️ Здесь ты можешь запустить нового бота или управлять своими текущими проектами.</b>

👇 <i>Выбирай нужное действие на панели ниже:</i>"""
        bot.send_message(user_id, text, parse_mode="HTML", reply_markup=main_menu_keyboard(user_id))
        
    except Exception as e:
        print(f"❌ Ошибка обработки платежа: {e}")
        bot.send_message(user_id, f"❌ Ошибка при обработке платежа: {e}")

# ========== ОБРАБОТЧИКИ ЗАГРУЗКИ ==========
def process_deposit(message):
    try:
        user_id = message.from_user.id
        amount = int(message.text.strip())
        if amount < 1:
            bot.send_message(message.chat.id, "❌ Сумма должна быть не меньше 1 ⭐.")
            return
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        btn_pay = types.InlineKeyboardButton(f"💰 Заплатить {amount}", callback_data=f"pay_{amount}")
        btn_back = types.InlineKeyboardButton("⬅️ Назад в главное меню", callback_data="main_menu")
        markup.add(btn_pay, btn_back)
        
        text = f"""<b>⭐ Пополнение баланса JakeHost</b>

<b>Пополнение баланса на {amount} звезд</b>

Сумма: {amount} ⭐

Нажмите кнопку ниже для оплаты через Telegram Stars"""

        bot.send_message(message.chat.id, text, parse_mode="HTML", reply_markup=markup)
        
    except ValueError:
        bot.send_message(message.chat.id, "❌ Введите целое число.")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка: {e}")

def process_file_upload(message, server_id):
    try:
        user_id = message.from_user.id
        if not message.document:
            bot.send_message(message.chat.id, "❌ Отправьте файл как документ.")
            return
        
        if message.document.file_size > 20 * 1024 * 1024:
            bot.send_message(message.chat.id, "❌ Файл больше 20MB.")
            return
        
        file_info = bot.get_file(message.document.file_id)
        downloaded = bot.download_file(file_info.file_path)
        server_path = get_server_folder(user_id, server_id)
        
        filename = os.path.basename(message.document.file_name)
        safe_filename = "".join(c for c in filename if c.isalnum() or c in "._-")
        file_path = os.path.join(server_path, safe_filename)
        
        with open(file_path, "wb") as f:
            f.write(downloaded)
        
        bot.send_message(message.chat.id, f"✅ Файл {safe_filename} загружен.")
        fake_call = type('', (), {'data': f"server_files_{server_id}", 'message': message, 'from_user': message.from_user})()
        handle_callbacks(fake_call)
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка: {e}")

def process_zip_upload(message, server_id):
    try:
        user_id = message.from_user.id
        
        if not message.document:
            bot.send_message(message.chat.id, "❌ Отправьте ZIP файл.")
            return
        
        if not message.document.file_name.lower().endswith('.zip'):
            bot.send_message(message.chat.id, "❌ Файл должен быть ZIP архивом.")
            return
        
        if message.document.file_size > 20 * 1024 * 1024:
            bot.send_message(message.chat.id, "❌ ZIP больше 20MB.")
            return
        
        bot.send_message(message.chat.id, "📦 Скачиваю ZIP...")
        
        file_info = bot.get_file(message.document.file_id)
        downloaded = bot.download_file(file_info.file_path)
        
        server_path = os.path.join(USERS_DIR, f"user_{user_id}", f"server_{server_id}")
        os.makedirs(server_path, exist_ok=True)
        
        zip_path = os.path.join(server_path, "project.zip")
        with open(zip_path, "wb") as f:
            f.write(downloaded)
        
        bot.send_message(message.chat.id, "📦 Распаковываю ZIP...")
        
        with zipfile.ZipFile(zip_path, 'r') as zf:
            all_names = zf.namelist()
            
            common_folder = None
            for name in all_names:
                if '/' in name:
                    parts = name.split('/')
                    if len(parts) >= 2 and not parts[0].endswith('.py') and not parts[0].endswith('/'):
                        if common_folder is None:
                            common_folder = parts[0]
                        elif common_folder != parts[0]:
                            common_folder = None
                            break
                else:
                    common_folder = None
                    break
            
            if common_folder:
                zf.extractall(server_path)
                extracted_folder = os.path.join(server_path, common_folder)
                if os.path.exists(extracted_folder):
                    for item in os.listdir(extracted_folder):
                        item_path = os.path.join(extracted_folder, item)
                        shutil.move(item_path, server_path)
                    os.rmdir(extracted_folder)
                    bot.send_message(message.chat.id, f"✅ Файлы перемещены из папки '{common_folder}' в корень!")
            else:
                zf.extractall(server_path)
        
        os.remove(zip_path)
        
        extracted = [f for f in os.listdir(server_path) if os.path.isfile(os.path.join(server_path, f))]
        
        if extracted:
            bot.send_message(message.chat.id, f"✅ ZIP распакован! Файлов: {len(extracted)}")
            fake_call = type('', (), {'data': f"server_files_{server_id}", 'message': message, 'from_user': message.from_user})()
            handle_callbacks(fake_call)
        else:
            bot.send_message(message.chat.id, "❌ ZIP пустой или не содержит файлов!")
        
        conn = get_db()
        if conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE servers SET files = ? WHERE id = ?", (message.document.file_name, server_id))
            conn.commit()
            close_db(conn)
            
    except zipfile.BadZipFile:
        bot.send_message(message.chat.id, "❌ Файл повреждён или не является ZIP архивом!")
        if os.path.exists(zip_path):
            os.remove(zip_path)
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        bot.send_message(message.chat.id, f"❌ Ошибка: {e}")

def save_env_file(message, server_id):
    try:
        user_id = message.from_user.id
        new_content = message.text
        server_path = get_server_folder(user_id, server_id)
        env_path = os.path.join(server_path, ".env")
        with open(env_path, "w", encoding="utf-8") as f:
            f.write(new_content)
        bot.send_message(message.chat.id, "✅ .env сохранён.")
        fake_call = type('', (), {'data': f"server_env_{server_id}", 'message': message, 'from_user': message.from_user})()
        handle_callbacks(fake_call)
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка: {e}")

def finalize_delete(message, server_id):
    try:
        user_id = message.from_user.id
        if int(message.text.strip()) != server_id:
            bot.send_message(message.chat.id, "❌ ID не совпадает. Удаление отменено.")
            return
    except:
        bot.send_message(message.chat.id, "❌ Неверный ID. Отмена.")
        return
    
    conn = get_db()
    if not conn:
        bot.send_message(message.chat.id, "❌ Ошибка подключения к БД!")
        return
    
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM servers WHERE id = ?", (server_id,))
    row = cursor.fetchone()
    if not row or row[0] != user_id:
        bot.send_message(message.chat.id, "❌ Сервер не принадлежит вам.")
        close_db(conn)
        return
    
    stop_server_process(server_id, conn)
    server_path = get_server_folder(user_id, server_id)
    if os.path.exists(server_path):
        shutil.rmtree(server_path)
    
    cursor.execute("DELETE FROM servers WHERE id = ?", (server_id,))
    conn.commit()
    close_db(conn)
    
    bot.send_message(message.chat.id, f"✅ Сервер #{server_id} удалён.")
    fake_call = type('', (), {'data': "my_servers", 'message': message, 'from_user': message.from_user})()
    handle_callbacks(fake_call)

# ========== АКТИВАЦИЯ ПРОМОКОДА ==========
def process_activate_promo(message):
    try:
        user_id = message.from_user.id
        promo_code = message.text.strip()
        
        if not promo_code.startswith('#'):
            bot.send_message(message.chat.id, "❌ Промокод должен начинаться с #!")
            return
        
        conn = get_db()
        if not conn:
            bot.send_message(message.chat.id, "❌ Ошибка подключения к БД!")
            return
        
        cursor = conn.cursor()
        
        cursor.execute("SELECT bonus, max_activations, used_count FROM promocodes WHERE code = ?", (promo_code,))
        row = cursor.fetchone()
        
        if not row:
            bot.send_message(message.chat.id, f"❌ Промокод {promo_code} не найден!")
            close_db(conn)
            return
        
        bonus, max_act, used = row
        left = max_act - used
        
        if left <= 0:
            bot.send_message(message.chat.id, f"❌ Промокод {promo_code} уже использован!")
            close_db(conn)
            return
        
        cursor.execute("SELECT * FROM promocode_activations WHERE user_id = ? AND promo_code = ?", (user_id, promo_code))
        if cursor.fetchone():
            bot.send_message(message.chat.id, f"❌ Вы уже активировали {promo_code}!")
            close_db(conn)
            return
        
        cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (bonus, user_id))
        cursor.execute("UPDATE promocodes SET used_count = used_count + 1 WHERE code = ?", (promo_code,))
        cursor.execute("INSERT INTO promocode_activations (user_id, promo_code) VALUES (?, ?)", (user_id, promo_code))
        
        conn.commit()
        close_db(conn)
        
        conn2 = get_db()
        if conn2:
            cur2 = conn2.cursor()
            cur2.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
            new_balance = cur2.fetchone()[0]
            close_db(conn2)
        else:
            new_balance = 0
        
        text = f"""<b>✅ Промокод активирован!</b>

🎫 <b>Промокод:</b> <code>{promo_code}</code>
🎁 <b>Получено:</b> <code>{bonus} ⭐</code>
💰 <b>Баланс:</b> <code>{new_balance} ⭐</code>"""
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("⬅️ Главное меню", callback_data="main_menu"))
        
        bot.send_message(message.chat.id, text, parse_mode="HTML", reply_markup=markup)
        
    except Exception as e:
        print(f"❌ Ошибка активации промокода: {e}")
        bot.send_message(message.chat.id, "❌ Ошибка при активации!")

# ========== ВОССТАНОВЛЕНИЕ ПРОЦЕССОВ ==========
def restore_user_processes():
    print("🔄 Восстановление процессов и файлов...")
    
    conn = get_db()
    if not conn:
        print("❌ Ошибка подключения к БД!")
        return
    
    cursor = conn.cursor()
    
    cursor.execute("SELECT id, user_id, pid, main_file FROM servers WHERE status = 'включена'")
    servers = cursor.fetchall()
    
    restored = 0
    restored_files = 0
    
    for server_id, user_id, old_pid, main_file in servers:
        server_path = get_server_folder(user_id, server_id)
        zip_path = os.path.join(server_path, "project.zip")
        
        all_py = find_all_py_files(server_path)
        
        if not all_py and os.path.exists(zip_path):
            print(f"  📦 Восстановление файлов сервера #{server_id} из ZIP...")
            try:
                with zipfile.ZipFile(zip_path, 'r') as zf:
                    all_names = zf.namelist()
                    common_folder = None
                    for name in all_names:
                        if '/' in name:
                            parts = name.split('/')
                            if len(parts) >= 2 and not parts[0].endswith('.py') and not parts[0].endswith('/'):
                                if common_folder is None:
                                    common_folder = parts[0]
                                elif common_folder != parts[0]:
                                    common_folder = None
                                    break
                        else:
                            common_folder = None
                            break
                    
                    if common_folder:
                        zf.extractall(server_path)
                        extracted_folder = os.path.join(server_path, common_folder)
                        if os.path.exists(extracted_folder):
                            for item in os.listdir(extracted_folder):
                                item_path = os.path.join(extracted_folder, item)
                                shutil.move(item_path, server_path)
                            os.rmdir(extracted_folder)
                    else:
                        zf.extractall(server_path)
                
                all_py = find_all_py_files(server_path)
                restored_files += 1
                print(f"  ✅ Файлы сервера #{server_id} восстановлены из ZIP")
            except Exception as e:
                print(f"  ❌ Ошибка восстановления файлов сервера #{server_id}: {e}")
        
        alive = False
        if old_pid:
            try:
                if psutil.Process(old_pid).is_running():
                    alive = True
                    print(f"  ✅ Сервер #{server_id} уже работает (PID:{old_pid})")
            except:
                pass
        
        if not alive and all_py:
            selected = None
            if main_file and main_file in all_py:
                selected = os.path.join(server_path, main_file)
            elif "main.py" in all_py:
                selected = os.path.join(server_path, "main.py")
            else:
                selected = os.path.join(server_path, all_py[0])
            
            try:
                log_file = os.path.join(server_path, "output.log")
                with open(log_file, "a", encoding="utf-8") as out:
                    out.write(f"\n--- Восстановлен после перезапуска: {datetime.now()} ---\n")
                    out.flush()
                    p = subprocess.Popen([sys.executable, "-u", selected], stdout=out, stderr=out, cwd=server_path)
                
                cursor.execute("UPDATE servers SET pid = ? WHERE id = ?", (p.pid, server_id))
                conn.commit()
                restored += 1
                print(f"  🔄 Сервер #{server_id} запущен (новый PID:{p.pid})")
            except Exception as e:
                print(f"  ❌ Ошибка запуска сервера #{server_id}: {e}")
                cursor.execute("UPDATE servers SET status = 'отключена', pid = NULL WHERE id = ?", (server_id,))
                conn.commit()
        
        elif not all_py and not os.path.exists(zip_path):
            cursor.execute("UPDATE servers SET status = 'отключена', pid = NULL WHERE id = ?", (server_id,))
            conn.commit()
            print(f"  ⚠️ Сервер #{server_id} отключён (нет файлов и ZIP)")
    
    close_db(conn)
    print(f"✅ Восстановлено процессов: {restored}")
    print(f"✅ Восстановлено файлов: {restored_files}")

# ========== ФОНОВЫЙ ПОТОК ==========
def background_renewal_checker():
    """Фоновый поток для проверки окончания срока серверов"""
    while True:
        time.sleep(86400)  # 24 часа
        try:
            conn = get_db()
            if not conn:
                continue
            
            cursor = conn.cursor()
            now = datetime.now()
            cursor.execute("SELECT id, user_id, tariff, paid_till, auto_renew FROM servers WHERE paid_till IS NOT NULL")
            servers = cursor.fetchall()
            
            for sid, uid, tariff, paid_till_str, auto in servers:
                try:
                    paid_till = datetime.strptime(paid_till_str, "%Y-%m-%d %H:%M:%S")
                    days_left = (paid_till - now).days
                    
                    if days_left in [3, 2, 1]:
                        try:
                            bot.send_message(uid, f"⚠️ Сервер #{sid} закончится через {days_left} дня.")
                        except:
                            pass
                    
                    if now > paid_till:
                        cursor.execute("UPDATE servers SET status = 'отключена', pid = NULL WHERE id = ?", (sid,))
                        conn.commit()
                        stop_server_process(sid, conn)
                        try:
                            bot.send_message(uid, f"🛑 Сервер #{sid} отключён.")
                        except:
                            pass
                        
                        if auto:
                            price = {"Старт": 50, "Стандарт": 120, "Про": 300}.get(tariff, 50)
                            cur = conn.cursor()
                            cur.execute("SELECT balance, ref_balance FROM users WHERE user_id = ?", (uid,))
                            bal, ref_bal = cur.fetchone()
                            bal, ref_bal = bal or 0, ref_bal or 0
                            total = bal + ref_bal
                            
                            if total >= price:
                                if ref_bal >= price:
                                    cur.execute("UPDATE users SET ref_balance = ref_balance - ? WHERE user_id = ?", (price, uid))
                                else:
                                    remaining = price - ref_bal
                                    cur.execute("UPDATE users SET ref_balance = 0, balance = balance - ? WHERE user_id = ?", (remaining, uid))
                                
                                new_date = (now + timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
                                cur.execute("UPDATE servers SET paid_till = ? WHERE id = ?", (new_date, sid))
                                conn.commit()
                                try:
                                    bot.send_message(uid, f"🔄 Сервер #{sid} продлён")
                                except:
                                    pass
                        
                        if (now - paid_till).days >= 5:
                            server_path = get_server_folder(uid, sid)
                            if os.path.exists(server_path):
                                shutil.rmtree(server_path)
                            cursor.execute("DELETE FROM servers WHERE id = ?", (sid,))
                            conn.commit()
                except Exception as e:
                    print(f"❌ Ошибка сервера {sid}: {e}")
            
            close_db(conn)
        except Exception as e:
            print(f"❌ Ошибка в фоновом потоке: {e}")

Thread(target=background_renewal_checker, daemon=True).start()

# ========== ЗАПУСК ==========
if __name__ == "__main__":
    init_db()
    
    try:
        bot_user = bot.get_me()
        BOT_USERNAME = bot_user.username
        print(f"✅ Бот: @{BOT_USERNAME}")
    except:
        BOT_USERNAME = None
        print("⚠️ Не удалось получить username бота")
    
    print(f"📁 Папка: {USERS_DIR}")
    print("✅ Хостинг SELVER HOSTING запущен!")
    print("🔄 Восстановление файлов и процессов...")
    
    restore_user_processes()
    
    print("🤖 Бот запущен и готов к работе!")
    bot.infinity_polling()
