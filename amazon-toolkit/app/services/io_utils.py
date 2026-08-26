"""上传解析 + 列名自动识别"""
import chardet
import pandas as pd


# 标准字段 -> 常见列名别名（匹配时大小写、全半角、空格均归一化）
ALIASES = {
    "sku":        ["sku", "子sku", "商品编码", "产品编码", "货号", "编码", "sku编码", "卖家sku"],
    "asin":       ["asin", "亚马逊asin", "amazonasin"],
    "title":      ["title", "标题", "产品名称", "名称", "商品名称", "品名"],
    "color":      ["color", "颜色", "颜色名称", "颜色属性"],
    "size":       ["size", "尺码", "尺寸", "尺码属性"],
    "price":      ["price", "价格", "售价", "零售价", "listing价格"],
    "order_no":   ["order_no", "订单号", "订单编号", "订单"],
    "tracking_no":["tracking_no", "跟踪号", "追踪号", "物流单号", "运单号", "tracking", "track"],
    "weight":     ["weight", "重量", "实重", "计费重", "重量kg"],
    "channel":    ["channel", "渠道", "发货渠道", "物流渠道", "线路", "运输渠道"],
    "postcode":   ["postcode", "邮编", "邮政编码", "zip", "zipcode"],
    "qty":        ["qty", "数量", "件数", "购买数量", "quantity"],
    "image":      ["image", "图片", "图片链接", "图片地址", "img", "产品图片"],
    "p1688_id":   ["p1688_id", "1688id", "1688_id", "1688编号", "id"],
    "url":        ["url", "链接", "1688链接", "采购链接", "商品链接", "产品链接"],
    "spec":       ["spec", "规格", "规格信息", "1688规格", "采购规格"],
    "address":    ["address", "地址", "采购地址", "收货地址", "供应商地址"],
    "ref_no":     ["ref_no", "单号", "跟踪号", "物流单号", "运单号"],
    "c_weight":   ["courier_weight", "货代重量", "称重", "实际称重", "记比重"],
}


def _norm(s: str) -> str:
    """归一化列名字符串用于匹配"""
    if not isinstance(s, str):
        s = str(s)
    s = s.replace(" ", "").replace("　", "").replace("_", "").replace("-", "").lower()
    return s


def _norm_aliases(aliases):
    return [_norm(a) for a in aliases]


_ALIAS_MAP = {field: _norm_aliases(item) for field, item in ALIASES.items()}


def _match_field(col: str, exclude=(), exact_only=False):
    c = _norm(col)
    candidates = []
    for field, nms in _ALIAS_MAP.items():
        if field in exclude:
            continue
        for nm in nms:
            if nm in c:
                candidates.append((field, len(nm)))
    if not candidates:
        return None
    candidates.sort(key=lambda x: -x[1])  # 别名越长越精确
    return candidates[0][0]


def map_columns(columns, exclude_fields=()):
    """返回 {标准字段: 原始列名} 与未识别列；每个原始列只映射到一个标准字段"""
    mapping, taken = {}, set()
    for col in columns:  # 第一轮：只认精确别名
        f = _match_field(col, exclude=exclude_fields)
        if f and f not in mapping and _norm(col) in set(_ALIAS_MAP[f]):
            mapping[f] = col
            taken.add(col)
    for col in columns:  # 第二轮：包含匹配，字段仍未占用才分配
        if col in taken:
            continue
        f = _match_field(col, exclude=exclude_fields)
        if f and f not in mapping:
            mapping[f] = col
            taken.add(col)
    unknown = [c for c in columns if c not in taken]
    return mapping, unknown


def read_table(file_bytes, filename):
    """读取 xlsx/csv -> DataFrame，自动处理编码"""
    name = filename.lower()
    if name.endswith(".csv"):
        raw = file_bytes
        enc = "utf-8"
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError:
            enc = chardet.detect(raw)["encoding"] or "gbk"
        import io
        df = pd.read_csv(io.BytesIO(raw), encoding=enc, dtype=str)
    else:
        import io
        df = pd.read_excel(io.BytesIO(file_bytes), engine="openpyxl", dtype=str)
    df.columns = [str(c).strip() for c in df.columns]
    df = df.dropna(how="all")
    df = df.fillna("")   # 空单元格统一为空串，避免读成 'nan' 字符串
    return df


def build_mapping_from_aliases():
    """返回标准字段到别名的正反映射，便于前端展示"""
    return {f: a for f, a in ALIASES.items()}