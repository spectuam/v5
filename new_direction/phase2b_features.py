#!/home/soso/v5/.venv/bin/python3
"""Phase 2b: 扩展特征工程

加 T-10/20/30 量价多窗口 + 大盘环境(等权ret/波动率/上涨股比例) + 时间(星期/月份)。
采样 +1/-1 各 1 万, t 检验对比, 为 Phase 3a 重跑提供扩展特征集。
大盘用 SQL 聚合预算(不 pivot 全数据, 内存安全)。
行业/38 因子待加。
"""
import sys, os, sqlite3, time
from datetime import datetime
from math import erf, sqrt
from datetime import datetime as dt
import numpy as np
import pandas as pd

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
SAMPLE_N = 10000
OUT = '/home/soso/v5/phase2b_features_result.json'


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def build_mkt_cache(db):
    """SQL 聚合预算大盘日序列: 等权ret, 上涨股比例。vol 在 python 算。"""
    log("building market cache (SQL)...")
    rows = db.execute("""
        SELECT date, AVG((close - prev_close)/prev_close) as mkt_ret,
               SUM(CASE WHEN close > prev_close THEN 1.0 ELSE 0 END)/COUNT(*) as up_ratio
        FROM (
            SELECT code, date, close,
                   LAG(close) OVER (PARTITION BY code ORDER BY date) as prev_close
            FROM daily_kline WHERE close > 0
        ) WHERE prev_close IS NOT NULL AND prev_close > 0
        GROUP BY date ORDER BY date
    """).fetchall()
    cache = {}
    mkt_rets = []
    dates = []
    for d, mr, ur in rows:
        ds = str(d)[:10]
        mr = float(mr) if mr is not None else 0.0
        ur = float(ur) if ur is not None else 0.0
        cache[ds] = {'mkt_ret': mr, 'up_ratio': ur}
        mkt_rets.append(mr)
        dates.append(ds)
    # mkt_vol: 20 天滚动 std
    s = pd.Series(mkt_rets)
    vol = s.rolling(20).std()
    for i, d in enumerate(dates):
        cache[d]['mkt_vol'] = float(vol.iloc[i]) if not np.isnan(vol.iloc[i]) else 0.0
    log(f"  market cache: {len(cache)} days")
    return cache


def features_for_ext(code, date, db, mkt_cache):
    rows = db.execute("""
        SELECT high, low, close, volume FROM daily_kline
        WHERE code=? AND date < ? AND close>0 ORDER BY date DESC LIMIT 30
    """, (code, date)).fetchall()
    if len(rows) < 30:
        return None
    rows = rows[::-1]
    close = np.array([r[2] for r in rows], float)
    high = np.array([r[0] for r in rows], float)
    low = np.array([r[1] for r in rows], float)
    volume = np.array([r[3] for r in rows], float)
    rets = np.diff(close) / close[:-1]
    feats = {}
    # 量价多窗口
    for W in [10, 20, 30]:
        c = close[-W:]
        r = rets[-(W - 1):]
        h = high[-W:]
        l = low[-W:]
        feats[f'cum_ret_{W}'] = float(c[-1] / c[0] - 1)
        feats[f'ret_std_{W}'] = float(r.std()) if len(r) > 1 else 0.0
        feats[f'max_up_{W}'] = float(r.max()) if len(r) > 0 else 0.0
        feats[f'up_ratio_{W}'] = float((r > 0).mean()) if len(r) > 0 else 0.0
        feats[f'amp_{W}'] = float(((h - l) / c).mean())
    # T-10 细节
    feats['ret_1d'] = float(rets[-1])
    feats['ret_3d'] = float(close[-1] / close[-4] - 1)
    vn = volume[-9:]
    feats['vol_price_corr_10'] = float(np.corrcoef(rets[-9:], vn / vn.mean() if vn.mean() > 0 else vn)[0, 1]) if np.std(vn) > 0 else 0.0
    feats['vol_change_10'] = float(np.diff(volume[-10:]).mean() / volume[-10:-1].mean()) if volume[-10:-1].mean() > 0 else 0.0
    # 大盘
    mkt = mkt_cache.get(date, {})
    feats['mkt_ret'] = mkt.get('mkt_ret', 0.0)
    feats['mkt_vol'] = mkt.get('mkt_vol', 0.0)
    feats['up_ratio_mkt'] = mkt.get('up_ratio', 0.0)
    # 时间
    try:
        d = dt.strptime(date, '%Y-%m-%d')
        feats['weekday'] = float(d.weekday())
        feats['month'] = float(d.month)
    except Exception:
        feats['weekday'] = 0.0
        feats['month'] = 0.0
    return feats


def sample_features(label, n, db, mkt_cache):
    rows = db.execute(
        "SELECT code, date FROM triple_barrier_labels WHERE label=? ORDER BY RANDOM() LIMIT ?",
        (label, n)).fetchall()
    feats = []
    for i, (code, date) in enumerate(rows):
        f = features_for_ext(code, date, db, mkt_cache)
        if f:
            f['label'] = label
            feats.append(f)
        if (i + 1) % 2000 == 0:
            log(f"  label {label}: {i+1}/{len(rows)}")
    return pd.DataFrame(feats)


def main():
    log("=" * 60)
    log("Phase 2b: 扩展特征 (量价多窗口 + 大盘 + 时间)")
    log("=" * 60)
    db = sqlite3.connect(DB)
    mkt_cache = build_mkt_cache(db)
    t0 = time.time()
    log("sampling +1...")
    pos = sample_features(1, SAMPLE_N, db, mkt_cache)
    log("sampling -1...")
    neg = sample_features(-1, SAMPLE_N, db, mkt_cache)
    log(f"pos={len(pos)} neg={len(neg)} [{time.time()-t0:.0f}s]")

    feat_cols = [c for c in pos.columns if c != 'label']
    results = []
    for feat in feat_cols:
        p = pos[feat].dropna()
        n = neg[feat].dropna()
        if len(p) < 10 or len(n) < 10:
            continue
        diff = p.mean() - n.mean()
        se = np.sqrt(p.var() / len(p) + n.var() / len(n))
        t = diff / se if se > 0 else 0
        pval = 2 * (1 - 0.5 * (1 + erf(abs(t) / sqrt(2))))
        results.append({
            'feat': feat, 'pos_mean': round(p.mean(), 5), 'neg_mean': round(n.mean(), 5),
            'diff': round(diff, 5), 't': round(t, 2), 'pval': round(pval, 6),
            'sig': pval < 0.01,
        })
    df = pd.DataFrame(results).sort_values('pval')
    log("=" * 60)
    log("FEATURE DIFFERENCES (sorted by pval)")
    log("=" * 60)
    log(f"{'feat':<22}{'pos':>10}{'neg':>10}{'diff':>10}{'t':>8}{'pval':>10}")
    for _, r in df.iterrows():
        log(f"{r['feat']:<22}{r['pos_mean']:>10}{r['neg_mean']:>10}{r['diff']:>10}"
            f"{r['t']:>8}{r['pval']:>10} {'***' if r['sig'] else ''}")
    df.to_json(OUT, orient='records', indent=2, force_ascii=False)
    log(f"written: {OUT}")
    db.close()


if __name__ == '__main__':
    main()
