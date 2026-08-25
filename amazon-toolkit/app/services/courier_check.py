"""货代称重清单对账：差异预警 + 采用货代重量"""
from app import db
from app.services import weight as weight_svc


def run_check(df, mapping, batch: str):
    conn = db.get_conn()
    threshold = float(db.get_config("weight_diff_threshold", "3") or 3)
    items, known, unknown = [], 0, 0

    for _i, row in df.iterrows():
        def g(f):
            col = mapping.get(f)
            v = row[col] if col else None
            return str(v).strip() if v is not None else ""

        ref_no = g("ref_no") or g("tracking_no")
        cw = _f(g("c_weight"))
        if not ref_no or not cw:
            continue

        # 我方重量：优先匹配发货订单记录，其次重量批次/参考重量
        order = conn.execute(
            "SELECT * FROM shipping_orders WHERE tracking_no=? ORDER BY created_at DESC LIMIT 1",
            (ref_no,)).fetchone()
        our, src = None, ""
        if order and order["weight"]:
            our, src = order["weight"], f"发货单({order['sku']})"
        else:
            if order and order["product_id"]:
                our, src = weight_svc.effective_weight(order["product_id"])
            else:
                our, src = None, "未知产品"

        diff_pct = None
        if our:
            diff_pct = round((cw - our) / our * 100, 2)
        alert = 1 if (diff_pct is not None and abs(diff_pct) > threshold) else 0
        conn.execute(
            "INSERT INTO courier_check(batch_id, ref_no, our_weight, courier_weight, diff_pct, alert, resolved, created_at) "
            "VALUES(?,?,?,?,?,?,0,?)", (batch, ref_no, our, cw, diff_pct, alert, db.now()))
        items.append({"ref_no": ref_no, "our_weight": our or "-", "courier_weight": cw,
                      "diff_pct": diff_pct, "alert": alert, "our_source": src})
        if our:
            known += 1
        else:
            unknown += 1
    conn.commit()
    return {"items": items, "threshold": threshold,
            "stats": {"rows": len(items), "known": known, "unknown": unknown,
                      "alert": sum(1 for i in items if i["alert"])}}


def apply_courier_weight(check_ids):
    """把通过的货代称重写入多批次重量（source=货代）"""
    conn = db.get_conn()
    n = 0
    for cid in check_ids:
        row = conn.execute("SELECT * FROM courier_check WHERE id=?", (cid,)).fetchone()
        if not row or row["resolved"]:
            continue
        order = conn.execute(
            "SELECT * FROM shipping_orders WHERE tracking_no=? ORDER BY created_at DESC LIMIT 1",
            (row["ref_no"],)).fetchone()
        pid = order["product_id"] if order else None
        if not pid:
            continue
        weight_svc.add_weight(order["sku"], pid, row["created_at"][:10], row["courier_weight"], "货代")
        conn.execute("UPDATE courier_check SET resolved=1 WHERE id=?", (cid,))
        n += 1
    conn.commit()
    return n


def _f(v):
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None