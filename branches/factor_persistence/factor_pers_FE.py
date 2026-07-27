#!/home/soso/v5/.venv/bin/python3
"""F+E: 低波多Top/horizon + 组合, 月切片概率 + t值
F: lowvol Top5/10/20/50 x T+5/10/20 (12组)
E: lowvol+reversal combo Top10 T+10/20 (2组)
"""
import sys, os, sqlite3, time, json
from datetime import datetime
from collections import defaultdict
import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
TEST_START = '2024-01-01'
TEST_END = '2026-06-30'
OUT = os.path.expanduser('~/v5/branches/factor_persistence/factor_pers_FE_result.json')


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def vol_20(code, date, db):
    rows = db.execute("SELECT close FROM daily_kline WHERE code=? AND date < ? AND close>0 ORDER BY date DESC LIMIT 21", (code, date + ' 23:59:59')).fetchall()
    if len(rows) < 21: return None
    closes = [r[0] for r in rows]
    rets = np.diff(closes) / closes[:-1]
    return float(np.std(rets))


def cum_ret_20(code, date, db):
    rows = db.execute("SELECT close FROM daily_kline WHERE code=? AND date < ? AND close>0 ORDER BY date DESC LIMIT 21", (code, date + ' 23:59:59')).fetchall()
    if len(rows) < 21: return None
    rows = rows[::-1]
    return rows[-1][0] / rows[0][0] - 1


def t_return(code, date, db, H):
    rows = db.execute("SELECT close FROM daily_kline WHERE code=? AND date > ? AND close>0 ORDER BY date LIMIT ?", (code, date + ' 23:59:59', H)).fetchall()
    buy = db.execute("SELECT close FROM daily_kline WHERE code=? AND date LIKE ?", (code, date + '%')).fetchone()
    if not buy or buy[0] <= 0 or len(rows) < H: return None
    return rows[-1][0] / buy[0] - 1


def newey_west_t(returns, max_lag=None):
    n = len(returns)
    if n < 10: return 0, 1.0, n
    if max_lag is None: max_lag = min(int(4 * (n / 100) ** (2 / 9)), n // 4)
    mean = np.mean(returns)
    gamma0 = np.var(returns, ddof=0)
    nw_var = gamma0
    for k in range(1, max_lag + 1):
        if n - k > 0:
            nw_var += 2 * np.mean((returns[:-k] - mean) * (returns[k:] - mean))
    nw_se = np.sqrt(nw_var / n) if nw_var > 0 else 0
    if nw_se == 0: return 0, 1.0, n
    t_nw = mean / nw_se
    autocorr_sum = 0
    for k in range(1, max_lag + 1):
        if n - k > 0 and gamma0 > 0:
            autocorr_sum += np.mean((returns[:-k] - mean) * (returns[k:] - mean)) / gamma0
    n_eff = n / (1 + 2 * autocorr_sum) if (1 + 2 * autocorr_sum) > 0 else n
    p_val = 2 * (1 - scipy_stats.t.cdf(abs(t_nw), df=max(1, int(n_eff) - 1)))
    return float(t_nw), float(p_val), float(n_eff)


def main():
    log("=" * 60)
    log("F+E: 低波多Top/horizon + 组合")
    log("=" * 60)
    db = sqlite3.connect(DB)
    dates = [str(r[0])[:10] for r in db.execute(
        "SELECT DISTINCT date FROM daily_kline WHERE date>=? AND date<=? ORDER BY date",
        (TEST_START, TEST_END)).fetchall()]
    codes = [r[0] for r in db.execute(
        "SELECT s.symbol FROM stock_info s WHERE s.class='stock' AND s.name NOT LIKE '%ST%' "
        "AND s.symbol NOT LIKE 'bj%'").fetchall()]
    log(f"test {len(dates)} days, {len(codes)} stocks")

    # configs: (label, top, horizon, mode)
    configs = []
    for top in [5, 10, 20, 50]:
        for hor in [5, 10, 20]:
            configs.append((f'lv_T{top}_h{hor}', top, hor, 'lowvol'))
    configs.append(('combo_lv+rev_T10_h10', 10, 10, 'combo'))
    configs.append(('combo_lv+rev_T10_h20', 10, 20, 'combo'))

    results = {c[0]: {'strat': [], 'mkt': [], 'date': []} for c in configs}
    t0 = time.time()
    for di, date in enumerate(dates):
        rows = []
        mkt_rets = []
        for code in codes:
            v = vol_20(code, date, db)
            cr = cum_ret_20(code, date, db)
            r5 = t_return(code, date, db, 5)
            r10 = t_return(code, date, db, 10)
            r20 = t_return(code, date, db, 20)
            if v is None or cr is None: continue
            rows.append({'vol': v, 'cr': cr, 'code': code, 'r5': r5, 'r10': r10, 'r20': r20})
            if r10 is not None: mkt_rets.append(r10)
        if len(rows) < 50: continue
        mkt_avg = float(np.mean(mkt_rets)) if mkt_rets else 0

        df = pd.DataFrame(rows)
        for label, top, hor, mode in configs:
            rets_field = {5: 'r5', 10: 'r10', 20: 'r20'}[hor]
            if mode == 'lowvol':
                sel = df.sort_values('vol').head(top)
            else:  # combo
                df['r_vol'] = 1 - df['vol'].rank(pct=True)
                df['r_rev'] = 1 - df['cr'].rank(pct=True)
                df['combo'] = df['r_vol'] + df['r_rev']
                sel = df.sort_values('combo', ascending=False).head(top)
            rets = sel[rets_field].dropna().tolist()
            if rets:
                avg = float(np.mean(rets))
                results[label]['strat'].append(avg)
                results[label]['mkt'].append(mkt_avg)
                results[label]['date'].append(date)

        if (di + 1) % 100 == 0:
            log(f"  {di+1}/{len(dates)} [{time.time()-t0:.0f}s]")

    log("=" * 60)
    log("RESULT (F+E)")
    log("=" * 60)
    out = {}
    log(f"\n{'config':<24} {'月概率':>7} {'t绝对':>7} {'t超额':>7} {'苗头':>5}")
    for label, _, _, _ in configs:
        strat = np.array(results[label]['strat'])
        if len(strat) < 10: continue
        mkt = np.array(results[label]['mkt'])
        dates_f = results[label]['date']
        excess = strat - mkt

        month_excess = defaultdict(list)
        for i, date in enumerate(dates_f):
            month_excess[date[:7]].append(excess[i])
        month_avg = {m: float(np.mean(rets)) for m, rets in month_excess.items()}
        positive = sum(1 for v in month_avg.values() if v > 0)
        total = len(month_avg)
        prob = positive / total if total > 0 else 0

        t_abs, p_abs, _ = newey_west_t(strat)
        t_exc, p_exc, _ = newey_west_t(excess)
        has = t_abs > 2  # 新标准: t>2 = 不是运气

        out[label] = {'prob': round(prob, 4), 't_abs': round(t_abs, 4), 't_exc': round(t_exc, 4), 'has': has}
        log(f"{label:<24} {prob:>7.1%} {t_abs:>+7.2f} {t_exc:>+7.2f} {'是' if has else '否':>5}")

    log(f"\n(新标准: t绝对>2=不是运气=有苗头, 不要求概率>50%)")
    json.dump(out, open(OUT, 'w'), indent=2, ensure_ascii=False)
    log(f"written: {OUT}")
    db.close()


if __name__ == '__main__':
    main()
