import React from 'react';
import { Composition, Folder } from 'remotion';
import './index.css';
import {
  VIDEO_FPS,
  VIDEO_WIDTH,
  VIDEO_HEIGHT,
  OVERVIEW_DURATION_IN_FRAMES,
  AGENT_DURATION_IN_FRAMES,
} from './theme/constants';

import { OverviewComp } from './compositions/01_Overview/OverviewComp';
import { DataFetcherComp } from './compositions/02_DataFetcher/DataFetcherComp';
import { DataInterpreterComp } from './compositions/03_DataInterpreter/DataInterpreterComp';
import { ChartGeneratorComp } from './compositions/04_ChartGenerator/ChartGeneratorComp';
import { ChapterWriterComp } from './compositions/05_ChapterWriter/ChapterWriterComp';
import { ReportFusionComp } from './compositions/06_ReportFusion/ReportFusionComp';

export const RemotionRoot: React.FC = () => {
  return (
    <>
      {/* 视频 1: 系统总体架构与全链路流转 (35秒 / 1050帧) */}
      <Composition
        id="SystemOverview"
        component={OverviewComp}
        durationInFrames={OVERVIEW_DURATION_IN_FRAMES}
        fps={VIDEO_FPS}
        width={VIDEO_WIDTH}
        height={VIDEO_HEIGHT}
      />

      {/* 文件夹分组：5 大独立智能体微观拆解系列 (各 20秒 / 600帧) */}
      <Folder name="MicroAgents">
        {/* 视频 2: Stage 1 数据采集智能体 */}
        <Composition
          id="DataFetcherAgent"
          component={DataFetcherComp}
          durationInFrames={AGENT_DURATION_IN_FRAMES}
          fps={VIDEO_FPS}
          width={VIDEO_WIDTH}
          height={VIDEO_HEIGHT}
        />

        {/* 视频 3: Stage 2 数据解读智能体 */}
        <Composition
          id="DataInterpreterAgent"
          component={DataInterpreterComp}
          durationInFrames={AGENT_DURATION_IN_FRAMES}
          fps={VIDEO_FPS}
          width={VIDEO_WIDTH}
          height={VIDEO_HEIGHT}
        />

        {/* 视频 4: Stage 3 图表生成智能体 */}
        <Composition
          id="ChartGeneratorAgent"
          component={ChartGeneratorComp}
          durationInFrames={AGENT_DURATION_IN_FRAMES}
          fps={VIDEO_FPS}
          width={VIDEO_WIDTH}
          height={VIDEO_HEIGHT}
        />

        {/* 视频 5: Stage 4 章节撰写智能体 */}
        <Composition
          id="ChapterWriterAgent"
          component={ChapterWriterComp}
          durationInFrames={AGENT_DURATION_IN_FRAMES}
          fps={VIDEO_FPS}
          width={VIDEO_WIDTH}
          height={VIDEO_HEIGHT}
        />

        {/* 视频 6: Stage 5 报告融合智能体 */}
        <Composition
          id="ReportFusionAgent"
          component={ReportFusionComp}
          durationInFrames={AGENT_DURATION_IN_FRAMES}
          fps={VIDEO_FPS}
          width={VIDEO_WIDTH}
          height={VIDEO_HEIGHT}
        />
      </Folder>
    </>
  );
};
