import sqlite3
from datetime import datetime, timezone

import customtkinter as ctk
import pandas as pd

try:
    import mysql.connector
except ImportError:
    mysql = None


class DatabaseConfig:
    """
    Describes which database backend the program is currently pointed at -
    a local SQLite file, or a MySQL server - and is shared across tabs the
    same way a plain `db_path` StringVar used to be: `display_var` carries a
    one-line human-readable summary, and tabs `trace_add` it the same way
    they used to trace `db_path`, so switching backend/target in Settings
    still auto-reloads every tab.
    """

    def __init__(self):
        self.backend = "sqlite"
        self.sqlite_path = ""
        self.mysql_host = "localhost"
        self.mysql_port = 3306
        self.mysql_user = ""
        self.mysql_password = ""
        self.mysql_database = ""
        self.display_var = ctk.StringVar(value="")

    def trace_add(self, mode, callback):
        return self.display_var.trace_add(mode, callback)

    def is_configured(self):
        if self.backend == "mysql":
            return bool(
                self.mysql_host and self.mysql_user and self.mysql_database)
        return bool(self.sqlite_path)

    def refresh_display(self):
        if self.backend == "mysql":
            if self.is_configured():
                text = (f"MySQL: {self.mysql_user}@{self.mysql_host}:"
                        f"{self.mysql_port}/{self.mysql_database}")
            else:
                text = "MySQL (not configured yet - set it up in Settings)"
        else:
            text = self.sqlite_path
        self.display_var.set(text)

    def set_sqlite(self, path):
        self.backend = "sqlite"
        self.sqlite_path = path
        self.refresh_display()

    def set_mysql(self, host, port, user, password, database):
        self.backend = "mysql"
        self.mysql_host = host
        self.mysql_port = port
        self.mysql_user = user
        self.mysql_password = password
        self.mysql_database = database
        self.refresh_display()


class SpeciesList:
    """
    The "current species list" - shared across Fetch FASTA, Synonym search
    and Gap Report the same way DatabaseConfig is, so a species list built
    in one tab can be saved here and loaded into the others instead of
    being re-entered/re-picked up to three times. Tabs keep their own
    CSV/textbox inputs and only touch this when the user explicitly saves
    or loads - nothing here updates automatically as a tab's inputs change.
    """

    def __init__(self):
        self.names = []
        self.source = ""
        self.display_var = ctk.StringVar(value="No shared species list set yet.")

    def trace_add(self, mode, callback):
        return self.display_var.trace_add(mode, callback)

    def set(self, names, source=""):
        self.names = list(dict.fromkeys(n for n in names if n))
        self.source = source
        self.refresh_display()

    def refresh_display(self):
        if not self.names:
            text = "No shared species list set yet."
        else:
            text = f"{len(self.names)} species"
            if self.source:
                text += f" (last saved from {self.source})"
        self.display_var.set(text)


# runs/species/synonyms are safe to create unconditionally - only
# "sequences" might already exist from before species/synonyms/queried_as
# were introduced, so it's handled separately (see _migrate_sequences_table).
# SQLite-only - a fresh MySQL database is always created with the current
# schema (see BASE_SCHEMA_MYSQL), so there's nothing to migrate there.
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

# MySQL equivalents of the schema above. Differences from the SQLite version:
# AUTO_INCREMENT instead of AUTOINCREMENT, CREATE OR REPLACE VIEW instead of
# CREATE VIEW IF NOT EXISTS (MySQL has no "IF NOT EXISTS" for views - REPLACE
# is an idempotent no-op after the first run), and bounded VARCHAR sizes on
# the columns that sit inside a UNIQUE key or foreign key (canonical_name,
# marker, accession) since MySQL/InnoDB can't index unbounded TEXT/BLOB
# columns without an explicit prefix length.
BASE_SCHEMA_MYSQL = """
CREATE TABLE IF NOT EXISTS runs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    started_at VARCHAR(64) NOT NULL,
    output_dir TEXT,
    source VARCHAR(64)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS species (
    id INT AUTO_INCREMENT PRIMARY KEY,
    canonical_name VARCHAR(255) NOT NULL UNIQUE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS synonyms (
    id INT AUTO_INCREMENT PRIMARY KEY,
    species_id INT NOT NULL,
    language VARCHAR(32),
    name VARCHAR(255) NOT NULL,
    UNIQUE KEY uniq_synonym (species_id, language, name),
    FOREIGN KEY (species_id) REFERENCES species(id)
) ENGINE=InnoDB;

CREATE OR REPLACE VIEW synonyms_view AS
SELECT
    synonyms.id,
    species.canonical_name AS species,
    synonyms.language,
    synonyms.name
FROM synonyms
JOIN species ON species.id = synonyms.species_id;
"""

SEQUENCES_SCHEMA_MYSQL = """
CREATE TABLE IF NOT EXISTS sequences (
    id INT AUTO_INCREMENT PRIMARY KEY,
    run_id INT NOT NULL,
    species_id INT NOT NULL,
    marker VARCHAR(64) NOT NULL,
    source VARCHAR(32),
    accession VARCHAR(255),
    organism TEXT,
    title TEXT,
    length INT,
    geo_loc TEXT,
    lat_lon TEXT,
    collection_date TEXT,
    voucher TEXT,
    score REAL,
    queried_as TEXT,
    sequence LONGTEXT NOT NULL,
    fetched_at VARCHAR(64) NOT NULL,
    UNIQUE KEY uniq_sequence (species_id, marker, accession),
    FOREIGN KEY (run_id) REFERENCES runs(id),
    FOREIGN KEY (species_id) REFERENCES species(id)
) ENGINE=InnoDB;

CREATE OR REPLACE VIEW sequences_view AS
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


class SQLiteConn:
    """Thin wrapper so callers use the same surface regardless of backend."""

    backend = "sqlite"

    def __init__(self, path):
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row

    def execute(self, sql, params=()):
        return self._conn.execute(sql, params)

    def executemany(self, sql, seq_of_params):
        return self._conn.executemany(sql, seq_of_params)

    def executescript(self, sql):
        return self._conn.executescript(sql)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


class MySQLConn:
    """
    Same surface as SQLiteConn (execute/executemany/executescript/commit/
    rollback/close, "?" placeholders, dict-style row access, cur.lastrowid)
    so the rest of the codebase doesn't need to know which backend it's
    talking to.
    """

    backend = "mysql"

    def __init__(self, host, port, user, password, database):
        if mysql is None:
            raise RuntimeError(
                "The mysql-connector-python package is required to use a "
                "MySQL database. Install it with: "
                "pip install mysql-connector-python"
            )
        self._conn = mysql.connector.connect(
            host=host, port=port, user=user, password=password,
            database=database
        )

    def execute(self, sql, params=()):
        cur = self._conn.cursor(dictionary=True, buffered=True)
        cur.execute(sql.replace("?", "%s"), params)
        return cur

    def executemany(self, sql, seq_of_params):
        cur = self._conn.cursor()
        cur.executemany(sql.replace("?", "%s"), list(seq_of_params))
        return cur

    def executescript(self, sql):
        # mysql-connector has no executescript() - split on ";" and run each
        # statement in turn (fine here since the schema strings above are
        # ours, not arbitrary user SQL with embedded semicolons in strings).
        cur = self._conn.cursor()
        for statement in sql.split(";"):
            statement = statement.strip()
            if statement:
                cur.execute(statement)
        self._conn.commit()

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


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


def _connect_sqlite(path):
    conn = SQLiteConn(path)

    conn.executescript(BASE_SCHEMA)

    if _sequences_needs_migration(conn):
        _migrate_sequences_table(conn)

    conn.executescript(SEQUENCES_SCHEMA)

    return conn


def _connect_mysql(config):
    conn = MySQLConn(
        config.mysql_host, config.mysql_port, config.mysql_user,
        config.mysql_password, config.mysql_database
    )

    conn.executescript(BASE_SCHEMA_MYSQL)
    conn.executescript(SEQUENCES_SCHEMA_MYSQL)

    return conn


def connect(source):
    """
    source: either a DatabaseConfig instance (the shared program-wide
    backend choice made in the Settings tab - SQLite or MySQL), or a plain
    SQLite file path string for callers that manage their own file
    selection independently of the Settings tab (e.g. blast_tab.py).
    """
    if isinstance(source, DatabaseConfig):
        if source.backend == "mysql":
            return _connect_mysql(source)
        return _connect_sqlite(source.sqlite_path)

    return _connect_sqlite(source)


def _insert_ignore_into(conn, table):
    # SQLite and MySQL spell "insert, but silently skip on a UNIQUE
    # conflict" differently
    return f"INSERT IGNORE INTO {table}" if conn.backend == "mysql" \
        else f"INSERT OR IGNORE INTO {table}"


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
        f"{_insert_ignore_into(conn, 'species')} (canonical_name) VALUES (?)",
        (canonical_name,)
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
            f"{_insert_ignore_into(conn, 'synonyms')} "
            "(species_id, language, name) VALUES (?, ?, ?)",
            rows
        )
        conn.commit()

    return species_id


def get_synonym_names(conn, species_name):
    """
    Returns the other known synonym/vernacular names on file for a species
    (any language), resolved the same way count_sequences_by_marker
    resolves a name - by canonical name or by an already-known synonym -
    excluding the queried name itself. Used to retry a lookup under an
    alternate name (e.g. an observation-site search) when the name as
    typed doesn't match, the same way count_sequences_by_marker already
    lets sequence lookups succeed under any name variant on file.
    """
    rows = conn.execute("""
        SELECT DISTINCT name
        FROM synonyms_view
        WHERE (
            LOWER(species) = LOWER(?)
            OR LOWER(species) IN (
                SELECT LOWER(species) FROM synonyms_view WHERE LOWER(name) = LOWER(?)
            )
        )
        AND LOWER(name) != LOWER(?)
    """, (species_name, species_name, species_name)).fetchall()

    return [row["name"] for row in rows]


def get_sequences_for_species(conn, species_name, marker):
    """
    Returns [sequence, ...] on file for the given species and marker,
    matched the same way count_sequences_by_marker matches species names
    (canonical name, synonym, or queried_as).
    """
    rows = conn.execute("""
        SELECT sequence
        FROM sequences_view
        WHERE marker = ?
          AND (
            LOWER(species) = LOWER(?)
            OR LOWER(queried_as) = LOWER(?)
            OR LOWER(species) IN (
                SELECT LOWER(species) FROM synonyms_view WHERE LOWER(name) = LOWER(?)
            )
          )
    """, (marker, species_name, species_name, species_name)).fetchall()

    return [row["sequence"] for row in rows]


def _species_in_genus(conn, genus):
    """
    Canonical names on file whose first word (the genus) matches genus,
    case-insensitively. Shared by get_congener_sequences (which then
    excludes the target species) and get_genus_sequences (which doesn't).
    """
    genus = genus.strip().lower()
    rows = conn.execute("SELECT canonical_name FROM species").fetchall()
    return [
        row["canonical_name"] for row in rows
        if row["canonical_name"].split()[0].lower() == genus
    ]


def get_congener_sequences(conn, species_name, marker):
    """
    Returns [(other_species_name, sequence), ...] for every sequence on
    file, for the given marker, belonging to a different species in the
    same genus as species_name - genus is derived from the first word of
    canonical_name, so species_name is expected to already be a canonical
    name (as opposed to a synonym) here. Excludes species_name itself.
    Empty list if no congeners are on file - callers treat that as
    "insufficient data", not an error.
    """
    genus = species_name.strip().split()[0]
    target = species_name.strip().lower()

    congener_names = [
        name for name in _species_in_genus(conn, genus)
        if name.strip().lower() != target
    ]

    if not congener_names:
        return []

    placeholders = ",".join("?" for _ in congener_names)
    rows = conn.execute(f"""
        SELECT species, sequence
        FROM sequences_view
        WHERE marker = ?
          AND species IN ({placeholders})
    """, (marker, *congener_names)).fetchall()

    return [(row["species"], row["sequence"]) for row in rows]


def get_genus_sequences(conn, genus, marker):
    """
    Returns [(species_name, accession, sequence), ...] for every sequence
    on file, for the given marker, belonging to any species in genus
    (including all of them, unlike get_congener_sequences which excludes
    one target species). Used to build a genus-wide neighbor-joining guide
    tree - see gap_analysis.build_genus_guide_tree.
    """
    member_names = _species_in_genus(conn, genus)
    if not member_names:
        return []

    placeholders = ",".join("?" for _ in member_names)
    rows = conn.execute(f"""
        SELECT species, accession, sequence
        FROM sequences_view
        WHERE marker = ?
          AND species IN ({placeholders})
    """, (marker, *member_names)).fetchall()

    return [(row["species"], row["accession"], row["sequence"]) for row in rows]


def count_sequences_by_marker(conn, species_name):
    """
    Returns [(marker, count), ...] for the given species name, matched
    case-insensitively against either its canonical name or any synonym/
    queried_as name on file - so it works regardless of which name variant
    the sequences were originally fetched under.
    """
    rows = conn.execute("""
        SELECT marker, COUNT(*) AS count
        FROM sequences_view
        WHERE LOWER(species) = LOWER(?)
           OR LOWER(queried_as) = LOWER(?)
           OR LOWER(species) IN (
                SELECT LOWER(species) FROM synonyms_view WHERE LOWER(name) = LOWER(?)
           )
        GROUP BY marker
        ORDER BY marker
    """, (species_name, species_name, species_name)).fetchall()

    return [(row["marker"], row["count"]) for row in rows]


def extract_sequence(fasta_text):
    lines = fasta_text.strip().splitlines()
    return "".join(lines[1:])


def insert_sequences(conn, run_id, results):
    if not results:
        return 0

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

    cur = conn.executemany(
        f"{_insert_ignore_into(conn, 'sequences')} ("
        "run_id, species_id, marker, source, accession, organism, title, "
        "length, geo_loc, lat_lon, collection_date, voucher, score, "
        "queried_as, sequence, fetched_at"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows
    )
    conn.commit()

    return cur.rowcount


def query_df(conn, sql, params=()):
    """
    Runs a SELECT and returns the result as a pandas DataFrame, regardless
    of backend. Doesn't use pandas.read_sql_query directly - that only
    officially supports a sqlite3.Connection or a SQLAlchemy connectable,
    not an arbitrary DBAPI2 connection like mysql-connector's.
    """
    rows = conn.execute(sql, params).fetchall()
    return pd.DataFrame([dict(row) for row in rows])
