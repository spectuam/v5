#!/home/soso/v5/.venv/bin/python3
"""v5 每日荐股 — 14:50 运行

1. 构建 90 天面板 (daily_kline 历史 + Sina 今日)
2. 加载本周因子列表
3. 算因子值 → 等权复合排名 → Top5
4. 飞书推送

用法:
  python3 daily_pick_v5.py              # 实时
  python3 daily_pick_v5.py --test       # 最近交易日模拟
"""
import sys, os, re, json, time, sqlite3
from datetime import datetime, date, timedelta
import requests
import numpy as np
import pandas as pd

sys.path.insert(0, '/home/soso/trading-strategy')
sys.path.insert(0, '/home/soso/.local/lib/python3.12/site-packages/src/factors')
sys.path.insert(0, '/home/soso/v5')

from factor_zoo_adapter import compute_alpha

DB = os.path.expanduser("~/ading/db/tdx_stock_data.db")
FACTOR_JSON = os.path.expanduser("~/ading/data/reports/factor_decay_results_tdx.json")
REPORT_DIR = os.path.expanduser("~/ading/data/reports")
LOG_FILE = os.path.expanduser("~/ading/logs/daily_pick_v5.log")
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
os.makedirs(REPORT_DIR, exist_ok=True)

LOOKBACK = 90
TOP_K = 5
LIMIT_UP = 9.8

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


# ── 1. 加载本周因子 ──
def load_factors():
    if not os.path.exists(FACTOR_JSON):
        log(f"FATAL: {FACTOR_JSON} not found")
        sys.exit(1)
    with open(FACTOR_JSON) as f:
        data = json.load(f)
    # 用所有正交因子
    ortho = data.get('all_orthogonal', [])
    qualified = [o for o in ortho if o.get('status') in ('confirmed','degraded','unstable')]
    qualified.sort(key=lambda x: x.get('ic_mean',0), reverse=True)
    factor_ids = [q['id'] for q in qualified]
    log(f"Loaded {len(factor_ids)} factors")
    return factor_ids


# ── 2. 构建 90 天面板 ──
def build_panel(today_str):
    """daily_kline (89天历史) + Sina (今日)，返回 panel dict"""
    db = sqlite3.connect(DB)

    # 89 天历史
    lookback_date = (datetime.strptime(today_str, "%Y-%m-%d") - timedelta(days=LOOKBACK)).strftime("%Y-%m-%d")
    df = pd.read_sql("""
        SELECT d.code, d.date, d.open, d.high, d.low, d.close, d.volume, d.amount
        FROM daily_kline d
        JOIN stock_info s ON d.code = s.symbol
        WHERE d.date >= ? AND d.date < ?
          AND s.class = 'stock'
          AND s.name NOT LIKE '%ST%'
          AND d.code NOT LIKE 'bj%'
        ORDER BY d.code, d.date
    """, db, params=(lookback_date, today_str))

    # 检查有多少天
    n_dates = df['date'].nunique()
    log(f"  History: {n_dates} trading days, {df['code'].nunique()} stocks")

    # Sina 实时今日数据（不复权）
    codes = sorted(df['code'].unique().tolist())
    sina_rows = _pull_sina_today(codes)
    log(f"  Sina today: {len(sina_rows)} stocks")

    # 后复权 Sina 数据
    factors = {}
    for code, f in db.execute("SELECT code, hfq_factor FROM adjustment_factor"):
        factors[code] = f
    db.close()

    for r in sina_rows:
        f = factors.get(r['code'])
        if f is None:
            continue
        df = pd.concat([df, pd.DataFrame([{
            'code': r['code'], 'date': today_str,
            'open':  round(r['open'] * f, 2),
            'high':  round(r['high'] * f, 2),
            'low':   round(r['low'] * f, 2),
            'close': round(r['close'] * f, 2),
            'volume': r['volume'],
            'amount': r['amount'],
        }])], ignore_index=True)

    df['date'] = pd.to_datetime(df['date'], format='mixed')
    df['vwap'] = df['amount'] / df['volume'].replace(0, np.nan)

    panel = {}
    for field in ['open','high','low','close','volume','vwap','amount']:
        wide = df.pivot(index='date', columns='code', values=field)
        wide = wide.sort_index().astype('float32')
        panel[field] = wide

    log(f"  Panel: {len(panel['close'].index)}d × {len(panel['close'].columns)}c")
    return panel


# ── 3. Sina 实时拉取 ──
def _pull_sina_today(codes):
    results = []
    sina_codes = [c for c in codes if not c.startswith('bj')]  # Sina 格式同 TDX
    BATCH = 800
    for i in range(0, len(sina_codes), BATCH):
        batch = sina_codes[i:i+BATCH]
        url = "http://hq.sinajs.cn/list=" + ",".join(batch)
        try:
            resp = requests.get(url, headers={"Referer": "https://finance.sina.com.cn"}, timeout=15)
            for line in resp.text.strip().split("\n"):
                m = re.search(r'hq_str_(s[hz]\d{6})="(.+?)"', line)
                if not m: continue
                code = m.group(1)
                parts = m.group(2).split(",")
                if len(parts) < 32: continue
                try:
                    open_p  = float(parts[1]) if parts[1] else None
                    close_p = float(parts[3]) if parts[3] else None
                    high_p  = float(parts[4]) if parts[4] else None
                    low_p   = float(parts[5]) if parts[5] else None
                    volume  = float(parts[8]) if parts[8] else 0
                    amount  = float(parts[9]) if parts[9] else 0
                except (ValueError, IndexError):
                    continue
                if not all([open_p, close_p, high_p, low_p]):
                    continue
                results.append({
                    "code": code, "open": open_p, "high": high_p,
                    "low": low_p, "close": close_p,
                    "volume": volume, "amount": amount,
                })
        except Exception as e:
            log(f"  Sina batch error: {e}")
    return results


# ── 4. 因子计算 + 排名选股 ──
def rank_and_pick(panel, factor_ids):
    # 计算因子值
    factor_vals = {}
    today = panel['close'].index[-1]
    for aid in factor_ids:
        zoo, fid = aid.split('/')
        try:
            vals = compute_alpha(zoo, fid + '.py', panel)
            if vals is not None and not vals.empty and today in vals.index:
                factor_vals[aid] = vals.loc[today].dropna()
        except Exception:
            pass

    if not factor_vals:
        log("ERROR: no factor values computed")
        return []

    log(f"  Computed {len(factor_vals)}/{len(factor_ids)} factors")

    # 过滤涨停 (今日涨幅 >= 9.8%)
    close = panel['close']
    day_idx = close.index.get_loc(today)
    if day_idx > 0:
        prev = close.index[day_idx - 1]
        gain = (close.loc[today] / close.loc[prev] - 1) * 100
        limit_up = set(gain[gain >= LIMIT_UP].index)
    else:
        limit_up = set()

    # 投票池: 至少一半因子能覆盖 + 因子值里确实存在的
    min_votes = max(1, len(factor_vals) // 2)
    code_votes = {}
    for aid, vals in factor_vals.items():
        for c in vals.index:
            if c not in limit_up:
                code_votes[c] = code_votes.get(c, 0) + 1
    pool = [c for c, v in code_votes.items() if v >= min_votes]

    if len(pool) < TOP_K:
        log(f"  Pool too small: {len(pool)} (min_votes={min_votes})")
        return []

    pool = list(pool)
    log(f"  Vote pool: {len(pool)} stocks")

    # 等权复合 — 只取能算出的
    composite = pd.Series(0.0, index=pool)
    n_contrib = pd.Series(0, index=pool)
    for aid, vals in factor_vals.items():
        common = list(set(pool) & set(vals.index))
        if len(common) < TOP_K:
            continue
        composite[common] += vals[common].rank(pct=True)
        n_contrib[common] += 1
    composite = composite[n_contrib > 0]
    composite /= n_contrib[composite.index]

    if len(composite) < TOP_K:
        log(f"  Composite too small: {len(composite)}")
        return []

    top = composite.nlargest(TOP_K)
    log(f"  Top {TOP_K}: composite scores {[round(top[c],4) for c in top.index]}")

    # 匹配名称 (过滤不在 stock_info 的)
    db = sqlite3.connect(DB)
    valid_codes = set(r[0] for r in db.execute(
        f"SELECT symbol FROM stock_info WHERE symbol IN ({','.join(['?']*len(top))})",
        list(top.index)
    ).fetchall())
    top = top[top.index.isin(valid_codes)]
    name_map = dict(db.execute(
        f"SELECT symbol, name FROM stock_info WHERE symbol IN ({','.join(['?']*len(top))})",
        list(top.index)
    ).fetchall())
    db.close()

    picks = []
    for code in top.index:
        picks.append({
            "code": code,
            "name": name_map.get(code, code),
            "score": round(float(top[code]), 4),
        })
    return picks


# ── 5. 飞书推送 ──
def send_feishu(picks, mode="实时"):
    today_str = date.today().strftime("%Y-%m-%d")
    lines = [f"阿盯 v5 每日荐股 — {today_str} ({mode})", ""]
    lines.append(f"{'排名':<4} {'名称':<12} {'代码':<12} {'得分':>8}")
    lines.append("-" * 40)
    for i, s in enumerate(picks):
        lines.append(f"{i+1:<4} {s['name']:<12} {s['code']:<12} {s['score']:>8.4f}")
    lines.append("")
    lines.append(f"因子: {len(picks)} 只入选 | 策略: v5 等权复合 | 涨停过滤: {LIMIT_UP}%")

    text = "\n".join(lines)
    print(text)

    # 飞书
    try:
        sys.path.insert(0, os.path.expanduser("~"))
        from feishu import send_text, MONITOR_CHAT_ID
        send_text(text, chat_id=MONITOR_CHAT_ID)
        log("Feishu sent")
    except Exception as e:
        log(f"Feishu failed: {e}")

    # 存 workspace
    path = os.path.join(REPORT_DIR, f"picks_v5_{today_str}.md")
    with open(path, "w") as f:
        f.write(text)


# ── Main ──
def main():
    log("=" * 50)
    log("v5 Daily Pick")

    factor_ids = load_factors()
    today_str = date.today().strftime("%Y-%m-%d")

    if "--test" in sys.argv:
        # 模拟: 用最近一个交易日
        db = sqlite3.connect(DB)
        last_date = db.execute(
            "SELECT MAX(date) FROM daily_kline WHERE date < ?",
            (today_str + " 00:00:00",)
        ).fetchone()[0]
        db.close()
        today_str = last_date[:10]
        log(f"TEST mode: using {today_str}")
        mode = f"测试({today_str})"
    else:
        mode = "实时"

    t0 = time.time()
    panel = build_panel(today_str)
    picks = rank_and_pick(panel, factor_ids)
    elapsed = time.time() - t0

    if picks:
        send_feishu(picks, mode)
        log(f"Done: {elapsed:.1f}s")
    else:
        log(f"No picks generated ({elapsed:.1f}s)")


if __name__ == "__main__":
    main()
