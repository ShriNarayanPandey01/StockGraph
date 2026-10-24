"""Normalize documented quarterly income summaries without guessing annual values.

Upstox's income_statement categories follow time_period=quarterly; its
full_statement, balance sheet and cash flow remain annual even for matching month
labels. They are retained raw and must not be mislabeled quarterly or as EBITDA.
Reference: https://upstox.com/developer/api-documentation/get-income-statement/
"""

from calendar import monthrange
from datetime import date, datetime
from decimal import Decimal, InvalidOperation


def _period(value):
    try:
        parsed = datetime.strptime(str(value), "%b %Y")
        if parsed.month not in (3, 6, 9, 12):
            return None
        return date(parsed.year, parsed.month, monthrange(parsed.year, parsed.month)[1])
    except (ValueError, TypeError):
        return None


def _amount(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = Decimal(str(value))
        return parsed if parsed.is_finite() and abs(parsed) < Decimal("1000000000000") else None
    except (InvalidOperation, ValueError):
        return None


def normalize_statements(ticker, statements, vendor_id, vendor_as_of):
    statement = statements.get("income-statement")
    if not isinstance(statement, dict):
        return []
    data = statement.get("data")
    if not isinstance(data, dict):
        return []
    if data.get("time_period") != "quarterly" or data.get("units_in") != "crore":
        return []
    values = {}
    for category in data.get("income_statement", []):
        if not isinstance(category, dict):
            continue
        name = category.get("category")
        if name not in {"revenue", "net_profit"}:
            continue
        for record in category.get("history", []):
            if not isinstance(record, dict):
                continue
            period, value = _period(record.get("period")), _amount(record.get("value"))
            if period is not None and value is not None and period <= vendor_as_of.date():
                values.setdefault(period, {})[name] = value
    rows = []
    for period, value in sorted(values.items()):
        quarter = {6: 1, 9: 2, 12: 3, 3: 4}[period.month]
        fiscal_year = period.year + (period.month != 3)
        row = {"ticker": ticker, "quarter_label": f"Q{quarter}FY{fiscal_year}",
               # The provider does not return a publication date. This is the
               # receipt date, never a fabricated filing/quarter-end knowledge date.
               "published_date": vendor_as_of.date(), "valid_from_ts": int(vendor_as_of.timestamp()),
               "revenue_cr": value.get("revenue"), "pat_cr": value.get("net_profit"),
               "source_id": vendor_id, "source_as_of": vendor_as_of}
        prior = values.get(date(period.year - 1, period.month, period.day), {})
        for name, field in (("revenue", "rev_yoy_pct"), ("net_profit", "pat_yoy_pct")):
            base = prior.get(name)
            if base not in (None, 0) and name in value:
                change = (value[name] - base) / abs(base) * 100
                if abs(change) < 10000:
                    rounded = change.quantize(Decimal("0.01"))
                    if abs(rounded) < 10000:
                        row[field] = rounded
        rows.append(row)
    return rows


def narrative_quarter_context(rows):
    if not rows:
        return None
    row = max(rows, key=lambda r: (int(r["quarter_label"][-4:]), int(r["quarter_label"][1])))
    observations = []
    for field, label in (("rev_yoy_pct", "Revenue"), ("pat_yoy_pct", "Net profit")):
        if row.get(field) is not None:
            observations.append(f"{label} {'increased' if row[field] > 0 else 'decreased' if row[field] < 0 else 'was unchanged'} year over year")
    if row.get("pat_cr") is not None:
        observations.append("Reported a net loss" if row["pat_cr"] < 0 else "Reported a net profit")
    return (f"{row['quarter_label']} quarterly income statement. " + "; ".join(observations) +
            f". Source: {row['source_id']}; received {row['source_as_of'].isoformat()}. "
            "Exact financial figures remain in the Data Service; receipt time is not a filing publication time.")
