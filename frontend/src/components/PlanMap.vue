<!--
  src/components/PlanMap.vue：行程地图组件
  作用：使用 @amap/amap-jsapi-loader 初始化高德地图，
       展示景点标记（带序号圆点 + 点击信息窗）、路线 polyline，并自动调整视野。
  升级说明：
       1. 标记支持 order（序号）与 color（主题色），以数字圆点样式渲染，直观表达游览顺序；
       2. 点击标记弹出 InfoWindow，显示评分 / 门票 / 营业时间等信息；
       3. 新增 polylines 多线 prop（每条可配独立颜色），用于"全程总览"按天配色画线；
       4. 保留原 polyline 单线 prop，兼容每日行程地图的既有用法。
-->

<script setup lang="ts">
/**
 * 组合式 API 入口
 * 主要流程：
 * 1. 从 props 读取 markers、polyline/polylines、center、style
 * 2. 从 import.meta.env.VITE_AMAP_KEY 读取高德 Key
 * 3. 组件挂载后调用 AMapLoader 加载高德 JSAPI 并初始化地图
 * 4. 添加序号标记、绑定信息窗、绘制路线、调整视野
 */

// 引入 Vue 的响应式 API 与生命周期钩子
import { ref, onMounted, watch } from 'vue'
// 引入高德 JSAPI Loader
import AMapLoader from '@amap/amap-jsapi-loader'
// 引入 Ant Design Vue 警告提示组件
import { Alert } from 'ant-design-vue'

/**
 * MapMarkerInfo：点击标记时信息窗展示的补充信息
 */
export interface MapMarkerInfo {
  rating?: number
  ticket?: number | string
  hours?: string
  address?: string
}

/**
 * MapMarker：地图点标记对象
 * order：可选序号（从 1 开始），传入后以数字圆点样式渲染
 * color：可选主题色（默认蓝色），总览地图按天配色
 * info：可选信息窗内容
 */
export interface MapMarker {
  longitude: number
  latitude: number
  title?: string
  order?: number
  color?: string
  info?: MapMarkerInfo
}

/**
 * MapCenter：地图中心点对象
 */
export interface MapCenter {
  longitude: number
  latitude: number
}

/**
 * MapPolyline：一条路线（总览地图按天传入多条）
 * path：坐标串，格式 "lon,lat;lon,lat"
 * color：路线颜色
 */
export interface MapPolyline {
  path: string
  color?: string
}

/**
 * PlanMapProps：组件 props 类型
 */
interface PlanMapProps {
  style?: Record<string, string>
  markers?: MapMarker[]
  /** 单条路线（兼容原每日地图用法） */
  polyline?: string
  /** 多条路线（总览地图按天配色），优先级高于 polyline */
  polylines?: MapPolyline[]
  center?: MapCenter
  /** 路线默认颜色 */
  lineColor?: string
}

// 声明 props，设置默认值
const props = withDefaults(defineProps<PlanMapProps>(), {
  markers: () => [],
  polyline: '',
  polylines: () => [],
  center: undefined,
  lineColor: '#1890ff'
})

// mapContainerRef：地图容器 DOM 引用
const mapContainerRef = ref<HTMLDivElement | null>(null)
// amapInstance：高德地图实例
let amapInstance: any = null
// AMap：高德 JSAPI 全局对象
let AMap: any = null
// hasKey：标记是否配置了高德 Key
const hasKey = ref(true)
// mapLoaded：标记地图是否初始化完成
const mapLoaded = ref(false)
// infoWindow：复用的信息窗实例
let infoWindow: any = null

// amapKey：从环境变量读取高德 JSAPI Key
const amapKey = import.meta.env.VITE_AMAP_KEY

// 默认标记配色（未指定 color 时使用）
const DEFAULT_MARKER_COLOR = '#1890ff'

/**
 * parsePolyline：将 "lon,lat;lon,lat" 字符串解析为高德路径坐标数组
 */
const parsePolyline = (polyline: string): any[] => {
  if (!polyline || !AMap) return []
  const points: any[] = []
  for (const segment of polyline.split(';')) {
    const parts = segment.split(',')
    if (parts.length !== 2) continue
    const lon = parseFloat(parts[0])
    const lat = parseFloat(parts[1])
    if (!isNaN(lon) && !isNaN(lat)) {
      points.push(new AMap.LngLat(lon, lat))
    }
  }
  return points
}

/**
 * buildMarkerContent：生成序号圆点标记的 HTML 内容
 * @param marker 标记数据
 */
const buildMarkerContent = (marker: MapMarker): string => {
  const color = marker.color || DEFAULT_MARKER_COLOR
  const label = marker.order ? String(marker.order) : '·'
  return `
    <div style="position:relative;transform:translate(-50%,-50%);">
      <div style="
        width:28px;height:28px;border-radius:50% 50% 50% 0;
        transform:rotate(-45deg);
        background:${color};border:2px solid #fff;
        box-shadow:0 2px 6px rgba(0,0,0,0.35);
        display:flex;align-items:center;justify-content:center;
      ">
        <span style="transform:rotate(45deg);color:#fff;font-size:12px;font-weight:700;line-height:1;">${label}</span>
      </div>
    </div>
  `
}

/**
 * openInfoWindow：点击标记时打开信息窗
 * @param marker 标记数据
 */
const openInfoWindow = (marker: MapMarker) => {
  if (!amapInstance || !infoWindow) return
  const lines: string[] = []
  if (marker.info?.rating) lines.push(`<span>⭐ ${marker.info.rating} 分</span>`)
  if (marker.info?.ticket !== undefined && marker.info?.ticket !== null && marker.info?.ticket !== '') {
    lines.push(`<span>🎫 门票 ¥${marker.info.ticket}</span>`)
  }
  if (marker.info?.hours) lines.push(`<span>🕐 ${marker.info.hours}</span>`)
  if (marker.info?.address) lines.push(`<span>📍 ${marker.info.address}</span>`)

  infoWindow.setContent(`
    <div style="font-size:13px;line-height:1.7;max-width:220px;word-break:break-all;">
      <div style="font-weight:700;margin-bottom:2px;">${marker.title || '地点'}</div>
      ${lines.length ? lines.join('<br/>') : '<span style="color:#999;">暂无详情</span>'}
    </div>
  `)
  infoWindow.open(amapInstance, [marker.longitude, marker.latitude])
}

/**
 * addMarkers：在地图上添加点标记（序号圆点样式 + 点击信息窗）
 */
const addMarkers = (markers: MapMarker[]) => {
  if (!amapInstance || !AMap || markers.length === 0) return

  markers.forEach((marker) => {
    if (!marker.longitude || !marker.latitude) return
    const amapMarker = new AMap.Marker({
      position: new AMap.LngLat(marker.longitude, marker.latitude),
      title: marker.title || '',
      content: buildMarkerContent(marker),
      anchor: 'center',
      zIndex: marker.order || 10
    })
    // 点击弹出信息窗
    amapMarker.on('click', () => openInfoWindow(marker))
    amapInstance.add(amapMarker)
  })
}

/**
 * collectPolylines：归一化路线数据（polylines 优先，其次 polyline 单线）
 */
const collectPolylines = (): MapPolyline[] => {
  if (props.polylines && props.polylines.length > 0) return props.polylines
  if (props.polyline) return [{ path: props.polyline, color: props.lineColor }]
  return []
}

/**
 * drawPolylines：在地图上绘制路线（多条时各自着色）
 */
const drawPolylines = (polylines: MapPolyline[]) => {
  if (!amapInstance || !AMap || polylines.length === 0) return

  polylines.forEach((line) => {
    const path = parsePolyline(line.path)
    if (path.length < 2) return
    const routeLine = new AMap.Polyline({
      path,
      strokeColor: line.color || props.lineColor || '#1890ff',
      strokeWeight: 4,
      strokeOpacity: 0.85,
      strokeStyle: 'dashed',
      showDir: true
    })
    amapInstance.add(routeLine)
  })
}

/**
 * fitView：调整地图视野以展示所有标记和路线
 */
const fitView = () => {
  if (!amapInstance) return

  // 如果传入了中心点，优先使用中心点
  if (props.center && props.center.longitude && props.center.latitude) {
    amapInstance.setCenter([props.center.longitude, props.center.latitude])
    if (props.markers && props.markers.length > 1) {
      amapInstance.setFitView()
    }
    return
  }

  // 如果没有中心点但有标记，自动调整视野
  if ((props.markers && props.markers.length > 0) || collectPolylines().length > 0) {
    amapInstance.setFitView()
  }
}

/**
 * clearMapOverlays：清除地图上的所有覆盖物并关闭信息窗
 */
const clearMapOverlays = () => {
  if (!amapInstance) return
  if (infoWindow) infoWindow.close()
  amapInstance.clearMap()
}

/**
 * renderMap：渲染标记和路线
 */
const renderMap = () => {
  if (!amapInstance || !AMap) return
  clearMapOverlays()
  addMarkers(props.markers)
  drawPolylines(collectPolylines())
  fitView()
}

/**
 * initMap：初始化高德地图
 */
const initMap = async () => {
  if (!amapKey) {
    hasKey.value = false
    return
  }

  try {
    AMap = await AMapLoader.load({
      key: amapKey,
      version: '2.0',
      plugins: ['AMap.Marker', 'AMap.Polyline', 'AMap.InfoWindow']
    })

    const centerLng = props.center?.longitude || 116.397428
    const centerLat = props.center?.latitude || 39.90923

    amapInstance = new AMap.Map(mapContainerRef.value as HTMLDivElement, {
      zoom: 13,
      center: [centerLng, centerLat]
    })

    // 创建复用信息窗实例
    infoWindow = new AMap.InfoWindow({ isCustom: false, offset: new AMap.Pixel(0, -32) })

    mapLoaded.value = true
    renderMap()
  } catch (error) {
    console.error('高德地图初始化失败', error)
    hasKey.value = false
  }
}

// 组件挂载后初始化地图
onMounted(() => {
  initMap()
})

// 监听 props 变化，当地图已初始化且数据更新时重新渲染
watch(
  () => [props.markers, props.polyline, props.polylines, props.center],
  () => {
    if (amapInstance && AMap) {
      renderMap()
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
