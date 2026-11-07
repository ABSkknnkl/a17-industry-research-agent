import React from 'react';
import { interpolate, useCurrentFrame, useVideoConfig } from 'remotion';
import { colors } from '../theme/colors';
import { typography } from '../theme/typography';

interface FlowConnectorProps {
  label?: string;
  width?: number;
  reverse?: boolean;
  color?: string;
  packetColor?: string;
}

export const FlowConnector: React.FC<FlowConnectorProps> = ({
  label,
  width = 120,
  reverse = false,
  color = colors.lineDark,
  packetColor = colors.gold,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // 数据包沿着连线移动 (0 ~ 1 循环)
  const progress = (frame % (fps * 1.5)) / (fps * 1.5);
  const packetX = reverse
    ? interpolate(progress, [0, 1], [width - 10, 10])
    : interpolate(progress, [0, 1], [10, width - 10]);

  return (
    <div
      style={{
        width,
        height: 60,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        position: 'relative',
      }}
    >
      {label && (
        <span
          style={{
            fontSize: 10,
            fontFamily: typography.mono,
            color: colors.inkMuted,
            marginBottom: 6,
            letterSpacing: 0.5,
          }}
        >
          {label}
        </span>
      )}
      <svg width={width} height="16" style={{ overflow: 'visible' }}>
        {/* 基础虚线轨迹 */}
        <line
          x1="0"
          y1="8"
          x2={width}
          y2="8"
          stroke={color}
          strokeWidth="2"
          strokeDasharray="4 4"
        />
        {/* 箭头标头 */}
        {reverse ? (
          <polygon
            points={`0,8 8,4 8,12`}
            fill={color}
          />
        ) : (
          <polygon
            points={`${width},8 ${width - 8},4 ${width - 8},12`}
            fill={color}
          />
        )}
        {/* 移动的发光数据包 */}
        <circle
          cx={packetX}
          cy="8"
          r="4"
          fill={packetColor}
          filter="drop-shadow(0 0 4px rgba(169, 133, 63, 0.8))"
        />
      </svg>
    </div>
  );
};
