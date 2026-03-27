"""
Moodle RAG API (Stable) — Chroma Local Embeddings + Ollama Generate
-------------------------------------------------------------------

Key design:
- NO Ollama /api/embed (removes RemoteDisconnected issues)
- Uses Chroma's collection embedding function via query_texts
- Uses Ollama only for /api/generate (LLM response)

Endpoints:
- POST /ask
  body: {"question": "...", "courseid": 2, "userid": 1}

Returns:
- {"answer": "...", "sources": ["Lecture1.pdf", ...]}

Run inside Moodle 'webserver' container:
  cd /var/www/html/blocks/llmassistant/rag
  uvicorn rag_api:app --host 0.0.0.0 --port 8001
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from chromadb import PersistentClient
import os
import re
import requests
from typing import List, Tuple

# -----------------------------
# CONFIG
# -----------------------------
CHROMA_DB_PATH = "/var/www/moodledata/chroma_db"

LLM_MODEL = os.getenv("OLLAMA_LLM_MODEL", "llama3.2")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
OLLAMA_GEN_URL = f"{OLLAMA_BASE_URL}/api/generate"

client = PersistentClient(path=CHROMA_DB_PATH)
app = FastAPI()


class Query(BaseModel):
    question: str
    courseid: int
    userid: int


# -----------------------------
# TEACHER MODE (DETERMINISTIC EXTRACTION)
# -----------------------------
def is_teacher_question(q: str) -> bool:
    q = q.lower()
    keywords = [
        "teacher", "teachers", "lecturer", "instructor", "professor",
        "docente", "docentes", "labs", "theoretical"
    ]
    return any(k in q for k in keywords)


def extract_lecturers_from_text(text: str) -> Tuple[List[str], List[str]]:
    """
    Extract lecturer lines + emails deterministically from context text.
    Avoid hallucinations by parsing explicit lines.
    """
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
    for m in re.finditer(
        r"Email:\s*([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})",
        text,
        flags=re.IGNORECASE
    ):
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


# -----------------------------
# MAIN ENDPOINT
# -----------------------------
@app.post("/ask")
def ask(data: Query):
    collection_name = f"course_docs_{data.courseid}"

    try:
        collection = client.get_collection(collection_name)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Collection not found: {collection_name} ({e})")

    q = (data.question or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="Empty question")

    teacher = is_teacher_question(q)

    # -----------------------------
    # 1) Retrieval (Chroma local embeddings via query_texts)
    # -----------------------------
    try:
        sem_results = collection.query(
            query_texts=[q],
            n_results=15,
            include=["documents", "metadatas"],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Chroma query failed: {e}")

    sem_docs = sem_results["documents"][0]
    sem_metas = sem_results["metadatas"][0]

    # Teacher lexical boost: filter chunks containing "Lecturer"
    lex_docs, lex_metas = [], []
    if teacher:
        try:
            lex_results = collection.query(
                query_texts=[q],
                n_results=15,
                include=["documents", "metadatas"],
                where_document={"$contains": "Lecturer"},
            )
            lex_docs = lex_results["documents"][0]
            lex_metas = lex_results["metadatas"][0]
        except Exception:
            # If lexical query fails, ignore and continue with semantic results.
            pass

    docs = lex_docs + sem_docs
    metas = lex_metas + sem_metas

    # Prioritize Lecture1.pdf when teacher question
    if teacher and docs and metas:
        zipped = list(zip(docs, metas))
        zipped.sort(key=lambda dm: 0 if (dm[1] and dm[1].get("source") == "Lecture1.pdf") else 1)
        docs, metas = zip(*zipped)

    # Build context text
    context = ""
    for doc, meta in zip(docs, metas):
        src = meta.get("source", "unknown.pdf") if meta else "unknown.pdf"
        context += f"[SOURCE: {src}]\n{doc}\n\n"

    # -----------------------------
    # 2) Deterministic answer for teacher questions
    # -----------------------------
    if teacher:
        lecturer_lines, email_lines = extract_lecturers_from_text(context)
        if lecturer_lines or email_lines:
            theoretical = [l for l in lecturer_lines if "theoretical" in l.lower()]
            labs = [l for l in lecturer_lines if "labs" in l.lower()]
            generic = [l for l in lecturer_lines if l not in theoretical and l not in labs]

            answer_lines = ["Teachers / Lecturers found in the PDFs:"]
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

    # -----------------------------
    # 3) LLM fallback for non-teacher questions (Ollama generate only)
    # -----------------------------
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

    try:
        r = requests.post(
            OLLAMA_GEN_URL,
            json={"model": LLM_MODEL, "prompt": prompt, "stream": False},
            timeout=(5, 120),
            headers={"Connection": "close"},
        )
        r.raise_for_status()
        answer = r.json().get("response", "")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ollama generate failed: {e}")

    sources = [m.get("source", "unknown.pdf") if m else "unknown.pdf" for m in metas]
    sources = list(dict.fromkeys(sources))
    return {"answer": answer, "sources": sources}
