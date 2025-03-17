import json
import csv
from collections import defaultdict
import re
from typing import List, Dict, Tuple
from tqdm import tqdm
import multiprocessing as mp
from functools import partial


#Get the input data from the following ULR, provided as an example: http://data.gdeltproject.org/gdeltv3/webngrams/20250316000100.webngrams.json.gz and extract the json.


#Functions for recosntructing the news articles
def transform_dict(original_dict: Dict) -> Dict:
    """
    Transforms a nested dictionary of article entries into a cleaned and simplified format.
    Each entry contains text fragments ('pre', 'ngram', 'post') that are concatenated into a single sentence.
    If an entry appears at the beginning of an article and contains " / ", it is assumed to include
    incorrectly appended content from the article's end, which is removed.
    Returns a dictionary where each key is a URL and the value is a list of cleaned entries,
    each containing a reconstructed sentence and associated metadata (date, language, type, and sentence position).
    """

    transformed_data = {}

    for url, entries in original_dict.items():
        transformed_entries = []
        for entry in entries:
            # Combine strings and clean in one pass
            sentence = ' '.join([entry['pre'], entry['ngram'], entry['post']])
            #Remove the part that has been added from the end of the article and concatenated to its beginning
            #Can lead to minor errors if an article has " / " at its beginning
            if int(entry['pos']) < 20 and " / " in sentence:
                parts = sentence.split(" / ")
                if len(parts) > 1:
                    sentence = " / ".join(parts[1:])

            transformed_entries.append({
                'date': entry['date'],
                'lang': entry['lang'],
                'type': entry['type'],
                'pos': entry['pos'],
                'sentence': sentence
            })
        transformed_data[url] = transformed_entries

    return transformed_data


def reconstruct_sentence(fragments: List[str], positions: List[int] = None) -> str:
    """
    Reconstructs text by merging a group of overlapping fragments.
    Begins with the first fragment and iteratively finds the best matching unused fragment
    based on word overlap, appending or prepending it as needed.
    If position data is provided, it uses that to prioritize fragments that are not overly distant
    in original text order to improve reconstruction accuracy.
    Returns a single string that represents the reconstructed text.
    """

    if not fragments:
        return ""
    if len(fragments) == 1:
        return fragments[0]

    # Create position mapping if provided
    pos_map = {}
    if positions:
        pos_map = {i: pos for i, pos in enumerate(positions)}

    # Split all fragments into words once
    words_list = [fragment.split() for fragment in fragments]
    result_words = words_list[0]
    used = {0}

    while len(used) < len(fragments):
        best_overlap = 0
        best_fragment = -1
        best_is_prefix = False

        for i in range(len(fragments)):
            if i in used:
                continue

            words = words_list[i]

            # Check suffix matching prefix (append operation)
            min_len = min(len(result_words), len(words))
            # Only if positions allow (current fragment position >= first fragment position)
            # Allowance for small position differences
            if positions is None or pos_map[i] + 10 >= pos_map[0]:
                for k in range(min_len, 0, -1):
                    if result_words[-k:] == words[:k] and k > best_overlap:
                        best_overlap = k
                        best_fragment = i
                        best_is_prefix = False
                        break

            # Check prefix matching suffix (prepend operation)
            # Only if positions allow (current fragment position <= first fragment position)
            # Allowance for small position differences
            if positions is None or pos_map[i] - 10 <= pos_map[0]:
                for k in range(min_len, 0, -1):
                    if result_words[:k] == words[-k:] and k > best_overlap:
                        best_overlap = k
                        best_fragment = i
                        best_is_prefix = True
                        break

        if best_fragment == -1:
            break

        if best_is_prefix:
            result_words = words_list[best_fragment][:-best_overlap] + result_words
        else:
            result_words = result_words + words_list[best_fragment][best_overlap:]

        used.add(best_fragment)

    return ' '.join(result_words)


def remove_overlap(text: str) -> str:
    """
    Removes duplicated content that appears at both the beginning and end of a reconstructed text,
    which can occur when overlapping fragments are merged improperly.
    Checks for the longest matching prefix and suffix in the text, and removes the repeated segment.
    Returns the cleaned version of the input text.
    """

    if len(text) < 2:
        return text

    # Maximum possible overlap length to check (half the text length)
    max_check_len = len(text) // 2
    max_overlap_len = 0

    # Find the longest string overlap from beginning and end
    for i in range(1, max_check_len + 1):
        if text[:i] == text[-i:]:
            max_overlap_len = i

    # Remove the overlap from the beginning if found
    if max_overlap_len > 0:
        return text[max_overlap_len:]

    return text


def process_article(url_entries_tuple, language_filter="en"):
    """Process a single article - designed to be run in parallel"""
    url, entries = url_entries_tuple

    # Sort entries by position
    entries.sort(key=lambda x: x['pos'])

    sentences = [entry['sentence'] for entry in entries]
    positions = [entry['pos'] for entry in entries]

    # Calculate group positions
    group_positions = []
    for fragment in sentences:
        idx = sentences.index(fragment)
        group_positions.append(positions[idx])

    # Simplified: treat all sentences as one group
    reconstructed_sentences = reconstruct_sentence(sentences, group_positions)
    text = remove_overlap(reconstructed_sentences)

    # Clean and format text
    textok = text.replace("|", " ").replace('"', " ").strip()
    textok = re.sub(r'\s+', ' ', textok)  # Remove extra spaces

    return {
        "url": url,
        "text": textok,
        "date": entries[0]['date'][:10]
    }

def load_and_filter_data(input_file, language_filter="en", url_filter=None):
    """Load data from file and filter by language and URL, preserving original URL order"""
    articles = defaultdict(list)
    # Track the order of URLs as they first appear in the file
    url_order = []

    with open(input_file, "r", encoding="utf-8") as file:
        for line in file:
            try:
                entry = json.loads(line)
                if entry.get("lang") == language_filter:
                    if url_filter is None or url_filter in entry.get("url", ""):
                        url = entry["url"]
                        if url not in articles:
                            url_order.append(url)
                        articles[url].append(entry)
            except json.JSONDecodeError as e:
                print(f"Skipping line due to JSON error: {e}")

    # Transform the data
    return transform_dict(articles), url_order

def process_file_multiprocessing(input_file: str, output_file: str, language_filter: str = "en",
                               url_filter: str = None, num_processes: int = None) -> None:
    """
    Reads a line-based JSON file and processes articles in parallel using multiprocessing.
    """
    # If num_processes is not specified, use CPU count
    if num_processes is None:
        num_processes = mp.cpu_count()

    print(f"Loading and filtering data using {num_processes} processes...")

    # Load and filter data, capturing original URL order
    articles, url_order = load_and_filter_data(input_file, language_filter, url_filter)

    # Create lookup by URL for later reordering
    url_index = {url: idx for idx, url in enumerate(url_order)}

    # Prepare list of work items
    work_items = list(articles.items())
    total_articles = len(work_items)
    print(f"Processing {total_articles} articles...")

    # Create a pool of worker processes
    with mp.Pool(processes=num_processes) as pool:
        # Process articles in parallel with progress tracking
        process_func = partial(process_article, language_filter=language_filter)
        results = []

        # Use imap to process chunks and track progress
        with tqdm(total=total_articles, desc="Processing articles") as pbar:
            for result in pool.imap_unordered(process_func, work_items, chunksize=10):
                results.append(result)
                pbar.update(1)

    # Sort results based on the original URL order
    sorted_results = sorted(results, key=lambda x: url_index.get(x['url'], float('inf')))

    # Write results to file
    with open(output_file, mode='w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file, delimiter="|", quoting=csv.QUOTE_NONE)
        writer.writerow(["Text", "Date", "URL"])
        for article in sorted_results:
            writer.writerow([article['text'], article['date'], article['url']])

    print(f"Successfully processed {len(results)} articles and saved to {output_file}")


if __name__ == "__main__":
    input_file = "20250316000100.webngrams.json"
    output_file = "articles_wordmatch4_multiprocess.csv"

    # You can specify the number of processes or let it use all available cores
    process_file_multiprocessing(
        input_file=input_file,
        output_file=output_file,
        language_filter="en",
        url_filter=None,
        num_processes=None  # Uses all available cores
    )