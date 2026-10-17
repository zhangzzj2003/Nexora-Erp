<script setup lang="ts">
import { computed, ref, watch, onUnmounted } from 'vue'
import { NCollapse, NDropdown } from 'naive-ui'
import AppCollapseItem from '../../../components/app/AppCollapseItem.vue'
import { storeToRefs } from 'pinia'
import { useRoute } from 'vue-router'
import { usePiniaAppStore } from '../../../store/app-store'
import { productKindLabels } from '../../../../../shared/product-api'
import type { ProductProfile, ProductModel, ProductLifecycleAction } from '../../../../../shared/product-api'
import type { Bom } from '../../../../../shared/erp-api'
import { materialChoiceFacts } from '../../../utils/material-selection'
import { captureDialogOrigin } from '../../../utils/dialog-origin'
import WorkspaceDocumentDialog from '../../../components/workspace/WorkspaceDocumentDialog.vue'
import InventoryDetailDialogs from '../../../components/workspace/InventoryDetailDialogs.vue'
import WorkspaceMaterialParameters from '../../../components/workspace/WorkspaceMaterialParameters.vue'
import AppButton from '../../../components/app/AppButton.vue'
import AppStatusTag from '../../../components/app/AppStatusTag.vue'
import type { AppStatusTone } from '../../../components/app/AppStatusTag.vue'
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import ProductEditor from './ProductEditor.vue'
import ProductTreeSidebar from './ProductTreeSidebar.vue'
import ProductBomReuseDialog from './ProductBomReuseDialog.vue'
import ProductModelsDialog from './ProductModelsDialog.vue'
import ProductModelDeleteDialog from './ProductModelDeleteDialog.vue'
import ProductLifecycleDialog from './ProductLifecycleDialog.vue'
import BomEditor from './BomEditor.vue'
import BomDetailDialog from './BomDetailDialog.vue'
import ProductBomStructure from './ProductBomStructure.vue'
import type { BomStructureRow } from './bom-structure'
// 页面只组织展示，分页、草稿、版本写入和会话边界统一放在 Pinia。
const store = usePiniaAppStore(), route = useRoute()
const {productQuery: query, productResult: result, productDirectoryRows, productModels: models, productsLoading, productsError,
  productsLoadingMore, productsMoreError,
  productDetailRecord: detail, productDetailId, productDetailLoading, productDetailError,
  productBomRecords, productChangeRecords, productChangesLoading, productChangesError, productEditorOpen, bomDetailRecord, bomDetailLoading, bomDetailError,
  materials, materialCategories, boms, productModelForm, productModelChanges, busy, connectionLost} = storeToRefs(store)
// 系列是目录中的归属与新建上下文，不再作为整棵树的查询条件。
const currentSeriesId = ref<number|null>(query.value.model_id)
const seriesRevealKey = ref(0)
let contextProductId = 0
let followsProductSelection = true
// 兼容页面刷新前遗留的系列筛选，让未归组和其他系列都能继续浏览。
if (query.value.model_id !== null) query.value = {...query.value,model_id:null,page:1}
const modelsOpen = ref(false), bomOpen = ref(false), detailsOpen = ref(false), reuseOpen = ref(false), createSeriesOnly = ref(false)
const versionsOpen = ref(false)
let seriesEditIntent=0, pendingSeriesId=0
function cancelSeriesEdit(pendingOnly=false): void {
  // 其他弹窗只撤销在途系列读取，不干扰已经完成的编辑票据或草稿。
  if (pendingOnly && !pendingSeriesId) return
  seriesEditIntent++
  pendingSeriesId=0; store.cancelProductModelEdit()
}
// 关闭聚焦表单保留草稿，但不允许旧的未完成读取再次打开它。
watch(modelsOpen, open => {if (!open) cancelSeriesEdit()}, {flush:'sync'})
const creationAllowsBlank = ref(true)
let creationTarget = 0, creationSelection = 0, creationSession = 0
const modelToDelete = ref<ProductModel|null>(null)
const lifecycleTarget = ref<ProductProfile|null>(null)
const lifecycleAction = ref<ProductLifecycleAction>('disable')
const lifecycleOptions = computed(() => detail.value ? [
  {key:detail.value.can_produce===false ? 'enable' : 'disable',label:detail.value.can_produce===false ? '启用子机型' : '停用子机型'},
  {key:'delete',label:'删除子机型'}] : [])
function selectLifecycle(action: string): void {
  if (!detail.value || productUnavailable.value || !store.can('catalog.manage') || !['enable','disable','delete'].includes(action)) return
  cancelSeriesEdit(true)
  lifecycleAction.value=action as ProductLifecycleAction; lifecycleTarget.value=detail.value
}
const pendingProductId = ref(0)
const bomTargetId = ref(0)
const revisingBomVersion = ref<number|undefined>()
let viewSessionEpoch = 0
const selectedBomId = ref(0)
let productSelectionEpoch=0
// 默认看启用版本，手动选择历史版本后保持到切换产品为止。
const selectedBom = computed(() => productBomRecords.value.find(row => row.id === selectedBomId.value)
  ?? productBomRecords.value.find(row => row.status === 'active') ?? productBomRecords.value[0])
watch(productDetailId, () => {
  productSelectionEpoch++; selectedBomId.value = 0; versionsOpen.value = false; reuseOpen.value = false
}, {flush:'sync'})
const bomStatuses: Record<Bom['status'], {label:string; tone:AppStatusTone}> = {
  draft:{label:'草稿',tone:'pending'}, active:{label:'已启用',tone:'success'},
  retired:{label:'已停用',tone:'neutral'}, cancelled:{label:'已取消',tone:'danger'}
}
const versionOptions = computed(() => productBomRecords.value.map(row => ({value:row.id,
  label:`V${row.version} · ${bomStatuses[row.status].label}`})))
const productUnavailable = computed(() => busy.value || connectionLost.value || productDetailLoading.value || !!productDetailError.value)
// 详情读取属于当前组成；切换产品或版本时撤销旧请求，防止迟到响应重新弹出。
watch([productDetailId, () => selectedBom.value?.id], () => store.closeLedgerMaterial(), {flush:'sync'})
function openCompositionMaterial(row:BomStructureRow): void {
  if (productUnavailable.value || !store.can('inventory.view') || !selectedBom.value
    || !row.key.startsWith(`${selectedBom.value.id}/`)) return
  cancelSeriesEdit(true)
  // 从 BOM 查看完整物料记录，不继承用户在库存台账页面遗留的仓库、日期或来源筛选。
  void store.openLedgerMaterial({material_id:row.materialId,sku:row.sku,material_name:row.name},
    {warehouse_id:null,from_date:null,to_date:null,source_type:null})
}
function selectVersion(id: number): void {
  // 只接受当前产品已经加载的版本，禁用期间的迟到事件不能切换组成视图。
  if (!productUnavailable.value && productBomRecords.value.some(row => row.id === id)) selectedBomId.value = id
}
function viewComposition(id: number): void {
  if (productUnavailable.value) return
  selectVersion(id); versionsOpen.value = false
}
const seriesName = computed(() => models.value.find(row => row.id === currentSeriesId.value)?.name ?? '未归组产品 / 半成品')
watch(detail, row => {
  // 真正切换产品才跟随归属；普通 BOM 刷新不能抢走用户刚选的新建系列。
  if (followsProductSelection && row && row.id === productDetailId.value && row.id !== contextProductId) {
    contextProductId=row.id; currentSeriesId.value=row.model_id
  }
})
watch(models, rows => {
  if (pendingSeriesId && !rows.some(row=>row.id===pendingSeriesId)) cancelSeriesEdit()
  if (currentSeriesId.value !== null && !rows.some(row=>row.id===currentSeriesId.value)) currentSeriesId.value=null
})
const bomColumns = [{key:'version',title:'BOM 版本',width:'110'}, {key:'status',title:'状态',width:'90'},
  {key:'source',title:'派生来源'}, {key:'actions',title:'操作',width:'390'}]
// 身份信息与详细参数分区，参数直接展示，避免详情中还需寻找折叠入口。
const facts = computed(() => detail.value ? materialChoiceFacts(detail.value.material, materialCategories.value)
  .filter(fact => ['category_name','unit'].includes(fact.key)) : [])
const showDetail = computed(() => detailsOpen.value && !!productDetailId.value && !bomOpen.value && !productEditorOpen.value
  && !bomDetailRecord.value && !bomDetailLoading.value && !bomDetailError.value)
// 历史只在查看资料时读取，审计接口的等待或失败不能阻塞右侧 BOM。
watch(() => showDetail.value && !productDetailLoading.value && detail.value?.id === productDetailId.value, ready => {
  if (ready) void store.loadProductChanges()
})
watch(() => JSON.stringify([query.value.query, query.value.kind, query.value.model_id,
  store.user?.id, store.user?.permissions.slice().sort(), connectionLost.value, store.server?.id, store.server?.fingerprint]),
  () => {if (store.can('inventory.view') && !connectionLost.value) void store.queryProducts()}, {immediate:true})
// 固定编号的外部定位只消费一次；后续系列筛选和分页使用当前服务端结果。
let consumedRoute = ''
watch([result, () => route.query.product_id], ([page, rawId]) => {
  if (!page) {store.closeProduct(); detailsOpen.value = false; reuseOpen.value = false; return}
  if (pendingProductId.value) {const id=pendingProductId.value; pendingProductId.value=0; void store.openProduct(id); return}
  const routeId = Number(rawId)
  if (Number.isSafeInteger(routeId) && routeId > 0 && consumedRoute !== String(rawId)) {
    consumedRoute = String(rawId); void store.openProduct(routeId); return
  }
  // 切换筛选时撤销旧读取，迟到的上一系列响应不能回填右侧。
  // 追加只更新最后一页的元数据，选择依据完整已加载目录，避免滚到底就跳到另一产品。
  const retained = detail.value?.id === productDetailId.value
    && (query.value.model_id === null || detail.value.model_id === query.value.model_id)
    && (query.value.kind === null || detail.value.kind === query.value.kind) ? detail.value : undefined
  const selected = productDirectoryRows.value.find(row => row.id === productDetailId.value)
    ?? retained ?? productDirectoryRows.value[0]
  if (selected && selected.id !== productDetailId.value) void store.openProduct(selected.id)
  else if (!selected) store.closeProduct()
}, {immediate:true})
// 保存后的定位意图不能跨账号、实例或权限边界执行。
watch(() => JSON.stringify([store.user?.id,store.server?.id,store.server?.fingerprint,store.user?.permissions.slice().sort()]), () => {
  viewSessionEpoch++; cancelSeriesEdit()
  currentSeriesId.value=null; contextProductId=0; followsProductSelection=true; seriesRevealKey.value++
  pendingProductId.value=0; reuseOpen.value=false; modelsOpen.value=false; bomOpen.value=false; bomTargetId.value=0; revisingBomVersion.value=undefined; versionsOpen.value=false; modelToDelete.value=null; lifecycleTarget.value=null
}, {flush:'sync'})
onUnmounted(() => {cancelSeriesEdit(); store.closeLedgerMaterial(); store.closeProduct(); store.closeBomDetail()})
function reset(): void {
  if (busy.value || connectionLost.value) return
  const unchanged = !query.value.query && query.value.kind === null
  query.value = {...query.value,query:'',kind:null,page:1}
  // 没有搜索条件变化时，筛选监听不会触发；仍须真正查询第一页。
  if (unchanged) {store.closeProduct(); void store.queryProducts(1)}
}
function selectSeries(id: number | null): void {
  if (busy.value || connectionLost.value || (id !== null && !models.value.some(row=>row.id===id))) return
  cancelSeriesEdit()
  // 折叠由侧栏维护；选择系列只决定下一次新建的归属，不清空右侧 BOM。
  // 用户的明确归属意图优先于在途详情，迟到响应不能把“未归组”改回旧系列。
  followsProductSelection=false; currentSeriesId.value=id
}
function selectProduct(id: number): Promise<void> {
  if (!busy.value && !connectionLost.value) {cancelSeriesEdit(); modelsOpen.value=false}
  pendingProductId.value=0; detailsOpen.value = false
  followsProductSelection=true
  const row=productDirectoryRows.value.find(item=>item.id===id) ?? (detail.value?.id===id ? detail.value : undefined)
  if (row) currentSeriesId.value=row.model_id
  else contextProductId=0
  return store.openProduct(id)
}
function startBom(source?: Bom, revision=false): void {
  if (productUnavailable.value || (source && !store.can('production.view'))) return
  cancelSeriesEdit(true)
  if (detail.value && store.prepareProductBom(detail.value.material_id, source)) {
    revisingBomVersion.value=revision ? source?.version : undefined
    bomTargetId.value=detail.value.material_id; reuseOpen.value=false; versionsOpen.value=false; bomOpen.value=true
  }
}
function openBomCreation(allowBlank=true): void {
  if (!detail.value || productUnavailable.value || !store.can('bom.create') || (!allowBlank && !store.can('production.view'))) return
  cancelSeriesEdit(true)
  // 选择方式时锁定目标意图，不能在切到另一子机型后将旧选择带给新产品。
  creationTarget=detail.value.material_id; creationSelection=productSelectionEpoch; creationSession=viewSessionEpoch
  creationAllowsBlank.value=allowBlank; reuseOpen.value=true
}
function chooseBomSource(source?: Bom): void {
  if (!reuseOpen.value || !detail.value || productUnavailable.value || !store.can('bom.create')
    || creationTarget!==detail.value.material_id || creationSelection!==productSelectionEpoch || creationSession!==viewSessionEpoch) return
  if (!source && !creationAllowsBlank.value) return
  // 来源可能在浮层打开后取消或被刷新移除，使用当前目录中的完整版本重新校验。
  const current=source ? boms.value.find(row=>row.id===source.id && row.status!=='cancelled') : undefined
  if (source && (!store.can('production.view') || !current)) return
  if (!productBomRecords.value.length && store.can('production.view')) {
    if (store.prepareProductBom(creationTarget,current)) reuseOpen.value=false
  } else startBom(current)
}
function reviseBom(): void {
  const source=selectedBom.value
  // 修订固定当前已选版本，不猜最新配方；已取消来源及其他产品的旧回执不能带入。
  if (!source || source.status==='cancelled' || source.product_material_id!==detail.value?.material_id) return
  startBom(source,true)
}
async function editProduct(): Promise<void> {
  if (!detail.value || productUnavailable.value || !store.can('catalog.manage')) return
  cancelSeriesEdit(true)
  detailsOpen.value=false
  await store.startProduct('edit',detail.value.id)
}
// 每个明确的弹窗入口都先撤销旧系列读取，避免迟到资料在新窗口上方再次弹出。
function openProductDetails(): void {
  if (!detail.value || productUnavailable.value || !store.can('inventory.view')) return
  cancelSeriesEdit(true); detailsOpen.value=true
}
function openVersionList(): void {
  if (productUnavailable.value || !store.can('production.view') || !productBomRecords.value.length) return
  cancelSeriesEdit(true); versionsOpen.value=true
}
function openBomDetails(id:number): void {
  if (productUnavailable.value || !store.can('production.view') || !Number.isSafeInteger(id) || id<=0) return
  cancelSeriesEdit(true); void store.openBomDetail(id)
}
function requestSeriesDelete(model:ProductModel): void {
  if (busy.value || connectionLost.value || !store.can('catalog.manage')) return
  const current=models.value.find(row=>row.id===model.id)
  if (!current) return
  cancelSeriesEdit(true); modelToDelete.value=current
}
function newSeries(): void {
  if (!store.can('catalog.manage') || busy.value || connectionLost.value) return
  cancelSeriesEdit()
  // 显式新建系列才退出原编辑模式，新建失败的同一份草稿继续保留。
  if (productModelForm.value.id) productModelForm.value={id:0,version:0,code:'',name:'',notes:'',reason:''}
  productModelChanges.value=[]; createSeriesOnly.value=true; modelsOpen.value=true
}
async function editSeries(id:number): Promise<void> {
  if (!store.can('catalog.manage') || busy.value || connectionLost.value || !models.value.some(row=>row.id===id)) return
  modelsOpen.value=false; cancelSeriesEdit()
  createSeriesOnly.value=false
  // 同一系列收起再打开沿用草稿；换系列才读取详情与审计，失败不会展示旧表单。
  if (productModelForm.value.id===id) {modelsOpen.value=true; return}
  const intent=++seriesEditIntent, session=viewSessionEpoch
  pendingSeriesId=id
  const row=await store.editProductModel(id)
  if (intent!==seriesEditIntent) return
  pendingSeriesId=0
  if (!row || session!==viewSessionEpoch || !store.can('catalog.manage') || busy.value || connectionLost.value
    || !models.value.some(model=>model.id===id) || productModelForm.value.id!==id) return
  modelsOpen.value=true
}
function newModel(mode:'new'|'existing'='new'): Promise<void> {
  if (store.can('catalog.manage') && !busy.value && !connectionLost.value) {cancelSeriesEdit(); modelsOpen.value=false}
  // null 明确表示未归组，不能回退到右侧旧产品的系列。
  return store.startProduct(mode,0,false,currentSeriesId.value)
}
function seriesSaved(model:ProductModel): void {selectSeries(model.id); seriesRevealKey.value++}
function productSaved(row:ProductProfile): void {
  // 新子机型可能位于另一页，先保存定位意图，再刷新左侧目录和右侧 BOM。
  pendingProductId.value=row.id
  followsProductSelection=false; currentSeriesId.value=row.model_id; seriesRevealKey.value++
  const unchanged=query.value.model_id===null && !query.value.query && query.value.kind===null
  query.value={...query.value,model_id:null,query:'',kind:null,page:1}
  if (unchanged) void store.queryProducts(1)
}
async function afterBomSaved(saved?: Bom): Promise<void> {
  const id=productDetailId.value, epoch=viewSessionEpoch, selection=productSelectionEpoch
  if (!id || (saved && saved.product_material_id!==detail.value?.material_id)) return
  // 只定位自己的创建回执；并发产生的更高版本不能抢走修订后的当前选择。
  await store.openProduct(id)
  if (saved && epoch===viewSessionEpoch && selection===productSelectionEpoch && id===productDetailId.value && !productDetailError.value
    && productBomRecords.value.some(row=>row.id===saved.id && row.product_material_id===saved.product_material_id)) selectedBomId.value=saved.id
}
function changeSummary(value: ProductProfile): string {
  return [value.material.sku, value.material.name, productKindLabels[value.kind], value.model_name || '未归组',
    value.configuration_name || '未设置配置', value.can_sell === false ? '不可销售' : '可销售',
    value.can_purchase === false ? '不可采购' : '可采购', value.can_produce === false ? '不可生产' : '可生产', value.material.specification || '未填写规格', value.material.unit].join(' · ')
}
function sameModel(): void {
  if (!detail.value?.model_id) return
  detailsOpen.value = false; selectSeries(detail.value.model_id); seriesRevealKey.value++
}
</script>
<template>
  <section class="product-workspace">
    <ProductTreeSidebar :models="models" :page="result" :rows="productDirectoryRows" :query="query" :selected-id="productDetailId" :selected="detail"
      :active-series-id="currentSeriesId" :reveal-series-key="seriesRevealKey"
      :loading="productsLoading" :error="productsError" :busy="busy" :disconnected="connectionLost" :can-manage="store.can('catalog.manage')"
      :loading-more="productsLoadingMore" :more-error="productsMoreError"
      @series="selectSeries" @select="selectProduct" @new-series="newSeries" @new-model="newModel()" @include="newModel('existing')"
      @delete="requestSeriesDelete" @edit="editSeries" @load-more="store.loadMoreProducts()" @reset="reset" @retry="store.queryProducts()" />
    <div class="product-main">
    <section v-if="productDetailId" class="product-bom-panel" aria-label="选中产品的 BOM">
      <header v-if="detail" class="product-bom-heading">
        <div class="product-identity">
          <div class="product-meta"><span class="product-kind">{{ productKindLabels[detail.kind] }}</span><AppStatusTag v-if="detail.can_produce===false" label="子机型已停用" tone="pending" /><span class="product-code">{{ detail.material.sku }}</span><span v-if="detail.configuration_name && detail.configuration_name !== detail.material.name">{{ detail.configuration_name }}</span></div>
          <h3>{{ detail.material.name }}</h3>
          <p v-if="detail.material.spec_summary || detail.material.specification" class="muted">{{ detail.material.spec_summary || detail.material.specification }}</p>
        </div>
        <div class="product-toolbar">
          <AppButton size="small" :disabled="productUnavailable" @click.capture="captureDialogOrigin('product-detail',$event)" @click="openProductDetails">产品资料</AppButton>
          <AppButton v-if="store.can('catalog.manage')" size="small" :disabled="productUnavailable" @click="editProduct">编辑产品</AppButton>
          <NDropdown v-if="store.can('catalog.manage')" trigger="click" :options="lifecycleOptions" :disabled="productUnavailable" @select="selectLifecycle">
            <AppButton size="small" :disabled="productUnavailable" aria-haspopup="menu" @click.capture="captureDialogOrigin('product-lifecycle',$event)">子机型操作</AppButton>
          </NDropdown>
          <AppButton v-if="store.can('bom.create') && (productBomRecords.length || !store.can('production.view'))" size="small" variant="primary" :disabled="productUnavailable" @click="openBomCreation()">新建版本</AppButton>
        </div>
      </header>
      <!-- 当前组成是工作区主体，历史表格按需打开，避免每次查看都占用一张卡片。 -->
      <template v-if="store.can('production.view')">
        <div v-if="productDetailLoading" class="bom-workspace-state" role="status">正在读取 BOM…</div>
        <div v-else-if="productDetailError" class="bom-workspace-state" role="alert"><p>{{ productDetailError }}</p><AppButton size="small" :disabled="busy || connectionLost" @click="afterBomSaved()">重试</AppButton></div>
        <template v-else-if="selectedBom">
          <div class="bom-version-bar" aria-label="当前 BOM 版本">
            <div class="bom-version-choice"><span class="bom-version-label">BOM 版本</span>
              <WorkspaceSelect :model-value="selectedBom.id" :options="versionOptions" aria-label="选择 BOM 版本" size="small" :disabled="productUnavailable" @update:model-value="selectVersion" />
              <AppStatusTag :label="bomStatuses[selectedBom.status].label" :tone="bomStatuses[selectedBom.status].tone" />
            </div>
            <div class="product-toolbar"><AppButton v-if="store.can('bom.create')" size="small" tone="primary" :disabled="productUnavailable || selectedBom.status==='cancelled'" @click.capture="captureDialogOrigin('ProductionBomsView:form',$event)" @click="reviseBom">修订 BOM</AppButton>
              <AppButton size="small" :disabled="productUnavailable" @click="openBomDetails(selectedBom.id)">版本详情</AppButton>
              <AppButton size="small" :disabled="productUnavailable" @click.capture="captureDialogOrigin('product-bom-versions',$event)" @click="openVersionList">版本管理 · {{ productBomRecords.length }}</AppButton></div>
          </div>
          <div v-if="selectedBom.source_bom" class="bom-source muted">复制来源：<AppButton variant="text" size="small" :disabled="productUnavailable" @click="openBomDetails(selectedBom.source_bom.id)">{{ selectedBom.source_bom.product_name }} · V{{ selectedBom.source_bom.version }}</AppButton></div>
          <ProductBomStructure :bom="selectedBom" :catalog="boms" :materials="materials" :categories="materialCategories" :disabled="productUnavailable" @open="openBomDetails" @material="openCompositionMaterial" />
        </template>
        <!-- 首次配方直接编辑，物料选择、数量校验和保存仍与升版弹窗共用。 -->
        <BomEditor v-else-if="detail && store.can('bom.create')" :key="detail.material_id" inline :show="true"
          :target-material-id="detail.material_id" @saved="afterBomSaved" @reuse="openBomCreation(false)" />
        <div v-else class="bom-workspace-state"><h4>尚未建立 BOM</h4><p class="muted">此产品暂无可查看的 BOM 版本。</p></div>
      </template>
        <p v-if="!store.can('production.view')" class="muted">当前账号没有生产查看权限，关联 BOM 内容不加载。</p>
    </section>
    <section v-else class="bom-workspace-empty"><h3>BOM 工作区</h3><p class="muted">{{ productsLoading ? '正在读取子机型…' : productsError ? '左侧目录查询失败，请重试。' : `在左侧选择子机型，或在「${seriesName}」中新建子机型，再配置 BOM。` }}</p></section>
    </div>
    <ProductEditor v-if="!bomOpen && productEditorOpen" entity-label="子机型" @saved="productSaved" />
    <ProductModelsDialog v-model:show="modelsOpen" :create-only="createSeriesOnly" form-only @saved="seriesSaved" @delete="requestSeriesDelete" />
    <ProductModelDeleteDialog :model="modelToDelete" @close="modelToDelete=null" />
    <ProductLifecycleDialog :product="lifecycleTarget" :action="lifecycleAction" @close="lifecycleTarget=null" />
    <ProductBomReuseDialog :show="reuseOpen && store.can('bom.create')" :allow-blank="creationAllowsBlank"
      :sources="store.can('production.view') ? boms : []" :target-name="detail ? `${detail.material.name} · ${detail.material.sku}` : ''"
      :busy="busy" :disconnected="connectionLost" @update:show="reuseOpen=$event" @choose="chooseBomSource" @blank="chooseBomSource()" />
    <BomEditor v-if="bomOpen" v-model:show="bomOpen" :target-material-id="bomTargetId || undefined" :source-version="revisingBomVersion" @saved="afterBomSaved" />
    <BomDetailDialog />
    <WorkspaceDocumentDialog origin-key="product-bom-versions" :show="versionsOpen && store.can('production.view') && !bomDetailRecord && !bomDetailLoading && !bomDetailError"
      read-only title="BOM 版本管理" lines-title="全部版本" :data="productBomRecords" :columns="bomColumns" :min-table-width="860"
      :ready="!productDetailLoading" :load-error="productDetailError" :busy="busy" @update:show="versionsOpen=$event" @invalidated="versionsOpen=false">
      <template #basicInfo><div v-if="detail" class="document-detail-field"><span>当前产品</span><strong>{{ detail.material.name }}</strong></div>
        <div v-if="detail" class="document-detail-field"><span>产品编码</span><strong>{{ detail.material.sku }}</strong></div>
        <div class="document-detail-field"><span>版本规则</span><strong>同一产品仅允许一个启用版本</strong></div></template>
      <template #cell-version="{row}"><strong>V{{ row.version }}</strong><small class="muted"> · #{{ row.id }}</small></template>
      <template #cell-status="{row}"><AppStatusTag :label="bomStatuses[row.status].label" :tone="bomStatuses[row.status].tone" /></template>
      <template #cell-source="{row}"><AppButton v-if="row.source_bom" variant="text" size="small" :disabled="productUnavailable" @click="openBomDetails(row.source_bom.id)">{{ row.source_bom.product_name }} · V{{ row.source_bom.version }}</AppButton><span v-else class="muted">独立创建</span></template>
      <template #cell-actions="{row}"><div class="form-actions">
        <AppButton size="small" :disabled="productUnavailable" @click="viewComposition(row.id)">{{ selectedBom?.id === row.id ? '当前组成' : '查看组成' }}</AppButton>
        <AppButton v-if="row.status !== 'cancelled' && store.can('bom.create')" size="small" :disabled="productUnavailable" @click="startBom(row)">复制派生</AppButton>
        <AppButton v-if="row.status === 'draft' && store.can('bom.activate')" size="small" tone="success" :disabled="productUnavailable || productBomRecords.some(item=>item.status==='active') || detail?.can_produce===false" @click="store.activateBom(row.id).then(()=>afterBomSaved())">启用</AppButton>
        <AppButton v-if="row.status === 'active' && store.can('bom.retire')" size="small" tone="warning" :disabled="productUnavailable" @click="store.retireBom(row.id).then(()=>afterBomSaved())">停用</AppButton>
        <AppButton v-if="row.status === 'draft' && store.can('bom.cancel')" size="small" tone="error" :disabled="productUnavailable" @click="store.cancelBom(row.id).then(()=>afterBomSaved())">取消草稿</AppButton>
      </div></template>
    </WorkspaceDocumentDialog>
    <WorkspaceDocumentDialog origin-key="product-detail" :show="showDetail" read-only title="产品资料" :data="[]" :columns="[]" :show-lines="false"
      :ready="!productDetailLoading" :load-error="productDetailError" :busy="busy" @update:show="detailsOpen = $event" @invalidated="detailsOpen = false">
      <template #basicInfo><template v-if="detail">
        <div class="document-detail-field"><span>产品编码</span><strong>{{ detail.material.sku }}</strong></div>
        <div class="document-detail-field"><span>产品名称</span><strong>{{ detail.material.name }}</strong></div>
        <div class="document-detail-field"><span>产品类型</span><strong>{{ productKindLabels[detail.kind] }}</strong></div>
        <div class="document-detail-field"><span>业务用途</span><strong>{{ [detail.can_sell !== false ? '可销售' : '不可销售',detail.can_purchase !== false ? '可采购' : '不可采购',detail.can_produce !== false ? '可生产' : '不可生产'].join(' · ') }}</strong></div>
        <div class="document-detail-field"><span>产品系列</span><strong>{{ detail.model_name || '未归组' }}</strong></div>
        <div class="document-detail-field"><span>配置</span><strong>{{ detail.configuration_name || '—' }}</strong></div>
        <div v-for="fact in facts" :key="fact.key" class="document-detail-field"><span>{{ fact.label }}</span><strong>{{ fact.value }}</strong></div>
      </template></template>
      <template #afterLines><template v-if="detail">
        <section class="product-parameters"><h3>物料参数</h3><WorkspaceMaterialParameters :material="detail.material" :categories="materialCategories" :compact="false" /></section>
        <div class="form-actions product-section-actions">
          <AppButton v-if="store.can('catalog.manage')" :disabled="busy || connectionLost" @click="editProduct">编辑子机型</AppButton>
          <AppButton v-if="detail.model_id" :disabled="busy" @click="sameModel">查看同系列产品</AppButton>
          <AppButton v-if="store.can('bom.create')" :disabled="busy || connectionLost" @click="startBom()">新建 BOM</AppButton>
        </div>
        <section class="product-section-actions"><h3>产品变更记录</h3>
          <p v-if="productChangesLoading" class="muted" role="status">正在读取产品变更记录…</p>
          <div v-else-if="productChangesError" role="alert"><p>{{ productChangesError }}</p><AppButton size="small" :disabled="busy || connectionLost" @click="store.loadProductChanges(true)">重试读取记录</AppButton></div>
          <p v-else-if="!productChangeRecords.length" class="muted">暂无产品变更记录。</p>
          <NCollapse v-else><AppCollapseItem v-for="change in productChangeRecords" :key="change.id" :name="change.id" :title="`${store.localTime(change.created_at)} · ${change.changed_by_name} · ${change.reason}`">
            <p v-if="change.before && 'material' in change.before">变更前：{{ changeSummary(change.before) }}</p>
            <p v-if="'material' in change.after">变更后：{{ changeSummary(change.after) }}</p>
          </AppCollapseItem></NCollapse>
        </section>
      </template></template>
    </WorkspaceDocumentDialog>
    <InventoryDetailDialogs />
  </section>
</template>
<style scoped>
/* 既有主题控制颜色；产品头、版本栏和组成共用一个容器，减少重复卡片留白。 */
.product-workspace { display:grid; grid-template-columns:280px minmax(0,1fr); gap:14px; align-items:stretch; flex:1; min-height:0; }
.product-main { min-width:0; min-height:0; }
.product-bom-panel { min-width:0; padding:20px; border:1px solid var(--workspace-field-border); border-radius:14px; background:var(--app-modal-background); }
.product-bom-heading { display:flex; align-items:flex-start; justify-content:space-between; gap:16px; flex-wrap:wrap; padding-bottom:18px; }
.product-identity { display:grid; gap:8px; min-width:0; flex:1 1 260px; }
.product-bom-heading h3,.product-bom-heading p { margin:0; overflow-wrap:anywhere; }
.product-bom-heading h3 { font-size:20px; line-height:1.4; }
.product-bom-heading p { font-size:13px; line-height:1.6; }
.product-meta { display:flex; align-items:center; gap:8px; flex-wrap:wrap; font-size:12px; color:var(--workspace-field-muted); }
.product-kind { border-radius:5px; padding:3px 7px; color:var(--workspace-field-accent); background:var(--app-accent-tint); font-weight:600; }
.product-code { font-variant-numeric:tabular-nums; overflow-wrap:anywhere; }
.product-toolbar { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
.bom-version-bar { display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px; padding:14px 0; border-top:1px solid var(--workspace-field-border); border-bottom:1px solid var(--workspace-field-border); }
.bom-version-choice { display:flex; align-items:center; gap:10px; flex-wrap:wrap; min-width:0; }
/* 公共标签默认贴顶部；版本栏局部覆盖，保证标签与选择框、左右文字共用中心线。 */
.bom-version-choice > .app-status-tag { align-self:center; }
.bom-version-label { font-size:12px; color:var(--workspace-field-muted); }
.bom-version-choice .workspace-select { width:170px; max-width:100%; }
.bom-source { display:flex; align-items:center; flex-wrap:wrap; gap:4px; padding-top:14px; font-size:12px; }
.bom-workspace-state { display:grid; justify-items:center; align-content:center; gap:12px; min-height:260px; text-align:center; }
.bom-workspace-state h4,.bom-workspace-state p { margin:0; overflow-wrap:anywhere; }
.bom-workspace-state[role='alert'] { color:var(--workspace-field-text); }
.bom-workspace-empty { display:grid; align-content:center; justify-items:center; gap:12px; min-height:360px; padding:32px; text-align:center; border:1px solid var(--workspace-field-border); border-radius:14px; background:var(--app-modal-surface); }
.bom-workspace-empty h3,.bom-workspace-empty p { margin:0; }
@media(max-width:1100px) { .product-workspace { grid-template-columns:260px minmax(0,1fr); gap:14px; } .product-bom-panel { padding:16px; } }
/* 与左侧目录分别占用剩余高度，长 BOM 的滚动不再带走目录的搜索和新建入口。 */
@media(min-width:761px) { .product-main { overflow-y:auto; overscroll-behavior:contain; scrollbar-gutter:stable; } }
/* 桌面最小宽度仍保留两列，隐藏重复标签，为版本选择与状态留出同一行。 */
@media(max-width:1000px) { .bom-version-label { display:none; } .bom-version-choice .workspace-select { width:140px; } }
@media(max-width:760px) { .product-workspace { grid-template-columns:minmax(0,1fr); } .product-bom-heading h3 { font-size:18px; } }
.product-section-actions { margin:20px 0; }
/* 产品资料直接展示参数，保留独立标题与身份区的间距。 */
.product-parameters { margin:16px 0; }
</style>
