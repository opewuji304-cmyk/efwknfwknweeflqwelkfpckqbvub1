# Aether Wallet

Проект движется к кастодиальному внутреннему балансу в USD₮ — модели, соответствующей запросу на один счёт и комиссию в стейблкоине. Текущий `index.html` остаётся прежним on-chain прототипом и пока не подключён к новому API.

Добавлен backend sandbox на FastAPI/PostgreSQL: серверная проверка Telegram `initData`, баланс ledger в микродолях USD₮, HMAC-подписанные тестовые зачисления, idempotency и fail-closed production gate. Выводы, реальный мониторинг депозитов, хранение/подписание ключей, KYC/AML, on/off-ramp и кроссчейн-маршруты намеренно выключены до правовой и технической интеграции.

## Локальная разработка

Нужны Docker Compose и Telegram bot token для локальных запросов:

```sh
cp .env.example .env
# Задайте POSTGRES_PASSWORD и TELEGRAM_BOT_TOKEN в .env
docker compose up --build
```

API доступен локально на `http://127.0.0.1:8000`; документация разработчика — `/docs`. Тесты без Docker:

```sh
pip install -r requirements-dev.txt
python3 -m unittest discover -s tests -v
```

Локальный bootstrap использует SQLite; compose поднимает PostgreSQL. Оба режима — только sandbox. Никакие реальные депозиты/выводы не поддерживаются.

Подробнее: [архитектура, правовые ограничения РФ и блокеры production](ARCHITECTURE.md), [аудит исходного клиента](AUDIT.md).
Условия интеграции эквайринга: [ACQUIRER_INTEGRATION.md](ACQUIRER_INTEGRATION.md).
