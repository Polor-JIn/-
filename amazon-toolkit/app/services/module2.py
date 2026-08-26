"""模块 2：发货单清洗 → 乱码SKU还原 → 图片拼图 → 利润初算 → (由路由推送飞书)"""
import hashlib
from datetime import date
from app import config, db
from app.services import sku_gen, dedup, weight as weight_svc, freight as freight_svc, images, dicts


def batch_for_file(filename: str, file_bytes: bytes) -> str:
    """幂等批次号：日期 + 文件哈希"""
    return f"SH{date.today():%Y%m%d}_{hashlib.md5(file_bytes).hexdigest()[:8]}"


def already_processed(batch: str) -> bool:
    conn = db.get_conn()
    return conn.execute("SELECT 1 FROM batch_log WHERE batch_id=?", (batch,)).fetchone() is not None


def process_shipping(df, mapping, batch: str, xlsx_path=None, images_by_row=None):
    conn = db.get_conn()
    images_by_row = images_by_row or {}
    stats = {"added": 0, "skipped": 0, "conflict": 0, "unknown_sku": 0, "orders": 0}
    unknown_skus = []
    collage_items = []
    today = date.today().isoformat()

    for idx, row in df.iterrows():
        def g(f):
            col = mapping.get(f)
            v = row[col] if col else None
            return str(v).strip() if v is not None else ""

        sku_raw = g("sku")
        order_no, tracking = g("order_no"), g("tracking_no")
        channel, postcode = g("channel"), g("postcode")
        qty = _int(g("qty")) or 1
        weight_raw = _f(g("weight"))
        sales = _f(g("price"))

        if not sku_raw:
            stats["unknown_sku"] += 1
            continue

        product = sku_gen.resolve(sku_raw)
        status = "已关联"
        if product is None:
            # 未入库：尝试按规范 SKU 自动建档（颜色尺码过字典）
            parsed = sku_gen.parse_sku(sku_raw)
            if parsed:
                _p, color_raw, size_raw = parsed
                color_std, _cs = dicts.normalize(color_raw, "color")
                size_std, _ss = dicts.normalize(size_raw, "size")
                if not color_std.startswith("*") and not size_std.startswith("*"):
                    res = dedup.ingest(batch, sku_raw, {"color": color_std, "size": size_std}, source="发货")
                    product = res["product"]
                    stats[res["action"]] += 1
                    status = {"added": "自动建档", "skipped": "已存在", "conflict": "冲突"}.get(res["action"], "冲突")
            if product is None:
                # 乱码/无主：进入待人工映射（幂等登记）
                if sku_gen.find_alias(sku_raw) is None:
                    sku_gen.bind_alias(sku_raw, product_id=None, note="待人工识别")
                unknown_skus.append(sku_raw)
                stats["unknown_sku"] += 1
                status = "待映射"

        product_id = product["product_id"] if product else None
        if weight_raw and product_id:
            weight_svc.add_weight(sku_raw, product_id, today, weight_raw, "发货单")

        # 图片：嵌入图优先，外链兜底
        img = None
        row_images = images_by_row.get(idx + 2)  # df 索引 +2 = excel行号
        if row_images:
            img = row_images[0]
        elif g("image"):
            img = images.download_url(g("image"))

        # 采购成本快照 + 利润初算（当日日账口径）
        purchase = product["purchase_price"] if product else None
        profit_est, note = None, ""
        if product is None:
            note = "产品未入库"
        elif purchase is None:
            note = "缺采购价"
        elif sales is None:
            note = "缺销售额"
        else:
            fre, add, why = freight_svc.total_freight(channel, weight_raw, postcode, qty)
            if fre is None:
                fre = 0.0
            profit_est = round(sales - (purchase or 0) * qty - fre, 2)
            note = "未对账·日账口径"

        conn.execute(
            "INSERT INTO shipping_orders(batch_id, order_no, sku, color, size, tracking_no, channel, "
            "weight, postcode, qty, image_path, product_id, purchase_price, profit_est, profit_note, created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (batch, order_no, sku_raw, product["color"] if product else "", product["size"] if product else "",
             tracking, channel, weight_raw, postcode, qty, img, product_id, purchase,
             profit_est, note, db.now()))
        stats["orders"] += 1
        collage_items.append({"image": img, "sku": sku_raw, "tracking": tracking,
                              "qty": qty, "profit": profit_est, "note": note, "profit_est": profit_est,
                              "profit_note": note, "order_no": order_no, "channel": channel,
                              "weight": weight_raw, "status": status})

    conn.execute("INSERT OR IGNORE INTO batch_log(batch_type, filename, batch_id, summary, created_at) "
                 "VALUES('shipping', ?, ?, ?, ?)",
                 (batch, batch, f"orders={stats['orders']}, unknown={stats['unknown_sku']}", db.now()))
    conn.commit()

    collage_path = None
    if collage_items:
        collage_path = str(config.OUTPUT_DIR / "images" / f"拼图_{batch}.png")
        images.make_collage(collage_items, collage_path, title=f"发货批次 {batch}")
    stats["batch"] = batch
    return {"stats": stats, "unknown_skus": unknown_skus, "collage": collage_path,
            "orders": collage_items}


def _int(v):
    try:
        return int(float(str(v).strip()))
    except (TypeError, ValueError):
        return None


def _f(v):
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None