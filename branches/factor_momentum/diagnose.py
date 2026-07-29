#!/home/soso/v5/.venv/bin/python3
"""#5 因子动量诊断层（线1尺子校准版）
颗粒度对比提前定best_gran -> 1.1MinTRL/1.3转移矩阵/决策门A全用best_gran口径
K_LOCK(策略层)已解耦为K_DIAG(诊断层独立参数)。
相对值口径，NW/成本/FDR 暂缓。训练段 2015-2022。
数据：factor_map(rank,2015-2022) + factor_ic_daily(T20_IC,2015-2022)
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
K_DIAG = 12     # 诊断层K（原K_LOCK借自策略层，已解耦为诊断层独立参数；待按K扫描最优对齐）
TOPK = 12        # 转移矩阵 TopK
BLOCK = 6        # block bootstrap 长度
N_FACTORS_MAP = 42  # factor_map 因子数（38正交+4OHLCV）


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def block_bootstrap_ci(series, block=None, n_boot=2000, seed=42):
    """block bootstrap 均值的 95% CI（Politis-Romano optimal block，数据驱动）"""
    rng = np.random.default_rng(seed)
    s = np.asarray(series, float)
    n = len(s)
    if n < 2:
        return (float('nan'), float('nan'))
    if block is None:
        block = max(1, int(round(2 * n ** (1 / 3))))
    boots = np.empty(n_boot)
    for b in range(n_boot):
        idx = []
        while len(idx) < n:
            st = rng.integers(0, max(1, n - block + 1))
            idx.extend(range(st, min(st + block, n)))
        boots[b] = np.mean(s[idx[:n]])
    return (float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5)))


def trans_for_gran(db, g, orth, ts, te):
    """某颗粒度的转移矩阵 counts + P_TT + CI（供颗粒度对比与主链路复用）"""
    tc = defaultdict(int)
    pser = []
    for fid in orth:
        rows = db.execute("SELECT period,rank FROM factor_map WHERE granularity=? AND factor=? AND period>=? AND period<=? ORDER BY 1",
                          (g, fid, ts, te)).fetchall()
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
    p_tt = tc['TT'] / (tc['TT'] + tc['TF']) if (tc['TT'] + tc['TF']) > 0 else 0
    return {'trans': dict(tc), 'p_tt': p_tt, 'n': sum(tc.values()), 'ci': block_bootstrap_ci(pser)}


def main():
    log("=" * 60); log("#5 因子动量诊断层（线1尺子校准，2015-2022）"); log("=" * 60)
    orth = [f['id'] for f in json.load(open(JSON_P))['all_orthogonal']]
    log(f"正交池: {len(orth)} 因子")
    db = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    base = TOPK / N_FACTORS_MAP

    # 0. 颗粒度对比 + 数据驱动选 best_gran（诊断层不预设，不引入成本考量）
    log("--- 0. 颗粒度对比 ---")
    gran = {}
    for g in ['week', 'month', 'quarter']:
        r = trans_for_gran(db, g, orth, TRAIN_START, TRAIN_END)
        gran[g] = r
        log(f"  {g}: P_TT={r['p_tt']:.3f} n={r['n']} CI=[{r['ci'][0]:.3f},{r['ci'][1]:.3f}] lift={r['p_tt']/base:.2f}")
    best_gran = max(gran, key=lambda g: gran[g]['p_tt'])
    log(f"  数据驱动最优颗粒度: {best_gran} (P_TT={gran[best_gran]['p_tt']:.3f}, lift={gran[best_gran]['p_tt']/base:.2f})")

    # 1.1 MinTRL（用 best_gran 颗粒度，K_DIAG 诊断层参数，不借策略层 K_LOCK）
    log("--- 1.1 MinTRL ---")
    periods = [r[0] for r in db.execute(
        "SELECT DISTINCT period FROM factor_map WHERE granularity=? AND period>=? AND period<=? ORDER BY 1",
        (best_gran, TRAIN_START, TRAIN_END)).fetchall()]
    n_p = len(periods)
    eff = n_p - K_DIAG
    eff_blocks = eff // BLOCK
    mintrl = {'gran': best_gran, 'n_periods': n_p, 'K': K_DIAG, 'effective': eff, 'block': BLOCK,
              'eff_blocks': eff_blocks, 'pass': eff_blocks >= 10}
    log(f"  {best_gran}: {n_p}期, K_DIAG={K_DIAG}有效{eff}, block={BLOCK}有效{eff_blocks}块 -> {'PASS' if mintrl['pass'] else 'STOP'}")

    # 1.2 AR(1) + K 扫描（week+month 双颗粒度；week 用 ISO 周对齐 factor_map，sqlite 不支持 %G%V 故 Python 聚合）
    log("--- 1.2 AR(1) (week+month) ---")

    def week_key_iso(s):
        iso = datetime.strptime(s[:10], '%Y-%m-%d').isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"

    ar1_by_gran = {}
    for gran_name, key_fn in [('week', week_key_iso), ('month', lambda s: s[:7])]:
        ar1, gran_ic = {}, {}
        for fid in orth:
            rows = db.execute("SELECT date, T20_IC FROM factor_ic_daily "
                              "WHERE factor_id=? AND date>='2015-01-01' AND date<='2022-12-31' AND T20_IC IS NOT NULL "
                              "ORDER BY date", (fid,)).fetchall()
            if len(rows) < 20:
                continue
            wk = defaultdict(list)
            for d, ic in rows:
                wk[key_fn(d)].append(ic)
            ic = np.array([np.mean(wk[k]) for k in sorted(wk)], float)
            gran_ic[fid] = ic
            rho = float(np.corrcoef(ic[:-1], ic[1:])[0, 1]) if len(ic) > 2 and np.std(ic[:-1]) > 0 and np.std(ic[1:]) > 0 else 0
            n = len(ic) - 1
            t = rho * math.sqrt((n - 2) / (1 - rho**2)) if abs(rho) < 1 and n > 2 else 0
            p = 2 * sp.norm.sf(abs(t))
            ar1[fid] = {'rho': rho, 'p': p, 'n': n + 1}
        nf = len(ar1)
        pos = sum(1 for v in ar1.values() if v['rho'] > 0)
        sigpos = sum(1 for v in ar1.values() if v['rho'] > 0 and v['p'] < 0.05)
        k_scan = {}
        for ks in [1, 3, 6, 12]:
            cors = []
            for fid, ic in gran_ic.items():
                if len(ic) < ks + 5:
                    continue
                ma = np.array([ic[i:i+ks].mean() for i in range(len(ic) - ks)])
                nxt = ic[ks:]
                if np.std(ma) > 0 and np.std(nxt) > 0:
                    cors.append(np.corrcoef(ma, nxt)[0, 1])
            k_scan[ks] = float(np.mean(cors)) if cors else 0
        log(f"  [{gran_name}] AR(1)>0 {pos}/{nf}={pos/nf:.1%} (GK91%) | 显著为正 {sigpos}/{nf} | K扫描 {dict((k, round(v, 3)) for k, v in k_scan.items())}")
        ar1_by_gran[gran_name] = {'details': ar1, 'nf': nf, 'pos': pos, 'sigpos': sigpos,
                                   'ar1_pos_pct': pos / nf if nf else 0,
                                   'sig_pos_pct': sigpos / nf if nf else 0, 'k_scan': k_scan}

    # 1.3 转移矩阵主链路（用 best_gran 口径，复用 gran[best_gran]）
    log("--- 1.3 转移矩阵 (best_gran口径) ---")
    bg = gran[best_gran]
    obs = np.array([[bg['trans'].get('TT', 0), bg['trans'].get('TF', 0)],
                    [bg['trans'].get('FT', 0), bg['trans'].get('FF', 0)]])
    chi2, chi_p, dof, _ = sp.chi2_contingency(obs) if obs.sum() > 0 else (0, 1, 0, None)
    p_tt = bg['p_tt']
    ci = bg['ci']
    lift = p_tt / base if base > 0 else 0
    log(f"  [{best_gran}] P(TopK->TopK)={p_tt:.3f} vs 基准{base:.3f}, lift={lift:.2f}, χ²p={chi_p:.2e}")
    log(f"  block bootstrap CI=[{ci[0]:.3f},{ci[1]:.3f}] (CI下界>{base:.3f}? {ci[0] > base})")

    # 决策门 A（best_gran 口径：AR1 + 转移矩阵 ci 均用 best_gran）
    ar1_pos_pct = ar1_by_gran[best_gran]['ar1_pos_pct']
    sig_pos_pct = ar1_by_gran[best_gran]['sig_pos_pct']
    nf = ar1_by_gran[best_gran]['nf']
    strong = (ar1_pos_pct >= 0.85) and (ci[0] > base)
    verdict = {'gran': best_gran, 'ar1_pos_pct': ar1_pos_pct, 'gk_bench': 0.91, 'sig_pos_pct': sig_pos_pct,
               'p_tt': p_tt, 'base': base, 'lift': lift, 'chi2_p': float(chi_p), 'ci': ci,
               'strong_positive': bool(strong),
               'gran_lift': {g: round(gran[g]['p_tt']/base, 2) for g in gran},
               'ar1_by_gran': {g: {'ar1_pos_pct': v['ar1_pos_pct'], 'sig_pos_pct': v['sig_pos_pct'], 'k_scan': v['k_scan']} for g, v in ar1_by_gran.items()},
               'caveat': f'诊断层主链路(MinTRL/AR1/转移矩阵/决策门A)均已切{best_gran}口径；K_DIAG={K_DIAG}诊断层独立(已解耦策略层K_LOCK)；AR1保留week+month双测备查',
               'prompt': 'A.进入阶段二 / B.阴性归档（人判断）'}
    log("--- 决策门 A ---")
    log(f"  [{best_gran}口径] AR(1)>0 {ar1_pos_pct:.1%}(GK91%) | 转移 P_TT {p_tt:.3f} lift {lift:.2f} CI[{ci[0]:.3f},{ci[1]:.3f}] vs 基准{base:.3f}")
    log(f"  强阳性(AR(1)>0≥85% 且 转移CI下界>基准): {strong}")
    log(f"  颗粒度对比: week lift={gran['week']['p_tt']/base:.2f} / month={gran['month']['p_tt']/base:.2f} / quarter={gran['quarter']['p_tt']/base:.2f}")
    log(f"  提示: {verdict['prompt']}")

    out = {'run_at': datetime.now().isoformat(), 'train': '2015-2022', 'orth_size': len(orth),
           'best_gran': best_gran,
           'mintrl': mintrl,
           'ar1_by_gran': ar1_by_gran,
           'trans': {'gran': best_gran, 'counts': bg['trans'], 'p_tt': p_tt, 'base': base, 'lift': lift, 'chi2_p': float(chi_p), 'ci': ci},
           'gran': {g: {'P_TT': gran[g]['p_tt'], 'n': gran[g]['n'], 'ci': gran[g]['ci']} for g in gran},
           'verdict': verdict}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, 'w'), indent=2, ensure_ascii=False, default=float)
    log(f"written: {OUT}")
    db.close()


if __name__ == '__main__':
    main()
