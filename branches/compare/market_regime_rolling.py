#!/home/soso/v5/.venv/bin/python3
"""market_regime_rolling statsmodels 版（expanding fit，严格 live）

替换 hmmlearn 滚动版（见 market_regime_rolling.py.hmmlearn.bak）。

三层诚实对比「状态识别的 live 可达性」：
  1. smoothed-global: 全局 fit + Kim smoother（全样本 look-ahead = 理论上限）
  2. filtered-global: 全局 fit + Hamilton filter（状态因果，参数全样本 look-ahead）
  3. expanding-filtered: 每月 t 用 [0,t] 重估参数 + Hamilton filter（状态因果+参数无未来 = 最严 live）

对 long-only 候选做择时验证。旧 hmmlearn 结论「滚动 fit 实盘无改善」用正确模型重测。
择时规则双向测试（A股等权「crash」regime 含高收益，hide crash 可能损价值）：
  - hide_crash: 高波动 regime 空仓（旧规则）
  - hide_calmlowSR: 低 SR regime 空仓（替代规则）

注意：contemporaneous timing（regime 于月末可知）；regime 持续性强(transmat 0.85/0.74)，
故 contemporaneous ≈ ex-ante。严格 ex-ante 应用 regime(t-1) 预测 t，标注为 future。
"""
import os, json
from datetime import datetime
import numpy as np
from market_regime import (week_to_month, monthly_resample, fit_k,
                           label_by_variance, max_dd, K_CANDIDATES, TREND)

MKT = os.path.expanduser('~/v5/branches/compare/market_benchmark_returns.json')
REGIME = os.path.expanduser('~/v5/branches/compare/market_regime_result.json')
CAND = os.path.expanduser('~/v5/branches/compare/candidates_returns.json')
OUT = os.path.expanduser('~/v5/branches/compare/market_regime_rolling_result.json')
MIN_WINDOW = 60  # 前5年(60月)暖机，之后逐月expanding预测
FREQ = 52
LONG_NAMES = ['tsmom_long_K12', 'funnel_top5_eq_long', 'funnel_top5_tsmom_long']


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def expanding_regimes(mret, k, min_window=MIN_WINDOW):
    """每月 t 用 [0,t] fit + Hamilton filter 取月末 regime（最严 live）。
    返回 regimes[list|None]，前 min_window 个为 None。"""
    regimes = [None] * len(mret)
    for t in range(min_window, len(mret)):
        res = fit_k(mret[:t + 1], k)
        if res is None:
            continue
        fil = np.asarray(res.filtered_marginal_probabilities)
        regimes[t] = int(fil[-1].argmax())
    return regimes


def stats(rets):
    arr = np.asarray(rets, float)
    if len(arr) < 2 or arr.std() == 0:
        return {'n': len(arr), 'sharpe': 0, 'annual': 0, 'max_dd': 0}
    sr = float(arr.mean() / arr.std() * np.sqrt(FREQ))
    return {'n': len(arr), 'sharpe': round(sr, 2),
            'annual': round(float(arr.mean() * FREQ), 4), 'max_dd': round(max_dd(arr), 3)}


def timing(weekly_pairs, week_state, hide_labels):
    """contemporaneous 择时：week 属 hide_labels 的 regime 则空仓。"""
    out = []
    for w, r in weekly_pairs:
        if week_state.get(w) in hide_labels:
            out.append(0.0)
        else:
            out.append(r)
    return out


def main():
    log("=" * 60); log("market_regime_rolling (expanding fit, 三层 live 对比)"); log("=" * 60)
    mkt_raw = json.load(open(MKT))['market_eq']
    mkt = dict(mkt_raw)
    weeks = sorted(mkt.keys())
    months, mret = monthly_resample([(w, mkt[w]) for w in weeks])
    regime = json.load(open(REGIME))
    k = regime['best_k']
    regime_label = regime['regime_label']  # {int: label}
    log(f"用 market_regime_result: k={k}, 标注 {regime_label}")

    # 找 hide 候选标签：crash（高波动）与低 SR
    stats_fil = regime['state_stats_filtered']
    # regime_label 的 key 是 str(int) after json roundtrip
    label_by_str = {str(r): lab for r, lab in regime_label.items()}
    crash_label = next((lab for r, lab in regime_label.items() if lab == 'crash'), None)
    # 低 SR：取 SR 最低的 regime label
    low_sr_label = min(stats_fil, key=lambda l: stats_fil[l]['sharpe'])
    log(f"hide 候选: crash={crash_label}, 低SR={low_sr_label} (SR={stats_fil[low_sr_label]['sharpe']})")

    # expanding-filtered regimes（最严 live）
    log(f"expanding fit（前{MIN_WINDOW}月暖机，逐月重估）...")
    t0 = datetime.now()
    exp_regimes = expanding_regimes(mret, k)
    log(f"  耗时 {(datetime.now()-t0).total_seconds():.0f}s，得 {sum(r is not None for r in exp_regimes)}月 regime")

    # 三层 month-state（映射到 label）
    month_state_smoothed = regime['month_state_smoothed']
    month_state_filtered = regime['month_state_filtered']
    month_state_expanding = {}
    for i, r in enumerate(exp_regimes):
        if r is not None:
            month_state_expanding[months[i]] = regime_label[str(r)]

    # 传播到周
    def weekmap(month_state):
        ws = {}
        for w in weeks:
            ym = week_to_month(w)
            if ym in month_state:
                ws[w] = month_state[ym]
        return ws
    ws_smoothed = weekmap(month_state_smoothed)
    ws_filtered = weekmap(month_state_filtered)
    ws_expanding = weekmap(month_state_expanding)
    # expanding 覆盖的周（去暖机）
    exp_weeks = set(ws_expanding.keys())

    # 择时验证
    cands = json.load(open(CAND))
    hide_sets = {'hide_crash': {crash_label}, 'hide_lowSR': {low_sr_label}}

    results = {}
    for name in LONG_NAMES:
        if name not in cands:
            continue
        strat = cands[name]
        log(f"\n{name}:")
        row = {'原版': stats([r for _, r in strat])}
        log(f"  原版(all {len(strat)}周): SR{row['原版']['sharpe']} 年化{row['原版']['annual']:.2%} MDD{row['原版']['max_dd']:.2%}")
        for hide_name, hide in hide_sets.items():
            # 三层：smoothed(上限) / filtered(live状态) / expanding(最严live)
            # expanding 只在其覆盖周内评估；smoothed/filtered 也对齐到同周以保证可比
            seg_strat = [[w, r] for w, r in strat if w in exp_weeks]
            orig_seg = stats([r for _, r in seg_strat])
            row['原版_seg'] = orig_seg  # 段内原版，与timing同口径
            sm = stats(timing(seg_strat, ws_smoothed, hide))
            fil = stats(timing(seg_strat, ws_filtered, hide))
            exp = stats(timing(seg_strat, ws_expanding, hide))
            row[f'{hide_name}/smoothed'] = sm
            row[f'{hide_name}/filtered'] = fil
            row[f'{hide_name}/expanding'] = exp
            log(f"  {hide_name} [{len(seg_strat)}周可比段] 原版SR{orig_seg['sharpe']} -> "
                f"sm SR{sm['sharpe']} / fil SR{fil['sharpe']} / exp SR{exp['sharpe']}")
        results[name] = row

    # 诚实结论（段内同口径：原版_seg vs timing）
    log("-" * 60); log("诚实结论（段内同口径对比，expanding 覆盖的可比段）:")
    for name, row in results.items():
        orig_seg = row.get('原版_seg', row['原版'])['sharpe']
        best_sm = max(row.get(f'{h}/smoothed', {}).get('sharpe', 0) for h in hide_sets)
        best_fil = max(row.get(f'{h}/filtered', {}).get('sharpe', 0) for h in hide_sets)
        best_exp = max(row.get(f'{h}/expanding', {}).get('sharpe', 0) for h in hide_sets)
        log(f"  {name}: 段内原版SR{orig_seg} | 上限(smoothed)最佳SR{best_sm} "
            f"| live(filtered)最佳SR{best_fil} | 最严live(expanding)最佳SR{best_exp}")

    out = {
        'run_at': datetime.now().isoformat(),
        'method': f'expanding fit MarkovRegression k={k}, 三层(smoothed上限/filtered-global/expanding-live)',
        'min_window': MIN_WINDOW,
        'layers': {
            'smoothed': '全局fit Kim smoother 全样本 look-ahead 理论上限',
            'filtered': '全局fit Hamilton filter 状态因果 参数全样本',
            'expanding': f'每月[0,t]重估参数+Hamilton filter 状态因果+参数无未来 最严live(前{MIN_WINDOW}月暖机)',
        },
        'hide_rules': {'hide_crash': f'高波动regime({crash_label})空仓-旧规则',
                       'hide_lowSR': f'低SR regime({low_sr_label}, SR{stats_fil[low_sr_label]["sharpe"]})空仓'},
        'month_state_expanding': month_state_expanding,
        'week_state_expanding': ws_expanding,
        'results': results,
        'caveat': 'contemporaneous timing(regime月末可知); regime持续性强故≈ex-ante; 严格ex-ante用regime(t-1)预测t',
    }
    json.dump(out, open(OUT, 'w'), indent=2, ensure_ascii=False, default=float)
    log(f"\nwritten: {OUT}")


if __name__ == '__main__':
    main()
