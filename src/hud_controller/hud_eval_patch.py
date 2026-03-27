"""
HUD eval: make grouped-table Success% show mean cocotb pass rate (reward = test fraction).

Upstream HUD defines success_rate as fraction of episodes with reward > 0, which is misleading
when reward is already a partial pass score. We patch stats + table header for verilog evals.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)
_PATCHED = False


def apply_hud_eval_pass_rate_metrics() -> None:
    """Idempotent: patch hud.datasets.utils for mean pass rate as success_rate + column label."""
    global _PATCHED
    if _PATCHED:
        return

    import rich.table as rich_table
    import hud.datasets.utils as u

    _orig_stats = u.calculate_group_stats
    _orig_display = u.display_results

    def calculate_group_stats(
        tasks: list[Any],
        traces: list[Any],
        group_size: int,
        group_ids: dict[int, str],
    ) -> list[dict[str, Any]]:
        stats = _orig_stats(tasks, traces, group_size, group_ids)
        for s in stats:
            rewards = s.get("rewards") or []
            if rewards:
                arr = np.asarray(rewards, dtype=float)
                # Mean cocotb pass fraction across episodes (same units as reward)
                s["success_rate"] = float(np.mean(arr))
        return stats

    _orig_add_column = rich_table.Table.add_column

    def _add_column_patched(self: Any, *args: Any, **kwargs: Any) -> Any:
        if args and args[0] == "Success%":
            args = ("Mean pass%",) + tuple(args[1:])
        elif kwargs.get("header") == "Success%":
            kwargs = {**kwargs, "header": "Mean pass%"}
        return _orig_add_column(self, *args, **kwargs)

    def display_results(
        results: list[Any],
        *,
        tasks: list[Any],
        elapsed: float | None = None,
        show_details: bool = True,
    ) -> None:
        rich_table.Table.add_column = _add_column_patched  # type: ignore[method-assign]
        try:
            _orig_display(results, tasks=tasks, elapsed=elapsed, show_details=show_details)
        finally:
            rich_table.Table.add_column = _orig_add_column  # type: ignore[method-assign]

    u.calculate_group_stats = calculate_group_stats
    u.display_results = display_results
    _PATCHED = True
    logger.debug("hud.datasets.utils: success_rate = mean(reward); table column Mean pass%%")
