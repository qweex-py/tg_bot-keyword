import asyncio
import json
import re
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.types import Message
from aiogram.filters import Command, Filter
import pymorphy3

BOT_TOKEN = "ТОКЕК"
SUBSCRIBER_FILE = Path("subscriber.txt")
CHATS_FILE = Path("chats.json")
#README Бот для поиска по ключевым словам, введите свой токен и ключевые слова.
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
morph = pymorphy3.MorphAnalyzer()

TARGET_WORDS = {"КЛЮЧЕВОЕ СЛОВО"}



def save_subscriber(chat_id: int):
    SUBSCRIBER_FILE.write_text(str(chat_id), encoding="utf-8")


def get_subscriber() -> int | None:
    if not SUBSCRIBER_FILE.exists():
        return None
    try:
        return int(SUBSCRIBER_FILE.read_text(encoding="utf-8").strip())
    except ValueError:
        return None



def load_chats() -> dict:
    """Возвращает {chat_id: title}"""
    if not CHATS_FILE.exists():
        return {}
    try:
        return json.loads(CHATS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_chats(chats: dict):
    CHATS_FILE.write_text(
        json.dumps(chats, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def add_chat(chat_id: int, title: str):
    chats = load_chats()
    chats[str(chat_id)] = title
    save_chats(chats)


def remove_chat(chat_id: int):
    chats = load_chats()
    chats.pop(str(chat_id), None)
    save_chats(chats)


def is_tracked(chat_id: int) -> bool:
    return str(chat_id) in load_chats()



@dp.message(Command("start"))
async def cmd_start(message: Message):
    if message.chat.type == "private":
        save_subscriber(message.chat.id)
        await message.answer(
            "Готово! Теперь сюда будут приходить уведомления "
            "по ключевым словам из отслеживаемых чатов.\n\n"
            "Команды:\n"
            "/chats — список отслеживаемых чатов\n"
            "/stop — отписаться"
        )
    else:
        # если /start прилетел в группу — просто добавим её в отслеживаемые
        add_chat(message.chat.id, message.chat.title or "Без названия")
        await message.answer("👀 Чат добавлен в отслеживаемые.")



@dp.my_chat_member()
async def on_bot_added(update):
    # update — ChatMemberUpdated
    new_status = update.new_chat_member.status
    chat = update.chat
    if new_status in ("member", "administrator"):
        if chat.type in ("group", "supergroup"):
            add_chat(chat.id, chat.title or "Без названия")
            print(f"➕ Добавлен чат: {chat.title} ({chat.id})")
    elif new_status in ("left", "kicked"):
        remove_chat(chat.id)
        print(f"➖ Удалён чат: {chat.title} ({chat.id})")



@dp.message(Command("chats"))
async def cmd_chats(message: Message):
    chats = load_chats()
    if not chats:
        await message.answer("📭 Пока нет отслеживаемых чатов.")
        return

    lines = ["<b>Отслеживаемые чаты:</b>\n"]
    for cid, title in chats.items():
        lines.append(f"• <b>{title}</b>\n  <code>{cid}</code>")
    await message.answer("\n".join(lines), parse_mode="HTML")


# /remove_chat <id>
@dp.message(Command("remove_chat"))
async def cmd_remove_chat(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: <code>/remove_chat -1001234567890</code>", parse_mode="HTML")
        return
    try:
        cid = int(args[1].strip())
    except ValueError:
        await message.answer("ID должен быть числом.")
        return

    if not is_tracked(cid):
        await message.answer(" Такого чата нет в списке.")
        return

    remove_chat(cid)
    await message.answer(f"🗑 Чат <code>{cid}</code> убран из отслеживаемых.", parse_mode="HTML")



@dp.message(Command("stop"))
async def cmd_stop(message: Message):
    if get_subscriber() == message.chat.id:
        SUBSCRIBER_FILE.unlink(missing_ok=True)
        await message.answer("Уведомления отключены.")
    else:
        await message.answer("Ты и так не подписан.")



class KeywordFilter(Filter):
    async def __call__(self, message: Message) -> bool:
        if not message.text:
            return False
        if message.from_user and message.from_user.is_bot:
            return False
        if not is_tracked(message.chat.id):
            return False
        words = re.findall(r"\w+", message.text.lower(), flags=re.UNICODE)
        return any(morph.parse(w)[0].normal_form in TARGET_WORDS for w in words)



@dp.message(KeywordFilter())
async def alert(message: Message):
    target = get_subscriber()
    if target is None:
        print("Нет подписчика — кто-то должен написать /start в личке")
        return

    user = message.from_user
    chat = message.chat

    link = None
    if str(chat.id).startswith("-100"):
        link = f"https://t.me/c/{str(chat.id)[4:]}/{message.message_id}"

    header = (
        f"<b>Найдено ключевое слово</b>\n"
        f"{chat.title or chat.full_name}\n"
        f"{user.full_name}"
    )
    if user.username:
        header += f" (@{user.username})"
    if link:
        header += f"\n🔗 <a href='{link}'>Перейти к сообщению</a>"

    print(f"Слово найдено в «{chat.title}» от {user.full_name} → отправляю {target}")

    try:
        await bot.send_message(
            chat_id=target,
            text=header,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except Exception as e:
        print(f"Не удалось отправить шапку: {e}")

    try:
        await bot.forward_message(
            chat_id=target,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
        )
    except Exception as e:
        print(f"Не удалось переслать, пробую copy_message: {e}")
        try:
            await bot.copy_message(
                chat_id=target,
                from_chat_id=message.chat.id,
                message_id=message.message_id,
            )
        except Exception as e2:
            print(f"copy_message тоже не сработал: {e2}")


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())