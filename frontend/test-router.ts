import { useRouter, createRouter, createWebHistory, RouteRecordRaw } from 'vue-router'
const router = useRouter()
const r = createRouter({
  history: createWebHistory(),
  routes: [] as RouteRecordRaw[]
})
