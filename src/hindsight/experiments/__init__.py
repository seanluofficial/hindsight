"""Experiment-platform signal code (experiments/PROTOCOL.md).

Each module here is a *signal* plugged into the existing evaluation harness
(`hindsight.evaluate`), not a new pipeline. Results are written to
`data/results/` as JSON bundles the Streamlit dashboard reads.
"""
