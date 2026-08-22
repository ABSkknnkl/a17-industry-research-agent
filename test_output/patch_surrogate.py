from pathlib import Path

p = Path('/Users/Zhuanz1/PycharmProjects/同花顺/eval/surrogate_models.py')
s = p.read_text(encoding='utf-8')

start_anchor = '        sections: list[SectionDraft] = []'
end_anchor = '        for text_value in [draft.summary, *[p.text for s in sections for p in s.paragraphs]]:'

start = s.index(start_anchor)
end = s.index(end_anchor)
old_block = s[start:end]

new_block = '''        available_charts = [
            item
            for item in payload.get("available_charts", [])
            if isinstance(item, dict) and item.get("chart_id")
        ]
        evidence_claim = {
            str(evidence_id): claim
            for claim in claims
            for evidence_id in claim["evidence_ids"]
        }
        # 图表按小节轮转落位；覆盖图表证据的结论与图表同小节全量渲染，
        # 以满足 audit/provenance 对“小节段落证据须覆盖图表证据”的硬约束。
        section_chart_ids: dict[int, list[str]] = {1: [], 2: [], 3: []}
        section_claim_map: dict[int, list[dict[str, Any]]] = {1: [], 2: [], 3: []}
        section_seen: dict[int, set[str]] = {1: set(), 2: set(), 3: set()}
        for chart_index, chart in enumerate(available_charts):
            chart_evidence = [str(item) for item in chart.get("evidence_ids", []) or []]
            if not chart_evidence or any(
                str(evidence_id) not in evidence_claim for evidence_id in chart_evidence
            ):
                continue
            section_index = (chart_index % 3) + 1
            section_chart_ids[section_index].append(str(chart["chart_id"]))
            for evidence_id in chart_evidence:
                claim = evidence_claim[evidence_id]
                claim_id = str(claim["claim_id"])
                if claim_id not in section_seen[section_index]:
                    section_seen[section_index].add(claim_id)
                    section_claim_map[section_index].append(claim)
        covered_claim_ids: set[str] = set().union(*section_seen.values())
        extra_index = 0
        for claim in claims:
            claim_id = str(claim["claim_id"])
            if claim_id in covered_claim_ids:
                continue
            section_index = (extra_index % 3) + 1
            extra_index += 1
            if claim_id not in section_seen[section_index]:
                section_seen[section_index].add(claim_id)
                section_claim_map[section_index].append(claim)

        sections: list[SectionDraft] = []
        chapter_claim_ids: list[str] = []
        chapter_evidence_ids: list[str] = []
        chapter_chart_ids: list[str] = []
        for section_index, section_config in enumerate(config_sections, 1):
            section_claims = section_claim_map[section_index]
            rendered_claims = (
                section_claims
                if section_chart_ids[section_index]
                else section_claims[:3]
            )
            paragraphs: list[ParagraphDraft] = []
            section_claim_ids: list[str] = []
            section_evidence_ids: list[str] = []
            for paragraph_index, claim in enumerate(rendered_claims, 1):
                claim_id = str(claim["claim_id"])
                evidence_ids = [str(item) for item in claim["evidence_ids"]]
                paragraphs.append(
                    ParagraphDraft(
                        paragraph_id=f"P-{number}-{section_index:02d}-{paragraph_index:02d}",
                        kind="analysis",
                        text=str(claim.get("text") or ""),
                        claim_ids=[claim_id],
                        evidence_ids=evidence_ids,
                    )
                )
                section_claim_ids.append(claim_id)
                for evidence_id in evidence_ids:
                    if evidence_id not in section_evidence_ids:
                        section_evidence_ids.append(evidence_id)
            if not paragraphs:
                paragraphs.append(
                    ParagraphDraft(
                        paragraph_id=f"P-{number}-{section_index:02d}-01",
                        kind="methodology",
                        text=(
                            f"本节围绕{section_config.get('title', '研究小节')}展开，"
                            f"按“{section_config.get('purpose', '章节目标')}”组织论述；"
                            "当前小节缺少可引用结论，相关数据边界已在研究边界中披露。"
                        ),
                    )
                )
            key_points = [
                str(claim.get("text") or "") for claim in rendered_claims[:3]
            ] or [f"{section_config.get('title', '本小节')}：证据不足，仅保留研究框架。"]
            section_charts = list(section_chart_ids[section_index])
            sections.append(
                SectionDraft(
                    section_id=str(section_config["section_id"]),
                    title=str(section_config["title"]),
                    purpose=str(section_config["purpose"]),
                    key_points=[point for point in key_points if point],
                    paragraphs=paragraphs,
                    chart_ids=section_charts,
                    uncertainties=["部分结论依赖单一来源证据，口径差异风险待核验。"],
                )
            )
            chapter_claim_ids.extend(section_claim_ids)
            chapter_evidence_ids.extend(section_evidence_ids)
            for chart_id in section_charts:
                if chart_id not in chapter_chart_ids:
                    chapter_chart_ids.append(chart_id)

        title = str(config.get("title") or chapter_id)
        summary = (
            f"本章围绕“{title}”，基于{len(set(chapter_claim_ids))}项可追溯结论展开，"
            "全部结论均可回溯至证据编号。"
        )
        draft = ChapterDraft(
            chapter_id=chapter_id,
            title=title,
            summary=summary,
            sections=sections,
            claim_ids=list(dict.fromkeys(chapter_claim_ids)),
            evidence_ids=list(dict.fromkeys(chapter_evidence_ids)),
            chart_ids=chapter_chart_ids,
            missing_inputs=[],
            revision=max(1, revision),
        )
'''

s = s[:start] + new_block + s[end:]
p.write_text(s, encoding='utf-8')
print('surrogate_models.py patched; replaced', len(old_block), 'chars')
