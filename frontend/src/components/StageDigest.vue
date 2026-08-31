<script setup lang="ts">
import { computed } from 'vue'
import {
  type ChartCandidate,
  type Claim,
  type CollaborationRequest,
  type DimensionCoverage,
  type IntentRouting,
  type StageName,
} from '../api/types'

const props = defineProps<{ stage: StageName; data: Record<string, unknown> }>()

const d = computed(() => props.data as Record<string, unknown>)

function asArray<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : []
}

/** data_fetch：意图路由计划 */
const intentRouting = computed<IntentRouting | null>(() => {
  const raw = d.value.intent_routing
  return raw && typeof raw === 'object' ? (raw as IntentRouting) : null
})

const intentPlanEntries = computed(() => Object.entries(intentRouting.value?.plans ?? {}))

/** data_fetch：协作请求（澄清问题） */
const collaborationRequests = computed<CollaborationRequest[]>(() =>
  asArray<CollaborationRequest>(d.value.collaboration_requests)
)

const blockingIssues = computed<string[]>(() =>
  asArray<string>(d.value.blocking_issues).map(String)
)

/** data_fetch：检索到的来源记录数 */
const sourceRecords = computed<Record<string, unknown>[]>(() =>
  asArray<Record<string, unknown>>(d.value.source_records)
)

/** data_interpret：结论主张 */
const claims = computed<Claim[]>(() => asArray<Claim>(d.value.claims))

/** data_interpret：维度覆盖 */
const dimensionCoverage = computed<DimensionCoverage[]>(() =>
  asArray<DimensionCoverage>(d.value.dimension_coverage)
)

/** data_interpret：风险 */
const risks = computed<Record<string, unknown>[]>(() => asArray(d.value.risks))

/** chart_generate：图表候选 */
const charts = computed<ChartCandidate[]>(() => asArray<ChartCandidate>(d.value.charts))

/** chapter_write：章节 */
const chapters = computed<Record<string, unknown>[]>(() => {
  const raw = d.value.chapters ?? d.value.sections
  return asArray<Record<string, unknown>>(raw)
})

/** 报告融合 / 兜底：展示顶层标量键值 */
const scalarEntries = computed(() => {
  const entries: Array<[string, string]> = []
  for (const [key, value] of Object.entries(d.value)) {
    if (value === null || value === undefined) continue
    if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
      entries.push([key, String(value)])
    }
  }
  return entries.slice(0, 20)
})

const coverageTagType = (status?: string) => {
  switch (status) {
    case 'supported':
    case 'complete':
      return 'success'
    case 'partial':
      return 'warning'
    case 'missing':
      return 'danger'
    default:
      return 'info'
  }
}
</script>

<template>
  <div class="digest">
    <!-- 所有阶段通用：智能体的协作/澄清请求 -->
    <template v-if="collaborationRequests.length > 0">
      <h4 class="digest-title">待澄清问题（智能体向你提出的请求）</h4>
      <el-alert
        v-for="(req, idx) in collaborationRequests"
        :key="idx"
        type="warning"
        show-icon
        :closable="false"
        class="clarify-item"
      >
        <template #title>{{ req.question || req.reason || '需要人工确认' }}</template>
        <span v-if="req.reason" class="muted">{{ req.reason }}</span>
      </el-alert>
    </template>

    <!-- data_fetch -->
    <template v-if="stage === 'data_fetch'">
      <template v-if="intentPlanEntries.length > 0">
        <h4 class="digest-title">意图识别与数据技能路由</h4>
        <el-table :data="intentPlanEntries" size="small" border>
          <el-table-column label="研究问题" min-width="220">
            <template #default="{ row }">{{ row[0] }}</template>
          </el-table-column>
          <el-table-column label="路由状态" width="110">
            <template #default="{ row }">
              <el-tag :type="row[1]?.requires_clarification ? 'warning' : 'success'" size="small">
                {{ row[1]?.requires_clarification ? '需澄清' : '已路由' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="匹配的数据技能" min-width="200">
            <template #default="{ row }">
              <template v-if="(row[1]?.sub_requirements ?? []).length > 0">
                <div v-for="(sub, idx) in row[1].sub_requirements" :key="idx" class="skill-line">
                  <span class="muted">{{ sub.description }}</span>
                  <el-tag
                    v-for="skill in sub.candidate_skills ?? []"
                    :key="skill"
                    size="small"
                    effect="plain"
                    style="margin-left: 4px"
                  >
                    {{ skill }}
                  </el-tag>
                  <el-tag
                    v-if="(sub.candidate_skills ?? []).length === 0"
                    size="small"
                    type="danger"
                    effect="plain"
                  >
                    无匹配技能
                  </el-tag>
                </div>
              </template>
              <span v-else class="muted">—</span>
            </template>
          </el-table-column>
        </el-table>
      </template>

      <template v-if="sourceRecords.length > 0">
        <h4 class="digest-title">采集来源（{{ sourceRecords.length }} 条）</h4>
        <el-table :data="sourceRecords.slice(0, 10)" size="small" border>
          <el-table-column prop="source_name" label="来源" min-width="200" show-overflow-tooltip />
          <el-table-column prop="skill_name" label="数据技能" width="200" show-overflow-tooltip />
          <el-table-column prop="as_of_date" label="数据日期" width="110" />
          <el-table-column prop="row_count" label="行数" width="80" />
        </el-table>
        <p v-if="sourceRecords.length > 10" class="muted">
          仅显示前 10 条，共 {{ sourceRecords.length }} 条
        </p>
      </template>
    </template>

    <!-- data_interpret -->
    <template v-else-if="stage === 'data_interpret'">
      <template v-if="claims.length > 0">
        <h4 class="digest-title">结论主张（{{ claims.length }} 条）</h4>
        <el-table :data="claims.slice(0, 20)" size="small" border>
          <el-table-column prop="claim_id" label="ID" width="110" show-overflow-tooltip />
          <el-table-column prop="statement" label="主张" min-width="280" show-overflow-tooltip />
          <el-table-column prop="dimension" label="维度" width="110" show-overflow-tooltip />
          <el-table-column label="证据" width="90">
            <template #default="{ row }">{{ (row.evidence_ids ?? []).length }} 条</template>
          </el-table-column>
        </el-table>
        <p v-if="claims.length > 20" class="muted">仅显示前 20 条，共 {{ claims.length }} 条</p>
      </template>
      <template v-if="dimensionCoverage.length > 0">
        <h4 class="digest-title">维度覆盖</h4>
        <div class="coverage-row">
          <el-tooltip
            v-for="(cov, idx) in dimensionCoverage"
            :key="idx"
            :content="cov.reason || cov.dimension || ''"
            placement="top"
          >
            <el-tag :type="coverageTagType(cov.status)" effect="plain">
              {{ cov.dimension }}: {{ cov.status }}
            </el-tag>
          </el-tooltip>
        </div>
      </template>
      <template v-if="risks.length > 0">
        <h4 class="digest-title">风险提示（{{ risks.length }} 条）</h4>
        <ul class="risk-list">
          <li v-for="(risk, idx) in risks.slice(0, 10)" :key="idx" class="muted">
            {{
              risk.description ||
              risk.message ||
              risk.risk_code ||
              JSON.stringify(risk).slice(0, 120)
            }}
          </li>
        </ul>
      </template>
    </template>

    <!-- chart_generate -->
    <template v-else-if="stage === 'chart_generate'">
      <template v-if="charts.length > 0">
        <h4 class="digest-title">图表候选（{{ charts.length }} 张）</h4>
        <el-table :data="charts" size="small" border>
          <el-table-column prop="chart_id" label="图表 ID" width="150" show-overflow-tooltip />
          <el-table-column prop="chart_type" label="类型" width="130" />
          <el-table-column prop="title" label="标题" min-width="220" show-overflow-tooltip />
        </el-table>
      </template>
    </template>

    <!-- chapter_write -->
    <template v-else-if="stage === 'chapter_write'">
      <template v-if="chapters.length > 0">
        <h4 class="digest-title">章节（{{ chapters.length }} 个）</h4>
        <el-table :data="chapters.slice(0, 20)" size="small" border>
          <el-table-column
            v-for="col in ['section_id', 'title', 'word_count']"
            :key="col"
            :prop="col"
            :label="col"
            min-width="140"
            show-overflow-tooltip
          />
        </el-table>
      </template>
    </template>

    <!-- report_fusion 与兜底 -->
    <template v-if="scalarEntries.length > 0">
      <h4 class="digest-title">阶段输出摘要</h4>
      <el-descriptions :column="2" size="small" border>
        <el-descriptions-item v-for="[key, value] in scalarEntries" :key="key" :label="key">
          {{ value }}
        </el-descriptions-item>
      </el-descriptions>
    </template>

    <template v-if="blockingIssues.length > 0">
      <el-alert
        v-for="(issue, idx) in blockingIssues"
        :key="idx"
        type="error"
        show-icon
        :closable="false"
        :title="`阻塞问题: ${issue}`"
        style="margin-top: 12px"
      />
    </template>
  </div>
</template>

<style scoped>
.digest-title {
  margin: 16px 0 8px;
  font-size: 14px;
  font-weight: 600;
}
.digest-title:first-child {
  margin-top: 0;
}
.skill-line {
  line-height: 1.9;
}
.clarify-item {
  margin-bottom: 8px;
}
.coverage-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.risk-list {
  margin: 0;
  padding-left: 18px;
}
</style>
