import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

const STORAGE_KEY = 'trc:token'

/**
 * 默认 Token：来自 .env.local 的 VITE_DEFAULT_TOKEN（已 git 忽略）。
 * 非空时优先生效，本地部署时免手工输入；删除该变量即恢复手工输入模式。
 * 注意：Vite 只暴露 VITE_ 前缀变量，且构建期内联，切勿放生产密钥。
 */
const ENV_TOKEN = import.meta.env.VITE_DEFAULT_TOKEN?.trim() ?? ''

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string>(ENV_TOKEN || (localStorage.getItem(STORAGE_KEY) ?? ''))
  const authDialogVisible = ref(false)

  const isAuthenticated = computed(() => token.value.trim().length > 0)
  const authHeader = computed(() => `Bearer ${token.value.trim()}`)

  function setToken(value: string): void {
    token.value = value.trim()
    localStorage.setItem(STORAGE_KEY, token.value)
    authDialogVisible.value = false
  }

  function clearToken(): void {
    token.value = ''
    localStorage.removeItem(STORAGE_KEY)
  }

  function requireAuth(): void {
    authDialogVisible.value = true
  }

  return {
    token,
    authDialogVisible,
    isAuthenticated,
    authHeader,
    setToken,
    clearToken,
    requireAuth,
  }
})
