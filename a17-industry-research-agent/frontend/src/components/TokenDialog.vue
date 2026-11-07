<script setup lang="ts">
import { ref, watch } from 'vue'
import { useAuthStore } from '../stores/auth'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ (e: 'update:modelValue', value: boolean): void }>()

const auth = useAuthStore()
const input = ref('')
const showHelp = ref(false)

watch(
  () => props.modelValue,
  (visible) => {
    if (visible) {
      input.value = auth.token
      showHelp.value = false
    }
  }
)

function confirm(): void {
  const value = input.value.trim()
  if (!value) {
    auth.clearToken()
    return
  }
  auth.setToken(value)
}

function clearAndClose(): void {
  auth.clearToken()
  emit('update:modelValue', false)
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    title="访问令牌"
    width="480px"
    :close-on-click-modal="false"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <el-alert
      type="info"
      show-icon
      :closable="false"
      title="访问本系统需要输入后端配置的 API Token（Authorization: Bearer）"
      style="margin-bottom: 16px"
    />
    <el-input
      v-model="input"
      placeholder="粘贴访问 Token"
      clearable
      show-password
      @keyup.enter="confirm"
    />
    <div style="margin-top: 8px">
      <el-link type="primary" :underline="false" @click="showHelp = !showHelp">
        {{ showHelp ? '收起说明' : 'Token 从哪里获取？' }}
      </el-link>
      <div v-if="showHelp" class="help-text">
        Token 由系统管理员在后端 <code>API_BEARER_TOKENS</code> 环境变量中配置；
        本地开发环境请咨询部署人员，或使用后端 .env 中列出的开发 Token。 若已在前端
        <code>.env.local</code> 设置 <code>VITE_DEFAULT_TOKEN</code>，则无需手工输入。 Token
        保存在浏览器本地，仅用于请求鉴权头。
      </div>
    </div>
    <template #footer>
      <el-button @click="clearAndClose">清除并关闭</el-button>
      <el-button type="primary" @click="confirm">保存</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.help-text {
  margin-top: 8px;
  font-size: 12px;
  line-height: 1.7;
  color: var(--el-text-color-secondary);
}
</style>
