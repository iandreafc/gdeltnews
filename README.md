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

## Docs

This package documentation is available [here](https://iandreafc.github.io/gdeltnews/), and a more detailed explanation of the functions’ logic is provided in the accompanying [paper](https://arxiv.org/abs/2504.16063).

## GUI Version
If you prefer to use a **software with a graphical user interface** that runs this code, you can find it [here](https://github.com/iandreafc/gdeltnews/tree/main/GUI) and read the [instructions here](https://iandreafc.github.io/gdeltnews/gui).

## Python Package Quickstart

### Install

```bash
pip install gdeltnews
```

### Step 1: Download Web NGrams files

```bash
from gdeltnews.download import download

download(
    "2025-11-25T10:00:00",
    "2025-11-25T13:59:00",
    outdir="gdeltdata",
    decompress=False,
)
```

### Step 2: Reconstruct articles (run as a script, not in Jupyter)
Multiprocessing can be problematic inside notebooks. Run this from a `.py` script.

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
A. Fronzetti Colladon, R. Vestrelli (2025). “A Python Tool for Reconstructing Full News Text from GDELT.” [https://arxiv.org/abs/2504.16063](https://arxiv.org/abs/2504.16063)

Code co-developed with [robves99](https://github.com/robves99).