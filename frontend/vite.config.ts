/**
 * vite.config.ts：Vite 构建工具配置文件
 * 作用：配置开发服务器、构建行为、路径别名 @ -> src 等
 */

// 引入 Vite 配置函数 defineConfig，提供类型提示
import { defineConfig } from 'vite'
// 引入 Vue 官方 Vite 插件，用于编译 .vue 单文件组件
import vue from '@vitejs/plugin-vue'
// 引入 Node.js URL 工具，用于在 ESM 中安全解析 __dirname 等效路径
import { fileURLToPath, URL } from 'node:url'

// https://vitejs.dev/config/
export default defineConfig({
  // plugins：注册 Vite 插件
  plugins: [vue()],
  // resolve：配置模块解析规则
  resolve: {
    // alias：路径别名，@ 指向项目根目录下的 src 目录，简化模块导入路径
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  // server：开发服务器配置
  server: {
    // host：监听 0.0.0.0，允许局域网内其他设备通过本机 IP 访问（手机/第二台电脑联调）
    host: true,
    // port：开发服务器监听端口
    port: 5173,
    // open：启动时是否自动打开浏览器
    open: true
  }
})
