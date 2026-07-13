import tkinter
from tkinter import filedialog, ttk

import customtkinter as ctk
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# Colorblind-friendly categorical palette
CB_COLORS = ["#2a78d6", "#1baf7a", "#eda100",
             "#008300", "#4a3aa7", "#e34948", "#e87ba4", "#eb6834"]

NON_MARKER_COUNT_COLUMNS = {"NCBI_count", "BOLD_count", "Total_count"}


def get_marker_count_columns(df):
    return [
        c for c in df.columns
        if c.endswith("_count") and c not in NON_MARKER_COUNT_COLUMNS
    ]


def build_retrieval_rate_tab(parent, get_data, root=None):
    """
    parent: the CTkTabview tab frame to build the widgets into.
    get_data: zero-arg callable returning the current retrieval_data
              DataFrame (or None, before any run has completed).
    root: the main app window, used as the save-dialog's parent.
    """

    def get_entry_value(entry):
        value = entry.get()
        return value if value else entry.cget("placeholder_text")

    def Plots(selected_plot):
        df_plot = get_data()

        if df_plot is None or df_plot.empty:
            status_label.configure(
                text="No data yet - run a search on the Fetch FASTA tab first."
            )
            return

        status_label.configure(text="")

        marker_columns = get_marker_count_columns(df_plot)
        marker_labels = [c[:-len("_count")] for c in marker_columns]

        if selected_plot == "Barplot":
            ax.clear()
            ax.set_aspect("auto")

            counts = [df_plot[c].sum() for c in marker_columns]

            ax.bar(marker_labels, counts, color=CB_COLORS[:len(marker_labels)])

            ax.set_xlabel(get_entry_value(plot_xlabel), fontsize=14)
            ax.set_ylabel(get_entry_value(plot_ylabel), fontsize=14)
            ax.set_title(get_entry_value(plot_title), fontsize=16)
            ax.tick_params(axis="both", labelsize=12)
            plt.setp(ax.get_xticklabels(), rotation=20, ha="right")

            for index, value in enumerate(counts):
                ax.text(index, value, str(value),
                        ha="center", va="bottom", fontsize=12)

            fig.tight_layout(pad=3)
            canvas.draw()

        if selected_plot == "Piechart":
            ax.clear()

            counts = [df_plot[c].sum() for c in marker_columns]

            ax.pie(counts, labels=marker_labels, autopct='%1.1f%%',
                   colors=CB_COLORS[:len(marker_labels)],
                   textprops={"fontsize": 14})
            ax.set_title(get_entry_value(plot_title), fontsize=16)
            canvas.draw()

        if selected_plot == "NCBI/BOLD":
            ax.clear()
            ax.set_aspect("auto")

            source_columns = ["NCBI_count", "BOLD_count"]
            counts = [df_plot[c].sum() for c in source_columns]

            ax.bar(source_columns, counts,
                   color=CB_COLORS[:len(source_columns)])

            ax.set_xlabel(get_entry_value(plot_xlabel), fontsize=14)
            ax.set_ylabel(get_entry_value(plot_ylabel), fontsize=14)
            ax.set_title(get_entry_value(plot_title), fontsize=16)
            ax.tick_params(axis="both", labelsize=12)
            plt.setp(ax.get_xticklabels(), rotation=20, ha="right")

            for index, value in enumerate(counts):
                ax.text(index, value, str(value),
                        ha="center", va="bottom", fontsize=12)

            fig.tight_layout(pad=3)
            canvas.draw()

        if selected_plot == "Table":
            table_frame.tkraise()

            tree.delete(*tree.get_children())
            tree["columns"] = list(df_plot.columns)
            for col in df_plot.columns:
                tree.heading(col, text=col)
                tree.column(col, width=100, anchor="center")
            for _, row in df_plot.iterrows():
                tree.insert("", "end", values=list(row))
        else:
            canvas_container.tkraise()

        resize_grip.lift()

    def save_plot():
        file_path = filedialog.asksaveasfilename(
            parent=root,
            defaultextension=".png",
            filetypes=[("PNG image", "*.png"), ("JPEG image", "*.jpg"),
                       ("PDF file", "*.pdf"), ("SVG file", "*.svg")],
            title="Save plot as"
        )
        if file_path:
            fig.savefig(file_path, dpi=fig.dpi, facecolor=fig.get_facecolor())

    plots = ["Barplot", "Piechart", "Table", "NCBI/BOLD"]

    options_frame = ctk.CTkFrame(parent, fg_color="transparent")
    options_frame.pack(pady=(20, 5))

    plot_options = ctk.CTkOptionMenu(options_frame, values=plots)
    plot_options.pack(side=tkinter.LEFT, padx=5)

    plot_title = ctk.CTkEntry(
        options_frame, placeholder_text="FASTA Retrieval Rate")
    plot_title.pack(side=tkinter.LEFT, padx=5)

    plot_xlabel = ctk.CTkEntry(options_frame, placeholder_text="X-label")
    plot_xlabel.pack(side=tkinter.LEFT, padx=5)

    plot_ylabel = ctk.CTkEntry(
        options_frame, placeholder_text="Nr of FASTA sequences")
    plot_ylabel.pack(side=tkinter.LEFT, padx=5)

    button_frame = ctk.CTkFrame(parent, fg_color="transparent")
    button_frame.pack(pady=10)

    display_button = ctk.CTkButton(
        button_frame, text="Display", command=lambda: Plots(plot_options.get()))
    display_button.pack(side=tkinter.LEFT, padx=5)

    save_button = ctk.CTkButton(
        button_frame, text="Save Plot", command=save_plot)
    save_button.pack(side=tkinter.LEFT, padx=5)

    status_label = ctk.CTkLabel(parent, text="", text_color="gray")
    status_label.pack(pady=(0, 5))

    plot_frame = tkinter.Frame(
        parent, bg="white", highlightbackground="#3a3a3a", highlightthickness=1)
    plot_frame.place(x=20, y=150, width=1180, height=600)

    canvas_container = tkinter.Frame(plot_frame)
    canvas_container.place(x=0, y=0, relwidth=1, relheight=1)

    fig, ax = plt.subplots(figsize=(7, 3.6), dpi=100)
    canvas = FigureCanvasTkAgg(fig, master=canvas_container)
    canvas_widget = canvas.get_tk_widget()
    canvas_widget.pack(fill=tkinter.BOTH, expand=True)

    table_style = ttk.Style()
    table_style.theme_use("clam")
    table_style.configure(
        "Treeview",
        background="#2b2b2b", fieldbackground="#2b2b2b",
        foreground="white", rowheight=40,
        font=("Arial", 18)
    )
    table_style.configure(
        "Treeview.Heading",
        background="#3a3a3a", foreground="white",
        font=("Arial", 18, "bold")
    )

    table_frame = tkinter.Frame(plot_frame)
    table_frame.place(x=0, y=0, relwidth=1, relheight=1)

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
    tree.pack(fill=tkinter.BOTH, expand=True)

    canvas_container.tkraise()

    def on_resize(event):
        fig.tight_layout(pad=3)
        canvas.draw_idle()

    fig.canvas.mpl_connect("resize_event", on_resize)

    resize_grip = tkinter.Frame(
        plot_frame, bg="#3a3a3a", width=14, height=14, cursor="size_nw_se")
    resize_grip.place(relx=1.0, rely=1.0, anchor="se")
    resize_grip.lift()

    _grip_start = {}

    def start_frame_resize(event):
        _grip_start["x"] = event.x_root
        _grip_start["y"] = event.y_root
        _grip_start["width"] = plot_frame.winfo_width()
        _grip_start["height"] = plot_frame.winfo_height()

    def do_frame_resize(event):
        dx = event.x_root - _grip_start["x"]
        dy = event.y_root - _grip_start["y"]
        new_width = max(_grip_start["width"] + dx, 200)
        new_height = max(_grip_start["height"] + dy, 150)
        plot_frame.place_configure(width=new_width, height=new_height)

    resize_grip.bind("<ButtonPress-1>", start_frame_resize)
    resize_grip.bind("<B1-Motion>", do_frame_resize)
