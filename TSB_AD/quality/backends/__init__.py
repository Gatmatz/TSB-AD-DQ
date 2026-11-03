"""Pollution backends: `pollute(df, kind, params, seed) -> (DataFrame, report)` on a TSB-AD frame (`Data`, `Label`);
labels are never modified."""

from . import icewafl, jenga

BACKENDS = {"jenga": jenga, "icewafl": icewafl}
