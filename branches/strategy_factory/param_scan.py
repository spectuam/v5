#!/home/soso/v5/.venv/bin/python3
"""参数扫描：TopK × 涨停过滤（#a 调生产策略检验）

假设：daily_pick 跑输市场(SR0.43 vs 0.58)+MDD最大(-50%) 的头号嫌疑是 Top5 集中 + 涨停过滤。
扫描 TopK[5,10,20,30,50] × 涨停[on,off]，看参数空间趋势：
- TopK 增大能否降 MDD、提 SR、跑赢 market_eq(0.58,-33%)？
- 涨停 off 能否改善（不误杀动量延续）？

诚实：参数人为设定非 fit，无 look-ahead；看趋势不挑单点（避免过拟合搜参）。
因子集 = 38（2000-2015 选，已 OOS）；只扫选股参数。复用 #3 panel+factor 一次预算。

优化：涨停 on/off 决定 vote pool/composite，故每涨停设定算一次 composite；
TopK 只影响 nlargest，cheap，在 composite 上扫。
"""
import os, sys, json, time
from datetime import datetime
import numpy as np
import pandas as pd

sys.path.insert(0, '/home/soso/v5')
sys.path.insert(0, '/home/soso/v5/branches/strategy_factory')
import strategy_factory as sf
from factor_zoo_adapter import compute_alpha

DB = os.path.expanduser("~/ading/db/tdx_stock_data.db")
OUT = os.path.expanduser("~/v5/branches/strategy_factory/param_scan_result.json")
START, END = '2016-01-01', '2026-06-30'
TOP_KS = [5, 10, 20, 30, 50]
LIMIT_UPS = [('on', 9.8), ('off', None)]
VOTE_THR = 0.5
HORIZON = 5
FREQ = 52


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def max_dd(rets):
    nav = np.cumprod(1 + np.asarray(rets, float))
    if len(nav) == 0:
        return 0.0
    peak = np.maximum.accumulate(nav)
    return float(((nav - peak) / peak).min())


def stats(rets):
    arr = np.asarray(rets, float)
    arr = arr[~np.isnan(arr)]
    if len(arr) < 2 or arr.std() == 0:
        return {'n': len(arr), 'sharpe': 0, 'annual': 0, 'max_dd': 0, 'calmar': 0}
    sr = float(arr.mean() / arr.std() * np.sqrt(FREQ))
    mdd = max_dd(arr)
    return {'n': len(arr), 'sharpe': round(sr, 3),
            'annual': round(float(arr.mean() * FREQ), 4),
            'max_dd': round(mdd, 3), 'calmar': round(float(arr.mean() * FREQ / abs(mdd)) if mdd else 0, 3)}


def main():
    log("=" * 60); log("参数扫描 TopK × 涨停 (调生产策略检验)"); log("=" * 60)
    cfg = sf.load_config(os.path.expanduser('~/v5/branches/strategy_factory/strategy_config.json'))
    factor_ids = sf.load_factor_ids(cfg)
    log(f"因子 {len(factor_ids)}")

    panel = sf.build_panel_history(START, END)
    close = panel['close']
    all_dates = close.index

    # 一次性预算 38 因子
    log(f"预算 {len(factor_ids)} 因子...")
    t0 = time.time()
    factor_mats = {}
    for aid in factor_ids:
        zoo, fid = aid.split('/')
        try:
            vals = compute_alpha(zoo, fid + '.py', panel)
            if vals is not None and not vals.empty:
                factor_mats[aid] = vals
        except Exception:
            pass
    log(f"预算 {len(factor_mats)}/{len(factor_ids)}，耗时 {time.time()-t0:.0f}s")

    # 周度 rebalance 日期
    week_first = {}
    for d in all_dates:
        iso = d.isocalendar()
        wk = f"{iso[0]}-W{iso[1]:02d}"
        if wk not in week_first:
            week_first[wk] = d
    weeks = sorted(week_first)
    log(f"周度 {len(weeks)} 期")

    # 预算每日期的 fvals（不依赖 limit_up）
    log("预算每日期因子值...")
    date_fvals = {}
    for d in [week_first[w] for w in weeks]:
        fv = {}
        for aid, mat in factor_mats.items():
            if d in mat.index:
                v = mat.loc[d].dropna()
                if len(v):
                    fv[aid] = v
        date_fvals[d] = fv

    results = {}
    for lu_name, lu_val in LIMIT_UPS:
        log(f"\n--- 涨停过滤: {lu_name} ({lu_val}) ---")
        # 每周算 composite（依赖 limit_up：排除涨停股出 vote pool）
        week_composite = {}
        for w in weeks:
            d = week_first[w]
            fv = date_fvals.get(d, {})
            if len(fv) < 2:
                continue
            di = all_dates.get_loc(d)
            if di > 0 and lu_val is not None:
                prev = all_dates[di - 1]
                gain = (close.loc[d] / close.loc[prev] - 1) * 100
                limit_up_set = set(gain[gain >= lu_val].index)
            else:
                limit_up_set = set()
            min_votes = max(1, int(VOTE_THR * len(fv)))
            code_votes = {}
            for aid, v in fv.items():
                for c in v.index:
                    if c not in limit_up_set:
                        code_votes[c] = code_votes.get(c, 0) + 1
            pool = [c for c, ct in code_votes.items() if ct >= min_votes]
            if len(pool) < 5:
                continue
            composite = pd.Series(0.0, index=pool)
            n_contrib = pd.Series(0, index=pool)
            for aid, v in fv.items():
                common = list(set(pool) & set(v.index))
                if len(common) < 5:
                    continue
                composite[common] += v[common].rank(pct=True)
                n_contrib[common] += 1
            composite = composite[n_contrib > 0]
            composite /= n_contrib[composite.index]
            if len(composite) < 5:
                continue
            week_composite[w] = (d, composite)

        # 扫 TopK
        for tk in TOP_KS:
            rets = []
            for w, (d, comp) in week_composite.items():
                if len(comp) < tk:
                    continue
                top = comp.nlargest(tk)
                di = all_dates.get_loc(d)
                if di + HORIZON >= len(all_dates):
                    continue
                rts = []
                for code in top.index:
                    try:
                        buy = close.loc[d, code]
                        sell = close.iloc[di + HORIZON][code]
                        if buy > 0 and not np.isnan(sell):
                            rts.append(sell / buy - 1)
                    except Exception:
                        continue
                if rts:
                    rets.append(float(np.mean(rts)))
            st = stats(rets)
            key = f"topk{tk}_limitup_{lu_name}"
            results[key] = st
            beat = "跑赢市场" if st['sharpe'] > 0.58 else "跑输市场"
            log(f"  TopK={tk:>2} 涨停{lu_name}: SR{st['sharpe']:.3f} 年化{st['annual']:.2%} MDD{st['max_dd']:.2%} Calmar{st['calmar']} -> {beat}")

    # market_eq 基准
    log("\n--- 基准 ---")
    log(f"  market_eq: SR0.580 年化16.30% MDD-33.2% (compare_pool)")
    log(f"  daily_pick原版(Top5+涨停on): SR0.40 MDD-50% (#3)")

    out = {
        'run_at': datetime.now().isoformat(),
        'method': 'TopK×涨停 扫描, 38因子静态(2000-2015选OOS), 周度T+5, 2016-2026',
        'baseline': {'market_eq': {'sharpe': 0.58, 'max_dd': -0.332}, 'daily_pick_orig': {'sharpe': 0.40, 'max_dd': -0.50}},
        'results': results,
        'caveat': '参数人为设定非fit无lookahead; 看趋势不挑单点; 因子集静态OOS; 扫参SR若高仍需forward验证(防walk-forward过拟合)',
    }
    json.dump(out, open(OUT, 'w'), indent=2, ensure_ascii=False, default=float)
    log(f"\nwritten: {OUT}")


if __name__ == '__main__':
    main()
