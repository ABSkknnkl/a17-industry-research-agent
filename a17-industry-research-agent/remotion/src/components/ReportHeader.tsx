import React from 'react';
import { interpolate, useCurrentFrame, useVideoConfig } from 'remotion';
import { colors } from '../theme/colors';
import { typography } from '../theme/typography';

interface ReportHeaderProps {
  title: string;
  subtitle: string;
  stageBadge?: string;
  stageNumber?: string;
}

export const ReportHeader: React.FC<ReportHeaderProps> = ({
  title,
  subtitle,
  stageBadge = 'STAGE ARCHITECTURE',
  stageNumber = '01',
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // 顶部标题平滑淡入 + 微微位移
  const opacity = interpolate(frame, [0, 15], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const translateY = interpolate(frame, [0, 15], [-20, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  // 呼吸状态指示灯
  const pulse = Math.sin((frame / fps) * Math.PI * 2) * 0.3 + 0.7;

  return (
    <div
      style={{
        position: 'absolute',
        top: 48,
        left: 64,
        right: 64,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        borderBottom: `2px solid ${colors.navy}`,
        paddingBottom: 16,
        opacity,
        transform: `translateY(${translateY}px)`,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 20 }}>
        {/* 阶段编号徽章 */}
        <div
          style={{
            backgroundColor: colors.navy,
            color: colors.card,
            padding: '6px 14px',
            borderRadius: 3,
            fontSize: 16,
            fontWeight: 700,
            fontFamily: typography.mono,
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            boxShadow: '0 2px 6px rgba(30,58,92,0.18)',
          }}
        >
          <span style={{ color: colors.goldLight }}>STAGE</span>
          <span style={{ fontSize: 18 }}>{stageNumber}</span>
        </div>

        {/* 标题与副标题 */}
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <h1
              style={{
                margin: 0,
                fontSize: 32,
                fontFamily: typography.serif,
                fontWeight: 700,
                color: colors.navy,
                letterSpacing: 0.8,
              }}
            >
              {title}
            </h1>
            <span
              style={{
                backgroundColor: colors.goldUltralight,
                border: `1px solid ${colors.goldLight}`,
                color: colors.gold,
                fontSize: 12,
                fontWeight: 600,
                padding: '2px 8px',
                borderRadius: 2,
                fontFamily: typography.mono,
              }}
            >
              {stageBadge}
            </span>
          </div>
          <div
            style={{
              fontSize: 14,
              color: colors.inkMuted,
              marginTop: 4,
              fontWeight: 400,
            }}
          >
            {subtitle}
          </div>
        </div>
      </div>

      {/* 右侧系统运行指标与绿灯 */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 16,
          backgroundColor: colors.card,
          border: `1px solid ${colors.line}`,
          padding: '8px 16px',
          borderRadius: 4,
          boxShadow: '0 1px 4px rgba(0,0,0,0.04)',
        }}
      >
        <div
          style={{
            width: 10,
            height: 10,
            borderRadius: '50%',
            backgroundColor: colors.success,
            opacity: pulse,
            boxShadow: `0 0 8px ${colors.success}`,
          }}
        />
        <div style={{ fontSize: 13, fontFamily: typography.mono }}>
          <span style={{ color: colors.inkMuted }}>STATUS: </span>
          <strong style={{ color: colors.success }}>RUNNING / SYNCHRONIZED</strong>
        </div>
        <div style={{ width: 1, height: 16, backgroundColor: colors.line }} />
        <div style={{ fontSize: 13, fontFamily: typography.mono, color: colors.ink }}>
          <span>T+{(frame / fps).toFixed(1)}s</span>
        </div>
      </div>
    </div>
  );
};
