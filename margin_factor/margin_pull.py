#!/home/soso/v5/.venv/bin/python3
"""Phase 1: 拉融资融券明细 (沪深, 2023-2026)
akshare stock_margin_detail_sse/szse, 存 margin_detail 表。
沪深字段不同统一映射: 深市缺融资偿还额/融券偿还量填 None。
断点续传。代码加 sh/sz 前缀匹配 daily_kline。
"""
import sys, os, sqlite3, time
from datetime import datetime
import akshare as ak

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
START = '2023-01-01'
END = '2026-07-20'
LOG = os.path.expanduser('~/v5/margin_factor/margin_pull.log')


def log(m):
    line = f"[{datetime.now():%H:%M:%S}] {m}"
    print(line, flush=True)
    with open(LOG, 'a') as f:
        f.write(line + '\n')


def get_trade_dates(db):
    return [str(r[0])[:10] for r in db.execute(
        "SELECT DISTINCT date FROM daily_kline WHERE date>=? AND date<=? ORDER BY date",
        (START, END)).fetchall()]


def pull_sse(date, db):
    """沪市: 标的证券代码, 融资余额, 融资买入额, 融资偿还额, 融券余量, 融券卖出量, 融券偿还量"""
    ds = date.replace('-', '')
    df = ak.stock_margin_detail_sse(date=ds)
    rows = []
    for _, r in df.iterrows():
        code = 'sh' + str(r['标的证券代码']).zfill(6)
        rows.append((code, date, float(r['融资余额']), float(r['融资买入额']), float(r['融资偿还额']),
                     float(r['融券余量']), float(r['融券卖出量']), float(r['融券偿还量'])))
    db.executemany("INSERT OR REPLACE INTO margin_detail VALUES (?,?,?,?,?,?,?,?)", rows)
    return len(rows)


def pull_szse(date, db):
    """深市: 证券代码, 融资买入额, 融资余额, 融券卖出量, 融券余量 (无融资偿还额/融券偿还量)"""
    ds = date.replace('-', '')
    df = ak.stock_margin_detail_szse(date=ds)
    rows = []
    for _, r in df.iterrows():
        code = 'sz' + str(r['证券代码']).zfill(6)
        rows.append((code, date, float(r['融资余额']), float(r['融资买入额']), None,
                     float(r['融券余量']), float(r['融券卖出量']), None))
    db.executemany("INSERT OR REPLACE INTO margin_detail VALUES (?,?,?,?,?,?,?,?)", rows)
    return len(rows)


def main():
    log("=" * 60)
    log(f"Phase 1: 拉融资融券 {START}~{END}")
    log("=" * 60)
    db = sqlite3.connect(DB)
    db.execute("""CREATE TABLE IF NOT EXISTS margin_detail (
        code TEXT, date TEXT, rz_ye REAL, rz_buy REAL, rz_repay REAL,
        rq_yl REAL, rq_sell REAL, rq_repay REAL, PRIMARY KEY(code,date))""")
    db.commit()
    dates = get_trade_dates(db)
    done = set(r[0] for r in db.execute("SELECT DISTINCT date FROM margin_detail"))
    todo = [d for d in dates if d not in done]
    log(f"total {len(dates)} days, done {len(done)}, todo {len(todo)}")
    t0 = time.time()
    for i, date in enumerate(todo):
        n = 0
        try:
            n += pull_sse(date, db)
        except Exception as e:
            log(f"  {date} 沪 ERR: {e}")
        try:
            n += pull_szse(date, db)
        except Exception as e:
            log(f"  {date} 深 ERR: {e}")
        db.commit()
        time.sleep(0.5)
        if (i + 1) % 30 == 0:
            cnt = db.execute("SELECT COUNT(*) FROM margin_detail").fetchone()[0]
            log(f"  {i+1}/{len(todo)} {date} +{n} total={cnt} [{time.time()-t0:.0f}s]")
    cnt = db.execute("SELECT COUNT(*) FROM margin_detail").fetchone()[0]
    log(f"done: {cnt} rows")
    db.close()


if __name__ == '__main__':
    main()
