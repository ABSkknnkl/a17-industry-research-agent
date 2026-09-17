<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { chapterNumber } from '../../api/labels'
import { usePrototypeStore } from '../../mock/prototypeRun'
import {
  chartStatusLabel,
  chartTypeLabel,
  claimStatusLabel,
  dimensionLabel,
  evidenceCategoryLabel,
  evidenceStatusLabel,
  paragraphStatusLabel,
  skillLabel,
} from '../../api/labels'

const props = defineProps<{
  modelValue: boolean
  objectId: string | null
  /** A1 source_records，用于结论「数据来源」区块 */
  sourceRecords?: Record<string, unknown>[]
  /** 打开时聚焦：sources=数据来源，citations=引用列表 */
  focus?: 'sources' | 'citations' | null
}>()
const emit = defineEmits<{ (e: 'update:modelValue', value: boolean): void }>()

const store = usePrototypeStore()

const visible = computed({
  get: () => props.modelValue,
  set: (v: boolean) => emit('update:modelValue', v),
})

/** 用户手动折叠/展开「数据来源」；初始由 focus 驱动 */
const sourcesOpen = ref(true)

watch(
  () => [props.modelValue, props.focus],
  ([open, focus]) => {
    if (!open) return
    sourcesOpen.value = focus !== 'citations'
  },
  { immediate: true }
)

const evidence = computed(() => store.state.evidences.find((e) => e.evidence_id === props.objectId))
const claim = computed(() => store.state.claims.find((c) => c.claim_id === props.objectId))
const chart = computed(() => store.state.charts.find((c) => c.chart_id === props.objectId))

/**
 * 与「证据审核」表共用的编号规则：按证据列表顺序生成。
 * 两处必须用同一套编号，否则用户对不上号。
 */
const evidenceNo = computed<Record<string, number>>(() => {
  const map: Record<string, number> = {}
  store.state.evidences.forEach((e, idx) => {
    map[e.evidence_id] = idx + 1
  })
  return map
})

const noOf = (id: string): string => {
  const n = evidenceNo.value[id]
  return n ? `#${n}` : id
}

/** source_name → SourceRecord；mock 下与 evidence.title 一一对应 */
const recordByTitle = computed(() => {
  const map = new Map<string, Record<string, unknown>>()
  for (const rec of props.sourceRecords ?? []) {
    const name = String(rec.source_name ?? '')
    if (name) map.set(name, rec)
  }
  return map
})

interface SourceCard {
  evidenceId: string
  no: string
  title: string
  sourceType: string
  publisher: string
  asOfDate: string
  skillName: string
  rowCount: string
  status: string
  linked: boolean
}

/** 结论引用的证据 → 数据来源卡片（关联不到采集明细时降级展示） */
const sourceCards = computed<SourceCard[]>(() => {
  if (!claim.value) return []
  return claim.value.evidence_ids.map((eid) => {
    const ev = store.state.evidences.find((e) => e.evidence_id === eid)
    const rec = ev ? recordByTitle.value.get(ev.title) : undefined
    const linked = Boolean(rec)
    return {
      evidenceId: eid,
      no: noOf(eid),
      title: ev?.title ?? eid,
      sourceType: evidenceCategoryLabel(ev?.source_type),
      publisher: ev?.publisher ?? '—',
      asOfDate: ev?.as_of_date ?? '—',
      skillName: linked ? skillLabel(String(rec!.skill_name ?? '')) : '未关联到采集明细',
      rowCount: linked ? String(rec!.row_count ?? '—') : '未关联到采集明细',
      status: evidenceStatusLabel(ev?.status) || '—',
      linked,
    }
  })
})

interface RefMeta {
  label: string
  value: string
}

const rows = computed<RefMeta[]>(() => {
  const id = props.objectId
  if (!id) return []
  if (evidence.value) {
    const ev = evidence.value
    return [
      { label: '类型', value: '证据' },
      { label: '标题', value: ev.title },
      { label: '来源类型', value: evidenceCategoryLabel(ev.source_type) },
      { label: '发布主体', value: ev.publisher },
      { label: '日期', value: ev.as_of_date },
      { label: '摘要', value: ev.summary },
      { label: '状态', value: evidenceStatusLabel(ev.status) },
      { label: '排除原因', value: ev.exclude_reason ?? '—' },
      { label: '引用来源', value: ev.url_hint },
      { label: '完整识别码', value: ev.evidence_id },
    ]
  }
  if (claim.value) {
    const c = claim.value
    return [
      { label: '类型', value: '结论' },
      { label: '主张', value: c.statement },
      { label: '维度', value: dimensionLabel(c.dimension) },
      { label: '证据引用', value: c.evidence_ids.map(noOf).join('、') },
      { label: '反证条件', value: c.counter_condition },
      { label: '状态', value: claimStatusLabel(c.status) },
    ]
  }
  if (chart.value) {
    const ch = chart.value
    return [
      { label: '类型', value: '图表' },
      { label: '标题', value: ch.title },
      { label: '图表类型', value: chartTypeLabel(ch.chart_type) },
      { label: '模板', value: ch.template },
      { label: '配色', value: ch.color_theme },
      { label: 'unitRevision', value: String(ch.unit_revision) },
      { label: '是否纳入报告', value: ch.in_report ? '是' : '否' },
      { label: '状态', value: chartStatusLabel(ch.status) },
      { label: '分析目的', value: ch.insight_goal },
    ]
  }
  for (const chapter of store.state.chapters) {
    for (const section of chapter.sections) {
      const p = section.paragraphs.find((x) => x.paragraph_id === id)
      if (p) {
        return [
          { label: '类型', value: '段落' },
          { label: '章节', value: `第${chapterNumber(chapter.chapter_id)}章 · ${chapter.title}` },
          { label: '小节', value: `${section.title}（${section.section_id}）` },
          { label: '段落 ID', value: p.paragraph_id },
          { label: '版本', value: `v${p.version}` },
          { label: '正文', value: p.text },
          { label: '状态', value: paragraphStatusLabel(p.status) },
        ]
      }
    }
  }
  return [
    { label: '对象', value: id },
    { label: '说明', value: '演示对象详情；操作仍在对应卡片完成' },
  ]
})

const impacts = computed(() => {
  const rec = store.state.lastAction
  if (!rec || !props.objectId) return []
  if (rec.object_id !== props.objectId && !rec.affected.includes(props.objectId)) {
    if (rec.affected.length === 0) return []
  }
  return rec.affected
})
</script>

<template>
  <el-drawer
    v-model="visible"
    title="对象详情与影响"
    size="420px"
    data-testid="review-inspector-drawer"
  >
    <el-descriptions :column="1" size="small" border>
      <el-descriptions-item v-for="row in rows" :key="row.label" :label="row.label">
        {{ row.value }}
      </el-descriptions-item>
    </el-descriptions>

    <!-- 结论：数据来源区块（默认展开；focus=sources 时强制展开） -->
    <template v-if="claim && sourceCards.length > 0">
      <button
        class="section-toggle"
        type="button"
        data-testid="toggle-sources"
        @click="sourcesOpen = !sourcesOpen"
      >
        <span class="section-toggle-title">数据来源（{{ sourceCards.length }}）</span>
        <span class="muted">{{ sourcesOpen ? '收起' : '展开' }}</span>
      </button>
      <div v-if="sourcesOpen" class="source-list" data-testid="source-list">
        <div v-for="card in sourceCards" :key="card.evidenceId" class="source-card">
          <div class="source-head">
            <span class="source-no">{{ card.no }}</span>
            <span class="source-title">{{ card.title }}</span>
            <el-tag
              size="small"
              effect="plain"
              :type="card.status === '已排除' ? 'info' : 'success'"
            >
              {{ card.status }}
            </el-tag>
          </div>
          <dl class="source-meta">
            <div>
              <dt>来源类型</dt>
              <dd>{{ card.sourceType }}</dd>
            </div>
            <div>
              <dt>发布主体</dt>
              <dd>{{ card.publisher }}</dd>
            </div>
            <div>
              <dt>数据日期</dt>
              <dd>{{ card.asOfDate }}</dd>
            </div>
            <div>
              <dt>采集技能</dt>
              <dd :class="{ muted: !card.linked }">{{ card.skillName }}</dd>
            </div>
            <div>
              <dt>采集行数</dt>
              <dd :class="{ muted: !card.linked }">{{ card.rowCount }}</dd>
            </div>
          </dl>
        </div>
        <p v-if="sourceCards.some((c) => !c.linked)" class="muted join-hint">
          部分证据未能关联到 A1 采集明细（真实模式下 source_name
          口径可能不一致），仅展示证据自带字段。
        </p>
      </div>
    </template>

    <template v-if="impacts.length">
      <h4 class="impact-title">最近操作影响</h4>
      <ul class="impact-list">
        <li v-for="id in impacts" :key="id">
          <el-tag size="small" effect="plain">{{ noOf(id) }}</el-tag>
        </li>
      </ul>
    </template>
    <p class="muted">此处仅展示详情，删除/通过/重生成/下载请使用对象卡上的按钮。</p>
  </el-drawer>
</template>

<style scoped>
.impact-title {
  margin: 16px 0 8px;
  font-size: 13px;
  color: var(--rp-navy);
}
.impact-list {
  margin: 0 0 12px;
  padding: 0;
  list-style: none;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.section-toggle {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  margin: 16px 0 8px;
  padding: 6px 0;
  border: none;
  border-bottom: 2px solid var(--rp-navy);
  background: transparent;
  cursor: pointer;
  text-align: left;
}
.section-toggle-title {
  font-family: var(--rp-serif);
  font-size: 13px;
  font-weight: 700;
  color: var(--rp-navy);
  letter-spacing: 0.5px;
}
.source-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.source-card {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 3px;
  padding: 8px 10px;
  background: var(--el-fill-color-lighter);
}
.source-head {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}
.source-no {
  font-family: var(--rp-serif);
  font-weight: 700;
  color: var(--rp-gold);
  font-size: 12px;
  flex-shrink: 0;
}
.source-title {
  flex: 1;
  font-size: 12px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.source-meta {
  margin: 0;
}
.source-meta > div {
  display: flex;
  gap: 8px;
  font-size: 11.5px;
  line-height: 1.6;
}
.source-meta dt {
  flex-shrink: 0;
  width: 56px;
  color: var(--el-text-color-secondary);
}
.source-meta dd {
  margin: 0;
  color: var(--el-text-color-primary);
  word-break: break-all;
}
.join-hint {
  margin-top: 4px;
}
</style>
