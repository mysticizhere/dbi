"""Column generators for the playground dataset (spec section 6).

Three distributions matter here, and each one exists to break a specific planner
assumption:

* **uniform** -- ``score``. Honest selectivity, so the seq-scan crossover point
  in exercise 4 lands where the cost model says it should.
* **zipfian** -- ``user_id``. A few very heavy users, so per-user queries have
  wildly different real costs while the planner assumes one average.
* **correlated pairs** -- ``city`` / ``pincode``, where pincode is functionally
  determined by city. The planner multiplies the two selectivities as if they
  were independent, and is wrong by roughly the number of cities. That is the
  whole point of exercise 7 (``CREATE STATISTICS``).

Generation is vectorised through numpy: 10M rows built one Python object at a
time is minutes of pure interpreter overhead for no benefit.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# 200 city/pincode pairs, 1:1. The independence assumption therefore overestimates
# a two-column equality predicate by ~200x, which is comfortably visible.
_CITY_STEMS = [
    "Mumbai", "Delhi", "Bengaluru", "Hyderabad", "Ahmedabad", "Chennai", "Kolkata",
    "Surat", "Pune", "Jaipur", "Lucknow", "Kanpur", "Nagpur", "Indore", "Thane",
    "Bhopal", "Visakhapatnam", "Patna", "Vadodara", "Ghaziabad",
]
_CITY_SUFFIXES = ["", " North", " South", " East", " West", " Central", " Extension",
                  " New Town", " Old City", " Cantonment"]

_NAME_STEMS = [
    "aarav", "vivaan", "aditya", "vihaan", "arjun", "sai", "reyansh", "ayaan",
    "krishna", "ishaan", "rohan", "ananya", "diya", "saanvi", "aadhya", "kiara",
    "myra", "anika", "navya", "riya",
]

STATUS_DONE = "DONE"
STATUS_PENDING = "PENDING"

# Wide enough that a 10M-row table lands near 1.5GB, narrow enough to stay off TOAST.
_PAYLOAD_WIDTH = 32
_PAYLOAD_POOL_SIZE = 512


@dataclass(frozen=True)
class Vocabulary:
    """Precomputed string pools. Building these once and indexing into them is
    far cheaper than formatting a fresh string per row."""

    cities: list[str]
    pincodes: np.ndarray  # pincodes[i] is the pincode of cities[i] -- 1:1 by design
    names: list[str]
    payloads: list[str]

    @property
    def n_cities(self) -> int:
        return len(self.cities)


def build_vocabulary(rng: np.random.Generator) -> Vocabulary:
    cities = [f"{stem}{suffix}" for stem in _CITY_STEMS for suffix in _CITY_SUFFIXES]
    # Pincode is a pure function of the city index: the correlation is total.
    pincodes = np.array([400001 + i * 37 for i in range(len(cities))], dtype=np.int32)

    # Mixed casing, so a plain btree on email cannot serve lower(email) = ...
    # That is exercise 2.
    names: list[str] = []
    for stem in _NAME_STEMS:
        names.extend([stem, stem.capitalize(), stem.upper(), f"{stem.capitalize()}."])

    alphabet = np.array(list("abcdefghijklmnopqrstuvwxyz0123456789"))
    raw = rng.choice(alphabet, size=(_PAYLOAD_POOL_SIZE, _PAYLOAD_WIDTH))
    payloads = ["".join(row) for row in raw]

    return Vocabulary(cities=cities, pincodes=pincodes, names=names, payloads=payloads)


def zipf_cdf(n: int, exponent: float = 1.1) -> np.ndarray:
    """Cumulative distribution over ``n`` items with weight ~ 1/rank^exponent.

    Sampling is then a single ``searchsorted`` against uniform randoms, which is
    both exact and fast -- unlike ``np.random.zipf``, whose unbounded tail has to
    be clamped, and clamping distorts the shape.
    """
    weights = 1.0 / np.power(np.arange(1, n + 1, dtype=np.float64), exponent)
    cdf = np.cumsum(weights)
    normalised: np.ndarray = cdf / cdf[-1]
    return normalised


def sample_zipf(rng: np.random.Generator, cdf: np.ndarray, size: int) -> np.ndarray:
    """Draw ``size`` 1-based ranks from a precomputed zipf CDF."""
    ranks: np.ndarray = np.searchsorted(cdf, rng.random(size)).astype(np.int64)
    return ranks + 1
