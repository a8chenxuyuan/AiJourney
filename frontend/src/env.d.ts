/**
 * src/env.d.ts：Vite 环境变量类型声明文件
 * 作用：为 import.meta.env 中自定义的环境变量提供 TypeScript 类型支持
 *       声明后可在组件或工具函数中通过 import.meta.env.VITE_* 安全访问
 */

// 引入 Vite 默认环境变量类型声明
/// <reference types="vite/client" />

// 扩展 ImportMetaEnv 接口，声明项目所需的自定义环境变量
interface ImportMetaEnv {
  // VITE_AMAP_KEY：高德地图 JSAPI Key，用于初始化地图
  readonly VITE_AMAP_KEY: string
  // VITE_API_BASE_URL：后端 API 基地址，可选，默认值为 http://localhost:8000/api
  readonly VITE_API_BASE_URL?: string
}

// 扩展 ImportMeta 接口，使 import.meta.env 具备上述类型
interface ImportMeta {
  readonly env: ImportMetaEnv
}

