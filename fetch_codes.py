#!/usr/bin/env python3
"""Fetch all A-share stock codes from East Money, update all_codes.txt."""
import os
import time
import httpx

URL = "https://push2delay.eastmoney.com/api/qt/clist/get"
# Combined A-share: 沪主板 + 科创板 + 深主板 + 创业板
MARKET_FILTER = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": "https://data.eastmoney.com/",
}


def fetch_page(client: httpx.Client, page: int) -> dict | None:
    params = {
        "fid": "f3", "po": "1", "pz": "100",
        "pn": str(page), "np": "1", "fltt": "2", "invt": "2",
        "fs": MARKET_FILTER,
        "fields": "f12,f14",
    }
    for attempt in range(3):
        try:
            resp = client.get(URL, params=params, headers=HEADERS, timeout=30.0)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            if attempt < 2:
                wait = 2 ** attempt
                print(f"  page {page} attempt {attempt+1} failed ({e}), retrying in {wait}s...")
                time.sleep(wait)
            else:
                print(f"  Error on page {page}: {e}")
                return None


def main():
    print("Fetching A-share stock list...")

    codes = []
    page = 1
    seen = 0

    with httpx.Client() as client:
        while True:
            data = fetch_page(client, page)
            if not data:
                break

            d = data.get("data")
            if not d:
                break

            diffs = d.get("diff") or []
            for item in diffs:
                codes.append(item["f12"])

            seen += len(diffs)
            total = d.get("total", 0)
            print(f"  page {page}: {len(diffs)} items, {seen}/{total} total", flush=True)

            if len(diffs) == 0 or seen >= total:
                break
            page += 1
            time.sleep(0.3)  # avoid rate limiting

    codes.sort()
    sh = sum(1 for c in codes if c.startswith(("6", "68")))
    sz = sum(1 for c in codes if c.startswith(("0", "3", "9")))

    print(f"  Total: {len(codes)} (沪:{sh} 深:{sz})")

    script_dir = os.path.dirname(os.path.abspath(__file__))
    out_path = os.path.join(script_dir, "all_codes.txt")
    with open(out_path, "w") as f:
        f.write("\n".join(codes))
    print(f"  Written to {out_path}")


if __name__ == "__main__":
    main()
