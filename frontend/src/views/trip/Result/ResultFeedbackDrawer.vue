<!-- ResultFeedbackDrawer.vue：修改意见抽屉——快捷标签、具体意见提交/编辑与候选池搜索 -->
<script setup lang="ts">
import { ref } from 'vue'
import { Drawer, Select, Input, Button, Spin, List, Image, Rate, message } from 'ant-design-vue'
import { submitPlanFeedback, editPlanFeedback, type PlanFeedbackRequest } from '@/api/trip'
import { searchPoi, type PoiItem } from '@/api/trip/map'

const props = defineProps<{
  planId: string
  city?: string
}>()

const emit = defineEmits<{
  (e: 'submitted'): void
}>()

// feedbackMode：'create' 新建反馈 / 'edit' 编辑反馈
const feedbackMode = ref<'create' | 'edit'>('create')
const feedbackDrawerVisible = ref(false)
const currentDayIndex = ref<number | null>(null)
const editingFeedbackId = ref<number | null>(null)
const feedbackTags = ref<string[]>([])
const feedbackText = ref('')
const feedbackSubmitting = ref(false)
const candidateLoading = ref(false)
const candidateList = ref<PoiItem[]>([])
const candidateKeyword = ref('')

// 反馈快捷标签选项
const feedbackTagsOptions = [
  { label: '餐饮不满意', value: '餐饮不满意' },
  { label: '景点不喜欢', value: '景点不喜欢' },
  { label: '行程太满', value: '行程太满' },
  { label: '想加某地', value: '想加某地' },
  { label: '想删某地', value: '想删某地' },
  { label: '换酒店', value: '换酒店' },
  { label: '其他', value: '其他' }
]

/**
 * open：打开反馈抽屉
 * @param dayIndex 第几天（从 1 开始）
 * @param mode 模式：create 或 edit
 * @param feedback 可选，编辑时传入已有反馈
 */
const open = (
  dayIndex: number,
  mode: 'create' | 'edit' = 'create',
  feedback?: { feedback_id: number; tags?: string[]; raw_text?: string }
) => {
  currentDayIndex.value = dayIndex
  feedbackMode.value = mode
  feedbackDrawerVisible.value = true

  if (mode === 'edit' && feedback) {
    editingFeedbackId.value = feedback.feedback_id
    feedbackTags.value = feedback.tags || []
    feedbackText.value = feedback.raw_text || ''
  } else {
    editingFeedbackId.value = null
    feedbackTags.value = []
    feedbackText.value = ''
  }
  candidateList.value = []
  candidateKeyword.value = ''
}

/**
 * closeFeedbackDrawer：关闭反馈抽屉
 */
const closeFeedbackDrawer = () => {
  feedbackDrawerVisible.value = false
  currentDayIndex.value = null
  feedbackMode.value = 'create'
  editingFeedbackId.value = null
  feedbackTags.value = []
  feedbackText.value = ''
  candidateList.value = []
  candidateKeyword.value = ''
}

/**
 * handleSearchCandidates：根据关键词搜索候选池
 */
const handleSearchCandidates = async () => {
  if (!candidateKeyword.value.trim() || !props.city) return
  candidateLoading.value = true
  try {
    const res = await searchPoi(candidateKeyword.value.trim(), props.city, 10)
    if (res.success && Array.isArray(res.data)) {
      candidateList.value = res.data
    } else {
      candidateList.value = []
    }
  } catch (error) {
    console.error('搜索候选池失败', error)
    candidateList.value = []
  } finally {
    candidateLoading.value = false
  }
}

/**
 * handleSubmitFeedback：提交或更新反馈
 */
const handleSubmitFeedback = async () => {
  if (!currentDayIndex.value || !feedbackText.value.trim()) {
    message.warning('请填写反馈内容')
    return
  }

  feedbackSubmitting.value = true
  const feedback: PlanFeedbackRequest = {
    day_index: currentDayIndex.value,
    tags: feedbackTags.value,
    raw_text: feedbackText.value
  }

  try {
    let res
    if (feedbackMode.value === 'edit' && editingFeedbackId.value) {
      res = await editPlanFeedback(props.planId, editingFeedbackId.value, feedback)
    } else {
      res = await submitPlanFeedback(props.planId, feedback)
    }

    if (res.success) {
      // 单条意见只保存到数据库，点"根据所有反馈重新生成行程"时统一处理
      message.success(
        feedbackMode.value === 'edit'
          ? '意见已更新，点底部"根据所有反馈重新生成行程"统一处理'
          : '意见已保存，点底部"根据所有反馈重新生成行程"统一处理'
      )
      closeFeedbackDrawer()
      emit('submitted')
    }
  } catch (error) {
    console.error('提交反馈失败', error)
  } finally {
    feedbackSubmitting.value = false
  }
}

defineExpose({ open })
</script>

<template>
  <Drawer
    v-model:visible="feedbackDrawerVisible"
    :title="(feedbackMode === 'edit' ? '编辑反馈' : '修改这一天') + (currentDayIndex ? ` · 第 ${currentDayIndex} 天` : '')"
    placement="right"
    width="480"
    @close="closeFeedbackDrawer"
  >
    <div style="margin-bottom: 16px;">
      <p style="font-weight: 600; margin-bottom: 8px;">快捷标签</p>
      <Select
        v-model:value="feedbackTags"
        mode="multiple"
        style="width: 100%;"
        :options="feedbackTagsOptions"
        placeholder="选择反馈类型"
      />
    </div>

    <div style="margin-bottom: 16px;">
      <p style="font-weight: 600; margin-bottom: 8px;">具体修改意见</p>
      <Input.TextArea
        v-model:value="feedbackText"
        :rows="4"
        placeholder="例如：这家餐厅太贵了，想换一家海鲜餐厅；或者这一天行程太满，删掉一个景点"
      />
    </div>

    <div style="margin-bottom: 16px;">
      <p style="font-weight: 600; margin-bottom: 8px;">候选池</p>
      <div style="display: flex; gap: 8px; margin-bottom: 12px;">
        <Input
          v-model:value="candidateKeyword"
          placeholder="输入想替换/添加的地点类型，如：海鲜餐厅、博物馆"
          @press-enter="handleSearchCandidates"
        />
        <Button type="primary" :loading="candidateLoading" @click="handleSearchCandidates">
          搜索
        </Button>
      </div>
      <Spin :spinning="candidateLoading">
        <div v-if="candidateList.length > 0" style="max-height: 300px; overflow-y: auto;">
          <List :data-source="candidateList" size="small">
            <template #renderItem="{ item }">
              <List.Item>
                <div style="display: flex; gap: 10px; width: 100%;">
                  <Image
                    :src="item.image_url || 'https://placehold.co/80x60?text=POI'"
                    style="width: 80px; height: 60px; object-fit: cover; border-radius: 6px; flex-shrink: 0;"
                    fallback="https://placehold.co/80x60?text=POI"
                  />
                  <div style="flex: 1; min-width: 0;">
                    <div style="font-weight: 500;">{{ item.name }}</div>
                    <div v-if="item.rating" style="font-size: 12px; color: #888;">
                      <Rate :value="item.rating / 5 * 5" disabled allow-half :count="5" style="font-size: 11px;" />
                      {{ item.rating }} 分
                    </div>
                    <div v-if="item.address" style="font-size: 12px; color: #888; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">
                      {{ item.address }}
                    </div>
                  </div>
                </div>
              </List.Item>
            </template>
          </List>
        </div>
        <div v-else-if="!candidateLoading" style="color: #888; text-align: center; padding: 24px 0;">
          输入关键词搜索候选替换项
        </div>
      </Spin>
    </div>

    <div style="display: flex; justify-content: flex-end; gap: 12px; margin-top: 24px;">
      <Button @click="closeFeedbackDrawer">取消</Button>
      <Button type="primary" :loading="feedbackSubmitting" @click="handleSubmitFeedback">
        {{ feedbackMode === 'edit' ? '更新反馈' : '提交反馈' }}
      </Button>
    </div>
  </Drawer>
</template>
