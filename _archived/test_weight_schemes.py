#!/home/soso/v5/.venv/bin/python3
"""测试三种因子权重方案（Train 期计算权重，防前视）
  equal: 等权（基线）
  ic:    IC_mean 加权
  ir:    IR = IC_mean/IC_std 加权
"""
import sys, os, time, json, gc, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, '/home/soso/trading-strategy')
sys.path.insert(0, '/home/soso/.local/lib/python3.12/site-packages/src/factors')
sys.path.insert(0, '/home/soso/v5')

import numpy as np, pandas as pd, sqlite3
from datetime import datetime
from factor_decay_utils import build_daily_panel, compute_forward_returns
from factor_zoo_adapter import compute_alpha

TDX_DB = os.path.expanduser("~/ading/db/tdx_stock_data.db")
FACTOR_JSON = os.path.expanduser("~/ading/data/reports/factor_decay_results_tdx.json")

VALID_START, VALID_END = '2016-01-01', '2020-12-31'
DAILY_PICK_K, LIMIT_UP_THRESH = 5, 9.8

def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)

# 1. 加载因子池
with open(FACTOR_JSON) as f:
    factor_data = json.load(f)
ortho = factor_data['all_orthogonal']
qualified = [o for o in ortho if o.get('status') in ('confirmed','degraded','unstable')]
qualified.sort(key=lambda x: x.get('ic_mean',0), reverse=True)
factor_ids = [q['id'] for q in qualified]
log(f"{len(factor_ids)} qualified factors from Train")

# 2. 从 Train 期 IC 表计算权重（<=2015-12-31）
db = sqlite3.connect(TDX_DB)
rows = db.execute("""
    SELECT factor_id, AVG(T1_IC) as ic,
           AVG(T1_IC)/NULLIF(SQRT(AVG(T1_IC*T1_IC)-AVG(T1_IC)*AVG(T1_IC)),0) as ir
    FROM factor_ic_daily
    WHERE date <= '2015-12-31' AND factor_id IN ({})
    GROUP BY factor_id
""".format(','.join(['?']*len(factor_ids))), factor_ids).fetchall()
db.close()

ic_map = {r[0]: abs(r[1]) for r in rows if r[1] and abs(r[1])>0}
ir_map = {r[0]: r[2] for r in rows if r[2] and r[2]>0}

def normalize(d):
    total = sum(d.values())
    return {k: v/total*len(d) for k,v in d.items()} if total>0 else {}

weights = {
    'equal': {f:1.0 for f in factor_ids},
    'ic': normalize(ic_map),
    'ir': normalize(ir_map),
}
for scheme in weights:
    w = weights[scheme]
    top5 = sorted(w.items(), key=lambda x:-x[1])[:5]
    log(f"  {scheme}: top5 weights = {[(f[:20],round(v,2)) for f,v in top5]}")

# 3. 构建面板+因子
log("Building panel...")
panel = build_daily_panel(lookback_days=4200, db_path='tdx', date_end=VALID_END)
log(f"  Panel: {len(panel['close'].index)}d × {len(panel['close'].columns)}c")

db = sqlite3.connect(TDX_DB)
ind_df = pd.read_sql("SELECT code, sw2_code FROM stock_sw2", db)
industry_map = dict(zip(ind_df['code'], ind_df['sw2_code']))
db.close()

fwd_all = compute_forward_returns(panel, horizons=[1])
fwd_T1 = fwd_all[1]; del fwd_all; gc.collect()

log("Computing 38 factors...")
fdfs = []
for aid in factor_ids:
    zoo, fid = aid.split('/')
    vals = compute_alpha(zoo, fid+'.py', panel)
    if vals is not None and not vals.empty:
        fdfs.append((aid, vals))
    gc.collect()
log(f"  {len(fdfs)} factors ready")

# 4. 跑三种权重
close = panel['close']
dates = close.index[(close.index >= VALID_START) & (close.index <= VALID_END)]

for weight_scheme in ['equal', 'ic', 'ir']:
    w = weights[weight_scheme]
    daily_records = []
    t0 = time.time()

    for day in dates:
        factors_today = []
        for name, fdf in fdfs:
            if day not in fdf.index: continue
            vals = fdf.loc[day].dropna()
            if len(vals) > DAILY_PICK_K+5:
                factors_today.append((name, vals))
        if not factors_today: continue

        day_idx = close.index.get_loc(day)
        if day_idx == 0: continue
        gain = (close.loc[day]/close.loc[close.index[day_idx-1]]-1)*100
        limit_up = set(gain[gain>=LIMIT_UP_THRESH].index)

        candidate_sets = []
        for _n, vals in factors_today:
            t = vals.index.difference(limit_up, sort=False)
            if len(t) >= DAILY_PICK_K+10: candidate_sets.append(set(t))
        if not candidate_sets: continue
        pool = candidate_sets[0]
        for s in candidate_sets[1:]: pool = pool.intersection(s)
        if len(pool) < DAILY_PICK_K: continue
        pool = list(pool)

        composite = pd.Series(0.0, index=pool)
        total_w = 0.0
        for name, vals in factors_today:
            fw = w.get(name, 1.0)
            composite += vals[pool].rank(pct=True) * fw
            total_w += fw
        composite /= total_w if total_w > 0 else 1
        top = composite.nlargest(DAILY_PICK_K)

        if day not in fwd_T1.index: continue
        fwd_day = fwd_T1.loc[day].dropna()
        ind_s = pd.Series(industry_map)
        ret_df = pd.DataFrame({'ret':fwd_day,'sw2':ind_s}).dropna(subset=['sw2'])
        ind_med = ret_df.groupby('sw2')['ret'].median()
        ret_pct = fwd_day.rank(pct=True)

        for code in top.index:
            if code not in fwd_day.index or code not in industry_map: continue
            sw2 = industry_map[code]
            if sw2 not in ind_med.index: continue
            sr = fwd_day[code]
            daily_records.append({
                'beat': 1 if sr > ind_med[sw2] else 0,
                'return_pct': float(sr),
                'return_percentile': float(ret_pct.get(code)) if code in ret_pct.index else None,
            })

    df = pd.DataFrame(daily_records)
    wr = float(df['beat'].mean())
    ret = float(df['return_pct'].mean())
    rp = float(df['return_percentile'].mean())
    elapsed = time.time()-t0
    log(f"\n  {weight_scheme}: WR={wr:.2%}, ret={ret:.4f}, rp={rp:.2%}, trades={len(df)}, {elapsed:.0f}s")

gc.collect()
log("\nDone.")
