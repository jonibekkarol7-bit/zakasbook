"""
╔══════════════════════════════════════════════════════════╗
║           KITOB DO'KONI TELEGRAM BOT  v4.0              ║
║  ✅ O'tkazib yuborish — FAQAT TUGMA (matn emas)         ║
║  ✅ Joylashuv — faqat tugma orqali, qurilma yoqish xabar║
║  ✅ Bir kitobdan bir nechta nusxa (savat orqali)         ║
║  ✅ Kitoblar saqlanadi (DB dan yuklanadi)                ║
║  ✅ Qo'shimcha yaxshilanishlar v4.0                     ║
╚══════════════════════════════════════════════════════════╝
"""

import asyncio
import aiosqlite
import re
import logging
import os
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime
from collections import defaultdict

from aiogram import Bot, Dispatcher, F, BaseMiddleware
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message,
    CallbackQuery,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardRemove,
    TelegramObject,
)
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter

# ═══════════════════════════════════════════════════
#  LOGGING
# ═══════════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════
#  SOZLAMALAR
# ═══════════════════════════════════════════════════
load_dotenv(Path(__file__).resolve().parent / ".env")
TOKEN          = os.getenv("BOT_TOKEN", "").strip()
if not TOKEN:
    raise RuntimeError("BOT_TOKEN muhit o'zgaruvchisi o'rnatilmagan. Tokenni kodga yozmang.")
ADMIN_ID       = 6722242402
ADMIN_USERNAME = "@admoyin_lvl"
ADMIN_PHONE    = "+998950714664"

CARD_HOLDER = "Mustafayev Jonibek"
HUMO_CARD   = "9860 1606 4184 4008"
UZUM_CARD   = "4916 9903 2538 3294"

FLOOD_LIMIT      = 5
FLOOD_INTERVAL   = 3
FLOOD_BLOCK_TIME = 30

# ═══════════════════════════════════════════════════
#  GLOBAL MA'LUMOTLAR
# ═══════════════════════════════════════════════════
BOOKS: dict      = {}
CARTS: dict      = {}
WISHLISTS: dict  = {}
PROMO_CODES: dict = {}

_flood_tracker: dict = defaultdict(list)
_blocked_users: dict = {}

# ═══════════════════════════════════════════════════
#  FSM HOLATLAR
# ═══════════════════════════════════════════════════
class OrderState(StatesGroup):
    waiting_full_name = State()
    waiting_phone     = State()
    waiting_address   = State()
    waiting_promo     = State()
    waiting_payment   = State()
    waiting_check     = State()

class AddBookState(StatesGroup):
    waiting_book_name        = State()
    waiting_book_author      = State()
    waiting_book_price       = State()
    waiting_book_description = State()
    waiting_book_photo       = State()

class SearchState(StatesGroup):
    waiting_search_query = State()

class BroadcastState(StatesGroup):
    waiting_message = State()

class FeedbackState(StatesGroup):
    waiting_feedback = State()

class PromoState(StatesGroup):
    waiting_code     = State()
    waiting_discount = State()
    waiting_type     = State()
    waiting_max_uses = State()

# ═══════════════════════════════════════════════════
#  ANTI-FLOOD MIDDLEWARE
# ═══════════════════════════════════════════════════
class AntiFloodMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: TelegramObject, data: dict):
        user = None
        if isinstance(event, Message):
            user = event.from_user
        elif isinstance(event, CallbackQuery):
            user = event.from_user

        if user and user.id != ADMIN_ID:
            uid = user.id
            now = datetime.now().timestamp()

            if uid in _blocked_users:
                if now < _blocked_users[uid]:
                    remaining = int(_blocked_users[uid] - now)
                    if isinstance(event, Message):
                        await event.answer(
                            f"⏳ Juda tez xabar yuboryapsiz!\n"
                            f"<b>{remaining} soniyadan</b> so'ng qayta urinib ko'ring.",
                            parse_mode="HTML",
                        )
                    elif isinstance(event, CallbackQuery):
                        await event.answer(f"⏳ {remaining} soniya kuting!", show_alert=True)
                    return
                else:
                    del _blocked_users[uid]

            _flood_tracker[uid] = [t for t in _flood_tracker[uid] if now - t < FLOOD_INTERVAL]
            _flood_tracker[uid].append(now)

            if len(_flood_tracker[uid]) > FLOOD_LIMIT:
                _blocked_users[uid] = now + FLOOD_BLOCK_TIME
                if isinstance(event, Message):
                    await event.answer(
                        f"🚫 Siz juda tez xabar yubordingiz!\n"
                        f"<b>{FLOOD_BLOCK_TIME} soniya</b> kuting.",
                        parse_mode="HTML",
                    )
                return

        return await handler(event, data)


# ═══════════════════════════════════════════════════
#  SAFE SENDER
# ═══════════════════════════════════════════════════
async def safe_send(coro, retries: int = 3):
    for attempt in range(retries):
        try:
            return await coro
        except TelegramRetryAfter as e:
            wait = e.retry_after + 1
            logger.warning(f"Rate limited. {wait}s kutilmoqda...")
            await asyncio.sleep(wait)
        except TelegramForbiddenError:
            logger.info("Foydalanuvchi botni bloklagan.")
            return None
        except TelegramBadRequest as e:
            logger.warning(f"Bad request: {e}")
            return None
        except Exception as e:
            logger.error(f"Yuborishda xato (urinish {attempt+1}): {e}")
            await asyncio.sleep(1)
    return None


# ═══════════════════════════════════════════════════
#  BOT & DISPATCHER
# ═══════════════════════════════════════════════════
storage = MemoryStorage()
bot = Bot(token=TOKEN)
dp  = Dispatcher(storage=storage)

dp.message.middleware(AntiFloodMiddleware())
dp.callback_query.middleware(AntiFloodMiddleware())


# ═══════════════════════════════════════════════════
#  YORDAMCHI FUNKSIYALAR
# ═══════════════════════════════════════════════════
def fmt(price: int) -> str:
    return f"{price:,}".replace(",", " ")

def generate_book_id(name: str) -> str:
    slug = re.sub(r'[^a-zA-Z0-9_]', '_', name.lower().replace(' ', '_'))
    ts   = str(int(datetime.now().timestamp()))
    return slug[:25] + "_" + ts[-6:]

def get_cart(uid: int) -> dict:
    return CARTS.get(uid, {})

def cart_total(uid: int) -> int:
    return sum(BOOKS[b]["price"] * q for b, q in get_cart(uid).items() if b in BOOKS)

def cart_count(uid: int) -> int:
    return sum(get_cart(uid).values())

def get_wishlist(uid: int) -> set:
    return WISHLISTS.get(uid, set())

def apply_promo(total: int, code: str) -> tuple:
    code = code.strip().upper()
    if code not in PROMO_CODES:
        return total, ""
    p = PROMO_CODES[code]
    if p["max_uses"] > 0 and p["uses"] >= p["max_uses"]:
        return total, ""
    if p["type"] == "percent":
        disc = int(total * p["discount"] / 100)
        new  = total - disc
        desc = f"🎟️ Promo: -{p['discount']}% (-{fmt(disc)} so'm)"
    else:
        disc = min(p["discount"], total)
        new  = total - disc
        desc = f"🎟️ Promo: -{fmt(disc)} so'm"
    # Foydalanish soni buyurtma muvaffaqiyatli saqlangandan keyin oshiriladi.
    return new, desc

def format_order_row(row) -> str:
    # row[10] = status indeksi
    status_col = row[10] if len(row) > 10 else "yangi"
    emoji = {"yangi": "🆕", "tasdiqlandi": "✅", "yuborildi": "🚚", "yetkazildi": "📬", "mijoz qabul qilmadi": "↩️", "bekor qilindi": "❌"}.get(status_col, "📌")
    return (
        f"━━━━━━━━━━━━━━━━\n"
        f"🧾 Buyurtma #{row[0]}\n"
        f"📖 {row[9]}\n"
        f"💰 {fmt(row[11])} so'm\n"
        f"{emoji} {status_col}\n"
        f"🕒 {row[15]}\n"
        f"━━━━━━━━━━━━━━━━"
    )


# ═══════════════════════════════════════════════════
#  KLAVIATURALAR
# ═══════════════════════════════════════════════════
def main_menu_keyboard(uid: int) -> ReplyKeyboardMarkup:
    wl   = len(get_wishlist(uid))
    cart = cart_count(uid)
    cart_txt = f"🛒 Savatcha ({cart})" if cart else "🛒 Savatcha"
    wl_txt   = f"❤️ Wishlist ({wl})"   if wl   else "❤️ Wishlist"
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📚 Kitoblar"),     KeyboardButton(text="🔍 Qidirish")],
        [KeyboardButton(text=cart_txt),           KeyboardButton(text=wl_txt)],
        [KeyboardButton(text="📦 Buyurtmalarim"), KeyboardButton(text="💬 Fikr")],
        [KeyboardButton(text="🧭 Kitob tanlash"), KeyboardButton(text="📔 Mutolaa kundaligi")],
        [KeyboardButton(text="🎁 To'plamlar"), KeyboardButton(text="👥 Do'st taklif qilish")],
        [KeyboardButton(text="💡 Kun hikmati"), KeyboardButton(text="🎟️ Promo kod")],
        [KeyboardButton(text="🎲 Kitob ruletkasi"), KeyboardButton(text="🎮 Bilim viktorinasi")],
        [KeyboardButton(text="🔥 Mutolaa marafoni"), KeyboardButton(text="🏆 Mening profilim")],
        [KeyboardButton(text="💝 Kayfiyatga qarab"), KeyboardButton(text="🥇 Kitobxonlar reytingi")],
        [KeyboardButton(text="🔔 Mutolaa eslatmasi")],
        [KeyboardButton(text="ℹ️ Aloqa")],
    ], resize_keyboard=True)

def admin_menu_keyboard() -> ReplyKeyboardMarkup:
    # Admin ham mijoz funksiyalarini sinab ko'ra olishi uchun barcha tugmalar ko'rsatiladi.
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📚 Kitoblar"), KeyboardButton(text="🔍 Qidirish")],
        [KeyboardButton(text="🛒 Savatcha"), KeyboardButton(text="📦 Buyurtmalarim")],
        [KeyboardButton(text="➕ Kitob qo'shish"), KeyboardButton(text="📋 Kitoblar (Admin)")],
        [KeyboardButton(text="📊 Admin panel"), KeyboardButton(text="📣 Xabar yuborish")],
        [KeyboardButton(text="🎟️ Promo yaratish"), KeyboardButton(text="📑 Promolar")],
        [KeyboardButton(text="📦 Ombor"), KeyboardButton(text="🎁 To'plamlar")],
        [KeyboardButton(text="🧭 Kitob tanlash"), KeyboardButton(text="📔 Mutolaa kundaligi")],
        [KeyboardButton(text="🎲 Kitob ruletkasi"), KeyboardButton(text="🎮 Bilim viktorinasi")],
        [KeyboardButton(text="🔥 Mutolaa marafoni"), KeyboardButton(text="🏆 Mening profilim")],
        [KeyboardButton(text="💝 Kayfiyatga qarab"), KeyboardButton(text="🥇 Kitobxonlar reytingi")],
        [KeyboardButton(text="👥 Do'st taklif qilish"), KeyboardButton(text="💡 Kun hikmati")],
        [KeyboardButton(text="🔔 Mutolaa eslatmasi"), KeyboardButton(text="ℹ️ Aloqa")],
    ], resize_keyboard=True)

def get_main_menu(uid: int) -> ReplyKeyboardMarkup:
    return admin_menu_keyboard() if uid == ADMIN_ID else main_menu_keyboard(uid)

def phone_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📱 Kontaktni ulashish", request_contact=True)],
        [KeyboardButton(text="✍️ Raqamni qo'lda yozish")],
        [KeyboardButton(text="❌ Bekor qilish")],
    ], resize_keyboard=True, one_time_keyboard=True)

def address_keyboard() -> ReplyKeyboardMarkup:
    """
    GPS joylashuv: request_location=True — Telegram avtomatik so'raydi.
    Qo'lda yozish ham mumkin.
    """
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📍 Joylashuvimni yuborish", request_location=True)],
        [KeyboardButton(text="✍️ Manzilni qo'lda yozish")],
        [KeyboardButton(text="❌ Bekor qilish")],
    ], resize_keyboard=True, one_time_keyboard=True)

payment_keyboard = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="💳 Humo"),  KeyboardButton(text="💳 Visa")],
    [KeyboardButton(text="💵 Naqd"), KeyboardButton(text="❌ Bekor qilish")],
], resize_keyboard=True)

cancel_keyboard = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="❌ Bekor qilish")]],
    resize_keyboard=True,
)

def promo_skip_keyboard() -> ReplyKeyboardMarkup:
    """Promo ekranda FAQAT tugma — matn yozish kerak emas."""
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="⭐ Ball ishlatish")],
        [KeyboardButton(text="⏭️ O'tkazib yuborish")],
        [KeyboardButton(text="❌ Bekor qilish")],
    ], resize_keyboard=True, one_time_keyboard=True)

def photo_skip_keyboard() -> ReplyKeyboardMarkup:
    """Rasm yuklash ekranida o'tkazib yuborish."""
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="⏭️ O'tkazib yuborish")],
        [KeyboardButton(text="❌ Bekor qilish")],
    ], resize_keyboard=True, one_time_keyboard=True)

def books_keyboard(page: int = 0, source: list = None) -> InlineKeyboardMarkup:
    src   = source if source is not None else list(BOOKS.keys())
    ps    = 5
    start = page * ps
    end   = start + ps
    rows  = []
    for bid in src[start:end]:
        if bid not in BOOKS:
            continue
        b   = BOOKS[bid]
        avg = b.get("avg_rating", 0)
        star = ("⭐" * round(avg)) if avg >= 1 else ""
        rows.append([InlineKeyboardButton(
            text=f"📖 {b['name']} — {fmt(b['price'])} so'm {star}",
            callback_data=f"book:{bid}",
        )])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"page:{page-1}"))
    total_pages = max(1, (len(src) - 1) // ps + 1)
    nav.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="noop"))
    if end < len(src):
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"page:{page+1}"))
    if nav:
        rows.append(nav)
    return InlineKeyboardMarkup(inline_keyboard=rows)

def book_detail_keyboard(bid: str, uid: int) -> InlineKeyboardMarkup:
    """
    Savatdagi miqdor ko'rsatiladi.
    ➕/➖ tugmalar orqali miqdor o'zgartiriladi.
    """
    cart = get_cart(uid)
    qty  = cart.get(bid, 0)
    wl   = get_wishlist(uid)
    rows = []

    if qty > 0:
        rows.append([
            InlineKeyboardButton(text="➖", callback_data=f"cart_remove:{bid}"),
            InlineKeyboardButton(text=f"🛒 {qty} ta", callback_data="noop"),
            InlineKeyboardButton(text="➕", callback_data=f"cart_add:{bid}"),
        ])
        rows.append([InlineKeyboardButton(text="📦 Savatni ko'rish", callback_data="view_cart")])
        rows.append([InlineKeyboardButton(text="⚡ Hoziroq buyurtma", callback_data=f"order_now:{bid}")])
    else:
        rows.append([InlineKeyboardButton(text="🛒 Savatga qo'shish", callback_data=f"cart_add:{bid}")])
        rows.append([InlineKeyboardButton(text="⚡ Hoziroq buyurtma",  callback_data=f"order_now:{bid}")])

    wl_text = "💔 Wishlistdan chiqarish" if bid in wl else "❤️ Wishlistga qo'shish"
    rows.append([InlineKeyboardButton(text=wl_text, callback_data=f"wl_toggle:{bid}")])
    rows.append([InlineKeyboardButton(text="⭐ Baholash", callback_data=f"rate:{bid}")])
    rows.append([InlineKeyboardButton(text="📔 O'qiyapman", callback_data=f"reading_set:{bid}:oqilyapti"), InlineKeyboardButton(text="✅ O'qidim", callback_data=f"reading_set:{bid}:oqildi")])
    rows.append([InlineKeyboardButton(text="📝 O'qimoqchiman", callback_data=f"reading_set:{bid}:reja")])
    rows.append([InlineKeyboardButton(text="⬅️ Orqaga",  callback_data="back:books")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def rating_keyboard(bid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"{i}⭐", callback_data=f"rating:{bid}:{i}")
        for i in range(1, 6)
    ]])

def cart_keyboard(uid: int) -> InlineKeyboardMarkup:
    cart = get_cart(uid)
    rows = []
    for bid, qty in cart.items():
        if bid not in BOOKS:
            continue
        b = BOOKS[bid]
        rows.append([
            InlineKeyboardButton(text="➖", callback_data=f"cart_remove:{bid}"),
            InlineKeyboardButton(text=f"📖 {b['name'][:16]} ×{qty}", callback_data=f"book:{bid}"),
            InlineKeyboardButton(text="➕", callback_data=f"cart_add:{bid}"),
        ])
    if rows:
        rows.append([InlineKeyboardButton(text="🗑️ Tozalash",       callback_data="cart_clear")])
        rows.append([InlineKeyboardButton(text="📦 Buyurtma berish", callback_data="order_cart")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def admin_order_keyboard(
    order_id: int,
    uid: int,
    status: str = "yangi",
) -> InlineKeyboardMarkup:
    """Buyurtma holatiga mos admin tugmalarini qaytaradi."""
    if status == "yangi":
        rows = [[
            InlineKeyboardButton(
                text="✅ Tasdiqlash",
                callback_data=f"admin_confirm:{order_id}:{uid}",
            ),
            InlineKeyboardButton(
                text="❌ Bekor qilish",
                callback_data=f"admin_cancel:{order_id}:{uid}",
            ),
        ]]
    elif status == "tasdiqlandi":
        rows = [[
            InlineKeyboardButton(text="🚚 Yuborildi", callback_data=f"admin_sent:{order_id}:{uid}"),
            InlineKeyboardButton(text="❌ Bekor qilish", callback_data=f"admin_cancel:{order_id}:{uid}"),
        ]]
    elif status == "yuborildi":
        rows = [[
            InlineKeyboardButton(text="✅ Yetkazildi", callback_data=f"admin_delivered:{order_id}:{uid}"),
            InlineKeyboardButton(text="↩️ Mijoz qabul qilmadi", callback_data=f"admin_refused:{order_id}:{uid}"),
        ]]
    else:
        # Yuborilgan yoki bekor qilingan buyurtmada faol tugma bo'lmaydi.
        rows = []

    return InlineKeyboardMarkup(inline_keyboard=rows)

def promo_type_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📊 Foiz (%)")],
        [KeyboardButton(text="💵 Belgilangan summa (so'm)")],
        [KeyboardButton(text="❌ Bekor qilish")],
    ], resize_keyboard=True)


# ═══════════════════════════════════════════════════
#  MA'LUMOTLAR BAZASI
# ═══════════════════════════════════════════════════
DB_PATH = os.getenv("BOT_DB_PATH", str(Path(__file__).resolve().parent / "data" / "orders.db"))
Path(DB_PATH).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS books (
                id           TEXT    PRIMARY KEY,
                name         TEXT    NOT NULL,
                author       TEXT    NOT NULL,
                price        INTEGER NOT NULL,
                description  TEXT,
                photo        TEXT,
                avg_rating   REAL    DEFAULT 0,
                rating_count INTEGER DEFAULT 0,
                sold_count   INTEGER DEFAULT 0,
                created_at   TEXT    NOT NULL
            );
            CREATE TABLE IF NOT EXISTS orders (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id        INTEGER NOT NULL,
                username       TEXT,
                full_name      TEXT,
                phone          TEXT,
                address        TEXT,
                lat            REAL,
                lon            REAL,
                payment_method TEXT,
                book_id        TEXT    NOT NULL,
                book_name      TEXT    NOT NULL,
                price          INTEGER NOT NULL,
                original_price INTEGER NOT NULL DEFAULT 0,
                promo_code     TEXT,
                status         TEXT    NOT NULL DEFAULT 'yangi',
                created_at     TEXT    NOT NULL,
                quantity       INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS ratings (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL,
                book_id    TEXT    NOT NULL,
                rating     INTEGER NOT NULL,
                created_at TEXT    NOT NULL,
                UNIQUE(user_id, book_id)
            );
            CREATE TABLE IF NOT EXISTS users (
                id         INTEGER PRIMARY KEY,
                username   TEXT,
                first_name TEXT,
                lang       TEXT DEFAULT 'uz',
                joined_at  TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS feedbacks (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL,
                username   TEXT,
                full_name  TEXT,
                message    TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS promo_codes (
                code       TEXT    PRIMARY KEY,
                discount   INTEGER NOT NULL,
                type       TEXT    NOT NULL DEFAULT 'percent',
                uses       INTEGER NOT NULL DEFAULT 0,
                max_uses   INTEGER NOT NULL DEFAULT 100,
                created_at TEXT    NOT NULL
            );
            CREATE TABLE IF NOT EXISTS carts (
                user_id INTEGER NOT NULL,
                book_id TEXT NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (user_id, book_id)
            );
            CREATE TABLE IF NOT EXISTS wishlists (
                user_id INTEGER NOT NULL,
                book_id TEXT NOT NULL,
                PRIMARY KEY (user_id, book_id)
            );
            CREATE TABLE IF NOT EXISTS reading_log (
                user_id INTEGER NOT NULL, book_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'reja', updated_at TEXT NOT NULL,
                PRIMARY KEY(user_id, book_id)
            );
            CREATE TABLE IF NOT EXISTS bundles (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '', price INTEGER NOT NULL,
                active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS bundle_items (
                bundle_id INTEGER NOT NULL, book_id TEXT NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY(bundle_id, book_id)
            );
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY, value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS referrals (
                inviter_id INTEGER NOT NULL, invited_id INTEGER NOT NULL UNIQUE,
                created_at TEXT NOT NULL, rewarded INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS stock_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT, book_id TEXT NOT NULL,
                change_qty INTEGER NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS reading_checkins (
                user_id INTEGER NOT NULL, checkin_date TEXT NOT NULL,
                minutes INTEGER NOT NULL DEFAULT 10, created_at TEXT NOT NULL,
                PRIMARY KEY(user_id, checkin_date)
            );
            CREATE TABLE IF NOT EXISTS daily_quiz (
                user_id INTEGER NOT NULL, quiz_date TEXT NOT NULL,
                q_index INTEGER NOT NULL DEFAULT 0, score INTEGER NOT NULL DEFAULT 0,
                finished INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(user_id, quiz_date)
            );
            CREATE TABLE IF NOT EXISTS reminder_settings (
                user_id INTEGER PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 0,
                last_sent_date TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_orders_user   ON orders(user_id);
            CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
        """)
        # quantity ustuni mavjud emasligini tekshirib qo'shamiz (eski DB uchun)
        # Eski bazalar uchun xavfsiz, takroran ishlaydigan migratsiyalar.
        for sql in (
            "ALTER TABLE books ADD COLUMN category TEXT NOT NULL DEFAULT 'Boshqa'",
            "ALTER TABLE books ADD COLUMN stock INTEGER NOT NULL DEFAULT -1",
            "ALTER TABLE users ADD COLUMN points INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE users ADD COLUMN referred_by INTEGER",
            "ALTER TABLE orders ADD COLUMN delivered_at TEXT",
            "ALTER TABLE orders ADD COLUMN points_used INTEGER NOT NULL DEFAULT 0",
        ):
            try:
                await db.execute(sql)
            except Exception:
                pass
        try:
            await db.execute("ALTER TABLE orders ADD COLUMN quantity INTEGER NOT NULL DEFAULT 1")
        except Exception:
            pass
        await db.commit()
    await asyncio.gather(load_books_from_db(), load_promos_from_db(), load_user_state_from_db())


async def load_user_state_from_db():
    """Savat va wishlist ma'lumotlarini SQLite bazasidan xotiraga yuklaydi."""
    global CARTS, WISHLISTS
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id, book_id, quantity FROM carts") as cur:
            cart_rows = await cur.fetchall()
        async with db.execute("SELECT user_id, book_id FROM wishlists") as cur:
            wishlist_rows = await cur.fetchall()
    CARTS = {}
    for user_id, book_id, quantity in cart_rows:
        CARTS.setdefault(user_id, {})[book_id] = quantity
    WISHLISTS = {}
    for user_id, book_id in wishlist_rows:
        WISHLISTS.setdefault(user_id, set()).add(book_id)


async def save_cart_to_db(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM carts WHERE user_id=?", (user_id,))
        items = [(user_id, book_id, qty) for book_id, qty in CARTS.get(user_id, {}).items()]
        if items:
            await db.executemany("INSERT INTO carts(user_id, book_id, quantity) VALUES (?, ?, ?)", items)
        await db.commit()


async def save_wishlist_to_db(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM wishlists WHERE user_id=?", (user_id,))
        items = [(user_id, book_id) for book_id in WISHLISTS.get(user_id, set())]
        if items:
            await db.executemany("INSERT INTO wishlists(user_id, book_id) VALUES (?, ?)", items)
        await db.commit()


async def load_books_from_db():
    global BOOKS
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT * FROM books ORDER BY created_at DESC") as cur:
            rows = await cur.fetchall()
    BOOKS = {
        r[0]: {
            "name": r[1], "author": r[2], "price": r[3],
            "description": r[4], "photo": r[5],
            "avg_rating": r[6] or 0, "rating_count": r[7] or 0,
            "sold_count": r[8] or 0,
        }
        for r in rows
    }


async def load_promos_from_db():
    global PROMO_CODES
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT code,discount,type,uses,max_uses FROM promo_codes") as cur:
            rows = await cur.fetchall()
    PROMO_CODES = {
        r[0]: {"discount": r[1], "type": r[2], "uses": r[3], "max_uses": r[4]}
        for r in rows
    }


async def save_book(bid, name, author, price, desc, photo):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT OR REPLACE INTO books
               (id,name,author,price,description,photo,avg_rating,rating_count,sold_count,created_at)
               VALUES (?,?,?,?,?,?,0,0,0,?)""",
            (bid, name, author, price, desc, photo, _now()),
        )
        await db.commit()
    await load_books_from_db()


async def delete_book(bid: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM books WHERE id=?", (bid,))
        await db.commit()
    await load_books_from_db()


async def save_order(uid, username, full_name, phone, address,
                     payment_method, book_id, book_name, price,
                     original_price, quantity=1, promo_code="",
                     lat=None, lon=None) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """INSERT INTO orders
               (user_id,username,full_name,phone,address,lat,lon,
                payment_method,book_id,book_name,price,original_price,
                promo_code,status,created_at,quantity)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (uid, username, full_name, phone, address, lat, lon,
             payment_method, book_id, book_name, price,
             original_price, promo_code, "yangi", _now(), quantity),
        )
        oid = cur.lastrowid
        await db.execute(
            "UPDATE books SET sold_count=sold_count+? WHERE id=?",
            (quantity, book_id)
        )
        await db.commit()
    return oid


async def update_order_status(order_id: int, status: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE orders SET status=? WHERE id=?", (status, order_id))
        await db.commit()


async def add_rating(uid: int, bid: str, rating: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO ratings(user_id,book_id,rating,created_at) VALUES(?,?,?,?)",
            (uid, bid, rating, _now()),
        )
        async with db.execute(
            "SELECT AVG(rating),COUNT(*) FROM ratings WHERE book_id=?", (bid,)
        ) as cur:
            avg, cnt = await cur.fetchone()
        await db.execute(
            "UPDATE books SET avg_rating=?,rating_count=? WHERE id=?",
            (round(avg or 0, 1), cnt or 0, bid),
        )
        await db.commit()
    await load_books_from_db()


async def register_user(user):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users(id,username,first_name,joined_at) VALUES(?,?,?,?)",
            (user.id, user.username, user.first_name, _now()),
        )
        await db.commit()


async def save_feedback(uid, username, full_name, text):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO feedbacks(user_id,username,full_name,message,created_at) VALUES(?,?,?,?,?)",
            (uid, username, full_name, text, _now()),
        )
        await db.commit()


async def save_promo(code, discount, ptype, max_uses):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO promo_codes(code,discount,type,uses,max_uses,created_at) VALUES(?,?,?,0,?,?)",
            (code, discount, ptype, max_uses, _now()),
        )
        await db.commit()
    await load_promos_from_db()


async def get_all_user_ids() -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id FROM users") as cur:
            return [r[0] for r in await cur.fetchall()]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ═══════════════════════════════════════════════════
#  /START
# ═══════════════════════════════════════════════════
@dp.message(CommandStart())
async def start_handler(message: Message, state: FSMContext):
    await state.clear()
    await register_user(message.from_user)
    # /start ref_<telegram_id> orqali taklif qilgan mijozni bir marta qayd etamiz.
    try:
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) > 1 and parts[1].startswith("ref_"):
            inviter = int(parts[1][4:])
            invited = message.from_user.id
            if inviter != invited:
                async with aiosqlite.connect(DB_PATH) as db:
                    async with db.execute("SELECT referred_by FROM users WHERE id=?", (invited,)) as cur:
                        row = await cur.fetchone()
                    if row and row[0] is None:
                        async with db.execute("SELECT id FROM users WHERE id=?", (inviter,)) as cur:
                            inviter_exists = await cur.fetchone()
                        if inviter_exists:
                            await db.execute("UPDATE users SET referred_by=? WHERE id=?", (inviter, invited))
                            await db.execute("INSERT OR IGNORE INTO referrals(inviter_id,invited_id,created_at) VALUES(?,?,?)", (inviter, invited, _now()))
                            await db.commit()
    except Exception:
        logger.exception("Referral havolasini qayd etishda xato")
    name = message.from_user.first_name or "Do'st"
    await message.answer(
        f"Assalomu alaykum, <b>{name}</b>! 👋\n\n"
        "📚 <b>Kitob do'konimizga xush kelibsiz!</b>\n\n"
        "❤️ Sevimli kitoblarni Wishlistga qo'shing\n"
        "🛒 Bir nechta kitob — savatga soling\n"
        "🎟️ Promo kod bilan chegirma oling\n"
        "⭐ Kitoblarga baho bering\n\n"
        "Quyidagi menyudan boshlang 👇",
        reply_markup=get_main_menu(message.from_user.id),
        parse_mode="HTML",
    )


@dp.message(Command("myid"))
async def myid_handler(message: Message):
    await message.answer(
        f"🆔 Sizning ID: <code>{message.from_user.id}</code>",
        parse_mode="HTML",
    )


# ═══════════════════════════════════════════════════
#  📚 KITOBLAR
# ═══════════════════════════════════════════════════
@dp.message(F.text == "📚 Kitoblar")
async def books_handler(message: Message):
    if not BOOKS:
        await message.answer(
            f"📭 Hozircha kitoblar mavjud emas.\n{ADMIN_USERNAME} ga murojaat qiling.",
            reply_markup=get_main_menu(message.from_user.id),
        )
        return
    await message.answer(
        f"📚 <b>Mavjud kitoblar ({len(BOOKS)} ta):</b>\n\nKitobni tanlang 👇",
        reply_markup=books_keyboard(),
        parse_mode="HTML",
    )
    await message.answer("Saralash:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="💸 Arzonidan", callback_data="sort:price"),
        InlineKeyboardButton(text="🆕 Yangilari", callback_data="sort:new"),
    ],[InlineKeyboardButton(text="📚 Kategoriyalar", callback_data="categories")]]))


# ═══════════════════════════════════════════════════
#  🔍 QIDIRUV
# ═══════════════════════════════════════════════════
@dp.message(F.text == "🔍 Qidirish")
async def search_start(message: Message, state: FSMContext):
    await state.set_state(SearchState.waiting_search_query)
    await message.answer(
        "🔍 Kitob nomi yoki muallif ismini yozing:",
        reply_markup=cancel_keyboard,
    )


@dp.message(SearchState.waiting_search_query)
async def search_query(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("Bosh menyu 👇", reply_markup=get_main_menu(message.from_user.id))
        return
    q = message.text.strip().lower()
    results = [
        bid for bid, b in BOOKS.items()
        if q in b["name"].lower() or q in b["author"].lower()
        or q in (b.get("description") or "").lower()
    ]
    await state.clear()
    if not results:
        await message.answer(
            f"❌ <b>'{message.text}'</b> bo'yicha hech narsa topilmadi.\n"
            f"Admin: {ADMIN_USERNAME}",
            reply_markup=get_main_menu(message.from_user.id),
            parse_mode="HTML",
        )
        return
    await message.answer(
        f"🔍 <b>{len(results)} ta natija topildi:</b>",
        reply_markup=books_keyboard(source=results),
        parse_mode="HTML",
    )


# ═══════════════════════════════════════════════════
#  ❤️ WISHLIST
# ═══════════════════════════════════════════════════
@dp.message(F.text.startswith("❤️ Wishlist"))
async def wishlist_handler(message: Message):
    uid = message.from_user.id
    wl  = get_wishlist(uid)
    if not wl:
        await message.answer(
            "❤️ <b>Wishlist bo'sh</b>\n\n"
            "Kitob sahifasida <b>❤️ Wishlistga qo'shish</b> tugmasini bosing.",
            parse_mode="HTML",
        )
        return
    valid = [bid for bid in wl if bid in BOOKS]
    if not valid:
        WISHLISTS.pop(uid, None)
        await message.answer("❤️ Wishlist bo'sh.")
        return
    await message.answer(
        f"❤️ <b>Sizning Wishlistingiz ({len(valid)} ta kitob):</b>",
        reply_markup=books_keyboard(source=valid),
        parse_mode="HTML",
    )


@dp.callback_query(F.data.startswith("wl_toggle:"))
async def wl_toggle(callback: CallbackQuery):
    bid = callback.data.split(":", 1)[1]
    uid = callback.from_user.id
    if uid not in WISHLISTS:
        WISHLISTS[uid] = set()
    if bid in WISHLISTS[uid]:
        WISHLISTS[uid].discard(bid)
        await callback.answer("💔 Wishlistdan olib tashlandi")
    else:
        WISHLISTS[uid].add(bid)
        await callback.answer("❤️ Wishlistga qo'shildi!")
    await save_wishlist_to_db(uid)
    try:
        await callback.message.edit_reply_markup(
            reply_markup=book_detail_keyboard(bid, uid)
        )
    except TelegramBadRequest:
        pass


# ═══════════════════════════════════════════════════
#  🛒 SAVATCHA
# ═══════════════════════════════════════════════════
@dp.message(F.text.startswith("🛒"))
async def cart_handler(message: Message):
    uid  = message.from_user.id
    cart = get_cart(uid)
    if not cart:
        await message.answer(
            "🛒 <b>Savatchangiz bo'sh</b>\n\n"
            "Kitob tanlab <b>🛒 Savatga qo'shish</b> tugmasini bosing.\n"
            "Bir xil kitobdan <b>bir nechta nusxa</b> qo'shishingiz mumkin!",
            parse_mode="HTML",
        )
        return
    text  = "🛒 <b>Sizning savatchingiz:</b>\n\n"
    total = 0
    for bid, qty in cart.items():
        if bid not in BOOKS:
            continue
        b   = BOOKS[bid]
        sub = b["price"] * qty
        total += sub
        text += f"📖 <b>{b['name']}</b>\n   {qty} × {fmt(b['price'])} = <b>{fmt(sub)} so'm</b>\n\n"
    text += f"━━━━━━━━━━━━━━━━\n💰 Jami: <b>{fmt(total)} so'm</b>"
    await message.answer(text, reply_markup=cart_keyboard(uid), parse_mode="HTML")


@dp.callback_query(F.data.startswith("cart_add:"))
async def cart_add(callback: CallbackQuery):
    bid = callback.data.split(":", 1)[1]
    uid = callback.from_user.id
    if bid not in BOOKS:
        await callback.answer("Kitob topilmadi.", show_alert=True)
        return
    CARTS.setdefault(uid, {})[bid] = CARTS.get(uid, {}).get(bid, 0) + 1
    qty = CARTS[uid][bid]
    await save_cart_to_db(uid)
    await callback.answer(f"✅ Savatga qo'shildi ({qty} ta)")
    try:
        await callback.message.edit_reply_markup(reply_markup=book_detail_keyboard(bid, uid))
    except TelegramBadRequest:
        pass


@dp.callback_query(F.data.startswith("cart_remove:"))
async def cart_remove(callback: CallbackQuery):
    bid = callback.data.split(":", 1)[1]
    uid = callback.from_user.id
    if uid in CARTS and bid in CARTS[uid]:
        CARTS[uid][bid] -= 1
        if CARTS[uid][bid] <= 0:
            del CARTS[uid][bid]
        if not CARTS[uid]:
            del CARTS[uid]
    await save_cart_to_db(uid)
    await callback.answer("➖ Kamaytirildi")
    try:
        await callback.message.edit_reply_markup(reply_markup=book_detail_keyboard(bid, uid))
    except TelegramBadRequest:
        pass


@dp.callback_query(F.data == "cart_clear")
async def cart_clear(callback: CallbackQuery):
    CARTS.pop(callback.from_user.id, None)
    await save_cart_to_db(callback.from_user.id)
    await callback.answer("🗑️ Savatcha tozalandi!", show_alert=True)
    try:
        await callback.message.edit_text("🛒 Savatchangiz bo'sh.")
    except TelegramBadRequest:
        pass


@dp.callback_query(F.data == "view_cart")
async def view_cart_cb(callback: CallbackQuery):
    uid  = callback.from_user.id
    cart = get_cart(uid)
    if not cart:
        await callback.answer("Savatcha bo'sh.", show_alert=True)
        return
    text  = "🛒 <b>Savatcha:</b>\n\n"
    total = 0
    for bid, qty in cart.items():
        if bid not in BOOKS:
            continue
        b   = BOOKS[bid]
        sub = b["price"] * qty
        total += sub
        text += f"📖 {b['name']} ×{qty} = <b>{fmt(sub)} so'm</b>\n"
    text += f"\n💰 Jami: <b>{fmt(total)} so'm</b>"
    await callback.message.answer(text, reply_markup=cart_keyboard(uid), parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data == "order_cart")
async def order_cart_cb(callback: CallbackQuery, state: FSMContext):
    uid  = callback.from_user.id
    cart = get_cart(uid)
    if not cart:
        await callback.answer("Savatcha bo'sh!", show_alert=True)
        return
    await state.update_data(order_type="cart")
    await state.set_state(OrderState.waiting_full_name)
    total = cart_total(uid)
    cnt   = cart_count(uid)
    await callback.message.answer(
        f"📦 <b>Savatcha buyurtmasi</b>\n\n"
        f"🛒 {cnt} ta kitob | 💰 {fmt(total)} so'm\n\n"
        f"1️⃣ Ism-familiyangizni yozing:",
        reply_markup=cancel_keyboard,
        parse_mode="HTML",
    )
    await callback.answer()


# ═══════════════════════════════════════════════════
#  📖 KITOB BATAFSIL
# ═══════════════════════════════════════════════════
@dp.callback_query(F.data == "back:books")
async def back_books(callback: CallbackQuery):
    if not BOOKS:
        await callback.message.answer("📭 Kitoblar yo'q.")
    else:
        await callback.message.answer("📚 Kitoblar:", reply_markup=books_keyboard())
    await callback.answer()


@dp.callback_query(F.data.startswith("page:"))
async def page_cb(callback: CallbackQuery):
    page = int(callback.data.split(":")[1])
    try:
        await callback.message.edit_reply_markup(reply_markup=books_keyboard(page=page))
    except TelegramBadRequest:
        await callback.message.answer("📚 Kitoblar:", reply_markup=books_keyboard(page=page))
    await callback.answer()


@dp.callback_query(F.data.startswith("sort:"))
async def sort_books_cb(callback: CallbackQuery):
    mode=callback.data.split(":",1)[1]
    async with aiosqlite.connect(DB_PATH) as db:
        order="price ASC" if mode=="price" else "created_at DESC"
        async with db.execute(f"SELECT id FROM books ORDER BY {order}") as cur: ids=[r[0] for r in await cur.fetchall()]
    ids=[bid for bid in ids if bid in BOOKS]
    await callback.message.answer("📚 Saralangan kitoblar:",reply_markup=books_keyboard(source=ids))
    await callback.answer()

@dp.callback_query(F.data == "noop")
async def noop_cb(callback: CallbackQuery):
    await callback.answer()


@dp.callback_query(F.data.startswith("book:"))
async def book_detail_cb(callback: CallbackQuery):
    bid = callback.data.split(":", 1)[1]
    if bid not in BOOKS:
        await callback.answer("Bu kitob mavjud emas.", show_alert=True)
        return
    b    = BOOKS[bid]
    avg  = b.get("avg_rating", 0)
    cnt  = b.get("rating_count", 0)
    sold = b.get("sold_count", 0)
    rating_txt = f"⭐ {avg}/5 ({cnt} baho)" if cnt else "⭐ Hali baholanmagan"

    caption = (
        f"📖 <b>{b['name']}</b>\n"
        f"✍️ Muallif: {b['author']}\n"
        f"💰 Narx: <b>{fmt(b['price'])} so'm</b>\n"
        f"{rating_txt} | 🛒 {sold} ta sotilgan\n\n"
        f"📝 {b.get('description') or 'Tavsif yoq'}\n\n"
        f"➕/➖ tugmalar bilan miqdorni sozlang"
    )
    kb = book_detail_keyboard(bid, callback.from_user.id)
    try:
        if b.get("photo"):
            await callback.message.answer_photo(
                photo=b["photo"], caption=caption, reply_markup=kb, parse_mode="HTML"
            )
        else:
            await callback.message.answer(caption, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await callback.message.answer(caption, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


# ═══════════════════════════════════════════════════
#  ⭐ REYTING
# ═══════════════════════════════════════════════════
@dp.callback_query(F.data.startswith("rate:"))
async def rate_cb(callback: CallbackQuery):
    bid = callback.data.split(":", 1)[1]
    if bid not in BOOKS:
        await callback.answer("Kitob topilmadi.", show_alert=True)
        return
    await callback.message.answer(
        f"⭐ <b>{BOOKS[bid]['name']}</b> kitobiga baho bering:",
        reply_markup=rating_keyboard(bid),
        parse_mode="HTML",
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("rating:"))
async def rating_submit(callback: CallbackQuery):
    _, bid, r = callback.data.split(":")
    rating = int(r)
    await add_rating(callback.from_user.id, bid, rating)
    await callback.answer(f"Rahmat! Bahoyingiz: {'⭐'*rating}", show_alert=True)
    try:
        await callback.message.delete()
    except Exception:
        pass


# ═══════════════════════════════════════════════════
#  🎟️ PROMO KOD (Foydalanuvchi)
# ═══════════════════════════════════════════════════
@dp.message(F.text == "🎟️ Promo kod")
async def promo_user_info(message: Message):
    await message.answer(
        "🎟️ <b>Promo kod</b>\n\n"
        "Promo kod orqali chegirma olishingiz mumkin.\n"
        "Buyurtma berish jarayonida promo kod kiritish so'raladi.\n\n"
        f"Promo kod olish uchun: {ADMIN_USERNAME}",
        parse_mode="HTML",
    )


# ═══════════════════════════════════════════════════
#  📦 BUYURTMALARIM
# ═══════════════════════════════════════════════════
@dp.message(F.text == "📦 Buyurtmalarim")
async def my_orders(message: Message):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT * FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 10",
            (message.from_user.id,)
        ) as cur:
            rows = await cur.fetchall()
    if not rows:
        await message.answer(
            "📭 Hali buyurtmalar yo'q.\n<b>📚 Kitoblar</b> bo'limiga o'ting.",
            parse_mode="HTML",
        )
        return
    await message.answer(f"📦 <b>Buyurtmalaringiz ({len(rows)} ta):</b>", parse_mode="HTML")
    for row in rows:
        emoji = {"yangi": "🆕", "tasdiqlandi": "✅", "yuborildi": "🚚", "yetkazildi": "📬", "mijoz qabul qilmadi": "↩️", "bekor qilindi": "❌"}.get(row[14], "📌")
        qty = row[16] if len(row) > 16 else 1
        promo_line = f"\n🎟️ Promo: {row[13]}" if row[13] else ""
        qty_line   = f"\n📦 Miqdor: {qty} ta" if qty > 1 else ""
        text = (
            f"━━━━━━━━━━━━━━━━\n"
            f"🧾 Buyurtma #{row[0]}\n"
            f"📖 {row[9]}{qty_line}\n"
            f"💰 {fmt(row[11])} so'm{promo_line}\n"
            f"{emoji} {row[14]}\n"
            f"🕒 {row[15]}\n"
            f"━━━━━━━━━━━━━━━━"
        )
        await message.answer(text)


# ═══════════════════════════════════════════════════
#  💬 FIKR BILDIRISH
# ═══════════════════════════════════════════════════
@dp.message(F.text == "💬 Fikr")
async def feedback_start(message: Message, state: FSMContext):
    await state.set_state(FeedbackState.waiting_feedback)
    await message.answer(
        "💬 Fikr, taklif yoki shikoyatingizni yozing:",
        reply_markup=cancel_keyboard,
    )


@dp.message(FeedbackState.waiting_feedback)
async def feedback_receive(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=get_main_menu(message.from_user.id))
        return
    await save_feedback(
        message.from_user.id, message.from_user.username,
        message.from_user.full_name, message.text,
    )
    await safe_send(bot.send_message(
        ADMIN_ID,
        f"💬 <b>Yangi fikr</b>\n"
        f"👤 @{message.from_user.username or 'yoq'} ({message.from_user.full_name})\n"
        f"🆔 {message.from_user.id}\n\n"
        f"📝 {message.text}",
        parse_mode="HTML",
    ))
    await state.clear()
    await message.answer("✅ Fikringiz uchun rahmat!", reply_markup=get_main_menu(message.from_user.id))


# ═══════════════════════════════════════════════════
#  ℹ️ ALOQA
# ═══════════════════════════════════════════════════
@dp.message(F.text == "ℹ️ Aloqa")
async def contact_handler(message: Message):
    await message.answer(
        "📞 <b>Aloqa</b>\n"
        "━━━━━━━━━━━━━━━━\n"
        f"👤 Admin: {ADMIN_USERNAME}\n"
        f"📱 Tel: {ADMIN_PHONE}\n"
        "━━━━━━━━━━━━━━━━\n"
        "Savol va takliflar uchun murojaat qiling!",
        parse_mode="HTML",
    )


# ═══════════════════════════════════════════════════
#  FSM BUYURTMA — ISM
# ═══════════════════════════════════════════════════
@dp.callback_query(F.data.startswith("order_now:"))
async def start_order_now_cb(callback: CallbackQuery, state: FSMContext):
    """Hoziroq buyurtma — savatdagi miqdorni hisobga oladi."""
    bid = callback.data.split(":", 1)[1]
    if bid not in BOOKS:
        await callback.answer("Kitob mavjud emas.", show_alert=True)
        return
    uid  = callback.from_user.id
    cart = get_cart(uid)
    qty  = cart.get(bid, 1)   # Savatchadagi miqdor, aks holda 1
    await state.update_data(book_id=bid, order_type="single", quantity=qty)
    await state.set_state(OrderState.waiting_full_name)
    b = BOOKS[bid]
    qty_line = f"📦 Miqdor: {qty} ta\n" if qty > 1 else ""
    await callback.message.answer(
        f"📦 <b>Buyurtma berish</b>\n\n"
        f"📖 {b['name']}\n"
        f"{qty_line}"
        f"💰 {fmt(b['price'] * qty)} so'm\n\n"
        f"1️⃣ Ism-familiyangizni yozing:",
        reply_markup=cancel_keyboard,
        parse_mode="HTML",
    )
    await callback.answer()


@dp.message(OrderState.waiting_full_name)
async def get_full_name(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=get_main_menu(message.from_user.id))
        return
    name = message.text.strip()
    if len(name) < 3:
        await message.answer("❌ Kamida 3 harf kiriting.")
        return
    await state.update_data(full_name=name)
    await state.set_state(OrderState.waiting_phone)
    await message.answer(
        f"✅ Ism: <b>{name}</b>\n\n"
        "2️⃣ Telefon raqamingizni ulashing:",
        reply_markup=phone_keyboard(),
        parse_mode="HTML",
    )


# ═══════════════════════════════════════════════════
#  FSM — TELEFON
# ═══════════════════════════════════════════════════
@dp.message(OrderState.waiting_phone, F.contact)
async def get_contact(message: Message, state: FSMContext):
    phone = message.contact.phone_number
    if not phone.startswith("+"):
        phone = "+" + phone
    await state.update_data(phone=phone)
    await state.set_state(OrderState.waiting_address)
    await message.answer(
        f"✅ Telefon: <b>{phone}</b>\n\n"
        "3️⃣ <b>Yetkazib berish manzili</b>\n\n"
        "📍 <b>Joylashuvimni yuborish</b> tugmasini bosing\n"
        "   ➜ Telegram qurilmangizdan <b>joylashuvni yoqib</b> yuboring\n\n"
        "✍️ Yoki manzilni qo'lda yozing",
        reply_markup=address_keyboard(),
        parse_mode="HTML",
    )


@dp.message(OrderState.waiting_phone, F.text == "✍️ Raqamni qo'lda yozish")
async def phone_manual(message: Message):
    await message.answer(
        "📱 Telefon raqamingizni yozing:\nMasalan: +998901234567",
        reply_markup=cancel_keyboard,
    )


@dp.message(OrderState.waiting_phone)
async def get_phone_text(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=get_main_menu(message.from_user.id))
        return
    phone = message.text.strip()
    if len(phone) < 9:
        await message.answer("❌ Noto'g'ri raqam. Masalan: +998901234567")
        return
    await state.update_data(phone=phone)
    await state.set_state(OrderState.waiting_address)
    await message.answer(
        f"✅ Telefon: <b>{phone}</b>\n\n"
        "3️⃣ <b>Yetkazib berish manzili</b>\n\n"
        "📍 <b>Joylashuvimni yuborish</b> tugmasini bosing\n"
        "   ➜ Telegram qurilmangizdan <b>joylashuvni yoqib</b> yuboring\n\n"
        "✍️ Yoki manzilni qo'lda yozing",
        reply_markup=address_keyboard(),
        parse_mode="HTML",
    )


# ══════════════════════════════════════════════════════════════
#  FSM — MANZIL: GPS (tugma orqali, avtomatik)
# ══════════════════════════════════════════════════════════════
@dp.message(OrderState.waiting_address, F.location)
async def get_location(message: Message, state: FSMContext):
    lat = message.location.latitude
    lon = message.location.longitude
    maps = f"https://maps.google.com/?q={lat},{lon}"
    await state.update_data(
        address=f"📍 GPS: {lat:.5f}, {lon:.5f}",
        lat=lat,
        lon=lon,
    )
    await state.set_state(OrderState.waiting_promo)
    await message.answer(
        f"✅ <b>Joylashuv qabul qilindi!</b>\n"
        f"📍 <a href='{maps}'>Xaritada ko'rish</a>\n\n"
        "4️⃣ 🎟️ <b>Promo kodingiz bormi?</b>\n\n"
        "Promo kodingizni yozing.\n"
        "Agar kod yo'q bo'lsa — <b>⏭️ O'tkazib yuborish</b> tugmasini bosing:",
        reply_markup=promo_skip_keyboard(),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


# ══════════════════════════════════════════════════════════════
#  FSM — MANZIL: QO'LDA YOZISH
# ══════════════════════════════════════════════════════════════
@dp.message(OrderState.waiting_address, F.text == "✍️ Manzilni qo'lda yozish")
async def address_manual(message: Message):
    await message.answer(
        "🏠 Shahar, tuman, ko'cha, uy raqamini yozing:",
        reply_markup=cancel_keyboard,
    )


@dp.message(OrderState.waiting_address)
async def get_address_text(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=get_main_menu(message.from_user.id))
        return
    addr = message.text.strip()
    if len(addr) < 5:
        await message.answer(
            "❌ Manzilni to'liqroq yozing.\n\n"
            "Yoki GPS orqali ulashing:",
            reply_markup=address_keyboard(),
        )
        return
    await state.update_data(address=addr, lat=None, lon=None)
    await state.set_state(OrderState.waiting_promo)
    await message.answer(
        f"✅ Manzil: <b>{addr}</b>\n\n"
        "4️⃣ 🎟️ <b>Promo kodingiz bormi?</b>\n\n"
        "Promo kodingizni yozing.\n"
        "Agar kod yo'q bo'lsa — <b>⏭️ O'tkazib yuborish</b> tugmasini bosing:",
        reply_markup=promo_skip_keyboard(),
        parse_mode="HTML",
    )


# ═══════════════════════════════════════════════════
#  FSM — PROMO KOD
#  ✅ FAQAT TUGMA: ⏭️ O'tkazib yuborish
#  Matnda ham promo kod kiritish mumkin (ixtiyoriy)
# ═══════════════════════════════════════════════════
@dp.message(OrderState.waiting_promo)
async def get_promo(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=get_main_menu(message.from_user.id))
        return

    promo_code = ""
    promo_desc = ""

    # Ballar 100 ball = 5 000 so'm chegirma; buyurtma qiymatidan oshmaydi.
    if message.text == "⭐ Ball ishlatish":
        data = await state.get_data()
        uid = message.from_user.id
        if data.get("order_type") == "cart":
            total = cart_total(uid)
        else:
            total = BOOKS.get(data.get("book_id", ""), {}).get("price", 0) * data.get("quantity", 1)
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT COALESCE(points,0) FROM users WHERE id=?", (uid,)) as cur:
                row = await cur.fetchone()
        points = row[0] if row else 0
        use_points = min(points, (total // 5000) * 100)
        discount = (use_points // 100) * 5000
        if use_points < 100 or discount <= 0:
            await message.answer("Ball ishlatish uchun kamida 100 ball va 5 000 so'mlik buyurtma kerak.", reply_markup=promo_skip_keyboard())
            return
        await state.update_data(points_to_use=use_points, points_discount=discount)
        await message.answer(f"✅ {use_points} ball ishlatiladi. Chegirma: {fmt(discount)} so'm. Qolgan promo kodingiz bo'lsa yozing yoki o'tkazib yuboring.", reply_markup=promo_skip_keyboard())
        return

    # ⏭️ tugmasi bosildi — o'tkazib yuborish
    if message.text != "⏭️ O'tkazib yuborish":
        code = message.text.strip().upper()
        data = await state.get_data()
        uid  = message.from_user.id

        if data.get("order_type") == "cart":
            total = cart_total(uid)
        else:
            qty   = data.get("quantity", 1)
            total = BOOKS.get(data.get("book_id", ""), {}).get("price", 0) * qty

        new_total, promo_desc = apply_promo(total, code)
        if promo_desc:
            promo_code = code
            await state.update_data(promo_code=code, promo_desc=promo_desc)
            await message.answer(
                f"✅ Promo kod qo'llandi!\n{promo_desc}\n\n"
                f"💰 Yangi narx: <b>{fmt(new_total)} so'm</b>",
                parse_mode="HTML",
            )
        else:
            await message.answer(
                "❌ Promo kod noto'g'ri yoki muddati tugagan.\n"
                "Davom ettirilmoqda...",
            )

    await state.set_state(OrderState.waiting_payment)
    await message.answer(
        "5️⃣ To'lov usulini tanlang 👇",
        reply_markup=payment_keyboard,
    )


# ═══════════════════════════════════════════════════
#  FSM — TO'LOV
# ═══════════════════════════════════════════════════
@dp.message(OrderState.waiting_payment)
async def get_payment(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=get_main_menu(message.from_user.id))
        return

    allowed = {"💳 Humo": "Humo", "💳 Visa": "Visa", "💵 Naqd": "Naqd"}
    if message.text not in allowed:
        await message.answer("❌ Tugmalardan birini tanlang.")
        return

    pm   = allowed[message.text]
    data = await state.get_data()
    uid  = message.from_user.id

    if data.get("order_type") == "cart":
        original = cart_total(uid)
    else:
        qty      = data.get("quantity", 1)
        original = BOOKS.get(data.get("book_id", ""), {}).get("price", 0) * qty

    promo_code = data.get("promo_code", "")
    promo_desc = data.get("promo_desc", "")
    # Birinchi buyurtmaga 10% avtomatik chegirma (promo kod bilan birga emas).
    first_order_discount = 0
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM orders WHERE user_id=?", (uid,)) as cur:
            prior_orders = (await cur.fetchone())[0]
    if promo_code:
        p = PROMO_CODES.get(promo_code, {})
        if p and (p.get("max_uses", 0) <= 0 or p.get("uses", 0) < p.get("max_uses", 0)):
            if p.get("type") == "percent":
                final = max(0, original - int(original * p["discount"] / 100))
            else:
                final = max(0, original - min(original, p["discount"]))
        else:
            # Promo endi yaroqsiz bo'lsa, buyurtma narxini xavfsiz qayta hisoblaymiz.
            promo_code = ""
            promo_desc = ""
            final = max(0, original - int(original * 0.10)) if prior_orders == 0 else original
            if prior_orders == 0:
                promo_desc = "🎉 Birinchi buyurtma chegirmasi: -10%"
    elif prior_orders == 0:
        first_order_discount = int(original * 0.10)
        final = original - first_order_discount
        promo_desc = "🎉 Birinchi buyurtma chegirmasi: -10%"
    else:
        final = original

    # Savat aynan to'plam tarkibiga mos bo'lsa, avval maxsus narxni qo'llaymiz.
    # Birinchi buyurtma chegirmasi yoki promo kod bilan birga qo'shib hisoblamaymiz.
    bundle_applied = False
    if data.get("order_type") == "cart" and not promo_code and prior_orders != 0:
        cart_now = {k: int(v) for k, v in get_cart(uid).items() if k in BOOKS}
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT id,price FROM bundles WHERE active=1") as cur:
                bundle_rows = await cur.fetchall()
            for bundle_id, bundle_price in bundle_rows:
                async with db.execute("SELECT book_id,quantity FROM bundle_items WHERE bundle_id=?", (bundle_id,)) as cur:
                    bundle_items = {r[0]: int(r[1]) for r in await cur.fetchall()}
                if bundle_items and bundle_items == cart_now:
                    final = max(0, int(bundle_price))
                    promo_desc = f"🎁 To'plam narxi qo'llandi: {fmt(bundle_price)} so'm"
                    bundle_applied = True
                    break

    # Faqat amalda qo'llangan chegirmaga mos ballni yechamiz:
    # 100 ball = 5 000 so'm. Chegirma buyurtma narxidan oshmaydi.
    requested_points_discount = max(0, int(data.get("points_discount", 0) or 0))
    points_discount = min(requested_points_discount, final)
    points_to_use_actual = (points_discount // 5000) * 100
    points_discount = points_to_use_actual // 100 * 5000
    final = max(0, final - points_discount)
    if points_discount:
        promo_desc += f"\n⭐ Ball chegirmasi: -{fmt(points_discount)} so'm"
    await state.update_data(
        payment_method=pm, final_price=final, original_price=original,
        points_to_use=points_to_use_actual, promo_code=promo_code, promo_desc=promo_desc,
    )

    if pm in ("Humo", "Visa"):
        card = HUMO_CARD if pm == "Humo" else VISA_CARD
        await state.set_state(OrderState.waiting_check)
        promo_line = f"\n{promo_desc}" if promo_desc else ""
        await message.answer(
            f"💳 <b>{pm} orqali to'lov</b>\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"👤 Karta egasi:\n"
            f"<b>{CARD_HOLDER}</b>\n\n"
            f"💳 Karta raqami:\n"
            f"<code>{card}</code>\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"💰 To'lov summasi: <b>{fmt(final)} so'm</b>"
            f"{promo_line}\n\n"
            f"✅ To'lovni amalga oshirib, <b>chek (screenshot)</b> yuboring:",
            reply_markup=cancel_keyboard,
            parse_mode="HTML",
        )
    else:
        await complete_order(message, state, has_check=False)


# ═══════════════════════════════════════════════════
#  FSM — CHEK
# ═══════════════════════════════════════════════════
@dp.message(OrderState.waiting_check)
async def get_check(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=get_main_menu(message.from_user.id))
        return
    if not message.photo and not message.document:
        await message.answer(
            "❌ To'lov chekini <b>rasm</b> yoki <b>fayl</b> ko'rinishida yuboring.",
            parse_mode="HTML",
        )
        return
    await complete_order(message, state, has_check=True)


# ═══════════════════════════════════════════════════
#  BUYURTMANI YAKUNLASH
# ═══════════════════════════════════════════════════
async def complete_order(message: Message, state: FSMContext, has_check: bool = False):
    data           = await state.get_data()
    uid            = message.from_user.id
    order_type     = data.get("order_type", "single")
    full_name      = data["full_name"]
    phone          = data["phone"]
    address        = data["address"]
    pm             = data["payment_method"]
    lat            = data.get("lat")
    lon            = data.get("lon")
    promo_code     = data.get("promo_code", "")
    final_price    = data.get("final_price", 0)
    original_price = data.get("original_price", 0)

    order_ids  = []
    book_lines = ""
    first_oid  = 0

    if order_type == "cart":
        cart  = get_cart(uid)
        tasks = []
        for bid, qty in cart.items():
            if bid not in BOOKS:
                continue
            b = BOOKS[bid]
            ratio      = (b["price"] * qty) / original_price if original_price else 1
            item_price = round(final_price * ratio) if final_price != original_price else b["price"] * qty
            book_lines += f"  📖 {b['name']} ×{qty} = {fmt(b['price']*qty)} so'm\n"
            tasks.append(save_order(
                uid=uid, username=message.from_user.username,
                full_name=full_name, phone=phone, address=address,
                payment_method=pm, book_id=bid, book_name=b["name"],
                price=item_price, original_price=b["price"] * qty,
                quantity=qty, promo_code=promo_code, lat=lat, lon=lon,
            ))
        results   = await asyncio.gather(*tasks)
        order_ids = list(results)
        CARTS.pop(uid, None)
        first_oid = order_ids[0] if order_ids else 0

        promo_line = f"\n🎟️ Promo: {promo_code}" if promo_code else (f"\n{data.get('promo_desc', '')}" if data.get("promo_desc") else "")
        ids_str    = ", #".join(str(i) for i in order_ids)
        admin_text = (
            f"🛒 <b>Yangi savatcha buyurtma</b>\n"
            f"🧾 #{ids_str}\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"👤 @{message.from_user.username or 'yoq'} (ID: {uid})\n"
            f"🙍 {full_name} | 📞 {phone}\n"
            f"🏠 {address}\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"📚 Kitoblar:\n{book_lines}"
            f"💰 Asl: {fmt(original_price)} → To'lov: <b>{fmt(final_price)} so'm</b>{promo_line}\n"
            f"💳 {pm} | {'✅ Chek bor' if has_check else '💵 Naqd'}\n"
            f"━━━━━━━━━━━━━━━━\n🕒 {_now()}"
        )
        user_text = (
            f"🎉 <b>Buyurtmangiz qabul qilindi!</b>\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"🧾 #{ids_str}\n"
            f"📚 Kitoblar:\n{book_lines}"
            f"💰 Jami: <b>{fmt(final_price)} so'm</b>{promo_line}\n"
            f"💳 {pm}\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"⏳ Admin tasdiqlashini kuting.\n"
            f"Savollar: {ADMIN_USERNAME}"
        )

    else:
        # Bitta kitob — savatchadagi miqdor bilan
        bid      = data["book_id"]
        b        = BOOKS[bid]
        qty      = data.get("quantity", 1)
        price    = data.get("final_price", b["price"] * qty)
        orig     = b["price"] * qty
        oid      = await save_order(
            uid=uid, username=message.from_user.username,
            full_name=full_name, phone=phone, address=address,
            payment_method=pm, book_id=bid, book_name=b["name"],
            price=price, original_price=orig,
            quantity=qty, promo_code=promo_code, lat=lat, lon=lon,
        )
        order_ids = [oid]
        first_oid = oid

        qty_line   = f"📦 Miqdor: {qty} ta\n" if qty > 1 else ""
        promo_line = f"\n🎟️ Promo: {promo_code}" if promo_code else (f"\n{data.get('promo_desc', '')}" if data.get("promo_desc") else "")
        admin_text = (
            f"🛒 <b>Yangi buyurtma #{oid}</b>\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"👤 @{message.from_user.username or 'yoq'} (ID: {uid})\n"
            f"🙍 {full_name} | 📞 {phone}\n"
            f"🏠 {address}\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"📖 <b>{b['name']}</b> — {b['author']}\n"
            f"{qty_line}"
            f"💰 Asl: {fmt(orig)} → To'lov: <b>{fmt(price)} so'm</b>{promo_line}\n"
            f"💳 {pm} | {'✅ Chek bor' if has_check else '💵 Naqd'}\n"
            f"━━━━━━━━━━━━━━━━\n🕒 {_now()}"
        )
        user_text = (
            f"🎉 <b>Buyurtmangiz qabul qilindi!</b>\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"🧾 Buyurtma #{oid}\n"
            f"📖 <b>{b['name']}</b>\n"
            f"{qty_line}"
            f"💰 <b>{fmt(price)} so'm</b>{promo_line}\n"
            f"💳 {pm}\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"⏳ Admin tasdiqlashini kuting.\n"
            f"Savollar: {ADMIN_USERNAME}"
        )

    # Promo ishlatilishini faqat saqlangan buyurtmadan keyin bir marta hisoblaymiz.
    if promo_code and order_ids:
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "UPDATE promo_codes SET uses=uses+1 WHERE code=? AND (max_uses<=0 OR uses<max_uses)",
                (promo_code,),
            )
            await db.commit()
        if cur.rowcount and promo_code in PROMO_CODES:
            PROMO_CODES[promo_code]["uses"] = int(PROMO_CODES[promo_code].get("uses", 0)) + 1

    # Ballar faqat buyurtma yuborilganda yechiladi; bekor qilinsa admin amalida qaytariladi.
    points_used = int(data.get("points_to_use", 0) or 0)
    if points_used and order_ids:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT COALESCE(points,0) FROM users WHERE id=?", (uid,)) as cur:
                prow = await cur.fetchone()
            available = int(prow[0]) if prow else 0
            points_used = min(points_used, available)
            await db.execute("UPDATE users SET points=MAX(0,COALESCE(points,0)-?) WHERE id=?", (points_used, uid))
            # Refundni bir marta bajarish uchun faqat birinchi orderga yozamiz.
            await db.execute("UPDATE orders SET points_used=? WHERE id=?", (points_used, order_ids[0]))
            await db.commit()

    # Admin uchun har bir kitob buyurtmasi alohida boshqariladi.
    # Savatdagi barcha buyurtmalar uchun alohida status tugmalari chiqadi.
    if order_type == "cart":
        for oid in order_ids:
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute("SELECT book_name, quantity, price, payment_method, status FROM orders WHERE id=?", (oid,)) as cur:
                    item_row = await cur.fetchone()
            if not item_row:
                continue
            item_name, item_qty, item_price, item_payment, item_status = item_row
            individual = (
                f"🛒 <b>Yangi buyurtma #{oid}</b>\n━━━━━━━━━━━━━━━━\n"
                f"👤 @{message.from_user.username or 'yoq'} (ID: {uid})\n"
                f"🙍 {full_name} | 📞 {phone}\n🏠 {address}\n"
                f"📖 {item_name} ×{item_qty}\n💰 <b>{fmt(item_price)} so'm</b>\n"
                f"💳 {item_payment} | Holat: {item_status}\n🕒 {_now()}"
            )
            await safe_send(bot.send_message(ADMIN_ID, individual, reply_markup=admin_order_keyboard(oid, uid, item_status), parse_mode="HTML"))
    else:
        await safe_send(bot.send_message(
            ADMIN_ID, admin_text,
            reply_markup=admin_order_keyboard(first_oid, uid),
            parse_mode="HTML",
        ))

    if has_check:
        if message.photo:
            await safe_send(bot.send_photo(
                ADMIN_ID, message.photo[-1].file_id,
                caption=f"🧾 Buyurtma #{first_oid} — To'lov cheki",
            ))
        elif message.document:
            await safe_send(bot.send_document(
                ADMIN_ID, message.document.file_id,
                caption=f"🧾 Buyurtma #{first_oid} — To'lov cheki",
            ))

    if lat and lon:
        await safe_send(bot.send_location(ADMIN_ID, latitude=lat, longitude=lon))

    await message.answer(user_text, reply_markup=get_main_menu(uid), parse_mode="HTML")
    await state.clear()


# ═══════════════════════════════════════════════════
#  ADMIN — KITOB QO'SHISH
# ═══════════════════════════════════════════════════
@dp.message(F.text == "➕ Kitob qo'shish")
async def add_book_start(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Faqat admin uchun.")
        return
    await state.set_state(AddBookState.waiting_book_name)
    await message.answer("📌 Kitob nomini yozing:", reply_markup=cancel_keyboard)


@dp.message(AddBookState.waiting_book_name)
async def add_name(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("Bekor.", reply_markup=get_main_menu(message.from_user.id))
        return
    await state.update_data(book_name=message.text.strip())
    await state.set_state(AddBookState.waiting_book_author)
    await message.answer("✍️ Muallif ismini yozing:")


@dp.message(AddBookState.waiting_book_author)
async def add_author(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("Bekor.", reply_markup=get_main_menu(message.from_user.id))
        return
    await state.update_data(book_author=message.text.strip())
    await state.set_state(AddBookState.waiting_book_price)
    await message.answer("💰 Narxini yozing (so'mda):")


@dp.message(AddBookState.waiting_book_price)
async def add_price(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("Bekor.", reply_markup=get_main_menu(message.from_user.id))
        return
    try:
        price = int(message.text.strip().replace(" ", "").replace(",", ""))
        if price <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Faqat musbat raqam. Masalan: 50000")
        return
    await state.update_data(book_price=price)
    await state.set_state(AddBookState.waiting_book_description)
    await message.answer("📝 Tavsif yozing:")


@dp.message(AddBookState.waiting_book_description)
async def add_desc(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("Bekor.", reply_markup=get_main_menu(message.from_user.id))
        return
    await state.update_data(book_description=message.text.strip())
    await state.set_state(AddBookState.waiting_book_photo)
    await message.answer(
        "🖼 Rasm yuboring yoki <b>⏭️ O'tkazib yuborish</b> tugmasini bosing:",
        reply_markup=photo_skip_keyboard(),
        parse_mode="HTML",
    )


@dp.message(AddBookState.waiting_book_photo)
async def add_photo(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("Bekor.", reply_markup=get_main_menu(message.from_user.id))
        return
    photo = None
    if message.photo:
        photo = message.photo[-1].file_id
    elif message.text == "⏭️ O'tkazib yuborish":
        photo = None   # rasm yo'q
    else:
        # Boshqa matn — URL sifatida saqlanadi
        photo = message.text.strip()

    data = await state.get_data()
    bid  = generate_book_id(data["book_name"])
    await save_book(bid, data["book_name"], data["book_author"],
                    data["book_price"], data["book_description"], photo)
    await state.clear()
    await message.answer(
        f"✅ <b>Kitob qo'shildi!</b>\n\n"
        f"📖 {data['book_name']}\n✍️ {data['book_author']}\n"
        f"💰 {fmt(data['book_price'])} so'm\n📚 Jami: {len(BOOKS)} ta",
        reply_markup=get_main_menu(message.from_user.id),
        parse_mode="HTML",
    )


# ═══════════════════════════════════════════════════
#  ADMIN — KITOBLAR RO'YXATI
# ═══════════════════════════════════════════════════
@dp.message(F.text == "📋 Kitoblar (Admin)")
async def admin_books(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Faqat admin uchun.")
        return
    if not BOOKS:
        await message.answer("📭 Kitoblar yo'q.")
        return
    text = f"📚 <b>Kitoblar ({len(BOOKS)} ta):</b>\n\n"
    for i, (bid, b) in enumerate(BOOKS.items(), 1):
        text += f"{i}. <b>{b['name']}</b> — {fmt(b['price'])} so'm | 🛒 {b['sold_count']} ta\n"
    await message.answer(text, parse_mode="HTML")
    for bid, b in BOOKS.items():
        await message.answer(
            f"📖 {b['name']} | {fmt(b['price'])} so'm | Sotilgan: {b['sold_count']} ta",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🗑️ O'chirish", callback_data=f"delete_book:{bid}")
            ]]),
        )


@dp.callback_query(F.data.startswith("delete_book:"))
async def delete_book_cb(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Ruxsat yo'q.", show_alert=True)
        return
    bid  = callback.data.split(":", 1)[1]
    name = BOOKS.get(bid, {}).get("name", "?")
    await delete_book(bid)
    await callback.answer(f"✅ '{name}' o'chirildi.", show_alert=True)
    try:
        await callback.message.delete()
    except Exception:
        pass


# ═══════════════════════════════════════════════════
#  ADMIN — PANEL
# ═══════════════════════════════════════════════════
@dp.message(F.text == "📊 Admin panel")
@dp.message(Command("admin"))
async def admin_panel(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Faqat admin uchun.")
        return
    async with aiosqlite.connect(DB_PATH) as db:
        queries = [
            "SELECT COUNT(*) FROM orders",
            "SELECT COUNT(*) FROM orders WHERE status='yangi'",
            "SELECT COUNT(*) FROM orders WHERE status='tasdiqlandi'",
            "SELECT COUNT(*) FROM orders WHERE status='yuborildi'",
            "SELECT COUNT(*) FROM orders WHERE status='bekor qilindi'",
            "SELECT COALESCE(SUM(price),0) FROM orders WHERE status='yuborildi'",
            "SELECT COUNT(*) FROM users",
            "SELECT COUNT(*) FROM feedbacks",
            "SELECT COUNT(*) FROM promo_codes",
        ]
        results = []
        for q in queries:
            async with db.execute(q) as cur:
                row = await cur.fetchone()
                results.append(row[0])
        async with db.execute(
            "SELECT book_name, SUM(quantity) as total FROM orders GROUP BY book_id ORDER BY total DESC LIMIT 3"
        ) as cur:
            top = await cur.fetchall()

    total, new_c, conf, sent, cancel, revenue, users, feedbacks, promos = results
    top_text = "\n".join(
        f"  {i+1}. {r[0]} — {r[1]} ta" for i, r in enumerate(top)
    ) if top else "  Ma'lumot yo'q"

    await message.answer(
        f"📊 <b>Admin Panel</b>\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"👥 Foydalanuvchilar: <b>{users}</b>\n"
        f"📦 Jami buyurtmalar: <b>{total}</b>\n"
        f"  🆕 Yangi: <b>{new_c}</b>\n"
        f"  ✅ Tasdiqlangan: <b>{conf}</b>\n"
        f"  🚚 Yuborilgan: <b>{sent}</b>\n"
        f"  ❌ Bekor: <b>{cancel}</b>\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"💰 Daromad: <b>{fmt(revenue)} so'm</b>\n"
        f"📚 Kitoblar: <b>{len(BOOKS)}</b>\n"
        f"🎟️ Promo kodlar: <b>{promos}</b>\n"
        f"💬 Fikrlar: <b>{feedbacks}</b>\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"🏆 <b>TOP 3 kitob:</b>\n{top_text}\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"📋 Buyurtmalar: /orders\n"
        f"📤 Barcha foydalanuvchilarga: 📣 Xabar yuborish",
        parse_mode="HTML",
    )


@dp.message(Command("orders"))
async def admin_orders(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Faqat admin uchun.")
        return
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT * FROM orders ORDER BY id DESC LIMIT 10"
        ) as cur:
            rows = await cur.fetchall()
    if not rows:
        await message.answer("📭 Buyurtmalar yo'q.")
        return
    await message.answer(f"📋 <b>So'nggi {len(rows)} ta:</b>", parse_mode="HTML")
    for row in rows:
        maps_link = ""
        if row[6] and row[7]:
            maps_link = f"\n🗺 <a href='https://maps.google.com/?q={row[6]},{row[7]}'>Xaritada ko'rish</a>"
        qty = row[16] if len(row) > 16 else 1
        qty_line = f" ×{qty}" if qty > 1 else ""
        text = (
            f"🧾 <b>#{row[0]}</b> | @{row[2] or 'yoq'} ({row[1]})\n"
            f"🙍 {row[3]} | 📞 {row[4]}\n"
            f"🏠 {row[5]}{maps_link}\n"
            f"📖 {row[9]}{qty_line} | 💰 {fmt(row[11])} so'm\n"
            f"💳 {row[8]} | 📌 {row[14]}\n"
            f"🕒 {row[15]}"
        )
        await message.answer(
            text,
            reply_markup=admin_order_keyboard(row[0], row[1], row[14]),
            parse_mode="HTML"
        )


# ═══════════════════════════════════════════════════
#  ADMIN — BROADCAST
# ═══════════════════════════════════════════════════
@dp.message(F.text == "📣 Xabar yuborish")
async def broadcast_start(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Faqat admin uchun.")
        return
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cur:
            count = (await cur.fetchone())[0]
    await state.set_state(BroadcastState.waiting_message)
    await message.answer(
        f"📣 <b>Xabar yuborish</b>\n\n"
        f"👥 Foydalanuvchilar: <b>{count}</b>\n\n"
        f"Xabar (matn/rasm/video) yuboring:",
        reply_markup=cancel_keyboard,
        parse_mode="HTML",
    )


@dp.message(BroadcastState.waiting_message)
async def broadcast_send(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("Bekor.", reply_markup=get_main_menu(message.from_user.id))
        return
    user_ids   = await get_all_user_ids()
    sent = failed = 0
    status_msg = await message.answer(f"⏳ 0/{len(user_ids)} yuborilmoqda...")

    for i, uid in enumerate(user_ids):
        try:
            if message.photo:
                await safe_send(bot.send_photo(uid, message.photo[-1].file_id, caption=message.caption or ""))
            elif message.video:
                await safe_send(bot.send_video(uid, message.video.file_id, caption=message.caption or ""))
            elif message.text:
                await safe_send(bot.send_message(uid, message.text, parse_mode="HTML"))
            sent += 1
        except Exception:
            failed += 1
        if (i + 1) % 20 == 0:
            try:
                await status_msg.edit_text(f"⏳ {i+1}/{len(user_ids)} yuborildi...")
            except Exception:
                pass
        await asyncio.sleep(0.04)

    await state.clear()
    try:
        await status_msg.edit_text(
            f"✅ <b>Yuborildi!</b>\n📤 Muvaffaqiyatli: {sent}\n❌ Xato: {failed}",
            parse_mode="HTML",
        )
    except Exception:
        pass
    await message.answer("Tugadi.", reply_markup=get_main_menu(message.from_user.id))


# ═══════════════════════════════════════════════════
#  ADMIN — PROMO KOD YARATISH
# ═══════════════════════════════════════════════════
@dp.message(F.text == "🎟️ Promo yaratish")
async def promo_create_start(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Faqat admin uchun.")
        return
    await state.set_state(PromoState.waiting_code)
    await message.answer(
        "🎟️ <b>Yangi promo kod yaratish</b>\n\n"
        "Promo kod nomini yozing (masalan: KITOB20):",
        reply_markup=cancel_keyboard,
        parse_mode="HTML",
    )


@dp.message(PromoState.waiting_code)
async def promo_code_input(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("Bekor.", reply_markup=get_main_menu(message.from_user.id))
        return
    code = message.text.strip().upper()
    if not re.match(r'^[A-Z0-9_]{3,20}$', code):
        await message.answer("❌ Kod 3-20 ta harf/raqamdan iborat bo'lsin.")
        return
    await state.update_data(promo_code=code)
    await state.set_state(PromoState.waiting_type)
    await message.answer("Chegirma turini tanlang:", reply_markup=promo_type_keyboard())


@dp.message(PromoState.waiting_type)
async def promo_type_input(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("Bekor.", reply_markup=get_main_menu(message.from_user.id))
        return
    if message.text == "📊 Foiz (%)":
        ptype = "percent"
    elif message.text == "💵 Belgilangan summa (so'm)":
        ptype = "fixed"
    else:
        await message.answer("Tugmalardan birini tanlang.")
        return
    await state.update_data(promo_type=ptype)
    await state.set_state(PromoState.waiting_discount)
    hint = "Masalan: 10 (10%)" if ptype == "percent" else "Masalan: 5000 (5 000 so'm)"
    await message.answer(f"💰 Chegirma miqdorini yozing:\n{hint}", reply_markup=cancel_keyboard)


@dp.message(PromoState.waiting_discount)
async def promo_discount_input(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("Bekor.", reply_markup=get_main_menu(message.from_user.id))
        return
    try:
        disc = int(message.text.strip())
        if disc <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Faqat musbat raqam.")
        return
    await state.update_data(promo_discount=disc)
    await state.set_state(PromoState.waiting_max_uses)
    await message.answer("🔢 Maksimal foydalanish sonini yozing (masalan: 50):")


@dp.message(PromoState.waiting_max_uses)
async def promo_max_uses_input(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("Bekor.", reply_markup=get_main_menu(message.from_user.id))
        return
    try:
        max_u = int(message.text.strip())
        if max_u <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Faqat musbat raqam.")
        return
    data = await state.get_data()
    await save_promo(data["promo_code"], data["promo_discount"], data["promo_type"], max_u)
    await state.clear()

    disc_txt = (f"{data['promo_discount']}%" if data["promo_type"] == "percent"
                else f"{fmt(data['promo_discount'])} so'm")
    await message.answer(
        f"✅ <b>Promo kod yaratildi!</b>\n\n"
        f"🎟️ Kod: <code>{data['promo_code']}</code>\n"
        f"💰 Chegirma: {disc_txt}\n"
        f"🔢 Foydalanish limiti: {max_u} ta",
        reply_markup=get_main_menu(message.from_user.id),
        parse_mode="HTML",
    )


@dp.message(F.text == "📑 Promolar")
async def promos_list(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Faqat admin uchun.")
        return
    if not PROMO_CODES:
        await message.answer("📭 Hech qanday promo kod yo'q.")
        return
    text = "🎟️ <b>Promo kodlar:</b>\n\n"
    for code, p in PROMO_CODES.items():
        disc = f"{p['discount']}%" if p["type"] == "percent" else f"{fmt(p['discount'])} so'm"
        text += f"<code>{code}</code> — {disc} | {p['uses']}/{p['max_uses']} ta\n"
    await message.answer(text, parse_mode="HTML")


# ═══════════════════════════════════════════════════
#  ADMIN — STATUS BOSHQARUVI
# ═══════════════════════════════════════════════════
async def _admin_status_action(
    callback: CallbackQuery,
    new_status: str,
    label: str,
    user_msg: str,
):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Admin emassiz.", show_alert=True)
        return

    # Callback ma'lumotlarini tekshirish.
    try:
        parts = callback.data.split(":")
        order_id = int(parts[1])
        user_id = int(parts[2])
    except (ValueError, IndexError, AttributeError):
        await callback.answer(
            "❌ Buyurtma ma'lumoti noto'g'ri.",
            show_alert=True,
        )
        return

    # Faqat belgilangan ketma-ketlikda status o'zgarishiga ruxsat beriladi.
    allowed_transitions = {
        "yangi": {"tasdiqlandi", "bekor qilindi"},
        "tasdiqlandi": {"yuborildi", "bekor qilindi"},
        "yuborildi": {"yetkazildi", "mijoz qabul qilmadi"},
    }

    # Statusni tekshirish va yangilash bitta DB ulanishida bajariladi.
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT user_id, status FROM orders WHERE id = ?",
            (order_id,),
        ) as cur:
            order = await cur.fetchone()

        if not order:
            await callback.answer(
                "❌ Buyurtma topilmadi.",
                show_alert=True,
            )
            return

        actual_user_id, current_status = order

        # Callbackdagi foydalanuvchi ID'si buyurtma egasiga mosligini tekshirish.
        if int(actual_user_id) != user_id:
            await callback.answer(
                "❌ Buyurtma egasi ma'lumoti mos kelmadi.",
                show_alert=True,
            )
            return

        if new_status not in allowed_transitions.get(current_status, set()):
            await callback.answer(
                "⚠️ Buyurtma holati allaqachon o'zgargan yoki bu amal mumkin emas.",
                show_alert=True,
            )
            return

        await db.execute("UPDATE orders SET status = ?, delivered_at = CASE WHEN ?='yetkazildi' THEN ? ELSE delivered_at END WHERE id = ?", (new_status, new_status, _now(), order_id))
        # Zaxira faqat admin buyurtmani tasdiqlaganda kamayadi; bekor qilishda qaytariladi.
        async with db.execute("SELECT book_id, quantity FROM orders WHERE id=?", (order_id,)) as cur:
            stock_order = await cur.fetchone()
        if stock_order and new_status == "tasdiqlandi":
            book_id, qty = stock_order
            async with db.execute("SELECT stock FROM books WHERE id=?", (book_id,)) as cur:
                sr = await cur.fetchone()
            if sr and sr[0] >= 0:
                if sr[0] < qty:
                    await db.rollback()
                    await callback.answer("❌ Omborda yetarli kitob yo'q. Qoldiqni yangilang.", show_alert=True)
                    return
                await db.execute("UPDATE books SET stock=stock-? WHERE id=?", (qty, book_id))
                await db.execute("INSERT INTO stock_log(book_id,change_qty,reason,created_at) VALUES(?,?,?,?)", (book_id,-qty,f"Buyurtma #{order_id} tasdiqlandi",_now()))
        if stock_order and new_status == "bekor qilindi" and current_status == "tasdiqlandi":
            book_id, qty = stock_order
            await db.execute("UPDATE books SET stock=CASE WHEN stock < 0 THEN stock ELSE stock+? END WHERE id=?", (qty, book_id))
        if new_status == "bekor qilindi":
            async with db.execute("SELECT user_id, COALESCE(points_used,0) FROM orders WHERE id=?", (order_id,)) as cur:
                used_row = await cur.fetchone()
            if used_row and used_row[1] > 0:
                await db.execute("UPDATE users SET points=COALESCE(points,0)+? WHERE id=?", (used_row[1], used_row[0]))
                await db.execute("UPDATE orders SET points_used=0 WHERE id=?", (order_id,))
        if new_status == "yetkazildi":
            async with db.execute("SELECT user_id, price FROM orders WHERE id=?", (order_id,)) as cur:
                delivered = await cur.fetchone()
            if delivered:
                points = max(1, int(max(0, delivered[1]) // 10000))
                await db.execute("UPDATE users SET points=COALESCE(points,0)+? WHERE id=?", (points, delivered[0]))
                async with db.execute("SELECT referred_by FROM users WHERE id=?", (delivered[0],)) as cur:
                    refrow = await cur.fetchone()
                if refrow and refrow[0]:
                    async with db.execute("SELECT rewarded FROM referrals WHERE invited_id=?", (delivered[0],)) as cur:
                        rr = await cur.fetchone()
                    if rr and not rr[0]:
                        await db.execute("UPDATE users SET points=COALESCE(points,0)+5 WHERE id=?", (refrow[0],))
                        await db.execute("UPDATE referrals SET rewarded=1 WHERE invited_id=?", (delivered[0],))
        await db.commit()

    # Admin xabaridagi tugmalarni yangi statusga moslab yangilash.
    try:
        old_text = callback.message.text or callback.message.caption or ""
        updated_text = (
            old_text
            + f"\n\n{label} — {datetime.now().strftime('%H:%M')}"
        )
        await callback.message.edit_text(
            updated_text,
            parse_mode="HTML",
            reply_markup=admin_order_keyboard(order_id, user_id, new_status),
        )
    except Exception:
        logger.exception(
            "Admin xabarini yangilashda xato (buyurtma #%s).",
            order_id,
        )

    # Status o'zgargandan so'ng mijozga tegishli xabarni yuborish.
    try:
        await bot.send_message(
            user_id,
            f"{user_msg}\n🧾 Buyurtma #{order_id}\n\nSavollar: {ADMIN_USERNAME}",
            parse_mode="HTML",
        )
    except Exception:
        logger.exception(
            "Buyurtma #%s bo'yicha mijozga xabar yuborilmadi.",
            order_id,
        )

    await callback.answer(label, show_alert=True)


@dp.callback_query(F.data.startswith("admin_confirm:"))
async def admin_confirm(callback: CallbackQuery):
    await _admin_status_action(
        callback, "tasdiqlandi", "✅ TASDIQLANDI",
        "✅ <b>Buyurtmangiz tasdiqlandi!</b>\n📦 Tez orada yetkazib beriladi.",
    )


@dp.callback_query(F.data.startswith("admin_sent:"))
async def admin_sent(callback: CallbackQuery):
    await _admin_status_action(
        callback, "yuborildi", "🚚 YUBORILDI",
        "🚚 <b>Buyurtmangiz yo'lda!</b>\n📬 Tez orada qo'lingizga yetadi.",
    )


@dp.callback_query(F.data.startswith("admin_cancel:"))
async def admin_cancel_cb(callback: CallbackQuery):
    await _admin_status_action(
        callback, "bekor qilindi", "❌ BEKOR QILINDI",
        "❌ <b>Buyurtmangiz bekor qilindi.</b>\nMurojaat uchun:",
    )



# ═══════════════════════════════════════════════════
#  TAQWOBOOK — QO'SHIMCHA FUNKSIYALAR
# ═══════════════════════════════════════════════════
CATEGORIES = ["Qur'on va tafsir", "Hadis", "Siyrat", "Aqida", "Odob-axloq", "Bolalar uchun", "Boshqa"]

@dp.message(F.text == "🧭 Kitob tanlash")
async def book_guide(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌱 Islomni endi o'rganayotganlar", callback_data="guide:beginner")],
        [InlineKeyboardButton(text="👨‍👩‍👧 Ota-onalar", callback_data="guide:parents")],
        [InlineKeyboardButton(text="🧑 Yoshlar", callback_data="guide:youth")],
        [InlineKeyboardButton(text="🧒 Bolalar", callback_data="guide:children")],
        [InlineKeyboardButton(text="📚 Barcha kategoriyalar", callback_data="categories")],
    ])
    await message.answer("🧭 <b>Sizga mos kitobni topamiz</b>\nKim uchun kitob izlayapsiz?", reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data.startswith("guide:"))
async def guide_result(callback: CallbackQuery):
    topic = callback.data.split(":", 1)[1]
    keywords = {
        "beginner": ["aqida", "odob", "asos", "islom", "namoz"],
        "parents": ["tarbiya", "ota", "ona", "farzand", "oila"],
        "youth": ["yosh", "siyrat", "odob", "tarbiya"],
        "children": ["bola", "bolalar", "ertak", "tarbiya"],
    }.get(topic, [])
    results = [bid for bid, b in BOOKS.items() if any(k in (b.get("name","")+" "+b.get("description","")+" "+b.get("category","")).lower() for k in keywords)]
    if not results:
        results = [bid for bid, b in BOOKS.items() if b.get("category") == ("Bolalar uchun" if topic == "children" else "Odob-axloq")]
    await callback.message.answer("📚 Tavsiyalar:" if results else "Hozircha aniq mos kitob topilmadi. Kategoriyalarni ko'rib chiqing.", reply_markup=books_keyboard(source=results) if results else None)
    await callback.answer()

@dp.callback_query(F.data == "categories")
async def categories_cb(callback: CallbackQuery):
    rows=[]
    for cat in CATEGORIES:
        rows.append([InlineKeyboardButton(text=cat, callback_data="cat:"+cat)])
    await callback.message.answer("📚 Kategoriyani tanlang:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()

@dp.callback_query(F.data.startswith("cat:"))
async def category_cb(callback: CallbackQuery):
    cat=callback.data[4:]
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id FROM books WHERE category=? ORDER BY created_at DESC", (cat,)) as cur:
            ids=[r[0] for r in await cur.fetchall()]
    ids=[bid for bid in ids if bid in BOOKS]
    await callback.message.answer(f"📚 {cat}: {len(ids)} ta kitob", reply_markup=books_keyboard(source=ids) if ids else None)
    await callback.answer()

@dp.message(F.text == "📔 Mutolaa kundaligi")
async def reading_diary(message: Message):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT book_id,status,updated_at FROM reading_log WHERE user_id=? ORDER BY updated_at DESC", (message.from_user.id,)) as cur:
            rows=await cur.fetchall()
    lines=["📔 <b>Mutolaa kundaligingiz</b>", "Kitob sahifasida quyidagi tugmalar orqali ro'yxatga qo'shishingiz mumkin:", ""]
    for bid,status,updated in rows[:30]:
        lines.append(f"{'✅' if status=='oqildi' else '📖' if status=='oqilyapti' else '📝'} {BOOKS.get(bid,{}).get('name',bid)} — {status} ({updated[:10]})")
    kb=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📚 Kitob tanlash", callback_data="reading:pick")],
        [InlineKeyboardButton(text="🎯 Haftalik maqsad", callback_data="reading:goal")],
    ])
    await message.answer("\n".join(lines), reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data == "reading:pick")
async def reading_pick(callback: CallbackQuery):
    await callback.message.answer("Mutolaa ro'yxatiga qo'shish uchun kitobni tanlang:", reply_markup=books_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "reading:goal")
async def reading_goal(callback: CallbackQuery):
    await callback.message.answer("🎯 Haftalik tavsiya: 3 kun, kuniga 10–15 daqiqadan mutolaa qiling. Maqsadni bajarganingizda kundalikda o'qilgan kitobni belgilang.")
    await callback.answer()

@dp.callback_query(F.data.startswith("reading_set:"))
async def reading_set(callback: CallbackQuery):
    _,bid,status=callback.data.split(":",2)
    if bid not in BOOKS:
        await callback.answer("Kitob topilmadi", show_alert=True); return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO reading_log(user_id,book_id,status,updated_at) VALUES(?,?,?,?) ON CONFLICT(user_id,book_id) DO UPDATE SET status=excluded.status,updated_at=excluded.updated_at", (callback.from_user.id,bid,status,_now()))
        await db.commit()
    await callback.answer("Mutolaa kundaligi yangilandi")

@dp.message(F.text == "👥 Do'st taklif qilish")
async def invite_friends(message: Message):
    me=await bot.get_me()
    link=f"https://t.me/{me.username}?start=ref_{message.from_user.id}"
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM referrals WHERE inviter_id=?", (message.from_user.id,)) as cur:
            count=(await cur.fetchone())[0]
    await message.answer(f"👥 <b>Do'stingizni TAQWOBOOK'ga taklif qiling</b>\n\nSizning havolangiz:\n<code>{link}</code>\n\nTakliflar: {count}\n🎁 Bonus taklif qilingan do'st birinchi buyurtmasini olgach beriladi.", parse_mode="HTML")

@dp.message(F.text == "💡 Kun hikmati")
async def daily_wisdom(message: Message):
    await message.answer("💡 <b>Kun hikmati</b>\n\nBugungi kichik vazifa: har kuni oz bo'lsa ham foydali ilmga vaqt ajrating. O'qiyotgan kitobingizdan bir fikrni yozib qo'ying.\n\n📚 Mutolaa uchun kitob tanlash: «Kitoblar» bo'limi.\n\nEslatma: manbasi tekshirilmagan diniy iqtiboslar hadis yoki oyat sifatida berilmaydi.", parse_mode="HTML")

@dp.message(F.text == "🎁 To'plamlar")
async def bundles_list(message: Message):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id,name,description,price FROM bundles WHERE active=1 ORDER BY id DESC") as cur:
            rows=await cur.fetchall()
    if not rows:
        await message.answer("🎁 Hozircha tayyor to'plamlar yo'q. Admin keyinroq qo'shishi mumkin.")
        return
    for bid,name,desc,price in rows:
        await message.answer(f"🎁 <b>{name}</b>\n{desc}\n💰 {fmt(price)} so'm", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📚 Tarkibini ko'rish",callback_data=f"bundle:{bid}")]]))

@dp.callback_query(F.data.startswith("bundle:"))
async def bundle_detail(callback: CallbackQuery):
    try: bundle_id=int(callback.data.split(":",1)[1])
    except ValueError: await callback.answer("Noto'g'ri to'plam"); return
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT name,description,price FROM bundles WHERE id=? AND active=1",(bundle_id,)) as cur: b=await cur.fetchone()
        async with db.execute("SELECT book_id,quantity FROM bundle_items WHERE bundle_id=?",(bundle_id,)) as cur: items=await cur.fetchall()
    if not b: await callback.answer("To'plam topilmadi",show_alert=True); return
    names=[f"• {BOOKS.get(bid,{}).get('name',bid)} ×{q}" for bid,q in items]
    await callback.message.answer(f"🎁 <b>{b[0]}</b>\n{b[1]}\n\n"+("\n".join(names) if names else "Tarkib hali kiritilmagan")+f"\n\n💰 To'plam narxi: {fmt(b[2])} so'm\nKitoblarni savatga qo'shib, odatdagi tartibda buyurtma berishingiz mumkin.",parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🛒 To'plamni savatga qo'shish",callback_data=f"bundle_add:{bundle_id}")]]))
    await callback.answer()

@dp.callback_query(F.data.startswith("bundle_add:"))
async def bundle_add_cart(callback: CallbackQuery):
    try: bundle_id=int(callback.data.split(":",1)[1])
    except ValueError: await callback.answer("To'plam noto'g'ri",show_alert=True); return
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT book_id,quantity FROM bundle_items WHERE bundle_id=?",(bundle_id,)) as cur: items=await cur.fetchall()
        async with db.execute("SELECT name FROM bundles WHERE id=? AND active=1",(bundle_id,)) as cur: bundle=await cur.fetchone()
    if not bundle or not items:
        await callback.answer("To'plam tarkibi hali kiritilmagan",show_alert=True); return
    cart=CARTS.setdefault(callback.from_user.id,{})
    for bid,qty in items:
        if bid in BOOKS: cart[bid]=cart.get(bid,0)+qty
    await save_cart_to_db(callback.from_user.id)
    await callback.message.answer(f"✅ {bundle[0]} to'plami savatga qo'shildi. Narx savatdagi alohida kitoblar narxi bo'yicha hisoblanadi; maxsus to'plam narxi admin tomonidan alohida tasdiqlanadi.",reply_markup=cart_keyboard(callback.from_user.id))
    await callback.answer("Savatga qo'shildi")

@dp.message(Command("addbundle"))
async def add_bundle_command(message: Message):
    if message.from_user.id != ADMIN_ID: await message.answer("❌ Faqat admin uchun."); return
    # Format: /addbundle Nomi | Tavsif | Narx | book_id:son,book_id:son
    parts=(message.text or "").partition(" ")[2].split("|")
    if len(parts)<4:
        await message.answer("Format:\n/addbundle Nomi | Tavsif | Narx | book_id:son,book_id:son\nKitob ID'larini /stock bo'limidan tekshiring.")
        return
    name,desc,price_raw,items_raw=[x.strip() for x in parts[:4]]
    try:
        price=int(price_raw)
        items=[]
        for item in items_raw.split(","):
            bid,qty=item.strip().split(":",1); qty=int(qty)
            if bid not in BOOKS or qty<1: raise ValueError
            items.append((bid,qty))
        if price<0 or not name or not items: raise ValueError
    except Exception:
        await message.answer("❌ Narx yoki tarkib noto'g'ri. Misol: /addbundle Oila | Oila uchun | 120000 | kitob_id:1")
        return
    async with aiosqlite.connect(DB_PATH) as db:
        cur=await db.execute("INSERT INTO bundles(name,description,price,active,created_at) VALUES(?,?,?,1,?)",(name,desc,price,_now()))
        bundle_id=cur.lastrowid
        await db.executemany("INSERT INTO bundle_items(bundle_id,book_id,quantity) VALUES(?,?,?)",[(bundle_id,bid,qty) for bid,qty in items])
        await db.commit()
    await message.answer(f"✅ To'plam yaratildi: {name} (ID: {bundle_id})")

@dp.message(Command("points"))
async def points_command(message: Message):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COALESCE(points,0) FROM users WHERE id=?",(message.from_user.id,)) as cur: row=await cur.fetchone()
    points=row[0] if row else 0
    await message.answer(f"🎁 Sizda {points} bonus ball bor. Har bir yetkazilgan buyurtma uchun xarid summasiga qarab ball beriladi. Hozircha ballar admin orqali chegirmaga aylantiriladi; avtomatik yechish keyingi bosqichda sozlanishi mumkin.")

@dp.message(F.text == "📦 Ombor")
async def stock_admin(message: Message):
    if message.from_user.id != ADMIN_ID: await message.answer("❌ Faqat admin uchun."); return
    lines=["📦 <b>Ombor qoldig'i</b>"]
    for bid,b in list(BOOKS.items())[:60]:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT stock,category FROM books WHERE id=?",(bid,)) as cur: row=await cur.fetchone()
        stock=row[0] if row else -1
        lines.append(f"• {b['name']} — {'cheklanmagan' if stock < 0 else str(stock)+' ta'} | {row[1] if row else 'Boshqa'}")
    lines.append("\nQoldiq: /stock KITOB_ID MIQDOR (masalan: /stock abc123 15)\nKategoriya: /setcategory KITOB_ID kategoriya nomi")
    await message.answer("\n".join(lines),parse_mode="HTML")

@dp.message(Command("stock"))
async def stock_command(message: Message):
    if message.from_user.id != ADMIN_ID: await message.answer("❌ Faqat admin uchun."); return
    parts=(message.text or "").split(maxsplit=2)
    if len(parts)!=3: await message.answer("Ishlatish: /stock KITOB_ID MIQDOR\n-1 = cheklanmagan"); return
    bid=parts[1]
    try: qty=int(parts[2]); assert qty >= -1
    except Exception: await message.answer("Miqdor -1 yoki 0 dan katta raqam bo'lishi kerak."); return
    async with aiosqlite.connect(DB_PATH) as db:
        cur=await db.execute("UPDATE books SET stock=? WHERE id=?",(qty,bid)); await db.commit()
    await message.answer("✅ Qoldiq yangilandi." if cur.rowcount else "❌ Kitob ID topilmadi.")
    if cur.rowcount and qty >= 0 and qty <= 3:
        book_name = BOOKS.get(bid, {}).get("name", bid)
        await message.answer(f"⚠️ <b>Kam qoldiq ogohlantirishi</b>\n{book_name}: omborda {qty} ta qoldi.", parse_mode="HTML")

@dp.message(Command("setcategory"))
async def set_category_command(message: Message):
    if message.from_user.id != ADMIN_ID: await message.answer("❌ Faqat admin uchun."); return
    parts=(message.text or "").split(maxsplit=2)
    if len(parts)!=3: await message.answer("Ishlatish: /setcategory KITOB_ID KATEGORIYA\nKategoriyalar: "+", ".join(CATEGORIES)); return
    async with aiosqlite.connect(DB_PATH) as db:
        cur=await db.execute("UPDATE books SET category=? WHERE id=?",(parts[2],parts[1])); await db.commit()
    await message.answer("✅ Kategoriya saqlandi." if cur.rowcount else "❌ Kitob ID topilmadi.")

@dp.message(Command("backup"))
async def backup_command(message: Message):
    if message.from_user.id != ADMIN_ID: await message.answer("❌ Faqat admin uchun."); return
    try:
        import sqlite3
        from datetime import date
        backup_dir=Path(DB_PATH).expanduser().resolve().parent / "backups"
        backup_dir.mkdir(parents=True,exist_ok=True)
        target=backup_dir / f"orders-{date.today().isoformat()}.db"
        src=sqlite3.connect(DB_PATH); dst=sqlite3.connect(target)
        with dst: src.backup(dst)
        dst.close(); src.close()
        await message.answer(f"✅ Zaxira nusxa yaratildi: <code>{target.name}</code>\nEslatma: Railway qayta deployida saqlanishi uchun DB va backups papkasi persistent Volume ichida bo'lishi kerak.",parse_mode="HTML")
    except Exception:
        logger.exception("DB backup failed")
        await message.answer("❌ Zaxira nusxa yaratilmadi. Bot logini tekshiring.")

@dp.message(Command("export_orders"))
async def export_orders(message: Message):
    if message.from_user.id != ADMIN_ID: await message.answer("❌ Faqat admin uchun."); return
    import csv, io
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id,created_at,full_name,phone,address,book_name,quantity,price,payment_method,status FROM orders ORDER BY id DESC") as cur: rows=await cur.fetchall()
    out=io.StringIO(); w=csv.writer(out); w.writerow(["ID","Sana","Mijoz","Telefon","Manzil","Kitob","Soni","Narx","To'lov","Holat"]); w.writerows(rows)
    from aiogram.types import BufferedInputFile
    await message.answer_document(BufferedInputFile(out.getvalue().encode('utf-8-sig'),filename="taqwobook_orders.csv"),caption="📊 Buyurtmalar eksporti")

@dp.callback_query(F.data.startswith("admin_delivered:"))
async def admin_delivered(callback: CallbackQuery):
    await _admin_status_action(callback,"yetkazildi","✅ YETKAZILDI","✅ <b>Buyurtmangiz yetkazildi deb belgilandi.</b> Xaridingiz uchun rahmat!")

@dp.callback_query(F.data.startswith("admin_refused:"))
async def admin_refused(callback: CallbackQuery):
    await _admin_status_action(callback,"mijoz qabul qilmadi","↩️ MIJOZ QABUL QILMADI","↩️ <b>Buyurtma bo'yicha yetkazib berish yakunlanmadi.</b> Tafsilotlarni kelishish uchun admin bilan bog'laning.")


# ═══════════════════════════════════════════════════
#  QIZIQARLI VA FOYDALI YANGI FUNKSIYALAR
# ═══════════════════════════════════════════════════

@dp.message(F.text == "🎲 Kitob ruletkasi")
async def random_book(message: Message):
    """Sotuvdagi kitoblardan tasodifiy kitob tanlaydi."""
    import random
    available = [(bid, b) for bid, b in BOOKS.items() if b.get("price", 0) >= 0]
    if not available:
        await message.answer("📭 Hozircha ruletka uchun kitob yo'q. Keyinroq yana urinib ko'ring!")
        return
    bid, book = random.choice(available)
    rating = book.get("avg_rating", 0)
    await message.answer(
        f"🎲 <b>TAQWOBOOK ruletkasi siz uchun tanladi!</b>\n\n"
        f"📖 <b>{book['name']}</b>\n✍️ Muallif: {book.get('author') or 'Ko‘rsatilmagan'}\n"
        f"💰 Narxi: {fmt(book['price'])} so'm\n"
        f"⭐ Reyting: {rating}/5\n\nBugun shu kitob bilan yangi bilim sari qadam qo'yasizmi?",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📘 Kitobni ko'rish", callback_data=f"book:{bid}")],
            [InlineKeyboardButton(text="🎲 Yana tanlab ber", callback_data="random_book_again")],
        ]),
    )

@dp.callback_query(F.data == "random_book_again")
async def random_book_again(callback: CallbackQuery):
    import random
    available = [(bid, b) for bid, b in BOOKS.items()]
    if not available:
        await callback.answer("Kitoblar topilmadi", show_alert=True)
        return
    bid, book = random.choice(available)
    await callback.message.answer(
        f"🎲 Yangi tanlov: <b>{book['name']}</b>\n💰 {fmt(book['price'])} so'm",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📘 Ko'rish", callback_data=f"book:{bid}")]])
    )
    await callback.answer("Yangi kitob tanlandi!")

QUIZ_QUESTIONS = [
    ("Kitob o'qishda eng foydali odatlardan biri qaysi?", ["Tushunmagan joyni belgilash", "Faqat tez o'qish", "Har safar chalg'ish"], 0),
    ("Mutolaa kundaligi nima uchun kerak?", ["Kitoblarni yo'qotish uchun", "O'qish jarayoni va fikrlarni qayd etish uchun", "Narxlarni yashirish uchun"], 1),
    ("Yangi kitob tanlayotganda nimaga qarash foydali?", ["Faqat muqovasiga", "Maqsad, tavsif va mavzusiga", "Faqat sahifa rangiga"], 1),
    ("O'qigan narsani eslab qolishga nima yordam beradi?", ["Asosiy fikrlarni yozib borish", "Darhol unutishga urinish", "Kitobni ochmaslik"], 0),
    ("Barqaror mutolaa uchun qaysi yo'l ma'qul?", ["Faqat yiliga bir marta", "Har kuni oz-ozdan vaqt ajratish", "Faqat kayfiyat bo'lsa"], 1),
]

async def show_quiz_question(target, uid: int, q_index: int):
    question, options, correct = QUIZ_QUESTIONS[q_index]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{i+1}. {option}", callback_data=f"quizans:{q_index}:{i}")]
        for i, option in enumerate(options)
    ])
    await target.answer(f"🎮 <b>Kunlik bilim viktorinasi</b> ({q_index+1}/{len(QUIZ_QUESTIONS)})\n\n{question}", reply_markup=kb, parse_mode="HTML")

@dp.message(F.text == "🎮 Bilim viktorinasi")
async def quiz_start(message: Message):
    today = datetime.now().strftime("%Y-%m-%d")
    uid = message.from_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT q_index,score,finished FROM daily_quiz WHERE user_id=? AND quiz_date=?", (uid,today)) as cur:
            row = await cur.fetchone()
        if row and row[2]:
            await message.answer(f"🏁 Bugungi viktorinani allaqachon tugatgansiz! Natijangiz: {row[1]}/{len(QUIZ_QUESTIONS)}. Ertaga yana urinib ko'ring.")
            return
        if not row:
            await db.execute("INSERT INTO daily_quiz(user_id,quiz_date,q_index,score,finished) VALUES(?,?,0,0,0)", (uid,today))
            await db.commit()
    await show_quiz_question(message, uid, 0)

@dp.callback_query(F.data.startswith("quizans:"))
async def quiz_answer(callback: CallbackQuery):
    try:
        _, q_raw, choice_raw = callback.data.split(":")
        q_index, choice = int(q_raw), int(choice_raw)
    except (ValueError, TypeError):
        await callback.answer("Javobni o'qib bo'lmadi", show_alert=True); return
    if q_index < 0 or q_index >= len(QUIZ_QUESTIONS):
        await callback.answer("Savol topilmadi", show_alert=True); return
    today = datetime.now().strftime("%Y-%m-%d")
    uid = callback.from_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT q_index,score,finished FROM daily_quiz WHERE user_id=? AND quiz_date=?", (uid,today)) as cur:
            row = await cur.fetchone()
        if not row or row[2] or row[0] != q_index:
            await callback.answer("Bu javob eskirgan yoki viktorina tugagan.", show_alert=True); return
        score = row[1] + (1 if choice == QUIZ_QUESTIONS[q_index][2] else 0)
        next_q = q_index + 1
        if next_q >= len(QUIZ_QUESTIONS):
            reward = score * 2
            await db.execute("UPDATE daily_quiz SET q_index=?,score=?,finished=1 WHERE user_id=? AND quiz_date=?", (next_q,score,uid,today))
            await db.execute("UPDATE users SET points=COALESCE(points,0)+? WHERE id=?", (reward,uid))
            await db.commit()
            result_text = f"🏁 <b>Viktorina yakunlandi!</b>\nNatija: <b>{score}/{len(QUIZ_QUESTIONS)}</b>\n🎁 Hisobingizga <b>{reward} ball</b> qo'shildi.\n\nErtaga yangi urinishda ko'rishamiz!"
        else:
            await db.execute("UPDATE daily_quiz SET q_index=?,score=? WHERE user_id=? AND quiz_date=?", (next_q,score,uid,today))
            await db.commit()
            result_text = "✅ To'g'ri!" if choice == QUIZ_QUESTIONS[q_index][2] else "💡 Bu safar bo'lmadi — keyingi savolga o'tamiz."
    await callback.answer("Javob qabul qilindi")
    if next_q >= len(QUIZ_QUESTIONS):
        await callback.message.answer(result_text, parse_mode="HTML")
    else:
        await callback.message.answer(result_text)
        await show_quiz_question(callback.message, uid, next_q)

@dp.message(F.text == "🔥 Mutolaa marafoni")
async def reading_marathon(message: Message):
    today = datetime.now().strftime("%Y-%m-%d")
    uid = message.from_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT minutes FROM reading_checkins WHERE user_id=? AND checkin_date=?", (uid,today)) as cur:
            checked = await cur.fetchone()
        async with db.execute("SELECT checkin_date FROM reading_checkins WHERE user_id=? ORDER BY checkin_date DESC LIMIT 30", (uid,)) as cur:
            dates = [r[0] for r in await cur.fetchall()]
        async with db.execute("SELECT COUNT(*) FROM reading_checkins WHERE user_id=? AND checkin_date>=date('now','-6 day')", (uid,)) as cur:
            week_count = (await cur.fetchone())[0]
    streak = 0
    from datetime import date, timedelta
    d = date.today()
    date_set = set(dates)
    if d.isoformat() not in date_set:
        d -= timedelta(days=1)
    while d.isoformat() in date_set:
        streak += 1
        d -= timedelta(days=1)
    text = ("🔥 <b>7 kunlik mutolaa marafoni</b>\n\n"
            f"📅 Shu haftadagi faol kunlar: <b>{week_count}/7</b>\n"
            f"⚡ Ketma-ket kunlar: <b>{streak}</b>\n"
            f"🎁 Har kuni belgilaganingiz uchun 2 ball beriladi. Bir kunda faqat bir marta.\n\n")
    if checked:
        text += f"✅ Bugun mutolaa qayd etilgan: {checked[0]} daqiqa. Ertaga davom eting!"
        kb = None
    else:
        text += "Bugun qancha vaqt mutolaa qildingiz? Belgilang:"
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="📖 10 daqiqa", callback_data="checkin:10"),
            InlineKeyboardButton(text="📚 20 daqiqa", callback_data="checkin:20"),
            InlineKeyboardButton(text="💪 30 daqiqa", callback_data="checkin:30"),
        ]])
    await message.answer(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data.startswith("checkin:"))
async def reading_checkin(callback: CallbackQuery):
    try: minutes = int(callback.data.split(":",1)[1])
    except ValueError: await callback.answer("Vaqt noto'g'ri", show_alert=True); return
    if minutes not in (10,20,30):
        await callback.answer("Vaqt noto'g'ri", show_alert=True); return
    uid = callback.from_user.id
    today = datetime.now().strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("INSERT OR IGNORE INTO reading_checkins(user_id,checkin_date,minutes,created_at) VALUES(?,?,?,?)", (uid,today,minutes,_now()))
        if cur.rowcount:
            await db.execute("UPDATE users SET points=COALESCE(points,0)+2 WHERE id=?", (uid,))
            await db.commit()
            message = f"🎉 Zo'r! Bugungi {minutes} daqiqalik mutolaa qayd etildi. +2 ball! Ertaga yana davom eting."
        else:
            message = "Bugungi mutolaa allaqachon qayd etilgan. Ertaga yana ball olishingiz mumkin!"
    await callback.answer("Qayd etildi")
    await callback.message.answer(message)

@dp.message(F.text == "🏆 Mening profilim")
async def customer_profile(message: Message):
    uid = message.from_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COALESCE(points,0) FROM users WHERE id=?", (uid,)) as cur:
            row = await cur.fetchone()
        points = row[0] if row else 0
        async with db.execute("SELECT status,COUNT(*) FROM reading_log WHERE user_id=? GROUP BY status", (uid,)) as cur:
            reading = dict(await cur.fetchall())
        async with db.execute("SELECT COUNT(*) FROM orders WHERE user_id=?", (uid,)) as cur:
            orders = (await cur.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM reading_checkins WHERE user_id=?", (uid,)) as cur:
            days = (await cur.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM referrals WHERE inviter_id=?", (uid,)) as cur:
            invites = (await cur.fetchone())[0]
    level = "🌱 Yangi kitobxon"
    if points >= 50: level = "📚 Faol kitobxon"
    if points >= 150: level = "🏅 Bilim izlovchi"
    if points >= 400: level = "👑 TAQWOBOOK ustasi"
    await message.answer(
        f"🏆 <b>Sizning TAQWOBOOK profilingiz</b>\n━━━━━━━━━━━━\n"
        f"{level}\n⭐ Ballar: <b>{points}</b>\n\n"
        f"📔 O'qimoqchi: {reading.get('reja',0)} ta\n"
        f"📖 O'qiyapman: {reading.get('oqilyapti',0)} ta\n"
        f"✅ O'qib bo'ldim: {reading.get('oqildi',0)} ta\n"
        f"🔥 Mutolaa kunlari: {days}\n🛍 Buyurtmalar: {orders}\n👥 Takliflar: {invites}\n\n"
        f"Ball yig'ish: kunlik viktorina (+ball) va mutolaa marafonida qatnashing!",
        parse_mode="HTML",
    )


# ═══════════════════════════════════════════════════
#  QO'SHIMCHA: KAYFIYATGA MOS TAVSIYA, REYTING, ESLATMA
# ═══════════════════════════════════════════════════

@dp.message(F.text == "💝 Kayfiyatga qarab")
async def mood_recommendations(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌱 O'zimni rivojlantirish", callback_data="mood:grow")],
        [InlineKeyboardButton(text="👨‍👩‍👧 Oila va tarbiya", callback_data="mood:family")],
        [InlineKeyboardButton(text="🕌 Ma'naviyat va siyrat", callback_data="mood:faith")],
        [InlineKeyboardButton(text="🧒 Bolalar uchun", callback_data="mood:kids")],
        [InlineKeyboardButton(text="🎁 Tasodifiy tanlov", callback_data="mood:random")],
    ])
    await message.answer("💝 <b>Bugun nimani o'rganishni xohlaysiz?</b>\nKayfiyatingizga mos yo'nalishni tanlang:", reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data.startswith("mood:"))
async def mood_recommendation_result(callback: CallbackQuery):
    import random
    mood = callback.data.split(":", 1)[1]
    keys = {"grow": ("O'zini rivojlantirish", ("rivoj", "odat", "ilm", "tarbiya")),
            "family": ("Oila va tarbiya", ("oila", "farzand", "tarbiya", "bola")),
            "faith": ("Ma'naviyat va siyrat", ("siyrat", "aqida", "hadis", "qur", "tafsir", "odob")),
            "kids": ("Bolalar uchun", ("bola", "bolalar", "ertak"))}
    pool = list(BOOKS.items())
    if mood in keys:
        _, words = keys[mood]
        pool = [(bid,b) for bid,b in pool if any(w in (b.get("name","")+" "+b.get("author","")+" "+b.get("description","")).lower() for w in words)]
    if not pool:
        pool = list(BOOKS.items())
    if not pool:
        await callback.answer("Hozircha kitob yo'q", show_alert=True); return
    random.shuffle(pool)
    lines = ["💝 <b>Siz uchun tavsiyalar</b>"]
    for bid,b in pool[:5]:
        lines.append(f"📚 <b>{b['name']}</b> — {fmt(b['price'])} so'm\n{b.get('author','')}")
    await callback.message.answer("\n\n".join(lines), parse_mode="HTML", reply_markup=books_keyboard())
    await callback.answer()

@dp.message(F.text == "🥇 Kitobxonlar reytingi")
async def reader_leaderboard(message: Message):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT first_name,points FROM users ORDER BY COALESCE(points,0) DESC,joined_at ASC LIMIT 10") as cur:
            rows = await cur.fetchall()
    if not rows:
        await message.answer("Hali reyting uchun ma'lumot yo'q."); return
    medals = ["🥇", "🥈", "🥉"]
    lines = ["🏆 <b>TAQWOBOOK kitobxonlari reytingi</b>"]
    for i,(name,points) in enumerate(rows,1):
        lines.append(f"{medals[i-1] if i<=3 else str(i)+'.'} {name or 'Kitobxon'} — ⭐ {points or 0} ball")
    lines.append("\nBall yig'ish uchun viktorina, mutolaa marafoni va buyurtmalarda qatnashing!")
    await message.answer("\n".join(lines), parse_mode="HTML")

@dp.message(F.text == "🔔 Mutolaa eslatmasi")
async def toggle_reading_reminder(message: Message):
    uid = message.from_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT enabled FROM reminder_settings WHERE user_id=?", (uid,)) as cur:
            row = await cur.fetchone()
        enabled = 0 if row and row[0] else 1
        await db.execute("INSERT INTO reminder_settings(user_id,enabled,last_sent_date) VALUES(?,?,NULL) ON CONFLICT(user_id) DO UPDATE SET enabled=excluded.enabled", (uid,enabled))
        await db.commit()
    if enabled:
        await message.answer("🔔 Mutolaa eslatmasi yoqildi! Har kuni taxminan soat 20:00 da (Toshkent vaqti) kitob o'qish eslatmasi yuboramiz. O'chirish uchun shu tugmani yana bosing.")
    else:
        await message.answer("🔕 Mutolaa eslatmasi o'chirildi.")

async def reading_reminder_worker():
    """Har kuni Toshkent vaqti bilan 20:00 da obuna bo'lganlarga bir marta eslatadi."""
    from zoneinfo import ZoneInfo
    from datetime import timedelta
    while True:
        try:
            now = datetime.now(ZoneInfo("Asia/Tashkent"))
            if now.hour == 20:
                today = now.strftime("%Y-%m-%d")
                async with aiosqlite.connect(DB_PATH) as db:
                    async with db.execute("SELECT user_id FROM reminder_settings WHERE enabled=1 AND (last_sent_date IS NULL OR last_sent_date<>?)", (today,)) as cur:
                        user_ids = [r[0] for r in await cur.fetchall()]
                    for uid in user_ids:
                        try:
                            await bot.send_message(uid, "🔔 <b>Mutolaa vaqti!</b>\nBugun 10 daqiqa bo'lsa ham kitob o'qib, mutolaa marafonida kuningizni belgilang. 📚", parse_mode="HTML")
                            await db.execute("UPDATE reminder_settings SET last_sent_date=? WHERE user_id=?", (today,uid))
                        except (TelegramForbiddenError, TelegramBadRequest):
                            pass
                    await db.commit()
        except Exception:
            logger.exception("Mutolaa eslatmasida xato")
        await asyncio.sleep(60)

# ═══════════════════════════════════════════════════
#  FALLBACK
# ═══════════════════════════════════════════════════
@dp.message()
async def fallback(message: Message, state: FSMContext):
    if await state.get_state():
        return
    await message.answer(
        "Kerakli bo'limni tanlang 👇",
        reply_markup=get_main_menu(message.from_user.id),
    )


# ═══════════════════════════════════════════════════
#  ISHGA TUSHIRISH (VPS / polling)
# ═══════════════════════════════════════════════════
async def main():
    # Ishga tushishda bazaning SQLite backup API orqali xavfsiz nusxasi.
    try:
        import sqlite3
        from datetime import date
        db_file=Path(DB_PATH).expanduser().resolve()
        if db_file.exists() and db_file.stat().st_size:
            backup_dir=db_file.parent / "backups"; backup_dir.mkdir(parents=True,exist_ok=True)
            target=backup_dir / f"orders-{date.today().isoformat()}.db"
            src=sqlite3.connect(str(db_file)); dst=sqlite3.connect(str(target))
            with dst: src.backup(dst)
            dst.close(); src.close()
            old=sorted(backup_dir.glob("orders-*.db"), key=lambda x:x.stat().st_mtime, reverse=True)
            for stale in old[7:]: stale.unlink(missing_ok=True)
    except Exception:
        logger.exception("Avtomatik backup bajarilmadi")
    await init_db()
    logger.info("Kitob do'koni boti ishga tushdi.")
    reminder_task = asyncio.create_task(reading_reminder_worker())
    try:
        await dp.start_polling(
        bot,
        allowed_updates=dp.resolve_used_update_types(),
        # Telegramda navbatda qolgan yangilanishlarni tashlab yubormaymiz.
        drop_pending_updates=False,
        )
    finally:
        reminder_task.cancel()
        try:
            await reminder_task
        except asyncio.CancelledError:
            pass


if __name__ == "__main__":
    asyncio.run(main())
