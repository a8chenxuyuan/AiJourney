/**
 * src/main.ts：Vue 应用入口文件
 * 作用：创建 Vue 应用实例、注册全局插件（路由、Pinia、Ant Design Vue）并挂载到 DOM
 */

// 从 Vue 核心库导入创建应用实例的函数
import { createApp } from 'vue'
// 导入根组件 App.vue
import App from './App.vue'
// 导入路由实例
import router from './router'
// 从 Pinia 导入 createPinia，用于创建状态管理实例
import { createPinia } from 'pinia'
// 导入 Ant Design Vue 组件库
import Antd from 'ant-design-vue'
// 导入 Ant Design Vue 默认样式
import 'ant-design-vue/dist/reset.css'
// 导入全局设计系统样式（设计令牌/玻璃拟态/组件覆写）
import './styles/design-system.css'

// createApp(App)：创建 Vue 应用实例
const app = createApp(App)

// 创建 Pinia 实例
const pinia = createPinia()
// 注册 Pinia 状态管理
app.use(pinia)
// 注册 Vue Router 路由
app.use(router)
// 注册 Ant Design Vue 全部组件（可按需引入以优化体积）
app.use(Antd)

// 将应用挂载到 index.html 中的 #app 节点
app.mount('#app')
