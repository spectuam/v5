#!/home/soso/v5/.venv/bin/python3
"""T1+T2 诊断：38正交因子的 IC/IR/t 分窗口统计

从 factor_ic_daily 表（Spearman rank IC）查38正交因子的IC，
按5个时间窗口算 mean/std/IR/t，看因子衰减与test期显著性。
同时回答 T1（IC/IR替代WR）和 T2（哪些因子衰减/仍显著）。

内存：纯SQL聚合，38因子×6窗口×5horizon=1140次轻查询，<10MB。
"""
import sqlite3, os, json, math, sys
from datetime import datetime

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
JSON_P = '/home/soso/ading/data/reports/factor_decay_results_tdx.json'
OUT = '/home/soso/v5/t1_t2_diag_result.json'

WINDOWS = [
    ('P1_select_0615', '2006-01-01', '2015-12-31'),   # 因子选择期
    ('P2_trans_1618',  '2016-01-01', '2018-12-31'),   # 过渡
    ('P3_core_1921',   '2019-01-01', '2021-12-31'),   # 核心资产牛市
    ('P4_small_2224',  '2022-01-01', '2024-12-31'),   # 小盘量化
    ('P5_recent_2526', '2025-01-01', '2026-12-31'),   # 近期
    ('FULL',           '2006-01-01', '2026-12-31'),
]
HORIZONS = [1, 3, 5, 10, 20]

def log(m): print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)

def main():
    d = json.load(open(JSON_P))
    orth = d['all_orthogonal']
    orth_ids = [f['id'] for f in orth]
    cat_map = {f['id']: f.get('category','?') for f in orth}
    hl_map  = {f['id']: f.get('half_life',None) for f in orth}
    log(f"orthogonal pool: {len(orth_ids)} factors")

    db = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    c = db.cursor()

    unmatched = [i for i in orth_ids if not c.execute('SELECT 1 FROM factor_ic_daily WHERE factor_id=? LIMIT 1',(i,)).fetchone()]
    log(f"matched: {len(orth_ids)-len(unmatched)}/{len(orth_ids)}, unmatched(skip): {unmatched}")
    orth_ids = [i for i in orth_ids if i not in set(unmatched)]

    results = []
    for idx, fid in enumerate(orth_ids):
        fac = {'id': fid, 'category': cat_map.get(fid,'?'),
               'half_life': hl_map.get(fid), 'stats': {}}
        for H in HORIZONS:
            col = f'T{H}_IC'
            fac['stats'][f'T{H}'] = {}
            for wname, ws, we in WINDOWS:
                row = c.execute(f"""
                    SELECT COUNT(*), AVG({col}), AVG({col}*{col})
                    FROM factor_ic_daily
                    WHERE factor_id=? AND date>=? AND date<=? AND {col} IS NOT NULL
                """, (fid, ws, we)).fetchone()
                n, mean, mean_x2 = row
                if n < 10 or mean is None:
                    fac['stats'][f'T{H}'][wname] = {'n': n, 'mean': None}
                    continue
                var = mean_x2 - mean*mean
                std = math.sqrt(var) if var > 0 else 0.0
                ir = mean/std if std > 0 else 0.0
                t = mean/math.sqrt(var/n) if var > 0 else 0.0
                fac['stats'][f'T{H}'][wname] = {
                    'n': n, 'mean': round(mean,5), 'std': round(std,5),
                    'ir': round(ir,4), 't': round(t,2)
                }
        results.append(fac)
        if (idx+1) % 10 == 0:
            log(f"  {idx+1}/{len(orth_ids)} done")

    # 汇总：T5（5日horizon，最贴近持仓周期）各窗口IR
    summary = {
        'T5_ir_significant_P5recent': [],   # 近期仍 |t|>2
        'T5_ir_decayed': [],                # P1显著但P4/P5不显著
        'T5_ir_strong_full': [],            # 全段 |IR|>0.3
    }
    for fac in results:
        s5 = fac['stats']['T5']
        fid = fac['id']
        p1 = s5.get('P1_select_0615',{}).get('t')
        p4 = s5.get('P4_small_2224',{}).get('t')
        p5 = s5.get('P5_recent_2526',{}).get('t')
        full_ir = s5.get('FULL',{}).get('ir')
        if p5 is not None and abs(p5) > 2:
            summary['T5_ir_significant_P5recent'].append(fid)
        if p1 is not None and abs(p1) > 2 and (p4 is None or abs(p4) < 2) and (p5 is None or abs(p5) < 2):
            summary['T5_ir_decayed'].append(fid)
        if full_ir is not None and abs(full_ir) > 0.3:
            summary['T5_ir_strong_full'].append((fid, full_ir))

    out = {
        'run_at': datetime.now().isoformat(),
        'data_source': 'factor_ic_daily (2006-2026, 436 factors, Spearman rank IC)',
        'orthogonal_pool_size': len(d['all_orthogonal']),
        'unmatched_factors': unmatched,
        'windows': [(w[0],w[1],w[2]) for w in WINDOWS],
        'note': 'T5_IC = 5日horizon Spearman IC，最贴近持仓周期',
        'factors': results,
        'summary': summary,
    }
    json.dump(out, open(OUT,'w'), ensure_ascii=False, indent=2)
    log(f"written: {OUT}")
    log(f"=== T5 summary ===")
    log(f"近期(P5)仍显著|t|>2: {len(summary['T5_ir_significant_P5recent'])}/{len(orth_ids)}")
    log(f"选择期显著但test期衰减: {len(summary['T5_ir_decayed'])}/{len(orth_ids)}")
    log(f"全段|IR|>0.3: {len(summary['T5_ir_strong_full'])}/{len(orth_ids)}")
    log(f"近期仍显著因子: {summary['T5_ir_significant_P5recent']}")
    log(f"衰减因子: {summary['T5_ir_decayed']}")

if __name__ == '__main__':
    main()
