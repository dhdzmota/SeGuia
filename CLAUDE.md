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
python src/data/downloader.py            # resume: skips files that already exist
python src/data/downloader.py --refresh  # monthly run: re-download CONAGUA, fetch NASA incrementally

# 1. Process raw data (clean drought index, join NASA data, build neighbour graph)
python src/features/process_data.py                 # add --force to rebuild every partition

# 2. Engineer all features and targets
python src/features/create_target_and_features.py   # add --force to recompute all meteorological features

# 3. Split, train, evaluate and (conditionally) promote the model
python src/models/create_model.py                   # --promote auto|never|force
python src/models/evaluate_model.py 20260914        # re-evaluate an existing candidate

# 4a. Launch the legacy Dash dashboard (original)
python src/demo/app.py

# 4b. Launch the FastAPI dashboard (current, preferred) — http://localhost:8000
python src/demo/api.py
# or: uvicorn src.demo.api:app --host 0.0.0.0 --port 8000
```

`downloader.py` has two modes. Without flags it resumes (skips anything already on disk). With `--refresh` it re-downloads the CONAGUA Excel (validated: required columns present, no fewer dates than the current file, written atomically) and asks NASA POWER only for days after each municipality's last stored date, merging them into the existing pickle. Trailing days NASA has not processed yet come back as `-999` and are trimmed so the next run re-requests them; interior `-999` values become NaN. Each run writes `data/raw/download_manifest.json` (what was updated, last dates, errors). It disables SSL verification for the CONAGUA/CONABIO hosts.

Stages 1 and 2 keep per-municipality parquet partitions (`data/interim/meteorological_information/mun_id=*/`, `data/interim/meteorological_features/mun_id=*/`). A partition is recomputed only when its source is newer than it (`src.data.utils.is_stale`, mtime-based like `make`), so an interrupted run resumes and a `--refresh` propagates; partitions are written with `existing_data_behavior='delete_matching'` so reruns replace rather than append rows. The neighbour graph is reused while `municipal_data.pkl` is unchanged. `--force` bypasses the staleness check.

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
│   │   ├── train_model.py      # XGBoost training → versioned candidate models/SeGuia_<run_id>.pkl
│   │   ├── model_utils.py      # Load splits, load model, generate predictions
│   │   ├── evaluate_model.py   # Metrics on train/dev/test/oot, metrics report, promotion rule
│   │   └── create_model.py     # Stage 3 orchestrator
│   └── demo/app.py             # Dash web app — interactive choropleth map, date slider
├── notebooks/                  # 12 numbered development notebooks (exploration → src/)
├── models/                     # SeGuia.pkl = promoted model; SeGuia.json = which run is promoted;
│                               # SeGuia_<YYYYMMDD>.pkl = every trained candidate (generated, not in git)
├── reports/metrics/            # metrics_<run_id>.json per training run (generated, not in git)
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
| Feature loading | `src/models/model_utils.py` | `read_features()` reads parquet in 64-column blocks and casts to float32 (`all_features.parquet` is 630K × 770; plain `pd.read_parquet` peaks at ~10 GB, this at ~4 GB). Used by `split_data`, `read_xy_set` and the API |
| Prediction horizon | Default target | 6 months (`target_6m`) |
| Data start threshold | Multiple modules | 2016-01-01 (CONAGUA index change) |
| XGBoost config | `src/models/train_model.py` | 10K estimators, max\_depth=6, LR=0.001, early stopping (never triggered on the 2026-09 run: best_iteration 9999) |
| Model promotion | `src/models/evaluate_model.py` | Candidate replaces `models/SeGuia.pkl` only if its OOT AUC ≥ the current model's AUC on the same OOT set (`--promote never|force` to override). Every run writes `reports/metrics/metrics_<run_id>.json` |

### Pipeline timings (full rebuild, 2026-09-13, WSL 15 GB RAM)

Download (first `--refresh`, all NASA data) ~21 min; stage 1 ~17 min; stage 2 ~81 min (meteorological features ~54 min, neighbour features ~8 min, peaks ~6 GB RAM); stage 3 ~2 h 50 min (split 3 min, training ~2 h 40 min for 10K trees on 20 cores, evaluation ~5 min). Total ≈ 5 h. A monthly incremental run re-downloads only new days but still recomputes every meteorological partition (all raw pickles change).

### Model performance (run 20260914, first with 2026 data)

Train/dev/test AUC ≈ 0.95/0.95/0.94 but **OOT AUC 0.634** (AUC-PR 0.21, 4 % positives). Per feature date, OOT AUC is 0.91–0.97 for Sep–Dec 2025 (targets Mar–Jun 2026, drought persisting/receding) and ~0.45 for Jan–Feb 2026 (targets Jul–Aug 2026, *new* drought onset after a historic minimum). The model behaves largely as a persistence model; the random train/test split leaks neighbouring fortnights of the same municipality, so test AUC overstates forward-looking skill. Treat OOT (ideally per-date) as the real metric.

### Known TODOs (from code comments)

- `general_pipeline.py`: Automate periodic data updates (currently manual).
- `src/demo/app.py`: Add threshold visualization to the prediction map.
- Modelling: temporal (not random) dev/test split; per-date OOT AUC as promotion metric; features for drought *onset* (precipitation anomalies vs climatology, ENSO); early stopping never triggers with LR 0.001 — consider a higher LR.

## Language Note

All README files, in-code comments, UI text, and documentation are in Spanish — this is intentional for the target audience (Mexican government/agricultural institutions).
