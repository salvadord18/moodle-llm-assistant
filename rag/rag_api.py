"""
RAG API for Moodle - Advanced Retrieval + Context Handling
--------------------------------------------------------------

Features:
- n_results = 10
- include metadata + documents
- boosted retrieval for teacher queries
- strong anti-hallucination prompt
"""

from fastapi import FastAPI
from pydantic import BaseModel
from chromadb import PersistentClient
import requests
import re

CHROMA_DB_PATH = "/rag_vectordb"
EMBED_MODEL = "nomic-embed-text"
LLM_MODEL = "llama3.2"

client = PersistentClient(path=CHROMA_DB_PATH)
app = FastAPI()

class Query(BaseModel):
    question: str
    courseid: int
    userid: int

def embed(text: str):
    r = requests.post(
        "http://host.docker.internal:11434/api/embed",
        json={"model": EMBED_MODEL, "input": text}
    )
    
    data = r.json()
    
    # Debug print
    print("[EMBED RESPONSE]", data)
    
    # New models: "embeddings": [[...]]
    if "embeddings" in data:
        return data["embeddings"][0]
    
    # Older models: "embedding": [...]
    if "embedding" in data:
        return data["embedding"]
    
    # Error case: Ollama returned an error
    raise ValueError(f"Ollama embed error: {data}")

@app.post("/ask")
def ask(data: Query):

    collection_name = f"course_docs_{data.courseid}"
    collection = client.get_collection(collection_name)

    q_emb = embed(data.question.lower())

    # Boost when question is about teachers
    teacher_keywords = ["teacher", "lecturer", "instructor", "professor", "email"]
    boost = any(k in data.question.lower() for k in teacher_keywords)

    n_results = 15 if boost else 10

    results = collection.query(
        query_embeddings=[q_emb],
        n_results=n_results,
        include=["documents", "metadatas"]
    )

    docs = results["documents"][0]
    metas = results["metadatas"][0]

    # Build context
    context = ""
    for doc, meta in zip(docs, metas):
        src = meta.get("source", "unknown.pdf") if meta else "unknown.pdf"
        context += f"[SOURCE: {src}]\n{doc}\n\n"

    # Anti hallucination
    prompt = f"""
You are an AI assistant for university students.

Answer ONLY using information found in the CONTEXT below.
If the answer is not in the context, reply:
"The provided PDFs do not contain this information."

CONTEXT:
{context}

QUESTION:
{data.question}

ANSWER (based ONLY on the context):
"""

    r = requests.post(
        "http://host.docker.internal:11434/api/generate",
        json={"model": LLM_MODEL, "prompt": prompt, "stream": False}
    )

    answer = r.json()["response"]
    sources = [m.get("source") if m else "unknown.pdf" for m in metas]

    return {
        "answer": answer,
        "sources": sources
    }
