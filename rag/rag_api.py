"""
Moodle RAG API — Generic RAG (Improved Retrieval + Rerank + Context Compression)
-------------------------------------------------------------------------------

Pipeline:
1) Retrieve top-K candidates from Chroma (multi-query: original + rewrite + keywords)
2) Rerank with a hybrid score (vector distance + lexical overlap + source/label bonuses)
3) Compress + pack best chunks into a bounded context (priority source + diversity-by-source)
4) Generate with Ollama using system/style prompts

Run:
  cd /var/www/html/blocks/llmassistant/rag
  uvicorn rag_api:app --host 0.0.0.0 --port 8001
"""

from fastapi import FastAPI
from pydantic import BaseModel, Field
from chromadb import PersistentClient
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
import os
import re
import time
import hashlib
import requests

# -----------------------------
# CONFIG
# -----------------------------
CHROMA_DB_PATH = "/var/www/moodledata/chroma_db"

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
OLLAMA_GEN_URL = f"{OLLAMA_BASE_URL}/api/generate"
LLM_MODEL = os.getenv("OLLAMA_LLM_MODEL", "qwen2.5:1.5b")

PROMPTS_DIR = os.getenv(
    "LLMASSISTANT_PROMPTS_DIR",
    "/var/www/html/blocks/llmassistant/rag/prompts"
)
SYSTEM_COURSE_FILE = "system_course.txt"
SYSTEM_GLOBAL_FILE = "system_global.txt"
STYLE_FILE = "style.txt"

# Defaults tuned for "aggregation" questions (teachers/contacts/deadlines/rules)
TOP_K = int(os.getenv("LLMASSISTANT_TOP_K", "30"))
MAX_CHUNKS = int(os.getenv("LLMASSISTANT_MAX_CHUNKS", "12"))
MAX_CONTEXT_CHARS = int(os.getenv("LLMASSISTANT_MAX_CONTEXT_CHARS", "14000"))
MAX_LINES_PER_CHUNK = int(os.getenv("LLMASSISTANT_MAX_LINES_PER_CHUNK", "40"))

DISTANCE_THRESHOLD = float(os.getenv("LLMASSISTANT_DISTANCE_THRESHOLD", "0.96"))

ALPHA_VEC = float(os.getenv("LLMASSISTANT_RERANK_ALPHA", "0.55"))  # vector
BETA_LEX  = float(os.getenv("LLMASSISTANT_RERANK_BETA", "0.45"))   # lexical

DEBUG = os.getenv("LLMASSISTANT_DEBUG", "0").lower() in ("1", "true", "yes")
ENABLE_QUERY_REWRITE = os.getenv("LLMASSISTANT_QUERY_REWRITE", "1").lower() in ("1", "true", "yes")

GEN_TEMPERATURE = float(os.getenv("LLMASSISTANT_TEMPERATURE", "0.0"))
GEN_TOP_P = float(os.getenv("LLMASSISTANT_TOP_P", "1.0"))
GEN_NUM_CTX = int(os.getenv("LLMASSISTANT_NUM_CTX", "2048"))

COMPRESS_CONTEXT = os.getenv("LLMASSISTANT_COMPRESS_CONTEXT", "1").lower() in ("1", "true", "yes")

# Priority sources (comma-separated). Default: Lecture1.pdf (course overview/intro).
PRIORITY_SOURCES = [
    s.strip() for s in os.getenv("LLMASSISTANT_PRIORITY_SOURCES", "Lecture1.pdf").split(",")
    if s.strip()
]
SOURCE_BONUS = float(os.getenv("LLMASSISTANT_SOURCE_BONUS", "0.10"))
MIN_PRIORITY_CHUNKS = int(os.getenv("LLMASSISTANT_MIN_PRIORITY_CHUNKS", "3"))

# For contacts/admin questions: boost chunks with real teacher/contact labels, penalize example datasets
CONTACT_LABEL_BONUS = float(os.getenv("LLMASSISTANT_CONTACT_LABEL_BONUS", "0.25"))
EXAMPLE_PENALTY_EMAIL = float(os.getenv("LLMASSISTANT_EXAMPLE_EMAIL_PENALTY", "0.30"))
EXAMPLE_PENALTY_TABLE = float(os.getenv("LLMASSISTANT_EXERCISE_TABLE_PENALTY", "0.20"))

STOPWORDS = {
    "the","a","an","and","or","of","to","in","on","for","with","is","are","was","were",
    "this","that","these","those","who","what","when","where","why","how",
    "me","my","your","our","their",
    "do","does","did",
    "course","lecture","pdf"
}

SYNONYMS = {
    "teachers": ["lecturer", "instructor", "professor", "faculty", "email", "contact"],
    "teacher": ["lecturer", "instructor", "professor", "email", "contact"],
    "lecturer": ["teacher", "instructor", "professor", "email", "contact"],
    "instructor": ["teacher", "lecturer", "professor", "email", "contact"],
    "professor": ["teacher", "lecturer", "instructor", "email", "contact"],
    "email": ["contact", "lecturer", "instructor", "teacher"],
    "deadline": ["due", "submission", "submit", "date"],
    "exam": ["test", "assessment", "evaluation"],
    "grade": ["grading", "assessment", "evaluation", "criteria"],
    "thesis": ["dissertation", "proposal", "supervisor", "steps", "procedure"],
    "contact": ["email", "lecturer", "teacher", "instructor"],
}

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
TEACHER_LABEL_RE = re.compile(r"\b(lecturer|instructor|professor)\b", re.IGNORECASE)
NOV_AFFIL_EMAIL_RE = re.compile(r"@novaims\.unl\.pt\b", re.IGNORECASE)

# Common “example dataset” signals in DB lectures (avoid false positives)
EXAMPLE_EMAIL_RE = re.compile(r"\b(example\.com|mailinator\.com|fakemail\.com)\b", re.IGNORECASE)
EXERCISE_TABLE_RE = re.compile(
    r"\b(order_id|customer email|functional dependencies|shipping department|patients? appointment|bill|payment)\b",
    re.IGNORECASE
)

# -----------------------------
# INIT
# -----------------------------
client = PersistentClient(path=CHROMA_DB_PATH)
embedding_fn = DefaultEmbeddingFunction()

app = FastAPI()
_session = requests.Session()


class Query(BaseModel):
    question: str
    courseid: int
    userid: int
    history: list[dict] = Field(default_factory=list)


# -----------------------------
# HELPERS
# -----------------------------
def load_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def build_system_prompt(courseid: int) -> str:
    style = load_text(os.path.join(PROMPTS_DIR, STYLE_FILE))
    system_file = SYSTEM_GLOBAL_FILE if courseid == 0 else SYSTEM_COURSE_FILE
    system = load_text(os.path.join(PROMPTS_DIR, system_file))
    parts = [p for p in (system, style) if p]
    return "\n\n".join(parts).strip()


def build_history_block(history: list[dict]) -> str:
    if not history:
        return ""
    lines = []
    for turn in history[-6:]:
        role = (turn.get("role") or "user").strip().upper()
        msg = (turn.get("message") or "").strip()
        if msg:
            lines.append(f"{role}: {msg}")
    return ("CHAT HISTORY:\n" + "\n".join(lines) + "\n\n") if lines else ""


def ollama_generate(prompt: str) -> str:
    payload = {
        "model": LLM_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": GEN_TEMPERATURE,
            "top_p": GEN_TOP_P,
            "num_ctx": GEN_NUM_CTX,
        }
    }
    headers = {"Connection": "close"}
    last_err = None

    for attempt in range(4):
        try:
            r = _session.post(OLLAMA_GEN_URL, json=payload, headers=headers, timeout=(5, 120))
            r.raise_for_status()
            data = r.json()
            response = (data.get("response") or "").strip()
            if not response:
                raise RuntimeError(f"Ollama returned empty response: {data}")
            return response
        except Exception as e:
            last_err = e
            time.sleep(min(2.0, 0.2 * (2 ** attempt)))

    raise RuntimeError(f"Ollama generate failed: {last_err}")


def ollama_rewrite_query(q: str) -> str:
    rewrite_prompt = (
        "Rewrite the user question into a search query for lecture PDFs. "
        "Add synonyms AND common document labels used in slides (e.g., Lecturer, Instructor, Professor, Email, Contact, Assessment, Deadline, Exam). "
        "Keep it short. Return ONE line only.\n\n"
        f"Question: {q}\n"
        "Search query:"
    )
    payload = {
        "model": LLM_MODEL,
        "prompt": rewrite_prompt,
        "stream": False,
        "options": {"temperature": 0.0, "num_ctx": 1024}
    }
    try:
        r = _session.post(OLLAMA_GEN_URL, json=payload, timeout=(5, 60))
        r.raise_for_status()
        out = (r.json().get("response") or "").strip()
        return out.splitlines()[0].strip() if out else ""
    except Exception:
        return ""


def tokenize(text: str):
    text = (text or "").lower()
    return set(re.findall(r"[a-zA-ZÀ-ÿ0-9]+", text))


def build_keyword_query(q: str) -> str:
    toks = [t for t in re.findall(r"[a-zA-ZÀ-ÿ0-9]+", (q or "").lower()) if t not in STOPWORDS]
    toks = toks[:10]
    expanded = []
    for t in toks:
        expanded.append(t)
        for syn in SYNONYMS.get(t, []):
            expanded.append(syn)
    out = list(dict.fromkeys(expanded))
    return " ".join(out[:18]).strip()


def lexical_overlap_score(query: str, doc: str) -> float:
    qset = tokenize(query)
    if not qset:
        return 0.0
    dset = tokenize(doc or "")
    if not dset:
        return 0.0
    inter = qset.intersection(dset)
    return len(inter) / max(1, len(qset))


def doc_key(doc: str, meta: dict):
    src = (meta or {}).get("source", "")
    return hashlib.md5((src + "|" + (doc or "")).encode("utf-8", errors="ignore")).hexdigest()


def compress_doc(doc: str, query_text: str) -> str:
    if not COMPRESS_CONTEXT:
        return doc or ""

    lines = (doc or "").splitlines()
    qtokens = tokenize(query_text)
    if not lines:
        return doc or ""

    keep = []
    for i, line in enumerate(lines):
        line_stripped = line.strip()
        if not line_stripped:
            continue

        email_like = bool(EMAIL_RE.search(line_stripped))
        structured = (":" in line_stripped and len(line_stripped) <= 260)

        if email_like or structured:
            keep.append(line_stripped)
            continue

        ltoks = tokenize(line_stripped)
        if ltoks and qtokens and (ltoks & qtokens):
            for j in (i - 1, i, i + 1):
                if 0 <= j < len(lines):
                    lj = lines[j].strip()
                    if lj:
                        keep.append(lj)

    out, seen = [], set()
    for l in keep:
        if l not in seen:
            out.append(l)
            seen.add(l)
        if len(out) >= MAX_LINES_PER_CHUNK:
            break

    return "\n".join(out) if out else (doc or "")


def pack_context(ranked_items, query_text: str):
    context = []
    used_sources = []
    total = 0

    for doc, meta, dist, score in ranked_items:
        src = (meta or {}).get("source", "unknown.pdf")
        d2 = compress_doc(doc, query_text)

        if d2.lstrip().startswith("[SOURCE:"):
            block = f"{d2}\n"
        else:
            block = f"[SOURCE: {src}]\n{d2}\n"

        if total + len(block) > MAX_CONTEXT_CHARS:
            break

        context.append(block)
        used_sources.append(src)
        total += len(block)

    used_sources = list(dict.fromkeys(used_sources))
    return "\n".join(context), used_sources


def is_contacts_or_admin(q: str) -> bool:
    ql = (q or "").lower()
    return any(k in ql for k in [
        "who","teacher","teachers","lecturer","instructor","professor",
        "email","contact","office","hours","grading","assessment","deadline","due","exam","policy","criteria","rule"
    ])


# -----------------------------
# ROUTES
# -----------------------------
@app.post("/ask")
def ask(data: Query):
    q = (data.question or "").strip()
    if not q:
        return {"answer": "Please enter a question.", "sources": []}

    collection_name = "global_docs" if data.courseid == 0 else f"course_docs_{data.courseid}"
    try:
        collection = client.get_collection(collection_name, embedding_function=embedding_fn)
    except Exception as e:
        resp = {"answer": "The provided PDFs do not contain this information.", "sources": []}
        if DEBUG:
            resp["debug"] = f"Collection not found: {collection_name} ({e})"
        return resp

    queries = [q]
    q_kw = build_keyword_query(q)
    if q_kw and q_kw.lower() != q.lower():
        queries.append(q_kw)

    q2 = ""
    if ENABLE_QUERY_REWRITE:
        q2 = ollama_rewrite_query(q)
        if q2 and q2.lower() not in [x.lower() for x in queries]:
            queries.append(q2)

    try:
        results = collection.query(
            query_texts=queries,
            n_results=TOP_K,
            include=["documents", "metadatas", "distances"]
        )
    except Exception as e:
        resp = {"answer": "Error: retrieval failed.", "sources": []}
        if DEBUG:
            resp["debug"] = str(e)
        return resp

    all_docs = results.get("documents") or []
    all_metas = results.get("metadatas") or []
    all_dists = results.get("distances") or []

    q_mix = " ".join([x for x in [q, q_kw, q2] if x]).strip()
    want_contacts = is_contacts_or_admin(q)

    merged = {}
    seen_sources = []

    for qi in range(len(queries)):
        docs_i = all_docs[qi] if qi < len(all_docs) else []
        metas_i = all_metas[qi] if qi < len(all_metas) else []
        dists_i = all_dists[qi] if qi < len(all_dists) else []

        for doc, meta, dist in zip(docs_i, metas_i, dists_i):
            if not doc or dist is None:
                continue

            dist = float(dist)
            lex = lexical_overlap_score(q_mix, doc)
            vec_sim = max(0.0, 1.0 - dist)
            score = ALPHA_VEC * vec_sim + BETA_LEX * lex

            src = (meta or {}).get("source", "")
            if src in PRIORITY_SOURCES:
                score += SOURCE_BONUS

            if want_contacts:
                teacher_label = bool(TEACHER_LABEL_RE.search(doc))
                has_email = bool(EMAIL_RE.search(doc))
                has_nov_email = bool(NOV_AFFIL_EMAIL_RE.search(doc))

                # positive signals for real teacher/contact chunks
                if teacher_label and has_email:
                    score += CONTACT_LABEL_BONUS * 1.8
                elif teacher_label:
                    score += CONTACT_LABEL_BONUS * 1.2
                elif has_nov_email:
                    score += CONTACT_LABEL_BONUS * 0.9

                # negative signals for exercise datasets / fake emails
                if EXAMPLE_EMAIL_RE.search(doc):
                    score -= EXAMPLE_PENALTY_EMAIL
                if EXERCISE_TABLE_RE.search(doc):
                    score -= EXAMPLE_PENALTY_TABLE

            k = doc_key(doc, meta)
            cur = merged.get(k)
            if cur is None:
                merged[k] = (doc, meta, dist, score)
            else:
                _, _, d0, s0 = cur
                if (score > s0) or (score == s0 and dist < d0):
                    merged[k] = (doc, meta, dist, score)

            if src:
                seen_sources.append(src)

    candidates = list(merged.values())
    if not candidates:
        resp = {"answer": "The provided PDFs do not contain this information.", "sources": []}
        if DEBUG:
            resp["debug"] = {"reason": "no_candidates", "queries": queries}
        return resp

    candidates.sort(key=lambda x: (-x[3], x[2]))
    best_dist = min([c[2] for c in candidates]) if candidates else None

    if best_dist is not None and best_dist > DISTANCE_THRESHOLD:
        resp = {"answer": "The provided PDFs do not contain this information.", "sources": []}
        if DEBUG:
            resp["debug"] = {
                "min_dist": best_dist,
                "threshold": DISTANCE_THRESHOLD,
                "queries": queries,
                "top_sources": list(dict.fromkeys(seen_sources))[:10]
            }
        return resp

    # -----------------------------
    # Selection strategy:
    # 1) For contacts/admin: ensure Lecture1 chunks that actually look like contacts/teacher info.
    # 2) Fill with diversity-by-source (best 2 per source).
    # -----------------------------
    top = []
    used = set()

    # 1) Priority source selection
    priority_candidates = [c for c in candidates if ((c[1] or {}).get("source", "") in PRIORITY_SOURCES)]
    if priority_candidates:
        if want_contacts:
            def priority_rank(c):
                doc = c[0] or ""
                hits = 0
                if TEACHER_LABEL_RE.search(doc): hits += 2
                if NOV_AFFIL_EMAIL_RE.search(doc): hits += 2
                if EMAIL_RE.search(doc): hits += 1
                if EXAMPLE_EMAIL_RE.search(doc): hits -= 2
                if EXERCISE_TABLE_RE.search(doc): hits -= 1
                return (-hits, -c[3], c[2])
            priority_candidates.sort(key=priority_rank)
        else:
            priority_candidates.sort(key=lambda x: (-x[3], x[2]))

        for c in priority_candidates[:MIN_PRIORITY_CHUNKS]:
            k = doc_key(c[0], c[1])
            if k not in used:
                top.append(c)
                used.add(k)

    # 2) Diversity-by-source fill (best 2 per source)
    per_source = {}
    for c in candidates:
        doc, meta, dist, score = c
        src = (meta or {}).get("source", "unknown.pdf")
        per_source.setdefault(src, []).append(c)

    for src in per_source:
        per_source[src].sort(key=lambda x: (-x[3], x[2]))
        per_source[src] = per_source[src][:2]

    diverse = []
    for items in per_source.values():
        diverse.extend(items)
    diverse.sort(key=lambda x: (-x[3], x[2]))

    for c in diverse:
        if len(top) >= MAX_CHUNKS:
            break
        k = doc_key(c[0], c[1])
        if k not in used:
            top.append(c)
            used.add(k)

    context, used_sources = pack_context(top, q_mix)
    history_block = build_history_block(data.history)
    system_prompt = build_system_prompt(data.courseid)

    prompt = f"""{system_prompt}

{history_block}CONTEXT:
{context}

QUESTION:
{q}

ANSWER:
"""

    try:
        answer = ollama_generate(prompt).strip()
    except Exception as e:
        resp = {"answer": "Error: LLM generation failed."}
        if DEBUG:
            resp["debug"] = str(e)
        return resp

    if not answer:
        return {"answer": "Error: empty response from model."}

    resp = {"answer": answer, "sources": used_sources}
    if DEBUG:
        resp["debug"] = {
            "queries": queries,
            "best_dist": best_dist,
            "priority_sources": PRIORITY_SOURCES,
            "top_sources": used_sources,
            "context_preview": context[:800]
        }
    return resp