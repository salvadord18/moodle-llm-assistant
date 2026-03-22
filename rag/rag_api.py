"""
Improved FastAPI RAG Server for Moodle
--------------------------------------

This service:
1) Embeds user question
2) Retrieves relevant chunks from ChromaDB (documents + metadata)
3) Builds a clean context
4) Sends a strong RAG prompt to Ollama
5) Returns answer + PDF sources
"""

from fastapi import FastAPI
from pydantic import BaseModel
from chromadb import PersistentClient
import requests

# ----------------------------------------------------
# CONFIG
# ----------------------------------------------------
CHROMA_DB_PATH = "/rag_vectordb"
OLLAMA_EMBED_URL = "http://host.docker.internal:11434/api/embed"
OLLAMA_GEN_URL = "http://host.docker.internal:11434/api/generate"

EMBED_MODEL = "nomic-embed-text"
LLM_MODEL = "llama3.2"

client = PersistentClient(path=CHROMA_DB_PATH)
app = FastAPI()

# ----------------------------------------------------
# REQUEST
# ----------------------------------------------------
class Query(BaseModel):
    question: str
    courseid: int
    userid: int

# ----------------------------------------------------
# EMBEDDING
# ----------------------------------------------------
def embed(text: str):
    r = requests.post(
        OLLAMA_EMBED_URL,
        json={"model": EMBED_MODEL, "input": text}
    )
    return r.json()["embeddings"][0]

# ----------------------------------------------------
# ASK ENDPOINT
# ----------------------------------------------------
@app.post("/ask")
def ask(data: Query):

    collection_name = f"course_docs_{data.courseid}"
    collection = client.get_collection(collection_name)

    q_emb = embed(data.question)

    results = collection.query(
        query_embeddings=[q_emb],
        n_results=5,
        include=["documents", "metadatas"]
    )

    docs = results["documents"][0]
    metas = results["metadatas"][0]

    # Build context
    context = ""
    for doc, meta in zip(docs, metas):
        src = meta.get("source", "unknown.pdf")
        context += f"[SOURCE: {src}]\n{doc}\n\n"

    # Strong anti‑hallucination prompt
    prompt = f"""
You are an AI assistant for university students.

You MUST answer strictly using ONLY the information found in the context below.
If the answer is not present in the context, reply:
"The provided PDFs do not contain this information."

CONTEXT:
{context}

QUESTION:
{data.question}

ANSWER (based ONLY on the context above):
"""

    r = requests.post(
        OLLAMA_GEN_URL,
        json={"model": LLM_MODEL, "prompt": prompt, "stream": False}
    )

    answer = r.json()["response"]
    sources = [m.get("source") for m in metas]

    return {
        "answer": answer,
        "sources": sources
    }