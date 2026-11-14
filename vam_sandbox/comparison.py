"""Compare user-defined actions under the same hypothetical contract triggers."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Dict, List


ROLES = {
    'tenant': '承租人', 'landlord': '出租人', 'company': '融资方',
    'investor': '投资方', 'other': '其他合同方',
}
OBJECTIVES = {
    'cash': '现金负担', 'liability': '责任上限',
    'timing': '付款灵活性', 'equity': '股权影响',
}
TEMPLATES = {'repurchase': '回购付款', 'lease_exit': '提前退租负担', 'qualitative': '条款与责任'}
TRIGGERS = {'met': '假设计算义务已触发', 'not_met': '假设计算义务未触发', 'unknown': '触发状态待确认'}
PARAMETERS = {
    'repurchase': {
        'principal': '本金（元）',
        'annual_rate': '年利率（%）',
        'years': '自合同约定起算点计的整年数',
        'interest': '计息方式',
        'extra_fee': '其他应付费用（元）',
        'offset': '抵扣金额（元）',
        'cap_mode': '责任上限约定',
        'cap': '责任上限（元）',
        'payment_days': '触发后付款天数',
    },
    'lease_exit': {
        'deposit': '押金（元）',
        'penalty': '违约金（元）',
        'extra_fee': '其他应付费用（元）',
        'deposit_rule': '押金与违约金的关系',
        'cap_mode': '责任上限约定',
        'cap': '责任上限（元）',
        'payment_days': '触发后付款天数',
    },
}
ENUM_LABELS = {
    'simple': '单利', 'compound': '按年复利', 'add': '押金没收与违约金叠加',
    'offset': '没收的押金抵扣违约金', 'refund': '押金退还',
    'none': '确认无上限', 'fixed': '按约定金额封顶',
}
MONEY_QUANTUM = Decimal('0.01')


def _number(value: Any, limit: int, integer: bool = False) -> Decimal | None:
    if value is None or isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        return None
    try:
        number = Decimal(str(value))
        if not number.is_finite() or not 0 <= number <= limit:
            return None
        if integer and number != number.to_integral_value():
            return None
        return number
    except InvalidOperation:
        return None


def calculate(template: str, raw: Dict[str, Any], trigger: str) -> Dict[str, Any]:
    """Apply only confirmed inputs and return a trace of the conditional formula."""
    result = {'amount': None, 'payment_days': None, 'cap': None, 'missing': [], 'formula': ''}
    if template not in PARAMETERS:
        result['missing'] = ['此方案使用条款比较，尚未选择金额模型']
        return result

    if trigger == 'not_met':
        return {**result, 'amount': 0.0, 'formula': '此情景假设该项义务未触发，本项金额为 0。'}
    if trigger != 'met':
        result['missing'] = ['该情景下的义务触发状态']
        return result

    missing: List[str] = result['missing']

    def number(key: str, limit: int = 1_000_000_000_000, integer: bool = False) -> Decimal | None:
        value = _number(raw.get(key), limit, integer)
        if value is None:
            missing.append(PARAMETERS[template][key])
        return value

    def option(key: str, allowed: tuple[str, ...]) -> Any:
        value = raw.get(key)
        if value not in allowed:
            missing.append(PARAMETERS[template][key])
            return None
        return value

    fee = number('extra_fee')
    cap_mode = option('cap_mode', ('none', 'fixed'))
    cap = number('cap') if cap_mode == 'fixed' else None
    result['cap'] = float(cap) if cap is not None else None
    days = _number(raw.get('payment_days'), 36_600, integer=True)
    result['payment_days'] = int(days) if days is not None else None
    if template == 'repurchase':
        principal = number('principal')
        percentage = number('annual_rate', 100)
        years = number('years', 30, integer=True)
        interest = option('interest', ('simple', 'compound'))
        offset = number('offset')
        if not missing:
            rate = percentage / 100
            if interest == 'simple':
                gross = principal * (1 + rate * years)
                expression = f'{principal} × (1 + {percentage}% × {int(years)})'
            else:
                gross = principal * (1 + rate) ** int(years)
                expression = f'{principal} × (1 + {percentage}%) ^ {int(years)}'
            amount = max(Decimal(0), gross + fee - offset)
            expression = f'max(0, {expression} + {fee} − {offset})'
    else:
        deposit = number('deposit')
        penalty = number('penalty')
        rule = option('deposit_rule', ('add', 'offset', 'refund'))
        notice = raw.get('early_exit_applies')
        if notice is not True:
            missing.append('确认当前退租时间、通知/豁免条件已适用这组参数')
        if not missing:
            if rule == 'add':
                amount = deposit + penalty + fee
                expression = f'{deposit} + {penalty} + {fee}'
            elif rule == 'offset':
                amount = max(deposit, penalty) + fee
                expression = f'max({deposit}, {penalty}) + {fee}'
            else:
                amount = penalty + fee
                expression = f'{penalty} + {fee}（押金退还）'

    if missing:
        return result

    if cap is not None:
        amount = min(amount, cap)
        expression = f'min({expression}, {cap})'
    result['amount'] = float(amount.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP))
    result['formula'] = f'{expression} 元'
    return result


def _direction(study: Dict[str, Any]) -> str | None:
    """Amounts represent the named payer's liability, not profit or net cash flow."""
    if study.get('template') == 'repurchase':
        return {'company': 'pay', 'investor': 'receive'}.get(study.get('role'))
    if study.get('template') == 'lease_exit' and study.get('role') == 'tenant':
        return 'pay'
    return None


def _preference(study: Dict[str, Any], trigger: str, cells: List[Dict[str, Any]]) -> Dict[str, Any]:
    preference = {'preferred_action_ids': [], 'reason': ''}
    direction = _direction(study)
    objective = study.get('objective')
    if len(cells) < 2:
        preference['reason'] = '填写至少两个方案后可比较。'
    elif trigger != 'met':
        preference['reason'] = '按此情景查看条件后果。义务触发时才比较该项偏好。'
    elif direction is None:
        preference['reason'] = '当前身份或金额模型无法确定收付口径。请结合条款比较。'
    elif objective == 'cash':
        key = 'amount'
        label = '应付金额最低' if direction == 'pay' else '合同约定应收金额最高'
    elif objective == 'liability' and direction == 'pay':
        key = 'cap'
        label = '明确约定的责任上限最低'
    elif objective == 'timing':
        key = 'payment_days'
        label = '约定付款期限最长' if direction == 'pay' else '约定收款期限最短'
    else:
        preference['reason'] = '当前目标需要结合方案条款人工判断。'
    if preference['reason']:
        return preference

    values = [cell.get(key) for cell in cells]
    if any(value is None for value in values):
        preference['reason'] = '至少一个方案缺少该目标所需的参数，暂不判断偏好。'
        return preference
    pick_max = (key == 'amount' and direction == 'receive') or (key == 'payment_days' and direction == 'pay')
    best = (max if pick_max else min)(values)
    ids = [cell['action_id'] for cell in cells if cell[key] == best]
    preference['preferred_action_ids'] = ids
    preference['reason'] = f'按当前身份和目标，{label}。' if len(ids) == 1 else f'{label}的方案并列。'
    return preference


def build_comparison(study: Dict[str, Any], leaves: list) -> Dict[str, Any]:
    template = study.get('template', 'qualitative')
    actions = study.get('actions', [])
    scenarios = []
    for path, node in leaves:
        trigger = node.get('trigger_override', node.get('trigger', 'unknown'))
        analyzed = node.get('effect_actions', study.get('analyzed_actions', {}))
        cells = [
            {'action_id': action['id'],
             'effect': node.get('action_effects', {}).get(action['id'], '')
             if analyzed.get(action['id']) == [action['label'], action['terms']] else '',
             **calculate(template, action.get('parameters', {}), trigger)}
            for action in actions
        ]
        scenarios.append({
            'leaf_id': node['id'], 'path': path, 'branch': node['branch'], 'trigger': trigger,
            'cells': cells, **_preference(study, trigger, cells),
        })
    peaks = {}
    for action in actions:
        amounts = [cell['amount'] for scenario in scenarios for cell in scenario['cells']
                   if cell['action_id'] == action['id']]
        peaks[action['id']] = max(amounts) if amounts and None not in amounts else None
    return {
        'template': template, 'direction': _direction(study), 'scenarios': scenarios,
        'max_amounts': peaks,
    }
