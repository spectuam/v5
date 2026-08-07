#!/home/soso/v5/.venv/bin/python3
"""strategy_factory：配置 -> 可执行策略（生产选股 + 历史回测）

口径对象化（待办#3）：daily_pick_v5 的策略从硬编码抽成 config，生产 produce_picks
与验证 backtest 共用同一 config 实例。

口径匹配原理：factor_set 来自 factor_decay_results_tdx.json 的 38 正交因子；
lookback≤90天的因子在全历史 panel 上 date T 的值 = 生产 90天 panel 上 date T 的值
（因子只回看≤90天），故 backtest 一次性预算全历史因子等价于生产逐日 90天 panel。

- produce_picks(config, date_str, realtime)：生产选股（精确复刻 daily_pick rank_and_pick）
- backtest(config, start, end, freq)：历史 returns 序列（对齐 candidates_returns.json 喂 compare_pool）

复用 daily_pick_v5.py 的 load_factors/build_panel/rank_and_pick 逻辑，零行为变更。
"""
import sys, os, re, json, time, sqlite3
from datetime import datetime, date, timedelta
import requests
import numpy as np
import pandas as pd

sys.path.insert(0, '/home/soso/trading-strategy')
sys.path.insert(0, '/home/soso/.local/lib/python3.12/site-packages/src/factors')
from factor_zoo_adapter import compute_alpha

DB = os.path.expanduser("~/ading/db/tdx_stock_data.db")
LOG_FILE = os.path.expanduser("~/ading/logs/strategy_factory.log")
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


# ── config ──
def load_config(path):
    with open(path) as f:
        return json.load(f)


def load_factor_ids(config):
    """从 config.factor_set 读因子 ids（复用 daily_pick.load_factors）"""
    fs = config['factor_set']
    src = os.path.expanduser(fs['source_file'])
    with open(src) as f:
        data = json.load(f)
    items = data.get(fs['field'], [])
    flt = fs.get('filter', {})
    qualified = [o for o in items if all(o.get(k) in v for k, v in flt.items())]
    sort = fs.get('sort', {})
    if sort:
        qualified.sort(key=lambda x: x.get(sort['key'], 0), reverse=sort.get('desc', True))
    return [o[fs.get('id_field', 'id')] for o in qualified]


# ── panel: 实时（生产）──
def build_panel_realtime(today_str, lookback):
    """daily_kline(lookback天历史) + Sina(今日不复权->后复权)。复刻 daily_pick.build_panel"""
    db = sqlite3.connect(DB)
    lookback_date = (datetime.strptime(today_str, "%Y-%m-%d") - timedelta(days=lookback)).strftime("%Y-%m-%d")
    df = pd.read_sql("""
        SELECT d.code, d.date, d.open, d.high, d.low, d.close, d.volume, d.amount
        FROM daily_kline d
        JOIN stock_info s ON d.code = s.symbol
        WHERE d.date >= ? AND d.date < ?
          AND s.class = 'stock' AND s.name NOT LIKE '%ST%' AND d.code NOT LIKE 'bj%'
        ORDER BY d.code, d.date
    """, db, params=(lookback_date, today_str))
    n_dates = df['date'].nunique()
    log(f"  History: {n_dates} trading days, {df['code'].nunique()} stocks")

    codes = sorted(df['code'].unique().tolist())
    sina_rows = _pull_sina_today(codes)
    log(f"  Sina today: {len(sina_rows)} stocks")

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
            'open': round(r['open'] * f, 2), 'high': round(r['high'] * f, 2),
            'low': round(r['low'] * f, 2), 'close': round(r['close'] * f, 2),
            'volume': r['volume'], 'amount': r['amount'],
        }])], ignore_index=True)

    df['date'] = pd.to_datetime(df['date'], format='mixed')
    df['vwap'] = df['amount'] / df['volume'].replace(0, np.nan)
    panel = {}
    for field in ['open', 'high', 'low', 'close', 'volume', 'vwap', 'amount']:
        wide = df.pivot(index='date', columns='code', values=field).sort_index().astype('float32')
        panel[field] = wide
    log(f"  Panel: {len(panel['close'].index)}d × {len(panel['close'].columns)}c")
    return panel


def _pull_sina_today(codes):
    """复刻 daily_pick._pull_sina_today"""
    results = []
    sina_codes = [c for c in codes if not c.startswith('bj')]
    BATCH = 800
    for i in range(0, len(sina_codes), BATCH):
        batch = sina_codes[i:i + BATCH]
        url = "http://hq.sinajs.cn/list=" + ",".join(batch)
        try:
            resp = requests.get(url, headers={"Referer": "https://finance.sina.com.cn"}, timeout=15)
            for line in resp.text.strip().split("\n"):
                m = re.search(r'hq_str_(s[hz]\d{6})="(.+?)"', line)
                if not m:
                    continue
                code = m.group(1)
                parts = m.group(2).split(",")
                if len(parts) < 32:
                    continue
                try:
                    open_p = float(parts[1]) if parts[1] else None
                    close_p = float(parts[3]) if parts[3] else None
                    high_p = float(parts[4]) if parts[4] else None
                    low_p = float(parts[5]) if parts[5] else None
                    volume = float(parts[8]) if parts[8] else 0
                    amount = float(parts[9]) if parts[9] else 0
                except (ValueError, IndexError):
                    continue
                if not all([open_p, close_p, high_p, low_p]):
                    continue
                results.append({"code": code, "open": open_p, "high": high_p, "low": low_p,
                                "close": close_p, "volume": volume, "amount": amount})
        except Exception as e:
            log(f"  Sina batch error: {e}")
    return results


# ── panel: 历史（回测）──
def build_panel_history(start, end):
    """全历史 panel（DB 后复权 daily_kline，无 Sina）。float32 省 mem。"""
    db = sqlite3.connect(DB)
    df = pd.read_sql("""
        SELECT d.code, d.date, d.open, d.high, d.low, d.close, d.volume, d.amount
        FROM daily_kline d
        JOIN stock_info s ON d.code = s.symbol
        WHERE d.date >= ? AND d.date <= ?
          AND s.class = 'stock' AND s.name NOT LIKE '%ST%' AND d.code NOT LIKE 'bj%'
        ORDER BY d.code, d.date
    """, db, params=(start + ' 00:00:00', end + ' 23:59:59'))
    db.close()
    df['date'] = pd.to_datetime(df['date'].str.slice(0, 10), format='%Y-%m-%d')
    df['vwap'] = df['amount'] / df['volume'].replace(0, np.nan)
    panel = {}
    for field in ['open', 'high', 'low', 'close', 'volume', 'vwap', 'amount']:
        wide = df.pivot(index='date', columns='code', values=field).sort_index().astype('float32')
        panel[field] = wide
    log(f"  History panel: {len(panel['close'].index)}d × {len(panel['close'].columns)}c")
    return panel


# ── rank_and_pick（精确复刻 daily_pick.rank_and_pick）──
def rank_and_pick(panel, factor_ids, config):
    """核心选股逻辑。与 daily_pick.rank_and_pick 行为一致。"""
    sel = config['selection']
    sig = config['signal']
    flt = config['filters']
    top_k = sel['top_k']
    vote_thr = sig['vote_threshold']
    limit_up = flt['limit_up_pct']

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

    close = panel['close']
    day_idx = close.index.get_loc(today)
    if day_idx > 0:
        prev = close.index[day_idx - 1]
        gain = (close.loc[today] / close.loc[prev] - 1) * 100
        limit_up_set = set(gain[gain >= limit_up].index)
    else:
        limit_up_set = set()

    min_votes = max(1, int(vote_thr * len(factor_vals)))  # 等价 daily_pick max(1, len//2)
    code_votes = {}
    for aid, vals in factor_vals.items():
        for c in vals.index:
            if c not in limit_up_set:
                code_votes[c] = code_votes.get(c, 0) + 1
    pool = [c for c, v in code_votes.items() if v >= min_votes]
    if len(pool) < top_k:
        log(f"  Pool too small: {len(pool)}")
        return []
    pool = list(pool)
    log(f"  Vote pool: {len(pool)} stocks")

    composite = pd.Series(0.0, index=pool)
    n_contrib = pd.Series(0, index=pool)
    for aid, vals in factor_vals.items():
        common = list(set(pool) & set(vals.index))
        if len(common) < top_k:
            continue
        composite[common] += vals[common].rank(pct=True)
        n_contrib[common] += 1
    composite = composite[n_contrib > 0]
    composite /= n_contrib[composite.index]

    if len(composite) < top_k:
        log(f"  Composite too small: {len(composite)}")
        return []

    top = composite.nlargest(top_k)
    log(f"  Top {top_k}: {[round(float(top[c]), 4) for c in top.index]}")

    db = sqlite3.connect(DB)
    valid_codes = set(r[0] for r in db.execute(
        f"SELECT symbol FROM stock_info WHERE symbol IN ({','.join(['?'] * len(top))})",
        list(top.index)).fetchall())
    top = top[top.index.isin(valid_codes)]
    name_map = dict(db.execute(
        f"SELECT symbol, name FROM stock_info WHERE symbol IN ({','.join(['?'] * len(top))})",
        list(top.index)).fetchall())
    db.close()

    return [{"code": code, "name": name_map.get(code, code),
             "score": round(float(top[code]), 4)} for code in top.index]


# ── produce_picks（生产）──
def produce_picks(config, today_str, realtime=True):
    """生产选股。realtime=True: 历史+Sina；False: 仅历史(测试/回测点)。"""
    lookback = config['panel']['lookback_days']
    if realtime:
        panel = build_panel_realtime(today_str, lookback)
    else:
        # 测试模式：用历史 panel 到 today_str（不含 Sina）
        panel = build_panel_realtime(today_str, lookback)  # build_panel 用 date<today 历史不含今日
        # 注：daily_pick --test 用 MAX(date)<today 作为 today_str，历史 panel 含该日
    factor_ids = load_factor_ids(config)
    log(f"Loaded {len(factor_ids)} factors")
    return rank_and_pick(panel, factor_ids, config)


# ── backtest（验证）──
def backtest(config, start, end, freq='weekly'):
    """历史回测：全历史 panel + 一次性预算因子 + 按 freq 选股 + T+5 持有。
    产出 [(week, ret)]，对齐 candidates_returns.json 格式喂 compare_pool。
    口径注：生产 daily horizon=1，回测 weekly+T+5（compare 约定）；诚实标注。"""
    factor_ids = load_factor_ids(config)
    log(f"Loaded {len(factor_ids)} factors")
    panel = build_panel_history(start, end)
    close = panel['close']
    all_dates = close.index
    log(f"  一次性预算 {len(factor_ids)} 因子（全历史 panel）...")
    t0 = time.time()
    factor_mats = {}
    for aid in factor_ids:
        zoo, fid = aid.split('/')
        try:
            vals = compute_alpha(zoo, fid + '.py', panel)
            if vals is not None and not vals.empty:
                factor_mats[aid] = vals
        except Exception:
            pass
    log(f"  预算 {len(factor_mats)}/{len(factor_ids)} 因子，耗时 {time.time()-t0:.0f}s")

    # rebalance 日期：weekly = 每周首个交易日
    if freq == 'weekly':
        week_first = {}
        for d in all_dates:
            iso = d.isocalendar()
            wk = f"{iso[0]}-W{iso[1]:02d}"
            if wk not in week_first:
                week_first[wk] = d
        rebal_dates = [week_first[w] for w in sorted(week_first)]
    else:
        rebal_dates = list(all_dates)

    sel = config['selection']
    flt = config['filters']
    sig = config['signal']
    top_k = sel['top_k']
    vote_thr = sig['vote_threshold']
    limit_up = flt['limit_up_pct']
    horizon = 5  # T+5 周度持有（compare 约定）

    out = {}
    t0 = time.time()
    for i, d in enumerate(rebal_dates):
        # 该日因子值
        fvals = {}
        for aid, mat in factor_mats.items():
            if d in mat.index:
                v = mat.loc[d].dropna()
                if len(v):
                    fvals[aid] = v
        if len(fvals) < max(2, len(factor_mats) // 2):
            continue
        # 涨停过滤
        di = all_dates.get_loc(d)
        if di > 0:
            prev = all_dates[di - 1]
            gain = (close.loc[d] / close.loc[prev] - 1) * 100
            limit_up_set = set(gain[gain >= limit_up].index)
        else:
            limit_up_set = set()
        # vote pool
        code_votes = {}
        for aid, v in fvals.items():
            for c in v.index:
                if c not in limit_up_set:
                    code_votes[c] = code_votes.get(c, 0) + 1
        min_votes = max(1, int(vote_thr * len(fvals)))
        pool = [c for c, ct in code_votes.items() if ct >= min_votes]
        if len(pool) < top_k:
            continue
        # 等权复合
        composite = pd.Series(0.0, index=pool)
        n_contrib = pd.Series(0, index=pool)
        for aid, v in fvals.items():
            common = list(set(pool) & set(v.index))
            if len(common) < top_k:
                continue
            composite[common] += v[common].rank(pct=True)
            n_contrib[common] += 1
        composite = composite[n_contrib > 0]
        composite /= n_contrib[composite.index]
        if len(composite) < top_k:
            continue
        top = composite.nlargest(top_k)
        # T+horizon 等权收益
        rets = []
        for code in top.index:
            try:
                di = all_dates.get_loc(d)
                if di + horizon >= len(all_dates):
                    continue
                buy = close.loc[d, code]
                sell = close.iloc[di + horizon][code]
                if buy > 0 and not np.isnan(sell):
                    rets.append(sell / buy - 1)
            except Exception:
                continue
        if rets:
            iso = d.isocalendar()
            wk = f"{iso[0]}-W{iso[1]:02d}"
            out[wk] = float(np.mean(rets))
        if (i + 1) % 100 == 0:
            log(f"  {i+1}/{len(rebal_dates)} [{time.time()-t0:.0f}s]")
    arr = np.array(list(out.values()), float)
    arr = arr[~np.isnan(arr)]
    sr = float(arr.mean() / arr.std() * np.sqrt(52)) if len(arr) and arr.std() > 0 else 0
    log(f"backtest: {len(out)}周, SR{sr:.2f}, 年化{arr.mean()*52:.2%}")
    return [[w, out[w]] for w in sorted(out)]


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--config', default=os.path.expanduser('~/v5/branches/strategy_factory/strategy_config.json'))
    p.add_argument('--pick', action='store_true', help='生产选股(需实时或--date)')
    p.add_argument('--backtest', action='store_true', help='历史回测')
    p.add_argument('--date', type=str, help='选股日期(测试)')
    p.add_argument('--start', default='2016-01-01')
    p.add_argument('--end', default='2026-06-30')
    args = p.parse_args()
    cfg = load_config(args.config)
    if args.pick:
        d = args.date or date.today().strftime("%Y-%m-%d")
        picks = produce_picks(cfg, d, realtime=not args.date)
        print(json.dumps(picks, ensure_ascii=False, indent=2))
    if args.backtest:
        rets = backtest(cfg, args.start, args.end, freq='weekly')
        out_p = os.path.expanduser('~/v5/branches/strategy_factory/backtest_result.json')
        json.dump([{'strategy': cfg['name'], 'returns': rets}], open(out_p, 'w'),
                  indent=2, ensure_ascii=False, default=float)
        print(f"written: {out_p}")
