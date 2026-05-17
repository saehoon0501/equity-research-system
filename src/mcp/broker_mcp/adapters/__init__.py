"""Broker adapter implementations.

v0.1 ships only Schwab. The `BrokerAdapter` ABC in `base.py` defines the
contract so v0.5+ can add IBKR / Fidelity without changing the MCP server
interface in `../server.py`.
"""
