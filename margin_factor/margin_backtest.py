#!/home/soso/v5/.venv/bin/python3
"""Phase 4: 融资融券因子回测 (RZ_buy_ratio 最低 Top N)
IC负 -> 选 RZ_buy_ratio 最低(融资买入少->未来涨), T+收益分位, 对比v5/动量。
先3个月(2026-04~07)对比doubler, 有效再扩展全段。
"""
import sys, os, sqlite3, time, json
from datetime import datetime
import numpy as np
import pandas as pd

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
TEST_START = '2026-04-01'
TEST_END = '2026-07-14'
TOPS = [5, 10]
HORIZONS = [5, 10, 20]
OUT = os.path.expanduser('~/v5/margin_factor/margin_backtest_result.json')


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def t_return(code, date, db, H):
    rows = db.execute(
        "SELECT close FROM daily_kline WHERE code=? AND date > ? AND close>0 ORDER BY date LIMIT ?",
        (code, date + ' 23:59:59', H)).fetchall()
    buy = db.execute("SELECT close FROM daily_kline WHERE code=? AND date LIKE ?", (code, date + '%')).fetchone()
    if not buy or buy[0] <= 0 or len(rows) < H:
        return None
    return rows[-1][0] / buy[0] - 1


def main():
    log("=" * 60)
    log(f"Phase 4: RZ_buy_ratio 最低 Top 回测 {TEST_START}~{TEST_END}")
    log("=" * 60)
    db = sqlite3.connect(DB)
    log("loading margin_detail (过滤 ETF + rz_buy>0)...")
    md = pd.read_sql("""SELECT m.code, m.date, m.rz_ye, m.rz_buy FROM margin_detail m
        JOIN stock_info s ON m.code = s.symbol
        WHERE s.class='stock' AND m.rz_buy > 0""", db)
    md['date'] = md['date'].str[:10]
    md['RZ_buy_ratio'] = md['rz_buy'] / md['rz_ye']
    log(f"  {len(md)} rows")
    dates = sorted(md[(md.date >= TEST_START) & (md.date <= TEST_END)]['date'].unique())
    log(f"test {len(dates)} days")
    all_codes = [r[0] for r in db.execute(
        "SELECT s.symbol FROM stock_info s WHERE s.class='stock' AND s.name NOT LIKE '%ST%' "
        "AND s.symbol NOT LIKE 'bj%'").fetchall()]
    log(f"{len(all_codes)} all stocks (for percentile)")

    results = {(t, h): [] for t in TOPS for h in HORIZONS}
    t0 = time.time()
    for di, date in enumerate(dates):
        day_md = md[md.date == date].sort_values('RZ_buy_ratio')  # 升序,最低在前
        mkt = {h: [] for h in HORIZONS}
        for code in all_codes:
            for h in HORIZONS:
                r = t_return(code, date, db, h)
                if r is not None:
                    mkt[h].append(r)
        for top in TOPS:
            sel = day_md.head(top)
            for h in HORIZONS:
                mkt_arr = np.array(mkt[h])
                if len(mkt_arr) == 0:
                    continue
                for code in sel['code']:
                    r = t_return(code, date, db, h)
                    if r is None:
                        continue
                    pct = float((mkt_arr < r).mean())
                    results[(top, h)].append(pct)
        if (di + 1) % 10 == 0:
            log(f"  {di+1}/{len(dates)} " + " ".join(f"t{t}h{h}={np.mean(results[(t,h)]):.3f}"
                                                     for t in TOPS for h in HORIZONS) + f" [{time.time()-t0:.0f}s]")

    log("=" * 60)
    log("RESULT")
    log("=" * 60)
    log(f"{'top':>4} {'hor':>4} {'pct':>8} n")
    for top in TOPS:
        for h in HORIZONS:
            pcts = results[(top, h)]
            log(f"{top:>4} {h:>4} {np.mean(pcts):.4f} {len(pcts)}")
    log("(对比: v5=0.51, 动量3月=0.625/2.5年=0.40, 目标>0.70)")
    out = {f'top{top}_h{h}': round(float(np.mean(results[(top, h)])), 4) for top in TOPS for h in HORIZONS}
    json.dump(out, open(OUT, 'w'), indent=2, ensure_ascii=False)
    log(f"written: {OUT}")
    db.close()


if __name__ == '__main__':
    main()
