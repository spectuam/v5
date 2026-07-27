#!/home/soso/v5/.venv/bin/python3
"""扩展测试期: RZ_buy_ratio 最低 Top10, T+5, 全段2023-2026+分年
确认3个月0.514是否稳定。
"""
import sys, os, sqlite3, time, json
from datetime import datetime
import numpy as np
import pandas as pd

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
TEST_START = '2023-01-01'
TEST_END = '2026-07-17'
TOP = 10
HORIZON = 5
OUT = os.path.expanduser('~/v5/margin_factor/margin_backtest_extended_result.json')


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
    log(f"扩展: RZ_buy_ratio 最低 Top{TOP} T+{HORIZON} {TEST_START}~{TEST_END}")
    log("=" * 60)
    db = sqlite3.connect(DB)
    md = pd.read_sql("""SELECT m.code, m.date, m.rz_ye, m.rz_buy FROM margin_detail m
        JOIN stock_info s ON m.code = s.symbol
        WHERE s.class='stock' AND m.rz_buy > 0""", db)
    md['date'] = md['date'].str[:10]
    md['RZ_buy_ratio'] = md['rz_buy'] / md['rz_ye']
    dates = sorted(md[(md.date >= TEST_START) & (md.date <= TEST_END)]['date'].unique())
    all_codes = [r[0] for r in db.execute(
        "SELECT s.symbol FROM stock_info s WHERE s.class='stock' AND s.name NOT LIKE '%ST%' "
        "AND s.symbol NOT LIKE 'bj%'").fetchall()]
    log(f"test {len(dates)} days, {len(all_codes)} stocks")

    by_year = {}
    all_pcts = []
    t0 = time.time()
    for di, date in enumerate(dates):
        day_md = md[md.date == date].sort_values('RZ_buy_ratio')
        mkt_rets = []
        for code in all_codes:
            r = t_return(code, date, db, HORIZON)
            if r is not None:
                mkt_rets.append(r)
        sel = day_md.head(TOP)
        mkt_arr = np.array(mkt_rets)
        for code in sel['code']:
            r = t_return(code, date, db, HORIZON)
            if r is None:
                continue
            pct = float((mkt_arr < r).mean())
            all_pcts.append(pct)
            by_year.setdefault(date[:4], []).append(pct)
        if (di + 1) % 100 == 0:
            log(f"  {di+1}/{len(dates)} overall={np.mean(all_pcts):.4f} [{time.time()-t0:.0f}s]")

    log("=" * 60)
    log("RESULT")
    log("=" * 60)
    log(f"overall: {np.mean(all_pcts):.4f} (3月=0.514, 动量全段=0.40, 目标0.70) n={len(all_pcts)}")
    log("分年:")
    for y in sorted(by_year):
        log(f"  {y}: {np.mean(by_year[y]):.4f} n={len(by_year[y])}")
    out = {'overall': round(float(np.mean(all_pcts)), 4),
           'by_year': {y: round(float(np.mean(by_year[y])), 4) for y in sorted(by_year)}}
    json.dump(out, open(OUT, 'w'), indent=2, ensure_ascii=False)
    log(f"written: {OUT}")
    db.close()


if __name__ == '__main__':
    main()
