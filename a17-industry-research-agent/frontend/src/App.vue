<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, RouterView, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Setting } from '@element-plus/icons-vue'
import { AUTH_REQUIRED_EVENT } from './api/http'
import { useAuthStore } from './stores/auth'
import { useHealthCheck } from './composables/useHealth'
import { usePendingReviews } from './composables/usePendingReviews'
import TokenDialog from './components/TokenDialog.vue'
import PipelineOverlay from './components/PipelineOverlay.vue'
import SettingsModal from './components/SettingsModal.vue'

const auth = useAuthStore()
const route = useRoute()
const settingsModalVisible = ref(false)

// 顶栏引擎状态来自真实 /health 轮询，不再写死
const health = useHealthCheck()
const healthTag = computed(() => {
  if (health.state.value === 'online') return { type: 'success' as const, text: '引擎就绪' }
  if (health.state.value === 'offline') return { type: 'danger' as const, text: '引擎离线' }
  return { type: 'info' as const, text: '检测中' }
})

// 待审任务角标：审阅完一单回到列表时自动刷新
const pending = usePendingReviews()
watch(
  () => route.fullPath,
  () => void pending.refresh()
)

onMounted(() => {
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
      <nav class="nav" aria-label="主导航">
        <RouterLink
          to="/"
          class="nav-link"
          exact-active-class="nav-link-current"
          data-testid="nav-runs"
        >
          任务列表
          <el-badge
            v-if="pending.count.value > 0"
            :value="pending.count.value"
            type="warning"
            class="nav-badge"
            data-testid="nav-pending-badge"
          />
        </RouterLink>
        <RouterLink to="/create" class="nav-link" exact-active-class="nav-link-current"
          >创建任务</RouterLink
        >
        <RouterLink to="/skills" class="nav-link" exact-active-class="nav-link-current"
          >问财Skill库</RouterLink
        >
        <RouterLink to="/welcome" class="nav-link" exact-active-class="nav-link-current"
          >产品介绍</RouterLink
        >
      </nav>
      <div class="header-right">
        <el-tag
          :type="healthTag.type"
          effect="plain"
          class="engine-health-tag"
          data-testid="engine-health-tag"
          :title="health.model.value ? `模型：${health.model.value}` : '后端健康探测 /health'"
        >
          {{ healthTag.text }}
        </el-tag>
        <el-button
          size="small"
          :icon="Setting"
          aria-label="模型与接口配置"
          @click="settingsModalVisible = true"
        >
          <span class="settings-label">模型与接口配置</span>
          <span class="settings-label-short">配置</span>
        </el-button>
      </div>
    </el-header>
    <el-main
      class="app-main"
      :class="{ 'app-main-wide': route.meta.wide, 'app-main-workbench': route.name === 'review' }"
    >
      <RouterView />
    </el-main>
  </el-container>
  <TokenDialog v-model="auth.authDialogVisible" />
  <SettingsModal v-model="settingsModalVisible" />
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
  white-space: nowrap;
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
  white-space: nowrap;
}
/* 用 exact-active-class 而非默认 active：根路由 "/" 是所有路径的祖先，默认 active 会常亮 */
.nav-link.nav-link-current {
  background: transparent;
  color: var(--el-color-primary);
  font-weight: 700;
  border-bottom: 2px solid var(--rp-gold);
}
.nav-badge {
  margin-left: 6px;
  vertical-align: 1px;
}
:deep(.nav-badge .el-badge__content) {
  height: 16px;
  line-height: 16px;
  padding: 0 5px;
}
.header-right {
  display: flex;
  align-items: center;
  gap: 10px;
}
.settings-label-short {
  display: none;
}
.app-main {
  max-width: 1280px;
  margin: 0 auto;
  width: 100%;
}
.app-main-wide {
  max-width: 1760px;
}
.app-main-workbench {
  overflow: visible;
}
@media (max-width: 1100px) {
  .brand-sub {
    display: none;
  }
  .app-header {
    gap: 14px;
  }
  .nav-link {
    padding-inline: 9px;
  }
}
@media (max-width: 850px) {
  .app-header {
    height: auto;
    min-height: 60px;
    padding: 10px 16px 0;
    flex-wrap: wrap;
    justify-content: space-between;
    gap: 6px 10px;
  }
  .nav {
    order: 1;
    flex: 1 1 100%;
    flex-wrap: wrap;
  }
}
@media (max-width: 520px) {
  .app-header {
    padding-inline: 12px;
  }
  .brand-name {
    font-size: 16px;
    letter-spacing: 0;
  }
  .settings-label {
    display: none;
  }
  .settings-label-short {
    display: inline;
  }
  .nav-link {
    padding-inline: 6px;
    letter-spacing: 0;
  }
  .header-right {
    gap: 6px;
  }
  .app-main {
    padding: 12px;
  }
}
</style>
