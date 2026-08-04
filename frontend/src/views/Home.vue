<!--
  Home.vue - 最小首页（启动验证点）
  负责人：前端A（UI工程师）

  骨架验证用途，展示项目名称和基本导航入口
-->

<template>
  <div class="home">
    <el-card class="welcome-card" shadow="hover">
      <template #header>
        <div class="card-header">
          <span>🚀 欢迎使用同花顺问财SkillHub</span>
        </div>
      </template>
      <div class="card-body">
        <p class="description">基于多智能体Pipeline的行业研究报告智能生成与人机协同优化系统</p>
        <el-divider />
        <div class="features">
          <el-tag type="primary" size="large">5个智能体</el-tag>
          <el-tag type="success" size="large">7章×21节</el-tag>
          <el-tag type="warning" size="large">6+数据技能</el-tag>
          <el-tag type="info" size="large">人机协同</el-tag>
        </div>
        <el-divider />
        <div class="actions">
          <el-button type="primary" size="large" disabled> 开始生成报告（即将上线） </el-button>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
// 最小首页，无复杂逻辑
</script>

<style scoped>
.home {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: calc(100vh - 200px);
}

.welcome-card {
  width: 100%;
  max-width: 600px;
}

.card-header {
  font-size: 18px;
  font-weight: 600;
}

.card-body {
  text-align: center;
}

.description {
  font-size: 16px;
  color: #606266;
  line-height: 1.8;
}

.features {
  display: flex;
  justify-content: center;
  gap: 12px;
  flex-wrap: wrap;
}

.actions {
  margin-top: 16px;
}
</style>
