import io
import itertools

import matplotlib.pyplot as plt
from Bio.Align import PairwiseAligner

import database

BARCODE_GAP_VERDICTS = {
    "clear_gap": "Clear barcode gap",
    "overlap": "Overlap (no gap)",
    "insufficient_data": "Insufficient data",
}

STATUS_RANK = {"no_sequences": 0, "partial": 1, "complete": 2, "no_data": 3}
STATUS_LABELS = {
    "no_sequences": "No sequences",
    "partial": "Partial",
    "complete": "Complete",
    "no_data": "No data available",
}
# Same status colors as gap_tab.py's Treeview tags, reused here so the chart
# matches what the results table already shows.
STATUS_CHART_COLORS = {
    "no_sequences": "#e35d5d",
    "partial": "#eda100",
    "complete": "#4caf50",
    "no_data": "#9a9a9a",
}


def compute_status(marker_counts, target_markers):
    """
    marker_counts: {marker: count}, from database.count_sequences_by_marker
    target_markers: the markers this report cares about
    """
    covered = [m for m in target_markers if marker_counts.get(m, 0) > 0]

    if not covered:
        return "no_sequences"
    if len(covered) < len(target_markers):
        return "partial"
    return "complete"


def build_gap_rows(species_names, observation_counts, db_config, target_markers):
    """
    db_config: shared database.DatabaseConfig chosen in the Settings tab -
        pass None/unconfigured to skip the sequence-coverage lookup entirely
        (every row becomes "no_data").

    Returns a list of row dicts species, observations, one key per target
    marker , status, status_label
    """
    conn = (
        database.connect(db_config)
        if db_config is not None and db_config.is_configured() else None
    )

    rows = []
    for species in species_names:
        observations = observation_counts.get(species)

        if observations is None:
            status = "no_data"
            marker_counts = {}
        else:
            marker_counts = (
                dict(database.count_sequences_by_marker(conn, species))
                if conn is not None else {}
            )
            status = compute_status(marker_counts, target_markers)

        row = {
            "species": species,
            "observations": observations,
            "status": status,
            "status_label": STATUS_LABELS[status],
        }
        for marker in target_markers:
            row[marker] = marker_counts.get(
                marker, 0) if observations is not None else None
        rows.append(row)

    if conn is not None:
        conn.close()

    rows.sort(key=lambda r: (
        STATUS_RANK[r["status"]], -(r["observations"] or 0)))

    return rows


def build_marker_coverage_stats(rows, target_markers):
    """
    Returns [(marker, covered_count, assessed_count, percentage), ...] - for
    each target marker, what fraction of species with a confirmed
    observation count (i.e. excluding "no_data" rows, which couldn't be
    assessed against the observation site at all) have at least one
    sequence for that marker. More directly comparable across report runs
    than the raw counts in Table 1 alone.
    """
    assessed = [row for row in rows if row["observations"] is not None]
    assessed_count = len(assessed)

    stats = []
    for marker in target_markers:
        covered_count = sum(1 for row in assessed if (row[marker] or 0) > 0)
        percentage = (
            covered_count / assessed_count * 100 if assessed_count else 0.0)
        stats.append((marker, covered_count, assessed_count, percentage))

    return stats


def build_status_chart_png(rows):
    """
    Returns PNG bytes of a bar chart summarizing how many species fall into
    each gap-analysis status - a visual companion to the Table 1 counts,
    used as an optional figure in the exported report.
    """
    counts = {key: 0 for key in STATUS_RANK}
    for row in rows:
        counts[row["status"]] += 1

    # keep the same left-to-right order as STATUS_RANK (severity order),
    # same as the results table's sort priority
    ordered_keys = sorted(STATUS_RANK, key=STATUS_RANK.get)
    labels = [STATUS_LABELS[key] for key in ordered_keys]
    values = [counts[key] for key in ordered_keys]
    bar_colors = [STATUS_CHART_COLORS[key] for key in ordered_keys]

    fig, ax = plt.subplots(figsize=(6, 3.2), dpi=150)
    bars = ax.bar(labels, values, color=bar_colors)
    ax.set_ylabel("Number of species")
    ax.set_title("Gap analysis status summary")
    ax.tick_params(axis="x", labelsize=10)

    for bar, value in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2, bar.get_height(), str(value),
            ha="center", va="bottom", fontsize=10
        )

    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


def _default_aligner():
    aligner = PairwiseAligner()
    aligner.mode = "global"
    aligner.match_score = 1
    aligner.mismatch_score = 0
    aligner.gap_score = -1
    return aligner


def p_distance(seq1, seq2, aligner=None):
    """
    Returns (distance, n_sites): distance is the fraction of aligned,
    non-gap columns that differ; n_sites is how many such columns there
    were. Returns (None, 0) if there were no comparable columns (e.g. one
    sequence is empty, or the two share no ungapped alignment column).
    """
    seq1 = "".join(seq1.split())
    seq2 = "".join(seq2.split())

    aligner = aligner or _default_aligner()
    alignment = aligner.align(seq1, seq2)[0]
    a1, a2 = str(alignment[0]), str(alignment[1])

    n_sites = 0
    n_diff = 0
    for c1, c2 in zip(a1, a2):
        if c1 == "-" or c2 == "-":
            continue
        n_sites += 1
        if c1 != c2:
            n_diff += 1

    if n_sites == 0:
        return None, 0
    return n_diff / n_sites, n_sites


def compute_barcode_gap(conn, species_name, marker, aligner=None):
    """
    Assesses whether species_name has a barcode gap at the given marker:
    the max pairwise distance among its own sequences (intraspecific)
    versus the min pairwise distance to any congener sequence on file
    (interspecific, scoped to genus - see database.get_congener_sequences).

    Returns a dict:
      verdict: one of BARCODE_GAP_VERDICTS
      reason: set (a short explanation) when verdict is "insufficient_data"
      max_intraspecific: float or None
      min_interspecific: float or None
      nearest_neighbor: the congener species the closest sequence belongs
          to, or None
      gap: min_interspecific - max_intraspecific, or None
    """
    def insufficient(reason):
        return {
            "verdict": "insufficient_data",
            "reason": reason,
            "max_intraspecific": None,
            "min_interspecific": None,
            "nearest_neighbor": None,
            "gap": None,
        }

    own_sequences = database.get_sequences_for_species(
        conn, species_name, marker)
    if len(own_sequences) < 2:
        return insufficient("fewer than 2 sequences on file for this marker")

    congener_sequences = database.get_congener_sequences(
        conn, species_name, marker)
    if not congener_sequences:
        return insufficient("no congeners on file for this marker")

    aligner = aligner or _default_aligner()

    max_intra = 0.0
    for seq_a, seq_b in itertools.combinations(own_sequences, 2):
        distance, n_sites = p_distance(seq_a, seq_b, aligner)
        if distance is not None:
            max_intra = max(max_intra, distance)

    min_inter = None
    nearest_neighbor = None
    for own_seq in own_sequences:
        for other_species, other_seq in congener_sequences:
            distance, n_sites = p_distance(own_seq, other_seq, aligner)
            if distance is None:
                continue
            if min_inter is None or distance < min_inter:
                min_inter = distance
                nearest_neighbor = other_species

    if min_inter is None:
        return insufficient(
            "no comparable (ungapped) alignment sites with any congener sequence")

    gap = min_inter - max_intra
    verdict = "clear_gap" if gap > 0 else "overlap"

    return {
        "verdict": verdict,
        "reason": None,
        "max_intraspecific": max_intra,
        "min_interspecific": min_inter,
        "nearest_neighbor": nearest_neighbor,
        "gap": gap,
    }
