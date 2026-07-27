#!/home/soso/v5/.venv/bin/python3
"""factor_map_38: 38因子切片最优+收益+分位, 分批pkl, 存CSV+sqlite
每切片每因子: avg收益 + avg全市场分位 + rank
存 factor_map 表(追加) + factor_map_38.csv
断点续传
"""
import sys, os, sqlite3, time, json, csv, gc
from datetime import datetime
from collections import defaultdict
import numpy as np
import pandas as pd

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
PKL_DIR = os.path.expanduser('~/ading/cache/t3a_factors')
TEST_START = '2024-01-01'
TEST_END = '2026-06-30'
HORIZON = 20
TOP = 10
CSV_OUT = os.path.expanduser('~/v5/branches/factor_persistence/factor_map_38.csv')
DONE_FILE = os.path.expanduser('~/v5/branches/factor_persistence/factor_map_38_done.json')


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def period_key(date_str, gran):
    y, m = int(date_str[:4]), int(date_str[5:7])
    if gran == 'week':
        dt = datetime(int(date_str[:4]), int(date_str[5:7]), int(date_str[8:10]))
        iso = dt.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    if gran == 'month': return f"{y}-{m:02d}"
    if gran == 'quarter': return f"{y}-Q{(m-1)//3+1}"
    if gran == 'half': return f"{y}-H{'1' if m<=6 else '2'}"
    if gran == 'year': return str(y)


def main():
    log("=" * 60)
    log("factor_map_38: 38因子切片最优+收益+分位")
    log("=" * 60)
    db = sqlite3.connect(DB)

    dates = [str(r[0])[:10] for r in db.execute(
        "SELECT DISTINCT date FROM daily_kline WHERE date>=? AND date<=? ORDER BY date",
        (TEST_START, TEST_END)).fetchall()]
    codes = [r[0] for r in db.execute(
        "SELECT s.symbol FROM stock_info s WHERE s.class='stock' AND s.name NOT LIKE '%ST%' "
        "AND s.symbol NOT LIKE 'bj%'").fetchall()]
    log(f"test {len(dates)} days, {len(codes)} stocks")

    # 预算全市场等权T+20收益 + 全市场T+20收益分布(算分位)
    log("precomputing mkt distribution...")
    mkt_avgs = {}
    mkt_dists = {}  # {date: [all rets]} for percentile
    t0 = time.time()
    for di, date in enumerate(dates):
        rets = []
        for code in codes:
            rows = db.execute("SELECT close FROM daily_kline WHERE code=? AND date > ? AND close>0 ORDER BY date LIMIT ?",
                               (code, date + ' 23:59:59', HORIZON)).fetchall()
            buy = db.execute("SELECT close FROM daily_kline WHERE code=? AND date LIKE ?", (code, date + '%')).fetchone()
            if buy and buy[0] > 0 and len(rows) >= HORIZON:
                rets.append(rows[-1][0] / buy[0] - 1)
        mkt_avgs[date] = float(np.mean(rets)) if rets else 0
        mkt_dists[date] = np.array(rets) if rets else np.array([0])
        if (di + 1) % 100 == 0:
            log(f"  mkt {di+1}/{len(dates)} [{time.time()-t0:.0f}s]")
    log(f"mkt precomputed: {len(mkt_avgs)} days")

    granularities = ['week', 'month', 'quarter', 'half', 'year']

    # 断点续传
    done = {}
    if os.path.exists(DONE_FILE):
        done = json.load(open(DONE_FILE))

    pkls = sorted(f for f in os.listdir(PKL_DIR) if f.endswith('.pkl'))
    log(f"{len(pkls)} factor pkls, done {len(done)}")

    # CSV 追加模式
    csv_exists = os.path.exists(CSV_OUT)
    csv_f = open(CSV_OUT, 'a', newline='')
    csv_w = csv.writer(csv_f)
    if not csv_exists:
        csv_w.writerow(['granularity', 'period', 'factor', 'return', 'percentile', 'rank', 'is_best'])

    # sqlite 追加
    db.execute("DELETE FROM factor_map WHERE factor LIKE 'alpha%' OR factor LIKE 'gtja%' OR factor LIKE 'qlib%'")

    all_results = {}  # {factor: {gran: {period: {ret, pct}}}}
    t0 = time.time()
    for pi, pkl_fn in enumerate(pkls):
        parts = pkl_fn[:-4].split('_', 1)
        aid = parts[0] + '/' + parts[1]
        if aid in done:
            continue

        log(f"  [{pi+1}/{len(pkls)}] {aid}...")
        try:
            fdf = pd.read_pickle(os.path.join(PKL_DIR, pkl_fn))
        except Exception as e:
            log(f"    ERR: {e}")
            done[aid] = 'error'
            continue

        # 每天该因子Top10收益+分位
        daily_data = {}  # {date: (avg_ret, pct)}
        for date in dates:
            if date not in fdf.index:
                continue
            day_vals = fdf.loc[date].dropna()
            if len(day_vals) < TOP:
                continue
            top_codes = day_vals.nlargest(TOP).index
            rets = []
            for code in top_codes:
                rows = db.execute("SELECT close FROM daily_kline WHERE code=? AND date > ? AND close>0 ORDER BY date LIMIT ?",
                                   (code, date + ' 23:59:59', HORIZON)).fetchall()
                buy = db.execute("SELECT close FROM daily_kline WHERE code=? AND date LIKE ?", (code, date + '%')).fetchone()
                if buy and buy[0] > 0 and len(rows) >= HORIZON:
                    rets.append(rows[-1][0] / buy[0] - 1)
            if rets:
                avg_ret = float(np.mean(rets))
                mkt_arr = mkt_dists.get(date, np.array([0]))
                pct = float((mkt_arr < avg_ret).mean()) if len(mkt_arr) > 0 else 0.5
                daily_data[date] = (avg_ret, pct)

        if len(daily_data) < 30:
            done[aid] = 'too_few'
            del fdf
            continue

        # 切片汇总
        factor_gran = {}
        for gran in granularities:
            periods = defaultdict(list)
            for date, (ret, pct) in daily_data.items():
                periods[period_key(date, gran)].append((ret, pct))

            factor_gran[gran] = {}
            for pk in sorted(periods):
                vals = periods[pk]
                avg_ret = float(np.mean([v[0] for v in vals]))
                avg_pct = float(np.mean([v[1] for v in vals]))
                factor_gran[gran][pk] = {'ret': round(avg_ret, 5), 'pct': round(avg_pct, 4)}

        all_results[aid] = factor_gran
        done[aid] = 'done'
        del fdf
        gc.collect()

        # 每个因子后存
        json.dump(done, open(DONE_FILE, 'w'), indent=2, ensure_ascii=False)

        if (pi + 1) % 5 == 0:
            log(f"  {pi+1}/{len(pkls)} done [{time.time()-t0:.0f}s]")

    # 全部因子完成后，计算rank + 存表
    log("computing ranks + writing table...")
    rows_written = 0
    for gran in granularities:
        # 收集该gran所有period所有factor
        all_periods = set()
        for aid, factor_gran in all_results.items():
            if gran in factor_gran:
                all_periods.update(factor_gran[gran].keys())

        for pk in sorted(all_periods):
            fac_pcts = []
            for aid, factor_gran in all_results.items():
                if gran in factor_gran and pk in factor_gran[gran]:
                    fac_pcts.append((aid, factor_gran[gran][pk]))
            if not fac_pcts:
                continue
            fac_pcts.sort(key=lambda x: -x[1]['pct'])
            best = fac_pcts[0][0]
            for rank, (aid, fdata) in enumerate(fac_pcts, 1):
                csv_w.writerow([gran, pk, aid, fdata['ret'], fdata['pct'], rank, 1 if aid == best else 0])
                db.execute("INSERT INTO factor_map VALUES (?,?,?,?,?,?,?)",
                           (gran, pk, aid, fdata['ret'], fdata['pct'], rank, 1 if aid == best else 0))
                rows_written += 1

    db.commit()
    csv_f.close()
    json.dump(all_results, open(os.path.expanduser('~/v5/branches/factor_persistence/factor_map_38_result.json'), 'w'),
              indent=2, ensure_ascii=False, default=str)

    log("=" * 60)
    log(f"DONE: {len(all_results)} factors, {rows_written} rows written")
    log(f"CSV: {CSV_OUT}")
    log(f"sqlite: factor_map 表")

    # 示例
    log("\n=== 示例: month 2025-10 前5 ===")
    for r in db.execute("SELECT factor, return, percentile FROM factor_map WHERE granularity='month' AND period='2025-10' AND factor LIKE 'alpha%' OR factor LIKE 'gtja%' OR factor LIKE 'qlib%' ORDER BY rank LIMIT 5"):
        log(f"  {r[0]}: ret={r[1]:+.4f} pct={r[2]:.2f}")

    log("\n=== 示例: month 2026-04 前5 ===")
    for r in db.execute("SELECT factor, return, percentile FROM factor_map WHERE granularity='month' AND period='2026-04' AND (factor LIKE 'alpha%' OR factor LIKE 'gtja%' OR factor LIKE 'qlib%') ORDER BY rank LIMIT 5"):
        log(f"  {r[0]}: ret={r[1]:+.4f} pct={r[2]:.2f}")

    db.close()


if __name__ == '__main__':
    main()
