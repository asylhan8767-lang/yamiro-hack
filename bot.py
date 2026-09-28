# -*- coding: utf-8 -*-
# pip install pyTelegramBotAPI Flask
import telebot, sqlite3, threading, html, os
from urllib.parse import quote
from telebot import types

# --- RENDER ТЕГІН ІСТЕУ ҮШІН КОД ---
from flask import Flask
app = Flask(__name__)
@app.route('/')
def home():
    return "YAMIRO MODS SHOP - BOT IS ALIVE!"

def run_web():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

threading.Thread(target=run_web, daemon=True).start()
# --- БІТТІ ---

TOKEN = "8826997118:AAGBeacnHGziZ5WwnIERS57" # <-- мұнда сенің токенің тұрады
ADMIN_ID = 8826944181
SHOP_NAME = "YAMIRO MODS SHOP"
DEFAULT_REF_BONUS = 10
DEFAULT_TOP_COUNT = 10

import re, inspect
from telebot.apihelper import ApiTelegramException

# ======================= PREMIUM EMOJI =======================
PREMIUM_EMOJI = True      # False қылсаңыз, барлық премиум эмодзи өшеді (қарапайым эмодзи қалады)
PREMIUM_BUTTONS = True    # False қылсаңыз, батырмалардағы премиум эмодзи өшеді
COLOR_BUTTONS = True      # False қылсаңыз, түсті батырмалар (жасыл/қызыл/көк) өшеді

PREMIUM = {
    "📂": "5800835941543186089", "👇": "5276019825922049495", "👋": "5249373522400150544",
    "📁": "5798700621242568649", "📦": "5256143060873547502", "💸": "5463046637842608206",
    "📊": "5231200819986047254", "📈": "5244837092042750681", "✅": "5377766231069722341",
    "🔑": "5280626839771971853", "🫂": "5431446050890088313", "⭐": "6100340203119971469",
    "❤": "5388790256772331442", "🌍": "5280767353922028283", "💲": "5409048419211682843",
    "💳": "5454134258580877567", "👤": "5765076907125120345", "💰": "6208619743151136863",
    "⚠": "5420323339723881652", "💵": "5456343997779831665", "🛒": "5260683661644171595",
    "🗓": "6194823951714099861", "🏆": "6266973397922616654", "🤝": "5350533479828326393",
    "👥": "6033125983572201397", "❌": "5210952531676504517",
    "🔙": "5253997076169115797", "🇰🇿": "5312522091545797979", "🇷🇺": "5339080090540079666",
    "🔗": "5249027897791910858", "📢": "5197304993920616826", "ℹ": "5447410659077661506",
    "🇬🇧": "5202196682497859879",
}
_KEYS_RX = "(" + "|".join(re.escape(k) for k in sorted(PREMIUM, key=len, reverse=True)) + ")\ufe0f?"
_RX = re.compile(_KEYS_RX)
_RX_END = re.compile(_KEYS_RX + "$")


def pe(text):
    """Мәтіндегі эмодзиді премиум (custom) эмодзиге ауыстырады."""
    if not PREMIUM_EMOJI or not text:
        return text
    return _RX.sub(lambda m: f'<tg-emoji emoji-id="{PREMIUM[m.group(1)]}">{m.group(0)}</tg-emoji>', text)


_IKB = types.InlineKeyboardButton
_SIG = inspect.signature(_IKB.__init__).parameters
_ICON_OK = "icon_custom_emoji_id" in _SIG
_STYLE_OK = "style" in _SIG

# Батырма түстері: success = жасыл, danger = қызыл, primary = көк
_STYLE_RULES = [
    ("danger", ("🔙", "❌", "🗑")),
    ("success", ("✅", "🛒", "➕", "💲")),
    ("primary", ("👤", "📜", "👥", "🌍", "ℹ", "⚙", "🏆", "💳")),
]


def _auto_style(text):
    t0 = (text or "").lstrip()
    for st, prefs in _STYLE_RULES:
        if t0.startswith(prefs):
            return st
    return None


def IKB(text, *a, style=None, **kw):
    """Батырма: түс (style) + алдындағы/соңындағы эмодзиді премиум иконка қылады."""
    extra = {}
    if COLOR_BUTTONS and _STYLE_OK:
        st = style or _auto_style(text)
        if st:
            extra["style"] = st
    label, icon = text, None
    if PREMIUM_EMOJI and PREMIUM_BUTTONS and _ICON_OK and text:
        m = _RX.match(text)
        if m and text[m.end():].strip():
            label, icon = text[m.end():].lstrip(), PREMIUM[m.group(1)]
        else:
            m = _RX_END.search(text)          # эмодзи соңында тұрса (мысалы: «Қазақша 🇰🇿»)
            if m and text[:m.start()].strip():
                label, icon = text[:m.start()].rstrip(), PREMIUM[m.group(1)]
    if icon:
        extra["icon_custom_emoji_id"] = icon
    btn = _IKB(label, *a, **extra, **kw)
    if icon or extra.get("style"):
        btn._plain = text
    return btn


def _strip_icons(mk):
    if isinstance(mk, types.InlineKeyboardMarkup):
        for row in mk.keyboard:
            for b in row:
                pl = getattr(b, "_plain", None)
                if pl:
                    b.text = pl
                    b.icon_custom_emoji_id = None
                    if hasattr(b, "style"):
                        b.style = None


def _retry_needed(e):
    s = str(e).lower()
    return any(x in s for x in ("emoji", "entit", "icon", "parse", "tag", "style", "button"))


class PBot(telebot.TeleBot):
    def _send(self, fn, a, kw, idx=None, key=None):
        a2, kw2 = list(a), dict(kw)
        if idx is not None and len(a2) > idx:
            a2[idx] = pe(a2[idx])
        if key and kw2.get(key):
            kw2[key] = pe(kw2[key])
        try:
            return fn(*a2, **kw2)
        except ApiTelegramException as e:
            if not (PREMIUM_EMOJI and _retry_needed(e)):
                raise
            _strip_icons(kw.get("reply_markup"))
            return fn(*a, **kw)

    def send_message(self, *a, **kw):
        return self._send(super().send_message, a, kw, idx=1, key="text")

    def send_photo(self, *a, **kw):
        return self._send(super().send_photo, a, kw, key="caption")

    def send_video(self, *a, **kw):
        return self._send(super().send_video, a, kw, key="caption")

    def copy_message(self, *a, **kw):
        return self._send(super().copy_message, a, kw, key="caption")

    def edit_message_text(self, *a, **kw):
        return self._send(super().edit_message_text, a, kw, idx=0, key="text")

    def edit_message_caption(self, *a, **kw):
        return self._send(super().edit_message_caption, a, kw, idx=0, key="caption")


bot = PBot(TOKEN, parse_mode="HTML")
BOT_USERNAME = bot.get_me().username

# ======================= DATABASE =======================
db = sqlite3.connect("shop.db", check_same_thread=False)
db.row_factory = sqlite3.Row
lock = threading.RLock()


def ex(sql, a=()):
    with lock:
        cur = db.execute(sql, a)
        db.commit()
        return cur.lastrowid


def qa(sql, a=()):
    with lock:
        return db.execute(sql, a).fetchall()


def q1(sql, a=()):
    with lock:
        return db.execute(sql, a).fetchone()


with lock:
    db.executescript("""
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT, name TEXT, lang TEXT,
        balance INTEGER DEFAULT 0, spent INTEGER DEFAULT 0, bought INTEGER DEFAULT 0, joined TEXT);
    CREATE TABLE IF NOT EXISTS categories(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT);
    CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY AUTOINCREMENT, cat_id INTEGER, name TEXT, price INTEGER);
    CREATE TABLE IF NOT EXISTS keys(id INTEGER PRIMARY KEY AUTOINCREMENT, product_id INTEGER, key TEXT, sold INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS purchases(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, product_id INTEGER,
        name TEXT, duration TEXT, price INTEGER, qty INTEGER, keys TEXT, date TEXT);
    CREATE TABLE IF NOT EXISTS requisites(id INTEGER PRIMARY KEY AUTOINCREMENT, country TEXT, number TEXT, holder TEXT);
    CREATE TABLE IF NOT EXISTS channels(id INTEGER PRIMARY KEY AUTOINCREMENT, chat TEXT, url TEXT, name TEXT);
    CREATE TABLE IF NOT EXISTS infobtn(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, url TEXT);
    CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT);
    CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amount INTEGER,
        status TEXT DEFAULT 'pending', date TEXT);
    CREATE TABLE IF NOT EXISTS referrals(id INTEGER PRIMARY KEY AUTOINCREMENT, inviter INTEGER, invited INTEGER UNIQUE, bonus INTEGER);
    CREATE TABLE IF NOT EXISTS pending_ref(invited INTEGER PRIMARY KEY, inviter INTEGER);
    """)
    db.commit()


def get_set(k, d=None):
    r = q1("SELECT v FROM settings WHERE k=?", (k,))
    return r["v"] if r else d


def set_set(k, v):
    ex("INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, str(v)))


def del_set(k):
    ex("DELETE FROM settings WHERE k=?", (k,))


# ======================= TEXTS =======================
LANG_TITLE = "🌍 Тілді таңдаңыз / Выберите язык / Choose a language:"

T = {
    "kk": {
        "sub_req": "📢 Ботты қолдану үшін төмендегі арналарға міндетті түрде тіркеліңіз!\n\n✅ Барлық арнаға тіркелгеннен кейін «✅ Тексеру» батырмасын басыңыз.",
        "check": "✅ Тексеру",
        "not_sub": "❌ Арналарға тіркелмегенсіз! Алдымен барлық арнаға тіркеліңіз.",
        "welcome": f"{SHOP_NAME} - ҒА ҚОШ КЕЛДІҢІЗ 👋\n\nКеректі санатты таңдаңыз 👇",
        "goods": "🛒 Тауарлар", "profile": "👤 Профиль", "ref": "👥 Рефералдар", "info": "ℹ️ Ақпарат",
        "lang": "🌍 Тіл", "admin": "⚙️ Админ панель", "back": "🔙 Артқа",
        "goods_title": "📂 Төменнен өзіңізге қажетті категорияны таңдаңыз 👇",
        "no_cats": "❌ Әзірге категориялар жоқ.",
        "cat_title": "📁 Категория: {cat}\n\nСатып алғыңыз келетін тауарды таңдаңыз:",
        "no_products": "❌ Бұл категорияда тауар жоқ.",
        "card": "📦 Тауар: {name}\n——————————————\n💸 Бағасы: {price} 〒\n📊 Қоймада бар: {stock} дана.\n📈 Сатылды: {sold} дана.",
        "buy1": "🛒 1 дана сатып алу", "buym": "🛒 Бірнешеуін сатып алу",
        "ask_qty": "Қанша дана сатып аласыз санмен жазыңыз 👇",
        "bad_qty": "❌ Тек оң сан жазыңыз.",
        "no_stock": "❌ Қоймада жеткілікті кілт жоқ.",
        "no_money": "❌ Балансыңыз жеткіліксіз! Қажет: {total} ₸\nАлдымен теңгерімді толтырыңыз.",
        "bought": "✅ Сәтті сатып алынды\n\n📦Тауар: {name}\n⏱️Мерзімі: {dur}\n💰Бағасы: {price} ₸\n🔢Дана: {qty}\n━━━━━━━━━━━━━━\nҚазіргі баланс: {bal}₸\nСіздің балансыңыздан {total}₸ шегерілді!\n━━━━━━━━━━━━━━\n🔑 Сіздің кілтіңіз:\n{keys}\n━━━━━━━━━━━━━━\nСатып алғаныңызға рахмет 🫂\nОтзыв жазып кетіңіз 👇",
        "rev_btn": "💬 Отзыв жазу",
        "rev_ask": "⭐️ Сатып алғаныңызға рақмет! Пікіріңізді қалдырып кетіңіз 👇",
        "rev_ok": "✅ Пікіріңіз қабылданды! Рақмет! ❤️",
        "profile_t": "👤 ЖЕКЕ КАБИНЕТ (ПРОФИЛЬ)\n━━━━━━━━━━━━━━━━━━━━━━\n\n🔑 ID-нөміріңіз: {id}\n👤 Логиніңіз: {login}\n\n💳 ҚАРЖЫЛЫҚ СТАТИСТИКА:\n━━━━━━━━━━━━━━━━━━━━━━\n💵 Қазіргі балансыңыз: {bal} 〒\n🛒 Сатып алынған тауарлар: {cnt} дана\n💲 Барлық жұмсалған сома: {spent} 〒\n━━━━━━━━━━━━━━━━━━━━━━",
        "hist_btn": "📜 Сатып алу тарихы", "topup_btn": "💲 Теңгерімді толтыру",
        "hist_none": "❌ Сізде әлі сатып алулар тарихы жоқ!",
        "hist_title": "📜 САТЫП АЛУ ТАРИХЫ\n\n", "back_prof": "🔙 Профильге қайту",
        "topup_country": "🌍 Қай елмен төлейсіз? Таңдаңыз 👇",
        "no_reqs": "❌ Әзірге реквизит қосылмаған. Админге жазыңыз.",
        "topup_amount": "💲 Қанша теңге толтырасыз? Тек санмен жазыңыз 👇",
        "bad_amount": "❌ Тек оң сан жазыңыз.",
        "pay_reqs": "💳 ТӨЛЕМ РЕКВИЗИТТЕРІ:\n\n💳 Номер: <code>{number}</code>\n👤 Аты-жөні: {holder}\n💰 Сомма: {amount} ₸\n\n⚠️ Төлем жасаған соң чек жіберіңіз.",
        "need_photo": "❌ Чекті фото немесе файл түрінде жіберіңіз.",
        "receipt_ok": "✅ Чек қабылданды! Тексерілуге жіберілді.",
        "pay_ok": "✅ Чек қабылданды, балансыңызға {amount}₸ толықтырылды",
        "pay_no": "❌ Чек қабылданбады.\n\n📝 Себебі: {reason}",
        "ref_t": "🤝 СЕРІКТЕСТІК (РЕФЕРАЛ) БАҒДАРЛАМАСЫ\n━━━━━━━━━━━━━━━━━━━━━━\n\nДостарыңызды ботқа шақырып, әр тіркелген досыңыз үшін +{bonus} 〒 бонус алыңыз!\n\n🔗 Сіздің реферал сілтемеңіз:\n<code>{link}</code>\n\n📊 Сіздің статистикаңыз:\n👥 Шақырылған достар: {n} адам\n💸 Табылған жалпы бонус: {earned} 〒\n━━━━━━━━━━━━━━━━━━━━━━",
        "share_btn": "👥 Достармен бөлісу", "top_btn": "🏆 Топ рефералдар",
        "share_text": "🔥 Сәлем! Мына ботта сапалы кілттер мен тауарлар бар. Тіркел:",
        "top_t": "🏆 ТОП РЕФЕРАЛДАР\n\n", "top_none": "Әзірге ешкім жоқ.", "people": "адам",
        "ref_new": "👥 Сіздің шақыру сілтемеңіз арқылы жаңа пайдаланушы тіркелді! Балансыңызға +{bonus} 〒 сыйақы берілді.",
        "info_t": "Керекті батырманы таңдаңыз:", "info_none": "❌ Ақпарат батырмалары әзірге жоқ.",
        "lang_pick": LANG_TITLE, "cancel": "❌ Бас тартылды.",
    },
    "ru": {
        "sub_req": "📢 Для использования бота обязательно подпишитесь на каналы ниже!\n\n✅ После подписки на все каналы нажмите кнопку «✅ Проверить».",
        "check": "✅ Проверить",
        "not_sub": "❌ Вы не подписались на каналы! Сначала подпишитесь на все каналы.",
        "welcome": f"ДОБРО ПОЖАЛОВАТЬ В {SHOP_NAME} 👋\n\nВыберите нужный раздел 👇",
        "goods": "🛒 Товары", "profile": "👤 Профиль", "ref": "👥 Рефералы", "info": "ℹ️ Информация",
        "lang": "🌍 Язык", "admin": "⚙️ Админ панель", "back": "🔙 Назад",
        "goods_title": "📂 Выберите нужную категорию ниже 👇",
        "no_cats": "❌ Категорий пока нет.",
        "cat_title": "📁 Категория: {cat}\n\nВыберите товар, который хотите купить:",
        "no_products": "❌ В этой категории нет товаров.",
        "card": "📦 Товар: {name}\n——————————————\n💸 Цена: {price} 〒\n📊 В наличии: {stock} шт.\n📈 Продано: {sold} шт.",
        "buy1": "🛒 Купить 1 шт.", "buym": "🛒 Купить несколько",
        "ask_qty": "Напишите числом, сколько штук хотите купить 👇",
        "bad_qty": "❌ Напишите положительное число.",
        "no_stock": "❌ На складе недостаточно ключей.",
        "no_money": "❌ Недостаточно средств! Нужно: {total} ₸\nСначала пополните баланс.",
        "bought": "✅ Успешно куплено\n\n📦Товар: {name}\n⏱️Срок: {dur}\n💰Цена: {price} ₸\n🔢Количество: {qty}\n━━━━━━━━━━━━━━\nТекущий баланс: {bal}₸\nС вашего баланса списано {total}₸!\n━━━━━━━━━━━━━━\n🔑 Ваш ключ:\n{keys}\n━━━━━━━━━━━━━━\nСпасибо за покупку 🫂\nОставьте отзыв 👇",
        "rev_btn": "💬 Написать отзыв",
        "rev_ask": "⭐️ Спасибо за покупку! Оставьте свой отзыв 👇",
        "rev_ok": "✅ Ваш отзыв принят! Спасибо! ❤️",
        "profile_t": "👤 ЛИЧНЫЙ КАБИНЕТ (ПРОФИЛЬ)\n━━━━━━━━━━━━━━━━━━━━━━\n\n🔑 Ваш ID: {id}\n👤 Ваш логин: {login}\n\n💳 ФИНАНСОВАЯ СТАТИСТИКА:\n━━━━━━━━━━━━━━━━━━━━━━\n💵 Текущий баланс: {bal} 〒\n🛒 Куплено товаров: {cnt} шт.\n💲 Всего потрачено: {spent} 〒\n━━━━━━━━━━━━━━━━━━━━━━",
        "hist_btn": "📜 История покупок", "topup_btn": "💲 Пополнить баланс",
        "hist_none": "❌ У вас пока нет истории покупок!",
        "hist_title": "📜 ИСТОРИЯ ПОКУПОК\n\n", "back_prof": "🔙 Вернуться в профиль",
        "topup_country": "🌍 Из какой страны оплата? Выберите 👇",
        "no_reqs": "❌ Реквизиты пока не добавлены. Напишите админу.",
        "topup_amount": "💲 На сколько тенге пополнить? Напишите только число 👇",
        "bad_amount": "❌ Напишите положительное число.",
        "pay_reqs": "💳 РЕКВИЗИТЫ ДЛЯ ОПЛАТЫ:\n\n💳 Номер: <code>{number}</code>\n👤 Имя: {holder}\n💰 Сумма: {amount} ₸\n\n⚠️ После оплаты отправьте чек.",
        "need_photo": "❌ Отправьте чек в виде фото или файла.",
        "receipt_ok": "✅ Чек принят! Отправлен на проверку.",
        "pay_ok": "✅ Чек принят, на ваш баланс зачислено {amount}₸",
        "pay_no": "❌ Чек отклонён.\n\n📝 Причина: {reason}",
        "ref_t": "🤝 ПАРТНЁРСКАЯ (РЕФЕРАЛЬНАЯ) ПРОГРАММА\n━━━━━━━━━━━━━━━━━━━━━━\n\nПриглашайте друзей в бота и получайте +{bonus} 〒 за каждого зарегистрированного друга!\n\n🔗 Ваша реферальная ссылка:\n<code>{link}</code>\n\n📊 Ваша статистика:\n👥 Приглашено друзей: {n} чел.\n💸 Всего заработано бонусов: {earned} 〒\n━━━━━━━━━━━━━━━━━━━━━━",
        "share_btn": "👥 Поделиться с друзьями", "top_btn": "🏆 Топ рефералов",
        "share_text": "🔥 Привет! В этом боте есть качественные ключи и товары. Заходи:",
        "top_t": "🏆 ТОП РЕФЕРАЛОВ\n\n", "top_none": "Пока никого нет.", "people": "чел.",
        "ref_new": "👥 По вашей пригласительной ссылке зарегистрировался новый пользователь! На ваш баланс начислено +{bonus} 〒 в качестве бонуса.",
        "info_t": "Выберите нужную кнопку:", "info_none": "❌ Кнопок информации пока нет.",
        "lang_pick": LANG_TITLE, "cancel": "❌ Отменено.",
    },
    "en": {
        "sub_req": "📢 To use the bot you must subscribe to the channels below!\n\n✅ After subscribing to all channels press the «✅ Check» button.",
        "check": "✅ Check",
        "not_sub": "❌ You have not subscribed to the channels! Subscribe to all channels first.",
        "welcome": f"WELCOME TO {SHOP_NAME} 👋\n\nChoose a section 👇",
        "goods": "🛒 Products", "profile": "👤 Profile", "ref": "👥 Referrals", "info": "ℹ️ Information",
        "lang": "🌍 Language", "admin": "⚙️ Admin panel", "back": "🔙 Back",
        "goods_title": "📂 Choose the category you need below 👇",
        "no_cats": "❌ No categories yet.",
        "cat_title": "📁 Category: {cat}\n\nChoose the product you want to buy:",
        "no_products": "❌ No products in this category.",
        "card": "📦 Product: {name}\n——————————————\n💸 Price: {price} 〒\n📊 In stock: {stock} pcs.\n📈 Sold: {sold} pcs.",
        "buy1": "🛒 Buy 1 pc.", "buym": "🛒 Buy several",
        "ask_qty": "Write how many pieces you want to buy (number) 👇",
        "bad_qty": "❌ Send a positive number.",
        "no_stock": "❌ Not enough keys in stock.",
        "no_money": "❌ Insufficient balance! Required: {total} ₸\nTop up your balance first.",
        "bought": "✅ Purchased successfully\n\n📦Product: {name}\n⏱️Duration: {dur}\n💰Price: {price} ₸\n🔢Quantity: {qty}\n━━━━━━━━━━━━━━\nCurrent balance: {bal}₸\n{total}₸ was deducted from your balance!\n━━━━━━━━━━━━━━\n🔑 Your key:\n{keys}\n━━━━━━━━━━━━━━\nThank you for your purchase 🫂\nPlease leave a review 👇",
        "rev_btn": "💬 Write a review",
        "rev_ask": "⭐️ Thank you for your purchase! Leave your feedback 👇",
        "rev_ok": "✅ Your review has been received! Thank you! ❤️",
        "profile_t": "👤 PERSONAL ACCOUNT (PROFILE)\n━━━━━━━━━━━━━━━━━━━━━━\n\n🔑 Your ID: {id}\n👤 Your login: {login}\n\n💳 FINANCIAL STATISTICS:\n━━━━━━━━━━━━━━━━━━━━━━\n💵 Current balance: {bal} 〒\n🛒 Purchased items: {cnt} pcs.\n💲 Total spent: {spent} 〒\n━━━━━━━━━━━━━━━━━━━━━━",
        "hist_btn": "📜 Purchase history", "topup_btn": "💲 Top up balance",
        "hist_none": "❌ You have no purchase history yet!",
        "hist_title": "📜 PURCHASE HISTORY\n\n", "back_prof": "🔙 Back to profile",
        "topup_country": "🌍 Which country are you paying from? Choose 👇",
        "no_reqs": "❌ No payment details added yet. Contact the admin.",
        "topup_amount": "💲 How many tenge do you want to top up? Send only a number 👇",
        "bad_amount": "❌ Send a positive number.",
        "pay_reqs": "💳 PAYMENT DETAILS:\n\n💳 Number: <code>{number}</code>\n👤 Name: {holder}\n💰 Amount: {amount} ₸\n\n⚠️ After paying, send the receipt.",
        "need_photo": "❌ Send the receipt as a photo or a file.",
        "receipt_ok": "✅ Receipt received! Sent for review.",
        "pay_ok": "✅ Receipt approved, {amount}₸ added to your balance",
        "pay_no": "❌ Receipt rejected.\n\n📝 Reason: {reason}",
        "ref_t": "🤝 PARTNER (REFERRAL) PROGRAM\n━━━━━━━━━━━━━━━━━━━━━━\n\nInvite friends to the bot and get +{bonus} 〒 bonus for every registered friend!\n\n🔗 Your referral link:\n<code>{link}</code>\n\n📊 Your statistics:\n👥 Invited friends: {n}\n💸 Total bonus earned: {earned} 〒\n━━━━━━━━━━━━━━━━━━━━━━",
        "share_btn": "👥 Share with friends", "top_btn": "🏆 Top referrals",
        "share_text": "🔥 Hi! This bot has quality keys and products. Join:",
        "top_t": "🏆 TOP REFERRALS\n\n", "top_none": "Nobody yet.", "people": "pcs",
        "ref_new": "👥 A new user has registered via your invite link! +{bonus} 〒 reward has been added to your balance.",
        "info_t": "Choose the button you need:", "info_none": "❌ No information buttons yet.",
        "lang_pick": LANG_TITLE, "cancel": "❌ Cancelled.",
    },
}


# ======================= HELPERS =======================
def esc(s):
    return html.escape(str(s if s is not None else ""))


def uname(username):
    return f"@{username}" if username else "—"


def ulang(uid):
    r = q1("SELECT lang FROM users WHERE id=?", (uid,))
    return r["lang"] if r and r["lang"] in T else "kk"


def t(uid, key, **kw):
    s = T[ulang(uid)][key]
    return s.format(**kw) if kw else s


def is_admin(uid):
    return uid == ADMIN_ID


def now():
    return time.strftime("%d.%m.%Y %H:%M")


def delete(cid, mid):
    try:
        bot.delete_message(cid, mid)
    except Exception:
        pass


def show(cid, text, markup=None, old=None):
    if old:
        delete(cid, old)
    return bot.send_message(cid, text, reply_markup=markup, disable_web_page_preview=True)


def ensure_user(u):
    r = q1("SELECT id FROM users WHERE id=?", (u.id,))
    if not r:
        ex("INSERT INTO users(id,username,name,joined) VALUES(?,?,?,?)",
           (u.id, u.username, u.first_name or "", now()))
        return True
    ex("UPDATE users SET username=?, name=? WHERE id=?", (u.username, u.first_name or "", u.id))
    return False


def duration_of(name):
    w = name.split()
    if len(w) >= 2 and w[-2].isdigit():
        return " ".join(w[-2:])
    return name


def norm_url(u):
    u = u.strip()
    if u.startswith("@"):
        return "https://t.me/" + u[1:]
    if u.startswith("t.me/"):
        return "https://" + u
    return u


def back_btn(uid, data):
    return IKB(t(uid, "back"), callback_data=data)


def bail(msg):
    """Если админ/пайдаланушы команда жазса, ағымдағы сұрақты тоқтатады."""
    if msg.content_type == "text" and msg.text and msg.text.startswith("/"):
        if msg.text.startswith("/start"):
            cmd_start(msg)
        elif msg.text.startswith("/admin"):
            cmd_admin(msg)
        else:
            bot.send_message(msg.chat.id, t(msg.from_user.id, "cancel"))
        return True
    return False


def ask(cid, prompt, fn, *args, markup=None):
    m = bot.send_message(cid, prompt, reply_markup=markup)
    bot.register_next_step_handler(m, fn, *args)


# ======================= SUBSCRIPTION =======================
def not_subscribed(uid):
    if is_admin(uid):
        return []
    bad = []
    for ch in qa("SELECT * FROM channels"):
        chat = ch["chat"]
        try:
            chat_id = int(chat) if chat.lstrip("-").isdigit() else chat
            st = bot.get_chat_member(chat_id, uid).status
            if st not in ("member", "administrator", "creator"):
                bad.append(ch)
        except Exception as e:
            print("Subscription check error:", chat, e)
            bad.append(ch)
    return bad


def sub_screen(cid, uid, old=None):
    mk = types.InlineKeyboardMarkup()
    for ch in qa("SELECT * FROM channels"):
        mk.row(IKB("📢 " + ch["name"], url=ch["url"]))
    mk.row(IKB(t(uid, "check"), callback_data="chk"))
    show(cid, t(uid, "sub_req"), mk, old)


def gate(cid, uid, old=None):
    if not_subscribed(uid):
        sub_screen(cid, uid, old)
        return False
    main_menu(cid, uid, old)
    return True


# ======================= MAIN MENU =======================
def reward_referral(uid):
    """Жазылымнан өткен соң ғана шақырушыға сыйақы береді (бір рет)."""
    with lock:
        pr = q1("SELECT inviter FROM pending_ref WHERE invited=?", (uid,))
        if not pr:
            return
        db.execute("DELETE FROM pending_ref WHERE invited=?", (uid,))
        inviter = pr["inviter"]
        if q1("SELECT id FROM referrals WHERE invited=?", (uid,)):
            db.commit()
            return
        bonus = int(get_set("ref_bonus", DEFAULT_REF_BONUS))
        db.execute("INSERT INTO referrals(inviter,invited,bonus) VALUES(?,?,?)", (inviter, uid, bonus))
        db.execute("UPDATE users SET balance=balance+? WHERE id=?", (bonus, inviter))
        db.commit()
    try:
        bot.send_message(inviter, t(inviter, "ref_new", bonus=bonus))
    except Exception:
        pass


def main_menu(cid, uid, old=None):
    reward_referral(uid)
    if old:
        delete(cid, old)
    mk = types.InlineKeyboardMarkup()
    mk.row(IKB(t(uid, "goods"), callback_data="goods"))
    mk.row(IKB(t(uid, "topup_btn"), callback_data="topup"))
    mk.row(IKB(t(uid, "profile"), callback_data="prof"),
           IKB(t(uid, "ref"), callback_data="ref"))
    mk.row(IKB(t(uid, "info"), callback_data="info"),
           IKB(t(uid, "lang"), callback_data="langmenu"))
    if is_admin(uid):
        mk.row(IKB(t(uid, "admin"), callback_data="a|home"))
    text = t(uid, "welcome")
    media = get_set("media")
    if media:
        typ, fid = media.split("|", 1)
        try:
            if typ == "photo":
                bot.send_photo(cid, fid, caption=text, reply_markup=mk)
            else:
                bot.send_video(cid, fid, caption=text, reply_markup=mk)
            return
        except Exception as e:
            print("media error:", e)
    bot.send_message(cid, text, reply_markup=mk)


def lang_markup(back=None):
    mk = types.InlineKeyboardMarkup(row_width=3)
    mk.add(IKB("Қазақша 🇰🇿", callback_data="lang|kk"),
           IKB("Орысша 🇷🇺", callback_data="lang|ru"),
           IKB("English 🇬🇧", callback_data="lang|en"))
    if back:
        mk.row(IKB(back, callback_data="menu"))
    return mk


# ======================= /start =======================
@bot.message_handler(commands=["start"])
def cmd_start(msg):
    uid = msg.from_user.id
    new = ensure_user(msg.from_user)
    # реферал
    parts = msg.text.split()
    if new and len(parts) > 1 and parts[1].startswith("ref_"):
        try:
            inviter = int(parts[1][4:])
            if inviter != uid and q1("SELECT id FROM users WHERE id=?", (inviter,)):
                ex("INSERT OR IGNORE INTO pending_ref(invited,inviter) VALUES(?,?)", (uid, inviter))
        except Exception:
            pass
    u = q1("SELECT lang FROM users WHERE id=?", (uid,))
    if not u["lang"]:
        bot.send_message(msg.chat.id, LANG_TITLE, reply_markup=lang_markup())
    else:
        gate(msg.chat.id, uid)


@bot.message_handler(commands=["admin"])
def cmd_admin(msg):
    if is_admin(msg.from_user.id):
        admin_home(msg.chat.id)
    else:
        bot.send_message(msg.chat.id,
                         f"⛔ Сіз админ емессіз.\nСіздің ID: <code>{msg.from_user.id}</code>\n"
                         f"Кодтағы ADMIN_ID: <code>{ADMIN_ID}</code>\n\nЕкеуі бірдей болуы керек.")


@bot.message_handler(commands=["id"])
def cmd_id(msg):
    bot.send_message(msg.chat.id, f"Сіздің ID: <code>{msg.from_user.id}</code>")


# ======================= USER CALLBACKS =======================
def profile_screen(cid, uid, old):
    u = q1("SELECT * FROM users WHERE id=?", (uid,))
    mk = types.InlineKeyboardMarkup()
    mk.row(IKB(t(uid, "hist_btn"), callback_data="hist"))
    mk.row(back_btn(uid, "menu"))
    show(cid, t(uid, "profile_t", id=uid, login=uname(u["username"]), bal=u["balance"],
                cnt=u["bought"], spent=u["spent"]), mk, old)


def product_screen(cid, uid, pid, old):
    p = q1("SELECT * FROM products WHERE id=?", (pid,))
    if not p:
        return
    stock = q1("SELECT COUNT(*) c FROM keys WHERE product_id=? AND sold=0", (pid,))["c"]
    sold = q1("SELECT COALESCE(SUM(qty),0) c FROM purchases WHERE product_id=?", (pid,))["c"]
    mk = types.InlineKeyboardMarkup()
    mk.row(IKB(t(uid, "buy1"), callback_data=f"buy|{pid}"))
    mk.row(IKB(t(uid, "buym"), callback_data=f"buym|{pid}"))
    mk.row(back_btn(uid, f"cat|{p['cat_id']}"))
    show(cid, t(uid, "card", name=esc(p["name"]), price=p["price"], stock=stock, sold=sold), mk, old)


def do_buy(uid, pid, qty):
    with lock:
        p = q1("SELECT * FROM products WHERE id=?", (pid,))
        if not p:
            return "none", None
        ks = qa("SELECT * FROM keys WHERE product_id=? AND sold=0 ORDER BY id LIMIT ?", (pid, qty))
        if len(ks) < qty:
            return "stock", None
        u = q1("SELECT * FROM users WHERE id=?", (uid,))
        total = p["price"] * qty
        if u["balance"] < total:
            return "money", total
        for k in ks:
            db.execute("UPDATE keys SET sold=1 WHERE id=?", (k["id"],))
        db.execute("UPDATE users SET balance=balance-?, spent=spent+?, bought=bought+? WHERE id=?",
                   (total, total, qty, uid))
        keys_text = "\n".join(k["key"] for k in ks)
        cur = db.execute("INSERT INTO purchases(user_id,product_id,name,duration,price,qty,keys,date) VALUES(?,?,?,?,?,?,?,?)",
                         (uid, pid, p["name"], duration_of(p["name"]), p["price"], qty, keys_text, now()))
        db.commit()
        return "ok", dict(id=cur.lastrowid, name=p["name"], dur=duration_of(p["name"]), price=p["price"],
                          qty=qty, total=total, keys=keys_text, bal=u["balance"] - total)


def finish_buy(cid, uid, pid, qty, user, old=None):
    res, data = do_buy(uid, pid, qty)
    if res == "stock":
        bot.send_message(cid, t(uid, "no_stock"))
        return
    if res == "money":
        mk = types.InlineKeyboardMarkup()
        mk.row(IKB(t(uid, "topup_btn"), callback_data="topup"))
        show(cid, t(uid, "no_money", total=data), mk, old)
        return
    if res != "ok":
        return
    keys_html = "\n".join(f"<code>{esc(k)}</code>" for k in data["keys"].split("\n"))
    mk = types.InlineKeyboardMarkup()
    mk.row(IKB(t(uid, "rev_btn"), callback_data=f"rev|{data['id']}"))
    mk.row(back_btn(uid, "menu"))
    show(cid, t(uid, "bought", name=esc(data["name"]), dur=esc(data["dur"]), price=data["price"],
                qty=data["qty"], bal=data["bal"], total=data["total"], keys=keys_html), mk, old)
    try:
        bot.send_message(ADMIN_ID,
                         f"🛒 ЖАҢА САТЫП АЛУ\n\n👤 Сатып алушы: {esc(user.first_name)} ({uname(user.username)})\n"
                         f"ID: <code>{uid}</code>\n📜 Сұраныс: #{data['id']}\n📦 Өнім: {esc(data['name'])}\n"
                         f"⏱️ Күні: {esc(data['dur'])}\n💰 Бағасы: {data['total']}₸\n📊 Кілттер: {data['qty']} дана\n\n"
                         f"🔑 Сатып алынған кілттер:\n{keys_html}")
    except Exception as e:
        print("admin notify error:", e)


def qty_step(msg, pid):
    if bail(msg):
        return
    uid = msg.from_user.id
    if not (msg.text and msg.text.strip().isdigit() and int(msg.text.strip()) > 0):
        ask(msg.chat.id, t(uid, "bad_qty"), qty_step, pid)
        return
    finish_buy(msg.chat.id, uid, pid, int(msg.text.strip()), msg.from_user)


def review_step(msg, purchase_id):
    if bail(msg):
        return
    uid = msg.from_user.id
    if msg.content_type != "text":
        ask(msg.chat.id, t(uid, "rev_ask"), review_step, purchase_id)
        return
    bot.send_message(msg.chat.id, t(uid, "rev_ok"))
    bot.send_message(ADMIN_ID,
                     f"💬 Жаңа отзыв\n\n👤 Сатып алушы: {esc(msg.from_user.first_name)} ({uname(msg.from_user.username)})\n"
                     f"ID: <code>{uid}</code>\n\n💬 Отзыв сипаттамасы:\n{esc(msg.text)}")


def amount_step(msg, country_id):
    if bail(msg):
        return
    uid = msg.from_user.id
    if not (msg.text and msg.text.strip().isdigit() and int(msg.text.strip()) > 0):
        ask(msg.chat.id, t(uid, "bad_amount"), amount_step, country_id)
        return
    amount = int(msg.text.strip())
    r = q1("SELECT * FROM requisites WHERE id=?", (country_id,))
    if not r:
        bot.send_message(msg.chat.id, t(uid, "no_reqs"))
        return
    ask(msg.chat.id, t(uid, "pay_reqs", number=esc(r["number"]), holder=esc(r["holder"]), amount=amount),
        receipt_step, amount)


def pay_caption(pay_id, status=None):
    p = q1("SELECT * FROM payments WHERE id=?", (pay_id,))
    u = q1("SELECT * FROM users WHERE id=?", (p["user_id"],))
    text = (f"📋Жаңа төлем\n\n📝Аты: {esc(u['name'])}\n👤Қолданушы: {uname(u['username'])}\n"
            f"🆔ID: <code>{u['id']}</code>\n📋Сұраныс: #{pay_id}\n💰Сомма: {p['amount']}₸")
    if status:
        text += "\n\n" + status
    return text


def set_pay_status(chat_id, mid, pay_id, status):
    cap = pay_caption(pay_id, status)
    try:
        bot.edit_message_caption(cap, chat_id, mid, parse_mode="HTML", reply_markup=None)
    except Exception:
        try:
            bot.edit_message_text(cap, chat_id, mid, parse_mode="HTML", reply_markup=None)
        except Exception as e:
            print("status edit error:", e)


def receipt_step(msg, amount):
    if bail(msg):
        return
    uid = msg.from_user.id
    if msg.content_type not in ("photo", "document"):
        ask(msg.chat.id, t(uid, "need_photo"), receipt_step, amount)
        return
    pay_id = ex("INSERT INTO payments(user_id,amount,date) VALUES(?,?,?)", (uid, amount, now()))
    bot.send_message(msg.chat.id, t(uid, "receipt_ok"))
    mk = types.InlineKeyboardMarkup()
    mk.row(IKB("✅ Қабылдау", callback_data=f"pay|ok|{pay_id}"),
           IKB("❌ Қабылдамау", callback_data=f"pay|no|{pay_id}"))
    cap = pay_caption(pay_id)
    try:
        bot.copy_message(ADMIN_ID, msg.chat.id, msg.message_id, caption=cap, reply_markup=mk, parse_mode="HTML")
    except Exception as e:
        print("copy error:", e)
        bot.send_message(ADMIN_ID, cap, reply_markup=mk)


def reject_step(msg, pay_id, mid):
    if bail(msg):
        return
    p = q1("SELECT * FROM payments WHERE id=?", (pay_id,))
    if not p or p["status"] != "pending":
        bot.send_message(msg.chat.id, "⚠️ Бұл төлем өңделіп қойған.")
        return
    reason = msg.text or "—"
    ex("UPDATE payments SET status='rejected' WHERE id=?", (pay_id,))
    try:
        bot.send_message(p["user_id"], t(p["user_id"], "pay_no", reason=esc(reason)))
    except Exception:
        pass
    set_pay_status(msg.chat.id, mid, pay_id, f"❌ Қабылданбады\n📝 Себебі: {esc(reason)}")
    bot.send_message(msg.chat.id, f"❌ Төлем #{pay_id} қабылданбады, себебі пайдаланушыға жіберілді.")


@bot.callback_query_handler(func=lambda c: True)
def on_cb(c):
    uid = c.from_user.id
    cid = c.message.chat.id
    mid = c.message.message_id
    p = c.data.split("|")
    act = p[0]
    alert = None
    try:
        ensure_user(c.from_user)

        # ---------- админ ----------
        if act == "a":
            if not is_admin(uid):
                bot.answer_callback_query(c.id)
                return
            admin_cb(c, p[1:])
            bot.answer_callback_query(c.id)
            return

        if act == "pay":
            if not is_admin(uid):
                bot.answer_callback_query(c.id)
                return
            pay_id = int(p[2])
            pay = q1("SELECT * FROM payments WHERE id=?", (pay_id,))
            if not pay or pay["status"] != "pending":
                bot.answer_callback_query(c.id, "⚠️ Өңделіп қойған", show_alert=True)
                return
            try:
                bot.edit_message_reply_markup(cid, mid, reply_markup=None)
            except Exception:
                pass
            if p[1] == "ok":
                ex("UPDATE payments SET status='approved' WHERE id=?", (pay_id,))
                ex("UPDATE users SET balance=balance+? WHERE id=?", (pay["amount"], pay["user_id"]))
                try:
                    bot.send_message(pay["user_id"], t(pay["user_id"], "pay_ok", amount=pay["amount"]))
                except Exception:
                    pass
                set_pay_status(cid, mid, pay_id, "✅ Қабылданды")
            else:
                set_pay_status(cid, mid, pay_id, "❌ Қабылданбады")
                ask(cid, f"📝 Төлем #{pay_id} қабылданбау себебін жазыңыз:", reject_step, pay_id, mid)
            bot.answer_callback_query(c.id)
            return

        # ---------- тіл ----------
        if act == "lang":
            ex("UPDATE users SET lang=? WHERE id=?", (p[1], uid))
            gate(cid, uid, mid)
            bot.answer_callback_query(c.id)
            return

        if act == "chk":
            if not_subscribed(uid):
                bot.answer_callback_query(c.id, t(uid, "not_sub"), show_alert=True)
                return
            main_menu(cid, uid, mid)
            bot.answer_callback_query(c.id)
            return

        # ---------- міндетті жазылым тексеру ----------
        if not_subscribed(uid):
            sub_screen(cid, uid, mid)
            bot.answer_callback_query(c.id, t(uid, "not_sub"), show_alert=True)
            return

        if act == "menu":
            main_menu(cid, uid, mid)

        elif act == "langmenu":
            show(cid, T[ulang(uid)]["lang_pick"], lang_markup(t(uid, "back")), mid)

        elif act == "goods":
            cats = qa("SELECT * FROM categories ORDER BY id")
            mk = types.InlineKeyboardMarkup(row_width=2)
            if not cats:
                mk.row(back_btn(uid, "menu"))
                show(cid, t(uid, "no_cats"), mk, mid)
            else:
                mk.add(*[IKB("📁 " + x["name"], callback_data=f"cat|{x['id']}") for x in cats])
                mk.row(back_btn(uid, "menu"))
                show(cid, t(uid, "goods_title"), mk, mid)

        elif act == "cat":
            cat = q1("SELECT * FROM categories WHERE id=?", (int(p[1]),))
            if not cat:
                return
            prods = qa("SELECT * FROM products WHERE cat_id=? ORDER BY id", (cat["id"],))
            mk = types.InlineKeyboardMarkup()
            for x in prods:
                mk.row(IKB(f"{x['name']} – {x['price']} ₸", callback_data=f"prod|{x['id']}"))
            mk.row(back_btn(uid, "goods"))
            text = t(uid, "cat_title", cat=esc(cat["name"])) if prods else t(uid, "no_products")
            show(cid, text, mk, mid)

        elif act == "prod":
            product_screen(cid, uid, int(p[1]), mid)

        elif act == "buy":
            finish_buy(cid, uid, int(p[1]), 1, c.from_user, mid)

        elif act == "buym":
            delete(cid, mid)
            ask(cid, t(uid, "ask_qty"), qty_step, int(p[1]))

        elif act == "rev":
            ask(cid, t(uid, "rev_ask"), review_step, int(p[1]))

        elif act == "prof":
            profile_screen(cid, uid, mid)

        elif act == "hist":
            rows = qa("SELECT * FROM purchases WHERE user_id=? ORDER BY id DESC LIMIT 10", (uid,))
            mk = types.InlineKeyboardMarkup()
            mk.row(IKB(t(uid, "back_prof"), callback_data="prof"))
            if not rows:
                show(cid, t(uid, "hist_none"), mk, mid)
            else:
                text = t(uid, "hist_title")
                for r in rows:
                    ks = "\n".join(f"<code>{esc(k)}</code>" for k in r["keys"].split("\n"))
                    text += (f"📦 {esc(r['name'])}\n🗓 {r['date']}\n💰 {r['price'] * r['qty']} ₸ × {r['qty']}\n"
                             f"🔑 {ks}\n━━━━━━━━━━━━━━\n")
                show(cid, text[:4000], mk, mid)

        elif act == "topup":
            rs = qa("SELECT * FROM requisites ORDER BY id")
            mk = types.InlineKeyboardMarkup(row_width=2)
            if not rs:
                mk.row(back_btn(uid, "menu"))
                show(cid, t(uid, "no_reqs"), mk, mid)
            else:
                mk.add(*[IKB(r["country"], callback_data=f"cty|{r['id']}") for r in rs])
                mk.row(back_btn(uid, "menu"))
                show(cid, t(uid, "topup_country"), mk, mid)

        elif act == "cty":
            delete(cid, mid)
            ask(cid, t(uid, "topup_amount"), amount_step, int(p[1]))

        elif act == "ref":
            n = q1("SELECT COUNT(*) c, COALESCE(SUM(bonus),0) s FROM referrals WHERE inviter=?", (uid,))
            link = f"https://t.me/{BOT_USERNAME}?start=ref_{uid}"
            bonus = get_set("ref_bonus", DEFAULT_REF_BONUS)
            share = f"https://t.me/share/url?url={quote(link, safe='')}&text={quote(T[ulang(uid)]['share_text'] + ' ' + link)}"
            mk = types.InlineKeyboardMarkup()
            mk.row(IKB(t(uid, "share_btn"), url=share))
            mk.row(IKB(t(uid, "top_btn"), callback_data="top"))
            mk.row(back_btn(uid, "menu"))
            show(cid, t(uid, "ref_t", bonus=bonus, link=link, n=n["c"], earned=n["s"]), mk, mid)

        elif act == "top":
            lim = int(get_set("top_count", DEFAULT_TOP_COUNT))
            rows = qa("SELECT inviter, COUNT(*) c FROM referrals GROUP BY inviter ORDER BY c DESC LIMIT ?", (lim,))
            text = t(uid, "top_t")
            if not rows:
                text += t(uid, "top_none")
            for i, r in enumerate(rows, 1):
                u = q1("SELECT username, name FROM users WHERE id=?", (r["inviter"],))
                nm = uname(u["username"]) if u and u["username"] else esc(u["name"] if u else r["inviter"])
                text += f"{i}. {nm} — {r['c']} {T[ulang(uid)]['people']}\n"
            mk = types.InlineKeyboardMarkup()
            mk.row(back_btn(uid, "ref"))
            show(cid, text, mk, mid)

        elif act == "info":
            btns = qa("SELECT * FROM infobtn ORDER BY id")
            mk = types.InlineKeyboardMarkup(row_width=2)
            if btns:
                mk.add(*[IKB(b["name"], url=b["url"]) for b in btns])
            mk.row(back_btn(uid, "menu"))
            show(cid, t(uid, "info_t") if btns else t(uid, "info_none"), mk, mid)

        bot.answer_callback_query(c.id, alert)
    except Exception:
        traceback.print_exc()
        try:
            bot.answer_callback_query(c.id)
        except Exception:
            pass


# ======================= ADMIN PANEL =======================
def admin_home(cid, old=None):
    mk = types.InlineKeyboardMarkup()
    mk.row(IKB("⚙️ Настройка", callback_data="a|set"))
    mk.row(IKB("🛍 Тауарлар баптауы", callback_data="a|goods"))
    mk.row(IKB("📢 Міндетті жазылым баптауы", callback_data="a|subs"))
    mk.row(IKB("👥 Пайдаланушылар тізімі", callback_data="a|users|0"))
    mk.row(IKB("📊 Статистика бота", callback_data="a|stats"))
    mk.row(IKB("🔙 Артқа", callback_data="menu"))
    show(cid, "⚙️ АДМИН ПАНЕЛЬ", mk, old)


def kb(rows, back="a|home"):
    """rows: [(text, data), ...] -> әр қатарға біреуі + артқа."""
    mk = types.InlineKeyboardMarkup()
    for txt, data in rows:
        mk.row(IKB(txt, callback_data=data))
    mk.row(IKB("🔙 Артқа", callback_data=back))
    return mk


def done(msg, text, back="a|home", label="🔙 Админ панель"):
    mk = types.InlineKeyboardMarkup()
    mk.row(IKB(label, callback_data=back))
    bot.send_message(msg.chat.id, text, reply_markup=mk)


# ---- админ step handlers ----
def st_info_url(msg):
    if bail(msg):
        return
    url = norm_url(msg.text or "")
    ask(msg.chat.id, "2. Батырма атауын жазыңыз:", st_info_name, url)


def st_info_name(msg, url):
    if bail(msg):
        return
    ex("INSERT INTO infobtn(name,url) VALUES(?,?)", (msg.text, url))
    done(msg, "✅ Сәтті қосылды", "a|info")


def st_ref_bonus(msg):
    if bail(msg):
        return
    if not (msg.text or "").strip().isdigit():
        ask(msg.chat.id, "❌ Тек сан жазыңыз. Жаңа санды жазыңыз:", st_ref_bonus)
        return
    set_set("ref_bonus", int(msg.text.strip()))
    done(msg, "✅ Реферал тиыны өзгерді", "a|refset")


def st_top_count(msg):
    if bail(msg):
        return
    if not (msg.text or "").strip().isdigit() or int(msg.text.strip()) < 1:
        ask(msg.chat.id, "❌ Тек сан жазыңыз. Реферал топ санын жазыңыз:", st_top_count)
        return
    set_set("top_count", int(msg.text.strip()))
    done(msg, "✅ Өзгертілді", "a|refset")


def st_req_country(msg):
    if bail(msg):
        return
    ask(msg.chat.id, "Реквизит номерін бірінші жолға, аты-жөнін екінші жолға жазыңыз:\n\nМысалы:\n4400 4300 1234 5678\nАйдос А.",
        st_req_data, msg.text)


def st_req_data(msg, country):
    if bail(msg):
        return
    lines = (msg.text or "").strip().split("\n", 1)
    number = lines[0].strip()
    holder = lines[1].strip() if len(lines) > 1 else "—"
    ex("INSERT INTO requisites(country,number,holder) VALUES(?,?,?)", (country, number, holder))
    done(msg, "✅ Реквизит сақталды", "a|set")


def st_media(msg):
    if bail(msg):
        return
    if msg.content_type == "photo":
        set_set("media", "photo|" + msg.photo[-1].file_id)
    elif msg.content_type == "video":
        set_set("media", "video|" + msg.video.file_id)
    else:
        ask(msg.chat.id, "❌ Фото немесе видео жіберіңіз:", st_media)
        return
    done(msg, "✅ Фото қосылды.", "a|set")


def st_cat_name(msg):
    if bail(msg):
        return
    ex("INSERT INTO categories(name) VALUES(?)", (msg.text,))
    done(msg, "✅ Категория қосылды", "a|goods")


def st_prod_name(msg, cat_id):
    if bail(msg):
        return
    ask(msg.chat.id, "Тауар бағасын жазыңыз (тек сан, ₸):", st_prod_price, cat_id, msg.text)


def st_prod_price(msg, cat_id, name):
    if bail(msg):
        return
    if not (msg.text or "").strip().isdigit():
        ask(msg.chat.id, "❌ Тек сан жазыңыз. Бағасын жазыңыз:", st_prod_price, cat_id, name)
        return
    ex("INSERT INTO products(cat_id,name,price) VALUES(?,?,?)", (cat_id, name, int(msg.text.strip())))
    done(msg, "✅ Тауар қосылды", "a|goods")


def st_keys(msg, pid):
    if bail(msg):
        return
    ks = [k.strip() for k in (msg.text or "").split("\n") if k.strip()]
    with lock:
        for k in ks:
            db.execute("INSERT INTO keys(product_id,key) VALUES(?,?)", (pid, k))
        db.commit()
    done(msg, f"✅ Кілттер қосылды: {len(ks)}", "a|goods")


def st_chan_id(msg):
    if bail(msg):
        return
    chat = (msg.text or "").strip()
    if not chat.lstrip("-").isdigit() and not chat.startswith("@"):
        chat = "@" + chat
    ask(msg.chat.id, "2. Каналдың сілтемесін жіберіңіз:", st_chan_url, chat)


def st_chan_url(msg, chat):
    if bail(msg):
        return
    ask(msg.chat.id, "3. Каналдың атын жазыңыз:", st_chan_name, chat, norm_url(msg.text or ""))


def st_chan_name(msg, chat, url):
    if bail(msg):
        return
    ex("INSERT INTO channels(chat,url,name) VALUES(?,?,?)", (chat, url, msg.text))
    done(msg, "✅ Канал сәтті қосылды", "a|subs")


# ---- админ callback ----
def admin_cb(c, p):
    cid = c.message.chat.id
    mid = c.message.message_id
    act = p[0]

    if act == "home":
        admin_home(cid, mid)

    # ---------- Настройка ----------
    elif act == "set":
        show(cid, "⚙️ НАСТРОЙКА", kb([
            ("ℹ️ Ақпарат баптауы", "a|info"),
            ("🤝 Реферал баптауы", "a|refset"),
            ("💳 Реквизит қосу", "a|reqadd"),
            ("🗑 Реквизит өшіру", "a|reqdel"),
            ("🖼 Басты бетке фота қосу", "a|mediaadd"),
            ("🗑 Фота өшіру", "a|mediadel"),
        ]), mid)

    elif act == "info":
        show(cid, "ℹ️ АҚПАРАТ БАПТАУЫ", kb([
            ("➕ Батырма қосу", "a|infoadd"),
            ("🗑 Батырма өшіру", "a|infodel"),
        ], "a|set"), mid)

    elif act == "infoadd":
        delete(cid, mid)
        ask(cid, "1. Батырма сілтемесін жіберіңіз:", st_info_url)

    elif act == "infodel":
        rows = [(f"❌ {b['name']}", f"a|infodel2|{b['id']}") for b in qa("SELECT * FROM infobtn")]
        show(cid, "Өшіретін батырманы таңдаңыз:" if rows else "Батырмалар жоқ.", kb(rows, "a|info"), mid)

    elif act == "infodel2":
        ex("DELETE FROM infobtn WHERE id=?", (int(p[1]),))
        admin_cb(c, ["infodel"])

    elif act == "refset":
        bonus = get_set("ref_bonus", DEFAULT_REF_BONUS)
        top = get_set("top_count", DEFAULT_TOP_COUNT)
        show(cid, f"🤝 РЕФЕРАЛ БАПТАУЫ\n\nБонус: {bonus} 〒\nТоп саны: {top}", kb([
            ("💸 Реферал тиынын өзгерту", "a|refbonus"),
            ("🏆 Топ реферал саны", "a|reftop"),
            ("🗑 Реферал өшіру", "a|refclear"),
        ], "a|set"), mid)

    elif act == "refbonus":
        delete(cid, mid)
        ask(cid, "Жаңа санды жазыңыз:", st_ref_bonus)

    elif act == "reftop":
        delete(cid, mid)
        ask(cid, "Реферал топ санын жазыңыз:", st_top_count)

    elif act == "refclear":
        ex("DELETE FROM referrals")
        show(cid, "✅ Барлық реферал деректері өшірілді, топ 0 болды.", kb([], "a|refset"), mid)

    elif act == "reqadd":
        delete(cid, mid)
        ask(cid, "Реквизит елін қосыңыз (мысалы: Қазақстан 🇰🇿):", st_req_country)

    elif act == "reqdel":
        rows = [(f"❌ {r['country']} — {r['number']}", f"a|reqdel2|{r['id']}") for r in qa("SELECT * FROM requisites")]
        show(cid, "Өшіретін реквизитті таңдаңыз:" if rows else "Реквизиттер жоқ.", kb(rows, "a|set"), mid)

    elif act == "reqdel2":
        ex("DELETE FROM requisites WHERE id=?", (int(p[1]),))
        admin_cb(c, ["reqdel"])

    elif act == "mediaadd":
        delete(cid, mid)
        ask(cid, "Фото немесе видео жіберіңіз:", st_media)

    elif act == "mediadel":
        del_set("media")
        show(cid, "✅ Фото өшірілді", kb([], "a|set"), mid)

    # ---------- Тауарлар баптауы ----------
    elif act == "goods":
        show(cid, "🛍 ТАУАРЛАР БАПТАУЫ", kb([
            ("📁 Категория қосу", "a|cataddq"),
            ("🗑 Категория өшіру", "a|catdel"),
            ("📦 Тауар қосу", "a|prodadd"),
            ("🗑 Тауар өшіру", "a|proddel"),
            ("🔑 Кілт қосу", "a|keyadd"),
        ]), mid)

    elif act == "cataddq":
        delete(cid, mid)
        ask(cid, "Категория атын жазыңыз:", st_cat_name)

    elif act == "catdel":
        rows = [(f"❌ {x['name']}", f"a|catdel2|{x['id']}") for x in qa("SELECT * FROM categories")]
        show(cid, "Өшіретін категорияны таңдаңыз:" if rows else "Категориялар жоқ.", kb(rows, "a|goods"), mid)

    elif act == "catdel2":
        cat = int(p[1])
        with lock:
            pids = [r["id"] for r in db.execute("SELECT id FROM products WHERE cat_id=?", (cat,)).fetchall()]
            for pid in pids:
                db.execute("DELETE FROM keys WHERE product_id=? AND sold=0", (pid,))
            db.execute("DELETE FROM products WHERE cat_id=?", (cat,))
            db.execute("DELETE FROM categories WHERE id=?", (cat,))
            db.commit()
        admin_cb(c, ["catdel"])

    elif act == "prodadd":
        rows = [(f"📁 {x['name']}", f"a|prodadd2|{x['id']}") for x in qa("SELECT * FROM categories")]
        show(cid, "Тауар қосу үшін категория таңдаңыз:" if rows else "Алдымен категория қосыңыз.", kb(rows, "a|goods"), mid)

    elif act == "prodadd2":
        delete(cid, mid)
        ask(cid, "Тауар атын жазыңыз (мысалы: DRIP CLIENT 1 DAY):", st_prod_name, int(p[1]))

    elif act == "proddel":
        rows = [(f"❌ {r['cn']} / {r['name']}", f"a|proddel2|{r['id']}") for r in
                qa("SELECT p.id, p.name, c.name cn FROM products p JOIN categories c ON c.id=p.cat_id ORDER BY p.id")]
        show(cid, "Өшіретін тауарды таңдаңыз:" if rows else "Тауарлар жоқ.", kb(rows, "a|goods"), mid)

    elif act == "proddel2":
        pid = int(p[1])
        ex("DELETE FROM keys WHERE product_id=? AND sold=0", (pid,))
        ex("DELETE FROM products WHERE id=?", (pid,))
        admin_cb(c, ["proddel"])

    elif act == "keyadd":
        rows = [(f"{r['cn']} / {r['name']}", f"a|keyadd2|{r['id']}") for r in
                qa("SELECT p.id, p.name, c.name cn FROM products p JOIN categories c ON c.id=p.cat_id ORDER BY p.id")]
        show(cid, "Кілт қосатын тауарды таңдаңыз:" if rows else "Алдымен тауар қосыңыз.", kb(rows, "a|goods"), mid)

    elif act == "keyadd2":
        delete(cid, mid)
        ask(cid, "Кілт жазыңыз (бірнеше болса, әр кілтті жаңа жолға жазыңыз):", st_keys, int(p[1]))

    # ---------- Міндетті жазылым ----------
    elif act == "subs":
        chans = qa("SELECT * FROM channels")
        lst = "\n".join(f"• {esc(x['name'])} — {esc(x['chat'])}" for x in chans) or "Каналдар жоқ."
        show(cid,
             "📢 Міндетті жазылу баптаулары (Настройка обязательной подписки)\n\n"
             "Бұл жерде сіз пайдаланушылар ботқа кірмес бұрын тіркелуі тиіс Telegram каналдарын реттей аласыз.\n\n"
             "⚠️ МАҢЫЗДЫ: Тексеру жүйесі дұрыс жұмыс істеуі үшін бот бұл каналдарда міндетті түрде "
             "Әкімші (Администратор) құқығына ие болуы қажет!\n\n" + lst,
             kb([("➕ Канал қосу", "a|chadd"), ("🗑 Канал өшіру", "a|chdel")]), mid)

    elif act == "chadd":
        delete(cid, mid)
        ask(cid, "1. Каналдың айдиі немесе юзерін жіберіңіз (мысалы: @kanal немесе -100123...):", st_chan_id)

    elif act == "chdel":
        rows = [(f"❌ {x['name']}", f"a|chdel2|{x['id']}") for x in qa("SELECT * FROM channels")]
        show(cid, "Өшіретін каналды таңдаңыз:" if rows else "Каналдар жоқ.", kb(rows, "a|subs"), mid)

    elif act == "chdel2":
        ex("DELETE FROM channels WHERE id=?", (int(p[1]),))
        admin_cb(c, ["chdel"])

    # ---------- Пайдаланушылар ----------
    elif act == "users":
        page = int(p[1])
        per = 20
        total = q1("SELECT COUNT(*) c FROM users")["c"]
        pages = max(1, (total + per - 1) // per)
        page = max(0, min(page, pages - 1))
        rows = qa("SELECT * FROM users ORDER BY joined DESC, id DESC LIMIT ? OFFSET ?", (per, page * per))
        text = f"👥 Пайдаланушылар: {total}\n\nПайдаланушылар тізімі (Парақ {page + 1}/{pages}):\n\n"
        for i, u in enumerate(rows, page * per + 1):
            text += f"{i}. {uname(u['username'])} (ID: {u['id']}) — {u['balance']} 〒\n"
        mk = types.InlineKeyboardMarkup()
        nav = []
        if page > 0:
            nav.append(IKB("⬅️", callback_data=f"a|users|{page - 1}"))
        if page < pages - 1:
            nav.append(IKB("➡️", callback_data=f"a|users|{page + 1}"))
        if nav:
            mk.row(*nav)
        mk.row(IKB("🔙 Артқа", callback_data="a|home"))
        show(cid, text, mk, mid)

    # ---------- Статистика ----------
    elif act == "stats":
        req = q1("SELECT COUNT(*) c FROM purchases")["c"]
        usr = q1("SELECT COUNT(*) c FROM users")["c"]
        rev = q1("SELECT COALESCE(SUM(price*qty),0) s FROM purchases")["s"]
        cats = q1("SELECT COUNT(*) c FROM categories")["c"]
        prods = q1("SELECT COUNT(*) c FROM products")["c"]
        allk = q1("SELECT COUNT(*) c FROM keys")["c"]
        sold = q1("SELECT COUNT(*) c FROM keys WHERE sold=1")["c"]
        show(cid,
             f"📊 БОТ СТАТИСТИКАСЫ\n\nСұраныстар: #{req}\nҚолданушылар: {usr}\nЖалпы сатылым: {rev}₸\n"
             f"Категория саны: {cats}\nТауар саны: {prods}\nБарлық кілттер: {allk}\n"
             f"Сатылған кілттер: {sold}\nҚалған кілттер: {allk - sold}",
             kb([]), mid)


# ======================= RUN =======================
if __name__ == "__main__":
    print(f"Bot @{BOT_USERNAME} started | ADMIN_ID = {ADMIN_ID}")
    bot.infinity_polling(skip_pending=True, allowed_updates=["message", "callback_query"])
