"""
Moodle RAG Ingestion — Per-course collections for one or all Moodle courses
-------------------------------------------------------------------------

Features:
- Uses Chroma local embeddings (DefaultEmbeddingFunction)
- Stores documents + metadatas only (no manual embeddings)
- Creates one collection per course: course_docs_<courseid>
- If TARGET_COURSE_ID is set (>0), ingests only that course
- If TARGET_COURSE_ID is not set or is 0, ingests ALL courses with PDFs
- Looks for PDFs in BOTH:
    - course context (contextlevel = 50)
    - module/activity context (contextlevel = 70)
- Supports RESET_COLLECTION=true to rebuild collections cleanly
"""

import os
import re
import fitz
import psycopg2
from chromadb import PersistentClient
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

# -----------------------------
# CONFIG
# -----------------------------
MOODLEDATA_PATH = "/var/www/moodledata/filedir"
CHROMA_DB_PATH = "/var/www/moodledata/chroma_db"

# If 0 or missing => ingest all courses
TARGET_COURSE_ID = int(os.getenv("TARGET_COURSE_ID", "0"))

# If true => delete existing collection(s) before re-ingesting
RESET_COLLECTION = os.getenv("RESET_COLLECTION", "false").lower() == "true"

# Moodle DB prefix
DB_PREFIX = os.getenv("MOODLE_DB_PREFIX", "m_")

DB = {
    "host": os.getenv("MOODLE_DB_HOST", "db"),
    "port": int(os.getenv("MOODLE_DB_PORT", "5432")),
    "dbname": os.getenv("MOODLE_DB_NAME", "moodle"),
    "user": os.getenv("MOODLE_DB_USER", "moodle"),
    "password": os.getenv("MOODLE_DB_PASSWORD", "CHANGE_ME"),
}

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 175

# Moodle context levels
COURSE_CONTEXTLEVEL = 50
MODULE_CONTEXTLEVEL = 70

# -----------------------------
# HELPERS
# -----------------------------
def normalize(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def chunk_text(text: str, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    chunks = []
    start = 0
    while start < len(text):
        end = start + size
        chunks.append(text[start:end])
        start = end - overlap
        if start < 0:
            start = 0
        if start >= len(text):
            break
    return chunks


def db_connect():
    return psycopg2.connect(**DB)


def get_all_course_ids_with_pdfs():
    """
    Return all course IDs that have at least one PDF either:
    - directly in course context
    - in a module/activity that belongs to the course
    """
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


def get_course_pdfs(courseid: int):
    """
    Return (contenthash, filename) for PDFs belonging to a course, either via:
    - course context
    - module context mapped through course_modules.course
    """
    conn = db_connect()
    cur = conn.cursor()

    sql = f"""
        SELECT DISTINCT f.contenthash, f.filename
        FROM {DB_PREFIX}files f
        JOIN {DB_PREFIX}context c
          ON f.contextid = c.id
        LEFT JOIN {DB_PREFIX}course_modules cm
          ON c.contextlevel = %s
         AND c.instanceid = cm.id
        WHERE f.filename LIKE '%%.pdf'
          AND f.filesize > 0
          AND (
                (c.contextlevel = %s AND c.instanceid = %s)
                OR
                (c.contextlevel = %s AND cm.course = %s)
              )
        ORDER BY f.filename
    """

    cur.execute(sql, (
        MODULE_CONTEXTLEVEL,
        COURSE_CONTEXTLEVEL, courseid,
        MODULE_CONTEXTLEVEL, courseid,
    ))

    rows = cur.fetchall()
    cur.close()
    conn.close()

    return rows


def get_collection_for_course(chroma_client, courseid: int):
    collection_name = f"course_docs_{courseid}"

    if RESET_COLLECTION:
        try:
            chroma_client.delete_collection(collection_name)
            print(f"[INFO] Deleted existing collection: {collection_name}")
        except Exception:
            pass

    collection = chroma_client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
        embedding_function=embedding_fn
    )
    return collection_name, collection


def ingest_pdf_into_collection(collection, contenthash: str, filename: str):
    sub1 = contenthash[:2]
    sub2 = contenthash[2:4]
    pdf_path = f"{MOODLEDATA_PATH}/{sub1}/{sub2}/{contenthash}"

    if not os.path.exists(pdf_path):
        print(f"[SKIP] Missing file: {pdf_path}")
        return 0

    print(f"[INFO] Processing: {filename}")

    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        print(f"[SKIP] Could not open PDF {filename}: {e}")
        return 0

    text = ""
    for page in doc:
        try:
            text += (page.get_text() or "") + "\n"
        except Exception:
            continue

    text = normalize(text)
    if not text:
        print(f"[SKIP] No text extracted: {filename}")
        return 0

    chunks = chunk_text(text)
    if not chunks:
        print(f"[SKIP] No chunks created: {filename}")
        return 0

    ids = [f"{contenthash}_{i}" for i in range(len(chunks))]
    metadatas = [{"source": filename} for _ in chunks]

    try:
        collection.upsert(ids=ids, documents=chunks, metadatas=metadatas)
        print(f"[OK] Upserted {len(chunks)} chunks from {filename}")
        return len(chunks)
    except Exception as e:
        print(f"[ERROR] Failed to upsert chunks for {filename}: {e}")
        return 0


def ingest_course(chroma_client, courseid: int):
    pdfs = get_course_pdfs(courseid)
    collection_name, collection = get_collection_for_course(chroma_client, courseid)

    print(f"[INFO] Using collection: {collection_name}")
    print(f"[INFO] Found {len(pdfs)} PDFs for course {courseid}.")

    total_chunks = 0
    for contenthash, filename in pdfs:
        total_chunks += ingest_pdf_into_collection(collection, contenthash, filename)

    print(f"[SUCCESS] Course {courseid} ingestion completed. Total chunks: {total_chunks}")
    return {
        "courseid": courseid,
        "collection": collection_name,
        "pdfs": len(pdfs),
        "chunks": total_chunks,
    }


# -----------------------------
# CHROMA INIT
# -----------------------------
chroma = PersistentClient(path=CHROMA_DB_PATH)
embedding_fn = DefaultEmbeddingFunction()


# -----------------------------
# MAIN
# -----------------------------
if __name__ == "__main__":
    if TARGET_COURSE_ID > 0:
        course_ids = [TARGET_COURSE_ID]
        print(f"[INFO] Single-course mode: TARGET_COURSE_ID={TARGET_COURSE_ID}")
    else:
        course_ids = get_all_course_ids_with_pdfs()
        print(f"[INFO] All-courses mode: found {len(course_ids)} course(s) with PDFs.")

    if not course_ids:
        print("[WARN] No courses with PDFs were found.")
        raise SystemExit(0)

    summary = []
    for courseid in course_ids:
        try:
            result = ingest_course(chroma, courseid)
            summary.append(result)
        except Exception as e:
            print(f"[ERROR] Failed course {courseid}: {e}")

    print("\n========== INGEST SUMMARY ==========")
    for item in summary:
        print(
            f"Course {item['courseid']}: "
            f"{item['pdfs']} PDF(s), "
            f"{item['chunks']} chunk(s), "
            f"collection={item['collection']}"
        )

    print("[DONE] Moodle ingestion finished.")
