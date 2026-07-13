import tkinter
from tkinter import filedialog, ttk
import customtkinter
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import pandas as pd


df_plot = pd.read_csv(r"B:\Stage\test\summary.csv")

# Colorblind-friendly categorical palette
CB_COLORS = ["#2a78d6", "#1baf7a", "#eda100",
             "#008300", "#4a3aa7", "#e34948", "#e87ba4", "#eb6834"]


def get_entry_value(entry):
    value = entry.get()
    return value if value else entry.cget("placeholder_text")


def Plots(selected_plot):
    plot_options.configure()

    if selected_plot == "Barplot":
        ax.clear()
        ax.set_aspect("auto")
        markers = ["ITS1_count",  "ITS2_count",  "rbcL_count",
                   "matK_count",  "trnL_count",  "psbA-trnH_count"]

        counts = []

        for marker in markers:
            m = df_plot[marker].sum()
            counts.append(m)

        ax.bar(markers, counts, color=CB_COLORS[:len(markers)])

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
        markers = ["ITS1_count",  "ITS2_count",  "rbcL_count",
                   "matK_count",  "trnL_count",  "psbA-trnH_count"]

        counts = []

        for marker in markers:
            m = df_plot[marker].sum()
            counts.append(m)

        ax.pie(counts, labels=markers, autopct='%1.1f%%',
               colors=CB_COLORS[:len(markers)],
               textprops={"fontsize": 14})
        ax.set_title(get_entry_value(plot_title), fontsize=16)
        canvas.draw()

    if selected_plot == "NCBI/BOLD":
        ax.clear()
        ax.set_aspect("auto")
        markers = ["NCBI_count", "BOLD_count"]

        counts = []

        for marker in markers:
            m = df_plot[marker].sum()
            counts.append(m)

        ax.bar(markers, counts, color=CB_COLORS[:len(markers)])

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
        parent=tk,
        defaultextension=".png",
        filetypes=[("PNG image", "*.png"), ("JPEG image", "*.jpg"),
                   ("PDF file", "*.pdf"), ("SVG file", "*.svg")],
        title="Save plot as")
    if file_path:
        fig.savefig(file_path, dpi=fig.dpi, facecolor=fig.get_facecolor())


# GUI--------------------------------------------------------------------
customtkinter.set_appearance_mode("dark")
customtkinter.set_default_color_theme("dark-blue")

tk = customtkinter.CTk()

tk.title("plot")
tk.geometry("760x520")

plots = ["Barplot", "Piechart", "Table", "NCBI/BOLD"]

options_frame = customtkinter.CTkFrame(tk, fg_color="transparent")
options_frame.pack(pady=40)

plot_options = customtkinter.CTkOptionMenu(options_frame, values=plots)
plot_options.pack(side=tkinter.LEFT, padx=5)

plot_title = customtkinter.CTkEntry(
    options_frame, placeholder_text="FASTA Retrieval Rate")
plot_title.pack(side=tkinter.LEFT, padx=5)

plot_xlabel = customtkinter.CTkEntry(options_frame, placeholder_text="X-label")
plot_xlabel.pack(side=tkinter.LEFT, padx=5)

plot_ylabel = customtkinter.CTkEntry(
    options_frame, placeholder_text="Nr of FASTA sequences")
plot_ylabel.pack(side=tkinter.LEFT, padx=5)

button_frame = customtkinter.CTkFrame(tk, fg_color="transparent")
button_frame.pack(pady=10)

display_button = customtkinter.CTkButton(
    button_frame, text="Display", command=lambda: Plots(plot_options.get()))
display_button.pack(side=tkinter.LEFT, padx=5)

save_button = customtkinter.CTkButton(
    button_frame, text="Save Plot", command=save_plot)
save_button.pack(side=tkinter.LEFT, padx=5)

tk.resizable(True, True)
tk.minsize(400, 300)

plot_frame = tkinter.Frame(
    tk, bg="white", highlightbackground="#3a3a3a", highlightthickness=1)
plot_frame.place(x=25, y=250, width=710, height=250)

canvas_container = tkinter.Frame(plot_frame)
canvas_container.place(x=0, y=0, relwidth=1, relheight=1)

fig, ax = plt.subplots(figsize=(7, 3.6), dpi=100)
canvas = FigureCanvasTkAgg(fig, master=canvas_container)
canvas_widget = canvas.get_tk_widget()
canvas_widget.pack(fill=tkinter.BOTH, expand=True)

table_style = ttk.Style()
table_style.theme_use("clam")
table_style.configure("Treeview",
                      background="#2b2b2b", fieldbackground="#2b2b2b",
                      foreground="white", rowheight=40,
                      font=("Arial", 18))
table_style.configure("Treeview.Heading",
                      background="#3a3a3a", foreground="white",
                      font=("Arial", 18, "bold"))

table_frame = tkinter.Frame(plot_frame)
table_frame.place(x=0, y=0, relwidth=1, relheight=1)

table_vsb = ttk.Scrollbar(table_frame, orient="vertical")
table_hsb = ttk.Scrollbar(table_frame, orient="horizontal")

tree = ttk.Treeview(table_frame, show="headings",
                    yscrollcommand=table_vsb.set,
                    xscrollcommand=table_hsb.set)

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


def on_closing():
    plt.close(fig)
    tk.quit()
    tk.destroy()


tk.protocol("WM_DELETE_WINDOW", on_closing)

tk.mainloop()
