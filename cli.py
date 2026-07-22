#!/usr/bin/env python3
"""A-Share Financial Data Fetcher — CLI.

Usage:
  python cli.py refresh [--years 2022,2023,2024,2025] [--count N]
  python cli.py export --format json [--output data.json] [--years 2022,2023,2024,2025]
  python cli.py serve --port 8080
"""

import asyncio
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from fetcher.rate_limiter import RateLimiter
from fetcher.client import FetcherClient
from fetcher.cache import init_db, upsert_financials, load_financials, is_stale
from fetcher.merger import merge_one
from fetcher.sources import eastmoney_fin, eastmoney_quote, eastmoney_dividend

# Rate limiters: emweb is very fast (~300+ rpm实测), but play safe at 200
limiter_fin = RateLimiter(rpm=360, burst=20)    # financial data: ~360 stocks/min
limiter_div = RateLimiter(rpm=360, burst=20)    # dividend data
limiter_quote = RateLimiter(rpm=30)              # push2: not used for bulk PB

# Default stock pool: load from all_codes.txt or use built-in list
ALL_CODES_FILE = os.path.join(os.path.dirname(__file__), "all_codes.txt")
PB_CACHE_FILE = os.path.join(os.path.dirname(__file__), "pb_cache.json")

def _load_codes() -> list[str]:
    if os.path.exists(ALL_CODES_FILE):
        with open(ALL_CODES_FILE) as f:
            return [l.strip() for l in f if l.strip()]
    return []

def _load_pb_cache() -> dict[str, float | None]:
    if os.path.exists(PB_CACHE_FILE):
        import json
        with open(PB_CACHE_FILE) as f:
            return json.load(f)
    return {}


async def fetch_one_stock(code: str,
                          sem: asyncio.Semaphore,
                          client_fin: FetcherClient,
                          client_div: FetcherClient,
                          pb_map: dict[str, float | None]) -> list[dict]:
    """Fetch all data for one stock, merge, return rows."""
    async with sem:
        # 1. Financial indicators (all years)
        fin_rows = await eastmoney_fin.fetch_one(client_fin, code)
        if not fin_rows:
            return []

        # 2. PB from batch cache (supports both float and {pb, shares} dict formats)
        pb_entry = pb_map.get(code)
        if isinstance(pb_entry, dict):
            pb = pb_entry.get("pb") if pb_entry else None
        else:
            pb = pb_entry
        quote = {"code": code, "name": "", "pb": pb, "price": None}

        # 3. Dividends
        dividends = await eastmoney_dividend.fetch_one(client_div, code)

        # 4. Merge
        return merge_one(fin_rows, quote, dividends)


async def fetch_all(stock_codes: list[str], years: list[int] | None = None):
    """Fetch all data for all stocks concurrently with rate limiting."""
    init_db()

    client_fin = FetcherClient(limiter=limiter_fin)
    client_div = FetcherClient(limiter=limiter_div)
    pb_map = _load_pb_cache()

    # Higher concurrency for bulk fetch
    sem = asyncio.Semaphore(25)

    done = 0
    total = len(stock_codes)
    errors = 0
    lock = asyncio.Lock()
    all_rows = []

    async def fetch_one(code):
        nonlocal done, errors, all_rows
        try:
            rows = await fetch_one_stock(code, sem, client_fin, client_div, pb_map)
            async with lock:
                if rows:
                    if years:
                        rows = [r for r in rows if r["year"] in years]
                    all_rows.extend(rows)
                else:
                    errors += 1
                done += 1
                if done % 100 == 0 or done == total:
                    print(f"  [{done}/{total}] {len(all_rows)} rows, {errors} err", flush=True)
        except Exception as e:
            async with lock:
                errors += 1
                done += 1

    print(f"Fetching {total} stocks (PB cache: {len(pb_map)} entries)...")
    tasks = [fetch_one(c) for c in stock_codes]
    await asyncio.gather(*tasks)

    await client_fin.close()
    await client_div.close()

    n_stocks = len({r['code'] for r in all_rows})
    print(f"\nTotal: {len(all_rows)} rows for {n_stocks} stocks ({errors} errors)")

    # Batch cache write
    if all_rows:
        upsert_financials(all_rows)
        print("Cached to SQLite.")
    return all_rows


def _convert_to_dashboard(rows: list[dict],
                           years: list[int]) -> list[dict]:
    """Convert cached rows to the dashboard's DATA format:

    {c: code, n: name, ind: industry,
     roe:    [yr1, yr2, ...],
     debt:   [yr1, yr2, ...],
     fcf:    [yr1, yr2, ...],
     roepb:  [yr1, yr2, ...],
     payout: [yr1, yr2, ...],
     gross:  [yr1, yr2, ...]}
    """
    # Load industry mapping
    industry_map: dict[str, str] = {}
    industry_json = os.path.join(os.path.dirname(__file__), "industry.json")
    if os.path.exists(industry_json):
        with open(industry_json) as f:
            ind_data = json.load(f)
        industry_map = {c: v.get("industry", "") for c, v in ind_data.items()}

    by_code: dict[str, dict] = {}
    for r in rows:
        c = r["code"]
        if c not in by_code:
            by_code[c] = {"_name": r.get("name", c)}
        y = r["year"]
        by_code[c][y] = r

    out = []
    for code, data in sorted(by_code.items()):
        item = {"c": code, "n": data["_name"],
                "ind": industry_map.get(code, "")}
        for metric, key in [
            ("roe", "roe"), ("debt", "debt_ratio"),
            ("fcf", "fcf"), ("roepb", "roe_pb"),
            ("payout", "payout"), ("gross", "gross_margin"),
        ]:
            item[metric] = []
            scan_years = list(years)
            for yr in scan_years:
                row = data.get(yr, {})
                v = row.get(key)
                item[metric].append(round(v, 1) if v is not None else None)
        out.append(item)

    return out


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------

def cmd_refresh(args):
    init_db()

    # --pb-only: just refresh PB quotes and recalculate ROE/PB
    if args.pb_only:
        import time
        print("Refreshing PB quotes for all stocks...")
        t0 = time.monotonic()
        asyncio.run(refresh_pb_only())
        print(f"PB refresh done in {time.monotonic()-t0:.0f}s")
        return

    if not args.force and not is_stale("financials", ttl_hours=48):
        print("Cache is fresh (<48h). Use --force to re-fetch.")
        years_list = [int(y.strip()) for y in args.years.split(",")] if args.years else None
        cached = load_financials(years=years_list)
        if cached:
            print(f"Loaded {len(cached)} rows from cache.")
            return

    # Determine stock list
    codes = _load_codes()  # all_codes.txt (5540 stocks)
    if not codes:
        codes = ["688692", "688278", "688617", "000429", "600062", "300487",
                 "603816", "002130", "600563", "603298", "601156", "600873",
                 "600519", "000858", "601318", "600036", "000333", "002415",
                 "300750", "601012"]
    if args.pool:
        import csv as _csv
        with open(args.pool) as f:
            reader = _csv.reader(f)
            codes = [row[0].strip().zfill(6) for row in reader if row]
    if args.count:
        codes = codes[:int(args.count)]

    years_list = [int(y.strip()) for y in args.years.split(",")] if args.years else None
    print(f"Fetching {len(codes)} stocks for years: {args.years}")
    asyncio.run(fetch_all(codes, years=years_list))


async def refresh_pb_only():
    """Fetch fresh PB for all cached stocks and update ROE/PB in-place."""
    import time, json as _json

    # 1. Re-fetch all PB via per-stock API
    codes_file = ALL_CODES_FILE
    if not os.path.exists(codes_file):
        print("No all_codes.txt, loading codes from DB")
        conn = __import__('sqlite3').connect(os.path.expanduser('~/projects/a_share_fetcher/data.db'))
        codes = [r[0] for r in conn.execute('SELECT DISTINCT stock_code FROM financials').fetchall()]
        conn.close()
    else:
        with open(codes_file) as f:
            codes = [l.strip() for l in f if l.strip()]

    sem = asyncio.Semaphore(30)
    client = FetcherClient(limiter=RateLimiter(rpm=200, burst=10))
    pb_map = {}
    done = 0
    lock = asyncio.Lock()

    async def fetch_one(code):
        nonlocal done
        async with sem:
            quote = await eastmoney_quote.fetch_one(client, code)
            async with lock:
                pb_map[code] = quote.get("pb") if quote else None
                done += 1
                if done % 500 == 0:
                    print(f"  [{done}/{len(codes)}] PB quotes")

    await asyncio.gather(*[fetch_one(c) for c in codes])
    await client.close()

    valid = sum(1 for v in pb_map.values() if v is not None and v > 0)
    print(f"  PB valid: {valid}/{len(pb_map)}")

    # Save PB cache
    with open(PB_CACHE_FILE, 'w') as f:
        _json.dump(pb_map, f)

    # 2. Update DB in-place
    import sqlite3
    db = os.path.expanduser('~/projects/a_share_fetcher/data.db')
    conn = sqlite3.connect(db)
    updated = 0
    for code, pb in pb_map.items():
        if pb is None:
            continue
        cur = conn.execute('''UPDATE financials SET pb = ?, roe_pb =
            CASE WHEN roe IS NOT NULL AND ? > 0 THEN ROUND(roe / ?, 2) ELSE NULL END
            WHERE stock_code = ?''', (pb, pb, pb, code))
        updated += cur.rowcount
    conn.commit()
    conn.close()
    print(f"  DB updated: {updated} rows")


def cmd_export(args):
    years_list = [int(y.strip()) for y in args.years.split(",")] if args.years else [2022, 2023, 2024, 2025]
    rows = load_financials(years=years_list)

    if not rows:
        print("No data in cache. Run 'refresh' first.")
        return

    if args.format == "json":
        # Dashboard-compatible format
        dashboard_data = _convert_to_dashboard(rows, years_list)

        # Filter out suspended stocks (no valid PB)
        dashboard_data = [
            item for item in dashboard_data
            if any(v is not None for v in item.get("roepb", []))
        ]

        # Print summary
        for item in dashboard_data:
            metrics_with_data = sum(
                1 for m in ["roe", "debt", "fcf", "roepb", "payout", "gross"]
                if any(v is not None for v in item[m])
            )
            print(f"  {item['c']} {item['n']}: {metrics_with_data}/6 metrics")

        output = json.dumps(dashboard_data, ensure_ascii=False, indent=2)
        if args.output:
            os.makedirs(os.path.dirname(os.path.abspath(args.output)) or ".", exist_ok=True)
            out_path = args.output
            # Write both JSON and JS (for file:// dashboard compatibility)
            with open(out_path, "w") as f:
                f.write(output)
            print(f"\nExported {len(dashboard_data)} stocks to {out_path}")

            # Also write .js version for <script> tag loading
            js_path = out_path.rsplit(".", 1)[0] + ".js"
            with open(js_path, "w") as f:
                f.write("var STOCK_DATA = ")
                f.write(output)
                f.write(";\n")
            print(f"Exported JS to {js_path}")
        else:
            print(output)

    elif args.format == "csv":
        import csv, io
        out = io.StringIO()
        writer = csv.writer(out)
        header = ["code", "name"] + [
            f"{m}_{y}"
            for m in ["roe", "debt_ratio", "gross_margin", "fcf", "payout", "roe_pb"]
            for y in years_list
        ]
        writer.writerow(header)
        for r in rows:
            # ...
            pass
        print("CSV export not yet implemented for new format. Use --format json.")


def main():
    parser = argparse.ArgumentParser(
        description="A-Share Financial Data Fetcher — fetch & export to dashboard"
    )
    sub = parser.add_subparsers(dest="command")

    p_refresh = sub.add_parser("refresh", help="Fetch and cache financial data")
    p_refresh.add_argument("--years", default="2022,2023,2024,2025")
    p_refresh.add_argument("--count", help="Limit to first N stocks")
    p_refresh.add_argument("--pool", help="CSV file with stock codes")
    p_refresh.add_argument("--force", action="store_true", help="Force re-fetch")
    p_refresh.add_argument("--pb-only", action="store_true", help="Only refresh PB + ROE/PB")

    p_export = sub.add_parser("export", help="Export cached data to dashboard JSON")
    p_export.add_argument("--format", default="json", choices=["json", "csv"])
    p_export.add_argument("--output", "-o", help="Output file path")
    p_export.add_argument("--years", default="2022,2023,2024,2025",
                          help="Comma-separated years for export")

    sub.add_parser("serve", help="Start API server (TODO)")

    args = parser.parse_args()

    if args.command == "refresh":
        cmd_refresh(args)
    elif args.command == "export":
        cmd_export(args)
    elif args.command == "serve":
        print("API server not yet implemented.")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
