#!/home/soso/v5/.venv/bin/python3
"""factor_persistence 周切片: 4因子周超额概率 + t值
月30段少统计不稳, 周~120段更稳. 看低波概率是否>50%.
"""
import sys, os, sqlite3, time, json
from datetime import datetime
from collections import defaultdict
import numpy as np
from scipy import stats as scipy_stats

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
TEST_START = '2024-01-01'
TEST_END = '2026-06-30'
HORIZON = 20
OUT = os.path.expanduser('~/v5/branches/factor_persistence/factor_persistence_week_result.json')


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


def rz_buy_ratio(code, date, db):
    row = db.execute("SELECT rz_ye, rz_buy FROM margin_detail WHERE code=? AND date=?", (code, date)).fetchone()
    if not row or row[0] <= 0: return None
    return row[1] / row[0]


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


def week_key(date_str):
    dt = datetime.strptime(date_str, '%Y-%m-%d')
    iso = dt.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def main():
    log("=" * 60)
    log("factor_persistence 周切片: 4因子")
    log("=" * 60)
    db = sqlite3.connect(DB)
    dates = [str(r[0])[:10] for r in db.execute(
        "SELECT DISTINCT date FROM daily_kline WHERE date>=? AND date<=? ORDER BY date",
        (TEST_START, TEST_END)).fetchall()]
    codes = [r[0] for r in db.execute(
        "SELECT s.symbol FROM stock_info s WHERE s.class='stock' AND s.name NOT LIKE '%ST%' "
        "AND s.symbol NOT LIKE 'bj%'").fetchall()]
    log(f"test {len(dates)} days, {len(codes)} stocks")

    factors = {
        'lowvol': {'func': vol_20, 'sort': 'asc'},
        'reversal': {'func': cum_ret_20, 'sort': 'asc'},
        'momentum': {'func': cum_ret_20, 'sort': 'desc'},
        'rz_buy_ratio': {'func': rz_buy_ratio, 'sort': 'asc'},
    }

    factor_daily = {f: {'strategy': [], 'mkt': [], 'date': []} for f in factors}
    t0 = time.time()
    for di, date in enumerate(dates):
        all_rets = []
        scored_by_factor = {f: [] for f in factors}
        for code in codes:
            r = t_return(code, date, db, HORIZON)
            if r is None: continue
            all_rets.append(r)
            for fname, fcfg in factors.items():
                v = fcfg['func'](code, date, db)
                if v is not None:
                    scored_by_factor[fname].append((v, r))
        if len(all_rets) < 10: continue
        mkt_avg = float(np.mean(all_rets))
        for fname, fcfg in factors.items():
            scored = scored_by_factor[fname]
            if len(scored) < 10: continue
            scored.sort(key=lambda x: x[0], reverse=(fcfg['sort'] == 'desc'))
            top10_avg = float(np.mean([s[1] for s in scored[:10]]))
            factor_daily[fname]['strategy'].append(top10_avg)
            factor_daily[fname]['mkt'].append(mkt_avg)
            factor_daily[fname]['date'].append(date)
        if (di + 1) % 100 == 0:
            log(f"  {di+1}/{len(dates)} [{time.time()-t0:.0f}s]")

    log("=" * 60)
    log("RESULT (周切片)")
    log("=" * 60)
    out = {}
    log(f"\n{'因子':<16} {'周概率':>7} {'t绝对':>7} {'t超额':>7} {'苗头':>5}")
    for fname in factors:
        strat = np.array(factor_daily[fname]['strategy'])
        mkt = np.array(factor_daily[fname]['mkt'])
        dates_f = factor_daily[fname]['date']
        excess = strat - mkt

        week_excess = defaultdict(list)
        for i, date in enumerate(dates_f):
            week_excess[week_key(date)].append(excess[i])

        week_avg = {w: float(np.mean(rets)) for w, rets in week_excess.items()}
        positive = sum(1 for v in week_avg.values() if v > 0)
        total = len(week_avg)
        prob = positive / total if total > 0 else 0

        t_abs, p_abs, n_eff_abs = newey_west_t(strat)
        t_exc, p_exc, n_eff_exc = newey_west_t(excess)
        has_potential = prob > 0.5 and t_abs > 2

        out[fname] = {
            'n_weeks': total, 'positive_prob': round(prob, 4),
            't_absolute': round(t_abs, 4), 't_excess': round(t_exc, 4),
            'has_potential': has_potential,
            'week_avg_excess_mean': round(float(np.mean(list(week_avg.values()))), 6),
        }
        log(f"{fname:<16} {prob:>7.1%} {t_abs:>+7.2f} {t_exc:>+7.2f} {'是' if has_potential else '否':>5}")

    log(f"\n(对比月切片: 低波50%+2.84, 融资融券53%+1.71)")
    json.dump(out, open(OUT, 'w'), indent=2, ensure_ascii=False)
    log(f"written: {OUT}")
    db.close()


if __name__ == '__main__':
    main()
