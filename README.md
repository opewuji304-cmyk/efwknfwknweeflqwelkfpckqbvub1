# Aether Wallet

Aether is a **self-custody Telegram Mini App prototype**. Seed phrases and signing keys are created and used in the browser. The API stores only public addresses linked to a server-verified Telegram user. The client connects to public mainnet RPC/indexer services and does not custody user funds.

## Implemented in this sandbox

- Encrypted browser wallet storage using Web Crypto AES-GCM and PBKDF2; the seed is no longer written to plaintext `localStorage`.
- First-session backup reminder with **Now** and **Later** actions, a backup page, encrypted export/import, and a local user-confirmed backup status.
- Server API validates Telegram `initData` and stores one public address per supported network (`BSC`, `ETH`, `POL`, `ARB`, `TRX`) in SQLite/PostgreSQL. It never accepts a seed or private key.
- Direct receive and send code is present for the listed EVM mainnets and TRON Mainnet. TRON USDT uses Tether's TRC-20 contract; the send flow simulates the call, estimates Energy/Bandwidth, checks the returned transaction fields/hash, applies a 50 TRX Energy-fee ceiling, and asks for confirmation before signing.
- Mainnet code is not a launch certification: there has been no live transfer, independent wallet/security review, provider SLA/rate-limit setup, or production operations review. Only test with a small amount you control after the app is hosted on HTTPS and you have checked the exact network and recipient.
- Production startup stays blocked pending independent wallet/security review, chain integration review, load test, and operational readiness.

The xRocket Exchange and Pay APIs operate on an xRocket account or application balance. They do not provide per-user seed phrases for this wallet. They are not used to custody or sign Aether user transactions. xRocket-based invoicing or swaps would be a separate custodial product flow and is intentionally not wired into this self-custody wallet.

## Local development

```sh
cp .env.example .env
# Set POSTGRES_PASSWORD and TELEGRAM_BOT_TOKEN for the API.
docker compose up --build
```

GitHub Pages is currently configured to publish the repository root from `main`; a commit to `index.html` updates the live site. The current site URL is `https://opewuji304-cmyk.github.io/efwknfwknweeflqwelkfpckqbvub1/`. Set that HTTPS URL as the Telegram Mini App URL. The BotFather menu/app URL still needs to point to the published site.

For address records linked to Telegram accounts and production TRON access, deploy the API and PostgreSQL separately, set `APP_ORIGINS` to the exact HTTPS frontend origin, store `TRONGRID_API_KEY` and a random 32+ character `API_SESSION_SECRET` in the API host's secret settings, and set `BACKEND_API` in `index.html` to the API origin. The API validates fresh Telegram `initData`, issues a 12-hour bearer session, proxies a strict allowlist of TRON Mainnet calls, applies per-user rate limits, and never receives seed phrases/private keys. Without these settings, the browser falls back to an unauthenticated public TronGrid endpoint with no production quota guarantee, and address registration is off. A self-custody wallet restored on another device must use its backup phrase; Telegram login alone does not recover a wallet.

The backend is available on `http://127.0.0.1:8000`. Local tests:

```sh
pip install -r requirements-dev.txt
python3 -m unittest discover -s tests -v
```

## Production limitations

No mainnet end-to-end transfer, independent audit, supported-network completeness review, KYC/on-ramp, 10,000-user load test, or completed deployment has been verified. The key storage still depends on an HTML app loading JavaScript from third-party CDNs; this needs a hardened asset supply chain and a browser threat review before customer use. Public RPC/indexer endpoints are not provisioned for 10,000 users. Network fees are paid in each network's native token. xRocket API availability does not create gas sponsorship or cross-chain routes for these user-controlled wallets.

See [ARCHITECTURE.md](ARCHITECTURE.md), [AUDIT.md](AUDIT.md), and [ACQUIRER_INTEGRATION.md](ACQUIRER_INTEGRATION.md).
