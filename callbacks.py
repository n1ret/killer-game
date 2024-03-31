from aiogram import Router
from aiogram.exceptions import TelegramForbiddenError
from aiogram.types import CallbackQuery
from aiogram.utils.callback_answer import CallbackAnswerMiddleware
from aiogram.utils.keyboard import InlineKeyboardBuilder

from callback_models import (
    ClearLeaderBoard,
    ConfirmCallback,
    DenyCallback,
    KillCallback,
)
from utils import conn_db

router = Router()
router.callback_query.middleware(CallbackAnswerMiddleware())



@router.callback_query(KillCallback.filter())
async def kill(call: CallbackQuery):
    with conn_db() as conn:
        cur = conn.cursor()
        row = cur.execute(
            "SELECT targets.id, killers.is_kill_requested FROM users as killers "
            "LEFT JOIN users as targets "
            "ON killers.target = targets.id "
            "WHERE killers.id = ?",
            (call.from_user.id,)
        ).fetchone()
        if row is None:
            return
        target_id, is_kill_requested = row
        if target_id is None:
            await call.answer("Сообщение устарело", True)
            return
    
        if not is_kill_requested:
            conn.execute("UPDATE users SET is_kill_requested = true WHERE id = ?",
                         (call.from_user.id,))
            
            rpl = InlineKeyboardBuilder()
            rpl.button(text="Да", callback_data=ConfirmCallback().pack())
            rpl.button(text="Нет", callback_data=DenyCallback().pack())
            rpl.adjust(2)

            await call.bot.send_message(
                target_id,
                "🔪 Тебя <b>убили</b>?",
                reply_markup=rpl
            )

            conn.commit()

    await call.message.edit_text(
        "🕑 Ожидайте подтверждения",
        reply_markup=InlineKeyboardBuilder().as_markup()
    )


@router.callback_query(ConfirmCallback.filter())
async def confirm(call: CallbackQuery):
    with conn_db() as conn:
        cur = conn.cursor()
        row = cur.execute(
            "SELECT killers.id, killers.name, targets.target FROM users as targets "
            "JOIN users as killers "
            "ON targets.id = killers.target "
            "WHERE targets.id = ?",
            (call.from_user.id,)
        ).fetchone()
        if row is None:
            await call.answer("Сообщение устарело", True)
            return

        killer_id, killer_name, target_target = row
        new_target_name = cur.execute("SELECT name FROM users WHERE id = ?",
                                      (target_target,)).fetchone()

        conn.execute("UPDATE users SET "
                     "is_kill_requested = false, target = ?, kills = kills+1 "
                     "WHERE id = ?",
                     (target_target, killer_id))
        conn.execute("UPDATE users SET target = null WHERE id = ?",
                     (call.from_user.id,))

        if target_target == killer_id:
            conn.execute("UPDATE users SET "
                         "target = 0 "
                         "WHERE id = ?",
                         (killer_id,))

        conn.commit()
    
    if target_target == killer_id:
        for tgid, in cur.execute("SELECT id FROM users").fetchall():
            try:
                await call.bot.send_message(
                    tgid,
                    f"🎉 <i>Игра окончена</i>\nПобедитель: <b>{killer_name}</b>"
                )
            except TelegramForbiddenError:
                pass
        return

    await call.bot.send_message(
        killer_id,
        "✅ Подтверждено\n"
        f"🎯 Твоя <b>следующая цель</b>: {new_target_name}"
    )
    await call.message.edit_text(
        "🎯 Ваша <b>цель передана</b>\n"
        f"{killer_name}",
        reply_markup=InlineKeyboardBuilder().as_markup()
    )


@router.callback_query(DenyCallback.filter())
async def deny(call: CallbackQuery):
    with conn_db() as conn:
        cur = conn.cursor()
        row = cur.execute(
            "SELECT killers.id FROM users as targets "
            "JOIN users as killers "
            "ON targets.id = killers.target "
            "WHERE targets.id = ?",
            (call.from_user.id,)
        ).fetchone()
        if row is None:
            await call.answer("Сообщение устарело", True)
            return
        killer_id, = row

        conn.execute("UPDATE users SET "
                     "is_kill_requested = false "
                     "WHERE id = ?",
                     (killer_id,))
        conn.commit()

    await call.bot.send_message(
        killer_id,
        "❌ <b>Не подтверждено</b>"
    )
    await call.message.edit_text(
        "✅ <b>Отклонено</b>",
        reply_markup=InlineKeyboardBuilder().as_markup()
    )


@router.callback_query(ClearLeaderBoard.filter())
async def clear_lb_accept(call: CallbackQuery):
    with conn_db() as conn:
        cur = conn.cursor()
        if cur.execute("SELECT 1 FROM users WHERE is_admin = true AND id = ?",
                       (call.from_user.id,)).fetchone() is None:
            await call.answer(
                "Доступ запрещён",
                True
            )
            return

        conn.execute("UPDATE users SET kills = 0, target = null")
        conn.commit()

    await call.message.edit_text(
        "✅ Таблица очищена",
        reply_markup=InlineKeyboardBuilder().as_markup()
    )
