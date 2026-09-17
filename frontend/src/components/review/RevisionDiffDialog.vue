<script setup lang="ts">
import { computed } from 'vue'
import { chapterNumber } from '../../api/labels'
import { usePrototypeStore } from '../../mock/prototypeRun'

const props = defineProps<{ modelValue: boolean; paragraphId: string | null }>()
const emit = defineEmits<{ (e: 'update:modelValue', value: boolean): void }>()

const store = usePrototypeStore()

const visible = computed({
  get: () => props.modelValue,
  set: (v: boolean) => emit('update:modelValue', v),
})

function findParagraph() {
  for (const ch of store.state.chapters) {
    for (const sec of ch.sections) {
      const p = sec.paragraphs.find((x) => x.paragraph_id === props.paragraphId)
      if (p) return { p, chapter: ch, section: sec }
    }
  }
  return null
}

const found = computed(findParagraph)
const lines = computed(() => found.value?.p.diff?.lines ?? [])
const history = computed(() => found.value?.p.history ?? [])
/** 编号从 chapter_id 反推（后端标题是纯文本，不含序号） */
const chapterLabel = computed(() =>
  found.value ? `第${chapterNumber(found.value.chapter.chapter_id)}章 · ${found.value.chapter.title}` : ''
)
</script>

<template>
  <el-dialog v-model="visible" title="版本差异" width="640px" data-testid="revision-diff-dialog">
    <template v-if="found">
      <p class="muted">
        {{ chapterLabel }} · {{ found.section.title }} · {{ found.p.paragraph_id }}
      </p>
      <h4 class="diff-title">当前版本 v{{ found.p.version }}</h4>
      <p class="body-text">{{ found.p.text }}</p>
      <template v-if="lines.length">
        <h4 class="diff-title">与上一版差异</h4>
        <pre class="diff-pre" data-testid="diff-lines">{{ lines.join('\n') }}</pre>
      </template>
      <template v-if="history.length">
        <h4 class="diff-title">历史版本</h4>
        <ul>
          <li v-for="h in history" :key="h.version">
            v{{ h.version }}：{{ h.text.slice(0, 60) }}…
          </li>
        </ul>
      </template>
    </template>
    <el-empty v-else description="未找到段落" :image-size="60" />
  </el-dialog>
</template>

<style scoped>
.diff-title {
  font-size: 13px;
  color: var(--rp-navy);
  margin: 12px 0 6px;
}
.body-text {
  font-size: 12.5px;
  line-height: 1.8;
}
.diff-pre {
  background: var(--rp-paper);
  border: 1px solid var(--el-border-color-lighter);
  padding: 8px 10px;
  font-size: 11.5px;
  white-space: pre-wrap;
}
</style>
