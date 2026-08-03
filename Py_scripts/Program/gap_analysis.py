import io

import matplotlib.pyplot as plt

import database

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
