"""Shared generator context: one seeded RNG, Faker, counterparty registry, transaction builder."""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from faker import Faker

CONFIG_PATH = Path(__file__).with_name("config.yaml")
OUT_DIR = Path(__file__).resolve().parents[1] / "out"

Txn = dict[str, Any]

# Transliterated name pools by region, so names match nationality.
ARAB_FIRST = ["Ahmed", "Mohammed", "Omar", "Khalid", "Yousef", "Hassan", "Ali", "Saeed", "Rashid",
              "Fatima", "Mariam", "Aisha", "Noura", "Layla", "Huda", "Reem", "Salma", "Hind"]
ARAB_LAST = ["Al Mansoori", "Al Hashimi", "Al Suwaidi", "Haddad", "Khoury", "Nasser", "Saleh",
             "Abdullah", "Al Falasi", "Mahmoud", "Ibrahim", "Darwish", "Al Nuaimi", "Farouk"]
SOUTH_ASIAN_FIRST = ["Rahul", "Arjun", "Priya", "Anjali", "Imran", "Ayesha", "Faisal", "Sanjay",
                     "Deepa", "Kiran", "Nadia", "Usman", "Rohan", "Sana", "Tariq", "Meera"]
SOUTH_ASIAN_LAST = ["Sharma", "Patel", "Nair", "Khan", "Iqbal", "Menon", "Reddy", "Chowdhury",
                    "Perera", "Siddiqui", "Hussain", "Fernando", "Rao", "Qureshi", "Das"]
FILIPINO_FIRST = ["Maria", "Jose", "Angelica", "Mark", "Kristine", "Paolo", "Jasmine", "Ramon"]
FILIPINO_LAST = ["Santos", "Reyes", "Cruz", "Bautista", "Garcia", "Mendoza", "Villanueva"]
CHINESE_FIRST = ["Wei", "Li", "Jun", "Mei", "Hao", "Xin"]
CHINESE_LAST = ["Wang", "Chen", "Zhang", "Liu", "Huang"]
WEST_AFRICAN_FIRST = ["Chinedu", "Ngozi", "Emeka", "Funmi", "Tunde", "Ada"]
WEST_AFRICAN_LAST = ["Okafor", "Adeyemi", "Eze", "Balogun", "Nwosu"]

NAME_POOLS = {
    **{c: (ARAB_FIRST, ARAB_LAST) for c in ["AE", "EG", "JO", "LB", "SA", "XA", "XB", "XC"]},
    **{c: (SOUTH_ASIAN_FIRST, SOUTH_ASIAN_LAST) for c in ["IN", "PK", "BD", "LK"]},
    "PH": (FILIPINO_FIRST, FILIPINO_LAST),
    "CN": (CHINESE_FIRST, CHINESE_LAST),
    "NG": (WEST_AFRICAN_FIRST, WEST_AFRICAN_LAST),
}

COUNTRY_NAMES = {"AE": "the UAE", "IN": "India", "PK": "Pakistan", "EG": "Egypt",
                 "PH": "the Philippines", "GB": "the UK", "JO": "Jordan", "LB": "Lebanon",
                 "BD": "Bangladesh", "LK": "Sri Lanka", "NG": "Nigeria", "US": "the US",
                 "SA": "Saudi Arabia", "FR": "France", "CN": "China", "CA": "Canada",
                 "AU": "Australia", "TR": "Turkey"}


def country_name(code: str) -> str:
    """Readable name for KYC text; synthetic high-risk codes stay as 'country XA'."""
    return COUNTRY_NAMES.get(code, f"country {code}")


MERCHANTS = ["Carrefour", "Lulu Hypermarket", "Spinneys", "Waitrose", "Talabat", "Careem",
             "Noon.com", "Amazon.ae", "ENOC", "ADNOC Distribution", "Starbucks", "Deliveroo",
             "IKEA Dubai", "Ace Hardware", "Boots Pharmacy", "Aster Pharmacy", "VOX Cinemas",
             "Emirates Airline", "flydubai", "Union Coop", "Al Maya Supermarket", "Nandos",
             "Salik", "RTA Nol Top-up", "DEWA", "du", "e& (Etisalat)", "Zara", "H&M",
             "Sharaf DG", "Virgin Megastore", "Fitness First", "Apple Store Dubai Mall"]

ADDRESS_AREAS = ["JVC", "Al Barsha", "Deira", "Bur Dubai", "Karama", "JLT", "Dubai Marina",
                 "International City", "Al Nahda", "Mirdif", "Silicon Oasis", "Al Qusais",
                 "Sharjah Al Majaz", "Ajman Al Nuaimiya", "Abu Dhabi Khalifa City"]


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


@dataclass
class Ctx:
    """Everything random flows through `rng`; Faker is seeded from the same seed."""

    cfg: dict[str, Any]
    rng: np.random.Generator
    fake: Faker
    start: date
    end: date
    _cp_ids: dict[tuple[str, str], str] = field(default_factory=dict)
    _cp_seq: itertools.count = field(default_factory=lambda: itertools.count(1))
    _txn_seq: itertools.count = field(default_factory=lambda: itertools.count(1))

    @classmethod
    def create(cls, cfg: dict[str, Any]) -> Ctx:
        seed = cfg["seed"]
        Faker.seed(seed)
        fake = Faker(["en_US"])
        return cls(cfg=cfg, rng=np.random.default_rng(seed), fake=fake,
                   start=_as_date(cfg["start_date"]), end=_as_date(cfg["end_date"]))

    # ---- random helpers -------------------------------------------------
    def choice(self, items, p=None):
        return items[int(self.rng.choice(len(items), p=p))]

    def uniform(self, lo: float, hi: float) -> float:
        return float(self.rng.uniform(lo, hi))

    def randint(self, lo: int, hi: int) -> int:
        """Inclusive on both ends."""
        return int(self.rng.integers(lo, hi + 1))

    def chance(self, p: float) -> bool:
        return bool(self.rng.random() < p)

    def lognormal_around(self, median: float, sigma: float) -> float:
        return float(median * np.exp(self.rng.normal(0.0, sigma)))

    def person_name(self, nationality: str) -> str:
        pool = NAME_POOLS.get(nationality)
        if pool is None:
            return self.fake.name()
        first, last = pool
        return f"{self.choice(first)} {self.choice(last)}"

    def company_name(self, suffix: str | None = None) -> str:
        base = self.fake.company().replace(",", "")
        return f"{base} {suffix or self.choice(['LLC', 'FZE', 'FZCO', 'Trading LLC', 'DMCC'])}"

    def ts_on(self, day: date, hour_lo: int = 7, hour_hi: int = 22) -> datetime:
        seconds = self.randint(hour_lo * 3600, hour_hi * 3600 - 1)
        return datetime(day.year, day.month, day.day, tzinfo=UTC) + timedelta(seconds=seconds)

    def day_between(self, lo: date, hi: date) -> date:
        return lo + timedelta(days=self.randint(0, (hi - lo).days))

    # ---- ids and transactions -----------------------------------------
    def counterparty_id(self, name: str, country: str | None) -> str:
        key = (name, country or "")
        if key not in self._cp_ids:
            self._cp_ids[key] = f"CP-{next(self._cp_seq):05d}"
        return self._cp_ids[key]

    def txn(self, customer_id: str, ts: datetime, amount: float, direction: str, channel: str,
            cp_name: str | None = None, cp_country: str | None = "AE",
            reference: str | None = None) -> Txn:
        """Build one transaction. `_k` is an internal key; TXN ids are assigned after sorting."""
        if channel == "cash":
            cp_name, cp_country = None, None
        return {
            "_k": next(self._txn_seq),
            "customer_id": customer_id,
            "ts": ts,
            "amount_aed": round(max(float(amount), 1.0), 2),
            "direction": direction,
            "channel": channel,
            "counterparty_id": self.counterparty_id(cp_name, cp_country) if cp_name else None,
            "counterparty_name": cp_name,
            "counterparty_country": cp_country if cp_name else None,
            "reference": reference,
        }


def _as_date(v: Any) -> date:
    return v if isinstance(v, date) else date.fromisoformat(str(v))


def month_starts(start: date, end: date) -> list[date]:
    out, d = [], date(start.year, start.month, 1)
    while d <= end:
        out.append(d)
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return out


def clamp_day(month_start: date, day: int) -> date:
    """The given day-of-month, clamped to the month's length."""
    nxt = date(month_start.year + (month_start.month == 12), month_start.month % 12 + 1, 1)
    last = (nxt - timedelta(days=1)).day
    return month_start.replace(day=min(day, last))
