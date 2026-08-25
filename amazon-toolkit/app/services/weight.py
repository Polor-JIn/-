"""多批次重量 + 优先级取重
优先级: 确认重量(货代/手动实测) > 发货单当日 > 历史批次均值 > 参考重量(手填兜底)
"""
from app import db


def add_weight(sku: str, product_id, batch_at, weight, source: str):
    conn = db.get_conn()
    w = _f(weight)
    if w is None:
        return None
    conn.execute(
        "INSERT INTO weight_history(product_id, sku, batch_at, weight, source, created_at) "
        "VALUES(?,?,?,?,?,?)", (product_id, sku, batch_at, w, source, db.now()))
    conn.commit()
    return w


def effective_weight(product_id, sku="") -> tuple:
    """按优先级取有效重量。返回 (weight, source) 或 (None,"无")"""
    conn = db.get_conn()
    if not product_id:
        try:
            row = conn.execute("SELECT product_id FROM product_master WHERE sku=?", (sku,)).fetchone()
            if not row:
                return None, "无"
            product_id = row["product_id"]
        except Exception:
            return None, "无"

    def latest(sources):
        ph = ",".join("?" for _ in sources)
        r = conn.execute(
            f"SELECT weight FROM weight_history WHERE product_id=? AND source IN ({ph}) "
            "ORDER BY batch_at DESC, id DESC LIMIT 1", (product_id, *sources)).fetchone()
        return r["weight"] if r else None

    w = latest(("货代", "确认", "手动"))
    if w is not None:
        return w, "确认重量"
    w = latest(("发货单",))
    if w is not None:
        return w, "发货单重量"
    r = conn.execute(
        "SELECT AVG(weight) m FROM weight_history WHERE product_id=? AND weight IS NOT NULL",
        (product_id,)).fetchone()
    if r and r["m"]:
        return round(r["m"], 3), "历史均值"
    row = conn.execute("SELECT ref_weight FROM product_master WHERE product_id=?", (product_id,)).fetchone()
    if row and row["ref_weight"]:
        return row["ref_weight"], "参考重量"
    return None, "无"


def history(product_id=None, sku=""):
    conn = db.get_conn()
    args = []
    sql = "SELECT * FROM weight_history WHERE 1=1"
    if product_id:
        sql += " AND product_id=?"
        args.append(product_id)
    if sku:
        sql += " AND sku=?"
        args.append(sku)
    sql += " ORDER BY batch_at DESC, id DESC"
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


def _f(v):
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None