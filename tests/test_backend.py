import asyncio
import hashlib
import hmac
import json
import tempfile
import time
import unittest
from pathlib import Path

import httpx

from backend.app import Settings, create_app, init_db, validate_telegram_init_data

BOT_TOKEN = "123456:local-test-token"


def init_data(user_id="987654321", auth_date=None, tamper=False, with_signature=False):
    fields = {
        "auth_date": str(auth_date or int(time.time())),
        "query_id": "AAE-test-query",
        "user": json.dumps({"id": int(user_id), "first_name": "Test"}, separators=(",", ":")),
    }
    if with_signature:
        fields["signature"] = "test-ed25519-signature"
    check = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    digest = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if tamper:
        digest = "0" * 64
    return "&".join(f"{k}={v}" for k, v in fields.items()) + "&hash=" + digest


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.settings = Settings(
            app_env="development",
            database_url=f"sqlite:///{Path(self.temp.name) / 'db.sqlite'}",
            telegram_bot_token=BOT_TOKEN,
            telegram_auth_max_age_seconds=300,
            deposit_webhook_secret="local-webhook-secret",
            acquirer_webhook_secret="acquirer-webhook-secret",
            dev_credit_token="dev-only-secret",
            dev_credit_enabled=True,
            dev_acquirer_enabled=True,
        )
        init_db(self.settings)
        self.transport = httpx.ASGITransport(app=create_app(self.settings))

    def tearDown(self):
        self.temp.cleanup()

    def request(self, method, path, **kwargs):
        async def run():
            async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
                return await client.request(method, path, **kwargs)
        return asyncio.run(run())

    def test_telegram_signature_and_expiry(self):
        user = validate_telegram_init_data(init_data(), BOT_TOKEN, 300)
        self.assertEqual(user["id"], "987654321")
        self.assertEqual(validate_telegram_init_data(init_data(with_signature=True), BOT_TOKEN, 300)["id"], "987654321")
        with self.assertRaisesRegex(ValueError, "Invalid Telegram signature"):
            validate_telegram_init_data(init_data(tamper=True), BOT_TOKEN, 300)
        with self.assertRaisesRegex(ValueError, "expired"):
            validate_telegram_init_data(init_data(auth_date=int(time.time()) - 301), BOT_TOKEN, 300)

    def test_balance_requires_verified_telegram_init_data(self):
        rejected = self.request("GET", "/v1/account")
        self.assertEqual(rejected.status_code, 401)
        accepted = self.request("GET", "/v1/account", headers={"Authorization": "tma " + init_data()})
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.json()["balance_minor"], 0)

    def test_sandbox_credit_is_protected_and_idempotent(self):
        payload = {"event_id": "sandbox-event-0001", "telegram_id": "987654321", "amount_minor": 1234567, "status": "confirmed"}
        denied = self.request("POST", "/internal/dev/credits", json=payload, headers={"X-Dev-Token": "wrong"})
        self.assertEqual(denied.status_code, 401)
        headers = {"X-Dev-Token": "dev-only-secret"}
        first = self.request("POST", "/internal/dev/credits", json=payload, headers=headers)
        second = self.request("POST", "/internal/dev/credits", json=payload, headers=headers)
        self.assertEqual(first.status_code, 200)
        self.assertFalse(first.json()["duplicate"])
        self.assertTrue(second.json()["duplicate"])
        balance = self.request("GET", "/v1/account", headers={"Authorization": "tma " + init_data()})
        self.assertEqual(balance.json()["balance_minor"], 1234567)

    def test_provider_webhook_hmac_and_duplicate_delivery(self):
        payload = {"event_id": "provider-event-001", "telegram_id": "987654321", "amount_minor": 5000000, "status": "confirmed"}
        raw = json.dumps(payload, separators=(",", ":")).encode()
        signature = hmac.new(b"local-webhook-secret", raw, hashlib.sha256).hexdigest()
        bad = self.request("POST", "/internal/webhooks/deposits", content=raw, headers={"X-Provider-Signature": "no", "Content-Type": "application/json"})
        self.assertEqual(bad.status_code, 401)
        headers = {"X-Provider-Signature": signature, "Content-Type": "application/json"}
        first = self.request("POST", "/internal/webhooks/deposits", content=raw, headers=headers)
        second = self.request("POST", "/internal/webhooks/deposits", content=raw, headers=headers)
        self.assertEqual(first.status_code, 200)
        self.assertTrue(second.json()["duplicate"])

    def test_withdrawals_fail_closed_without_real_providers(self):
        response = self.request("POST", "/v1/withdrawals", json={
            "network": "TRX", "asset": "USDT", "recipient": "T" + "a" * 33, "amount_minor": 1000000,
        }, headers={"Authorization": "tma " + init_data()})
        self.assertEqual(response.status_code, 503)

    def test_sandbox_acquirer_purchase_and_signed_settlement(self):
        auth = {"Authorization": "tma " + init_data()}
        created = self.request("POST", "/v1/purchases", json={"amount_rub_minor": 250000},
                               headers={**auth, "Idempotency-Key": "purchase-demo-001"})
        repeated = self.request("POST", "/v1/purchases", json={"amount_rub_minor": 250000},
                                headers={**auth, "Idempotency-Key": "purchase-demo-001"})
        self.assertEqual(created.status_code, 200)
        self.assertIsNone(created.json()["checkout_url"])
        self.assertTrue(repeated.json()["duplicate"])
        purchase_id = created.json()["purchase_id"]
        other_user = self.request("POST", "/v1/purchases", json={"amount_rub_minor": 250000}, headers={
            "Authorization": "tma " + init_data(user_id="123456789"), "Idempotency-Key": "purchase-demo-001",
        })
        self.assertNotEqual(other_user.json()["purchase_id"], purchase_id)
        event = {"event_id": "acquirer-event-0001", "purchase_id": purchase_id,
                 "provider_invoice_id": f"sandbox:{purchase_id}", "status": "settled",
                 "paid_rub_minor": 250000, "credited_usdt_minor": 12340000}
        raw = json.dumps(event, separators=(",", ":")).encode()
        timestamp = str(int(time.time()))
        signature = hmac.new(b"acquirer-webhook-secret", timestamp.encode() + b"." + raw,
                             hashlib.sha256).hexdigest()
        headers = {"X-Acquirer-Timestamp": timestamp, "X-Acquirer-Signature": signature,
                   "Content-Type": "application/json"}
        mismatched = {**event, "event_id": "acquirer-event-bad-amount", "paid_rub_minor": 250001}
        mismatch_raw = json.dumps(mismatched, separators=(",", ":")).encode()
        mismatch_signature = hmac.new(b"acquirer-webhook-secret", timestamp.encode() + b"." + mismatch_raw,
                                      hashlib.sha256).hexdigest()
        mismatch = self.request("POST", "/internal/webhooks/acquirer", content=mismatch_raw, headers={
            "X-Acquirer-Timestamp": timestamp, "X-Acquirer-Signature": mismatch_signature,
            "Content-Type": "application/json",
        })
        self.assertEqual(mismatch.status_code, 409)
        first = self.request("POST", "/internal/webhooks/acquirer", content=raw, headers=headers)
        second = self.request("POST", "/internal/webhooks/acquirer", content=raw, headers=headers)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertFalse(first.json()["duplicate"])
        self.assertTrue(second.json()["duplicate"])
        balance = self.request("GET", "/v1/account", headers=auth)
        self.assertEqual(balance.json()["balance_minor"], 12340000)

    def test_production_gate_cannot_be_enabled_by_environment_labels_alone(self):
        production = Settings(
            app_env="production",
            database_url="postgresql://prod:secret@db/aether",
            telegram_bot_token="configured",
            deposit_webhook_secret="configured",
            data_region="ru",
            regulatory_approved=True,
            custody_provider="configured",
            chain_provider="configured",
            screening_provider="configured",
            kyc_aml_provider="configured",
            onramp_provider="configured",
            payout_provider="configured",
            kms_key_reference="configured",
        )
        self.assertTrue(any("adapters" in gap for gap in production.production_gaps()))
        app = create_app(production)
        async def enter_production_lifespan():
            async with app.router.lifespan_context(app):
                pass
        with self.assertRaisesRegex(RuntimeError, "audited production provider adapters"):
            asyncio.run(enter_production_lifespan())


if __name__ == "__main__":
    unittest.main()
