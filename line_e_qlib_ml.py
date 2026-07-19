#!/home/soso/v5/.venv/bin/python3
"""Line E — Qlib + LightGBM ML 支路

Train (2006-2015) → LightGBM训练
Valid (2016-2020) → 回测验证

防泄漏: 训练只看 Train 期, 验证只看 Valid 期
用法: ~/v5/.venv/bin/python3 ~/v5/line_e_qlib_ml.py
"""
import sys, os, time, json, gc, warnings, sqlite3
warnings.filterwarnings('ignore')

sys.path.insert(0, '/home/soso/trading-strategy')
sys.path.insert(0, '/home/soso/.local/lib/python3.12/site-packages/src/factors')
sys.path.insert(0, '/home/soso/v5')

import numpy as np
import pandas as pd
from datetime import datetime
from pathlib import Path

TDX_DB = os.path.expanduser("~/ading/db/tdx_stock_data.db")
QLIB_DIR = os.path.expanduser("~/ading/data/qlib_line_e/bin")
OUT_DIR = os.path.expanduser("~/ading/data/reports")
QLIB_ROOT = os.path.expanduser("~/qlib")  # Qlib source, for scripts

# Time splits
TRAIN_START = '2006-01-01'
TRAIN_END   = '2015-12-31'
VALID_START = '2016-01-01'
VALID_END   = '2020-12-31'

def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)

# ═══════════════════════════════════════════
# Step 1: 构建 Qlib 二进制数据
# ═══════════════════════════════════════════
def build_qlib_binary():
    log("Step 1: Building Qlib binary from TDX daily_kline...")
    os.makedirs(os.path.join(QLIB_DIR, "calendars"), exist_ok=True)
    os.makedirs(os.path.join(QLIB_DIR, "instruments"), exist_ok=True)
    os.makedirs(os.path.join(QLIB_DIR, "features"), exist_ok=True)

    db = sqlite3.connect(TDX_DB)

    # 取 Train+Valid 期数据，过滤 ST + 北交所
    df = pd.read_sql("""
        SELECT d.code, d.date, d.open, d.high, d.low, d.close, d.volume, d.amount
        FROM daily_kline d
        JOIN stock_info s ON d.code = s.symbol
        WHERE d.date >= ? AND date(d.date) <= ?
          AND d.close > 0 AND d.open > 0
          AND s.class = 'stock'
          AND s.name NOT LIKE '%%ST%%'
          AND d.code NOT LIKE 'bj%%'
        ORDER BY d.date, d.code
    """, db, params=(TRAIN_START, VALID_END))
    db.close()

    df['date'] = pd.to_datetime(df['date'])
    dates = sorted(df['date'].unique())
    codes = sorted(df['code'].unique())
    log(f"  {len(df):,} rows, {len(dates)} days, {len(codes)} codes")
    log(f"  Range: {dates[0].date()} ~ {dates[-1].date()}")

    # Calendar
    cal_path = os.path.join(QLIB_DIR, "calendars", "day.txt")
    with open(cal_path, "w") as f:
        for d in dates:
            f.write(d.strftime("%Y-%m-%d") + "\n")

    # Instruments
    inst_path = os.path.join(QLIB_DIR, "instruments", "all.txt")
    with open(inst_path, "w") as f:
        for c in codes:
            f.write(c + "\t1\n")  # tab-separated: code, start_flag

    # Features: one binary file per stock, columns: [date_idx, open, high, low, close, volume, vwap, amount]
    log(f"  Writing {len(codes)} feature files...")
    date_map = {d: i for i, d in enumerate(dates)}
    FEATURE_COLS = ['open', 'high', 'low', 'close', 'volume', 'vwap', 'amount']
    N_FEATURES = 7

    for ci, code in enumerate(codes):
        sdf = df[df['code'] == code].set_index('date')
        arr = np.zeros((len(dates), 1 + N_FEATURES), dtype='<f')
        for di, d in enumerate(dates):
            if d in sdf.index:
                row = sdf.loc[d]
                arr[di, 0] = di  # date index
                for fi, col in enumerate(FEATURE_COLS):
                    val = row[col] if col != 'vwap' else (row['amount'] / row['volume'] if row['volume'] > 0 else 0)
                    arr[di, 1 + fi] = val if not np.isnan(val) and not np.isinf(val) else 0

        fpath = os.path.join(QLIB_DIR, "features", code)
        os.makedirs(os.path.dirname(fpath), exist_ok=True)
        os.makedirs(os.path.join(fpath, "day"), exist_ok=True)
        arr.astype('<f').tofile(os.path.join(fpath, "day", "day_00.bin"))

        if (ci + 1) % 1000 == 0:
            log(f"    [{ci+1}/{len(codes)}]")

    log(f"  Binary data written to {QLIB_DIR}")

# ═══════════════════════════════════════════
# Step 2: Qlib 初始化 + Alpha158
# ═══════════════════════════════════════════
def train_and_backtest():
    log("Step 2: Qlib + LightGBM training...")

    import qlib
    from qlib.config import C
    from qlib.data import D
    from qlib.data.dataset import DatasetH
    from qlib.data.dataset.handler import DataHandlerLP
    from qlib.contrib.model.gbdt import LGBModel
    from qlib.contrib.data.handler import Alpha158

    provider_uri = str(Path(QLIB_DIR).resolve())
    qlib.init(provider_uri=provider_uri, region='cn')

    # 确认数据可用
    instruments = D.instruments(market='all')
    all_codes = D.list_instruments(instruments=instruments, as_list=True)
    log(f"  {len(all_codes)} instruments loaded")

    # Alpha158 handler: Train on 2006-2015
    handler_conf = {
        "start_time": TRAIN_START,
        "end_time": VALID_END,
        "fit_start_time": TRAIN_START,
        "fit_end_time": TRAIN_END,
        "instruments": "all",
    }
    h = Alpha158(**handler_conf)

    # Dataset
    dataset_conf = {
        "class": "DatasetH",
        "module_path": "qlib.data.dataset",
        "kwargs": {
            "handler": h,
            "segments": {
                "train": (TRAIN_START, TRAIN_END),
                "valid": (VALID_START, VALID_END),
                "test": (VALID_START, VALID_END),  # 不碰真实Test
            },
        },
    }
    dataset = DatasetH(**dataset_conf["kwargs"])

    # LightGBM
    model = LGBModel(
        loss="mse",
        num_leaves=64,
        learning_rate=0.05,
        n_estimators=500,
        early_stopping_rounds=50,
        num_threads=4,
    )

    log("  Training LightGBM...")
    t0 = time.time()
    model.fit(dataset)
    log(f"  Training done ({time.time()-t0:.0f}s)")

    # Predict on Valid
    log(f"  Predicting on Valid ({VALID_START} ~ {VALID_END})...")
    pred = model.predict(dataset, segment="valid")
    log(f"  Predictions: {len(pred)} records")

    # IC
    from scipy.stats import spearmanr
    pred_df = pred.copy()
    if 'score' in pred_df.columns and 'label' in pred_df.columns:
        ic, pval = spearmanr(pred_df['score'], pred_df['label'])
        log(f"  Valid IC: {ic:.4f} (p={pval:.4f})")

    # 简单 Top5 回测
    # 按日期分组, 每天选 top5, 算 label 均值
    pred_df['date'] = pred_df.index.get_level_values('datetime') if hasattr(pred_df.index, 'get_level_values') else None
    # 尝试从 multi-index 提取
    try:
        dates = pred_df.index.get_level_values('datetime')
    except:
        dates = None

    # 简化: 对全部预测排序取 top 5%
    n_top = max(5, len(pred_df) // 100)
    top = pred_df.nlargest(n_top, 'score') if 'score' in pred_df.columns else pred_df.head(5)
    mean_label = top['label'].mean() if 'label' in top.columns else 0
    wr = (top['label'] > 0).mean() if 'label' in top.columns else 0

    result = {
        'line': 'E',
        'model': 'LightGBM+Alpha158',
        'train_period': f'{TRAIN_START}~{TRAIN_END}',
        'valid_period': f'{VALID_START}~{VALID_END}',
        'n_codes': len(all_codes),
        'valid_ic': round(float(ic) if 'ic' in dir() else 0, 4),
        'top5_mean_return': round(float(mean_label), 4),
        'top5_wr': round(float(wr), 4),
    }

    out_path = os.path.join(OUT_DIR, 'line_e_results.json')
    with open(out_path, 'w') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    log(f"  Results saved to {out_path}")
    log(f"  {json.dumps(result, ensure_ascii=False, indent=2)}")


if __name__ == '__main__':
    log("=" * 60)
    log("Line E — Qlib ML Pipeline")
    log(f"  Train: {TRAIN_START} ~ {TRAIN_END}")
    log(f"  Valid: {VALID_START} ~ {VALID_END}")
    log("=" * 60)

    build_qlib_binary()
    gc.collect()

    try:
        train_and_backtest()
    except Exception as e:
        log(f"ERROR: {e}")
        import traceback
        traceback.print_exc()

        # Fallback: 写一个错误结果
        result = {
            'line': 'E',
            'status': 'error',
            'error': str(e),
            'train_period': f'{TRAIN_START}~{TRAIN_END}',
            'valid_period': f'{VALID_START}~{VALID_END}',
        }
        out_path = os.path.join(OUT_DIR, 'line_e_results.json')
        with open(out_path, 'w') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    finally:
        log("Line E complete.")
