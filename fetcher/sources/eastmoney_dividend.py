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

    # 2. Accumulate DPS from all fhyx events (both implemented and planned)
    #    Per-share dividend is the same for A and H shares — reliable for payout ratio
    #    regardless of whether East Money's TOTAL_DIVIDEND covers A-share only or A+H.
    for event in resp.get("fhyx") or []:
        progress = str(event.get("ASSIGN_PROGRESS", ""))
        per_share = _parse_plan(event.get("IMPL_PLAN_PROFILE", ""))
        if per_share is None:
            continue

        notice_date = str(event.get("NOTICE_DATE", ""))[:4]
        if not notice_date.isdigit():
            continue
        notice_year = int(notice_date)

        # Map notice date to fiscal year:
        #   Jan-Jul: final dividend of previous FY (N+1 → FY N)
        #   Aug-Dec: mid-year dividend of current FY (N → FY N)
        month = int(str(event.get("NOTICE_DATE", ""))[5:7])
        fiscal_year = notice_year if month >= 8 else notice_year - 1

        existing = out.get(fiscal_year, {})

        # Always accumulate dps (per-share, correct for both A and H shares)
        existing["dps"] = round((existing.get("dps") or 0) + per_share, 4)

        # Planned (not yet implemented) dividends: fill gaps + mark planned_dps
        if '股东大会预案' in progress:
            existing_div = existing.get("total_dividend")
            if existing_div and existing_div > 0:
                # Already has implemented dividend (e.g. mid-term);
                # add planned DPS on top so merger can sum them (mid + final)
                existing["planned_dps"] = per_share
                out[fiscal_year] = existing
                continue

            # No implemented dividend yet for this fiscal year
            if "total_dividend" not in existing:
                existing["total_dividend"] = None

        out[fiscal_year] = existing

    return out
