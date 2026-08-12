#!/home/soso/v5/.venv/bin/python3
"""orchestrator: 策略评估管道编排器（C1）

按依赖顺序串模块, 口径 config(pipeline_config.json)沿管道流转.
各模块读输入JSON写输出JSON, 可拼接可替换.

模块链(B1 SOP): funnel -> collect_* -> compare_pool(成本) -> export_holdings
  -> rq_executor -> rq_terminal_review -> 四件套证伪判定

用法:
  orchestrator.py --list                      列阶段
  orchestrator.py --stage compare_pool       跑单阶段
  orchestrator.py --from compare_pool --to rq_review  跑范围
  orchestrator.py --strategy tsmom_K12 --stage export_holdings  带策略参数

设计: 编排器只调度(读config+调脚本), 不含业务逻辑. 模块失败不静默(非0即停).
"""
import os, sys, json, argparse, subprocess
from datetime import datetime

BASE = os.path.expanduser('~/v5')
PY = '/home/soso/v5/.venv/bin/python3'
CFG = os.path.join(BASE, 'branches/strategy_factory/pipeline_config.json')


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


# 管道阶段定义: name -> (脚本, 描述, 产出)
STAGES = {
    "funnel":           ("branches/compare/funnel.py", "阶段1 因子筛选五路漏斗", "funnel_result.json"),
    "collect":          (None, "阶段2 候选执行(多脚本, 见B1)", "candidates_returns.json"),
    "compare_pool":     ("branches/compare/compare_pool.py", "阶段3 成本复核+MCS/DSR(净口径)", "compare_pool_result.json"),
    "export_holdings":  ("branches/compare/export_holdings.py", "阶段4a 导出周持仓", "<strategy>_holdings.json"),
    "rq_executor":      ("branches/compare/run_rq.py", "阶段4b RQAlpha真实撮合终审", "rq_result_<tag>.pkl"),
    "rq_review":        ("branches/compare/rq_terminal_review.py", "阶段4c 三口径对比+归因", "rq_review_<strategy>.json"),
}

ORDER = ["funnel", "collect", "compare_pool", "export_holdings", "rq_executor", "rq_review"]


def run_cmd(cmd, env_extra=None):
    log(f"RUN: {' '.join(cmd)}")
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    r = subprocess.run(cmd, cwd=BASE, env=env)
    if r.returncode != 0:
        log(f"FATAL: 阶段失败 returncode={r.returncode}")
        sys.exit(r.returncode)


def load_config():
    return json.load(open(CFG))


def stage_collect():
    """阶段2: 候选执行多脚本(部分碰DB重计算, 按需跑)."""
    log("阶段2 候选执行: collect_candidates -> collect_heterogeneous -> market_benchmark -> lowvol_weekly")
    log("  注: market_benchmark/lowvol 碰DB(10min), collect_*秒级. daily_pick 走 strategy_factory --backtest --export-holdings")
    for s in ["branches/compare/collect_candidates.py",
              "branches/compare/collect_heterogeneous.py"]:
        run_cmd([PY, s])
    log("  market_benchmark/lowvol/strategy_factory 按需单独跑(碰DB), 此编排器不自动跑(避免长任务)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--list', action='store_true', help='列出阶段')
    ap.add_argument('--stage', help='跑单阶段')
    ap.add_argument('--from', dest='frm', help='起始阶段')
    ap.add_argument('--to', help='结束阶段')
    ap.add_argument('--strategy', default='tsmom_K12', help='export_holdings/rq 策略名')
    ap.add_argument('--tag', help='rq_executor 结果标签')
    ap.add_argument('--capital', type=float, help='RQAlpha 资金(覆盖config)')
    args = ap.parse_args()

    if args.list:
        cfg = load_config()
        log(f"管道阶段(口径 config: {CFG}):")
        for s in ORDER:
            sc, desc, out = STAGES[s]
            log(f"  {s:<18} {desc:<32} -> {out}")
        log(f"\ncost_model: candidates固定{cfg['cost_model']['candidates_layer']['round_trip_bp']}bp + RQAlpha真实(capital={cfg['cost_model']['rqalpha_layer']['capital']})")
        return

    cfg = load_config()

    if args.stage:
        stages = [args.stage]
    elif args.frm or args.to:
        i0 = ORDER.index(args.frm) if args.frm else 0
        i1 = ORDER.index(args.to) if args.to else len(ORDER)
        stages = ORDER[i0:i1 + 1]
    else:
        log("缺 --stage/--from/--to, 用 --list 看阶段"); return

    for s in stages:
        if s not in STAGES:
            log(f"未知阶段: {s}"); continue
        script, desc, _ = STAGES[s]
        log("=" * 60)
        log(f"阶段: {s} ({desc})")
        if s == "collect":
            stage_collect(); continue
        if s == "compare_pool":
            run_cmd([PY, script])
        elif s == "export_holdings":
            run_cmd([PY, script, "--strategy", "tsmom", "--name", args.strategy,
                     "--out", f"branches/compare/{args.strategy}_holdings.json"])
        elif s == "rq_executor":
            tag = args.tag or args.strategy
            cap = args.capital or cfg['cost_model']['rqalpha_layer']['capital']
            hpath = f"branches/compare/{args.strategy}_holdings.json"
            run_cmd([PY, script, hpath, tag, str(cap),
                     str(cfg['cost_model']['rqalpha_layer']['min_commission']),
                     "normal" if cfg['cost_model']['rqalpha_layer']['price_limit'] else "nolimit",
                     cfg['start'], cfg['end']])
        elif s == "rq_review":
            tag = args.tag or args.strategy
            run_cmd([PY, script, "--pkl", f"branches/compare/rq_result_{tag}.pkl",
                     "--strategy", args.strategy])
        elif s == "funnel":
            run_cmd([PY, script])
        log(f"阶段 {s} 完成")
    log("=" * 60)
    log("编排完成. 口径 config 沿管道流转, 产出见各阶段 out 字段(--list).")


if __name__ == '__main__':
    main()
