---
layout: default
title: GUI version
nav_order: 2
---

# GUI Version

The GUI folder contains a small graphical utility for running the
[`gdeltnews`](https://github.com/iandreafc/gdeltnews) pipeline without
writing Python code. The program wraps the three high‑level functions
provided by the package into an easy‑to‑use interface and adds a
recap tab with a textual overview of the pipeline:

1. **Recap** – presents a short explanation of the pipeline steps and
   options.  This informational tab helps users understand what each
   operation does.
2. **Download** – fetches Web NGrams files from the GDELT project for a
   specified time range and writes the compressed files (and optionally
   the decompressed JSON files) into a directory of your choice.
3. **Reconstruct** – reconstructs full article text from the downloaded
   n‑gram fragments and writes one CSV per input file.
4. **Filter & merge** – filters the reconstructed CSVs using a
   Boolean query, de‑duplicates by URL and merges everything into a
   single file.

The GUI is built with the standard `tkinter` library so there are no
extra dependencies beyond `gdeltnews` itself.  Fonts and padding have
been tuned for improved readability and the interface uses a modern
theme where available.

## Installation

Make sure Python 3.9 or later is installed on your system.  You also
need to install the `gdeltnews` package from PyPI:

```bash
pip install gdeltnews
```

Donwload the GUI folder and run `main.py` from a terminal:

```bash
python main.py
```

<!-- If you would like to create a standalone executable for Windows you can
use [PyInstaller](https://pyinstaller.org/). From within the GUI
directory run:

```bash
py -m venv .venv
.\.venv\Scripts\activate.bat

python -m pip install --upgrade pip setuptools wheel
python -m pip install gdeltnews
python -m pip install pyinstaller

pyinstaller --noconfirm --clean --windowed --onedir --name "gdeltnewsexe" main.py
```

The resulting `gdeltnewsexe`folder can be distributed to non‑technical
users.  Note that building Windows binaries must be done on a Windows
machine; cross‑compilation from Linux is not supported.-->

## Usage

When you start the program a window with four tabs appears: Recap, Download,
Reconstruct, and Filter/Merge.

* **Recap** – read a brief description of the three steps above and
  learn how the application orchestrates downloading, reconstructing
  and filtrating the data.  This tab does not perform any action but
  serves as an easy reference.

* **Download** – enter a start date/time and an end date/time using
  the ISO format `YYYY‑MM‑DDTHH:MM:SS`, choose an output directory
  where the compressed `.gz` files will be saved and decide whether
  the program should decompress the files as they are downloaded.

* **Reconstruct** – select the directory containing the downloaded
  `.webngrams.json.gz` files, choose an output directory for the
  reconstructed CSVs and optionally specify a language code (e.g.
  `en` or `it`), one or more URL filters (comma‑separated) and the
  number of worker processes to use (leave blank to use all cores).

* **Filter/Merge** – select the directory containing the per‑file
  CSVs, choose a destination path for the final CSV and write a
  Boolean query to filter the articles.  The query syntax uses
  `AND`, `OR` and `NOT` with parentheses; use double quotes to
  match phrases.

Click the **Run** button in each operational tab (Download,
Reconstruct or Filter/Merge) to execute the corresponding
operation.  A progress bar at the bottom of each tab indicates how
much of the operation has completed, and a pop‑up message will notify
you when the task completes or if an error occurs.