<!--
  App.vue - 基础布局壳与路由出口
  负责人：前端A（UI工程师）

  本轮仅保留：基础布局壳与路由出口
  后续扩展：全局导航栏、侧边栏、布局组件
-->

<template>
  <el-container class="app-container">
    <!-- 顶部导航 -->
    <el-header class="app-header">
      <div class="header-content">
        <h1 class="app-title">📊 同花顺问财SkillHub</h1>
        <span class="app-subtitle">行业研究报告智能生成系统</span>
        <nav class="app-nav">
          <router-link to="/" class="nav-link">首页</router-link>
          <router-link to="/runs" class="nav-link">运行历史</router-link>
        </nav>
      </div>
    </el-header>

    <!-- 主内容区 -->
    <el-main class="app-main">
      <router-view />
    </el-main>
  </el-container>
</template>

<script setup lang="ts">
// 极简入口，不承载状态管理或复杂逻辑
</script>

<style>
/* 全局样式重置 */
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  font-family: 'PingFang SC', 'Microsoft YaHei', sans-serif;
  background-color: #f5f7fa;
}

.app-container {
  min-height: 100vh;
}

.app-header {
  background: linear-gradient(135deg, #1e40af 0%, #3b82f6 100%);
  color: white;
  display: flex;
  align-items: center;
  padding: 0 24px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

.header-content {
  display: flex;
  align-items: baseline;
  gap: 12px;
}

.app-title {
  font-size: 20px;
  font-weight: 700;
}

.app-subtitle {
  font-size: 14px;
  opacity: 0.85;
}

.app-nav {
  margin-left: auto;
  display: flex;
  gap: 16px;
  align-self: center;
}

.nav-link {
  color: rgba(255, 255, 255, 0.85);
  text-decoration: none;
  font-size: 14px;
}

.nav-link:hover,
.nav-link.router-link-active {
  color: #ffffff;
  font-weight: 600;
}

.app-main {
  padding: 24px;
  max-width: 1200px;
  margin: 0 auto;
  width: 100%;
}
</style>
