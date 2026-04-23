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

SPECIAL_EXAM_RE = re.compile(r"\b(época especial|epoca especial)\b", re.IGNORECASE)
RESIT_EXAM_RE = re.compile(r"\b(época de recurso|epoca de recurso|recurso|melhoria)\b", re.IGNORECASE)
ACCESS_CUE_RE = re.compile(
    r"\b(t[êe]m acesso|podem ter acesso|pode(m)? inscrever[- ]se|t[êe]m direito|s[aã]o eleg[ií]veis)\b",
    re.IGNORECASE
)
PERIOD_SCOPE_RE = re.compile(
    r"\b(destina[- ]se|per[ií]odo de)\b",
    re.IGNORECASE
)
ELIGIBILITY_QUESTION_RE = re.compile(
    r"\b(quem pode|quem se pode|quem tem acesso|t[eê]m acesso|who can|who may|eligibility|eligible|access to)\b",
    re.IGNORECASE
)
PROCEDURAL_POLICY_RE = re.compile(
    r"\b(inscri[cç][aã]o em exames|portal acad[eé]mico|prazos|impresso|calend[aá]rio escolar|inscri[cç][aã]o)\b",
    re.IGNORECASE
)

FOLLOWUP_RE = re.compile(
    r"\b(other|another|else|more|isn['’]?t|isnt|what about|and their|and the|those|them)\b",
    re.IGNORECASE
)

TOPIC_RE = re.compile(
    r"\b(teacher|teachers|lecturer|instructor|professor|email|contact|contacts|assessment|deadline|exam|grade|grading|dbms|sql|thesis|supervisor)\b",
    re.IGNORECASE
)

ENTITY_FOLLOWUP_RE = re.compile(
    r"^\s*(who is|what about|and who is|and what about)\b",
    re.IGNORECASE
)

PERSON_NAME_RE = re.compile(
    r"\b[A-ZÀ-Ý][a-zà-ÿ]+(?:[\s-]+[A-ZÀ-Ý][a-zà-ÿ]+){1,3}\b"
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

def ollama_rewrite_query_course(q: str) -> str:
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
    
def ollama_rewrite_query_global(q: str) -> str:
    rewrite_prompt = (
        "Rewrite the user question into a search query for institutional regulations, rules, procedures and official PDFs. "
        "Add relevant legal/administrative terms such as regulation, rule, procedure, eligibility, access, deadline, registration, exam, special exam, academic services. "
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

USED_SOURCES_RE = re.compile(r"(?im)^USED[\s_-]?SOURCES:\s*(.+?)\s*$")

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

def no_info_text(is_global_scope: bool) -> str:
    return (
        "The provided global documents do not contain this information."
        if is_global_scope
        else "The provided PDFs do not contain this information."
    )


def simple_source_ranking(answer: str, query: str, source_map: list[dict]):
    """
    Rank source chunks heuristically using overlap with:
    - the final answer
    - the original user query
    This is used as a fallback when the model forgets to output USED_SOURCES.
    """
    answer_tokens = tokenize(answer)
    query_tokens = tokenize(query)

    scored = []

    for item in source_map:
        content = item.get("content", "")
        content_tokens = tokenize(content)

        if not content_tokens:
            continue

        overlap_answer = len(answer_tokens & content_tokens)
        overlap_query = len(query_tokens & content_tokens)

        # small normalization to avoid favouring huge chunks too much
        denom = max(len(content_tokens), 20)

        norm_answer = overlap_answer / denom
        norm_query = overlap_query / denom

        score = (0.7 * norm_answer) + (0.3 * norm_query)
        scored.append((item, score))

    scored.sort(key=lambda x: -x[1])
    return scored

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
        # English
        "grading policy", "grade", "assessment", "exam", "criteria", "rules",
        "regulation", "regulations", "procedure", "procedures", "deadline", "deadlines",
        "special exam", "special exams", "enrollment", "registration", "eligibility",

        # Portuguese
        "regulamento", "regulamentos", "norma", "normas", "regra", "regras",
        "procedimento", "procedimentos", "prazo", "prazos",
        "época especial", "epoca especial", "exame", "exames",
        "inscrever", "inscrição", "inscricao", "acesso", "elegível", "elegivel",
        "quem se pode", "quem pode", "estatuto especial", "serviços académicos", "servicos academicos"
    ])
    
def is_eligibility_question(q: str) -> bool:
    return bool(ELIGIBILITY_QUESTION_RE.search(q or ""))
    
def is_priority_source(src: str, priority_sources: list[str] | None = None) -> bool:
    if not src:
        return False
    priority_sources = priority_sources or PRIORITY_SOURCES
    return any(src.strip().lower() == p.lower() for p in priority_sources)

def is_regulatory_source(src: str) -> bool:
    s = (src or "").lower()
    return any(k in s for k in [
        "regulamento", "regulation", "despacho", "norma", "statute", "estatuto"
    ])


def is_fee_table_source(src: str) -> bool:
    s = (src or "").lower()
    return any(k in s for k in [
        "tabela de emolumentos", "emolumentos", "fees", "tuition", "costs"
    ])


def is_form_source(src: str) -> bool:
    s = (src or "").lower()
    return any(k in s for k in [
        "inscricao", "inscrição", "form", "formulario", "formulário", "requerimento"
    ])

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

def policy_chunk_quality(doc: str, meta: dict, query_text: str, is_global_scope: bool = False) -> float:
    doc = doc or ""
    meta = meta or {}
    q = (query_text or "").lower()
    src = (meta.get("source") or "")
    chunk_type = (meta.get("chunk_type") or "").lower()

    score = 0.0

    # Prefer normative sources in global/policy mode
    if is_regulatory_source(src):
        score += 0.40
    if is_fee_table_source(src):
        score -= 0.40
    if is_form_source(src):
        score -= 0.50

    ask_special = bool(SPECIAL_EXAM_RE.search(q))
    ask_eligibility = is_eligibility_question(q)

    # Explicit access / entitlement / eligibility cues
    if ACCESS_CUE_RE.search(doc):
        score += 0.45

    # Query-aware special exam handling
    if ask_special:
        if SPECIAL_EXAM_RE.search(doc):
            score += 0.60
        if RESIT_EXAM_RE.search(doc) and not SPECIAL_EXAM_RE.search(doc):
            score -= 0.60

    # Penalize purely procedural chunks for eligibility questions
    if ask_eligibility:
        if chunk_type == "page" and PROCEDURAL_POLICY_RE.search(doc) and not ACCESS_CUE_RE.search(doc):
            score -= 0.40

        if chunk_type == "block" and ACCESS_CUE_RE.search(doc):
            score += 0.20
            
    if PERIOD_SCOPE_RE.search(doc) and not ACCESS_CUE_RE.search(doc):
        score -= 0.15

    # Slight boost for formal rule-style chunks
    if "artigo" in doc.lower():
        score += 0.10

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

def expand_same_page_siblings(collection, ranked_items, max_extra=8):
    expanded = list(ranked_items)
    seen = {doc_key(d, m) for d, m, _, _ in ranked_items}

    for doc, meta, dist, score in ranked_items:
        src = (meta or {}).get("source")
        page = safe_int((meta or {}).get("page"))

        if not src or page is None:
            continue

        if contact_chunk_quality(doc, meta) <= 0.10:
            continue

        try:
            siblings = collection.get(
                where={"source": src},
                include=["documents", "metadatas"]
            )
        except Exception:
            continue

        docs = siblings.get("documents") or []
        metas = siblings.get("metadatas") or []

        for d, m in zip(docs, metas):
            if safe_int((m or {}).get("page")) != page:
                continue

            k = doc_key(d, m)
            if k in seen:
                continue

            expanded.append((d, m, dist, score - 0.02))
            seen.add(k)

            if len(expanded) >= len(ranked_items) + max_extra:
                return expanded

    return expanded

def build_retrieval_query(question: str, history: list[dict]) -> str:
    """
    Make retrieval history-aware only for genuinely ambiguous follow-up questions.
    Handles cases like:
    - "Isn't there any other teacher?"
    - "And their emails?"
    - "Who is Yuri?"
    But does NOT rewrite complete standalone questions.
    """
    q = (question or "").strip()
    if not q or not history:
        return q

    q_tokens = tokenize(q)
    has_explicit_topic = bool(TOPIC_RE.search(q))
    is_short_ambiguous = len(q_tokens) <= 6 and not has_explicit_topic
    is_followup = bool(FOLLOWUP_RE.search(q))
    is_entity_followup = bool(ENTITY_FOLLOWUP_RE.search(q))

    if not (is_followup or is_short_ambiguous or is_entity_followup):
        return q

    previous_user_messages = [
        (turn.get("message") or "").strip()
        for turn in history
        if (turn.get("role") == "user" and (turn.get("message") or "").strip())
    ]

    if not previous_user_messages:
        return q

    previous_user = previous_user_messages[-1]
    return f"{previous_user} {q}".strip()

def extract_known_contact_entities(history: list[dict]):
    known_emails = set()
    known_names = set()

    for turn in history[-6:]:
        if (turn.get("role") or "") != "assistant":
            continue

        text = (turn.get("message") or "").strip()
        if not text:
            continue

        for email in EMAIL_RE.findall(text):
            known_emails.add(email.lower())

        for name in PERSON_NAME_RE.findall(text):
            known_names.add(normalize_compare(name))

    return known_names, known_emails

def contact_novelty_bonus(doc: str, known_names: set, known_emails: set) -> float:
    doc = doc or ""

    doc_emails = {e.lower() for e in EMAIL_RE.findall(doc)}
    doc_names = {normalize_compare(n) for n in PERSON_NAME_RE.findall(doc)}

    new_emails = doc_emails - known_emails
    new_names = doc_names - known_names

    score = 0.0

    if new_emails:
        score += 0.60 * len(new_emails)

    if new_names:
        score += 0.40 * len(new_names)

    # Penalize chunks that only repeat already known people/emails
    if (doc_emails & known_emails or doc_names & known_names) and not (new_emails or new_names):
        score -= 0.35

    return score

def is_additive_followup(q: str) -> bool:
    return bool(FOLLOWUP_RE.search(q or ""))

def source_map_has_new_contact_payload(source_map: list[dict], known_names: set, known_emails: set) -> bool:
    for item in source_map:
        if contact_novelty_bonus(item.get("content", ""), known_names, known_emails) > 0:
            return True
    return False

def expand_adjacent_regulation_pages(collection, ranked_items, max_extra=4):
    expanded = list(ranked_items)
    seen = {doc_key(d, m) for d, m, _, _ in ranked_items}

    for doc, meta, dist, score in ranked_items:
        src = (meta or {}).get("source")
        page = safe_int((meta or {}).get("page"))

        if not src or page is None:
            continue

        if not is_regulatory_source(src):
            continue

        target_pages = {page - 1, page + 1}

        try:
            siblings = collection.get(
                where={"source": src},
                include=["documents", "metadatas"]
            )
        except Exception:
            continue

        docs = siblings.get("documents") or []
        metas = siblings.get("metadatas") or []

        for d, m in zip(docs, metas):
            mp = safe_int((m or {}).get("page"))
            if mp not in target_pages:
                continue

            k = doc_key(d, m)
            if k in seen:
                continue

            expanded.append((d, m, dist, score - 0.03))
            seen.add(k)

            if len(expanded) >= len(ranked_items) + max_extra:
                return expanded

    return expanded

# -----------------------------
# ROUTES
# -----------------------------
@app.post("/ask")
def ask(data: Query):
    t0_total = time.perf_counter()
    
    q = (data.question or "").strip()
    if not q:
        return {"answer": "Please enter a question.", "sources": []}

    q_for_retrieval = build_retrieval_query(q, data.history)

    is_global_scope = (data.courseid == 0)
    
    effective_priority_sources = [] if is_global_scope else PRIORITY_SOURCES

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

    queries = [q_for_retrieval]

    q_kw = build_keyword_query(q_for_retrieval)
    if q_kw and q_kw.lower() != q_for_retrieval.lower():
        queries.append(q_kw)

    q2 = ""  
    if ENABLE_QUERY_REWRITE:
        q2 = ollama_rewrite_query_global(q_for_retrieval) if is_global_scope else ollama_rewrite_query_course(q_for_retrieval)
        if q2 and q2.lower() not in [x.lower() for x in queries]:
            queries.append(q2)

    q_mix = " ".join([x for x in [q_for_retrieval, q_kw, q2] if x]).strip()

    t0_retrieval = time.perf_counter()
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
    
    retrieval_ms = round((time.perf_counter() - t0_retrieval) * 1000, 1)

    want_contacts = is_contacts_question(q_for_retrieval)
    want_policy = is_policy_question(q_for_retrieval)
    want_eligibility = is_eligibility_question(q_for_retrieval)
    
    additive_followup = want_contacts and is_additive_followup(q)
    known_names, known_emails = extract_known_contact_entities(data.history) if want_contacts else (set(), set())
    
    if want_contacts:
        MAX_CHUNKS_LOCAL = 8
    else:
        MAX_CHUNKS_LOCAL = MAX_CHUNKS

    merged = {}
    seen_sources = set()
    
    t0_rerank = time.perf_counter()

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

            # Policy/global-specific scoring
            if want_policy or is_global_scope:
                score += policy_chunk_quality(doc, meta, q_for_retrieval, is_global_scope=is_global_scope)

            # Contact-specific scoring
            if want_contacts:
                score += contact_chunk_quality(doc, meta)

                if EMAIL_RE.search(doc) and not TEACHER_LABEL_RE.search(doc):
                    score -= 0.05

                if additive_followup:
                    score += contact_novelty_bonus(doc, known_names, known_emails)

            # Canonical priority-source boosts
            if want_policy and is_priority_source(src, effective_priority_sources):
                score += 0.30

            if is_priority_source(src, effective_priority_sources):
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
    
    if want_policy or is_global_scope:
        regulatory_candidates = [
            c for c in candidates
            if is_regulatory_source((c[1] or {}).get("source", ""))
        ]
        if regulatory_candidates:
            candidates = regulatory_candidates
            
    if want_policy or is_global_scope:
        policy_candidates = [
            c for c in candidates
            if policy_chunk_quality(c[0], c[1], q_for_retrieval, is_global_scope=is_global_scope) > 0
        ]
        if policy_candidates:
            candidates = policy_candidates
            
    if want_eligibility:
        eligibility_candidates = [
            c for c in candidates
            if ACCESS_CUE_RE.search(c[0] or "")
        ]
        if eligibility_candidates:
            candidates = eligibility_candidates

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
        if is_priority_source((c[1] or {}).get("source", ""), effective_priority_sources)
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
                doc, meta, dist, score = c
                doc = doc or ""
                hits = 0

                if TEACHER_LABEL_RE.search(doc):
                    hits += 2
                if NOV_AFFIL_EMAIL_RE.search(doc):
                    hits += 2
                if EMAIL_RE.search(doc):
                    hits += 1
                if EXAMPLE_EMAIL_RE.search(doc):
                    hits -= 2
                if EXERCISE_TABLE_RE.search(doc):
                    hits -= 1

                if additive_followup:
                    hits += int(contact_novelty_bonus(doc, known_names, known_emails) * 10)

                return (-hits, -score, dist)

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
            
    if want_contacts:
        top = expand_same_page_siblings(collection, top, max_extra=6)
        
    if want_policy or want_eligibility or is_global_scope:
        top = expand_adjacent_regulation_pages(collection, top, max_extra=4)
        top.sort(key=lambda x: (-x[3], x[2]))

    context, used_sources = pack_context(
        top,
        q_mix,
        mode="contacts" if want_contacts else "generic"
    )
    
    rerank_context_ms = round((time.perf_counter() - t0_rerank) * 1000, 1)

    if want_contacts and additive_followup and not source_map_has_new_contact_payload(used_sources, known_names, known_emails):
        fallback_top = [
            c for c in candidates
            if contact_novelty_bonus(c[0], known_names, known_emails) > 0
        ]
        fallback_top.sort(key=lambda x: (-(x[3] + contact_novelty_bonus(x[0], known_names, known_emails)), x[2]))
        fallback_top = fallback_top[:6]

        if fallback_top:
            fallback_top = expand_same_page_siblings(collection, fallback_top, max_extra=8)

            context, used_sources = pack_context(
                fallback_top,
                q_mix,
                mode="contacts"
            )

    elif want_contacts and not source_map_has_contact_payload(used_sources):
        fallback_top = [
            c for c in candidates
            if contact_chunk_quality(c[0], c[1]) > 0.10
        ]
        fallback_top.sort(key=lambda x: (-x[3], x[2]))
        fallback_top = fallback_top[:6]

        if fallback_top:
            fallback_top = expand_same_page_siblings(collection, fallback_top, max_extra=8)

            context, used_sources = pack_context(
                fallback_top,
                q_mix,
                mode="contacts"
            )
    history_block = build_history_block(data.history)
    system_prompt = build_system_prompt(0 if is_global_scope else data.courseid)
    
    already_mentioned_block = ""
    if want_contacts and known_names:
        already_mentioned_block = "ALREADY_MENTIONED_IN_CHAT:\n" + "\n".join(
            f"- {name}" for name in sorted(known_names)
        ) + "\n\n"

    prompt = f"""{system_prompt}

{already_mentioned_block}{history_block}CONTEXT:
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
- If the user is asking for additional or other people/items, do not simply repeat previously mentioned items unless needed for clarity.
- In that case, look for additional supported items not already mentioned in the chat.
- If no additional supported items exist in the CONTEXT, say so clearly.

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
    t0_generation = time.perf_counter()
    
    try:
        answer = ollama_generate(prompt).strip()
        generation_ms = round((time.perf_counter() - t0_generation) * 1000, 1)
    except Exception as e:
        resp = {"answer": "Error: LLM generation failed."}
        if DEBUG:
            resp["debug"] = str(e)
        return resp

    if not answer:
        return {"answer": "Error: empty response from model."}

    used_source_ids, clean_answer = extract_used_source_ids(answer, used_sources)
    used_sources_from_model = bool(used_source_ids)

    if used_source_ids:
        selected_items = [item for item in used_sources if item["id"] in used_source_ids]

        # In global/policy mode, prefer regulatory sources even when model returned IDs.
        if want_policy or is_global_scope:
            regulatory_selected = [
                item for item in selected_items
                if is_regulatory_source(item.get("source", ""))
            ]
            if regulatory_selected:
                selected_items = regulatory_selected

        final_sources = format_sources(selected_items)

    else:
        if clean_answer.strip() != no_info_text(is_global_scope):
            fallback_scored = simple_source_ranking(clean_answer, q, used_sources)
            fallback_items = [item for item, _score in fallback_scored]

            # In policy/global mode, keep only normative chunks that match policy semantics
            if want_policy or is_global_scope:
                filtered_items = [
                    item for item in fallback_items
                    if policy_chunk_quality(item.get("content", ""), item, q_for_retrieval, is_global_scope=is_global_scope) > 0
                ]
                if filtered_items:
                    fallback_items = filtered_items

            fallback_items = fallback_items[:3]
            final_sources = format_sources(fallback_items)
            used_source_ids = [item["id"] for item in fallback_items]
        else:
            final_sources = []
            
    total_ms = round((time.perf_counter() - t0_total) * 1000, 1)

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
            "q_for_retrieval": q_for_retrieval,
            "want_policy": want_policy,
            "want_contacts": want_contacts,
            "want_eligibility": want_eligibility,
            "best_dist": best_dist,
            "effective_priority_sources": effective_priority_sources,
            "top_sources": used_sources,
            "used_source_ids": used_source_ids,
            "final_sources": final_sources,
            "source_resolution_mode": "model_used_sources" if used_sources_from_model else "fallback_overlap",
            "timing_ms": {
                "retrieval": retrieval_ms,
                "rerank_and_context": rerank_context_ms,
                "generation": generation_ms,
                "total": total_ms
            },
            "context_preview": context[:800]
        }
    return resp