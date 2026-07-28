#!/home/soso/v5/.venv/bin/python3
"""B: 38因子切片超额概率, 分批(每次1个pkl)
每因子: Top10 T+20, 超额vs全市场, 月切片概率 + t值
断点续传: 已算因子跳过
"""
import sys, os, sqlite3, time, json
from datetime import datetime
from collections import defaultdict
import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
PKL_DIR = os.path.expanduser('~/ading/cache/t3a_factors')
TEST_START = '2024-01-01'
TEST_END = '2026-06-30'
HORIZON = 20
TOP = 10
OUT = os.path.expanduser('~/v5/branches/factor_persistence/factor_pers_B_result.json')
DONE_FILE = os.path.expanduser('~/v5/branches/factor_persistence/factor_pers_B_done.json')


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def newey_west_t(returns, max_lag=None):
    n = len(returns)
    if n < 10: return 0, 1.0, n
    if max_lag is None: max_lag = max(min(int(4 * (n / 100) ** (2 / 9)), n // 4), HORIZON - 1)  # #7 NW: max(自动, 持有期-1=19)
    mean = np.mean(returns)
    gamma0 = np.var(returns, ddof=0)
    nw_var = gamma0
    for k in range(1, max_lag + 1):
        if n - k > 0:
            nw_var += 2 * np.mean((returns[:-k] - mean) * (returns[k:] - mean))
    nw_se = np.sqrt(nw_var / n) if nw_var > 0 else 0
    if nw_se == 0: return 0, 1.0, n
    t_nw = mean / nw_se
    p_val = 2 * (1 - scipy_stats.t.cdf(abs(t_nw), df=max(1, n // 4)))
    return float(t_nw), float(p_val)


def main():
    log("=" * 60)
    log("B: 38因子切片超额概率 (分批)")
    log("=" * 60)
    db = sqlite3.connect(DB)

    # 测试期日期
    dates = [str(r[0])[:10] for r in db.execute(
        "SELECT DISTINCT date FROM daily_kline WHERE date>=? AND date<=? ORDER BY date",
        (TEST_START, TEST_END)).fetchall()]
    log(f"test {len(dates)} days")

    # 全市场等权T+20收益(预算一次)
    log("precomputing mkt avg...")
    codes = [r[0] for r in db.execute(
        "SELECT s.symbol FROM stock_info s WHERE s.class='stock' AND s.name NOT LIKE '%ST%' "
        "AND s.symbol NOT LIKE 'bj%'").fetchall()]
    mkt_avgs = {}
    for di, date in enumerate(dates):
        rets = []
        for code in codes:
            rows = db.execute("SELECT close FROM daily_kline WHERE code=? AND date > ? AND close>0 ORDER BY date LIMIT ?", (code, date + ' 23:59:59', HORIZON)).fetchall()
            buy = db.execute("SELECT close FROM daily_kline WHERE code=? AND date LIKE ?", (code, date + '%')).fetchone()
            if buy and buy[0] > 0 and len(rows) >= HORIZON:
                rets.append(rows[-1][0] / buy[0] - 1)
        mkt_avgs[date] = float(np.mean(rets)) if rets else 0
        if (di + 1) % 100 == 0:
            log(f"  mkt {di+1}/{len(dates)}")
    log(f"mkt precomputed: {len(mkt_avgs)} days")

    # 断点续传
    done = {}
    if os.path.exists(DONE_FILE):
        done = json.load(open(DONE_FILE))

    # 38因子pkl
    pkls = sorted(f for f in os.listdir(PKL_DIR) if f.endswith('.pkl'))
    log(f"{len(pkls)} factor pkls, done {len(done)}")

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
            continue

        strat_rets = []
        dates_used = []
        for date in dates:
            if date not in fdf.index:
                continue
            day_vals = fdf.loc[date].dropna()
            if len(day_vals) < TOP:
                continue
            top10 = day_vals.nlargest(TOP).index  # 因子值最高Top10
            # 算top10的T+20收益
            rets = []
            for code in top10:
                rows = db.execute("SELECT close FROM daily_kline WHERE code=? AND date > ? AND close>0 ORDER BY date LIMIT ?", (code, date + ' 23:59:59', HORIZON)).fetchall()
                buy = db.execute("SELECT close FROM daily_kline WHERE code=? AND date LIKE ?", (code, date + '%')).fetchone()
                if buy and buy[0] > 0 and len(rows) >= HORIZON:
                    rets.append(rows[-1][0] / buy[0] - 1)
            if rets:
                strat_rets.append(float(np.mean(rets)))
                dates_used.append(date)

        if len(strat_rets) < 30:
            done[aid] = {'error': 'too few days'}
            continue

        excess = np.array(strat_rets) - np.array([mkt_avgs.get(d, 0) for d in dates_used])
        month_excess = defaultdict(list)
        for i, date in enumerate(dates_used):
            month_excess[date[:7]].append(excess[i])
        month_avg = {m: float(np.mean(rets)) for m, rets in month_excess.items()}
        positive = sum(1 for v in month_avg.values() if v > 0)
        total = len(month_avg)
        prob = positive / total if total > 0 else 0

        t_abs, p_abs = newey_west_t(np.array(strat_rets))
        t_exc, p_exc = newey_west_t(excess)
        has = t_abs > 2

        done[aid] = {
            'prob': round(prob, 4), 't_abs': round(t_abs, 4),
            't_exc': round(t_exc, 4), 'has': has,
            'n_days': len(strat_rets), 'n_months': total,
        }
        log(f"    prob={prob:.1%} t_abs={t_abs:+.2f} t_exc={t_exc:+.2f} has={has}")

        # 每个因子后保存
        json.dump(done, open(DONE_FILE, 'w'), indent=2, ensure_ascii=False)

        del fdf

        if (pi + 1) % 5 == 0:
            log(f"  {pi+1}/{len(pkls)} done, elapsed {time.time()-t0:.0f}s")

    # 汇总
    log("=" * 60)
    log("B RESULT (38因子)")
    log("=" * 60)
    has_potential = {k: v for k, v in done.items() if isinstance(v, dict) and v.get('has')}
    log(f"有苗头(t>2): {len(has_potential)}/{len(done)}")
    for aid, r in sorted(has_potential.items(), key=lambda x: -x[1]['t_abs']):
        log(f"  {aid}: t_abs={r['t_abs']} prob={r['prob']} t_exc={r['t_exc']}")

    log(f"\n全部(按t_abs排序 top 10):")
    sorted_all = sorted([(k, v) for k, v in done.items() if isinstance(v, dict) and 't_abs' in v], key=lambda x: -x[1]['t_abs'])[:10]
    for aid, r in sorted_all:
        log(f"  {aid}: t_abs={r['t_abs']} prob={r['prob']} t_exc={r['t_exc']} has={r.get('has')}")

    json.dump(done, open(OUT, 'w'), indent=2, ensure_ascii=False)
    log(f"written: {OUT}")
    db.close()


if __name__ == '__main__':
    import pandas as pd
    main()
