import React from 'react';
import { Easing, interpolate, useCurrentFrame } from 'remotion';
import { colors } from '../theme/colors';
import { typography } from '../theme/typography';

interface AnimatedBadgeProps {
  text: string;
  subtext?: string;
  enterFrame?: number;
  color?: string;
  size?: 'normal' | 'large';
  angle?: number;
}

export const AnimatedBadge: React.FC<AnimatedBadgeProps> = ({
  text,
  subtext = 'AUDITED',
  enterFrame = 0,
  color = colors.success,
  size = 'normal',
  angle = -12,
}) => {
  const frame = useCurrentFrame();

  const localFrame = Math.max(0, frame - enterFrame);

  // 盖印下落冲击动效 (从 2.5 倍缩放到 1.0 倍，带有微震荡)
  const scale = interpolate(localFrame, [0, 8, 14], [2.2, 0.95, 1], {
    easing: Easing.bezier(0.16, 1, 0.3, 1),
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const opacity = interpolate(localFrame, [0, 6], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  const isLarge = size === 'large';

  return (
    <div
      style={{
        display: 'inline-flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        border: `3px double ${color}`,
        borderRadius: 8,
        padding: isLarge ? '12px 28px' : '8px 18px',
        backgroundColor: 'rgba(255, 255, 255, 0.92)',
        boxShadow: `0 8px 24px rgba(0,0,0,0.12), inset 0 0 12px ${color}22`,
        opacity,
        transform: `rotate(${angle}deg) scale(${scale})`,
        pointerEvents: 'none',
      }}
    >
      <div
        style={{
          fontFamily: typography.serif,
          fontWeight: 800,
          fontSize: isLarge ? 22 : 16,
          color,
          letterSpacing: 1.5,
          textTransform: 'uppercase',
        }}
      >
        {text}
      </div>
      {subtext && (
        <div
          style={{
            fontFamily: typography.mono,
            fontSize: isLarge ? 11 : 9,
            fontWeight: 700,
            color,
            letterSpacing: 2,
            marginTop: 2,
            opacity: 0.85,
          }}
        >
          {subtext}
        </div>
      )}
    </div>
  );
};
