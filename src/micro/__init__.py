"""Intraday (≤1-day) day-trading signal helper backing the /micro command.

Deterministic technical-indicator math + a probabilistic LONG/SHORT/HOLD model.
Per CLAUDE.md P1, signal logic is internal Python (a leaf tool), not an
external MCP capability and not LLM prose in the command markdown. The /micro
command pipes a {bars, live, prior} payload to ``src.micro.cli`` and renders
the JSON it prints.

Lane note (CLAUDE.md P9): this module's vocabulary is LONG/SHORT/HOLD — a
day-trading directional bias, NOT the slow layer's BUY/HOLD/TRIM/SELL portfolio
decision. The two never mix; /micro persists to its own ``micro_signal`` lane.
"""
