"""Merge per-stock financial data into dashboard-ready rows."""


def merge_one(fin_rows: list[dict],
              quote: dict | None,
              dividends: dict[int, dict]) -> list[dict]:
    """Merge financial, quote, and dividend data for ONE stock.

    fin_rows: list of {code, year, name, roe, debt_ratio, gross_margin,
                        fcf_back, bps, eps, net_profit, op_cf_ps}
    quote: {code, name, pb, price} or None
    dividends: {year: {total_dividend, ...}}

    Returns list of {code, name, year, roe, debt_ratio, gross_margin,
                     fcf, payout, pb, roe_pb}
    """
    pb = quote.get("pb") if quote else None

    rows = []
    for fin in fin_rows:
        year = fin["year"]
        div = dividends.get(year, {})

        # FCF in 亿 (100 million yuan)
        # Primary: East Money FCFF_FORWARD (cash-flow method ≈ OCF - CapEx)
        # Fallback 1: FCFF_BACK (balance-sheet method, sensitive to ΔWC)
        # Fallback 2: operating cashflow = OpCF_per_share * total_shares / 1e8
        fcf_forward = fin.get("fcf_forward")
        fcf_back = fin.get("fcf_back")
        fcf = None
        if fcf_forward is not None:
            fcf = round(fcf_forward / 1e8, 2)
        elif fcf_back is not None:
            fcf = round(fcf_back / 1e8, 2)
        else:
            op_cf_ps = fin.get("op_cf_ps")
            net_profit = fin.get("net_profit")
            eps = fin.get("eps")
            if op_cf_ps is not None and net_profit is not None and eps is not None and eps > 0:
                shares = net_profit / eps
                fcf = round(op_cf_ps * shares / 1e8, 2)

        # Payout ratio = total_dividend / net_profit * 100
        # If planned_dps exists (mid-term already paid + final 预案), add it on top
        # Fallback: dps / eps * 100 (for planned but not yet implemented dividends)
        total_div = div.get("total_dividend")
        dps = div.get("dps")
        planned_dps = div.get("planned_dps")
        net_profit = fin.get("net_profit")
        eps = fin.get("eps")
        payout = None
        if total_div is not None and total_div > 0 and net_profit is not None and net_profit > 0:
            full_div = total_div
            if planned_dps is not None and eps is not None and eps > 0:
                shares = net_profit / eps
                full_div = full_div + planned_dps * shares
            payout = round(full_div / net_profit * 100, 2)
        elif dps is not None and eps is not None and eps > 0:
            payout = round(dps / eps * 100, 2)

        # ROE/PB
        roe = fin.get("roe")
        roe_pb = None
        if roe is not None and pb is not None and pb > 0:
            roe_pb = round(roe / pb, 2)

        rows.append({
            "code": fin["code"],
            "name": fin.get("name") or (quote.get("name") if quote else ""),
            "year": year,
            "roe": roe,
            "debt_ratio": fin.get("debt_ratio"),
            "gross_margin": fin.get("gross_margin"),
            "fcf": fcf,
            "payout": payout,
            "pb": pb,
            "roe_pb": roe_pb,
        })

    return rows
