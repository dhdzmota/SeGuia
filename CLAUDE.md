# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**SeGuía** is an AI-based drought prediction system that uses supervised learning (XGBoost) to identify droughts in Mexico 6 months in advance. It covers all ~2,457 Mexican municipalities using data from CONAGUA (drought index), NASA (meteorology), and CONABIO (geospatial boundaries).

## Setup

```bash
cd seguia/
pip install -r requirements.txt   # also installs local src/ package in editable mode via setup.py
```

The package root is `seguia/`. All pipeline scripts must be run from that directory. Data is excluded from git (see `.gitignore`); the `data/`, trained model pickle, and parquet files must be generated locally.

## Running the Pipeline

The full pipeline is documented in `seguia/general_pipeline.py`. Each stage is independently runnable:

```bash
# 0. Download raw data (CONAGUA drought index, CONABIO shapefile, NASA POWER meteorology)
python src/data/downloader.py

# 1. Process raw data (clean drought index, join NASA data, build neighbour graph)
python src/features/process_data.py

# 2. Engineer all features and targets
python src/features/create_target_and_features.py

# 3. Split data and train XGBoost model
python src/models/create_model.py

# 4a. Launch the legacy Dash dashboard (original)
python src/demo/app.py

# 4b. Launch the FastAPI dashboard (current, preferred) — http://localhost:8000
python src/demo/api.py
# or: uvicorn src.demo.api:app --host 0.0.0.0 --port 8000
```

Every download step is idempotent (skips files that already exist), so `downloader.py` can be re-run to resume interrupted NASA fetches. It disables SSL verification for the CONAGUA/CONABIO hosts.

## Linting

```bash
flake8 src/
```

## Architecture

```
seguia/
├── config/config.conf          # YAML — URLs for CONAGUA drought data and CONABIO geo data
├── src/
│   ├── data/
│   │   ├── downloader.py       # Stage 0: fetch CONAGUA, CONABIO and NASA POWER raw data
│   │   └── utils.py            # Path resolution, serialization helpers, config loader
│   ├── features/
│   │   ├── process_data.py     # Stage 1: clean drought data, join NASA, build neighbour graph
│   │   ├── process_utils.py    # Helpers: NASA join, neighbour graph, drought cleaning
│   │   ├── drought_utils.py    # CONAGUA drought index mapping (NaN, D0–D4)
│   │   ├── meteorological_utils.py  # NASA data processing
│   │   ├── neighbour_utils.py  # NetworkX municipal adjacency graph
│   │   ├── build_features.py   # Core feature engineering (target, rolling windows, neighbours)
│   │   └── create_target_and_features.py  # Stage 2 orchestrator
│   ├── models/
│   │   ├── split_data.py       # Temporal + stratified splits (train/dev/test/OOT)
│   │   ├── train_model.py      # XGBoost training (10K estimators, depth 6, LR 0.001)
│   │   ├── model_utils.py      # Load splits, load model, generate predictions
│   │   ├── evaluate_model.py   # Placeholder — not yet implemented
│   │   └── create_model.py     # Stage 3 orchestrator
│   └── demo/app.py             # Dash web app — interactive choropleth map, date slider
├── notebooks/                  # 12 numbered development notebooks (exploration → src/)
├── models/SeGuia.pkl           # Serialized trained model (generated, not in git)
└── data/
    ├── raw/                    # Original downloads
    ├── interim/                # Intermediate processed files
    └── processed/              # ML-ready parquet files
```

### Key Design Patterns

- **Composite index**: `mun_id__date` is the primary join key across all feature DataFrames.
- **Serialization**: Pickle for complex objects (geo DataFrames, NetworkX graphs, the trained model); Parquet for tabular DataFrames.
- **Partitioned meteorological processing**: NASA data is split into 4 state-group partitions to manage memory during the municipality-level join loop.
- **Neighbour features**: Grade-1 and grade-2 spatial neighbours are aggregated via the NetworkX adjacency graph, then merged as additional features.
- **Path portability**: All file paths are resolved through `src.data.utils.get_general_path()` — do not hard-code absolute paths.

### Data & Model Configuration

| Item | Location | Value |
|---|---|---|
| Training period | `src/models/model_utils.py` | From 2017-01-01 up to `last_labelled_date − OOT_MONTHS` — derived from data at split time, not hard-coded |
| OOT (out-of-time) test | `src/models/model_utils.py` | Last `OOT_MONTHS` (6) months of rows whose 6-month target is already known |
| Train/Dev/Test split | `src/models/split_data.py` | 60/20/20 (random seed 69); rows with <50% non-null features (no NASA data yet) are excluded; summary written to `data/processed/split_info.json` |
| Prediction horizon | Default target | 6 months (`target_6m`) |
| Data start threshold | Multiple modules | 2016-01-01 (CONAGUA index change) |
| XGBoost config | `src/models/train_model.py` | 10K estimators, max\_depth=6, LR=0.001, early stopping |

### Known TODOs (from code comments)

- `general_pipeline.py`: Automate periodic data updates (currently manual).
- `src/demo/app.py`: Add threshold visualization to the prediction map.
- `src/models/evaluate_model.py`: Evaluation logic not yet implemented.
- `src/data/downloader.py`: downloads skip existing files, so a monthly rerun does not refresh CONAGUA/NASA data yet (needs a refresh mode + incremental NASA fetch).

## Language Note

All README files, in-code comments, UI text, and documentation are in Spanish — this is intentional for the target audience (Mexican government/agricultural institutions).
