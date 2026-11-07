import React from 'react';
import { Easing, interpolate, useCurrentFrame } from 'remotion';
import { PaperBackground } from '../../components/PaperBackground';
import { ReportHeader } from '../../components/ReportHeader';
import { AnimatedBadge } from '../../components/AnimatedBadge';
import { colors } from '../../theme/colors';
import { typography } from '../../theme/typography';

export const OverviewComp: React.FC = () => {
  const frame = useCurrentFrame();

  // 阶段 1: 0~120 帧 (0~4s) 标题与系统定位展开
  // 阶段 2: 120~300 帧 (4~10s) 四层拓扑展开
  // 阶段 3: 300~780 帧 (10~26s) 五智能体流水线穿梭 + 补数回路
  // 阶段 4: 780~930 帧 (26~31s) 终态研报成果爆发
  // 阶段 5: 930~1050 帧 (31~35s) 全景定格收拢

  // 1. 四层架构卡片进入动画 (120~220帧)
  const layer1Opacity = interpolate(frame, [120, 140], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  const layer2Opacity = interpolate(frame, [140, 160], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  const layer3Opacity = interpolate(frame, [160, 180], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  const layer4Opacity = interpolate(frame, [180, 200], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });

  // 2. 5大智能体流水线各节点的高亮时机
  const agent1Active = frame >= 300 && frame < 400;
  const agent2Active = frame >= 400 && frame < 500;
  const agent3Active = frame >= 500 && frame < 650;
  const agent4Active = frame >= 650 && frame < 730;
  const agent5Active = frame >= 730 && frame < 820;

  // 3. 补数回路反向激活 (560~620帧: Stage 3 逆向回传至 Stage 1)
  const feedbackActive = frame >= 560 && frame <= 630;

  // 4. 终态成果卡片展开 (780~860帧)
  const finalReportScale = interpolate(frame, [780, 810], [0.8, 1], {
    easing: Easing.bezier(0.16, 1, 0.3, 1),
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const finalReportOpacity = interpolate(frame, [780, 800], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  // 5大智能体名称 (严格映射 real code 与 runtime 规范)
  const stages = [
    { num: '01', id: 'DataFetcher', name: '数据获取智能体', desc: '20大问财Skill / DAG自愈 / 913条', contract: 'dataset.json (3.5MB)' },
    { num: '02', id: 'DataInterpreter', name: '数据解读智能体', desc: '7大量化引擎 / 杜邦拆解 / 38证据卡', contract: 'interpretation_report.json' },
    { num: '03', id: 'ChartGenerator', name: '图表生成智能体', desc: '15组纯Python矢量SVG / MetricGuard', contract: 'chart_result.json + 15 SVGs' },
    { num: '04', id: 'ChapterWriter', name: '章节撰写智能体', desc: '7章21节 (OUTLINE 2026.1) / 1.35万字', contract: 'chapter_result.json' },
    { num: '05', id: 'ReportFusion', name: '报告融合智能体', desc: '4大主编审校 / 95分卓越 / Playwright', contract: 'report.pdf / html / md' },
  ];

  return (
    <PaperBackground watermarkText="SYSTEM OVERVIEW & FULL-CYCLE PIPELINE">
      {/* 顶部标题栏 */}
      <ReportHeader
        title="五智能体全链路架构全景"
        subtitle="确定性量化引擎与基座大模型深度融合 · 跨智能体协同与质量自愈回路"
        stageBadge="SYSTEM OVERVIEW"
        stageNumber="ALL"
      />

      {/* 主体架构图画幅 */}
      <div
        style={{
          position: 'absolute',
          top: 150,
          left: 64,
          right: 64,
          bottom: 60,
          display: 'flex',
          flexDirection: 'column',
          gap: 16,
        }}
      >
        {/* Layer 1: 前端交互工作台 */}
        <div
          style={{
            height: 95,
            backgroundColor: colors.card,
            border: `1.5px solid ${colors.line}`,
            borderRadius: 6,
            padding: '12px 24px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            opacity: layer1Opacity,
            boxShadow: '0 2px 8px rgba(0,0,0,0.03)',
          }}
        >
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{ fontSize: 13, fontFamily: typography.mono, color: colors.gold, fontWeight: 700 }}>
                LAYER 01 // FRONTEND
              </span>
              <strong style={{ fontSize: 16, color: colors.navy }}>前端交互工作台 (Vue 3 + Vite + ECharts)</strong>
            </div>
            <div style={{ fontSize: 12, color: colors.inkMuted, marginTop: 4 }}>
              实时驾驶舱 AgentLiveCockpit · 人机反馈台 FeedbackWorkbench · 研报图表画廊 ChartGallery · 在线长图阅读器
            </div>
          </div>
          <div style={{ display: 'flex', gap: 10 }}>
            {['AgentLiveCockpit', 'FeedbackWorkbench', 'ReportReader'].map((tab, idx) => (
              <div
                key={idx}
                style={{
                  padding: '4px 10px',
                  backgroundColor: '#f2f0ea',
                  border: `1px solid ${colors.line}`,
                  borderRadius: 3,
                  fontSize: 11,
                  fontFamily: typography.mono,
                  color: colors.inkLight,
                }}
              >
                {tab}
              </div>
            ))}
          </div>
        </div>

        {/* Layer 2: 编排与服务网关 */}
        <div
          style={{
            height: 85,
            backgroundColor: colors.card,
            border: `1.5px solid ${colors.line}`,
            borderRadius: 6,
            padding: '10px 24px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            opacity: layer2Opacity,
            boxShadow: '0 2px 8px rgba(0,0,0,0.03)',
          }}
        >
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{ fontSize: 13, fontFamily: typography.mono, color: colors.gold, fontWeight: 700 }}>
                LAYER 02 // GATEWAY
              </span>
              <strong style={{ fontSize: 16, color: colors.navy }}>服务网关与状态机编排层 (FastAPI + SSE)</strong>
            </div>
            <div style={{ fontSize: 12, color: colors.inkMuted, marginTop: 4 }}>
              FastAPI Router (15 Endpoints) · WorkflowEngine 状态机 · SSE 毫秒级双向事件广播 EventHub
            </div>
          </div>
          <div style={{ fontSize: 11, fontFamily: typography.mono, color: colors.success, backgroundColor: '#edf4ee', padding: '4px 10px', borderRadius: 3, border: `1px solid ${colors.successLight}` }}>
            SSE STREAMING ACTIVE
          </div>
        </div>

        {/* Layer 3: 五智能体核心流水线 (最核心区域，高度扩大) */}
        <div
          style={{
            flex: 1,
            backgroundColor: '#faf8f3',
            border: `2px solid ${colors.navy}`,
            borderRadius: 8,
            padding: '16px 20px',
            display: 'flex',
            flexDirection: 'column',
            position: 'relative',
            opacity: layer3Opacity,
            boxShadow: '0 8px 24px rgba(30,58,92,0.06)',
          }}
        >
          {/* 流水线标头 */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <span style={{ fontSize: 13, fontFamily: typography.mono, color: colors.navy, fontWeight: 700, backgroundColor: colors.goldUltralight, padding: '3px 8px', borderRadius: 3 }}>
                LAYER 03 // 5-STAGE MULTI-AGENT PIPELINE
              </span>
              <strong style={{ fontSize: 18, color: colors.navy, fontFamily: typography.serif }}>
                五智能体执行流水线与数据契约流转
              </strong>
            </div>
            <div style={{ fontSize: 12, fontFamily: typography.mono, color: colors.inkMuted }}>
              CONTRACTS: DATASET ➔ INTERPRETATION ➔ CHARTS ➔ CHAPTERS ➔ FUSION
            </div>
          </div>

          {/* 5 个智能体横向节点卡片 */}
          <div style={{ display: 'flex', alignItems: 'stretch', justifyContent: 'space-between', gap: 12, flex: 1, position: 'relative' }}>
            {stages.map((stage, idx) => {
              const isActive = [agent1Active, agent2Active, agent3Active, agent4Active, agent5Active][idx];
              const isPast = (idx === 0 && frame >= 400) ||
                             (idx === 1 && frame >= 500) ||
                             (idx === 2 && frame >= 650) ||
                             (idx === 3 && frame >= 730) ||
                             (idx === 4 && frame >= 820);

              const borderColor = isActive ? colors.gold : isPast ? colors.success : colors.line;
              const bgColor = isActive ? '#fffcf5' : colors.card;
              const shadow = isActive ? '0 8px 20px rgba(169,133,63,0.22)' : '0 2px 6px rgba(0,0,0,0.04)';

              return (
                <div
                  key={stage.id}
                  style={{
                    flex: 1,
                    backgroundColor: bgColor,
                    border: `1.5px solid ${borderColor}`,
                    borderRadius: 6,
                    padding: '14px 14px',
                    display: 'flex',
                    flexDirection: 'column',
                    justifyContent: 'space-between',
                    boxShadow: shadow,
                    position: 'relative',
                  }}
                >
                  <div>
                    {/* 卡片头部编号与状态 */}
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
                      <span
                        style={{
                          fontSize: 11,
                          fontFamily: typography.mono,
                          fontWeight: 700,
                          backgroundColor: isActive ? colors.gold : colors.navy,
                          color: '#fff',
                          padding: '2px 6px',
                          borderRadius: 2,
                        }}
                      >
                        STAGE {stage.num}
                      </span>
                      {isPast && (
                        <span style={{ fontSize: 11, color: colors.success, fontFamily: typography.mono, fontWeight: 700 }}>
                          ✓ PASS
                        </span>
                      )}
                      {isActive && (
                        <span style={{ fontSize: 11, color: colors.gold, fontFamily: typography.mono, fontWeight: 700 }}>
                          ● RUN
                        </span>
                      )}
                    </div>

                    <div style={{ fontSize: 15, fontWeight: 700, color: colors.navy, marginBottom: 4 }}>
                      {stage.name}
                    </div>
                    <div style={{ fontSize: 11, color: colors.inkMuted, lineHeight: 1.4 }}>
                      {stage.desc}
                    </div>
                  </div>

                  {/* 产出数据契约标签 */}
                  <div
                    style={{
                      marginTop: 12,
                      padding: '6px 8px',
                      backgroundColor: '#f5f3ec',
                      borderRadius: 3,
                      border: `1px solid ${colors.line}`,
                      fontSize: 10,
                      fontFamily: typography.mono,
                      color: colors.navyLight,
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    契约: {stage.contract}
                  </div>
                </div>
              );
            })}

            {/* 跨智能体反向补数回路动效 (Stage 3 回调 Stage 1) */}
            {feedbackActive && (
              <div
                style={{
                  position: 'absolute',
                  top: -24,
                  left: 80,
                  right: 480,
                  height: 36,
                  pointerEvents: 'none',
                }}
              >
                <svg width="100%" height="36" style={{ overflow: 'visible' }}>
                  <path
                    d="M 540 10 C 350 -20, 180 -20, 30 10"
                    fill="none"
                    stroke={colors.warning}
                    strokeWidth="2.5"
                    strokeDasharray="6 4"
                  />
                  <polygon points="20,12 30,5 30,19" fill={colors.warning} />
                </svg>
                <div
                  style={{
                    position: 'absolute',
                    top: -16,
                    left: '40%',
                    backgroundColor: colors.warning,
                    color: '#fff',
                    fontSize: 10,
                    fontFamily: typography.mono,
                    fontWeight: 700,
                    padding: '2px 8px',
                    borderRadius: 2,
                    boxShadow: '0 2px 6px rgba(0,0,0,0.15)',
                  }}
                >
                  FEEDBACK LOOP: STAGE 3 ➔ STAGE 1 定向补数
                </div>
              </div>
            )}
          </div>

          {/* 终态研报成果爆发悬浮卡片 (780帧之后出现) */}
          {frame >= 780 && (
            <div
              style={{
                position: 'absolute',
                top: 50,
                left: 100,
                right: 100,
                bottom: 30,
                backgroundColor: 'rgba(255, 254, 251, 0.96)',
                backdropFilter: 'blur(8px)',
                border: `2px solid ${colors.gold}`,
                borderRadius: 8,
                padding: '24px 36px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                boxShadow: '0 16px 40px rgba(30,58,92,0.2)',
                opacity: finalReportOpacity,
                transform: `scale(${finalReportScale})`,
              }}
            >
              <div>
                <span style={{ fontSize: 12, fontFamily: typography.mono, color: colors.gold, fontWeight: 700 }}>
                  DELIVERY // FINAL OUTPUT ARTIFACTS
                </span>
                <h2 style={{ margin: '4px 0 8px', fontSize: 26, fontFamily: typography.serif, color: colors.navy }}>
                  五智能体协同交付完成 · 顶级券商研报就绪
                </h2>
                <div style={{ display: 'flex', gap: 24, fontSize: 14, color: colors.inkLight }}>
                  <div>• 深度文本: <strong>13,500+ 字</strong> (7章21节)</div>
                  <div>• 出版图表: <strong>15 组</strong> (纯Python SVG矢量+ECharts)</div>
                  <div>• 质量打分: <strong>95 分</strong> (卓越级 · 0冲突)</div>
                </div>
              </div>

              {/* 三大格式产物 */}
              <div style={{ display: 'flex', gap: 14 }}>
                {[
                  { name: 'report.md', desc: 'Markdown 源码', tag: 'ARCHIVE' },
                  { name: 'report.html', desc: '交互式画廊长图', tag: 'WEB VIEW' },
                  { name: 'report.pdf', desc: '出版级 A4 矢量', tag: 'PRINT A4' },
                ].map((item, idx) => (
                  <div
                    key={idx}
                    style={{
                      border: `1.5px solid ${colors.navy}`,
                      backgroundColor: colors.card,
                      borderRadius: 4,
                      padding: '10px 16px',
                      textAlign: 'center',
                    }}
                  >
                    <div style={{ fontSize: 13, fontFamily: typography.mono, fontWeight: 700, color: colors.navy }}>
                      {item.name}
                    </div>
                    <div style={{ fontSize: 11, color: colors.inkMuted, marginTop: 2 }}>{item.desc}</div>
                    <span style={{ fontSize: 9, fontFamily: typography.mono, color: colors.gold, fontWeight: 700 }}>
                      {item.tag}
                    </span>
                  </div>
                ))}
              </div>

              {/* 盖章 */}
              <AnimatedBadge
                text="INSTITUTIONAL GRADE"
                subtext="APPROVED ★★★★★"
                enterFrame={810}
                color={colors.gold}
                size="large"
                angle={-8}
              />
            </div>
          )}
        </div>

        {/* Layer 4: 外部生态与底层基座 */}
        <div
          style={{
            height: 75,
            backgroundColor: colors.card,
            border: `1.5px solid ${colors.line}`,
            borderRadius: 6,
            padding: '10px 24px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            opacity: layer4Opacity,
            boxShadow: '0 2px 8px rgba(0,0,0,0.03)',
          }}
        >
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{ fontSize: 13, fontFamily: typography.mono, color: colors.gold, fontWeight: 700 }}>
                LAYER 04 // FOUNDATION
              </span>
              <strong style={{ fontSize: 16, color: colors.navy }}>外部生态与底层推理基座</strong>
            </div>
            <div style={{ fontSize: 12, color: colors.inkMuted, marginTop: 4 }}>
              同花顺问财 SkillHub OpenAPI (7大技能集) · 火山引擎 DeepSeek V4 Flash (64K 语义推理上下文)
            </div>
          </div>
          <div style={{ display: 'flex', gap: 10 }}>
            <span style={{ fontSize: 11, fontFamily: typography.mono, color: colors.navy, backgroundColor: '#edf3f9', padding: '3px 8px', borderRadius: 2 }}>
              HITHINK OPENAPI
            </span>
            <span style={{ fontSize: 11, fontFamily: typography.mono, color: colors.navy, backgroundColor: '#edf3f9', padding: '3px 8px', borderRadius: 2 }}>
              VOLCENGINE ARK
            </span>
          </div>
        </div>
      </div>
    </PaperBackground>
  );
};
