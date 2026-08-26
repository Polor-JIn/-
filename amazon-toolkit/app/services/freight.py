"""运费计算：区间计价(模板) + 首重续重(通用) + 偏远邮编附加费"""
import math
from app import db


def _channel_match(rows, channel, conn):
    """匹配渠道：先精确(名称/代码)，再包含匹配（如发货单写'商业派送'能命中'加拿大商业派送（普货）'）。
    未提供渠道时取第一条渠道（默认计价渠道）。"""
    ch = str(channel or "").strip()
    if not ch:
        return rows[0] if rows else None
    exact = [r for r in rows if (r["channel"] or "").strip() == ch or (r["code"] or "").strip() == ch]
    if exact:
        return exact[-1]
    for r in rows:
        if ch in (r["channel"] or "") or (r["channel"] or "") in ch:
            return r
    return None


def freight_zone_cost(channel: str, weight_kg, qty=1, conn=None, country="CA"):
    """区间一口价：运费 = 区间价格 + 操作费×件数。找到匹配区间返回 (price+op, op, channel)；找不到返回 (None,None,'')"""
    conn = conn or db.get_conn()
    w = _f(weight_kg)
    if w is None:
        return None, None, ""
    rows = conn.execute(
        "SELECT * FROM freight_zone WHERE country=? ORDER BY weight_low", (country or "CA",)).fetchall()
    if not rows:
        rows = conn.execute("SELECT * FROM freight_zone ORDER BY weight_low").fetchall()
    r = _channel_match(rows, channel, conn)
    if not r:
        return None, None, ""
    for z in conn.execute(
            "SELECT * FROM freight_zone WHERE channel=? ORDER BY weight_low", (r["channel"],)).fetchall():
        hi = z["weight_high"] if z["weight_high"] is not None else math.inf
        if z["weight_low"] <= w <= hi:
            op = (z["op_fee"] or 0) * max(int(qty or 1), 1)
            return (z["price"] or 0) + op, op, z["channel"]
    return None, None, r["channel"]


def freight_cost(channel: str, weight_kg, qty=1, conn=None):
    """运费（不含偏远费）：优先区间计价表，其次首重续重模板"""
    z, opc, cname = freight_zone_cost(channel, weight_kg, qty, conn)
    if z is not None:
        return z
    conn = conn or db.get_conn()
    w = _f(weight_kg)
    if w is None:
        return None
    row = conn.execute(
        "SELECT * FROM freight_template ORDER BY id DESC LIMIT 1").fetchone()
    if not row:
        return None
    # 首重续重模板按渠道匹配
    row = None
    for r in conn.execute("SELECT * FROM freight_template ORDER BY id"):
        if (r["channel"] or "").strip() == str(channel or "").strip():
            row = r
            break
    if not row:
        return None
    if w <= (row["first_weight"] or 0):
        return row["first_price"]
    extra = (w - row["first_weight"]) / max(row["cont_weight"], 0.001)
    return round(row["first_price"] + math.ceil(extra) * row["cont_price"], 2)


def surcharge(channel: str, postcode: str, qty=1, conn=None):
    """偏远邮编附加费：先精确匹配完整邮编，再按前缀匹配（最长命中优先）。channel 传空串=全渠道。"""
    conn = conn or db.get_conn()
    pc = str(postcode or "").strip().upper()
    if not pc:
        return 0.0
    rows = conn.execute(
        "SELECT * FROM postcode_surcharge WHERE channel='' OR channel=?", (str(channel or "").strip(),)).fetchall()
    # 1) 完整邮编精确
    for r in rows:
        if str(r["postcode_pattern"] or "").strip().upper() == pc:
            return r["surcharge"] or 0.0
    # 2) 前缀匹配（最长优先）
    best = (0.0, 0)
    for r in rows:
        pat = str(r["postcode_pattern"] or "").strip().upper()
        if pat and pc.startswith(pat) and len(pat) > best[1]:
            best = (r["surcharge"] or 0.0, len(pat))
    return best[0]


def total_freight(channel: str, weight_kg, postcode: str, qty=1, conn=None):
    """总运费 = 基础运费 + 偏远附加费。返回 (total, surcharge, note)"""
    freight = freight_cost(channel, weight_kg, qty, conn)
    add = surcharge(channel, postcode, qty, conn)
    if freight is None:
        return None, add, "无运费计费模板"
    return freight + add, add, ""


def templates(conn=None):
    conn = conn or db.get_conn()
    return [dict(r) for r in conn.execute("SELECT * FROM freight_template ORDER BY channel").fetchall()]


def zones(conn=None):
    conn = conn or db.get_conn()
    return [dict(r) for r in conn.execute("SELECT * FROM freight_zone ORDER BY channel, weight_low").fetchall()]


def surcharges(conn=None):
    conn = conn or db.get_conn()
    return [dict(r) for r in conn.execute("SELECT * FROM postcode_surcharge ORDER BY country, postcode_pattern").fetchall()]


def _f(v):
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None