"""SQLite 数据层：建表 + 种子数据 + 通用查询"""
import sqlite3
import threading
from datetime import datetime
from app import config

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS product_master (
    product_id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku TEXT UNIQUE NOT NULL,
    asin TEXT, title TEXT,
    color TEXT, size TEXT, category TEXT,
    purchase_price REAL, purchase_url TEXT, purchase_spec TEXT, p1688_id TEXT,
    ref_weight REAL, target_margin REAL,
    source TEXT DEFAULT '跟卖', status TEXT DEFAULT 'active',
    created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS sku_alias (
    alias_sku TEXT PRIMARY KEY,
    product_id INTEGER,
    note TEXT,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS sku_prefix (
    prefix TEXT PRIMARY KEY,
    ref_hash INTEGER,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS config_kv (
    key TEXT PRIMARY KEY, value TEXT
);
CREATE TABLE IF NOT EXISTS dict_color (
    id INTEGER PRIMARY KEY AUTOINCREMENT, std TEXT NOT NULL, alias TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS dict_size (
    id INTEGER PRIMARY KEY AUTOINCREMENT, std TEXT NOT NULL, alias TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS dedup_review (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku TEXT, field TEXT, old_value TEXT, new_value TEXT,
    batch TEXT, status TEXT DEFAULT 'pending', created_at TEXT
);
CREATE TABLE IF NOT EXISTS batch_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_type TEXT, filename TEXT, batch_id TEXT UNIQUE, summary TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS shipping_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id TEXT, order_no TEXT, sku TEXT, color TEXT, size TEXT,
    tracking_no TEXT, channel TEXT, weight REAL, postcode TEXT, qty INTEGER DEFAULT 1,
    image_path TEXT, product_id INTEGER, purchase_price REAL,
    profit_est REAL, profit_note TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS weight_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER, sku TEXT, batch_at TEXT, weight REAL,
    source TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS courier_check (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id TEXT, ref_no TEXT, our_weight REAL, courier_weight REAL,
    diff_pct REAL, alert INTEGER DEFAULT 0, resolved INTEGER DEFAULT 0, created_at TEXT
);
CREATE TABLE IF NOT EXISTS freight_template (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel TEXT, first_weight REAL, first_price REAL, cont_weight REAL, cont_price REAL, currency TEXT DEFAULT 'USD'
);
CREATE TABLE IF NOT EXISTS postcode_surcharge (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel TEXT, country TEXT, postcode_pattern TEXT, surcharge REAL, note TEXT
);
CREATE TABLE IF NOT EXISTS price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER, sku TEXT, ref_date TEXT, price REAL, floor_price REAL,
    price_source TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS purchase_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id TEXT, p1688_id TEXT, url TEXT, sku TEXT, spec TEXT,
    qty INTEGER, unit_price REAL, address TEXT, created_at TEXT
);
"""

SEED_COLORS = {
    "黑色": ["黑", "black", "blk", "BK"],
    "白色": ["白", "white", "wht", "WH"],
    "红色": ["红", "red", "RD"],
    "蓝色": ["蓝", "blue", "BL"],
    "绿色": ["绿", "green", "GR"],
    "黄色": ["黄", "yellow", "YL"],
    "灰色": ["灰", "grey", "gray", "GY"],
    "粉色": ["粉", "pink", "PK"],
    "紫色": ["紫", "purple", "PU"],
    "驼色": ["驼", "camel", "ca"],
    "卡其色": ["卡其", "khaki", "kh"],
    "藏青色": ["藏青", "navy", "nv"],
}
SEED_SIZES = {
    "XS": ["xs", "加小"],
    "S": ["s", "小码", "S码"],
    "M": ["m", "中码", "M码"],
    "L": ["l", "大码", "L码"],
    "XL": ["xl", "加大"],
    "XXL": ["xxl", "2xl", "2XL"],
}


def get_conn() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(config.DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        _local.conn = conn
    return conn


def init_db():
    conn = get_conn()
    conn.executescript(SCHEMA)
    # 种子默认配置
    for k, v in config.DEFAULT_CONFIG.items():
        conn.execute("INSERT OR IGNORE INTO config_kv(key, value) VALUES(?, ?)", (k, v))
    # 种子颜色/尺码字典
    for std, aliases in SEED_COLORS.items():
        for a in aliases:
            conn.execute("INSERT OR IGNORE INTO dict_color(std, alias) VALUES(?, ?)", (std, a.lower()))
    for std, aliases in SEED_SIZES.items():
        for a in aliases:
            conn.execute("INSERT OR IGNORE INTO dict_size(std, alias) VALUES(?, ?)", (std, a.lower()))
    conn.commit()


def get_config(key: str, default="") -> str:
    row = get_conn().execute("SELECT value FROM config_kv WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_config(key: str, value: str):
    conn = get_conn()
    conn.execute("INSERT INTO config_kv(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
    conn.commit()


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")