import os
import threading
from tkinter import filedialog

import customtkinter as ctk
from Bio import SeqIO

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")


def merge_fasta_files(input_paths, output_path):
    records = []
    for path in input_paths:
        records.extend(SeqIO.parse(path, "fasta"))
    SeqIO.write(records, output_path, "fasta")
    return len(records)


class MergeFastaApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Merge FASTA Files")
        self.geometry("650x550")

        self.input_paths = []
        self.output_path = ctk.StringVar()

        ctk.CTkLabel(self, text="📁 FASTA FILES TO MERGE", font=(
            "Arial", 16, "bold")).pack(anchor="w", padx=10, pady=(10, 2))

        button_row = ctk.CTkFrame(self, fg_color="transparent")
        button_row.pack(fill="x", padx=10, pady=(0, 5))

        ctk.CTkButton(
            button_row, text="Add FASTA Files...", command=self.add_files
        ).pack(side="left", padx=(0, 5))

        ctk.CTkButton(
            button_row, text="Clear All", command=self.clear_files, width=80
        ).pack(side="left")

        self.file_list_frame = ctk.CTkScrollableFrame(self, height=250)
        self.file_list_frame.pack(
            fill="both", expand=True, padx=10, pady=(0, 10))

        ctk.CTkLabel(self, text="💾 OUTPUT FILE", font=(
            "Arial", 16, "bold")).pack(anchor="w", padx=10, pady=(0, 2))

        ctk.CTkButton(
            self, text="Choose Output File...", command=self.choose_output
        ).pack(fill="x", padx=10, pady=5)

        ctk.CTkLabel(self, textvariable=self.output_path, text_color="gray").pack(
            anchor="w", padx=10, pady=(0, 10))

        self.status_label = ctk.CTkLabel(self, text="")
        self.status_label.pack(anchor="w", padx=10, pady=(0, 5))

        self.merge_button = ctk.CTkButton(
            self, text="▶ Merge", command=self.start_merge
        )
        self.merge_button.pack(fill="x", padx=10, pady=(0, 10))

        self.refresh_file_list()

    def refresh_file_list(self):
        for widget in self.file_list_frame.winfo_children():
            widget.destroy()

        if not self.input_paths:
            ctk.CTkLabel(
                self.file_list_frame, text="No files selected yet.", text_color="gray"
            ).pack(anchor="w", pady=5)
            return

        for path in self.input_paths:
            row = ctk.CTkFrame(self.file_list_frame, fg_color="transparent")
            row.pack(fill="x", pady=2)

            ctk.CTkLabel(row, text=os.path.basename(path), anchor="w").pack(
                side="left", fill="x", expand=True)

            ctk.CTkButton(
                row, text="✕", width=28,
                command=lambda p=path: self.remove_file(p)
            ).pack(side="right")

    def add_files(self):
        paths = filedialog.askopenfilenames(
            parent=self,
            title="Select FASTA files to merge",
            filetypes=[("FASTA", "*.fasta *.fa *.fna"), ("All files", "*.*")]
        )
        for path in paths:
            if path not in self.input_paths:
                self.input_paths.append(path)
        self.refresh_file_list()

    def remove_file(self, path):
        self.input_paths.remove(path)
        self.refresh_file_list()

    def clear_files(self):
        self.input_paths.clear()
        self.refresh_file_list()

    def choose_output(self):
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Save merged FASTA as",
            defaultextension=".fasta",
            filetypes=[("FASTA", "*.fasta"), ("All files", "*.*")]
        )
        if path:
            self.output_path.set(path)

    def start_merge(self):
        if len(self.input_paths) < 2:
            self.status_label.configure(
                text="Select at least two FASTA files.")
            return

        if not self.output_path.get():
            self.status_label.configure(text="Choose an output file first.")
            return

        self.status_label.configure(text="Merging...")
        self.merge_button.configure(state="disabled")

        thread = threading.Thread(
            target=self._merge_worker,
            args=(list(self.input_paths), self.output_path.get()),
            daemon=True
        )
        thread.start()

    def _merge_worker(self, input_paths, output_path):
        try:
            count = merge_fasta_files(input_paths, output_path)
        except Exception as e:
            self.after(0, lambda: self.status_label.configure(
                text=f"Merge failed: {e}"))
            self.after(0, lambda: self.merge_button.configure(state="normal"))
            return

        def finish():
            self.status_label.configure(
                text=f"Done - {count} sequences written to "
                f"{os.path.basename(output_path)}.")
            self.merge_button.configure(state="normal")

        self.after(0, finish)


if __name__ == "__main__":
    app = MergeFastaApp()
    app.mainloop()
