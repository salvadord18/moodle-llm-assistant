"""
Moodle RAG Ingestion — Generic, course-aware ingestion for Moodle PDFs and native Moodle text
---------------------------------------------------------------------------------------------

What this version improves:
- No assumptions about PDF file names (e.g. no Lecture1.pdf bias)
- Per-course Chroma collections: course_docs_<courseid>
- Extracts PDFs from course context (50) and module context (70)
- Also ingests native Moodle text:
    * course summary
    * section summaries
    * labels
    * pages
    * book chapters
- Indexes page-aware and structured chunks with rich metadata:
    * source
    * source_type
    * page
    * chunk_index
    * courseid
    * contextlevel
    * section_type
    * title_hint
    * contenthash
    * module_name
    * cmid
    * sectionnum
- Chunking is page-first and structure-aware instead of only fixed-size slicing
- Can ingest one course or all courses
- Can rebuild collections cleanly with RESET_COLLECTION=true
"""

import os
import re
from typing import Dict, List, Tuple
from html import unescape

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None
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
CONTACT_RE = re.compile(
    r"\b(lecturer|instructor|professor|teacher|faculty|contact|contacto|contactos|email|office hours?|labs?|practical|docente|docentes|regente)\b",
    re.I
)
ASSESSMENT_RE = re.compile(r"\b(assessment|exam|grade|grading|evaluation|criteria|policy|deadline|submission|deliverable)\b", re.I)
SCHEDULE_RE = re.compile(r"\b(schedule|calendar|week\s*\d+|session|timeline|plan|agenda|date)\b", re.I)
EXAMPLE_RE = re.compile(r"\b(example|exercise|case study|dataset|sample|patients?|orders?|appointments?|payment)\b", re.I)

DR_HEADER_RE = re.compile(
    r"di[aá]rio da rep[uú]blica|www\.dre\.pt",
    re.I
)

REGULATION_START_RE = re.compile(
    r"(anexo\s+regulamento|regulamento\s+n\.º\s*\d+/\d+|regulamento\s+do|regulamento\s+de)",
    re.I
)

ARTICLE_RE = re.compile(r"^\s*Artigo\s+\d+\.º", re.I | re.M)
CHAPTER_RE = re.compile(r"^\s*CAP[IÍ]TULO\s+[IVXLC]+", re.I | re.M)

NEW_DIPLOMA_RE = re.compile(
    r"^\s*(Regulamento\s+n\.º\s*\d+/\d+|Despacho\s+n\.º\s*\d+/\d+|Aviso.*n\.º\s*\d+/\d+)",
    re.I
)

DEADLINE_RE = re.compile(
    r"\b(prazo|prazos|30 dias|60 dias|60 dias úteis|30 dias úteis|até 15 de julho|até 31 de janeiro|até ao final do mês de setembro)\b",
    re.I
)

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

def strip_html_fallback(html: str) -> str:
    """Very simple HTML stripping fallback if BeautifulSoup is unavailable."""
    if not html:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
    text = re.sub(r"</p\s*>", "\n", text, flags=re.I)
    text = re.sub(r"</li\s*>", "\n", text, flags=re.I)
    text = re.sub(r"<li\s*>", "- ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    return normalize(text)


def html_to_clean_text(html: str) -> str:
    """
    Convert Moodle HTML content into clean plain text while preserving:
    - headings
    - lists
    - table rows/cells
    - paragraph structure
    """
    if not html:
        return ""

    html = unescape(html)

    if BeautifulSoup is None:
        return strip_html_fallback(html)

    soup = BeautifulSoup(html, "html.parser")

    # Line breaks
    for tag in soup.find_all(["br"]):
        tag.replace_with("\n")

    # Paragraph/block structure
    for tag in soup.find_all(["p", "div", "section"]):
        tag.insert_after("\n")

    # Lists
    for tag in soup.find_all(["li"]):
        txt = tag.get_text(" ", strip=True)
        tag.clear()
        tag.append(f"- {txt}")
        tag.insert_after("\n")

    # Headings
    for tag in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        tag.insert_before("\n")
        tag.insert_after("\n")

    # Tables: preserve row/cell structure better
    for tag in soup.find_all(["th", "td"]):
        tag.insert_after(" | ")

    for tag in soup.find_all(["tr"]):
        tag.insert_after("\n")

    text = soup.get_text(separator=" ")
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\| *", " | ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return normalize(text)
    """
    Convert Moodle HTML content into clean plain text while preserving basic structure.
    """
    if not html:
        return ""

    html = unescape(html)

    if BeautifulSoup is None:
        return strip_html_fallback(html)

    soup = BeautifulSoup(html, "html.parser")

    # Convert structural tags into explicit separators
    for tag in soup.find_all(["br"]):
        tag.replace_with("\n")

    for tag in soup.find_all(["p", "div", "section"]):
        tag.insert_after("\n")

    for tag in soup.find_all(["li"]):
        if tag.string:
            tag.string.replace_with(f"- {tag.get_text(strip=True)}")
        else:
            tag.insert(0, "- ")
        tag.insert_after("\n")

    for tag in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        tag.insert_before("\n")
        tag.insert_after("\n")

    for tag in soup.find_all(["tr"]):
        tag.insert_after("\n")

    text = soup.get_text(separator=" ")
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return normalize(text)

def format_unix_ts(ts) -> str:
    """
    Convert Moodle Unix timestamp to a readable UTC string.
    Returns '' if empty/invalid.
    """
    try:
        ts = int(ts or 0)
        if ts <= 0:
            return ""
        from datetime import datetime, timezone
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return ""


def join_text_parts(parts: List[str]) -> str:
    """
    Join text pieces while dropping empties.
    """
    return "\n".join([p.strip() for p in parts if p and str(p).strip()])


def remove_running_headers_footers(text: str) -> str:
    lines = []
    for raw in normalize(text).splitlines():
        line = raw.strip()

        if not line:
            continue

        if DR_HEADER_RE.search(line):
            continue

        if re.search(r"^N\.º\s+\d+", line, re.I):
            continue

        if re.search(r"^Pág\.", line, re.I):
            continue

        lines.append(line)

    return "\n".join(lines)


def normalize_deadline_rules(text: str) -> str:
    """
    Canonicalize common deadline/defense rules that may come from table-like layouts.
    """
    text = normalize(text)

    text = re.sub(
        r"Entrega até 15 de julho\s+Defesa no mês de outubro",
        "Entrega até 15 de julho -> Defesa no mês de outubro",
        text,
        flags=re.I
    )

    text = re.sub(
        r"Entrega até 31 de janeiro.*?Defesa no mês de abril",
        "Entrega até 31 de janeiro -> Defesa no mês de abril",
        text,
        flags=re.I | re.S
    )

    return text


def trim_legal_document(page_texts: List[Tuple[int, str]]) -> List[Tuple[int, str]]:
    """
    Keep only the main regulation body in Diário da República-style PDFs.
    Start when regulation-like content begins; stop if another diploma starts later.
    """
    trimmed = []
    started = False

    for page_num, text in page_texts:
        t = normalize(text)

        if not started:
            if REGULATION_START_RE.search(t) or ARTICLE_RE.search(t) or CHAPTER_RE.search(t):
                started = True
                trimmed.append((page_num, t))
            continue

        # stop if another regulation/diploma starts after the relevant one
        if NEW_DIPLOMA_RE.search(t) and not ARTICLE_RE.search(t):
            break

        trimmed.append((page_num, t))

    return trimmed if trimmed else page_texts

def infer_section_type(text: str) -> str:
    tl = (text or "").lower()

    if CONTACT_RE.search(tl):
        return "contact"

    if DEADLINE_RE.search(tl):
        return "deadline"

    if ARTICLE_RE.search(text or "") or CHAPTER_RE.search(text or ""):
        return "regulation"

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
            if len(block) >= MIN_TEXT_CHARS or infer_section_type(block) == "contact":
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

def split_into_legal_blocks(page_text: str) -> List[Dict]:
    """
    Split legal/regulatory text by chapter/article headings.
    Returns structured blocks with legal metadata.
    """
    text = normalize(page_text)
    if not text:
        return []

    lines = text.splitlines()
    blocks = []

    current_lines = []
    current_article = ""
    current_title = ""
    current_chapter = ""

    def flush():
        nonlocal current_lines, current_article, current_title, current_chapter
        body = "\n".join(current_lines).strip()
        if len(body) >= MIN_TEXT_CHARS:
            blocks.append({
                "text": body,
                "article_number": current_article,
                "article_title": current_title,
                "chapter_title": current_chapter,
            })
        current_lines = []

    for line in lines:
        s = line.strip()

        if CHAPTER_RE.match(s):
            flush()
            current_chapter = s
            current_article = ""
            current_title = ""
            current_lines = [s]
            continue

        if ARTICLE_RE.match(s):
            flush()
            current_article = s
            current_title = s
            current_lines = [s]
            continue

        current_lines.append(s)

    flush()
    return blocks


def page_title_hint(page_text: str) -> str:
    for line in normalize(page_text).splitlines()[:6]:
        if 3 <= len(line) <= 120:
            return line
    return ""


def db_connect():
    return psycopg2.connect(**DB)


def get_all_course_ids_with_content() -> List[int]:
    """
    Return all course IDs that have either:
    - PDFs
    - Moodle-native text content (course summary, section summary, modules)
    """
    conn = db_connect()
    cur = conn.cursor()

    sql = f"""
        SELECT DISTINCT courseid
        FROM (
            -- Courses with PDFs
            SELECT
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

            UNION

            -- Courses with course summary
            SELECT c.id AS courseid
            FROM {DB_PREFIX}course c
            WHERE COALESCE(c.summary, '') <> ''

            UNION

            -- Courses with section names/summaries
            SELECT cs.course AS courseid
            FROM {DB_PREFIX}course_sections cs
            WHERE COALESCE(cs.name, '') <> ''
               OR COALESCE(cs.summary, '') <> ''

            UNION

            -- Courses with modules
            SELECT cm.course AS courseid
            FROM {DB_PREFIX}course_modules cm
        ) q
        WHERE courseid IS NOT NULL
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


def get_course_moodle_text_items(courseid: int) -> List[Dict]:
    """
    Return Moodle-native text items for a course, covering:
    - course summary
    - section names + section summaries
    - labels
    - pages
    - book chapters
    - assignments (with due/open/cutoff dates)
    - quizzes (with open/close dates)
    - forums
    - URLs
    - folders
    - resources
    """
    conn = db_connect()
    cur = conn.cursor()
    items: List[Dict] = []

    # --------------------------------------------------
    # 1) Course summary
    # --------------------------------------------------
    sql_course = f"""
        SELECT id, fullname, shortname, summary
        FROM {DB_PREFIX}course
        WHERE id = %s
    """
    cur.execute(sql_course, (courseid,))
    row = cur.fetchone()
    if row:
        cid, fullname, shortname, summary = row
        if summary and str(summary).strip():
            items.append({
                "item_type": "course_summary",
                "item_id": f"course_summary:{cid}",
                "title": f"Course summary - {fullname}",
                "html": summary,
                "courseid": cid,
                "contextlevel": COURSE_CONTEXTLEVEL,
                "cmid": None,
                "sectionnum": None,
                "module_name": "course",
            })

    # --------------------------------------------------
    # 2) Section names + section summaries
    # --------------------------------------------------
    sql_sections = f"""
        SELECT id, course, section, name, summary
        FROM {DB_PREFIX}course_sections
        WHERE course = %s
        ORDER BY section
    """
    cur.execute(sql_sections, (courseid,))
    for section_id, cid, sectionnum, name, summary in cur.fetchall():
        title = name.strip() if name and str(name).strip() else f"Section {sectionnum}"
        html = join_text_parts([
            f"<h2>{title}</h2>",
            summary or ""
        ])
        if html.strip():
            items.append({
                "item_type": "section_summary",
                "item_id": f"section_summary:{section_id}",
                "title": title,
                "html": html,
                "courseid": cid,
                "contextlevel": COURSE_CONTEXTLEVEL,
                "cmid": None,
                "sectionnum": sectionnum,
                "module_name": "course_section",
            })

    # --------------------------------------------------
    # 3) Labels
    # --------------------------------------------------
    sql_labels = f"""
        SELECT
            cm.id AS cmid,
            cm.course,
            cs.section AS sectionnum,
            cs.name AS sectionname,
            l.intro
        FROM {DB_PREFIX}course_modules cm
        JOIN {DB_PREFIX}modules m
          ON cm.module = m.id
        JOIN {DB_PREFIX}label l
          ON cm.instance = l.id
        LEFT JOIN {DB_PREFIX}course_sections cs
          ON cm.section = cs.id
        WHERE m.name = 'label'
          AND cm.course = %s
        ORDER BY cm.id
    """
    cur.execute(sql_labels, (courseid,))
    for cmid, cid, sectionnum, sectionname, intro in cur.fetchall():
        if intro and str(intro).strip():
            html = join_text_parts([
                f"<h2>{sectionname}</h2>" if sectionname else "",
                intro
            ])
            items.append({
                "item_type": "label",
                "item_id": f"label:{cmid}",
                "title": f"Label {cmid}" if not sectionname else f"{sectionname} - Label {cmid}",
                "html": html,
                "courseid": cid,
                "contextlevel": MODULE_CONTEXTLEVEL,
                "cmid": cmid,
                "sectionnum": sectionnum,
                "module_name": "label",
            })

    # --------------------------------------------------
    # 4) Pages
    # --------------------------------------------------
    sql_pages = f"""
        SELECT
            cm.id AS cmid,
            cm.course,
            cs.section AS sectionnum,
            cs.name AS sectionname,
            p.name,
            p.intro,
            p.content
        FROM {DB_PREFIX}course_modules cm
        JOIN {DB_PREFIX}modules m
          ON cm.module = m.id
        JOIN {DB_PREFIX}page p
          ON cm.instance = p.id
        LEFT JOIN {DB_PREFIX}course_sections cs
          ON cm.section = cs.id
        WHERE m.name = 'page'
          AND cm.course = %s
        ORDER BY cm.id
    """
    cur.execute(sql_pages, (courseid,))
    for cmid, cid, sectionnum, sectionname, name, intro, content in cur.fetchall():
        html = join_text_parts([
            f"<h2>{sectionname}</h2>" if sectionname else "",
            f"<h3>{name}</h3>" if name else "",
            intro or "",
            content or "",
        ])
        if html.strip():
            items.append({
                "item_type": "page",
                "item_id": f"page:{cmid}",
                "title": name.strip() if name and str(name).strip() else f"Page {cmid}",
                "html": html,
                "courseid": cid,
                "contextlevel": MODULE_CONTEXTLEVEL,
                "cmid": cmid,
                "sectionnum": sectionnum,
                "module_name": "page",
            })

    # --------------------------------------------------
    # 5) Book chapters
    # --------------------------------------------------
    sql_books = f"""
        SELECT
            cm.id AS cmid,
            cm.course,
            cs.section AS sectionnum,
            cs.name AS sectionname,
            b.name AS book_name,
            bc.id AS chapterid,
            bc.title,
            bc.content
        FROM {DB_PREFIX}course_modules cm
        JOIN {DB_PREFIX}modules m
          ON cm.module = m.id
        JOIN {DB_PREFIX}book b
          ON cm.instance = b.id
        JOIN {DB_PREFIX}book_chapters bc
          ON bc.bookid = b.id
        LEFT JOIN {DB_PREFIX}course_sections cs
          ON cm.section = cs.id
        WHERE m.name = 'book'
          AND cm.course = %s
        ORDER BY cm.id, bc.pagenum
    """
    try:
        cur.execute(sql_books, (courseid,))
        for cmid, cid, sectionnum, sectionname, book_name, chapterid, chapter_title, content in cur.fetchall():
            if content and str(content).strip():
                html = join_text_parts([
                    f"<h2>{sectionname}</h2>" if sectionname else "",
                    f"<h3>{book_name}</h3>" if book_name else "",
                    f"<h4>{chapter_title}</h4>" if chapter_title else "",
                    content
                ])
                title = f"{book_name} - {chapter_title}" if chapter_title else book_name
                items.append({
                    "item_type": "book_chapter",
                    "item_id": f"book_chapter:{chapterid}",
                    "title": title,
                    "html": html,
                    "courseid": cid,
                    "contextlevel": MODULE_CONTEXTLEVEL,
                    "cmid": cmid,
                    "sectionnum": sectionnum,
                    "module_name": "book",
                })
    except Exception as exc:
        print(f"[WARN] Could not fetch book chapters for course={courseid}: {exc}")

    # --------------------------------------------------
    # 6) Assignments (intro + dates)
    # --------------------------------------------------
    sql_assign = f"""
        SELECT
            cm.id AS cmid,
            cm.course,
            cs.section AS sectionnum,
            cs.name AS sectionname,
            a.name,
            a.intro,
            a.allowsubmissionsfromdate,
            a.duedate,
            a.cutoffdate
        FROM {DB_PREFIX}course_modules cm
        JOIN {DB_PREFIX}modules m
          ON cm.module = m.id
        JOIN {DB_PREFIX}assign a
          ON cm.instance = a.id
        LEFT JOIN {DB_PREFIX}course_sections cs
          ON cm.section = cs.id
        WHERE m.name = 'assign'
          AND cm.course = %s
        ORDER BY cm.id
    """
    try:
        cur.execute(sql_assign, (courseid,))
        for cmid, cid, sectionnum, sectionname, name, intro, allowsubmissionsfromdate, duedate, cutoffdate in cur.fetchall():
            date_text = join_text_parts([
                f"Open from: {format_unix_ts(allowsubmissionsfromdate)}" if format_unix_ts(allowsubmissionsfromdate) else "",
                f"Due date: {format_unix_ts(duedate)}" if format_unix_ts(duedate) else "",
                f"Cut-off date: {format_unix_ts(cutoffdate)}" if format_unix_ts(cutoffdate) else "",
            ])
            html = join_text_parts([
                f"<h2>{sectionname}</h2>" if sectionname else "",
                f"<h3>{name}</h3>" if name else "",
                intro or "",
                f"<p>{date_text}</p>" if date_text else ""
            ])
            if html.strip():
                items.append({
                    "item_type": "assignment",
                    "item_id": f"assign:{cmid}",
                    "title": name.strip() if name and str(name).strip() else f"Assignment {cmid}",
                    "html": html,
                    "courseid": cid,
                    "contextlevel": MODULE_CONTEXTLEVEL,
                    "cmid": cmid,
                    "sectionnum": sectionnum,
                    "module_name": "assign",
                })
    except Exception as exc:
        print(f"[WARN] Could not fetch assignments for course={courseid}: {exc}")

    # --------------------------------------------------
    # 7) Quizzes (intro + dates)
    # --------------------------------------------------
    sql_quiz = f"""
        SELECT
            cm.id AS cmid,
            cm.course,
            cs.section AS sectionnum,
            cs.name AS sectionname,
            q.name,
            q.intro,
            q.timeopen,
            q.timeclose
        FROM {DB_PREFIX}course_modules cm
        JOIN {DB_PREFIX}modules m
          ON cm.module = m.id
        JOIN {DB_PREFIX}quiz q
          ON cm.instance = q.id
        LEFT JOIN {DB_PREFIX}course_sections cs
          ON cm.section = cs.id
        WHERE m.name = 'quiz'
          AND cm.course = %s
        ORDER BY cm.id
    """
    try:
        cur.execute(sql_quiz, (courseid,))
        for cmid, cid, sectionnum, sectionname, name, intro, timeopen, timeclose in cur.fetchall():
            date_text = join_text_parts([
                f"Open date: {format_unix_ts(timeopen)}" if format_unix_ts(timeopen) else "",
                f"Close date: {format_unix_ts(timeclose)}" if format_unix_ts(timeclose) else "",
            ])
            html = join_text_parts([
                f"<h2>{sectionname}</h2>" if sectionname else "",
                f"<h3>{name}</h3>" if name else "",
                intro or "",
                f"<p>{date_text}</p>" if date_text else ""
            ])
            if html.strip():
                items.append({
                    "item_type": "quiz",
                    "item_id": f"quiz:{cmid}",
                    "title": name.strip() if name and str(name).strip() else f"Quiz {cmid}",
                    "html": html,
                    "courseid": cid,
                    "contextlevel": MODULE_CONTEXTLEVEL,
                    "cmid": cmid,
                    "sectionnum": sectionnum,
                    "module_name": "quiz",
                })
    except Exception as exc:
        print(f"[WARN] Could not fetch quizzes for course={courseid}: {exc}")

    # --------------------------------------------------
    # 8) Forums
    # --------------------------------------------------
    sql_forum = f"""
        SELECT
            cm.id AS cmid,
            cm.course,
            cs.section AS sectionnum,
            cs.name AS sectionname,
            f.name,
            f.intro
        FROM {DB_PREFIX}course_modules cm
        JOIN {DB_PREFIX}modules m
          ON cm.module = m.id
        JOIN {DB_PREFIX}forum f
          ON cm.instance = f.id
        LEFT JOIN {DB_PREFIX}course_sections cs
          ON cm.section = cs.id
        WHERE m.name = 'forum'
          AND cm.course = %s
        ORDER BY cm.id
    """
    try:
        cur.execute(sql_forum, (courseid,))
        for cmid, cid, sectionnum, sectionname, name, intro in cur.fetchall():
            html = join_text_parts([
                f"<h2>{sectionname}</h2>" if sectionname else "",
                f"<h3>{name}</h3>" if name else "",
                intro or ""
            ])
            if html.strip():
                items.append({
                    "item_type": "forum",
                    "item_id": f"forum:{cmid}",
                    "title": name.strip() if name and str(name).strip() else f"Forum {cmid}",
                    "html": html,
                    "courseid": cid,
                    "contextlevel": MODULE_CONTEXTLEVEL,
                    "cmid": cmid,
                    "sectionnum": sectionnum,
                    "module_name": "forum",
                })
    except Exception as exc:
        print(f"[WARN] Could not fetch forums for course={courseid}: {exc}")

    # --------------------------------------------------
    # 9) URLs
    # --------------------------------------------------
    sql_url = f"""
        SELECT
            cm.id AS cmid,
            cm.course,
            cs.section AS sectionnum,
            cs.name AS sectionname,
            u.name,
            u.intro,
            u.externalurl
        FROM {DB_PREFIX}course_modules cm
        JOIN {DB_PREFIX}modules m
          ON cm.module = m.id
        JOIN {DB_PREFIX}url u
          ON cm.instance = u.id
        LEFT JOIN {DB_PREFIX}course_sections cs
          ON cm.section = cs.id
        WHERE m.name = 'url'
          AND cm.course = %s
        ORDER BY cm.id
    """
    try:
        cur.execute(sql_url, (courseid,))
        for cmid, cid, sectionnum, sectionname, name, intro, externalurl in cur.fetchall():
            html = join_text_parts([
                f"<h2>{sectionname}</h2>" if sectionname else "",
                f"<h3>{name}</h3>" if name else "",
                intro or "",
                f"<p>URL: {externalurl}</p>" if externalurl else ""
            ])
            if html.strip():
                items.append({
                    "item_type": "url",
                    "item_id": f"url:{cmid}",
                    "title": name.strip() if name and str(name).strip() else f"URL {cmid}",
                    "html": html,
                    "courseid": cid,
                    "contextlevel": MODULE_CONTEXTLEVEL,
                    "cmid": cmid,
                    "sectionnum": sectionnum,
                    "module_name": "url",
                })
    except Exception as exc:
        print(f"[WARN] Could not fetch URLs for course={courseid}: {exc}")

    # --------------------------------------------------
    # 10) Folders
    # --------------------------------------------------
    sql_folder = f"""
        SELECT
            cm.id AS cmid,
            cm.course,
            cs.section AS sectionnum,
            cs.name AS sectionname,
            fo.name,
            fo.intro
        FROM {DB_PREFIX}course_modules cm
        JOIN {DB_PREFIX}modules m
          ON cm.module = m.id
        JOIN {DB_PREFIX}folder fo
          ON cm.instance = fo.id
        LEFT JOIN {DB_PREFIX}course_sections cs
          ON cm.section = cs.id
        WHERE m.name = 'folder'
          AND cm.course = %s
        ORDER BY cm.id
    """
    try:
        cur.execute(sql_folder, (courseid,))
        for cmid, cid, sectionnum, sectionname, name, intro in cur.fetchall():
            html = join_text_parts([
                f"<h2>{sectionname}</h2>" if sectionname else "",
                f"<h3>{name}</h3>" if name else "",
                intro or ""
            ])
            if html.strip():
                items.append({
                    "item_type": "folder",
                    "item_id": f"folder:{cmid}",
                    "title": name.strip() if name and str(name).strip() else f"Folder {cmid}",
                    "html": html,
                    "courseid": cid,
                    "contextlevel": MODULE_CONTEXTLEVEL,
                    "cmid": cmid,
                    "sectionnum": sectionnum,
                    "module_name": "folder",
                })
    except Exception as exc:
        print(f"[WARN] Could not fetch folders for course={courseid}: {exc}")

    # --------------------------------------------------
    # 11) Resources
    # --------------------------------------------------
    sql_resource = f"""
        SELECT
            cm.id AS cmid,
            cm.course,
            cs.section AS sectionnum,
            cs.name AS sectionname,
            r.name,
            r.intro
        FROM {DB_PREFIX}course_modules cm
        JOIN {DB_PREFIX}modules m
          ON cm.module = m.id
        JOIN {DB_PREFIX}resource r
          ON cm.instance = r.id
        LEFT JOIN {DB_PREFIX}course_sections cs
          ON cm.section = cs.id
        WHERE m.name = 'resource'
          AND cm.course = %s
        ORDER BY cm.id
    """
    try:
        cur.execute(sql_resource, (courseid,))
        for cmid, cid, sectionnum, sectionname, name, intro in cur.fetchall():
            html = join_text_parts([
                f"<h2>{sectionname}</h2>" if sectionname else "",
                f"<h3>{name}</h3>" if name else "",
                intro or ""
            ])
            if html.strip():
                items.append({
                    "item_type": "resource",
                    "item_id": f"resource:{cmid}",
                    "title": name.strip() if name and str(name).strip() else f"Resource {cmid}",
                    "html": html,
                    "courseid": cid,
                    "contextlevel": MODULE_CONTEXTLEVEL,
                    "cmid": cmid,
                    "sectionnum": sectionnum,
                    "module_name": "resource",
                })
    except Exception as exc:
        print(f"[WARN] Could not fetch resources for course={courseid}: {exc}")

    cur.close()
    conn.close()
    return items


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
        metadata={
            "courseid": courseid,
            "kind": "moodle_course_docs",
        },
    )

    return name, collection


def pdf_path_from_hash(contenthash: str) -> str:
    return os.path.join(MOODLEDATA_PATH, contenthash[:2], contenthash[2:4], contenthash)


def extract_page_texts(pdf_path: str) -> List[Tuple[int, str]]:
    page_texts = []

    with fitz.open(pdf_path) as doc:
        for idx, page in enumerate(doc, start=1):
            blocks = page.get_text("blocks") or []
            lines = []

            for b in blocks:
                if len(b) >= 5:
                    text = b[4]
                    if text and text.strip():
                        lines.append(text.strip())

            text = normalize("\n".join(lines))
            text = remove_running_headers_footers(text)
            text = normalize_deadline_rules(text)

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
        page_texts = trim_legal_document(page_texts)
    except Exception as exc:
        print(f"[WARN] Could not parse {filename}: {exc}")
        return [], [], []

    for page_num, page_text in page_texts:
        title_hint = page_title_hint(page_text)

        is_legal_like = bool(
            REGULATION_START_RE.search(page_text)
            or ARTICLE_RE.search(page_text)
            or CHAPTER_RE.search(page_text)
        )

        # PAGE-LEVEL FALLBACK CHUNK
        page_rec_id = f"{contenthash}:p{page_num}:page"
        ids.append(page_rec_id)
        docs.append(page_text)
        metas.append({
            "courseid": int(courseid),
            "source": filename,
            "page": int(page_num),
            "chunk_index": -1,
            "contextlevel": int(contextlevel),
            "section_type": infer_section_type(page_text),
            "title_hint": title_hint,
            "contenthash": contenthash,
            "chunk_type": "page",
            "doc_kind": "regulation" if is_legal_like else "generic_pdf",
            "article_number": "",
            "article_title": "",
            "chapter_title": "",
        })

        if is_legal_like:
            blocks = split_into_legal_blocks(page_text)
        else:
            blocks = [{"text": b} for b in split_into_structured_blocks(page_text)]

        for chunk_index, block in enumerate(blocks):
            chunk_text = (block.get("text", "") or "").strip()
            if len(chunk_text) < MIN_TEXT_CHARS:
                continue

            rec_id = f"{contenthash}:p{page_num}:c{chunk_index}"
            ids.append(rec_id)
            docs.append(chunk_text)
            metas.append({
                "courseid": int(courseid),
                "source": filename,
                "page": int(page_num),
                "chunk_index": int(chunk_index),
                "contextlevel": int(contextlevel),
                "section_type": infer_section_type(chunk_text),
                "title_hint": title_hint,
                "contenthash": contenthash,
                "chunk_type": "article" if is_legal_like else "block",
                "doc_kind": "regulation" if is_legal_like else "generic_pdf",
                "article_number": block.get("article_number", ""),
                "article_title": block.get("article_title", ""),
                "chapter_title": block.get("chapter_title", ""),
            })

    return ids, docs, metas

def build_records_for_moodle_text(courseid: int, item: Dict) -> Tuple[List[str], List[str], List[Dict]]:
    """
    Convert one Moodle-native text item into Chroma upsert records.
    """
    raw_html = item.get("html", "") or ""
    cleaned_text = html_to_clean_text(raw_html)

    if len(cleaned_text) < MIN_TEXT_CHARS:
        return [], [], []

    blocks = split_into_structured_blocks(cleaned_text)

    if not blocks:
        return [], [], []

    ids: List[str] = []
    docs: List[str] = []
    metas: List[Dict] = []

    base_id = f"moodle:{courseid}:{item['item_type']}:{item['item_id']}"
    title = item.get("title", "") or item.get("item_type", "Moodle text")
    source_type = item.get("item_type", "moodle_text")
    module_name = item.get("module_name", "") or ""
    cmid = item.get("cmid", None)
    sectionnum = item.get("sectionnum", None)
    contextlevel = int(item.get("contextlevel", COURSE_CONTEXTLEVEL))

    for chunk_index, block in enumerate(blocks):
        rec_id = f"{base_id}:c{chunk_index}"
        ids.append(rec_id)
        docs.append(block)
        metas.append({
            "courseid": int(courseid),
            "source": title,
            "page": -1,
            "chunk_index": int(chunk_index),
            "contextlevel": contextlevel,
            "section_type": infer_section_type(block),
            "title_hint": title,
            "contenthash": "",
            "chunk_type": "block",
            "doc_kind": "moodle_text",
            "article_number": "",
            "article_title": "",
            "chapter_title": "",
            "source_type": source_type,
            "module_name": module_name,
            "cmid": int(cmid) if cmid is not None else -1,
            "sectionnum": int(sectionnum) if sectionnum is not None else -1,
        })

    return ids, docs, metas

def ingest_moodle_text_for_course(collection, courseid: int) -> int:
    """
    Ingest Moodle-native text items into the course collection.
    Returns the number of chunks inserted/upserted.
    """
    items = get_course_moodle_text_items(courseid)
    if not items:
        print(f"[INFO] No Moodle text items found for course {courseid}")
        return 0

    total_chunks = 0
    print(f"[INFO] Ingesting Moodle-native text for course={courseid} ({len(items)} item(s))")

    # small debug summary by type
    type_counts: Dict[str, int] = {}
    for it in items:
        type_counts[it["item_type"]] = type_counts.get(it["item_type"], 0) + 1

    for k, v in sorted(type_counts.items()):
        print(f"  [INFO] {k}: {v} item(s)")

    for item in items:
        ids, docs, metas = build_records_for_moodle_text(courseid, item)
        if not ids:
            continue

        collection.upsert(ids=ids, documents=docs, metadatas=metas)
        total_chunks += len(ids)
        print(f"  [OK] {item['item_type']} - {item['title']}: {len(ids)} chunk(s)")

    return total_chunks


def ingest_course(chroma_client: PersistentClient, courseid: int) -> None:
    pdfs = get_course_pdfs(courseid)
    collection_name, collection = get_collection_for_course(chroma_client, courseid)

    print(f"[INFO] Ingesting course={courseid} into {collection_name}")

    total_chunks = 0

    # -----------------------------------------
    # 1) PDF ingestion
    # -----------------------------------------
    if pdfs:
        print(f"[INFO] Found {len(pdfs)} PDF(s) for course={courseid}")
        for contenthash, filename, contextlevel in pdfs:
            ids, docs, metas = build_records_for_pdf(courseid, contenthash, filename, contextlevel)
            if not ids:
                continue
            collection.upsert(ids=ids, documents=docs, metadatas=metas)
            total_chunks += len(ids)
            print(f"  [OK] PDF {filename}: {len(ids)} chunk(s)")
    else:
        print(f"[INFO] No PDFs found for course {courseid}")

    # -----------------------------------------
    # 2) Moodle-native text ingestion
    # -----------------------------------------
    moodle_chunks = ingest_moodle_text_for_course(collection, courseid)
    total_chunks += moodle_chunks

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
        course_ids = get_all_course_ids_with_content()
        print(f"[INFO] All-courses mode: found {len(course_ids)} course(s) with PDFs")

    for cid in course_ids:
        try:
            ingest_course(chroma, cid)
        except Exception as exc:
            print(f"[ERROR] Failed course={cid}: {exc}")
