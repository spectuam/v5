#!/home/soso/v5/.venv/bin/python3
"""TDX vipdoc 本地文件 → TDX SQLite (后备通道)

老板手动在 Windows TDX 盘后下载数据后，指定日期同步:
  python3 tdx_vipdoc_sync.py --dates 2026-07-16,2026-07-17,2026-07-18
  python3 tdx_vipdoc_sync.py --since 2026-07-16

源: /mnt/c/new_tdx64/vipdoc/{sh,sz}/lday/*.day (二进制, 不复权)
目标: tdx_stock_data.db → daily_kline (后复权)
"""

import sys, os, time, struct, sqlite3
from datetime import datetime, date, timedelta
from collections import defaultdict

VIPDOC = "/mnt/c/new_tdx64/vipdoc"
DB = os.path.expanduser("~/ading/db/tdx_stock_data.db")

def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


# ── 读 TDX .day 二进制文件 ──
def read_day_file(filepath, target_dates=None):
    """读取通达信日线文件，返回 [{code, date, open, high, low, close, volume, amount}]"""
    results = []
    try:
        with open(filepath, "rb") as f:
            data = f.read()
    except OSError:
        return results

    # 每笔 32 字节: date(4) open(4) high(4) low(4) close(4) amount(4) volume(4) reserved(4)
    RECORD_SIZE = 32
    n = len(data) // RECORD_SIZE
    for i in range(n):
        off = i * RECORD_SIZE
        raw = data[off:off + RECORD_SIZE]
        dt_int = struct.unpack_from("<I", raw, 0)[0]
        # TDX 日期格式: YYYYMMDD as integer
        dt_str = str(dt_int)
        if len(dt_str) != 8:
            continue
        d = f"{dt_str[:4]}-{dt_str[4:6]}-{dt_str[6:8]}"
        if target_dates and d not in target_dates:
            continue

        open_p  = struct.unpack_from("<I", raw, 4)[0] / 100.0
        high_p  = struct.unpack_from("<I", raw, 8)[0] / 100.0
        low_p   = struct.unpack_from("<I", raw, 12)[0] / 100.0
        close_p = struct.unpack_from("<I", raw, 16)[0] / 100.0
        amount  = struct.unpack_from("<f", raw, 20)[0]
        volume  = struct.unpack_from("<I", raw, 24)[0]

        # 过滤无效数据
        if open_p < 0.01 and close_p < 0.01:
            continue

        results.append({
            "date": d,
            "open": open_p, "high": high_p, "low": low_p,
            "close": close_p, "volume": volume, "amount": amount,
        })
    return results


# ── 加载股票映射 ──
def load_stock_map():
    """从 stock_info 加载 code → (symbol, name)"""
    db = sqlite3.connect(DB)
    rows = db.execute(
        "SELECT symbol, name FROM stock_info WHERE class='stock'"
    ).fetchall()
    db.close()
    # sh600000 → market=sh, code=600000
    return {(r[0][:2], r[0][2:]): r[0] for r in rows}


# ── 加载复权因子 ──
def load_factors():
    db = sqlite3.connect(DB)
    factors = {}
    for code, f in db.execute("SELECT code, hfq_factor FROM adjustment_factor"):
        factors[code] = f
    db.close()
    return factors


# ── 更新 stock_info (新股上市) ──
def update_stock_info():
    """扫描 vipdoc，把 stock_info 里没有的股票补进去"""
    db = sqlite3.connect(DB)
    existing = set(r[0] for r in db.execute("SELECT symbol FROM stock_info").fetchall())

    new_stocks = []
    for market in ["sh", "sz", "bj"]:
        lday_dir = os.path.join(VIPDOC, market, "lday")
        if not os.path.isdir(lday_dir):
            continue
        for fname in os.listdir(lday_dir):
            if not fname.endswith(".day"):
                continue
            symbol = fname.replace(".day", "")
            if symbol not in existing:
                # 只加真股票: sh60, sz00, sz30, bj (排除 ETF sh51, 指数 sh00/sz39 等)
                if (symbol.startswith('sh60') or symbol.startswith('sh68') or
                    symbol.startswith('sz00') or symbol.startswith('sz30') or
                    symbol.startswith('bj')):
                    new_stocks.append(symbol)

    if new_stocks:
        db.executemany(
            "INSERT OR IGNORE INTO stock_info (symbol, name, class) VALUES (?, '', 'stock')",
            [(s,) for s in new_stocks]
        )
        db.commit()
        log(f"  stock_info: added {len(new_stocks)} new stocks from vipdoc")
    else:
        log(f"  stock_info: up to date")
    db.close()


# ── 更新复权因子 (从 DuckDB, 需先在 Windows 端跑 tdx2db cron) ──
def update_adjustment_factors():
    """从 DuckDB raw_adjust_factor 导出最新复权因子到 SQLite"""
    duckdb_path = os.path.join(os.path.dirname(VIPDOC), "tdx.db")
    if not os.path.exists(duckdb_path):
        log(f"  adj factors: DuckDB not found at {duckdb_path}, skipping")
        return

    try:
        import duckdb
        con = duckdb.connect(duckdb_path, read_only=True)
        rows = con.execute("""
            SELECT symbol, hfq_factor FROM (
                SELECT symbol, hfq_factor,
                       ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date DESC) as rn
                FROM raw_adjust_factor
            ) WHERE rn = 1
        """).fetchall()
        con.close()
    except Exception as e:
        log(f"  adj factors: DuckDB error: {e}")
        return

    if not rows:
        log(f"  adj factors: no data from DuckDB")
        return

    db = sqlite3.connect(DB)
    updated = 0
    new = 0
    for symbol, factor in rows:
        old = db.execute("SELECT hfq_factor FROM adjustment_factor WHERE code=?", (symbol,)).fetchone()
        if old:
            if abs(old[0] - factor) > 0.0001:
                db.execute("UPDATE adjustment_factor SET hfq_factor=? WHERE code=?", (factor, symbol))
                updated += 1
        else:
            db.execute("INSERT INTO adjustment_factor (code, hfq_factor) VALUES (?, ?)", (symbol, factor))
            new += 1
    db.commit()
    db.close()
    log(f"  adj factors: {len(rows)} total, {updated} updated, {new} new")


# ── 同步 ──
def sync_vipdoc(target_dates):
    update_stock_info()

    stock_map = load_stock_map()
    factors = load_factors()
    log(f"{len(stock_map)} stocks mapped, {len(factors)} adj factors")

    date_set = set(target_dates)
    all_rows = []
    files_read = 0
    files_hit = 0

    for market in ["sh", "sz", "bj"]:
        lday_dir = os.path.join(VIPDOC, market, "lday")
        if not os.path.isdir(lday_dir):
            log(f"  Missing: {lday_dir}")
            continue

        for fname in sorted(os.listdir(lday_dir)):
            if not fname.endswith(".day"):
                continue
            # sh600000.day → market=sh, code=600000
            code_num = fname.replace(".day", "")
            if code_num.startswith(market):
                code_num = code_num[len(market):]
            key = (market, code_num)
            db_code = stock_map.get(key)
            if db_code is None:
                continue

            filepath = os.path.join(lday_dir, fname)
            rows = read_day_file(filepath, date_set)
            files_read += 1
            if rows:
                files_hit += 1
                for r in rows:
                    r["code"] = db_code
                all_rows.extend(rows)

            if files_read % 1000 == 0:
                log(f"  [{files_read} files] {len(all_rows)} rows, {files_hit} with data")

    log(f"  Read {files_read} files: {files_hit} with data, {len(all_rows)} total rows")

    if not all_rows:
        log("  No data found for specified dates")
        return 0

    # 后复权 + 写入
    db = sqlite3.connect(DB)
    written, skipped, no_factor = 0, 0, 0
    for r in all_rows:
        code, d = r["code"], r["date"]

        # 检查已存在
        existing = db.execute(
            "SELECT open FROM daily_kline WHERE code=? AND date=?",
            (code, d + " 00:00:00")
        ).fetchone()
        if existing and existing[0] is not None and existing[0] > 0:
            skipped += 1
            continue

        f = factors.get(code)
        if f is None:
            no_factor += 1
            continue

        db.execute("""
            INSERT OR REPLACE INTO daily_kline (code, date, open, high, low, close, volume, amount)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (code, d + " 00:00:00",
              round(r["open"]*f, 2), round(r["high"]*f, 2),
              round(r["low"]*f, 2), round(r["close"]*f, 2),
              r["volume"], r["amount"]))
        written += 1

    db.commit()
    db.close()

    log(f"  Written: {written} | Skipped: {skipped} | No factor: {no_factor}")
    return written


if __name__ == "__main__":
    dates = []
    for i, a in enumerate(sys.argv):
        if a == '--dates' and i+1 < len(sys.argv):
            dates = sys.argv[i+1].split(",")
        elif a == '--since' and i+1 < len(sys.argv):
            since = date.fromisoformat(sys.argv[i+1])
            today = date.today()
            d = since
            while d <= today:
                if d.weekday() < 5:  # 周一到周五
                    dates.append(d.strftime("%Y-%m-%d"))
                d += timedelta(days=1)

    if not dates:
        print("Usage: tdx_vipdoc_sync.py --dates 2026-07-16,2026-07-17")
        print("       tdx_vipdoc_sync.py --since 2026-07-16")
        sys.exit(1)

    log(f"Syncing {len(dates)} dates: {dates[0]} ~ {dates[-1]}")
    n = sync_vipdoc(dates)
    log(f"Done: {n} rows written")
