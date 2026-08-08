<template>
  <el-card class="export-decision-card">
    <template #header>
      <span class="export-title">报告导出确认</span>
    </template>

    <el-descriptions :column="2" border>
      <el-descriptions-item label="正式报告资格">
        <el-tag :type="formalEligible ? 'success' : 'danger'">
          {{ formalEligible ? '满足' : '不满足' }}
        </el-tag>
      </el-descriptions-item>
      <el-descriptions-item label="风险草稿资格">
        <el-tag :type="draftEligible ? 'success' : 'danger'">
          {{ draftEligible ? '满足' : '不满足' }}
        </el-tag>
      </el-descriptions-item>
      <el-descriptions-item label="阻断问题">
        {{ blockingCount }}
      </el-descriptions-item>
      <el-descriptions-item label="需确认风险">
        {{ advisoryCount }}
      </el-descriptions-item>
    </el-descriptions>

    <el-alert
      v-if="advisoryCount > 0"
      type="warning"
      :closable="false"
      show-icon
      title="存在未确认的专业风险"
      class="export-alert"
    >
      导出草稿将在报告中标注风险项，并附带水印标识。
    </el-alert>

    <div v-if="advisoryCount > 0" class="advisory-list">
      <h4>专业风险详情</h4>
      <ul>
        <li v-for="(issue, index) in (advisoryIssues || [])" :key="index">{{ issue }}</li>
      </ul>
    </div>

    <div v-if="blockingCount > 0" class="blocking-list">
      <h4>阻断问题</h4>
      <ul>
        <li v-for="(issue, index) in (blockingIssues || [])" :key="index">{{ issue }}</li>
      </ul>
    </div>

    <div class="export-actions">
      <el-button
        v-if="formalEligible"
        type="primary"
        @click="$emit('export-formal')"
      >
        导出正式报告
      </el-button>
      <el-button
        v-if="draftEligible"
        type="warning"
        @click="$emit('export-draft')"
      >
        导出内部审核草稿
      </el-button>
      <el-button @click="$emit('back-to-edit')">
        返回修改
      </el-button>
      <el-button type="danger" @click="$emit('cancel')">
        取消
      </el-button>
    </div>
  </el-card>
</template>

<script setup lang="ts">
defineProps<{
  formalEligible: boolean
  draftEligible: boolean
  blockingCount: number
  advisoryCount: number
  blockingIssues?: string[]
  advisoryIssues?: string[]
}>()

defineEmits<{
  'export-formal': []
  'export-draft': []
  'back-to-edit': []
  'cancel': []
}>()
</script>

<style scoped>
.export-decision-card {
  margin-bottom: 16px;
}
.export-title {
  font-size: 16px;
  font-weight: 600;
}
.export-alert {
  margin: 12px 0;
}
.advisory-list {
  margin: 12px 0;
}
.advisory-list h4 {
  margin: 0 0 8px;
  font-size: 14px;
  color: #f59e0b;
}
.advisory-list ul {
  margin: 0;
  padding-left: 20px;
  color: #6b7280;
  font-size: 13px;
}
.blocking-list {
  margin: 12px 0;
}
.blocking-list h4 {
  margin: 0 0 8px;
  font-size: 14px;
  color: #dc2626;
}
.blocking-list ul {
  margin: 0;
  padding-left: 20px;
  color: #dc2626;
  font-size: 13px;
}
.export-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid #e5e7eb;
}
</style>