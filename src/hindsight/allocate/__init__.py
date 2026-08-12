"""Systematic asset-allocation (the 'allocate' sibling to the signal experiments).

Not an attempt to find alpha in filings — that is what the experiments showed does not survive.
This module harvests a documented, capacity-friendly *risk premium* (trend / absolute momentum)
on a basket of liquid ETFs, with the same rigor: point-in-time, mandatory costs, no lookahead,
and an out-of-sample forward window. The honest deliverable is a risk-managed allocation, not a
money machine — over 2010-2024 it is expected to reduce drawdowns more than it boosts return.
"""
