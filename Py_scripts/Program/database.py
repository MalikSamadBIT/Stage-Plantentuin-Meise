import sqlite3
from datetime import datetime, timezone

# runs/species/synonyms are safe to create unconditionally - only
# "sequences" might already exist from before species/synonyms/queried_as
# were introduced, so it's handled separately (see _migrate_sequences_table).
BASE_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    output_dir TEXT,
    source TEXT
);

CREATE TABLE IF NOT EXISTS species (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS synonyms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    species_id INTEGER NOT NULL REFERENCES species(id),
    language TEXT,
    name TEXT NOT NULL,
    UNIQUE (species_id, language, name)
);

CREATE VIEW IF NOT EXISTS synonyms_view AS
SELECT
    synonyms.id,
    species.canonical_name AS species,
    synonyms.language,
    synonyms.name
FROM synonyms
JOIN species ON species.id = synonyms.species_id;
"""

SEQUENCES_SCHEMA = """
CREATE TABLE IF NOT EXISTS sequences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    species_id INTEGER NOT NULL REFERENCES species(id),
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
    queried_as TEXT,
    sequence TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    UNIQUE (species_id, marker, accession)
);

CREATE VIEW IF NOT EXISTS sequences_view AS
SELECT
    sequences.id,
    sequences.run_id,
    species.canonical_name AS species,
    sequences.marker,
    sequences.source,
    sequences.accession,
    sequences.organism,
    sequences.title,
    sequences.length,
    sequences.geo_loc,
    sequences.lat_lon,
    sequences.collection_date,
    sequences.voucher,
    sequences.score,
    sequences.queried_as,
    sequences.sequence,
    sequences.fetched_at
FROM sequences
JOIN species ON species.id = sequences.species_id;
"""
# sequences.species is normalized out into its own table (species_id FK)
# so the same canonical species can be found under several synonym names
# (see synonyms table / queried_as) without duplicating the name string
# everywhere - sequences_view re-flattens that back to a plain "species"
# column so existing "SELECT ... FROM sequences" readers (database_tab.py,
# blast_tab.py) don't need to know about the join.


def _sequences_needs_migration(conn):
    # a pre-species/synonyms database has "species" (plain text) but no
    # "species_id" on the sequences table
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(sequences)")}
    return "species" in cols and "species_id" not in cols


def _migrate_sequences_table(conn):
    # rebuild sequences with species_id/queried_as, preserving existing rows
    # - SQLite can't ALTER a column's type/constraints or add a REFERENCES
    # column with data already needing backfill, so this does the classic
    # SQLite migration dance: build the new table, copy+transform data in,
    # drop the old one, rename. Wrapped in one explicit transaction so a
    # failure midway (e.g. a bad row) can't leave a half-built
    # "sequences_new" behind to break the next connect() attempt - SQLite's
    # Python driver auto-commits DDL immediately unless a transaction is
    # opened explicitly first.
    conn.execute("DROP TABLE IF EXISTS sequences_new")

    try:
        conn.execute("BEGIN")

        conn.execute("""
            CREATE TABLE sequences_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL REFERENCES runs(id),
                species_id INTEGER NOT NULL REFERENCES species(id),
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
                queried_as TEXT,
                sequence TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                UNIQUE (species_id, marker, accession)
            )
        """)

        for row in conn.execute("SELECT DISTINCT species FROM sequences"):
            conn.execute(
                "INSERT OR IGNORE INTO species (canonical_name) VALUES (?)",
                (row["species"],)
            )

        conn.execute("""
            INSERT INTO sequences_new (
                id, run_id, species_id, marker, source, accession, organism,
                title, length, geo_loc, lat_lon, collection_date, voucher,
                score, queried_as, sequence, fetched_at
            )
            SELECT
                old.id, old.run_id, species.id, old.marker, old.source,
                old.accession, old.organism, old.title, old.length, old.geo_loc,
                old.lat_lon, old.collection_date, old.voucher, old.score,
                NULL, old.sequence, old.fetched_at
            FROM sequences AS old
            JOIN species ON species.canonical_name = old.species
        """)

        conn.execute("DROP TABLE sequences")
        conn.execute("ALTER TABLE sequences_new RENAME TO sequences")
        conn.commit()
    except Exception:
        conn.rollback()
        conn.execute("DROP TABLE IF EXISTS sequences_new")
        conn.commit()
        raise


def connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    conn.executescript(BASE_SCHEMA)

    if _sequences_needs_migration(conn):
        _migrate_sequences_table(conn)

    conn.executescript(SEQUENCES_SCHEMA)

    return conn


def create_run(conn, output_dir, source):
    cur = conn.execute(
        "INSERT INTO runs (started_at, output_dir, source) VALUES (?, ?, ?)",
        (datetime.now(timezone.utc).isoformat(), output_dir, source)
    )
    conn.commit()
    return cur.lastrowid


def get_or_create_species(conn, canonical_name):
    cur = conn.execute(
        "SELECT id FROM species WHERE canonical_name = ?", (canonical_name,)
    )
    row = cur.fetchone()
    if row:
        return row["id"]

    cur = conn.execute(
        "INSERT INTO species (canonical_name) VALUES (?)", (canonical_name,)
    )
    conn.commit()
    return cur.lastrowid


def add_synonyms(conn, canonical_name, synonyms):
    """
    synonyms: {language: name}, as returned by synonym_client.search_synonyms
    for a single species. Returns the species_id the synonyms were attached to.
    """

    species_id = get_or_create_species(conn, canonical_name)

    rows = [
        (species_id, language, name)
        for language, name in synonyms.items()
        if name
    ]

    if rows:
        conn.executemany(
            "INSERT OR IGNORE INTO synonyms (species_id, language, name) "
            "VALUES (?, ?, ?)",
            rows
        )
        conn.commit()

    return species_id


def extract_sequence(fasta_text):
    lines = fasta_text.strip().splitlines()
    return "".join(lines[1:])


def insert_sequences(conn, run_id, results):
    fetched_at = datetime.now(timezone.utc).isoformat()

    species_id_cache = {}
    rows = []

    for species, marker, fasta_text, meta in results:
        if species not in species_id_cache:
            species_id_cache[species] = get_or_create_species(conn, species)
        species_id = species_id_cache[species]

        rows.append((
            run_id, species_id, marker, meta.get("source"), meta.get("accession"),
            meta.get("organism"), meta.get("title"), meta.get("length"),
            meta.get("geo_loc"), meta.get(
                "lat_lon"), meta.get("collection_date"),
            meta.get("voucher"), meta.get("score"), meta.get("queried_as"),
            extract_sequence(fasta_text), fetched_at
        ))

    cur = conn.executemany("""
        INSERT OR IGNORE INTO sequences (
            run_id, species_id, marker, source, accession, organism, title,
            length, geo_loc, lat_lon, collection_date, voucher, score,
            queried_as, sequence, fetched_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, rows)
    conn.commit()

    return cur.rowcount
