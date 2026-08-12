FLORA FETCH
===========

NCBI / BOLD DNA barcode pipeline, developed during an internship at
Plantentuin Meise (Meise Botanic Garden).


WHAT IT DOES
------------

Flora Fetch searches NCBI GenBank and BOLD Systems for DNA barcode
sequences (ITS, rbcL, matK, and other markers) for a list of plant
species, scores and ranks the candidates it finds (by geographic origin,
sequence length, and quality), and builds a reference database you can
browse, query, export, and BLAST against. It was built to help assemble
and maintain a DNA barcode reference collection for the Belgian flora.


TABS AT A GLANCE
-----------------

Home
    Overview and quick links to the other tabs.

Settings
    NCBI credentials, the database backend (SQLite or MySQL), scoring
    weights, target/neighbor country groups, and saved presets.

Fetch FASTA
    The main pipeline - load a species list and markers, then search
    NCBI and/or BOLD and save the best-scoring sequences.

Retrieval Rate
    Charts showing how much sequence coverage you have per species and
    marker after a run.

Synonym search
    Looks up alternate/vernacular names for a species so searches
    aren't limited to its canonical Latin name.

MSA
    Multiple sequence alignment and scoring for a chosen species/marker,
    including a reverse-complement option per sequence.

Database
    Browse, filter, export, query, and transfer (SQLite -> MySQL) the
    sequence database.

BLAST
    Build a local BLAST database from your sequences and search it with
    one query or a batch FASTA file.

Maps
    View species occurrence records on a map and cross-check them
    against what's already in the database.

Gap Report
    Finds species/markers with missing or thin coverage, and assembles
    a Word/PDF report from snapshots pushed by the other tabs.

Terminal
    Live log output while a Fetch FASTA run is in progress.


GETTING STARTED
----------------

1. Settings - enter your NCBI email/API key, and choose or create the
   database that fetched sequences will be saved to.

2. Fetch FASTA - load a species list (CSV or typed) and pick markers,
   then run the pipeline to search and score sequences.

3. Retrieval Rate / Gap Report - see which species/markers still need
   coverage.

4. Database / BLAST / Maps - browse what's been collected, search it,
   and cross-check it against occurrence records.


INSTALLATION
------------

Option A - Run the packaged .exe

    If you have the built "Flora Fetch.exe", just run it - MUSCLE and
    BLAST+ are bundled inside, no extra setup needed.

Option B - Run from source

    Requires Python 3.10+ and the following packages:

        pip install customtkinter pandas biopython pymsaviz pymsa pillow
        requests beautifulsoup4 playwright tkintermapview tkcalendar
        matplotlib reportlab python-docx mysql-connector-python

    Playwright also needs its browser binary installed once:

        playwright install chromium

    You'll also need these external tools available locally, with paths
    matching what msa_tab.py and blast_tab.py expect (MUSCLE_EXE /
    BLAST_BIN):

        - MUSCLE (https://drive5.com/muscle) - used by the MSA tab.
        - NCBI BLAST+
          (https://blast.ncbi.nlm.nih.gov/doc/blast-help/downloadblastdata.html)
          - used by the BLAST tab.

    Then launch the app:

        python Program/gui.py


CHOOSING A DATABASE BACKEND
----------------------------

The Database tab supports two backends, set from Settings:

- SQLite (default) - a single local file, zero setup.

- MySQL - point it at a MySQL/MariaDB server (host, port, user,
  database). The password is never saved to disk, you re-enter it each
  session. If you're hosting the server yourself without root access, a
  user-space install via conda (or the official portable binaries) works
  fine, just make sure the app can reach the host/port you configure,
  either directly or through an SSH tunnel.


NOTES
-----

- Fetched species/marker data and settings are cached locally so a run
  can resume after an interruption.

- Closing the app safely saves your Settings (NCBI credentials excluding
  MySQL password, database backend, and other preferences) before
  exiting.
