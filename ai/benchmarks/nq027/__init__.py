"""NQ-027 - local model benchmark and selection evidence.

Measures. Does not choose. The choice is ADR-012, written by a human after
reading what this produced.

The one rule that shapes every module here: a generation that was cut off at
the token cap, came back empty, failed to parse, or failed schema validation
is NOT a successful run and must never contribute to a latency or throughput
number. See validity.py - that ladder is the point of this package.
"""

__all__ = ["__version__"]

__version__ = "2.0.0"
