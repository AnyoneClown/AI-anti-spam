# AI Anti-Spam

Telegram group captcha bot. New users are restricted until they solve a simple math captcha. Failed or expired captcha attempts are banned.

## Required `.env`

Copy `.env.example` to `.env` and replace at least `BOT_TOKEN`.

```env
COMPOSE_PROJECT_NAME=ai-anti-spam
BOT_TOKEN=123456789:replace-with-your-telegram-bot-token
ADMIN_CHAT_ID=0

DEBUG=False
USE_WEBHOOK=False
WEBHOOK_HOST=0.0.0.0
WEBHOOK_PORT=8080
WEBHOOK_BASE_URL=https://example.com
WEBHOOK_PATH=/webhook
WEBHOOK_SECRET=replace-with-random-secret

COCKROACHDB_URL=cockroachdb+asyncpg://USER:PASSWORD@HOST:26257/defaultdb?ssl=require

REDIS_HOST=redis
REDIS_PORT=6379
REDIS_PASS=
```

`ADMIN_CHAT_ID=0` disables admin notifications.

## Launch

```bash
docker compose up -d --build
```

For CockroachDB Cloud, copy your connection string and use the `cockroachdb+asyncpg://` scheme. With asyncpg, use `ssl=require`, not `sslmode=require`.

For polling mode, keep `USE_WEBHOOK=False`. For webhook mode, set `USE_WEBHOOK=True` and configure `WEBHOOK_BASE_URL`, `WEBHOOK_PATH`, `WEBHOOK_SECRET`, and `WEBHOOK_PORT`.
