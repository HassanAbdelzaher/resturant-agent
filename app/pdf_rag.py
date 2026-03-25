"""
PDF RAG Pipeline — Ingests PDFs, creates embeddings, and answers questions.

Architecture:
  1. Load PDFs from a directory
  2. Split into chunks
  3. Generate embeddings (sentence-transformers, runs locally — no API cost)
  4. Store in ChromaDB (persistent, file-based vector store)
  5. Query with semantic search + LLM for answers
"""

import os
import logging
from pathlib import Path
from typing import Optional

import chromadb
from chromadb.config import Settings as ChromaSettings

from langchain_text_splitters.character import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import PyPDFLoader, DirectoryLoader
from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnableParallel, RunnablePassthrough

from app.config import settings

logger = logging.getLogger(__name__)


# ── Prompt template for the Q&A chain ──────────────────────────────
QA_PROMPT = PromptTemplate(
    template="""You are a helpful WhatsApp assistant. Use the following context
from PDF documents to answer the user's question. If the answer is not in the
context, say "I don't have that information in my documents."

Context:
{context}

Question: {question}

Answer in a clear, concise way suitable for a WhatsApp message (keep it short):""",
    input_variables=["context", "question"],
)


def _format_docs(docs) -> str:
    return "\n\n".join(doc.page_content for doc in docs)


class PDFRagPipeline:
    """Manages the full PDF → Embeddings → Q&A pipeline."""

    def __init__(
        self,
        pdf_dir: str = None,
        persist_dir: str = None,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
    ):
        self.pdf_dir = pdf_dir or settings.pdf_directory
        self.persist_dir = persist_dir or settings.chroma_persist_dir
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

        # Use a local embedding model (free, no API key needed)
        self.embeddings = HuggingFaceEmbeddings(
            model_name="all-MiniLM-L6-v2",
            model_kwargs={"device": "cpu"},
        )

        self.vectorstore: Optional[Chroma] = None
        self.qa_chain = None

    # ── PDF Loading ────────────────────────────────────────────────
    def load_pdfs(self) -> list:
        """Load all PDFs from the configured directory."""
        pdf_path = Path(self.pdf_dir)
        if not pdf_path.exists():
            pdf_path.mkdir(parents=True, exist_ok=True)
            logger.warning(f"Created empty PDF directory: {self.pdf_dir}")
            return []

        loader = DirectoryLoader(
            str(pdf_path),
            glob="**/*.pdf",
            loader_cls=PyPDFLoader,
            show_progress=True,
        )
        documents = loader.load()
        logger.info(f"Loaded {len(documents)} pages from PDFs")
        return documents

    # ── Chunking ───────────────────────────────────────────────────
    def split_documents(self, documents: list) -> list:
        """Split documents into smaller chunks for embedding."""
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n", "\n", ". ", " ", ""],
        )
        chunks = splitter.split_documents(documents)
        logger.info(f"Split into {len(chunks)} chunks")
        return chunks

    # ── Indexing ───────────────────────────────────────────────────
    def create_vectorstore(self, chunks: list) -> Chroma:
        """Create or update the ChromaDB vector store."""
        os.makedirs(self.persist_dir, exist_ok=True)

        self.vectorstore = Chroma.from_documents(
            documents=chunks,
            embedding=self.embeddings,
            persist_directory=self.persist_dir,
            collection_name="pdf_documents",
        )
        logger.info("Vector store created/updated successfully")
        return self.vectorstore

    def load_existing_vectorstore(self) -> Optional[Chroma]:
        """Load an existing vector store from disk."""
        if not os.path.exists(self.persist_dir):
            return None

        self.vectorstore = Chroma(
            persist_directory=self.persist_dir,
            embedding_function=self.embeddings,
            collection_name="pdf_documents",
        )
        count = self.vectorstore._collection.count()
        if count == 0:
            return None

        logger.info(f"Loaded existing vector store with {count} chunks")
        return self.vectorstore

    # ── Full Ingestion Pipeline ────────────────────────────────────
    def ingest(self) -> int:
        """Run the full PDF ingestion pipeline. Returns chunk count."""
        documents = self.load_pdfs()
        if not documents:
            logger.warning("No PDFs found to ingest")
            return 0

        chunks = self.split_documents(documents)
        self.create_vectorstore(chunks)
        return len(chunks)

    # ── Query / Q&A ───────────────────────────────────────────────
    def build_qa_chain(self, llm):
        """Build the LCEL RAG chain with the given LLM."""
        if not self.vectorstore:
            self.load_existing_vectorstore()

        if not self.vectorstore:
            raise ValueError(
                "No vector store available. Run ingest() first or add PDFs."
            )

        retriever = self.vectorstore.as_retriever(
            search_type="similarity",
            search_kwargs={"k": 4},
        )

        # LCEL chain: retrieve → format → prompt → LLM → parse
        self.qa_chain = (
            RunnableParallel(
                context=(retriever | _format_docs),
                question=RunnablePassthrough(),
            )
            | QA_PROMPT
            | llm
            | StrOutputParser()
        )
        # Attach retriever so we can get source docs in query()
        self._retriever = retriever
        return self.qa_chain

    async def query(self, question: str) -> dict:
        """
        Ask a question against the PDF knowledge base.

        Returns:
            {"answer": str, "sources": list[str]}
        """
        if not self.qa_chain:
            raise ValueError("QA chain not built. Call build_qa_chain() first.")

        answer = await self.qa_chain.ainvoke(question)

        # Fetch source documents separately
        sources: list[str] = []
        if hasattr(self, "_retriever"):
            try:
                docs = await self._retriever.ainvoke(question)
                sources = list({
                    doc.metadata.get("source", "unknown") for doc in docs
                })
            except Exception:
                pass

        return {"answer": answer, "sources": sources}

    # ── Add a single PDF on-the-fly ───────────────────────────────
    def add_pdf(self, pdf_path: str) -> int:
        """Add a single PDF to the existing vector store."""
        loader = PyPDFLoader(pdf_path)
        documents = loader.load()
        chunks = self.split_documents(documents)

        if self.vectorstore:
            self.vectorstore.add_documents(chunks)
        else:
            self.create_vectorstore(chunks)

        logger.info(f"Added {len(chunks)} chunks from {pdf_path}")
        return len(chunks)
