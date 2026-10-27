<!--
  src/components/CommunityRail.vue：社区右栏（旅行圈 / 旅行笔记两页共用）
  作用：深色玩法引导卡 + 活跃旅行者 + 热门标签；玩法文案按 zone 切换，
       活跃用户与热门标签由父页基于已加载 feed 聚合后传入
-->

<script setup lang="ts">
// 组件入参：zone 决定玩法卡文案；users/tags 为父页聚合结果；activeTag 当前筛选标签
defineProps<{
  zone: 'circle' | 'note'
  users: Array<{ name: string; posts: number; likes: number }>
  tags: Array<{ name: string; count: number }>
  activeTag: string | null
}>()

// emit：toggle-tag 通知父页切换标签筛选（再点一次取消）
const emit = defineEmits<{
  (e: 'toggle-tag', name: string): void
}>()

// 玩法卡文案：旅行圈教晒照，旅行笔记教沉淀攻略
const PLAY_STEPS: Record<'circle' | 'note', Array<{ b: string; s: string }>> = {
  circle: [
    { b: '拍下旅途瞬间', s: '风景、美食、路边的小惊喜' },
    { b: '配一句话心情', s: '不用长篇大论，真实就好' },
    { b: '晒进旅行圈', s: '九宫格照片墙立刻呈现' },
    { b: '收获点赞评论', s: '和同好旅行者聊起来' }
  ],
  note: [
    { b: '规划行程', s: 'AI 帮你定制路线' },
    { b: '行中打卡', s: '记录足迹与照片' },
    { b: '生成游记', s: 'AI 一键写好图文' },
    { b: '发布 · 照着走', s: '把路线分享给他人' }
  ]
}

/**
 * toggleTag：点击热门标签，通知父页切换筛选
 */
const toggleTag = (name: string) => emit('toggle-tag', name)
</script>

<template>
  <aside class="rail">
    <!-- 玩法引导（深色卡）：与白色数据卡形成对比，消除右栏苍白感 -->
    <section class="rail-card rail-play">
      <h4>{{ zone === 'circle' ? '圈内玩法' : '社区怎么玩' }}</h4>
      <ol class="rail-steps">
        <li v-for="(step, i) in PLAY_STEPS[zone]" :key="step.b">
          <i>{{ i + 1 }}</i>
          <div><b>{{ step.b }}</b><span>{{ step.s }}</span></div>
        </li>
      </ol>
    </section>

    <!-- 活跃旅行者（按已加载内容聚合作者维度） -->
    <section class="rail-card">
      <h4>活跃旅行者</h4>
      <ul v-if="users.length" class="rail-users">
        <li v-for="(u, i) in users" :key="u.name">
          <span class="ru-rank" :class="{ 'is-top': i < 3 }">{{ i + 1 }}</span>
          <span class="ru-avatar">{{ u.name.charAt(0).toUpperCase() }}</span>
          <div class="ru-info">
            <b>{{ u.name }}</b>
            <span>{{ zone === 'circle' ? `${u.posts} 条动态 · ${u.likes} 获赞` : `${u.posts} 篇笔记 · ${u.likes} 获赞` }}</span>
          </div>
        </li>
      </ul>
      <p v-else class="rail-empty">{{ zone === 'circle' ? '还没有活跃作者，晒第一张照片试试' : '还没有活跃作者，发第一篇笔记试试' }}</p>
    </section>

    <!-- 热门标签 -->
    <section class="rail-card">
      <h4>热门标签</h4>
      <div v-if="tags.length" class="rail-tags">
        <button
          v-for="t in tags"
          :key="t.name"
          :class="{ on: activeTag === t.name }"
          @click="toggleTag(t.name)"
        ># {{ t.name }}<i>{{ t.count }}</i></button>
      </div>
      <p v-else class="rail-empty">发帖时添加标签，就会出现在这里</p>
    </section>
  </aside>
</template>

<style scoped>
/* ===== 右栏容器：固定宽度 + 吸顶 ===== */
.rail {
  width: 292px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 16px;
  position: sticky;
  top: 16px;
}
@media (max-width: 1080px) {
  .rail {
    display: none;
  }
}

/* ===== 通用白卡 ===== */
.rail-card {
  background: #fff;
  border-radius: 16px;
  padding: 18px;
  box-shadow: 0 2px 10px rgba(31, 56, 88, 0.05);
}
.rail-card h4 {
  margin: 0 0 14px;
  font-size: 14.5px;
  font-weight: 700;
  color: #1f2a37;
}

/* ===== 玩法卡：深色渐变 ===== */
.rail-play {
  background: linear-gradient(165deg, #1d2f28 0%, #2e4a3e 100%);
  box-shadow: 0 10px 26px rgba(10, 23, 32, 0.35);
}
.rail-play h4 {
  color: #fff;
}
.rail-play .rail-steps b {
  color: #fff;
}
.rail-play .rail-steps span {
  color: rgba(255, 255, 255, 0.55);
}
.rail-play .rail-steps i {
  background: rgba(255, 255, 255, 0.16);
}

/* ===== 玩法步骤 ===== */
.rail-steps {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.rail-steps li {
  display: flex;
  align-items: center;
  gap: 10px;
}
.rail-steps i {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--grad-primary);
  color: #fff;
  font-size: 12px;
  font-weight: 700;
  font-style: normal;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.rail-steps b {
  display: block;
  font-size: 13.5px;
  color: #1f2a37;
}
.rail-steps span {
  display: block;
  font-size: 12px;
  color: #98a3b3;
}

/* ===== 热门标签 ===== */
.rail-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.rail-tags button {
  border: 1px solid #e3ecf5;
  background: #f7fafd;
  color: #4b5768;
  font-size: 12.5px;
  padding: 5px 11px;
  border-radius: 999px;
  cursor: pointer;
  transition: all 0.2s ease;
}
.rail-tags button i {
  font-style: normal;
  color: #b3bdc9;
  margin-left: 4px;
  font-size: 11.5px;
}
.rail-tags button:hover {
  border-color: #bcd8c9;
  color: var(--brand);
}
.rail-tags button.on {
  background: var(--brand);
  border-color: var(--brand);
  color: #fff;
}
.rail-tags button.on i {
  color: rgba(255, 255, 255, 0.7);
}

/* ===== 活跃旅行者 ===== */
.rail-users {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.rail-users li {
  display: flex;
  align-items: center;
  gap: 10px;
}
.rail-empty {
  margin: 0;
  font-size: 12.5px;
  color: #b3bdc9;
  line-height: 1.6;
}
.ru-rank {
  width: 18px;
  font-size: 12px;
  font-weight: 800;
  font-style: normal;
  color: #b3bdc9;
  text-align: center;
  flex-shrink: 0;
}
.ru-rank.is-top {
  color: #ff9a44;
}
.ru-avatar {
  width: 34px;
  height: 34px;
  border-radius: 50%;
  background: linear-gradient(135deg, #ffb199 0%, #ff6f91 100%);
  color: #fff;
  font-size: 14px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.ru-info {
  min-width: 0;
}
.ru-info b {
  display: block;
  font-size: 13.5px;
  color: #1f2a37;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ru-info span {
  display: block;
  font-size: 12px;
  color: #98a3b3;
}
</style>
