/**
 * Vue Router 配置
 * 负责人：前端A（UI工程师）
 */

import { createRouter, createWebHistory } from 'vue-router'
import Home from '@/views/Home.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'home',
      component: Home,
      meta: {
        title: '首页 - 同花顺问财SkillHub',
      },
    },
    {
      path: '/review/:runId',
      name: 'review',
      component: () => import('@/views/Review.vue'),
      meta: {
        title: '审核 - 同花顺问财SkillHub',
      },
    },
  ],
})

// 路由守卫 - 设置页面标题
router.beforeEach((to) => {
  document.title = (to.meta.title as string) || '同花顺问财SkillHub'
})

export default router
