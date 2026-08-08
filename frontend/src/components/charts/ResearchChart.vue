<script setup lang="ts">
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import {
  BarChart,
  BoxplotChart,
  GraphChart,
  HeatmapChart,
  LineChart,
  PieChart,
  RadarChart,
  ScatterChart,
  TreemapChart,
} from 'echarts/charts'
import {
  AriaComponent,
  GridComponent,
  LegendComponent,
  RadarComponent,
  TitleComponent,
  TooltipComponent,
  VisualMapComponent,
} from 'echarts/components'
import VChart from 'vue-echarts'

import type { ChartSpec } from '@/types/workflow'

use([
  CanvasRenderer,
  LineChart,
  BarChart,
  PieChart,
  RadarChart,
  GraphChart,
  ScatterChart,
  HeatmapChart,
  BoxplotChart,
  TreemapChart,
  GridComponent,
  LegendComponent,
  RadarComponent,
  TitleComponent,
  TooltipComponent,
  VisualMapComponent,
  AriaComponent,
])

defineProps<{
  spec: ChartSpec
}>()
</script>

<template>
  <figure class="research-chart" :data-chart-type="spec.chart_type">
    <VChart class="chart-canvas" :option="spec.option" autoresize />
    <figcaption>
      <strong>{{ spec.title }}</strong>
      <span>证据：{{ spec.evidence_ids.join('、') }}</span>
    </figcaption>
  </figure>
</template>

<style scoped>
.research-chart {
  min-width: 0;
  margin: 0;
  padding: 16px;
  border: 1px solid #dbe4ef;
  border-radius: 14px;
  background: #fff;
}

.chart-canvas {
  width: 100%;
  height: 420px;
}

figcaption {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 8px 16px;
  margin-top: 10px;
  color: #64748b;
  font-size: 13px;
}

figcaption strong {
  color: #0f172a;
}

@media (max-width: 768px) {
  .chart-canvas {
    height: 320px;
  }
}
</style>
