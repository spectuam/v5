#!/home/soso/v5/.venv/bin/python3
"""LightGBM多因子: 融资融券7因子训练分类器, 看能否提升选股
标签: T+10收益>全市场中位数=1(强势). 训练<2025, 测试>=2025. AUC+回测分位.
"""
import sys, os, sqlite3, time, json
from datetime import datetime
import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.metrics import roc_auc_score

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
TRAIN_END = '2025-01-01'
HORIZON = 10
TOPS = [10, 50]
OUT = os.path.expanduser('~/v5/margin_factor/margin_lightgbm_result.json')


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def t_return(code, date, db, H):
    rows = db.execute(
        "SELECT close FROM daily_kline WHERE code=? AND date > ? AND close>0 ORDER BY date LIMIT ?",
        (code, date + ' 23:59:59', H)).fetchall()
    buy = db.execute("SELECT close FROM daily_kline WHERE code=? AND date LIKE ?", (code, date + '%')).fetchone()
    if not buy or buy[0] <= 0 or len(rows) < H:
        return None
    return rows[-1][0] / buy[0] - 1


def main():
    log("=" * 60)
    log("LightGBM多因子: 融资融券7因子")
    log("=" * 60)
    db = sqlite3.connect(DB)
    md = pd.read_sql("""SELECT m.code, m.date, m.rz_ye, m.rz_buy, m.rq_yl, m.rq_sell FROM margin_detail m
        JOIN stock_info s ON m.code = s.symbol WHERE s.class='stock' AND m.rz_buy>0""", db)
    md['date'] = md['date'].str[:10]
    md = md.sort_values(['code', 'date'])
    md['RZ_buy_ratio'] = md['rz_buy'] / md['rz_ye']
    md['RZ_chg_1d'] = md.groupby('code')['rz_ye'].pct_change(1)
    md['RZ_chg_5d'] = md.groupby('code')['rz_ye'].pct_change(5)
    md['RZ_chg_20d'] = md.groupby('code')['rz_ye'].pct_change(20)
    md['RQ_chg_5d'] = md.groupby('code')['rq_yl'].pct_change(5)
    md['RQ_sell_ratio'] = md['rq_sell'] / md['rq_yl']
    dk = pd.read_sql("SELECT code, date, close FROM daily_kline WHERE close>0", db)
    dk['date'] = dk['date'].str[:10]
    md = md.merge(dk, on=['code', 'date'], how='left')
    md['rq_ye'] = md['rq_yl'] * md['close']
    md['RZ_RQ_ratio'] = md['rz_ye'] / md['rq_ye']
    md = md.sort_values(['code', 'date'])
    close = md[['code', 'date', 'close']].dropna().copy()
    close[f'fwd_{HORIZON}'] = close.groupby('code')['close'].shift(-HORIZON) / close['close'] - 1
    md = md.merge(close[['code', 'date', f'fwd_{HORIZON}']], on=['code', 'date'], how='left')
    md['label'] = md.groupby('date')[f'fwd_{HORIZON}'].transform(lambda x: (x > x.median()).astype(int))
    md = md.dropna(subset=['RZ_buy_ratio', 'RZ_chg_20d', 'RZ_RQ_ratio', f'fwd_{HORIZON}'])
    log(f"  {len(md)} rows")

    feat_cols = ['RZ_buy_ratio', 'RZ_chg_1d', 'RZ_chg_5d', 'RZ_chg_20d', 'RQ_chg_5d', 'RQ_sell_ratio', 'RZ_RQ_ratio']
    train = md[md.date < TRAIN_END]
    test = md[md.date >= TRAIN_END]
    log(f"train={len(train)} test={len(test)}")
    X_tr = train[feat_cols].fillna(0)
    y_tr = train['label']
    X_te = test[feat_cols].fillna(0)
    y_te = test['label']
    log("training LightGBM...")
    model = lgb.LGBMClassifier(n_estimators=100, max_depth=5, learning_rate=0.1, verbose=-1)
    model.fit(X_tr, y_tr)
    proba = model.predict_proba(X_te)[:, 1]
    auc = roc_auc_score(y_te, proba)
    log(f"AUC: {auc:.4f}")
    log("feature importance:")
    for f, imp in sorted(zip(feat_cols, model.feature_importances_), key=lambda x: -x[1]):
        log(f"  {f}: {imp}")

    test = test.copy()
    test['proba'] = proba
    all_codes = [r[0] for r in db.execute(
        "SELECT s.symbol FROM stock_info s WHERE s.class='stock' AND s.name NOT LIKE '%ST%' "
        "AND s.symbol NOT LIKE 'bj%'").fetchall()]
    results = {t: [] for t in TOPS}
    t0 = time.time()
    for di, date in enumerate(sorted(test['date'].unique())):
        day = test[test.date == date].sort_values('proba', ascending=False)
        mkt_rets = []
        for code in all_codes:
            r = t_return(code, date, db, HORIZON)
            if r is not None:
                mkt_rets.append(r)
        mkt_arr = np.array(mkt_rets)
        for top in TOPS:
            sel = day.head(top)
            for code in sel['code']:
                r = t_return(code, date, db, HORIZON)
                if r is None:
                    continue
                results[top].append(float((mkt_arr < r).mean()))
        if (di + 1) % 50 == 0:
            log(f"  {di+1} days [{time.time()-t0:.0f}s]")
    log("=" * 60)
    log("RESULT")
    log("=" * 60)
    log(f"AUC: {auc:.4f}")
    for t in TOPS:
        log(f"Top{t} return_pct: {np.mean(results[t]):.4f} n={len(results[t])}")
    log("(对比: 单因子0.51, 目标0.70)")
    out = {'auc': round(auc, 4), **{f'top{t}': round(float(np.mean(results[t])), 4) for t in TOPS}}
    json.dump(out, open(OUT, 'w'), indent=2, ensure_ascii=False)
    log(f"written: {OUT}")
    db.close()


if __name__ == '__main__':
    main()
