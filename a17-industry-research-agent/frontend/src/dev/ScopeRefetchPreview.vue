<script setup lang="ts">
import { ref } from 'vue'
import StageInterventionModal from '../components/StageInterventionModal.vue'

const visible = ref(true)
/** 录制演示时用 ?rec=1 隐藏顶部开发说明栏 */
const showBar = !window.location.search.includes('rec=1')
/** 默认停在第一个页签；?tab=refetch 直接进「局部子域重采」 */
const initialTab = new URLSearchParams(window.location.search).get('tab') === 'refetch'
  ? 'partial_refetch'
  : 'scope_keywords'
const lastPayload = ref<Record<string, unknown> | null>(null)
const lastComment = ref('')

/** 模拟 data_fetch 阶段下发的数据：实体名会被组件读取，用于填充数据点前缀 */
const mockData: Record<string, unknown> = {
  industry_topic: '新能源汽车',
  keywords: [
    '行业总销量与渗透率',
    '碳酸锂均价',
    '动力电池装机量',
    '龙头毛利率',
    '整车出口量',
    '充电桩保有量',
    'CR5 市场集中度',
  ],
  source_records: [
    { entity_name: '比亚迪', metric: '营业收入', value: '¥1,342 亿', period: 'FY2025Q3', source_type: '年报', confidence: 96 },
    { entity_name: '比亚迪', metric: '归母净利润', value: '', period: 'FY2025Q3', source_type: '公告', confidence: 0 },
    { entity_name: '比亚迪', metric: '毛利率', value: '21.4%', period: 'FY2024', source_type: '年报', confidence: 91 },
    { entity_name: '宁德时代', metric: '资产负债率', value: '58.2%', period: 'FY2024', source_type: '年报', confidence: 88 },
    { entity_name: '宁德时代', metric: '研发费用率', value: '', period: 'FY2024', source_type: '年报', confidence: 0 },
    { entity_name: '理想汽车', metric: '经营性现金流', value: '¥96 亿', period: 'FY2024', source_type: '年报', confidence: 62 },
    { entity_name: '理想汽车', metric: '季度交付量', value: '163.2 万辆', period: 'FY2025Q3', source_type: '公告', confidence: 93 },
    { entity_name: '特斯拉', metric: '全球市占率', value: '17.8%', period: 'FY2024', source_type: '研报', confidence: 71 },
    { entity_name: '亿纬锂能', metric: '产能利用率', value: '', period: 'FY2025Q3', source_type: '协会', confidence: 0 },
  ],
}

function handleVisible(val: boolean) {
  visible.value = val
}

function handleSubmitRevise(payload: {
  comment: string
  edited_data?: Record<string, unknown> | null
}) {
  lastComment.value = payload.comment
  lastPayload.value = payload.edited_data || null
}

function reopen() {
  visible.value = true
}
</script>

<template>
  <div class="preview-page">
    <div v-if="showBar" class="preview-bar">
      <div class="preview-text">
        <h1>UI 预览 · 定向补采（点级清单 + 多轮检索）</h1>
        <p>
          两个页签可切换：审核确认检索范围与关键词 / 定向补采（点级清单 + 多轮检索）。
          定向补采页签里勾数据点、切「多轮检索（AI）或 常规单次查询」、改口径，提交后下方打印
          edited_data。全部本地模拟，不走后端。
        </p>
      </div>
      <el-button type="primary" @click="reopen">重新打开弹窗</el-button>
    </div>

    <div v-if="lastPayload" class="payload-box">
      <div class="payload-head">
        <h2>提交的 payload（模拟）</h2>
        <el-tag size="small" type="success">{{ lastComment }}</el-tag>
      </div>
      <pre>{{ JSON.stringify(lastPayload, null, 2) }}</pre>
    </div>
  </div>

  <StageInterventionModal
    :visible="visible"
    stage="data_fetch"
    :revision="1"
    :data="mockData"
    :initial-tab="initialTab"
    @update:visible="handleVisible"
    @submit-revise="handleSubmitRevise"
  />
</template>

<style scoped>
.preview-page {
  min-height: 100vh;
  padding: 24px 32px;
  background: #f5f7fa;
}
.preview-bar {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  padding: 16px 20px;
  background: #fff;
  border-radius: 8px;
  box-shadow: 0 1px 4px rgb(0 0 0 / 6%);
}
.preview-text h1 {
  margin: 0 0 6px;
  font-size: 16px;
  font-weight: 600;
  color: #1f2329;
}
.preview-text p {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.7;
  color: #646a73;
}
.payload-box {
  margin-top: 16px;
  padding: 16px 20px;
  background: #fff;
  border-radius: 8px;
  box-shadow: 0 1px 4px rgb(0 0 0 / 6%);
}
.payload-head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
}
.payload-head h2 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
}
.payload-box pre {
  margin: 0;
  padding: 12px;
  font-size: 12px;
  line-height: 1.7;
  color: #1f2329;
  background: #f5f7fa;
  border-radius: 6px;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
