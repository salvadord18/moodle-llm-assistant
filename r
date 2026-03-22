"""
FastAPI RAG Server for Moodle
------------------------------

Endpoints:
- POST /ask
Receives:
{
    "question": "...",
    "courseid": 5,        # 0 means global chat
    "userid": 12
}

Returns:
{
    "answer": "...",
    "sources": ["Lecture3.pdf", "Lecture2.pdf"]
}

This service:
1) Embeds user question
2) Retrieves relevant chunks from ChromaDB
3) Builds context
4) Sends prompt to Ollama
5) Returns final answer
"""

from fastapi import FastAPI
from pydantic import BaseModel
from chromadb import PersistentClient
import requests

# -------------------------
# CONFIG
# -------------------------

CHROMA_DB_PATH = "/rag_vectordb"

OLLAMA_URL = "http://host.docker.internal:11434/api/generate"
EMBED_MODEL = "nomic-embed-text"
LLM_MODEL = "llama3.2"

client = PersistentClient(path=CHROMA_DB_PATH)

app = FastAPI()


# -------------------------
# REQUEST SCHEMA
# -------------------------

class Query(BaseModel):
    question: str
    courseid: int   # 0 = global chat
    userid: int


# -------------------------
# EMBEDDING FUNCTION
# -------------------------

def embed(text: str):
    """Get embedding vector from Ollama."""
    r = requests.post(
        "http://host.docker.internal:11434/api/embed",
        json={"model": EMBED_MODEL, "input": text}
    )
    return r.json()["embeddings"][0]


# -------------------------
# ASK ENDPOINT
# -------------------------

@app.post("/ask")
def ask(data: Query):

    # Select collection
    if data.courseid == 0:
        collection_name = "global_docs"
    else:
        collection_name = f"course_docs_{data.courseid}"

    collection = client.get_collection(collection_name)

    # Embed question
    q_emb = embed(data.question)

    # Retrieve top 5 chunks
    results = collection.query(
        query_embeddings=[q_emb],
        n_results=5
    )

    documents = results["documents"][0]
    sources = results["metadatas"][0] if "metadatas" in results else []

    # Build RAG context
    context = "\n\n".join(documents)

    prompt = f"""
You are an AI tutor. Answer using ONLY the following context.

CONTEXT:
{context}

QUESTION:
{data.question}

Your answer must be accurate and based on the provided context.
"""

    # Send final prompt to Ollama
    r = requests.post(
        OLLAMA_URL,
        json={
            "model": LLM_MODEL,
            "prompt": prompt,
            "stream": False
        }
    )

    answer = r.json()["response"]

    return {
        "answer": answer,
        "sources": sources
    }