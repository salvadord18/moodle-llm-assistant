import os
import chromadb
from chromadb.config import Settings
from fastapi import FastAPI
from pydantic import BaseModel
import uvicorn
import fitz  # PyMuPDF for PDF
import requests

OLLAMA_URL = "http://localhost:11434/api/generate"
CHROMA_DB_PATH = "./vectordb"

# FastAPI app
app = FastAPI()

# Chroma client
chroma_client = chromadb.Client(Settings(chroma_db_impl="duckdb+parquet",
                                        persist_directory=CHROMA_DB_PATH))

collection = chroma_client.get_or_create_collection("course_docs", metadata={"hnsw:space": "cosine"})


# MODEL FOR REQUEST
class Question(BaseModel):
    question: str


def embed_text(text: str):
    """Get embeddings from Ollama."""
    r = requests.post(
        "http://localhost:11434/api/embed",
        json={"model": "llama3.2", "input": text}
    )
    return r.json()["embedding"]


def rag_query(question: str):
    q_emb = embed_text(question)

    # Retrieve top 3
    results = collection.query(
        query_embeddings=[q_emb],
        n_results=3
    )

    retrieved_text = "\n\n".join([t for t in results["documents"][0]])

    # Send to Ollama with context
    prompt = f"""You are a course assistant.  
Use ONLY the following context to answer the question.

Context:
{retrieved_text}

Question: {question}

Answer:"""

    r = requests.post(OLLAMA_URL, json={
        "model": "llama3.2",
        "prompt": prompt,
        "stream": False
    })

    return r.json()["response"]


@app.post("/ask")
def ask(data: Question):
    try:
        answer = rag_query(data.question)
        return {"answer": answer}
    except Exception as e:
        return {"error": str(e)}


@app.post("/ingest")
def ingest_pdf(path: str):
    """Ingest text from a PDF file path"""
    doc = fitz.open(path)
    all_text = ""

    for page in doc:
        all_text += page.get_text()

    # Chunk text
    chunks = [all_text[i:i+500] for i in range(0, len(all_text), 500)]

    embeddings = [embed_text(c) for c in chunks]

    collection.add(
        documents=chunks,
        ids=[f"chunk_{i}" for i in range(len(chunks))],
        embeddings=embeddings
    )

    chroma_client.persist()

    return {"status": "ok", "chunks": len(chunks)}


uvicorn.run(app, host="0.0.0.0", port=8001)