<template>
  <div style="display: none"></div>
</template>

<script setup lang="ts">
// 兼容历史浏览器缓存占位组件
defineProps<{
  modelValue?: boolean
  visible?: boolean
}>()
defineEmits<{
  (e: 'update:modelValue', value: boolean): void
  (e: 'close'): void
}>()
</script>
