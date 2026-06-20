#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SHOXSOMSA — Milliy Taomlar Telegram Bot
Railway deployment uchun tayyor (env variables ishlatadi)

Yangiliklar:
  - 2 filial (Axsikent, Jasmin) — har biri o'z manzil/telefoni bilan
  - To'liq menyu (93 taom, 5 kategoriya)
  - Har bir dona uchun avtomatik +1000 so'm (narxga singdirilgan, ko'rinmaydi)
  - Bir nechta admin, ish vaqti (09:00-02:00), admin qabul/rad tugmalari
"""

import asyncio
import logging
import os
from datetime import datetime, time
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton
)
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ══════════════════════════════════════════
#  SOZLAMALAR — Railway Environment Variables
# ══════════════════════════════════════════
BOT_TOKEN  = os.environ["BOT_TOKEN"]
COURIER_ID = int(os.environ["COURIER_ID"])

# ──────────────────────────────────────────
# BIR NECHTA ADMIN
# Railway "Variables" bo'limida ADMIN_IDS ga vergul bilan ajratib yozing:
#   ADMIN_IDS=123456789,987654321,555555555
# Eski ADMIN_ID o'zgaruvchisi ham hali ishlaydi (orqaga moslik uchun).
# ──────────────────────────────────────────
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

DELIVERY_PRICE = 10_000
SERVICE_FEE_PER_ITEM = 1_000  # har bir dona ovqatga avtomatik qo'shiladigan summa (narxga singdiriladi)

# ──────────────────────────────────────────
# ISH VAQTI — 09:00 dan 02:00 gacha (Toshkent vaqti, kunni kesib o'tadi)
# ──────────────────────────────────────────
TIMEZONE   = ZoneInfo("Asia/Tashkent")
OPEN_TIME  = time(9, 0)    # 09:00
CLOSE_TIME = time(2, 0)    # 02:00 (keyingi kun)

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
#  MENYU — asl narxlar (RAW), botda +1000/dona qo'shilib ko'rsatiladi
#  Ikkala filialda hozircha bir xil narx (keyinroq filial bo'yicha
#  farqlash kerak bo'lsa, BRANCH_MENU strukturasiga o'tkaziladi).
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

# Botda ishlatiladigan yakuniy menyu — har bir narxga +SERVICE_FEE_PER_ITEM qo'shilgan
MENU: dict[str, dict[str, int]] = {
    cat: {name: price + SERVICE_FEE_PER_ITEM for name, price in items.items()}
    for cat, items in RAW_MENU.items()
}

ALL_ITEMS: dict[str, int] = {}
for _cat in MENU.values():
    ALL_ITEMS.update(_cat)

# ──────────────────────────────────────────
# KATEGORIYA RASMLARI
# Har bir kategoriya uchun Telegram file_id shu yerga yoziladi.
# Avval botga rasmni yuboring, /getfileid buyrug'i bilan ID oling,
# keyin shu lug'atga kategoriya nomi bilan bir xil kalit ostida qo'ying.
# Bo'sh qoldirilgan kategoriyalar uchun rasm yuborilmaydi, faqat matn chiqadi.
# ──────────────────────────────────────────
CATEGORY_IMAGES: dict[str, str] = {
    # "🫕 Sho'rvalar": "AgACAgI...",      # file_id shu yerga
    # "🥟 Somsalar": "AgACAgI...",
    # "🍣 Sushi rollar": "AgACAgI...",
    # "🥗 Salatlar": "AgACAgI...",
    # "🍖 Asosiy taomlar": "AgACAgI...",
}

# ══════════════════════════════════════════
#  HOLATLAR
# ══════════════════════════════════════════
class OrderState(StatesGroup):
    choosing_branch   = State()
    choosing_category = State()
    choosing_item     = State()
    entering_name     = State()
    entering_phone    = State()
    entering_address  = State()
    choosing_payment  = State()
    confirming        = State()

# ══════════════════════════════════════════
#  YORDAMCHILAR
# ══════════════════════════════════════════
order_counter = 0

def next_order_id() -> str:
    global order_counter
    order_counter += 1
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
    lines += [
        f"\n🚚 Yetkazib berish: {fmt(DELIVERY_PRICE)}",
        f"💰 <b>Jami: {fmt(total + DELIVERY_PRICE)}</b>",
    ]
    return "\n".join(lines)

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

def items_kb(category: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"{name} — {fmt(price)}", callback_data=f"item:{name}")]
        for name, price in MENU[category].items()
    ]
    rows.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back:categories")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def cart_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Yana qo'shish",  callback_data="cart:add_more")],
        [InlineKeyboardButton(text="🗑️ Tozalash",       callback_data="cart:clear")],
        [InlineKeyboardButton(text="✅ Buyurtma berish", callback_data="cart:checkout")],
    ])

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
            InlineKeyboardButton(text="✅ Qabul qilindi", callback_data=f"admin:accept:{oid}"),
            InlineKeyboardButton(text="❌ Rad etildi",    callback_data=f"admin:reject:{oid}"),
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
active_orders: dict[str, dict] = {}

# ──────────────────────────────────────────
# ISH VAQTI TEKSHIRUVI — middleware sifatida ishlaydi.
# Bu yondashuv muhim: aiogram'da filtrsiz @dp.message() handler birinchi
# ishlaydi va keyingi handlerlarga yo'l qoldirmaydi. Shuning uchun ish vaqti
# tekshiruvini "outer middleware" qilib yozamiz — u har bir update'dan oldin
# ishlaydi, lekin boshqa handlerlarni (masalan rasm qabul qilish) to'smaydi.
# Adminlarga cheklov qo'yilmaydi, ular istalgan vaqt botdan foydalansin.
# ──────────────────────────────────────────
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from typing import Callable, Awaitable, Any

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
            return  # handlerga yuborilmaydi — bot "yopiq" deb javob berdi

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
    await state.update_data(current_category=cat)
    await state.set_state(OrderState.choosing_item)

    image_id = CATEGORY_IMAGES.get(cat)
    if image_id:
        # Rasmli xabar — eski xabarni o'chirib, yangi rasm+tugma xabar yuboramiz
        # (rasmli xabarni "edit_text" qila olmaymiz, shuning uchun yangi yuboramiz)
        try:
            await cb.message.delete()
        except Exception:
            pass
        await cb.message.answer_photo(
            photo=image_id,
            caption=f"<b>{cat}</b>\n\nTaom tanlang:",
            reply_markup=items_kb(cat)
        )
    else:
        await cb.message.edit_text(f"<b>{cat}</b>\n\nTaom tanlang:", reply_markup=items_kb(cat))
    await cb.answer()

@dp.callback_query(F.data.startswith("item:"))
async def add_item(cb: CallbackQuery, state: FSMContext):
    name = cb.data.split(":", 1)[1]
    data = await state.get_data()
    cart = data.get("cart", {})
    cart[name] = cart.get(name, 0) + 1
    await state.update_data(cart=cart)
    await cb.answer(f"✅ {name} qo'shildi!")

@dp.callback_query(F.data == "back:categories")
async def back_categories(cb: CallbackQuery, state: FSMContext):
    await state.set_state(OrderState.choosing_category)
    try:
        await cb.message.edit_text("Kategoriyani tanlang 👇", reply_markup=categories_kb())
    except Exception:
        # Oldingi xabar rasmli bo'lsa, edit_text ishlamaydi — yangi xabar yuboramiz
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
        f"🛒 <b>Savatchingiz:</b>\n\n{cart_text(cart)}",
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
    await state.set_state(OrderState.entering_name)
    await cb.message.answer("👤 Ism Familiyangizni kiriting:")
    await cb.answer()

@dp.message(OrderState.entering_name)
async def enter_name(msg: Message, state: FSMContext):
    await state.update_data(client_name=msg.text)
    await state.set_state(OrderState.entering_phone)
    await msg.answer("📞 Telefon raqamingiz:\nMasalan: +998901234567")

@dp.message(OrderState.entering_phone)
async def enter_phone(msg: Message, state: FSMContext):
    await state.update_data(client_phone=msg.text)
    await state.set_state(OrderState.entering_address)
    await msg.answer("📍 Yetkazib berish manzili:")

@dp.message(OrderState.entering_address)
async def enter_address(msg: Message, state: FSMContext):
    await state.update_data(client_address=msg.text)
    await state.set_state(OrderState.choosing_payment)
    await msg.answer("💳 To'lov usulini tanlang:", reply_markup=payment_kb())

@dp.callback_query(F.data.startswith("pay:"))
async def choose_payment(cb: CallbackQuery, state: FSMContext):
    method = cb.data.split(":", 1)[1]
    await state.update_data(payment=method)
    await state.set_state(OrderState.confirming)
    data   = await state.get_data()
    cart   = data.get("cart", {})
    branch = BRANCHES[data["branch_key"]]
    total  = sum(ALL_ITEMS[n] * q for n, q in cart.items()) + DELIVERY_PRICE
    await cb.message.edit_text(
        f"📋 <b>Buyurtma tasdig'i</b>\n\n"
        f"🏠 Filial: {branch['title']}\n"
        f"👤 {data['client_name']}\n"
        f"📞 {data['client_phone']}\n"
        f"📍 {data['client_address']}\n\n"
        f"🛒 <b>Tarkib:</b>\n{cart_text(cart)}\n\n"
        f"💳 To'lov: {PAY_LABELS[method]}\n\nTasdiqlaysizmi?",
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
    total  = sum(ALL_ITEMS[n] * q for n, q in cart.items()) + DELIVERY_PRICE
    oid    = next_order_id()

    active_orders[oid] = {
        "client_id": cb.from_user.id, "client_name": data["client_name"],
        "phone": data["client_phone"], "address": data["client_address"],
        "branch_key": data["branch_key"],
        "cart": cart, "payment": method, "total": total, "status": "new",
    }

    await cb.message.edit_text(
        f"✅ <b>Buyurtmangiz qabul qilindi!</b>\n\n"
        f"🔖 Raqam: <b>#{oid}</b>\n"
        f"⏳ Admin tomonidan tasdiqlanishi kutilmoqda.\n\n"
        f"Holatni bilish: /status_{oid}"
    )

    items_str = "\n".join(f"• {n} × {q}" for n, q in cart.items())
    notify = (
        f"🔔 <b>YANGI BUYURTMA #{oid}</b>\n\n"
        f"🏠 Filial: <b>{branch['title']}</b>\n"
        f"👤 {data['client_name']} · {data['client_phone']}\n"
        f"📍 {data['client_address']}\n\n"
        f"📦 Tarkib:\n{items_str}\n\n"
        f"💳 {PAY_LABELS[method]}\n💰 Jami: {fmt(total)}"
    )
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, notify, reply_markup=admin_order_kb(oid))
        except Exception as e:
            logging.warning(f"Admin {admin_id} ga yuborilmadi: {e}")

    await state.clear()
    await cb.answer()

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

    admin_name = cb.from_user.full_name
    branch = BRANCHES[order["branch_key"]]

    if action == "accept":
        order["status"] = "accept"
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
                f"👤 {order['client_name']} · {order['phone']}\n"
                f"📍 {order['address']}\n💰 {fmt(order['total'])}",
                reply_markup=courier_kb(oid))
        except Exception as e:
            logging.warning(f"Kuryerga yuborilmadi: {e}")
    else:
        order["status"] = "rejected"
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
    await msg.answer(
        f"📦 <b>#{oid} holati:</b>\n\n{labels.get(order['status'],'—')}\n\n"
        f"💰 {fmt(order['total'])}\n💳 {PAY_LABELS[order['payment']]}"
    )

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
    lines  = [
        f"• <b>#{oid}</b> — {BRANCHES[o['branch_key']]['title']} — {o['client_name']} — {fmt(o['total'])} — {labels.get(o['status'],'—')}"
        for oid, o in active_orders.items()
    ]
    await msg.answer("📊 <b>Buyurtmalar:</b>\n\n" + "\n".join(lines))

# ──────────────────────────────────────────
# ADMIN YORDAMCHISI: kategoriya rasmlari uchun file_id olish
# Admin botga rasm yuborsa (caption shart emas), bot file_id ni qaytaradi.
# Shu ID ni CATEGORY_IMAGES lug'atiga qo'lda yozib qo'yiladi.
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

async def main():
    logging.info("🥟 SHOXSOMSA bot ishga tushdi!")
    logging.info(f"Adminlar: {ADMIN_IDS}")
    logging.info(f"Filiallar: {list(BRANCHES.keys())}")
    logging.info(f"Menyuda jami taom: {len(ALL_ITEMS)}")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

if __name__ == "__main__":
    asyncio.run(main())
