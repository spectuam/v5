#!/home/soso/v5/.venv/bin/python3
"""T3a 流式版: equal vs ic vs ir 加权 + 剔除衰减对比 - 路径B直接验证

内存优化(vs 囤版):
  - 因子值逐个算 + 存盘 float32(不囤 factor_dfs)
  - 释放 panel 非close字段(simulate 只用 close)
  - 回测每方案按需从盘读因子, 完即释放
  - 断点续传(已存盘的跳过)
峰值预估: ~2-3GB(equal_38 读38个float32因子值), 远低于7G杀。
避开 timer 密集期跑。
"""
import sys, os, json, gc, time, resource
from datetime import datetime

sys.path.insert(0, '/home/soso/trading-strategy')
sys.path.insert(0, '/home/soso/.local/lib/python3.12/site-packages/src/factors')
sys.path.insert(0, '/home/soso/v5')

import numpy as np, pandas as pd
from line_bcd_backtest import (
    compute_factor_weights, simulate_daily_picks, load_industry_map, FACTOR_JSON, TDX_DB
)
from factor_decay_utils import build_daily_panel, compute_forward_returns
from factor_zoo_adapter import compute_alpha

OUT = '/home/soso/v5/t3a_weight_compare_result.json'
T12 = '/home/soso/v5/t1_t2_diag_result.json'
TMP = '/home/soso/ading/cache/t3a_factors'
VALID_START, VALID_END = '2016-01-01', '2020-12-31'
TEST_START, TEST_END = '2021-01-01', '2026-07-14'

# 9个衰减因子(T1+T2: P1|IR|>0.3 但 P5|IR|<0.2)
DECAYED = {'gtja191/alpha_008','alpha101/alpha_084','gtja191/alpha_026',
           'alpha101/alpha_024','gtja191/alpha_037','gtja191/alpha_006',
           'alpha101/alpha_080','alpha101/alpha_067','qlib158/cntn5'}

def log(m): print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)
def rss_mb(): return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024
def pkl_path(aid): return os.path.join(TMP, aid.replace('/', '_') + '.pkl')

def build_panel_light(lookback_days=4200, date_end=None):
    """轻量 panel: 按字段单独读 SQL + pivot + 释放, 避免 6GB 长格式 df。峰值 ~1GB。"""
    import sqlite3
    db = sqlite3.connect(TDX_DB)
    min_date = db.execute("SELECT date(MAX(date), ? || ' days') FROM daily_kline",
                          (f'-{lookback_days}',)).fetchone()[0]
    flt = (" FROM daily_kline d JOIN stock_info s ON d.code = s.symbol"
           " WHERE d.date >= ? AND date(d.date) <= ? AND d.close > 0 AND d.open > 0"
           " AND s.class = 'stock' AND s.name NOT LIKE '%%ST%%' AND d.code NOT LIKE 'bj%%'")
    panel = {}
    for f in ['open', 'high', 'low', 'close', 'volume', 'amount']:
        df = pd.read_sql("SELECT d.code, d.date, d." + f + flt, db, params=(min_date, date_end))
        df['date'] = pd.to_datetime(df['date'])
        wide = df.pivot(index='date', columns='code', values=f).sort_index().astype('float32')
        panel[f] = wide
        log(f"    {f}: {wide.shape} RSS={rss_mb()}MB")
        del df, wide; gc.collect()
    panel['vwap'] = (panel['amount'] / panel['volume'].replace(0, np.nan)
                     ).replace([np.inf, -np.inf], np.nan).astype('float32')
    db.close()
    return panel


def main():
    log("=" * 60); log("T3a streaming: weight scheme compare"); log("=" * 60)

    # 1. 因子列表
    d = json.load(open(FACTOR_JSON))
    ortho = [o for o in d['all_orthogonal'] if o.get('status') in ('confirmed','degraded','unstable')]
    ortho.sort(key=lambda x: x.get('ic_mean', 0), reverse=True)
    all38 = [o['id'] for o in ortho]
    equal29 = [f for f in all38 if f not in DECAYED]
    t12 = json.load(open(T12))
    strong21 = [f['id'] for f in t12['factors']
                if f['stats']['T5'].get('P5_recent_2526', {}).get('ir') is not None
                and abs(f['stats']['T5']['P5_recent_2526']['ir']) > 0.3]
    log(f"groups: all38={len(all38)}, equal29={len(equal29)}, strong21={len(strong21)}")

    # 2. 面板
    log("Building panel (2016~2026)...")
    t0 = time.time()
    panel = build_panel_light(lookback_days=4200, date_end=TEST_END)
    dates = panel['close'].index
    log(f"  Panel: {len(dates)}d x {len(panel['close'].columns)}c "
        f"({dates[0].date()}~{dates[-1].date()}) [{time.time()-t0:.0f}s] RSS={rss_mb()}MB")
    industry_map = load_industry_map()
    fwd_T1 = compute_forward_returns(panel, horizons=[1])[1]

    # 3. Phase1: 算38因子值, 每个存盘 float32(流式, 断点续传) -- compute_alpha 需 panel 全字段
    os.makedirs(TMP, exist_ok=True)
    log("Computing+storing 38 factors (streaming, float32)...")
    t0 = time.time()
    stored = []
    for i, aid in enumerate(all38):
        pk = pkl_path(aid)
        if os.path.exists(pk):
            stored.append(aid); continue
        zoo, fid = aid.split('/')
        try:
            vals = compute_alpha(zoo, fid + '.py', panel)
            if vals is not None and not vals.empty:
                vals = vals.astype('float32')  # 强制 float32 省一半
                vals.to_pickle(pk)
                stored.append(aid)
                del vals
        except Exception as e:
            log(f"  {aid}: ERR {e}")
        if (i + 1) % 5 == 0:
            log(f"  {i+1}/38 stored, RSS={rss_mb()}MB")
            gc.collect()
    log(f"  {len(stored)} factors stored [{time.time()-t0:.0f}s] RSS={rss_mb()}MB")

    # 释放 panel 非close字段(Phase1 因子算完, Phase2 simulate 只用 close)
    for k in ['open','high','low','volume','vwap','amount']:
        if k in panel: del panel[k]
    gc.collect()
    log(f"  panel slimmed after Phase1 RSS={rss_mb()}MB")

    # 4. 权重(train<=2015)
    valid_ids = [aid for aid in all38 if aid in stored]
    weights = compute_factor_weights(valid_ids)
    log(f"  weights equal/ic/ir: {len(weights['equal'])}/{len(weights['ic'])}/{len(weights['ir'])}")

    def load_fdfs(fids):
        fdfs = []
        for aid in fids:
            pk = pkl_path(aid)
            if os.path.exists(pk):
                fdfs.append((aid, pd.read_pickle(pk)))
        return fdfs

    def eq_w(fids): return {aid: 1.0 for aid in fids}

    configs = [
        ('equal_38', valid_ids, eq_w(valid_ids)),
        ('equal_29', [f for f in equal29 if f in valid_ids], None),
        ('equal_21', [f for f in strong21 if f in valid_ids], None),
        ('ic_38', valid_ids, weights['ic']),
        ('ir_38', valid_ids, weights['ir']),
    ]

    # 5. Phase2: 5方案回测, 每方案读因子, simulate, 释放
    results = {}
    for label, fids, w in configs:
        fdfs = load_fdfs(fids)
        log(f"  {label}: {len(fdfs)} factors loaded RSS={rss_mb()}MB")
        t1 = time.time()
        vr = simulate_daily_picks(panel, fdfs, VALID_START, VALID_END, industry_map, fwd_T1, w)
        tr = simulate_daily_picks(panel, fdfs, TEST_START, TEST_END, industry_map, fwd_T1, w)
        results[label] = {
            'n_factors': len(fdfs),
            'valid': {'WR': vr['WR'], 'mean_ret': vr['mean_return'],
                      'mean_rp': vr['mean_return_pct'], 'n_trades': vr['n_trades']},
            'test':  {'WR': tr['WR'], 'mean_ret': tr['mean_return'],
                      'mean_rp': tr['mean_return_pct'], 'n_trades': tr['n_trades']},
        }
        log(f"    VALID WR={vr['WR']:.4f} ret={vr['mean_return']:.4f} | "
            f"TEST WR={tr['WR']:.4f} ret={tr['mean_return']:.4f} [{time.time()-t1:.0f}s]")
        del fdfs; gc.collect()

    # 6. 输出
    out = {
        'run_at': datetime.now().isoformat(),
        'note': 'path B streaming: equal/ic/ir加权 + 剔除9衰减 + 仅21强',
        'decayed_9': list(DECAYED),
        'strong21': strong21,
        'configs': results,
    }
    json.dump(out, open(OUT, 'w'), ensure_ascii=False, indent=2)
    log(f"written: {OUT}")
    log("=" * 60); log("SUMMARY"); log("=" * 60)
    log(f"{'scheme':<12} {'nFac':>4} {'V_WR':>7} {'V_ret':>8} {'T_WR':>7} {'T_ret':>8} {'T_trades':>8}")
    for label, r in results.items():
        log(f"{label:<12} {r['n_factors']:>4} {r['valid']['WR']:>7.4f} {r['valid']['mean_ret']:>8.4f} "
            f"{r['test']['WR']:>7.4f} {r['test']['mean_ret']:>8.4f} {r['test']['n_trades']:>8}")

if __name__ == '__main__':
    main()
