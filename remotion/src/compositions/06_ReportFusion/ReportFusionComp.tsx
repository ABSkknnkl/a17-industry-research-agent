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

export const ReportFusionComp: React.FC = () => {
  const frame = useCurrentFrame();

  // Part 1: 输入契约 (源自前序所有阶段真实落盘资产清单)
  const inputProps: ContractProperty[] = [
    { key: 'input_chapters', value: '7 Chapters / 21 Sections (153 KB)' },
    { key: 'input_charts', value: '15 Publication SVGs (61 KB)', highlight: true },
    { key: 'evidence_chain', value: '38 Grounded R-xxx Evidence Cards' },
    { key: 'audit_spec', value: 'ConsistencyAudit + Jinja2 Templates' },
    { key: 'export_formats', value: 'Markdown / HTML / Playwright A4 PDF' },
    { key: 'quality_evaluator', value: 'QualityPanel Formula (Weights: 10/10/40/40)' },
  ];

  // Part 2: 4 大主编级审校技能与多模态编译 (严格对齐真实 consistency_report.json 与 pdf.py)
  const engineItems: EngineItem[] = [
    {
      name: 'ExecutiveSummary (高管核心摘要看板)',
      desc: '提炼固态电池“一超多强”格局，宁德时代 1.39 万亿市值绝对龙头及风险提示',
      result: 'Headline Ready',
      active: frame >= 120,
      statusText: frame >= 180 ? 'SUMMARIZED' : 'DISTILLING',
    },
    {
      name: 'ConsistencyAudit (全文事实交叉审计)',
      desc: '跨章节交叉扫描：19 项事实自动采纳，0 致命冲突，总市值 1.56 万亿元自动标定',
      result: '19 Edits Accepted',
      active: frame >= 180,
      statusText: frame >= 260 ? 'AUDITED 100%' : 'AUDITING',
    },
    {
      name: 'Typography & Jinja2 出版级模板编排',
      desc: '统一排版版心、封面、免责声明、自动目录导航及 15 组图文槽位自适应混排',
      result: 'Editorial Formatted',
      active: frame >= 260,
      statusText: frame >= 340 ? 'POLISHED' : 'TYPESETTING',
    },
    {
      name: 'Playwright A4 矢量 PDF 服务端打印 (pdf.py)',
      desc: '调度无头 Chromium 服务端离线光栅化，生成 4.5 MB 高保真出版级红头研报',
      result: 'PDF Exported (4.5M)',
      active: frame >= 340,
      statusText: frame >= 400 ? 'COMPILED' : 'PRINTING',
    },
  ];

  // Part 3: 输出契约产物 (严格对应真实落盘的多模态出版物)
  const outputProps: ContractProperty[] = [
    { key: 'format_1_markdown', value: '"report.md" (100 KB Source)', highlight: true },
    { key: 'format_2_html', value: '"report.html" (369 KB Interactive Web)' },
    { key: 'format_3_pdf', value: '"report.pdf" (4.5 MB Vector Print)' },
    { key: 'audit_log', value: '"consistency_report.json" (Passed)' },
    { key: 'comprehensive_score', value: '95 / 100 (Exceptional Grade)' },
    { key: 'system_status', value: '"completed" · All 5 Stages Approved' },
  ];

  return (
    <PaperBackground watermarkText="STAGE 5: REPORT FUSION & PLAYWRIGHT COMPILER">
      <ReportHeader
        title="报告融合智能体微观拆解"
        subtitle="四大主编级审校技能组 · 跨章节事实一致性交叉审计与 Playwright 出版级 PDF 打印"
        stageBadge="CHIEF FUSION AGENT"
        stageNumber="05"
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
          title="INPUT ALL ARTIFACTS"
          contractName="stage_artifacts.bundle"
          type="input"
          properties={inputProps}
          enterFrame={0}
          width={450}
          height={550}
          badgeText="ALL STAGES COMBINED"
          badgeColor={colors.navyLight}
        />

        <FlowConnector label="CHIEF AUDIT" width={100} />

        {/* 中间: 4 大主编审校技能组 */}
        <div style={{ position: 'relative' }}>
          <EngineBox
            title="四大主编级审校技能矩阵"
            engineCodeName="ReportFusion & ConsistencyAudit"
            items={engineItems}
            enterFrame={90}
            width={720}
            height={550}
            badge="EDITORIAL REVIEW PIPELINE"
          />

          {/* 浮动特写：真实落盘一致性审计与 95 分评分 */}
          {frame >= 260 && frame <= 460 && (
            <div
              style={{
                position: 'absolute',
                bottom: 60,
                left: 30,
                right: 30,
                backgroundColor: colors.card,
                border: `2px solid ${colors.gold}`,
                borderRadius: 4,
                padding: '10px 16px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                fontFamily: typography.mono,
                fontSize: 12,
                boxShadow: '0 4px 20px rgba(169,133,63,0.2)',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <span style={{ color: colors.gold, fontSize: 16 }}>★</span>
                <strong style={{ color: colors.navy }}>QUALITY SCORE:</strong>
                <span>Final Score: 95/100 (Chapters 10 + Structure 10 + Evidence 38 + Consistency 37)</span>
              </div>
              <span style={{ color: colors.success, fontWeight: 700 }}>GRADE: EXCEPTIONAL</span>
            </div>
          )}
        </div>

        <FlowConnector label="COMPILE & EXPORT" width={100} packetColor={colors.gold} />

        {/* 右侧: 多格式出版物清单产出卡片 */}
        <div style={{ position: 'relative' }}>
          <ContractCard
            title="STANDARDIZED ARTIFACT"
            contractName="final_report_suite"
            type="output"
            properties={outputProps}
            enterFrame={380}
            width={450}
            height={550}
            badgeText="STAGE 5 COMPLETE"
            badgeColor={colors.gold}
          />

          <div style={{ position: 'absolute', bottom: 40, right: 30 }}>
            <AnimatedBadge
              text="GRADE: 95 (★★★★★)"
              subtext="INSTITUTIONAL DELIVERED"
              enterFrame={430}
              color={colors.gold}
              size="large"
              angle={-10}
            />
          </div>
        </div>
      </div>
    </PaperBackground>
  );
};
