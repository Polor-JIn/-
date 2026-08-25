"""运费模板 + 偏远邮编附加费计算"""
import math
from app import db


def freight_cost(channel: str, weight_kg, conn=None):
    """按渠道运费模板计算运费。模板按首重价 + 续重计价。无模板返回 None"""
    conn = conn or db.get_conn()
    w = _f(weight_kg)
    if w is None:
        return None
    row = conn.execute(
        "SELECT * FROM freight_template WHERE channel=? ORDER BY id DESC LIMIT 1",
        (str(channel).strip(),)).fetchone()
    if not row:
        return None
    if w <= (row["first_weight"] or 0):
        return row["first_price"]
    extra = (w - row["first_weight"]) / max(row["cont_weight"], 0.001)
    return round(row["first_price"] + math.ceil(extra) * row["cont_price"], 2)


def surcharge(channel: str, postcode: str, conn=None):
    """偏远邮编附加费：按邮编前缀匹配（最长的命中优先）。"""
    conn = conn or db.get_conn()
    pc = str(postcode or "").strip().upper()
    if not pc:
        return 0.0
    rows = conn.execute(
        "SELECT * FROM postcode_surcharge WHERE channel=? OR channel=''", (str(channel).strip(),)).fetchall()
    best = (0.0, 0)
    for r in rows:
        pat = str(r["postcode_pattern"] or "").strip().upper()
        if pat and pc.startswith(pat) and len(pat) > best[1]:
            best = (r["surcharge"] or 0.0, len(pat))
    return best[0]


def total_freight(channel: str, weight_kg, postcode: str, conn=None):
    freight = freight_cost(channel, weight_kg, conn)
    add = surcharge(channel, postcode, conn)
    if freight is None:
        return None, add, "无运费模板"
    return freight + add, add, ""


def templates(conn=None):
    conn = conn or db.get_conn()
    return [dict(r) for r in conn.execute("SELECT * FROM freight_template ORDER BY channel").fetchall()]


def surcharges(conn=None):
    conn = conn or db.get_conn()
    return [dict(r) for r in conn.execute("SELECT * FROM postcode_surcharge ORDER BY channel").fetchall()]


def _f(v):
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None