"""Broker MCP server package.

Read-only broker integration for the equity research system. Exposes positions
+ account-summary + fill-detection tools to Claude Code per Section 4.6 (L5/L6
execution output) and Section 7 Q5 (broker MCP as position state source).

Per Section 7 Q5 lock: READ-ONLY scope; the system does NOT execute trades.
HMAC anchor-drift signing happens at the application layer over the positions
table; this MCP only returns broker data.

v0.1 ships Schwab as the default first broker. IBKR / Fidelity adapters are
v0.5+ pluggable additions via `adapters/base.py` BrokerAdapter ABC.
"""
