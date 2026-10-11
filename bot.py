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
    PROMO_CODES[code]["uses"] += 1
    return new, desc

def format_order_row(row) -> str:
    # row[10] = status indeksi
    status_col = row[10] if len(row) > 10 else "yangi"
    emoji = {"yangi": "🆕", "tasdiqlandi": "✅", "yuborildi": "🚚", "bekor qilindi": "❌"}.get(status_col, "📌")
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
        [KeyboardButton(text="🎟️ Promo kod"),    KeyboardButton(text="ℹ️ Aloqa")],
    ], resize_keyboard=True)

def admin_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📚 Kitoblar"),          KeyboardButton(text="🔍 Qidirish")],
        [KeyboardButton(text="🛒 Savatcha"),           KeyboardButton(text="📦 Buyurtmalarim")],
        [KeyboardButton(text="➕ Kitob qo'shish"),     KeyboardButton(text="📋 Kitoblar (Admin)")],
        [KeyboardButton(text="📊 Admin panel"),        KeyboardButton(text="📣 Xabar yuborish")],
        [KeyboardButton(text="🎟️ Promo yaratish"),    KeyboardButton(text="📑 Promolar")],
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

def admin_order_keyboard(order_id: int, uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"admin_confirm:{order_id}:{uid}"),
            InlineKeyboardButton(text="🚚 Yuborildi",  callback_data=f"admin_sent:{order_id}:{uid}"),
        ],
        [InlineKeyboardButton(text="❌ Bekor qilish",  callback_data=f"admin_cancel:{order_id}:{uid}")],
    ])

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
            CREATE INDEX IF NOT EXISTS idx_orders_user   ON orders(user_id);
            CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
        """)
        # quantity ustuni mavjud emasligini tekshirib qo'shamiz (eski DB uchun)
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
        emoji = {"yangi": "🆕", "tasdiqlandi": "✅", "yuborildi": "🚚", "bekor qilindi": "❌"}.get(row[14], "📌")
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
    if promo_code:
        final, _ = apply_promo(original, promo_code)
    else:
        final = original

    await state.update_data(payment_method=pm, final_price=final, original_price=original)

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
            item_price = round(final_price * ratio) if promo_code else b["price"] * qty
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

        promo_line = f"\n🎟️ Promo: {promo_code}" if promo_code else ""
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
        promo_line = f"\n🎟️ Promo: {promo_code}" if promo_code else ""
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

    # Admin ga yuborish
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
            reply_markup=admin_order_keyboard(row[0], row[1]),
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
async def _admin_status_action(callback: CallbackQuery, new_status: str, label: str, user_msg: str):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Admin emassiz.", show_alert=True)
        return
    parts    = callback.data.split(":")
    order_id = int(parts[1])
    user_id  = int(parts[2])
    await update_order_status(order_id, new_status)
    await safe_send(bot.send_message(
        user_id,
        f"{user_msg}\n🧾 Buyurtma #{order_id}\n\nSavollar: {ADMIN_USERNAME}",
        parse_mode="HTML",
    ))
    await callback.answer(label, show_alert=True)
    try:
        await callback.message.edit_text(
            callback.message.text + f"\n\n{label} — {datetime.now().strftime('%H:%M')}",
            parse_mode="HTML",
        )
    except Exception:
        pass


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
    await init_db()
    logger.info("Kitob do'koni boti ishga tushdi.")
    await dp.start_polling(
        bot,
        allowed_updates=dp.resolve_used_update_types(),
        # Telegramda navbatda qolgan yangilanishlarni tashlab yubormaymiz.
        drop_pending_updates=False,
    )


if __name__ == "__main__":
    asyncio.run(main())
