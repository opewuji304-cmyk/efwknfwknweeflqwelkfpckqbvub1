from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field


@dataclass(frozen=True)
class Settings:
    app_env: str = "development"
    database_url: str = "sqlite:///./aether-sandbox.db"
    telegram_bot_token: str = ""
    telegram_auth_max_age_seconds: int = 300
    deposit_webhook_secret: str = ""
    acquirer_webhook_secret: str = ""
    dev_credit_token: str = ""
    dev_credit_enabled: bool = False
    dev_acquirer_enabled: bool = False
    data_region: str = ""
    regulatory_approved: bool = False
    custody_provider: str = ""
    chain_provider: str = ""
    screening_provider: str = ""
    kyc_aml_provider: str = ""
    onramp_provider: str = ""
    acquirer_provider: str = ""
    payout_provider: str = ""
    kms_key_reference: str = ""

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            app_env=os.getenv("APP_ENV", "development"),
            database_url=os.getenv("DATABASE_URL", "sqlite:///./aether-sandbox.db"),
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
            telegram_auth_max_age_seconds=int(os.getenv("TELEGRAM_AUTH_MAX_AGE_SECONDS", "300")),
            deposit_webhook_secret=os.getenv("DEPOSIT_WEBHOOK_SECRET", ""),
            acquirer_webhook_secret=os.getenv("ACQUIRER_WEBHOOK_SECRET", ""),
            dev_credit_token=os.getenv("DEV_CREDIT_TOKEN", ""),
            dev_credit_enabled=os.getenv("DEV_CREDIT_ENABLED", "0") == "1",
            dev_acquirer_enabled=os.getenv("DEV_ACQUIRER_ENABLED", "0") == "1",
            data_region=os.getenv("DATA_REGION", ""),
            regulatory_approved=os.getenv("REGULATORY_APPROVED", "0") == "1",
            custody_provider=os.getenv("CUSTODY_PROVIDER", ""),
            chain_provider=os.getenv("CHAIN_PROVIDER", ""),
            screening_provider=os.getenv("SCREENING_PROVIDER", ""),
            kyc_aml_provider=os.getenv("KYC_AML_PROVIDER", ""),
            onramp_provider=os.getenv("ONRAMP_PROVIDER", ""),
            acquirer_provider=os.getenv("ACQUIRER_PROVIDER", ""),
            payout_provider=os.getenv("PAYOUT_PROVIDER", ""),
            kms_key_reference=os.getenv("KMS_KEY_REFERENCE", ""),
        )

    def production_gaps(self) -> list[str]:
        required = {
            "TELEGRAM_BOT_TOKEN": self.telegram_bot_token,
            "DATA_REGION=ru": self.data_region.lower() == "ru",
            "REGULATORY_APPROVED=1": self.regulatory_approved,
            "CUSTODY_PROVIDER": self.custody_provider,
            "CHAIN_PROVIDER": self.chain_provider,
            "SCREENING_PROVIDER": self.screening_provider,
            "KYC_AML_PROVIDER": self.kyc_aml_provider,
            "ONRAMP_PROVIDER": self.onramp_provider,
            "ACQUIRER_PROVIDER": self.acquirer_provider,
            "PAYOUT_PROVIDER": self.payout_provider,
            "KMS_KEY_REFERENCE": self.kms_key_reference,
            "DEPOSIT_WEBHOOK_SECRET": self.deposit_webhook_secret,
            "ACQUIRER_WEBHOOK_SECRET": self.acquirer_webhook_secret,
        }
        gaps = [name for name, value in required.items() if not value]
        if not self.database_url.startswith(("postgresql://", "postgres://")):
            gaps.append("PostgreSQL DATABASE_URL")
        # Provider names in environment are configuration labels only. The actual custody,
        # chain-indexing, screening, KYC and payout adapters have not been security-reviewed
        # or integrated in this repository, so production must remain impossible to start.
        gaps.append("audited production provider adapters (not implemented)")
        return gaps


def connect(settings: Settings):
    if settings.database_url.startswith(("postgresql://", "postgres://")):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("Install psycopg[binary] to use PostgreSQL") from exc
        return psycopg.connect(settings.database_url, row_factory=dict_row)
    if settings.app_env == "production":
        raise RuntimeError("SQLite is sandbox-only; production requires PostgreSQL")
    if settings.database_url.startswith("sqlite:///"):
        db_path = settings.database_url.removeprefix("sqlite:///")
    else:
        raise RuntimeError("DATABASE_URL must be PostgreSQL or sandbox SQLite")
    path = Path(db_path)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10, isolation_level="DEFERRED", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def execute(conn, sql: str, params: tuple = ()):
    if isinstance(conn, sqlite3.Connection):
        return conn.execute(sql, params)
    return conn.execute(sql.replace("?", "%s"), params)


def init_db(settings: Settings) -> None:
    conn = connect(settings)
    try:
        if isinstance(conn, sqlite3.Connection):
            schema = """
            CREATE TABLE IF NOT EXISTS users (
              telegram_id TEXT PRIMARY KEY,
              created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ledger_transactions (
              id TEXT PRIMARY KEY,
              kind TEXT NOT NULL,
              idempotency_key TEXT NOT NULL UNIQUE,
              reference TEXT NOT NULL,
              created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ledger_postings (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              transaction_id TEXT NOT NULL REFERENCES ledger_transactions(id),
              account TEXT NOT NULL,
              asset TEXT NOT NULL,
              amount_minor INTEGER NOT NULL CHECK(amount_minor != 0)
            );
            CREATE INDEX IF NOT EXISTS ledger_postings_account_asset ON ledger_postings(account, asset);
            CREATE TABLE IF NOT EXISTS audit_events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              event TEXT NOT NULL,
              subject_ref TEXT NOT NULL,
              reference TEXT NOT NULL,
              created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS withdrawal_intents (
              id TEXT PRIMARY KEY,
              user_id TEXT NOT NULL REFERENCES users(telegram_id),
              network TEXT NOT NULL,
              asset TEXT NOT NULL,
              recipient_fingerprint TEXT NOT NULL,
              amount_minor INTEGER NOT NULL,
              fee_minor INTEGER NOT NULL,
              state TEXT NOT NULL,
              created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS purchase_intents (
              id TEXT PRIMARY KEY,
              user_id TEXT NOT NULL REFERENCES users(telegram_id),
              idempotency_key TEXT NOT NULL UNIQUE,
              rub_minor INTEGER NOT NULL,
              state TEXT NOT NULL,
              provider_invoice_id TEXT UNIQUE,
              credited_usdt_minor INTEGER,
              created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS acquirer_events (
              provider_event_id TEXT PRIMARY KEY,
              purchase_id TEXT NOT NULL REFERENCES purchase_intents(id),
              payload_hash TEXT NOT NULL,
              created_at INTEGER NOT NULL
            );
            """
        else:
            schema = """
            CREATE TABLE IF NOT EXISTS users (
              telegram_id TEXT PRIMARY KEY, created_at BIGINT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ledger_transactions (
              id TEXT PRIMARY KEY, kind TEXT NOT NULL,
              idempotency_key TEXT NOT NULL UNIQUE, reference TEXT NOT NULL,
              created_at BIGINT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ledger_postings (
              id BIGSERIAL PRIMARY KEY,
              transaction_id TEXT NOT NULL REFERENCES ledger_transactions(id),
              account TEXT NOT NULL, asset TEXT NOT NULL,
              amount_minor BIGINT NOT NULL CHECK(amount_minor != 0)
            );
            CREATE INDEX IF NOT EXISTS ledger_postings_account_asset ON ledger_postings(account, asset);
            CREATE TABLE IF NOT EXISTS audit_events (
              id BIGSERIAL PRIMARY KEY, event TEXT NOT NULL,
              subject_ref TEXT NOT NULL, reference TEXT NOT NULL, created_at BIGINT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS withdrawal_intents (
              id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(telegram_id),
              network TEXT NOT NULL, asset TEXT NOT NULL, recipient_fingerprint TEXT NOT NULL,
              amount_minor BIGINT NOT NULL, fee_minor BIGINT NOT NULL,
              state TEXT NOT NULL, created_at BIGINT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS purchase_intents (
              id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(telegram_id),
              idempotency_key TEXT NOT NULL UNIQUE, rub_minor BIGINT NOT NULL,
              state TEXT NOT NULL, provider_invoice_id TEXT UNIQUE,
              credited_usdt_minor BIGINT, created_at BIGINT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS acquirer_events (
              provider_event_id TEXT PRIMARY KEY,
              purchase_id TEXT NOT NULL REFERENCES purchase_intents(id),
              payload_hash TEXT NOT NULL, created_at BIGINT NOT NULL
            );
            """
        for statement in schema.split(";"):
            if statement.strip():
                execute(conn, statement)
        conn.commit()
    finally:
        conn.close()


def validate_telegram_init_data(init_data: str, bot_token: str, max_age: int, now: int | None = None) -> dict[str, Any]:
    if not bot_token:
        raise ValueError("Telegram authentication is not configured")
    if not init_data or len(init_data) > 8192:
        raise ValueError("Telegram initData has invalid size")
    pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True)
    fields: dict[str, str] = {}
    for key, value in pairs:
        if key in fields:
            raise ValueError("Duplicate initData field")
        fields[key] = value
    supplied = fields.pop("hash", None)
    if not supplied or not re.fullmatch(r"[0-9a-f]{64}", supplied):
        raise ValueError("Missing or malformed Telegram hash")
    check_string = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, supplied):
        raise ValueError("Invalid Telegram signature")
    try:
        auth_date = int(fields["auth_date"])
        user = json.loads(fields["user"])
        user_id = str(int(user["id"]))
    except (KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Malformed Telegram user or auth_date") from exc
    current = int(time.time()) if now is None else now
    if auth_date > current + 30 or current - auth_date > max_age:
        raise ValueError("Telegram authorization expired")
    return {"id": user_id}


def account_ref(user_id: str) -> str:
    return f"user:{user_id}:USDT"


def add_audit(conn, event: str, user_id: str, reference: str) -> None:
    subject_ref = hashlib.sha256(user_id.encode()).hexdigest()
    execute(conn, "INSERT INTO audit_events(event, subject_ref, reference, created_at) VALUES(?,?,?,?)",
            (event, subject_ref, reference, int(time.time())))


def post_transaction(conn, kind: str, idempotency_key: str, reference: str,
                     postings: list[tuple[str, int]], user_id: str) -> tuple[str, bool]:
    if not idempotency_key or len(idempotency_key) > 128:
        raise ValueError("Invalid idempotency key")
    if len(postings) < 2 or any(not amount for _, amount in postings) or sum(amount for _, amount in postings) != 0:
        raise ValueError("Ledger postings must be non-zero and balance to zero")
    tx_id = secrets.token_hex(16)
    inserted = execute(conn, "INSERT INTO ledger_transactions(id,kind,idempotency_key,reference,created_at) VALUES(?,?,?,?,?) ON CONFLICT(idempotency_key) DO NOTHING",
                       (tx_id, kind, idempotency_key, reference, int(time.time())))
    if inserted.rowcount == 0:
        existing = execute(conn, "SELECT id FROM ledger_transactions WHERE idempotency_key=?", (idempotency_key,)).fetchone()
        return existing["id"], False
    for account, amount in postings:
        execute(conn, "INSERT INTO ledger_postings(transaction_id,account,asset,amount_minor) VALUES(?,?,?,?)",
                (tx_id, account, "USDT", amount))
    add_audit(conn, kind, user_id, reference)
    return tx_id, True


def credit_deposit(settings: Settings, provider_event_id: str, telegram_id: str, amount_minor: int) -> tuple[str, bool]:
    if amount_minor <= 0 or amount_minor > 100_000_000_000:
        raise ValueError("Deposit amount outside configured bounds")
    conn = connect(settings)
    try:
        execute(conn, "INSERT INTO users(telegram_id,created_at) VALUES(?,?) ON CONFLICT(telegram_id) DO NOTHING",
                (telegram_id, int(time.time())))
        result = post_transaction(conn, "deposit", f"deposit:{provider_event_id}", provider_event_id,
                                  [(account_ref(telegram_id), amount_minor), ("platform:deposit-clearing:USDT", -amount_minor)], telegram_id)
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def balance(settings: Settings, telegram_id: str) -> int:
    conn = connect(settings)
    try:
        row = execute(conn, "SELECT COALESCE(SUM(amount_minor),0) AS total FROM ledger_postings WHERE account=? AND asset='USDT'",
                      (account_ref(telegram_id),)).fetchone()
        return int(row["total"])
    finally:
        conn.close()


def create_purchase_intent(settings: Settings, telegram_id: str, rub_minor: int, idempotency_key: str) -> tuple[str, bool]:
    if rub_minor < 10_000 or rub_minor > 100_000_000:
        raise ValueError("Purchase amount must be between 100 and 1,000,000 RUB")
    if not idempotency_key or len(idempotency_key) > 128:
        raise ValueError("Invalid idempotency key")
    conn = connect(settings)
    scoped_key = f"{telegram_id}:{idempotency_key}"
    try:
        execute(conn, "INSERT INTO users(telegram_id,created_at) VALUES(?,?) ON CONFLICT(telegram_id) DO NOTHING",
                (telegram_id, int(time.time())))
        purchase_id = secrets.token_hex(16)
        inserted = execute(conn, "INSERT INTO purchase_intents(id,user_id,idempotency_key,rub_minor,state,provider_invoice_id,created_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(idempotency_key) DO NOTHING",
                           (purchase_id, telegram_id, scoped_key, rub_minor, "awaiting_payment", f"sandbox:{purchase_id}", int(time.time())))
        if inserted.rowcount == 0:
            existing = execute(conn, "SELECT id FROM purchase_intents WHERE idempotency_key=?", (scoped_key,)).fetchone()
            conn.commit()
            return existing["id"], False
        add_audit(conn, "purchase_created_sandbox", telegram_id, purchase_id)
        conn.commit()
        return purchase_id, True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def settle_purchase(settings: Settings, event_id: str, purchase_id: str, provider_invoice_id: str,
                    paid_rub_minor: int, credited_usdt_minor: int) -> tuple[str | None, bool]:
    if credited_usdt_minor <= 0 or credited_usdt_minor > 100_000_000_000:
        raise ValueError("Credited USDT amount outside configured bounds")
    conn = connect(settings)
    payload_hash = hashlib.sha256(f"{purchase_id}|{provider_invoice_id}|{paid_rub_minor}|{credited_usdt_minor}".encode()).hexdigest()
    try:
        old_event = execute(conn, "SELECT purchase_id,payload_hash FROM acquirer_events WHERE provider_event_id=?", (event_id,)).fetchone()
        if old_event:
            if old_event["purchase_id"] != purchase_id or old_event["payload_hash"] != payload_hash:
                raise ValueError("Acquirer event ID was reused with different data")
            conn.commit()
            return None, False
        purchase = execute(conn, "SELECT * FROM purchase_intents WHERE id=?", (purchase_id,)).fetchone()
        if not purchase or purchase["provider_invoice_id"] != provider_invoice_id:
            raise ValueError("Unknown purchase or invoice")
        if purchase["state"] != "awaiting_payment":
            raise ValueError("Purchase is not awaiting settlement")
        if int(purchase["rub_minor"]) != paid_rub_minor:
            raise ValueError("Settled fiat amount does not match purchase intent")
        tx_id, created = post_transaction(conn, "purchase_credit", f"acquirer:{event_id}", purchase_id,
                                          [(account_ref(purchase["user_id"]), credited_usdt_minor),
                                           ("platform:acquirer-clearing:USDT", -credited_usdt_minor)], purchase["user_id"])
        execute(conn, "INSERT INTO acquirer_events(provider_event_id,purchase_id,payload_hash,created_at) VALUES(?,?,?,?)",
                (event_id, purchase_id, payload_hash, int(time.time())))
        updated = execute(conn, "UPDATE purchase_intents SET state='credited',credited_usdt_minor=? WHERE id=? AND state='awaiting_payment'",
                          (credited_usdt_minor, purchase_id))
        if updated.rowcount != 1:
            raise ValueError("Purchase was settled concurrently")
        conn.commit()
        return tx_id if created else None, created
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


class DepositWebhook(BaseModel):
    event_id: str = Field(min_length=8, max_length=128)
    telegram_id: str = Field(pattern=r"^[0-9]{1,20}$")
    amount_minor: int = Field(gt=0, le=100_000_000_000)
    status: str


class WithdrawalRequest(BaseModel):
    network: str = Field(pattern=r"^(BSC|ETH|POL|ARB|TRX)$")
    asset: str = Field(pattern=r"^USDT$")
    recipient: str = Field(min_length=20, max_length=128)
    amount_minor: int = Field(gt=0, le=100_000_000_000)


class PurchaseCreate(BaseModel):
    amount_rub_minor: int = Field(ge=10_000, le=100_000_000)


class AcquirerEvent(BaseModel):
    event_id: str = Field(min_length=8, max_length=128)
    purchase_id: str = Field(min_length=16, max_length=64)
    provider_invoice_id: str = Field(min_length=1, max_length=128)
    status: str
    paid_rub_minor: int = Field(gt=0, le=100_000_000)
    credited_usdt_minor: int = Field(gt=0, le=100_000_000_000)


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings.from_env()
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if config.app_env == "production":
            gaps = config.production_gaps()
            if gaps:
                raise RuntimeError("Production launch blocked; missing: " + ", ".join(gaps))
        init_db(config)
        yield

    app = FastAPI(title="Aether Wallet API", version="0.1.0", docs_url=None if config.app_env == "production" else "/docs", lifespan=lifespan)

    def authenticated_user(authorization: str | None = Header(default=None)) -> dict[str, str]:
        if not authorization or not authorization.startswith("tma "):
            raise HTTPException(status_code=401, detail="Telegram initData required")
        try:
            return validate_telegram_init_data(authorization[4:], config.telegram_bot_token,
                                               config.telegram_auth_max_age_seconds)
        except ValueError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "mode": "sandbox" if config.app_env != "production" else "production"}

    @app.get("/v1/account")
    def get_account(user: dict[str, str] = Depends(authenticated_user)) -> dict[str, Any]:
        amount = balance(config, user["id"])
        return {"asset": "USDT", "balance_minor": amount, "decimals": 6,
                "display_balance": f"{amount // 1_000_000}.{amount % 1_000_000:06d}"}

    @app.post("/v1/purchases")
    def create_purchase(payload: PurchaseCreate, user: dict[str, str] = Depends(authenticated_user),
                        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
        if config.app_env == "production" or not config.dev_acquirer_enabled:
            raise HTTPException(status_code=503, detail="Acquirer checkout is not configured")
        if not idempotency_key:
            raise HTTPException(status_code=400, detail="Idempotency-Key is required")
        try:
            purchase_id, created = create_purchase_intent(config, user["id"], payload.amount_rub_minor, idempotency_key)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"purchase_id": purchase_id, "status": "awaiting_payment", "asset": "USDT",
                "checkout_url": None, "sandbox_only": True, "duplicate": not created}

    @app.post("/internal/webhooks/acquirer")
    async def acquirer_webhook(payload: AcquirerEvent, request: Request,
                               x_acquirer_signature: str | None = Header(default=None),
                               x_acquirer_timestamp: str | None = Header(default=None)):
        if config.app_env == "production":
            raise HTTPException(status_code=503, detail="Acquirer adapter is not implemented")
        if not config.acquirer_webhook_secret:
            raise HTTPException(status_code=503, detail="Acquirer webhook is not configured")
        try:
            timestamp = int(x_acquirer_timestamp or "")
        except ValueError as exc:
            raise HTTPException(status_code=401, detail="Invalid acquirer timestamp") from exc
        if abs(int(time.time()) - timestamp) > 300:
            raise HTTPException(status_code=401, detail="Acquirer callback expired")
        raw = await request.body()
        signed = str(timestamp).encode() + b"." + raw
        expected = hmac.new(config.acquirer_webhook_secret.encode(), signed, hashlib.sha256).hexdigest()
        if not x_acquirer_signature or not hmac.compare_digest(expected, x_acquirer_signature):
            raise HTTPException(status_code=401, detail="Invalid acquirer signature")
        if payload.status != "settled":
            return {"accepted": False, "reason": "payment is not settled"}
        try:
            tx_id, created = settle_purchase(config, payload.event_id, payload.purchase_id, payload.provider_invoice_id,
                                             payload.paid_rub_minor, payload.credited_usdt_minor)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"accepted": True, "transaction_id": tx_id, "duplicate": not created}

    @app.post("/internal/webhooks/deposits")
    async def deposit_webhook(payload: DepositWebhook, request: Request,
                              x_provider_signature: str | None = Header(default=None)) -> dict[str, Any]:
        if config.app_env == "production":
            raise HTTPException(status_code=503, detail="On-chain deposit verification adapter is not implemented")
        if not config.deposit_webhook_secret:
            raise HTTPException(status_code=503, detail="Deposit provider is not configured")
        raw = await request.body()
        expected = hmac.new(config.deposit_webhook_secret.encode(), raw, hashlib.sha256).hexdigest()
        if not x_provider_signature or not hmac.compare_digest(expected, x_provider_signature):
            raise HTTPException(status_code=401, detail="Invalid provider signature")
        if payload.status != "confirmed":
            return {"accepted": False, "reason": "deposit is not confirmed"}
        tx_id, created = credit_deposit(config, payload.event_id, payload.telegram_id, payload.amount_minor)
        return {"accepted": True, "transaction_id": tx_id, "duplicate": not created}

    @app.post("/internal/dev/credits")
    def dev_credit(payload: DepositWebhook, x_dev_token: str | None = Header(default=None)) -> dict[str, Any]:
        if config.app_env == "production" or not config.dev_credit_enabled or not config.dev_credit_token:
            raise HTTPException(status_code=404, detail="Not found")
        if not x_dev_token or not hmac.compare_digest(config.dev_credit_token, x_dev_token):
            raise HTTPException(status_code=401, detail="Invalid development token")
        if payload.status != "confirmed":
            raise HTTPException(status_code=400, detail="Sandbox credit must be confirmed")
        tx_id, created = credit_deposit(config, f"sandbox:{payload.event_id}", payload.telegram_id, payload.amount_minor)
        return {"transaction_id": tx_id, "duplicate": not created, "sandbox_only": True}

    @app.post("/v1/withdrawals")
    def create_withdrawal(payload: WithdrawalRequest, user: dict[str, str] = Depends(authenticated_user)):
        # Deliberately fail closed: no route quote, beneficiary screening, custody signer,
        # licensed counterparty, or settlement watcher is wired into this sandbox.
        raise HTTPException(status_code=503, detail="Withdrawals are disabled until approved providers and legal controls are configured")

    @app.get("/v1/withdrawals/{withdrawal_id}")
    def withdrawal_status(withdrawal_id: str, user: dict[str, str] = Depends(authenticated_user)):
        raise HTTPException(status_code=503, detail="Withdrawal provider is not configured")

    return app


app = create_app()
