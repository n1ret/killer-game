from aiogram.filters.callback_data import CallbackData


class KillCallback(CallbackData, prefix="kill"): pass


class ConfirmCallback(CallbackData, prefix="confirm"): pass


class DenyCallback(CallbackData, prefix="deny"): pass


class ClearLeaderBoard(CallbackData, prefix="clear_lb"): pass
