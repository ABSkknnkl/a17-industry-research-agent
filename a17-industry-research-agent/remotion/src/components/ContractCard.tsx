import React from 'react';
import { Easing, interpolate, useCurrentFrame } from 'remotion';
import { colors } from '../theme/colors';
import { typography } from '../theme/typography';

export interface ContractProperty {
  key: string;
  value: string;
  type?: 'string' | 'number' | 'array' | 'object' | 'badge';
  highlight?: boolean;
}

interface ContractCardProps {
  title: string;
  contractName: string;
  type: 'input' | 'output';
  properties: ContractProperty[];
  enterFrame?: number;
  width?: number;
  height?: number;
  badgeText?: string;
  badgeColor?: string;
}

export const ContractCard: React.FC<ContractCardProps> = ({
  title,
  contractName,
  type,
  properties,
  enterFrame = 0,
  width = 460,
  height = 540,
  badgeText,
  badgeColor = colors.success,
}) => {
  const frame = useCurrentFrame();

  // 延迟进入动画
  const localFrame = Math.max(0, frame - enterFrame);
  const opacity = interpolate(localFrame, [0, 15], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const translateY = interpolate(localFrame, [0, 20], [30, 0], {
    easing: Easing.bezier(0.16, 1, 0.3, 1),
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const scale = interpolate(localFrame, [0, 20], [0.94, 1], {
    easing: Easing.bezier(0.16, 1, 0.3, 1),
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  const isInput = type === 'input';
  const accentColor = isInput ? colors.navyLight : colors.gold;

  return (
    <div
      style={{
        width,
        height,
        backgroundColor: colors.card,
        border: `1.5px solid ${colors.lineDark}`,
        borderRadius: 6,
        boxShadow: '0 8px 24px rgba(30,58,92,0.08), 0 1px 3px rgba(0,0,0,0.05)',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        position: 'relative',
        opacity,
        transform: `translateY(${translateY}px) scale(${scale})`,
      }}
    >
      {/* 顶部标签栏 */}
      <div
        style={{
          backgroundColor: isInput ? '#edf3f9' : '#faf4ea',
          borderBottom: `1.5px solid ${colors.line}`,
          padding: '12px 18px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span
            style={{
              display: 'inline-block',
              width: 8,
              height: 8,
              borderRadius: '50%',
              backgroundColor: accentColor,
            }}
          />
          <span
            style={{
              fontSize: 12,
              fontFamily: typography.mono,
              fontWeight: 700,
              color: accentColor,
              letterSpacing: 0.5,
              textTransform: 'uppercase',
            }}
          >
            {title}
          </span>
        </div>
        <div
          style={{
            fontSize: 11,
            fontFamily: typography.mono,
            color: colors.inkMuted,
            backgroundColor: colors.card,
            padding: '2px 8px',
            borderRadius: 3,
            border: `1px solid ${colors.line}`,
          }}
        >
          JSON SCHEMA V2
        </div>
      </div>

      {/* 合约文件名与图标 */}
      <div
        style={{
          padding: '16px 20px 10px',
          borderBottom: `1px dashed ${colors.line}`,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}
      >
        <div>
          <div
            style={{
              fontSize: 20,
              fontFamily: typography.mono,
              fontWeight: 700,
              color: colors.navy,
            }}
          >
            {contractName}
          </div>
          <div style={{ fontSize: 12, color: colors.inkMuted, marginTop: 2 }}>
            Data Contract · Strongly Typed
          </div>
        </div>
        {badgeText && (
          <div
            style={{
              border: `1.5px solid ${badgeColor}`,
              color: badgeColor,
              fontSize: 11,
              fontFamily: typography.mono,
              fontWeight: 700,
              padding: '3px 8px',
              borderRadius: 3,
              letterSpacing: 0.5,
            }}
          >
            {badgeText}
          </div>
        )}
      </div>

      {/* 键值对列表展示 */}
      <div
        style={{
          flex: 1,
          padding: '16px 20px',
          display: 'flex',
          flexDirection: 'column',
          gap: 12,
          overflow: 'hidden',
          backgroundColor: '#fbfaf7',
        }}
      >
        {properties.map((prop, idx) => {
          const propDelay = enterFrame + 8 + idx * 3;
          const propLocal = Math.max(0, frame - propDelay);
          const propOpacity = interpolate(propLocal, [0, 8], [0, 1], {
            extrapolateLeft: 'clamp',
            extrapolateRight: 'clamp',
          });

          return (
            <div
              key={idx}
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '8px 12px',
                borderRadius: 4,
                backgroundColor: prop.highlight ? '#f4ece1' : colors.card,
                border: `1px solid ${prop.highlight ? colors.goldLight : colors.line}`,
                opacity: propOpacity,
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span
                  style={{
                    color: colors.navyLight,
                    fontFamily: typography.mono,
                    fontSize: 13,
                    fontWeight: 600,
                  }}
                >
                  "{prop.key}":
                </span>
              </div>
              <div
                style={{
                  fontFamily: typography.mono,
                  fontSize: 13,
                  fontWeight: 600,
                  color: prop.highlight ? colors.gold : colors.ink,
                }}
              >
                {prop.value}
              </div>
            </div>
          );
        })}
      </div>

      {/* 卡片底栏校验通过标记 */}
      <div
        style={{
          padding: '10px 18px',
          borderTop: `1px solid ${colors.line}`,
          backgroundColor: colors.card,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          fontSize: 12,
          fontFamily: typography.mono,
          color: colors.inkMuted,
        }}
      >
        <span>INTEGRITY VERIFIED</span>
        <span style={{ color: colors.success }}>✓ SHA-256 MATCH</span>
      </div>
    </div>
  );
};
