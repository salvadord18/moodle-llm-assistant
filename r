from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from chromadb import PersistentClient
import requests
import re
import os
from typing import List, Tuple

CHROMA_DB_PATH = "/var/www/moodledata/chroma_db"
EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
LLM_MODEL = os.getenv("OLLAMA_LLM_MODEL", "llama3.2")

# Preferir base URL configurável:
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
OLLAMA_EMBED_URL = f"{OLLAMA_BASE_URL}/api/embed"
OLLAMA_GEN_URL = f"{OLLAMA_BASE_URL}/api/generate"

client = PersistentClient(path=CHROMA_DB_PATH)
app = FastAPI()

class Query(BaseModel):
    question: str
    courseid: int
    userid: int

def embed(text: str) -> List[float]:
    """Call Ollama /api/embed with retry + timeouts; returns one embedding vector."""
    payload = {"model": EMBED_MODEL, "input": text}

    last_err = None
    for _ in range(3):
        try:
            r = requests.post(OLLAMA_EMBED_URL, json=payload, timeout=(5, 60))
            r.raise_for_status()
            data = r.json()
            # /api/embed returns {"embeddings": [[...], ...]}
            return data["embeddings"][0]
        except Exception as e:
            last_err = e

    raise RuntimeError(f"Ollama embed failed after retries: {last_err}")

def is_teacher_question(q: str) -> bool:
    q = q.lower()
    keywords = [
        "teacher", "teachers", "lecturer", "instructor", "professor",
        "docente", "docentes", "labs", "theoretical"
    ]
    return any(k in q for k in keywords)

def extract_lecturers_from_text(text: str) -> Tuple[List[str], List[str]]:
    """Extract lecturer lines + emails deterministically from context text."""
    patterns = [
        r"(Lecturer\s*\(Theoretical\)\s*:\s*.*?)(?=\s*Email:|$)",
        r"(Lecturer\s*\(Labs\)\s*:\s*.*?)(?=\s*Email:|$)",
        r"(Lecturer\s*:\s*.*?)(?=\s*Email:|$)",
    ]

    lecturer_lines = []
    for pat in patterns:
        for m in re.finditer(pat, text, flags=re.IGNORECASE):
            lecturer_lines.append(m.group(1).strip()[:180])

    email_lines = []
    for m in re.finditer(r"Email:\s*([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})", text, flags=re.IGNORECASE):
        email_lines.append("Email: " + m.group(1))

    def uniq(seq):
        seen = set()
        out = []
        for x in seq:
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out

    return uniq(lecturer_lines), uniq(email_lines)

@app.post("/ask")
def ask(data: Query):
    collection_name = f"course_docs_{data.courseid}"

    try:
        collection = client.get_collection(collection_name)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Collection not found: {collection_name} ({e})")

    q = data.question.strip()
    teacher = is_teacher_question(q)

    # embedding
    try:
        q_emb = embed(q.lower())
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Embedding failed: {e}")

    # semantic retrieval
    sem_results = collection.query(
        query_embeddings=[q_emb],
        n_results=15,
        include=["documents", "metadatas"],
    )
    sem_docs = sem_results["documents"][0]
    sem_metas = sem_results["metadatas"][0]

    # teacher-aware lexical filter
    lex_docs, lex_metas = [], []
    if teacher:
        lex_results = collection.query(
            query_embeddings=[q_emb],
            n_results=15,
            include=["documents", "metadatas"],
            where_document={"$contains": "Lecturer"},
        )
        lex_docs = lex_results["documents"][0]
        lex_metas = lex_results["metadatas"][0]

    docs = lex_docs + sem_docs
    metas = lex_metas + sem_metas

    # prioritize a specific source if needed
    if teacher and docs and metas:
        zipped = list(zip(docs, metas))
        zipped.sort(key=lambda dm: 0 if (dm[1] and dm[1].get("source") == "Lecture1.pdf") else 1)
        docs, metas = zip(*zipped)

    # build context
    context = ""
    for doc, meta in zip(docs, metas):
        src = meta.get("source", "unknown.pdf") if meta else "unknown.pdf"
        context += f"[SOURCE: {src}]\n{doc}\n\n"

    # deterministic teacher extraction
    if teacher:
        lecturer_lines, email_lines = extract_lecturers_from_text(context)
        if lecturer_lines or email_lines:
            answer_lines = ["Teachers:"]
            theoretical = [l for l in lecturer_lines if "theoretical" in l.lower()]
            labs = [l for l in lecturer_lines if "labs" in l.lower()]
            generic = [l for l in lecturer_lines if l not in theoretical and l not in labs]

            if theoretical:
                answer_lines += ["", "Theoretical:"] + [f"- {l}" for l in theoretical]
            if labs:
                answer_lines += ["", "Labs:"] + [f"- {l}" for l in labs]
            if generic:
                answer_lines += ["", "Other lecturer lines:"] + [f"- {l}" for l in generic]
            if email_lines:
                answer_lines += ["", "Emails:"] + [f"- {e}" for e in email_lines]

            sources = [m.get("source") for m in metas if m and m.get("source")]
            sources = list(dict.fromkeys(sources))
            return {"answer": "\n".join(answer_lines), "sources": sources}

        # fallback LLM (still constrained)
        prompt = f"""
You MUST answer using ONLY the context below.
If the context does not explicitly contain the lecturers/teachers, reply:
"The provided PDFs do not contain this information."

CONTEXT:
{context}

QUESTION:
{q}

ANSWER:
"""
        r = requests.post(OLLAMA_GEN_URL, json={"model": LLM_MODEL, "prompt": prompt, "stream": False}, timeout=(5, 120))
        r.raise_for_status()
        return {"answer": r.json().get("response", ""), "sources": [m.get("source", "unknown.pdf") if m else "unknown.pdf" for m in metas]}

    # non-teacher question
    prompt = f"""
Answer ONLY using the context below.
If the answer is not present, reply:
"The provided PDFs do not contain this information."

CONTEXT:
{context}

QUESTION:
{q}

ANSWER:
"""
    r = requests.post(OLLAMA_GEN_URL, json={"model": LLM_MODEL, "prompt": prompt, "stream": False}, timeout=(5, 120))
    r.raise_for_status()

    sources = [m.get("source", "unknown.pdf") if m else "unknown.pdf" for m in metas]
    sources = list(dict.fromkeys(sources))
    return {"answer": r.json().get("response", ""), "sources": sources}
