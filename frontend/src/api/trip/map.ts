/**
 * src/api/map.ts：地图与 POI 相关 API 封装
 * 作用：封装 POI 搜索、天气查询、路线规划等高德地图相关后端接口调用
 */

// 导入统一响应类型与 GET/POST 请求方法
import { httpGet, httpPost, type StandardResponse } from '../request'

/**
 * PoiItem：POI 搜索结果单项
 */
export interface PoiItem {
  id: string
  name: string
  address: string
  location: string
  type?: string
}

/**
 * WeatherData：天气查询结果
 */
export interface WeatherData {
  city: string
  weather: string
  temperature: string
  winddirection?: string
  windpower?: string
}

/**
 * RouteData：路线规划结果
 */
export interface RouteData {
  distance: number
  duration: number
  steps: RouteStep[]
  polyline?: string
}

/**
 * RouteStep：路线规划单步信息
 */
export interface RouteStep {
  instruction: string
  distance: number
  duration: number
}

/**
 * searchPoi：根据关键词与城市搜索 POI
 * @param keyword POI 关键词，如“故宫”
 * @param city 目标城市，如“北京”
 * @param pageSize 每页返回数量，默认 10
 * @returns Promise<StandardResponse<PoiItem[]>> 后端响应，data 为 POI 列表
 */
export function searchPoi(keyword: string, city: string, pageSize: number = 10): Promise<StandardResponse<PoiItem[]>> {
  return httpGet<PoiItem[]>('/map/poi', {
    params: { keyword, city, page_size: pageSize }
  })
}

/**
 * getWeather：查询指定城市的天气信息
 * @param city 城市名称，如“杭州”
 * @returns Promise<StandardResponse<WeatherData>> 后端响应，data 为天气数据
 */
export function getWeather(city: string): Promise<StandardResponse<WeatherData>> {
  return httpGet<WeatherData>('/map/weather', {
    params: { city }
  })
}

/**
 * planRoute：规划两点之间的路线
 * @param origin 起点坐标或地址
 * @param destination 终点坐标或地址
 * @param mode 出行方式，如 driving / walking / transit / riding
 * @returns Promise<StandardResponse<RouteData>> 后端响应，data 为路线数据
 */
export function planRoute(origin: string, destination: string, mode: string = 'driving'): Promise<StandardResponse<RouteData>> {
  return httpPost<RouteData>('/map/route', null, {
    params: { origin, destination, mode }
  })
}
