<!--
  src/components/MapContainer.vue：高德地图容器组件
  作用：使用 @amap/amap-jsapi-loader 初始化高德地图，接收 markers 数组打点；
       若未配置 VITE_AMAP_KEY，则只初始化空地图并提示
-->

<script setup lang="ts">
/**
 * 组合式 API 入口
 * 主要流程：
 * 1. 从 props 读取容器样式与 markers 数组
 * 2. 从 import.meta.env.VITE_AMAP_KEY 读取高德 Key
 * 3. 组件挂载后调用 AMapLoader 加载高德 JSAPI 并初始化地图
 * 4. 若传入 markers，则在地图上添加点标记
 */

// 引入 Vue 的响应式 API 与生命周期钩子
import { ref, onMounted, watch } from 'vue'
// 引入高德 JSAPI Loader
import AMapLoader from '@amap/amap-jsapi-loader'
// 引入 Ant Design Vue 警告提示组件
import { Alert } from 'ant-design-vue'

/**
 * MapMarker：地图点标记对象
 */
export interface MapMarker {
  longitude: number
  latitude: number
  title?: string
}

/**
 * MapContainerProps：组件 props 类型
 * style：容器样式对象
 * markers：需要在地图上展示的点标记数组，默认为空
 */
interface MapContainerProps {
  style?: Record<string, string>
  markers?: MapMarker[]
}

// 声明 props，设置 markers 默认值为空数组
const props = withDefaults(defineProps<MapContainerProps>(), {
  markers: () => []
})

// mapContainerRef：地图容器 DOM 引用
const mapContainerRef = ref<HTMLDivElement | null>(null)
// amapInstance：高德地图实例，用于后续添加/清除标记
let amapInstance: any = null
// amapObject：AMap 全局对象
let AMap: any = null
// hasKey：标记是否配置了高德 Key
const hasKey = ref(true)
// mapLoaded：标记地图是否初始化完成
const mapLoaded = ref(false)

// amapKey：从环境变量读取高德 JSAPI Key
const amapKey = import.meta.env.VITE_AMAP_KEY

/**
 * addMarkers：在地图上添加点标记
 * @param markers 点标记数组
 */
const addMarkers = (markers: MapMarker[]) => {
  if (!amapInstance || !AMap || markers.length === 0) return

  // 遍历 markers 创建 Marker 并添加到地图
  markers.forEach((marker) => {
    const amapMarker = new AMap.Marker({
      position: new AMap.LngLat(marker.longitude, marker.latitude),
      title: marker.title || ''
    })
    amapInstance.add(amapMarker)
  })

  // 自动调整地图视野以展示所有标记
  amapInstance.setFitView()
}

/**
 * initMap：初始化高德地图
 * 作用：调用 AMapLoader 加载 JSAPI，创建地图实例，并添加默认标记
 */
const initMap = async () => {
  // 若未配置 Key，则标记 hasKey 为 false 并退出
  if (!amapKey) {
    hasKey.value = false
    return
  }

  try {
    AMap = await AMapLoader.load({
      key: amapKey,
      version: '2.0',
      // 按需加载插件，Marker 插件用于打点
      plugins: ['AMap.Marker']
    })

    // 在 DOM 容器中创建地图实例，默认中心点为天安门
    amapInstance = new AMap.Map(mapContainerRef.value as HTMLDivElement, {
      zoom: 12,
      center: [116.397428, 39.90923]
    })

    mapLoaded.value = true
    // 添加传入的 markers
    addMarkers(props.markers)
  } catch (error) {
    console.error('高德地图初始化失败', error)
    hasKey.value = false
  }
}

// 组件挂载后初始化地图
onMounted(() => {
  initMap()
})

// 监听 markers 变化，当地图已初始化且 markers 更新时重新打点
watch(
  () => props.markers,
  (newMarkers) => {
    if (amapInstance && AMap) {
      // 简化处理：清除所有覆盖物后重新添加
      amapInstance.clearMap()
      addMarkers(newMarkers)
    }
  },
  { deep: true }
)
</script>

<template>
  <div style="position: relative; width: 100%; height: 100%; min-height: 300px;">
    <!-- 未配置 Key 时的提示 -->
    <Alert
      v-if="!hasKey"
      message="未配置高德地图 Key"
      description="请在 .env 文件中设置 VITE_AMAP_KEY，否则地图无法正常加载。"
      type="warning"
      show-icon
      style="position: absolute; top: 16px; left: 16px; right: 16px; z-index: 10;"
    />
    <!-- 地图容器 DOM -->
    <div ref="mapContainerRef" :style="{ width: '100%', height: '100%', minHeight: '300px', ...props.style }">
    </div>
  </div>
</template>
