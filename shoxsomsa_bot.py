#!/usr/bin/env python3
"""
SHOXSOMSA — Milliy Taomlar Telegram Bot
Railway deployment uchun tayyor (env variables ishlatadi)
"""

import asyncio
import logging
import os
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
ADMIN_ID   = int(os.environ["ADMIN_ID"])
COURIER_ID = int(os.environ["COURIER_ID"])

DELIVERY_PRICE = 10_000

logging.basicConfig(level=logging.INFO, format="%(asctime)s — %(levelname)s — %(message)s")

# ══════════════════════════════════════════
#  MENYU
# ══════════════════════════════════════════
MENU = {
    "🥟 Somsalar": {
        "Somsa": 8_000, "Katta Somsa": 12_000, "Qaymoqli Somsa": 10_000,
    },
    "🍜 Lag'monlar": {
        "Uyg'ur Lag'mon": 28_000, "Qovurma Lag'mon": 32_000, "Suyuq Lag'mon": 25_000,
    },
    "🍢 Shashliklar": {
        "Qo'y Shashlik": 35_000, "Tovuq Shashlik": 22_000, "Liver Shashlik": 18_000,
    },
    "🍚 Oshlar": {
        "Farg'ona Oshi": 30_000, "Toshkent Oshi": 28_000, "Qo'zi Oshi": 45_000,
    },
    "🫕 Sho'rvalar": {
        "Shurpa": 22_000, "Mastava": 20_000, "Qozonkabob": 38_000,
    },
    "🥟 Chuchvaralar": {
        "Chuchvara": 18_000, "Qaymoqli Chuchvara": 22_000,
    },
    "🍵 Ichimliklar": {
        "Kompot": 5_000, "Ayron": 6_000, "Ko'k choy": 4_000,
    },
}

ALL_ITEMS: dict[str, int] = {}
for _cat in MENU.values():
    ALL_ITEMS.update(_cat)

# ══════════════════════════════════════════
#  HOLATLAR
# ══════════════════════════════════════════
class OrderState(StatesGroup):
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
    ], resize_keyboard=True)

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

@dp.message(CommandStart())
async def cmd_start(msg: Message, state: FSMContext):
    await state.clear()
    await msg.answer(
        "🥟 <b>SHOXSOMSA</b> ga xush kelibsiz!\n\n"
        "Milliy taomlarimizdan buyurtma bering —\n"
        "kuryer eshigingizgacha yetkazadi! 🛵\n\n"
        "⏰ Ish vaqti: 10:00 – 23:00",
        reply_markup=main_kb()
    )

@dp.message(F.text == "🍽️ Menyu")
async def show_menu(msg: Message, state: FSMContext):
    await state.set_state(OrderState.choosing_category)
    await msg.answer("Kategoriyani tanlang 👇", reply_markup=categories_kb())

@dp.callback_query(F.data.startswith("cat:"))
async def choose_category(cb: CallbackQuery, state: FSMContext):
    cat = cb.data.split(":", 1)[1]
    await state.update_data(current_category=cat)
    await state.set_state(OrderState.choosing_item)
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
    await cb.message.edit_text("Kategoriyani tanlang 👇", reply_markup=categories_kb())
    await cb.answer()

@dp.message(F.text == "🛒 Savatcha")
async def show_cart(msg: Message, state: FSMContext):
    data = await state.get_data()
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
    data  = await state.get_data()
    cart  = data.get("cart", {})
    total = sum(ALL_ITEMS[n] * q for n, q in cart.items()) + DELIVERY_PRICE
    await cb.message.edit_text(
        f"📋 <b>Buyurtma tasdig'i</b>\n\n"
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
    total  = sum(ALL_ITEMS[n] * q for n, q in cart.items()) + DELIVERY_PRICE
    oid    = next_order_id()

    active_orders[oid] = {
        "client_id": cb.from_user.id, "client_name": data["client_name"],
        "phone": data["client_phone"], "address": data["client_address"],
        "cart": cart, "payment": method, "total": total, "status": "new",
    }

    await cb.message.edit_text(
        f"✅ <b>Buyurtmangiz qabul qilindi!</b>\n\n"
        f"🔖 Raqam: <b>#{oid}</b>\n"
        f"⏳ Kuryer tez orada tayinlanadi.\n\n"
        f"Holatni bilish: /status_{oid}"
    )

    items_str = "\n".join(f"• {n} × {q}" for n, q in cart.items())
    notify = (
        f"🔔 <b>YANGI BUYURTMA #{oid}</b>\n\n"
        f"👤 {data['client_name']} · {data['client_phone']}\n"
        f"📍 {data['client_address']}\n\n"
        f"📦 Tarkib:\n{items_str}\n\n"
        f"💳 {PAY_LABELS[method]}\n💰 Jami: {fmt(total)}"
    )
    for uid in (ADMIN_ID, COURIER_ID):
        try:
            await bot.send_message(uid, notify,
                reply_markup=courier_kb(oid) if uid == COURIER_ID else None)
        except Exception as e:
            logging.warning(f"ID {uid} ga yuborilmadi: {e}")

    await state.clear()
    await cb.answer()

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
    try:
        await bot.send_message(ADMIN_ID, f"🔄 <b>#{oid}</b> → {label}")
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
    labels = {"new": "🕐 Qabul qilindi", "accept": "🍳 Tayyorlanmoqda",
              "onway": "🛵 Kuryer yo'lda", "done": "✅ Yetkazildi"}
    await msg.answer(
        f"📦 <b>#{oid} holati:</b>\n\n{labels.get(order['status'],'—')}\n\n"
        f"💰 {fmt(order['total'])}\n💳 {PAY_LABELS[order['payment']]}"
    )

@dp.message(F.text == "📞 Aloqa")
async def contact(msg: Message):
    await msg.answer(
        "📞 <b>SHOXSOMSA</b>\n\n"
        "📍 Toshkent, Chilonzor tumani\n"
        "📞 +998 90 123 45 67\n"
        "⏰ 10:00 – 23:00\n✈️ @shoxsomsa_support"
    )

@dp.message(Command("orders"))
async def admin_orders(msg: Message):
    if msg.from_user.id != ADMIN_ID:
        return
    if not active_orders:
        await msg.answer("Hozircha buyurtma yo'q.")
        return
    labels = {"new":"Yangi","accept":"Tayyorlanmoqda","onway":"Yo'lda","done":"Yetkazildi"}
    lines  = [f"• <b>#{oid}</b> — {o['client_name']} — {fmt(o['total'])} — {labels.get(o['status'],'—')}"
              for oid, o in active_orders.items()]
    await msg.answer("📊 <b>Buyurtmalar:</b>\n\n" + "\n".join(lines))

async def main():
    logging.info("🥟 SHOXSOMSA bot ishga tushdi!")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

if __name__ == "__main__":
    asyncio.run(main())
