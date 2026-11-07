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

export const DataInterpreterComp: React.FC = () => {
  const frame = useCurrentFrame();

  // Part 1: 输入契约 (源自 Stage 1 落盘产物 dataset.json)
  const inputProps: ContractProperty[] = [
    { key: 'source_contract', value: '"dataset.json" (3.5 MB)' },
    { key: 'raw_records', value: '913 Items Indexed', highlight: true },
    { key: 'tracked_universe', value: '宁德时代 / 亿纬锂能 / 国轩高科 / 当升科技' },
    { key: 'historical_window', value: '近 3 年年度 + 2026 最新中报' },
    { key: 'financial_matrices', value: '资产负债表 · 利润表 · 现金流量表' },
    { key: 'clean_status', value: 'NORMALIZED' },
  ];

  // Part 2: 内部量化方法论算法引擎 (严格对齐 engine.py 源码实现)
  const engineItems: EngineItem[] = [
    {
      name: 'DeterministicEngine._trends()',
      desc: '历史复合年均增长率(CAGR)与渗透率S曲线定量测算，定位固态电池产业周期',
      result: 'CAGR: +38.5%',
      active: frame >= 120,
      statusText: frame >= 180 ? 'DETERMINISTIC' : 'COMPUTING',
    },
    {
      name: 'Robust MAD / Z-Score 异动检测',
      desc: '识别出亿纬锂能净现背离：净利润 33 亿元但经营现金流为 -3.88 亿元',
      result: 'Anomaly: High',
      active: frame >= 180,
      statusText: frame >= 260 ? 'DETECTED' : 'SCANNING',
    },
    {
      name: 'build_peer_comps_matrix() & 杜邦拆解',
      desc: '同行对标：宁德时代 PE(TTM) 15.7倍(行业中位16.8倍)，ROE 24.9%，净利率 15.6%',
      result: 'Comps Mapped',
      active: frame >= 260,
      statusText: frame >= 340 ? 'BENCHMARKED' : 'ANALYZING',
    },
    {
      name: 'extract_industry_chain() & 证据索引生成',
      desc: '电解质/正负极➔电芯制造➔车端应用；为每个量化事实构建哈希索引 R-xxx',
      result: '38 Evidence Cards',
      active: frame >= 340,
      statusText: frame >= 400 ? 'STRICT GROUND' : 'EXTRACTING',
    },
  ];

  // Part 3: 输出契约产物 (严格对应真实落盘 interpretation_report.json)
  const outputProps: ContractProperty[] = [
    { key: 'contract_id', value: '"interpretation_report.json" (377 KB)' },
    { key: 'evidence_index_count', value: '38 Grounded Evidence Cards', highlight: true },
    { key: 'hash_key_format', value: 'R-4e6f98b933037bf19709' },
    { key: 'reconciliation_result', value: '宁德时代净现比 1.85 (>=1 达标)' },
    { key: 'peer_comps_matrix', value: 'PE / PB / ROE / 市值分位数全量就绪' },
    { key: 'chain_profit_margins', value: '上游材料 28%~35% · 中游电芯 15%~22%' },
  ];

  return (
    <PaperBackground watermarkText="STAGE 2: 7-METHODOLOGY DETERMINISTIC ENGINE">
      <ReportHeader
        title="数据解读智能体微观拆解"
        subtitle="7 大专属行研量化方法论 · 杜邦拆解、同行矩阵对标与确定性证据索引池"
        stageBadge="DETERMINISTIC INTERPRETER"
        stageNumber="02"
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
          title="INPUT DATASET"
          contractName="dataset.json"
          type="input"
          properties={inputProps}
          enterFrame={0}
          width={450}
          height={550}
          badgeText="STAGE 1 ASSET"
          badgeColor={colors.navyLight}
        />

        <FlowConnector label="QUANT ANALYZE" width={100} />

        {/* 中间: 确定性量化方法论算法引擎 */}
        <div style={{ position: 'relative' }}>
          <EngineBox
            title="7 大确定性行研量化方法论引擎"
            engineCodeName="DeterministicEngine & CompsMatrix"
            items={engineItems}
            enterFrame={90}
            width={720}
            height={550}
            badge="ZERO-HALLUCINATION ENGINE"
          />

          {/* 浮动特写：真实落盘事实与异常检测条 */}
          {frame >= 260 && frame <= 460 && (
            <div
              style={{
                position: 'absolute',
                bottom: 60,
                left: 30,
                right: 30,
                backgroundColor: colors.card,
                border: `1.5px solid ${colors.gold}`,
                borderRadius: 4,
                padding: '10px 16px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                fontFamily: typography.mono,
                fontSize: 12,
                boxShadow: '0 4px 16px rgba(169,133,63,0.15)',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ color: colors.gold, fontSize: 16 }}>★</span>
                <strong style={{ color: colors.navy }}>EVIDENCE GROUNDING:</strong>
                <span>CATL PE 15.7x · ROE 24.9% · 38 R-xxx Evidence Bound</span>
              </div>
              <span style={{ color: colors.success, fontWeight: 700 }}>STRICT AUDIT</span>
            </div>
          )}
        </div>

        <FlowConnector label="EVIDENCE POOL" width={100} packetColor={colors.gold} />

        {/* 右侧: 解读报告产出卡片 */}
        <div style={{ position: 'relative' }}>
          <ContractCard
            title="STANDARDIZED ARTIFACT"
            contractName="interpretation_report.json"
            type="output"
            properties={outputProps}
            enterFrame={380}
            width={450}
            height={550}
            badgeText="STAGE 2 COMPLETE"
            badgeColor={colors.success}
          />

          <div style={{ position: 'absolute', bottom: 40, right: 30 }}>
            <AnimatedBadge
              text="38 EVIDENCE CARDS"
              subtext="GROUNDED ZERO-HALLUCINATION"
              enterFrame={430}
              color={colors.success}
              angle={-8}
            />
          </div>
        </div>
      </div>
    </PaperBackground>
  );
};
