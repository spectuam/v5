#!/home/soso/v5/.venv/bin/python3
"""第3步多因子组合: RZ_buy_ratio + RZ_chg_20d + RZ_RQ_ratio rank合成
方向统一: RZ_buy/chg选低(IC负), RZ_RQ选高(IC正). 选Top10/50, T+5, 3月。
"""
import sys, os, sqlite3, time, json
from datetime import datetime
import numpy as np
import pandas as pd

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
TEST_START = '2026-04-01'
TEST_END = '2026-07-14'
TOPS = [10, 50]
HORIZON = 5
OUT = os.path.expanduser('~/v5/margin_factor/margin_backtest_combo_result.json')


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
    log(f"第3步: 多因子组合 Top{TOPS} T+{HORIZON} {TEST_START}~{TEST_END}")
    log("=" * 60)
    db = sqlite3.connect(DB)
    md = pd.read_sql("""SELECT m.code, m.date, m.rz_ye, m.rz_buy, m.rq_yl, m.rq_sell FROM margin_detail m
        JOIN stock_info s ON m.code = s.symbol
        WHERE s.class='stock' AND m.rz_buy > 0""", db)
    md['date'] = md['date'].str[:10]
    md = md.sort_values(['code', 'date'])
    md['RZ_buy_ratio'] = md['rz_buy'] / md['rz_ye']
    md['RZ_chg_20d'] = md.groupby('code')['rz_ye'].pct_change(20)
    # RZ_RQ_ratio = 融资余额/融券余额(融券余量×close)
    dk = pd.read_sql("SELECT code, date, close FROM daily_kline WHERE close>0", db)
    dk['date'] = dk['date'].str[:10]
    md = md.merge(dk, on=['code', 'date'], how='left')
    md['rq_ye'] = md['rq_yl'] * md['close']
    md['RZ_RQ_ratio'] = md['rz_ye'] / md['rq_ye']
    log(f"  {len(md)} rows")

    dates = sorted(md[(md.date >= TEST_START) & (md.date <= TEST_END)]['date'].unique())
    all_codes = [r[0] for r in db.execute(
        "SELECT s.symbol FROM stock_info s WHERE s.class='stock' AND s.name NOT LIKE '%ST%' "
        "AND s.symbol NOT LIKE 'bj%'").fetchall()]
    log(f"test {len(dates)} days, {len(all_codes)} stocks")

    results = {t: [] for t in TOPS}
    t0 = time.time()
    for di, date in enumerate(dates):
        day_md = md[md.date == date].dropna(subset=['RZ_buy_ratio', 'RZ_chg_20d', 'RZ_RQ_ratio']).copy()
        if len(day_md) < max(TOPS):
            continue
        # rank 方向统一: RZ_buy/chg IC负选低 -> 1-rank; RZ_RQ IC正选高 -> rank
        day_md['r_buy'] = 1 - day_md['RZ_buy_ratio'].rank(pct=True)
        day_md['r_chg'] = 1 - day_md['RZ_chg_20d'].rank(pct=True)
        day_md['r_rq'] = day_md['RZ_RQ_ratio'].rank(pct=True)
        day_md['combo'] = day_md['r_buy'] + day_md['r_chg'] + day_md['r_rq']
        day_md = day_md.sort_values('combo', ascending=False)  # combo 高在前

        mkt_rets = []
        for code in all_codes:
            r = t_return(code, date, db, HORIZON)
            if r is not None:
                mkt_rets.append(r)
        mkt_arr = np.array(mkt_rets)
        for top in TOPS:
            sel = day_md.head(top)
            for code in sel['code']:
                r = t_return(code, date, db, HORIZON)
                if r is None:
                    continue
                results[top].append(float((mkt_arr < r).mean()))
        if (di + 1) % 20 == 0:
            log(f"  {di+1}/{len(dates)} " + " ".join(f"t{t}={np.mean(results[t]):.3f}" for t in TOPS) + f" [{time.time()-t0:.0f}s]")

    log("=" * 60)
    log("RESULT")
    log("=" * 60)
    log(f"{'top':>5} {'pct':>8} n")
    for t in TOPS:
        log(f"{t:>5} {np.mean(results[t]):.4f} {len(results[t])}")
    log("(对比: 单因子Top10=0.514/Top50=0.531, v5=0.51, 动量3月=0.625, 目标0.70)")
    out = {f'top{t}': round(float(np.mean(results[t])), 4) for t in TOPS}
    json.dump(out, open(OUT, 'w'), indent=2, ensure_ascii=False)
    log(f"written: {OUT}")
    db.close()


if __name__ == '__main__':
    main()
