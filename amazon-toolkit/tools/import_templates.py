"""迁移用户上传的 '加拿大运费模板.xlsx' 到系统数据库
结构：重量区间计价表（渠道×[区间, 价格, 操作费]）+ 偏远邮编表（邮编前缀→偏远费）
用法: python tools/import_templates.py
"""
import re
import sys
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402

TEMPLATE = ROOT / "加拿大运费模板.xlsx"


def parse_weight_range(s: str):
    m = re.match(r"^\s*([\d.]+)\s*[-~]\s*([\d.]+)\s*KG\s*$", str(s or ""), re.I)
    if m:
        return float(m.group(1)), float(m.group(2))
    return None, None


def main():
    if not TEMPLATE.exists():
        print("未找到模板文件:", TEMPLATE)
        return
    df = pd.read_excel(TEMPLATE, header=None, dtype=str)
    conn = db.get_conn()
    conn.execute("DELETE FROM freight_zone")
    conn.execute("DELETE FROM postcode_surcharge")

    n_zone = n_pc = 0
    cur_channel, cur_code, cur_country, cur_op = None, None, None, None

    def to_float(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    for idx, (_, row) in enumerate(df.iterrows()):
        if idx == 0:  # 跳过表头行
            continue
        country = str(row[0]).strip().upper() if pd.notna(row[0]) else cur_country
        channel = str(row[1]).strip() if pd.notna(row[1]) else cur_channel
        code = str(row[2]).strip() if pd.notna(row[2]) else cur_code
        rng = str(row[3]).strip() if pd.notna(row[3]) else ""
        price = row[5] if pd.notna(row[5]) else None
        op = row[6] if pd.notna(row[6]) else None
        postcode = str(row[7]).strip() if pd.notna(row[7]) else ""
        zone_lvl = str(row[8]).strip() if pd.notna(row[8]) else ""
        fee = row[9] if pd.notna(row[9]) else None

        if channel:
            cur_channel, cur_code, cur_country = channel, code, country
            cur_op = to_float(op) if pd.notna(op) else None

        # 1) 重量区间行
        lo, hi = parse_weight_range(rng)
        price_f = to_float(price)
        if lo is not None and channel and price_f is not None:
            conn.execute(
                "INSERT INTO freight_zone(channel, code, country, weight_low, weight_high, price, op_fee) "
                "VALUES(?,?,?,?,?,?,?)",
                (cur_channel, cur_code, country, lo, hi, price_f,
                 cur_op if cur_op is not None else None))
            n_zone += 1
            # 区间行若带代表邮编，也补录邮编（模板把示例邮编写在同一行）
            if postcode and zone_lvl and to_float(fee) is not None:
                conn.execute(
                    "INSERT INTO postcode_surcharge(channel, country, postcode_pattern, surcharge, note) "
                    "VALUES('', ?, ?, ?, ?)", (country, postcode, to_float(fee), zone_lvl))
                n_pc += 1
            continue

        # 2) 偏远邮编行（channel 留空=全渠道适用）
        fee_f = to_float(fee)
        if postcode and zone_lvl and fee_f is not None:
            conn.execute(
                "INSERT INTO postcode_surcharge(channel, country, postcode_pattern, surcharge, note) "
                "VALUES('', ?, ?, ?, ?)",
                (country, postcode, fee_f, zone_lvl))
            n_pc += 1

    conn.commit()

    # 3) 聚合：同"国家+前3位前缀"且费用唯一 → 升级为前缀规则（覆盖该前缀全部邮编）
    rows = conn.execute(
        "SELECT country, substr(postcode_pattern,1,3) p, surcharge, COUNT(*) c "
        "FROM postcode_surcharge GROUP BY country, substr(postcode_pattern,1,3), surcharge").fetchall()
    prefix_fee = {}
    for r in rows:
        key = (r["country"], r["p"])
        prefix_fee.setdefault(key, set()).add(r["surcharge"])
    for (country, p), fees in prefix_fee.items():
        if len(fees) == 1:
            fee = fees.pop()
            conn.execute(
                "INSERT INTO postcode_surcharge(channel, country, postcode_pattern, surcharge, note) "
                "VALUES('', ?, ?, ?, '前缀聚合')", (country, p, fee))
    conn.commit()
    zones = conn.execute("SELECT COUNT(*) c FROM freight_zone").fetchone()["c"]
    pcs = conn.execute("SELECT COUNT(*) c FROM postcode_surcharge").fetchone()["c"]
    print(f"迁移完成: 重量区间 {n_zone} 条(库内 {zones} 条) | 偏远邮编 {n_pc} 条(库内 {pcs} 条)")
    print("渠道:")
    for r in conn.execute("SELECT DISTINCT channel, code FROM freight_zone").fetchall():
        print("  ", r["channel"], r["code"])
    print("偏远分区费用:", sorted(set(
        r["surcharge"] for r in conn.execute("SELECT DISTINCT surcharge FROM postcode_surcharge").fetchall())))


if __name__ == "__main__":
    main()