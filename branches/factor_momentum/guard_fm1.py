#!/home/soso/v5/.venv/bin/python3
"""#11 2.6 护栏：FM-1(因子动量k5) vs 纯个股动量 相关 ≤0.8
超过 -> 因子动量是个股动量马甲，废弃（Ehsani-Linnainmaa）
FM-1: phase2 k5 策略月收益（IC前5因子放行，factor_map ret均值）
个股动量: 每月过去252天涨幅Top10 T+20收益
解耦：只读 factor_ic_daily/factor_map/daily_kline。
"""
import sqlite3, os, json, time
from datetime import datetime
from collections import defaultdict
import numpy as np

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
JSON_P = '/home/soso/ading/data/reports/factor_decay_results_tdx.json'
OUT = os.path.expanduser('~/v5/branches/factor_momentum/guard_fm1_result.json')
K_IC = 12
K_STOCK = 252  # 个股动量回看（12月）
K_FACTOR = 5   # FM-1 用 k5（phase2 最优）
TOP = 10
HORIZON = 20


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def main():
    log("=" * 60); log("#11 2.6 护栏 FM-1 vs 纯个股动量"); log("=" * 60)
    orth = [f['id'] for f in json.load(open(JSON_P))['all_orthogonal']]
    db = sqlite3.connect(DB)

    # FM-1: k5 因子动量月收益（复用 phase2 逻辑）
    log("算 FM-1 (k5 因子动量) 月收益...")
    ic_monthly = defaultdict(dict)
    for fid in orth:
        rows = db.execute("SELECT substr(date,1,7) ym, AVG(T20_IC) FROM factor_ic_daily WHERE factor_id=? AND T20_IC IS NOT NULL GROUP BY ym ORDER BY 1", (fid,)).fetchall()
        for ym, ic in rows:
            ic_monthly[fid][ym] = ic
    ret_monthly = defaultdict(dict)
    for fid in orth:
        rows = db.execute("SELECT period, return FROM factor_map WHERE granularity='month' AND factor=?", (fid,)).fetchall()
        for ym, ret in rows:
            ret_monthly[fid][ym] = ret
    yms = sorted(set(ym for fid in ic_monthly for ym in ic_monthly[fid]))
    yms = [y for y in yms if '2016-01' <= y <= '2026-06']
    fm1 = {}
    for i, ym in enumerate(yms):
        if i < K_IC:
            continue
        past = yms[i - K_IC:i]
        ic_vals = {}
        for fid in orth:
            vals = [ic_monthly[fid].get(py) for py in past]
            vals = [v for v in vals if v is not None]
            if vals:
                ic_vals[fid] = float(np.mean(vals))
        if not ic_vals:
            continue
        sorted_fids = sorted(ic_vals, key=lambda f: -ic_vals[f])
        active = sorted_fids[:K_FACTOR]
        rets = [ret_monthly[fid].get(ym) for fid in active]
        rets = [r for r in rets if r is not None]
        if rets:
            fm1[ym] = float(np.mean(rets))
    log(f"FM-1 月数: {len(fm1)}")

    # 个股动量: 每月252天涨幅Top10 T+20
    log("算纯个股动量（252天涨幅Top10 T+20）月收益...")
    codes = [r[0] for r in db.execute("SELECT s.symbol FROM stock_info s WHERE s.class='stock' AND s.name NOT LIKE '%ST%' AND s.symbol NOT LIKE 'bj%'").fetchall()]
    month_date = {}
    for ym in yms:
        d = db.execute("SELECT MIN(date) FROM daily_kline WHERE date LIKE ?", (ym + '%',)).fetchone()[0]
        month_date[ym] = str(d)[:10]
    stock_mom = {}
    t0 = time.time()
    for i, (ym, ds) in enumerate(month_date.items()):
        if ym not in fm1:
            continue
        scored = []
        for code in codes:
            rows = db.execute("SELECT close FROM daily_kline WHERE code=? AND date < ? AND close>0 ORDER BY date DESC LIMIT ?",
                              (code, ds + ' 23:59:59', K_STOCK + 1)).fetchall()
            if len(rows) < K_STOCK + 1:
                continue
            mom = rows[0][0] / rows[-1][0] - 1
            trows = db.execute("SELECT close FROM daily_kline WHERE code=? AND date > ? AND close>0 ORDER BY date LIMIT ?",
                               (code, ds + ' 23:59:59', HORIZON)).fetchall()
            buy = db.execute("SELECT close FROM daily_kline WHERE code=? AND date LIKE ?", (code, ds + '%')).fetchone()
            if not buy or buy[0] <= 0 or len(trows) < HORIZON:
                continue
            tret = trows[-1][0] / buy[0] - 1
            scored.append((mom, tret))
        if len(scored) < TOP:
            continue
        scored.sort(key=lambda x: -x[0])
        top_rets = [scored[j][1] for j in range(TOP)]
        stock_mom[ym] = float(np.mean(top_rets))
        if (i + 1) % 24 == 0:
            log(f"  {i+1}/{len(month_date)} [{time.time()-t0:.0f}s]")
    log(f"个股动量月数: {len(stock_mom)}")

    # 对齐算相关
    common = sorted(set(fm1) & set(stock_mom))
    fm1_arr = np.array([fm1[y] for y in common])
    sm_arr = np.array([stock_mom[y] for y in common])
    corr = float(np.corrcoef(fm1_arr, sm_arr)[0, 1]) if len(common) > 2 else 0
    log("=" * 60); log("护栏结果"); log("=" * 60)
    log(f"FM-1 vs 个股动量 相关: {corr:.3f} (n={len(common)}月)")
    verdict = '通过(≤0.8, 因子动量非个股动量马甲)' if corr <= 0.8 else '废弃(>0.8, 因子动量是个股动量马甲)'
    log(f"判定: {verdict}")

    out = {'run_at': datetime.now().isoformat(), 'fm1_n': len(fm1), 'stock_mom_n': len(stock_mom),
           'common_n': len(common), 'corr': round(corr, 4), 'pass': corr <= 0.8, 'k_stock': K_STOCK, 'fm1_k': K_FACTOR}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, 'w'), indent=2, ensure_ascii=False, default=float)
    log(f"written: {OUT}")
    db.close()


if __name__ == '__main__':
    main()
