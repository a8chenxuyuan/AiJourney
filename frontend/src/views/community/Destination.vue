<!--
  src/views/Destination.vue：目的地聚合页
  作用：一页聚合「目的地简介（百科）+ 精选攻略 + 真实游记 + 热门行程模板」，
       并内置 AI 目的地问答框；规划按钮携带城市跳首页自动填充。
-->

<script setup lang="ts">
/**
 * 主要流程：
 * 1. 按路由城市参数加载聚合数据（路由换城市时重载）；
 * 2. 问答框提交 → destination/ask → 展示 AI 回复（支持多轮追加气泡）；
 * 3. 模板跳社区帖子（可照着走），游记跳公开分享页，攻略跳详情页。
 */
import { ref, computed, watch, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { Button, Card, Empty, Input, Spin, Tag } from 'ant-design-vue'
import { getDestination, destinationAsk, type DestinationData } from '@/api/community/guides'

const router = useRouter()
const route = useRoute()

const loading = ref(true)
const data = ref<DestinationData | null>(null)

// ==================== AI 问答 ====================
// question：输入框内容；asking：请求中；messages：问答气泡（user/assistant 交替）
const question = ref('')
const asking = ref(false)
const messages = ref<{ role: 'user' | 'assistant'; text: string }[]>([])

/**
 * fetchDestination：加载目的地聚合数据
 */
const fetchDestination = async () => {
  loading.value = true
  data.value = null
  try {
    const res = await getDestination(String(route.params.city || ''))
    if (res.success && res.data) {
      data.value = res.data
    }
  } finally {
    loading.value = false
  }
}

/**
 * ask：提交问题，把回答追加到气泡流（失败时提示并终止）
 */
const ask = async () => {
  const q = question.value.trim()
  if (!q || asking.value) return
  const city = data.value?.city || String(route.params.city || '')
  messages.value.push({ role: 'user', text: q })
  question.value = ''
  asking.value = true
  try {
    const res = await destinationAsk(city, q)
    if (res.success && res.data) {
      messages.value.push({ role: 'assistant', text: res.data.reply })
    } else {
      messages.value.push({ role: 'assistant', text: res.message || '回答失败，请稍后再试。' })
    }
  } catch {
    messages.value.push({ role: 'assistant', text: '网络异常，请稍后再试。' })
  } finally {
    asking.value = false
  }
}

/**
 * planTrip：去规划 → 首页带城市预填
 */
const planTrip = () => router.push({ path: '/', query: { city: String(route.params.city || '') } })

// city：展示用城市名
const city = computed(() => String(route.params.city || ''))

// 路由城市变化时重载（同页面跳转不重建组件）
watch(() => route.params.city, () => {
  if (route.name === 'Destination') {
    messages.value = []
    fetchDestination()
  }
})

onMounted(fetchDestination)
</script>

<template>
  <div class="page-fade" style="max-width: 1280px; margin: 0 auto; padding: 0 16px;">
    <Spin :spinning="loading">
      <!-- Hero：城市名 + 百科简介 -->
      <div class="dest-hero">
        <div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; flex-wrap: wrap;">
          <div style="flex: 1; min-width: 260px;">
            <h1 style="color: #fff; font-size: 32px; margin: 0 0 12px;">📍 {{ city }}</h1>
            <p style="color: rgba(255,255,255,0.92); line-height: 1.9; margin: 0; font-size: 14px;">
              {{ data?.summary || '这座城市暂无百科简介，往下看看游记与攻略吧。' }}
            </p>
            <a
              v-if="data?.summary_url"
              :href="data.summary_url"
              target="_blank"
              style="color: #ffe58f; font-size: 13px;"
            >查看百科词条 →</a>
          </div>
          <Button type="primary" size="large" style="height: 46px; padding: 0 28px; border-radius: 999px;"
                  @click="planTrip">
            ✨ 规划 {{ city }} 行程
          </Button>
        </div>
      </div>

      <Empty v-if="!loading && !data" :description="`「${city}」的内容加载失败`" />

      <template v-else-if="data">
        <!-- AI 目的地问答 -->
        <Card style="border-radius: 14px; margin-top: 20px;">
          <template #title>🤖 问问 AI 顾问</template>
          <div v-if="messages.length" style="display: flex; flex-direction: column; gap: 10px; margin-bottom: 14px; max-height: 360px; overflow-y: auto;">
            <div
              v-for="(m, idx) in messages"
              :key="idx"
              :style="{
                alignSelf: m.role === 'user' ? 'flex-end' : 'flex-start',
                maxWidth: '86%',
                padding: '10px 14px',
                borderRadius: '12px',
                lineHeight: '1.8',
                fontSize: '14px',
                background: m.role === 'user' ? '#e6f4ff' : '#f6f6f6',
                whiteSpace: 'pre-wrap'
              }"
            >{{ m.text }}</div>
            <div v-if="asking" style="color: #999; font-size: 13px;">AI 顾问正在思考中…</div>
          </div>
          <div style="display: flex; gap: 10px;">
            <Input
              v-model:value="question"
              :placeholder="`问问「${city}」的玩法、美食、交通…`"
              :maxlength="200"
              @press-enter="ask"
            />
            <Button type="primary" :loading="asking" @click="ask">提问</Button>
          </div>
        </Card>

        <!-- 热门行程模板（社区公开帖，可照着走） -->
        <Card v-if="data.templates.length" style="border-radius: 14px; margin-top: 20px;">
          <template #title>🔥 热门行程模板</template>
          <div
            v-for="tpl in data.templates"
            :key="tpl.post_id"
            style="display: flex; justify-content: space-between; align-items: center; padding: 12px 0; border-bottom: 1px solid #f0f0f0; cursor: pointer; gap: 12px;"
            @click="router.push(`/community/${tpl.post_id}`)"
          >
            <div style="min-width: 0;">
              <p style="margin: 0; font-size: 15px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">{{ tpl.title }}</p>
              <p style="margin: 4px 0 0; color: #999; font-size: 13px;">
                ✍️ <a style="color: inherit;" @click.stop="tpl.user_id && router.push(`/user/${tpl.user_id}`)">{{ tpl.author }}</a> · {{ tpl.travel_days }} 天
              </p>
            </div>
            <div style="display: flex; align-items: center; gap: 10px; flex-shrink: 0;">
              <Tag color="orange">❤️ {{ tpl.like_count }}</Tag>
              <span style="color: var(--brand); font-size: 13px;">照着走 →</span>
            </div>
          </div>
        </Card>

        <!-- 真实游记 -->
        <Card v-if="data.journals.length" style="border-radius: 14px; margin-top: 20px;">
          <template #title>📔 真实游记</template>
          <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 14px;">
            <div
              v-for="j in data.journals"
              :key="j.id"
              style="border: 1px solid #f0f0f0; border-radius: 12px; overflow: hidden; cursor: pointer; transition: box-shadow .2s;"
              @click="j.public_token && router.push(`/journal/${j.public_token}`)"
            >
              <img
                v-if="j.cover_url"
                :src="j.cover_url"
                style="width: 100%; height: 130px; object-fit: cover; display: block;"
              />
              <div v-else style="width: 100%; height: 130px; background: linear-gradient(135deg, #a18cd1 0%, #fbc2eb 100%); display: flex; align-items: center; justify-content: center; font-size: 36px;">📔</div>
              <div style="padding: 10px 12px;">
                <p style="margin: 0; font-weight: 600; font-size: 14px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">{{ j.title }}</p>
                <p style="margin: 4px 0 0; color: #999; font-size: 12px;">✍️ <a style="color: inherit;" @click.stop="j.user_id && router.push(`/user/${j.user_id}`)">{{ j.author }}</a> · {{ j.travel_days }} 天</p>
              </div>
            </div>
          </div>
        </Card>

        <!-- 社区笔记（可点赞/评论/照着走） -->
        <Card v-if="data.notes?.length" style="border-radius: 14px; margin-top: 20px;">
          <template #title>📝 社区笔记</template>
          <div
            v-for="n in data.notes"
            :key="n.id"
            style="display: flex; justify-content: space-between; align-items: center; padding: 10px 0; border-bottom: 1px solid #f0f0f0; cursor: pointer; gap: 12px;"
            @click="router.push(`/community/${n.id}`)"
          >
            <span style="font-size: 15px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">📝 {{ n.title }}</span>
            <span style="color: #999; font-size: 13px; flex-shrink: 0;">❤️ {{ n.like_count || 0 }} · 💬 {{ n.comment_count || 0 }}</span>
          </div>
        </Card>

        <!-- 精选攻略 -->
        <Card v-if="data.guides.length" style="border-radius: 14px; margin-top: 20px; margin-bottom: 32px;">
          <template #title>🧳 精选攻略</template>
          <div
            v-for="g in data.guides"
            :key="g.id"
            style="display: flex; justify-content: space-between; align-items: center; padding: 10px 0; border-bottom: 1px solid #f0f0f0; cursor: pointer; gap: 12px;"
            @click="router.push(`/guides/${g.id}`)"
          >
            <span style="font-size: 15px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">📄 {{ g.title }}</span>
            <span style="color: var(--brand); font-size: 13px; flex-shrink: 0;">查看 →</span>
          </div>
        </Card>
      </template>
    </Spin>
  </div>
</template>

<style scoped>
/* 目的地 Hero：品牌渐变横幅，简介文字反白 */
.dest-hero {
  margin-top: 24px;
  padding: 28px 28px;
  border-radius: 16px;
  background: var(--grad-primary);
  box-shadow: 0 8px 24px rgba(23, 125, 220, 0.25);
}
</style>
