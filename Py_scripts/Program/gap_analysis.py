import database

STATUS_RANK = {"no_sequences": 0, "partial": 1, "complete": 2, "no_data": 3}
STATUS_LABELS = {
    "no_sequences": "No sequences",
    "partial": "Partial",
    "complete": "Complete",
    "no_data": "No data available",
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
