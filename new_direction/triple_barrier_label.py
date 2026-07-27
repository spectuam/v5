#!/home/soso/v5/.venv/bin/python3
"""Phase 1: Triple Barrier 标注（结果驱动模式捕捉）

对每只股票每天，用波动率缩放的三元障碍打标签 +1(强势)/0(平庸)/-1(弱势)。
- 上门: entry × (1 + 1.5 × vol × sqrt(K))
- 下门: entry × (1 - 1.5 × vol × sqrt(K))
- 右门: K 天后没碰上下门 = 0
- vol = 过去 VOL_WIN 天日收益 std, shift(1) 防前视

流式按股票（每次1只，存 sqlite），内存低。断点续传。
"""
import sys, os, sqlite3, time
from datetime import datetime
import numpy as np
import pandas as pd

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
K = 10          # 右门天数
VOL_WIN = 20    # 波动率窗口
VOL_SCALE = 1.5  # 门宽波动率倍数
LOG_FILE = os.path.expanduser('~/ading/logs/triple_barrier.log')
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)


def log(m):
    line = f"[{datetime.now():%H:%M:%S}] {m}"
    print(line, flush=True)
    with open(LOG_FILE, 'a') as f:
        f.write(line + "\n")


def label_one(df):
    """df: 单只股票 date/code/close/high/low (已按date排序), 返回 [(date, code, label)]"""
    n = len(df)
    if n < VOL_WIN + K + 1:
        return []
    ret = df['close'].pct_change()
    vol = ret.rolling(VOL_WIN).std().shift(1)  # 过去 VOL_WIN 天, 不含当日
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
        upper = entry * (1 + VOL_SCALE * v * sqrtK)
        lower = entry * (1 - VOL_SCALE * v * sqrtK)
        fh = high[i + 1:i + 1 + K]
        fl = low[i + 1:i + 1 + K]
        up_idx = np.where(fh >= upper)[0]
        dn_idx = np.where(fl <= lower)[0]
        t_up = up_idx[0] if len(up_idx) else None
        t_dn = dn_idx[0] if len(dn_idx) else None
        if t_up is None and t_dn is None:
            label = 0
        elif t_up is None:
            label = -1
        elif t_dn is None:
            label = 1
        else:
            label = 1 if t_up <= t_dn else -1
        out.append((code, str(dates[i])[:10], int(label)))
    return out


def main():
    log("=" * 60)
    log(f"Phase 1: Triple Barrier K={K} VOL_WIN={VOL_WIN} SCALE={VOL_SCALE}")
    log("=" * 60)
    db = sqlite3.connect(DB)
    db.execute("""CREATE TABLE IF NOT EXISTS triple_barrier_labels (
        code TEXT, date TEXT, label INTEGER, PRIMARY KEY(code, date))""")
    db.commit()

    # 断点续传: 已标的 code
    done = set(r[0] for r in db.execute("SELECT DISTINCT code FROM triple_barrier_labels"))
    codes = [r[0] for r in db.execute("""
        SELECT s.symbol FROM stock_info s
        WHERE s.class='stock' AND s.name NOT LIKE '%ST%' AND s.symbol NOT LIKE 'bj%'
        ORDER BY s.symbol""").fetchall()]
    todo = [c for c in codes if c not in done]
    log(f"total={len(codes)} done={len(done)} todo={len(todo)}")

    t0 = time.time()
    n_labeled = 0
    for i, code in enumerate(todo):
        df = pd.read_sql(
            "SELECT date, code, close, high, low FROM daily_kline "
            "WHERE code=? AND close>0 ORDER BY date",
            db, params=(code,))
        if len(df) < VOL_WIN + K + 1:
            continue
        rows = label_one(df)
        if rows:
            db.executemany("INSERT OR REPLACE INTO triple_barrier_labels VALUES (?,?,?)", rows)
            n_labeled += len(rows)
        if (i + 1) % 200 == 0:
            db.commit()
            log(f"  {i+1}/{len(todo)} (+{len(done)} done) samples={n_labeled} [{time.time()-t0:.0f}s]")
    db.commit()
    log(f"labeling done: {n_labeled} samples added [{time.time()-t0:.0f}s]")

    # 分布
    dist = db.execute(
        "SELECT label, COUNT(*) FROM triple_barrier_labels GROUP BY label ORDER BY label"
    ).fetchall()
    total = sum(r[1] for r in dist)
    log("=" * 60)
    log(f"DISTRIBUTION (total={total})")
    log("=" * 60)
    for lab, cnt in dist:
        log(f"  label {lab}: {cnt} ({cnt/total:.1%})")
    db.close()


if __name__ == '__main__':
    main()
