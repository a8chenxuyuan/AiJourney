<!--
  src/views/Circle.vue：旅行圈（朋友圈式晒旅行生活，zone=circle 分区）
  C2 先落路由骨架占位页，C3 替换为瀑布流 MomentCard + 晒一晒弹窗完整实现
-->

<script setup lang="ts">
// 引入路由（占位页提供去旅行笔记的跳转）
import { useRouter } from 'vue-router'

const router = useRouter()
</script>

<template>
  <div class="page-fade" style="max-width: 820px; margin: 0 auto; padding: 64px 16px; text-align: center;">
    <div style="font-size: 64px;">📷</div>
    <h2 style="margin: 12px 0 8px;">旅行圈</h2>
    <p style="color: #98a3b3; margin: 0 0 24px;">晒出你的旅行瞬间 —— 照片墙搭建中</p>
    <button
      style="border: none; background: #1677ff; color: #fff; font-size: 14px; font-weight: 600; padding: 10px 22px; border-radius: 999px; cursor: pointer;"
      @click="router.push('/notes')"
    >先去逛逛旅行笔记 →</button>
  </div>
</template>
