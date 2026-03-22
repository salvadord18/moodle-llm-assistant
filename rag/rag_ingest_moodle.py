"""
RAG Ingestion for Moodle - Optimized Chunking + Metadata
-----------------------------------------------------------

Improvements:
- Larger chunks (3000 chars)
- Overlap (400 chars)
- Normalize text (remove weird spacing)
- Store metadata 'source' per chunk
- Designed for FastAPI RAG v3

Run inside the Moodle 'webserver' container.
"""

import os
import fitz
import psycopg2
import requests
from chromadb import PersistentClient
import re

MOODLEDATA_PATH = "/var/www/moodledata/filedir"
CHROMA_DB_PATH = "/rag_vectordb"
TARGET_COURSE_ID = 2

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

def normalize(text):
    """Normalize whitespace and remove stray characters."""
    text = re.sub(r"\s+", " ", text)
    return text.strip()

def embed(text: str):
    response = requests.post(
        "http://host.docker.internal:11434/api/embed",
        json={"model": "nomic-embed-text", "input": text}
    )
    return response.json()["embeddings"][0]

def chunk_text(text, size=3000, overlap=400):
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

def ingest_pdf(contenthash, filename):
    sub1 = contenthash[:2]
    sub2 = contenthash[2:4]
    pdf_path = f"{MOODLEDATA_PATH}/{sub1}/{sub2}/{contenthash}"

    if not os.path.exists(pdf_path):
        print(f"[SKIP] Missing: {pdf_path}")
        return

    print(f"[INFO] Processing: {filename}")
    doc = fitz.open(pdf_path)

    text = ""
    for page in doc:
        text += page.get_text() + "\n"

    text = normalize(text)
    chunks = chunk_text(text)

    embeddings = [embed(c) for c in chunks]
    metadatas = [{"source": filename} for _ in chunks]
    ids = [f"{contenthash}_{i}" for i in range(len(chunks))]

    collection.add(
        documents=chunks,
        metadatas=metadatas,
        ids=ids,
        embeddings=embeddings
    )

if __name__ == "__main__":
    pdfs = get_course_pdfs()
    print(f"[INFO] Found {len(pdfs)} PDFs.")
    for contenthash, filename in pdfs:
        ingest_pdf(contenthash, filename)
    print("[SUCCESS] Ingestion v3 completed.")