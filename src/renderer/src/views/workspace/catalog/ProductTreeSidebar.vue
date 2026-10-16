<script setup lang="ts">
import { computed, ref, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { captureDialogOrigin } from '../../../utils/dialog-origin'
import AppButton from '../../../components/app/AppButton.vue'
import AppInput from '../../../components/app/AppInput.vue'
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import { productKinds, productKindLabels } from '../../../../../shared/product-api'
import type { ProductModel, ProductProfile, ProductPage, ProductQuery } from '../../../../../shared/product-api'
const props = defineProps<{models:ProductModel[]; page:ProductPage|null; rows:ProductProfile[]; query:ProductQuery;
  selectedId:number; selected:ProductProfile|null; loading:boolean; error:string; loadingMore:boolean; moreError:string;
  busy:boolean; disconnected:boolean; canManage:boolean}>()
const emit = defineEmits<{
  series:[id:number|null]; select:[id:number]; newSeries:[]; newModel:[]; manage:[]; include:[];
  delete:[model:ProductModel]; reset:[]; retry:[]; loadMore:[]
}>()
const filterOpen=ref(false)
const scrollEl=ref<HTMLElement|null>(null)
const hasMore=computed(() => !!props.page && props.page.page * props.page.page_size < props.page.total)
let requestingMore=false
let sizeObserver:ResizeObserver|undefined
// 连续滚动事件可能先于父组件传回 loadingMore；同一帧只发出一次加载意图。
function requestMore(retry=false): void {
  if (requestingMore || props.loading || props.loadingMore || props.busy || props.disconnected || !hasMore.value
    || (!retry && props.moreError)) return
  requestingMore=true
  emit('loadMore')
  void nextTick(() => {requestingMore=false})
}
function onScroll(event:Event): void {
  const target=event.currentTarget as HTMLElement|null
  if (target && target.scrollHeight-target.scrollTop-target.clientHeight<=64) requestMore()
}
function checkMore(): void {
  const target=scrollEl.value
  if (target && target.scrollHeight-target.scrollTop-target.clientHeight<=64) requestMore()
}
// 筛选才回到目录顶部，追加数据保留滚动位置；内容不足一屏时按页补满。
watch(() => JSON.stringify([props.query.query,props.query.kind,props.query.model_id]), () => {
  if (scrollEl.value) scrollEl.value.scrollTop=0
}, {flush:'post'})
watch([() => props.page,() => props.loading,() => props.loadingMore,() => props.rows.length],checkMore,{flush:'post'})
onMounted(() => {
  checkMore()
  if (typeof ResizeObserver!=='undefined' && scrollEl.value) {
    sizeObserver=new ResizeObserver(checkMore); sizeObserver.observe(scrollEl.value)
  }
})
onUnmounted(() => sizeObserver?.disconnect())
// 单页元数据和累计节点分开；原始响应仍遵循服务端分页上限，目录可以继续向下浏览。
const children = computed(() => {
  if (props.loading || !props.page) return []
  const rows = [...props.rows]
  // 刚保存或由固定编号定位的机型可能在另一页，保留一个明确的当前节点供操作。
  if (props.selected && props.selectedId === props.selected.id && !rows.some(row=>row.id===props.selectedId)
    && (props.query.model_id === null || props.selected.model_id === props.query.model_id)) rows.unshift(props.selected)
  return rows
})
const members = (id:number|null):ProductProfile[] => children.value.filter(row=>row.model_id===id)
</script>
<template>
  <aside class="product-tree" aria-label="产品系列与子机型">
    <header><h3>产品列表</h3><span v-if="page" class="tree-count">{{ page.total }} 个子机型</span></header>
    <div class="tree-search">
      <div class="tree-search-row"><AppInput v-model.trim="query.query" size="small" aria-label="搜索子机型" maxlength="120" placeholder="名称、编码或配置" :disabled="busy || disconnected" />
        <AppButton size="small" :aria-expanded="filterOpen || !!query.kind" :disabled="busy || disconnected" @click="filterOpen=!filterOpen">筛选</AppButton></div>
      <div v-if="filterOpen || query.kind" class="tree-filter"><WorkspaceSelect v-model="query.kind" size="small" aria-label="子机型类型" :options="[{value:null,label:'全部类型'},...productKinds.map(value=>({value,label:productKindLabels[value]}))]" :disabled="busy || disconnected" />
        <AppButton size="small" :disabled="busy || disconnected" @click="emit('reset')">重置</AppButton></div>
    </div>
    <div v-if="canManage" class="tree-create">
      <AppButton size="small" :disabled="busy || disconnected" @click="emit('newSeries')">新建系列</AppButton>
      <AppButton size="small" variant="primary" :disabled="busy || disconnected" @click="emit('newModel')">新建子机型</AppButton>
    </div>
    <nav ref="scrollEl" class="tree-scroll" aria-label="选择系列与子机型" tabindex="0" :aria-busy="loading || loadingMore" @scroll.passive="onScroll">
      <AppButton variant="plain" class="tree-all" :aria-pressed="query.model_id===null" :disabled="busy || disconnected" @click="emit('series',null)">全部系列</AppButton>
      <p v-if="loading" role="status" class="muted">正在读取子机型…</p>
      <div v-else-if="error" role="alert"><p>{{ error }}</p><AppButton :disabled="disconnected" @click="emit('retry')">重试</AppButton></div>
      <ul v-if="!loading && !error" class="tree-roots">
        <li v-for="model in models" :key="model.id">
          <div class="tree-series-row"><AppButton variant="plain" class="tree-series" :class="{'is-current':query.model_id===model.id}" :aria-expanded="query.model_id===model.id || members(model.id).length>0" :disabled="busy || disconnected" @click="emit('series',model.id)">
            <span aria-hidden="true">{{ query.model_id===model.id || members(model.id).length ? '▾' : '▸' }}</span>
            <span class="series-label"><strong>{{ model.name }}</strong><small>{{ model.code }}<template v-if="model.child_count !== undefined"> · {{ model.child_count }} 个子机型</template></small></span>
          </AppButton>
            <!-- plain 保留语义红色，避免旧全局 text 样式把危险操作染成主题强调色。 -->
            <AppButton v-if="canManage" variant="plain" tone="error" size="small" :aria-label="`删除产品系列 ${model.name}`" :disabled="busy || disconnected"
              @click.capture="captureDialogOrigin('product-model-delete',$event)" @click="emit('delete',model)">删除</AppButton>
          </div>
          <ul v-if="members(model.id).length" class="tree-children">
            <li v-for="row in members(model.id)" :key="row.id"><AppButton variant="plain" class="tree-model" :class="{'is-active':selectedId===row.id}" :aria-pressed="selectedId===row.id" :disabled="busy || disconnected" @click="emit('select',row.id)">
              <!-- 名称只显示一次；配置有实际差异时才补充，避免未配置产品出现重复行。 -->
              <strong>{{ row.material.name }}</strong><small>{{ row.material.sku }}</small><span class="tree-product-meta"><span class="tree-kind">{{ productKindLabels[row.kind] }}</span><span v-if="row.can_produce===false">已停用</span><span v-if="row.configuration_name && row.configuration_name !== row.material.name">{{ row.configuration_name }}</span></span>
            </AppButton></li>
          </ul>
          <p v-else-if="query.model_id===model.id && !loading && !error" class="tree-empty muted">此系列暂无匹配子机型</p>
        </li>
        <li v-if="members(null).length"><h4 class="tree-unassigned">未归组产品 / 半成品</h4><ul class="tree-children">
          <li v-for="row in members(null)" :key="row.id"><AppButton variant="plain" class="tree-model" :class="{'is-active':selectedId===row.id}" :aria-pressed="selectedId===row.id" :disabled="busy || disconnected" @click="emit('select',row.id)">
            <!-- 名称只显示一次；配置有实际差异时才补充，避免未配置产品出现重复行。 -->
              <strong>{{ row.material.name }}</strong><small>{{ row.material.sku }}</small><span class="tree-product-meta"><span class="tree-kind">{{ productKindLabels[row.kind] }}</span><span v-if="row.can_produce===false">已停用</span><span v-if="row.configuration_name && row.configuration_name !== row.material.name">{{ row.configuration_name }}</span></span>
          </AppButton></li>
        </ul></li>
      </ul>
      <p v-if="!loading && !error && !children.length && query.model_id===null" class="tree-empty muted">{{ canManage ? '暂无子机型，可先新建系列，再建立子机型。' : '暂无匹配子机型，请调整搜索条件。' }}</p>
      <!-- 失败暂停自动请求，保留已加载节点并提供明确重试，避免触底后无限重发。 -->
      <div v-if="!loading && !error && page" class="tree-load-state">
        <p v-if="loadingMore" role="status">正在加载更多…</p>
        <template v-else-if="moreError"><p role="alert">{{ moreError }}</p><div class="tree-reload-actions"><AppButton size="small" :disabled="busy || disconnected" @click="requestMore(true)">重试加载</AppButton><AppButton size="small" variant="plain" :disabled="busy || disconnected" @click="emit('retry')">刷新目录</AppButton></div></template>
        <AppButton v-else-if="hasMore" size="small" variant="plain" :disabled="busy || disconnected" @click="requestMore(true)">加载更多</AppButton>
        <p v-else-if="rows.length >= page.total && rows.length">已显示全部 {{ rows.length }} 个子机型</p>
        <template v-else-if="rows.length"><p>已加载 {{ rows.length }} 个子机型，目录有更新</p><AppButton size="small" variant="plain" :disabled="busy || disconnected" @click="emit('retry')">刷新目录</AppButton></template>
      </div>
    </nav>
    <footer v-if="canManage">
      <div class="tree-maintenance"><AppButton size="small" :disabled="busy || disconnected" @click="emit('manage')">系列管理</AppButton><AppButton size="small" :disabled="busy || disconnected" @click="emit('include')">纳入已有物料</AppButton></div>
    </footer>
  </aside>
</template>
<style scoped>
/* 左侧独立滚动目录，系列与子机型缩进对应真实归属；右侧始终留给 BOM。 */
.product-tree { display:flex; flex-direction:column; gap:10px; min-height:0; height:100%; min-width:0; padding:12px; border:1px solid var(--workspace-field-border); border-radius:12px; background:var(--app-modal-surface); box-sizing:border-box; }
header { display:flex; align-items:center; justify-content:space-between; gap:8px; }
header h3 { margin:0; font-size:14px; }
.tree-count { color:var(--workspace-field-muted); font-size:11px; }
.tree-create,.tree-maintenance { display:flex; flex-wrap:wrap; gap:8px; }
.tree-create>* { flex:1; }
.tree-search { display:grid; gap:8px; } .tree-search label { display:grid; gap:7px; font-size:12px; }
.tree-filter,.tree-search-row { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:8px; }
.tree-scroll { flex:1; min-height:0; overflow-y:auto; overflow-x:hidden; overscroll-behavior:contain; scrollbar-gutter:stable; scrollbar-width:thin; scrollbar-color:var(--workspace-field-border) transparent; }
/* 明确可见的细滚动条与键盘焦点，让目录无需页码也能被发现和连续浏览。 */
.tree-scroll:focus-visible { outline:2px solid var(--workspace-field-accent); outline-offset:2px; }
.tree-scroll::-webkit-scrollbar { width:6px; }
.tree-scroll::-webkit-scrollbar-thumb { background:var(--workspace-field-border); border-radius:4px; }
.tree-roots,.tree-children { list-style:none; padding:0; margin:0; }
.tree-roots>li { margin-top:8px; }
.tree-all,.tree-series,.tree-model { width:100%; min-width:0; padding:8px 10px; border-radius:8px; text-align:left; white-space:normal; }
.tree-series-row { display:flex; align-items:center; gap:4px; }
.tree-series-row .tree-series { flex:1; width:auto; }
.tree-series { display:flex; align-items:center; justify-content:start; gap:8px; }
.series-label { display:grid; justify-items:start; gap:5px; }
/* 按钮内部承载文字网格，避免公共按钮的居中容器让不同长度的名称来回跳动。 */
.tree-model :deep(.n-button__content) { display:grid; justify-items:start; gap:4px; width:100%; text-align:left; }
.tree-product-meta { display:flex; align-items:center; flex-wrap:wrap; gap:6px; }
.tree-kind { padding:1px 5px; border-radius:4px; background:var(--app-accent-tint); color:var(--workspace-field-accent); }
small,.tree-product-meta { color:var(--workspace-field-muted); font-size:11px; overflow-wrap:anywhere; }
strong { font-size:13px; overflow-wrap:anywhere; }
.tree-all { display:flex; justify-content:flex-start; text-align:left; color:var(--workspace-field-muted); }
.tree-series.is-current { background:var(--app-accent-tint); color:var(--workspace-field-accent); }
.tree-children { margin:4px 0 8px 15px; padding-left:10px; border-left:1px solid var(--workspace-field-border); }
.tree-model { margin-bottom:4px; border:1px solid transparent; }
.tree-model.is-active { border-color:var(--workspace-field-accent); background:var(--app-accent-tint); color:var(--workspace-field-accent); }
.tree-empty { margin:10px 12px; font-size:12px; line-height:1.7; }
.tree-unassigned { margin:14px 12px 8px; font-size:13px; color:var(--workspace-field-muted); }
footer { padding-top:10px; border-top:1px solid var(--workspace-field-border); }
.tree-maintenance { justify-content:space-between; }
.tree-load-state { display:grid; justify-items:center; gap:6px; padding:10px 4px; color:var(--workspace-field-muted); font-size:11px; text-align:center; }
.tree-load-state p { margin:0; line-height:1.6; }
.tree-reload-actions { display:flex; align-items:center; gap:10px; }
@media(max-width:760px) { .product-tree { height:min(440px,65vh); min-height:280px; } }
</style>
