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

export const DataFetcherComp: React.FC = () => {
  const frame = useCurrentFrame();

  // Part 1: 输入契约 (严格映射 backend/app/schemas/workflow.py 中的 ResearchInput / input_data.json)
  const inputProps: ContractProperty[] = [
    { key: 'industry_topic', value: '"固态电池"', highlight: true },
    { key: 'analysis_depth', value: '"standard" (可扩展至 deep)' },
    { key: 'market_scope', value: '["中国 A 股", "港股", "美股", "B股"]' },
    { key: 'security_types', value: '["股票", "债券", "基金", "期货", "指数"]' },
    { key: 'reporting_currency', value: '"CNY"' },
    { key: 'focus_questions', value: '固态电解质瓶颈、龙头研发规划对比' },
    { key: 'status', value: 'VALIDATED' },
  ];

  // Part 2: 内部算子微观执行状态 (严格对齐 skillhub.py 与 DAG 调度机制)
  const engineItems: EngineItem[] = [
    {
      name: 'Query Planner (LLM 自然语言拆解)',
      desc: '分解研报主题，生成针对 7 大数据域的结构化问财金融检索 Prompt',
      result: '7 Prompts Ready',
      active: frame >= 120,
      statusText: frame >= 180 ? 'DONE' : 'PLANNING',
    },
    {
      name: 'SkillHub 20 大金融 OpenAPI 调度矩阵',
      desc: 'hithink-industry / finance / macro / business / astock-selector 并发采集',
      result: '20/20 Skills OK',
      active: frame >= 180,
      statusText: frame >= 260 ? '7 DOMAINS SYNC' : 'FETCHING',
    },
    {
      name: 'DataFusion 实体对齐与单位归一',
      desc: '实体映射: [300750.SZ]➔宁德时代, 002491.SZ➔通鼎互联, 亿元/万元归一',
      result: '100% Normalized',
      active: frame >= 260,
      statusText: frame >= 340 ? 'ALIGNED' : 'ALIGNING',
    },
    {
      name: 'DAG 依赖自愈机制 (DAG Healing)',
      desc: '当特定标的筛选受阻时，自愈器自动降级至行业高信用基准池获取候选公司',
      result: 'Self-Healed',
      active: frame >= 340,
      statusText: frame >= 400 ? 'RESILIENT' : 'CHECKING',
    },
  ];

  // Part 3: 输出契约产物 (严格对应真实落盘 dataset.json，913条真实记录)
  const outputProps: ContractProperty[] = [
    { key: 'contract_id', value: '"dataset.json" (3.5 MB)' },
    { key: 'total_records', value: '913 Structured Data Items', highlight: true },
    { key: 'covered_domains', value: '7 Domains (Companies/Macro/Chain...)' },
    { key: 'core_universe', value: '宁德时代、亿纬锂能、国轩高科、当升科技' },
    { key: 'source_provenance', value: '100% Sourced from Wencai SkillHub' },
    { key: 'data_integrity', value: 'Verified (Checksum SHA-256)' },
  ];

  return (
    <PaperBackground watermarkText="STAGE 1: DATA FETCHER & DAG HEALING ENGINE">
      <ReportHeader
        title="数据获取智能体微观拆解"
        subtitle="同花顺问财 20 大金融技能矩阵 · DAG 依赖自愈与 DataFusion 实体归一化"
        stageBadge="DATA FETCHER & FUSION"
        stageNumber="01"
      />

      {/* 主三段式横向布局：输入 ➔ 核心引擎 ➔ 输出 */}
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
          title="INPUT CONTRACT"
          contractName="ResearchInput (input_data.json)"
          type="input"
          properties={inputProps}
          enterFrame={0}
          width={450}
          height={550}
          badgeText="STRICT SCHEMA"
          badgeColor={colors.navyLight}
        />

        {/* 左向中流线 */}
        <FlowConnector label="DISPATCH" width={100} />

        {/* 中间: 内部核心引擎与算子微观剖析 */}
        <div style={{ position: 'relative' }}>
          <EngineBox
            title="数据采集规划与 DAG 自愈引擎"
            engineCodeName="SkillHubAdapter & DataFusion"
            items={engineItems}
            enterFrame={90}
            width={720}
            height={550}
            badge="STAGE 1 MICRO-ENGINE"
          />

          {/* 浮动特写：实体对齐与真实代码映射 */}
          {frame >= 280 && frame <= 480 && (
            <div
              style={{
                position: 'absolute',
                bottom: 60,
                left: 30,
                right: 30,
                backgroundColor: colors.navyDark,
                color: '#fff',
                padding: '10px 16px',
                borderRadius: 4,
                boxShadow: '0 8px 20px rgba(0,0,0,0.2)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                fontFamily: typography.mono,
                fontSize: 12,
                border: `1px solid ${colors.gold}`,
              }}
            >
              <div>
                <span style={{ color: colors.goldLight }}>RESOLVE: </span>
                <span>[300750.SZ] ➔ 宁德时代 (CATL · 1.39万亿市值)</span>
              </div>
              <div style={{ width: 1, height: 16, backgroundColor: 'rgba(255,255,255,0.2)' }} />
              <div>
                <span style={{ color: colors.goldLight }}>DATASET SIZE: </span>
                <span>913 Records · 7 Standard Domains</span>
              </div>
            </div>
          )}
        </div>

        {/* 中向右流线 */}
        <FlowConnector label="FUSED EMIT" width={100} packetColor={colors.gold} />

        {/* 右侧: 标准化交付产物卡片 */}
        <div style={{ position: 'relative' }}>
          <ContractCard
            title="STANDARDIZED ARTIFACT"
            contractName="dataset.json"
            type="output"
            properties={outputProps}
            enterFrame={380}
            width={450}
            height={550}
            badgeText="STAGE 1 COMPLETE"
            badgeColor={colors.success}
          />

          {/* 盖章动效 */}
          <div style={{ position: 'absolute', bottom: 40, right: 30 }}>
            <AnimatedBadge
              text="FUSED & SEALED"
              subtext="913 RECORDS READY"
              enterFrame={430}
              color={colors.gold}
              angle={-10}
            />
          </div>
        </div>
      </div>
    </PaperBackground>
  );
};
