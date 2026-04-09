from aiogram import Router

from app.handlers.start import router as start_router
from app.handlers.free_prompts import router as free_prompts_router
from app.handlers.payment import router as payment_router
from app.handlers.admin import router as admin_router

root_router = Router()
root_router.include_router(admin_router)
root_router.include_router(start_router)
root_router.include_router(free_prompts_router)
root_router.include_router(payment_router)
