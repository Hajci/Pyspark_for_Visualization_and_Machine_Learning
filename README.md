# 🚕🗳️ Big Data Analytics in Spark – Italian Elections & NYC Yellow Taxi

**Group 29 · NOVA IMS · Big Data Analytics in Spark**
Libero Biagi · Jenny Kerr Cubelo · Emily Garrone · Marcell Hajdú

---

## 📌 Overview

The project applies the Spark ecosystem to two datasets with very different characteristics:

| | Italian elections | NYC Yellow Taxi |
|---|---|---|
| **Data** | Official results of Chamber of Deputies and municipal elections, 1948–2022 (Ministry of the Interior) | Yellow taxi trips, January and March 2016 ([Kaggle](https://www.kaggle.com/datasets/elemento/nyc-yellow-taxi-trip-data)) |
| **Challenge** | 239 files with 57 different schemas, legacy encodings, inconsistent naming | Dirty values, outliers, skewed distributions |
| **Spark tools** | PySpark DataFrames, Spark SQL, RDDs, Parquet lakehouse (Bronze/Silver/Gold) | MLlib pipelines, Random Forest, distributed PyTorch (`TorchDistributor`), GraphFrames, Structured Streaming |
| **Deliverable** | Interactive Streamlit dashboard | Fare and duration prediction, zone network analysis, streaming scoring |

The presentation is in [`docs/Group29_Presentation.pdf`](docs/Group29_Presentation.pdf).

## 📁 Repository structure

```
.
├── README.md
├── requirements.txt
├── .gitignore
├── elections/
│   ├── download_elections.py       # Step 0 – scrapes and downloads raw zip files
│   ├── convert_to_csv-2.ipynb      # Step 1 – raw .txt/.xlsx → clean UTF-8 CSV
│   ├── electoral_pipeline.ipynb    # Step 2 – PySpark pipeline Bronze → Silver → Gold
│   ├── dashboard.py                # Step 3 – Streamlit dashboard
│   └── italy_regions.geojson       # region boundaries for the choropleth map
├── taxi/
│   ├── ML.ipynb                    # cleaning, models for time and fare, streaming
│   ├── taxi_graph.ipynb            # GraphFrames network analysis
│   ├── taxi_data_visualization.ipynb  # Plotly visualizations
│   ├── train.csv                   # 50,000 trips (January 2016)
│   ├── validation.csv              # 10,000 trips (January 2016)
│   ├── test.csv                    # 20,000 trips (March 2016)
│   └── streaming.csv               # 500 trips used to simulate the stream
└── docs/
    └── Group29_Presentation.pdf
```

Generated folders (`data/`, `data_csv/`, `data_parquet/`, `taxi_stream/`) are produced by the scripts and are not committed.

## ⚙️ Environment setup

Requirements: Python 3.10+, **Java 17** (needed by Spark and GraphFrames), Chrome (only for the download script).

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
jupyter lab
```

---

# 🗳️ Part 1 – Italian Electoral Data

Run everything from the `elections/` folder:

```bash
cd elections
```

### Step 0 – Download raw data
`download_elections.py` uses Selenium to scrape the Ministry of the Interior open-data page and downloads all election zip files into `data/Camera/` (Chamber of Deputies) and `data/Comunali/` (municipal), one folder per election date (`yyyymmdd`). Links are cached, and already extracted folders are skipped. Set `TEST_MODE = True` in the script to try a few files first.

```bash
python download_elections.py
```

### Step 1 – Convert to CSV
`convert_to_csv-2.ipynb` converts every `.txt` and `.xlsx` file in `data/` into a clean UTF-8 CSV in `data_csv/`, mirroring the folder structure. It auto-detects encoding (Italian legacy encodings) and delimiter (`;` or `|` depending on the era). Run all cells; converted files are skipped.

### Step 2 – Spark pipeline
`electoral_pipeline.ipynb` processes all **239 CSV files (1948–2022, 57 different source schemas)** through three layers:

- **Bronze** – reads every CSV as strings and applies a 105-entry rename map that normalises the different Italian column names into consistent English ones (e.g. `ELETTORITOTALI`, `NUMELETTORITOTALI`, `ElettoriTotali` → `registered_voters`). Output: `data_parquet/bronze/`.
- **Silver** – cleans and types the data: converts the Italian decimal format (`"5181,00"` → `5181`), parses election and birth dates from several formats, unifies the two historical conventions for elected status, and builds MD5 surrogate keys for elections, geographies, parties and candidates. Output: `data_parquet/silver/`.
- **Gold** – star schema of 7 tables, with fact tables partitioned by `(election_type, year)`. Output: `data_parquet/gold/`.

| Table | Contents |
|---|---|
| `dim_election` | One row per election (date, type, year) |
| `dim_geography` | All geographic levels: municipality, district, constituency, abroad |
| `dim_list` | Party / list names, scoped per election |
| `dim_candidate` | Candidate identity (name, birth date, sex) |
| `fact_turnout` | Registered voters, turnout, blank ballots per geography |
| `fact_list_votes` | Party votes and seats won per geography |
| `fact_candidate_votes` | Individual candidate votes and elected status |

The notebook then runs 6 analytical SQL queries (turnout trends, top parties, seat efficiency, abroad participation, gender representation, closest races) and re-implements two of them with the **RDD API**, comparing execution times with the DataFrame versions. DataFrames and Spark SQL turned out faster and more efficient on this structured data.

Run with **Kernel → Restart & Run All**. The first run takes several minutes; later runs can reload from Parquet.

### Step 3 – Dashboard

```bash
streamlit run dashboard.py
```

Opens at `http://localhost:8501`. It reads `data_parquet/gold/`, so Step 2 must be completed first.

- **Sidebar** – election type (Chamber / Municipal), date and metric
- **Choropleth map** – Italy by region, coloured by turnout % or by the winning party's vote share
- **Summary panel** – registered voters, turnout % and blank ballots for the selected election
- **Top parties** – the 15 parties with the most votes
- **Region breakdown** – turnout and winning party per region
- **Gender** – male/female split among elected candidates

---

# 🚕 Part 2 – NYC Yellow Taxi

The goal is to predict **trip duration** (seconds) and **fare amount** from information available at pickup. Run the notebooks from the `taxi/` folder, next to the CSV files.

### Data

| File | Rows | Source |
|---|---|---|
| `train.csv` | 50,000 | random sample, January 2016 |
| `validation.csv` | 10,000 | random sample, January 2016 (no overlap with train) |
| `test.csv` | 20,000 | March 2016 (different month, to test generalisation) |
| `streaming.csv` | 500 | trips used to simulate a live stream |

The samples come from the full monthly files (hundreds of millions of trips across the whole dataset). Cleaning rules are learned on the training set and applied unchanged to validation and test.

### `ML.ipynb` – cleaning and models

**Cleaning and feature engineering**
- Duration computed from pickup and dropoff timestamps; trips below 0 s or above 4 h removed
- Invalid `trip_distance` (zero/null) replaced with the **Haversine distance** from coordinates
- Coordinates encoded as the nearest of **12 NYC hotspots** (JFK, LaGuardia, Times Square, Empire State, Central Park, Wall Street, Brooklyn Bridge, Williamsburg, Astoria, Long Island City, Yankee Stadium, Harlem)
- Negative values fixed, unrealistic distances/tolls and zero targets removed, IQR-based outlier replacement on non-airport trips
- Columns with no predictive value or data leakage (e.g. `total_amount`, `tip_amount`, `payment_type`) dropped

**Feature selection (filter methods):** variance threshold (0.01), univariate F-test (p < 0.05) and Spearman correlation (|ρ| ≥ 0.05). Selected features:
- numeric: `trip_distance`, `tolls_amount`, `extra`
- categorical: `RatecodeID`, `area_pickup`, `area_dropoff`, `pickup_hour`

**Models** (all built as Spark `Pipeline`s: `StringIndexer` → `OneHotEncoder` → `VectorAssembler` → `StandardScaler`): Linear Regression baseline, Random Forest baseline, MLP in PyTorch trained with `TorchDistributor`, and Random Forest tuned with a random search over `numTrees`, `maxDepth`, `featureSubsetStrategy`, `subsamplingRate`, `minInstancesPerNode` and `maxBins`.

**Results** (validation RMSE; the best model is retrained on train + validation and evaluated on the March test set):

| Target | Linear Regression | Random Forest | MLP | Tuned RF (validation) | **Tuned RF (test)** |
|---|---|---|---|---|---|
| Duration (s) | 604.08 (R² 0.069) | 435.88 (R² 0.515) | 526.71 | 388.26 | **RMSE 318.48 · R² 0.665** |
| Fare ($) | 6.25 (R² 0.309) | 4.34 (R² 0.666) | 5.25 | 2.91 | **RMSE 2.56 · R² 0.890** |

Best parameters — duration: 200 trees, depth 12, `onethird`, subsampling 0.6, min 5 instances, 64 bins. Fare: 50 trees, depth 12, `onethird`, subsampling 0.7, min 10 instances, 128 bins.

**Streaming simulation** (end of `ML.ipynb`), in two versions:
- **Manual** – trips are fed one by one and scored with the same preprocessing as in training
- **Automatic** – Spark **Structured Streaming** watches a landing directory (`taxi_stream/`) where each trip is written as a CSV; one file per micro-batch (`maxFilesPerTrigger=1`, 10 s trigger) with an explicit schema, and each batch is scored with `foreachBatch`. It mimics a booking app that shows duration and fare estimates as soon as a trip is requested.

### `taxi_graph.ipynb` – network analysis with GraphFrames

Taxi trips are modelled as a directed weighted graph: **vertices** are the 12 hotspot areas, **edges** are pickup → dropoff routes weighted by `trip_count`, `avg_fare`, `avg_duration_min` and `avg_distance` (12 vertices, 141 edges, including self-loops).

Analyses: degree / in-degree / out-degree, density, **PageRank**, **BFS** (shortest path from the least to the most active area), **label propagation** (a single community: the network is fully interconnected), **motif finding** (distributor and convergence zones), weighted flow analysis (most frequent and most expensive routes, flow matrix) and an interactive **NYC flow map** (routes with at least 200 trips).

Requires Java 17, `pyspark==3.5.3` and the GraphFrames package (`graphframes:graphframes:0.8.2-spark3.2-s_2.12`), as set up in the notebook's first cells.

### `taxi_data_visualization.ipynb` – visualizations

Plotly charts on the cleaned data: descriptive statistics, distributions (fare, tip, distance, duration), most popular pickup/dropoff areas, fare and duration by pickup zone, origin–destination heatmap, correlation matrix, fare vs distance (5% random sample) and hourly patterns of fare, tip, duration and distance.

---

## ⚠️ Limitations

- The taxi models are trained on small samples (50k trips) in local mode, so the notebooks show the Spark workflow but do not measure real cluster scalability.
- Duration is much harder to predict than fare (R² 0.66 vs 0.89): traffic and weather are not in the data.
- With only 12 hotspot areas the taxi graph is almost fully connected, which limits what PageRank and community detection can reveal.
- Election files have changed format over seven decades, so the rename map and cleaning rules may need extending if new elections are added.

## 🛠️ Tech stack

Python · Apache Spark / PySpark (DataFrames, Spark SQL, RDD, MLlib, Structured Streaming) · GraphFrames · PyTorch · Streamlit · Plotly · Selenium · Parquet

## 📚 Data sources

- NYC Yellow Taxi Trip Data – NYC Taxi & Limousine Commission, via [Kaggle](https://www.kaggle.com/datasets/elemento/nyc-yellow-taxi-trip-data)
- Italian electoral data – Ministero dell'Interno, [elezionistorico.interno.gov.it](https://elezionistorico.interno.gov.it/eligendo/opendata.php)
- [Apache Spark / PySpark documentation](https://spark.apache.org/docs/latest/api/python)
