import sqlite3
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    output_dir TEXT,
    source TEXT
);

CREATE TABLE IF NOT EXISTS sequences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    species TEXT NOT NULL,
    marker TEXT NOT NULL,
    source TEXT,
    accession TEXT,
    organism TEXT,
    title TEXT,
    length INTEGER,
    geo_loc TEXT,
    lat_lon TEXT,
    collection_date TEXT,
    voucher TEXT,
    score REAL,
    sequence TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    UNIQUE (species, marker, accession)
);
"""


def connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def create_run(conn, output_dir, source):
    cur = conn.execute(
        "INSERT INTO runs (started_at, output_dir, source) VALUES (?, ?, ?)",
        (datetime.now(timezone.utc).isoformat(), output_dir, source)
    )
    conn.commit()
    return cur.lastrowid


def extract_sequence(fasta_text):
    lines = fasta_text.strip().splitlines()
    return "".join(lines[1:])


def insert_sequences(conn, run_id, results):
    fetched_at = datetime.now(timezone.utc).isoformat()

    rows = [
        (
            run_id, species, marker, meta.get("source"), meta.get("accession"),
            meta.get("organism"), meta.get("title"), meta.get("length"),
            meta.get("geo_loc"), meta.get(
                "lat_lon"), meta.get("collection_date"),
            meta.get("voucher"), meta.get(
                "score"), extract_sequence(fasta_text),
            fetched_at
        )
        for species, marker, fasta_text, meta in results
    ]

    cur = conn.executemany("""
        INSERT OR IGNORE INTO sequences (
            run_id, species, marker, source, accession, organism, title,
            length, geo_loc, lat_lon, collection_date, voucher, score,
            sequence, fetched_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, rows)
    conn.commit()

    return cur.rowcount
