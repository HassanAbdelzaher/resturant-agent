"""
WhatsApp AI Agent — Main Entry Point (GreenAPI)

Starts a FastAPI server with:
  - GreenAPI webhook endpoint  (POST /webhook/greenapi)
  - Restaurant MCP pipeline    (menu, prices, recommendations)
  - PDF RAG pipeline           (supplementary documents)
  - Database layer             (conversation history, user tracking)

Usage:
    python main.py

    Or with uvicorn:
    uvicorn main:fastapi_app --host 0.0.0.0 --port 8000 --reload

GreenAPI setup (one-time):
    1. Create a free instance at https://green-api.com
    2. Copy idInstance  → GREENAPI_ID_INSTANCE in .env
    3. Copy apiTokenInstance → GREENAPI_API_TOKEN in .env
    4. In the instance settings set Webhook URL to:
         https://<your-public-host>/webhook/greenapi
    5. Enable "Incoming messages" notifications
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.agent import WhatsAppAgent
from app.whatsapp_handler import register_handlers

# ── Logging ───────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ── Global Agent Instance ─────────────────────────────────────────
agent = WhatsAppAgent()


# ── FastAPI Lifespan ──────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting WhatsApp Restaurant Agent (GreenAPI)...")
    await agent.initialize()
    yield
    logger.info("Shutting down...")
    await agent.shutdown()


# ── FastAPI App ───────────────────────────────────────────────────
fastapi_app = FastAPI(
    title="مطعم أبو طبق — WhatsApp Agent",
    description="Restaurant WhatsApp bot powered by GreenAPI, MCP, PDF RAG, and LLM",
    version="2.0.0",
    lifespan=lifespan,
)

# Register GreenAPI webhook + all message handlers
register_handlers(fastapi_app, agent)


# ── Health Check ──────────────────────────────────────────────────
@fastapi_app.get("/")
async def health_check():
    return {
        "status": "running",
        "provider": "greenapi",
        "instance": settings.greenapi_id_instance or "⚠️ not configured",
        "agent_initialized": agent.initialized,
        "pdf_rag_active": agent.rag_pipeline.qa_chain is not None,
        "mcp_servers": agent.mcp.connected_count,
        "mcp_tools": agent.mcp.total_tools,
    }


@fastapi_app.get("/status")
async def status():
    stats = await agent.db.get_stats()
    return {
        "agent": {
            "initialized": agent.initialized,
            "llm_provider": settings.llm_provider,
        },
        "greenapi": {
            "id_instance": settings.greenapi_id_instance,
            "webhook_url": "POST /webhook/greenapi",
        },
        "pdf_rag": {
            "active": agent.rag_pipeline.qa_chain is not None,
            "pdf_directory": settings.pdf_directory,
        },
        "database": stats,
        "mcp": agent.mcp.get_status(),
    }


# ── Manual PDF Re-ingestion ───────────────────────────────────────
@fastapi_app.post("/ingest")
async def ingest_pdfs():
    count = agent.rag_pipeline.ingest()
    if count > 0:
        agent.rag_pipeline.build_qa_chain(agent.llm)
    return {"status": "ok", "chunks_indexed": count}


# ── Run ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:fastapi_app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.debug,
    )
