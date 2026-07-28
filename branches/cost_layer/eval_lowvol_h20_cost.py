#!/home/soso/v5/.venv/bin/python3
"""#9/#12 lowvol 扣成本回测（eval_lowvol_h20 + 成本层）
零成本(T+20) vs 扣成本(往返11bp + 分层冲击)
解耦: 新支路 branches/cost_layer/, 不污染 eval_lowvol_h20.py 基线
"""
import sys, os, sqlite3, time, json
sys.path.insert(0, '/home/soso/v5/branches/cost_layer')
from datetime import datetime
import numpy as np
from cost_utils import round_trip_cost, impact_cost

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
TEST_START = '2024-01-01'
TEST_END = '2026-06-30'
TOP = 10
HORIZON = 20
TOTAL_CAPITAL = 1_000_000  # 假设总资金 100万, 等权每只 10万
OUT = os.path.expanduser('~/v5/branches/cost_layer/eval_lowvol_h20_cost_result.json')


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def vol_20(code, date, db):
    rows = db.execute("SELECT close FROM daily_kline WHERE code=? AND date < ? AND close>0 ORDER BY date DESC LIMIT 21",
                      (code, date + ' 23:59:59')).fetchall()
    if len(rows) < 21:
        return None
    closes = [r[0] for r in rows]
    return float(np.std(np.diff(closes) / closes[:-1]))


def avg_amount_20(code, date, db):
    """前20天日均成交额（算冲击）"""
    rows = db.execute("SELECT amount FROM daily_kline WHERE code=? AND date < ? AND amount>0 ORDER BY date DESC LIMIT 20",
                      (code, date + ' 23:59:59')).fetchall()
    if len(rows) < 10:
        return 0.0
    return float(np.mean([r[0] for r in rows]))


def t_return(code, date, db, H):
    rows = db.execute("SELECT close FROM daily_kline WHERE code=? AND date > ? AND close>0 ORDER BY date LIMIT ?",
                      (code, date + ' 23:59:59', H)).fetchall()
    buy = db.execute("SELECT close FROM daily_kline WHERE code=? AND date LIKE ?", (code, date + '%')).fetchone()
    if not buy or buy[0] <= 0 or len(rows) < H:
        return None
    return rows[-1][0] / buy[0] - 1


def stats(returns):
    if not returns:
        return None
    arr = np.array(returns)
    arr = np.clip(arr, -0.95, 5.0)
    wins = arr[arr > 0]; losses = arr[arr <= 0]
    wr = len(wins) / len(arr) if len(arr) > 0 else 0
    avg_win = wins.mean() if len(wins) > 0 else 0
    avg_loss = abs(losses.mean()) if len(losses) > 0 else 0
    pnl = avg_win / avg_loss if avg_loss > 0 else 0
    sharpe = arr.mean() / arr.std() * np.sqrt(252) if arr.std() > 0 else 0
    cum = np.cumsum(arr); peak = np.maximum.accumulate(cum); dd = cum - peak
    max_dd = dd.min() if len(dd) > 0 else 0
    return {'win_rate': round(wr, 4), 'pnl_ratio': round(pnl, 4), 'sharpe': round(sharpe, 4),
            'max_dd': round(max_dd, 4), 'avg_ret': round(arr.mean(), 6), 'n': len(arr)}


def main():
    log("=" * 60); log("#9 lowvol 扣成本回测（往返11bp + 分层冲击）"); log("=" * 60)
    db = sqlite3.connect(DB)
    dates = [str(r[0])[:10] for r in db.execute(
        "SELECT DISTINCT date FROM daily_kline WHERE date>=? AND date<=? ORDER BY date", (TEST_START, TEST_END)).fetchall()]
    codes = [r[0] for r in db.execute(
        "SELECT s.symbol FROM stock_info s WHERE s.class='stock' AND s.name NOT LIKE '%ST%' AND s.symbol NOT LIKE 'bj%'").fetchall()]
    log(f"test {len(dates)} days, {len(codes)} stocks")
    holding_per_stock = TOTAL_CAPITAL / TOP
    rt = round_trip_cost()
    log(f"往返成本: {rt*10000:.1f}bp, 持仓/只: {holding_per_stock:,.0f}元")

    by_year = {}
    all_rets = []; all_rets_net = []
    cost_total = 0.0; n_impact = 0
    t0 = time.time()
    for di, date in enumerate(dates):
        scored = []
        for code in codes:
            v = vol_20(code, date, db)
            r = t_return(code, date, db, HORIZON)
            if v is None or r is None:
                continue
            amt = avg_amount_20(code, date, db)
            scored.append((v, r, amt))
        if len(scored) < TOP:
            continue
        scored.sort(key=lambda x: x[0])
        for i in range(TOP):
            v, r, amt = scored[i]
            impact = impact_cost(holding_per_stock, amt)
            cost = rt + impact
            net = r - cost
            all_rets.append(r); all_rets_net.append(net)
            by_year.setdefault(date[:4], {'gross': [], 'net': []})
            by_year[date[:4]]['gross'].append(r)
            by_year[date[:4]]['net'].append(net)
            cost_total += cost
            if impact > 0:
                n_impact += 1
        if (di + 1) % 100 == 0:
            log(f"  {di+1}/{len(dates)} [{time.time()-t0:.0f}s]")

    log("=" * 60); log("RESULT"); log("=" * 60)
    gross = stats(all_rets); net = stats(all_rets_net)
    log(f"零成本(基线): 夏普={gross['sharpe']} 盈亏比={gross['pnl_ratio']} 胜率={gross['win_rate']} 回撤={gross['max_dd']} 均收={gross['avg_ret']}")
    log(f"扣成本: 夏普={net['sharpe']} 盈亏比={net['pnl_ratio']} 胜率={net['win_rate']} 回撤={net['max_dd']} 均收={net['avg_ret']}")
    log(f"总成本均值: {cost_total/len(all_rets)*10000:.2f}bp, 有冲击笔数: {n_impact}/{len(all_rets)} ({n_impact/len(all_rets)*100:.1f}%)")
    log("分年:")
    year_stats = {}
    for y in sorted(by_year):
        g = stats(by_year[y]['gross']); n = stats(by_year[y]['net'])
        year_stats[y] = {'gross': g, 'net': n}
        log(f"  {y}: 夏普 gross={g['sharpe']} net={n['sharpe']} | 均收 gross={g['avg_ret']} net={n['avg_ret']}")
    log(f"目标: 扣成本夏普>1, 跑赢固收+4.5%(年化, T+20均收>0.035/12≈0.0029)")
    out = {'run_at': datetime.now().isoformat(), 'gross': gross, 'net': net,
           'by_year': year_stats, 'round_trip_bp': 11, 'capital': TOTAL_CAPITAL,
           'avg_cost_bp': round(cost_total / len(all_rets) * 10000, 2),
           'impact_pct': round(n_impact / len(all_rets) * 100, 1)}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, 'w'), indent=2, ensure_ascii=False)
    log(f"written: {OUT}")
    db.close()


if __name__ == '__main__':
    main()
