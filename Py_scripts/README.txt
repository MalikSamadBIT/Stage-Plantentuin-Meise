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


FEATURES IN DETAIL
-------------------

Fetch FASTA
~~~~~~~~~~~

This is the main pipeline. For each species name you provide, it searches
NCBI GenBank and/or BOLD Systems for each DNA barcode marker you select,
scores the candidate sequences it finds, and saves the best-scoring
one(s) as FASTA (plus optional metadata) to your output folder and/or
the database.

How to use it:

1. Choose a data source (NCBI, BOLD, or NCBI + BOLD). This changes which
   options appear below it:
     - NCBI shows a concurrent-workers field (parallel requests).
     - BOLD and NCBI + BOLD show batch-size and batch-pause fields,
       since BOLD is queried in batches rather than one request at a
       time.
   You can also have species that come up empty on one source
   automatically retried on the other ("Retry NCBI no-matches with
   BOLD" / "Retry BOLD no-matches with NCBI").

2. Provide your species list, either by:
     - selecting a CSV file with a "Name" column, or
     - typing/pasting species names into the text box, comma-separated.
   Both can be used together - the two lists are merged and
   de-duplicated. There's also a shared species list (buttons below the
   text box) that other tabs, such as Maps, can read from and write to,
   so you don't have to retype the same species elsewhere in the app.

3. (Optional) Resume a previous run instead of starting fresh: load the
   no_matches.txt file from an earlier run's output folder to pick up
   only the species/marker combinations that didn't get a match last
   time. If a summary.csv from that run is found in the same folder,
   this run's results are merged into it rather than overwriting it.

4. Pick your markers: check any of ITS, ITS1, ITS2, rbcL, matK, trnL,
   psbA-trnH, and/or add your own in "Extra markers" (comma separated).

5. (Optional) Adjust filters: a candidate sequence whose description
   contains a checked "bad word" (whole genome, chromosome, scaffold,
   contig, assembly by default) is penalized in scoring - add your own
   via "Extra bad words".

6. Choose output options:
     - How to organize the saved FASTA files: per-species folder,
       per-marker subfolder within it, or one flat file. A live preview
       of the resulting folder structure is shown on the right.
     - Whether to also write a metadata text file, a no_matches.txt
       (species/marker pairs with no result), a summary.csv
       (sequence counts per species), and/or a zero_species.csv
       (species that returned nothing at all).
     - Whether to also save results into the configured database
       (SQLite or MySQL, chosen in Settings) in addition to the files.

7. Tune scoring (sliders on the right, 0-100): a target-country boost, a
   neighbor-country boost, a Europe fallback score, a length bonus, and
   a penalty for matching a "bad word" filter. The actual target/
   neighbor country name lists are configured in Settings. For each
   species/marker search, up to "Candidates to score per search" (10 by
   default, set in Settings) results are pulled and scored, and the
   top-scoring "Results to save per marker" (1 by default, set in
   Settings) are kept.

8. Click Run. A status message, progress bar, and estimated time per
   sample are shown while it runs; detailed live logs appear in the
   Terminal tab. If you're processing a lot of species, tune the
   request pacing first in Settings (sleep between requests, worker
   count for NCBI, or batch size/pause for BOLD) to stay under NCBI/
   BOLD's rate limits.

Prerequisite: an NCBI email address must be set in Settings (NCBI
requires this for API access). An NCBI API key is optional but raises
the rate limit from 3 to 10 requests/second.


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
