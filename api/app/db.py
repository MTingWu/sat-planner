import os

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

# open=False：import 時不連線，由 main.py 的 lifespan 在啟動時開啟、關閉時釋放。
# 這樣沒有資料庫也能 import app（例如只跑單元測試）。
pool = ConnectionPool(
    conninfo=os.environ.get("DATABASE_URL", ""),
    min_size=1,
    max_size=5,
    timeout=10,                              # 拿不到連線時最多等 10 秒（預設 30）
    check=ConnectionPool.check_connection,   # 借出前先確認連線還活著：Neon 閒置時會斷線
    kwargs={"row_factory": dict_row},        # 全部查詢統一回傳 dict
    open=False,
)