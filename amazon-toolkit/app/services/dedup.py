"""去重入库核心逻辑（系统自动过滤 + 冲突转人工）
去重键 = SKU。重量是批次变量，永远追加不判重。
"""
from app import db

# 参与一致比对的单值属性（重量除外）
COMPARE_FIELDS = ["asin", "title", "color", "size", "category",
                  "purchase_price", "purchase_url", "p1688_id", "purchase_spec"]


def ingest(batch: str, sku_key: str, attrs: dict, source: str):
    """入库一条记录（跟卖/发货还原后）。返回 dict:
    action: added(新增) | skipped(完全一致跳过) | conflict(转人工审核)
    product: product_master 行或缺省 None/挂起标记
    conflicts: [{"sku", "field", "old", "new"}, ...]
    """
    conn = db.get_conn()
    sku_key = str(sku_key).strip()
    if not sku_key:
        return {"action": "error", "reason": "缺少SKU"}

    existing = _find_existing(conn, sku_key)
    created = _now()

    if existing is None:
        cur = conn.execute(
            """INSERT INTO product_master(sku, asin, title, color, size, category,
                purchase_price, purchase_url, purchase_spec, p1688_id, ref_weight, target_margin,
                source, status, created_at, updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (sku_key, attrs.get("asin"), attrs.get("title"), attrs.get("color"),
             attrs.get("size"), attrs.get("category"), _f(attrs.get("purchase_price")),
             attrs.get("purchase_url"), attrs.get("purchase_spec"), attrs.get("p1688_id"),
             _f(attrs.get("ref_weight")), _f(attrs.get("target_margin")),
             source, "待确认" if _needs_confirm(attrs) else "active", created, created),
        )
        conn.commit()
        return {"action": "added", "product": _row_by_product_id(conn, cur.lastrowid), "conflicts": []}

    # 已存在：比对单值属性
    conflicts = []
    for f in COMPARE_FIELDS:
        if f not in attrs or attrs[f] in (None, ""):
            continue
        old = existing[f]
        new = str(attrs[f])
        if old is None or str(old) == "":
            continue  # 库中空缺，不视为冲突（可后续补齐）
        if str(old) != new:
            conflicts.append({"sku": sku_key, "field": f, "old": str(old), "new": new})
    if conflicts:
        for c in conflicts:
            conn.execute(
                "INSERT INTO dedup_review(sku, field, old_value, new_value, batch, status, created_at) "
                "VALUES(?,?,?,?,?,'pending',?)",
                (sku_key, c["field"], c["old"], c["new"], batch, created))
        conn.commit()
        return {"action": "conflict", "product": existing, "conflicts": conflicts}
    return {"action": "skipped", "product": existing, "conflicts": []}


def _find_existing(conn, sku_key: str):
    # 规范 SKU 直接命中；乱码 SKU 经别名映射命中
    row = conn.execute("SELECT * FROM product_master WHERE sku=?", (sku_key,)).fetchone()
    if row:
        return row
    return conn.execute(
        """SELECT pm.* FROM sku_alias a JOIN product_master pm ON pm.product_id=a.product_id
           WHERE a.alias_sku=? LIMIT 1""", (sku_key,)).fetchone()


def _row_by_product_id(conn, pid):
    return conn.execute("SELECT * FROM product_master WHERE product_id=?", (pid,)).fetchone()


def _needs_confirm(attrs):
    """颜色/尺码带 * 的说明是未收录值，标待确认"""
    return isinstance(attrs.get("color"), str) and attrs["color"].startswith("*") or \
           isinstance(attrs.get("size"), str) and attrs["size"].startswith("*")


def _f(v):
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _now():
    return db.now()