"""Befund einer Regel oder des Ladevorgangs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class Finding:
    rule: str
    severity: str
    node_id: str | None
    message: str
