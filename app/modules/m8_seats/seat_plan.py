"""场馆缩座清退规则。

决策顺序（先撤未付款占位，再拆已收款套票）：
1. 未付款占位（无票码关联或票码未收款）可无争议释放，不产生退款；
2. 仍不足时拆已收款套票在该场的座位，按已发布分账中该票场份额登记待清退票款，不换场；
3. 全部可清退座位移除后仍超容，整单失败，由调用方回退且不得改动座位版本。
"""

from collections import defaultdict


def split_unpaid_paid(holds):
    """未付款占位在前；已收款套票座位在后。已释放的历史占位不参与清退。"""
    unpaid, paid = [], []
    for hold in holds:
        if hold['hold_status'] == 'released':
            continue
        (paid if hold['ticket'] else unpaid).append(hold)
    unpaid.sort(key=lambda item: (item['held_at'], item['hold_id']))
    return unpaid, paid


def plan_show(show, holds, new_capacity, allocations):
    """返回单场清退计划，不修改入参。

    allocations: 已发布分账中 (ticket, show) -> allocated_cents 的映射。
    未付款占位可全部释放；已收款套票座位只有在该票场存在正额已发布分账时才可拆，
    否则不得清退，缺口无法弥合时整单失败、由调用方回退。
    """
    active = [hold for hold in holds if hold['hold_status'] != 'released']
    gap = len(active) - new_capacity
    unpaid, paid = split_unpaid_paid(holds)
    evictions, dues = [], []
    if gap <= 0:
        return {'show': show, 'gap': 0, 'evictions': evictions, 'refund_dues': dues,
                'remaining_seats': sorted(hold['seat_label'] for hold in active), 'feasible': True}
    order = list(unpaid)
    paid_groups = defaultdict(list)
    for hold in paid:
        paid_groups[hold['ticket']].append(hold)
    splittable = []
    for ticket in sorted(paid_groups):
        seats = sorted(paid_groups[ticket], key=lambda item: (item['held_at'], item['hold_id']))
        if allocations.get((ticket, show), 0) > 0:
            splittable.extend(seats)
    order.extend(splittable)
    if len(order) < gap:
        return {'show': show, 'gap': gap, 'evictions': evictions, 'refund_dues': dues,
                'remaining_seats': sorted(hold['seat_label'] for hold in active), 'feasible': False}
    chosen = order[:gap]
    for hold in chosen:
        if hold['ticket']:
            due = allocations.get((hold['ticket'], show), 0)
            evictions.append({**hold, 'eviction_type': 'package_split',
                              'reason_code': 'SEAT_PACKAGE_SPLIT', 'due_cents': due})
            if due:
                dues.append({'ticket': hold['ticket'], 'show': show, 'due_cents': due,
                             'allocated_cents': due, 'hold_id': hold['hold_id']})
        else:
            evictions.append({**hold, 'eviction_type': 'unpaid_release',
                              'reason_code': 'SEAT_UNPAID_HOLD_RELEASED', 'due_cents': 0})
    remaining = sorted(hold['seat_label'] for hold in active
                       if hold['hold_id'] not in {item['hold_id'] for item in evictions})
    return {'show': show, 'gap': gap, 'evictions': evictions, 'refund_dues': dues,
            'remaining_seats': remaining, 'feasible': True}


def check_show_balance(show, capacity, active_seats, evictions, dues):
    """逐场座位与待清退票守恒，失败返回原因码，通过返回空串。

    拆票座位数与待清退记录数一致；待退票款总额只来自退款表，金额依据不丢失。
    """
    if len(active_seats) > capacity:
        return 'SEAT_CAPACITY_EXCEEDED'
    split_count = sum(1 for item in evictions if item['eviction_type'] == 'package_split')
    if split_count != len(dues):
        return 'SEAT_RECONCILE_FAILED'
    if any(item['due_cents'] <= 0 for item in dues):
        return 'SEAT_RECONCILE_FAILED'
    return ''
