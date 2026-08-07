#!/home/soso/v5/.venv/bin/python3
"""walk-forward 因子重选 backtest（#4 forward OOS 核心）

#3 的 daily_pick backtest SR0.40 用的是静态 2000-2015 选的 38 因子（已是因子层 OOS，
因子选择无 look-ahead）。本脚本测：**每年 expanding 重选因子（只用过去数据）是否优于
静态 2000-2015 集**。这是策略改进问题（自适应因子选择），非诚实修正。

方法：
1. 全历史 panel 2016-2026 一次性建
2. 每年 Y：用 factor_ic_daily [2006, Y-1] 选 top-38 因子（IR+persistence 准则，对齐生产池大小）
3. union 各年选中因子，一次性 compute_alpha 各因子（全 panel）
4. 每年 Y 内周度：用 Y 的因子集 composite rank Top5 + 涨停过滤 + T+5 持有
5. concat 各年 OOS returns -> walk-forward SR，对比 #3 静态 0.40

口径标注：
- 静态集(#3)=38 正交池（factor_decay 2000-2015）；walk-forward=top-38 by IR 无正交化
- expanding 窗口对齐生产"全前置数据"口径（factor_ic_daily 2006 起，近似 2000-2015）
"""
import os, sys, json, time, sqlite3
from datetime import datetime
import numpy as np
import pandas as pd

sys.path.insert(0, '/home/soso/v5')
sys.path.insert(0, '/home/soso/v5/branches/strategy_factory')
import strategy_factory as sf
from factor_zoo_adapter import compute_alpha

DB = os.path.expanduser("~/ading/db/tdx_stock_data.db")
OUT = os.path.expanduser("~/v5/branches/strategy_factory/walkforward_result.json")
IC_DB = DB
START, END = '2016-01-01', '2026-06-30'
IC_START = '2006-01-01'  # factor_ic_daily 起
TOP_N = 38  # 对齐生产 all_orthogonal 池大小
IC_MIN, IR_MIN = 0.02, 0.3
PERSIST_RATIO = 0.9  # T20/T1 persistent 准则
HORIZON = 5
TOP_K = 5
LIMIT_UP = 9.8
VOTE_THR = 0.5


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def select_factors_ic_daily(year, top_n=TOP_N):
    """用 factor_ic_daily [IC_START, year-1] 选因子：IC/IR/persistence 准则，top_n by IR。"""
    end = f"{year-1}-12-31"
    db = sqlite3.connect(IC_DB)
    df = pd.read_sql("""
        SELECT factor_id, date, T1_IC, T20_IC FROM factor_ic_daily
        WHERE date >= ? AND date <= ? AND T1_IC IS NOT NULL
    """, db, params=(IC_START, end))
    db.close()
    if df.empty:
        return []
    g = df.groupby('factor_id')
    stats = []
    for fid, sub in g:
        t1 = sub['T1_IC'].dropna()
        t20 = sub['T20_IC'].dropna()
        if len(t1) < 50:
            continue
        ic_mean = float(t1.mean())
        ir = ic_mean / float(t1.std()) if t1.std() > 0 else 0
        t20_mean = float(t20.mean()) if len(t20) else 0
        persist = t20_mean / ic_mean if ic_mean != 0 else 0
        if ic_mean < IC_MIN or ir < IR_MIN:
            continue
        if persist < PERSIST_RATIO:
            continue
        stats.append((fid, ic_mean, ir, persist))
    stats.sort(key=lambda x: x[2], reverse=True)  # by IR
    return stats[:top_n]


def main():
    log("=" * 60); log("walk-forward 因子重选 backtest"); log("=" * 60)
    cfg = sf.load_config(os.path.expanduser('~/v5/branches/strategy_factory/strategy_config.json'))

    # 1. 每年选因子
    years = list(range(2016, 2027))
    year_factors = {}
    all_factors = set()
    log("年度因子重选（expanding [2006, Y-1]）：")
    for y in years:
        sel = select_factors_ic_daily(y)
        fids = [s[0] for s in sel]
        year_factors[y] = fids
        all_factors.update(fids)
        log(f"  {y}: 选中 {len(fids)} 因子，top3 IR={[round(s[2],2) for s in sel[:3]]}")
    log(f"union 因子: {len(all_factors)} 唯一")

    # 2. 全历史 panel
    panel = sf.build_panel_history(START, END)
    close = panel['close']
    all_dates = close.index

    # 3. 一次性 compute union 因子
    log(f"一次性预算 {len(all_factors)} 因子...")
    t0 = time.time()
    factor_mats = {}
    for fid in sorted(all_factors):
        zoo, alpha = fid.split('/')
        try:
            vals = compute_alpha(zoo, alpha + '.py', panel)
            if vals is not None and not vals.empty:
                factor_mats[fid] = vals
        except Exception:
            pass
    log(f"预算 {len(factor_mats)}/{len(all_factors)}，耗时 {time.time()-t0:.0f}s")

    # 4. 每年周度选股
    out = {}
    for y in years:
        fids = [f for f in year_factors[y] if f in factor_mats]
        if len(fids) < 2:
            log(f"  {y}: 因子不足，跳过")
            continue
        # 该年周度
        ymask = all_dates.year == y
        ydates = all_dates[ymask]
        week_first = {}
        for d in ydates:
            iso = d.isocalendar()
            wk = f"{iso[0]}-W{iso[1]:02d}"
            if wk not in week_first:
                week_first[wk] = d
        for wk, d in week_first.items():
            fvals = {}
            for f in fids:
                mat = factor_mats[f]
                if d in mat.index:
                    v = mat.loc[d].dropna()
                    if len(v):
                        fvals[f] = v
            if len(fvals) < 2:
                continue
            di = all_dates.get_loc(d)
            if di > 0:
                prev = all_dates[di-1]
                gain = (close.loc[d] / close.loc[prev] - 1) * 100
                limit_up_set = set(gain[gain >= LIMIT_UP].index)
            else:
                limit_up_set = set()
            min_votes = max(1, int(VOTE_THR * len(fvals)))
            code_votes = {}
            for f, v in fvals.items():
                for c in v.index:
                    if c not in limit_up_set:
                        code_votes[c] = code_votes.get(c, 0) + 1
            pool = [c for c, ct in code_votes.items() if ct >= min_votes]
            if len(pool) < TOP_K:
                continue
            composite = pd.Series(0.0, index=pool)
            n_contrib = pd.Series(0, index=pool)
            for f, v in fvals.items():
                common = list(set(pool) & set(v.index))
                if len(common) < TOP_K:
                    continue
                composite[common] += v[common].rank(pct=True)
                n_contrib[common] += 1
            composite = composite[n_contrib > 0]
            composite /= n_contrib[composite.index]
            if len(composite) < TOP_K:
                continue
            top = composite.nlargest(TOP_K)
            rets = []
            for code in top.index:
                try:
                    di2 = all_dates.get_loc(d)
                    if di2 + HORIZON >= len(all_dates):
                        continue
                    buy = close.loc[d, code]
                    sell = close.iloc[di2 + HORIZON][code]
                    if buy > 0 and not np.isnan(sell):
                        rets.append(sell / buy - 1)
                except Exception:
                    continue
            if rets:
                out[wk] = float(np.mean(rets))
        log(f"  {y}: {sum(1 for w in out if w.startswith(str(y)))}周")

    arr = np.array(list(out.values()), float)
    arr = arr[~np.isnan(arr)]
    sr = float(arr.mean() / arr.std() * np.sqrt(52)) if len(arr) and arr.std() > 0 else 0
    nav = np.cumprod(1 + arr)
    mdd = float(((nav - np.maximum.accumulate(nav)) / np.maximum.accumulate(nav)).min())
    log("-" * 60)
    log(f"walk-forward: {len(out)}周, SR {sr:.3f}, 年化 {arr.mean()*52:.2%}, MDD {mdd:.2%}")
    log(f"对比 #3 静态2000-2015集: SR 0.40 -> walk-forward {'改善' if sr>0.48 else '约同/更差' if sr<0.32 else '相近'}({sr:.3f})")

    out_j = {
        'run_at': datetime.now().isoformat(),
        'method': f'expanding factor_ic_daily [2006,Y-1] 重选 top-{TOP_N} by IR+persistence, 周度T+5',
        'year_factors': {str(y): f for y, f in year_factors.items()},
        'n_unique_factors': len(all_factors),
        'n_weeks': len(out),
        'sharpe': round(sr, 3), 'annual': round(float(arr.mean()*52), 4),
        'max_dd': round(mdd, 3),
        'vs_static_040': round(sr, 3),
        'caveat': 'walk-forward=top-38 by IR 无正交化; 静态集=38正交池(2000-2015); expanding窗口近似全前置',
        'returns': [[w, out[w]] for w in sorted(out)],
    }
    json.dump(out_j, open(OUT, 'w'), indent=2, ensure_ascii=False, default=float)
    log(f"written: {OUT}")


if __name__ == '__main__':
    main()
