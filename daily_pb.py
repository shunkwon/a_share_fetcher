#!/usr/bin/env python3
"""Daily PB refresher: fetch PB for all stocks via batch API, update ROE/PB in data.json.

Uses the push2 clist batch API (100 stocks/page) instead of per-stock API,
so it completes in ~30 seconds instead of ~15 minutes.

Reads existing data.json (with cached financials), fetches fresh PB from eastmoney,
recalculates ROE/PB = ROE / PB, writes updated data.json and data.js.
"""
import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

from fetcher.client import FetcherClient


async def fetch_all_pb_batch(codes: set[str]) -> dict[str, float | None]:
    """Fetch PB for all codes using the batch clist API (fast, ~100 per page)."""
    client = FetcherClient()
    results: dict[str, float | None] = {}
    page = 1
    seen = 0

    while True:
        params = {
            "fid": "f3", "po": "1", "pz": "100",
            "pn": str(page), "np": "1", "fltt": "2", "invt": "2",
            "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
            "fields": "f12,f23",
        }
        resp = await client.get_json(
            "https://push2delay.eastmoney.com/api/qt/clist/get", params
        )
        if not resp:
            break

        data = resp.get("data")
        if not data:
            break

        diffs = data.get("diff") or []
        for item in diffs:
            code = item.get("f12", "")
            if code not in codes:
                continue
            raw = item.get("f23")
            if raw is not None and raw != "-" and raw != "":
                results[code] = float(raw)
            else:
                results[code] = None

        seen += len(diffs)
        total = data.get("total", 0)
        print(f"  page {page}: {len(diffs)} items, {seen}/{total} total", flush=True)
        if len(diffs) == 0 or seen >= total:
            break
        page += 1
        await asyncio.sleep(0.3)

    await client.close()
    return results


async def refresh_pb(input_json: str, output_json: str, output_js: str):
    # Load existing dashboard data
    print(f"Loading {input_json}...")
    with open(input_json) as f:
        stocks = json.load(f)
    print(f"  {len(stocks)} stocks loaded")

    # Collect all codes we need PB for
    codes = {s["c"] for s in stocks}
    print(f"Fetching PB for {len(codes)} stocks via batch API...")
    t0 = time.monotonic()

    pb_map = await fetch_all_pb_batch(codes)

    valid = sum(1 for v in pb_map.values() if v is not None and v > 0)
    elapsed = time.monotonic() - t0
    print(f"  Done in {elapsed:.0f}s: {valid}/{len(codes)} valid PB")

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
    os.makedirs(os.path.dirname(os.path.abspath(output_json)) or ".", exist_ok=True)
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
    dashboard_dir = os.path.join(script_dir, "dashboard")
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
