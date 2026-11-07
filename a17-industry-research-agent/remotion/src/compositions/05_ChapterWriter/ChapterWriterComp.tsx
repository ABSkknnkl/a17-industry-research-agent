import React from 'react';
import { useCurrentFrame } from 'remotion';
import { PaperBackground } from '../../components/PaperBackground';
import { ReportHeader } from '../../components/ReportHeader';
import { ContractCard, ContractProperty } from '../../components/ContractCard';
import { EngineBox, EngineItem } from '../../components/EngineBox';
import { FlowConnector } from '../../components/FlowConnector';
import { AnimatedBadge } from '../../components/AnimatedBadge';
import { colors } from '../../theme/colors';
import { typography } from '../../theme/typography';

export const ChapterWriterComp: React.FC = () => {
  const frame = useCurrentFrame();

  // Part 1: 输入契约 (源自 Stage 2 证据池与 Stage 3 的 15 张图表)
  const inputProps: ContractProperty[] = [
    { key: 'input_facts', value: '38 Evidence Cards (R-xxx)', highlight: true },
    { key: 'input_charts', value: '15 Publication SVGs' },
    { key: 'outline_version', value: '"2026.1" (7 Chapters / 21 Sections)' },
    { key: 'execution_engine', value: 'asyncio.gather Parallel Pool' },
    { key: 'compliance_guard', value: 'WritingLinter Mandatory [R-xxx]' },
    { key: 'human_intervention', value: 'Targeted Chapter Rewrite Supported' },
  ];

  // Part 2: 并发撰写池与合规审查微观引擎 (严格对齐 outline.py, agent.py, retriever.py)
  const engineItems: EngineItem[] = [
    {
      name: 'ConcurrentWriterEngine (asyncio.gather)',
      desc: '21 个小节全并发批处理创作池，各节独立挂载上下文，解决长文本生成瓶颈',
      result: '+420% Speedup',
      active: frame >= 120,
      statusText: frame >= 180 ? '21/21 POOL RUNNING' : 'SPAWNING',
    },
    {
      name: 'WritingLinter 合规质检与去幻觉审查',
      desc: '强制扫描每个结论句是否绑定 [R-xxx] 证据哈希，过滤违规绝对化推荐词',
      result: '0 Hallucinations',
      active: frame >= 180,
      statusText: frame >= 260 ? 'LINTER PASSED' : 'SCANNING',
    },
    {
      name: 'AnchorInjector 图文锚点精准插桩',
      desc: '将 15 张 SVG 矢量图与 38 条证据链精准嵌入对应小节，保持文图强互证',
      result: '15 Charts Docked',
      active: frame >= 260,
      statusText: frame >= 340 ? 'DOCKED' : 'INJECTING',
    },
    {
      name: '7 大标准行研骨架大纲 (OUTLINE 2026.1)',
      desc: 'CH-01 定义基础 ➔ CH-02 规模成长 ➔ CH-03 产业链 ➔ CH-04 格局 ➔ CH-05 财务估值 ➔ CH-06 催化 ➔ CH-07 结论',
      result: '13,500+ Words',
      active: frame >= 340,
      statusText: frame >= 400 ? '7/7 ASSEMBLED' : 'WRITING',
    },
  ];

  // Part 3: 输出契约产物 (严格对应真实落盘 chapter_result.json，153 KB)
  const outputProps: ContractProperty[] = [
    { key: 'contract_id', value: '"chapter_result.json" (153 KB)' },
    { key: 'standard_chapters', value: '7 Chapters (CH-01 ~ CH-07)', highlight: true },
    { key: 'standard_sections', value: '21 Sub-sections (SEC-01-01~21)' },
    { key: 'total_words', value: '13,500+ Deep Research Words' },
    { key: 'grounded_evidence_rate', value: '100% Bound to R-xxx Index' },
    { key: 'review_ready', value: 'True (Waiting Review / Stage 5)' },
  ];

  const showGrid = frame >= 150 && frame <= 440;

  return (
    <PaperBackground watermarkText="STAGE 4: 7-CHAPTER 21-SECTION CONCURRENT WRITER">
      <ReportHeader
        title="章节撰写智能体微观拆解"
        subtitle="7 章 21 节标准大纲体系 · 21 节全并发写作池、WritingLinter 合规与证据锚点插桩"
        stageBadge="CONCURRENT WRITER"
        stageNumber="04"
      />

      <div
        style={{
          position: 'absolute',
          top: 170,
          left: 64,
          right: 64,
          bottom: 60,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}
      >
        {/* 左侧: 输入契约卡片 */}
        <ContractCard
          title="INPUT DATA & CHARTS"
          contractName="facts_and_charts.bundle"
          type="input"
          properties={inputProps}
          enterFrame={0}
          width={450}
          height={550}
          badgeText="STAGES 2+3 BUNDLE"
          badgeColor={colors.navyLight}
        />

        <FlowConnector label="CONCURRENT RUN" width={100} />

        {/* 中间: 并发池与插桩微观引擎 */}
        <div style={{ position: 'relative' }}>
          <EngineBox
            title="全并发小节写作池与合规质检"
            engineCodeName="ConcurrentWriterEngine & WritingLinter"
            items={engineItems}
            enterFrame={90}
            width={720}
            height={550}
            badge="PARALLEL GENERATION (+420%)"
          />

          {/* 浮动特写：21 并发写作小节真实微网格 */}
          {showGrid && (
            <div
              style={{
                position: 'absolute',
                top: 80,
                left: 30,
                right: 30,
                backgroundColor: colors.navyDark,
                color: '#fff',
                padding: '12px 18px',
                borderRadius: 4,
                boxShadow: '0 8px 24px rgba(0,0,0,0.3)',
                border: `1px solid ${colors.goldLight}`,
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8, fontSize: 11, fontFamily: typography.mono }}>
                <span style={{ color: colors.goldLight }}>21-SUBSECTION PARALLEL WORKERS ACTIVE (CH-01 ~ CH-07)</span>
                <span style={{ color: colors.success }}>13,500+ WORDS STREAMING</span>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', gap: 6 }}>
                {Array.from({ length: 21 }).map((_, i) => {
                  const isDone = frame >= 180 + i * 8;
                  return (
                    <div
                      key={i}
                      style={{
                        padding: '4px 2px',
                        backgroundColor: isDone ? colors.success : 'rgba(255,255,255,0.12)',
                        borderRadius: 2,
                        textAlign: 'center',
                        fontSize: 10,
                        fontFamily: typography.mono,
                        color: '#fff',
                      }}
                    >
                      S{i + 1} {isDone ? '✓' : '...'}
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        <FlowConnector label="SEMBLE & PASS" width={100} packetColor={colors.gold} />

        {/* 右侧: 章节全稿产物卡片 */}
        <div style={{ position: 'relative' }}>
          <ContractCard
            title="STANDARDIZED ARTIFACT"
            contractName="chapter_result.json"
            type="output"
            properties={outputProps}
            enterFrame={380}
            width={450}
            height={550}
            badgeText="STAGE 4 COMPLETE"
            badgeColor={colors.success}
          />

          <div style={{ position: 'absolute', bottom: 40, right: 30 }}>
            <AnimatedBadge
              text="21 SECTIONS FULL"
              subtext="WRITINGLINTER PASSED"
              enterFrame={430}
              color={colors.gold}
              angle={-8}
            />
          </div>
        </div>
      </div>
    </PaperBackground>
  );
};
