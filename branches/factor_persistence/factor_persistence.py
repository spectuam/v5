#!/home/soso/v5/.venv/bin/python3
"""factor_persistence: 因子切片超额概率统计
4因子(低波/反转/动量/融资融券) Top10 T+20, 月切片超额概率 + 全段t值(Newey-West)
找"有has_potential"(概率>50% + t>2 + 高收益低稳定)
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
OUT = os.path.expanduser('~/v5/branches/factor_persistence/factor_persistence_result.json')


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
    autocorr_sum = 0
    for k in range(1, max_lag + 1):
        if n - k > 0 and gamma0 > 0:
            autocorr_sum += np.mean((returns[:-k] - mean) * (returns[k:] - mean)) / gamma0
    n_eff = n / (1 + 2 * autocorr_sum) if (1 + 2 * autocorr_sum) > 0 else n
    p_val = 2 * (1 - scipy_stats.t.cdf(abs(t_nw), df=max(1, int(n_eff) - 1)))
    return float(t_nw), float(p_val), float(n_eff)


def main():
    log("=" * 60)
    log("factor_persistence: 4因子切片超额概率")
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
        'lowvol': {'func': vol_20, 'sort': 'asc', 'source': 'daily_kline'},
        'reversal': {'func': cum_ret_20, 'sort': 'asc', 'source': 'daily_kline'},
        'momentum': {'func': cum_ret_20, 'sort': 'desc', 'source': 'daily_kline'},
        'rz_buy_ratio': {'func': rz_buy_ratio, 'sort': 'asc', 'source': 'margin_detail'},
    }

    # 每因子: 每天策略收益 + 全市场收益
    factor_daily = {f: {'strategy': [], 'mkt': [], 'date': []} for f in factors}
    t0 = time.time()
    for di, date in enumerate(dates):
        # 全市场收益
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
    log("RESULT")
    log("=" * 60)
    out = {}
    for fname in factors:
        strat = np.array(factor_daily[fname]['strategy'])
        mkt = np.array(factor_daily[fname]['mkt'])
        dates_f = factor_daily[fname]['date']
        excess = strat - mkt

        # 月切片
        month_excess = defaultdict(list)
        for i, date in enumerate(dates_f):
            month_excess[date[:7]].append(excess[i])

        month_avg = {}
        positive_months = 0
        for m, rets in sorted(month_excess.items()):
            month_avg[m] = float(np.mean(rets))
            if month_avg[m] > 0: positive_months += 1
        total_months = len(month_excess)
        prob = positive_months / total_months if total_months > 0 else 0

        # 全段t值
        t_abs, p_abs, n_eff_abs = newey_west_t(strat)
        t_exc, p_exc, n_eff_exc = newey_west_t(excess)

        result = {
            'n_days': len(strat),
            'n_months': total_months,
            'positive_month_prob': round(prob, 4),
            'positive_months': positive_months,
            'month_avg_excess_mean': round(float(np.mean(list(month_avg.values()))), 6),
            'month_avg_excess_std': round(float(np.std(list(month_avg.values()))), 6),
            't_absolute': round(t_abs, 4),
            'p_absolute': round(p_abs, 6),
            'n_eff_absolute': round(n_eff_abs, 1),
            't_excess': round(t_exc, 4),
            'p_excess': round(p_exc, 6),
            'n_eff_excess': round(n_eff_exc, 1),
        }
        out[fname] = result
        log(f"\n{fname}:")
        log(f"  月正超额概率: {prob:.1%} ({positive_months}/{total_months}月)")
        log(f"  月均超额: {np.mean(list(month_avg.values())):+.5f}")
        log(f"  月超额波动: {np.std(list(month_avg.values())):.5f}")
        log(f"  t绝对: {t_abs:+.2f} (p={p_abs:.4f}, N_eff={n_eff_abs:.0f})")
        log(f"  t超额: {t_exc:+.2f} (p={p_exc:.4f}, N_eff={n_eff_exc:.0f})")
        has_potential = prob > 0.5 and t_abs > 2
        log(f"  有has_potential: {'是' if has_potential else '否'} (概率>50% + t绝对>2)")

    log(f"\n=== 汇总 ===")
    log(f"{'因子':<16} {'月概率':>7} {'t绝对':>7} {'t超额':>7} {'has_potential':>5}")
    for fname in factors:
        r = out[fname]
        has_potential = r['positive_month_prob'] > 0.5 and r['t_absolute'] > 2
        log(f"{fname:<16} {r['positive_month_prob']:>7.1%} {r['t_absolute']:>+7.2f} {r['t_excess']:>+7.2f} {'是' if has_potential else '否':>5}")

    json.dump(out, open(OUT, 'w'), indent=2, ensure_ascii=False)
    log(f"\nwritten: {OUT}")
    db.close()


if __name__ == '__main__':
    main()
