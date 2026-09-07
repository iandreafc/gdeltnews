## Reconstructing Full-Text News Articles from GDELT - gdeltnews

Reconstruct full news article text from the GDELT Web News NGrams 3.0 dataset.

This package helps you:
1) download GDELT Web NGrams files for a time range,
2) reconstruct article text from overlapping n-gram fragments,
3) filter and merge reconstructed CSVs using Boolean queries.

To learn more about the dataset, please visit the official announcement:
[https://blog.gdeltproject.org/announcing-the-new-web-news-ngrams-3-0-dataset/](https://blog.gdeltproject.org/announcing-the-new-web-news-ngrams-3-0-dataset/)

Input files look like:
http://data.gdeltproject.org/gdeltv3/webngrams/20250316000100.webngrams.json.gz

Reconstruction quality depends on the n-gram fragments available in the dataset.
When a fragment does not overlap anything else it is dropped, so an article can
come out truncated. Pass `keep_unmerged=True` to `reconstruct()` to append those
leftover fragments at the end instead of discarding them; the default `False`
reproduces the original behaviour exactly.

## Docs

This package documentation is available [here](https://iandreafc.github.io/gdeltnews/), and a more detailed explanation of the functions’ logic is provided in the accompanying [paper](https://doi.org/10.3390/bdcc10020045).

## GUI Version
If you prefer to use a **software with a graphical user interface** that runs this code, you can find it [here](https://github.com/iandreafc/gdeltnews/tree/main/GUI) and read the [instructions here](https://iandreafc.github.io/gdeltnews/gui).

## Python Package Quickstart

### Install

```bash
pip install gdeltnews
```

Optionally, install the `fast` extra to decompress the GDELT files with
[isal](https://pypi.org/project/isal/) instead of the standard library:

```bash
pip install "gdeltnews[fast]"
```

This is purely a speed option (roughly 10-15% off the reading time of each
file). Everything works exactly the same without it.

### Step 1: Download Web NGrams files

```bash
from gdeltnews.download import download

download(
    "2025-11-25T10:00:00",
    "2025-11-25T13:59:00",
    outdir="gdeltdata",
    decompress=False,
    workers=8,   # concurrent downloads
)
```

Files are fetched concurrently over a shared connection pool, and each one is
retried a few times on network errors. `download()` returns a `DownloadStats`
telling you how many minute slots were downloaded, how many simply do not
exist on the GDELT server (`missing`, which is normal) and how many kept
failing (`failed`, which means a real gap in your data).

### Step 2: Reconstruct articles (run as a script, not in Jupyter)
Multiprocessing can be problematic inside notebooks. Run this from a `.py` script.
The compressed `.json.gz` files are read directly, so you do not need to
decompress them first.

```bash
from multiprocessing import freeze_support
from gdeltnews.reconstruct import reconstruct

def main():
    reconstruct(
        input_dir="gdeltdata",
        output_dir="gdeltpreprocessed",
        language="it",
        url_filters=["repubblica.it", "corriere.it"],
        processes=10,  # use None for all available cores
    )

if __name__ == "__main__":
    freeze_support()  # important on Windows
    main()
```

### Step 3: Filter, deduplicate, and merge CSVs

```bash
from gdeltnews.filtermerge import filtermerge

filtermerge(
    input_dir="gdeltpreprocessed",
    output_file="final_filtered_dedup.csv",
    query='((elezioni OR voto) AND (regionali OR campania)) OR ((fico OR cirielli) AND NOT veneto)'
)
```

Advanced users can pre-filter and download GDELT data via Google BigQuery, then process it directly with `wordmatch.py`.

## Citation and Credits

If you use this package for research, please cite:

Fronzetti Colladon, A., & Vestrelli, R. (2026). Free Access to World News: Reconstructing Full-Text Articles from GDELT. Big Data and Cognitive Computing, 10(2), 45. [https://doi.org/10.3390/bdcc10020045](https://doi.org/10.3390/bdcc10020045)

Code co-developed with [robves99](https://github.com/robves99).
