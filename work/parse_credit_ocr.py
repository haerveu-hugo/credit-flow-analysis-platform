from __future__ import annotations
import json
import re
import sys
from difflib import SequenceMatcher
from datetime import datetime, timedelta
from pathlib import Path


def clean(s: str) -> str:
    return (s.replace('货款', '贷款')
             .replace('触资型租赁', '融资型租赁')
             .replace('融融资租赁', '融资租赁')
             .replace('资租赁', '融资租赁')
             .replace('融融资租赁', '融资租赁')
             .replace('货记卡', '贷记卡')
             .replace('投信', '授信')
             .replace('投值', '授信')
             .replace('授值', '授信')
             .replace('授伯', '授信')
             .replace('颜度', '额度')
             .replace('顾度', '额度')
             .replace('余颜', '余额')
             .replace('余商', '余额')
             .replace('彩余', '剩余')
             .replace('贵任', '责任')
             .replace('资任', '责任')
             .replace('费任', '责任')
             .replace('肃任', '责任')
             .replace('进任', '责任')
             .replace('饮贵', '款责')
             .replace('还饮责任', '还款责任')
             .replace('还效', '还款')
             .replace('旧效人', '借款人')
             .replace('团效人', '借款人')
             .replace('份款人', '借款人')
             .replace('价款人', '借款人')
             .replace('世款人', '借款人')
             .replace('国款人', '借款人')
             .replace('供款人', '借款人')
             .replace('欲人', '借款人')
             .replace('顺图区', '顺德区')
             .replace('版创区', '顺德区')
             .replace('中批', '审批')
             .replace('申查', '审查')
             .replace('变淘', '查询')
             .replace('豪询', '查询')
             .replace('盗询', '查询')
             .replace('信用卡年批', '信用卡审批')
             .replace('信用事批', '信用卡审批'))


def money(s: str) -> float:
    m = re.search(r'-?\d[\d,]*(?:\.\d+)?', s or '')
    return float(m.group(0).replace(',', '')) if m else 0.0


def ocr_money(s: str) -> float:
    """Read amounts where OCR may turn a thousands comma into a full stop."""
    token = (s or '').strip().replace('，', ',')
    if re.fullmatch(r'\d{1,3}(?:[,.]\d{3})+', token):
        return float(re.sub(r'[,.]', '', token))
    return money(token)


def normalize_org_name(name: str) -> str:
    text = clean(name or '')
    text = re.sub(r'[^\u4e00-\u9fffA-Za-z0-9（）()]+', '', text)
    text = re.sub(r'[A-Z]?\d{6,}[A-Za-z0-9]*', '', text)
    fixes = {
        '奇助做银汽车金限股份有限公司': '奇瑞徽银汽车金融股份有限公司',
        '奇瑞散银汽车金联股份有限公司': '奇瑞徽银汽车金融股份有限公司',
        '河南中原消费金胶股份有限公司': '河南中原消费金融股份有限公司',
        '中信百信银行股份有限公司': '中信百信银行股份有限公司',
        '西安银行股份有限公司': '西安银行股份有限公司',
        '上海浦东发展银行股份有限公司天津河西浦琪支行': '上海浦东发展银行股份有限公司天津河西浦琪支行',
        '中国邮政储蓄银行股份有限公司佛山市分行': '中国邮政储蓄银行股份有限公司佛山市分行',
        '中国邮政储蓄银行股份有限公司广东省分行': '中国邮政储蓄银行股份有限公司广东省分行',
        '中国农业银行股份有限公司顺德分行': '中国农业银行股份有限公司顺德分行',
        '中国对外经济贸易信托有限公司': '中国对外经济贸易信托有限公司',
        '渤海银行股份有限公司合肥分行': '渤海银行股份有限公司合肥分行',
    }
    for bad, good in fixes.items():
        if bad in text:
            return good
    text = text.replace('股份有限责任公司', '股份有限公司')
    text = text.replace('股份有限', '股份有限公司')
    text = text.replace('股份有限公司公司', '股份有限公司')
    text = text.replace('金限', '金融')
    text = text.replace('金胶', '金融')
    text = text.replace('同络', '网络')
    text = text.replace('小颜', '小额')
    text = text.replace('小频', '小额')
    return text[:80]


def line_after(lines, idx, max_scan=30, money_like=False):
    for j in range(idx + 1, min(len(lines), idx + max_scan)):
        val = lines[j].strip()
        if not val:
            continue
        if money_like and not re.search(r'\d', val):
            continue
        return val
    return ''


def detect_report_type(text: str) -> dict:
    enterprise_hits = [
        '企业信用报告', '企业征信', '企业基本信息', '基本概况信息', '组织机构代码',
        '统一社会信用代码', '法定代表人', '注册资本', '对公贷款', '银行承兑汇票',
        '保函', '信用证', '票据贴现', '贸易融资', '企业借款'
    ]
    personal_hits = [
        '个人信用报告', '个人征信', '贷记卡', '信用卡', '个人住房', '个人经营性贷款',
        '本人声明', '配偶', '居住信息', '职业信息'
    ]
    enterprise_score = sum(1 for key in enterprise_hits if key in text)
    personal_score = sum(1 for key in personal_hits if key in text)
    if enterprise_score >= max(2, personal_score + 1):
        kind = 'enterprise'
        label = '企业征信'
    elif personal_score:
        kind = 'personal'
        label = '个人征信'
    else:
        kind = 'unknown'
        label = '未知类型'
    return {'kind': kind, 'label': label, 'enterprise_score': enterprise_score, 'personal_score': personal_score}


def parse_summary(lines):
    text = '\n'.join(lines)
    result = {
        'report_date': '',
        'loan_summary': {'non_revolving_balance': 0, 'non_revolving_monthly': 0, 'revolving_balance': 0, 'revolving_monthly': 0},
        'card_summary': {'total_limit': 0, 'used': 0, 'last6_avg_used': 0},
        'guarantee_summary': {'count': 0, 'guarantee_amount': 0, 'balance': 0, 'main_borrower': ''},
        'inquiries': {'last_month_loan': 0, 'last_month_card': 0, 'two_year_loan': 0, 'two_year_card': 0},
    }
    m = re.search(r'报告时间[:：]?\s*(20\d{2})[.年-]?(\d{2})[.月-]?(\d{2})', text)
    if m:
        result['report_date'] = f'{m.group(1)}-{m.group(2)}-{m.group(3)}'

    # Summary page has stable consecutive numeric fields after labels.
    nums = [money(x) for x in lines if re.fullmatch(r'[\d,]+(?:\.\d+)?', x.strip())]
    # Use label proximity for card summary.
    for i, line in enumerate(lines):
        if '贷记卡账户信息汇总' in line:
            window = lines[i:i+35]
            vals = [money(x) for x in window if re.fullmatch(r'[\d,]+(?:\.\d+)?', x.strip())]
            # expected: institutions, accounts, max single, min single, total, used, avg
            if len(vals) >= 7:
                result['card_summary'] = {'total_limit': vals[2], 'used': vals[5], 'last6_avg_used': vals[6]}
        if '非循环贷账户信息汇总' in line:
            window = lines[i:i + 35]
            vals = [money(x) for x in window if re.fullmatch(r'[\d,]+(?:\.\d+)?', x.strip())]
            if len(vals) >= 5:
                result['loan_summary']['non_revolving_balance'] = vals[3]
                result['loan_summary']['non_revolving_monthly'] = vals[4]
        if '循环贷账户' in line and '信息汇总' in line:
            window = lines[i:i + 35]
            vals = [money(x) for x in window if re.fullmatch(r'[\d,]+(?:\.\d+)?', x.strip())]
            if len(vals) >= 5:
                result['loan_summary']['revolving_balance'] = vals[3]
                result['loan_summary']['revolving_monthly'] = vals[4]
        if '相关还款责任信息汇总' in line:
            window = lines[i:i+25]
            row_values = None
            for row in window:
                tokens = re.findall(r'\d[\d,]*(?:\.\d+)?', row)
                vals = [money(token) for token in tokens]
                if len(vals) >= 3 and 0 < vals[0] <= 100 and vals[1] >= 10_000 and vals[2] >= 0:
                    row_values = vals
                    break
            if row_values:
                result['guarantee_summary'].update({
                    'count': int(row_values[0]),
                    'guarantee_amount': row_values[1],
                    'balance': row_values[2],
                })
            else:
                vals = [money(x) for x in window if re.fullmatch(r'[\d,]+(?:\.\d+)?', x.strip())]
                if len(vals) >= 3:
                    result['guarantee_summary'].update({'count': int(vals[0]), 'guarantee_amount': vals[1], 'balance': vals[2]})
        if '查询记录概要' in line:
            window = lines[i:i+35]
            vals = [int(money(x)) for x in window if re.fullmatch(r'\d+', x.strip())]
            # OCR order here: last month loan/card often 0/0, two-year loan/card 46/13
            if len(vals) >= 4:
                result['inquiries'] = {
                    'last_month_loan': vals[0], 'last_month_card': vals[1],
                    'two_year_post_loan_management': vals[3] if len(vals) > 3 else 0, 'two_year_guarantee_qualification': vals[4] if len(vals) > 4 else 0
                }
    # Row reconstruction can place the compact guarantee summary before the
    # vertically extracted section heading. Prefer the explicit three-column row.
    for i, line in enumerate(lines):
        if '担保责任' not in line or '其他相关还款责任' not in line:
            continue
        for row in lines[i + 1:i + 6]:
            vals = [money(token) for token in re.findall(r'\d[\d,]*(?:\.\d+)?', row)]
            if len(vals) >= 3 and 0 < vals[0] <= 100 and vals[1] >= 10_000:
                result['guarantee_summary'].update({
                    'count': int(vals[0]),
                    'guarantee_amount': vals[1],
                    'balance': vals[2],
                })
                return result
    return result


def normalize_inline(text: str) -> str:
    return re.sub(r'\s+', '', text.replace('，', ',').replace('。', '.').replace('．', '.'))


def parse_simple_cards(text: str):
    """Parse simplified report prose card lines."""
    inline = normalize_inline(text)
    cards = []
    pattern = re.compile(
        r'(\d{4}年\d{2}月\d{2}日)([^.。]{2,80}?)发放的贷记卡.*?'
        r'信用额度([\d,]+),已使用额度([\d,]+)'
    )
    for match in pattern.finditer(inline):
        lender = match.group(2)
        lender = re.sub(r'^.*?\d+[.、]?', '', lender)
        cards.append({'lender': lender[-40:] or '未识别', 'limit': money(match.group(3)), 'used': money(match.group(4))})
    # Photographed summary reports occasionally lose the lender/date line but
    # retain the two most important figures. Keep those figures instead of
    # returning an empty card summary.
    if not cards:
        photo_text = clean(text).replace('，', ',')
        amount_token = r'(?:\d{1,3}(?:[,.]\d{3})+|\d{4,8})'
        for match in re.finditer(rf'(?:信用额度)?({amount_token})[,.。]?\s*已使用额度({amount_token})', photo_text):
            limit = ocr_money(match.group(1))
            used = ocr_money(match.group(2))
            if limit > 0 and 0 <= used <= max(limit * 2, limit + 100_000):
                cards.append({'lender': '发卡机构未识别', 'limit': limit, 'used': used})
    return cards


def parse_simple_loans(text: str):
    """Parse simplified report prose loan lines."""
    inline = normalize_inline(text).replace('，', ',')
    section = inline
    loans = []
    direct_pattern = re.compile(
        r'(\d{4}年\d{2}月\d{2}日)([^.。]{2,100}?)发放的([\d,]+)元（人民币）'
        r'(个人住房商业贷款|个人经营性贷款|个人汽车消费贷款|其他个人消费贷款|其他贷款)'
        r'.*?截至(\d{4}年\d{2}月),余额(?:为)?([\d,]+)',
    )
    for match in direct_pattern.finditer(section):
        raw = match.group(0)
        if '已结清' in raw or '销户' in raw:
            continue
        lender = match.group(2)[-40:]
        limit = ocr_money(match.group(3) or '')
        type_ = match.group(4) or '贷款'
        balance = ocr_money(match.group(6))
        if balance > 0 or limit > 0:
            loans.append({
                'lender': lender or '未识别',
                'type': type_,
                'guarantee': '未识别',
                'limit': limit,
                'balance': balance,
                'remaining_terms': '',
                'monthly_payment': 0,
            })
    # New concise reports describe every open revolving facility in one prose
    # sentence. Match the sentence directly: PDF text extraction does not
    # preserve the printed list numbers, so splitting on list punctuation used
    # to merge several accounts and create duplicate balances.
    revolving_pattern = re.compile(
        r'(20\d{2}年\d{2}月\d{2}[日口H#]?)([^.。]{2,120}?)为?'
        r'(个人经营性贷款授信|其他个人消费贷款授信|个人消费贷款授信|其他贷款授信)'
        r'.{0,220}?'
        r'截至(20\d{2}年\d{2}月),(?:信用)(?:额度|顺度|融度|幅度|氯度)([\d,]+)元（人民币）,'
        r'余额(?:为)?([\d,]+)',
    )
    for match in revolving_pattern.finditer(section):
        lender = normalize_org_name(match.group(2)[-60:]) or '未识别'
        balance = ocr_money(match.group(6))
        loans.append({
            'lender': lender,
            'type': match.group(3),
            'guarantee': '未识别',
            'limit': ocr_money(match.group(5)),
            'balance': balance,
            'remaining_terms': '',
            'monthly_payment': 0,
        })
    # On oblique phone photos the small first line (date and lender) can drop
    # out while the larger limit/balance line remains readable. Preserve that
    # account as an explicitly marked item instead of losing the debt entirely.
    recognized_pairs = {
        (round(float(item.get('limit') or 0), 2), round(float(item.get('balance') or 0), 2))
        for item in loans
    }
    for match in re.finditer(
        r'信用(?:额度|顺度|融度|幅度|氯度)([\d,.，]+)元（人民币）[,.。]?余额(?:为)?([\d,.，]+)',
        section,
    ):
        limit = ocr_money(match.group(1))
        balance = ocr_money(match.group(2))
        key = (round(limit, 2), round(balance, 2))
        if key in recognized_pairs:
            continue
        recognized_pairs.add(key)
        loans.append({
            'lender': '机构名称未识别（拍照页）',
            'type': '贷款授信',
            'guarantee': '未识别',
            'limit': limit,
            'balance': balance,
            'remaining_terms': '',
            'monthly_payment': 0,
        })
    return loans


def parse_simple_other_business(text: str) -> list[dict]:
    """Parse personal-report financing lease and similar open businesses."""
    inline = normalize_inline(text)
    items = []
    pattern = re.compile(
        r'(20\d{2}年\d{2}月\d{2}日)([^.。]{2,100}?)办理的([\d,.，]+)元（人民币）'
        r'(融{1,2}资租赁业务|其他业务)(?:,(20\d{2}年\d{2}月\d{2}日)到期)?.{0,100}?'
        r'截至(20\d{2}年\d{2}月(?:\d{2}日)?),?余额(?:为)?([\d,.，]+)'
    )
    for match in pattern.finditer(inline):
        amount = ocr_money(match.group(3))
        balance = ocr_money(match.group(7))
        if amount <= 0 and balance <= 0:
            continue
        items.append({
            'lender': normalize_org_name(match.group(2)[-60:]) or '未识别',
            'type': match.group(4),
            'amount': amount,
            'balance': balance,
            'open_date': match.group(1),
            'due_date': match.group(5) or '',
        })
    return items


def add_summary_loan_supplements(summary: dict, loans: list[dict]) -> None:
    loan_summary = summary.get('loan_summary') or {}
    expected = float(loan_summary.get('non_revolving_balance') or 0) + float(loan_summary.get('revolving_balance') or 0)
    current = sum(item.get('balance', 0) for item in loans if item.get('balance', 0) > 0)
    diff = expected - current
    if diff <= 100:
        return
    monthly_expected = float(loan_summary.get('non_revolving_monthly') or 0) + float(loan_summary.get('revolving_monthly') or 0)
    monthly_current = sum(item.get('monthly_payment', 0) for item in loans if item.get('balance', 0) > 0)
    loans.append({
        'lender': '概要识别补充，需复核明细页',
        'type': '贷款负债补充',
        'guarantee': '未识别',
        'limit': 0,
        'balance': diff,
        'remaining_terms': '',
        'monthly_payment': max(0, monthly_expected - monthly_current),
    })


def account_blocks(lines, start_pat):
    starts = [i for i, line in enumerate(lines) if re.search(start_pat, line)]
    for n, start in enumerate(starts):
        end = starts[n+1] if n+1 < len(starts) else len(lines)
        yield lines[start:end]


def extract_personal_lender(block: list[str]) -> str:
    stop = len(block)
    for i, line in enumerate(block):
        if '业务种类' in line:
            stop = i
            break
    head = block[:stop]
    pieces = []
    label_pat = re.compile(r'账户|管理机构|标识|开立日期|到期日期|借款金额|账户币种|人民币元|第\d+页')
    def useful_org_piece(item: str) -> bool:
        if not item or label_pat.search(item):
            return False
        if is_money_line(item) or re.match(r'20\d{2}[.,-]\d{2}', item) or re.fullmatch(r'[A-Za-z0-9-]{5,}', item):
            return False
        return bool(re.search(r'银行|公司|金融|金限|信托|小额|消费|股份|有限|支行|分行|租赁|农商|邮政|农业|光大|中信|渤海|浦东|奇瑞|奇助|中原|财付通|蚂蚁|经济贸易', item))

    for idx, line in enumerate(head):
        item = line.strip(' ：:，,（）()')
        if useful_org_piece(item):
            prev_item = head[idx - 1].strip(' ：:，,（）()') if idx > 0 else ''
            if prev_item and useful_org_piece(prev_item) and prev_item not in pieces:
                pieces.append(prev_item)
            pieces.append(item)
            next_item = head[idx + 1].strip(' ：:，,（）()') if idx + 1 < len(head) else ''
            if next_item and useful_org_piece(next_item):
                pieces.append(next_item)
    lender = normalize_org_name(''.join(pieces[:5]))
    block_text = '\n'.join(block)
    if (
        lender in {'', '未识别', '银行股份有限公司', '股份有限公司'}
        and '广东顺德农村商业' in block_text
        and '银行股份有限公司' in block_text
    ):
        return '广东顺德农村商业银行股份有限公司'
    if '重庆妈' in block_text or '重庆蚂' in block_text or 'huabei' in block_text:
        return '重庆蚂蚁消费金融有限公司'
    if '佛山农村商业银行' in block_text:
        return '佛山农村商业银行股份有限公司'
    if '重庆度小' in block_text:
        return '重庆度小满小额贷款有限公司'
    if '重庆携程' in block_text:
        return '重庆携程小额贷款有限公司'
    return lender or '未识别'


def parse_balance_fields(block: list[str]) -> tuple[float, str, float]:
    balance = 0
    remaining = ''
    monthly = 0
    # Rebuilt OCR table rows preserve the column order better than the raw
    # vertical labels on photographed reports.
    for i, line in enumerate(block):
        if '账户状态' not in line or '余额' not in line or '本月应还款' not in line:
            continue
        for row in block[i + 1:i + 5]:
            if not re.search(r'正常|关注|次级|可疑|损失', row):
                continue
            prefix = re.split(r'20[0-9G]{2}[.,-]', row, maxsplit=1)[0]
            prefix = re.sub(r'(?<![A-Za-z])F(?=\d)', '', prefix)
            vals = [money(token) for token in re.findall(r'\d[\d,]*(?:\.\d+)?', prefix)]
            if vals:
                balance = vals[0]
                if len(vals) > 1 and 0 <= vals[1] <= 600:
                    remaining = str(int(vals[1]))
                if len(vals) > 2:
                    monthly = vals[2]
                return balance, remaining, monthly
    status_words = {'正常', '关注', '次级', '可疑', '损失', '结清', '销户', '正'}
    balance_labels = {'余额', '余颜', '余顺', '余颇', '余额）', '余质', '余颂'}
    for i, line in enumerate(block):
        if line in balance_labels:
            vals = []
            for item in block[i + 1:i + 22]:
                if item in status_words or '本月实还款' in item:
                    continue
                if re.search(r'\d', item) and not re.match(r'20\d{2}', item) and '逾期' not in item:
                    val = money(item)
                    vals.append(val)
                if len(vals) >= 3:
                    break
            if vals:
                balance = vals[0]
                if len(vals) > 1 and 0 <= vals[1] <= 600:
                    remaining = str(int(vals[1]))
                if len(vals) > 2:
                    monthly = vals[2]
                break
    return balance, remaining, monthly


OVERDUE_LEVEL_LABELS = {
    1: '逾期1-30天',
    2: '逾期31-60天',
    3: '逾期61-90天',
    4: '逾期91-120天',
    5: '逾期121-150天',
    6: '逾期151-180天',
    7: '逾期180天以上',
}


def parse_current_overdue(block: list[str]) -> tuple[int, float]:
    """Read current overdue periods/amount from a reconstructed horizontal row."""
    for i, header in enumerate(block):
        if '当前逾期期数' not in header or '当前逾期总额' not in header:
            continue
        for row in block[i + 1:i + 6]:
            if not re.search(r'\d', row) or '逾期' in row or re.match(r'20\d{2}', row):
                continue
            header_cells = header.split()
            row_cells = row.split()
            if len(header_cells) >= 2 and len(row_cells) >= len(header_cells):
                try:
                    periods = int(money(row_cells[header_cells.index('当前逾期期数')]))
                    amount = money(row_cells[header_cells.index('当前逾期总额')])
                    if 0 <= periods <= 120 and 0 <= amount <= 200_000_000:
                        return periods, amount
                except (ValueError, IndexError):
                    pass
            values = [money(token) for token in re.findall(r'\d[\d,]*(?:\.\d+)?', row)]
            if len(values) < 2:
                continue
            periods_pos = header.find('当前逾期期数')
            amount_pos = header.find('当前逾期总额')
            if periods_pos < amount_pos:
                periods, amount = int(values[0]), values[1]
            else:
                amount, periods = values[0], int(values[1])
            if 0 <= periods <= 120 and 0 <= amount <= 200_000_000:
                return periods, amount
    return 0, 0


def parse_repayment_overdue_events(block: list[str]) -> list[dict]:
    """Convert numeric repayment-status rows into dated overdue events."""
    events = []
    seen = set()
    for line in block:
        match = re.match(r'^(20\d{2})\s+(.+)$', line.strip())
        if not match:
            continue
        year = int(match.group(1))
        tokens = re.findall(r'(?<![A-Za-z0-9])(?:[1-7]|N|C|G|D|Z|B|M|\*|0)(?![A-Za-z0-9])', match.group(2).upper())
        if not tokens or len(tokens) > 12 or not any(token in {'N', 'C', 'G', 'D', 'Z', 'B', 'M', '*'} for token in tokens):
            continue
        for month, token in enumerate(tokens, start=1):
            if token not in {'1', '2', '3', '4', '5', '6', '7'}:
                continue
            key = (year, month, token)
            if key in seen:
                continue
            seen.add(key)
            level = int(token)
            events.append({
                'month': f'{year:04d}-{month:02d}',
                'level': level,
                'status': OVERDUE_LEVEL_LABELS[level],
                'amount': 0,
                'current': False,
            })
    return events


def parse_overdue_fields(block: list[str]) -> dict:
    periods, amount = parse_current_overdue(block)
    events = parse_repayment_overdue_events(block)
    as_of = ''
    block_text = '\n'.join(block)
    match = re.search(r'截至\s*(20\d{2})[年.\-/]?(\d{2})[月.\-/]?(\d{2})?', block_text)
    if match:
        as_of = f'{match.group(1)}-{match.group(2)}'
    if periods > 0 or amount > 0:
        events.append({
            'month': as_of or '报告基准月',
            'level': min(7, max(1, periods)) if periods else 0,
            'status': f'当前逾期{periods}期' if periods else '当前存在逾期',
            'amount': amount,
            'current': True,
        })
    return {
        'current_overdue_periods': periods,
        'current_overdue_amount': amount,
        'overdue_events': events,
        'has_overdue': bool(events),
    }


def parse_loan_accounts(lines):
    loans = []
    for block in account_blocks(lines, r'^账户(?:\d+|（|$)'):
        text = '\n'.join(block)
        if '主业务借款人' in text or '责任人类型' in text or '还款责任金额' in text:
            continue
        if '发卡机构' in text or '贷记卡' in text:
            continue
        if not ('循环贷款账户' in text or '循环贷账户' in text or '账户授信' in text or '账户授值' in text or '账户板伯' in text or '账户投信' in text):
            # Closed non-revolving loans are noisy in OCR and do not affect current debt.
            if '结清' in text or '结消' in text or '结沛' in text:
                continue
        if not any(k in text for k in ['借款金额', '账户授信额度', '贷款', '个人消费']):
            continue
        lender = extract_personal_lender(block)
        type_ = (
            '个人住房商业贷款' if '个人住房商业贷款' in text else
            '个人经营性贷款' if '个人经营性贷款' in text else
            '个人汽车消费贷款' if '个人汽车消费贷款' in text else
            '个人消费贷款' if '消费贷款' in text or '个人消费' in text else
            '其他贷款' if '其他贷款' in text else '贷款'
        )
        guarantee = '信用/无担保' if '信用/无担保' in text or '你用/无担保' in text else ('组合' if '组合' in text else '')
        limit = 0
        for i, line in enumerate(block):
            if re.search(r'账户.*(授信|授值|投信|板伯).*度|借款金额', line):
                vals = []
                for item in block[i+1:i+16]:
                    val = money(item)
                    if val and val <= 5_000_000 and not re.match(r'20\d{2}', item):
                        vals.append(val)
                    if '人民币元' in item:
                        break
                if vals:
                    limit = vals[-1]
        balance, remaining, monthly = parse_balance_fields(block)
        if balance > 0 or (limit and '正常' in text and '结清' not in text and '结消' not in text):
            overdue = parse_overdue_fields(block)
            loans.append({
                'lender': lender or '未识别',
                'type': type_,
                'guarantee': guarantee or '未识别',
                'limit': limit,
                'balance': balance,
                'remaining_terms': remaining,
                'monthly_payment': monthly,
                **overdue,
            })
    return loans


def parse_inquiry_detail(lines, report_date):
    items = []
    in_detail = False
    for i, line in enumerate(lines):
        if '机构查询记录明细' in line or '查询记录' in line:
            in_detail = True
            continue
        if '本人查询记录明细' in line:
            break
        if not in_detail:
            continue
        m = re.search(r'20\d{2}[.,:年-]\d{2}[.,月/-]\d{2}', line)
        if not m:
            continue
        d = m.group(0)
        snippet_lines = [line]
        for following in lines[i + 1:i + 7]:
            if re.search(r'20\d{2}[.,:年-]\d{2}[.,月/-]\d{2}', following):
                break
            snippet_lines.append(following)
        snippet = '\n'.join(snippet_lines)
        normalized = clean(snippet)
        reason = ''
        if re.search(r'信用卡.*(审批|申批|中批)', normalized):
            reason = '信用卡审批'
        elif re.search(r'贷款.*(审批|申批|中批|审此|市批)', normalized):
            reason = '贷款审批'
        if reason:
            date = re.sub(r'[.,:年月/]', '-', d).replace('日', '')
            items.append({'date': date, 'reason': reason})
    return items


def looks_like_org(line: str) -> bool:
    if not line or re.search(r'^\d+$|^20\d{2}', line):
        return False
    if any(token in line for token in ['证件', '号码', '币种', '日期', '余额', '分类', '逾期', '合同编号', '业务种类', '责任人类型']):
        return False
    return bool(re.search(r'银行|公司|金融|租赁|小额|股份|支行|分行|有限|中心|农商', line))


def compact_org(parts: list[str]) -> str:
    text = ''.join(part.strip(' ：:，,（）()') for part in parts if part.strip())
    text = re.sub(r'[^\u4e00-\u9fffA-Za-z0-9（）()]+', '', text)
    text = text.replace('（备用)', '').replace('（备', '')
    return text[:80]


def is_main_borrower_label(line: str) -> bool:
    normalized = clean(line or '')
    return bool(re.search(r'主业务.{0,3}借款人', normalized)) or bool(
        re.search(r'主业务.{0,3}(?:款人|贷人|借人)', line or '')
    )


def normalize_enterprise_lender(lender: str, window: list[str] | None = None) -> str:
    text = (lender or '').strip(' ：:，,（）()用')
    joined = ''.join(window or [])
    combined = text + joined
    text_only = text
    if '中国邮政储蓄银行' in text_only and '佛山' in combined:
        return '中国邮政储蓄银行股份有限公司佛山市分行'
    if '中国银行' in text_only and '顺德容桂' in combined:
        return '中国银行股份有限公司顺德容桂支行'
    if '中国工商银行' in text_only and '佛山' in combined and '容桂' in combined:
        return '中国工商银行股份有限公司佛山容桂支行'
    if '中国建设银行' in text_only and '广东' in combined:
        return '中国建设银行股份有限公司广东省分行'
    if '深圳前海微众' in text_only or '微众银行' in text_only:
        return '深圳前海微众银行股份有限公司'
    if '民生金融租赁' in text_only:
        return '民生金融租赁股份有限公司'
    if '仲信国际' in combined and '租赁' in combined:
        return '仲信国际融资租赁有限公司'
    if '中航信托' in text_only:
        return '中航信托股份有限公司'
    common = [
        '中国邮政储蓄银行股份有限公司佛山市分行',
        '中国银行股份有限公司顺德容桂支行',
        '中国工商银行股份有限公司佛山容桂支行',
        '中国建设银行股份有限公司广东省分行',
        '民生金融租赁股份有限公司',
        '仲信国际融资租赁有限公司',
        '中航信托股份有限公司',
        '天津金城银行股份有限公司',
        '中国银行股份有限公司佛山分行',
        '中国银行股份有限公司顺德北滘支行',
        '中信银行股份有限公司佛山三水支行',
        '上海浦东发展银行股份有限公司佛山禅城支行',
        '中国建设银行股份有限公司顺德分行',
        '中国农业银行股份有限公司',
        '深圳前海微众银行股份有限公司',
        '佛山农村商业银行股份有限公司',
        '中国人民财产保险股份有限公司',
        '远东宏信普惠融资租赁有限公司',
        '广东顺德农村商业银行股份有限公司',
        '广东南海农村商业银行股份有限公司',
        '思享驾融资租赁（上海）有限公司',
    ]
    for name in common:
        if name in combined:
            return name
    if '中国银行股份有' in combined and '佛山分行' in combined:
        return '中国银行股份有限公司佛山分行'
    if text.startswith('限公司') and '佛山分行' in text:
        return '中国银行股份有限公司佛山分行'
    if '中信银行' in combined and '佛山' in combined and '三水支行' in combined:
        return '中信银行股份有限公司佛山三水支行'
    if '上海浦东发展银行' in combined and '佛山' in combined and '禅城支行' in combined:
        return '上海浦东发展银行股份有限公司佛山禅城支行'
    if '中国建设银行' in combined and '顺德' in combined:
        return '中国建设银行股份有限公司顺德分行'
    if '广东顺德农村商业银行' in combined:
        return '广东顺德农村商业银行股份有限公司'
    if '广东南海农村商业' in combined:
        return '广东南海农村商业银行股份有限公司'
    if '佛山农村商业银行' in combined:
        return '佛山农村商业银行股份有限公司'
    if '中国农业银行' in combined:
        return '中国农业银行股份有限公司'
    if '微众银行' in combined:
        return '深圳前海微众银行股份有限公司'
    if '人民财产保险' in combined:
        return '中国人民财产保险股份有限公司'
    if '远东宏信' in combined:
        return '远东宏信普惠融资租赁有限公司'
    if text.endswith('股份有限'):
        for item in window or []:
            if item.startswith('公司'):
                return compact_org([text, item])
    return normalize_org_name(text) or '未识别'


def lender_quality(name: str) -> int:
    text = name or ''
    score = len(text)
    if any(k in text for k in ['银行', '公司', '租赁', '保险', '信托']):
        score += 30
    if any(k in text for k in ['股份有限公司', '有限公司', '分行', '支行']):
        score += 20
    if text in {'未识别', '概要补充'} or text.startswith('公司') or text.startswith('银行'):
        score -= 50
    return score


def dedupe_personal_loans(items: list[dict]) -> list[dict]:
    dedup: dict[tuple, dict] = {}
    for item in items:
        key = (item.get('type') or '', round(float(item.get('limit') or 0), 2), round(float(item.get('balance') or 0), 2))
        old = dedup.get(key)
        if not old or lender_quality(item.get('lender') or '') > lender_quality(old.get('lender') or ''):
            dedup[key] = item
    return list(dedup.values())


def dedupe_simple_cards(items: list[dict]) -> list[dict]:
    dedup: dict[tuple, dict] = {}
    for item in items:
        lender = normalize_org_name((item.get('lender') or '').replace('信用中心', '信用卡中心'))
        normalized = {**item, 'lender': lender or item.get('lender') or '未识别'}
        key = (round(float(normalized.get('limit') or 0), 2), round(float(normalized.get('used') or 0), 2))
        old = dedup.get(key)
        if not old or lender_quality(normalized.get('lender') or '') > lender_quality(old.get('lender') or ''):
            dedup[key] = normalized
    return list(dedup.values())


def enterprise_loan_quality(item: dict) -> int:
    score = lender_quality(item.get('lender') or '')
    if item.get('guarantee') in {'信用/无担保', '组合', '保证/保证金', '保证', '抵押', '质押'}:
        score += 20
    if item.get('classification') in {'正常', '关注', '次级', '可疑', '损失', '未分类'}:
        score += 20
    amount = float(item.get('amount') or 0)
    balance = float(item.get('balance') or 0)
    if amount and 0 <= balance <= amount * 1.05:
        score += 30
    if amount and balance > amount * 1.2:
        score -= 200
    if item.get('classification') == '正常' and float(item.get('overdue_total') or 0) > 0:
        score -= 80
    if float(item.get('overdue_total') or 0) > max(balance, amount, 1):
        score -= 80
    if item.get('open_date') and item.get('due_date') and item['open_date'] > item['due_date']:
        score -= 100
    return score


def is_money_line(line: str) -> bool:
    return bool(re.fullmatch(r'[\d,]+(?:\.\d+)?', (line or '').strip()))


def first_value_after(lines, labels, max_scan=8):
    if isinstance(labels, str):
        labels = [labels]
    for i, line in enumerate(lines):
        if any(label in line for label in labels):
            tail = line
            for label in labels:
                tail = tail.replace(label, '')
            tail = tail.strip(' ：:')
            if tail and not any(label in tail for label in labels):
                return tail
            for item in lines[i + 1:i + 1 + max_scan]:
                if item and not any(k in item for k in ['信息来源机构', '第', '页']):
                    return item.strip()
    return ''


def parse_enterprise_identity(lines, text):
    report_date = ''
    m = re.search(r'报告时间[:：]?\s*(20\d{2})[-年](\d{2})[-月](\d{2})', text)
    if m:
        report_date = f'{m.group(1)}-{m.group(2)}-{m.group(3)}'
    company = first_value_after(lines, '企业名称')
    if company.startswith('：'):
        company = company.strip('：: ')
    return {
        'company_name': company,
        'zhongzheng_code': first_value_after(lines, '中征码'),
        'credit_code': first_value_after(lines, '统一社会信用代码'),
        'org_code': first_value_after(lines, '组织机构代码'),
        'report_date': report_date,
        'legal_representative': '',
        'actual_controller': '',
        'registered_capital': '',
        'enterprise_scale': '',
        'industry': '',
    }


def parse_enterprise_basic(lines, identity):
    name_blacklist = {
        '职位', '姓名', '证件类型', '证件号码', '名称', '身份标识类型', '身份标识号码',
        '未结清信贷', '账户编', '信贷记录明细', '信息来源机构'
    }
    def nearby_name(start):
        for item in lines[start:start + 10]:
            m = re.search(r'(?:人\s*)?([\u4e00-\u9fff]{2,5})\s*身份证', item)
            if m and m.group(1) not in name_blacklist:
                return m.group(1)
            if re.fullmatch(r'[\u4e00-\u9fff]{2,5}', item) and item not in name_blacklist:
                return item
        return ''

    for i, line in enumerate(lines):
        if '法定代表人' in line:
            identity['legal_representative'] = nearby_name(i + 1) or identity['legal_representative']
        if '实际控制人' in line:
            identity['actual_controller'] = nearby_name(i + 1) or identity['actual_controller']
        if '注册资本折人民币合计' in line:
            m = re.search(r'注册资本折人民币合计\s*([\d,.]+万元?)', line)
            identity['registered_capital'] = m.group(1) if m else line_after(lines, i, 4)
        if line == '企业规模':
            identity['enterprise_scale'] = line_after(lines, i, 4)
        elif line.startswith('企业规模 '):
            identity['enterprise_scale'] = re.split(r'信息来源机构', line[len('企业规模 '):], maxsplit=1)[0].strip()
        if line == '所属行业':
            identity['industry'] = line_after(lines, i, 4)
        elif line.startswith('所属行业 '):
            identity['industry'] = re.split(r'信息来源机构', line[len('所属行业 '):], maxsplit=1)[0].strip()


def numbers_near(lines, start, limit=20):
    vals = []
    for item in lines[start:start + limit]:
        if is_money_line(item):
            vals.append(money(item))
        else:
            vals.extend(float(x.replace(',', '')) for x in re.findall(r'(?<![A-Za-z])\d+(?:,\d{3})*(?:\.\d+)?(?![A-Za-z])', item))
    return vals


def parse_enterprise_summary(lines):
    summary = {
        'loan_balance': 0,
        'guarantee_balance': 0,
        'attention_balance': 0,
        'npl_balance': 0,
        'overdue_principal': 0,
        'overdue_interest': 0,
        'overdue_total': 0,
        'non_revolving_limit': 0,
        'non_revolving_used': 0,
        'non_revolving_remaining': 0,
        'revolving_limit': 0,
        'revolving_used': 0,
        'revolving_remaining': 0,
        'current_loan_accounts': 0,
    }
    for i, line in enumerate(lines):
        if '借贷交易' in line and '担保交易' in '\n'.join(lines[i:i + 6]):
            vals = numbers_near(lines, i, 14)
            if len(vals) >= 2:
                summary['loan_balance'] = vals[0]
                summary['guarantee_balance'] = vals[1]
        if i < 180 and '本金' in line and '利息' in line and '总额' in line:
            vals = []
            for item in lines[i + 1:i + 8]:
                if '正常类' in item or '账户数' in item:
                    break
                vals.extend(money(x) for x in re.findall(r'\d+(?:\.\d+)?', item.replace(',', '')))
            if len(vals) >= 3:
                summary['overdue_principal'], summary['overdue_interest'], summary['overdue_total'] = vals[-3:]
        if '非循环信用额度' in line and '循环信用额度' in '\n'.join(lines[i:i + 4]):
            vals = numbers_near(lines, i, 18)
            if len(vals) >= 6:
                summary['non_revolving_limit'], summary['non_revolving_used'], summary['non_revolving_remaining'] = vals[:3]
                summary['revolving_limit'], summary['revolving_used'], summary['revolving_remaining'] = vals[3:6]
        if re.match(r'^(短期借款|中长期借款|循环透支)\s+', line):
            vals = numbers_near([line], 0, 1)
            if len(vals) >= 8:
                count = int(vals[-2])
                if count > 0:
                    summary['current_loan_accounts'] += count
    return summary


ENTERPRISE_LOAN_TYPES = ['流动资金贷款', '融资型租赁', '固定资产贷款', '贸易融资', '票据贴现', '保理', '透支', '融资租赁', '其他贷款']
ENTERPRISE_GUARANTEE_TYPES = ['银行承兑汇票', '贷款保证保险', '银行保函', '信用证', '融资担保']


def enterprise_lender_from_window(window: list[str], type_idx: int) -> str:
    parts = []
    label_pat = re.compile(r'授信机构|业务种类|开立日期|到期日|币种|借款金额|发放形式|账户|担保方式|余额|五级分类|逾期|还款|历史表现|信息报告|特定交易|形式|编号|号$')
    code_pat = re.compile(r'^[A-Z]?\d{3,}[A-Za-z0-9-]*$')
    guarantee_pat = re.compile(r'^(信用/无担保|组合|保证|抵押|质押|保证/保证金|保证/抵押)')

    def usable(item: str, after_type: bool = False) -> bool:
        if not item or label_pat.search(item):
            return False
        if is_money_line(item) or code_pat.match(item) or re.match(r'20\d{2}-\d{2}-\d{2}', item):
            return False
        if item in {'人民币元', '新增', '收回再贷', '无还本续贷', '其他', '正常', '关注', '未分类', '-', '一', '二', '”', '←'}:
            return False
        if re.search(r'银行|公司|租赁|信托|保险|股份|有限|分行|支行|农商|邮政|工商|建设|微众|民生|中航|金城|佛山|广东|容桂|市分行|省分行', item):
            return True
        return after_type and re.search(r'^(市分行|省分行|股份有限公司|有限公司|公司.{0,8}(?:分行|支行)|[\\u4e00-\\u9fff]{1,8}支行)$', item)

    for item in window[max(0, type_idx - 10):type_idx]:
        if usable(item):
            parts.append(item)
    for item in window[type_idx + 1:min(len(window), type_idx + 14)]:
        if guarantee_pat.search(item):
            break
        if usable(item, after_type=True):
            parts.append(item)
    return normalize_enterprise_lender(compact_org(parts), window)


def enterprise_native_lender(lines: list[str], type_index: int, inline_prefix: str = '') -> str:
    """Rebuild an institution name split across two or three native PDF lines."""
    pieces = []
    prefix = inline_prefix.strip(' ：:，,')
    if prefix and re.search(r'银行|公司|租赁|保险|信托|股份|有限|分行|支行', prefix):
        pieces.append(prefix)
    for pos in range(type_index - 1, max(-1, type_index - 5), -1):
        candidate = lines[pos].strip(' ：:，,')
        if not candidate or re.search(r'第\s*\d+\s*页|授信机构|业务种类|账户编|人民币元|20\d{2}-\d{2}-\d{2}', candidate):
            continue
        if re.fullmatch(r'[A-Za-z0-9-]+', candidate) or is_money_line(candidate):
            continue
        if re.search(r'银行|公司|租赁|保险|信托|商业|股份|有限|分行|支行|金融', candidate):
            pieces.insert(0, candidate)
            if re.search(r'^(?:中国|广东|平安|永赢|浙商|华晨|海通|民生|天津|佛山)', candidate):
                break
    return normalize_enterprise_lender(compact_org(pieces), lines[max(0, type_index - 4):type_index + 5])


def parse_enterprise_native_current_loans(section_lines: list[str]) -> list[dict]:
    """Parse the stable multi-row table used by current PBOC enterprise reports."""
    loans = []
    type_pat = '|'.join(map(re.escape, ENTERPRISE_LOAN_TYPES))
    row_pattern = re.compile(
        rf'^(?P<prefix>.*?)\s*(?P<type>{type_pat})\s*'
        r'(?P<open>20\d{2}-\d{2}-\d{2})\s*(?P<due>20\d{2}-\d{2}-\d{2})\s*'
        r'人民币元\s*(?P<amount>[\d,.]+)'
    )
    repayment_pattern = re.compile(
        r'^(?P<guarantee>信用/无担保|组合|保证/保证金|保证/抵押|抵押/质押|保证|信用|抵押|质押)\s*'
        r'(?P<balance>[\d,.]+)\s*(?P<classification>正常|关注|次级|可疑|损失|不良|未分类|违约)\s*'
        r'(?P<overdue_total>[\d,.]+)\s*(?P<overdue_principal>[\d,.]+)\s*(?P<overdue_months>\d+)\s*'
        r'(?P<last_payment>20\d{2}-\d{2}-\d{2})'
    )
    for i, line in enumerate(section_lines):
        match = row_pattern.search(line)
        if not match:
            continue
        repayment = None
        for candidate in section_lines[i + 1:i + 6]:
            repayment = repayment_pattern.search(candidate)
            if repayment:
                break
        if not repayment:
            continue
        classification = repayment.group('classification')
        loans.append({
            '_native_table': True,
            'lender': enterprise_native_lender(section_lines, i, match.group('prefix')),
            'type': match.group('type'),
            'open_date': match.group('open'),
            'due_date': match.group('due'),
            'amount': money(match.group('amount')),
            'guarantee': repayment.group('guarantee'),
            'balance': money(repayment.group('balance')),
            'classification': classification,
            'overdue_total': money(repayment.group('overdue_total')),
            'overdue_principal': money(repayment.group('overdue_principal')),
            'overdue_months': repayment.group('overdue_months'),
            'last_payment_date': repayment.group('last_payment'),
        })
    return loans


def parse_enterprise_current_loans(lines):
    text = '\n'.join(lines)
    detail_start = text.find('信贷记录明细')
    start = text.find('未结清信贷', detail_start if detail_start >= 0 else 0)
    # A page heading for the next section can be extracted before the final
    # rows of the current-loan table. The real boundary is the credit-line table.
    end_candidates = [pos for pos in [text.find('授信信息', start if start >= 0 else 0)] if pos > start]
    end = min(end_candidates) if end_candidates else -1
    if start < 0:
        return []
    section = text[start:end if end > start else len(text)]
    section_lines = [x.strip() for x in section.splitlines() if x.strip()]
    loans = []
    type_pat = '|'.join(map(re.escape, ENTERPRISE_LOAN_TYPES))
    class_pat = r'(正常|关注|次级|可疑|损失|不良|未分类|违约)'
    guarantee_pat = r'(组合|保证/保证金|保证/抵押|抵押/质押|保证|信用/无担保|信用|抵押|质押)'

    compact = re.sub(r'\s+', ' ', section)
    loans.extend(parse_enterprise_native_current_loans(section_lines))
    pattern = re.compile(
        rf'([\u4e00-\u9fff（）()A-Za-z]+(?:银行|公司)[\u4e00-\u9fff（）()A-Za-z]{{0,30}})\s+({type_pat})\s*'
        rf'(20\d{{2}}-\d{{2}}-\d{{2}})\s*(20\d{{2}}-\d{{2}}-\d{{2}})\s*人民币元\s*([\d,.]+).*?'
        rf'{guarantee_pat}\s*([\d,.]+)\s*{class_pat}\s*([\d,.]+)\s*([\d,.]+)\s*(\d+)\s*(20\d{{2}}-\d{{2}}-\d{{2}})',
        re.S
    )
    for m in pattern.finditer(compact):
        loans.append({
            'lender': normalize_enterprise_lender(compact_org([m.group(1)]), [m.group(0)]),
            'type': m.group(2),
            'open_date': m.group(3),
            'due_date': m.group(4),
            'amount': money(m.group(5)),
            'guarantee': m.group(6),
            'balance': money(m.group(7)),
            'classification': m.group(8),
            'overdue_total': money(m.group(9)),
            'overdue_principal': money(m.group(10)),
            'overdue_months': m.group(11),
            'last_payment_date': m.group(12),
        })

    # OCR scan fallback: business type may be separated from lender and numbers by line breaks.
    type_positions = []
    for i, line in enumerate(section_lines):
        matched_type = next((t for t in ENTERPRISE_LOAN_TYPES if t in line and '业务种类' not in line), '')
        if matched_type:
            type_positions.append((i, matched_type))

    for n, (i, matched_type) in enumerate(type_positions):
        block_start = max(0, i - 10)
        block_end = type_positions[n + 1][0] if n + 1 < len(type_positions) else min(len(section_lines), i + 34)
        window = section_lines[block_start:block_end]
        joined = ' '.join(window)
        if not matched_type:
            continue
        local_type_idx = i - block_start
        lender = enterprise_lender_from_window(window, local_type_idx)
        before_type, after_type = joined.split(matched_type, 1)
        if not lender or lender == '未识别':
            lender_match = re.search(r'([\u4e00-\u9fff（）()\s]{2,100}(?:银行|公司)[\u4e00-\u9fff（）()\s]{0,30})\s*$', before_type)
            if lender_match:
                lender = compact_org([lender_match.group(1)])
        if not lender or lender == '未识别':
            parts = []
            for candidate in window[:12]:
                if candidate == matched_type or re.search(r'20\d{2}-\d{2}-\d{2}|人民币元|新增|其他|正常还款|见附件', candidate):
                    continue
                if candidate in {'组合', '保证', '信用/无担保', '信用', '正常', '关注'} or is_money_line(candidate):
                    continue
                if re.search(r'银行|公司|商业|股份|有限|分行|支行', candidate):
                    parts.append(candidate)
            lender = compact_org(parts[:3])
        lender = normalize_enterprise_lender(lender, window)
        dates = [x.replace(':', '-') for x in re.findall(r'20\d{2}[-:]\d{2}[-:]\d{2}', after_type)]
        amount_match = re.search(r'人民币元\s*([\d,.]+)', after_type)
        guarantee_match = re.search(r'(信用/无担保|组合|保证/保证金|保证/抵押|抵押/质押|保证|信用|抵押|质押)\s*([\d,.]+)\s*(正常|关注|次级|可疑|损失|未分类)(?:\s*([\d,.]+)\s*([\d,.]+)\s*(\d+))?', after_type)
        if len(dates) >= 2 and amount_match and guarantee_match:
            amount = money(amount_match.group(1))
            guarantee = guarantee_match.group(1)
            balance = money(guarantee_match.group(2))
            classification = guarantee_match.group(3)
            overdue_total = money(guarantee_match.group(4) or 0)
            overdue_principal = money(guarantee_match.group(5) or 0)
            overdue_months = guarantee_match.group(6) or ''
            if overdue_total > max(amount, balance, 1000):
                overdue_total = 0
                overdue_principal = 0
                overdue_months = ''
            if classification == '正常' and overdue_total == 0:
                overdue_principal = 0
                overdue_months = '0'
            loans.append({
                'lender': lender or '未识别',
                'type': matched_type,
                'open_date': dates[0],
                'due_date': dates[1],
                'amount': amount,
                'guarantee': guarantee or '未识别',
                'balance': balance,
                'classification': classification or '未识别',
                'overdue_total': overdue_total,
                'overdue_principal': overdue_principal,
                'overdue_months': overdue_months,
                'last_payment_date': dates[2] if len(dates) > 2 else '',
            })
    dedup = {}
    for item in loans:
        key = (item['type'], item['open_date'], item.get('due_date', ''), item['amount'])
        old = dedup.get(key)
        if not old or (not old.get('_native_table') and enterprise_loan_quality(item) > enterprise_loan_quality(old)):
            dedup[key] = item
    result = list(dedup.values())
    for item in result:
        item.pop('_native_table', None)
    return result


def add_enterprise_summary_supplements(summary, loans):
    expected_balance = float(summary.get('loan_balance') or 0)
    current_balance = sum(float(item.get('balance') or 0) for item in loans)
    diff = round(expected_balance - current_balance, 2)
    if diff <= 0.01:
        return
    expected_count = int(summary.get('current_loan_accounts') or 0)
    missing_count = max(1, expected_count - len(loans)) if expected_count else 1
    loans.append({
        'lender': '概要补充',
        'type': f'未识别未结清贷款（约{missing_count}笔）',
        'open_date': '',
        'due_date': '',
        'amount': 0,
        'guarantee': '需复核',
        'balance': diff,
        'classification': '需复核',
        'overdue_total': 0,
        'overdue_principal': 0,
        'overdue_months': '',
        'last_payment_date': '',
    })


def prune_enterprise_overread(summary, loans):
    expected = float(summary.get('loan_balance') or 0)
    if expected <= 0:
        return loans
    generic_lenders = {'未识别', '股份有限公司', '银行股份有限公司', '有限公司', '股份有限'}
    filtered = [
        item for item in loans
        if float(item.get('balance') or 0) >= 0
        and (not float(item.get('amount') or 0) or float(item.get('balance') or 0) <= float(item.get('amount') or 0) * 1.2)
        and (item.get('lender') or '') not in generic_lenders
        and not (item.get('lender') or '').startswith('有限公司')
    ]

    def suspicious_score(item):
        score = 0
        lender = item.get('lender') or ''
        if lender in {'未识别', '股份有限公司', '银行股份有限公司'} or lender.startswith('有限公司'):
            score += 80
        if len(lender) < 8:
            score += 25
        if item.get('open_date') and item.get('due_date') and item['open_date'] > item['due_date']:
            score += 60
        if float(item.get('overdue_principal') or 0) > max(float(item.get('balance') or 0), float(item.get('amount') or 0), 1):
            score += 40
        if item.get('type') not in ENTERPRISE_LOAN_TYPES:
            score += 100
        return score

    total = round(sum(float(item.get('balance') or 0) for item in filtered), 2)
    if total <= expected + 0.01:
        return filtered
    for item in sorted(filtered, key=suspicious_score, reverse=True):
        if total <= expected + 0.01:
            break
        score = suspicious_score(item)
        if score <= 0:
            continue
        filtered.remove(item)
        total = round(total - float(item.get('balance') or 0), 2)
    return filtered


def parse_enterprise_credit_lines(lines):
    text = '\n'.join(lines)
    detail_start = text.find('信贷记录明细')
    start = text.find('授信信息', detail_start if detail_start >= 0 else 0)
    if start < 0:
        return []
    end_candidates = [pos for pos in [text.find('已结清信贷', start), text.find('公共记录', start)] if pos > start]
    end = min(end_candidates) if end_candidates else len(text)
    section = re.sub(r'\s+', ' ', text[start:end])
    pattern = re.compile(
        r'([\u4e00-\u9fff（）()A-Za-z]+?(?:银行|公司|分行|支行))\s*(贷款|综合授信|贸易融资|票据)\s*(是|否)\s*'
        r'(20\d{2}-\d{2}-\d{2})\s*(20\d{2}-\d{2}-\d{2}).*?人民币元\s*([\d,.]+)\s*([\d,.]+)(?:\s*([\d,.]+))?',
        re.S
    )
    lines_out = []
    for m in pattern.finditer(section):
        lines_out.append({
            'lender': normalize_enterprise_lender(compact_org([m.group(1)]), [m.group(0)]),
            'limit_type': m.group(2),
            'revolving': m.group(3),
            'start_date': m.group(4),
            'due_date': m.group(5),
            'limit': money(m.group(6)),
            'used': money(m.group(7)),
            'credit_limit': money(m.group(8) or 0),
        })
    section_lines = [x.strip() for x in text[start:end].splitlines() if x.strip()]
    native_pattern = re.compile(
        r'^(?P<prefix>.*?)\s*(?P<type>贷款|综合授信|贸易融资|票据)\s*'
        r'(?P<revolving>是|否)\s*(?P<start>20\d{2}-\d{2}-\d{2})\s*(?P<due>20\d{2}-\d{2}-\d{2})'
    )
    for i, line in enumerate(section_lines):
        match = native_pattern.search(line)
        if not match:
            continue
        amount_row = next((item for item in section_lines[i + 1:i + 7] if item.startswith('人民币元 ')), '')
        nums = [money(token) for token in re.findall(r'[\d,.]+', amount_row.replace('人民币元', '', 1))]
        if len(nums) < 2:
            continue
        lines_out.append({
            'lender': enterprise_native_lender(section_lines, i, match.group('prefix')),
            'limit_type': match.group('type'),
            'revolving': match.group('revolving'),
            'start_date': match.group('start'),
            'due_date': match.group('due'),
            'limit': nums[0],
            'used': nums[1],
            'credit_limit': nums[2] if len(nums) > 2 else 0,
        })
    for i, line in enumerate(section_lines):
        if line not in {'贷款', '综合授信', '贸易融资', '票据'}:
            continue
        window = section_lines[max(0, i - 8):i + 28]
        joined = ' '.join(window)
        lender = ''
        before_type = joined.split(line)[0]
        lender_match = re.search(r'([\u4e00-\u9fff（）()\s]{2,100}(?:银行|公司)[\u4e00-\u9fff（）()\s]{0,30})\s*$', before_type)
        if lender_match:
            lender = compact_org([lender_match.group(1)])
        else:
            parts = []
            for candidate in window:
                if candidate == line or re.search(r'20\d{2}-\d{2}-\d{2}|人民币元|是|否', candidate) or is_money_line(candidate):
                    continue
                if re.search(r'银行|公司|股份|有限|分行|支行', candidate):
                    parts.append(candidate)
            lender = compact_org(parts[:3])
        lender = normalize_enterprise_lender(lender, window)
        dates = re.findall(r'20\d{2}-\d{2}-\d{2}', '\n'.join(window))
        amount_match = re.search(r'人民币元\s*([\d,.]+)\s*([\d,.]+)?\s*([\d,.]+)?', joined)
        revolving = next((x for x in window if x in {'是', '否'}), '')
        if len(dates) >= 2 and amount_match:
            nums = [money(x) for x in amount_match.groups() if x]
            if len(nums) < 2:
                continue
            lines_out.append({
                'lender': lender or '未识别',
                'limit_type': line,
                'revolving': revolving,
                'start_date': dates[0],
                'due_date': dates[1],
                'limit': nums[0],
                'used': nums[1],
                'credit_limit': nums[2] if len(nums) > 2 else 0,
            })
    dedup = {}
    for item in lines_out:
        key = (item.get('limit_type'), item.get('start_date'), item.get('due_date'), item.get('limit'), item.get('used'))
        old = dedup.get(key)
        if not old or lender_quality(item.get('lender') or '') > lender_quality(old.get('lender') or ''):
            dedup[key] = item
    return list(dedup.values())


def parse_enterprise_off_balance(lines):
    text = '\n'.join(lines)
    items = []
    class_pat = r'(正常|关注|次级|可疑|损失|不良|未分类)'
    type_pat = '|'.join(map(re.escape, ENTERPRISE_GUARANTEE_TYPES))
    compact = re.sub(r'\s+', ' ', text)
    pattern = re.compile(rf'([\u4e00-\u9fff（）()A-Za-z]+?(?:银行|公司|分行|支行))\s*({type_pat})\s*{class_pat}\s*(\d+)\s*([\d,.]+|是|否|香)?')
    for m in pattern.finditer(compact):
        items.append({
            'lender': normalize_enterprise_lender(compact_org([m.group(1)]), [m.group(0)]),
            'type': m.group(2),
            'classification': m.group(3),
            'account_count': int(m.group(4)),
            'balance': money(m.group(5) or 0) if re.search(r'\d', m.group(5) or '') else 0,
        })
    dedup = {}
    for item in items:
        key = (item['lender'], item['type'], item['account_count'], item['balance'])
        dedup[key] = item
    return list(dedup.values())


def parse_enterprise(path, raw, normalized, lines):
    identity = parse_enterprise_identity(lines, normalized)
    parse_enterprise_basic(lines, identity)
    summary = parse_enterprise_summary(lines)
    loans = parse_enterprise_current_loans(lines)
    loans = prune_enterprise_overread(summary, loans)
    add_enterprise_summary_supplements(summary, loans)
    credit_lines = parse_enterprise_credit_lines(lines)
    off_balance = parse_enterprise_off_balance(lines)
    if loans and not summary['loan_balance']:
        summary['loan_balance'] = sum(item.get('balance', 0) for item in loans)
    if off_balance and not summary['guarantee_balance']:
        summary['guarantee_balance'] = sum(item.get('balance', 0) for item in off_balance)
    report_type = detect_report_type(normalized)
    return {
        'report_type': report_type,
        'enterprise': {
            'identity': identity,
            'summary': summary,
            'loans': loans,
            'credit_lines': credit_lines,
            'off_balance': off_balance,
            'inquiries': [],
        },
        'summary': {
            'report_date': identity.get('report_date', ''),
            'loan_summary': {},
            'card_summary': {'total_limit': 0, 'used': 0, 'last6_avg_used': 0},
            'guarantee_summary': {'count': len(off_balance), 'guarantee_amount': 0, 'balance': summary.get('guarantee_balance', 0), 'main_borrower': ''},
            'inquiries': {},
        },
        'loans': [],
        'cards': [],
        'guarantees': [],
        'inquiry_detail': [],
        'inquiry_buckets': {k: {'loan': 0, 'card': 0} for k in ['year', 'half_year', 'quarter', 'month']},
        'text_length': len(normalized),
    }


def parse_guarantee_accounts(lines):
    section_starts = [i for i, line in enumerate(lines) if '相关还款责任信息' in line and '汇总' not in line]
    guarantees = []
    for section_start in section_starts:
        section_end = len(lines)
        for j in range(section_start + 1, len(lines)):
            if re.search(r'（[一二三四五六七八九十]）', lines[j]) and '相关还款责任信息' not in lines[j]:
                section_end = j
                break

        section = lines[section_start:section_end]
        starts = [i for i, line in enumerate(section) if re.match(r'^账户\d+', line)]
        if not starts:
            starts = [i for i, line in enumerate(section) if line == '账户']
        if not starts and any(is_main_borrower_label(line) for line in section):
            starts = [0]

        for n, start in enumerate(starts):
            end = starts[n + 1] if n + 1 < len(starts) else len(section)
            block = section[start:end]
            block_text = '\n'.join(block)
            if not any(is_main_borrower_label(line) for line in block) and '保证人' not in block_text and '共同借款人' not in block_text:
                continue

            borrower = ''
            borrower_idx = len(block)
            for i, line in enumerate(block):
                if is_main_borrower_label(line) and '证件' not in line and '号码' not in line:
                    borrower_idx = i
                    for candidate in block[i + 1:i + 14]:
                        if (
                            '证件' in candidate
                            or '号码' in candidate
                            or is_main_borrower_label(candidate)
                            or candidate in {'中征码', '统一社会信用代码'}
                            or re.fullmatch(r'[\dA-Za-z-]{6,}', candidate)
                        ):
                            continue
                        if looks_like_org(candidate):
                            borrower = compact_org([candidate])
                            break
                    break

            lender_parts = []
            for line in block[:borrower_idx]:
                if looks_like_org(line):
                    lender_parts.append(line)
            lender = compact_org(lender_parts[:5])
            if '远东宏' in block_text and ('海）有限公司' in block_text or '海)有限公司' in block_text):
                lender = '远东宏信普惠融资租赁（天津）有限公司'

            responsibility_amount = 0
            for i, line in enumerate(block[:borrower_idx]):
                if line in {'保证人', '共同借款人'}:
                    for candidate in block[i + 1:min(i + 8, borrower_idx)]:
                        if '人民币元' in candidate:
                            break
                        if not is_money_line(candidate) or re.match(r'20\d{2}', candidate):
                            continue
                        value = money(candidate)
                        if 10_000 <= value <= 200_000_000:
                            responsibility_amount = value
                            break
                if responsibility_amount:
                    break
            for i, line in enumerate(block[:borrower_idx]):
                if re.search(r'还款责任金额|责任金额|担保金额', line):
                    for candidate in block[i + 1:min(i + 12, borrower_idx)]:
                        if not is_money_line(candidate):
                            continue
                        value = money(candidate)
                        if 10_000 <= value <= 200_000_000 and not re.match(r'20\d{2}', candidate):
                            responsibility_amount = value
                            break
                if responsibility_amount:
                    break
            if not responsibility_amount:
                values = []
                for idx, item in enumerate(block[:borrower_idx]):
                    val = money(item)
                    prev_next = '\n'.join(block[max(0, idx - 2):min(len(block), idx + 3)])
                    if (
                        is_money_line(item)
                        and 10_000 <= val <= 200_000_000
                        and not re.match(r'20\d{2}', item)
                        and '合同编号' not in prev_next
                    ):
                        values.append(val)
                responsibility_amount = max(values) if values else 0

            balance = 0
            for i, line in enumerate(block):
                if line == '余额':
                    for candidate in block[i + 1:i + 8]:
                        value = money(candidate)
                        if value >= 0 and re.search(r'\d', candidate) and not re.match(r'20\d{2}', candidate):
                            balance = value
                            break
                    break

            if borrower or lender or responsibility_amount or balance:
                guarantees.append({
                    'main_borrower': borrower or '未识别',
                    'lender': lender or '未识别',
                    'guarantee_amount': responsibility_amount,
                    'balance': balance,
                })
    return guarantees


def correct_guarantee_borrowers(lines, guarantees):
    """Use clearer company names elsewhere in the report to repair watermark OCR."""
    financial_words = re.compile(r'银行|金融|保险|担保|证券|信托|小额|租赁|征信')
    first_detail = next(
        (
            i for i, line in enumerate(lines)
            if ('相关还款责任信息' in line and '汇总' not in line) or is_main_borrower_label(line)
        ),
        len(lines),
    )
    candidates = []
    for line in lines[:first_detail]:
        for name in re.findall(r'[\u4e00-\u9fff]{4,32}(?:有限公司|公司)', line):
            name = compact_org([name])
            name = name.replace('佛山市嘉品瑞科技有限公司', '佛山市嘉晶瑞科技有限公司')
            if name not in {'有限公司', '股份有限公司'} and not financial_words.search(name) and name not in candidates:
                candidates.append(name)
    for item in guarantees:
        borrower = item.get('main_borrower') or ''
        if borrower == '未识别' or not candidates:
            continue
        ranked = sorted(
            (
                (SequenceMatcher(None, borrower, candidate).ratio(), candidate)
                for candidate in candidates
                if len(candidate) >= 8
            ),
            reverse=True,
        )
        if ranked and ranked[0][0] >= 0.45:
            item['main_borrower'] = ranked[0][1]


def bucket_inquiries(items, report_date):
    result = {k: {'loan': 0, 'card': 0} for k in ['year','half_year','quarter','month']}
    if not report_date:
        return result
    base = datetime.strptime(report_date, '%Y-%m-%d')
    windows = {'year':365, 'half_year':183, 'quarter':92, 'month':31}
    for it in items:
        try:
            d = datetime.strptime(it['date'][:10], '%Y-%m-%d')
        except Exception:
            continue
        days = (base-d).days
        for key, limit in windows.items():
            if 0 <= days <= limit:
                if it['reason'] == '贷款审批': result[key]['loan'] += 1
                if it['reason'] == '信用卡审批': result[key]['card'] += 1
    return result


def parse(path):
    raw = Path(path).read_text(encoding='utf-8')
    normalized = clean(raw)
    lines = [x.strip() for x in normalized.splitlines() if x.strip()]
    report_type = detect_report_type(normalized)
    if report_type['kind'] == 'enterprise':
        return parse_enterprise(path, raw, normalized, lines)
    summary = parse_summary(lines)
    personal_name = ''
    name_match = re.search(
        r'被查询者姓名[^\n]*\n\s*([一-鿿·]{2,20})\s+(?:身份证|护照|军官证|港澳台)',
        normalized,
    ) or re.search(r'姓名[:：]?\s*([一-鿿·]{2,20})(?=\s*(?:证件|报告|已婚|未婚|$))', normalized)
    if name_match:
        personal_name = name_match.group(1)
    loans = parse_loan_accounts(lines)
    guarantees = parse_guarantee_accounts(lines)
    correct_guarantee_borrowers(lines, guarantees)
    if guarantees:
        borrowers = [item['main_borrower'] for item in guarantees if item.get('main_borrower') and item.get('main_borrower') != '未识别']
        if borrowers:
            summary['guarantee_summary']['main_borrower'] = '、'.join(dict.fromkeys(borrowers))
        if not summary['guarantee_summary'].get('guarantee_amount'):
            summary['guarantee_summary']['guarantee_amount'] = sum(item.get('guarantee_amount', 0) for item in guarantees)
        if not summary['guarantee_summary'].get('balance'):
            summary['guarantee_summary']['balance'] = sum(item.get('balance', 0) for item in guarantees)
        elif len(guarantees) == 1 and guarantees[0].get('balance', 0) < summary['guarantee_summary']['balance'] * 0.2:
            guarantees[0]['balance'] = summary['guarantee_summary']['balance']
    simple_cards = dedupe_simple_cards(parse_simple_cards(normalized))
    if simple_cards and summary['card_summary']['total_limit'] == 0:
        summary['card_summary'] = {
            'total_limit': sum(item['limit'] for item in simple_cards),
            'used': sum(item['used'] for item in simple_cards),
            'last6_avg_used': 0,
        }
    simple_loans = dedupe_personal_loans(parse_simple_loans(normalized))
    other_business = parse_simple_other_business(normalized)
    if simple_loans:
        existing = {(item.get('lender'), item.get('balance'), item.get('limit')) for item in loans}
        for item in simple_loans:
            key = (item.get('lender'), item.get('balance'), item.get('limit'))
            if key not in existing:
                loans.append(item)
                existing.add(key)
    add_summary_loan_supplements(summary, loans)
    inquiries_detail = parse_inquiry_detail(lines, summary['report_date'])
    return {
        'report_type': report_type,
        'identity': {'name': personal_name},
        'summary': summary,
        'loans': loans,
        'cards': simple_cards,
        'other_business': other_business,
        'guarantees': guarantees,
        'inquiry_detail': inquiries_detail,
        'inquiry_buckets': bucket_inquiries(inquiries_detail, summary['report_date']),
        'text_length': len(normalized),
    }

if __name__ == '__main__':
    data = parse(sys.argv[1])
    print(json.dumps(data, ensure_ascii=False, indent=2))
