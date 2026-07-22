#!/usr/bin/env python3
"""Fetch all A-share stock codes from East Money, update all_codes.txt."""
import json
import httpx

URL = "https://push2.eastmoney.com/api/qt/clist/get"
# Combined A-share: 沪主板 + 科创板 + 深主板 + 创业板
MARKET_FILTER = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"


def main():
    print("Fetching A-share stock list...")

    url = f"{URL}?pn=1&pz=10000&po=1&np=1&fltt=2&invt=2&fid=f3&fs={MARKET_FILTER}&fields=f12,f14"

    try:
        resp = httpx.get(url, timeout=30.0)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"  Error: {e}")
        return

    total = data.get("data", {}).get("total", 0)
    items = data.get("data", {}).get("diff", [])
    codes = sorted(item["f12"] for item in items)
    sh = sum(1 for c in codes if c.startswith(("6", "68")))
    sz = sum(1 for c in codes if c.startswith(("0", "3", "9")))

    print(f"  API total: {total}, got: {len(codes)} (沪:{sh} 深:{sz})")

    import os
    script_dir = os.path.dirname(os.path.abspath(__file__))
    out_path = os.path.join(script_dir, "all_codes.txt")
    with open(out_path, "w") as f:
        f.write("\n".join(codes))
    print(f"  Written to {out_path}")


if __name__ == "__main__":
    main()
