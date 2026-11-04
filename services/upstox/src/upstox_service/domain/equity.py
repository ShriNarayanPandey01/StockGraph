"""Classify company shares within the exchanges' broader cash segments."""

# BSE uses trading groups rather than NSE's EQ instrument type. F/G are
# debt/government securities, E is ETFs, IF is investment trusts and R rights.
BSE_STOCK_GROUPS = frozenset({"A", "B", "T", "X", "XT", "Z", "P", "ZP", "M", "MT", "MS", "TS"})


def is_company_equity(row: dict, exchange: str | None = None) -> bool:
    """Keep company shares; cash-market membership alone also admits funds.

    Fund/ETF ISINs (INF...) can even carry NSE EQ or BSE B, so the trading
    group is insufficient. Do not classify by company name: listed asset
    managers are legitimate stocks.
    """
    exchange = exchange or row.get("exchange") or str(row.get("segment", "")).split("_")[0]
    if exchange not in {"NSE", "BSE"} or row.get("segment") != f"{exchange}_EQ":
        return False
    if not all(isinstance(row.get(key), str) and row[key] for key in (
        "trading_symbol", "isin", "instrument_key",
    )):
        return False
    if row["isin"].upper().startswith("INF"):
        return False
    instrument_type = row.get("instrument_type")
    if not isinstance(instrument_type, str):
        return False
    return instrument_type == "EQ" if exchange == "NSE" else instrument_type in BSE_STOCK_GROUPS
