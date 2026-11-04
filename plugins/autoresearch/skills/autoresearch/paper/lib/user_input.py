"""State-free questions and source-bound answers; the caller owns issuance.

Source integrity does not prove human identity or the meaning of a free-text reply.
The host must ask the question and truthfully translate the actual answer.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from .runtime import Refusal, digest, read_json, safe


def _object(value, label):
    if not isinstance(value, dict):
        raise Refusal(label + ' must be an object')
    return value


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise Refusal(label + ' must be nonempty text')
    return value


def _source(name, root):
    path = safe(Path(root).resolve(), name)
    if path.stat().st_size > 16 * 1024 * 1024:
        raise Refusal('Question source exceeds the 16 MiB input limit')
    raw = path.read_bytes()
    return {'path': name, 'sha256': hashlib.sha256(raw).hexdigest()}, raw


def check_human_response(record, root):
    """Verify the exact recorded bytes and quote, without attesting identity."""
    _object(record, 'human_response')
    if set(record) != {'path', 'sha256', 'quote'}:
        raise Refusal('human_response requires only path, sha256 and quote; delegated authorization is not an answer')
    _text(record.get('quote'), 'Human response quote')
    source, raw = _source(record.get('path'), root)
    if record.get('sha256') != source['sha256']:
        raise Refusal('Human response source SHA-256 differs')
    try:
        content = raw.decode('utf-8')
    except UnicodeDecodeError as error:
        raise Refusal('Human response source must be UTF-8 text') from error
    if record['quote'] not in content:
        raise Refusal('Human response quote is absent from the actual source')
    return copy.deepcopy(record)


def prepare(kind, packet, root, state):
    """Describe an unanswered question, binding its inputs and current Brief."""
    _object(packet, 'Question packet')
    _object(state, 'Controller state')
    brief = _object(state.get('brief'), 'Current Brief')
    if state.get('brief_sha256') != digest(brief):
        raise Refusal('Current Brief SHA-256 differs')
    question = {'version': 1, 'kind': kind, 'status': 'needs_input',
                'brief_sha256': state['brief_sha256'], 'packet': copy.deepcopy(packet),
                'packet_sha256': digest(packet),
                'limits': 'The controller verifies source bytes and option membership, not human identity or free-text meaning. The host must ask and record the actual answer.'}
    if kind == 'venue':
        from .venue_tools import comparison_report, comparison_digest
        report = comparison_report(packet, root)
        sources = []
        for candidate in report['candidates']:
            for evidence in candidate['evidence']:
                source, _ = _source(evidence['path'], root)
                if source['sha256'] != evidence['sha256']:
                    raise Refusal('Venue candidate source SHA-256 differs')
                if evidence not in sources:
                    sources.append(copy.deepcopy(evidence))
        question.update(comparison=report, comparison_sha256=comparison_digest(report),
                        candidates=copy.deepcopy(report['candidates']), sources=sources,
                        criteria={'values': report['criteria'], 'packet_sha256': question['packet_sha256'],
                                  'sources': copy.deepcopy(sources)},
                        recommendation={'candidate_id': report['selected_id'], 'reason': report['rationale']},
                        options=[{'id': row['id'], 'label': row['venue'], 'answer': {'candidate_id': row['id']}}
                                 for row in report['candidates']])
        rows = ['请用户回答选择哪个期刊或会议。推荐不构成答复，候选均可选择。',
                '比较标准：' + ', '.join(report['criteria']),
                '推荐：' + report['selected_id'] + '；理由：' + report['rationale']]
        for candidate in report['candidates']:
            rows.append(json.dumps(candidate, ensure_ascii=False, sort_keys=True))
        rows.append('比较来源 SHA-256：' + question['comparison_sha256'])
        question['summary'] = '\n'.join(rows)
    elif kind == 'budget':
        from .budget import summary
        if set(packet) - {'budget', 'plan', 'reason', 'estimate'}:
            raise Refusal('Unknown budget question packet fields')
        proposal = copy.deepcopy(_object(packet.get('budget'), 'Proposed budget'))
        current = copy.deepcopy(_object(brief.get('budget', {}), 'Current budget'))
        ledger = _object(state.get('usage_ledger', {}), 'Usage ledger')
        view = summary(state)
        usage = {key: copy.deepcopy(view[key]) for key in
                 ('known_usage', 'reserved', 'unresolved_usage', 'unknown_usage', 'unreported_fields', 'scope')}
        for key in ('unresolved_usage', 'unknown_usage'):
            usage[key].sort()
        reason = _text(packet.get('reason'), 'Budget proposal reason')
        plan, _ = _source(packet.get('plan'), root)
        _object(read_json(safe(Path(root).resolve(), plan['path'])), 'Question plan JSON')
        sources = [plan]
        estimate = None
        if 'estimate' in packet:
            estimate, raw = _source(packet['estimate'], root)
            try:
                estimate['text'] = raw.decode('utf-8')
            except UnicodeDecodeError as error:
                raise Refusal('Budget estimate must be UTF-8 text') from error
            sources.append({key: estimate[key] for key in ('path', 'sha256')})
        question.update(current_budget=current, proposal=proposal, default_budget={}, plan=plan,
                        usage=usage, usage_ledger_sha256=digest(ledger),
                        estimate=estimate, sources=sources,
                        fields={'calls': 'Explicit research resource calls, an integer count.',
                                'tokens': 'Tokens covered by the research resource ledger, an integer count.',
                                'cost': {'amount': 'Decimal string', 'currency': 'Three uppercase letters'},
                                'minutes': 'Wall-clock minutes since the run was created, including waiting and all host sessions.'},
                        time_scope={'origin': 'run.created_at', 'created_at': state.get('created_at'),
                                    'includes_waiting': True, 'cross_session': True},
                        checkpoint={'minutes': 30, 'is_task_limit': False},
                        options=[{'id': 'default', 'label': '默认预算，无隐含任务总上限', 'budget': {}},
                                 {'id': 'custom', 'label': '设置预算', 'answer_field': 'budget'},
                                 {'id': 'decline', 'label': '不接受本次预算提议，保持当前预算并修订计划',
                                  'budget': copy.deepcopy(current), 'proceed': False}])
        rows = ['请用户回答是否设置预算。默认值或拟议值均不构成答复。',
                '当前预算：' + json.dumps(current, ensure_ascii=False, sort_keys=True),
                '账本已知消耗：' + json.dumps(usage['known_usage'], ensure_ascii=False, sort_keys=True),
                '当前预留：' + json.dumps(usage['reserved'], ensure_ascii=False, sort_keys=True),
                '未结算操作：' + json.dumps(usage['unresolved_usage'], ensure_ascii=False),
                '用量未知操作：' + json.dumps(usage['unknown_usage'], ensure_ascii=False),
                '未报告用量字段：' + json.dumps(usage['unreported_fields'], ensure_ascii=False, sort_keys=True),
                '账本 SHA-256：' + question['usage_ledger_sha256'] + '。仅覆盖显式登记的科研资源操作，不推算宿主或模型账单。',
                '拟议预算：' + json.dumps(proposal, ensure_ascii=False, sort_keys=True),
                '默认预算：{}，无隐含任务总上限。',
                '默认值不新增付费服务或算力授权；执行仍须符合实际用户授权。',
                '可选字段与单位：calls 为显式科研资源调用次数；tokens 为账本覆盖的 token 数；cost.amount 为十进制字符串，cost.currency 为三位大写币种；minutes 为任务墙钟分钟。',
                '时间范围：从 run.created_at=' + str(state.get('created_at')) + ' 起，累计跨宿主会话并包含等待。30 分钟仅为检查点提示。',
                '理由：' + reason,
                '计划：' + plan['path'] + '，SHA-256=' + plan['sha256']]
        if estimate:
            rows.append('资源说明：' + estimate['path'] + '，SHA-256=' + estimate['sha256'] + '\n' + estimate['text'])
        rows.append('请回答 default、custom 并给出预算，或 decline。decline 保持当前预算，计划待修订。')
        question['summary'] = '\n'.join(rows)
    else:
        raise Refusal('Question kind must be venue or budget')
    question['question_sha256'] = digest(question)
    return question


def validate_response(question, response, root, state):
    """Validate a response to the exact issued question; never choose by default."""
    _object(question, 'Question')
    _object(response, 'Actual human response; wait for an answer')
    expected = prepare(question.get('kind'), question.get('packet'), root, state)
    if question != expected:
        raise Refusal('Question inputs or current Brief changed; ask the current question again')
    if set(response) != {'question_sha256', 'answer', 'human_response'}:
        raise Refusal('Response requires question_sha256, answer and human_response; delegated authorization is not an answer')
    if response.get('question_sha256') != question['question_sha256']:
        raise Refusal('Response does not bind the current question SHA-256')
    check_human_response(response['human_response'], root)
    answer = _object(response.get('answer'), 'Answer')
    if question['kind'] == 'venue':
        candidate = answer.get('candidate_id')
        if set(answer) != {'candidate_id'} or not isinstance(candidate, str) or candidate not in {row['id'] for row in question['candidates']}:
            raise Refusal('Answer must choose one of the current venue candidate IDs')
        return copy.deepcopy(answer)
    choice = answer.get('choice')
    if choice == 'custom':
        if set(answer) != {'choice', 'budget'}:
            raise Refusal('Custom budget answer requires only choice and budget')
        budget = copy.deepcopy(_object(answer.get('budget'), 'Custom budget'))
    elif choice in ('default', 'decline'):
        if set(answer) != {'choice'}:
            raise Refusal('Default or declined budget answer requires only choice')
        budget = {} if choice == 'default' else copy.deepcopy(question['current_budget'])
    else:
        raise Refusal('Budget answer choice must be default, custom or decline')
    return {'choice': choice, 'budget': budget, 'proceed': choice != 'decline'}
