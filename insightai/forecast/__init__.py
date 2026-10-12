"""Demand forecasting and stockout risk.

series.py     daily demand rows -> weekly series, outlier flags
baselines.py  naive / moving-average / seasonal-naive forecasts, MAE and MASE
model.py      Chronos wrapper (optional: falls back to the baseline if it cannot load)
synthetic.py  clearly-labelled synthetic demand for development
risk.py       forecast vs available stock and incoming purchase quantities
job.py        runs the whole thing and writes the result file the API serves
"""
