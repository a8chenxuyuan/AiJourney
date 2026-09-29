/**
 * src/router-meta.d.ts：vue-router RouteMeta 类型扩充
 * 作用：让路由表中的 meta.title 与 meta.public 获得 TypeScript 类型支持
 */

// 通过 import 把当前文件标记为 ES 模块，确保下面的 declare module 是“模块扩充”
// 而不是覆盖 vue-router 原始类型声明的“环境模块声明”
import 'vue-router'

declare module 'vue-router' {
  interface RouteMeta {
    title?: string
    public?: boolean
  }
}
