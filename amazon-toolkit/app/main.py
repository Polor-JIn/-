import uuid
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app import config, db
from app.services import (io_utils, module1, module2, courier_check, module4,
                          profit as profit_svc, weight as weight_svc, freight as freight_svc,
                          sku_gen, dicts, lark_notify, images)

app = FastAPI(title="亚马逊跟卖工作台")


@app.on_event("startup")
def _startup():
    db.init_db()


def _save_upload(file: UploadFile) -> Path:
    name = Path(file.filename or "upload").name
    target = config.UPLOAD_DIR / f"{uuid.uuid4().hex[:8]}_{name}"
    target.write_bytes(file.file.read())
    return target


# ---------- 上传处理 ----------

@app.post("/api/upload/listing")
async def upload_listing(file: UploadFile = File(...)):
    raw = file.file.read()
    df = io_utils.read_table(raw, file.filename)
    mapping, unknown = io_utils.map_columns(df.columns)
    batch = module1.make_batch("L")
    summary, out_path, (new_colors, new_sizes) = module1.process_listing(df, mapping, batch)
    return {"batch": batch, "summary": summary, "output": Path(out_path).name,
            "unknown_columns": unknown, "mapping": mapping, "new_colors": sorted(new_colors),
            "new_sizes": sorted(new_sizes)}


@app.post("/api/upload/shipping")
async def upload_shipping(file: UploadFile = File(...)):
    src = _save_upload(file)
    raw = src.read_bytes()
    batch = module2.batch_for_file(file.filename, raw)
    if module2.already_processed(batch):
        return {"batch": batch, "already_processed": True}
    df = io_utils.read_table(raw, file.filename)
    mapping, unknown = io_utils.map_columns(df.columns)
    images_by_row = images.extract_embedded_images(str(src)) if src.name.lower().endswith(".xlsx") else {}
    result = module2.process_shipping(df, mapping, batch, xlsx_path=str(src),
                                      images_by_row=images_by_row)
    # 组装推送内容
    stats = result["stats"]
    text = (f"📦 发货批次 {batch}\n订单 {stats['orders']} 单 | 新增 {stats['added']} "
            f"| 跳过 {stats['skipped']} | 冲突 {stats['conflict']} | 待映射 {stats['unknown_sku']}\n"
            f"拼图文件: {Path(result['collage']).name if result['collage'] else '无'}")
    fb = lark_notify.send_text(text)
    img_ok = False
    if result["collage"]:
        img_ok = lark_notify.send_image_message(result["collage"], f"发货批次 {batch}")["ok"]
    return {"batch": batch, "stats": result["stats"], "unknown_skus": result["unknown_skus"],
            "collage": Path(result["collage"]).name if result["collage"] else None,
            "orders": result["orders"], "unknown_columns": unknown, "mapping": mapping,
            "lark_text_ok": fb["ok"], "lark_img_ok": img_ok}


@app.post("/api/upload/courier")
async def upload_courier(file: UploadFile = File(...)):
    raw = file.file.read()
    df = io_utils.read_table(raw, file.filename)
    mapping, unknown = io_utils.map_columns(df.columns)
    batch = f"CK{uuid.uuid4().hex[:8]}"
    res = courier_check.run_check(df, mapping, batch)
    return {"batch": batch, **res, "unknown_columns": unknown, "mapping": mapping}


@app.post("/api/purchase/match")
async def purchase_match(file: UploadFile = File(...)):
    raw = file.file.read()
    df = io_utils.read_table(raw, file.filename)
    mapping, unknown = io_utils.map_columns(df.columns)
    batch = module4.current_batch()
    res = module4.match_orders(df, mapping, batch)
    return {"batch": batch, "matched": res["matched"], "unmatched": res["unmatched"],
            "unknown_columns": unknown}


@app.post("/api/purchase/save")
async def purchase_save(body: dict):
    matched = body.get("matched") or []
    batch = body.get("batch") or module4.current_batch()
    n = module4.save_purchase_orders(matched, batch)
    out = str(config.OUTPUT_DIR / f"1688采购单_{batch}.xlsx")
    module4.write_purchase_xlsx(matched, out)
    return {"saved": n, "batch": batch, "output": Path(out).name}


# ---------- 商品库 ----------

@app.get("/api/products")
def products(q: str = ""):
    conn = db.get_conn()
    if q:
        rows = conn.execute(
            "SELECT * FROM product_master WHERE sku LIKE ? OR title LIKE ? OR asin LIKE ? ORDER BY product_id DESC",
            (f"%{q}%", f"%{q}%", f"%{q}%")).fetchall()
    else:
        rows = conn.execute("SELECT * FROM product_master ORDER BY product_id DESC LIMIT 500").fetchall()
    return [dict(r) for r in rows]


@app.post("/api/products")
def product_upsert(p: dict):
    conn = db.get_conn()
    pid = p.get("product_id")
    fields = ("sku asin title color size category purchase_price purchase_url purchase_spec "
              "p1688_id ref_weight target_margin status source").split()
    if pid:
        sets = ", ".join(f"{f}=?" for f in fields)
        conn.execute(f"UPDATE product_master SET {sets}, updated_at=? WHERE product_id=?",
                     tuple(p.get(f) for f in fields) + (db.now(), pid))
    else:
        conn.execute(
            f"INSERT INTO product_master({','.join(fields)}, created_at, updated_at) "
            f"VALUES({','.join('?' * len(fields))},?,?)",
            tuple(p.get(f) for f in fields) + (db.now(), db.now()))
    conn.commit()
    return {"ok": True}


# ---------- 乱码映射 ----------

@app.get("/api/aliases/pending")
def aliases_pending():
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT a.*, pm.sku AS bound_sku FROM sku_alias a LEFT JOIN product_master pm "
        "ON pm.product_id=a.product_id WHERE a.product_id IS NULL OR a.product_id='' ORDER BY a.created_at").fetchall()
    return [dict(r) for r in rows]


@app.post("/api/aliases/bind")
def alias_bind(p: dict):
    sku_gen.bind_alias(p["alias_sku"], p.get("product_id"), p.get("note", ""))
    return {"ok": True}


# ---------- 去重审核 ----------

@app.get("/api/dedup/review")
def dedup_review():
    conn = db.get_conn()
    rows = conn.execute("SELECT * FROM dedup_review ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


@app.post("/api/dedup/review/{rid}/apply")
def dedup_apply(rid: int, keep_new: bool = Form(True)):
    """人工审核冲突：keep_new=True 采用新值覆盖商品库；否则保留旧值(拒绝)"""
    conn = db.get_conn()
    row = conn.execute("SELECT * FROM dedup_review WHERE id=? AND status='pending'", (rid,)).fetchone()
    if not row:
        raise HTTPException(404, "记录不存在或已处理")
    if keep_new:
        conn.execute(f"UPDATE product_master SET {row['field']}=?, updated_at=? WHERE sku=?",
                     (row["new_value"], db.now(), row["sku"]))
        conn.execute("UPDATE dedup_review SET status='approved' WHERE id=?", (rid,))
    else:
        conn.execute("UPDATE dedup_review SET status='rejected' WHERE id=?", (rid,))
    conn.commit()
    return {"ok": True}


# ---------- 重量 ----------

@app.get("/api/weights")
def weights(sku: str = "", product_id: int = 0):
    rows = weight_svc.history(product_id=product_id or None, sku=sku)
    return rows


@app.post("/api/weights")
def weight_add(p: dict):
    v = weight_svc.add_weight(p.get("sku", ""), p.get("product_id"), p.get("batch_at", ""),
                              p.get("weight"), p.get("source", "手动"))
    return {"ok": v is not None, "weight": v}


# ---------- 售价/保底价快照 ----------

@app.post("/api/price/history")
def price_history_add(p: dict):
    conn = db.get_conn()
    conn.execute(
        "INSERT INTO price_history(product_id, sku, ref_date, price, floor_price, price_source, created_at) "
        "VALUES(?,?,?,?,?,?,?)",
        (p.get("product_id"), p.get("sku"), p.get("ref_date") or db.now()[:10],
         p.get("price"), p.get("floor_price"), p.get("price_source", "手动"), db.now()))
    conn.commit()
    return {"ok": True}


# ---------- 称重对账 ----------

@app.get("/api/courier/checks")
def checks():
    conn = db.get_conn()
    rows = conn.execute("SELECT * FROM courier_check ORDER BY created_at DESC LIMIT 300").fetchall()
    return [dict(r) for r in rows]


@app.post("/api/courier/apply")
async def apply_courier(body: dict):
    ids = body.get("ids") or []
    n = courier_check.apply_courier_weight(ids)
    return {"ok": True, "applied": n}


# ---------- 采购单 ----------

@app.get("/api/purchase/orders")
def purchase_orders():
    conn = db.get_conn()
    rows = conn.execute("SELECT * FROM purchase_orders ORDER BY created_at DESC LIMIT 300").fetchall()
    return [dict(r) for r in rows]


# ---------- 利润报告 ----------

@app.get("/api/report/profit")
def report_profit():
    return profit_svc.report()


@app.get("/api/report/profit/download")
def report_download():
    rows = profit_svc.report()
    out = str(config.OUTPUT_DIR / "利润分析报告.xlsx")
    profit_svc.write_report_xlsx(rows, out)
    return FileResponse(out, filename="利润分析报告.xlsx")


# ---------- 配置 / 字典 / 运费模板 ----------

@app.get("/api/config")
def get_configs():
    conn = db.get_conn()
    rows = conn.execute("SELECT * FROM config_kv ORDER BY key").fetchall()
    return {r["key"]: r["value"] for r in rows}


@app.post("/api/config")
def set_configs(d: dict):
    for k, v in d.items():
        db.set_config(k, str(v))
    return {"ok": True}


@app.get("/api/dicts")
def get_dicts(kind: str = "color"):
    return dicts.all(kind)


@app.post("/api/dicts")
def add_dicts(p: dict):
    dicts.add_alias(p["kind"], p["std"], p["alias"])
    return {"ok": True}


@app.get("/api/freight/templates")
def get_templates():
    return {"templates": freight_svc.templates(), "zones": freight_svc.zones(),
            "surcharges": freight_svc.surcharges()}


@app.post("/api/freight/templates")
def add_template(p: dict):
    conn = db.get_conn()
    conn.execute(
        "INSERT INTO freight_template(channel, first_weight, first_price, cont_weight, cont_price, currency) "
        "VALUES(?,?,?,?,?,?)",
        (p["channel"], p["first_weight"], p["first_price"], p["cont_weight"], p["cont_price"], p.get("currency", "USD")))
    conn.commit()
    return {"ok": True}


@app.post("/api/freight/surcharges")
def add_surcharge(p: dict):
    conn = db.get_conn()
    conn.execute(
        "INSERT INTO postcode_surcharge(channel, country, postcode_pattern, surcharge, note) VALUES(?,?,?,?,?)",
        (p.get("channel", ""), p.get("country", ""), p["postcode_pattern"], p["surcharge"], p.get("note", "")))
    conn.commit()
    return {"ok": True}


# ---------- 业务查询 ----------

@app.get("/api/shipping/orders")
def shipping_orders(batch: str = ""):
    conn = db.get_conn()
    if batch:
        rows = conn.execute("SELECT * FROM shipping_orders WHERE batch_id=? ORDER BY id DESC", (batch,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM shipping_orders ORDER BY id DESC LIMIT 300").fetchall()
    return [dict(r) for r in rows]


# ---------- 文件下载 ----------

@app.get("/files/{name}")
def file_download(name: str):
    p = config.OUTPUT_DIR / Path(name).name
    if not p.exists():
        raise HTTPException(404, "文件不存在")
    return FileResponse(p, filename=p.name)


app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")


@app.get("/", response_class=HTMLResponse)
def index():
    return (Path(__file__).parent / "static" / "index.html").read_text(encoding="utf-8")