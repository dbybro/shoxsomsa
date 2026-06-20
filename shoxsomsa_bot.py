#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SHOXSOMSA — Milliy Taomlar Telegram Bot
Railway deployment uchun tayyor (env variables ishlatadi)

YANGI UPDATE (joriy):
  - 🛒 Tezkor buyurtma: taom tugmasi bosilganda darhol savatga qo'shiladi,
    har bir bosishdan keyin 3 tugma chiqadi: Yana qo'shish / Bekor qilish / Buyurtma berish
  - 💰 Har bir DONAGA +6000 so'm qo'shiladi (1000 xizmat haqi + 5000 idish puli,
    narxga singdirilgan, ko'rinmaydi alohida emas — masalan 5000 so'mlik somsa 11000 bo'ladi)
  - 👤 Ism-familiya endi SO'RALMAYDI — checkout to'g'ridan-to'g'ri telefondan boshlanadi
  - 📞 Telefon raqami: faqat kontakt tugmasi orqali, qo'shimcha tasdiqlash bosqichisiz
    (kontakt yuborilgan zahoti to'g'ridan-to'g'ri geolokatsiyaga o'tadi)
  - 📍 Geolokatsiya: majburiy, mustahkamlangan (boshqa narsa yuborilsa eslatma beradi)
  - 🚚 Yetkazib berish narxi: ENDI BUYURTMADA YO'Q — admin buyurtmani qabul qilganda
    qo'lda kiritadi, shundan keyin mijozga yakuniy summa yuboriladi
  - 💾 PERSISTENCE: active_orders va order_counter endi /data/bot_data.json faylga
    saqlanadi — bot qayta ishga tushganda (Railway restart/deploy) ma'lumot yo'qolmaydi
  - 🐛 Bug fix: manzil kiritish bosqichida boshqa tugma (Menyu/Savatcha/Aloqa) bosilsa
    endi noto'g'ri qabul qilinmaydi, foydalanuvchiga to'g'ri yo'naltiriladi
"""

import asyncio
import json
import logging
import os
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, F, BaseMiddleware
from aiogram.client.default import DefaultBotProperties
from aiogram.types import (
    Message, CallbackQuery, TelegramObject,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton
)
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from typing import Callable, Awaitable, Any

# ══════════════════════════════════════════
#  SOZLAMALAR — Railway Environment Variables
# ══════════════════════════════════════════
BOT_TOKEN  = os.environ["BOT_TOKEN"]
COURIER_ID = int(os.environ["COURIER_ID"])

_admin_ids_raw = os.environ.get("ADMIN_IDS", "")
ADMIN_IDS: list[int] = [
    int(x.strip()) for x in _admin_ids_raw.split(",") if x.strip()
]
if not ADMIN_IDS and "ADMIN_ID" in os.environ:
    ADMIN_IDS = [int(os.environ["ADMIN_ID"])]
if not ADMIN_IDS:
    raise RuntimeError("ADMIN_IDS yoki ADMIN_ID environment variable o'rnatilmagan!")

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

# Har bir DONAGA qo'shiladigan summa (1000 xizmat haqi + 5000 idish puli = 6000)
SERVICE_FEE_PER_ITEM = 6_000

# ──────────────────────────────────────────
# ISH VAQTI — 09:00 dan 02:00 gacha (Toshkent vaqti, kunni kesib o'tadi)
# ──────────────────────────────────────────
TIMEZONE   = ZoneInfo("Asia/Tashkent")
OPEN_TIME  = time(9, 0)
CLOSE_TIME = time(2, 0)

def is_open_now() -> bool:
    now = datetime.now(TIMEZONE).time()
    return now >= OPEN_TIME or now < CLOSE_TIME

def closed_message() -> str:
    return (
        "😴 <b>Hozir ish vaqtimiz tugagan</b>\n\n"
        f"⏰ Ish vaqti: {OPEN_TIME.strftime('%H:%M')} – {CLOSE_TIME.strftime('%H:%M')}\n"
        "Iltimos, ish vaqtida qaytadan murojaat qiling 🙏"
    )

logging.basicConfig(level=logging.INFO, format="%(asctime)s — %(levelname)s — %(message)s")

# ══════════════════════════════════════════
#  PERSISTENCE — active_orders va order_counter faylga saqlanadi
#  Railway'da "Volume" ulangan bo'lsa /data ishlatiladi, bo'lmasa joriy papka.
# ══════════════════════════════════════════
DATA_DIR  = Path(os.environ.get("DATA_DIR", "/data" if os.path.isdir("/data") else "."))
DATA_FILE = DATA_DIR / "bot_data.json"

def load_data() -> tuple[dict, int]:
    if DATA_FILE.exists():
        try:
            raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            return raw.get("active_orders", {}), raw.get("order_counter", 0)
        except Exception as e:
            logging.warning(f"Data faylini o'qishda xato: {e} — bo'sh holatda boshlanadi")
    return {}, 0

def save_data() -> None:
    try:
        DATA_FILE.write_text(
            json.dumps(
                {"active_orders": active_orders, "order_counter": order_counter},
                ensure_ascii=False, indent=2
            ),
            encoding="utf-8"
        )
    except Exception as e:
        logging.warning(f"Data faylini saqlashda xato: {e}")

# ══════════════════════════════════════════
#  FILIALLAR
# ══════════════════════════════════════════
BRANCHES = {
    "axsikent": {
        "title": "🏠 Axsikent filiali",
        "phone": "+998 95 162 50 50",
        "address": "Axsikent, Ayollar kompleksi oldida, Zilol ko'cha, 100-uy",
    },
    "jasmin": {
        "title": "🏠 Jasmin filiali",
        "phone": "+998 95 442 50 50",
        "address": "Jasmin ko'cha, Shoxsomsa",
    },
}

# ══════════════════════════════════════════
#  MENYU — narxlar (idish puli endi kategoriya darajasida qo'shiladi,
#  shuning uchun MENU = RAW_MENU, har bir taom narxi o'zgarmaydi)
# ══════════════════════════════════════════
RAW_MENU = {
    "🫕 Sho'rvalar": {
        "Mastava": 35_000,
        "Mol go'shtida sho'rva": 50_000,
        "Qo'y go'shtida sho'rva": 50_000,
        "Til sho'rva": 45_000,
        "Bo'yin sho'rva": 50_000,
        "Xash tuyoq sho'rva": 50_000,
        "Qozon kabob": 45_000,
        "Shoxona sho'rva": 70_000,
        "Manti sho'rva": 50_000,
        "Zakaz sho'rva": 70_000,
        "Manti": 8_000,
        "Kartoshka fri": 15_000,
        "Ko'za sho'rva": 40_000,
        "Osh Lazer": 35_000,
        "Quvvat sho'rva": 50_000,
    },
    "🥟 Somsalar": {
        "Qo'y go'shti turg'amchi": 10_000,
        "Mol go'shti turg'amchi": 10_000,
        "Sirli turg'amchi": 10_000,
        "Achchiq turg'amchi": 10_000,
        "Mayda turg'amchi": 8_000,
        "Mol go'shti tomchi": 10_000,
        "Tovuq go'shti somsa": 8_000,
        "Zakaz sirli": 10_000,
        "Ko'kli somsa": 5_000,
        "Kartoshkali somsa": 5_000,
        "Oshqovoqli somsa": 5_000,
        "Mador (So'qoq)": 7_000,
        "Tandir shashlik": 30_000,
        "Shoxona bir jilt": 20_000,
        "Sous": 3_000,
    },
    "🍣 Sushi rollar": {
        "Chuka salat": 25_000,
        "Filadelfiya (Klassik)": 85_000,
        "Filadelfiya (Avakado bilan)": 85_000,
        "Filadelfiya grill": 100_000,
        "Kaliforniya (Klassik)": 65_000,
        "Kaliforniya (Krabli)": 65_000,
        "Kaliforniya (Krevetka)": 80_000,
        "Kaliforniya (Ugor)": 85_000,
        "Kaliforniya (Tunets)": 70_000,
        "Запеченный с лососем": 65_000,
        "Запеченный с креветкой": 70_000,
        "Запеченный с курицей": 50_000,
        "Drakon roli": 120_000,
        "Сэт 1": 50_000,
        "Otjimaki roli": 70_000,
        "Бкин": 60_000,
        "Filadelfiya roli (Krevetka)": 95_000,
    },
    "🥗 Salatlar": {
        "Cho'ban salat": 30_000,
        "Сатэ": 45_000,
        "Класисcки": 20_000,
        "Choban salati": 35_000,
        "Свежий салат": 25_000,
        "Ташкентский салат": 20_000,
        "Vinegret": 30_000,
        "Греческий салат": 50_000,
        "Товукли салат": 36_000,
        "Chiroqchi": 35_000,
        "Акорошка": 20_000,
        "Сузма": 15_000,
        "Соллённый": 10_000,
        "Холодец": 20_000,
        "Цезарь": 40_000,
        "Хрустящий бакладжан": 45_000,
        "Каприз": 35_000,
        "Аливия": 35_000,
        "Шакароп": 15_000,
        "Свежий ассорти": 40_000,
        "Салат от ШЕФА": 80_000,
        "Японча": 50_000,
        "Баходиршох": 90_000,
        "American salat": 42_000,
        "Saboy qizilcha salat": 10_000,
        "Французский салат": 40_000,
        "Фантазия салат": 45_000,
        "Гнездо салат": 35_000,
        "Байский салат": 35_000,
        "Podshox salat": 50_000,
    },
    "🍖 Asosiy taomlar": {
        "Go'sht say": 75_000,
        "Sumburo": 90_000,
        "Uyg'urcha go'sht": 85_000,
        "Garnir": 20_000,
        "Adjika qayla": 5_000,
        "Ikra (qayla)": 5_000,
        "Smetana": 5_000,
        "Tovuq qanot": 35_000,
        "Uyg'urcha lagman": 40_000,
        "Premium Qozon kabob": 60_000,
        "Premium mastava": 35_000,
        "Чучвара гуштли": 30_000,
        "Сэт мясной 3п": 350_000,
        "Osh tuy oshi": 25_000,
        "Osh saboy": 20_000,
        "Zakaz osh": 40_000,
        "Do'lma": 35_000,
        "Ковурма лагмон": 40_000,
        "Sokoro": 90_000,
        "Tovuq": 40_000,
        "Mol go'shtida qotirma": 55_000,
        "Jiz 150 gr": 55_000,
        "Qo'zichoq till qaymoqli qayla bilan": 85_000,
    },
}

MENU: dict[str, dict[str, int]] = {
    cat: {name: price + SERVICE_FEE_PER_ITEM for name, price in items.items()}
    for cat, items in RAW_MENU.items()
}

ALL_ITEMS: dict[str, int] = {}
for _cat in MENU.values():
    ALL_ITEMS.update(_cat)

CATEGORY_IMAGES: dict[str, str] = {
    # "🫕 Sho'rvalar": "AgACAgI...",
    # "🥟 Somsalar": "AgACAgI...",
    # "🍣 Sushi rollar": "AgACAgI...",
    # "🥗 Salatlar": "AgACAgI...",
    # "🍖 Asosiy taomlar": "AgACAgI...",
}

# ══════════════════════════════════════════
#  HOLATLAR
# ══════════════════════════════════════════
class OrderState(StatesGroup):
    choosing_branch    = State()
    choosing_category  = State()
    choosing_item      = State()
    entering_phone     = State()
    entering_location   = State()
    entering_address    = State()
    choosing_payment    = State()
    confirming          = State()

# ══════════════════════════════════════════
#  YORDAMCHILAR
# ══════════════════════════════════════════
active_orders, order_counter = load_data()

def next_order_id() -> str:
    global order_counter
    order_counter += 1
    save_data()
    return f"SHX-{order_counter:03d}"

def fmt(n: int) -> str:
    return f"{n:,} so'm".replace(",", " ")

def cart_text(cart: dict) -> str:
    if not cart:
        return "Savatcha bo'sh"
    lines, total = [], 0
    for name, qty in cart.items():
        price = ALL_ITEMS[name]
        sub   = price * qty
        total += sub
        lines.append(f"• {name} × {qty} = {fmt(sub)}")
    lines.append(f"\n💰 <b>Taomlar jami: {fmt(total)}</b>")
    lines.append("🚚 Yetkazib berish narxi admin tomonidan tasdiqlangach aytiladi.")
    return "\n".join(lines)

def cart_grand_total(cart: dict) -> int:
    return sum(ALL_ITEMS[n] * q for n, q in cart.items())

PAY_LABELS = {
    "cash": "💵 Naqd pul", "card": "💳 Karta",
    "payme": "📱 Payme",   "click": "⚡ Click",
}

# ══════════════════════════════════════════
#  KLAVIATURALAR
# ══════════════════════════════════════════
def main_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🍽️ Menyu"),     KeyboardButton(text="🛒 Savatcha")],
        [KeyboardButton(text="📍 Buyurtmam"), KeyboardButton(text="📞 Aloqa")],
        [KeyboardButton(text="🔄 Filialni almashtirish")],
    ], resize_keyboard=True)

def branches_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=b["title"], callback_data=f"branch:{key}")]
        for key, b in BRANCHES.items()
    ])

def categories_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=cat, callback_data=f"cat:{cat}")]
        for cat in MENU
    ])

def items_kb(category: str, cart: dict | None = None) -> InlineKeyboardMarkup:
    cart = cart or {}
    rows = []
    for name, price in MENU[category].items():
        qty = cart.get(name, 0)
        label = f"{name} — {fmt(price)}"
        if qty > 0:
            label += f"  [🛒 {qty} ta]"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"item:{name}")])
    rows.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back:categories")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def after_add_kb() -> InlineKeyboardMarkup:
    """Taom savatga qo'shilgandan keyin chiqadigan 3 tugma."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Yana qo'shish",   callback_data="cart:add_more")],
        [InlineKeyboardButton(text="🗑️ Bekor qilish",    callback_data="cart:clear")],
        [InlineKeyboardButton(text="✅ Buyurtma berish",  callback_data="cart:checkout")],
    ])

def cart_kb() -> InlineKeyboardMarkup:
    return after_add_kb()

def phone_request_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📱 Raqamni ulashish", request_contact=True)],
    ], resize_keyboard=True, one_time_keyboard=True)

def location_request_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📍 Joylashuvni yuborish", request_location=True)],
    ], resize_keyboard=True, one_time_keyboard=True)

def payment_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💵 Naqd pul", callback_data="pay:cash")],
        [InlineKeyboardButton(text="💳 Karta",    callback_data="pay:card")],
        [InlineKeyboardButton(text="📱 Payme",    callback_data="pay:payme")],
        [InlineKeyboardButton(text="⚡ Click",    callback_data="pay:click")],
    ])

def confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Tasdiqlash",   callback_data="order:confirm"),
        InlineKeyboardButton(text="❌ Bekor qilish", callback_data="order:cancel"),
    ]])

def admin_order_kb(oid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Qabul qilish", callback_data=f"admin:accept:{oid}"),
            InlineKeyboardButton(text="❌ Rad etish",    callback_data=f"admin:reject:{oid}"),
        ]
    ])

def courier_kb(oid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Qabul qildim",   callback_data=f"courier:accept:{oid}")],
        [InlineKeyboardButton(text="🚚 Yo'lga chiqdim", callback_data=f"courier:onway:{oid}")],
        [InlineKeyboardButton(text="🏠 Yetkazdim",      callback_data=f"courier:done:{oid}")],
    ])

# ══════════════════════════════════════════
#  BOT
# ══════════════════════════════════════════
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp  = Dispatcher(storage=MemoryStorage())

MAIN_MENU_TEXTS = {"🍽️ Menyu", "🛒 Savatcha", "📍 Buyurtmam", "📞 Aloqa", "🔄 Filialni almashtirish"}

class WorkingHoursMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user and is_admin(user.id):
            return await handler(event, data)

        if not is_open_now():
            state: FSMContext = data.get("state")
            if isinstance(event, Message):
                await event.answer(closed_message(), reply_markup=main_kb())
            elif isinstance(event, CallbackQuery):
                await event.answer("😴 Hozir ish vaqtimiz tugagan. 09:00–02:00 oralig'ida kuting.", show_alert=True)
            if state:
                await state.clear()
            return

        return await handler(event, data)

dp.message.outer_middleware(WorkingHoursMiddleware())
dp.callback_query.outer_middleware(WorkingHoursMiddleware())


@dp.message(CommandStart())
async def cmd_start(msg: Message, state: FSMContext):
    await state.clear()
    await msg.answer(
        "🥟 <b>SHOXSOMSA</b> ga xush kelibsiz!\n\n"
        "Milliy taomlarimizdan buyurtma bering —\n"
        "kuryer eshigingizgacha yetkazadi! 🛵\n\n"
        f"⏰ Ish vaqti: {OPEN_TIME.strftime('%H:%M')} – {CLOSE_TIME.strftime('%H:%M')}\n\n"
        "Avval filialni tanlang 👇"
    )
    await state.set_state(OrderState.choosing_branch)
    await msg.answer("🏠 Filialni tanlang:", reply_markup=branches_kb())


@dp.message(F.text == "🔄 Filialni almashtirish")
async def change_branch(msg: Message, state: FSMContext):
    await state.update_data(cart={})
    await state.set_state(OrderState.choosing_branch)
    await msg.answer("🏠 Filialni tanlang:", reply_markup=branches_kb())


@dp.callback_query(F.data.startswith("branch:"))
async def choose_branch(cb: CallbackQuery, state: FSMContext):
    key = cb.data.split(":", 1)[1]
    branch = BRANCHES[key]
    await state.update_data(branch_key=key, cart={})
    await state.set_state(None)
    await cb.message.edit_text(
        f"✅ Siz <b>{branch['title']}</b> ni tanladingiz.\n\n"
        f"📍 {branch['address']}\n📞 {branch['phone']}"
    )
    await cb.message.answer("Quyidagi menyudan foydalaning 👇", reply_markup=main_kb())
    await cb.answer()


def _require_branch_kb_warning() -> str:
    return "⚠️ Avval filialni tanlang. /start ni bosing yoki \"🔄 Filialni almashtirish\" tugmasini ishlating."


@dp.message(F.text == "🍽️ Menyu")
async def show_menu(msg: Message, state: FSMContext):
    data = await state.get_data()
    if not data.get("branch_key"):
        await msg.answer(_require_branch_kb_warning())
        return
    await state.set_state(OrderState.choosing_category)
    await msg.answer("Kategoriyani tanlang 👇", reply_markup=categories_kb())

@dp.callback_query(F.data.startswith("cat:"))
async def choose_category(cb: CallbackQuery, state: FSMContext):
    cat = cb.data.split(":", 1)[1]
    data = await state.get_data()
    cart = data.get("cart", {})
    await state.update_data(current_category=cat)
    await state.set_state(OrderState.choosing_item)

    image_id = CATEGORY_IMAGES.get(cat)
    if image_id:
        try:
            await cb.message.delete()
        except Exception:
            pass
        await cb.message.answer_photo(
            photo=image_id,
            caption=f"<b>{cat}</b>\n\nTaom tanlang (bossangiz darhol savatga tushadi):",
            reply_markup=items_kb(cat, cart)
        )
    else:
        await cb.message.edit_text(
            f"<b>{cat}</b>\n\nTaom tanlang (bossangiz darhol savatga tushadi):",
            reply_markup=items_kb(cat, cart)
        )
    await cb.answer()

@dp.callback_query(F.data.startswith("item:"))
async def add_item(cb: CallbackQuery, state: FSMContext):
    name = cb.data.split(":", 1)[1]
    data = await state.get_data()
    cart = data.get("cart", {})
    cart[name] = cart.get(name, 0) + 1
    await state.update_data(cart=cart)

    qty = cart[name]
    await cb.answer(f"✅ {name} qo'shildi! Savatchada: {qty} ta")

    # Taom ro'yxatini yangilab, pastiga 3 tugmani ko'rsatamiz
    cat = data.get("current_category")
    text = f"🛒 <b>Savatchangiz:</b>\n\n{cart_text(cart)}"
    try:
        if cat:
            await cb.message.edit_text(
                f"<b>{cat}</b>\n\nTaom tanlang (bossangiz darhol savatga tushadi):",
                reply_markup=items_kb(cat, cart)
            )
        await cb.message.answer(text, reply_markup=after_add_kb())
    except Exception:
        pass

@dp.callback_query(F.data == "back:categories")
async def back_categories(cb: CallbackQuery, state: FSMContext):
    await state.set_state(OrderState.choosing_category)
    try:
        await cb.message.edit_text("Kategoriyani tanlang 👇", reply_markup=categories_kb())
    except Exception:
        try:
            await cb.message.delete()
        except Exception:
            pass
        await cb.message.answer("Kategoriyani tanlang 👇", reply_markup=categories_kb())
    await cb.answer()

@dp.message(F.text == "🛒 Savatcha")
async def show_cart(msg: Message, state: FSMContext):
    data = await state.get_data()
    if not data.get("branch_key"):
        await msg.answer(_require_branch_kb_warning())
        return
    cart = data.get("cart", {})
    await msg.answer(
        f"🛒 <b>Savatchangiz:</b>\n\n{cart_text(cart)}",
        reply_markup=cart_kb() if cart else None
    )

@dp.callback_query(F.data == "cart:add_more")
async def cart_add_more(cb: CallbackQuery, state: FSMContext):
    await state.set_state(OrderState.choosing_category)
    await cb.message.edit_text("Kategoriyani tanlang 👇", reply_markup=categories_kb())
    await cb.answer()

@dp.callback_query(F.data == "cart:clear")
async def cart_clear(cb: CallbackQuery, state: FSMContext):
    await state.update_data(cart={})
    await cb.message.edit_text("🗑️ Savatcha tozalandi.")
    await cb.answer()

@dp.callback_query(F.data == "cart:checkout")
async def checkout(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data.get("cart"):
        await cb.answer("Savatcha bo'sh!", show_alert=True)
        return
    await state.set_state(OrderState.entering_phone)
    await cb.message.answer(
        "📞 Telefon raqamingizni tasdiqlash uchun pastdagi tugmani bosing:",
        reply_markup=phone_request_kb()
    )
    await cb.answer()

# ──────────────────────────────────────────
# TELEFON: kontakt qabul qilish → to'g'ridan-to'g'ri geolokatsiyaga o'tish
# ──────────────────────────────────────────
@dp.message(OrderState.entering_phone, F.contact)
async def enter_phone_contact(msg: Message, state: FSMContext):
    phone = msg.contact.phone_number
    if not phone.startswith("+"):
        phone = "+" + phone
    await state.update_data(client_phone=phone)
    await state.set_state(OrderState.entering_location)
    await msg.answer(
        "✅ Raqam qabul qilindi!\n\n"
        "📍 Endi joylashuvingizni yuboring (xaritadan aniq nuqtani tanlash mumkin):",
        reply_markup=location_request_kb()
    )

@dp.message(OrderState.entering_phone, F.text.in_(MAIN_MENU_TEXTS))
async def enter_phone_menu_interrupt(msg: Message, state: FSMContext):
    # Foydalanuvchi checkout jarayonida asosiy menyu tugmasini bosdi —
    # checkout holatini tozalab, oddiy tugma ishlovchisiga yo'naltiramiz
    await state.set_state(None)
    await _route_main_menu_text(msg, state)

@dp.message(OrderState.entering_phone)
async def enter_phone_invalid(msg: Message):
    await msg.answer(
        "⚠️ Iltimos, raqamni faqat <b>\"📱 Raqamni ulashish\"</b> tugmasi orqali yuboring.",
        reply_markup=phone_request_kb()
    )

# ──────────────────────────────────────────
# GEOLOKATSIYA — majburiy, mustahkamlangan
# ──────────────────────────────────────────
@dp.message(OrderState.entering_location, F.location)
async def enter_location(msg: Message, state: FSMContext):
    lat, lon = msg.location.latitude, msg.location.longitude
    await state.update_data(client_lat=lat, client_lon=lon)
    await state.set_state(OrderState.entering_address)
    await msg.answer(
        "✅ Joylashuv qabul qilindi!\n\n"
        "📝 Endi aniqlik uchun manzilingizni yozing (mo'ljal, uy/xonadon raqami va h.k.):",
        reply_markup=None
    )

@dp.message(OrderState.entering_location, F.text.in_(MAIN_MENU_TEXTS))
async def enter_location_menu_interrupt(msg: Message, state: FSMContext):
    await state.set_state(None)
    await _route_main_menu_text(msg, state)

@dp.message(OrderState.entering_location)
async def enter_location_invalid(msg: Message):
    await msg.answer(
        "⚠️ Iltimos, joylashuvni faqat <b>\"📍 Joylashuvni yuborish\"</b> tugmasi orqali yuboring.\n"
        "Geolokatsiya buyurtmani to'g'ri yetkazib berish uchun majburiy.",
        reply_markup=location_request_kb()
    )

# ──────────────────────────────────────────
# MANZIL — endi boshqa tugmalar bilan to'qnashmaydi
# ──────────────────────────────────────────
@dp.message(OrderState.entering_address, F.text.in_(MAIN_MENU_TEXTS))
async def enter_address_menu_interrupt(msg: Message, state: FSMContext):
    await state.set_state(None)
    await _route_main_menu_text(msg, state)

@dp.message(OrderState.entering_address, F.text)
async def enter_address(msg: Message, state: FSMContext):
    await state.update_data(client_address=msg.text)
    await state.set_state(OrderState.choosing_payment)
    await msg.answer("💳 To'lov usulini tanlang:", reply_markup=payment_kb())

@dp.message(OrderState.entering_address)
async def enter_address_invalid(msg: Message):
    await msg.answer("⚠️ Iltimos, manzilni matn ko'rinishida yozing.")

@dp.callback_query(F.data.startswith("pay:"))
async def choose_payment(cb: CallbackQuery, state: FSMContext):
    method = cb.data.split(":", 1)[1]
    await state.update_data(payment=method)
    await state.set_state(OrderState.confirming)
    data   = await state.get_data()
    cart   = data.get("cart", {})
    branch = BRANCHES[data["branch_key"]]
    await cb.message.edit_text(
        f"📋 <b>Buyurtma tasdig'i</b>\n\n"
        f"🏠 Filial: {branch['title']}\n"
        f"📞 {data['client_phone']}\n"
        f"📍 {data['client_address']}\n"
        f"🗺 Lokatsiya: {data['client_lat']:.5f}, {data['client_lon']:.5f}\n\n"
        f"🛒 <b>Tarkib:</b>\n{cart_text(cart)}\n\n"
        f"💳 To'lov: {PAY_LABELS[method]}\n\n"
        f"⚠️ Yetkazib berish narxi admin tasdiqlagandan keyin aniqlanadi.\n\n"
        f"Tasdiqlaysizmi?",
        reply_markup=confirm_kb()
    )
    await cb.answer()

@dp.callback_query(F.data == "order:cancel")
async def order_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("❌ Buyurtma bekor qilindi.")
    await cb.answer()

@dp.callback_query(F.data == "order:confirm")
async def order_confirm(cb: CallbackQuery, state: FSMContext):
    data   = await state.get_data()
    cart   = data.get("cart", {})
    method = data.get("payment", "cash")
    branch = BRANCHES[data["branch_key"]]
    items_total = cart_grand_total(cart)
    oid    = next_order_id()

    active_orders[oid] = {
        "client_id": cb.from_user.id,
        "phone": data["client_phone"],
        "address": data["client_address"],
        "lat": data.get("client_lat"), "lon": data.get("client_lon"),
        "branch_key": data["branch_key"],
        "cart": cart, "payment": method,
        "items_total": items_total,
        "delivery_price": None,   # admin keyinroq kiritadi
        "total": None,            # delivery kiritilgandan keyin to'liq summa
        "status": "new",
    }
    save_data()

    await cb.message.edit_text(
        f"✅ <b>Buyurtmangiz qabul qilindi!</b>\n\n"
        f"🔖 Raqam: <b>#{oid}</b>\n"
        f"⏳ Admin tomonidan tasdiqlanishi va yetkazib berish narxi belgilanishi kutilmoqda.\n\n"
        f"Holatni bilish: /status_{oid}"
    )
    await cb.message.answer("Asosiy menyu 👇", reply_markup=main_kb())

    items_str = "\n".join(f"• {n} × {q}" for n, q in cart.items())
    notify = (
        f"🔔 <b>YANGI BUYURTMA #{oid}</b>\n\n"
        f"🏠 Filial: <b>{branch['title']}</b>\n"
        f"📞 {data['client_phone']}\n"
        f"📍 {data['client_address']}\n\n"
        f"📦 Tarkib:\n{items_str}\n\n"
        f"💳 {PAY_LABELS[method]}\n"
        f"💰 Taomlar jami: {fmt(items_total)}\n"
        f"🚚 Yetkazib berish narxini kiriting: <code>/delivery_{oid} 15000</code>"
    )
    lat, lon = data.get("client_lat"), data.get("client_lon")
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, notify, reply_markup=admin_order_kb(oid))
            if lat is not None and lon is not None:
                await bot.send_location(admin_id, latitude=lat, longitude=lon)
        except Exception as e:
            logging.warning(f"Admin {admin_id} ga yuborilmadi: {e}")

    await state.clear()
    await cb.answer()

# ──────────────────────────────────────────
# ADMIN: yetkazib berish narxini kiritish
# Format: /delivery_SHX-001 15000
# ──────────────────────────────────────────
@dp.message(F.text.regexp(r"^/delivery_(\S+)\s+(\d+)$"))
async def admin_set_delivery(msg: Message):
    if not is_admin(msg.from_user.id):
        return
    import re
    m = re.match(r"^/delivery_(\S+)\s+(\d+)$", msg.text)
    oid, price_str = m.group(1), m.group(2)
    order = active_orders.get(oid)
    if not order:
        await msg.answer("❌ Bunday buyurtma topilmadi.")
        return
    price = int(price_str)
    order["delivery_price"] = price
    order["total"] = order["items_total"] + price
    save_data()
    await msg.answer(
        f"✅ #{oid} uchun yetkazib berish narxi: {fmt(price)}\n"
        f"💰 Yakuniy summa: {fmt(order['total'])}\n\n"
        f"Endi buyurtmani qabul qilishingiz mumkin."
    )
    try:
        await bot.send_message(
            order["client_id"],
            f"🚚 <b>#{oid}</b> uchun yetkazib berish narxi: {fmt(price)}\n"
            f"💰 <b>Yakuniy summa: {fmt(order['total'])}</b>"
        )
    except Exception as e:
        logging.warning(f"Mijozga yetkazib berish narxi yuborilmadi: {e}")

# ──────────────────────────────────────────
# ADMIN: Qabul qilindi / Rad etildi
# ──────────────────────────────────────────
@dp.callback_query(F.data.startswith("admin:"))
async def admin_action(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("Sizda ruxsat yo'q.", show_alert=True)
        return

    _, action, oid = cb.data.split(":")
    order = active_orders.get(oid)
    if not order:
        await cb.answer("Buyurtma topilmadi.", show_alert=True)
        return

    if order["status"] != "new":
        await cb.answer("Bu buyurtma allaqachon ko'rib chiqilgan.", show_alert=True)
        return

    if action == "accept" and order.get("delivery_price") is None:
        await cb.answer(
            f"⚠️ Avval yetkazib berish narxini kiriting:\n/delivery_{oid} 15000",
            show_alert=True
        )
        return

    admin_name = cb.from_user.full_name
    branch = BRANCHES[order["branch_key"]]

    if action == "accept":
        order["status"] = "accept"
        save_data()
        await cb.answer("✅ Qabul qilindi")
        status_line = f"✅ <b>Qabul qilindi</b> — {admin_name}"
        client_text = (
            f"✅ <b>Buyurtmangiz #{oid} qabul qilindi!</b>\n\n"
            "Tez orada tayyorlanadi va kuryer yo'lga chiqadi 🛵"
        )
        try:
            await bot.send_message(COURIER_ID,
                f"🔔 <b>Yangi buyurtma #{oid}</b> admin tomonidan tasdiqlandi.\n\n"
                f"🏠 {branch['title']}\n"
                f"📞 {order['phone']}\n"
                f"📍 {order['address']}\n💰 {fmt(order['total'])}",
                reply_markup=courier_kb(oid))
            if order.get("lat") is not None and order.get("lon") is not None:
                await bot.send_location(COURIER_ID, latitude=order["lat"], longitude=order["lon"])
        except Exception as e:
            logging.warning(f"Kuryerga yuborilmadi: {e}")
    else:
        order["status"] = "rejected"
        save_data()
        await cb.answer("❌ Rad etildi")
        status_line = f"❌ <b>Rad etildi</b> — {admin_name}"
        client_text = (
            f"❌ <b>Buyurtmangiz #{oid} rad etildi.</b>\n\n"
            "Sabab haqida ma'lumot uchun biz bilan bog'laning 📞"
        )

    try:
        await bot.send_message(order["client_id"], client_text)
    except Exception as e:
        logging.warning(f"Mijozga yuborilmadi: {e}")

    for admin_id in ADMIN_IDS:
        if admin_id == cb.from_user.id:
            continue
        try:
            await bot.send_message(admin_id, f"ℹ️ Buyurtma #{oid}: {status_line}")
        except Exception:
            pass

    try:
        await cb.message.edit_text(cb.message.text + f"\n\n{status_line}")
    except Exception:
        pass

COURIER_STEPS = {
    "accept": ("🍳 Tayyorlanmoqda",  "Buyurtmangiz tayyorlanmoqda..."),
    "onway":  ("🛵 Kuryer yo'lda",   "Kuryer yo'lga chiqdi! 🛵"),
    "done":   ("✅ Yetkazildi",       "Buyurtmangiz yetkazildi! Rahmat 🥟"),
}

@dp.callback_query(F.data.startswith("courier:"))
async def courier_action(cb: CallbackQuery):
    _, action, oid = cb.data.split(":")
    order = active_orders.get(oid)
    if not order:
        await cb.answer("Buyurtma topilmadi.", show_alert=True)
        return
    label, client_msg = COURIER_STEPS[action]
    order["status"] = action
    save_data()
    await cb.answer(f"✅ {label}")
    try:
        await bot.send_message(order["client_id"],
            f"📦 <b>#{oid} — {label}</b>\n\n{client_msg}")
    except Exception as e:
        logging.warning(f"Mijozga yuborilmadi: {e}")
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, f"🔄 <b>#{oid}</b> → {label}")
        except Exception:
            pass
    await cb.message.edit_text(
        cb.message.text + f"\n\n✅ <b>{label}</b>",
        reply_markup=courier_kb(oid) if action != "done" else None
    )

@dp.message(F.text.startswith("/status_"))
async def check_status(msg: Message):
    oid   = msg.text.replace("/status_", "").strip()
    order = active_orders.get(oid)
    if not order:
        await msg.answer("❌ Buyurtma topilmadi.")
        return
    labels = {"new": "🕐 Admin tasdig'ini kutmoqda", "accept": "🍳 Tayyorlanmoqda",
              "rejected": "❌ Rad etildi",
              "onway": "🛵 Kuryer yo'lda", "done": "✅ Yetkazildi"}
    total_line = fmt(order["total"]) if order.get("total") is not None else "Hali aniqlanmagan (yetkazib berish narxi kutilmoqda)"
    await msg.answer(
        f"📦 <b>#{oid} holati:</b>\n\n{labels.get(order['status'],'—')}\n\n"
        f"💰 {total_line}\n💳 {PAY_LABELS[order['payment']]}"
    )

@dp.message(F.text == "📍 Buyurtmam")
async def my_orders(msg: Message):
    mine = [
        (oid, o) for oid, o in active_orders.items()
        if o.get("client_id") == msg.from_user.id
    ]
    if not mine:
        await msg.answer("Sizda hali buyurtma yo'q.")
        return
    labels = {"new": "🕐 Kutilmoqda", "accept": "🍳 Tayyorlanmoqda",
              "rejected": "❌ Rad etildi", "onway": "🛵 Yo'lda", "done": "✅ Yetkazildi"}
    lines = [
        f"• #{oid} — {labels.get(o['status'], '—')}" for oid, o in mine
    ]
    await msg.answer("📍 <b>Buyurtmalaringiz:</b>\n\n" + "\n".join(lines))

@dp.message(F.text == "📞 Aloqa")
async def contact(msg: Message):
    lines = ["📞 <b>SHOXSOMSA</b>\n"]
    for b in BRANCHES.values():
        lines.append(f"🏠 <b>{b['title']}</b>\n📍 {b['address']}\n📞 {b['phone']}\n")
    lines.append(f"⏰ {OPEN_TIME.strftime('%H:%M')} – {CLOSE_TIME.strftime('%H:%M')}")
    await msg.answer("\n".join(lines))

@dp.message(Command("orders"))
async def admin_orders(msg: Message):
    if not is_admin(msg.from_user.id):
        return
    if not active_orders:
        await msg.answer("Hozircha buyurtma yo'q.")
        return
    labels = {"new":"Yangi","accept":"Tayyorlanmoqda","rejected":"Rad etildi",
              "onway":"Yo'lda","done":"Yetkazildi"}
    lines  = []
    for oid, o in active_orders.items():
        total_str = fmt(o["total"]) if o.get("total") is not None else "narx kutilmoqda"
        lines.append(
            f"• <b>#{oid}</b> — {BRANCHES[o['branch_key']]['title']} — {total_str} — {labels.get(o['status'],'—')}"
        )
    await msg.answer("📊 <b>Buyurtmalar:</b>\n\n" + "\n".join(lines))

# ──────────────────────────────────────────
# ADMIN YORDAMCHISI: kategoriya rasmlari uchun file_id olish
# ──────────────────────────────────────────
@dp.message(F.photo)
async def admin_get_file_id(msg: Message):
    if not is_admin(msg.from_user.id):
        return
    file_id = msg.photo[-1].file_id
    await msg.answer(
        f"🖼 <b>file_id:</b>\n<code>{file_id}</code>\n\n"
        "Shu ID ni CATEGORY_IMAGES lug'atiga tegishli kategoriya nomi ostiga qo'ying."
    )

# ──────────────────────────────────────────
# Yordamchi: checkout oqimi to'xtatilganda asosiy menyu tugmalariga yo'naltirish
# ──────────────────────────────────────────
async def _route_main_menu_text(msg: Message, state: FSMContext):
    text = msg.text
    if text == "🍽️ Menyu":
        await show_menu(msg, state)
    elif text == "🛒 Savatcha":
        await show_cart(msg, state)
    elif text == "📍 Buyurtmam":
        await my_orders(msg)
    elif text == "📞 Aloqa":
        await contact(msg)
    elif text == "🔄 Filialni almashtirish":
        await change_branch(msg, state)

async def main():
    logging.info("🥟 SHOXSOMSA bot ishga tushdi!")
    logging.info(f"Adminlar: {ADMIN_IDS}")
    logging.info(f"Filiallar: {list(BRANCHES.keys())}")
    logging.info(f"Menyuda jami taom: {len(ALL_ITEMS)}")
    logging.info(f"Data fayli: {DATA_FILE}")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

if __name__ == "__main__":
    asyncio.run(main())
