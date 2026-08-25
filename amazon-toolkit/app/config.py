"""全局配置"""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
OUTPUT_DIR = DATA_DIR / "outputs"
DB_PATH = DATA_DIR / "app.db"

for d in (DATA_DIR, UPLOAD_DIR, OUTPUT_DIR):
    d.mkdir(parents=True, exist_ok=True)

# 飞书推送（留空则只生成本地文件不推送）
LARK_WEBHOOK = ""  # 自定义机器人 webhook 地址, 例: https://open.feishu.cn/open-apis/bot/v2/hook/xxxx
LARK_APP_ID = ""
LARK_APP_SECRET = ""
LARK_CHAT_ID = ""  # 群聊 chat_id（用 app 凭证推送时填）

# 默认跟卖配置（可在工作台"配置"页修改）
DEFAULT_CONFIG = {
    "inventory": "10",            # 默认库存
    "adjust_price": "0.50",       # 单次调整价格
    "max_purchase": "5",          # 最大采购量
    "weight_diff_threshold": "3", # 称重对账差异告警阈值 %
    "commission_rate": "0.15",    # 默认平台佣金率
    "target_margin": "0.30",      # 默认目标毛利率
    "exchange_rate": "7.20",      # 汇率(用于报告汇总)
}