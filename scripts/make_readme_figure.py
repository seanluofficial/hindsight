"""Render the README's summary figure.

Deliberately conservative about what it claims. Every experiment reported a different
pre-registered primary metric -- bps of abnormal return, long/short Sharpe, hit rate --
so plotting them on one axis would invent a comparability that does not exist. The figure
therefore shows only what is unambiguous: which hypotheses were tested, that none
survived, and the one clean explore/holdout pair (005) where both partitions used the
same book and the same metric.

A development-time script only. matplotlib is deliberately not a project dependency --
nothing at runtime plots -- so run it with a throwaway environment:

    uv run --with matplotlib python scripts/make_readme_figure.py
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "docs" / "media"

INK = "#1A1D23"
MUTED = "#6B7280"
FAIL = "#C0392F"
RULE = "#D9DDE3"

# Titles are the experiment directory names; verdicts are the repository's own stated
# result -- no signal survived out-of-sample after costs.
EXPERIMENTS = [
    ("001", "LLM reads anonymised 8-Ks"),
    ("002", "Event-type conditional returns"),
    ("003", "Filing novelty"),
    ("004", "Information staleness"),
    ("005", "Post-earnings drift"),
    ("006", "Insider cluster buying"),
    ("007", "Burying bad news"),
    ("008", "Peer lead-lag diffusion"),
    ("009", "Small-cap insider buying"),
    ("010", "Small-cap momentum"),
]

# The three experiments that each identified a distinct real-world cost, per the README.
COST_NOTES = {"007": "spread", "009": "survivorship", "010": "short-borrow"}


def build() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(11, 4.2))
    fig.patch.set_facecolor("white")
    ax.set_xlim(0, 2)
    ax.set_ylim(0, 6)
    ax.axis("off")

    ax.text(0.02, 5.62, "Ten pre-registered experiments", fontsize=17, color=INK,
            fontweight="semibold", va="center")
    ax.text(0.02, 5.16, "None produced a signal that survives out-of-sample after costs.",
            fontsize=11.5, color=MUTED, va="center")
    ax.plot([0.02, 1.98], [4.86, 4.86], color=RULE, lw=1)

    for i, (eid, title) in enumerate(EXPERIMENTS):
        col, row = divmod(i, 5)
        x = 0.02 + col * 1.0
        y = 4.34 - row * 0.72

        ax.text(x, y, eid, fontsize=10.5, color=MUTED, family="monospace", va="center")
        ax.text(x + 0.115, y, title, fontsize=11.5, color=INK, va="center")
        ax.text(x + 0.86, y, "✕", fontsize=12, color=FAIL, va="center", ha="right")

        note = COST_NOTES.get(eid)
        if note:
            ax.text(x + 0.115, y - 0.235, f"cost identified: {note}", fontsize=9,
                    color=MUTED, va="center", style="italic")

    ax.plot([0.02, 1.98], [0.52, 0.52], color=RULE, lw=1)
    ax.text(0.02, 0.24,
            "005 post-earnings drift, the closest call: 0.53 Sharpe on development "
            "→ −0.38 on the reserved holdout.",
            fontsize=10, color=MUTED, va="center")

    fig.tight_layout()
    path = OUT / "experiments.png"
    fig.savefig(path, dpi=150, facecolor="white")
    plt.close(fig)
    print(f"wrote {path}  ({path.stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    build()
