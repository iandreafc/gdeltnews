"""
GDELTNews GUI
---------------

This module implements a tiny graphical user interface around the
`gdeltnews` package.  It exposes three tabs: one for downloading
Web NGrams files, one for reconstructing articles from the downloaded
files, and one for filtering/merging the reconstructed CSVs.  Each
operation runs in a background thread so the UI remains responsive.

To run the GUI install the `gdeltnews` package (e.g. with
``pip install gdeltnews``) and then execute this script with
``python main.py``.  See the accompanying `README.md` for details.
"""

import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

# These imports raise ImportError if gdeltnews is not installed.  The
# error will be surfaced to the user when they attempt to run a
# pipeline step.
try:
    # Import top-level functions for convenience.  These are still used
    # for the default fallback paths when progress reporting is not
    # required.
    from gdeltnews.download import download  # type: ignore
    from gdeltnews.reconstruct import reconstruct  # type: ignore
    from gdeltnews.filtermerge import filtermerge  # type: ignore
    # Import internal helpers so that we can implement our own progress
    # reporting while reusing the core logic of the package.  These
    # imports are all conditional so that a missing dependency surfaces
    # gracefully when a user attempts to run the corresponding task.
    from gdeltnews.download import (
        parse_timestamp as dl_parse_timestamp,
        iter_minutes as dl_iter_minutes,
        download_gdelt_file as dl_download_gdelt_file,
        decompress_gzip as dl_decompress_gzip,
    )  # type: ignore
    from gdeltnews.reconstruct import (
        find_gz_files as rc_find_gz_files,
        decompress_gzip as rc_decompress_gzip,
        process_file_multiprocessing as rc_process_file_multiprocessing,
        csv_has_data as rc_csv_has_data,
    )  # type: ignore
    from gdeltnews.filtermerge import (
        build_query_expr as fm_build_query_expr,
        iter_csv_files as fm_iter_csv_files,
        text_matches_query as fm_text_matches_query,
        deduplicate_by_url as fm_deduplicate_by_url,
    )  # type: ignore
except Exception:
    # We defer handling import errors until runtime.  See `_require_module`.
    download = None  # type: ignore
    reconstruct = None  # type: ignore
    filtermerge = None  # type: ignore


def _require_module():
    """Raise a user‑friendly error if the gdeltnews module is missing."""
    if download is None or reconstruct is None or filtermerge is None:
        raise RuntimeError(
            "The 'gdeltnews' package is not installed. Please run "
            "'pip install gdeltnews' and try again."
        )


class GdeltNewsGUI:
    """Main application class encapsulating all tabs and logic."""

    def __init__(self, master: tk.Tk) -> None:
        self.master = master
        master.title("GDELT News Pipeline")
        # Increase window size for a more spacious layout
        master.geometry("700x550")
        master.resizable(False, False)

        # Define fonts for a more appealing look
        self.label_font = ("Helvetica", 11)
        self.entry_font = ("Helvetica", 11)
        self.button_font = ("Helvetica", 11, "bold")
        self.tab_font = ("Helvetica", 12, "bold")


        # Configure ttk styles
        style = ttk.Style(master)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        # ------------------------------------------------------------------
        # Colors
        # ------------------------------------------------------------------
        # Main background (very light blue) and accents (slightly darker blue)
        self.bg = "#d9efff"
        self.accent = "#8cc9ff"         # tabs + buttons
        self.accent_active = "#6bb8ff"  # hover/pressed
        self.progress_bar = "#4da3ff"   # moving bar
        self.white = "#ffffff"

        # Non-ttk root background + highlight borders
        master.configure(bg=self.bg, highlightbackground=self.white, highlightcolor=self.white)

        # Base widget styling
        style.configure(".", background=self.bg)
        style.configure("TFrame", background=self.bg)
        style.configure("TLabel", background=self.bg)
        style.configure("TLabelframe", background=self.bg, bordercolor=self.white, lightcolor=self.white, darkcolor=self.white)
        style.configure("TLabelframe.Label", background=self.bg)
        style.configure("TCheckbutton", background=self.bg)

        # Notebook + tabs (remove beige inner border)
        style.configure("TNotebook", background=self.bg, borderwidth=0, relief="flat")
        style.configure(
            "TNotebook.Tab",
            background=self.accent,
            borderwidth=1,
            relief="flat",
            lightcolor=self.white,
            darkcolor=self.white,
            bordercolor=self.white,
            focuscolor=self.white,
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", self.accent), ("active", self.accent_active)],
            lightcolor=[("selected", self.white), ("active", self.white)],
            darkcolor=[("selected", self.white), ("active", self.white)],
            bordercolor=[("selected", self.white), ("active", self.white)],
        )

        # Buttons (remove beige outline)
        style.configure(
            "TButton",
            font=self.button_font,
            padding=6,
            background=self.accent,
            relief="flat",
            borderwidth=1,
            lightcolor=self.white,
            darkcolor=self.white,
            bordercolor=self.white,
            focuscolor=self.white,
        )
        style.map(
            "TButton",
            background=[("active", self.accent_active), ("pressed", self.accent_active)],
            bordercolor=[("active", self.white), ("pressed", self.white)],
            lightcolor=[("active", self.white), ("pressed", self.white)],
            darkcolor=[("active", self.white), ("pressed", self.white)],
        )

        # Other widgets (fonts)
        style.configure("TLabel", font=self.label_font)
        style.configure("TEntry", font=self.entry_font)
        style.configure("TCheckbutton", font=self.label_font)
        style.configure("TNotebook.Tab", font=self.tab_font, padding=[12, 6])

        # Progress bars: white trough + blue bar, no beige frame
        style.configure(
            "Horizontal.TProgressbar",
            troughcolor=self.white,
            background=self.progress_bar,
            borderwidth=0,
            relief="flat",
            lightcolor=self.white,
            darkcolor=self.white,
            bordercolor=self.white,
        )

        self.notebook = ttk.Notebook(master)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self._create_recap_tab()
        self._create_download_tab()
        self._create_reconstruct_tab()
        self._create_filter_tab()


    # ------------------------------------------------------------------
    # Tab creation helpers
    # ------------------------------------------------------------------
    def _create_download_tab(self) -> None:
        """Create the widgets for the 'Download' tab."""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Download")

        row = 0
        ttk.Label(tab, text="Start time (YYYY‑MM‑DDTHH:MM:SS)").grid(
            row=row, column=0, sticky=tk.W, padx=10, pady=5
        )
        self.start_entry = ttk.Entry(tab, width=30)
        self.start_entry.grid(row=row, column=1, padx=10, pady=5)
        row += 1

        ttk.Label(tab, text="End time (YYYY‑MM‑DDTHH:MM:SS)").grid(
            row=row, column=0, sticky=tk.W, padx=10, pady=5
        )
        self.end_entry = ttk.Entry(tab, width=30)
        self.end_entry.grid(row=row, column=1, padx=10, pady=5)
        row += 1

        ttk.Label(tab, text="Output directory").grid(
            row=row, column=0, sticky=tk.W, padx=10, pady=5
        )
        self.download_dir_var = tk.StringVar()
        download_dir_entry = ttk.Entry(tab, textvariable=self.download_dir_var, width=30)
        download_dir_entry.grid(row=row, column=1, padx=10, pady=5)
        ttk.Button(
            tab,
            text="Browse…",
            command=lambda: self._choose_directory(self.download_dir_var),
        ).grid(row=row, column=2, padx=10, pady=5)
        row += 1

        self.decompress_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(tab, text="Decompress", variable=self.decompress_var).grid(
            row=row, column=0, sticky=tk.W, padx=10, pady=5
        )
        self.overwrite_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(tab, text="Overwrite existing", variable=self.overwrite_var).grid(
            row=row, column=1, sticky=tk.W, padx=10, pady=5
        )
        row += 1

        # Run button
        ttk.Button(tab, text="Run download", command=self._run_download).grid(
            row=row, column=0, columnspan=3, pady=15
        )
        # Progress bar (initially zero).  The determinate mode allows us
        # to reflect percentage completed.
        row += 1
        self.download_progress = ttk.Progressbar(
            tab, orient="horizontal", mode="determinate", maximum=100, length=450
        )
        self.download_progress.grid(row=row, column=0, columnspan=3, padx=10, pady=5, sticky="we")

    def _create_reconstruct_tab(self) -> None:
        """Create the widgets for the 'Reconstruct' tab."""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Reconstruct")

        row = 0
        ttk.Label(tab, text="Input directory").grid(
            row=row, column=0, sticky=tk.W, padx=10, pady=5
        )
        self.recon_in_var = tk.StringVar()
        ttk.Entry(tab, textvariable=self.recon_in_var, width=30).grid(
            row=row, column=1, padx=10, pady=5
        )
        ttk.Button(
            tab,
            text="Browse…",
            command=lambda: self._choose_directory(self.recon_in_var),
        ).grid(row=row, column=2, padx=10, pady=5)
        row += 1

        ttk.Label(tab, text="Output directory").grid(
            row=row, column=0, sticky=tk.W, padx=10, pady=5
        )
        self.recon_out_var = tk.StringVar()
        ttk.Entry(tab, textvariable=self.recon_out_var, width=30).grid(
            row=row, column=1, padx=10, pady=5
        )
        ttk.Button(
            tab,
            text="Browse…",
            command=lambda: self._choose_directory(self.recon_out_var),
        ).grid(row=row, column=2, padx=10, pady=5)
        row += 1

        ttk.Label(tab, text="Language (optional)").grid(
            row=row, column=0, sticky=tk.W, padx=10, pady=5
        )
        self.lang_var = tk.StringVar()
        ttk.Entry(tab, textvariable=self.lang_var, width=10).grid(
            row=row, column=1, padx=10, pady=5, sticky=tk.W
        )
        row += 1

        ttk.Label(tab, text="URL filters (comma‑separated)").grid(
            row=row, column=0, sticky=tk.W, padx=10, pady=5
        )
        self.url_filters_var = tk.StringVar()
        ttk.Entry(tab, textvariable=self.url_filters_var, width=30).grid(
            row=row, column=1, padx=10, pady=5
        )
        row += 1

        ttk.Label(tab, text="Processes (leave blank for all cores)").grid(
            row=row, column=0, sticky=tk.W, padx=10, pady=5
        )
        self.processes_var = tk.StringVar()
        ttk.Entry(tab, textvariable=self.processes_var, width=10).grid(
            row=row, column=1, padx=10, pady=5, sticky=tk.W
        )
        row += 1

        self.del_gz_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(tab, text="Delete .gz after processing", variable=self.del_gz_var).grid(
            row=row, column=0, sticky=tk.W, padx=10, pady=5
        )
        self.del_json_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(tab, text="Delete decompressed .json", variable=self.del_json_var).grid(
            row=row, column=1, sticky=tk.W, padx=10, pady=5
        )
        row += 1

        self.del_empty_csv_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            tab,
            text="Delete empty CSVs",
            variable=self.del_empty_csv_var,
        ).grid(row=row, column=0, sticky=tk.W, padx=10, pady=5)
        row += 1

        # Run button
        ttk.Button(tab, text="Run reconstruct", command=self._run_reconstruct).grid(
            row=row, column=0, columnspan=3, pady=15
        )
        # Progress bar for reconstruction
        row += 1
        self.recon_progress = ttk.Progressbar(
            tab, orient="horizontal", mode="determinate", maximum=100, length=450
        )
        self.recon_progress.grid(row=row, column=0, columnspan=3, padx=10, pady=5, sticky="we")

    def _create_filter_tab(self) -> None:
        """Create the widgets for the 'Filter/Merge' tab."""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Filter/Merge")

        row = 0
        ttk.Label(tab, text="Input directory").grid(
            row=row, column=0, sticky=tk.W, padx=10, pady=5
        )
        self.filter_in_var = tk.StringVar()
        ttk.Entry(tab, textvariable=self.filter_in_var, width=30).grid(
            row=row, column=1, padx=10, pady=5
        )
        ttk.Button(
            tab,
            text="Browse…",
            command=lambda: self._choose_directory(self.filter_in_var),
        ).grid(row=row, column=2, padx=10, pady=5)
        row += 1

        ttk.Label(tab, text="Output CSV file").grid(
            row=row, column=0, sticky=tk.W, padx=10, pady=5
        )
        self.filter_out_var = tk.StringVar()
        ttk.Entry(tab, textvariable=self.filter_out_var, width=30).grid(
            row=row, column=1, padx=10, pady=5
        )
        ttk.Button(
            tab,
            text="Browse…",
            command=lambda: self._choose_savefile(self.filter_out_var),
        ).grid(row=row, column=2, padx=10, pady=5)
        row += 1

        ttk.Label(tab, text="Boolean query (optional)").grid(
            row=row, column=0, sticky=tk.W, padx=10, pady=5
        )
        self.query_var = tk.StringVar()
        ttk.Entry(tab, textvariable=self.query_var, width=40).grid(
            row=row, column=1, padx=10, pady=5, columnspan=2
        )
        row += 1

        self.keep_temp_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(tab, text="Keep temporary file", variable=self.keep_temp_var).grid(
            row=row, column=0, sticky=tk.W, padx=10, pady=5
        )
        row += 1

        # Run button
        ttk.Button(tab, text="Run filter/merge", command=self._run_filtermerge).grid(
            row=row, column=0, columnspan=3, pady=15
        )
        # Progress bar for filtering/merging
        row += 1
        self.filter_progress = ttk.Progressbar(
            tab, orient="horizontal", mode="determinate", maximum=100, length=450
        )
        self.filter_progress.grid(row=row, column=0, columnspan=3, padx=10, pady=5, sticky="we")

    def _create_recap_tab(self) -> None:
        """Create an informational tab that explains the pipeline steps.

        This tab is purely informational. It outlines the three stages of the
        GDELT news pipeline so that users have context on what each action
        does. A read‑only text widget displays a short explanation of
        downloading, reconstructing and filtering the news data. Fonts and
        padding mirror the rest of the interface for a cohesive look.
        """
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Recap")

        # Use a Text widget for multi‑line content. Wrap words and disable editing.
        recap_text = tk.Text(
            tab,
            wrap="word",
            font=self.label_font,
            width=80,
            height=20,
            bg=self.white,
            fg="black",
            insertbackground="black",
            relief="flat",
            highlightthickness=1,
            highlightbackground=self.white,
            highlightcolor=self.white,
        )
        recap_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Assemble the explanatory text.  Keep the Italian phrasing clear and
        # concise and avoid splitting sentences with hyphens except for
        # compound words like problem‑solving.  The description is derived
        # from the gdeltnews quickstart guide but rewritten for the GUI.
        explanation = (
            "This app is a GUI for the 'gdeltnews' package. It can be used to obtain structured text "
            "starting from the Web NGrams files of the GDELT project. The process is divided "
            "into three successive phases.\n\n"
            "1. Download: the Web NGrams files are downloaded for a selected time interval. "
            "The files are saved in compressed .gz format in the specified folder and, if the 'Decompress' option is selected, "
            "they are also extracted in JSON format.\n\n"
            "2. Reconstruct: the downloaded files are read, sentences are reconstructed "
            "from overlapping n-grams, and CSVs are produced with one row per article. "
            "It is possible to filter by language, restrict to specific domains or URLs, and "
            "choose the number of processes. Depending on the chosen options, temporary files "
            "can be deleted automatically.\n\n"
            "3. Filter and merge: the reconstructed CSVs are filtered with a boolean query "
            "(AND, OR, NOT, and parentheses), then they are deduplicated by URL while keeping the "
            "version with the longest text, and a single final CSV file is written."
        )

        recap_text.insert("1.0", explanation)
        recap_text.config(state=tk.DISABLED)

    # ------------------------------------------------------------------
    # Utility methods
    # ------------------------------------------------------------------
    @staticmethod
    def _choose_directory(var: tk.StringVar) -> None:
        """Open a directory chooser and assign the result to the given variable."""
        path = filedialog.askdirectory()
        if path:
            var.set(path)

    @staticmethod
    def _choose_savefile(var: tk.StringVar) -> None:
        """Open a file save dialog and assign the result to the given variable."""
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if path:
            var.set(path)

    def _run_in_thread(self, func, *args, **kwargs) -> None:
        """Run `func` in a separate thread and report errors via a pop‑up."""

        def wrapper() -> None:
            try:
                _require_module()
                func(*args, **kwargs)
                self.master.after(
                    0, lambda: messagebox.showinfo("Done", "Operation completed successfully.")
                )
            except Exception as exc:
                self.master.after(
                    0,
                    lambda: messagebox.showerror(
                        "Error", f"An error occurred: {exc}"
                    ),
                )

        threading.Thread(target=wrapper, daemon=True).start()

    # ------------------------------------------------------------------
    # Operation handlers
    # ------------------------------------------------------------------
    def _run_download(self) -> None:
        """Collect parameters and start the download operation."""
        start = self.start_entry.get().strip()
        end = self.end_entry.get().strip()
        outdir = self.download_dir_var.get().strip()
        decompress = self.decompress_var.get()
        overwrite = self.overwrite_var.get()

        if not start or not end or not outdir:
            messagebox.showerror(
                "Missing values", "Start time, end time and output directory must be provided."
            )
            return

        # Reset progress bar before starting
        self.download_progress.config(value=0)

        def task() -> None:
            # Use internal helpers to show progress.  Parsing errors will
            # propagate as exceptions and be handled by `_run_in_thread`.
            start_dt = dl_parse_timestamp(start)
            end_dt = dl_parse_timestamp(end)
            minutes = list(dl_iter_minutes(start_dt, end_dt))
            total = len(minutes)
            if total == 0:
                raise ValueError("The selected time range covers zero minutes.")

            for idx, ts in enumerate(minutes):
                # download the .gz file (quiet=True to avoid printing to stdout)
                gz_path = dl_download_gdelt_file(
                    ts,
                    outdir,
                    overwrite=overwrite,
                    timeout=30,
                    quiet=True,
                )
                # decompress if requested and the file exists
                if gz_path is not None and decompress:
                    try:
                        dl_decompress_gzip(gz_path)
                    except Exception:
                        # Decompression errors are not fatal; skip silently
                        pass
                # update progress bar
                progress = int((idx + 1) / total * 100)
                self.master.after(
                    0,
                    lambda val=progress: self.download_progress.config(value=val),
                )

        # Run our custom download task with progress reporting
        self._run_in_thread(task)

    def _run_reconstruct(self) -> None:
        """Collect parameters and start the reconstruct operation."""
        input_dir = self.recon_in_var.get().strip()
        output_dir = self.recon_out_var.get().strip()
        if not input_dir or not output_dir:
            messagebox.showerror(
                "Missing values", "Input and output directories must be provided."
            )
            return

        language = self.lang_var.get().strip() or None
        url_filters_str = self.url_filters_var.get().strip()
        url_filters = (
            [x.strip() for x in url_filters_str.split(",") if x.strip()]
            if url_filters_str
            else None
        )
        processes_str = self.processes_var.get().strip()
        processes = None
        if processes_str:
            try:
                processes = int(processes_str)
            except ValueError:
                messagebox.showerror(
                    "Invalid value", "Processes must be an integer or left blank."
                )
                return

        delete_gz = self.del_gz_var.get()
        delete_json = self.del_json_var.get()
        delete_empty = self.del_empty_csv_var.get()

        # Reset progress bar before starting
        self.recon_progress.config(value=0)

        def task() -> None:
            import os
            from pathlib import Path

            in_path = Path(input_dir)
            out_path = Path(output_dir)
            gz_files = rc_find_gz_files(in_path)
            total = len(gz_files)
            if total == 0:
                raise ValueError(f"No *.webngrams.json.gz files found in {in_path}")

            # Normalize URL filters into a list or None
            url_filters_list = url_filters

            # ensure output directory exists
            out_path.mkdir(parents=True, exist_ok=True)

            for idx, gz_path in enumerate(gz_files):
                # Step 1: decompress to .json
                try:
                    json_path = rc_decompress_gzip(gz_path)
                except Exception:
                    # Skip file if decompression fails
                    continue

                # Step 2: determine CSV output path
                base_name = Path(str(json_path)).stem  # e.g. 20250316000100.webngrams
                csv_name = f"{base_name}.articles.csv"
                csv_path = out_path / csv_name

                # Step 3: run multiprocessing reconstruction
                try:
                    rc_process_file_multiprocessing(
                        input_file=str(json_path),
                        output_file=str(csv_path),
                        language_filter=language,
                        url_filter=url_filters_list,
                        num_processes=processes,
                    )
                except Exception:
                    # Continue even if one file fails
                    pass
                finally:
                    # Step 4: optionally remove decompressed .json
                    if delete_json:
                        try:
                            if Path(json_path).exists():
                                os.remove(json_path)
                        except Exception:
                            pass

                # Step 5: optionally remove empty CSVs
                if delete_empty and csv_path.exists() and not rc_csv_has_data(csv_path):
                    try:
                        os.remove(csv_path)
                    except Exception:
                        pass

                # Step 6: optionally remove the original .gz file
                if delete_gz:
                    try:
                        if gz_path.exists():
                            os.remove(gz_path)
                    except Exception:
                        pass

                # update progress bar
                progress = int((idx + 1) / total * 100)
                self.master.after(
                    0,
                    lambda val=progress: self.recon_progress.config(value=val),
                )

        # Run our custom reconstruction task with progress reporting
        self._run_in_thread(task)

    def _run_filtermerge(self) -> None:
        """Collect parameters and start the filter/merge operation."""
        input_dir = self.filter_in_var.get().strip()
        output_file = self.filter_out_var.get().strip()
        if not input_dir or not output_file:
            messagebox.showerror(
                "Missing values", "Input directory and output file must be provided."
            )
            return

        query = self.query_var.get().strip() or None
        keep_temp = self.keep_temp_var.get()

        # Reset progress bar before starting
        self.filter_progress.config(value=0)

        def task() -> None:
            import csv
            import os
            # Build query expression using gdeltnews utilities.  This may
            # raise ValueError on invalid queries, which will be surfaced.
            expr, phrases = fm_build_query_expr(query)
            # Determine temporary output path
            temp_output = output_file + ".tmp"

            # Find all CSV files in the input directory
            csv_files = fm_iter_csv_files(input_dir)
            total = len(csv_files)
            if total == 0:
                raise ValueError(f"No CSV files found in directory: {input_dir}")

            # Step 1: filter rows into temporary file
            with open(temp_output, "w", newline="", encoding="utf-8") as out_f:
                writer = csv.writer(out_f, delimiter="|", quoting=csv.QUOTE_NONE)
                writer.writerow(["Text", "Date", "URL", "Source"])
                for idx, path in enumerate(csv_files):
                    with open(path, "r", encoding="utf-8") as in_f:
                        reader = csv.reader(in_f, delimiter="|")
                        try:
                            header = next(reader)
                        except StopIteration:
                            continue
                        col_index = {name: i for i, name in enumerate(header)}
                        if "Text" not in col_index or "URL" not in col_index:
                            continue
                        text_idx = col_index["Text"]
                        date_idx = col_index.get("Date")
                        url_idx = col_index["URL"]
                        source_idx = col_index.get("Source")
                        for row in reader:
                            if len(row) <= max(text_idx, url_idx):
                                continue
                            text_val = row[text_idx]
                            # Evaluate boolean query (case-insensitive substring match)
                            if not fm_text_matches_query(text_val, expr, phrases):
                                continue
                            date_val = row[date_idx] if date_idx is not None and date_idx < len(row) else ""
                            url_val = row[url_idx]
                            source_val = row[source_idx] if source_idx is not None and source_idx < len(row) else ""
                            writer.writerow([text_val, date_val, url_val, source_val])
                    # update progress bar (filtering stage accounts for 90% of total)
                    progress = int((idx + 1) / total * 90)
                    self.master.after(
                        0,
                        lambda val=progress: self.filter_progress.config(value=val),
                    )

            # Step 2: deduplicate by URL and write final output
            fm_deduplicate_by_url(temp_output, output_file)
            # After deduplication set progress to 100%
            self.master.after(
                0,
                lambda: self.filter_progress.config(value=100),
            )
            # Optionally remove the temporary file
            if not keep_temp and os.path.exists(temp_output):
                try:
                    os.remove(temp_output)
                except Exception:
                    pass

        # Run our custom filter/merge task with progress reporting
        self._run_in_thread(task)


def main() -> None:
    """Entry point for the GUI.

    On Windows, PyInstaller bundles frozen executables must call
    ``multiprocessing.freeze_support()`` before doing anything else.  This
    wrapper ensures that the GUI can be built into a standalone binary
    without requiring users to install Python separately.  Any uncaught
    exception will be surfaced to the user via a simple message box.
    """
    from multiprocessing import freeze_support

    freeze_support()
    root = tk.Tk()
    try:
        app = GdeltNewsGUI(root)
        root.mainloop()
    except Exception as exc:
        # If initialization fails (e.g. missing dependencies), show a pop‑up
        messagebox.showerror("Startup Error", f"Errore durante l'avvio dell'applicazione: {exc}")
        root.destroy()


if __name__ == "__main__":
    main()