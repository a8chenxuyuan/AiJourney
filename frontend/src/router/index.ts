/**
 * src/router/index.ts：Vue Router 路由配置
 * 作用：定义前端页面路由表，包括登录、注册、首页、规划进度、结果展示、个人中心等页面
 */

// 引入 Vue Router 创建函数与路由类型
import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

// 引入各页面组件（使用动态导入可优化首屏加载，此处为骨架代码直接使用静态导入）
import Login from '@/views/Login.vue'
import Register from '@/views/Register.vue'
import Home from '@/views/Home.vue'
import Planning from '@/views/Planning.vue'
import Result from '@/views/Result.vue'
import Profile from '@/views/Profile.vue'
import SharedPlan from '@/views/SharedPlan.vue'
// 引入邀请加入协作页
import Join from '@/views/Join.vue'
// 引入用户认证 store，用于路由守卫判断登录状态
import { useAuthStore } from '@/stores/auth'

// routes：路由表数组，每个元素描述一个路由规则
const routes: RouteRecordRaw[] = [
  // /login：登录页
  {
    path: '/login',
    name: 'Login',
    component: Login,
    meta: { title: '登录', public: true }
  },
  // /register：注册页
  {
    path: '/register',
    name: 'Register',
    component: Register,
    meta: { title: '注册', public: true }
  },
  // /：首页（旅行规划表单页）
  {
    path: '/',
    name: 'Home',
    component: Home,
    meta: { title: '旅行规划' }
  },
  // /planning/:id：规划进度页，id 为规划任务 ID
  {
    path: '/planning/:id',
    name: 'Planning',
    component: Planning,
    meta: { title: '规划进度' }
  },
  // /result/:id：结果展示页，id 为规划任务 ID
  {
    path: '/result/:id',
    name: 'Result',
    component: Result,
    meta: { title: '行程结果' }
  },
  // /profile：个人中心页
  {
    path: '/profile',
    name: 'Profile',
    component: Profile,
    meta: { title: '个人中心' }
  },
  // /share/:token：行程只读分享页，公开访问无需登录
  {
    path: '/share/:token',
    name: 'SharedPlan',
    component: SharedPlan,
    meta: { title: '行程分享', public: true }
  },
  // /join/:token：邀请加入协作页，需登录（未登录先去登录，回跳后自动加入）
  {
    path: '/join/:token',
    name: 'Join',
    component: Join,
    meta: { title: '加入协作' }
  }
]

// createRouter：创建 Vue Router 实例
const router = createRouter({
  // createWebHistory：使用 HTML5 History 模式，URL 更美观
  history: createWebHistory(),
  routes
})

// 全局前置守卫：切换路由时自动更新页面标题，并对非公开页面进行登录校验
router.beforeEach((to, _from, next) => {
  // 若路由元信息存在标题，则设置 document.title
  if (to.meta.title) {
    document.title = `${to.meta.title} - agent1旅行`
  }

  // 获取用户认证状态，判断当前是否已登录
  const authStore = useAuthStore()
  // 若目标路由未标记 public 且用户未登录，则重定向到登录页
  if (!to.meta.public && !authStore.isAuthenticated) {
    next('/login')
    return
  }

  // 继续导航
  next()
})

// 导出路由实例，供 main.ts 注册
export default router
