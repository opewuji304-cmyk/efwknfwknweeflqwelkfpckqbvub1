# Aether Wallet

Aether is being prepared as a **self-custody Telegram Mini App**. Seed phrases and signing keys are created and used in the browser. The API stores only public addresses linked to a server-verified Telegram user. Do not use this sandbox with real funds.

## Implemented in this sandbox

- Encrypted browser wallet storage using Web Crypto AES-GCM and PBKDF2; the seed is no longer written to plaintext `localStorage`.
- First-session backup reminder with **Now** and **Later** actions, a backup page, encrypted export/import, and a local user-confirmed backup status.
- Server API validates Telegram `initData` and stores one public address per supported network (`BSC`, `ETH`, `POL`, `ARB`, `TRX`) in SQLite/PostgreSQL. It never accepts a seed or private key.
- Existing client supports direct receive/send for the listed EVM networks and TRON; LI.FI quotes and client-side EVM execution are present in the prototype.
- Production startup stays blocked pending independent wallet/security review, chain integration review, load test, and operational readiness.

The xRocket Exchange and Pay APIs operate on an xRocket account or application balance. They do not provide per-user seed phrases for this wallet. They are not used to custody or sign Aether user transactions. xRocket-based invoicing or swaps would be a separate custodial product flow and is intentionally not wired into this self-custody wallet.

## Local development

```sh
cp .env.example .env
# Set POSTGRES_PASSWORD and TELEGRAM_BOT_TOKEN for the API.
docker compose up --build
```

Set `APP_ORIGINS` to the exact HTTPS origin hosting the Mini App and `BACKEND_API` in `index.html` to the API origin. The browser sends Telegram `initData` only to the backend for signature verification; it does not send the seed or private keys.

The backend is available on `http://127.0.0.1:8000`. Local tests:

```sh
pip install -r requirements-dev.txt
python3 -m unittest discover -s tests -v
```

## Not production-ready

No mainnet/testnet end-to-end run, independent audit, supported-network completeness review, KYC/on-ramp, 10,000-user load test, or deployment has been completed. The key storage still depends on an HTML app loading JavaScript from third-party CDNs; this needs a hardened asset supply chain and a browser threat review before real funds. Network fees are paid in each network's native token. xRocket API availability does not create gas sponsorship or cross-chain routes for these user-controlled wallets.

See [ARCHITECTURE.md](ARCHITECTURE.md), [AUDIT.md](AUDIT.md), and [ACQUIRER_INTEGRATION.md](ACQUIRER_INTEGRATION.md).
