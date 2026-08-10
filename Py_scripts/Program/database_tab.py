import logging
import os
import threading
import tkinter
from tkinter import filedialog, ttk

import customtkinter as ctk
import pandas as pd

import database

try:
    from sqlite3_to_mysql import SQLite3toMySQL
except ImportError:
    SQLite3toMySQL = None

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


def build_database_tab(parent, root=None, db_config=None):
    """
    parent: the tab frame to build the widgets into.
    root: the main app window, used as the file-dialog parent.
    db_config: shared database.DatabaseConfig chosen in the Settings tab.
        Falls back to a private (unconfigured) one if this tab is ever used
        standalone.
    """

    if db_config is None:
        db_config = database.DatabaseConfig()

    sub_tabs = ctk.CTkTabview(parent)
    sub_tabs.pack(fill="both", expand=True)

    view_tab = sub_tabs.add("View Database")
    transfer_tab = sub_tabs.add("Transfer Database")
    query_tab = sub_tabs.add("Query Database")

    view_reload = _build_view_tab(view_tab, root, db_config)
    _build_transfer_tab(transfer_tab, root, db_config)
    _build_query_tab(query_tab, root, db_config, on_data_changed=view_reload)


def _build_view_tab(parent, root, db_config):
    full_df = None
    view_df = None
    sort_state = {}
    # committed filters, applied in order (AND'ed together)
    active_filters = []

    # TOP BAR----------------------------------------------------------------

    top_bar = ctk.CTkFrame(parent, fg_color="transparent")
    top_bar.pack(fill="x", padx=10, pady=(10, 5))

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

    ctk.CTkLabel(
        parent, textvariable=db_config.display_var, text_color="gray"
    ).pack(anchor="w", padx=10, pady=(0, 5))

    status_label = ctk.CTkLabel(
        parent, text="No database selected - choose one in the Settings tab.",
        text_color="gray"
    )
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

        if not db_config.is_configured():
            status_label.configure(
                text="No database selected - choose one in the Settings tab.")
            return

        source, columns = TABLE_OPTIONS[table_var.get()]
        select_clause = ", ".join(columns) if columns else "*"

        try:
            conn = database.connect(db_config)
            full_df = database.query_df(
                conn, f"SELECT {select_clause} FROM {source}"
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
            conn = database.connect(db_config)
            rows = database.fetch_by_accessions(conn, accessions)
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

    # REACT TO THE SHARED DATABASE CHOICE---------------------------------
    # db_config is shared with the Settings tab (and Fetch FASTA/Synonym
    # search) - reload automatically whenever the backend/target changes
    # there, and load immediately if a database was already configured
    # before this tab was built.

    db_config.trace_add("write", lambda *_: load_data())

    if db_config.is_configured():
        load_data()

    return load_data


# TRANSFER TAB (SQLite -> MySQL, via the sqlite3-to-mysql package)-----------

def _build_transfer_tab(parent, root, db_config):
    """
    Lets the user copy a SQLite database into a MySQL database, using the
    sqlite3-to-mysql package (SQLite3toMySQL class). Always transfers from
    the SQLite file remembered in Settings (db_config.sqlite_path) - not
    necessarily whichever backend is currently active, since sqlite3-to-mysql
    only ever migrates from SQLite.
    root is unused here, kept for consistency with the other build_*_tab
    functions.
    """

    ctk.CTkLabel(
        parent, text="Transfer the SQLite database to MySQL",
        font=("Arial", 16, "bold")
    ).pack(anchor="w", padx=10, pady=(10, 2))

    ctk.CTkLabel(
        parent,
        text="Copies every table from the SQLite database selected in the "
             "Settings tab into a MySQL database, using the sqlite3-to-mysql "
             "tool.",
        text_color="gray", justify="left", wraplength=700
    ).pack(anchor="w", padx=10, pady=(0, 10))

    if SQLite3toMySQL is None:
        ctk.CTkLabel(
            parent,
            text="The \"sqlite3-to-mysql\" package is not installed. "
                 "Install it first:",
            text_color="orange", justify="left", wraplength=700
        ).pack(anchor="w", padx=10, pady=(0, 2))
        ctk.CTkLabel(
            parent, text="pip install sqlite3-to-mysql==2.6.0",
            font=("Consolas", 12), justify="left"
        ).pack(anchor="w", padx=10, pady=(0, 10))
        return

    ctk.CTkLabel(parent, text="Source (SQLite):").pack(
        anchor="w", padx=10, pady=(0, 0))

    transfer_source_var = ctk.StringVar()

    def _refresh_transfer_source(*_):
        transfer_source_var.set(
            db_config.sqlite_path or
            "No SQLite file configured yet - select one in Settings.")

    db_config.trace_add("write", _refresh_transfer_source)
    _refresh_transfer_source()

    ctk.CTkLabel(
        parent, textvariable=transfer_source_var, text_color="gray"
    ).pack(anchor="w", padx=10, pady=(0, 10))

    # MYSQL CONNECTION FIELDS----------------------------------------------

    fields_frame = ctk.CTkFrame(parent, fg_color="transparent")
    fields_frame.pack(fill="x", padx=10)

    def labeled_entry(row, label, default="", show=None, width=250):
        ctk.CTkLabel(fields_frame, text=label).grid(
            row=row, column=0, sticky="w", padx=(0, 10), pady=5)
        entry = ctk.CTkEntry(fields_frame, width=width, show=show)
        if default:
            entry.insert(0, default)
        entry.grid(row=row, column=1, sticky="w", pady=5)
        return entry

    fields_frame.grid_columnconfigure(1, weight=0)

    # prefilled from the Settings tab's MySQL fields, if any are set there -
    # still a separate/independent destination, just a convenient starting
    # point (password is never carried over, same as in Settings)
    host_entry = labeled_entry(
        0, "MySQL host", default=db_config.mysql_host or "localhost")
    port_entry = labeled_entry(
        1, "MySQL port", default=str(db_config.mysql_port or 3306))
    user_entry = labeled_entry(2, "MySQL user", default=db_config.mysql_user)
    password_entry = labeled_entry(3, "MySQL password", show="*")
    database_entry = labeled_entry(
        4, "MySQL database name", default=db_config.mysql_database)
    chunk_entry = labeled_entry(5, "Chunk size (rows per batch, optional)")

    truncate_var = ctk.BooleanVar(value=False)
    ctk.CTkCheckBox(
        parent, text="Truncate existing tables in MySQL before transfer",
        variable=truncate_var
    ).pack(anchor="w", padx=10, pady=(5, 10))

    status_label = ctk.CTkLabel(
        parent, text="Fill in the MySQL connection details, then transfer.",
        text_color="gray"
    )
    status_label.pack(anchor="w", padx=10, pady=(0, 5))

    log_box = ctk.CTkTextbox(parent, height=180, state="disabled")
    log_box.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def append_log(message):
        def do_append():
            log_box.configure(state="normal")
            log_box.insert("end", message + "\n")
            log_box.see("end")
            log_box.configure(state="disabled")
        parent.after(0, do_append)

    class _LogBoxHandler(logging.Handler):
        def emit(self, record):
            append_log(self.format(record))

    def run_transfer(sqlite_file, host, port, user, password, mysql_db,
                      chunk, truncate):
        logger = logging.getLogger("SQLite3toMySQL")
        handler = _LogBoxHandler()
        handler.setFormatter(logging.Formatter(
            fmt="%(asctime)s %(levelname)-8s %(message)s",
            datefmt="%H:%M:%S"
        ))
        logger.addHandler(handler)

        try:
            converter = SQLite3toMySQL(
                sqlite_file=sqlite_file,
                mysql_user=user,
                mysql_password=password or None,
                mysql_host=host,
                mysql_port=port,
                mysql_database=mysql_db,
                chunk=chunk,
                mysql_truncate_tables=truncate,
                quiet=True,
            )
            converter.transfer()
        except Exception as e:
            append_log(f"ERROR: {e}")
            parent.after(
                0, lambda: status_label.configure(
                    text=f"Transfer failed: {e}", text_color="red"))
        else:
            parent.after(
                0, lambda: status_label.configure(
                    text="Transfer completed successfully.",
                    text_color="green"))
        finally:
            logger.removeHandler(handler)
            parent.after(0, lambda: transfer_button.configure(state="normal"))

    def start_transfer():
        sqlite_file = db_config.sqlite_path
        if not sqlite_file:
            status_label.configure(
                text="No SQLite file configured - select one in the "
                     "Settings tab.",
                text_color="red")
            return

        if not os.path.isfile(sqlite_file):
            status_label.configure(
                text="The selected SQLite database file does not exist.",
                text_color="red")
            return

        host = host_entry.get().strip() or "localhost"
        user = user_entry.get().strip()
        password = password_entry.get()
        mysql_db = database_entry.get().strip()

        if not user or not mysql_db:
            status_label.configure(
                text="MySQL user and database name are required.",
                text_color="red")
            return

        try:
            port = int(port_entry.get().strip() or "3306")
        except ValueError:
            status_label.configure(
                text="MySQL port must be a number.", text_color="red")
            return

        chunk_text = chunk_entry.get().strip()
        chunk = None
        if chunk_text:
            try:
                chunk = int(chunk_text)
            except ValueError:
                status_label.configure(
                    text="Chunk size must be a number.", text_color="red")
                return

        log_box.configure(state="normal")
        log_box.delete("1.0", "end")
        log_box.configure(state="disabled")

        status_label.configure(
            text="Transferring - this can take a while for large databases...",
            text_color="gray")
        transfer_button.configure(state="disabled")

        threading.Thread(
            target=run_transfer,
            args=(sqlite_file, host, port, user, password, mysql_db,
                  chunk, truncate_var.get()),
            daemon=True
        ).start()

    transfer_button = ctk.CTkButton(
        parent, text="Transfer to MySQL", command=start_transfer
    )
    transfer_button.pack(anchor="w", padx=10, pady=(0, 10))


# QUERY TAB (raw SQL against the active database)-----------------------

# a query "looks read-only" if - after stripping leading whitespace - it
# starts with one of these. Anything else is treated as a write and
# confirmed first. This is a guard against accidental data loss, not a
# security boundary - the user is running their own SQL against their own
# database, same trust level as typing it into a DB client directly.
_READ_ONLY_PREFIXES = (
    "select", "pragma", "show", "explain", "with", "desc", "describe"
)


def _build_query_tab(parent, root, db_config, on_data_changed=None):
    """
    Lets the user run a single raw SQL statement against the active
    database. Statements that return rows (SELECT, PRAGMA, SHOW, ...)
    display results in a table; anything else runs as a write (after a
    confirmation prompt) and reports rows affected, then refreshes the
    View Database tab via on_data_changed.
    """

    ctk.CTkLabel(
        parent, text="Query the database", font=("Arial", 16, "bold")
    ).pack(anchor="w", padx=10, pady=(10, 2))

    ctk.CTkLabel(
        parent,
        text="Run a single SQL statement against the active database - "
             "SELECT shows results below; INSERT/UPDATE/DELETE/etc. modify "
             "the database directly (you'll be asked to confirm first).",
        text_color="gray", justify="left", wraplength=700
    ).pack(anchor="w", padx=10, pady=(0, 5))

    ctk.CTkLabel(
        parent, textvariable=db_config.display_var, text_color="gray"
    ).pack(anchor="w", padx=10, pady=(0, 10))

    query_box = ctk.CTkTextbox(parent, height=100, font=("Consolas", 13))
    query_box.pack(fill="x", padx=10, pady=(0, 5))

    status_label = ctk.CTkLabel(
        parent, text="Enter a SQL statement above and run it.",
        text_color="gray"
    )
    status_label.pack(anchor="w", padx=10, pady=(0, 5))

    # RESULTS TABLE (for statements that return rows)----------------------

    results_frame = tkinter.Frame(parent)
    results_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    results_vsb = ttk.Scrollbar(results_frame, orient="vertical")
    results_hsb = ttk.Scrollbar(results_frame, orient="horizontal")

    results_tree = ttk.Treeview(
        results_frame, show="headings",
        yscrollcommand=results_vsb.set, xscrollcommand=results_hsb.set
    )

    results_vsb.configure(command=results_tree.yview)
    results_hsb.configure(command=results_tree.xview)

    results_vsb.pack(side=tkinter.RIGHT, fill=tkinter.Y)
    results_hsb.pack(side=tkinter.BOTTOM, fill=tkinter.X)
    results_tree.pack(side=tkinter.TOP, fill=tkinter.BOTH, expand=True)

    # last successful SELECT's results, kept around so "Export Results to
    # CSV" doesn't have to re-run the query
    last_result = {"columns": None, "rows": None}

    def populate_results(columns, rows):
        results_tree.delete(*results_tree.get_children())
        results_tree["columns"] = columns
        for col in columns:
            results_tree.heading(col, text=col)
            results_tree.column(col, width=110, anchor="center")
        for row in rows:
            results_tree.insert("", "end", values=[row[c] for c in columns])

    def clear_results():
        results_tree.delete(*results_tree.get_children())
        results_tree["columns"] = []
        last_result["columns"] = None
        last_result["rows"] = None
        export_button.configure(state="disabled")

    def looks_read_only(sql):
        return sql.strip().lower().startswith(_READ_ONLY_PREFIXES)

    def confirm_write(sql):
        result = {"confirmed": False}

        dialog = ctk.CTkToplevel(root)
        dialog.title("Confirm database change")
        dialog.geometry("480x240")
        dialog.transient(root)
        dialog.grab_set()

        ctk.CTkLabel(
            dialog, text="This will modify the database:",
            font=("Arial", 14, "bold")
        ).pack(padx=20, pady=(20, 5), anchor="w")

        preview = ctk.CTkTextbox(dialog, height=80)
        preview.pack(fill="x", padx=20)
        preview.insert("1.0", sql)
        preview.configure(state="disabled")

        def on_yes():
            result["confirmed"] = True
            dialog.destroy()

        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_frame.pack(pady=15)

        ctk.CTkButton(
            btn_frame, text="Run it", command=on_yes, fg_color="#a83232"
        ).pack(side="left", padx=10)
        ctk.CTkButton(
            btn_frame, text="Cancel", command=dialog.destroy
        ).pack(side="left", padx=10)

        dialog.wait_window()
        return result["confirmed"]

    def query_succeeded_read(columns, rows):
        populate_results(columns, rows)
        last_result["columns"] = columns
        last_result["rows"] = rows
        export_button.configure(state="normal" if rows else "disabled")
        status_label.configure(
            text=f"{len(rows)} row(s) returned.", text_color="white")
        run_button.configure(state="normal")

    def query_succeeded_write(affected):
        clear_results()
        text = (f"{affected} row(s) affected."
                if affected is not None and affected >= 0
                else "Statement executed successfully.")
        status_label.configure(text=text, text_color="green")
        run_button.configure(state="normal")
        if on_data_changed:
            on_data_changed()

    def query_failed(error):
        status_label.configure(
            text=f"Query failed: {error}", text_color="red")
        run_button.configure(state="normal")

    def do_run(sql):
        try:
            conn = database.connect(db_config)
            try:
                cur = conn.execute(sql)
                if cur.description is not None:
                    columns = [d[0] for d in cur.description]
                    rows = [dict(r) for r in cur.fetchall()]
                    conn.close()
                    parent.after(
                        0, lambda: query_succeeded_read(columns, rows))
                else:
                    conn.commit()
                    affected = cur.rowcount
                    conn.close()
                    parent.after(0, lambda: query_succeeded_write(affected))
            except Exception:
                conn.rollback()
                conn.close()
                raise
        except Exception as e:
            error_text = str(e)
            parent.after(0, lambda: query_failed(error_text))

    def run_query():
        sql = query_box.get("1.0", "end").strip()

        if not sql:
            status_label.configure(
                text="Enter a SQL statement first.", text_color="red")
            return

        if not db_config.is_configured():
            status_label.configure(
                text="No database selected - choose one in the Settings tab.",
                text_color="red")
            return

        if not looks_read_only(sql) and not confirm_write(sql):
            status_label.configure(
                text="Cancelled - nothing was run.", text_color="gray")
            return

        run_button.configure(state="disabled")
        status_label.configure(text="Running...", text_color="gray")

        threading.Thread(target=do_run, args=(sql,), daemon=True).start()

    def export_results_csv():
        columns = last_result["columns"]
        rows = last_result["rows"]

        if not columns or not rows:
            status_label.configure(
                text="No query results to export - run a SELECT first.",
                text_color="red")
            return

        path = filedialog.asksaveasfilename(
            parent=root,
            title="Export query results to CSV",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), ("All files", "*.*")]
        )
        if not path:
            return

        try:
            pd.DataFrame(rows, columns=columns).to_csv(path, index=False)
        except Exception as e:
            status_label.configure(
                text=f"CSV export failed: {e}", text_color="red")
            return

        status_label.configure(
            text=f"Exported {len(rows)} row(s) to {os.path.basename(path)}.",
            text_color="white"
        )

    button_row = ctk.CTkFrame(parent, fg_color="transparent")
    button_row.pack(anchor="w", padx=10, pady=(0, 10))

    run_button = ctk.CTkButton(button_row, text="Run Query", command=run_query)
    run_button.pack(side="left", padx=(0, 5))

    export_button = ctk.CTkButton(
        button_row, text="Export Results to CSV...",
        command=export_results_csv, state="disabled"
    )
    export_button.pack(side="left")
