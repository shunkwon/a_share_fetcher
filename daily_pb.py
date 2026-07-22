#!/usr/bin/env python3
"""Daily PB refresher: fetch fresh PB for all stocks, update ROE/PB in data.json.

Reads existing data.json (with cached financials), fetches PB from eastmoney,
recalculates ROE/PB = ROE / PB, writes updated data.json and data.js.

Fast (~15 min for 5000 stocks) — no financial data re-fetch needed.
"""
import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

from fetcher.rate_limiter import RateLimiter
from fetcher.client import FetcherClient
from fetcher.sources.eastmoney_quote import fetch_one as fetch_pb_one


async def refresh_pb(input_json: str, output_json: str, output_js: str):
    # Load existing dashboard data
    print(f"Loading {input_json}...")
    with open(input_json) as f:
        stocks = json.load(f)
    print(f"  {len(stocks)} stocks loaded")

    # Fetch PB for all stocks
    limiter = RateLimiter(rpm=360, burst=20)
    client = FetcherClient(limiter=limiter)
    sem = asyncio.Semaphore(30)

    pb_map: dict[str, float | None] = {}
    done = 0
    total = len(stocks)
    errors = 0
    lock = asyncio.Lock()
    t0 = time.monotonic()

    async def fetch_one(code: str):
        nonlocal done, errors
        async with sem:
            try:
                quote = await fetch_pb_one(client, code)
                async with lock:
                    pb_map[code] = quote.get("pb") if quote else None
                    done += 1
                    if done % 500 == 0:
                        elapsed = time.monotonic() - t0
                        rate = done / elapsed * 60
                        eta = (total - done) / rate * 60 if rate > 0 else 0
                        print(f"  [{done}/{total}] PB quotes, {rate:.0f}/min, ETA {eta:.0f}s")
            except Exception:
                async with lock:
                    errors += 1
                    done += 1

    print(f"Fetching PB for {total} stocks...")
    codes = [s["c"] for s in stocks]
    await asyncio.gather(*[fetch_one(c) for c in codes])
    await client.close()

    valid = sum(1 for v in pb_map.values() if v is not None and v > 0)
    elapsed = time.monotonic() - t0
    print(f"  Done in {elapsed:.0f}s: {valid}/{total} valid PB ({errors} errors)")

    # Update ROE/PB for each stock
    updated = 0
    for stock in stocks:
        code = stock["c"]
        pb = pb_map.get(code)
        if pb is None or pb <= 0:
            continue

        roepb = stock.get("roepb", [])
        roe = stock.get("roe", [])
        new_roepb = []
        changed = False
        for i, (r, old_rp) in enumerate(zip(roe, roepb)):
            if r is not None:
                new_val = round(r / pb, 2)
                new_roepb.append(new_val)
                if old_rp is None or abs(new_val - (old_rp or 0)) > 0.01:
                    changed = True
            else:
                new_roepb.append(None)

        if changed:
            stock["roepb"] = new_roepb
            updated += 1

    print(f"  ROE/PB updated for {updated}/{len(stocks)} stocks")

    # Write output
    out = json.dumps(stocks, ensure_ascii=False, indent=2)
    with open(output_json, "w") as f:
        f.write(out)
    with open(output_js, "w") as f:
        f.write("var STOCK_DATA = ")
        f.write(out)
        f.write(";\n")
    print(f"  Written to {output_json} + {output_js}")


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # Default: update the dashboard's data files in-place
    dashboard_dir = os.path.join(os.path.dirname(script_dir), "financial_dashboard")
    input_json = os.path.join(dashboard_dir, "data.json")
    output_json = os.path.join(dashboard_dir, "data.json")
    output_js = os.path.join(dashboard_dir, "data.js")

    # Allow override for CI: python daily_pb.py <input.json> <output.json> <output.js>
    if len(sys.argv) >= 4:
        input_json = sys.argv[1]
        output_json = sys.argv[2]
        output_js = sys.argv[3]

    if not os.path.exists(input_json):
        print(f"Error: {input_json} not found. Run full refresh first.")
        sys.exit(1)

    asyncio.run(refresh_pb(input_json, output_json, output_js))


if __name__ == "__main__":
    main()
