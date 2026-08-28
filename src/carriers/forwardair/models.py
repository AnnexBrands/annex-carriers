"""Data models for Forward Air invoice parsing."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RateItem:
    description: str
    amount: float


@dataclass
class Airbill:
    number: str = ""
    org_dst: str = ""
    ship_date: str = ""
    weight: float = 0.0
    reweigh: float = 0.0
    original: float = 0.0
    amount_due: float = 0.0
    rates: list[RateItem] = field(default_factory=list)

    @property
    def rate_total(self) -> float:
        return sum(r.amount for r in self.rates)


@dataclass
class Invoice:
    number: str
    bill_date: str = ""
    total_due: float = 0.0
    airbills: dict[str, Airbill] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def airbill_total(self) -> float:
        return sum(ab.amount_due for ab in self.airbills.values())
