"""East Money emweb: main financial indicators (ROE, debt, gross margin, FCF, BPS).

Uses the ZYZBAjaxNew endpoint which returns all available years for a single stock.
Fields: ROEJQ, ZCFZL (debt ratio), XSMLL (gross margin), FCFF_BACK,
        BPS (book value per share), EPSJB (basic EPS), PARENTNETPROFIT,
        MGJYXJJE (operating cashflow per share).
"""

from ..client import FetcherClient


EMWEB_URL = "https://emweb.securities.eastmoney.com/PC_HSF10/NewFinanceAnalysis/ZYZBAjaxNew"


def _exchange_prefix(code: str) -> str:
    """Return the East Money exchange prefix for a 6-digit A-share code."""
    if code.startswith(("6", "68")):
        return f"SH{code}"
    return f"SZ{code}"


async def fetch_one(client: FetcherClient, code: str) -> list[dict]:
    """Fetch all financial years for one stock. Returns list of {year, metric: val}."""
    secu = _exchange_prefix(code)
    resp = await client.get_json(f"{EMWEB_URL}?type=1&code={secu}")
    if not resp or not resp.get("data"):
        return []

    out = []
    for row in resp["data"]:
        year_str = (row.get("REPORT_DATE") or "")[:4]
        if not year_str.isdigit():
            continue
        year = int(year_str)

        # Parse all metrics, converting to float where possible
        def _f(key):
            v = row.get(key)
            return float(v) if v is not None else None

        out.append({
            "code": code,
            "year": year,
            "name": row.get("SECURITY_NAME_ABBR", ""),
            "roe": _f("ROEJQ"),                    # ROE (%)
            "debt_ratio": _f("ZCFZL"),             # 资产负债率 (%)
            "gross_margin": _f("XSMLL"),           # 销售毛利率 (%)
            "fcf_back": _f("FCFF_BACK"),             # FCFF balance-sheet method (absolute, yuan)
            "fcf_forward": _f("FCFF_FORWARD"),       # FCFF cash-flow method = OCF - CapEx (absolute, yuan)
            "bps": _f("BPS"),                      # 每股净资产
            "eps": _f("EPSJB"),                    # 基本每股收益
            "net_profit": _f("PARENTNETPROFIT"),   # 归母净利润
            "op_cf_ps": _f("MGJYXJJE"),            # 每股经营现金流
            "notify_date": row.get("NOTICE_DATE", ""),
        })

    return out
