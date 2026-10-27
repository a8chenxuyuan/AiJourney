<!-- ResultDailyPlans.vue：每日行程卡片——景点/餐饮/酒店、单日地图、收藏与反馈入口 -->
<script setup lang="ts">
import type { TripPlan, AttractionInfo, FavoriteRecord } from '@/api/trip'
import { Card, Alert, Row, Col, Tag, Timeline, Image, Rate, Divider, Button } from 'ant-design-vue'
import PlanMap from '@/components/PlanMap.vue'

const props = defineProps<{
  plan: TripPlan | null
  dayColor: (dayIndex: number) => string
  isMultiCity: boolean
  favoriteMap: Map<string, FavoriteRecord>
}>()

const emit = defineEmits<{
  (e: 'edit-day', dayIndex: number): void
  (e: 'toggle-favorite', payload: {
    itemType: 'attraction' | 'hotel' | 'restaurant'
    item: unknown
    name: string
  }): void
}>()

// CITY_TAG_COLORS：城市 Tag 的候选配色（按城市在行程中的顺序循环取色）
const CITY_TAG_COLORS = ['blue', 'green', 'purple', 'orange', 'cyan', 'magenta', 'volcano', 'geekblue']

/**
 * cityTagColor：返回某城市对应的 Tag 颜色（同一城市恒定同色，便于跨天区分）
 */
const cityTagColor = (city?: string | null) => {
  if (!city) return 'default'
  const idx = (props.plan?.cities || []).findIndex((c) => c.city === city)
  return idx >= 0 ? CITY_TAG_COLORS[idx % CITY_TAG_COLORS.length] : 'default'
}

/**
 * mealTypeText：将餐饮类型转为中文
 */
const mealTypeText = (type?: string) => {
  const map: Record<string, string> = {
    breakfast: '早餐',
    lunch: '午餐',
    dinner: '晚餐'
  }
  return map[type || ''] || type || '餐饮'
}

/**
 * isItemFavorited：按名称判断任意条目（景点/酒店/餐厅）是否已收藏
 */
const isItemFavorited = (name?: string): boolean => !!name && props.favoriteMap.has(name)

/**
 * isFavorited：判断景点是否已收藏
 */
const isFavorited = (spot: AttractionInfo): boolean => isItemFavorited(spot.name)

/**
 * toggleFavorite：收藏 / 取消收藏任意条目（景点、酒店、餐厅通用），交由页面统一处理
 */
const toggleFavorite = (
  itemType: 'attraction' | 'hotel' | 'restaurant',
  item: unknown,
  name: string
) => emit('toggle-favorite', { itemType, item, name })
</script>

<template>
  <Card title="每日行程" style="margin-bottom: 24px; border-radius: 12px;">
    <div v-if="plan?.day_plans && plan.day_plans.length > 0">
      <Card
        v-for="day in plan.day_plans"
        :key="day.day_index"
        size="small"
        style="margin-bottom: 24px; border-radius: 12px; background: #fafafa;"
        :body-style="{ padding: '20px' }"
      >
        <Row :gutter="[24, 24]">
          <!-- 左侧：当天行程内容 -->
          <Col :xs="24" :lg="14">
            <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 12px; flex-wrap: wrap;">
              <h3 style="margin: 0;">第 {{ day.day_index }} 天</h3>
              <Tag color="blue">{{ day.date }}</Tag>
              <!-- 多城联游：当日所在城市 Tag（按城市配色区分） -->
              <Tag v-if="isMultiCity && day.city" :color="cityTagColor(day.city)">📍 {{ day.city }}</Tag>
            </div>
            <!-- 城际交通说明（如"上午高铁 杭州→苏州（约1.5小时）"） -->
            <Alert
              v-if="day.intercity_note"
              type="info"
              show-icon
              :message="day.intercity_note"
              style="margin-bottom: 12px;"
            />
            <p v-if="day.description" style="color: #888; font-size: 14px; margin-bottom: 16px;">
              {{ day.description }}
            </p>
            <p v-if="day.transportation" style="color: #555; font-size: 13px; margin-bottom: 16px;">
              <strong>当日交通：</strong>{{ day.transportation }}
            </p>

            <!-- 景点卡片列表 -->
            <div v-if="day.attractions && day.attractions.length > 0" style="margin-bottom: 16px;">
              <p style="font-weight: 600; margin-bottom: 12px;">景点安排</p>
              <Timeline>
                <Timeline.Item v-for="(spot, idx) in day.attractions" :key="idx">
                  <Card size="small" style="border-radius: 8px; margin-bottom: 8px;">
                    <Row :gutter="[12, 12]">
                      <Col :span="7">
                        <Image
                          :src="spot.image_url || 'https://placehold.co/120x90?text=景点'"
                          :alt="spot.name"
                          style="width: 100%; height: 90px; object-fit: cover; border-radius: 6px;"
                          fallback="https://placehold.co/120x90?text=景点"
                        />
                      </Col>
                      <Col :span="17">
                        <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
                          <strong>{{ spot.name }}</strong>
                          <Tag v-if="spot.duration" size="small" color="orange">{{ spot.duration }}</Tag>
                          <Tag v-if="spot.ticket_price" size="small" color="green">¥{{ spot.ticket_price }}</Tag>
                          <a
                            style="margin-left: auto; font-size: 13px;"
                            :style="{ color: isFavorited(spot) ? '#faad14' : '#1890ff' }"
                            @click="toggleFavorite('attraction', spot, spot.name)"
                          >{{ isFavorited(spot) ? '★ 已收藏' : '☆ 收藏' }}</a>
                        </div>
                        <div v-if="spot.rating" style="margin-top: 4px;">
                          <Rate :value="spot.rating / 5 * 5" disabled allow-half :count="5" style="font-size: 12px;" />
                          <span style="font-size: 12px; color: #888; margin-left: 6px;">{{ spot.rating }} 分</span>
                        </div>
                        <p v-if="spot.description" style="color: #666; font-size: 13px; margin: 6px 0 0; line-height: 1.5;">
                          {{ spot.description }}
                        </p>
                        <div v-if="spot.phone || spot.business_hours || spot.detail_url" style="margin-top: 8px; font-size: 12px; color: #888;">
                          <span v-if="spot.phone">电话：{{ spot.phone }}</span>
                          <span v-if="spot.business_hours" style="margin-left: 8px;">营业：{{ spot.business_hours }}</span>
                          <a
                            v-if="spot.detail_url"
                            :href="spot.detail_url"
                            target="_blank"
                            style="margin-left: 8px; color: #1890ff;"
                          >查看详情</a>
                        </div>
                      </Col>
                    </Row>
                  </Card>
                </Timeline.Item>
              </Timeline>
            </div>

            <!-- 餐饮安排 -->
            <div v-if="day.meals && day.meals.length > 0" style="margin-bottom: 16px;">
              <p style="font-weight: 600; margin-bottom: 12px;">餐饮安排</p>
              <Row :gutter="[12, 12]">
                <Col v-for="(meal, idx) in day.meals" :key="`meal-${idx}`" :xs="24" :sm="12" :md="8">
                  <Card size="small" style="border-radius: 8px; background: #fff;">
                    <Row :gutter="[10, 10]">
                      <Col :span="8">
                        <Image
                          :src="meal.image_url || 'https://placehold.co/120x90?text=餐厅'"
                          :alt="meal.name || '餐厅'"
                          style="width: 100%; height: 72px; object-fit: cover; border-radius: 6px;"
                          fallback="https://placehold.co/120x90?text=餐厅"
                        />
                      </Col>
                      <Col :span="16">
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                          <strong>{{ mealTypeText(meal.type) }}</strong>
                          <Tag v-if="meal.estimated_cost" size="small" color="green">人均 ¥{{ meal.estimated_cost }}</Tag>
                        </div>
                        <p v-if="meal.name" style="margin: 4px 0 0; color: #333; font-weight: 500;">
                          {{ meal.name }}
                          <a
                            v-if="meal.name"
                            style="font-size: 12px; font-weight: 400; margin-left: 6px; color: #1890ff;"
                            :style="{ color: isItemFavorited(meal.name) ? '#faad14' : '#1890ff' }"
                            @click="toggleFavorite('restaurant', meal, meal.name)"
                          >{{ isItemFavorited(meal.name) ? '★ 已收藏' : '☆ 收藏' }}</a>
                        </p>
                        <div v-if="meal.rating" style="margin-top: 2px;">
                          <Rate :value="meal.rating / 5 * 5" disabled allow-half :count="5" style="font-size: 11px;" />
                          <span style="font-size: 11px; color: #888; margin-left: 4px;">{{ meal.rating }} 分</span>
                        </div>
                        <p v-if="meal.cuisine" style="margin: 2px 0 0; font-size: 12px; color: #888;">{{ meal.cuisine }}</p>
                        <p v-if="meal.address || meal.location_name" style="margin: 2px 0 0; font-size: 12px; color: #888;">
                          <span>地址：{{ meal.address || meal.location_name }}</span>
                        </p>
                        <div v-if="meal.phone || meal.business_hours || meal.detail_url" style="margin-top: 4px; font-size: 11px; color: #888;">
                          <span v-if="meal.phone">电话：{{ meal.phone }}</span>
                          <span v-if="meal.business_hours" style="margin-left: 6px;">营业：{{ meal.business_hours }}</span>
                          <a
                            v-if="meal.detail_url"
                            :href="meal.detail_url"
                            target="_blank"
                            style="margin-left: 6px; color: #1890ff;"
                          >查看详情</a>
                        </div>
                      </Col>
                    </Row>
                  </Card>
                </Col>
              </Row>
            </div>

            <!-- 酒店 -->
            <div v-if="day.hotel">
              <p style="font-weight: 600; margin-bottom: 12px;">推荐酒店</p>
              <Card size="small" style="border-radius: 8px; background: #fff;">
                <Row :gutter="[12, 12]">
                  <Col :span="7">
                    <Image
                      :src="day.hotel.image_url || 'https://placehold.co/120x90?text=酒店'"
                      :alt="day.hotel.name"
                      style="width: 100%; height: 90px; object-fit: cover; border-radius: 6px;"
                      fallback="https://placehold.co/120x90?text=酒店"
                    />
                  </Col>
                  <Col :span="17">
                    <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
                      <strong>{{ day.hotel.name }}</strong>
                      <Tag v-if="day.hotel.price_per_night" size="small" color="green">¥{{ day.hotel.price_per_night }} / 晚</Tag>
                      <a
                        style="font-size: 12px;"
                        :style="{ color: isItemFavorited(day.hotel.name) ? '#faad14' : '#1890ff' }"
                        @click="toggleFavorite('hotel', day.hotel, day.hotel.name)"
                      >{{ isItemFavorited(day.hotel.name) ? '★ 已收藏' : '☆ 收藏' }}</a>
                    </div>
                    <div v-if="day.hotel.rating" style="margin-top: 4px;">
                      <Rate :value="day.hotel.rating / 5 * 5" disabled allow-half :count="5" style="font-size: 12px;" />
                      <span style="font-size: 12px; color: #888; margin-left: 6px;">{{ day.hotel.rating }} 分</span>
                    </div>
                    <div v-if="day.hotel.phone || day.hotel.business_hours || day.hotel.detail_url" style="margin-top: 8px; font-size: 12px; color: #888;">
                      <span v-if="day.hotel.phone">电话：{{ day.hotel.phone }}</span>
                      <span v-if="day.hotel.business_hours" style="margin-left: 8px;">营业：{{ day.hotel.business_hours }}</span>
                      <a
                        v-if="day.hotel.detail_url"
                        :href="day.hotel.detail_url"
                        target="_blank"
                        style="margin-left: 8px; color: #1890ff;"
                      >查看详情</a>
                    </div>
                  </Col>
                </Row>
              </Card>
            </div>
          </Col>

          <!-- 右侧：当天地图 -->
          <Col :xs="24" :lg="10">
            <PlanMap
              :markers="day.attractions.map((a, i) => ({
                longitude: a.location?.longitude || 0,
                latitude: a.location?.latitude || 0,
                title: a.name,
                order: i + 1,
                color: dayColor(day.day_index),
                info: { rating: a.rating, ticket: a.ticket_price, hours: a.business_hours }
              }))"
              :polyline="day.route_polyline || ''"
              :line-color="dayColor(day.day_index)"
              :center="day.map_center ? {
                longitude: day.map_center.longitude,
                latitude: day.map_center.latitude
              } : undefined"
              style="width: 100%; height: 360px; border-radius: 12px; overflow: hidden;"
            />
          </Col>
        </Row>

        <!-- 当天反馈操作栏 -->
        <Divider style="margin: 16px 0 12px;" />
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <span style="color: #888; font-size: 13px;">对这一天不满意？</span>
          <Button type="link" @click="emit('edit-day', day.day_index)">
            修改这一天
          </Button>
        </div>
      </Card>
    </div>
    <div v-else style="color: #888;">
      暂无详细行程数据，以下为示例：
      <Timeline>
        <Timeline.Item>示例景点 A <Tag size="small">约 2 小时</Tag></Timeline.Item>
        <Timeline.Item>示例餐厅 B <Tag size="small">餐饮</Tag></Timeline.Item>
        <Timeline.Item>示例景点 C <Tag size="small">约 1.5 小时</Tag></Timeline.Item>
      </Timeline>
    </div>
  </Card>
</template>
