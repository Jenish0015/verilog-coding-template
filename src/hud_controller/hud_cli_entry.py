"""CLI entry that applies HUD eval patches then runs the stock `hud` CLI."""

from __future__ import annotations

import os


def main() -> None:
    # Avoid HUD OpenTelemetry export spam / DNS failures when telemetry host is unreachable.
    # Override by setting OTEL_SDK_DISABLED=false (or unset after export) before running.
    if os.environ.get("OTEL_SDK_DISABLED") is None:
        os.environ["OTEL_SDK_DISABLED"] = "true"

    from hud_controller.hud_eval_patch import apply_hud_eval_pass_rate_metrics

    apply_hud_eval_pass_rate_metrics()

    from hud.cli import main as hud_main

    hud_main()
