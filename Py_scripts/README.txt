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

Settings
~~~~~~~~

The central configuration hub. Nothing here runs a search itself - it
holds the credentials, defaults, and scoring rules that Fetch FASTA,
Synonym search, Database, and Maps all read from.

    - NCBI credentials: your email (required for any NCBI search) and
      an optional API key that raises the rate limit from 3 to 10
      requests/second.

    - Database: choose SQLite ("Select/Create Database File" - a
      single local file) or MySQL (host/port/user/password/database
      name, validated with a "Connect" button before it becomes
      active). The MySQL password is never saved to disk - you
      re-enter it each session. Whichever backend is active here is
      shared by every other tab that touches the database.

    - Country scoring: comma-separated lists of target-country and
      neighbor-country names/spellings (e.g. the same country in
      multiple languages). These decide which candidate sequences get
      Fetch FASTA's "Target country boost" vs. "Neighbor countries
      boost" - anything else in Europe gets the "Europe fallback"
      score instead.

    - Strip characters: optionally strip specific characters (e.g. the
      "x" in botanical hybrid names) from species names wherever they
      appear, before searching.

    - Request pacing / search depth: minimum interval between
      requests, concurrent workers (NCBI only), how many candidates to
      score per search, and how many top-scoring results to keep per
      marker; plus species-per-batch and pause-between-batches for
      BOLD searches.

    - Length bands: a default "full score" and "partial score" length
      range in bp - sequences inside the full range get the complete
      length bonus, tapering off across the partial range, nothing
      outside it. Per-marker overrides can be typed in, one per line:
      "MARKER full_min-full_max partial_min-partial_max".

    - Settings presets: save the current scoring/markers/filters/
      output settings (not NCBI credentials or the database
      connection) under a name, then load or delete it later.
      "Default" is a built-in preset that can't be deleted, used to
      reset everything back to factory values.

Closing the app automatically saves your NCBI email/API key, database
backend choice (excluding the MySQL password), and every setting above.


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


Retrieval Rate
~~~~~~~~~~~~~~

Visualizes how many sequences you retrieved per marker (and per source)
after a Fetch FASTA run.

How to use it:

1. Data comes automatically from the most recent Fetch FASTA run in
   this session, or click "Load CSV" to load any previous run's
   summary.csv instead - this overrides the live data until you load a
   different file or restart the app.

2. Pick a chart type:
     - Barplot - sequence count per marker.
     - Piechart - each marker's share of the total.
     - NCBI/BOLD - count split by source.
     - Table - the raw summary data, sortable by clicking a column
       header and filterable with the same filter-bar behavior as the
       Database tab (type a query, optionally restrict it to one
       column).

3. Optionally customize the title/axis labels (Barplot and NCBI/BOLD),
   then click "Display".

4. "Save Plot" exports the current chart as PNG, JPEG, PDF, or SVG.
   "Add to Report" pushes a snapshot of whatever chart is currently
   displayed into the Gap Report (not available from the Table view,
   which has no chart to add).

5. The chart panel can be resized by dragging its bottom-right corner.


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


BLAST
~~~~~

Builds a local BLAST database from sequences already in a database
file, and searches it with a single query sequence or a batch FASTA
file.

How to use it:

1. "Select Database" to load sequences from a SQLite database file.
   This is a separate, independent file picker from the active
   database in Settings - it always loads directly from a chosen .db
   file rather than the shared SQLite/MySQL backend. Click "Reload" to
   re-read the same file after it's changed elsewhere.

2. "Select/Create BLAST Database":
     - "Create New Database" exports every loaded sequence to a FASTA
       file and runs makeblastdb to build a nucleotide BLAST index
       from it.
     - "Select Existing Database" points at an already-built index via
       its .nin file.

3. Provide a query: type a single sequence directly, or "Load Query
   FASTA File..." to BLAST every sequence in a file at once (a loaded
   file takes priority over the typed sequence - use "Clear" to go
   back to typing one).

4. Pick the BLAST program (blastn, blastp, blastx, tblastn, tblastx)
   and click "Run BLAST". Output, in BLAST's standard pairwise text
   format, appears in the box below; if the BLAST executable itself
   fails, its error output is shown there instead.

Prerequisite: NCBI BLAST+ must be available at the location this tab
expects - bundled automatically in the packaged .exe, or installed and
pointed at manually when running from source (see Installation).


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


Maps
~~~~

Plots species occurrence records from an observation platform (e.g.
waarnemingen.be) on a map, and cross-checks the species against what's
already in your database.

How to use it:

1. Pick the map/data source, type a species name, and choose a start
   and end date.

2. Click "Load". It looks up the species' ID on that site, fetches
   occurrence data on a grid, and - if a database is configured in
   Settings - pulls how many sequences you already have per marker for
   that species. Both run in the background, since the site lookup can
   take 10-20 seconds (page load plus anti-bot checks).

3. Once loaded, the map centers and zooms to fit the returned grid
   cells, each marked with its observation count. A status line shows
   how many cells were loaded and, separately, what's already on file
   in the database per marker.

Without a database configured in Settings, you still get the map - just
not the "already on file" comparison.


Gap Report
~~~~~~~~~~

Finds species/marker combinations with missing or thin sequence
coverage by cross-checking your database against real occurrence data,
then assembles a PDF/Word report combining that with snapshots pushed
in from other tabs. Split into two sub-tabs.

Gap Analysis:

    - Provide species the same way as the other tabs: a CSV with a
      "Name" column, a no_matches.txt file, typed names, and/or the
      shared species list.

    - Choose options: the observation site and date range, which
      markers to check (checkboxes plus an extra-markers field), and
      whether to force-refresh observation counts instead of reusing
      ones already fetched this session.

    - "Run Gap Analysis" checks, per species: how many real-world
      observations exist in that date range (resolving through known
      synonyms in the database if available), and how many sequences
      exist per target marker in your database. Each row is
      color-labelled by status - no sequences, partial, complete, or
      no data (when no database is configured).

    - From the results table: "Export to CSV", "Send missing species
      to Fetch FASTA" (pushes every no-sequences/partial species into
      the shared species list and switches over to Fetch FASTA), or
      select a row and open "Barcode Gap Analysis..." - a drill-down
      window that builds a guide tree for that species' genus (per
      marker, with a choice of distance metric) and reports whether
      intraspecific vs. interspecific distances show a clean "barcode
      gap" for that species. Its tree image can be added to the report
      too.

Report Contents:

    - The gap analysis table is always the report's first section.
    - Optionally include a bar chart summarizing gap-status counts
      (no sequences/partial/complete/no data).
    - Any "Add to Report" snapshot pushed from Retrieval Rate, MSA,
      Synonym search, or a barcode gap drill-down is listed here, each
      removable.
    - "Export to PDF..." / "Export to Word..." assembles everything
      into a single document.


Terminal
~~~~~~~~

Shows live log output while a Fetch FASTA run is in progress - a
status line plus a scrolling text log of everything printed during the
search (NCBI/BOLD requests, matches found, warnings, etc.), so you can
follow a long-running search without a separate console window.

There's nothing to configure here - it's read-only output.


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
