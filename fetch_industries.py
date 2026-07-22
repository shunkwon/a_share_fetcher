"""Fetch industry classification for all A-share stocks from push2 clist API.

Output: industry.json → {code: {industry, name}}
"""

import asyncio
import json
import os
from fetcher.client import FetcherClient

OUTPUT = os.path.join(os.path.dirname(__file__), "industry.json")


async def fetch_all_industries():
    client = FetcherClient()
    results: dict[str, dict] = {}
    page = 1
    page_size = 500

    seen = 0
    while True:
        params = {
            "fid": "f3", "po": "1", "pz": str(page_size),
            "pn": str(page), "np": "1", "fltt": "2", "invt": "2",
            "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
            "fields": "f12,f14,f100",
        }
        resp = await client.get_json(
            "https://push2.eastmoney.com/api/qt/clist/get", params
        )
        if not resp:
            break

        data = resp.get("data")
        if not data:
            break

        diffs = data.get("diff") or []
        for item in diffs:
            code = item.get("f12", "")
            results[code] = {
                "industry": item.get("f100", ""),
                "name": item.get("f14", ""),
            }

        seen += len(diffs)
        total = data.get("total", 0)
        print(f"  page {page}: {len(diffs)} items, {seen}/{total} total", flush=True)
        if len(diffs) == 0 or seen >= total:
            break
        page += 1

    await client.close()

    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False)
    print(f"Saved {len(results)} stock industries to {OUTPUT}")
    return results


if __name__ == "__main__":
    asyncio.run(fetch_all_industries())
