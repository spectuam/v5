#!/home/soso/v5/.venv/bin/python3
"""forward paper trading 跟踪（#4 唯一真未来验证）

解析 daily_pick timer 产出的 picks_v5_*.md，算每 pick 的 realized T+5 等权收益，
积累 forward SR vs #3 基线 0.40 -> 诚实衰减（文献 backtest1.26 vs live0.31，4.1× 预期）。

forward = 唯一对未来有验证效力（CPCV/backtest 同历史分布内）。
当前样本极小（~14天起点），SR 无统计意义，仅作起点+持续积累机制。
"""
import os, re, glob, json, sqlite3
from datetime import datetime
import numpy as np

PICKS_DIR = os.path.expanduser("~/ading/data/reports")
DB = os.path.expanduser("~/ading/db/tdx_stock_data.db")
OUT = os.path.expanduser("~/v5/branches/strategy_factory/forward_track_result.json")
HORIZON = 5
BASELINE_SR = 0.40  # #3 静态因子 backtest 基线


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def parse_picks(md_path):
    """从 picks_v5_YYYY-MM-DD.md 解析日期 + Top5 代码。"""
    fn = os.path.basename(md_path)
    m = re.search(r'picks_v5_(\d{4}-\d{2}-\d{2})', fn)
    if not m:
        return None, []
    date_str = m.group(1)
    codes = []
    with open(md_path) as f:
        for line in f:
            m2 = re.search(r'^\d+\s+\S+\s+(s[hz]\d{6})\s+[\d.]+', line)
            if m2:
                codes.append(m2.group(1))
    return date_str, codes


def realized_t5(db, code, date_str, horizon=HORIZON):
    """date_str 当日 close 买入，后 horizon 交易日 close 卖出收益。无足够数据返 None。"""
    buy = db.execute("SELECT close FROM daily_kline WHERE code=? AND date LIKE ? AND close>0",
                     (code, date_str + '%')).fetchone()
    if not buy or buy[0] <= 0:
        return None
    rows = db.execute("SELECT close FROM daily_kline WHERE code=? AND date > ? AND close>0 ORDER BY date LIMIT ?",
                      (code, date_str + ' 23:59:59', horizon)).fetchall()
    if len(rows) < horizon:
        return None
    return rows[-1][0] / buy[0] - 1


def main():
    log("=" * 60); log("forward paper trading 跟踪"); log("=" * 60)
    md_files = sorted(glob.glob(os.path.join(PICKS_DIR, "picks_v5_*.md")))
    log(f"发现 {len(md_files)} 个 picks 文件（{os.path.basename(md_files[0]) if md_files else '-'} ~ {os.path.basename(md_files[-1]) if md_files else '-'}）")

    db = sqlite3.connect(DB)
    max_date = db.execute("SELECT MAX(date) FROM daily_kline").fetchone()[0][:10]
    log(f"DB 最新交易日: {max_date}")

    per_date = []
    for md in md_files:
        date_str, codes = parse_picks(md)
        if not codes:
            continue
        rets = []
        for c in codes:
            r = realized_t5(db, c, date_str)
            if r is not None:
                rets.append(r)
        realized = float(np.mean(rets)) if rets else None
        per_date.append({
            'date': date_str, 'n_picks': len(codes), 'n_realized': len(rets),
            'realized_t5': round(realized, 4) if realized is not None else None,
            'codes': codes,
        })
        status = f"SR{realized:.3f}" if realized is not None else "未到期(T+5未达)"
        log(f"  {date_str}: {len(codes)}只 -> {len(rets)}只realized, {status}")

    realized_rets = [d['realized_t5'] for d in per_date if d['realized_t5'] is not None]
    arr = np.array(realized_rets, float) if realized_rets else np.array([])
    n_real = len(arr)
    sr = float(arr.mean() / arr.std() * np.sqrt(52)) if n_real > 1 and arr.std() > 0 else 0
    annual = float(arr.mean() * 52) if n_real else 0

    # market_eq 同期基准（判 alpha vs beta）
    realized_dates = [d['date'] for d in per_date if d['realized_t5'] is not None]
    all_codes = [r[0] for r in db.execute(
        "SELECT s.symbol FROM stock_info s WHERE s.class='stock' AND s.name NOT LIKE '%ST%' AND s.symbol NOT LIKE 'bj%'").fetchall()]
    mkt_rets = []
    for ds in realized_dates:
        rs = [realized_t5(db, c, ds) for c in all_codes]
        rs = [r for r in rs if r is not None]
        mkt_rets.append(float(np.mean(rs)) if rs else None)
    mkt_arr = np.array([r for r in mkt_rets if r is not None], float)
    mkt_sr = float(mkt_arr.mean() / mkt_arr.std() * np.sqrt(52)) if len(mkt_arr) > 1 and mkt_arr.std() > 0 else 0
    excess = float(arr.mean() - mkt_arr.mean()) if len(arr) and len(mkt_arr) else 0
    db.close()

    log("-" * 60)
    log(f"forward daily_pick: {n_real}日, SR {sr:.3f}, 年化{annual:.2%}, 均值{arr.mean() if n_real else 0:.4f}")
    log(f"forward market_eq : {len(mkt_arr)}日, SR {mkt_sr:.3f}, 均值{mkt_arr.mean() if len(mkt_arr) else 0:.4f}")
    log(f"超额(daily-market): {excess:.4f}/日 -> {'daily 超额' if excess>0.01 else 'daily 跑输' if excess<-0.01 else '约同'}（小样本无统计意义）")
    if n_real < 20:
        log(f"注: 样本极小({n_real}日)，SR 无统计意义，仅作 forward 起点；需数月积累")

    out = {
        'run_at': datetime.now().isoformat(),
        'method': f'daily_pick picks_v5_*.md realized T+{HORIZON} 等权 + market_eq 同期基准',
        'n_pick_dates': len(per_date), 'n_realized': n_real,
        'sharpe': round(sr, 3), 'annual': round(annual, 4), 'mean': round(float(arr.mean()), 4) if n_real else 0,
        'market_eq_sharpe': round(mkt_sr, 3), 'market_eq_mean': round(float(mkt_arr.mean()), 4) if len(mkt_arr) else 0,
        'excess_daily_vs_market': round(excess, 4),
        'vs_baseline_040': round(sr, 3),
        'per_date': per_date,
        'caveat': f'forward=唯一真未来验证; 样本{n_real}日极小SR无统计意义; market_eq同期SR{mkt_sr:.1f}亦荒谬=强反弹期; 需数月积累; 建议weekly timer',
    }
    json.dump(out, open(OUT, 'w'), indent=2, ensure_ascii=False, default=float)
    log(f"written: {OUT}")


if __name__ == '__main__':
    main()
