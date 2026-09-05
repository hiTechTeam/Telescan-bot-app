# Telescan Bot

Telegram bot that links a public Telegram profile to Telescan. It requests
one-time codes and synchronizes the profile photo through the internal API. It
does not connect to MongoDB or object storage.

## Run locally

```sh
cp .env.example .env
uv sync
uv run pytest
make run_polling
```

Required settings are `BOT_TOKEN`, `API_BASE_URL` and `BOT_SERVICE_SECRET`.
Webhook mode additionally uses `WEBHOOK_BASE_URL` and
`WEBHOOK_SECRET_TOKEN`. Never commit `.env` or expose the internal notification
endpoint through nginx.

Users need a public Telegram username. `/start`, `/code` and `/update_code`
return a short-lived code once; the bot never stores or logs its clear value.
Photo synchronization runs independently, so temporary Telegram or storage
errors do not block code delivery or erase the previous photo.

## Checks and deployment

```sh
make check
docker compose config --quiet
```

Pull requests run lint, type checks, tests and a Docker build. A successful
push to protected `main` deploys the private polling container. Releases are
immutable and automatically roll back if health checks fail. Runtime secrets
remain on the server.

## License

Proprietary and confidential. See [LICENSE](LICENSE).
