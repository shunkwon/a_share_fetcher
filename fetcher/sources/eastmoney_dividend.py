"""East Money BonusFinancing: dividend distribution history.

Per-stock API: emweb.securities.eastmoney.com/PC_HSF10/BonusFinancing/PageAjax
  - lnfhrz: annual dividend statistics (TOTAL_DIVIDEND per STATISTICS_YEAR)
  - fhyx: individual dividend event records (includes planned dividends)
"""

import re
from ..client import FetcherClient

BONUS_URL = "https://emweb.securities.eastmoney.com/PC_HSF10/BonusFinancing/PageAjax"


def _exchange_prefix(code: str) -> str:
    if code.startswith(("6", "68")):
        return f"SH{code}"
    return f"SZ{code}"


def _parse_plan(profile: str) -> float | None:
    """Parse dividend per share from plan profile string like '10派65.6元'."""
    if not profile or '不分配' in profile:
        return None
    m = re.search(r'10派([\d.]+)元', profile)
    if m:
        return float(m.group(1)) / 10.0  # per share
    return None


async def fetch_one(client: FetcherClient, code: str) -> dict[int, dict]:
    """Fetch annual dividend totals for one stock.

    Combines two sources:
    1. lnfhrz: implemented dividends (TOTAL_DIVIDEND already calculated)
    2. fhyx: planned dividends not yet implemented (parse IMPL_PLAN_PROFILE)
    """
    secu = _exchange_prefix(code)
    resp = await client.get_json(f"{BONUS_URL}?code={secu}")
    if not resp:
        return {}

    out: dict[int, dict] = {}

    # 1. Implemented dividends from lnfhrz
    for row in resp.get("lnfhrz") or []:
        yr = row.get("STATISTICS_YEAR")
        if yr is None:
            continue
        out[int(yr)] = {
            "total_dividend": row.get("TOTAL_DIVIDEND"),
            "seo_num": row.get("SEO_NUM"),
            "allotment_num": row.get("ALLOTMENT_NUM"),
            "ipo_num": row.get("IPO_NUM"),
        }

    # 2. Planned dividends from fhyx: fill gaps where lnfhrz has 0 or missing
    for event in resp.get("fhyx") or []:
        progress = event.get("ASSIGN_PROGRESS", "")
        if '股东大会预案' not in str(progress):
            continue

        notice_date = str(event.get("NOTICE_DATE", ""))[:4]
        if not notice_date.isdigit():
            continue
        notice_year = int(notice_date)

        # The dividend plan announced in year N+1 belongs to fiscal year N
        fiscal_year = notice_year - 1

        per_share = _parse_plan(event.get("IMPL_PLAN_PROFILE", ""))
        if per_share is None:
            continue

        existing = out.get(fiscal_year, {})
        existing_div = existing.get("total_dividend")

        if existing_div and existing_div > 0:
            # Already has implemented dividend (e.g. mid-term);
            # add planned DPS on top so merger can sum them (mid + final)
            existing["planned_dps"] = per_share
            continue

        out[fiscal_year] = {
            "total_dividend": existing.get("total_dividend"),  # 0 or None
            "dps": per_share,  # dividend per share from plan
            "seo_num": existing.get("seo_num"),
            "allotment_num": existing.get("allotment_num"),
            "ipo_num": existing.get("ipo_num"),
        }

    return out
