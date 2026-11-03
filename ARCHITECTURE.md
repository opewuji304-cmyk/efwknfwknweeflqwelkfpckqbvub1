# Aether Wallet architecture

## Product model

The target is **self-custody**. A user's mnemonic/private key is generated and used in that user's browser. The server never receives the mnemonic, private key, encrypted backup, or a signing request. The backend verifies Telegram Mini App `initData` and stores public address mappings only.

## Current implementation

- The Mini App generates a mnemonic locally. It encrypts it in browser storage with AES-GCM; the wrapping key is derived from a device password with PBKDF2. Unlock is required on each new page session.
- An onboarding modal offers **Now** and **Later** for backup. **Now** opens the backup page. The page exports/imports a password-encrypted file and can show the recovery phrase. Backup completion is a local user confirmation, not something the server can verify.
- The address registry endpoint `GET/PUT /v1/wallet/addresses` requires recent signed Telegram `initData`; it stores public EVM and TRON addresses in a DB row keyed by Telegram ID and network. EVM networks share one address. No secret material is sent.
- EVM and TRON direct transfers are signed in the browser. For TRON, the API can proxy a strict allowlist of Mainnet RPC calls to TronGrid using a server-side API key; it authenticates signed Telegram `initData`, applies a per-user in-memory rate limit, and only relays the signed transaction. It never receives seed phrases or private keys. The frontend's direct public RPC fallback is for low-volume development only. LI.FI provides EVM quote/route data; the browser signs the returned EVM transaction. The supported lists in `index.html` define the current network/asset scope.
- The former custodial ledger and sandbox payment endpoints remain disabled for production. They do not represent user funds and must not be mixed with the self-custody balances.

## xRocket integration boundary

xRocket Exchange API is for an xRocket user's exchange account: market data, orders, funding/trading balances, transfers, and withdrawals. Its private bearer token grants control over that xRocket account. xRocket Pay API is for an application balance: invoices, swaps against that balance, payouts, withdrawals, and signed webhooks. These APIs do not issue an Aether user's seed phrase or turn an xRocket application balance into a self-custody wallet. Connecting a single xRocket app token to user send/swap buttons would change the product into a custodial service, so this build does not do that.

If xRocket is used later, it should be an explicitly separate, opt-in payment or exchange workflow with a provider account, legally reviewed terms, server-side secrets, signed webhook verification, idempotency, reconciliation, and user-visible disclosure. The Pay API's request limits and callback delivery semantics must be handled by shared caches/queues and a durable event store.

## Known limits

- A recovery phrase unlocks funds on every chain derived from it. Browser extensions, XSS, compromised CDN assets, device malware, or a weak password can expose it. Use local/pinned dependencies, a hardened content security policy, independent wallet review, and a threat-modelled recovery flow before mainnet use.
- Backup completion is self-reported locally. The product cannot verify that a user saved a file or wrote down words.
- Address registry requests are protected by Telegram HMAC verification and use Postgres in Compose. Production CORS must be restricted with `APP_ORIGINS`. The TRON proxy's current rate limiter is per-process/in-memory and is not a substitute for a shared gateway limiter. Abuse controls, backup/restore, database failover, alerting and a 10,000-user concurrency test remain deployment work.
- Current transaction UI is not equivalent to Telegram Wallet: EVM and TRON are separate networks; native gas is required; cross-chain quoting covers only the routes supported by the current EVM client/LI.FI account; no shared USDT ledger or universal USDT fee sponsorship exists.
- SBP/on-ramp, fiat conversion, KYC/AML, bridge execution monitoring, sanctions checks, account recovery, and production deployment are not connected.

## Production gate

Production startup is deliberately blocked. Before customer launch, finish an independent audit of wallet derivation, encrypted storage, restore/import, UI/script supply chain, transaction confirmation, and address registry; validate each chain/token contract; complete a controlled low-value Mainnet receive/send and recovery drill; complete concurrency and failure testing; configure production database, hosting, TLS, monitoring, backups and incident response; and obtain jurisdiction-specific legal review. The controlled Mainnet operation must use wallets and funds owned by the operator and be reconciled in a block explorer.
