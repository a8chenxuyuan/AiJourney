<!--
  AdminUserTable.vue：管理后台用户管理——搜索、封禁/授权、资料编辑与密码重置弹窗
-->
<script setup lang="ts">
import { reactive, ref } from 'vue'
import { message, Popconfirm } from 'ant-design-vue'
import {
  listAdminUsers,
  banUser,
  unbanUser,
  setUserRole,
  updateUserProfile,
  resetUserPassword,
  type AdminUserRow
} from '@/api/admin'

const users = ref<AdminUserRow[]>([])
const userTotal = ref(0)
const userPage = ref(1)
const userSize = 10
const search = ref('')
const usersLoading = ref(false)

/** load：拉取用户列表 */
async function load() {
  usersLoading.value = true
  try {
    const res = await listAdminUsers(search.value.trim(), userPage.value, userSize)
    if (res.success) {
      users.value = res.data.users
      userTotal.value = res.data.total
    }
  } finally {
    usersLoading.value = false
  }
}

/** onSearchUsers：搜索（重置回第一页） */
function onSearchUsers() {
  userPage.value = 1
  load()
}

/** toggleBan：封禁/解封 */
async function toggleBan(row: AdminUserRow) {
  const res = row.is_banned ? await unbanUser(row.id) : await banUser(row.id)
  if (res.success) {
    message.success(res.message)
    load()
  }
}

/** toggleRole：授权/收权 */
async function toggleRole(row: AdminUserRow) {
  const res = await setUserRole(row.id, row.role === 'admin' ? 'user' : 'admin')
  if (res.success) {
    message.success(res.message)
    load()
  }
}

// editOpen：编辑弹窗开关；editSaving：保存中；editForm：弹窗表单
const editOpen = ref(false)
const editSaving = ref(false)
const editForm = reactive({ id: 0, username: '', email: '', password: '' })

/** openEdit：打开编辑弹窗（密码留空表示不改） */
function openEdit(row: AdminUserRow) {
  editForm.id = row.id
  editForm.username = row.username
  editForm.email = row.email
  editForm.password = ''
  editOpen.value = true
}

/** saveEdit：保存资料修改；填了新密码则同时重置密码 */
async function saveEdit() {
  if (!editForm.username.trim()) {
    message.warning('用户名不能为空')
    return
  }
  if (editForm.password && editForm.password.length < 6) {
    message.warning('新密码至少 6 位')
    return
  }
  editSaving.value = true
  try {
    const res = await updateUserProfile(editForm.id, {
      username: editForm.username.trim(),
      email: editForm.email.trim()
    })
    if (!res.success) return
    if (editForm.password) {
      const pwdRes = await resetUserPassword(editForm.id, editForm.password)
      if (!pwdRes.success) return
    }
    message.success(editForm.password ? '资料与密码已更新' : '资料已更新')
    editOpen.value = false
    load()
  } finally {
    editSaving.value = false
  }
}

const userColumns = [
  { title: '用户', dataIndex: 'username', key: 'username' },
  { title: '邮箱', dataIndex: 'email', key: 'email' },
  { title: '角色', key: 'role' },
  { title: '状态', key: 'status' },
  { title: '行程', dataIndex: 'plans_count', key: 'plans_count', width: 70 },
  { title: '发帖', dataIndex: 'posts_count', key: 'posts_count', width: 70 },
  { title: '注册时间', key: 'created_at', width: 170 },
  { title: '操作', key: 'actions', width: 270 }
]

/** fmtTime：时间格式化（YYYY-MM-DD HH:mm） */
function fmtTime(iso: string | null | undefined) {
  if (!iso) return '-'
  return iso.slice(0, 16).replace('T', ' ')
}

defineExpose({ load })
</script>

<template>
  <div class="ad-toolbar">
    <a-input
      v-model:value="search"
      placeholder="搜索用户名 / 邮箱"
      style="width: 260px"
      allow-clear
      @press-enter="onSearchUsers"
    />
    <a-button type="primary" @click="onSearchUsers">搜索</a-button>
  </div>
  <a-table
    :columns="userColumns"
    :data-source="users"
    :loading="usersLoading"
    :pagination="{ current: userPage, pageSize: userSize, total: userTotal, onChange: (p: number) => { userPage = p; load() } }"
    row-key="id"
  >
    <template #bodyCell="{ column, record }">
      <template v-if="column.key === 'username'">
        <b>{{ record.username }}</b>
      </template>
      <template v-else-if="column.key === 'role'">
        <a-tag :color="record.role === 'admin' ? 'gold' : 'default'">
          {{ record.role === 'admin' ? '管理员' : '普通用户' }}
        </a-tag>
      </template>
      <template v-else-if="column.key === 'status'">
        <a-tag :color="record.is_banned ? 'red' : 'green'">
          {{ record.is_banned ? '已封禁' : '正常' }}
        </a-tag>
      </template>
      <template v-else-if="column.key === 'created_at'">
        {{ fmtTime(record.created_at) }}
      </template>
      <template v-else-if="column.key === 'actions'">
        <a-button size="small" @click="openEdit(record)">编辑</a-button>
        <Popconfirm :title="`确认${record.is_banned ? '解封' : '封禁'} ${record.username}？`" @confirm="toggleBan(record)">
          <a-button size="small" :danger="!record.is_banned" style="margin-left: 8px">
            {{ record.is_banned ? '解封' : '封禁' }}
          </a-button>
        </Popconfirm>
        <Popconfirm :title="`确认将 ${record.username} 设为${record.role === 'admin' ? '普通用户' : '管理员'}？`" @confirm="toggleRole(record)">
          <a-button size="small" style="margin-left: 8px">
            {{ record.role === 'admin' ? '收权' : '设为管理员' }}
          </a-button>
        </Popconfirm>
      </template>
    </template>
  </a-table>

  <!-- 编辑用户弹窗：资料修改 + 密码重置 -->
  <a-modal v-model:open="editOpen" title="编辑用户" :confirm-loading="editSaving" @ok="saveEdit">
    <div class="ad-edit-form">
      <label>用户名</label>
      <a-input v-model:value="editForm.username" placeholder="2-32 位用户名" />
      <label>邮箱</label>
      <a-input v-model:value="editForm.email" placeholder="user@example.com" />
      <label>新密码（留空表示不修改）</label>
      <a-input-password v-model:value="editForm.password" placeholder="至少 6 位" autocomplete="new-password" />
    </div>
  </a-modal>
</template>

<style scoped>
.ad-toolbar {
  display: flex;
  gap: 10px;
  margin-bottom: 16px;
  align-items: center;
}

/* 用户编辑弹窗表单 */
.ad-edit-form {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding-top: 4px;
}
.ad-edit-form label {
  font-size: 13px;
  color: #64748b;
  margin-top: 8px;
}
.ad-edit-form label:first-child {
  margin-top: 0;
}
</style>
