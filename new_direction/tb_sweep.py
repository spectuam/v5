#!/home/soso/v5/.venv/bin/python3
"""Triple Barrier 参数 sweep: K/门宽 几组, 看 AUC 趋势

采样 1000 股, 对每组 (K, SCALE) 重新标注 + 采样训练/测试 + 扩展特征 + LightGBM AUC。
特征(features_for_ext)固定, 标签随 K/SCALE 变。对比 AUC 找最佳参数。
CUSUM 后续(如果 sweep 没提升)。
"""
import sys, os, sqlite3, time, json
from datetime import datetime
import numpy as np
import pandas as pd
from phase2b_features import features_for_ext, build_mkt_cache, log
import lightgbm as lgb
from sklearn.metrics import roc_auc_score

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
VOL_WIN = 20
SAMPLE_STOCKS = 1000
TRAIN_END = '2019-01-01'
SAMPLE_POS = 3000
SAMPLE_NEG = 3000
OUT = '/home/soso/v5/tb_sweep_result.json'
# (K, SCALE): K 变化 + SCALE 变化
PARAMS = [(5, 1.5), (10, 1.5), (20, 1.5), (10, 1.0), (10, 2.0)]


def label_one(df, K, SCALE):
    n = len(df)
    if n < VOL_WIN + K + 1:
        return []
    ret = df['close'].pct_change()
    vol = ret.rolling(VOL_WIN).std().shift(1)
    high = df['high'].values
    low = df['low'].values
    close = df['close'].values
    dates = df['date'].values
    code = df['code'].iloc[0]
    out = []
    sqrtK = np.sqrt(K)
    vol_arr = vol.values
    for i in range(n - K):
        v = vol_arr[i]
        if v is None or np.isnan(v) or v <= 0:
            continue
        entry = close[i]
        upper = entry * (1 + SCALE * v * sqrtK)
        lower = entry * (1 - SCALE * v * sqrtK)
        fh = high[i + 1:i + 1 + K]
        fl = low[i + 1:i + 1 + K]
        up_idx = np.where(fh >= upper)[0]
        dn_idx = np.where(fl <= lower)[0]
        t_up = up_idx[0] if len(up_idx) else None
        t_dn = dn_idx[0] if len(dn_idx) else None
        if t_up is None and t_dn is None:
            lab = 0
        elif t_up is None:
            lab = -1
        elif t_dn is None:
            lab = 1
        else:
            lab = 1 if t_up <= t_dn else -1
        out.append({'code': code, 'date': str(dates[i])[:10], 'label': int(lab)})
    return out


def to_feats(df_, db, mkt_cache):
    feats = []
    for _, row in df_.iterrows():
        f = features_for_ext(row['code'], row['date'], db, mkt_cache)
        if f:
            f['label'] = 1 if row['label'] == 1 else 0
            feats.append(f)
    return pd.DataFrame(feats)


def sweep_one(K, SCALE, db, codes, mkt_cache):
    log(f"  K={K} SCALE={SCALE}: labeling {len(codes)} stocks...")
    t0 = time.time()
    labels = []
    for code in codes:
        df = pd.read_sql(
            "SELECT date,code,close,high,low FROM daily_kline WHERE code=? AND close>0 ORDER BY date",
            db, params=(code,))
        if len(df) >= VOL_WIN + K + 1:
            labels.extend(label_one(df, K, SCALE))
    if not labels:
        return None
    ldf = pd.DataFrame(labels)

    def sample_split(label, n, is_train):
        sub = ldf[ldf.label == label]
        sub = sub[sub.date < TRAIN_END] if is_train else sub[sub.date >= TRAIN_END]
        return sub.sample(n=min(n, len(sub)), random_state=42)

    tr_pos = sample_split(1, SAMPLE_POS, True)
    tr_neg = pd.concat([sample_split(0, SAMPLE_NEG // 2, True),
                        sample_split(-1, SAMPLE_NEG // 2, True)])
    te_pos = sample_split(1, SAMPLE_POS, False)
    te_neg = pd.concat([sample_split(0, SAMPLE_NEG // 2, False),
                        sample_split(-1, SAMPLE_NEG // 2, False)])

    log(f"    feats train(pos={len(tr_pos)}) test(pos={len(te_pos)})...")
    tr = pd.concat([to_feats(tr_pos, db, mkt_cache), to_feats(tr_neg, db, mkt_cache)])
    te = pd.concat([to_feats(te_pos, db, mkt_cache), to_feats(te_neg, db, mkt_cache)])
    if len(tr) < 100 or len(te) < 100:
        return None
    feat_cols = [c for c in tr.columns if c != 'label']
    X_tr = tr[feat_cols].fillna(0)
    y_tr = tr['label']
    X_te = te[feat_cols].fillna(0)
    y_te = te['label']
    model = lgb.LGBMClassifier(n_estimators=100, max_depth=5, learning_rate=0.1, verbose=-1)
    model.fit(X_tr, y_tr)
    proba = model.predict_proba(X_te)[:, 1]
    auc = roc_auc_score(y_te, proba)
    dist = ldf.label.value_counts().to_dict()
    log(f"    AUC={auc:.4f} dist={dist} [{time.time()-t0:.0f}s]")
    return {'K': K, 'SCALE': SCALE, 'auc': round(auc, 4), 'dist': {int(k): int(v) for k, v in dist.items()}}


def main():
    log("=" * 60)
    log("TB sweep: K/门宽 参数 (5组)")
    log("=" * 60)
    db = sqlite3.connect(DB)
    mkt_cache = build_mkt_cache(db)
    codes = [r[0] for r in db.execute(
        "SELECT s.symbol FROM stock_info s WHERE s.class='stock' AND s.name NOT LIKE '%ST%' "
        "AND s.symbol NOT LIKE 'bj%' ORDER BY RANDOM() LIMIT ?", (SAMPLE_STOCKS,)).fetchall()]
    log(f"sampled {len(codes)} stocks (固定, 所有组共用)")

    results = []
    for K, SCALE in PARAMS:
        r = sweep_one(K, SCALE, db, codes, mkt_cache)
        if r:
            results.append(r)
    log("=" * 60)
    log("SWEEP RESULT")
    log("=" * 60)
    log(f"{'K':>4} {'SCALE':>6} {'AUC':>8}  dist")
    for r in results:
        log(f"{r['K']:>4} {r['SCALE']:>6} {r['auc']:>8}  {r['dist']}")
    json.dump(results, open(OUT, 'w'), indent=2, ensure_ascii=False)
    log(f"written: {OUT}")
    db.close()


if __name__ == '__main__':
    main()
