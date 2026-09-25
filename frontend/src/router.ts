import { createRouter, createWebHistory } from 'vue-router'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'home',
      component: () => import('./views/LandingView.vue'),
      meta: { wide: true },
    },
    {
      path: '/create',
      name: 'create',
      component: () => import('./views/CreateRunView.vue'),
    },
    { path: '/runs', name: 'runs', component: () => import('./views/RunsView.vue') },
    {
      path: '/runs/:runId',
      name: 'review',
      component: () => import('./views/ReviewView.vue'),
      // 三栏工作台需要更宽的视口
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
