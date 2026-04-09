from aiogram.fsm.state import State, StatesGroup


class AdminBroadcast(StatesGroup):
    waiting_for_message = State()


class AdminEditText(StatesGroup):
    waiting_for_text = State()


class AdminEditFreePrompts(StatesGroup):
    waiting_for_content = State()
