# Telescan Bot

Official Telegram bot for [Telescan](https://github.com/hiTechTeam/Telescan-iOS). [@tgtelescan_bot](https://t.me/tgtelescan_bot) creates an eight-character code that links a Telegram profile to the iOS app. Only its SHA-256 hash is stored; generating a new code invalidates the previous one.

## Use

Open the bot, send `/start` or `/code`, and enter the returned code in Telescan. Use `/update_code` when you need a replacement.

## Run locally

Requires Python 3.13+, [uv](https://docs.astral.sh/uv/), MongoDB, and S3-compatible storage. Create `.env` with:

```dotenv
BOT_TOKEN=
TELEGRAM_PROXY_URL=
MONGO_USERNAME=
MONGO_PASSWORD=
MONGO_HOST=
MONGO_PORT=27017
MONGO_DBNAME=
TelescanS3AccessKey=
TelescanS3SecretKey=
WEBHOOK_BASE_URL=
WEBHOOK_SECRET_TOKEN=
```

`TELEGRAM_PROXY_URL` is required by the current bot configuration. The webhook variables are needed only for webhook mode.

```sh
uv sync
make run_polling
```

Alternatively, create the shared Docker network once and run the bot in Docker:

```sh
docker network create telescan_network
make bot-up
```

## Links

[Project documentation](https://github.com/hiTechTeam/Telescan-info) · [Developer](https://github.com/r66cha)

Licensed under the [MIT License](LICENSE).
