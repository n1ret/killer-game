import random
from os import getenv

from aiogram import F, Router
from aiogram.exceptions import TelegramForbiddenError
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.utils.chat_action import ChatActionMiddleware
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.utils.text_decorations import HtmlDecoration

from callback_models import ConfirmCallback, KillCallback
from utils import conn_db

router = Router()
router.message.middleware(ChatActionMiddleware())

html = HtmlDecoration()


@router.message(Command("start"))
async def start(message: Message):
    if message.chat.type != "private":
        await message.answer("⚠️ Пиши мне в <b>личные</b> сообщения")
        return

    with conn_db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (id) VALUES (?)",
            (message.from_user.id,)
        )
        conn.commit()

    await message.answer(
        "<i>Бот \"киллер\"</i>\n"
        "Напиши свое ФИО"
    )


@router.message(Command("admin"))
async def admin(message: Message):
    if str(message.from_user.id) != getenv("ADMIN"):
        return
    
    args = message.text.split()
    if len(args) != 3 or args[1] not in {"add", "remove"}:
        await message.answer(
            "Аргументы комманды:\n"
            f"{html.quote('<add|remove>')} <user_id>"
        )
        return
    _, operation, target_id = args

    with conn_db() as conn:
        cur = conn.cursor()
        target_user = cur.execute(
            "SELECT is_admin FROM users WHERE id = ?",
            (target_id,)
        ).fetchone()
    
        if target_user is None:
            await message.answer(
                "Пользователь с таким <b>ID не найден</b> в базе"
            )
            return
        is_target_user_admin, = target_user

        if operation == "add" and not is_target_user_admin:
            conn.execute(
                "UPDATE users SET is_admin = true WHERE id = ?",
                (target_id,)
            )
        elif operation == "remove" and is_target_user_admin:
            conn.execute(
                "UPDATE users SET is_admin = false WHERE id = ?",
                (target_id,)
            )
        else:
            await message.answer("Значение не изменилось")
            return

        conn.commit()
    await message.answer("Пользователь успешно изменён")


@router.message(Command("disclaimer"))
async def disclaimer(message: Message):
    await message.answer(
        "<b>Дисклеймер</b>\n\n"
        "Бот никак не связан с реальным миром.\n"
        "Название было выдвинуто заказчиком.\n"
        "Автор кода бота не несёт ответственности за действия участников"
    )


@router.message(Command("cancel"))
async def cancel(message: Message):
    with conn_db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (id) VALUES (?)",
            (message.from_user.id,)
        )

        cur = conn.cursor()
        target, = cur.execute("SELECT target FROM users WHERE id = ?",
                              (message.from_user.id,)).fetchone()
        if target is not None:
            rpl = InlineKeyboardBuilder()
            rpl.button(text="❌ Выйти", callback_data=ConfirmCallback().pack())
            rpl.adjust(1)

            await message.answer(
                "❌ Игра уже идёт, вы уверены что хотите <b>отменить участие</b>?",
                reply_markup=rpl.as_markup()
            )
            return
        conn.execute(
            "UPDATE users SET name = null WHERE id = ?",
            (message.from_user.id,)
        )
        conn.commit()

    await message.answer(
        "😢 Ты больше <b>не участвуешь</b> в игре"
    )


@router.message(Command("menu", "stats", "status"))
async def killer_menu(message: Message):
    with conn_db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (id) VALUES (?)",
            (message.from_user.id,)
        )
        conn.commit()

        cur = conn.cursor()
        killer_name, target_name = cur.execute(
            "SELECT killers.name, targets.name FROM users as killers "
            "LEFT JOIN users as targets "
            "ON killers.target = targets.id "
            "WHERE killers.id = ?",
            (message.from_user.id,)
        ).fetchone()

        players_count = cur.execute(
            "SELECT COUNT(*) FROM users WHERE name is not null"
        ).fetchone()[0]

    rpl = InlineKeyboardBuilder()
    if killer_name is None:
        text = "Ты <b>не участвуешь</b>\nНапиши ФИО для принятия участия в игре"
    else:
        text = (
            f"Ты <b>участвуешь</b>. Всего игроков зарегистрировано: <i>{players_count}</i>\n"
            f"👤 <b>Твоё имя</b>: {killer_name}\n"
            "🎯 <b>Цель</b>: " +
            (f"<tg-spoiler>{target_name}</tg-spoiler>"
             if target_name is not None else
             "Не выбрана")
        )
        if target_name is not None:
            rpl.button(text="🔪 Цель убита", callback_data=KillCallback().pack())
    rpl.adjust(1)

    await message.answer(
        text,
        reply_markup=rpl.as_markup()
    )


@router.message(Command("clear_lb"))
async def clear_leaderboard(message: Message):
    with conn_db() as conn:
        cur = conn.cursor()
        if cur.execute("SELECT 1 FROM users WHERE is_admin = true AND id = ?",
                       (message.from_user.id,)).fetchone() is None:
            await message.answer(
                "Доступ запрещён"
            )
            return

    rpl = InlineKeyboardBuilder()
    rpl.button(text="🔴 Подтверждаю", callback_data="clear_lb")
    rpl.adjust(1)

    await message.answer(
        "⚠️ Вы действительно хотите отчистить игру?",
        reply_markup=rpl.as_markup()
    )


@router.message(Command("distribute"))
async def distribute(message: Message):
    with conn_db() as conn:
        cur = conn.cursor()
        if cur.execute("SELECT 1 FROM users WHERE is_admin = true AND id = ?",
                       (message.from_user.id,)).fetchone() is None:
            await message.answer(
                "Доступ запрещён"
            )
            return

        users = {
            tgid: name
            for tgid, name in cur.execute(
                "SELECT id, name FROM users WHERE name is not null AND target is null"
            ).fetchall()
        }

    if len(users) <= 1:
        await message.answer(
            "😢 Слишком <b>мало игроков</b>"
        )
        return

    for_disribution = list(users.keys())
    random.shuffle(for_disribution)
    targets = {}
    for i in range(len(for_disribution)):
        targets[for_disribution[i]] = for_disribution[i+1 if i+1 < len(for_disribution) else 0]

    with conn_db() as conn:
        conn.executemany(
            "UPDATE users SET target = ? WHERE id = ?",
            map(lambda v: tuple(reversed(v)), targets.items())
        )
        conn.commit()

    for killer, target in targets.items():
        try:
            await message.bot.send_message(
                killer,
                "🎯 Вам назначена <b>цель</b>:\n"
                f"<i>{users[target]}</i>"
            )
        except TelegramForbiddenError:
            pass

    await message.answer("✅ Цели распределены")


@router.message(Command("leaderboard"))
async def leaderboard(message: Message):
    text = "🗒️ Таблица <b>лидеров</b>:\n<i>Статус Имя: Киллов</i>\n\n"
    lb = ""
    with conn_db() as conn:
        cur = conn.cursor()
        for name, kills, target_id in cur.execute(
            "SELECT name, kills, target FROM users WHERE name is not null ORDER BY kills DESC"
        ).fetchall():
            lb += ('🟢' if target_id is not None else '🔴')+ f"{name}: {kills}\n"
    text += lb or "<b>Пусто</b>"
    await message.answer(text)


@router.message(F.text)
async def text_message(message: Message):
    with conn_db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (id) VALUES (?)",
            (message.from_user.id,)
        )
        conn.execute(
            "UPDATE users SET name = ? WHERE id = ?",
            (message.text, message.from_user.id)
        )
        conn.commit()

    await message.answer(
        "🎉 Теперь ты <b>участвуешь</b> в игре\n"
        "✏️ Твоим именем выбрано:\n"
        f"{message.text}\n\n"
        "Для отмены участия отправь <code>/cancel</code>"
    )
