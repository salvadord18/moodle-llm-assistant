"""
Global RAG Ingestion for Moodle (Faculty rules / regulations)
------------------------------------------------------------

Builds a single Chroma collection called: global_docs

Source selection:
- Detects the Moodle course whose fullname or shortname contains:
  - "Serviços Académicos"
  - "Academic services"
- Matching is accent-insensitive and case-insensitive

What this version improves:
- Reuses the same structured, page-aware chunking logic as rag_ingest_moodle.py
- Extracts PDFs from both course context (50) and module context (70)
- Stores rich metadata:
    * source
    * page
    * chunk_index
    * courseid
    * contextlevel
    * section_type
    * title_hint
    * contenthash
- Writes into a single collection: global_docs
"""

import os
import re
import unicodedata
from typing import Dict, List, Tuple

import fitz
import psycopg2
from chromadb import PersistentClient
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

# -----------------------------
# CONFIG
# -----------------------------
MOODLEDATA_PATH = os.getenv("MOODLEDATA_PATH", "/var/www/moodledata/filedir")
CHROMA_DB_PATH = os.getenv("CHROMA_DB_PATH", "/var/www/moodledata/chroma_db")

# If > 0, force a course id manually (optional override for debugging).
# Keep default = 0 so name-based detection is the normal behaviour.
GLOBAL_SOURCE_COURSE_ID = int(os.getenv("GLOBAL_SOURCE_COURSE_ID", "0"))

GLOBAL_SOURCE_PATTERNS = [
    s.strip() for s in os.getenv(
        "GLOBAL_SOURCE_PATTERNS",
        "Serviços Académicos,Academic services"
    ).split(",") if s.strip()
]

RESET_GLOBAL_COLLECTION = os.getenv("RESET_GLOBAL_COLLECTION", "false").lower() == "true"
DB_PREFIX = os.getenv("MOODLE_DB_PREFIX", "m_")

DB = {
    "host": os.getenv("MOODLE_DB_HOST", "db"),
    "port": int(os.getenv("MOODLE_DB_PORT", "5432")),
    "dbname": os.getenv("MOODLE_DB_NAME", "moodle"),
    "user": os.getenv("MOODLE_DB_USER", "moodle"),
    "password": os.getenv("MOODLE_DB_PASSWORD", "CHANGE_ME"),
}

COURSE_CONTEXTLEVEL = 50
MODULE_CONTEXTLEVEL = 70
MAX_BLOCK_CHARS = int(os.getenv("RAG_MAX_BLOCK_CHARS", "1200"))
BLOCK_OVERLAP = int(os.getenv("RAG_BLOCK_OVERLAP", "160"))
MIN_TEXT_CHARS = int(os.getenv("RAG_MIN_TEXT_CHARS", "30"))

# -----------------------------
# REGEX / LABELS
# -----------------------------
CONTACT_RE = re.compile(r"\b(lecturer|instructor|professor|teacher|faculty|contact|email|office hours?)\b", re.I)
ASSESSMENT_RE = re.compile(r"\b(assessment|exam|grade|grading|evaluation|criteria|policy|deadline|submission|deliverable|regulation|rule)\b", re.I)
SCHEDULE_RE = re.compile(r"\b(schedule|calendar|week\s*\d+|session|timeline|plan|agenda|date)\b", re.I)
EXAMPLE_RE = re.compile(r"\b(example|exercise|case study|dataset|sample|patients?|orders?|appointments?|payment)\b", re.I)

# -----------------------------
# HELPERS
# -----------------------------
def normalize(text: str) -> str:
    cleaned = []
    for raw_line in (text or "").splitlines():
        line = re.sub(r"[ \t]+", " ", raw_line).strip()
        if line:
            cleaned.append(line)
    return "\n".join(cleaned)


def normalize_compare(text: str) -> str:
    """
    Accent-insensitive, case-insensitive normalisation for course name matching.
    Example:
      'Serviços Académicos' -> 'servicos academicos'
    """
    text = (text or "").strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def infer_section_type(text: str) -> str:
    tl = (text or "").lower()
    if CONTACT_RE.search(tl):
        return "contact"
    if ASSESSMENT_RE.search(tl):
        return "assessment"
    if SCHEDULE_RE.search(tl):
        return "schedule"
    if EXAMPLE_RE.search(tl):
        return "example"
    return "concept"


def looks_like_heading(line: str) -> bool:
    if not line:
        return False
    if len(line) > 120:
        return False
    if line.endswith(":"):
        return True
    words = line.split()
    if 1 <= len(words) <= 12 and sum(w[:1].isupper() for w in words) >= max(1, len(words) // 2):
        return True
    if line.isupper() and len(line) <= 80:
        return True
    return False


def split_into_structured_blocks(page_text: str,
                                 max_chars: int = MAX_BLOCK_CHARS,
                                 overlap: int = BLOCK_OVERLAP) -> List[str]:
    text = normalize(page_text)
    if not text:
        return []

    lines = text.splitlines()
    blocks: List[str] = []
    current: List[str] = []

    for line in lines:
        if looks_like_heading(line) and current:
            blocks.append("\n".join(current).strip())
            current = [line]
        else:
            current.append(line)

    if current:
        blocks.append("\n".join(current).strip())

    final_blocks: List[str] = []
    for block in blocks:
        if len(block) <= max_chars:
            if len(block) >= MIN_TEXT_CHARS:
                final_blocks.append(block)
            continue

        start = 0
        while start < len(block):
            end = min(len(block), start + max_chars)
            piece = block[start:end].strip()
            if len(piece) >= MIN_TEXT_CHARS:
                final_blocks.append(piece)
            if end >= len(block):
                break
            start = max(0, end - overlap)

    return final_blocks


def page_title_hint(page_text: str) -> str:
    for line in normalize(page_text).splitlines()[:6]:
        if 3 <= len(line) <= 120:
            return line
    return ""


def db_connect():
    return psycopg2.connect(**DB)


def resolve_global_source_course_id() -> int:
    """
    Resolve the global source course by:
    1) GLOBAL_SOURCE_COURSE_ID if manually forced
    2) Otherwise, detect by course fullname/shortname patterns
       using accent-insensitive and case-insensitive matching
    """
    if GLOBAL_SOURCE_COURSE_ID > 0:
        print(f"[INFO] Using GLOBAL_SOURCE_COURSE_ID override: {GLOBAL_SOURCE_COURSE_ID}")
        return GLOBAL_SOURCE_COURSE_ID

    patterns = [normalize_compare(p) for p in GLOBAL_SOURCE_PATTERNS]
    if not patterns:
        raise RuntimeError("GLOBAL_SOURCE_PATTERNS is empty. Please define at least one pattern.")

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

    matches = []

    for cid, fullname, shortname in rows:
        fullname_n = normalize_compare(fullname or "")
        shortname_n = normalize_compare(shortname or "")

        best_score = 0
        matched_pattern = None

        for pattern in patterns:
            score = 0

            # Exact match strongest
            if fullname_n == pattern or shortname_n == pattern:
                score = 100

            # Startswith next best
            elif fullname_n.startswith(pattern) or shortname_n.startswith(pattern):
                score = 80

            # Contains still acceptable
            elif pattern in fullname_n or pattern in shortname_n:
                score = 60

            if score > best_score:
                best_score = score
                matched_pattern = pattern

        if best_score > 0:
            matches.append({
                "id": int(cid),
                "fullname": fullname or "",
                "shortname": shortname or "",
                "score": best_score,
                "pattern": matched_pattern,
            })

    if not matches:
        raise RuntimeError(
            f"Could not resolve global source course by patterns: {GLOBAL_SOURCE_PATTERNS}"
        )

    # Best score first, then lowest id for deterministic behaviour
    matches.sort(key=lambda x: (-x["score"], x["id"]))

    best = matches[0]

    if len(matches) > 1:
        print("[WARN] Multiple courses matched the global patterns. Candidates:")
        for m in matches[:10]:
            print(
                f"  - id={m['id']} score={m['score']} "
                f"fullname={m['fullname']} shortname={m['shortname']} pattern={m['pattern']}"
            )

    print(
        f"[INFO] Resolved global source course: "
        f"id={best['id']}, fullname={best['fullname']}, shortname={best['shortname']}, pattern={best['pattern']}"
    )
    return int(best["id"])


def get_course_pdfs(courseid: int) -> List[Tuple[str, str, int]]:
    conn = db_connect()
    cur = conn.cursor()
    sql = f"""
        SELECT DISTINCT f.contenthash, f.filename, c.contextlevel
        FROM {DB_PREFIX}files f
        JOIN {DB_PREFIX}context c
          ON f.contextid = c.id
        LEFT JOIN {DB_PREFIX}course_modules cm
          ON c.contextlevel = %s
         AND c.instanceid = cm.id
        WHERE f.filename LIKE '%%.pdf'
          AND f.filesize > 0
          AND f.contenthash IS NOT NULL
          AND (
                (c.contextlevel = %s AND c.instanceid = %s)
                OR
                (c.contextlevel = %s AND cm.course = %s)
              )
        ORDER BY f.filename
    """
    cur.execute(sql, (
        MODULE_CONTEXTLEVEL,
        COURSE_CONTEXTLEVEL,
        courseid,
        MODULE_CONTEXTLEVEL,
        courseid,
    ))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def pdf_path_from_hash(contenthash: str) -> str:
    return os.path.join(MOODLEDATA_PATH, contenthash[:2], contenthash[2:4], contenthash)


def extract_page_texts(pdf_path: str) -> List[Tuple[int, str]]:
    page_texts: List[Tuple[int, str]] = []
    with fitz.open(pdf_path) as doc:
        for idx, page in enumerate(doc, start=1):
            text = normalize(page.get_text("text") or "")
            if text:
                page_texts.append((idx, text))
    return page_texts


def build_records_for_pdf(courseid: int,
                          contenthash: str,
                          filename: str,
                          contextlevel: int) -> Tuple[List[str], List[str], List[Dict]]:
    pdf_path = pdf_path_from_hash(contenthash)
    if not os.path.exists(pdf_path):
        print(f"[WARN] Missing PDF file for hash={contenthash} filename={filename}")
        return [], [], []

    ids: List[str] = []
    docs: List[str] = []
    metas: List[Dict] = []

    try:
        page_texts = extract_page_texts(pdf_path)
    except Exception as exc:
        print(f"[WARN] Could not parse {filename}: {exc}")
        return [], [], []

    for page_num, page_text in page_texts:
        title_hint = page_title_hint(page_text)
        blocks = split_into_structured_blocks(page_text)
        for chunk_index, block in enumerate(blocks):
            rec_id = f"global:{contenthash}:p{page_num}:c{chunk_index}"
            ids.append(rec_id)
            docs.append(block)
            metas.append({
                "courseid": int(courseid),
                "source": filename,
                "page": int(page_num),
                "chunk_index": int(chunk_index),
                "contextlevel": int(contextlevel),
                "section_type": infer_section_type(block),
                "title_hint": title_hint,
                "contenthash": contenthash,
            })

    return ids, docs, metas


def get_global_collection(chroma_client: PersistentClient):
    name = "global_docs"
    if RESET_GLOBAL_COLLECTION:
        try:
            chroma_client.delete_collection(name)
            print(f"[INFO] Deleted existing collection: {name}")
        except Exception:
            pass

    collection = chroma_client.get_or_create_collection(
        name=name,
        embedding_function=DefaultEmbeddingFunction(),
        metadata={"kind": "moodle_global_docs"}
    )
    return name, collection


def ingest_global_course(chroma_client: PersistentClient, courseid: int):
    pdfs = get_course_pdfs(courseid)
    if not pdfs:
        print(f"[INFO] No PDFs found for global source course {courseid}")
        return

    collection_name, collection = get_global_collection(chroma_client)
    print(f"[INFO] Ingesting global source course={courseid} into {collection_name} ({len(pdfs)} PDF(s))")

    total_chunks = 0
    for contenthash, filename, contextlevel in pdfs:
        ids, docs, metas = build_records_for_pdf(courseid, contenthash, filename, contextlevel)
        if not ids:
            continue
        collection.upsert(ids=ids, documents=docs, metadatas=metas)
        total_chunks += len(ids)
        print(f"  [OK] {filename}: {len(ids)} chunk(s)")

    print(f"[DONE] global source course={courseid} total_chunks={total_chunks}")


if __name__ == "__main__":
    chroma = PersistentClient(path=CHROMA_DB_PATH)
    source_course_id = resolve_global_source_course_id()
    ingest_global_course(chroma, source_course_id)
    print("[SUCCESS] Global ingestion completed.")
