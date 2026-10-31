"""Read-only SVG projection: no entity movement, name inference or company filling."""
from html import escape
import textwrap


from dataclasses import dataclass, field


@dataclass
class ChainCard:
    activity_id: str
    title: str
    stage: str
    display_policy: str = 'representative'
    companies: list[str] = field(default_factory=list)
    products: list[str] = field(default_factory=list)
    description: str = ''
    assertion_ids: list[str] = field(default_factory=list)
    profile_refs: list[str] = field(default_factory=list)


@dataclass
class ChainViewModel:
    subject: str
    release_status: str
    as_of: str
    cards: list[ChainCard]
    profile_id: str | None = None
    profile_status: str | None = None


def compile_chain_view(bundle):
    from .membership import activity_id
    from .models import Predicate
    entities = {e.entity_id: e for e in bundle.entities}
    supported = bundle.supported_assertions()
    stages = bundle.quality.coverage_values.get('view_stages', {})
    profile = bundle.profile_snapshot
    policies = {activity_id(profile, bundle.scope, a.activity_key): a for a in profile.activities} if profile else {}
    accepted = {d.decision_id for d in bundle.membership_decisions if d.status == 'accepted'}
    categories = {c.category_id: c.name for c in profile.categories} if profile else {}
    cards = []
    for aid in bundle.structure.activity_ids:
        policy = policies.get(aid)
        claims = [a for a in supported if aid in (a.subject_id, a.object_id)]
        memberships = [a for a in claims if a.object_id == aid
            and entities[a.subject_id].entity_type == 'organization'
            and a.predicate in (Predicate.PARTICIPATES_IN, Predicate.PERFORMS)
            and (not profile or a.qualifiers.extra.get('membership_decision_id') in accepted)]
        cards.append(ChainCard(activity_id=aid, title=entities[aid].canonical_name,
            stage=policy.stage if policy else stages.get(aid, 'support'),
            display_policy=policy.company_display_policy if policy else 'representative',
            companies=sorted({entities[a.subject_id].canonical_name for a in memberships}),
            products=([categories[c] for c in policy.category_ids] if policy else sorted({
                entities[a.object_id].canonical_name for a in claims if a.subject_id == aid
                and entities[a.object_id].entity_type == 'product'})),
            description=policy.description if policy else '',
            assertion_ids=sorted({a.assertion_id for a in claims}),
            profile_refs=([profile.profile_id + '/' + policy.activity_key, *profile.source_refs,
                           *policy.source_refs] if policy else [])))
    return ChainViewModel(bundle.scope.subject, bundle.quality.release_status, bundle.scope.as_of, cards,
                          profile.profile_id if profile else None, profile.status if profile else None)


def render_bundle(bundle):
    view = compile_chain_view(bundle)
    stages = ['upstream', 'midstream', 'downstream', 'support']
    labels = ['上游产品与投入', '制造与品牌', '渠道与应用', '配套服务']
    mapping = {c.activity_id: c.assertion_ids for c in view.cards}
    groups = [[c for c in view.cards if c.stage == s] for s in stages]
    blocks, positions, bottoms = [], {}, []
    for i, group in enumerate(groups):
        x, y = 30+i*435, 135
        for card in group:
            lines = [(card.title, 19)]
            if card.products:
                lines += [(p, 15) for p in textwrap.wrap('品类：'+'、'.join(card.products), 23)]
            if card.display_policy in ('process', 'scenario'):
                label = '工艺说明：' if card.display_policy == 'process' else '应用说明：'
                lines += [(p, 15) for p in textwrap.wrap(label+card.description, 23)]
            elif card.companies:
                lines += [('代表：'+name, 16) for name in card.companies[:4]]
                if len(card.companies) > 4:
                    lines.append((f'另有 {len(card.companies)-4} 家，见证据详情', 14))
            else:
                lines.append(('代表企业待补；结构保留', 14))
            lines = [(part, size) for text, size in lines for part in textwrap.wrap(text, 25)]
            height = max(125, 28 + 26*len(lines))
            positions[card.activity_id] = (x, y, height)
            blocks.append(f'<rect x="{x}" y="{y}" width="405" height="{height}" rx="9" fill="white" stroke="#b9c9dc"/>')
            py = y+29
            for text, size in lines:
                # Wrap every long enterprise/title, do not silently cut its name.
                for part in textwrap.wrap(text, 25):
                    blocks.append(f'<text x="{x+14}" y="{py}" font-size="{size}">{escape(part)}</text>')
                    py += 26
            y += height+18
        bottoms.append(y)
    height = max([620, *bottoms])+52
    quality = {'partial': '部分覆盖', 'draft': '结构草案', 'verified': '范围内已核验', 'failed': '研究失败'}[view.release_status]
    suffix = ' · 画像待来源审阅' if view.profile_status == 'draft' else ''
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="1760" height="{height}" viewBox="0 0 1760 {height}">',
           '<rect width="100%" height="100%" fill="#f6f8fc"/>',
           '<g font-family="Arial,PingFang SC,Microsoft YaHei,sans-serif" fill="#15283f">',
           f'<text x="30" y="40" font-size="27">{escape(view.subject)} · 产业链全景</text>',
           f'<text x="30" y="74" font-size="15">{quality} · {escape(view.as_of)}{suffix} · 代表参与不表示特定客户供货</text>']
    out += [f'<text x="{30+i*435}" y="113" font-size="20">{title}</text>' for i,title in enumerate(labels)]
    out += blocks

    # D3（V8 最终方案 §10.5）：关系边必须真实渲染。
    # 旧实现只画跨列直线：同列关系被 `x != tx` 直接跳过、且无箭头，
    # 前端还会把 <path> 从消毒白名单里删掉——三条叠加导致"连线永远看不到"。
    # 现在：同列/跨列都画，用 line + polygon 箭头（前后端都支持的安全图元），
    # 每条边带稳定 data-edge-id，并写入 view_mapping 供验收。
    edge_color = '#326898'
    edge_index = 0
    for claim in bundle.supported_assertions():
        if claim.predicate.value != 'precedes':
            continue
        if claim.subject_id not in positions or claim.object_id not in positions:
            continue
        sx, sy, sh = positions[claim.subject_id]
        tx, ty, th = positions[claim.object_id]
        edge_index += 1
        edge_id = f"edge-{edge_index}-{claim.assertion_id[:8]}"

        if sx == tx:
            # 同列：从卡片底边中点到下一张卡片顶边中点，纵向短箭头
            x1, y1 = sx + 202, sy + sh
            x2, y2 = tx + 202, ty
            if y2 <= y1:  # 目标在上方：改为从顶边向上
                x1, y1 = sx + 202, sy
                x2, y2 = tx + 202, ty + th
        else:
            # 跨列：右侧边中点 → 左侧边中点
            x1, y1 = sx + 405, sy + sh / 2
            x2, y2 = tx, ty + th / 2

        out.append(
            f'<line data-edge-id="{edge_id}" x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="{edge_color}" stroke-width="2" marker-end="url(#chain-arrow)"/>'
        )
        mapping.setdefault('edges', []).append({
            'edge_id': edge_id,
            'assertion_id': claim.assertion_id,
            'from': claim.subject_id,
            'to': claim.object_id,
            'kind': 'process_precedes',
            'evidence_ids': list(claim.evidence_ids),
            'render_status': 'rendered',
            'same_column': sx == tx,
        })
    # 组织—活动关系（offers / supplies_to / provides_service_to）：
    # 这些关系没有独立的"卡到卡"位置（企业名在活动卡内部），不适合画成活动间边；
    # 但**不能静默消失**——按方案要求给出 render_status 与可读原因，保留完整明细。
    relations = mapping.setdefault('relations', [])
    for claim in bundle.supported_assertions():
        predicate_value = str(getattr(getattr(claim, 'predicate', None), 'value', '') or '')
        if predicate_value == 'precedes':
            continue
        relations.append({
            'assertion_id': claim.assertion_id,
            'from': claim.subject_id,
            'to': claim.object_id,
            'kind': predicate_value,
            'evidence_ids': list(claim.evidence_ids),
            'render_status': 'in_card',
            'reason': '组织—活动关系在活动卡内部呈现（卡片内企业名+证据），不画成活动间边',
        })

    # 箭头 marker 定义（polygon，避免 path 被前端消毒删除）。
    # 只在确实有边时输出：无边的图不该留一个空 marker 让人以为"有连线被隐藏"。
    if edge_index > 0:
        arrow_def = ('<defs><marker id="chain-arrow" viewBox="0 0 10 10" refX="9" refY="5" '
                     'markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
                     f'<polygon points="0,0 10,5 0,10" fill="{edge_color}"/></marker></defs>')
        # 必须插在 <svg ...> 根标签之后：插到 out[0] 会把 defs 放到根外，SVG 非法
        insert_at = 1 if out and out[0].lstrip().startswith("<svg") else 0
        out.insert(insert_at, arrow_def)
    out.append('</g></svg>')
    return '\\n'.join(out), mapping

def render_evidence(bundle, svg):
    entities = {e.entity_id: e.canonical_name for e in bundle.entities}
    evidence = {e.evidence_id: e for e in bundle.evidence}
    rows = []
    for a in bundle.assertions:
        cites = []
        for eid in a.evidence_ids:
            ev = evidence[eid]
            cites.append(f'<p><a href="{escape(ev.url or "", quote=True)}">{escape(ev.title)}</a> '
                         f'{escape(ev.locator)}<br>{escape(ev.quote)}</p>')
        rows.append('<tr><td>'+escape(a.status)+'</td><td>'+escape(entities[a.subject_id])+
                    '</td><td>'+escape(a.predicate.value)+'</td><td>'+escape(entities[a.object_id])+
                    '</td><td>'+''.join(cites)+'</td><td>'+escape(a.verification.rationale)+'</td></tr>')
    admissions = ''.join('<tr><td>'+escape(entities[d.organization_id])+'</td><td>'+escape(d.activity_key)
        +'</td><td>'+escape(d.status)+'</td><td>'+escape('、'.join(d.reason_codes))
        +'</td><td>'+escape('、'.join(d.input_assertion_ids))+'</td><td>'
        +escape('、'.join(d.taxonomy_refs))+'</td></tr>' for d in bundle.membership_decisions)
    details = ('<details><summary>查看企业归属决定与映射依据</summary><table><tr><th>组织</th><th>活动</th>'
        '<th>准入</th><th>原因</th><th>输入断言</th><th>政策依据</th></tr>'+admissions+'</table></details>') if admissions else ''
    gaps = '<details><summary>查看质量缺口</summary><ul>'+''.join(
        '<li>'+escape(item)+'</li>' for item in bundle.quality.unresolved)+'</ul></details>'
    return ('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>产业链证据审阅</title>'
            '<style>body{font:15px sans-serif;margin:24px;color:#17283c}svg{max-width:100%;height:auto}'
            'table{border-collapse:collapse;width:100%}td,th{border:1px solid #cad3df;padding:10px;vertical-align:top}'
            'td:nth-child(5){min-width:320px}tr:nth-child(even){background:#f6f8fc}</style>'
            '<h1>'+escape(bundle.scope.subject)+' · '+escape(bundle.quality.release_status)+'</h1>'
            '<p>结构与画像的来源审阅状态独立记录。产品能力不证明特定客户供货；规则准入不等于人工认证。</p>'+
            svg+details+gaps+'<details><summary>查看全部断言与原文</summary><table><tr><th>状态</th><th>主体</th><th>关系</th><th>客体</th><th>原文证据</th><th>核验理由</th></tr>'+
            ''.join(rows)+'</table></details>')
