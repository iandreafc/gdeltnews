# Reconstructing News Text from GDELT

This repository contains code for reconstructing the text of news articles using data from the GDELT Web News NGrams 3.0 dataset.

## Code and Example Usage

The full multi-process pipeline lives in the [pipeline/](pipeline/) directory, and a walk-through demo is available in [pipeline/GDELT_Reconstructor.ipynb](pipeline/GDELT_Reconstructor.ipynb).
Alternatively, GDELT data can be pre-filtered and downloaded via Google BigQuery, then processed directly with [gdelt_wordmatch_multiprocess.py](pipeline/gdelt_wordmatch_multiprocess.py) without running the full download pipeline.

An example input file can be downloaded from the following URL:
[http://data.gdeltproject.org/gdeltv3/webngrams/20250316000100.webngrams.json.gz](http://data.gdeltproject.org/gdeltv3/webngrams/20250316000100.webngrams.json.gz)

To learn more about the dataset, please visit the official announcement:
[https://blog.gdeltproject.org/announcing-the-new-web-news-ngrams-3-0-dataset/](https://blog.gdeltproject.org/announcing-the-new-web-news-ngrams-3-0-dataset/)

## Reference and Credits

For a complete description and citable reference, please refer to this paper: [https://arxiv.org/abs/2504.16063](https://arxiv.org/abs/2504.16063)

Code co-developed with [robves99](https://github.com/robves99).