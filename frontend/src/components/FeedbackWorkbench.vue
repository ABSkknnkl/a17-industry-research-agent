<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { StageName } from '../api/types'
import { STAGE_LABELS } from '../api/types'

export interface UserAnnotation {
  id: string
  stage: string
  targetType: string
  targetId: string
  title: string
  type: 'emphasize' | 'accept' | 'doubt' | 'reject'
  note?: string
}

const props = defineProps<{
  visible: boolean
  stage: StageName
  revision: number
  annotations?: UserAnnotation[]
  submitting?: boolean
}>()

const emit = defineEmits<{
  (e: 'update:visible', val: boolean): void
  (e: 'submit', payload: { comment: string; annotations: UserAnnotation[]; questions: string[] }): void
}>()

const commentText = ref('')
const questionsText = ref('')

const stageChips: Record<string, string[]> = {
  data_fetch: [
    '补充近3年关键财务三表数据',
    '增加可比龙头企业样本',
    '剔除市值较小的非核心标的',
    '补充宏观电价与补贴政策时间线',
    '补充主营构成与产业链上下游数据',
  ],
  data_interpret: [
    '加大储能与逆变器环节的利润分化对比',
    '深入分析估值折价与高市净率成因',
    '剔除离群异常值对行业中枢的干扰',
    '结合宏观政策推演中长期需求变化',
    '增加杜邦分析净资产收益率ROE拆解',
  ],
  chart_generate: [
    '将营收与净利润合并为双轴柱折图',
    '柱状图增加行业中位数参考基准线',
    '高亮行业龙头企业的色彩对比',
    '增加产业链上下游传导关系图',
    '改用精细化横向条形图提高可读性',
  ],
  chapter_write: [
    '增强投资风险深度提示与不确定性分析',
    '精简段落文字密度，突出图表数据穿透',
    '强化海外出海壁垒与关税政策影响',
    '补充各龙头企业竞争格局与护城河卡片',
    '提高券商深度研报学术严谨性与论证自洽度',
  ],
  report_fusion: [
    '优化开篇执行摘要，提炼一句话核心研判',
    '在附录中完善数据局限性与风险对照表',
    '统一全文术语与财务指标统计口径',
  ],
}

const currentChips = computed(() => stageChips[props.stage] || [])

function addChip(chip: string) {
  if (!commentText.value.includes(chip)) {
    commentText.value = commentText.value
      ? `${commentText.value}；${chip}`
      : chip
  }
}

// 标注汇总统计
const annotatedList = computed(() => props.annotations || [])
const emphasizeCount = computed(() => annotatedList.value.filter((a) => a.type === 'emphasize').length)
const doubtCount = computed(() => annotatedList.value.filter((a) => a.type === 'doubt').length)
const rejectCount = computed(() => annotatedList.value.filter((a) => a.type === 'reject').length)

function handleSubmit() {
  const comment = commentText.value.trim()
  const questions = questionsText.value
    .split('\n')
    .map((q) => q.trim())
    .filter(Boolean)

  emit('submit', {
    comment,
    annotations: annotatedList.value,
    questions,
  })
}

function handleClose() {
  emit('update:visible', false)
}

watch(
  () => props.visible,
  (v) => {
    if (v) {
      // 打开时自动把标注项提示注入反馈框（如果反馈框为空）
      if (!commentText.value && annotatedList.value.length > 0) {
        const parts: string[] = []
        if (emphasizeCount.value > 0) parts.push(`重点强调 ${emphasizeCount.value} 项关注点`)
        if (doubtCount.value > 0) parts.push(`针对 ${doubtCount.value} 项存疑结论做事实重验`)
        if (rejectCount.value > 0) parts.push(`剔除 ${rejectCount.value} 项不合格数据`)
        commentText.value = `根据已标注要求：${parts.join('，')}。`
      }
    }
  }
)
</script>

<template>
  <el-dialog
    :model-value="visible"
    :title="`人机协同工作台：针对【${STAGE_LABELS[stage] || stage}】提交定向优化`"
    width="680px"
    class="feedback-workbench-dialog"
    destroy-on-close
    @close="handleClose"
  >
    <div class="workbench-body">
      <!-- 1. 当前版本与上下文引导 -->
      <div class="context-banner">
        <div class="banner-title">
          <span class="loop-icon">🔄</span>
          <strong>“生成 ➔ 审核 ➔ 反馈 ➔ 定向优化” 闭环协同</strong>
        </div>
        <p class="banner-desc">
          系统当前处于 <b>r{{ revision }}</b> 版本。您提出的批注与优化指令将以最高优先级穿透注入给底层大模型与量化引擎，在保留既有合规事实的基础上进行靶向优化，并生成 <b>r{{ revision + 1 }}</b> 新版本。
        </p>
      </div>

      <!-- 2. 已选对象级标注统计（若有） -->
      <div v-if="annotatedList.length > 0" class="annotation-summary-box">
        <div class="box-head">
          <span class="head-title">📌 已收集的对象级标注（共 {{ annotatedList.length }} 项）：</span>
          <span class="head-tags">
            <el-tag v-if="emphasizeCount" size="small" type="warning" effect="dark">🌟 强调 {{ emphasizeCount }}</el-tag>
            <el-tag v-if="doubtCount" size="small" type="danger" effect="plain">❓ 存疑 {{ doubtCount }}</el-tag>
            <el-tag v-if="rejectCount" size="small" type="info" effect="plain">🚫 剔除 {{ rejectCount }}</el-tag>
          </span>
        </div>
        <ul class="annot-items-list">
          <li v-for="a in annotatedList.slice(0, 5)" :key="a.id" class="annot-line">
            <span class="badge" :class="a.type">
              {{ a.type === 'emphasize' ? '强调' : a.type === 'doubt' ? '存疑' : '剔除' }}
            </span>
            <span class="annot-title">{{ a.title }}</span>
          </li>
          <li v-if="annotatedList.length > 5" class="muted more-line">
            + 另有 {{ annotatedList.length - 5 }} 项标注已一并打包
          </li>
        </ul>
      </div>

      <!-- 3. 场景化快捷反馈指令 Chips -->
      <div v-if="currentChips.length > 0" class="chips-box">
        <span class="chips-lead">💡 推荐快捷投研指令（点击添加）：</span>
        <div class="chips-row">
          <button
            v-for="chip in currentChips"
            :key="chip"
            type="button"
            class="feedback-chip"
            @click="addChip(chip)"
          >
            + {{ chip }}
          </button>
        </div>
      </div>

      <!-- 4. 反馈指令输入框 -->
      <div class="input-section">
        <label class="input-label">
          <strong>修改备注（协同反馈与优化指令）：</strong>
        </label>
        <el-input
          v-model="commentText"
          type="textarea"
          :rows="4"
          maxlength="2000"
          show-word-limit
          placeholder="例如：请在估值分析中加大对阳光电源海外逆变器毛利率与市占率的穿透分析；将科陆电子的PB异常剔除后重新绘制行业对标图；篇章语言请进一步精简突出核心结论。"
        />
      </div>

      <!-- 针对数据获取/解读：支持替换研究问题 -->
      <div v-if="stage === 'data_fetch' || stage === 'data_interpret'" class="input-section" style="margin-top: 12px">
        <label class="input-label">
          <span>修订后的研究问题（每行一个，若填写将重构意图路由）：</span>
        </label>
        <el-input
          v-model="questionsText"
          type="textarea"
          :rows="2"
          placeholder="如：锂电池行业2024-2025年营收增速如何？"
        />
      </div>
    </div>

    <template #footer>
      <div class="dialog-foot">
        <el-button @click="handleClose">取消</el-button>
        <el-button
          type="primary"
          :loading="submitting"
          class="btn-submit-opt"
          @click="handleSubmit"
        >
          🚀 提交修订并重跑（定向优化）
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>

<style scoped>
.workbench-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.context-banner {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-left: 4px solid var(--rp-navy, #1e3a5c);
  border-radius: 6px;
  padding: 10px 14px;
}
.banner-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13.5px;
  color: var(--rp-navy, #1e3a5c);
  margin-bottom: 4px;
}
.banner-desc {
  margin: 0;
  font-size: 12px;
  line-height: 1.6;
  color: #475569;
}

/* 标注汇总 */
.annotation-summary-box {
  background: #fffbeb;
  border: 1px solid #fde68a;
  border-radius: 6px;
  padding: 10px 12px;
}
.box-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}
.head-title {
  font-size: 12.5px;
  font-weight: 600;
  color: #92400e;
}
.head-tags {
  display: flex;
  gap: 4px;
}
.annot-items-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.annot-line {
  font-size: 11.5px;
  display: flex;
  align-items: center;
  gap: 6px;
  color: #78350f;
}
.badge {
  font-size: 10px;
  font-weight: 600;
  padding: 1px 5px;
  border-radius: 3px;
}
.badge.emphasize { background: #fef3c7; color: #b45309; }
.badge.doubt { background: #fee2e2; color: #dc2626; }
.badge.reject { background: #f1f5f9; color: #64748b; }
.annot-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.more-line {
  font-size: 11px;
  margin-top: 2px;
}

/* 快捷 Chips */
.chips-box {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.chips-lead {
  font-size: 12px;
  color: #64748b;
  font-weight: 500;
}
.chips-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.feedback-chip {
  border: 1px dashed #cbd5e1;
  background: #ffffff;
  border-radius: 4px;
  font-size: 11.5px;
  color: var(--rp-navy, #1e3a5c);
  padding: 3px 8px;
  cursor: pointer;
  transition: all 0.15s ease;
}
.feedback-chip:hover {
  background: #f1f5f9;
  border-color: #94a3b8;
  transform: translateY(-1px);
}

.input-section {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.input-label {
  font-size: 12.5px;
  color: #1e293b;
}

.dialog-foot {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
}
.btn-submit-opt {
  font-weight: 600;
  background: var(--rp-navy, #1e3a5c);
  border-color: var(--rp-navy, #1e3a5c);
}
.btn-submit-opt:hover {
  background: #2a4d77;
  border-color: #2a4d77;
}
</style>
