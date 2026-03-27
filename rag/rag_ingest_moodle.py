"""
Moodle RAG Ingestion (Stable) — Chroma Local Embeddings
-------------------------------------------------------

What this script does:
1) Connects to Moodle PostgreSQL (inside moodle-docker)
2) Retrieves PDF files for a specific course (TARGET_COURSE_ID)
3) Extracts text from moodledata/filedir using PyMuPDF
4) Normalizes and chunks text (size + overlap)
5) Adds documents + metadata to ChromaDB WITHOUT providing embeddings
   -> Chroma will compute embeddings locally using its embedding function.

Why this version is stable:
- It does NOT call Ollama /api/embed
- It avoids RemoteDisconnected / ConnectionError issues caused by Ollama embeddings

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
TARGET_COURSE_ID = 2

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


def get_course_pdfs():
    """
    Return list of (contenthash, filename) for a course.
    Uses instanceid mapping to course.
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
        (TARGET_COURSE_ID,),
    )

    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


# -----------------------------
# CHROMA INIT (LOCAL EMBEDDINGS)
# -----------------------------
chroma = PersistentClient(path=CHROMA_DB_PATH)

# Use Chroma's default embedding function (all-MiniLM-L6-v2).
# This will keep query_texts and stored embeddings consistent.
embedding_fn = DefaultEmbeddingFunction()

collection_name = f"course_docs_{TARGET_COURSE_ID}"
collection = chroma.get_or_create_collection(
    name=collection_name,
    metadata={"hnsw:space": "cosine"},
    embedding_function=embedding_fn,
)

print(f"[INFO] Using collection: {collection_name}")


# -----------------------------
# INGESTION
# -----------------------------
def ingest_pdf(contenthash: str, filename: str):
    """Extract text from the PDF, chunk it, and add to Chroma with metadata."""
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

    # IMPORTANT: Do NOT pass embeddings.
    # Chroma will embed locally using embedding_function attached to the collection.
    collection.add(
        ids=ids,
        documents=chunks,
        metadatas=metadatas,
    )


if __name__ == "__main__":
    pdfs = get_course_pdfs()
    print(f"[INFO] Found {len(pdfs)} PDFs for course {TARGET_COURSE_ID}.")

    for contenthash, filename in pdfs:
        ingest_pdf(contenthash, filename)

    print("[SUCCESS] Ingestion completed.")
