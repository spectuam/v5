#!/home/soso/v5/.venv/bin/python3
"""#5 因子动量阶段一诊断层
1.1 MinTRL + 1.2 AR(1)+K扫描 + 1.3 转移矩阵+χ²+block bootstrap + 1.4 颗粒度 + 决策门A
相对值口径，NW/成本/FDR 暂缓。训练段 2015-2022（96月）。
数据：factor_map(rank,2015-2022) + factor_ic_daily(T20_IC月均,2015-2022)
解耦：只读两表，不碰代码。baseline_v0 不动。
"""
import sqlite3, os, json, math
from datetime import datetime
from collections import defaultdict
import numpy as np
from scipy import stats as sp

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
JSON_P = '/home/soso/ading/data/reports/factor_decay_results_tdx.json'
OUT = os.path.expanduser('~/v5/branches/factor_momentum/diagnose_result.json')
TRAIN_START, TRAIN_END = '2015-01', '2022-12'
K_LOCK = 12      # 策略层锁定 K
TOPK = 12        # 转移矩阵 TopK
BLOCK = 6        # block bootstrap 长度（写死，Politis-Romano 简化）
N_FACTORS_MAP = 42  # factor_map 因子数（38正交+4OHLCV）


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def block_bootstrap_ci(series, block=BLOCK, n_boot=2000, seed=42):
    """block bootstrap 均值的 95% CI"""
    rng = np.random.default_rng(seed)
    s = np.asarray(series, float)
    n = len(s)
    if n < 2:
        return (float('nan'), float('nan'))
    boots = np.empty(n_boot)
    for b in range(n_boot):
        idx = []
        while len(idx) < n:
            st = rng.integers(0, max(1, n - block + 1))
            idx.extend(range(st, min(st + block, n)))
        boots[b] = np.mean(s[idx[:n]])
    return (float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5)))


def main():
    log("=" * 60); log("#5 因子动量诊断层（阶段一，2015-2022）"); log("=" * 60)
    orth = [f['id'] for f in json.load(open(JSON_P))['all_orthogonal']]
    log(f"正交池: {len(orth)} 因子")
    db = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)

    # 1.1 MinTRL
    log("--- 1.1 MinTRL ---")
    months = [r[0] for r in db.execute(
        "SELECT DISTINCT period FROM factor_map WHERE granularity='month' AND period>=? AND period<=? ORDER BY 1",
        (TRAIN_START, TRAIN_END)).fetchall()]
    n_m = len(months)
    eff = n_m - K_LOCK
    eff_blocks = eff // BLOCK
    mintrl = {'n_months': n_m, 'K': K_LOCK, 'effective': eff, 'block': BLOCK,
              'eff_blocks': eff_blocks, 'pass': eff_blocks >= 10}
    log(f"  {n_m}月, K={K_LOCK}有效{eff}, block={BLOCK}有效{eff_blocks}块 -> {'PASS' if mintrl['pass'] else 'STOP'}")

    # 1.2 AR(1) + K 扫描
    log("--- 1.2 AR(1) ---")
    ar1 = {}
    monthly_ic = {}
    for fid in orth:
        rows = db.execute("""SELECT substr(date,1,7) ym, AVG(T20_IC) FROM factor_ic_daily
            WHERE factor_id=? AND date>='2015-01-01' AND date<='2022-12-31' AND T20_IC IS NOT NULL
            GROUP BY ym ORDER BY ym""", (fid,)).fetchall()
        if len(rows) < 20:
            continue
        ic = np.array([r[1] for r in rows], float)
        monthly_ic[fid] = ic
        rho = float(np.corrcoef(ic[:-1], ic[1:])[0, 1]) if len(ic) > 2 and np.std(ic[:-1]) > 0 and np.std(ic[1:]) > 0 else 0
        n = len(ic) - 1
        t = rho * math.sqrt((n - 2) / (1 - rho**2)) if abs(rho) < 1 and n > 2 else 0
        p = 2 * sp.norm.sf(abs(t))
        ar1[fid] = {'rho': rho, 'p': p, 'n': n + 1}
    nf = len(ar1)
    pos = sum(1 for v in ar1.values() if v['rho'] > 0)
    sigpos = sum(1 for v in ar1.values() if v['rho'] > 0 and v['p'] < 0.05)
    log(f"  AR(1)>0: {pos}/{nf}={pos/nf:.1%} (对标 GK 91%)")
    log(f"  显著为正: {sigpos}/{nf}={sigpos/nf:.1%}")
    k_scan = {}
    for ks in [1, 3, 6, 12]:
        cors = []
        for fid, ic in monthly_ic.items():
            if len(ic) < ks + 5:
                continue
            ma = np.array([ic[i:i+ks].mean() for i in range(len(ic) - ks)])
            nxt = ic[ks:]
            if np.std(ma) > 0 and np.std(nxt) > 0:
                cors.append(np.corrcoef(ma, nxt)[0, 1])
        k_scan[ks] = float(np.mean(cors)) if cors else 0
    log(f"  K扫描(过去K期IC均值->下期IC): {dict((k, round(v, 3)) for k, v in k_scan.items())}")

    # 1.3 转移矩阵
    log("--- 1.3 转移矩阵 ---")
    trans = defaultdict(int)
    p_tt_series = []
    for fid in orth:
        rows = db.execute("SELECT period, rank FROM factor_map WHERE granularity='month' AND factor=? AND period>=? AND period<=? ORDER BY 1",
                          (fid, TRAIN_START, TRAIN_END)).fetchall()
        tt = tf = 0
        for i in range(len(rows) - 1):
            ct = rows[i][1] <= TOPK
            nt = rows[i+1][1] <= TOPK
            trans[('T' if ct else 'F') + ('T' if nt else 'F')] += 1
            if ct:
                if nt: tt += 1
                else: tf += 1
        if tt + tf > 0:
            p_tt_series.append(tt / (tt + tf))
    p_tt = trans['TT'] / (trans['TT'] + trans['TF']) if (trans['TT'] + trans['TF']) > 0 else 0
    base = TOPK / N_FACTORS_MAP
    obs = np.array([[trans['TT'], trans['TF']], [trans['FT'], trans['FF']]])
    chi2, chi_p, dof, _ = sp.chi2_contingency(obs) if obs.sum() > 0 else (0, 1, 0, None)
    ci = block_bootstrap_ci(p_tt_series)
    lift = p_tt / base if base > 0 else 0
    log(f"  P(TopK->TopK)={p_tt:.3f} vs 基准{base:.3f}, lift={lift:.2f}, χ²p={chi_p:.2e}")
    log(f"  block bootstrap CI=[{ci[0]:.3f},{ci[1]:.3f}] (CI下界>{base:.3f}? {ci[0] > base})")

    # 1.4 颗粒度
    log("--- 1.4 颗粒度 ---")
    gran = {}
    for g in ['week', 'month', 'quarter']:
        tc = defaultdict(int)
        pser = []
        for fid in orth:
            rows = db.execute("SELECT period,rank FROM factor_map WHERE granularity=? AND factor=? AND period>=? AND period<=? ORDER BY 1",
                              (g, fid, TRAIN_START, TRAIN_END)).fetchall()
            tt = tf = 0
            for i in range(len(rows) - 1):
                ct = rows[i][1] <= TOPK
                nt = rows[i+1][1] <= TOPK
                tc[('T' if ct else 'F') + ('T' if nt else 'F')] += 1
                if ct:
                    if nt: tt += 1
                    else: tf += 1
            if tt + tf > 0:
                pser.append(tt / (tt + tf))
        pg = tc['TT'] / (tc['TT'] + tc['TF']) if (tc['TT'] + tc['TF']) > 0 else 0
        gran[g] = {'P_TT': pg, 'n': sum(tc.values()), 'ci': block_bootstrap_ci(pser)}
        log(f"  {g}: P_TT={pg:.3f} n={sum(tc.values())} CI=[{gran[g]['ci'][0]:.3f},{gran[g]['ci'][1]:.3f}]")

    # 决策门 A
    ar1_pos_pct = pos / nf
    strong = (ar1_pos_pct >= 0.85) and (ci[0] > base)
    verdict = {'ar1_pos_pct': ar1_pos_pct, 'gk_bench': 0.91, 'sig_pos_pct': sigpos / nf,
               'p_tt': p_tt, 'base': base, 'lift': lift, 'chi2_p': float(chi_p), 'ci': ci,
               'strong_positive': bool(strong),
               'prompt': 'A.进入阶段二 / B.阴性归档（人判断）'}
    log("--- 决策门 A ---")
    log(f"  AR(1)>0 {ar1_pos_pct:.1%}(GK91%) | 转移 P_TT {p_tt:.3f} lift {lift:.2f} CI[{ci[0]:.3f},{ci[1]:.3f}] vs 基准{base:.3f}")
    log(f"  强阳性(AR(1)>0≥85% 且 转移CI下界>基准): {strong}")
    log(f"  提示: {verdict['prompt']}")

    out = {'run_at': datetime.now().isoformat(), 'train': '2015-2022', 'orth_size': len(orth),
           'mintrl': mintrl,
           'ar1': {'n': nf, 'ar1_pos_pct': ar1_pos_pct, 'sig_pos_pct': sigpos / nf, 'gk_bench': 0.91, 'details': ar1},
           'k_scan': k_scan,
           'trans': {'counts': dict(trans), 'p_tt': p_tt, 'base': base, 'lift': lift, 'chi2_p': float(chi_p), 'ci': ci},
           'gran': gran,
           'verdict': verdict}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, 'w'), indent=2, ensure_ascii=False, default=float)
    log(f"written: {OUT}")
    db.close()


if __name__ == '__main__':
    main()
