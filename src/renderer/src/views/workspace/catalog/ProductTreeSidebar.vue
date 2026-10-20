<script setup lang="ts">
import { computed, ref, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { captureDialogOrigin } from '../../../utils/dialog-origin'
import AppButton from '../../../components/app/AppButton.vue'
import AppInput from '../../../components/app/AppInput.vue'
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import IconArrowDownSLine from '~icons/ri/arrow-down-s-line'
import IconFolder3Line from '~icons/ri/folder-3-line'
import IconDeleteBin6Line from '~icons/ri/delete-bin-6-line'
import IconEditLine from '~icons/ri/edit-line'
import { productKinds, productKindLabels } from '../../../../../shared/product-api'
import type { ProductModel, ProductProfile, ProductPage, ProductQuery } from '../../../../../shared/product-api'
const props = defineProps<{models:ProductModel[]; page:ProductPage|null; rows:ProductProfile[]; query:ProductQuery;
  activeSeriesId:number|null; revealSeriesKey?:number;
  selectedId:number; selected:ProductProfile|null; loading:boolean; error:string; loadingMore:boolean; moreError:string;
  busy:boolean; disconnected:boolean; canManage:boolean}>()
const emit = defineEmits<{
  series:[id:number|null]; select:[id:number]; newSeries:[]; newModel:[]; edit:[id:number]; include:[];
  delete:[model:ProductModel]; reset:[]; retry:[]; loadMore:[]
}>()
const filterOpen=ref(false)
const scrollEl=ref<HTMLElement|null>(null)
const hasMore=computed(() => !!props.page && props.page.page * props.page.page_size < props.page.total)
// 单一展开身份保证主项互斥；null 是未归组，undefined 才是全部收起，不参与服务端筛选。
const expandedSeriesId=ref<number|null|undefined>(props.activeSeriesId)
const isExpanded=(id:number|null):boolean => expandedSeriesId.value===id
const canInteract=():boolean => !props.busy && !props.disconnected
function interact(action:()=>void):void {if (canInteract()) action()}
function revealSeries(id:number|null):void {
  expandedSeriesId.value=id
}
function toggleSeries(id:number|null):void {
  if (!canInteract() || (id!==null && !props.models.some(model=>model.id===id))) return
  expandedSeriesId.value=isExpanded(id)?undefined:id
  emit('series',id)
}
function selectProduct(id:number):void {
  if (canInteract() && children.value.some(row=>row.id===id)) emit('select',id)
}
function maintain(action:'newSeries'|'newModel'|'include'):void {
  if (!canInteract() || !props.canManage) return
  if (action==='newSeries') emit('newSeries')
  else if (action==='newModel') emit('newModel')
  else emit('include')
}
// 编辑入口与折叠按钮同级，既保留目录层级，也不把编辑误认为选择其他产品。
function requestEdit(id:number):void {
  if (canInteract() && props.canManage && props.models.some(row=>row.id===id)) emit('edit',id)
}
function requestDelete(model:ProductModel):void {
  if (canInteract() && props.canManage && props.models.some(row=>row.id===model.id)) emit('delete',model)
}
function captureDeleteOrigin(event:Event):void {
  if (canInteract() && props.canManage) captureDialogOrigin('product-model-delete',event)
}
let requestingMore=false
let lastScrollTop=0
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
  if (!target) return
  // 收起节点会让浏览器向上修正滚动位置，不能把这种变化当成再次触底。
  const movingDown=target.scrollTop>lastScrollTop
  lastScrollTop=target.scrollTop
  if (movingDown && target.scrollHeight-target.scrollTop-target.clientHeight<=64) requestMore()
}
function checkMore(): void {
  const target=scrollEl.value
  // 隐藏行不能撑高目录；此时自动补屏会连续翻完所有页，改由真实下滚或显式按钮继续。
  if (target && !hasHiddenChildren.value && target.scrollHeight-target.scrollTop-target.clientHeight<=64) requestMore()
}
// 筛选才回到目录顶部，追加数据保留滚动位置；内容不足一屏时按页补满。
watch(() => JSON.stringify([props.query.query,props.query.kind]), () => {
  if (scrollEl.value) scrollEl.value.scrollTop=0
  lastScrollTop=0
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
  if (props.selected && props.selectedId === props.selected.id && !rows.some(row=>row.id===props.selectedId)) rows.unshift(props.selected)
  return rows
})
const members = (id:number|null):ProductProfile[] => children.value.filter(row=>row.model_id===id)
const hasHiddenChildren=computed(() => children.value.some(row=>!isExpanded(row.model_id)))
// 完整末页无需重复报数；只有去重后的目录与服务端总数不符才提醒刷新。
const directoryChanged=computed(() => !!props.page && !hasMore.value && !!props.rows.length && props.rows.length!==props.page.total)
const showLoadState=computed(() => !props.loading && !props.error && !!props.page
  && (props.loadingMore || !!props.moreError || hasMore.value || directoryChanged.value))
let trackedSelectedId=0
let revealedSelectionKey=''
// 只对新的产品身份或实际归属变化展开；同一详情清空后重读不能推翻用户手动收起。
watch(() => [props.selectedId,props.selected?.id,props.selected?.model_id], () => {
  const selectionChanged=trackedSelectedId!==props.selectedId
  trackedSelectedId=props.selectedId
  if (selectionChanged || !props.selectedId) revealedSelectionKey=''
  if (!props.selectedId) return
  // 新选择可先按已加载目录定位；同编号详情暂时为空时等待原身份返回，不重复展开。
  const row=props.selected?.id===props.selectedId ? props.selected
    : selectionChanged ? props.rows.find(item=>item.id===props.selectedId) : undefined
  if (!row) return
  const key=JSON.stringify([row.id,row.model_id])
  if (revealedSelectionKey===key) return
  revealedSelectionKey=key
  revealSeries(row.model_id)
}, {immediate:true})
// 新建系列和“所在系列”属于显式定位；当前归属变化本身不强制展开，避免点击收起后立即反弹。
watch(() => props.revealSeriesKey, () => revealSeries(props.activeSeriesId))
// 删除当前展开系列后收起目录，不意外展开别的主项；未归组始终是独立根节点。
watch(() => props.models.map(model=>model.id).join(','), () => {
  const id=expandedSeriesId.value
  if (id!==null && id!==undefined && !props.models.some(model=>model.id===id)) expandedSeriesId.value=undefined
})
</script>
<template>
  <aside class="product-tree" aria-label="产品系列与子机型">
    <header><h3>产品列表</h3><span v-if="page" class="tree-count">{{ page.total }} 个子机型</span></header>
    <div class="tree-search">
      <div class="tree-search-row"><AppInput v-model.trim="query.query" size="small" aria-label="搜索子机型" maxlength="120" placeholder="名称、编码或配置" :disabled="busy || disconnected" />
        <AppButton size="small" :aria-expanded="filterOpen || !!query.kind" :disabled="busy || disconnected" @click="interact(()=>filterOpen=!filterOpen)">筛选</AppButton></div>
      <div v-if="filterOpen || query.kind" class="tree-filter"><WorkspaceSelect v-model="query.kind" size="small" aria-label="子机型类型" :options="[{value:null,label:'全部类型'},...productKinds.map(value=>({value,label:productKindLabels[value]}))]" :disabled="busy || disconnected" />
        <AppButton size="small" :disabled="busy || disconnected" @click="interact(()=>emit('reset'))">重置</AppButton></div>
    </div>
    <div v-if="canManage" class="tree-create">
      <AppButton size="small" :disabled="busy || disconnected" @click="maintain('newSeries')">新建系列</AppButton>
      <AppButton size="small" variant="primary" :disabled="busy || disconnected" @click="maintain('newModel')">新建子机型</AppButton>
    </div>
    <nav ref="scrollEl" class="tree-scroll" aria-label="选择系列与子机型" tabindex="0" :aria-busy="loading || loadingMore" @scroll.passive="onScroll">
      <p v-if="loading" role="status" class="muted">正在读取子机型…</p>
      <div v-else-if="error" role="alert"><p>{{ error }}</p><AppButton :disabled="busy || disconnected" @click="interact(()=>emit('retry'))">重试</AppButton></div>
      <ul v-if="!loading && !error" class="tree-roots">
        <li v-for="model in models" :key="model.id">
          <div class="tree-series-row" :class="{'is-current':activeSeriesId===model.id}"><AppButton variant="plain" class="tree-series" :aria-expanded="isExpanded(model.id)" :disabled="busy || disconnected" @click="toggleSeries(model.id)">
            <IconArrowDownSLine class="series-chevron" :class="{'is-collapsed':!isExpanded(model.id)}" aria-hidden="true" focusable="false" />
            <IconFolder3Line class="series-folder" aria-hidden="true" focusable="false" />
            <span class="series-label"><strong :title="model.name">{{ model.name }}</strong><small :title="model.code">{{ model.code }}</small></span>
          </AppButton>
            <AppButton v-if="canManage" class="tree-series-edit" variant="plain" size="small" :title="`编辑产品系列 ${model.name}`" :aria-label="`编辑产品系列 ${model.name}`" :disabled="busy || disconnected"
              @click="requestEdit(model.id)"><IconEditLine class="series-edit-icon" aria-hidden="true" focusable="false" /></AppButton>
            <!-- 图标入口保留独立确认与语义危险色，避免整行常驻红字抢走目录层级。 -->
            <AppButton v-if="canManage" class="tree-series-delete" variant="plain" tone="error" size="small" :title="`删除产品系列 ${model.name}`" :aria-label="`删除产品系列 ${model.name}`" :disabled="busy || disconnected"
              @click.capture="captureDeleteOrigin" @click="requestDelete(model)"><IconDeleteBin6Line class="series-delete-icon" aria-hidden="true" focusable="false" /></AppButton>
          </div>
          <ul v-if="isExpanded(model.id) && members(model.id).length" class="tree-children">
            <li v-for="row in members(model.id)" :key="row.id"><AppButton variant="plain" class="tree-model" :class="{'is-active':selectedId===row.id}" :aria-pressed="selectedId===row.id" :disabled="busy || disconnected" @click="selectProduct(row.id)">
              <!-- 子项隐藏物料编号以精简目录；选择仍使用原 ID，配置有实际差异时才补充。 -->
              <strong>{{ row.material.name }}</strong><span class="tree-product-meta"><span class="tree-kind">{{ productKindLabels[row.kind] }}</span><span v-if="row.can_produce===false">已停用</span><span v-if="row.configuration_name && row.configuration_name !== row.material.name">{{ row.configuration_name }}</span></span>
            </AppButton></li>
          </ul>
          <p v-else-if="isExpanded(model.id)" class="tree-empty muted">{{ hasMore ? '子机型尚未加载，可继续加载目录' : '此系列暂无匹配子机型' }}</p>
        </li>
        <!-- 未归组始终占有一个根节点，不再依赖当前页是否恰好包含 PCB 等旧产品。 -->
        <li><div class="tree-series-row tree-unassigned" :class="{'is-current':activeSeriesId===null}"><AppButton variant="plain" class="tree-series" :aria-expanded="isExpanded(null)" :disabled="busy || disconnected" @click="toggleSeries(null)">
          <IconArrowDownSLine class="series-chevron" :class="{'is-collapsed':!isExpanded(null)}" aria-hidden="true" focusable="false" />
          <IconFolder3Line class="series-folder" aria-hidden="true" focusable="false" />
          <span class="series-label"><strong title="未归组产品 / 半成品">未归组产品 / 半成品</strong><small>未分配产品系列</small></span>
        </AppButton></div><ul v-if="isExpanded(null) && members(null).length" class="tree-children">
          <li v-for="row in members(null)" :key="row.id"><AppButton variant="plain" class="tree-model" :class="{'is-active':selectedId===row.id}" :aria-pressed="selectedId===row.id" :disabled="busy || disconnected" @click="selectProduct(row.id)">
            <!-- 未归组产品采用同样的精简展示，保留原身份和按编码搜索能力。 -->
              <strong>{{ row.material.name }}</strong><span class="tree-product-meta"><span class="tree-kind">{{ productKindLabels[row.kind] }}</span><span v-if="row.can_produce===false">已停用</span><span v-if="row.configuration_name && row.configuration_name !== row.material.name">{{ row.configuration_name }}</span></span>
          </AppButton></li>
        </ul><p v-else-if="isExpanded(null)" class="tree-empty muted">{{ hasMore ? '子机型尚未加载，可继续加载目录' : '暂无匹配的未归组子机型' }}</p></li>
      </ul>
      <p v-if="!loading && !error && !children.length && !hasMore" class="tree-empty muted">{{ canManage ? '暂无子机型，可先新建系列，再建立子机型。' : '暂无匹配子机型，请调整搜索条件。' }}</p>
      <!-- 失败暂停自动请求，保留已加载节点并提供明确重试，避免触底后无限重发。 -->
      <div v-if="showLoadState" class="tree-load-state">
        <p v-if="loadingMore" role="status">正在加载更多…</p>
        <template v-else-if="moreError"><p role="alert">{{ moreError }}</p><div class="tree-reload-actions"><AppButton size="small" :disabled="busy || disconnected" @click="requestMore(true)">重试加载</AppButton><AppButton size="small" variant="plain" :disabled="busy || disconnected" @click="interact(()=>emit('retry'))">刷新目录</AppButton></div></template>
        <AppButton v-else-if="hasMore" size="small" variant="plain" :disabled="busy || disconnected" @click="requestMore(true)">加载更多</AppButton>
        <template v-else-if="directoryChanged"><p>已加载 {{ rows.length }} 个子机型，目录有更新</p><AppButton size="small" variant="plain" :disabled="busy || disconnected" @click="interact(()=>emit('retry'))">刷新目录</AppButton></template>
      </div>
    </nav>
    <footer v-if="canManage">
      <div class="tree-maintenance"><AppButton size="small" :disabled="busy || disconnected" @click="maintain('include')">纳入已有物料</AppButton></div>
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
.tree-series,.tree-model { width:100%; min-width:0; padding:8px 10px; border-radius:8px; text-align:left; white-space:normal; }
/* 系列只展示名称和编码，图标操作留在独立网格列，不挤压名称。 */
.tree-series-row { display:grid; grid-template-columns:minmax(0,1fr) auto auto; align-items:center; gap:4px; padding:2px; border:1px solid transparent; border-radius:10px; }
.tree-series { display:grid; grid-template-columns:12px 16px minmax(0,1fr); align-items:center; justify-content:initial; gap:8px; min-height:44px; padding:6px; }
.series-label { display:grid; justify-items:start; gap:2px; min-width:0; }
.series-label strong,.series-label small { max-width:100%; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.series-label strong { font-size:13px; line-height:18px; }
.series-label small { font-size:11px; line-height:15px; }
.series-chevron { width:12px; height:12px; color:var(--workspace-field-muted); transition:transform 160ms ease; }
.series-chevron.is-collapsed { transform:rotate(-90deg); }
.series-folder { width:16px; height:16px; color:var(--workspace-field-muted); }
/* 只压低 SVG 的静态颜色，按钮本身沿用 error 主题；悬停和键盘聚焦时恢复其语义色。 */
.tree-series-edit,.tree-series-delete { display:grid; place-items:center; width:32px; min-width:32px; height:32px; padding:0; border-radius:8px; }
.series-edit-icon,.series-delete-icon { width:16px; height:16px; color:var(--workspace-field-muted); }
.tree-series-edit:hover .series-edit-icon,.tree-series-edit:focus-visible .series-edit-icon,
.tree-series-delete:hover .series-delete-icon,.tree-series-delete:focus-visible .series-delete-icon { color:inherit; }
/* 按钮内部承载文字网格，避免公共按钮的居中容器让不同长度的名称来回跳动。 */
.tree-model :deep(.n-button__content) { display:grid; justify-items:start; gap:4px; width:100%; text-align:left; }
.tree-product-meta { display:flex; align-items:center; flex-wrap:wrap; gap:6px; }
.tree-kind { padding:1px 5px; border-radius:4px; background:var(--app-accent-tint); color:var(--workspace-field-accent); }
small,.tree-product-meta { color:var(--workspace-field-muted); font-size:11px; overflow-wrap:anywhere; }
strong { font-size:13px; overflow-wrap:anywhere; }
.tree-series-row.is-current { background:var(--app-accent-tint); color:var(--workspace-field-accent); }
.tree-series-row.is-current .series-folder,.tree-series-row.is-current .series-chevron { color:inherit; }
/* 主项与子项留出 10px 垂直间距，归组和未归组沿用相同缩进与层级线。 */
.tree-children { margin:10px 0 8px 15px; padding-left:10px; border-left:1px solid var(--workspace-field-border); }
.tree-model { margin-bottom:4px; border:1px solid transparent; }
.tree-model.is-active { border-color:var(--workspace-field-accent); background:var(--app-accent-tint); color:var(--workspace-field-accent); }
.tree-empty { margin:10px 12px; font-size:12px; line-height:1.7; }
.tree-unassigned { margin-top:6px; }
footer { padding-top:10px; border-top:1px solid var(--workspace-field-border); }
.tree-maintenance { justify-content:flex-end; }
.tree-load-state { display:grid; justify-items:center; gap:6px; padding:10px 4px; color:var(--workspace-field-muted); font-size:11px; text-align:center; }
.tree-load-state p { margin:0; line-height:1.6; }
.tree-reload-actions { display:flex; align-items:center; gap:10px; }
@media(max-width:760px) { .product-tree { height:min(440px,65vh); min-height:280px; } }
@media(prefers-reduced-motion:reduce) { .series-chevron { transition:none; } }
</style>
