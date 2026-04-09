import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

BOT_TOKEN: str = os.environ["BOT_TOKEN"]
YOOKASSA_SHOP_ID: str = os.environ["YOOKASSA_SHOP_ID"]
YOOKASSA_SECRET_KEY: str = os.environ["YOOKASSA_SECRET_KEY"]

PUBLIC_BASE_URL: str = os.environ["PUBLIC_BASE_URL"]
TELEGRAM_WEBHOOK_PATH: str = "/telegram/webhook"
YOOKASSA_WEBHOOK_PATH: str = "/yookassa/webhook"

TELEGRAM_WEBHOOK_URL: str = PUBLIC_BASE_URL.rstrip("/") + TELEGRAM_WEBHOOK_PATH
YOOKASSA_WEBHOOK_URL: str = PUBLIC_BASE_URL.rstrip("/") + YOOKASSA_WEBHOOK_PATH

CHANNEL_ID: int = int(os.environ["CHANNEL_ID"])
CHANNEL_INVITE: str = os.environ.get("CHANNEL_INVITE", "")

CURRENCY: str = os.environ.get("CURRENCY", "RUB")
ITEM_NAME: str = "Доступ в сообщество"

PLANS: dict[str, dict] = {
    "1m":  {"days": 30,  "amount": os.environ.get("PRICE_1M",  "399.00"),  "label": "1 месяц"},
    "3m":  {"days": 90,  "amount": os.environ.get("PRICE_3M",  "999.00"),  "label": "3 месяца"},
    "6m":  {"days": 180, "amount": os.environ.get("PRICE_6M",  "1799.00"), "label": "6 месяцев"},
    "12m": {"days": 365, "amount": os.environ.get("PRICE_12M", "2999.00"), "label": "12 месяцев"},
}

DATABASE_URL: str = os.environ["DATABASE_URL"]

ADMIN_IDS: list[int] = [
    int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip()
]

PORT: int = int(os.environ.get("PORT", "8000"))

BASE_DIR: Path = Path(__file__).resolve().parent.parent
DATA_DIR: Path = BASE_DIR / "data"
