import React from 'react';
import { AbsoluteFill } from 'remotion';
import { colors } from '../theme/colors';
import { typography } from '../theme/typography';

interface PaperBackgroundProps {
  children?: React.ReactNode;
  watermarkText?: string;
}

export const PaperBackground: React.FC<PaperBackgroundProps> = ({
  children,
  watermarkText = 'HITHINK ROBOT MULTI-AGENT ARCHITECTURE',
}) => {
  return (
    <AbsoluteFill
      style={{
        backgroundColor: colors.paper,
        fontFamily: typography.sans,
        color: colors.ink,
        overflow: 'hidden',
      }}
    >
      {/* 研报纸张经纬网格背景 */}
      <svg
        width="100%"
        height="100%"
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          opacity: 0.35,
          pointerEvents: 'none',
        }}
      >
        <defs>
          <pattern
            id="paper-grid"
            width="60"
            height="60"
            patternUnits="userSpaceOnUse"
          >
            <path
              d="M 60 0 L 0 0 0 60"
              fill="none"
              stroke={colors.line}
              strokeWidth="0.8"
            />
            {/* 网格交叉微十字 */}
            <circle cx="0" cy="0" r="1.5" fill={colors.gold} opacity="0.6" />
          </pattern>
        </defs>
        <rect width="100%" height="100%" fill="url(#paper-grid)" />
      </svg>

      {/* 研报出版版心外边框线与四个角标 */}
      <div
        style={{
          position: 'absolute',
          top: 24,
          left: 24,
          right: 24,
          bottom: 24,
          border: `1px solid ${colors.line}`,
          pointerEvents: 'none',
          boxSizing: 'border-box',
        }}
      >
        {/* 左上角标 */}
        <div
          style={{
            position: 'absolute',
            top: -1,
            left: -1,
            width: 24,
            height: 24,
            borderTop: `3px solid ${colors.gold}`,
            borderLeft: `3px solid ${colors.gold}`,
          }}
        />
        {/* 右上角标 */}
        <div
          style={{
            position: 'absolute',
            top: -1,
            right: -1,
            width: 24,
            height: 24,
            borderTop: `3px solid ${colors.gold}`,
            borderRight: `3px solid ${colors.gold}`,
          }}
        />
        {/* 左下角标 */}
        <div
          style={{
            position: 'absolute',
            bottom: -1,
            left: -1,
            width: 24,
            height: 24,
            borderBottom: `3px solid ${colors.gold}`,
            borderLeft: `3px solid ${colors.gold}`,
          }}
        />
        {/* 右下角标 */}
        <div
          style={{
            position: 'absolute',
            bottom: -1,
            right: -1,
            width: 24,
            height: 24,
            borderBottom: `3px solid ${colors.gold}`,
            borderRight: `3px solid ${colors.gold}`,
          }}
        />
      </div>

      {/* 背景深层透印水印 */}
      <div
        style={{
          position: 'absolute',
          bottom: 40,
          right: 48,
          fontSize: 14,
          fontFamily: typography.mono,
          letterSpacing: 2,
          color: colors.lineDark,
          opacity: 0.6,
          pointerEvents: 'none',
        }}
      >
        {watermarkText} · SPEC v2.4
      </div>

      {/* 顶部微观坐标 */}
      <div
        style={{
          position: 'absolute',
          top: 32,
          right: 48,
          fontSize: 12,
          fontFamily: typography.mono,
          color: colors.inkMuted,
          opacity: 0.7,
          pointerEvents: 'none',
        }}
      >
        SYSTEM COCKPIT // 1080P 30FPS // FASTAPI · VOLCENGINE · SKILLHUB
      </div>

      {/* 主视图插槽 */}
      <div style={{ position: 'relative', width: '100%', height: '100%' }}>
        {children}
      </div>
    </AbsoluteFill>
  );
};
