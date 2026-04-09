from aiogram.fsm.state import State, StatesGroup


class Purchase(StatesGroup):
    waiting_for_email = State()
    choosing_plan = State()


class AdminBroadcast(StatesGroup):
    waiting_for_message = State()


class AdminEditText(StatesGroup):
    waiting_for_text = State()
