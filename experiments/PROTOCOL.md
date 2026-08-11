# Research protocol

The rules every experiment in this platform obeys. They exist for one reason: **to make it
hard to fool ourselves.** A backtest that finds an edge is cheap; a backtest whose edge
survives a genuine attempt to kill it is rare, and only the second kind is worth anything.

Where this file and an individual `HYPOTHESIS.md` disagree, this file wins. Where this file
and `PREREGISTRATION.md` (the original Experiment 001 spec) disagree, the pre-registration
wins for 001 and this file governs 002+.

---

## 1. The progression, and the gates between stages

Every experiment moves through these stages **in order**. A stage may not begin until the
previous one is written down and committed. You cannot skip forward, and you cannot walk
backward across a gate without recording it as a deviation.

```
  hypothesis ─▶ historical experiment ─▶ untouched holdout ─▶ robustness ─▶ forward
   (locked)       (EXPLORE years)         (HOLDOUT years,       (kill it)    (live,
                                            touched once)                     uncontaminable)
```

1. **Hypothesis (locked).** `HYPOTHESIS.md` is written and committed *before any outcome is
   looked at*. It names one primary endpoint, the direction predicted, the baseline it must
   beat, the kill criteria, and the robustness battery. The git commit is the timestamp.
2. **Historical experiment (EXPLORE).** Build the signal and estimate the effect on the
   EXPLORE partition only. Iterate here as much as you like — this is where you are *allowed*
   to be human and try things.
3. **Untouched holdout (HOLDOUT).** Run the *frozen* procedure once on the HOLDOUT partition.
   One shot. If you tune anything after seeing a holdout number, the holdout is burned and
   the experiment is downgraded to exploratory — say so.
4. **Robustness.** Run the pre-specified battery (§4). The point is to *break* the effect.
5. **Forward.** Register live, out-of-sample predictions before the outcome window closes.
   This is the only evidence that cannot be contaminated by hindsight, and it is the only
   thing that should ever move someone toward real capital.

An effect is called **"survived"** only if it clears its kill criteria on the HOLDOUT *and*
does not collapse under robustness. Surviving EXPLORE alone means nothing.

---

## 2. Data partitions — the holdout architecture

The corpus is 2010-2024. Because the EXPLORE years have already been examined during
Experiment 001 and ongoing development, they are permanently "seen." The partitions:

| Partition | Span | Rule |
|---|---|---|
| **EXPLORE** | 2010-01-01 → 2019-12-31 | Seen. Develop, tune, and estimate here freely. |
| **HOLDOUT** | 2020-01-01 → 2024-12-31 | Quarantined. Each experiment touches it **once**, at stage 3, with a frozen procedure. |
| **FORWARD** | filings after the study freeze | Uncontaminable. Scored live, before outcomes exist. |

Honesty notes that a reviewer will check:

- **A partition is per-signal, not per-row.** The raw filings and prices in the HOLDOUT
  years exist and some were seen incidentally. What must stay unseen is *the relationship
  between a new signal and holdout outcomes*. A signal you have never computed on 2020-2024
  has a clean holdout even though the underlying filings are old.
- **Experiment 001's holdout is already spent.** Its pre-registered test was run on the full
  sample. 001 is therefore reported honestly as an in-sample / single-shot study; the
  EXPLORE⁄HOLDOUT discipline binds 002 onward, where the signals are genuinely new.
- **The shared holdout erodes, and we do not pretend otherwise.** Every experiment queries the
  *same* 2020-2024 window. Each individual signal's relationship to holdout outcomes is fresh,
  but collectively we learn what this period rewards — by the fifth experiment the holdout is
  no longer naive about the 2020-2024 *regime*. The FDR correction (§3) controls the inference,
  not this erosion. Three consequences we accept and state: (a) the time-based HOLDOUT is a
  strong filter but **not** an independent confirmation across experiments; (b) **FORWARD is the
  only truly clean confirmatory gate**, and no effect should move toward real capital on the
  strength of the shared holdout alone; (c) 2020-2024 is a single, unusual regime (COVID crash,
  meme episode, ZIRP→hiking) — a signal that dies there may have met a regime change, not a
  refutation, and one that survives may have fit the regime. Where an experiment can afford it,
  prefer a **company-hash holdout** (quarantine a fixed random subset of *issuers* across all
  years) over, or alongside, the time split, so different experiments do not all lean on the
  same five years.

Every experiment states, in its `HYPOTHESIS.md`, exactly which partition each reported
number comes from, and labels anything from EXPLORE as **not confirmatory**.

---

## 3. Multiple testing — the alpha budget

This is the trap the whole platform is designed around, and it is the one most "I ran a
bunch of strategies" projects fall into. **Running eight experiments and reporting the one
that looked significant is not a discovery — it is the expected output of chance.** At α=0.05,
eight independent tests produce a false positive about a third of the time.

Rules:

1. **One primary endpoint per experiment.** Each `HYPOTHESIS.md` declares a *single* primary
   test: one metric, one horizon, one cost level, one partition (the HOLDOUT). Everything
   else — other horizons, other costs, subgroups — is **secondary/exploratory**, reported in
   full but never counted as a discovery.
2. **The family is the set of primary endpoints**, tracked in `README.md`'s registry.
3. **The family size is declared up front, not discovered.** BH-FDR assumes all p-values are
   in hand at once; deciding to "stop when one works" and calling that "the end" is
   optional-stopping bias wearing a correction's clothes. So the registry names the *planned*
   experiments now (drafted or not) and they count against the budget. Adding an experiment
   never contemplated at lock time is a `DEVIATIONS.md` entry, and the correction is recomputed
   over the enlarged family — you cannot shrink the denominator by forgetting a planned test.
4. **Correction is applied across the family, once, at the end.** We use Benjamini-Hochberg
   FDR at **q = 0.10** over all pre-registered primary p-values. An experiment is a
   "discovery" only if it passes BH *and* its holdout kill criteria. Caveat a reviewer will
   raise: BH controls FDR under independence or positive dependence (PRDS); our primaries share
   filings, windows, and universe and may violate that. Where dependence is a concern we report
   the **Benjamini-Yekutieli** value (valid under arbitrary dependence) alongside BH, and let
   the more conservative one govern the "discovery" call.
5. **Every test counts, including abandoned ones.** An experiment started and dropped is
   still logged in the registry with status `abandoned` and the reason. You do not get to
   forget the tests that didn't work.
6. **Secondary findings are hypothesis-generating, not confirmatory.** A promising subgroup
   becomes a *new pre-registered experiment* with its own fresh holdout — never a result
   claimed from the run that discovered it.

If nothing survives BH-FDR, that is the finding, reported as such. "We ran seven
pre-registered experiments and, after correcting for multiple comparisons, none produced a
holdout effect distinguishable from noise" is a stronger, more honest sentence than any
single uncorrected p-value.

---

## 4. Robustness battery — try to kill it

Any effect that clears the holdout must then be *attacked*. These are pre-specified so the
attack cannot be quietly softened once it starts to bite. Each experiment lists which apply.

- **Time stability.** Split the effect by year and by regime (e.g. pre/post-2020, high/low
  VIX). A real effect is not one or two lucky years.
- **Subgroup stability.** Size, sector, and volatility buckets. Report *all* buckets; a
  finding that lives in a single sector is a lead, not a result.
- **Cost sensitivity.** Reported at 0 / 10 / 25 bps always. An effect that only works at zero
  cost does not work. **Short-side reality is part of cost, not a footnote:** the flat bps
  model omits short-borrow fees, and the names our long/short signals want to short (restatement
  filers, disclosure-rewriters) are exactly the hard-to-borrow, sometimes un-borrowable ones.
  Any experiment with a short leg reports a borrow-cost sensitivity and, separately, a
  **long-only** version — if the effect lives entirely in an untradeable short, say so.
- **Specification sensitivity.** Perturb the arbitrary knobs (text cap, quintile count,
  rebalance frequency). A finding that hinges on one parameter value is fragile.
- **Baseline dominance.** The signal must beat the pre-registered baseline (§5) on the same
  text. Beating "no signal" is not enough; it must beat the cheap, comprehension-free method.
- **Placebo / negative control.** Where feasible, run the same pipeline on shuffled labels or
  a signal that should carry no information. It must find nothing.

---

## 5. Baselines and kill criteria

- **Baseline.** Every experiment names the naive method its signal must outperform on
  identical inputs — usually the Loughran-McDonald lexicon (comprehension-free word counting)
  already in the codebase, or a "predict the base rate" constant.
- **Kill criteria (pre-registered).** Each `HYPOTHESIS.md` states, in advance, the numbers at
  which the hypothesis is declared **not supported**. The threshold is fixed before the data is
  seen so it cannot be moved when it becomes inconvenient.
- **Two gates, not one — do not conflate them.** A ~5-year holdout rebalanced monthly is only
  ~60 observations, where a Sharpe of 0.30 carries t ≈ 0.3·√5 ≈ 0.67 — economically marginal
  and nowhere near significant. So "clears 0.30" is **not** the same claim as "is statistically
  real," and we require both, kept distinct: (1) the **statistical gate** — the primary
  p-value passes BH-FDR (and BY where dependence bites) across the family; (2) the
  **economic-materiality floor** — a 5-day/10bps quintile L/S Sharpe of **0.30**, reused as the
  study default, that a survivor must also clear so we do not chase significant-but-trivial
  effects. Add an effect-size and a calibration floor as appropriate.

---

## 6. Reuse, reproducibility, and deviations

- **Reuse the existing harness.** Ingest, point-in-time universe, entry timing, market-excess
  returns, portfolio construction, calibration, and manifests already exist in
  `src/hindsight/`. A new experiment is a new *signal* plugged into the same evaluation, not a
  new pipeline. Resist building a generic framework before three experiments exist — the
  infrastructure you have is the platform.
- **Determinism.** Temperature 0, pinned model IDs, fixed seeds, versioned prompts. A rerun on
  the same database reproduces the same numbers.
- **Manifests.** Every run writes its git SHA, parameters, and row counts in/out.
- **Deviations are logged.** Any departure from a locked `HYPOTHESIS.md` or from this protocol
  goes in `DEVIATIONS.md` with the date and reason, append-only. Rewriting a hypothesis after
  seeing results is the cardinal sin; recording the deviation is the absolution.
