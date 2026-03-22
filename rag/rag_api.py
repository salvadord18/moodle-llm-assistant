"""
RAG API v4 for Moodle – Teacher-aware retrieval + deterministic extraction
-------------------------------------------------------------------------

Key improvements:
- Avoids query_texts to prevent 384D default embedding mismatch
- Adds lexical retrieval using where_document filters
- Extracts lecturer names/emails deterministically (no hallucinations)
"""

from fastapi import FastAPI
from pydantic import BaseModel
from chromadb import PersistentClient
import requests
import re

CHROMA_DB_PATH = "/var/www/moodledata/chroma_db"  # keep consistent with ingestion
EMBED_MODEL = "nomic-embed-text"
LLM_MODEL = "llama3.2"

OLLAMA_EMBED_URL = "http://host.docker.internal:11434/api/embed"
OLLAMA_GEN_URL = "http://host.docker.internal:11434/api/generate"

client = PersistentClient(path=CHROMA_DB_PATH)
app = FastAPI()

class Query(BaseModel):
    question: str
    courseid: int
    userid: int

def embed(text: str):
    """Get a 768-dim embedding from Ollama (nomic-embed-text)."""
    r = requests.post(OLLAMA_EMBED_URL, json={"model": EMBED_MODEL, "input": text})
    data = r.json()
    # Ollama embed returns {"embeddings": [[...]]}
    return data["embeddings"][0]

def is_teacher_question(q: str) -> bool:
    """Detect teacher/lecturer type questions."""
    q = q.lower()
    keywords = ["teacher", "teachers", "lecturer", "instructor", "professor", "docente", "docentes", "labs", "theoretical"]
    return any(k in q for k in keywords)

def extract_lecturers_from_text(text: str):
    """
    Deterministically extract lecturer-related lines.
    This avoids LLM hallucination.
    """
    # Common patterns seen in your PDFs:
    # "Lecturer: Name"
    # "Lecturer (Theoretical): Name"
    # "Lecturer (Labs): Name"
    # "Email: something@..."
    lecturer_lines = []
    email_lines = []

    # Capture lecturer lines (case-insensitive)
    for m in re.finditer(r"(Lecturer[^:\n]{0,40}:\s*[^\n]+)", text, flags=re.IGNORECASE):
        lecturer_lines.append(m.group(1).strip())

    for m in re.finditer(r"(Email:\s*\S+)", text, flags=re.IGNORECASE):
        email_lines.append(m.group(1).strip())

    # De-duplicate while preserving order
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
    collection = client.get_collection(collection_name)

    q = data.question.strip()
    q_emb = embed(q.lower())

    # 1) Standard semantic retrieval
    sem_results = collection.query(
        query_embeddings=[q_emb],
        n_results=15,
        include=["documents", "metadatas"]
    )

    sem_docs = sem_results["documents"][0]
    sem_metas = sem_results["metadatas"][0]

    # 2) Teacher-aware lexical retrieval (force chunks containing "Lecturer")
    lex_docs = []
    lex_metas = []
    if is_teacher_question(q):
        lex_results = collection.query(
            query_embeddings=[q_emb],
            n_results=15,
            include=["documents", "metadatas"],
            where_document={"$contains": "Lecturer"}  # supported by Chroma query API [1](https://docs.trychroma.com/docs/querying-collections/query-and-get)
        )
        lex_docs = lex_results["documents"][0]
        lex_metas = lex_results["metadatas"][0]

    # 3) Merge results, prioritizing lex matches first
    docs = lex_docs + sem_docs
    metas = lex_metas + sem_metas

    # 4) Build a single context string with sources
    context = ""
    for doc, meta in zip(docs, metas):
        src = meta.get("source", "unknown.pdf") if meta else "unknown.pdf"
        context += f"[SOURCE: {src}]\n{doc}\n\n"

    # 5) Deterministic extraction for teacher questions
    if is_teacher_question(q):
        lecturer_lines, email_lines = extract_lecturers_from_text(context)
        if lecturer_lines or email_lines:
            answer_lines = []
            answer_lines.append("Teachers / Lecturers found in the PDFs:")
            answer_lines.extend([f"- {l}" for l in lecturer_lines])
            if email_lines:
                answer_lines.append("")
                answer_lines.append("Emails found in the PDFs:")
                answer_lines.extend([f"- {e}" for e in email_lines])

            sources = []
            for m in metas:
                if m and "source" in m:
                    sources.append(m["source"])
            sources = list(dict.fromkeys(sources))  # unique preserving order

            return {"answer": "\n".join(answer_lines), "sources": sources}

        # If we didn't find explicit lecturer lines, fall back to LLM
        # (still anti-hallucination)
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
        r = requests.post(OLLAMA_GEN_URL, json={"model": LLM_MODEL, "prompt": prompt, "stream": False})
        return {"answer": r.json().get("response", ""), "sources": [m.get("source") if m else "unknown.pdf" for m in metas]}

    # Non-teacher questions: normal RAG prompt
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
    r = requests.post(OLLAMA_GEN_URL, json={"model": LLM_MODEL, "prompt": prompt, "stream": False})
    sources = [m.get("source") if m else "unknown.pdf" for m in metas]
    # de-duplicate sources
    sources = list(dict.fromkeys(sources))
    return {"answer": r.json().get("response", ""), "sources": sources}