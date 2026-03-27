"""
Moodle RAG Ingestion — Generic, Stable, No Special Cases
--------------------------------------------------------

Design:
- Uses Chroma local embeddings (DefaultEmbeddingFunction)
- Adds documents + metadatas only (no embeddings passed)
- Creates per-course collection: course_docs_<courseid>
- Chunking with overlap for better retrieval

Run inside webserver container:
  python3 /rag_ingest_moodle.py
"""

import os
import re
import fitz
import psycopg2
from chromadb import PersistentClient
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

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

CHUNK_SIZE = 2500
CHUNK_OVERLAP = 300

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
    return chunks

def get_course_pdfs():
    conn = psycopg2.connect(**DB)
    cur = conn.cursor()
    cur.execute("""
        SELECT f.contenthash, f.filename
        FROM m_files f
        JOIN m_context c ON f.contextid = c.id
        WHERE c.instanceid = %s
          AND f.filename LIKE '%%.pdf'
          AND f.filesize > 0;
    """, (TARGET_COURSE_ID,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

chroma = PersistentClient(path=CHROMA_DB_PATH)
embedding_fn = DefaultEmbeddingFunction()  # all-MiniLM-L6-v2 default embedding function 

collection_name = f"course_docs_{TARGET_COURSE_ID}"
collection = chroma.get_or_create_collection(
    name=collection_name,
    metadata={"hnsw:space": "cosine"},
    embedding_function=embedding_fn
)

print(f"[INFO] Using collection: {collection_name}")

def ingest_pdf(contenthash: str, filename: str):
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
        print(f"[SKIP] No text extracted: {filename}")
        return

    chunks = chunk_text(text)
    ids = [f"{contenthash}_{i}" for i in range(len(chunks))]
    metadatas = [{"source": filename} for _ in chunks]

    # IMPORTANT: do NOT pass embeddings
    collection.add(ids=ids, documents=chunks, metadatas=metadatas)

if __name__ == "__main__":
    pdfs = get_course_pdfs()
    print(f"[INFO] Found {len(pdfs)} PDFs for course {TARGET_COURSE_ID}.")
    for contenthash, filename in pdfs:
        ingest_pdf(contenthash, filename)
    print("[SUCCESS] Ingestion completed.")