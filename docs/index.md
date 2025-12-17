---
layout: default
title: Home
nav_order: 1
---

## Reconstructing Full-Text News Articles from GDELT - gdeltnews

Reconstruct full news article text from the GDELT Web News NGrams 3.0 dataset.

This package helps you:
- download GDELT Web NGrams files for a time range,
- reconstruct article text from overlapping n-gram fragments,
- filter and merge reconstructed CSVs using Boolean queries.

## Install

```bash
pip install gdeltnews
```

## Quickstart and Docs

If you prefer to use a **software with a graphical user interface** that runs this code, you can find it [here](https://github.com/iandreafc/gdeltnews/tree/main/GUI) and read the [instructions here](https://iandreafc.github.io/gdeltnews/gui).

See the quickstart guide [here](https://iandreafc.github.io/gdeltnews/quickstart/).

The package functions are documented [here](https://iandreafc.github.io/gdeltnews/functions/), and their underlying logic is explained in more detail in the accompanying [paper](https://arxiv.org/abs/2504.16063).

## Citation

If you use this package for research, please cite:

A. Fronzetti Colladon, R. Vestrelli (2025). “A Python Tool for Reconstructing Full News Text from GDELT.” [https://arxiv.org/abs/2504.16063](https://arxiv.org/abs/2504.16063)
