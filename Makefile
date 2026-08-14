run_polling:
	uv run run_polling.py

run_wh:
	uv run run_webhook.py

bot-up:
	docker compose up --build -d

test:
	uv run pytest
