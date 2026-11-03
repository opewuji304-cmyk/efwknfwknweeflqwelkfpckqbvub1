# Aether Wallet implementation review

## Changes in this pass

- Replaced the browser's plaintext mnemonic storage with a password-encrypted local record (AES-GCM, Web Crypto, PBKDF2, 600,000 iterations). Existing plaintext browser records are migrated after the user sets a password and then removed.
- Added the first-session **Now / Later** backup prompt. **Now** opens the backup screen; **Later** dismisses it. A seed reveal no longer marks the backup as complete. File export is encrypted and no longer copies the backup blob to the clipboard. Restore checks the decrypted mnemonic and expected EVM address before replacing the local wallet.
- Added an optional server address registry. It requires Telegram `initData` validated on the server; it stores only public addresses, validates configured networks/address formats, and prevents the same network/address being linked to multiple Telegram users.
- Added TRON Mainnet transaction review: live Energy/Bandwidth queries, a fee ceiling, transaction-field/hash validation before signature, and an in-app confirmation step. Default Receive and Send now select TRON USDT.
- Added an authenticated API proxy for a server-side TronGrid key, a strict RPC path allowlist, payload-size limit, and per-process user request throttle. The key remains outside the browser.
- Added a 12-hour HMAC bearer session minted only after fresh Telegram `initData` validation so the Mini App can poll after the five-minute initData freshness window without extending that window.
- Production startup remains fail-closed pending legal approval, independent review, controlled low-value Mainnet review, load test, and operations readiness.

## Remaining security / behavior issues

- Password-based browser encryption does not protect a session while unlocked. Third-party JavaScript loaded from CDNs can access page memory; local dependencies, CSP, dependency pinning, wallet-specific threat review and penetration testing are still required.
- Password KDF work can be heavy on low-end devices. Measure on target Telegram clients and consider a vetted memory-hard KDF before launch.
- Backup status is a local acknowledgement and cannot prove that a backup is usable or stored safely.
- Telegram ID from `initDataUnsafe` is used only to namespace local browser state and show profile labels. Server identity uses the signed `initData` in the `Authorization: tma` header.
- Direct EVM/TRON transfers need the chain's native gas asset. The client does not pay every network fee in USDT.
- No TronGrid key or production backend URL has been supplied/configured. GitHub Pages currently uses the unauthenticated direct TronGrid fallback, which has no production quota guarantee; the authenticated proxy is not live until a server is deployed and `BACKEND_API` is set.
- The current client does not support every chain/token/route, and no live Mainnet deposit/send has been verified from this environment.
- The separate `/Users/mac/Desktop/server.py` source originally supplied was a nonfunctional stub: wildcard CORS, no auth, user-controlled HTML in an admin message, fresh `aiohttp` session without timeout/status handling, and fabricated order/QR success. It has now been replaced with the tested backend API; it no longer fabricates orders or payment QR codes.

## Verification

Backend unit tests cover Telegram HMAC/expiry, address registration/authentication, address format checks, collisions, sandbox idempotency, and fail-closed withdrawals. Python compilation passes. Docker is not installed in the current environment, so Compose/PostgreSQL runtime, actual chain RPC, third-party quote execution, mobile Telegram display, and 10,000-user behavior still need external verification.
