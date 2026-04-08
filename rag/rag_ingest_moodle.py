"""
Moodle RAG Ingestion — Generic, course-aware ingestion for Moodle PDFs
---------------------------------------------------------------------

What this version improves:
- No assumptions about PDF file names (e.g. no Lecture1.pdf bias)
- Per-course Chroma collections: course_docs_<courseid>
- Extracts PDFs from course context (50) and module context (70)
- Indexes page-aware chunks with rich metadata:
    * source
    * page
    * chunk_index
    * courseid
    * contextlevel
    * section_type
    * title_hint
    * contenthash
- Chunking is page-first and structure-aware instead of only fixed-size slicing
- Can ingest one course or all courses
- Can rebuild collections cleanly with RESET_COLLECTION=true
"""

import os
import re
from typing import Dict, Iterable, List, Tuple

import fitz
import psycopg2
from chromadb import PersistentClient
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

# -----------------------------
# CONFIG
# -----------------------------
MOODLEDATA_PATH = os.getenv("MOODLEDATA_PATH", "/var/www/moodledata/filedir")
CHROMA_DB_PATH = os.getenv("CHROMA_DB_PATH", "/var/www/moodledata/chroma_db")
TARGET_COURSE_ID = int(os.getenv("TARGET_COURSE_ID", "0"))
RESET_COLLECTION = os.getenv("RESET_COLLECTION", "false").lower() == "true"
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
ASSESSMENT_RE = re.compile(r"\b(assessment|exam|grade|grading|evaluation|criteria|policy|deadline|submission|deliverable)\b", re.I)
SCHEDULE_RE = re.compile(r"\b(schedule|calendar|week\s*\d+|session|timeline|plan|agenda|date)\b", re.I)
EXAMPLE_RE = re.compile(r"\b(example|exercise|case study|dataset|sample|patients?|orders?|appointments?|payment)\b", re.I)

# -----------------------------
# HELPERS
# -----------------------------
def normalize(text: str) -> str:
    """Preserve line structure but normalize whitespace."""
    cleaned = []
    for raw_line in (text or "").splitlines():
        line = re.sub(r"[ \t]+", " ", raw_line).strip()
        if line:
            cleaned.append(line)
    return "\n".join(cleaned)


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


def split_into_structured_blocks(page_text: str, max_chars: int = MAX_BLOCK_CHARS, overlap: int = BLOCK_OVERLAP) -> List[str]:
    """
    Page-first chunking:
    1) preserve headings and short labeled sections,
    2) then split oversized blocks with overlap,
    3) ignore extremely small/noisy chunks.
    """
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


def get_all_course_ids_with_pdfs() -> List[int]:
    conn = db_connect()
    cur = conn.cursor()
    sql = f"""
        SELECT DISTINCT
            CASE
                WHEN c.contextlevel = %s THEN c.instanceid
                WHEN c.contextlevel = %s THEN cm.course
            END AS courseid
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
                c.contextlevel = %s
                OR (c.contextlevel = %s AND cm.course IS NOT NULL)
              )
        ORDER BY courseid
    """
    cur.execute(sql, (
        COURSE_CONTEXTLEVEL,
        MODULE_CONTEXTLEVEL,
        MODULE_CONTEXTLEVEL,
        COURSE_CONTEXTLEVEL,
        MODULE_CONTEXTLEVEL,
    ))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [r[0] for r in rows if r[0] is not None]


def get_course_pdfs(courseid: int) -> List[Tuple[str, str, int]]:
    """Return (contenthash, filename, contextlevel) for all PDFs in a course."""
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


def get_collection_for_course(chroma_client: PersistentClient, courseid: int):
    name = f"course_docs_{courseid}"
    if RESET_COLLECTION:
        try:
            chroma_client.delete_collection(name)
            print(f"[INFO] Deleted existing collection: {name}")
        except Exception:
            pass
    collection = chroma_client.get_or_create_collection(
        name=name,
        embedding_function=DefaultEmbeddingFunction(),
        metadata={"courseid": courseid, "kind": "moodle_course_docs"},
    )
    return name, collection


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


def build_records_for_pdf(courseid: int, contenthash: str, filename: str, contextlevel: int) -> Tuple[List[str], List[str], List[Dict]]:
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
            rec_id = f"{contenthash}:p{page_num}:c{chunk_index}"
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


def ingest_course(chroma_client: PersistentClient, courseid: int) -> None:
    pdfs = get_course_pdfs(courseid)
    if not pdfs:
        print(f"[INFO] No PDFs found for course {courseid}")
        return

    collection_name, collection = get_collection_for_course(chroma_client, courseid)
    print(f"[INFO] Ingesting course={courseid} into {collection_name} ({len(pdfs)} PDF(s))")

    total_chunks = 0
    for contenthash, filename, contextlevel in pdfs:
        ids, docs, metas = build_records_for_pdf(courseid, contenthash, filename, contextlevel)
        if not ids:
            continue
        collection.upsert(ids=ids, documents=docs, metadatas=metas)
        total_chunks += len(ids)
        print(f"  [OK] {filename}: {len(ids)} chunk(s)")

    print(f"[DONE] course={courseid} total_chunks={total_chunks}")


# -----------------------------
# MAIN
# -----------------------------
if __name__ == "__main__":
    chroma = PersistentClient(path=CHROMA_DB_PATH)

    if TARGET_COURSE_ID > 0:
        course_ids = [TARGET_COURSE_ID]
        print(f"[INFO] Single-course mode: TARGET_COURSE_ID={TARGET_COURSE_ID}")
    else:
        course_ids = get_all_course_ids_with_pdfs()
        print(f"[INFO] All-courses mode: found {len(course_ids)} course(s) with PDFs")

    for cid in course_ids:
        try:
            ingest_course(chroma, cid)
        except Exception as exc:
            print(f"[ERROR] Failed course={cid}: {exc}")
