#!/home/soso/v5/.venv/bin/python3
"""RQAlpha 通用启动器（A2 泛化）

用法: run_rq.py <holdings_json> <tag> [capital] [min_commission] [nolimit] [start] [end]
  holdings_json: export_holdings.py 产出的持仓文件(含 'holdings' 键)
  tag: 结果标签 -> rq_result_<tag>.pkl
  capital: 资金规模(默认1e6)
  min_commission: 最小佣金(默认5.0元)
  nolimit: 关闭涨跌停限制(price_limit=False)
  start/end: 可选, 默认 2016-01-04 ~ 2026-06-30

泛化自 DSF run_rq.py(硬编码 rq_tsmom_ls.py 单策略) -> 通用 rq_executor.py + 任意 holdings.
通过 HOLDINGS_PATH 环境变量传持仓路径给 rq_executor(策略文件无法用 argparse).
"""
import sys
import os
import rqalpha

if len(sys.argv) < 2:
    print("用法: run_rq.py <holdings_json> <tag> [capital] [min_commission] [nolimit] [start] [end]")
    sys.exit(1)

hpath = sys.argv[1]
tag = sys.argv[2] if len(sys.argv) > 2 else "run"
capital = float(sys.argv[3]) if len(sys.argv) > 3 else 1e6
min_comm = float(sys.argv[4]) if len(sys.argv) > 4 else 5.0
nolimit = len(sys.argv) > 5 and sys.argv[5] == "nolimit"
start = sys.argv[6] if len(sys.argv) > 6 else "2016-01-04"
end = sys.argv[7] if len(sys.argv) > 7 else "2026-06-30"
out = f"/home/soso/v5/branches/compare/rq_result_{tag}.pkl"

# 传持仓路径给 rq_executor 策略文件
os.environ['HOLDINGS_PATH'] = os.path.abspath(hpath)

config = {
    "base": {
        "start_date": start,
        "end_date": end,
        "frequency": "1d",
        "benchmark": "000300.XSHG",
        "accounts": {"stock": capital},
        "data_bundle_path": "/home/soso/.rqalpha/bundle",
        "strategy_file": "branches/compare/rq_executor.py",
    },
    "mod": {
        "sys_analyser": {
            "enabled": True,
            "plot": False,
            "output_file": out,
        },
        "sys_transaction_cost": {
            "enabled": True,
            "stock_min_commission": min_comm,
        },
        "sys_simulation": {
            "enabled": True,
            "matching_type": "current_bar",
            "slippage": 0,
            "price_limit": not nolimit,
        },
    },
}

print(f"RUN rq_executor | holdings={hpath} tag={tag} capital={capital} "
      f"min_comm={min_comm} nolimit={nolimit} {start}~{end}")
rqalpha.run_file("branches/compare/rq_executor.py", config=config)
print(f"DONE -> {out}")
