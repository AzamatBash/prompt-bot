from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import asyncpg

from app.config import DATABASE_URL

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


async def init_db() -> None:
    global _pool
    _pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)

    async with _pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id     BIGINT PRIMARY KEY,
                username    TEXT,
                email       TEXT,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id           SERIAL PRIMARY KEY,
                user_id      BIGINT NOT NULL REFERENCES users(user_id),
                yookassa_id  TEXT UNIQUE NOT NULL,
                amount       TEXT NOT NULL,
                currency     TEXT NOT NULL DEFAULT 'RUB',
                plan_days    INTEGER NOT NULL DEFAULT 30,
                status       TEXT NOT NULL DEFAULT 'pending',
                paid_at      TIMESTAMPTZ,
                created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                id           SERIAL PRIMARY KEY,
                user_id      BIGINT NOT NULL REFERENCES users(user_id),
                payment_id   INTEGER REFERENCES payments(id),
                starts_at    TIMESTAMPTZ NOT NULL,
                expires_at   TIMESTAMPTZ NOT NULL,
                is_active    BOOLEAN NOT NULL DEFAULT TRUE,
                reminded_3d  BOOLEAN NOT NULL DEFAULT FALSE,
                reminded_1d  BOOLEAN NOT NULL DEFAULT FALSE,
                created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS texts (
                key    TEXT PRIMARY KEY,
                value  TEXT NOT NULL
            )
        """)
        # safe migration for existing databases
        await conn.execute("""
            ALTER TABLE payments
            ADD COLUMN IF NOT EXISTS plan_days INTEGER NOT NULL DEFAULT 30
        """)
        for col in ("reminded_3d", "reminded_1d"):
            await conn.execute(f"""
                ALTER TABLE subscriptions
                ADD COLUMN IF NOT EXISTS {col} BOOLEAN NOT NULL DEFAULT FALSE
            """)

    logger.info("Database tables ready")


async def close_db() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


def _p() -> asyncpg.Pool:
    assert _pool is not None, "Database not initialised — call init_db() first"
    return _pool


# ── users ──────────────────────────────────────────────

async def upsert_user(user_id: int, username: str | None, email: str | None) -> None:
    await _p().execute(
        """
        INSERT INTO users (user_id, username, email)
        VALUES ($1, $2, $3)
        ON CONFLICT (user_id) DO UPDATE SET
            username = COALESCE(EXCLUDED.username, users.username),
            email    = COALESCE(EXCLUDED.email,    users.email)
        """,
        user_id, username, email,
    )


async def get_users_count() -> int:
    return await _p().fetchval("SELECT COUNT(*) FROM users")


async def get_users_page(offset: int, limit: int) -> list[asyncpg.Record]:
    return await _p().fetch(
        """
        SELECT
            u.user_id, u.username, u.email,
            EXISTS(
                SELECT 1 FROM subscriptions
                WHERE user_id = u.user_id AND is_active = TRUE
            ) AS has_active_sub
        FROM users u
        ORDER BY u.created_at DESC
        OFFSET $1 LIMIT $2
        """,
        offset, limit,
    )


async def get_user_info(user_id: int) -> asyncpg.Record | None:
    return await _p().fetchrow(
        """
        SELECT
            u.user_id, u.username, u.email, u.created_at,
            (
                SELECT expires_at FROM subscriptions
                WHERE user_id = u.user_id AND is_active = TRUE
                ORDER BY expires_at DESC LIMIT 1
            ) AS sub_expires,
            (SELECT COUNT(*) FROM payments WHERE user_id = u.user_id) AS payment_count
        FROM users u
        WHERE u.user_id = $1
        """,
        user_id,
    )


# ── payments ───────────────────────────────────────────

async def create_payment_record(
    user_id: int,
    yookassa_id: str,
    amount: str,
    currency: str,
    plan_days: int,
) -> int:
    row = await _p().fetchrow(
        """
        INSERT INTO payments (user_id, yookassa_id, amount, currency, plan_days, status)
        VALUES ($1, $2, $3, $4, $5, 'pending')
        RETURNING id
        """,
        user_id, yookassa_id, amount, currency, plan_days,
    )
    return row["id"]


async def mark_payment_succeeded(yookassa_id: str) -> dict | None:
    row = await _p().fetchrow(
        """
        UPDATE payments
        SET status = 'succeeded', paid_at = now()
        WHERE yookassa_id = $1 AND status = 'pending'
        RETURNING id, user_id, plan_days
        """,
        yookassa_id,
    )
    if row is None:
        return None
    return {"id": row["id"], "user_id": row["user_id"], "plan_days": row["plan_days"]}


async def get_payments_count() -> int:
    return await _p().fetchval("SELECT COUNT(*) FROM payments")


async def get_payments_page(offset: int, limit: int) -> list[asyncpg.Record]:
    return await _p().fetch(
        """
        SELECT
            p.id, p.amount, p.currency, p.status, p.paid_at, p.created_at,
            u.user_id, u.username
        FROM payments p
        JOIN users u ON u.user_id = p.user_id
        ORDER BY p.created_at DESC
        OFFSET $1 LIMIT $2
        """,
        offset, limit,
    )


async def get_user_payments_count(user_id: int) -> int:
    return await _p().fetchval(
        "SELECT COUNT(*) FROM payments WHERE user_id = $1", user_id,
    )


async def get_user_payments_page(
    user_id: int, offset: int, limit: int,
) -> list[asyncpg.Record]:
    return await _p().fetch(
        """
        SELECT id, amount, currency, status, paid_at, created_at
        FROM payments
        WHERE user_id = $1
        ORDER BY created_at DESC
        OFFSET $2 LIMIT $3
        """,
        user_id, offset, limit,
    )


# ── subscriptions ──────────────────────────────────────

async def add_subscription(user_id: int, payment_db_id: int, days: int) -> datetime:
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=days)
    await _p().execute(
        """
        INSERT INTO subscriptions (user_id, payment_id, starts_at, expires_at, is_active)
        VALUES ($1, $2, $3, $4, TRUE)
        """,
        user_id, payment_db_id, now, expires,
    )
    return expires


async def get_expired_subscriptions() -> list[tuple[int, int]]:
    """Atomically find and deactivate expired subscriptions. Returns (user_id, user_id)."""
    now = datetime.now(timezone.utc)
    rows = await _p().fetch(
        """
        UPDATE subscriptions
        SET is_active = FALSE
        WHERE is_active = TRUE AND expires_at <= $1
        RETURNING user_id
        """,
        now,
    )
    return [(r["user_id"], r["user_id"]) for r in rows]


async def deactivate_subscriptions(user_id: int) -> None:
    await _p().execute(
        "UPDATE subscriptions SET is_active = FALSE WHERE user_id = $1 AND is_active = TRUE",
        user_id,
    )


# ── reminders ──────────────────────────────────────────

async def get_subscriptions_for_reminder_3d() -> list[int]:
    """Find active subs expiring within 3 days, mark reminded, return user_ids."""
    now = datetime.now(timezone.utc)
    rows = await _p().fetch(
        """
        UPDATE subscriptions
        SET reminded_3d = TRUE
        WHERE is_active = TRUE
          AND reminded_3d = FALSE
          AND expires_at <= $1
          AND expires_at > $2
        RETURNING user_id
        """,
        now + timedelta(days=3), now,
    )
    return [r["user_id"] for r in rows]


async def get_subscriptions_for_reminder_1d() -> list[int]:
    """Find active subs expiring within 1 day, mark reminded, return user_ids."""
    now = datetime.now(timezone.utc)
    rows = await _p().fetch(
        """
        UPDATE subscriptions
        SET reminded_1d = TRUE
        WHERE is_active = TRUE
          AND reminded_1d = FALSE
          AND expires_at <= $1
          AND expires_at > $2
        RETURNING user_id
        """,
        now + timedelta(days=1), now,
    )
    return [r["user_id"] for r in rows]


# ── broadcast helpers ──────────────────────────────────

async def get_all_user_ids() -> list[int]:
    rows = await _p().fetch("SELECT user_id FROM users ORDER BY user_id")
    return [r["user_id"] for r in rows]


async def get_active_subscriber_ids() -> list[int]:
    rows = await _p().fetch(
        "SELECT DISTINCT user_id FROM subscriptions WHERE is_active = TRUE",
    )
    return [r["user_id"] for r in rows]


async def get_expired_subscriber_ids() -> list[int]:
    """Users who had subscriptions but none currently active."""
    rows = await _p().fetch(
        """
        SELECT DISTINCT s.user_id
        FROM subscriptions s
        WHERE NOT EXISTS (
            SELECT 1 FROM subscriptions s2
            WHERE s2.user_id = s.user_id AND s2.is_active = TRUE
        )
        """,
    )
    return [r["user_id"] for r in rows]


async def get_active_subscribers_count() -> int:
    return await _p().fetchval(
        "SELECT COUNT(DISTINCT user_id) FROM subscriptions WHERE is_active = TRUE",
    )


async def get_expired_subscribers_count() -> int:
    return await _p().fetchval(
        """
        SELECT COUNT(DISTINCT s.user_id)
        FROM subscriptions s
        WHERE NOT EXISTS (
            SELECT 1 FROM subscriptions s2
            WHERE s2.user_id = s.user_id AND s2.is_active = TRUE
        )
        """,
    )


# ── texts ──────────────────────────────────────────────

async def get_all_texts() -> dict[str, str]:
    rows = await _p().fetch("SELECT key, value FROM texts")
    return {r["key"]: r["value"] for r in rows}


async def upsert_text(key: str, value: str) -> None:
    await _p().execute(
        """
        INSERT INTO texts (key, value) VALUES ($1, $2)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """,
        key, value,
    )


async def delete_text(key: str) -> None:
    await _p().execute("DELETE FROM texts WHERE key = $1", key)


# ── free prompts content ───────────────────────────────

async def get_free_prompts() -> dict | None:
    rows = await _p().fetch("SELECT key, value FROM texts WHERE key LIKE 'fp_%'")
    data = {r["key"]: r["value"] for r in rows}
    if "fp_type" not in data:
        return None
    return {
        "type": data["fp_type"],
        "file_id": data.get("fp_file_id", ""),
        "caption": data.get("fp_caption", ""),
    }


async def set_free_prompts(content_type: str, file_id: str, caption: str) -> None:
    for key, value in [("fp_type", content_type), ("fp_file_id", file_id), ("fp_caption", caption)]:
        await upsert_text(key, value)


async def clear_free_prompts() -> None:
    await _p().execute("DELETE FROM texts WHERE key LIKE 'fp_%'")
