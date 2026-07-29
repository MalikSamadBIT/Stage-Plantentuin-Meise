import os
import tkinter
from tkinter import filedialog, ttk

import customtkinter as ctk
import pandas as pd

import database

# table dropdown -> (SQL source, columns to select or None for "*")
# sequence is excluded from the Sequences columns - it's long and would
# dominate the view - but export_fasta still pulls it back out per row
TABLE_OPTIONS = {
    "Sequences": ("sequences_view", [
        "species", "queried_as", "marker", "source", "accession", "organism",
        "length", "geo_loc", "score", "fetched_at"
    ]),
    "Species": ("species", None),
    "Synonyms": ("synonyms_view", ["species", "language", "name"]),
    "Runs": ("runs", None),
}


def build_database_tab(parent, root=None):
    """
    parent: the tab frame to build the widgets into.
    root: the main app window, used as the file-dialog parent.
    """

    db_path = ctk.StringVar()
    full_df = None
    view_df = None
    sort_state = {}
    # committed filters, applied in order (AND'ed together)
    active_filters = []

    # TOP BAR----------------------------------------------------------------

    top_bar = ctk.CTkFrame(parent, fg_color="transparent")
    top_bar.pack(fill="x", padx=10, pady=(10, 5))

    def choose_database():
        path = filedialog.askopenfilename(
            parent=root,
            title="Select a database file",
            filetypes=[("SQLite database", "*.db"), ("All files", "*.*")]
        )
        if path:
            db_path.set(path)
            load_data()

    ctk.CTkButton(
        top_bar, text="Select Database File...", command=choose_database
    ).pack(side="left", padx=(0, 5))

    ctk.CTkButton(
        top_bar, text="Reload", command=lambda: load_data()
    ).pack(side="left", padx=(0, 5))

    ctk.CTkButton(
        top_bar, text="Export View to FASTA...", command=lambda: export_fasta()
    ).pack(side="left", padx=(0, 15))

    ctk.CTkLabel(top_bar, text="Table:").pack(side="left", padx=(0, 5))

    table_var = ctk.StringVar(value="Sequences")
    ctk.CTkOptionMenu(
        top_bar, variable=table_var, values=list(TABLE_OPTIONS.keys()),
        command=lambda _choice: load_data(), width=120
    ).pack(side="left")

    ctk.CTkLabel(parent, textvariable=db_path, text_color="gray").pack(
        anchor="w", padx=10, pady=(0, 5))

    status_label = ctk.CTkLabel(
        parent, text="No database loaded yet.", text_color="gray")
    status_label.pack(anchor="w", padx=10, pady=(0, 5))

    # FILTER BAR---------------------------------------------------------

    filter_bar = tkinter.Frame(parent, bg="#2b2b2b")
    filter_bar.pack(fill="x", padx=10)

    tkinter.Label(
        filter_bar, text="Filter:", bg="#2b2b2b", fg="white"
    ).pack(side=tkinter.LEFT, padx=(8, 4), pady=6)

    filter_column_var = tkinter.StringVar(value="(all columns)")
    filter_column_menu = ttk.Combobox(
        filter_bar, textvariable=filter_column_var, state="readonly", width=18
    )
    filter_column_menu.pack(side=tkinter.LEFT, padx=4)

    filter_entry = tkinter.Entry(filter_bar)
    filter_entry.pack(side=tkinter.LEFT, padx=4, fill=tkinter.X, expand=True)
    filter_entry.bind("<KeyRelease>", lambda event: preview_filter())
    filter_entry.bind("<Return>", lambda event: apply_filter())

    tkinter.Button(
        filter_bar, text="Apply", command=lambda: apply_filter()
    ).pack(side=tkinter.LEFT, padx=4)

    tkinter.Button(
        filter_bar, text="Clear all", command=lambda: clear_filters()
    ).pack(side=tkinter.LEFT, padx=(4, 8))

    # active (committed) filters are shown as removable chips here - each new
    # "Apply" narrows further on top of these, instead of replacing them
    active_filters_row = tkinter.Frame(parent, bg="#2b2b2b")
    active_filters_row.pack(fill="x", padx=10)

    # TABLE----------------------------------------------------------------

    table_style = ttk.Style()
    table_style.theme_use("clam")
    table_style.configure(
        "Treeview",
        background="#2b2b2b", fieldbackground="#2b2b2b",
        foreground="white", rowheight=28,
        font=("Arial", 12)
    )
    table_style.configure(
        "Treeview.Heading",
        background="#3a3a3a", foreground="white",
        font=("Arial", 12, "bold")
    )

    table_frame = tkinter.Frame(parent)
    table_frame.pack(fill="both", expand=True, padx=10, pady=(5, 10))

    table_vsb = ttk.Scrollbar(table_frame, orient="vertical")
    table_hsb = ttk.Scrollbar(table_frame, orient="horizontal")

    tree = ttk.Treeview(
        table_frame, show="headings",
        yscrollcommand=table_vsb.set,
        xscrollcommand=table_hsb.set
    )

    table_vsb.configure(command=tree.yview)
    table_hsb.configure(command=tree.xview)

    table_vsb.pack(side=tkinter.RIGHT, fill=tkinter.Y)
    table_hsb.pack(side=tkinter.BOTTOM, fill=tkinter.X)
    tree.pack(side=tkinter.TOP, fill=tkinter.BOTH, expand=True)

    # DATA LOADING / FILTER / SORT----------------------------------------

    def populate_tree(df_view):
        tree.delete(*tree.get_children())
        tree["columns"] = list(df_view.columns)
        for col in df_view.columns:
            tree.heading(col, text=col, command=lambda c=col: sort_table(c))
            tree.column(col, width=110, anchor="center")
        for _, row in df_view.iterrows():
            tree.insert("", "end", values=list(row))

    def load_data():
        nonlocal full_df, view_df

        if not db_path.get():
            status_label.configure(text="Select a database file first.")
            return

        source, columns = TABLE_OPTIONS[table_var.get()]
        select_clause = ", ".join(columns) if columns else "*"

        try:
            conn = database.connect(db_path.get())
            full_df = pd.read_sql_query(
                f"SELECT {select_clause} FROM {source}", conn
            )
            conn.close()
        except Exception as e:
            status_label.configure(text=f"Failed to load database: {e}")
            return

        view_df = full_df
        sort_state.clear()
        active_filters.clear()
        rebuild_filter_chips()

        filter_column_menu.configure(
            values=["(all columns)"] + list(full_df.columns))
        filter_column_var.set("(all columns)")
        filter_entry.delete(0, "end")

        populate_tree(view_df)
        status_label.configure(
            text=f"{len(full_df)} row(s) loaded from {table_var.get()}.")

    def _column_matches(series, query):
        if pd.api.types.is_numeric_dtype(series):
            try:
                query_num = float(query)
            except ValueError:
                return pd.Series(False, index=series.index)
            return series == query_num

        return series.astype(str).str.lower().str.contains(query.lower(), na=False)

    def _filter_df(df, column, query):
        if column and column != "(all columns)":
            return df[_column_matches(df[column], query)]

        mask = pd.Series(False, index=df.index)
        for col in df.columns:
            mask = mask | _column_matches(df[col], query)
        return df[mask]

    def _committed_view():
        # active_filters are AND'ed together, each one narrowing the last
        result = full_df
        for f in active_filters:
            result = _filter_df(result, f["column"], f["query"])
        return result

    def _update_view(new_view_df, status_suffix=""):
        nonlocal view_df
        view_df = new_view_df
        populate_tree(view_df)
        status_label.configure(
            text=f"{len(view_df)} of {len(full_df)} sequence(s) shown."
            f"{status_suffix}")

    def preview_filter(*_):
        # live-as-you-type preview, on top of the committed filters below -
        # not added to active_filters until "Apply" (or Enter) is pressed
        if full_df is None:
            return

        base = _committed_view()
        query = filter_entry.get().strip()
        column = filter_column_var.get()

        if not query:
            _update_view(base)
        else:
            _update_view(_filter_df(base, column, query))

    def rebuild_filter_chips():
        for widget in active_filters_row.winfo_children():
            widget.destroy()

        if not active_filters:
            return

        tkinter.Label(
            active_filters_row, text="Active filters:", bg="#2b2b2b", fg="gray"
        ).pack(side=tkinter.LEFT, padx=(8, 4), pady=4)

        for i, f in enumerate(active_filters):
            col_label = f["column"] if f["column"] != "(all columns)" else "any column"
            chip = tkinter.Frame(active_filters_row, bg="#3a3a3a")
            chip.pack(side=tkinter.LEFT, padx=3, pady=4)
            tkinter.Label(
                chip, text=f'{col_label}: "{f["query"]}"',
                bg="#3a3a3a", fg="white"
            ).pack(side=tkinter.LEFT, padx=(6, 2), pady=2)
            tkinter.Button(
                chip, text="x", bg="#3a3a3a", fg="white", bd=0,
                command=lambda i=i: remove_filter(i)
            ).pack(side=tkinter.LEFT, padx=(0, 4))

    def remove_filter(index):
        active_filters.pop(index)
        rebuild_filter_chips()
        _update_view(_committed_view())

    def apply_filter(*_):
        if full_df is None:
            return

        query = filter_entry.get().strip()
        column = filter_column_var.get()

        if query:
            active_filters.append({"column": column, "query": query})
            rebuild_filter_chips()

        filter_entry.delete(0, "end")
        filter_column_var.set("(all columns)")

        _update_view(_committed_view())

    def clear_filters():
        active_filters.clear()
        rebuild_filter_chips()
        filter_entry.delete(0, "end")
        filter_column_var.set("(all columns)")
        if full_df is not None:
            _update_view(full_df)

    def sort_table(col):
        nonlocal view_df

        if view_df is None or view_df.empty:
            return

        ascending = not sort_state.get(col, False)
        sort_state[col] = ascending

        view_df = view_df.sort_values(
            by=col, ascending=ascending, kind="stable")
        populate_tree(view_df)

    # EXPORT----------------------------------------------------------------

    def export_fasta():
        if view_df is None or view_df.empty:
            status_label.configure(
                text="Nothing to export - load a database first.")
            return

        if table_var.get() != "Sequences":
            status_label.configure(
                text="FASTA export is only available for the Sequences table.")
            return

        path = filedialog.asksaveasfilename(
            parent=root,
            title="Export current view to FASTA",
            defaultextension=".fasta",
            filetypes=[("FASTA", "*.fasta"), ("All files", "*.*")]
        )
        if not path:
            return

        accessions = [a for a in view_df["accession"].tolist() if a]

        if not accessions:
            status_label.configure(
                text="No accessions in the current view to export.")
            return

        try:
            conn = database.connect(db_path.get())
            placeholders = ",".join("?" for _ in accessions)
            rows = conn.execute(
                f"SELECT species, marker, accession, sequence FROM sequences_view "
                f"WHERE accession IN ({placeholders})",
                accessions
            ).fetchall()
            conn.close()
        except Exception as e:
            status_label.configure(text=f"Export failed: {e}")
            return

        with open(path, "w", encoding="utf-8") as f:
            for row in rows:
                header = f">{row['accession']} {row['species']} {row['marker']}"
                f.write(header + "\n" + row["sequence"] + "\n")

        status_label.configure(
            text=f"Exported {len(rows)} sequence(s) to {os.path.basename(path)}.")
