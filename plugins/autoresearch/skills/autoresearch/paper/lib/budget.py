"""One task budget and receipt-backed resource accounting in controller state."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext
import math
import re

from .runtime import Refusal


def require(value, message):
    if not value:
        raise Refusal(message)


def money(value):
    require(isinstance(value, dict) and set(value) == {'amount', 'currency'},
            'cost needs amount and currency')
    require(isinstance(value['amount'], str), 'cost.amount must be a decimal string')
    require(len(value['amount']) <= 64 and re.fullmatch(r'(?:\d+(?:\.\d*)?|\.\d+)', value['amount']),
            'cost.amount must use bounded plain decimal notation')
    try:
        amount = Decimal(value['amount'])
    except InvalidOperation as exc:
        raise Refusal('Invalid cost.amount') from exc
    require(amount.is_finite() and amount >= 0 and len(value['amount']) <= 64,
            'cost.amount must be a finite nonnegative amount')
    require(isinstance(value['currency'], str) and re.fullmatch(r'[A-Z]{3}', value['currency']),
            'cost.currency must be a three-letter uppercase currency')
    return {'amount': format(amount, 'f'), 'currency': value['currency']}


def quantities(value, *, caps=False):
    fields = {'calls', 'tokens', 'cost'} | ({'minutes'} if caps else set())
    require(isinstance(value, dict) and not set(value) - fields,
            'budget accepts calls, tokens, cost and minutes only' if caps else
            'usage accepts calls, tokens and cost only')
    result = dict(value)
    for field in ('calls', 'tokens'):
        if field in result:
            require(type(result[field]) is int and result[field] >= 0,
                    field + ' must be a nonnegative integer; omission means no cap')
    if 'minutes' in result:
        number = result['minutes']
        require(type(number) in {int, float} and math.isfinite(number) and number > 0,
                'budget.minutes must be a positive explicit task wall-time limit')
    if 'cost' in result:
        result['cost'] = money(result['cost'])
    return result


def limits(brief):
    require('round_limits' not in brief, 'round_limits was removed; use the single top-level budget')
    resources = brief.get('resources')
    require(not isinstance(resources, dict) or not {'limits', 'budget'} & set(resources),
            'resources.limits/resources.budget are not read; use the single top-level budget')
    return quantities(brief.get('budget', {}), caps=True)


def task_started_at(state):
    return state.get('task_clock', {}).get('started_at', state['created_at'])


def elapsed(state):
    start = datetime.fromisoformat(task_started_at(state).replace('Z', '+00:00'))
    return max(0, (datetime.now(timezone.utc) - start).total_seconds() / 60)


def summary(state):
    with localcontext() as context:
        context.prec = 96
        return _summary(state)


def _summary(state):
    cap = limits(state['brief'])
    known = {'calls': 0, 'tokens': 0, 'cost': {}}
    held = {'calls': 0, 'tokens': 0, 'cost': {}}
    unresolved, unknown, unreported, incomplete_caps = [], [], {}, {}
    for key, entry in state.get('usage_ledger', {}).items():
        actual = entry.get('reported_usage', {})
        reservation = entry.get('reserved', {})
        pending = entry['status'] in {'reserved', 'unknown'}
        if pending:
            unresolved.append(key)
        if entry['status'] == 'unknown':
            unknown.append(key)
        if entry['status'] == 'reserved':
            missing = {field for field in cap if field != 'minutes' and field not in reservation}
            if 'cost' in cap and 'cost' in reservation and cap['cost']['currency'] != reservation['cost']['currency']:
                missing.add('cost')
            if missing:
                incomplete_caps[key] = sorted(missing)
        for field in ('calls', 'tokens'):
            known[field] += actual.get(field, 0)
            if pending:
                held[field] += max(0, reservation.get(field, 0) - actual.get(field, 0))
        if 'cost' in actual:
            currency = actual['cost']['currency']
            known['cost'][currency] = known['cost'].get(currency, Decimal(0)) + Decimal(actual['cost']['amount'])
        if pending and 'cost' in reservation:
            currency = reservation['cost']['currency']
            used = Decimal(actual['cost']['amount']) if actual.get('cost', {}).get('currency') == currency else Decimal(0)
            held['cost'][currency] = held['cost'].get(currency, Decimal(0)) + max(Decimal(0), Decimal(reservation['cost']['amount']) - used)
        if entry['status'] not in {'reserved', 'not_started'}:
            missing = sorted({'calls', 'tokens', 'cost'} - set(actual))
            if missing:
                unreported[key] = missing
            capped = {field for field in cap if field != 'minutes' and field not in actual}
            if 'cost' in cap and 'cost' in actual and cap['cost']['currency'] != actual['cost']['currency']:
                capped.add('cost')
            if capped:
                incomplete_caps[key] = sorted(capped)
    exhausted, remaining = [], {}
    for field in ('calls', 'tokens'):
        if field in cap:
            remaining[field] = max(0, cap[field] - known[field] - held[field])
            if known[field] >= cap[field]:
                exhausted.append(field)
    if 'cost' in cap:
        currency = cap['cost']['currency']
        amount = Decimal(cap['cost']['amount'])
        used = known['cost'].get(currency, Decimal(0))
        reserved = held['cost'].get(currency, Decimal(0))
        remaining['cost'] = {'amount': format(max(Decimal(0), amount - used - reserved), 'f'), 'currency': currency}
        if used >= amount:
            exhausted.append('cost')
    duration = elapsed(state)
    if 'minutes' in cap:
        remaining['minutes'] = max(0, cap['minutes'] - duration)
        if duration >= cap['minutes']:
            exhausted.append('minutes')
    for totals in (known, held):
        totals['cost'] = {currency: format(amount, 'f') for currency, amount in totals['cost'].items()}
    return {'limits': cap, 'known_usage': known, 'reserved': held, 'remaining': remaining,
            'unresolved_usage': unresolved, 'unknown_usage': unknown, 'unreported_fields': unreported,
            'incomplete_capped_usage': incomplete_caps,
            'exhausted': exhausted, 'elapsed_task_minutes': duration, 'task_started_at': task_started_at(state),
            'new_local_work_allowed': 'minutes' not in exhausted and state.get('task_stop') is None,
            'scope': 'Explicitly registered research resource operations; no inferred host/model billing'}


def ensure_work_allowed(state):
    require('minutes' not in summary(state)['exhausted'],
            'Explicit task budget.minutes exhausted; record checkpoint or finish existing delivery')
    require(state.get('task_stop') is None, 'Task stopped; preserve or finalize existing evidence, or record an actual user resumption')


def admit(state, packet):
    ensure_work_allowed(state)
    require(isinstance(packet, dict) and set(packet) == {'usage', 'purpose'},
            'Reservation needs usage and purpose')
    require(isinstance(packet['purpose'], str) and packet['purpose'].strip(), 'Reservation purpose is required')
    request = quantities(packet['usage'])
    require(any(v > 0 for k, v in request.items() if k != 'cost') or
            ('cost' in request and Decimal(request['cost']['amount']) > 0),
            'Reserve a concrete nonzero resource operation')
    view = summary(state)
    require(not view['unknown_usage'], 'Reconcile unknown usage before another resource operation; local work remains available')
    require(not view['incomplete_capped_usage'], 'Historical usage is unknown or unreserved for a current budget meter; reconcile its receipts before new resource operations')
    for field in ('calls', 'tokens', 'cost'):
        if field not in view['limits']:
            continue
        require(field in request, 'Supply a verifiable maximum for budgeted ' + field)
        if field == 'cost':
            require(request[field]['currency'] == view['limits'][field]['currency'], 'Reservation currency differs from task budget')
            within = Decimal(request[field]['amount']) <= Decimal(view['remaining'][field]['amount'])
        else:
            within = request[field] <= view['remaining'][field]
        require(within, 'Requested resource exceeds task budget.' + field + '; ask user before increasing it')
    return {'reserved': request, 'purpose': packet['purpose'], 'status': 'reserved'}


def settlement(state, entry, packet):
    require(isinstance(packet, dict) and set(packet) == {'receipt', 'status', 'usage'},
            'Settlement needs receipt, status and usage')
    require(packet['status'] in {'known', 'unknown', 'not_started'}, 'Unknown usage settlement status')
    actual = quantities(packet['usage'])
    if packet['status'] == 'not_started':
        require(entry is not None, 'not_started needs an existing reservation')
        old = entry.get('reported_usage', {})
        require(not any(value > 0 for field, value in old.items() if field != 'cost') and
                Decimal(old.get('cost', {}).get('amount', '0')) == 0,
                'Recorded nonzero actual usage cannot become not_started')
        require(all(value == 0 for key, value in actual.items() if key != 'cost') and
                Decimal(actual.get('cost', {}).get('amount', '0')) == 0, 'A not-started operation cannot consume resources')
    cap = limits(state['brief'])
    incomplete = any(key not in actual for key in cap if key != 'minutes')
    if 'cost' in cap and 'cost' in actual:
        incomplete |= actual['cost']['currency'] != cap['cost']['currency']
    status = 'unknown' if packet['status'] == 'unknown' or (packet['status'] == 'known' and incomplete) else packet['status']
    return {**(entry or {'reserved': {}, 'purpose': 'Unreserved actual usage'}),
            'status': status, 'reported_usage': actual, 'receipt': packet['receipt'],
            'unreserved': entry is None}
