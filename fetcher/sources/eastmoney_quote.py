"""East Money push2: individual stock quotes (PB ratio, name, price).

Per-stock API: push2.eastmoney.com/api/qt/stock/get
  secid = 1.{code} for Shanghai, 0.{code} for Shenzhen
  f167 = PB (scaled *100), f43 = price (scaled *100), f57/f58 = code/name
"""

from ..client import FetcherClient


QUOTE_URL = "https://push2.eastmoney.com/api/qt/stock/get"


def _secid(code: str) -> str:
    """East Money secid: 1. for Shanghai, 0. for Shenzhen."""
    if code.startswith(("6", "68")):
        return f"1.{code}"
    return f"0.{code}"


async def fetch_one(client: FetcherClient, code: str) -> dict | None:
    """Fetch quote for one stock. Returns {code, name, pb, price} or None."""
    resp = await client.get_json(
        f"{QUOTE_URL}?secid={_secid(code)}&fields=f43,f57,f58,f167"
    )
    if not resp:
        return None
    data = resp.get("data")
    if not data:
        return None

    pb_raw = data.get("f167")
    price_raw = data.get("f43")

    return {
        "code": data.get("f57", code),
        "name": data.get("f58", ""),
        "pb": float(pb_raw) / 100.0 if pb_raw is not None else None,
        "price": float(price_raw) / 100.0 if price_raw is not None else None,
    }
