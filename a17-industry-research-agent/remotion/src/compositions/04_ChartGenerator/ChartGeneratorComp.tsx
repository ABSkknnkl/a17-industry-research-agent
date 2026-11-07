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

export const ChartGeneratorComp: React.FC = () => {
  const frame = useCurrentFrame();

  // Part 1: 输入契约 (源自 Stage 2 产物与用户 15 张图表配额诉求)
  const inputProps: ContractProperty[] = [
    { key: 'input_report', value: '"interpretation_report.json"' },
    { key: 'requested_chart_count', value: '15 Charts Configured', highlight: true },
    { key: 'chart_families', value: 'Cartesian / Non-Cartesian / Topology' },
    { key: 'target_resolution', value: '960 × 520 CICC/Institutional Vector' },
    { key: 'render_pipeline', value: 'ECharts 5 + Pure Python SVG Engine' },
    { key: 'morphing_support', value: 'Line / Bar / Radar Multi-morphing' },
  ];

  // Part 2: 核心引擎与质检拦截 (严格对齐 compiler.py, render.py, metric_guard.py)
  const engineItems: EngineItem[] = [
    {
      name: 'ChartPlanner 智能场景匹配',
      desc: '自适应规划装机量折线预测、成熟度雷达、龙头对标条形与产业链拓扑',
      result: '15 Charts Planned',
      active: frame >= 120,
      statusText: frame >= 180 ? 'PLANNED' : 'ANALYZING',
    },
    {
      name: '纯 Python 几何矢量渲染器 (render.py)',
      desc: '纯 Python 数学几何引擎计算 Bezier 路径与版心排版，无须重量级浏览器渲染',
      result: '15 SVGs Rendered',
      active: frame >= 180,
      statusText: frame >= 260 ? 'VECTOR RENDER' : 'RENDERING',
    },
    {
      name: 'MetricGuard 金融质检拦截器',
      desc: '严格拦截同轴单位混用 (禁止同一 Y 轴混排“亿元”与“%”)，长标签防重叠旋转',
      result: '0 Conflicts',
      active: frame >= 260,
      statusText: frame >= 340 ? 'GUARD PASSED' : 'INSPECTING',
    },
    {
      name: '图表可塑型转换 (Chart Morphing) & 补数',
      desc: '前端无损切换图表形态；当图表数存在缺口时自动逆向触发 Stage 1 补数',
      result: 'Quota 15/15',
      active: frame >= 340,
      statusText: frame >= 420 ? 'COMPLETE' : 'CHECKING',
    },
  ];

  // Part 3: 输出契约产物 (严格对应真实落盘 chart_result.json 与 15 张 SVG 矢量文件)
  const outputProps: ContractProperty[] = [
    { key: 'contract_id', value: '"chart_result.json" (61 KB)' },
    { key: 'svg_vectors_count', value: '15 Publication SVGs', highlight: true },
    { key: 'echarts_interactive', value: '15 JSON Option Bundles' },
    { key: 'artifacts_path', value: '"data/runs/.../charts/*.svg"' },
    { key: 'metric_guard_status', value: '100% Interception-Free' },
    { key: 'render_fidelity', value: 'CICC/Top-Tier Institutional Palette' },
  ];

  const isLoopActive = frame >= 380 && frame <= 480;

  return (
    <PaperBackground watermarkText="STAGE 3: 15-SVG VECTOR GENERATOR & METRIC GUARD">
      <ReportHeader
        title="图表生成智能体微观拆解"
        subtitle="15 组金融矢量图表全矩阵规划 · 纯 Python 几何渲染、MetricGuard 与图表可塑型"
        stageBadge="CHART GENERATOR & GUARD"
        stageNumber="03"
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
          title="INPUT REPORT"
          contractName="interpretation_report.json"
          type="input"
          properties={inputProps}
          enterFrame={0}
          width={450}
          height={550}
          badgeText="STAGE 2 ASSET"
          badgeColor={colors.navyLight}
        />

        <FlowConnector label="COMPILE" width={100} />

        {/* 中间: 双通道渲染与 MetricGuard 引擎 */}
        <div style={{ position: 'relative' }}>
          <EngineBox
            title="双通道图表编译器与质检卫士"
            engineCodeName="EChartsCompiler & Python SVGRenderer"
            items={engineItems}
            enterFrame={90}
            width={720}
            height={550}
            badge="PUBLICATION VECTOR ENGINE"
          />

          {/* 浮动特写：真实落盘 15 张图表与质检信息 */}
          {isLoopActive && (
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
                boxShadow: '0 8px 24px rgba(0,0,0,0.35)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                fontFamily: typography.mono,
                fontSize: 12,
                border: `1px solid ${colors.gold}`,
              }}
            >
              <div>
                <strong>[PURE PYTHON VECTOR COMPILATION]</strong>
                <div style={{ marginTop: 2, fontSize: 11, opacity: 0.9 }}>
                  15 组 960×520 矢量图全部由纯 Python 数学引擎独立渲染落盘于 charts/*.svg
                </div>
              </div>
              <span style={{ backgroundColor: colors.gold, color: colors.navyDark, fontWeight: 700, padding: '3px 8px', borderRadius: 2 }}>
                15 SVGS READY
              </span>
            </div>
          )}
        </div>

        <FlowConnector label="RENDER & SEAL" width={100} packetColor={colors.gold} />

        {/* 右侧: 图表资产清单产出卡片 */}
        <div style={{ position: 'relative' }}>
          <ContractCard
            title="STANDARDIZED ARTIFACT"
            contractName="chart_result.json"
            type="output"
            properties={outputProps}
            enterFrame={380}
            width={450}
            height={550}
            badgeText="STAGE 3 COMPLETE"
            badgeColor={colors.success}
          />

          <div style={{ position: 'absolute', bottom: 40, right: 30 }}>
            <AnimatedBadge
              text="15 SVGS VERIFIED"
              subtext="METRICGUARD ZERO-CLASH"
              enterFrame={430}
              color={colors.success}
              angle={-10}
            />
          </div>
        </div>
      </div>
    </PaperBackground>
  );
};
