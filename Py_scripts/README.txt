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


Database
~~~~~~~~

Browse, filter, export, query, and migrate the sequence database (SQLite
or MySQL, whichever is active in Settings). Split into three sub-tabs.

View Database:

    - Pick a table (Sequences, Species, Synonyms, or Runs) and click
      "Reload" to load its rows.
    - Type into the filter bar and pick a column (or "(all columns)"),
      then "Apply" to narrow the results - each Apply adds another
      filter on top of the previous ones, shown as removable chips
      above the table. "Clear all" resets them.
    - Click a column header to sort by it; click again to reverse.
    - "Export View to FASTA..." saves whatever's currently shown as a
      FASTA file (only available on the Sequences table).

Transfer Database:

    - One-way copy of the SQLite database configured in Settings into a
      MySQL database, using the separately-installed sqlite3-to-mysql
      package (pip install sqlite3-to-mysql==2.6.0 - the tab shows this
      instruction itself if the package isn't found).
    - Enter the destination MySQL host/port/user/password/database name.
      These are pre-filled from Settings if you've already set MySQL
      details there, but this is an independent destination - it
      doesn't have to be the same server.
    - Optional: a chunk size (rows per batch, useful for large
      databases) and a "truncate existing tables" option to wipe the
      destination tables before copying.
    - A live log shows transfer progress; status turns green on success
      or red with the error on failure.

Query Database:

    - Run a single raw SQL statement against whichever database is
      active.
    - Statements that return rows (SELECT, PRAGMA, SHOW, EXPLAIN, WITH,
      DESC/DESCRIBE) are treated as read-only - results appear in a
      table below, with an "Export Results to CSV..." option.
    - Anything else (INSERT/UPDATE/DELETE/etc.) is treated as a write:
      you get a confirmation dialog showing the exact SQL before it
      runs. If the active backend is SQLite, a timestamped backup of
      the database file is made automatically first.
    - A successful write automatically refreshes the View Database tab.


Synonym search
~~~~~~~~~~~~~~

Looks up alternate/vernacular names for a species (via waarnemingen.be)
and, for whichever names you choose, searches NCBI for barcode
sequences under each one - useful for catching sequences that were
deposited under an older or local name rather than the species'
current canonical name.

How to use it:

1. Provide species the same way as Fetch FASTA: a CSV with a "Name"
   column, a no_matches.txt file, and/or typed names. These are
   combined and de-duplicated, except a loaded no_matches.txt replaces
   the CSV/typed names rather than adding to them. The shared species
   list (also used by Fetch FASTA and Maps) can be loaded/saved here
   too.

2. Click "Load Species" to preview the resolved list, then "Search
   Synonyms" (set the waarnemingen.be request interval first if
   needed) to look up alternate names for each one.

3. A checklist appears per species, showing its canonical name plus
   every alternate name found (grouped by which language it's used
   in) - all pre-checked. Uncheck anything you don't want searched.

4. Pick markers the same way as Fetch FASTA (checkboxes plus an "Extra
   markers" field), set the NCBI request interval/worker count, then
   click "Search Sequences for Selected Names" to search NCBI for
   every checked name x marker combination.
   Note: this tab only searches NCBI (not BOLD), and always uses the
   same default scoring weights, bad-word filters, and length bands as
   Fetch FASTA's defaults - they aren't adjustable from this tab.

5. Results (accession, score, and which name it was actually queried
   as) are listed below. From there you can "Save Synonyms to
   Database" (the species/alternate-name pairs), "Add Sequence Results
   to Database" (the sequences themselves), and/or "Add to Report" to
   push the synonym results into the Gap Report.


MSA
~~~

Aligns and scores multiple sequences using MUSCLE, with a couple of
file-prep utilities built in. Split into four sub-tabs.

Merge FASTA:

    - Add multiple FASTA files at once, remove individual ones, or
      clear the list.
    - Choose an output file, then "Merge" combines every sequence from
      the selected files into one FASTA file - handy for combining
      separate per-species/marker exports before aligning them
      together.

Run MSA:

    - Select a FASTA file to align and an output folder.
    - Once a file is selected, every sequence ID in it is listed with a
      checkbox: check any sequence you want flipped to its reverse
      complement before alignment. Checked sequences are rewritten to
      a "<filename>_revcomp.fasta" file, which is what actually gets
      aligned in their place - useful when a submitted sequence is on
      the opposite strand from the others and would otherwise misalign.
    - Toggle whether the alignment image shows a grid, a per-column
      count, and/or a consensus row.
    - "Run MSA" runs MUSCLE in the background (so the app doesn't
      freeze) and switches to the MSA Results tab once it's done.

MSA Results:

    - Shows the rendered alignment image (scrolls horizontally for long
      alignments).
    - "Add to Report" pushes the image - plus any scores already
      computed on the MSA Score tab - into the Gap Report.

MSA Score:

    - Select an aligned FASTA file (e.g. the one Run MSA just produced,
      or any other alignment).
    - Choose which scores to compute: percentage of non-gaps,
      percentage of totally conserved columns, entropy, Sum of Pairs
      (Blosum62 and/or PAM250 - each also shown as a % of the maximum
      possible score), and Star (Blosum62 and/or PAM250).
    - "Compute Scores" runs in the background and shows the results;
      these are what get attached if you then use "Add to Report" back
      on the Results tab.


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
