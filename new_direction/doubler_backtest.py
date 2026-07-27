#!/home/soso/v5/.venv/bin/python3
"""翻倍股分类器回测: 训练(date<2019), 测试期每天选Top5, 算收益分位
测试期 2026-04~2026-07(3个月控时间). 每天所有股票特征+打分+Top5,
T+20收益 + 全市场分位. 目标平均分位>0.70.
"""
import sys, os, sqlite3, time, json, gc
from datetime import datetime
import numpy as np
import pandas as pd
from phase2b_features import features_for_ext, build_mkt_cache, log
import lightgbm as lgb

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
TRAIN_END = '2019-01-01'
TEST_START = '2026-04-01'
TEST_END = '2026-07-14'
HORIZON = 20
SAMPLE_TRAIN = 5000
OUT = '/home/soso/v5/doubler_backtest_result.json'


def train_model(db, mkt_cache):
    pos = db.execute("SELECT code, date FROM doublers WHERE date < ? ORDER BY RANDOM() LIMIT ?",
                     (TRAIN_END, SAMPLE_TRAIN)).fetchall()
    neg = db.execute("""SELECT d.code, d.date FROM daily_kline d JOIN stock_info s ON d.code=s.symbol
        WHERE s.class='stock' AND s.name NOT LIKE '%ST%' AND d.code NOT LIKE 'bj%' AND d.close>0 AND d.date < ?
        AND NOT EXISTS (SELECT 1 FROM doublers db WHERE db.code=d.code AND db.date=d.date)
        ORDER BY RANDOM() LIMIT ?""", (TRAIN_END, SAMPLE_TRAIN)).fetchall()

    def feats(rows, lab):
        fs = []
        for code, date in rows:
            f = features_for_ext(code, str(date)[:10], db, mkt_cache)
            if f:
                f['label'] = lab
                fs.append(f)
        return pd.DataFrame(fs)

    train = pd.concat([feats(pos, 1), feats(neg, 0)], ignore_index=True)
    feat_cols = [c for c in train.columns if c != 'label']
    model = lgb.LGBMClassifier(n_estimators=100, max_depth=5, learning_rate=0.1, verbose=-1)
    model.fit(train[feat_cols].fillna(0), train['label'])
    return model, feat_cols


def t20_return(code, date, db):
    """T+20 收益 (daily_kline.date 格式 'YYYY-MM-DD 00:00:00')"""
    rows = db.execute("SELECT close FROM daily_kline WHERE code=? AND date > ? AND close>0 ORDER BY date LIMIT ?",
                      (code, date + ' 23:59:59', HORIZON)).fetchall()
    if len(rows) < HORIZON:
        return None
    buy = db.execute("SELECT close FROM daily_kline WHERE code=? AND date LIKE ?", (code, date + '%')).fetchone()
    if not buy or buy[0] <= 0:
        return None
    return rows[-1][0] / buy[0] - 1


def main():
    log("=" * 60)
    log("翻倍股分类器回测")
    log("=" * 60)
    db = sqlite3.connect(DB)
    mkt_cache = build_mkt_cache(db)
    log("training classifier...")
    model, feat_cols = train_model(db, mkt_cache)
    log("trained")

    dates = [r[0] for r in db.execute(
        "SELECT DISTINCT date FROM daily_kline WHERE date>=? AND date<=? ORDER BY date",
        (TEST_START, TEST_END)).fetchall()]
    codes = [r[0] for r in db.execute(
        "SELECT s.symbol FROM stock_info s WHERE s.class='stock' AND s.name NOT LIKE '%ST%' "
        "AND s.symbol NOT LIKE 'bj%'").fetchall()]
    log(f"test {len(dates)} days, {len(codes)} stocks")

    daily_pcts = []
    t0 = time.time()
    for di, date in enumerate(dates):
        ds = str(date)[:10]
        scored = []
        mkt_rets = []
        for code in codes:
            f = features_for_ext(code, ds, db, mkt_cache)
            if not f:
                continue
            r = t20_return(code, ds, db)
            if r is None:
                continue
            x = [f.get(c, 0) for c in feat_cols]
            scored.append((code, x, r))
            mkt_rets.append(r)
        if len(scored) < 5:
            continue
        X = pd.DataFrame([s[1] for s in scored], columns=feat_cols)
        proba = model.predict_proba(X)[:, 1]
        top_idx = np.argsort(proba)[::-1][:5]
        top_rets = [scored[i][2] for i in top_idx]
        mkt_arr = np.array(mkt_rets)
        for tr in top_rets:
            pct = float((mkt_arr < tr).mean())
            daily_pcts.append(pct)
        if (di + 1) % 5 == 0:
            log(f"  {di+1}/{len(dates)} avg_pct={np.mean(daily_pcts):.4f} [{time.time()-t0:.0f}s]")

    avg_pct = float(np.mean(daily_pcts)) if daily_pcts else 0.0
    log("=" * 60)
    log("RESULT")
    log("=" * 60)
    log(f"avg return_percentile: {avg_pct:.4f} (目标>0.70)")
    log(f"n_picks: {len(daily_pcts)}")
    out = {'avg_return_percentile': round(avg_pct, 4), 'n_picks': len(daily_pcts),
           'horizon': HORIZON, 'test_period': f'{TEST_START}~{TEST_END}'}
    json.dump(out, open(OUT, 'w'), indent=2, ensure_ascii=False)
    log(f"written: {OUT}")
    db.close()


if __name__ == '__main__':
    main()
