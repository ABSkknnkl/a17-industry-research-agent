import React from 'react';
import { Easing, interpolate, useCurrentFrame } from 'remotion';
import { colors } from '../theme/colors';
import { typography } from '../theme/typography';

export interface EngineItem {
  name: string;
  desc: string;
  result?: string;
  active?: boolean;
  statusText?: string;
}

interface EngineBoxProps {
  title: string;
  engineCodeName: string;
  items: EngineItem[];
  enterFrame?: number;
  width?: number;
  height?: number;
  badge?: string;
}

export const EngineBox: React.FC<EngineBoxProps> = ({
  title,
  engineCodeName,
  items,
  enterFrame = 0,
  width = 680,
  height = 540,
  badge = 'CORE ENGINE',
}) => {
  const frame = useCurrentFrame();

  const localFrame = Math.max(0, frame - enterFrame);
  const opacity = interpolate(localFrame, [0, 15], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const translateY = interpolate(localFrame, [0, 20], [25, 0], {
    easing: Easing.bezier(0.16, 1, 0.3, 1),
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const scale = interpolate(localFrame, [0, 20], [0.96, 1], {
    easing: Easing.bezier(0.16, 1, 0.3, 1),
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  // 齿轮微旋转动效 (纯帧驱动)
  const rotation = (frame * 2) % 360;

  return (
    <div
      style={{
        width,
        height,
        backgroundColor: colors.card,
        border: `2px solid ${colors.navy}`,
        borderRadius: 6,
        boxShadow: '0 12px 32px rgba(30,58,92,0.12), 0 2px 6px rgba(0,0,0,0.06)',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        position: 'relative',
        opacity,
        transform: `translateY(${translateY}px) scale(${scale})`,
      }}
    >
      {/* 头部引擎标识栏 */}
      <div
        style={{
          backgroundColor: colors.navyDark,
          color: colors.card,
          padding: '12px 20px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          {/* 旋转齿轮小动效 */}
          <div
            style={{
              width: 18,
              height: 18,
              border: `2px dashed ${colors.goldLight}`,
              borderRadius: '50%',
              transform: `rotate(${rotation}deg)`,
            }}
          />
          <span
            style={{
              fontFamily: typography.serif,
              fontSize: 16,
              fontWeight: 700,
              letterSpacing: 0.5,
            }}
          >
            {title}
          </span>
          <span
            style={{
              backgroundColor: 'rgba(255,255,255,0.15)',
              padding: '2px 8px',
              borderRadius: 2,
              fontSize: 11,
              fontFamily: typography.mono,
              color: colors.goldLight,
            }}
          >
            {engineCodeName}
          </span>
        </div>
        <div
          style={{
            fontSize: 11,
            fontFamily: typography.mono,
            color: colors.goldLight,
            letterSpacing: 1,
          }}
        >
          {badge}
        </div>
      </div>

      {/* 算子与流水线列表 */}
      <div
        style={{
          flex: 1,
          padding: '18px 24px',
          display: 'flex',
          flexDirection: 'column',
          gap: 14,
          overflow: 'hidden',
          backgroundColor: '#faf8f3',
        }}
      >
        {items.map((item, idx) => {
          const itemDelay = enterFrame + 10 + idx * 4;
          const itemLocal = Math.max(0, frame - itemDelay);
          const itemOpacity = interpolate(itemLocal, [0, 10], [0, 1], {
            extrapolateLeft: 'clamp',
            extrapolateRight: 'clamp',
          });
          const itemTranslateX = interpolate(itemLocal, [0, 12], [20, 0], {
            easing: Easing.bezier(0.16, 1, 0.3, 1),
            extrapolateLeft: 'clamp',
            extrapolateRight: 'clamp',
          });

          return (
            <div
              key={idx}
              style={{
                backgroundColor: colors.card,
                border: `1px solid ${item.active ? colors.navyLight : colors.line}`,
                borderRadius: 4,
                padding: '12px 16px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                boxShadow: item.active
                  ? '0 4px 12px rgba(30,58,92,0.08)'
                  : '0 1px 3px rgba(0,0,0,0.02)',
                opacity: itemOpacity,
                transform: `translateX(${itemTranslateX}px)`,
              }}
            >
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span
                    style={{
                      width: 6,
                      height: 6,
                      borderRadius: '50%',
                      backgroundColor: item.active ? colors.success : colors.gold,
                    }}
                  />
                  <span
                    style={{
                      fontFamily: typography.mono,
                      fontWeight: 700,
                      fontSize: 14,
                      color: colors.navy,
                    }}
                  >
                    {item.name}
                  </span>
                  {item.statusText && (
                    <span
                      style={{
                        fontSize: 11,
                        fontFamily: typography.mono,
                        padding: '1px 6px',
                        backgroundColor: '#edf4ee',
                        color: colors.success,
                        borderRadius: 2,
                        border: `1px solid ${colors.successLight}`,
                      }}
                    >
                      {item.statusText}
                    </span>
                  )}
                </div>
                <div
                  style={{
                    fontSize: 12,
                    color: colors.inkMuted,
                    marginTop: 4,
                    paddingLeft: 16,
                  }}
                >
                  {item.desc}
                </div>
              </div>

              {item.result && (
                <div
                  style={{
                    fontFamily: typography.mono,
                    fontSize: 14,
                    fontWeight: 700,
                    color: colors.gold,
                    backgroundColor: colors.goldUltralight,
                    padding: '4px 12px',
                    borderRadius: 3,
                    border: `1px solid ${colors.goldLight}`,
                  }}
                >
                  {item.result}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* 底部实时吞吐量与性能数据 */}
      <div
        style={{
          padding: '10px 20px',
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
        <span>LATENCY: &lt;120ms / DETERMINISTIC PIPELINE</span>
        <span style={{ color: colors.navy, fontWeight: 600 }}>VOLCENGINE DEEPSEEK V4 FLASH</span>
      </div>
    </div>
  );
};
