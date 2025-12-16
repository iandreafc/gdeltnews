---
layout: default
title: Quickstart guide
nav_order: 2
---

# Quickstart guide - gdeltnews

This package helps you:
- download GDELT Web NGrams files for a time range,
- reconstruct article text from overlapping n-gram fragments,
- filter and merge reconstructed CSVs using Boolean queries.

To learn more about the dataset, please visit the official announcement:
[https://blog.gdeltproject.org/announcing-the-new-web-news-ngrams-3-0-dataset/](https://blog.gdeltproject.org/announcing-the-new-web-news-ngrams-3-0-dataset/)

Input files look like:
[http://data.gdeltproject.org/gdeltv3/webngrams/20250316000100.webngrams.json.gz](http://data.gdeltproject.org/gdeltv3/webngrams/20250316000100.webngrams.json.gz)

Reconstruction quality depends on the n-gram fragments available in the dataset.

## Step 1: Download Web NGrams files

```bash
from gdeltnews.download import download

download(
    "2025-11-25T10:00:00",
    "2025-11-25T13:59:00",
    outdir="gdeltdata",
    decompress=False,
)
```

## Step 2: Reconstruct articles (run as a script, not in Jupyter)
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

## Step 3: Filter, deduplicate, and merge CSVs

```bash
from gdeltnews.filtermerge import filtermerge

filtermerge(
    input_dir="gdeltpreprocessed",
    output_file="final_filtered_dedup.csv",
    query='((elezioni OR voto) AND (regionali OR campania)) OR ((fico OR cirielli) AND NOT veneto)'
)
```

Advanced users can pre-filter and download GDELT data via Google BigQuery, then process it directly with `wordmatch.py`.
