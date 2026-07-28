Pre-Registration — hindsight

Committed: 07/27/2026 Status: LOCKED. Do not edit after the first evaluation run. Deviations go in DEVIATIONS.md with dates and reasons.

1. Research question

Can a large language model extract predictive signal from corporate disclosures (SEC 8-K filings), when it is prevented from identifying the company or the date?

Secondary: is it calibrated — when it states 70% confidence, is it right ~70% of the time?

Tertiary: does it beat a deterministic dictionary baseline that does no reading comprehension at all?

2. Hypotheses
H1 (edge). A long/short portfolio formed on LLM-predicted direction produces positive risk-adjusted returns before transaction costs at the 5-day horizon.
H2 (calibration). The LLM is overconfident: realized hit rates are below stated confidence, with the gap widening at higher confidence levels.
H3 (baseline). The LLM does not meaningfully outperform a Loughran-McDonald lexicon score on the same text.

Stating expected direction in advance is deliberate. H2 and H3 predict unflattering outcomes; confirming them is a valid result.

3. Universe and sample
Securities: US common equities that were members of the S&P 500 as of each filing date (point-in-time membership; no current-constituent lists).
Period: 2010-01-01 through 2024-12-31 for the historical study. Filings from the live phase are recorded separately and never merged into historical results.
Events: All 8-K filings by in-universe companies, including EX-99 press release exhibits.
Exclusions (fixed in advance):
Filings with acceptance timestamps outside 04:00–20:00 ET (data quality).
Companies with a price below $5 on the trading day prior.
Filings where the post-anonymization text is under 200 characters.
Days where the security did not trade.
4. Timing convention

The single most important rule in this document.

The event timestamp is the EDGAR acceptance datetime, not the period-of-report date and not the scrape date.
If acceptance is before 16:00 ET on a trading day, the position is entered at the next day's open.
If acceptance is at or after 16:00 ET, or on a non-trading day, the position is entered at the open of the next trading day following.
Same-day returns are never used, at any horizon.
5. Horizons

Returns measured from entry open to close at 1, 5, and 20 trading days. All three are reported. There is no primary horizon; reporting only the best one is prohibited.

Returns are market-excess: raw return minus SPY return over the identical window.

6. Anonymization protocol

Before any text reaches the model, remove or replace:

Company names, former names, and ticker symbols
Executive and director names
Addresses, phone numbers, state of incorporation, CIK, file numbers
All explicit dates → replaced with relative language ("the prior fiscal quarter")
Auditor, exchange, and transfer agent names

Contamination audit. On a random sample of 500 anonymized filings, the model is separately asked to name the issuer. The identification rate is reported as a headline limitation. If identification exceeds 20%, the primary analysis is restricted to filings the model failed to identify, and both versions are reported.

7. Prediction format

For each filing, the model returns strict JSON:

json
{"direction": "up" | "down", "probability": 0.50-1.00, "rationale": "one sentence"}
Temperature 0.
Prompt text is versioned; every stored prediction records its prompt_version and model_id.
Raw model responses are stored verbatim alongside parsed fields.
A filing that fails to parse after two retries is recorded as null and counted in a reported failure rate. It is not silently dropped.
8. Baseline

Loughran-McDonald financial sentiment dictionary. Score = (positive count − negative count) / total words. Applied to identical anonymized text. No tuning, no threshold optimization.

9. Portfolio construction
Sort filings by predicted probability, signed by direction, within each calendar month.
Long the top quintile, short the bottom quintile.
Equal weight. No leverage. No optimization of weights.
Hold for the full horizon; overlapping positions permitted and accounted for.
10. Transaction costs

Reported at three levels: 0, 10, and 25 bps round trip. The 10 bps figure is treated as the base case. Results are never presented cost-free alone.

11. Metrics
Mean market-excess return per horizon, with t-statistic
Sharpe ratio (annualized), at each cost level
Maximum drawdown
Hit rate
Brier score
Reliability diagram — predicted confidence bucketed in 10 bins vs. realized frequency
12. Robustness splits (specified in advance)

Every one of these is reported regardless of outcome:

Market cap terciles
Time period: 2010–2014, 2015–2019, 2020–2024
8-K item type (earnings, management change, material agreement, other)
Excluding filings the model could identify in the contamination audit
13. Multiple testing

The specifications listed in this document are the complete set of planned tests. Any additional specification run after seeing results is labeled exploratory in the writeup and reported separately. The count of all specifications run is disclosed.

14. What counts as a null result

If the 5-day long/short Sharpe is below 0.3 after 10 bps costs, H1 is not supported. This is reported as the finding. No search for a surviving subgroup is conducted after the fact except as labeled exploratory analysis.

15. Live phase (secondary, out-of-sample)

Beginning after the historical study is complete, new filings are scored in real time using the identical code path. Each prediction is written to storage with a timestamp before the outcome window closes. This record is never used to tune anything. Its purpose is to measure the gap between backtest and out-of-sample performance.