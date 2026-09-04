<script setup lang="ts">
import { onMounted } from 'vue'
import { RouterLink, RouterView, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { AUTH_REQUIRED_EVENT } from './api/http'
import { useAuthStore } from './stores/auth'
import TokenDialog from './components/TokenDialog.vue'
import PipelineOverlay from './components/PipelineOverlay.vue'

const auth = useAuthStore()
const route = useRoute()

onMounted(() => {
  if (!auth.isAuthenticated) auth.requireAuth()
  window.addEventListener(AUTH_REQUIRED_EVENT, () => {
    ElMessage.warning('登录状态已失效，请重新输入 Token')
    auth.requireAuth()
  })
})
</script>

<template>
  <el-container class="app-shell">
    <el-header class="app-header">
      <div class="brand">
        <el-icon :size="22"><TrendCharts /></el-icon>
        <span class="brand-name">行业研究智能体</span>
        <span class="brand-sub">INDUSTRY RESEARCH</span>
      </div>
      <nav class="nav">
        <RouterLink to="/" class="nav-link">创建任务</RouterLink>
        <RouterLink to="/runs" class="nav-link">任务列表</RouterLink>
      </nav>
      <div class="header-right">
        <el-tag v-if="auth.isAuthenticated" type="success" effect="plain">已登录</el-tag>
        <el-button v-else size="small" @click="auth.requireAuth()">登录</el-button>
      </div>
    </el-header>
    <el-main class="app-main" :class="{ 'app-main-wide': route.meta.wide }">
      <RouterView />
    </el-main>
  </el-container>
  <TokenDialog v-model="auth.authDialogVisible" />
  <PipelineOverlay />
</template>

<style scoped>
.app-shell {
  min-height: 100vh;
}
.app-header {
  display: flex;
  align-items: center;
  gap: 24px;
  /* 研报刊头：藏青粗线 + 细线双横线 */
  border-bottom: 3px double var(--el-color-primary);
  background: var(--el-bg-color);
}
.brand {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--el-color-primary);
}
.brand-name {
  font-family: var(--rp-serif);
  font-weight: 700;
  font-size: 18px;
  letter-spacing: 1px;
}
.brand-sub {
  font-size: 10px;
  letter-spacing: 3px;
  color: var(--rp-gold);
  font-weight: 600;
}
.nav {
  display: flex;
  gap: 4px;
  flex: 1;
}
.nav-link {
  padding: 5px 14px;
  border-radius: 2px;
  color: var(--el-text-color-primary);
  text-decoration: none;
  font-size: 13.5px;
  letter-spacing: 0.5px;
  border-bottom: 2px solid transparent;
}
.nav-link.router-link-active {
  background: transparent;
  color: var(--el-color-primary);
  font-weight: 700;
  border-bottom: 2px solid var(--rp-gold);
}
.header-right {
  display: flex;
  align-items: center;
}
.app-main {
  max-width: 1280px;
  margin: 0 auto;
  width: 100%;
}
.app-main-wide {
  max-width: 1760px;
}
</style>
