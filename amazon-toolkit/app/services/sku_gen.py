"""SKU 前缀分配与生成 + 乱码 SKU 映射还原"""
import hashlib
from app import db


def _ref_hash(title: str) -> int:
    """稳定哈希：相同标题跨进程/重启后始终一致（内置 hash() 每进程随机，不可用）"""
    return int(hashlib.md5(title.strip().encode("utf-8")).hexdigest()[:12], 16)


def _next_prefix(conn):
    """分配下一个 4 位数字前缀（从 0001 起，同款共用）"""
    row = conn.execute("SELECT COALESCE(MAX(CAST(prefix AS INTEGER)), 0) AS m FROM sku_prefix").fetchone()
    return f"{row['m'] + 1:04d}"


def build_sku(color: str, size: str, title_ref: str = ""):
    """为新品生成规范 SKU：前缀 + 颜色 + 尺码。
    同款(标题完全一致)复用已有前缀；否则分配新前缀。"""
    conn = db.get_conn()
    existing = None
    if title_ref.strip():
        row = conn.execute(
            "SELECT prefix FROM sku_prefix WHERE ref_hash=? LIMIT 1",
            (_ref_hash(title_ref),),
        ).fetchone()
        if row:
            existing = row["prefix"]
    prefix = existing or _next_prefix(conn)
    if not existing:
        conn.execute(
            "INSERT INTO sku_prefix(prefix, ref_hash) VALUES(?, ?)",
            (prefix, _ref_hash(title_ref) if title_ref.strip() else None),
        )
        conn.commit()
    return f"{prefix}-{color}-{size}"


def parse_sku(sku: str):
    """尝试解析规范 SKU -> (prefix, color, size)；失败返回 None"""
    import re
    m = re.match(r"^(\d{4})-(.+?)-(.+)$", sku.strip())
    if m:
        return m.group(1), m.group(2), m.group(3)
    return None


def resolve(sku: str):
    """按 SKU 查找已入库产品。返回 product_master 行(含 product_id) 或 None。
    先查乱码别名映射，再查规范 SKU。"""
    conn = db.get_conn()
    s = str(sku).strip()
    if not s:
        return None
    row = conn.execute(
        """SELECT pm.* FROM sku_alias a JOIN product_master pm ON pm.product_id=a.product_id
           WHERE a.alias_sku=? LIMIT 1""", (s,)).fetchone()
    if row:
        return row
    row = conn.execute("SELECT * FROM product_master WHERE sku=? LIMIT 1", (s,)).fetchone()
    return row


def find_alias(sku: str):
    """乱码 SKU 是否已建立映射。返回 alias 行(可能 product_id 为空)"""
    conn = db.get_conn()
    return conn.execute("SELECT * FROM sku_alias WHERE alias_sku=?", (str(sku).strip(),)).fetchone()


def bind_alias(alias_sku: str, product_id: int, note: str = ""):
    """人工确认：把乱码 SKU 绑定到某产品"""
    conn = db.get_conn()
    conn.execute(
        "INSERT INTO sku_alias(alias_sku, product_id, note, created_at) VALUES(?, ?, ?, ?) "
        "ON CONFLICT(alias_sku) DO UPDATE SET product_id=excluded.product_id, note=excluded.note",
        (str(alias_sku).strip(), product_id, note, db.now()),
    )
    conn.commit()