"""
Moodle RAG API — Generic RAG (No Per-Question Handlers)
--------------------------------------------------------

Design:
- One single RAG pipeline for ALL questions:
  Retrieve -> Build Context -> Generate
- Uses Chroma local embeddings via query_texts (no Ollama /api/embed) 
- Loads system/style prompts from .txt files
- Uses a distance threshold to decide whether context is relevant (cosine distance: closer to 0 = more similar) 
- Always returns JSON (never breaks UI)

Run:
  cd /var/www/html/blocks/llmassistant/rag
  uvicorn rag_api:app --host 0.0.0.0 --port 8001
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from chromadb import PersistentClient
import os
import requests
import time

CHROMA_DB_PATH = "/var/www/moodledata/chroma_db"
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
OLLAMA_GEN_URL = f"{OLLAMA_BASE_URL}/api/generate"
LLM_MODEL = os.getenv("OLLAMA_LLM_MODEL", "llama3.2")

PROMPTS_DIR = os.getenv("LLMASSISTANT_PROMPTS_DIR", "/var/www/html/blocks/llmassistant/rag/prompts")
SYSTEM_COURSE_FILE = "system_course.txt"
SYSTEM_GLOBAL_FILE = "system_global.txt"
STYLE_FILE = "style.txt"

TOP_K = int(os.getenv("LLMASSISTANT_TOP_K", "12"))

# Cosine distance threshold: smaller is better. Tune as needed.
# If min distance is higher than this, we treat it as "no relevant context".
DISTANCE_THRESHOLD = float(os.getenv("LLMASSISTANT_DISTANCE_THRESHOLD", "0.45"))

client = PersistentClient(path=CHROMA_DB_PATH)
app = FastAPI()
_session = requests.Session()

class Query(BaseModel):
    question: str
    courseid: int
    userid: int

def load_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""

def build_system_prompt(courseid: int) -> str:
    style = load_text(os.path.join(PROMPTS_DIR, STYLE_FILE))
    system = load_text(os.path.join(PROMPTS_DIR, SYSTEM_GLOBAL_FILE if courseid == 0 else SYSTEM_COURSE_FILE))
    parts = [p for p in [system, style] if p]
    return "\n\n".join(parts).strip()

def ollama_generate(prompt: str) -> str:
    payload = {"model": LLM_MODEL, "prompt": prompt, "stream": False}
    headers = {"Connection": "close"}
    last_err = None

    for attempt in range(4):
        try:
            r = _session.post(OLLAMA_GEN_URL, json=payload, headers=headers, timeout=(5, 120))
            r.raise_for_status()
            return r.json().get("response", "")
        except Exception as e:
            last_err = e
            time.sleep(min(2.0, 0.2 * (2 ** attempt)))

    raise RuntimeError(f"Ollama generate failed: {last_err}")

@app.post("/ask")
def ask(data: Query):
    q = (data.question or "").strip()
    if not q:
        return {"answer": "Please enter a question.", "sources": []}

    collection_name = "global_docs" if data.courseid == 0 else f"course_docs_{data.courseid}"

    try:
        collection = client.get_collection(collection_name)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Collection not found: {collection_name} ({e})")

    # Retrieve using query_texts (Chroma embeds query using the collection embedding function) 
    try:
        results = collection.query(
            query_texts=[q],
            n_results=TOP_K,
            include=["documents", "metadatas", "distances"]
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Chroma query failed: {e}")

    docs = results["documents"][0]
    metas = results["metadatas"][0]
    distances = results.get("distances", [[None]])[0]

    # Decide whether context is relevant using the best (minimum) cosine distance 
    min_dist = None
    if distances and distances[0] is not None:
        min_dist = min(distances)

    sources = []
    for m in metas:
        if m and m.get("source"):
            sources.append(m["source"])
    sources = list(dict.fromkeys(sources))

    # Build context only if we have relevant results
    if not docs or (min_dist is not None and min_dist > DISTANCE_THRESHOLD):
        # No relevant context -> respond strictly per RAG rule
        return {
            "answer": "The provided PDFs do not contain this information.",
            "sources": sources
        }

    context = ""
    for doc, meta in zip(docs, metas):
        src = meta.get("source", "unknown.pdf") if meta else "unknown.pdf"
        context += f"[SOURCE: {src}]\n{doc}\n\n"

    system_prompt = build_system_prompt(data.courseid)
    if not system_prompt:
        system_prompt = (
            "You MUST answer using ONLY the provided CONTEXT.\n"
            "If the answer is not explicitly present, reply:\n"
            "\"The provided PDFs do not contain this information.\""
        )

    prompt = f"""{system_prompt}

CONTEXT:
{context}

QUESTION:
{q}

ANSWER:
"""

    try:
        answer = ollama_generate(prompt)
    except Exception:
        # Always return JSON; never break the UI
        return {"answer": "Error: assistant backend temporarily unavailable. Please try again.", "sources": sources}

    return {"answer": answer, "sources": sources}
