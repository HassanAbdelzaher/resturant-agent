VENV   := .venv
PY     := $(VENV)/bin/python
PIP    := $(VENV)/bin/pip

.DEFAULT_GOAL := help

# ── Help ─────────────────────────────────────────────────────────────
.PHONY: help
help:
	@echo ""
	@echo "  🍽️  مطعم أبو طبق — WhatsApp Agent"
	@echo ""
	@echo "  Setup"
	@echo "    make install      Create .venv and install dependencies"
	@echo "    make env          Create .env from .env.example"
	@echo ""
	@echo "  Run"
	@echo "    make dev          Start with hot-reload  (DEBUG=true)"
	@echo "    make start        Start in production     (DEBUG=false)"
	@echo "    make tunnel       Expose port 8000 via ngrok"
	@echo ""
	@echo "  Test"
	@echo "    make health       GET / — check server is up"
	@echo "    make test-menu    Simulate 'give me the menu' WhatsApp message"
	@echo "    make test-mcp     Run restaurant MCP server standalone"
	@echo ""
	@echo "  Maintenance"
	@echo "    make kill         Free port 8000"
	@echo "    make reset-db     Delete SQLite database"
	@echo "    make reset-rag    Delete ChromaDB vector store"
	@echo "    make reset        Full reset (db + rag + cache)"
	@echo ""

# ── Setup ─────────────────────────────────────────────────────────────
.PHONY: install
install:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	@echo ""
	@echo "✅  Done! Activate the env with:  source $(VENV)/bin/activate"

.PHONY: env
env:
	@if [ -f .env ]; then \
		echo "⚠️  .env already exists — delete it first if you want to reset"; \
	else \
		cp .env.example .env; \
		echo "✅  .env created — fill in your API keys"; \
	fi

# ── Run ───────────────────────────────────────────────────────────────
.PHONY: dev
dev:
	DEBUG=true $(PY) main.py

.PHONY: start
start:
	DEBUG=false $(PY) main.py

.PHONY: tunnel
tunnel:
	@command -v ngrok >/dev/null 2>&1 || { echo "❌  ngrok not found → https://ngrok.com/download"; exit 1; }
	@echo "🌐  Tunnel started — paste the HTTPS URL into:"
	@echo "     GreenAPI → My Instances → Account → Notifications → Webhook URL"
	@echo "     Append:  /webhook/greenapi"
	ngrok http 8000

# ── Test ──────────────────────────────────────────────────────────────
.PHONY: health
health:
	@curl -s http://localhost:8000/ | python3 -m json.tool

.PHONY: test-menu
test-menu:
	@curl -s -X POST http://localhost:8000/webhook/greenapi \
		-H "Content-Type: application/json" \
		-d '{"typeWebhook":"incomingMessageReceived","instanceData":{"idInstance":0,"wid":"test@c.us","typeInstance":"whatsapp"},"timestamp":0,"idMessage":"test-001","senderData":{"chatId":"10000000000@c.us","chatName":"Test","sender":"10000000000@c.us","senderName":"Test"},"messageData":{"typeMessage":"textMessage","textMessageData":{"textMessage":"اعطني قائمة الطعام"}}}' \
		| python3 -m json.tool 2>/dev/null || echo "(check server logs)"

.PHONY: test-mcp
test-mcp:
	$(PY) mcp_servers/restaurant_mcp.py --menu-path ./data/restaurant_menu.json

# ── Maintenance ───────────────────────────────────────────────────────
.PHONY: kill
kill:
	@lsof -ti:8000 | xargs kill -9 2>/dev/null \
		&& echo "✅  Killed process on port 8000" \
		|| echo "ℹ️  Nothing running on port 8000"

.PHONY: reset-db
reset-db:
	rm -f data/bot.db data/bot.db-journal data/bot.db-shm data/bot.db-wal
	@echo "🗑️  Database deleted"

.PHONY: reset-rag
reset-rag:
	rm -rf data/chroma_db
	@echo "🗑️  ChromaDB deleted"

.PHONY: reset
reset: reset-db reset-rag
	find . -type d -name __pycache__ -not -path './.venv/*' -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -not -path './.venv/*' -delete 2>/dev/null || true
	@echo "✅  Full reset complete"
