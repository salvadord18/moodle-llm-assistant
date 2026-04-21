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
from itertools import groupby
import os
import re
import time
import hashlib
import requests
import numpy as np
import unicodedata
from functools import lru_cache
import psycopg2

# -----------------------------
# CONFIG
# -----------------------------
CHROMA_DB_PATH = "/var/www/moodledata/chroma_db"

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
OLLAMA_GEN_URL = f"{OLLAMA_BASE_URL}/api/generate"
LLM_MODEL = os.getenv("OLLAMA_LLM_MODEL", "qwen2.5:3b")

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
MAX_CONTEXT_CHARS = int(os.getenv("LLMASSISTANT_MAX_CONTEXT_CHARS", "9000"))
MAX_LINES_PER_CHUNK = int(os.getenv("LLMASSISTANT_MAX_LINES_PER_CHUNK", "80"))

DISTANCE_THRESHOLD = float(os.getenv("LLMASSISTANT_DISTANCE_THRESHOLD", "0.93"))
CONTACT_DISTANCE_THRESHOLD = float(
    os.getenv("LLMASSISTANT_CONTACT_DISTANCE_THRESHOLD", "1.25")
)
GENERIC_DISTANCE_THRESHOLD = float(
    os.getenv("LLMASSISTANT_DISTANCE_THRESHOLD", "0.93")
)

ALPHA_VEC = float(os.getenv("LLMASSISTANT_RERANK_ALPHA", "0.55"))  # vector
BETA_LEX  = float(os.getenv("LLMASSISTANT_RERANK_BETA", "0.45"))   # lexical

DEBUG = os.getenv("LLMASSISTANT_DEBUG", "0").lower() in ("1", "true", "yes")
ENABLE_QUERY_REWRITE = os.getenv("LLMASSISTANT_QUERY_REWRITE", "1").lower() in ("1", "true", "yes")

GEN_TEMPERATURE = float(os.getenv("LLMASSISTANT_TEMPERATURE", "0.0"))
GEN_TOP_P = float(os.getenv("LLMASSISTANT_TOP_P", "1.0"))
GEN_NUM_CTX = int(os.getenv("LLMASSISTANT_NUM_CTX", "4096"))

COMPRESS_CONTEXT = os.getenv("LLMASSISTANT_COMPRESS_CONTEXT", "1").lower() in ("1", "true", "yes")

# Priority sources (comma-separated). Default: Lecture1.pdf (course overview/intro).
PRIORITY_SOURCES = [
    s.strip() for s in os.getenv("LLMASSISTANT_PRIORITY_SOURCES", "Lecture1.pdf").split(",")
    if s.strip()
]
SOURCE_BONUS = float(os.getenv("LLMASSISTANT_SOURCE_BONUS", "0.25"))
PRIORITY_RATIO = float(os.getenv("LLMASSISTANT_PRIORITY_RATIO", "0.5"))
MIN_PRIORITY_CHUNKS = 2  # safety floor

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
TEACHER_LABEL_RE = re.compile(
    r"\b(lecturer|instructor|professor|teacher|docente|docentes|regente|professores?|labs?|theoretical|practical|assistente)\b",
    re.IGNORECASE
)
NOV_AFFIL_EMAIL_RE = re.compile(r"@novaims\.unl\.pt\b", re.IGNORECASE)
TITLE_HINT_CONTACT_RE = re.compile(
    r"\b(overview|lecturer|instructor|professor|teacher|contact|staff|faculty|email|docente|regente)\b",
    re.IGNORECASE
)
TEACHING_EXAMPLE_RE = re.compile(r"\bstudent[-\s]?teacher\b", re.IGNORECASE)

# Common “example dataset” signals in DB lectures (avoid false positives)
EXAMPLE_EMAIL_RE = re.compile(r"\b(example\.com|mailinator\.com|fakemail\.com)\b", re.IGNORECASE)
EXERCISE_TABLE_RE = re.compile(
    r"\b(order_id|customer email|functional dependencies|shipping department|patients? appointment|bill|payment)\b",
    re.IGNORECASE
)

DB_PREFIX = os.getenv("MOODLE_DB_PREFIX", "m_")

DB = {
    "host": os.getenv("MOODLE_DB_HOST", "db"),
    "port": int(os.getenv("MOODLE_DB_PORT", "5432")),
    "dbname": os.getenv("MOODLE_DB_NAME", "moodle"),
    "user": os.getenv("MOODLE_DB_USER", "moodle"),
    "password": os.getenv("MOODLE_DB_PASSWORD", "CHANGE_ME"),
}

GLOBAL_SOURCE_PATTERNS = [
    "serviços académicos",
    "servicos academicos",
    "academic services",
]

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
    
def db_connect():
    return psycopg2.connect(**DB)

def normalize_compare(text: str) -> str:
    text = (text or "").strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"\s+", " ", text)
    return text.strip()

@lru_cache(maxsize=1)
def resolve_global_source_course_id() -> int:
    """
    Resolve the course id that should act as the global source,
    matching course fullname/shortname against patterns like:
    - Serviços Académicos
    - Servicos Academicos
    - Academic services
    """

    patterns = [normalize_compare(p) for p in GLOBAL_SOURCE_PATTERNS if p.strip()]
    if not patterns:
        raise RuntimeError("GLOBAL_SOURCE_PATTERNS is empty.")

    conn = db_connect()
    cur = conn.cursor()

    sql = f"""
        SELECT id, fullname, shortname
        FROM {DB_PREFIX}course
        ORDER BY id ASC
    """
    cur.execute(sql)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    for cid, fullname, shortname in rows:
        fullname_n = normalize_compare(fullname or "")
        shortname_n = normalize_compare(shortname or "")

        for pattern in patterns:
            if pattern in fullname_n or pattern in shortname_n:
                return int(cid)

    raise RuntimeError(
        f"Could not resolve global source course by patterns: {GLOBAL_SOURCE_PATTERNS}"
    )

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


def compress_doc(doc: str, query_text: str, mode: str = "generic") -> str:
    if not COMPRESS_CONTEXT:
        return doc or ""

    lines = [l.rstrip() for l in (doc or "").splitlines()]
    if not lines:
        return doc or ""

    # -----------------------------
    # Contact / teachers mode
    # Preserve local semantic windows:
    # label -> name -> email
    # -----------------------------
    if mode == "contacts":
        keep = []

        for i, line in enumerate(lines):
            s = line.strip()
            if not s:
                continue

            is_label = bool(TEACHER_LABEL_RE.search(s)) or s.lower().startswith(("email", "e-mail", "lecturer", "docente"))
            is_email = bool(EMAIL_RE.search(s))

            if is_label or is_email:
                # Keep a window around the hit so we do not lose the person name / role.
                for j in range(max(0, i - 2), min(len(lines), i + 3)):
                    lj = lines[j].strip()
                    if lj:
                        keep.append(lj)

        if keep:
            out = []
            seen = set()
            for l in keep:
                if l not in seen:
                    out.append(l)
                    seen.add(l)
                if len(out) >= MAX_LINES_PER_CHUNK:
                    break
            return "\n".join(out)

        return doc or ""

    # -----------------------------
    # Generic mode
    # -----------------------------
    qtokens = tokenize(query_text)
    keep = []

    for i, line in enumerate(lines):
        line_stripped = line.strip()
        if not line_stripped:
            continue

        email_like = bool(EMAIL_RE.search(line_stripped))
        bullet = bool(re.match(r"^[•\-\*]", line_stripped))
        structured = (":" in line_stripped and len(line_stripped) <= 260) or bullet

        # IMPORTANT:
        # keep neighbours as well, not only the current structured line
        if email_like or structured:
            for j in range(max(0, i - 1), min(len(lines), i + 2)):
                lj = lines[j].strip()
                if lj:
                    keep.append(lj)
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


def pack_context(ranked_items, query_text: str, mode: str = "generic"):
    context = []
    source_map = []
    total = 0
    sid = 1

    for doc, meta, dist, score in ranked_items:
        src = (meta or {}).get("source", "unknown.pdf")
        page = (meta or {}).get("page")
        chunk_index = (meta or {}).get("chunk_index")
        d2 = compress_doc(doc, query_text, mode=mode)

        source_id = f"S{sid}"
        label = f"[SOURCE_ID: {source_id}|{src}|p{page}|c{chunk_index}]"
        block = f"{label}\n{d2}\n"

        if total + len(block) > MAX_CONTEXT_CHARS:
            break

        context.append(block)
        source_map.append({
            "id": source_id,
            "source": src,
            "page": page,
            "chunk_index": chunk_index,
            "content": d2.lower(),
        })

        total += len(block)
        sid += 1

    return "\n".join(context), source_map

def format_pages(pages):
    """Convert [1,2,3,5,6] -> 'p. 1-3, 5-6'"""
    if not pages:
        return ""

    pages = sorted(set(int(p) for p in pages if p is not None))

    ranges = []
    for _, group in groupby(enumerate(pages), lambda x: x[0] - x[1]):
        group = list(group)
        start = group[0][1]
        end = group[-1][1]
        if start == end:
            ranges.append(f"{start}")
        else:
            ranges.append(f"{start}-{end}")

    return "p. " + ", ".join(ranges)

def format_sources(source_map):
    """
    Groups by file and formats pages nicely:
    Lecture1.pdf (p. 4-5)
    Lecture2.pdf (p. 1, 3, 7)
    """

    grouped = {}

    for item in source_map:
        src = item["source"]
        page = item.get("page")

        if src not in grouped:
            grouped[src] = []

        if page is not None:
            if isinstance(page, int) or (isinstance(page, str) and page.isdigit()):
                grouped[src].append(int(page))

    output = []
    for src, pages in grouped.items():
        if pages:
            output.append(f"{src} ({format_pages(pages)})")
        else:
            output.append(src)

    return output

USED_SOURCES_RE = re.compile(r"(?im)^USED_SOURCES:\s*(.+?)\s*$")

def extract_used_source_ids(answer: str, source_map: list[dict]):
    """
    Extrai a linha final:
    USED_SOURCES: S1, S3

    e devolve:
    - lista de SOURCE_ID válidos
    - resposta limpa (sem essa linha)
    """
    answer = (answer or "").strip()
    valid_ids = {item["id"] for item in source_map}

    m = USED_SOURCES_RE.search(answer)
    if not m:
        return [], answer

    raw = m.group(1).strip()
    clean_answer = USED_SOURCES_RE.sub("", answer).strip()

    if raw.upper() == "NONE":
        return [], clean_answer

    ids = re.findall(r"S\d+", raw.upper())
    ids = [sid for sid in ids if sid in valid_ids]

    # deduplicar preservando ordem
    ids = list(dict.fromkeys(ids))

    return ids, clean_answer


def build_sources_from_ids(source_ids: list[str], source_map: list[dict]):
    """
    Converte SOURCE_IDs (ex.: S1, S3) nas respetivas fontes reais
    usando o source_map criado em pack_context().
    """
    by_id = {item["id"]: item for item in source_map}
    selected = [by_id[sid] for sid in source_ids if sid in by_id]
    return format_sources(selected)

def is_contacts_question(q: str) -> bool:
    ql = (q or "").lower()
    return any(k in ql for k in [
        "teacher","teachers","lecturer","instructor","professor",
        "email","e-mail","contact","contacts","office hours",
        "professor","professores","docente","docentes",
        "contacto","contactos","correio","regente"
    ])
    
def is_policy_question(q: str) -> bool:
    ql = (q or "").lower()
    return any(k in ql for k in [
        "grading policy","grade","assessment","exam","criteria","rules"
    ])
    
def is_priority_source(src: str) -> bool:
    if not src:
        return False
    return any(src.strip().lower() == p.lower() for p in PRIORITY_SOURCES)

def safe_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None

def contact_signal_count(text: str) -> int:
    text = text or ""
    return (
        len(TEACHER_LABEL_RE.findall(text)) * 2 +
        len(EMAIL_RE.findall(text)) +
        len(NOV_AFFIL_EMAIL_RE.findall(text))
    )
    
def contact_chunk_quality(doc: str, meta: dict) -> float:
    doc = doc or ""
    meta = meta or {}

    src = meta.get("source", "")
    page = safe_int(meta.get("page"))
    section_type = (meta.get("section_type") or "").lower()
    title_hint = (meta.get("title_hint") or "").lower()

    score = 0.0

    # Strong positive signals
    if section_type == "contact":
        score += 0.70

    if TITLE_HINT_CONTACT_RE.search(title_hint):
        score += 0.35

    if TEACHER_LABEL_RE.search(doc):
        score += 0.45

    if NOV_AFFIL_EMAIL_RE.search(doc):
        score += 0.40
    elif EMAIL_RE.search(doc):
        score += 0.15

    # Priority source / early overview pages
    if is_priority_source(src) and page is not None:
        if page <= 3:
            score += 0.40
        elif page > 10:
            score -= 0.25

    # Strong negative signals
    if EXAMPLE_EMAIL_RE.search(doc):
        score -= 1.20

    if EXERCISE_TABLE_RE.search(doc):
        score -= 0.80

    if TEACHING_EXAMPLE_RE.search(doc):
        score -= 0.60

    return score

def chunk_has_contact_payload(doc: str) -> bool:
    doc = doc or ""
    return bool(
        TEACHER_LABEL_RE.search(doc)
        or NOV_AFFIL_EMAIL_RE.search(doc)
        or ("email:" in doc.lower())
    )


def source_map_has_contact_payload(source_map: list[dict]) -> bool:
    for item in source_map:
        if chunk_has_contact_payload(item.get("content", "")):
            return True
    return False

# -----------------------------
# ROUTES
# -----------------------------
@app.post("/ask")
def ask(data: Query):
    q = (data.question or "").strip()
    if not q:
        return {"answer": "Please enter a question.", "sources": []}

    is_global_scope = (data.courseid == 0)

    try:
        source_courseid = resolve_global_source_course_id() if is_global_scope else int(data.courseid)
    except Exception as e:
        resp = {"answer": "The provided PDFs do not contain this information.", "sources": []}
        if DEBUG:
            resp["debug"] = f"Global source course resolution failed: {e}"
        return resp

    collection_name = f"course_docs_{source_courseid}"

    try:
        collection = client.get_collection(collection_name, embedding_function=embedding_fn)
    except Exception as e:
        resp = {"answer": "The provided PDFs do not contain this information.", "sources": []}
        if DEBUG:
            resp["debug"] = {
                "error": f"Collection not found: {collection_name} ({e})",
                "requested_courseid": data.courseid,
                "source_courseid": source_courseid,
                "is_global_scope": is_global_scope,
            }
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
    want_contacts = is_contacts_question(q)
    want_policy = is_policy_question(q)
    
    if want_contacts:
        MAX_CHUNKS_LOCAL = 8
    else:
        MAX_CHUNKS_LOCAL = MAX_CHUNKS

    merged = {}
    seen_sources = set()

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
            page = safe_int((meta or {}).get("page"))
            section_type = ((meta or {}).get("section_type") or "").lower()

            # General metadata-based boosts
            if want_policy and section_type in ("assessment", "schedule"):
                score += 0.20

            if section_type == "example":
                score -= 0.10

            # Contact-specific scoring
            if want_contacts:
                score += contact_chunk_quality(doc, meta)

                # Bare email chunks are less useful than structured role/name/email chunks
                if EMAIL_RE.search(doc) and not TEACHER_LABEL_RE.search(doc):
                    score -= 0.05

            # Canonical priority-source boosts
            if want_policy and is_priority_source(src):
                score += 0.30

            if is_priority_source(src):
                score += SOURCE_BONUS * 2

            k = doc_key(doc, meta)
            cur = merged.get(k)
            if cur is None:
                merged[k] = (doc, meta, dist, score)
            else:
                _, _, d0, s0 = cur
                if (score > s0) or (score == s0 and dist < d0):
                    merged[k] = (doc, meta, dist, score)

            if src:
                seen_sources.add(src)

        candidates = list(merged.values())

        if want_contacts:
            filtered_candidates = [
                c for c in candidates
                if contact_chunk_quality(c[0], c[1]) > 0.10
            ]
            if filtered_candidates:
                candidates = filtered_candidates

        if not candidates:
            resp = {"answer": "The provided PDFs do not contain this information.", "sources": []}
            if DEBUG:
                resp["debug"] = {
                    "return_stage": "no_candidates",
                    "requested_courseid": data.courseid,
                    "source_courseid": source_courseid,
                    "collection_name": collection_name,
                    "queries": queries
                }
            return resp

    candidates.sort(key=lambda x: (-x[3], x[2]))
    best_dist = min([c[2] for c in candidates]) if candidates else None

    threshold = CONTACT_DISTANCE_THRESHOLD if want_contacts else GENERIC_DISTANCE_THRESHOLD

    if best_dist > threshold:
        candidates = candidates[:10]
        resp = {"answer": "The provided PDFs do not contain this information.", "sources": []}
        if DEBUG:
            resp["debug"] = {
                "requested_courseid": data.courseid,
                "source_courseid": source_courseid,
                "collection_name": collection_name,
                "min_dist": best_dist,
                "threshold": threshold,
                "queries": queries,
                "top_sources": sorted(seen_sources)[:10]
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
    priority_candidates = [
        c for c in candidates
        if is_priority_source((c[1] or {}).get("source", ""))
        and (
            not want_contacts
            or contact_chunk_quality(c[0], c[1]) > 0.10
        )
    ]

    priority_limit = max(
        MIN_PRIORITY_CHUNKS,
        int(MAX_CHUNKS_LOCAL * PRIORITY_RATIO)
    )

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

        for c in priority_candidates[:priority_limit]:
            k = doc_key(c[0], c[1])
            if k not in used:
                top.append(c)
                used.add(k)

    # 2) Diversity-by-source fill (best 2 per source)
    if want_contacts:
        per_group = {}
        for c in candidates:
            doc, meta, dist, score = c
            src = (meta or {}).get("source", "unknown.pdf")
            page = safe_int((meta or {}).get("page"))
            key = (src, page)
            per_group.setdefault(key, []).append(c)

        for key in per_group:
            per_group[key].sort(key=lambda x: (-x[3], x[2]))
            per_group[key] = per_group[key][:3]  # allow a few sibling chunks from same page

        diverse = []
        for items in per_group.values():
            diverse.extend(items)
        diverse.sort(key=lambda x: (-x[3], x[2]))

    else:
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
        if len(top) >= MAX_CHUNKS_LOCAL:
            break
        k = doc_key(c[0], c[1])
        if k not in used:
            top.append(c)
            used.add(k)

        context, used_sources = pack_context(
            top,
            q_mix,
            mode="contacts" if want_contacts else "generic"
        )

        if want_contacts and not source_map_has_contact_payload(used_sources):
            fallback_top = [
                c for c in candidates
                if chunk_has_contact_payload(c[0])
            ]
            fallback_top.sort(key=lambda x: (-x[3], x[2]))
            fallback_top = fallback_top[:6]

            if fallback_top:
                context, used_sources = pack_context(
                    fallback_top,
                    q_mix,
                    mode="contacts"
                )
    history_block = build_history_block(data.history)
    system_prompt = build_system_prompt(0 if is_global_scope else data.courseid)

    prompt = f"""{system_prompt}

{history_block}CONTEXT:
{context}

QUESTION:
{q}

Instructions:
- Answer using only information supported by the CONTEXT.
- If the answer is explicitly present, extract it directly or paraphrase it faithfully.
- If relevant information is spread across multiple parts of the CONTEXT, combine the supported information into one coherent answer.
- If multiple relevant items exist, include all of them.
- Prefer completeness and usefulness over unnecessary brevity.
- Do not invent facts that are not supported by the CONTEXT.
- Do not mention SOURCE_IDs inside the main body of the answer.

Source handling:
- Treat each [SOURCE_ID: Sx|...] as a valid evidence unit.
- Use only SOURCE_IDs that exist in the CONTEXT.
- At the very end, add exactly one line in this format:
USED_SOURCES: S1, S3
- Include only the SOURCE_IDs that directly support the answer.
- If no source supports the answer, write:
USED_SOURCES: NONE

Fallback:
- If the answer is not supported by the CONTEXT, reply exactly:
{ "The provided global documents do not contain this information." if is_global_scope else "The provided PDFs do not contain this information." }

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

    used_source_ids, clean_answer = extract_used_source_ids(answer, used_sources)

    final_sources = build_sources_from_ids(used_source_ids, used_sources)

    resp = {
        "answer": clean_answer,
        "sources": final_sources
    }
    
    if DEBUG:
        resp["debug"] = {
            "requested_courseid": data.courseid,
            "source_courseid": source_courseid,
            "collection_name": collection_name,
            "queries": queries,
            "best_dist": best_dist,
            "priority_sources": PRIORITY_SOURCES,
            "top_sources": used_sources,
            "used_source_ids": used_source_ids,
            "final_sources": final_sources,
            "context_preview": context[:800]
        }
    return resp