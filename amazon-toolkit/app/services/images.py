"""图片提取与拼图：Excel 嵌入图 / 外链下载 / 多单拼一张大图"""
import io
import re
import uuid
import requests
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from openpyxl import load_workbook

from app import config


def extract_embedded_images(xlsx_path: str):
    """提取 xlsx 中嵌入图片，按所在行分组。返回 {excel_row: [paths]}"""
    out = {}
    wb = load_workbook(xlsx_path, data_only=True)
    ws = wb.active
    try:
        images = getattr(ws, "_images", []) or []
    except AttributeError:
        return out
    for img in images:
        try:
            anchor = getattr(img, "anchor", None)
            row = getattr(getattr(anchor, "_from", None), "row", None)
            if row is None:
                continue
            data = img._data()
            p = config.OUTPUT_DIR / "images" / f"{uuid.uuid4().hex[:8]}.png"
            p.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(data, bytes):
                # 兼容二进制或缺 import 的场景
                _save_image(data, p)
            else:
                data.save(p if isinstance(p, str) else str(p))
            out.setdefault(row + 1, []).append(str(p))
        except Exception:
            continue
    return out


def _save_image(data: bytes, p: Path):
    with open(p, "wb") as f:
        f.write(data)


def download_url(url: str) -> str | None:
    """下载外链图片到本地，失败返回 None"""
    if not url or not str(url).strip():
        return None
    try:
        r = requests.get(str(url).strip(), timeout=15)
        if r.status_code != 200:
            return None
        ext = ".png"
        ct = r.headers.get("content-type", "")
        if "jpeg" in ct or "jpg" in ct:
            ext = ".jpg"
        p = config.OUTPUT_DIR / "images" / f"{uuid.uuid4().hex[:8]}{ext}"
        p.write_bytes(r.content)
        return str(p)
    except Exception:
        return None


def make_collage(items, out_path: str, title: str = ""):
    """多单拼一张大图。items: [{image, sku, tracking}] 按顺序带标签拼成网格。
    返回输出路径。"""
    thumb = 220
    label_h = 36
    cols = min(max(len(items), 1), 4)
    if items:
        rows = (len(items) + cols - 1) // cols
    else:
        rows = 1
    W, H = cols * thumb, rows * (thumb + label_h) + (40 if title else 0)
    canvas = Image.new("RGB", (W, H), "white")
    draw = ImageDraw.Draw(canvas)
    _font = _load_font(16)
    y0 = 40 if title else 0
    if title:
        draw.text((10, 10), title, fill="black", font=_load_font(22))
    for i, it in enumerate(items):
        c, r = i % cols, i // cols
        x, y = c * thumb, y0 + r * (thumb + label_h)
        img = _load_img(it.get("image"))
        if img:
            img = img.resize((thumb, thumb))
            canvas.paste(img, (x, y))
        else:
            draw.rectangle([x, y, x + thumb, y + thumb], outline="grey")
            draw.text((x + 10, y + thumb // 2), "(无图)", fill="grey", font=_font)
        label = f"{it.get('sku','')} {it.get('tracking','')}"
        draw.text((x + 6, y + thumb + 6), label[:24], fill="black", font=_font)
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(p)
    return str(p)


def _load_img(src):
    if not src:
        return None
    try:
        if str(src).startswith(("http://", "https://")):
            r = requests.get(src, timeout=15)
            if r.status_code == 200:
                return Image.open(io.BytesIO(r.content))
            return None
        return Image.open(src)
    except Exception:
        return None


def _load_font(size):
    for fp in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",):
        try:
            return ImageFont.truetype(fp, size)
        except Exception:
            pass
    try:
        from PIL import ImageFont as _F
        return _F.load_default()
    except Exception:
        return None