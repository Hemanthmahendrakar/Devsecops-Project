"""
stats_engine.py

Stat engine rewritten to match this app's actual category list:

    ALLOWED_CATEGORIES = [
        "Food", "Transport", "Housing", "Utilities", "Entertainment",
        "Health", "Shopping", "Education", "Travel", "Other",
    ]

  HEALTH    — 50/30/20 rule deviation (needs/wants/savings split)
  ENERGY    — Z-score anomaly detection on historical monthly spend
  HAPPINESS — spending consistency: frequency of fun-category transactions
              (proxied via fun-spend ratio + days-since-fun)
  WEALTH    — Exponential Moving Average (EMA) trend instead of flat threshold

Each stat is 0-100.  compute_all_stats() also returns an `insights` dict:
plain-English sentences explaining *why* each stat is what it is.

Kept dependency-free (no numpy) so it runs in the existing environment.
"""

from __future__ import annotations
import math

# ---------------------------------------------------------------------------
# Category classification for the 50/30/20 rule
# Mapped 1:1 onto ALLOWED_CATEGORIES — no category outside that list is
# assumed to exist, and every category in that list is classified below.
# ---------------------------------------------------------------------------

ALLOWED_CATEGORIES = [
    "Food", "Transport", "Housing", "Utilities", "Entertainment",
    "Health", "Shopping", "Education", "Travel", "Other",
]

# "Needs" — essentials you can't easily skip month to month
NEEDS_CATEGORIES = {"Food", "Transport", "Housing", "Utilities", "Health", "Education"}

# "Wants" — discretionary / lifestyle spend
WANTS_CATEGORIES = {"Entertainment", "Shopping", "Travel"}

# "Other" is intentionally left unclassified — it's treated the same way
# leftover budget is in the 50/30/20 rule: it falls into the implicit
# savings/buffer bucket alongside whatever isn't spent on needs or wants.

# Categories that drive the "fun spend" / happiness signal
FUN_CATEGORIES = ("Entertainment", "Travel")

# ---------------------------------------------------------------------------
# Tunable constants
# ---------------------------------------------------------------------------

# 50/30/20 targets
NEEDS_TARGET = 0.50
WANTS_TARGET = 0.30
SAVINGS_TARGET = 0.20

# Z-score thresholds for energy
Z_HIGH_THRESHOLD = 1.5   # > 1.5 std devs above mean → drain energy
Z_LOW_THRESHOLD = -1.0   # < -1 std devs below mean  → boost energy
ENERGY_Z_HIGH_PENALTY = 25
ENERGY_Z_LOW_BONUS = 15
ENERGY_MIN_HISTORY = 2   # need at least 2 months for std dev

# EMA for wealth (alpha closer to 1 = reacts faster to recent data)
EMA_ALPHA = 0.3
WEALTH_EMA_SCALE = 8.0   # how aggressively EMA delta moves wealth score

# Fun-spend happiness
NO_FUN_DAYS_THRESHOLD = 30
NO_FUN_PENALTY = 8
FUN_MIN_RATIO = 0.02
FUN_MAX_RATIO = 0.30
FUN_HEALTHY_BONUS = 12
FUN_EXCESS_PENALTY = 15

DEFAULT_STAT = 50


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clamp(value: float) -> float:
    return max(0.0, min(100.0, value))


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _std(values: list[float], mean: float) -> float:
    if len(values) < 2:
        return 0.0
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(variance)


def _category_total(by_category: list[dict], categories) -> float:
    return sum(
        c.get("total", 0) or 0
        for c in by_category
        if c.get("category") in categories
    )


# ---------------------------------------------------------------------------
# HEALTH — 50/30/20 rule
# ---------------------------------------------------------------------------

def compute_health(summary: dict, by_category: list[dict]) -> tuple[float, list[str]]:
    """
    Score health by how closely spending matches the 50/30/20 rule.
    Returns (score 0-100, list of insight strings).
    """
    insights: list[str] = []
    total = summary.get("current_month_total") or 0.0

    if total <= 0:
        return float(DEFAULT_STAT), ["No spending data yet — health starts at neutral 50."]

    needs_total = _category_total(by_category, NEEDS_CATEGORIES)
    wants_total = _category_total(by_category, WANTS_CATEGORIES)
    savings_total = max(0.0, total - needs_total - wants_total)  # mostly "Other"

    needs_pct = needs_total / total
    wants_pct = wants_total / total
    savings_pct = savings_total / total

    # Total deviation from 50/30/20 targets (0 = perfect, 1 = completely off)
    deviation = (
        abs(needs_pct - NEEDS_TARGET) +
        abs(wants_pct - WANTS_TARGET) +
        abs(savings_pct - SAVINGS_TARGET)
    )

    # Map deviation [0, 1] → health [100, 0]
    score = _clamp(100.0 - deviation * 100.0)

    if needs_pct > NEEDS_TARGET + 0.10:
        insights.append(
            f"Needs spending (Food, Transport, Housing, Utilities, Health, Education) is "
            f"{needs_pct:.0%} of your budget — above the 50% target. Consider trimming "
            f"Housing or Utilities costs if possible."
        )
    elif needs_pct < NEEDS_TARGET - 0.10:
        insights.append(
            f"Needs are only {needs_pct:.0%} of your budget — well below target. "
            f"You have healthy room for savings or discretionary spending."
        )
    else:
        insights.append(f"Needs spending ({needs_pct:.0%}) is on track with the 50% target.")

    if wants_pct > WANTS_TARGET + 0.10:
        insights.append(
            f"Wants spending (Entertainment, Shopping, Travel) is {wants_pct:.0%} — "
            f"above the 30% target."
        )
    elif wants_pct > 0:
        insights.append(f"Wants spending ({wants_pct:.0%}) is within the 30% target.")

    if savings_pct < SAVINGS_TARGET - 0.05:
        insights.append(
            f"Only {savings_pct:.0%} of this month's spending is left over after needs and "
            f"wants. The 50/30/20 rule recommends 20% toward savings or investments."
        )
    else:
        insights.append(
            f"Savings allocation ({savings_pct:.0%}) meets or exceeds the 20% benchmark — great discipline."
        )

    return score, insights


# ---------------------------------------------------------------------------
# ENERGY — Z-score anomaly detection
# ---------------------------------------------------------------------------

def compute_energy(summary: dict, by_month: list[dict]) -> tuple[float, list[str]]:
    """
    Compares current month spend to historical distribution via z-score.
    Returns (score 0-100, insight strings).
    """
    insights: list[str] = []
    current = summary.get("current_month_total") or 0.0
    energy = float(DEFAULT_STAT)

    historical = [m["total"] for m in by_month if m.get("total") is not None]

    if len(historical) < ENERGY_MIN_HISTORY:
        insights.append(
            f"Not enough history yet to benchmark this month's spending "
            f"({len(historical)} month(s) recorded; need {ENERGY_MIN_HISTORY}). "
            f"Energy is neutral until a baseline is established."
        )
        return energy, insights

    mu = _mean(historical)
    std = _std(historical, mu)

    if std < 1.0:
        insights.append(
            f"Your monthly spending is very consistent (~₹{mu:,.0f}/mo). "
            f"Energy is at neutral — no anomalies detected."
        )
        return energy, insights

    z = (current - mu) / std

    if z > Z_HIGH_THRESHOLD:
        energy -= ENERGY_Z_HIGH_PENALTY
        insights.append(
            f"This month's spending (₹{current:,.0f}) is {z:.1f} standard deviations above "
            f"your average (₹{mu:,.0f}). That's a statistically unusual spike — "
            f"energy is drained from the financial stress."
        )
    elif z < Z_LOW_THRESHOLD:
        energy += ENERGY_Z_LOW_BONUS
        insights.append(
            f"Spending this month (₹{current:,.0f}) is {abs(z):.1f} std devs below your average "
            f"(₹{mu:,.0f}) — you're well within budget. Energy boosted."
        )
    else:
        insights.append(
            f"This month's spending (₹{current:,.0f}) is within 1.5 std devs of your "
            f"historical average (₹{mu:,.0f}). No anomalies — energy is stable."
        )

    return _clamp(energy), insights


# ---------------------------------------------------------------------------
# HAPPINESS — fun-spend consistency (Entertainment + Travel)
# ---------------------------------------------------------------------------

def compute_happiness(
    summary: dict,
    by_category: list[dict],
    days_since_last_fun_spend: float | None = None,
) -> tuple[float, list[str]]:
    """
    Rewards regular, moderate fun spending. Penalises excess or prolonged absence.
    Returns (score 0-100, insight strings).
    """
    insights: list[str] = []
    total = summary.get("current_month_total") or 0.0
    happiness = float(DEFAULT_STAT)

    fun_total = _category_total(by_category, FUN_CATEGORIES)

    if total > 0:
        fun_ratio = fun_total / total
        if fun_ratio > FUN_MAX_RATIO:
            happiness -= FUN_EXCESS_PENALTY
            insights.append(
                f"Entertainment + Travel is {fun_ratio:.0%} of spending — above the healthy "
                f"30% ceiling. Excess discretionary spending can cause financial stress."
            )
        elif fun_ratio >= FUN_MIN_RATIO:
            happiness += FUN_HEALTHY_BONUS
            insights.append(
                f"You're spending {fun_ratio:.0%} on Entertainment + Travel — a healthy balance. "
                f"Regular small treats correlate with sustained happiness."
            )
        else:
            insights.append(
                f"Very little fun spending this month ({fun_ratio:.0%}). "
                f"Consider a small discretionary treat — financial wellbeing includes enjoyment."
            )
    else:
        insights.append("No spending recorded yet. Happiness is at neutral.")

    if fun_total == 0 and days_since_last_fun_spend is not None:
        if days_since_last_fun_spend >= NO_FUN_DAYS_THRESHOLD:
            happiness -= NO_FUN_PENALTY
            insights.append(
                f"No Entertainment/Travel spending in {days_since_last_fun_spend:.0f} days. "
                f"Prolonged absence of discretionary spending is linked to lower life satisfaction."
            )

    return _clamp(happiness), insights


# ---------------------------------------------------------------------------
# WEALTH — EMA trend model
# ---------------------------------------------------------------------------

def compute_wealth_level(
    summary: dict,
    by_month: list[dict],
    previous_stats: dict | None,
) -> tuple[float, list[str]]:
    """
    Uses an Exponential Moving Average of historical spend to determine whether
    current spending is trending up or down vs the smoothed baseline.
    Returns (score 0-100, insight strings).
    """
    insights: list[str] = []
    current = summary.get("current_month_total") or 0.0
    prev_wealth = (previous_stats or {}).get("wealth_level")
    wealth = float(prev_wealth) if prev_wealth is not None else float(DEFAULT_STAT)

    historical = [m["total"] for m in by_month if m.get("total") is not None]

    if not historical:
        insights.append(
            "No spending history yet. Wealth level starts at neutral 50 "
            "and will trend based on your EMA spending pattern."
        )
        return _clamp(wealth), insights

    ema = historical[0]
    for val in historical[1:]:
        ema = EMA_ALPHA * val + (1 - EMA_ALPHA) * ema

    delta = ema - current
    wealth_delta = (delta / ema) * WEALTH_EMA_SCALE if ema > 0 else 0.0
    wealth = _clamp(wealth + wealth_delta)

    if delta > 0:
        insights.append(
            f"Your EMA spending baseline is ₹{ema:,.0f}/mo. This month (₹{current:,.0f}) "
            f"is below that — your wealth score is trending upward."
        )
    elif delta < -0.05 * ema:
        insights.append(
            f"Spending (₹{current:,.0f}) is above your smoothed baseline (₹{ema:,.0f}). "
            f"Consistent overspending relative to your own history erodes wealth score."
        )
    else:
        insights.append(
            f"Spending is roughly in line with your EMA baseline (₹{ema:,.0f}/mo). "
            f"Wealth level is holding steady."
        )

    return wealth, insights


# ---------------------------------------------------------------------------
# FORECAST — linear regression on monthly totals
# ---------------------------------------------------------------------------

def compute_forecast(by_month: list[dict]) -> dict | None:
    """
    Fit a simple linear trend (least squares) to the last N months' totals
    and project the next month. Returns None if insufficient data.
    """
    totals = [m["total"] for m in by_month if m.get("total") is not None]
    n = len(totals)
    if n < 3:
        return None

    xs = list(range(n))
    mx = _mean(xs)
    my = _mean(totals)
    num = sum((xs[i] - mx) * (totals[i] - my) for i in range(n))
    den = sum((xs[i] - mx) ** 2 for i in range(n))
    slope = num / den if den != 0 else 0.0
    intercept = my - slope * mx

    projected = slope * n + intercept  # one step beyond last observed

    trend = "rising" if slope > 0 else "falling" if slope < 0 else "flat"

    return {
        "projected_next_month": round(max(0.0, projected), 2),
        "trend": trend,
        "slope_per_month": round(slope, 2),
        "months_used": n,
    }


# ---------------------------------------------------------------------------
# Category breakdown — used by the new "category mix" UI card
# ---------------------------------------------------------------------------

def compute_category_breakdown(summary: dict, by_category: list[dict]) -> list[dict]:
    """
    Returns every ALLOWED_CATEGORIES entry (even ones with zero spend this
    month) with its total and share of the month's spend, plus whether it's
    classified as a need or a want. Sorted by total, descending.
    """
    total = summary.get("current_month_total") or 0.0
    totals_by_cat = {c.get("category"): (c.get("total") or 0) for c in by_category}

    rows = []
    for cat in ALLOWED_CATEGORIES:
        amount = float(totals_by_cat.get(cat, 0) or 0)
        if cat in NEEDS_CATEGORIES:
            bucket = "need"
        elif cat in WANTS_CATEGORIES:
            bucket = "want"
        else:
            bucket = "other"
        rows.append({
            "category": cat,
            "total": amount,
            "share": (amount / total) if total > 0 else 0.0,
            "bucket": bucket,
        })

    rows.sort(key=lambda r: r["total"], reverse=True)
    return rows


# ---------------------------------------------------------------------------
# Animation state
# ---------------------------------------------------------------------------

def map_animation_state(stats: dict) -> str:
    health = stats.get("health", DEFAULT_STAT)
    energy = stats.get("energy", DEFAULT_STAT)
    happiness = stats.get("happiness", DEFAULT_STAT)
    wealth_level = stats.get("wealth_level", DEFAULT_STAT)

    avg = (health + energy + happiness + wealth_level) / 4

    if happiness >= 55 and avg >= 60:
        return "happy"
    if health <= 35 or happiness <= 30:
        return "sad"
    if energy <= 35:
        return "tired"
    return "idle"


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def compute_all_stats(
    summary: dict,
    by_category: list[dict],
    by_month: list[dict],
    previous_stats: dict | None = None,
    days_since_last_fun_spend: float | None = None,
) -> dict:
    """
    Compute the full stat block. Returns stats + insights + (optional)
    forecast + category breakdown.
    """
    health, health_insights = compute_health(summary, by_category)
    energy, energy_insights = compute_energy(summary, by_month)
    happiness, happy_insights = compute_happiness(summary, by_category, days_since_last_fun_spend)
    wealth_level, wealth_insights = compute_wealth_level(summary, by_month, previous_stats)

    stats = {
        "health": health,
        "energy": energy,
        "happiness": happiness,
        "wealth_level": wealth_level,
    }
    stats["animation_state"] = map_animation_state(stats)

    stats["insights"] = {
        "health": health_insights,
        "energy": energy_insights,
        "happiness": happy_insights,
        "wealth_level": wealth_insights,
    }

    stats["category_breakdown"] = compute_category_breakdown(summary, by_category)

    forecast = compute_forecast(by_month)
    if forecast:
        stats["forecast"] = forecast

    return stats
