"""
Moodle RAG API (Restructured) — Stable responses + Prompt files (.txt)
-----------------------------------------------------------------------

Goals:
- Always respond with valid JSON (avoid breaking the UI)
- Answer greetings/small-talk without calling the LLM
- For real questions: retrieve from PDFs and call Ollama /api/generate
- Teacher questions: deterministic extraction (no hallucinations)
- Prompt/style rules loaded from .txt files for easy editing

Run inside Moodle 'webserver' container:
  cd /var/www/html/blocks/llmassistant/rag
  uvicorn rag_api:app --host 0.0.0.0 --port 8001
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from chromadb import PersistentClient
import os
import re
import time
import requests
from typing import List, Tuple

# -----------------------------
# CONFIG
# -----------------------------
CHROMA_DB_PATH = "/var/www/moodledata/chroma_db"

LLM_MODEL = os.getenv("OLLAMA_LLM_MODEL", "llama3.2")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
OLLAMA_GEN_URL = f"{OLLAMA_BASE_URL}/api/generate"

# Prompt files folder (inside repo / container)
PROMPTS_DIR = os.getenv(
    "LLMASSISTANT_PROMPTS_DIR",
    "/var/www/html/blocks/llmassistant/rag/prompts"
)

SYSTEM_COURSE_FILE = "system_course.txt"
SYSTEM_GLOBAL_FILE = "system_global.txt"
STYLE_FILE = "style.txt"

# Retrieval config
TOP_K = int(os.getenv("LLMASSISTANT_TOP_K", "15"))

client = PersistentClient(path=CHROMA_DB_PATH)
app = FastAPI()

# Reuse a session for better stability
_session = requests.Session()


# -----------------------------
# REQUEST SCHEMA
# -----------------------------
class Query(BaseModel):
    question: str
    courseid: int
    userid: int


# -----------------------------
# PROMPT LOADING
# -----------------------------
def load_text_file(path: str) -> str:
    """Load a UTF-8 text file. Returns empty string if missing."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def build_system_prompt(courseid: int) -> str:
    """
    Build system prompt from prompt files.
    - courseid == 0 -> global mode
    - else -> course mode
    """
    style = load_text_file(os.path.join(PROMPTS_DIR, STYLE_FILE))

    if courseid == 0:
        system = load_text_file(os.path.join(PROMPTS_DIR, SYSTEM_GLOBAL_FILE))
    else:
        system = load_text_file(os.path.join(PROMPTS_DIR, SYSTEM_COURSE_FILE))

    # Combine
    parts = []
    if system:
        parts.append(system)
    if style:
        parts.append(style)

    return "\n\n".join(parts).strip()


# -----------------------------
# SMALL TALK / GREETING HANDLER
# -----------------------------
def is_greeting(q: str) -> bool:
    """Detect very short greetings to avoid calling the LLM unnecessarily."""
    q = q.strip().lower()
    greetings = {"hi", "hello", "hey", "ola", "olá", "bom dia", "boa tarde", "boa noite"}
    if q in greetings:
        return True
    # Also treat very short messages as greetings
    if len(q) <= 3:
        return True
    return False


def greeting_answer(courseid: int) -> str:
    """Return a stable greeting message."""
    if courseid == 0:
        return (
            "Hi! Ask me about faculty rules, regulations, and general information.\n\n"
            "Example questions:\n"
            "- What is the grading policy?\n"
            "- What are the deadlines?\n"
            "- What is the attendance policy?"
        )
    else:
        return (
            "Hi! Ask me something about this course.\n\n"
            "Example questions:\n"
            "- Who are the teachers of this course?\n"
            "- What is the grading policy?\n"
            "- Summarize Lecture 3.\n"
            "- What is the definition of a DBMS?"
        )


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
# OLLAMA GENERATE (ROBUST)
# -----------------------------
def ollama_generate(prompt: str) -> str:
    """
    Robust /api/generate call with retries and backoff.
    Returns the generated response text.
    """
    payload = {"model": LLM_MODEL, "prompt": prompt, "stream": False}
    headers = {"Connection": "close"}

    last_err = None
    for attempt in range(5):
        try:
            r = _session.post(
                OLLAMA_GEN_URL,
                json=payload,
                headers=headers,
                timeout=(5, 120),
            )
            r.raise_for_status()
            data = r.json()
            return data.get("response", "")
        except Exception as e:
            last_err = e
            time.sleep(min(2.0, 0.2 * (2 ** attempt)))

    raise RuntimeError(f"Ollama generate failed after retries: {last_err}")


# -----------------------------
# MAIN ENDPOINT
# -----------------------------
@app.post("/ask")
def ask(data: Query):
    collection_name = "global_docs" if data.courseid == 0 else f"course_docs_{data.courseid}"

    # 0) Handle greetings without hitting LLM or DB
    q = (data.question or "").strip()
    if not q:
        return {"answer": "Error: empty question.", "sources": []}

    if is_greeting(q):
        return {"answer": greeting_answer(data.courseid), "sources": []}

    # 1) Load collection
    try:
        collection = client.get_collection(collection_name)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Collection not found: {collection_name} ({e})")

    teacher = is_teacher_question(q)

    # 2) Retrieval (Chroma local embeddings via query_texts)
    try:
        sem_results = collection.query(
            query_texts=[q],
            n_results=TOP_K,
            include=["documents", "metadatas"],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Chroma query failed: {e}")

    docs = sem_results["documents"][0]
    metas = sem_results["metadatas"][0]

    # 2.1) Teacher lexical boost
    if teacher:
        try:
            lex_results = collection.query(
                query_texts=[q],
                n_results=TOP_K,
                include=["documents", "metadatas"],
                where_document={"$contains": "Lecturer"},
            )
            docs = lex_results["documents"][0] + docs
            metas = lex_results["metadatas"][0] + metas
        except Exception:
            pass

    # 2.2) Build context with sources
    context = ""
    for doc, meta in zip(docs, metas):
        src = meta.get("source", "unknown.pdf") if meta else "unknown.pdf"
        context += f"[SOURCE: {src}]\n{doc}\n\n"

    # 3) Deterministic teacher extraction
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

    # 4) If context is too weak, return a safe response (no hallucination)
    if not context.strip():
        return {"answer": "The provided PDFs do not contain this information.", "sources": []}

    # 5) Build prompt from prompt files
    system_prompt = build_system_prompt(data.courseid)
    if not system_prompt:
        # Default fallback system prompt if prompt files are missing
        system_prompt = (
            "You MUST answer using ONLY the provided CONTEXT.\n"
            "If the answer is not explicitly present, say:\n"
            "\"The provided PDFs do not contain this information.\""
        )

    prompt = f"""{system_prompt}

CONTEXT:
{context}

QUESTION:
{q}

ANSWER:
"""

    # 6) Generate using Ollama (robust)
    try:
        answer = ollama_generate(prompt)
    except Exception as e:
        # IMPORTANT: Return a valid JSON response instead of crashing the UI
        return {
            "answer": "Error: the assistant backend is temporarily unavailable. Please try again.",
            "sources": []
        }

    sources = [m.get("source", "unknown.pdf") if m else "unknown.pdf" for m in metas]
    sources = list(dict.fromkeys(sources))
    return {"answer": answer, "sources": sources}
