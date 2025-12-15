#STEP 1 Download GDELT data in a specific time range
from gdeltnews.download import download

download(
    "2025-11-25T10:00:00",
    "2025-11-25T13:59:00",
    outdir="gdeltdata",
    decompress=False,
)

#STEP 2
#Decompress files
#Filter by URL and Language
#Reconstruct articles and produce CSVs
#Delete decompressed files
#Do not run inside Jupyter, due to multiprocessing issues
from gdeltnews.reconstruct import reconstruct

def main():
    reconstruct(
        input_dir="gdeltdata",
        output_dir="gdeltpreprocessed",
        language="it",
        url_filters=["repubblica.it", "corriere.it"],
        processes=10, #Use None for all available CPU cores
    )

if __name__ == "__main__":
    main()


#STEP3
#Filter CSV files based on search query
#Remove duplicates
#Merge all relevant data into a single CSV file
from gdeltnews.filtermerge import filtermerge

filtermerge(
    input_dir="gdeltpreprocessed",
    output_file="final_filtered_dedup.csv",
    query='((elezioni OR voto) AND (regionali OR campania)) OR ((fico OR cirielli) AND NOT veneto)'
)

