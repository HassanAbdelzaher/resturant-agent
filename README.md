<div align="center">

# 🍽️ مطعم أبو طبق — WhatsApp AI Agent

### An intelligent WhatsApp chatbot for **Abu Tabaq Restaurant**

<br>

Built with **FastAPI** · **LangChain** · **Model Context Protocol (MCP)** · **ChromaDB** · **GreenAPI**

<br>

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![LangChain](https://img.shields.io/badge/LangChain-1C3C3C?style=for-the-badge&logo=langchain&logoColor=white)
![Claude](https://img.shields.io/badge/Claude_3.5-Anthropic-D97706?style=for-the-badge)
![WhatsApp](https://img.shields.io/badge/WhatsApp-25D366?style=for-the-badge&logo=whatsapp&logoColor=white)

</div>

---

## Table of Contents

- [Overview](#overview)
- [Key Features](#key-features)
- [Architecture](#architecture)
- [Answer Pipeline — How Queries Are Resolved](#answer-pipeline--how-queries-are-resolved)
- [Project Structure](#project-structure)
- [Technology Stack](#technology-stack)
- [Setup & Installation](#setup--installation)
- [Configuration](#configuration)
- [Running the Server](#running-the-server)
- [WhatsApp Commands](#whatsapp-commands)
- [MCP Tools Reference](#mcp-tools-reference)
- [PDF RAG Pipeline](#pdf-rag-pipeline)
- [Database Schema](#database-schema)
- [API Endpoints](#api-endpoints)
- [Data Flow Examples](#data-flow-examples)
- [Makefile Commands](#makefile-commands)
- [Customization Guide](#customization-guide)

---

## Overview

**Abu Tabaq Restaurant Agent** is a production-ready WhatsApp AI assistant that serves as a virtual waiter for a Saudi Arabian restaurant. It answers customer questions about the menu, dishes, prices, recommendations, daily specials, and more — entirely in Arabic with a warm, humorous personality.

The agent receives messages through the **GreenAPI** WhatsApp gateway, processes them through an intelligent multi-stage pipeline, and responds with beautifully formatted WhatsApp messages. It combines three data sources — structured restaurant data via **MCP tools**, supplementary documents via a **PDF RAG pipeline**, and a personality-driven **LLM fallback** — to always provide a relevant answer.

---

## Key Features

| Feature                      | Description                                                                                           |
| ---------------------------- | ----------------------------------------------------------------------------------------------------- |
| **🤖 Intelligent Routing**   | LLM automatically selects the best MCP tool and generates arguments for each query                    |
| **📋 Full Menu Access**      | Browse by category, search by keyword, get detailed dish info with calories, allergens, and fun facts |
| **⭐ Smart Recommendations** | Curated suggestions for vegetarians, spicy lovers, families, kids, and budget-conscious diners        |
| **📅 Daily Specials**        | Automatic day-of-week specials with discounts                                                         |
| **📄 PDF Knowledge Base**    | Upload PDFs via WhatsApp to expand the agent's knowledge dynamically                                  |
| **💬 Conversation Memory**   | Maintains per-user conversation history (last 6 messages) for contextual replies                      |
| **🇸🇦 Arabic Personality**    | Responds in a blend of Modern Standard Arabic with Saudi warmth and humor                             |
| **🔌 Extensible MCP**        | Add new data sources by simply adding MCP servers to the config file                                  |
| **⚡ Fully Async**           | All I/O operations (database, HTTP, LLM) are non-blocking                                             |
| **🗄️ User Tracking**         | Tracks users, message counts, and first/last active timestamps                                        |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        WhatsApp User                                │
└────────────────────────────┬────────────────────────────────────────┘
                             │  Message
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    GreenAPI Cloud Gateway                            │
│              (Webhook POST → /webhook/greenapi)                     │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     FastAPI Server (main.py)                        │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │            WhatsApp Handler (whatsapp_handler.py)            │   │
│  │  • Parse GreenAPI webhook payload                           │   │
│  │  • Route: text → Agent  |  PDF → RAG  |  /command → handler │   │
│  └──────────────────────────┬───────────────────────────────────┘   │
│                             │                                       │
│                             ▼                                       │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │              WhatsApp Agent (agent.py)                       │   │
│  │                                                              │   │
│  │  ┌─────────────────────────────────────────────────────┐     │   │
│  │  │           ANSWER PIPELINE (Priority Order)          │     │   │
│  │  │                                                     │     │   │
│  │  │  ① MCP Tools ─────► Restaurant menu, specials,     │     │   │
│  │  │  │                   dish details, search           │     │   │
│  │  │  │                                                  │     │   │
│  │  │  ② PDF RAG ───────► Supplementary documents,       │     │   │
│  │  │  │                   uploaded PDFs                   │     │   │
│  │  │  │                                                  │     │   │
│  │  │  ③ LLM Fallback ──► Personality-driven response    │     │   │
│  │  │                      with Abu Tabaq waiter persona  │     │   │
│  │  └─────────────────────────────────────────────────────┘     │   │
│  └──────────┬──────────────┬──────────────┬─────────────────────┘   │
│             │              │              │                          │
│             ▼              ▼              ▼                          │
│  ┌──────────────┐ ┌──────────────┐ ┌────────────────┐              │
│  │  MCP Manager │ │  PDF RAG     │ │   Database      │              │
│  │  (mcp_mgr)   │ │  (pdf_rag)   │ │  (database.py)  │              │
│  │              │ │              │ │                  │              │
│  │  ┌────────┐ │ │  ChromaDB    │ │  SQLite/Postgres │              │
│  │  │MCP     │ │ │  + HuggingFace│ │  • Users         │              │
│  │  │Client  │ │ │  Embeddings  │ │  • Conversations  │              │
│  │  └───┬────┘ │ │              │ │  • Documents      │              │
│  └──────┼──────┘ └──────────────┘ └────────────────┘              │
│         │                                                           │
│         ▼                                                           │
│  ┌──────────────────────┐                                           │
│  │  Restaurant MCP      │                                           │
│  │  (restaurant_mcp.py) │                                           │
│  │  + menu JSON data    │                                           │
│  └──────────────────────┘                                           │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Answer Pipeline — How Queries Are Resolved

The agent uses a **three-stage fallback pipeline** to ensure every question gets an answer:

### Stage 1: MCP Tools (Structured Data — Highest Priority)

```
User Question
    │
    ▼
LLM analyzes question + available MCP tools
    │
    ▼
LLM selects best tool + generates JSON arguments
    ├── e.g. {"tool": "search_menu", "arguments": {"keyword": "دجاج"}}
    │
    ▼
MCPManager routes call to correct MCP server
    │
    ▼
MCP server executes tool, returns formatted result
    │
    ▼
Result returned directly (restaurant tools are pre-formatted)
```

**When it fires:** Any question about the menu, dishes, prices, categories, recommendations, specials, or restaurant info.

### Stage 2: PDF RAG (Document Knowledge — Secondary)

```
User Question
    │
    ▼
ChromaDB similarity search (k=4 chunks)
    │
    ▼
Top chunks passed as context to LLM
    │
    ▼
LLM generates answer grounded in document content
```

**When it fires:** When MCP tools don't produce a relevant result and PDFs have been ingested with matching content.

### Stage 3: LLM Fallback (Personality Response — Last Resort)

```
User Question + Conversation History
    │
    ▼
System Prompt (Abu Tabaq waiter persona)
    │
    ▼
LLM generates conversational Arabic response
```

**When it fires:** Greetings, off-topic questions, general conversation, or when neither MCP nor RAG has relevant data.

---

## Project Structure

```
restaurant_agent/
├── main.py                     # FastAPI entry point, lifecycle, health endpoints
├── Makefile                    # Development commands (install, dev, test, reset)
├── requirements.txt            # Python dependencies
├── .env.example                # Environment variables template
│
├── app/
│   ├── __init__.py
│   ├── config.py               # Pydantic Settings — loads .env variables
│   ├── agent.py                # Main orchestrator — answer pipeline logic
│   ├── whatsapp_handler.py     # GreenAPI webhook + command routing
│   ├── mcp_manager.py          # Multi-server MCP connection manager
│   ├── mcp_client.py           # Low-level MCP SDK wrapper (stdio/SSE)
│   ├── pdf_rag.py              # PDF ingestion → ChromaDB → QA chain
│   └── database.py             # Async SQLAlchemy models + operations
│
├── mcp_servers/
│   ├── __init__.py
│   ├── mcp_config.json         # MCP server definitions (command, args, enabled)
│   └── restaurant_mcp.py       # Restaurant menu MCP server (7 tools)
│
├── data/
│   ├── restaurant_menu.json    # Full restaurant data (dishes, specials, etc.)
│   ├── bot.db                  # SQLite database (auto-created)
│   └── chroma_db/              # ChromaDB vector store (auto-created)
│
└── pdfs/                       # Drop PDF files here for RAG ingestion
```

### Module Dependency Graph

```
main.py
  ├── app/config.py          (settings singleton)
  ├── app/agent.py           (WhatsAppAgent)
  │     ├── app/mcp_manager.py
  │     │     ├── app/mcp_client.py  (MCP SDK wrapper)
  │     │     └── mcp_servers/mcp_config.json
  │     ├── app/pdf_rag.py   (ChromaDB + LangChain)
  │     └── app/database.py  (SQLAlchemy async)
  └── app/whatsapp_handler.py (GreenAPI webhook)
        └── app/agent.py     (calls agent.answer())
```

---

## Technology Stack

| Layer                 | Technology                               | Purpose                                       |
| --------------------- | ---------------------------------------- | --------------------------------------------- |
| **Web Framework**     | FastAPI + Uvicorn                        | Async HTTP server with hot-reload             |
| **WhatsApp Gateway**  | GreenAPI                                 | Send/receive WhatsApp messages via REST API   |
| **HTTP Client**       | httpx                                    | Async HTTP requests to GreenAPI               |
| **LLM (Primary)**     | Claude 3.5 Sonnet (Anthropic)            | Tool selection, summarization, conversation   |
| **LLM (Alternative)** | GPT-4o-mini (OpenAI)                     | Drop-in replacement via config                |
| **LLM Orchestration** | LangChain                                | Chains, prompts, output parsing               |
| **Embeddings**        | sentence-transformers (all-MiniLM-L6-v2) | Local, free text embeddings                   |
| **Vector Store**      | ChromaDB                                 | Persistent local vector database              |
| **PDF Parsing**       | pypdf + pdfplumber                       | Extract text from PDF documents               |
| **Database**          | SQLAlchemy (async) + aiosqlite           | Users, conversations, document tracking       |
| **Tool Protocol**     | Model Context Protocol (MCP)             | Structured tool interface for restaurant data |
| **Config**            | Pydantic Settings + python-dotenv        | Type-safe environment variable loading        |

---

## Setup & Installation

### Prerequisites

- **Python 3.10+**
- A **GreenAPI** account (free tier available at [green-api.com](https://green-api.com))
- An **Anthropic** or **OpenAI** API key

### Step 1: Clone & Install

```bash
git clone <repository-url>
cd restaurant_agent

# Create virtual environment and install dependencies
make install
```

Or manually:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Step 2: Configure Environment

```bash
make env  # Creates .env from .env.example
```

Edit `.env` with your actual credentials:

```bash
# Required: GreenAPI credentials
GREENAPI_ID_INSTANCE=<your_instance_id>
GREENAPI_API_TOKEN=<your_api_token>
GREENAPI_API_URL=https://<your_subdomain>.api.greenapi.com
GREENAPI_MEDIA_URL=https://<your_subdomain>.media.greenapi.com

# Required: LLM API key (at least one)
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...

# Optional: Switch to OpenAI
# LLM_PROVIDER=openai
# OPENAI_API_KEY=sk-...
```

### Step 3: Configure GreenAPI Webhook

1. Log in to your [GreenAPI dashboard](https://green-api.com)
2. Go to your instance settings
3. Set the **webhook URL** to:
   ```
   https://<your-public-domain>/webhook/greenapi
   ```
4. For local development, use ngrok:
   ```bash
   make tunnel  # Exposes port 8000 via ngrok
   ```

---

## Configuration

All configuration is managed via environment variables loaded from `.env`:

| Variable               | Default                             | Description                                               |
| ---------------------- | ----------------------------------- | --------------------------------------------------------- |
| `GREENAPI_ID_INSTANCE` | —                                   | GreenAPI instance ID                                      |
| `GREENAPI_API_TOKEN`   | —                                   | GreenAPI API token                                        |
| `GREENAPI_API_URL`     | `https://api.green-api.com`         | GreenAPI REST API base URL                                |
| `GREENAPI_MEDIA_URL`   | `https://media.green-api.com`       | GreenAPI media download URL                               |
| `LLM_PROVIDER`         | `anthropic`                         | LLM provider: `"anthropic"` or `"openai"`                 |
| `ANTHROPIC_API_KEY`    | —                                   | Anthropic API key                                         |
| `OPENAI_API_KEY`       | —                                   | OpenAI API key (if using OpenAI)                          |
| `DATABASE_URL`         | `sqlite+aiosqlite:///./data/bot.db` | Database connection string                                |
| `CHROMA_PERSIST_DIR`   | `./data/chroma_db`                  | ChromaDB persistence directory                            |
| `PDF_DIRECTORY`        | `./pdfs`                            | Directory to scan for PDF files                           |
| `MCP_TRANSPORT`        | `stdio`                             | MCP transport: `"stdio"`, `"sse"`, or `"streamable-http"` |
| `APP_HOST`             | `0.0.0.0`                           | Server bind address                                       |
| `APP_PORT`             | `8000`                              | Server port                                               |
| `DEBUG`                | `true`                              | Enable debug logging and hot-reload                       |

---

## Running the Server

### Development (with hot-reload)

```bash
make dev
```

### Production

```bash
make start
```

### Expose to Internet (for GreenAPI webhooks)

```bash
make tunnel  # Requires ngrok installed
```

### Health Check

```bash
make health
# or
curl http://localhost:8000/
```

---

## WhatsApp Commands

Users can send these commands from WhatsApp:

| Command             | Description                                     |
| ------------------- | ----------------------------------------------- |
| `/قائمة` or `/menu` | Display the full restaurant menu                |
| `/عروض`             | Show today's daily specials and discounts       |
| `/توصية`            | Get chef's recommendations                      |
| `/مطعم`             | Restaurant information (hours, phone, delivery) |
| `/help`             | List all available commands                     |
| `/status`           | Show agent system status                        |
| `/ingest`           | Re-process all PDF files                        |
| `/sources`          | List all ingested PDF sources                   |

Any other text message is processed through the intelligent answer pipeline.

**PDF Upload:** Sending a PDF file via WhatsApp automatically ingests it into the RAG knowledge base.

---

## MCP Tools Reference

The restaurant MCP server exposes **7 tools** that the LLM can automatically select and invoke:

### `get_full_menu`

Returns the complete restaurant menu organized by category with prices and recommendations.

- **Input:** None
- **Output:** Formatted Arabic menu with all 20 dishes across 5 categories

### `get_category_menu`

Returns dishes in a specific category.

- **Input:** `category` — Category name in Arabic or English (e.g., `"مشويات"`, `"grills"`)
- **Output:** Formatted list of dishes in that category

### `get_dish_details`

Returns comprehensive details about a specific dish.

- **Input:** `dish_name` — Dish name in Arabic or English (e.g., `"كبسة دجاج"`)
- **Output:** Full details including ingredients, allergens, calories, prep time, and a fun fact

### `search_menu`

Search for dishes by keyword across names, ingredients, and descriptions.

- **Input:** `keyword` — Search term (e.g., `"دجاج"`, `"نباتي"`, `"حار"`)
- **Output:** All matching dishes with details

### `get_recommendations`

Returns curated dish recommendations based on dining preference.

- **Input:** `preference` — One of: `"نباتي"` (vegetarian), `"حار"` (spicy), `"عائلة"` (family), `"فردي"` (individual), `"أطفال"` (kids), `"اقتصادي"` (budget), `"chef_picks"`
- **Output:** 3-4 handpicked dishes with descriptions

### `get_daily_specials`

Returns today's special offer and the full week's schedule.

- **Input:** None
- **Output:** Today's discounted dish + all weekly specials

### `get_restaurant_info`

Returns general restaurant information.

- **Input:** None
- **Output:** Name, phone, working hours, delivery time, minimum order, currency

---

## PDF RAG Pipeline

The PDF RAG (Retrieval-Augmented Generation) system allows the agent to answer questions from uploaded PDF documents.

### How It Works

```
PDF File(s)
    │
    ▼  pypdf + pdfplumber
Extract Text
    │
    ▼  RecursiveCharacterTextSplitter (500 chars, 50 overlap)
Split into Chunks
    │
    ▼  all-MiniLM-L6-v2 (sentence-transformers)
Generate Embeddings
    │
    ▼
Store in ChromaDB (persistent)
    │
    ▼  On query: similarity search (k=4)
Retrieve Relevant Chunks
    │
    ▼  LangChain QA Chain
LLM Generates Grounded Answer
```

### Configuration

| Parameter       | Value                             |
| --------------- | --------------------------------- |
| Embedding Model | `all-MiniLM-L6-v2` (local, free)  |
| Chunk Size      | 500 characters                    |
| Chunk Overlap   | 50 characters                     |
| Retrieval Count | Top 4 similar chunks              |
| Vector Store    | ChromaDB (file-based, persistent) |
| PDF Directory   | `./pdfs/`                         |

### Adding PDFs

**Option 1:** Place PDF files in the `./pdfs/` directory before starting the server. They are ingested automatically on startup.

**Option 2:** Send a PDF via WhatsApp to the bot. It will be downloaded and ingested in real-time.

**Option 3:** Trigger manual re-ingestion:

```bash
curl -X POST http://localhost:8000/ingest
# or send /ingest command on WhatsApp
```

---

## Database Schema

The application uses async SQLAlchemy with SQLite (default) or PostgreSQL.

### Users Table

| Column          | Type                     | Description                            |
| --------------- | ------------------------ | -------------------------------------- |
| `id`            | Integer (PK)             | Auto-increment ID                      |
| `wa_id`         | String (unique, indexed) | WhatsApp ID (e.g., `79001234567@c.us`) |
| `name`          | String (nullable)        | User display name                      |
| `first_seen`    | DateTime (TZ)            | First message timestamp                |
| `last_active`   | DateTime (TZ)            | Most recent message timestamp          |
| `message_count` | Integer                  | Total messages sent                    |

### Conversations Table

| Column      | Type              | Description                                 |
| ----------- | ----------------- | ------------------------------------------- |
| `id`        | Integer (PK)      | Auto-increment ID                           |
| `wa_id`     | String (indexed)  | User's WhatsApp ID                          |
| `role`      | String            | `"user"` or `"assistant"`                   |
| `content`   | Text              | Full message text                           |
| `timestamp` | DateTime          | Message timestamp                           |
| `source`    | String (nullable) | Answer source: `"mcp"`, `"pdf"`, or `"llm"` |

### Documents Table

| Column        | Type         | Description                     |
| ------------- | ------------ | ------------------------------- |
| `id`          | Integer (PK) | Auto-increment ID               |
| `filename`    | String       | PDF file name                   |
| `file_path`   | String       | Full path to file               |
| `chunk_count` | Integer      | Number of vector chunks created |
| `ingested_at` | DateTime     | Ingestion timestamp             |

---

## API Endpoints

| Method                   | Path                  | Description                                    |
| ------------------------ | --------------------- | ---------------------------------------------- |
| `GET /`                  | Health check          | Returns initialization status, component info  |
| `GET /status`            | Detailed status       | Users, messages, documents, MCP servers, tools |
| `POST /ingest`           | Trigger PDF ingestion | Re-processes all PDFs in the pdfs/ directory   |
| `POST /webhook/greenapi` | GreenAPI webhook      | Receives incoming WhatsApp messages            |

### Health Check Response

```json
{
  "status": "running",
  "initialized": true,
  "pdf_rag": "ready",
  "mcp_servers": 1,
  "mcp_tools": 7
}
```

---

## Data Flow Examples

### Example 1: Customer asks for the menu

```
👤 Customer: "وش عندكم في القائمة؟"

🤖 Pipeline:
   ① LLM selects MCP tool → get_full_menu (no arguments needed)
   ② MCP server returns formatted menu
   ③ Agent sends pre-formatted result directly

💬 Response:
   "🍽️ قائمة مطعم أبو طبق
    ──────────────
    🥗 مقبلات
    • حمص بالطحينة     12 ر.س  ⭐
    • فتوش             10 ر.س
    ..."
```

### Example 2: Customer asks about a specific dish

```
👤 Customer: "كم سعرات الكبسة؟"

🤖 Pipeline:
   ① LLM selects → get_dish_details {"dish_name": "كبسة"}
   ② MCP returns full dish card with calories, ingredients, allergens
   ③ Agent sends formatted details

💬 Response:
   "🍗 كبسة دجاج
    💰 45 ر.س  |  🔥 520 سعرة
    📝 أرز بسمتي مع دجاج متبل...
    ⚠️ مسببات الحساسية: مكسرات
    💡 هل تعلم؟ الكبسة أصلها من نجد..."
```

### Example 3: Customer sends a PDF

```
👤 Customer: [Sends catering_menu.pdf]

🤖 Pipeline:
   ① WhatsApp handler detects PDF attachment
   ② Downloads file via GreenAPI media endpoint
   ③ pdf_rag.add_pdf() ingests into ChromaDB
   ④ Confirms ingestion to user

💬 Response: "✅ تم إضافة الملف بنجاح! يمكنني الآن الإجابة عن أسئلتك منه."

👤 Customer (later): "وش أسعار البوفيه في الملف اللي رسلته؟"

🤖 Pipeline:
   ① MCP tools → no match (not menu data)
   ② PDF RAG → similarity search finds catering pricing chunks
   ③ LLM summarizes chunks with Abu Tabaq personality

💬 Response: "البوفيه عندنا يبدأ من 75 ر.س للشخص..."
```

---

## Makefile Commands

| Command          | Description                                             |
| ---------------- | ------------------------------------------------------- |
| `make install`   | Create virtual environment and install all dependencies |
| `make env`       | Copy `.env.example` to `.env`                           |
| `make dev`       | Start server with `DEBUG=true` (hot-reload enabled)     |
| `make start`     | Start server with `DEBUG=false` (production mode)       |
| `make tunnel`    | Expose port 8000 to the internet via ngrok              |
| `make health`    | Run health check against `GET /`                        |
| `make test-menu` | Simulate a WhatsApp "show me the menu" message          |
| `make test-mcp`  | Run the MCP server standalone for testing               |
| `make kill`      | Kill any process running on port 8000                   |
| `make reset-db`  | Delete the SQLite database                              |
| `make reset-rag` | Delete the ChromaDB vector store                        |
| `make reset`     | Full reset (database + vector store + cache)            |

---

## Customization Guide

### Changing the Restaurant Data

Edit `data/restaurant_menu.json` to modify:

- **Restaurant info:** Name, phone, hours, delivery time
- **Categories:** Add or rename food categories
- **Dishes:** Add dishes with full metadata (price, calories, allergens, etc.)
- **Daily specials:** Change per-day discount offers
- **Recommendations:** Update curated lists for each preference type

### Switching LLM Provider

In your `.env` file:

```bash
# Use Anthropic Claude
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...

# Or use OpenAI GPT
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
```

### Adding New MCP Servers

1. Create a new MCP server file (e.g., `mcp_servers/delivery_mcp.py`)
2. Register it in `mcp_servers/mcp_config.json`:

```json
{
  "mcpServers": {
    "restaurant": { ... },
    "delivery": {
      "command": "python",
      "args": ["mcp_servers/delivery_mcp.py"],
      "description": "Delivery tracking tools",
      "enabled": true
    }
  }
}
```

3. Restart the server — the new tools are automatically discovered and available to the LLM.

### Customizing the Agent Personality

Edit the system prompt in `app/agent.py` (the `_build_system_prompt` method). The current personality is an enthusiastic Saudi waiter who:

- Speaks in a blend of Arabic Fus-ha with Saudi warmth
- Uses WhatsApp formatting (bold, bullets, emojis)
- Keeps responses short and fun
- Never over-explains

### Using PostgreSQL Instead of SQLite

Update `DATABASE_URL` in `.env`:

```bash
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/restaurant_bot
```

Install the async PostgreSQL driver:

```bash
pip install asyncpg
```

---

<div align="center">

**Built with ❤️ for Abu Tabaq Restaurant**

</div>
