"""
Global RAG Ingestion for Moodle (Faculty rules/norms)
-----------------------------------------------------

This script ingests PDFs from a specific Moodle course (e.g. "Serviços Académicos")
into a single global Chroma collection named: global_docs

Design notes:
- Uses Chroma local embeddings (DefaultEmbeddingFunction)
- Does NOT call Ollama /api/embed (more stable)
- Stores metadata {source: filename} per chunk
- Intended to power the Global chat (courseid = 0)

Run inside the Moodle 'webserver' container.
"""

import os
import re
import fitz  # PyMuPDF
import psycopg2
from chromadb import PersistentClient
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

# -----------------------------
# CONFIG
# -----------------------------
MOODLEDATA_PATH = "/var/www/moodledata/filedir"
CHROMA_DB_PATH = "/var/www/moodledata/chroma_db"

# IMPORTANT: set this to the course id of "Serviços Académicos"
GLOBAL_SOURCE_COURSE_ID = int(os.getenv("GLOBAL_SOURCE_COURSE_ID", "0"))

DB = {
    "host": "db",
    "port": 5432,
    "dbname": "moodle",
    "user": "moodle",
    "password": "CHANGE_ME",
}

CHUNK_SIZE = 3000
CHUNK_OVERLAP = 400


# -----------------------------
# HELPERS
# -----------------------------
def normalize(text: str) -> str:
    """Normalize whitespace to reduce noisy chunk boundaries."""
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP):
    """Split text into overlapping chunks."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + size
        chunks.append(text[start:end])
        start = end - overlap
    return chunks


def get_pdfs_for_course(courseid: int):
    """
    Return list of (contenthash, filename) for a given course.
    Uses context mapping instanceid -> courseid.
    """
    conn = psycopg2.connect(**DB)
    cur = conn.cursor()

    cur.execute(
        """
        SELECT f.contenthash, f.filename
        FROM m_files f
        JOIN m_context c ON f.contextid = c.id
        WHERE c.instanceid = %s
          AND f.filename LIKE '%%.pdf'
          AND f.filesize > 0;
        """,
        (courseid,),
    )

    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


# -----------------------------
# CHROMA INIT (LOCAL EMBEDDINGS)
# -----------------------------
chroma = PersistentClient(path=CHROMA_DB_PATH)
embedding_fn = DefaultEmbeddingFunction()

collection = chroma.get_or_create_collection(
    name="global_docs",
    metadata={"hnsw:space": "cosine"},
    embedding_function=embedding_fn,
)

print("[INFO] Using global collection: global_docs")


# -----------------------------
# INGESTION
# -----------------------------
def ingest_pdf(contenthash: str, filename: str):
    """Extract text, chunk, and add to Chroma with metadata."""
    sub1 = contenthash[:2]
    sub2 = contenthash[2:4]
    pdf_path = f"{MOODLEDATA_PATH}/{sub1}/{sub2}/{contenthash}"

    if not os.path.exists(pdf_path):
        print(f"[SKIP] Missing file: {pdf_path}")
        return

    print(f"[INFO] Processing: {filename}")

    doc = fitz.open(pdf_path)
    text = ""
    for page in doc:
        text += (page.get_text() or "") + "\n"

    text = normalize(text)
    if not text:
        print(f"[SKIP] No text extracted for: {filename}")
        return

    chunks = chunk_text(text)
    ids = [f"{contenthash}_{i}" for i in range(len(chunks))]
    metadatas = [{"source": filename} for _ in chunks]

    collection.upsert(
        ids=ids,
        documents=chunks,
        metadatas=metadatas,
    )


if __name__ == "__main__":
    if GLOBAL_SOURCE_COURSE_ID <= 0:
        raise SystemExit(
            "[ERROR] GLOBAL_SOURCE_COURSE_ID is not set. "
            "Run with: GLOBAL_SOURCE_COURSE_ID=<id> python3 rag_ingest_global.py"
        )

    pdfs = get_pdfs_for_course(GLOBAL_SOURCE_COURSE_ID)
    print(f"[INFO] Found {len(pdfs)} PDFs in global source course {GLOBAL_SOURCE_COURSE_ID}.")

    for contenthash, filename in pdfs:
        ingest_pdf(contenthash, filename)

    print("[SUCCESS] Global ingestion completed.")
