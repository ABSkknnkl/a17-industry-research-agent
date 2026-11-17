import { createRouter, createWebHistory } from 'vue-router'

/**
 * 路由（B43 / 前端 B3）：
 * 高频入口是任务列表，所以它占据根路由；Landing 作为产品介绍挪到 /welcome，
 * 仅新用户首次访问时展示一次（同一会话内只重定向一次，避免导航死循环）。
 */
export const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'runs',
      component: () => import('./views/RunsView.vue'),
    },
    // 旧书签/旧链接兼容
    { path: '/runs', redirect: { name: 'runs' } },
    {
      path: '/welcome',
      name: 'home',
      component: () => import('./views/LandingView.vue'),
      meta: { wide: true },
    },
    {
      path: '/create',
      name: 'create',
      component: () => import('./views/CreateRunView.vue'),
    },
    {
      path: '/skills',
      name: 'skills',
      component: () => import('./views/SkillsHubView.vue'),
      meta: { wide: true },
    },
    {
      path: '/runs/:runId',
      name: 'review',
      component: () => import('./views/ReviewView.vue'),
      // 工作台是「项目树 + 主工作区」双栏，需要更宽的视口
      meta: { wide: true },
    },
    {
      path: '/runs/:runId/report',
      name: 'report-preview',
      component: () => import('./views/ReportPreviewView.vue'),
      meta: { wide: true },
    },
    {
      path: '/runs/:runId/download',
      name: 'report-download',
      component: () => import('./views/ReportDownloadView.vue'),
      meta: { wide: true },
    },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

const VISITED_KEY = 'trc:visited'

function hasVisited(): boolean {
  try {
    return localStorage.getItem(VISITED_KEY) === '1'
  } catch {
    // 隐私模式下不可用：视为已访问，避免把用户永久困在介绍页
    return true
  }
}

function markVisited(): void {
  try {
    localStorage.setItem(VISITED_KEY, '1')
  } catch {
    /* 忽略 */
  }
}

/** 本次会话是否已经为「新用户」重定向过；只生效一次，防止点击导航被反复弹回 */
let introRedirected = false

router.beforeEach((to) => {
  if (to.name === 'runs' && !hasVisited() && !introRedirected) {
    introRedirected = true
    return { name: 'home' }
  }
  return true
})

router.afterEach((to) => {
  if (to.name !== 'home') markVisited()
})
