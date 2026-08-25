"""颜色/尺码受控字典：归一化 + 新值进入待确认"""
from app import db


def normalize(value, kind: str):
    """kind: color | size。返回 (标注值, 状态)
    状态: matched(命中标准值或别名) | new(未收录保留原值) | missing(为空)"""
    v = str(value).strip()
    if not v:
        return "", "missing"
    conn = db.get_conn()
    table = conn.execute(f"SELECT std, alias FROM dict_{kind}").fetchall()
    key = v.lower()
    # 1) 直接命中标准值（大小写不敏感）
    for row in table:
        if row["std"].lower() == key:
            return row["std"], "matched"
    # 2) 精确命中别名
    for row in table:
        if row["alias"] == key:
            return row["std"], "matched"
    # 3) 包含匹配：长别名出现在值中（如 "深黑色" 含 "黑色"）
    for row in sorted(table, key=lambda r: -len(r["alias"])):
        if len(row["alias"]) >= 2 and row["alias"] in key:
            return row["std"], "matched"
    return v, "new"  # 未收录，保留原值并标记，进入"待确认"


def add_alias(kind: str, std: str, alias: str):
    conn = db.get_conn()
    conn.execute(f"INSERT OR IGNORE INTO dict_{kind}(std, alias) VALUES(?, ?)", (std, alias.strip().lower()))
    conn.commit()


def all(kind: str):
    conn = db.get_conn()
    rows = conn.execute(f"SELECT std, alias FROM dict_{kind} ORDER BY std, alias").fetchall()
    out = {}
    for r in rows:
        out.setdefault(r["std"], []).append(r["alias"])
    return out