#!/home/soso/v5/.venv/bin/python3
"""融资融券×OHLCV组合: RZ_buy_ratio(低,IC负) + cum_ret_20(低,IC负) rank合成
选高分Top, T+5收益分位, 对比单因子。
"""
import sys, os, sqlite3, time, json
from datetime import datetime
import numpy as np
import pandas as pd

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
TEST_START = '2025-01-01'
TEST_END = '2026-07-17'
TOPS = [10, 50]
HORIZON = 5
OUT = os.path.expanduser('~/v5/margin_factor/margin_combo_ohlcv_result.json')


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
    log("融资融券×OHLCV组合")
    log("=" * 60)
    db = sqlite3.connect(DB)
    md = pd.read_sql("""SELECT m.code, m.date, m.rz_ye, m.rz_buy FROM margin_detail m
        JOIN stock_info s ON m.code = s.symbol WHERE s.class='stock' AND m.rz_buy>0""", db)
    md['date'] = md['date'].str[:10]
    md['RZ_buy_ratio'] = md['rz_buy'] / md['rz_ye']
    dk = pd.read_sql("SELECT code, date, close FROM daily_kline WHERE close>0", db)
    dk['date'] = dk['date'].str[:10]
    dk = dk.sort_values(['code', 'date'])
    dk['cum_ret_20'] = dk.groupby('code')['close'].pct_change(20)
    md = md.merge(dk[['code', 'date', 'cum_ret_20']], on=['code', 'date'], how='left')
    md = md.dropna(subset=['RZ_buy_ratio', 'cum_ret_20'])
    dates = sorted(md[(md.date >= TEST_START) & (md.date <= TEST_END)]['date'].unique())
    all_codes = [r[0] for r in db.execute(
        "SELECT s.symbol FROM stock_info s WHERE s.class='stock' AND s.name NOT LIKE '%ST%' "
        "AND s.symbol NOT LIKE 'bj%'").fetchall()]
    log(f"test {len(dates)} days, {len(all_codes)} stocks")

    results = {t: [] for t in TOPS}
    t0 = time.time()
    for di, date in enumerate(dates):
        day = md[md.date == date].copy()
        day['r_buy'] = 1 - day['RZ_buy_ratio'].rank(pct=True)
        day['r_cum'] = 1 - day['cum_ret_20'].rank(pct=True)
        day['combo'] = day['r_buy'] + day['r_cum']
        day = day.sort_values('combo', ascending=False)
        mkt_rets = []
        for code in all_codes:
            r = t_return(code, date, db, HORIZON)
            if r is not None:
                mkt_rets.append(r)
        mkt_arr = np.array(mkt_rets)
        for top in TOPS:
            sel = day.head(top)
            for code in sel['code']:
                r = t_return(code, date, db, HORIZON)
                if r is None:
                    continue
                results[top].append(float((mkt_arr < r).mean()))
        if (di + 1) % 50 == 0:
            log(f"  {di+1}/{len(dates)} " + " ".join(f"t{t}={np.mean(results[t]):.3f}" for t in TOPS) + f" [{time.time()-t0:.0f}s]")

    log("=" * 60)
    log("RESULT")
    log("=" * 60)
    for t in TOPS:
        log(f"Top{t}: {np.mean(results[t]):.4f} n={len(results[t])}")
    log("(对比: 单因子RZ_buy=0.51, 目标0.70)")
    out = {f'top{t}': round(float(np.mean(results[t])), 4) for t in TOPS}
    json.dump(out, open(OUT, 'w'), indent=2, ensure_ascii=False)
    log(f"written: {OUT}")
    db.close()


if __name__ == '__main__':
    main()
