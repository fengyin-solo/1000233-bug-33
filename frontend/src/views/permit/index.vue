<template>
  <section class="page" data-module="permit">
    <header class="page-head">
      <div>
        <h2>外景许可管理</h2>
        <p class="page-desc">维护拍摄许可，围绕许可编号、许可类型、申请地点、受理单位做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记拍摄许可</button>
        <button class="btn" type="button" @click="exportRows">导出外景许可清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无外景许可数据，可先登记拍摄许可</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条外景许可记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/permit'
const columns = ["许可编号", "许可类型", "申请地点", "受理单位", "申请日期", "有效期至", "许可费用", "许可状态"]
const actions = ["提交申请", "确认批准", "驳回申请", "撤回申请"]
const statuses = ["待申请", "已受理", "已批准", "已驳回", "已过期"]
const stats = ref([{"label": "待申请许可", "value": 0}, {"label": "已批准许可", "value": 0}, {"label": "即将过期许可", "value": 0}])

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '拍摄许可登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    if (!response.ok) {
      throw new Error('外景许可动作未生效，请稍后重试')
    }
    const result = await response.json()
    // 后端把「状态冲突/动作非法」放在 ok=false 里返回（HTTP 仍是 200），不检查就会假装成功。
    if (!result.ok) {
      throw new Error(result.message ?? '外景许可动作未生效')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '外景许可操作失败'
  }
}

function refreshStats(items: Row[]) {
  const countBy = (status: string) => items.filter((row) => row['许可状态'] === status).length
  const today = new Date()
  const soon = new Date()
  soon.setDate(today.getDate() + 30)
  const expiring = items.filter((row) => {
    const raw = row['有效期至']
    if (typeof raw !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(raw)) {
      return false
    }
    const deadline = new Date(raw)
    return row['许可状态'] === '已批准' && deadline >= today && deadline <= soon
  }).length
  stats.value = [
    {"label": "待申请许可", "value": countBy('待申请')},
    {"label": "已批准许可", "value": countBy('已批准')},
    {"label": "即将过期许可", "value": expiring},
  ]
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    // 统计口径取全量，避免只数当前筛选/分页的一页。
    const [pageResponse, allResponse] = await Promise.all([
      request(`${ENDPOINT}?${query}`),
      request(`${ENDPOINT}?size=200`),
    ])
    if (!pageResponse.ok || !allResponse.ok) {
      throw new Error('拍摄许可列表读取失败')
    }
    const payload = await pageResponse.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    const allPayload = await allResponse.json()
    refreshStats(allPayload.items ?? [])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '外景许可列表读取失败'
  }
}

onMounted(reload)
</script>
