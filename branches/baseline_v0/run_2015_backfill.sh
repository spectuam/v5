#!/bin/bash
# #1 factor_map 回填 2015（B 方案：4 OHLCV + 38 正交）
# 顺序：factor_map.py(4 OHLCV) -> to_table(重建表) -> factor_map_38.py(38 正交)
# to_table DROP 整表，必须在 factor_map.py 后、factor_map_38.py 前
set -e
cd /home/soso/v5
PY=~/v5/.venv/bin/python3

echo "[$(date +%H:%M:%S)] === Step 1/3: factor_map.py (4 OHLCV 2015-2026, rz_buy 2023+) ==="
$PY branches/factor_persistence/factor_map.py

echo "[$(date +%H:%M:%S)] === Step 2/3: factor_map_to_table.py (DROP+重建表 4 OHLCV) ==="
$PY branches/factor_persistence/factor_map_to_table.py

echo "[$(date +%H:%M:%S)] === Step 3/3: factor_map_38.py (38 正交 2015-2026) ==="
$PY branches/factor_persistence/factor_map_38.py

echo "[$(date +%H:%M:%S)] === ALL DONE ==="
