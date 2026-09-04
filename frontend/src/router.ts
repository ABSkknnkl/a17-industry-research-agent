import { createRouter, createWebHistory } from 'vue-router'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'home', component: () => import('./views/HomeView.vue') },
    { path: '/runs', name: 'runs', component: () => import('./views/RunsView.vue') },
    {
      path: '/runs/:runId',
      name: 'review',
      component: () => import('./views/ReviewView.vue'),
      // 三栏工作台需要更宽的视口
      meta: { wide: true },
    },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})
