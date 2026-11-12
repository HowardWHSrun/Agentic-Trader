# ML research (yearly refit of the v2.6 sizing model)

Needs scikit-learn, pandas, numpy and a folder of daily bars (`hist/<SYM>.json`) plus `dyn_sig.json`, the layout `harness.py` expects (set `SP` in each script).

1. `build_dip_signals.py`: rebuilds the dip signals from 2005, computes features and labels (estimated option P&L).
2. `train_sizing_model.py`: runs the walk-forward check, then writes `docs/data/options/ml_model.json`.

Live inference is in `scripts/options_ml.py`.
