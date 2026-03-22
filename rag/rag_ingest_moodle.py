"""
Improved Moodle RAG PDF Ingestion Script
-----------------------------------------

This script:
1. Connects to Moodle PostgreSQL (inside moodle-docker)
2. Retrieves only the PDF files belonging to one course
3. Loads the PDF from moodledata/filedir
4. Cleans text and chunks it with overlap
5. Generates embeddings through Ollama
6. Stores documents + embeddings + metadata in ChromaDB

Run this script INSIDE the 'webserver' container.
"""

import os
import fitz  # PyMuPDF
import psycopg2
import requests
from chromadb import PersistentClient

# ----------------------------------------------------
# CONFIG
# ----------------------------------------------------
MOODLEDATA_PATH = "/var/www/moodledata/filedir"
CHROMA_DB_PATH = "/rag_vectordb"
TARGET_COURSE_ID = 2  # <--- important

DB = {
    "host": "db",
    "port": 5432,
    "dbname": "moodle",
    "user": "moodle",
    "password": "CHANGE_ME"
}

chroma = PersistentClient(path=CHROMA_DB_PATH)
collection_name = f"course_docs_{TARGET_COURSE_ID}"

try:
    collection = chroma.get_collection(collection_name)
    print(f"[INFO] Loaded collection: {collection_name}")
except:
    print(f"[INFO] Creating collection: {collection_name}")
    collection = chroma.create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"}
    )

# ----------------------------------------------------
# EMBEDDING FUNCTION
# ----------------------------------------------------
def embed(text: str):
    """Generate embedding using Ollama."""
    r = requests.post(
        "http://host.docker.internal:11434/api/embed",
        json={"model": "nomic-embed-text", "input": text}
    )
    return r.json()["embeddings"][0]

# ----------------------------------------------------
# DATABASE QUERY
# ----------------------------------------------------
def get_course_pdfs():
    """Return list of (contenthash, filename, contextid) for TARGET_COURSE_ID."""
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

# ----------------------------------------------------
# CHUNKING
# ----------------------------------------------------
def chunk_text(text, size=1500, overlap=200):
    """Split text into overlapping chunks."""
    chunks = []
    start = 0

    while start < len(text):
        end = start + size
        chunks.append(text[start:end])
        start = end - overlap

    return chunks

# ----------------------------------------------------
# PROCESS PDF
# ----------------------------------------------------
def ingest_pdf(contenthash, filename):
    """Read PDF, chunk, embed, store in Chroma."""
    sub1 = contenthash[:2]
    sub2 = contenthash[2:4]

    pdf_path = f"{MOODLEDATA_PATH}/{sub1}/{sub2}/{contenthash}"

    if not os.path.exists(pdf_path):
        print(f"[SKIP] Missing: {pdf_path}")
        return

    print(f"[INFO] Processing {filename}")

    doc = fitz.open(pdf_path)
    fulltext = ""

    for page in doc:
        txt = page.get_text()
        if txt:
            fulltext += txt + "\n"

    chunks = chunk_text(fulltext)
    embeddings = [embed(chunk) for chunk in chunks]

    metadatas = [{"source": filename} for _ in chunks]
    ids = [f"{contenthash}_{i}" for i in range(len(chunks))]

    collection.add(
        documents=chunks,
        metadatas=metadatas,
        ids=ids,
        embeddings=embeddings
    )

# ----------------------------------------------------
# MAIN
# ----------------------------------------------------
if __name__ == "__main__":
    pdfs = get_course_pdfs()
    print(f"[INFO] Found {len(pdfs)} PDFs in course {TARGET_COURSE_ID}")

    for contenthash, filename in pdfs:
        ingest_pdf(contenthash, filename)

    print("[SUCCESS] Ingestion completed.")