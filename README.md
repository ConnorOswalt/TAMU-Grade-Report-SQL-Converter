# TAMU Grade Consolidator v2.2

**A robust Python ETL + analytics pipeline for downloading, parsing, cleaning, storing, analyzing, and visualizing university transcript and grade data.**

![Association Heatmap](associations_heatmap.png)

## Overview

The **TAMU Grade Consolidator** is an end-to-end data pipeline that automates the extraction, transformation, and loading (ETL) of academic grade/transcript data from Texas A&M University (and similar institutions). 

It pulls raw data files, intelligently extracts metadata from filenames, standardizes and cleans the data, stores everything in a SQL database, runs correlation analysis, and generates professional visualizations (such as the association heatmap shown above).

This project showcases real-world **data engineering** and **exploratory data analysis (EDA)** skills — exactly the kind of work done daily in data science & analytics roles.

## Why This Project Matters
- Handles real student transcript data at scale
- Demonstrates a complete production-style analytics workflow
- Uses modular, maintainable code that is easy to extend
- Perfect example of **cleaning/preprocessing data**, **SQL integration**, **statistical analysis**, and **complex data visualization**

## Features

- Automated file downloading from URLs or local sources
- Smart filename parsing (extracts student IDs, terms, etc.)
- Data cleaning and standardization with pandas
- Persistent storage in a relational SQL database
- Statistical correlation analysis between academic variables
- Generation of insightful visualizations (correlation heatmaps)
- Fully configurable via `config.py`
- Command-line interface with argparse

## Tech Stack

- **Python** (100%)
- **pandas** – Data manipulation & analysis
- **SQL / sqlite3** – Database storage & querying
- **matplotlib / seaborn** – Professional data visualization
- **requests** – File downloading
- **pathlib & re** – File handling & regex parsing

## Project Structure
TAMU-Grade-Consolidator-2.2/
├── main.py                 # Main entry point – runs the full pipeline
├── config.py               # All configuration settings
├── download.py             # Downloads raw grade files
├── data_from_filename.py   # Extracts metadata from filenames
├── converter.py            # Cleans and converts data to standard format
├── sql_handler.py          # SQL database operations (init, insert, query)
├── correlation_finder.py   # Performs correlation analysis
├── associations_heatmap.png # Example output visualization
├── .gitignore
└── README.md
text## How It Works (Step-by-Step)

1. **Download** – Fetches raw transcript/grade files
2. **Parse** – Extracts student IDs and metadata from filenames
3. **Convert & Clean** – Standardizes data into a clean pandas DataFrame
4. **Store** – Loads cleaned data into an SQLite database
5. **Analyze** – Finds statistically significant correlations
6. **Visualize** – Generates and saves a correlation heatmap

## Installation & Usage

### 1. Clone the repo
```bash
git clone https://github.com/ConnorOswalt/TAMU-Grade-Consolidator-2.2.git
cd TAMU-Grade-Consolidator-2.2
2. Install dependencies
Bashpip install pandas matplotlib seaborn requests
3. (Optional) Update config.py
Edit database path, download directory, etc.
4. Run the full pipeline
Bashpython main.py
Optional flags (extendable):
Bashpython main.py --download   # Only run the download step
The script will automatically:

Download and process new data
Update the database
Generate a fresh associations_heatmap.png

Example Output
The pipeline produces a correlation heatmap that highlights relationships between different academic performance indicators (GPA, credit hours, course difficulty, etc.). This kind of insight is directly transferable to analyzing sensor data, yield predictions, or equipment performance in precision agriculture.
Skills Demonstrated

End-to-end data pipelines (ETL)
Data cleaning & preprocessing
Relational database design & management (SQL)
Statistical analysis & insight extraction
Complex data visualization
Clean, modular, and well-documented Python code
Real-world application of pandas, SQL, and visualization libraries


Built by Connor Oswalt
Perfect for demonstrating Python + SQL + analytics skills in data science, analytics, or intelligent systems roles (especially those involving IoT/sensor data or agricultural machinery).