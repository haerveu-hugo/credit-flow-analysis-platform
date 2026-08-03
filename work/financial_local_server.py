from __future__ import annotations

import cgi
import html
import json
import math
import re
import sys
import threading
import traceback
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
UPLOADS = ROOT / "tmp" / "financial_uploads"
sys.path.insert(0, str(ROOT / "work"))
import flow_local_server as flow

JOBS: dict[str, dict] = {}
LOCK = threading.Lock()
SUPPORTED = {".xlsx", ".xls", ".csv", ".pdf", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}

ALIASES = {
    "cash": r"^(货币资金|现金及现金等价物|现金)$",
    "ar": r"^(应收账款|应收帐款)$",
    "notes_ar": r"^应收票据",
    "prepayments": r"^预付账款",
    "inventory": r"^存货$",
    "other_ar": r"^其他应收款$",
    "current_assets": r"^流动资产合计$",
    "fixed_assets": r"^(固定资产|固定资产净额|固定资产账面价值)$",
    "total_assets": r"^(资产总计|资产合计)$",
    "short_debt": r"^短期借款$",
    "ap": r"^(应付账款|应付帐款)$",
    "notes_ap": r"^应付票据",
    "advance_receipts": r"^(预收账款|合同负债)$",
    "tax_payable": r"^应交税费$",
    "other_ap": r"^其他应付款$",
    "current_liabilities": r"^流动负债合计$",
    "long_debt": r"^长期借款$",
    "total_liabilities": r"^负债合计$",
    "equity": r"^(所有者权益|股东权益)(（或股东权益）)?合计$|^所有者权益（或股东权益）合计$",
    "liabilities_equity": r"^负债(和|及)所有者权益(（或股东权益）)?总计$",
    "revenue": r"^(一、)?营业收入$|^主营业务收入$",
    "cost": r"^(减：)?营业成本$|^主营业务成本$",
    "tax_surcharge": r"^税金及附加$|^营业税金及附加$",
    "sales_expense": r"^销售费用$",
    "admin_expense": r"^管理费用$",
    "finance_expense": r"^财务费用$",
    "operating_profit": r"^营业利润(?:（.*）)?$",
    "total_profit": r"^利润总额(?:（.*）)?$",
    "net_profit": r"^净利润(?:（.*）)?$",
    "cfo": r"^经营活动产生的现金流量净额$",
    "cfi": r"^投资活动产生的现金流量净额$",
    "cff": r"^筹资活动产生的现金流量净额$",
    "cash_change": r"^现金及现金等价物净增加额$",
    "cash_end": r"^期末现金及现金等价物余额$",
}

LABELS = {
    "cash": "货币资金", "ar": "应收账款", "notes_ar": "应收票据", "prepayments": "预付账款",
    "inventory": "存货", "other_ar": "其他应收款", "current_assets": "流动资产合计", "fixed_assets": "固定资产",
    "total_assets": "资产总计", "short_debt": "短期借款", "ap": "应付账款", "notes_ap": "应付票据",
    "advance_receipts": "预收账款/合同负债", "tax_payable": "应交税费", "other_ap": "其他应付款",
    "current_liabilities": "流动负债合计", "long_debt": "长期借款", "total_liabilities": "负债合计",
    "equity": "所有者权益合计", "liabilities_equity": "负债和所有者权益总计", "revenue": "营业收入",
    "cost": "营业成本", "tax_surcharge": "税金及附加", "sales_expense": "销售费用", "admin_expense": "管理费用",
    "finance_expense": "财务费用", "operating_profit": "营业利润", "total_profit": "利润总额", "net_profit": "净利润",
    "cfo": "经营活动现金流量净额", "cfi": "投资活动现金流量净额", "cff": "筹资活动现金流量净额",
    "cash_change": "现金净增加额", "cash_end": "期末现金余额",
}

STATEMENT_KEYS = {
    "balance": set(list(ALIASES)[:20]),
    "profit": {"revenue", "cost", "tax_surcharge", "sales_expense", "admin_expense", "finance_expense", "operating_profit", "total_profit", "net_profit"},
    "cashflow": {"cfo", "cfi", "cff", "cash_change", "cash_end"},
}

INDUSTRIES = [
    {"key": "manufacturing", "name": "生产制造/加工", "re": r"制造|生产|加工|机械|五金|陶瓷|铝|钢|塑料|设备|材料", "current": 1.2, "quick": .7, "debt": .70, "gross": (.12, .40), "net": .03, "ar": 120, "inv": 150, "note": "重点看原料、存货、产能利用率、应收账期和经营现金回款。"},
    {"key": "trade", "name": "批发贸易/经销", "re": r"贸易|批发|经销|商贸|供应链|进出口|销售", "current": 1.1, "quick": .65, "debt": .75, "gross": (.05, .25), "net": .015, "ar": 90, "inv": 100, "note": "薄利快周转较常见，重点看上下游稳定性、库存周转和应收回款。"},
    {"key": "construction", "name": "建筑/工程/装修", "re": r"建筑|工程|施工|装修|装饰|安装|市政|园林", "current": 1.05, "quick": .55, "debt": .78, "gross": (.08, .35), "net": .025, "ar": 210, "inv": 240, "note": "项目制结算会拉长应收和合同资产周期，应结合合同、进度和回款节点。"},
    {"key": "retail", "name": "餐饮/零售/电商", "re": r"餐饮|食品|零售|超市|电商|电子商务|网络销售|直播", "current": 1.0, "quick": .55, "debt": .72, "gross": (.15, .60), "net": .025, "ar": 45, "inv": 90, "note": "现金或平台结算占比较高，应收通常较低，重点看毛利、存货损耗和门店现金流。"},
    {"key": "agriculture", "name": "农业/养殖/水产", "re": r"农业|种植|养殖|水产|渔业|农产品|饲料|生鲜", "current": 1.05, "quick": .45, "debt": .72, "gross": (.10, .45), "net": .025, "ar": 120, "inv": 240, "note": "季节性和生物资产周期明显，应结合生产周期、成活率、价格波动和灾害风险。"},
    {"key": "service", "name": "服务/技术/租赁", "re": r"服务|咨询|技术|软件|信息|物流|运输|租赁|维修|设计|广告|培训", "current": 1.2, "quick": .9, "debt": .65, "gross": (.20, .75), "net": .05, "ar": 100, "inv": 30, "note": "轻资产企业应关注人员成本、合同续约、应收质量及利润向现金的转化。"},
    {"key": "general", "name": "综合经营/通用模型", "re": r".*", "current": 1.1, "quick": .7, "debt": .70, "gross": (.10, .50), "net": .03, "ar": 120, "inv": 150, "note": "当前使用通用模型；补充实际经营描述可提高行业适配度。"},
]


def set_job(job_id: str, **updates) -> None:
    with LOCK:
        JOBS.setdefault(job_id, {}).update(updates)


def get_job(job_id: str) -> dict:
    with LOCK:
        return dict(JOBS.get(job_id) or {})


def clean_text(value) -> str:
    return re.sub(r"\s+", "", str(value or "")).replace("：", "").replace(":", "").strip()


def number(value):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "").replace("，", "").replace("￥", "").replace("¥", "")
    if not text or text in {"-", "--", "—", "/"}:
        return 0.0
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("() ")
    if not re.fullmatch(r"[-+]?\d+(?:\.\d+)?", text):
        return None
    value = float(text)
    return -value if negative else value


def canonical(label: str) -> str | None:
    text = clean_text(label).replace("其中", "").replace("加", "").replace("减", "减：")
    text = re.sub(r"^[一二三四五六七八九十]+[、.]", "", text)
    for key, pattern in ALIASES.items():
        if re.search(pattern, text):
            return key
    return None


def label_tokens(key: str) -> list[str]:
    special = {
        "fixed_assets": ["固定资产账面价值", "固定资产净额", "固定资产"],
        "total_assets": ["资产总计", "资产合计"],
        "advance_receipts": ["预收账款", "合同负债"],
        "equity": ["所有者权益", "股东权益"],
        "liabilities_equity": ["负债和所有者权益", "负债及所有者权益"],
        "revenue": ["营业收入", "主营业务收入"],
        "cost": ["营业成本", "主营业务成本"],
        "tax_surcharge": ["税金及附加", "营业税金及附加"],
    }
    return special.get(key, [LABELS[key].split("/")[0]])


def statement_for(key: str) -> str:
    return next((name for name, keys in STATEMENT_KEYS.items() if key in keys), "other")


def infer_industry(scope: str, description: str) -> dict:
    for source in (description, scope):
        for model in INDUSTRIES[:-1]:
            if re.search(model["re"], source or ""):
                return model
    return INDUSTRIES[-1]


def unit_scale(text: str) -> float:
    if re.search(r"单位[：:]?万元|金额单位[：:]?万元", text):
        return 10000.0
    if re.search(r"单位[：:]?千元|金额单位[：:]?千元", text):
        return 1000.0
    return 1.0


def period_info(source: str, content: str = "", sheet: str = "") -> dict:
    text = f"{source} {sheet} {content[:1200]}"
    matches = re.findall(r"(20\d{2})\s*[年./-]\s*(1[0-2]|0?[1-9])\s*月?", text)
    year = month = 0
    if matches:
        year, month = map(int, matches[-1])
    else:
        years = re.findall(r"(20\d{2})\s*年?", text)
        if years:
            year = int(years[-1])
            month = 12 if re.search(r"年度|年报|12月", text) else 0
    annual = bool(year and (month == 12 or re.search(rf"{year}\s*年?\s*年度|{year}年度|年报", text)))
    if annual:
        month = 12
    key = year * 100 + month if year else 0
    label = f"{year}年度" if annual else (f"{year}-{month:02d}累计" if year and month else "期间未识别")
    return {"year": year, "month": month, "annual": annual, "key": key, "label": label}


def rows_from_frame(df: pd.DataFrame, source: str, sheet: str) -> list[dict]:
    data = df.where(pd.notna(df), None).values.tolist()
    scale = unit_scale(" ".join(str(v or "") for row in data[:20] for v in row))
    records = []
    for row_idx, row in enumerate(data):
        label_indices = [i for i, v in enumerate(row) if canonical(str(v or ""))]
        for position, label_idx in enumerate(label_indices):
            key = canonical(str(row[label_idx]))
            end = label_indices[position + 1] if position + 1 < len(label_indices) else len(row)
            values = []
            for col in range(label_idx + 1, end):
                val = number(row[col])
                if val is not None:
                    values.append((col, val))
            if len(values) > 1 and values[0][1].is_integer() and 0 < values[0][1] < 500 and values[0][0] == label_idx + 1:
                values = values[1:]
            if not values:
                continue
            header = {col: "".join(str(data[r][col] or "") for r in range(0, row_idx)) for col, _ in values}
            cur = next((v for c, v in values if re.search(r"累计", header[c]) and not re.search(r"上期|上年|年初|期初", header[c])), None)
            if cur is None:
                cur = next((v for c, v in values if re.search(r"期末|本期|本年|本月|本季", header[c]) and not re.search(r"上期|上年|年初|期初", header[c])), None)
            prior = next((v for c, v in values if re.search(r"期初|年初|上期|上年", header[c])), None)
            if cur is None:
                cur = values[0][1]
            has_period_headers = any(re.search(r"期末|期初|年初|本期|本年|本月|本季|累计|上期|上年", header[c]) for c, _ in values)
            if prior is None and len(values) > 1 and not has_period_headers:
                prior = values[1][1]
            records.append({"key": key, "label": LABELS[key], "current": cur * scale, "prior": None if prior is None else prior * scale, "source": source, "sheet": sheet, "row": row_idx + 1})
    return records


def rows_from_text(text: str, source: str) -> list[dict]:
    scale = unit_scale(text)
    records = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        compact = re.sub(r"\s+", "", line)
        key = next((k for k, p in ALIASES.items() if re.search(p, re.sub(r"[-+]?\d[\d,，.()]*", "", compact).strip("：:"))), None)
        if not key:
            key = next((k for k, p in ALIASES.items() if re.search(p.strip("^$"), compact)), None)
        if not key:
            continue
        numeric_text = line
        token_hits = [(line.find(token), token) for token in label_tokens(key) if line.find(token) >= 0]
        if token_hits:
            position, token = min(token_hits, key=lambda x: x[0])
            numeric_text = line[position + len(token):]
        nums = [number(x) for x in re.findall(r"\(?[-+]?\d[\d,，]*(?:\.\d+)?\)?", numeric_text)]
        nums = [x for x in nums if x is not None]
        if len(nums) > 1 and float(nums[0]).is_integer() and 0 < nums[0] < 500:
            nums = nums[1:]
        if nums:
            records.append({"key": key, "label": LABELS[key], "current": nums[0] * scale, "prior": nums[1] * scale if len(nums) > 1 else None, "source": source, "sheet": "PDF/OCR", "row": line_no})
    return records


def analyze_file(path: Path, passwords: list[str]) -> dict:
    suffix = path.suffix.lower()
    groups = []
    if suffix in {".xlsx", ".xls", ".csv"}:
        if suffix == ".csv":
            sheets = {"CSV": pd.read_csv(path, header=None, dtype=str, encoding_errors="ignore")}
        else:
            sheets = pd.read_excel(path, sheet_name=None, header=None, dtype=object)
        for name, df in sheets.items():
            rows = rows_from_frame(df, path.name, str(name))
            if rows:
                preview = " ".join(str(v or "") for row in df.head(15).where(pd.notna(df), None).values.tolist() for v in row)
                groups.append({"source": path.name, "sheet": str(name), "period": period_info(path.name, preview, str(name)), "rows": rows})
    else:
        if suffix == ".pdf":
            text, _ = flow.extract_pdf_text(path, passwords=passwords)
            if len(text) < 300 or sum(1 for k in ALIASES if k in {r.get('key') for r in rows_from_text(text, path.name)}) < 4:
                text = flow.ocr_file(path, path.parent / f"{path.stem}-财务OCR", passwords=passwords)
        else:
            text = flow.ocr_file(path, path.parent / f"{path.stem}-财务OCR", passwords=passwords)
        rows = rows_from_text(text, path.name)
        if rows:
            groups.append({"source": path.name, "sheet": "PDF/OCR", "period": period_info(path.name, text), "rows": rows})
    return {"filename": path.name, "groups": groups}


def select_statements(file_results: list[dict]) -> tuple[dict, list[dict]]:
    selected, candidates = {}, []
    for file in file_results:
        for group in file["groups"]:
            for statement, keys in STATEMENT_KEYS.items():
                rows = [r for r in group["rows"] if r["key"] in keys]
                if rows:
                    item = {"statement": statement, "source": group["source"], "sheet": group["sheet"], "period": group.get("period") or period_info(group["source"], sheet=group["sheet"]), "rows": rows, "score": len({r['key'] for r in rows})}
                    candidates.append(item)
                    rank = (item["period"]["key"], item["score"])
                    old_rank = (selected[statement]["period"]["key"], selected[statement]["score"]) if statement in selected else (-1, -1)
                    if rank >= old_rank:
                        selected[statement] = item
    metrics = {}
    for statement, item in selected.items():
        for row in item["rows"]:
            metrics.setdefault(row["key"], row)
    if "equity" not in metrics and amount(metrics, "total_assets") is not None and amount(metrics, "total_liabilities") is not None:
        base = metrics["total_assets"]
        metrics["equity"] = {**base, "key": "equity", "label": LABELS["equity"], "current": amount(metrics, "total_assets") - amount(metrics, "total_liabilities"), "prior": None, "derived": True}
    return metrics, candidates


def safe_div(a, b):
    return a / b if b not in (None, 0) and a is not None else None


def amount(metrics: dict, key: str, period="current"):
    row = metrics.get(key) or {}
    return row.get(period)


def build_period_series(candidates: list[dict]) -> list[dict]:
    grouped: dict[tuple[int, str], dict] = {}
    for item in candidates:
        period = item["period"]
        slot = grouped.setdefault((period["key"], item["source"]), {"period": period, "source": item["source"], "rows": {}})
        for row in item["rows"]:
            slot["rows"].setdefault(row["key"], row)
    best_by_period: dict[int, dict] = {}
    for (key, _source), item in grouped.items():
        if key and (key not in best_by_period or len(item["rows"]) > len(best_by_period[key]["rows"])):
            best_by_period[key] = item
    series = []
    for key in sorted(best_by_period):
        item = best_by_period[key]
        rows = item["rows"]
        get = lambda name: (rows.get(name) or {}).get("current")
        assets, liabilities, equity = get("total_assets"), get("total_liabilities"), get("equity")
        if equity is None and assets is not None and liabilities is not None:
            equity = assets - liabilities
        revenue, cost, profit = get("revenue"), get("cost"), get("net_profit")
        ca, cl, inv = get("current_assets"), get("current_liabilities"), get("inventory") or 0
        series.append({
            "period": item["period"], "source": item["source"], "recognized": len(rows),
            "revenue": revenue, "cost": cost, "profit": profit, "assets": assets,
            "liabilities": liabilities, "equity": equity, "cfo": get("cfo"),
            "assets_prior": (rows.get("total_assets") or {}).get("prior"),
            "liabilities_prior": (rows.get("total_liabilities") or {}).get("prior"),
            "gross_margin": safe_div((revenue - cost) if revenue is not None and cost is not None else None, revenue),
            "net_margin": safe_div(profit, revenue), "debt_ratio": safe_div(liabilities, assets),
            "current_ratio": safe_div(ca, cl), "quick_ratio": safe_div((ca - inv) if ca is not None else None, cl),
        })
    return series


def analyze_metrics(metrics: dict, model: dict, context: str, period_type: str, latest_period: dict | None = None) -> tuple[dict, list[dict], list[dict]]:
    a = lambda k, p="current": amount(metrics, k, p)
    assets, liabilities, equity = a("total_assets"), a("total_liabilities"), a("equity")
    ca, cl, inventory = a("current_assets"), a("current_liabilities"), a("inventory") or 0
    revenue, cost, profit, cfo = a("revenue"), a("cost"), a("net_profit"), a("cfo")
    latest_period = latest_period or {}
    auto_factor = 1 if latest_period.get("annual") else 12 / max(1, int(latest_period.get("month") or 12))
    annual_factor = {"annual": 1, "cumulative": auto_factor, "monthly": 12, "auto": auto_factor}.get(period_type, auto_factor)
    annual_revenue = revenue * annual_factor if revenue is not None else None
    annual_cost = cost * annual_factor if cost is not None else None
    avg_ar = ((a("ar") or 0) + (a("ar", "prior") if a("ar", "prior") is not None else (a("ar") or 0))) / 2
    avg_inv = ((a("inventory") or 0) + (a("inventory", "prior") if a("inventory", "prior") is not None else (a("inventory") or 0))) / 2
    gross = revenue - cost if revenue is not None and cost is not None else None
    ratios = {
        "current_ratio": safe_div(ca, cl), "quick_ratio": safe_div((ca - inventory) if ca is not None else None, cl),
        "debt_ratio": safe_div(liabilities, assets), "gross_margin": safe_div(gross, revenue), "net_margin": safe_div(profit, revenue),
        "roa": safe_div(profit, assets), "roe": safe_div(profit, equity), "ar_days": safe_div(avg_ar * 365, annual_revenue),
        "inventory_days": safe_div(avg_inv * 365, annual_cost), "cfo_profit": safe_div(cfo, profit),
        "revenue_growth": None, "profit_growth": None,
        "working_capital": ca - cl if ca is not None and cl is not None else None,
    }
    checks = []
    def check(name, actual, expected, delta, passed, note): checks.append({"name": name, "actual": actual, "expected": expected, "delta": delta, "status": "通过" if passed else "异常", "note": note})
    if assets is not None and liabilities is not None and equity is not None and not (metrics.get("equity") or {}).get("derived"):
        delta = assets - liabilities - equity; tol = max(100, abs(assets) * .005)
        check("资产负债表平衡", assets, liabilities + equity, delta, abs(delta) <= tol, "资产应等于负债加所有者权益。")
    elif assets is not None and liabilities is not None and equity is not None:
        checks.append({"name": "资产负债表平衡", "actual": assets, "expected": liabilities + equity, "delta": 0, "status": "需核验", "note": "所有者权益合计因PDF换行未直接识别，当前按资产减负债推算；请对照原表复核。"})
    else: check("资产负债表平衡", "资料不足", "资产=负债+权益", "-", False, "缺少资产、负债或权益合计。")
    if a("cash_end") is not None and a("cash") is not None:
        delta = a("cash_end") - a("cash"); tol = max(100, abs(a("cash")) * .02)
        check("期末现金勾稽", a("cash_end"), a("cash"), delta, abs(delta) <= tol, "现金流量表期末现金与资产负债表货币资金可能因受限资金存在差异。")
    findings = []
    def add(level, item, observed, benchmark, reason, action): findings.append({"level": level, "item": item, "observed": observed, "benchmark": benchmark, "reason": reason, "action": action})
    if not metrics: add("高", "报表识别", "未识别有效科目", "至少识别一张主表", "文件可能不是标准财务报表或清晰度不足。", "提供原始Excel或清晰PDF。")
    if ratios["current_ratio"] is not None and ratios["current_ratio"] < model["current"]: add("中" if ratios["current_ratio"] >= .8 else "高", "短期偿债能力", f"流动比率{ratios['current_ratio']:.2f}", f"行业参考≥{model['current']:.2f}", "流动资产对短期负债覆盖偏弱。", "核验短债到期安排、可变现存货和应收质量。")
    if ratios["quick_ratio"] is not None and ratios["quick_ratio"] < model["quick"]: add("中", "速动能力", f"速动比率{ratios['quick_ratio']:.2f}", f"行业参考≥{model['quick']:.2f}", "剔除存货后短期流动性偏弱。", "核验银行存款、应收回款及短期借款续贷依赖。")
    if ratios["debt_ratio"] is not None and ratios["debt_ratio"] > model["debt"]: add("高" if ratios["debt_ratio"] > model["debt"] + .12 else "中", "负债水平", f"资产负债率{ratios['debt_ratio']:.1%}", f"行业参考≤{model['debt']:.0%}", "杠杆高于当前行业模型。", "核验有息负债、隐性负债和股东资金性质。")
    if ratios["gross_margin"] is not None:
        low, high = model["gross"]
        if ratios["gross_margin"] < low or ratios["gross_margin"] > high: add("中", "毛利率合理性", f"毛利率{ratios['gross_margin']:.1%}", f"行业常见{low:.0%}–{high:.0%}", "毛利水平与行业模型差异较大，可能存在口径、一次性交易或业务结构差异。", "结合产品结构、售价、采购发票和纳税申报表核验。")
    if ratios["net_margin"] is not None and ratios["net_margin"] < model["net"]: add("中" if ratios["net_margin"] >= 0 else "高", "盈利能力", f"净利率{ratios['net_margin']:.1%}", f"行业参考≥{model['net']:.1%}", "净利润留存偏薄。", "拆解毛利、期间费用、非经常损益和关联交易。")
    if ratios["ar_days"] is not None and ratios["ar_days"] > model["ar"]: add("中", "应收账款周转", f"约{ratios['ar_days']:.0f}天", f"行业参考≤{model['ar']}天", "回款周期偏长；项目制或赊销业务需结合实际合同判断。", "查看账龄、期后回款、主要欠款方及坏账准备。")
    if ratios["inventory_days"] is not None and ratios["inventory_days"] > model["inv"]: add("中", "存货周转", f"约{ratios['inventory_days']:.0f}天", f"行业参考≤{model['inv']}天", "存货占用期偏长。", "核验库龄、滞销、在产品和跌价准备。")
    if profit is not None and profit > 0 and cfo is not None and cfo <= 0: add("高", "利润现金含量", f"净利润{profit:,.0f}、经营现金流{cfo:,.0f}", "盈利时经营现金流宜为正", "利润未形成经营现金流，可能受应收、存货或非现金收益影响。", "结合应收、存货变动和期后流水核验。")
    if ratios["cfo_profit"] is not None and 0 < ratios["cfo_profit"] < .6: add("中", "利润现金含量", f"经营现金/净利润{ratios['cfo_profit']:.2f}", "参考≥0.60", "利润转化为现金的能力偏弱。", "核验收入确认、回款和营运资金占用。")
    if not context: add("中", "企业实际情况", "未填写", "建议填写经营模式", "行业模型缺少客户实际经营约束。", "补充主要产品、上下游、账期、淡旺季和结算方式。")
    if not findings: add("低", "规则检测", "未触发明显异常", "仍需人工复核", "核心指标位于当前行业参考区间。", "继续核验报表原件、纳税、流水和征信的一致性。")
    return ratios, checks, findings


def fmt_ratio(value, percent=False, days=False):
    if value is None: return "资料不足"
    if percent: return f"{value:.1%}"
    if days: return f"{value:.0f}天"
    return f"{value:.2f}"


def change_rate(current, previous):
    return safe_div((current - previous) if current is not None and previous is not None else None, abs(previous) if previous is not None else None)


def trend_analysis(series: list[dict]) -> tuple[list[str], list[dict]]:
    if not series:
        return ["未形成可比较期间序列。"], []
    conclusions, findings = [], []
    latest = series[-1]
    period = latest["period"]
    conclusions.append(f"本次共形成 {len(series)} 个有效期间，最新口径为 {period['label']}。")

    def add_growth(title: str, current, previous, current_label: str, previous_label: str):
        rate = change_rate(current, previous)
        if rate is None:
            return
        direction = "增长" if rate >= 0 else "下降"
        conclusions.append(f"{title}：{current_label}较{previous_label}{direction}{abs(rate):.1%}。")
        if rate <= -.20:
            level, reason, action = "高", f"{title}同比明显下滑，经营规模或盈利能力承压。", "核验订单、价格、销量、客户流失及期后经营情况。"
        elif rate < 0:
            level, reason, action = "中", f"{title}较可比期间下降。", "结合行业淡旺季、订单与纳税申报核验下降原因。"
        else:
            level, reason, action = "低", f"{title}较可比期间保持增长。", "核验增长是否与发票、纳税和银行流水一致。"
        findings.append({"level": level, "item": f"{title}趋势", "observed": f"{direction}{abs(rate):.1%}", "benchmark": f"{current_label} 对比 {previous_label}", "reason": reason, "action": action})

    comparable = next((x for x in reversed(series[:-1]) if x["period"]["year"] == period["year"] - 1 and x["period"]["month"] == period["month"] and x["period"]["annual"] == period["annual"]), None)
    if comparable:
        add_growth("营业收入", latest["revenue"], comparable["revenue"], period["label"], comparable["period"]["label"])
        add_growth("净利润", latest["profit"], comparable["profit"], period["label"], comparable["period"]["label"])
        asset_rate = change_rate(latest.get("assets"), comparable.get("assets"))
        liability_rate = change_rate(latest.get("liabilities"), comparable.get("liabilities"))
        if asset_rate is not None:
            conclusions.append(f"资产总额同比{'增长' if asset_rate >= 0 else '下降'}{abs(asset_rate):.1%}。")
        if liability_rate is not None:
            conclusions.append(f"负债总额同比{'增长' if liability_rate >= 0 else '下降'}{abs(liability_rate):.1%}。")
        if latest.get("debt_ratio") is not None and comparable.get("debt_ratio") is not None:
            delta = latest["debt_ratio"] - comparable["debt_ratio"]
            conclusions.append(f"资产负债率同比{'上升' if delta >= 0 else '下降'}{abs(delta):.1%}，由{comparable['debt_ratio']:.1%}变为{latest['debt_ratio']:.1%}。")
    elif not period["annual"]:
        conclusions.append("最新近期报表未找到上年同月累计口径，近期同比暂不计算。")

    annuals = [x for x in series if x["period"]["annual"]]
    if len(annuals) >= 2 and not (period["annual"] and comparable):
        previous, current = annuals[-2], annuals[-1]
        add_growth("年度营业收入", current["revenue"], previous["revenue"], current["period"]["label"], previous["period"]["label"])
        add_growth("年度净利润", current["profit"], previous["profit"], current["period"]["label"], previous["period"]["label"])

    if latest.get("assets") is not None and latest.get("assets_prior") not in (None, 0):
        rate = change_rate(latest["assets"], latest["assets_prior"])
        conclusions.append(f"资产规模：最新期末较年初{'增长' if rate >= 0 else '下降'}{abs(rate):.1%}。")
    if latest.get("debt_ratio") is not None:
        conclusions.append(f"最新资产负债率为 {latest['debt_ratio']:.1%}，流动比率为 {latest['current_ratio']:.2f}。" if latest.get("current_ratio") is not None else f"最新资产负债率为 {latest['debt_ratio']:.1%}。")
    if all(x.get("profit") is not None and x["profit"] > 0 for x in series if x.get("revenue") is not None):
        conclusions.append("已识别期间均保持盈利，但仍需结合现金流验证利润质量。")
    if not any(x.get("cfo") is not None for x in series):
        conclusions.append("上传资料未识别到现金流量表，暂不能判断利润的现金实现程度。")
        findings.append({"level": "中", "item": "现金流资料完整性", "observed": "未识别经营现金流", "benchmark": "建议提供现金流量表", "reason": "仅凭资产负债表和利润表无法验证利润是否真正转化为现金。", "action": "补充现金流量表，或结合银行流水、应收账龄和期后回款复核。"})
    return conclusions, findings


def build_result(company: str, scope: str, description: str, period_type: str, file_results: list[dict], errors: list[dict]) -> dict:
    metrics, candidates = select_statements(file_results)
    series = build_period_series(candidates)
    model = infer_industry(scope, description)
    latest_period = series[-1]["period"] if series else {}
    ratios, checks, findings = analyze_metrics(metrics, model, description, period_type, latest_period)
    conclusions, trend_findings = trend_analysis(series)
    if ratios.get("current_ratio") is not None and ratios.get("debt_ratio") is not None:
        if ratios["current_ratio"] >= model["current"] and ratios["debt_ratio"] <= model["debt"]:
            conclusions.append(f"按{model['name']}模型，流动比率和资产负债率均处于当前行业参考范围内，账面偿债结构总体尚可。")
    if ratios.get("gross_margin") is not None and ratios.get("net_margin") is not None:
        conclusions.append(f"最新毛利率为{ratios['gross_margin']:.1%}、净利率为{ratios['net_margin']:.1%}，需与主营产品结构、税票和流水回款一致性结合判断。")
    if trend_findings:
        findings = [x for x in findings if x["item"] != "规则检测"] + trend_findings
    findings.sort(key=lambda x: {"高": 0, "中": 1, "低": 2}.get(x["level"], 3))
    same_year = [x for x in series if x["period"]["year"] == latest_period.get("year") and not x["period"]["annual"] and x.get("revenue") is not None]
    if len(same_year) >= 2:
        monotonic = all(same_year[i]["revenue"] >= same_year[i-1]["revenue"] for i in range(1, len(same_year)))
        checks.append({"name": "累计利润表连续性", "actual": " → ".join(f"{x['period']['month']}月:{x['revenue']:,.0f}" for x in same_year), "expected": "本年累计收入应随月份不减少", "delta": "-", "status": "通过" if monotonic else "异常", "note": "用于识别把单月数误当累计数或期间错位的情况。"})
    weights = {"高": 20, "中": 9, "低": 0}; score = min(100, sum(weights[x["level"]] for x in findings) + sum(12 for x in checks if x["status"] == "异常"))
    level = "风险偏高" if score >= 55 else "中等风险" if score >= 30 else "需关注" if score >= 9 else "较低风险"
    blocks = [
        {"title": "分析概览", "headers": ["项目", "结果"], "rows": [["企业", company or "未填写"], ["行业模型", model["name"]], ["综合关注程度", level], ["规则评分", score], ["最新分析期间", latest_period.get("label") or "未识别"], ["有效比较期间", len(series)], ["经营范围", scope or "未填写"], ["实际经营情况", description or "未填写"], ["行业分析重点", model["note"]], ["报表口径", {"annual":"年度","cumulative":"本年累计","monthly":"单月","auto":"按文件自动识别"}.get(period_type, period_type)]]},
        {"title": "核心财务指标", "headers": ["指标", "结果"], "rows": [["流动比率", fmt_ratio(ratios["current_ratio"])], ["速动比率", fmt_ratio(ratios["quick_ratio"])], ["资产负债率", fmt_ratio(ratios["debt_ratio"], True)], ["毛利率", fmt_ratio(ratios["gross_margin"], True)], ["净利率", fmt_ratio(ratios["net_margin"], True)], ["净资产收益率", fmt_ratio(ratios["roe"], True)], ["应收周转天数", fmt_ratio(ratios["ar_days"], days=True)], ["存货周转天数", fmt_ratio(ratios["inventory_days"], days=True)], ["经营现金/净利润", fmt_ratio(ratios["cfo_profit"])], ["营运资金", ratios["working_capital"] if ratios["working_capital"] is not None else "资料不足"]]},
        {"title": "经营分析结论", "headers": ["序号", "结论"], "rows": [[idx, text] for idx, text in enumerate(conclusions, 1)]},
        {"title": "多期间财务趋势", "headers": ["期间", "口径", "营业收入", "营业成本", "净利润", "资产总额", "负债总额", "资产负债率", "流动比率", "毛利率", "净利率", "来源"], "rows": [[x["period"]["label"], "年度" if x["period"]["annual"] else "本年累计", x["revenue"] if x["revenue"] is not None else "", x["cost"] if x["cost"] is not None else "", x["profit"] if x["profit"] is not None else "", x["assets"] if x["assets"] is not None else "", x["liabilities"] if x["liabilities"] is not None else "", fmt_ratio(x["debt_ratio"], True), fmt_ratio(x["current_ratio"]), fmt_ratio(x["gross_margin"], True), fmt_ratio(x["net_margin"], True), x["source"]] for x in series]},
        {"title": "银行风控分析", "headers": ["程度", "项目", "检测结果", "行业参考", "分析", "建议核验"], "rows": [[x["level"], x["item"], x["observed"], x["benchmark"], x["reason"], x["action"]] for x in findings]},
        {"title": "报表勾稽检查", "headers": ["检查", "实际值", "应有值", "差额", "状态", "说明"], "rows": [[x["name"], x["actual"], x["expected"], x["delta"], x["status"], x["note"]] for x in checks]},
        {"title": "识别科目", "headers": ["报表", "科目", "本期/期末", "上期/期初", "来源文件", "工作表", "行号"], "rows": [[statement_for(k), row["label"], row["current"], row["prior"] if row["prior"] is not None else "", row["source"], row["sheet"], row["row"]] for k, row in metrics.items()]},
        {"title": "文件识别情况", "headers": ["文件", "识别期间", "识别分组", "候选主表数", "状态"], "rows": [[f["filename"], "、".join(dict.fromkeys(g.get("period", {}).get("label", "未识别") for g in f["groups"])), len(f["groups"]), sum(1 for c in candidates if c["source"] == f["filename"]), "已识别" if f["groups"] else "未识别有效财务科目"] for f in file_results] + [[e["file"], "", "", "", e["error"]] for e in errors]},
    ]
    e = html.escape
    ratio_cards = [("流动比率", fmt_ratio(ratios["current_ratio"])), ("资产负债率", fmt_ratio(ratios["debt_ratio"], True)), ("毛利率", fmt_ratio(ratios["gross_margin"], True)), ("净利率", fmt_ratio(ratios["net_margin"], True))]
    findings_html = "".join(f"<tr><td><span class='pill {x['level']}'>{x['level']}</span></td><td>{e(x['item'])}</td><td>{e(x['observed'])}</td><td>{e(x['benchmark'])}</td><td>{e(x['reason'])}</td><td>{e(x['action'])}</td></tr>" for x in findings)
    checks_html = "".join(f"<tr><td>{e(x['name'])}</td><td>{e(str(x['actual']))}</td><td>{e(str(x['expected']))}</td><td>{e(str(x['delta']))}</td><td>{e(x['status'])}</td><td>{e(x['note'])}</td></tr>" for x in checks)
    conclusion_html = "".join(f"<li>{e(text)}</li>" for text in conclusions)
    def fmt_money_html(value):
        return "" if value is None else f"{value:,.2f}"
    trend_html = "".join(f"<tr><td>{e(x['period']['label'])}</td><td>{'年度' if x['period']['annual'] else '本年累计'}</td><td>{fmt_money_html(x['revenue'])}</td><td>{fmt_money_html(x['profit'])}</td><td>{fmt_money_html(x['assets'])}</td><td>{fmt_ratio(x['debt_ratio'], True)}</td><td>{fmt_ratio(x['gross_margin'], True)}</td><td>{fmt_ratio(x['net_margin'], True)}</td></tr>" for x in series)
    metrics_html = "".join(f"<tr><td>{e(statement_for(k))}</td><td>{e(r['label'])}</td><td>{fmt_money_html(r['current'])}</td><td>{fmt_money_html(r['prior'])}</td><td>{e(r['source'])} / {e(r['sheet'])}</td></tr>" for k, r in metrics.items())
    report_html = f"""<article><div class='report-title'><div><h2>{e(company or '企业')}财务报表分析</h2><p>最新期间：{e(latest_period.get('label') or '未识别')}；行业模型：{e(model['name'])}；综合关注程度：<strong>{e(level)}</strong></p></div><span class='risk'>{e(level)}</span></div><div class='cards'>{''.join(f'<div class="card"><span>{e(a)}</span><strong>{e(b)}</strong></div>' for a,b in ratio_cards)}</div><div class='model'><strong>行业与实际经营分析：</strong>{e(model['note'])} {e(description or '尚未填写实际经营情况，当前结论采用行业通用假设。')}</div><h3>经营分析结论</h3><div class='model'><ol>{conclusion_html}</ol></div><h3>多期间财务趋势</h3><div class='table-wrap'><table><thead><tr><th>期间</th><th>口径</th><th>营业收入</th><th>净利润</th><th>资产总额</th><th>资产负债率</th><th>毛利率</th><th>净利率</th></tr></thead><tbody>{trend_html or '<tr><td colspan="8">未形成有效期间序列</td></tr>'}</tbody></table><h3>银行风控分析</h3><table><thead><tr><th>程度</th><th>项目</th><th>检测结果</th><th>行业参考</th><th>分析</th><th>建议核验</th></tr></thead><tbody>{findings_html}</tbody></table><h3>报表勾稽检查</h3><table><thead><tr><th>检查</th><th>实际值</th><th>应有值</th><th>差额</th><th>状态</th><th>说明</th></tr></thead><tbody>{checks_html}</tbody></table><h3>识别科目与来源</h3><table><thead><tr><th>报表</th><th>科目</th><th>本期/期末</th><th>上期/期初</th><th>来源</th></tr></thead><tbody>{metrics_html or '<tr><td colspan="5">未识别到有效财务科目</td></tr>'}</tbody></table></div><p class='note'>本结果用于贷前筛查和人工复核。行业阈值为解释性规则，不等同于审计意见或银行最终审批结论。</p></article>"""
    return {"company": company, "risk": level, "score": score, "model": model["name"], "latest_period": latest_period.get("label"), "report_html": report_html, "export_blocks": blocks, "metrics": {**ratios, "recognized": len(metrics), "period_count": len(series)}, "files": file_results, "errors": errors}


def run_job(job_id: str, paths: list[Path], company: str, scope: str, description: str, period_type: str, passwords: list[str]) -> None:
    results, errors = [], []
    try:
        for idx, path in enumerate(paths, 1):
            set_job(job_id, status="running", percent=int((idx - 1) * 90 / max(1, len(paths))), message=f"正在识别第 {idx}/{len(paths)} 个文件：{path.name}")
            try: results.append(analyze_file(path, passwords))
            except Exception as exc: errors.append({"file": path.name, "error": str(exc)})
        result = build_result(company, scope, description, period_type, results, errors)
        set_job(job_id, status="done", percent=100, message="财务报表分析完成", result=result)
    except Exception as exc:
        set_job(job_id, status="error", percent=100, message=str(exc), error=str(exc), trace=traceback.format_exc())


INDEX = r'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>财务报表分析</title><style>
:root{--ink:#edf7ff;--muted:#9db1c8;--line:rgba(166,210,255,.22);--nav:rgba(10,18,36,.72);--blue:#28d5ff;--violet:#8b5cf6;--green:#40f0b2;--shadow:0 28px 70px rgba(0,0,0,.32)}*{box-sizing:border-box}body{margin:0;min-height:100vh;background:radial-gradient(circle at 12% 12%,rgba(40,213,255,.28),transparent 30%),radial-gradient(circle at 86% 4%,rgba(139,92,246,.32),transparent 34%),linear-gradient(135deg,#07111f,#0c1832 48%,#121735);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif;line-height:1.5}.shell{display:grid;grid-template-columns:390px minmax(0,1fr);min-height:100vh}.side{position:relative;background:linear-gradient(180deg,rgba(10,18,36,.86),rgba(10,18,36,.56));border-right:1px solid var(--line);box-shadow:24px 0 70px rgba(0,0,0,.26);backdrop-filter:blur(22px);color:#fff;padding:28px}.main{padding:28px;min-width:0}.brand{padding:6px 0 10px}.brand h1{font-size:28px;margin:0 0 8px;letter-spacing:.04em;background:linear-gradient(90deg,#fff,#62e7ff,#b99cff);-webkit-background-clip:text;color:transparent}.brand p,.note{font-size:13px;color:var(--muted)}.brand p{color:#bdd5ea}.box,.metric,.panel,.card{background:linear-gradient(145deg,rgba(255,255,255,.16),rgba(255,255,255,.06));border:1px solid var(--line);border-radius:22px;box-shadow:var(--shadow);backdrop-filter:blur(18px)}.box{padding:18px;margin:18px 0}.field{margin-top:13px}.field label{display:block;font-size:13px;color:#cfe6ff}.field input,.field textarea,.field select{width:100%;margin-top:6px;border:1px solid rgba(166,210,255,.24);background:rgba(5,12,26,.42);color:#f4fbff;border-radius:14px;padding:11px 12px;outline:none}.field input:focus,.field textarea:focus,.field select:focus{border-color:rgba(40,213,255,.72);box-shadow:0 0 0 4px rgba(40,213,255,.12)}.field textarea{min-height:78px}select option{background:#111b35;color:#edf7ff}.drop{border:1px dashed rgba(98,231,255,.55);border-radius:18px;padding:18px;text-align:center;background:rgba(40,213,255,.08);color:#dff9ff}.drop small{display:block;color:#9db1c8}.native-file{width:100%;margin-top:12px;color:#dbeafe}.file-name,.status{font-size:13px;color:#cfe6ff;margin-top:10px;white-space:pre-wrap}.btn-row,.actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:14px}button{border:0;border-radius:14px;padding:11px 16px;cursor:pointer;font-weight:800;letter-spacing:.02em;transition:.18s ease;box-shadow:0 12px 28px rgba(0,0,0,.22)}button:hover{transform:translateY(-1px)}button.primary{background:linear-gradient(135deg,var(--blue),var(--violet));color:#fff}button.ghost{background:rgba(255,255,255,.08);color:#e8f7ff;border:1px solid rgba(255,255,255,.22)}button:disabled{opacity:.5;cursor:not-allowed}.progress{height:10px;background:rgba(255,255,255,.12);border-radius:99px;overflow:hidden;margin-top:13px}.progress span{display:block;height:100%;width:0;background:linear-gradient(90deg,var(--green),var(--blue),var(--violet));box-shadow:0 0 20px rgba(40,213,255,.7)}.metrics,.cards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px}.metric,.card{padding:18px}.metric span,.card span{display:block;color:var(--muted);font-size:13px}.metric strong,.card strong{display:block;font-size:25px;margin-top:8px;color:#fff;text-shadow:0 0 18px rgba(40,213,255,.24)}.panel{padding:20px;margin-top:18px}.toolbar,.report-title{display:flex;align-items:center;justify-content:space-between;gap:12px}.toolbar h2{margin:0;font-size:20px;color:#f7fbff}.actions{margin:0}.actions button{background:rgba(255,255,255,.1);color:#dff7ff;border:1px solid rgba(166,210,255,.22)}.empty,.model{padding:24px;background:rgba(255,255,255,.06);border:1px dashed rgba(166,210,255,.28);border-radius:18px;color:#b8cade}.model{margin:16px 0;color:#d6e8f8}.risk,.pill{display:inline-flex;border-radius:999px;padding:5px 12px;background:rgba(255,200,87,.16);color:#ffd978;border:1px solid rgba(255,217,120,.26)}.pill.高{background:rgba(255,99,99,.16);color:#ff9f9f;border-color:rgba(255,159,159,.35)}.pill.中{background:rgba(255,200,87,.16);color:#ffd978;border-color:rgba(255,217,120,.3)}.pill.低{background:rgba(64,240,178,.14);color:#7fffd5;border-color:rgba(127,255,213,.3)}.table-wrap{overflow:auto}table{border-collapse:collapse;width:100%;min-width:820px;margin:12px 0 20px;color:#eaf4ff}th,td{border:1px solid rgba(166,210,255,.18);padding:9px;text-align:left;font-size:13px;vertical-align:top}th{background:rgba(40,213,255,.10);color:#f4fbff}.debug{font-size:12px;color:#9db1c8;white-space:pre-wrap}.note{margin-top:16px}@media(max-width:980px){.shell{grid-template-columns:1fr}.metrics,.cards{grid-template-columns:1fr 1fr}}@media(max-width:600px){.metrics,.cards{grid-template-columns:1fr}.side,.main{padding:16px}}@media print{body{background:#fff;color:#111}.side,.actions,.debug{display:none}.shell{display:block}.main{padding:0}.panel,.metric,.card{box-shadow:none;background:#fff;color:#111;border:1px solid #ddd}table,th,td{color:#111;border-color:#ccc}}
</style></head><body><div class="shell"><aside class="side"><div class="brand"><h1>财务报表分析</h1><p>结合行业、实际经营情况和三张主表进行银行风控分析。</p></div><section class="box"><form id="form"><div class="field"><label>企业名称</label><input id="company" name="company" placeholder="请输入企业名称"></div><div class="field"><label>营业执照经营范围</label><textarea id="scope" name="scope" placeholder="粘贴营业执照经营范围"></textarea></div><div class="field"><label>实际经营情况</label><textarea id="description" name="description" placeholder="主营产品、上下游、账期、淡旺季、结算方式等"></textarea></div><div class="field"><label>利润表口径</label><select id="periodType" name="period_type"><option value="auto">自动/年度</option><option value="annual">年度</option><option value="cumulative">本年累计</option><option value="monthly">单月</option></select></div><div class="drop"><strong>上传财务报表</strong><small>资产负债表、利润表、现金流量表</small></div><input id="files" class="native-file" type="file" multiple accept=".xlsx,.xls,.csv,.pdf,image/*" required><div id="fileName" class="file-name">尚未选择文件</div><div class="field"><label>文件密码（如有）</label><textarea id="passwords" placeholder="每行一个密码"></textarea></div><div class="btn-row"><button class="primary" id="submitBtn">上传并分析</button><button class="ghost" id="resetBtn" type="button">清空</button></div></form><div class="progress"><span id="bar"></span></div><div id="status" class="status">请选择财务报表文件。</div></section><p style="color:#c7d1df;font-size:13px">建议优先上传原始Excel。扫描PDF和图片会使用本地OCR，识别结果需结合原件复核。</p></aside><main class="main"><section class="metrics"><div class="metric"><span>综合关注程度</span><strong id="mRisk">-</strong></div><div class="metric"><span>行业模型</span><strong id="mIndustry">-</strong></div><div class="metric"><span>识别科目</span><strong id="mCount">-</strong></div><div class="metric"><span>规则评分</span><strong id="mScore">-</strong></div></section><section class="panel"><div class="toolbar"><h2>财务分析报告</h2><div class="actions"><button id="pdfBtn" disabled>下载PDF</button><button id="excelBtn" disabled>下载Excel</button><button id="printBtn">打印</button></div></div><div id="result"><div class="empty">上传财务报表后，这里会显示行业化分析、核心指标和勾稽检查。</div></div></section><section class="panel"><h2>处理诊断</h2><div id="debug" class="debug">等待分析。</div></section></main></div><script>
const form=document.getElementById('form'),files=document.getElementById('files'),fileName=document.getElementById('fileName'),statusEl=document.getElementById('status'),bar=document.getElementById('bar'),result=document.getElementById('result'),debug=document.getElementById('debug'),submitBtn=document.getElementById('submitBtn');let jobId=null,lastData=null;
files.onchange=()=>fileName.textContent=files.files.length?[...files.files].map(x=>x.name).join('\n'):'尚未选择文件';const downloads=on=>['pdfBtn','excelBtn'].forEach(id=>document.getElementById(id).disabled=!on);const progress=v=>bar.style.width=`${Math.max(0,Math.min(100,Number(v)||0))}%`;
form.onsubmit=async e=>{e.preventDefault();if(!files.files.length)return;const fd=new FormData();[...files.files].forEach(f=>fd.append('file',f));['company','scope','description','periodType','passwords'].forEach(id=>fd.append(id==='periodType'?'period_type':id,document.getElementById(id).value||''));submitBtn.disabled=true;downloads(false);result.innerHTML='<div class="empty">正在识别报表并建立行业模型，请稍候。</div>';try{const start=await fetch('/financial/analyze/start',{method:'POST',body:fd}),s=await start.json();if(!start.ok)throw new Error(s.error||'提交失败');jobId=s.job_id;while(true){const r=await fetch(`/financial/progress?job_id=${encodeURIComponent(jobId)}`),j=await r.json();progress(j.percent);statusEl.textContent=`${j.percent||0}%  ${j.message||''}`;if(j.status==='done'){lastData=j.result;render(j.result);downloads(true);break}if(j.status==='error')throw new Error(j.error||j.message);await new Promise(x=>setTimeout(x,800))}}catch(err){statusEl.textContent=err.message;debug.textContent=err.stack||String(err)}finally{submitBtn.disabled=false}};
function render(d){document.getElementById('mRisk').textContent=d.risk;document.getElementById('mIndustry').textContent=d.model;document.getElementById('mCount').textContent=d.metrics.recognized;document.getElementById('mScore').textContent=d.score+'/100';result.innerHTML=d.report_html;debug.textContent=`文件：${d.files.length}\n识别科目：${d.metrics.recognized}\n异常文件：${d.errors.length}`}
async function download(format){if(!jobId)return;statusEl.textContent='正在生成下载文件...';const r=await fetch('/financial/export',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_id:jobId,format})});if(!r.ok){const e=await r.json();statusEl.textContent=e.error||'下载失败';return}const blob=await r.blob(),m=/filename\*=UTF-8''([^;]+)/i.exec(r.headers.get('Content-Disposition')||''),name=m?decodeURIComponent(m[1]):`财务报表分析.${format}`;const u=URL.createObjectURL(blob),a=document.createElement('a');a.href=u;a.download=name;document.body.appendChild(a);a.click();a.remove();URL.revokeObjectURL(u);statusEl.textContent=`已生成：${name}`}
document.getElementById('pdfBtn').onclick=()=>download('pdf');document.getElementById('excelBtn').onclick=()=>download('excel');document.getElementById('printBtn').onclick=()=>window.print();document.getElementById('resetBtn').onclick=()=>{form.reset();jobId=null;lastData=null;fileName.textContent='尚未选择文件';statusEl.textContent='请选择财务报表文件。';progress(0);downloads(false);result.innerHTML='<div class="empty">上传财务报表后，这里会显示行业化分析、核心指标和勾稽检查。</div>';debug.textContent='等待分析。'};downloads(false);
</script></body></html>'''


class Handler(BaseHTTPRequestHandler):
    def json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode(); self.send_response(status); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/financial"}:
            body = INDEX.encode(); self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
        if parsed.path == "/financial/progress":
            job = get_job((parse_qs(parsed.query).get("job_id") or [""])[0]); self.json(job or {"error": "任务不存在"}, 200 if job else 404); return
        self.send_error(404)

    def do_POST(self):
        if self.path == "/financial/export":
            try:
                payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}"); job = get_job(payload.get("job_id") or "")
                if job.get("status") != "done": raise ValueError("财务分析尚未完成。")
                data = {"title": f"{job['result'].get('company') or '企业'}财务报表分析报告", "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"), "filters_text": f"行业模型：{job['result']['model']}；结果需人工复核", "blocks": job["result"]["export_blocks"]}
                content, filename, ctype = flow.build_flow_export(data, payload.get("format") or "")
                self.send_response(200); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(content))); self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(filename)}"); self.end_headers(); self.wfile.write(content)
            except Exception as exc: self.json({"error": str(exc), "trace": traceback.format_exc()}, 500)
            return
        if self.path != "/financial/analyze/start": self.send_error(404); return
        try:
            form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ={"REQUEST_METHOD": "POST"}); items = form["file"] if isinstance(form["file"], list) else [form["file"]]
            job_id = uuid.uuid4().hex; folder = UPLOADS / job_id; folder.mkdir(parents=True, exist_ok=True); paths = []
            for idx, item in enumerate(items, 1):
                name = Path(item.filename or f"file-{idx}").name
                if Path(name).suffix.lower() not in SUPPORTED: continue
                path = folder / name; path.write_bytes(item.file.read()); paths.append(path)
            if not paths: raise ValueError("未收到支持的财务报表文件。")
            company = str(form.getfirst("company", "")).strip(); scope = str(form.getfirst("scope", "")).strip(); description = str(form.getfirst("description", "")).strip(); period_type = str(form.getfirst("period_type", "auto")); passwords = flow.parse_passwords(form.getfirst("passwords", ""))
            set_job(job_id, status="queued", percent=0, message=f"已接收 {len(paths)} 个文件"); threading.Thread(target=run_job, args=(job_id, paths, company, scope, description, period_type, passwords), daemon=True).start(); self.json({"job_id": job_id})
        except Exception as exc: self.json({"error": str(exc), "trace": traceback.format_exc()}, 500)

    def log_message(self, *_): return


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", "8793")); print(f"本地财务报表分析：http://127.0.0.1:{port}/financial", flush=True); ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
