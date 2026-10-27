/**
 * src/router/index.ts：Vue Router 路由配置
 * 作用：定义前端页面路由表，按业务域分组（认证/规划主流程/个人中心/社交/内容中心/管理后台/公开分享），
 *       页面组件全部懒加载，按需分包优化首屏加载
 */

// 引入 Vue Router 创建函数与路由类型
import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

// 引入用户认证 store，用于路由守卫判断登录状态
import { useAuthStore } from '@/stores/auth'

// routes：路由表数组，每个元素描述一个路由规则；组件懒加载（() => import(...)）
const routes: RouteRecordRaw[] = [
  // ==================== 认证 ====================
  // /login：登录页
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/auth/Login.vue'),
    meta: { title: '登录', public: true }
  },
  // /register：注册页
  {
    path: '/register',
    name: 'Register',
    component: () => import('@/views/auth/Register.vue'),
    meta: { title: '注册', public: true }
  },

  // ==================== 规划主流程 ====================
  // /：首页（旅行规划表单页）
  {
    path: '/',
    name: 'Home',
    component: () => import('@/views/trip/Home.vue'),
    meta: { title: '旅行规划' }
  },
  // /planning/:id：规划进度页，id 为规划任务 ID
  {
    path: '/planning/:id',
    name: 'Planning',
    component: () => import('@/views/trip/Planning.vue'),
    meta: { title: '规划进度' }
  },
  // /result/:id：结果展示页，id 为规划任务 ID
  {
    path: '/result/:id',
    name: 'Result',
    component: () => import('@/views/trip/Result.vue'),
    meta: { title: '行程结果' }
  },
  // /trip/:id/today：当日视图（行中伴侣，按时间轴执行/打卡/导航）
  {
    path: '/trip/:id/today',
    name: 'Today',
    component: () => import('@/views/trip/Today.vue'),
    meta: { title: '今日行程' }
  },
  // /trip/:id/footprints：足迹地图（打卡点按天连线）
  {
    path: '/trip/:id/footprints',
    name: 'Footprints',
    component: () => import('@/views/trip/Footprints.vue'),
    meta: { title: '足迹地图' }
  },
  // /trip/:id/journal：游记页（生成/展示/编辑）
  {
    path: '/trip/:id/journal',
    name: 'Journal',
    component: () => import('@/views/trip/Journal.vue'),
    meta: { title: '旅行游记' }
  },
  // /join/:token：邀请加入协作页，需登录（未登录先去登录，回跳后自动加入）
  {
    path: '/join/:token',
    name: 'Join',
    component: () => import('@/views/trip/Join.vue'),
    meta: { title: '加入协作' }
  },

  // ==================== 订单沙箱 ====================
  // /pay/:orderId：沙箱收银台（确认支付/取消订单）
  {
    path: '/pay/:orderId',
    name: 'Pay',
    component: () => import('@/views/trip/Pay.vue'),
    meta: { title: '收银台' }
  },
  // /orders：我的订单（全量订单与状态流转）
  {
    path: '/orders',
    name: 'Orders',
    component: () => import('@/views/trip/Orders.vue'),
    meta: { title: '我的订单' }
  },

  // ==================== 个人中心 ====================
  // /profile：个人中心页
  {
    path: '/profile',
    name: 'Profile',
    component: () => import('@/views/profile/Profile.vue'),
    meta: { title: '个人中心' }
  },
  // /profile/archive：旅行档案页（历史行程 + 打卡统计）
  {
    path: '/profile/archive',
    name: 'Archive',
    component: () => import('@/views/trip/Archive.vue'),
    meta: { title: '旅行档案' }
  },
  // /favorites：我的行囊（收藏独立页，需登录）
  {
    path: '/favorites',
    name: 'Favorites',
    component: () => import('@/views/profile/Favorites.vue'),
    meta: { title: '我的行囊' }
  },

  // ==================== 社交与消息 ====================
  // /messages：消息中心（新朋友/互动通知/会话列表/聊天窗，需登录）
  {
    path: '/messages',
    name: 'Messages',
    component: () => import('@/views/social/Messages.vue'),
    meta: { title: '消息', requiresAuth: true }
  },
  // /user/:id：用户主页（QQ 式资料卡 + TA 的旅行圈/游记，社交入口）
  {
    path: '/user/:id',
    name: 'UserProfile',
    component: () => import('@/views/social/UserProfile.vue'),
    meta: { title: '用户主页', requiresAuth: true }
  },
  // /circle：旅行圈（朋友圈式晒旅行生活，瀑布流照片卡）
  {
    path: '/circle',
    name: 'Circle',
    component: () => import('@/views/community/Circle.vue'),
    meta: { title: '旅行圈' }
  },
  // /community/:id：帖子详情（分节图文/点赞/评论/照着走）
  {
    path: '/community/:id',
    name: 'PostDetail',
    component: () => import('@/views/community/PostDetail.vue'),
    meta: { title: '帖子详情' }
  },

  // ==================== 内容中心（公开页免登录） ====================
  // /guides：攻略灵感流（游记优先合流，公开内容页免登录）
  {
    path: '/guides',
    name: 'Guides',
    component: () => import('@/views/community/Guides.vue'),
    meta: { title: '攻略灵感', public: true }
  },
  // /guides/:id：攻略详情（正文 + 相关攻略 + 规划同款行程入口）
  {
    path: '/guides/:id',
    name: 'GuideDetail',
    component: () => import('@/views/community/GuideDetail.vue'),
    meta: { title: '攻略详情', public: true }
  },
  // /destination/:city：目的地聚合页（百科简介/精选攻略/游记/模板/AI 问答）
  {
    path: '/destination/:city',
    name: 'Destination',
    component: () => import('@/views/community/Destination.vue'),
    meta: { title: '目的地', public: true }
  },
  // /search：全站搜索（帖子/游记/攻略/用户四源，免登录）
  {
    path: '/search',
    name: 'Search',
    component: () => import('@/views/community/Search.vue'),
    meta: { title: '搜索', public: true }
  },
  // /creators：同路人达人发现页（免登录）
  {
    path: '/creators',
    name: 'Creators',
    component: () => import('@/views/community/Creators.vue'),
    meta: { title: '同路人', public: true }
  },
  // /notes 与 /community：旧链接兼容，图文笔记内容已并入攻略灵感页
  { path: '/notes', redirect: '/guides' },
  { path: '/community', redirect: '/guides' },

  // ==================== 管理后台 ====================
  // /admin：管理后台（数据看板/用户管理/内容审核/系统公告，仅管理员）
  {
    path: '/admin',
    name: 'Admin',
    component: () => import('@/views/admin/Admin.vue'),
    meta: { title: '管理后台', requiresAuth: true, requiresAdmin: true }
  },

  // ==================== 公开分享 ====================
  // /journal/:token：公开游记分享页（免登录可看，支持复刻线路）
  {
    path: '/journal/:token',
    name: 'JournalShare',
    component: () => import('@/views/community/JournalShare.vue'),
    meta: { title: '游记分享', public: true }
  },
  // /share/:token：行程只读分享页，公开访问无需登录
  {
    path: '/share/:token',
    name: 'SharedPlan',
    component: () => import('@/views/trip/SharedPlan.vue'),
    meta: { title: '行程分享', public: true }
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
    document.title = `${to.meta.title} - 旅程`
  }

  // 获取用户认证状态，判断当前是否已登录
  const authStore = useAuthStore()
  // 若目标路由未标记 public 且用户未登录，则重定向到登录页
  if (!to.meta.public && !authStore.isAuthenticated) {
    next('/login')
    return
  }

  // 管理后台路由：非管理员访问重定向到首页（前端层拦截，后端接口另有 403 兜底）
  if (to.meta.requiresAdmin && !authStore.isAdmin) {
    next('/')
    return
  }

  // 继续导航
  next()
})

// 导出路由实例，供 main.ts 注册
export default router
