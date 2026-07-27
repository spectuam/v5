#!/home/soso/v5/.venv/bin/python3
"""t值测试: 低波Top10 T+20, 全市场等权+0两基准, Newey-West调整自相关
1. 低波Top10 T+20每日收益
2. 全市场等权基准(所有股票T+20平均)
3. 超额=策略-基准
4. t值(标准) + t值(Newey-West调整) + p值 + 年化收益
"""
import sys, os, sqlite3, time, json
from datetime import datetime
import numpy as np
from scipy import stats as scipy_stats

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
TEST_START = '2024-01-01'
TEST_END = '2026-06-30'
HORIZON = 20
OUT = os.path.expanduser('~/v5/branches/state_switch/t_value_result.json')


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def vol_20(code, date, db):
    rows = db.execute(
        "SELECT close FROM daily_kline WHERE code=? AND date < ? AND close>0 ORDER BY date DESC LIMIT 21",
        (code, date + ' 23:59:59')).fetchall()
    if len(rows) < 21:
        return None
    closes = [r[0] for r in rows]
    rets = np.diff(closes) / closes[:-1]
    return float(np.std(rets))


def t_return(code, date, db, H):
    rows = db.execute(
        "SELECT close FROM daily_kline WHERE code=? AND date > ? AND close>0 ORDER BY date LIMIT ?",
        (code, date + ' 23:59:59', H)).fetchall()
    buy = db.execute("SELECT close FROM daily_kline WHERE code=? AND date LIKE ?", (code, date + '%')).fetchone()
    if not buy or buy[0] <= 0 or len(rows) < H:
        return None
    return rows[-1][0] / buy[0] - 1


def newey_west_t(returns, max_lag=None):
    """Newey-West HAC 调整 t 值"""
    n = len(returns)
    if n < 10:
        return 0, 1.0
    if max_lag is None:
        max_lag = min(int(4 * (n / 100) ** (2 / 9)), n // 4)
    mean = np.mean(returns)
    gamma0 = np.var(returns, ddof=0)
    nw_var = gamma0
    for k in range(1, max_lag + 1):
        if n - k > 0:
            gamma_k = np.mean((returns[:-k] - mean) * (returns[k:] - mean))
            nw_var += 2 * gamma_k
    nw_se = np.sqrt(nw_var / n)
    if nw_se == 0:
        return 0, 1.0
    t_nw = mean / nw_se  # nw_se=sqrt(nw_var/n) 已含 1/sqrt(n)，不再乘 sqrt(n)
    # 有效样本数
    if gamma0 > 0:
        autocorr_sum = 0
        for k in range(1, max_lag + 1):
            if n - k > 0 and gamma0 > 0:
                autocorr_sum += np.mean((returns[:-k] - mean) * (returns[k:] - mean)) / gamma0
        n_eff = n / (1 + 2 * autocorr_sum) if (1 + 2 * autocorr_sum) > 0 else n
    else:
        n_eff = n
    p_val = 2 * (1 - scipy_stats.t.cdf(abs(t_nw), df=max(1, n_eff - 1)))
    return float(t_nw), float(p_val), float(n_eff)


def main():
    log("=" * 60)
    log("t值测试: 低波Top10 T+20, 两基准, Newey-West")
    log("=" * 60)
    db = sqlite3.connect(DB)
    dates = [str(r[0])[:10] for r in db.execute(
        "SELECT DISTINCT date FROM daily_kline WHERE date>=? AND date<=? ORDER BY date",
        (TEST_START, TEST_END)).fetchall()]
    codes = [r[0] for r in db.execute(
        "SELECT s.symbol FROM stock_info s WHERE s.class='stock' AND s.name NOT LIKE '%ST%' "
        "AND s.symbol NOT LIKE 'bj%'").fetchall()]
    log(f"test {len(dates)} days, {len(codes)} stocks")

    strategy_rets = []  # 低波Top10 T+20 每日平均收益
    mkt_rets = []        # 全市场等权 T+20 每日平均
    t0 = time.time()
    for di, date in enumerate(dates):
        scored = []
        all_rets = []
        for code in codes:
            v = vol_20(code, date, db)
            r = t_return(code, date, db, HORIZON)
            if v is None or r is None:
                continue
            scored.append((v, r))
            all_rets.append(r)
        if len(scored) < 10 or len(all_rets) < 10:
            continue
        scored.sort(key=lambda x: x[0])
        top10_avg = float(np.mean([s[1] for s in scored[:10]]))
        mkt_avg = float(np.mean(all_rets))
        strategy_rets.append(top10_avg)
        mkt_rets.append(mkt_avg)
        if (di + 1) % 100 == 0:
            log(f"  {di+1}/{len(dates)} [{time.time()-t0:.0f}s]")

    strategy_rets = np.array(strategy_rets)
    mkt_rets = np.array(mkt_rets)
    excess = strategy_rets - mkt_rets  # 超额(全市场等权基准)

    log("=" * 60)
    log("RESULT")
    log("=" * 60)

    # 基准1: 0(绝对收益)
    t_std_0 = float(np.mean(strategy_rets) / np.std(strategy_rets) * np.sqrt(len(strategy_rets)))
    t_nw_0, p_nw_0, n_eff_0 = newey_west_t(strategy_rets)
    ann_0 = float(np.mean(strategy_rets) * 252)

    # 基准2: 全市场等权
    t_std_mkt = float(np.mean(excess) / np.std(excess) * np.sqrt(len(excess)))
    t_nw_mkt, p_nw_mkt, n_eff_mkt = newey_west_t(excess)
    ann_mkt = float(np.mean(excess) * 252)
    ann_mkt_raw = float(np.mean(mkt_rets) * 252)

    log(f"\n策略: 低波Top10 T+{HORIZON}")
    log(f"天数: {len(strategy_rets)}")
    log(f"日均收益: {np.mean(strategy_rets):+.5f} ({np.mean(strategy_rets)*100:+.3f}%/天)")
    log(f"年化收益: {ann_0:+.2%} (T+{HORIZON}重叠, 虚高)")
    log(f"全市场年化: {ann_mkt_raw:+.2%} (重叠, 虚高)")
    log(f"超额年化: {ann_mkt:+.2%}")

    log(f"\n=== 基准0(绝对收益) ===")
    log(f"  t标准: {t_std_0:+.2f}")
    log(f"  t(Newey-West): {t_nw_0:+.2f}  p={p_nw_0:.4f}  N_eff={n_eff_0:.0f}")

    log(f"\n=== 基准全市场等权(超额) ===")
    log(f"  t标准: {t_std_mkt:+.2f}")
    log(f"  t(Newey-West): {t_nw_mkt:+.2f}  p={p_nw_mkt:.4f}  N_eff={n_eff_mkt:.0f}")

    log(f"\n=== 判定 ===")
    log(f"  t>2(p<5%): {'是' if abs(t_nw_mkt) > 2 else '否'} (全市场基准NW)")
    log(f"  t>4(强): {'是' if abs(t_nw_mkt) > 4 else '否'}")
    log(f"  年化>10%: {'是' if ann_0 > 0.10 else '否'}")

    out = {
        'strategy': 'lowvol_Top10_T20',
        'n_days': len(strategy_rets),
        'daily_avg': float(np.mean(strategy_rets)),
        'annual': round(ann_0, 4),
        'mkt_annual': round(ann_mkt_raw, 4),
        'excess_annual': round(ann_mkt, 4),
        'benchmark_0': {'t_std': round(t_std_0, 4), 't_nw': round(t_nw_0, 4), 'p': round(p_nw_0, 6), 'n_eff': round(n_eff_0, 1)},
        'benchmark_mkt': {'t_std': round(t_std_mkt, 4), 't_nw': round(t_nw_mkt, 4), 'p': round(p_nw_mkt, 6), 'n_eff': round(n_eff_mkt, 1)},
    }
    json.dump(out, open(OUT, 'w'), indent=2, ensure_ascii=False)
    log(f"\nwritten: {OUT}")
    db.close()


if __name__ == '__main__':
    main()
