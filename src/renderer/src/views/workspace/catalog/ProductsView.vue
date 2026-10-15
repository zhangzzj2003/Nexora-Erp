<script setup lang="ts">
import { computed, ref, watch, onUnmounted } from 'vue'
import { NCollapse } from 'naive-ui'
import AppCollapseItem from '../../../components/app/AppCollapseItem.vue'
import { storeToRefs } from 'pinia'
import { useRoute } from 'vue-router'
import { usePiniaAppStore } from '../../../store/app-store'
import { productKindLabels, productKinds } from '../../../../../shared/product-api'
import type { ProductProfile } from '../../../../../shared/product-api'
import type { Bom } from '../../../../../shared/erp-api'
import { materialChoiceFacts } from '../../../utils/material-selection'
import { captureDialogOrigin } from '../../../utils/dialog-origin'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import WorkspaceDocumentDialog from '../../../components/workspace/WorkspaceDocumentDialog.vue'
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import AppInput from '../../../components/app/AppInput.vue'
import AppButton from '../../../components/app/AppButton.vue'
import ProductEditor from './ProductEditor.vue'
import ProductModelsDialog from './ProductModelsDialog.vue'
import BomEditor from './BomEditor.vue'
import BomDetailDialog from './BomDetailDialog.vue'
// 页面只组织展示，分页、草稿、版本写入和会话边界统一放在 Pinia。
const store = usePiniaAppStore(), route = useRoute()
const {productQuery: query, productResult: result, productModels: models, productsLoading, productsError,
  productDetailRecord: detail, productDetailId, productDetailLoading, productDetailError,
  productBomRecords, productChangeRecords, productEditorOpen, bomDetailRecord, bomDetailLoading, bomDetailError,
  materialCategories, busy, connectionLost} = storeToRefs(store)
const modelsOpen = ref(false), bomOpen = ref(false)
const columns = [{key:'sku',title:'产品编码',width:'190'}, {key:'name',title:'产品名称',width:'230'},
  {key:'kind',title:'类型',width:'90'}, {key:'model',title:'机型 / 配置',width:'220'},
  {key:'specification',title:'规格'}, {key:'unit',title:'单位',width:'70',align:'center' as const}, {key:'actions',title:'查看',width:'80'}]
const bomColumns = [{key:'version',title:'BOM 版本',width:'160'}, {key:'status',title:'状态',width:'100'},
  {key:'source',title:'派生来源'}, {key:'actions',title:'操作',width:'350'}]
const facts = computed(() => detail.value ? materialChoiceFacts(detail.value.material, materialCategories.value) : [])
const technicalFacts = computed(() => detail.value ? materialChoiceFacts(detail.value.material, materialCategories.value, true) : [])
const showDetail = computed(() => !!productDetailId.value && !bomOpen.value && !productEditorOpen.value
  && !bomDetailRecord.value && !bomDetailLoading.value && !bomDetailError.value)
watch(() => JSON.stringify([query.value.query, query.value.kind, query.value.model_id,
  store.user?.id, store.user?.permissions.slice().sort(), connectionLost.value, store.server?.id, store.server?.fingerprint]),
  () => {if (store.can('inventory.view') && !connectionLost.value) void store.queryProducts()}, {immediate:true})
// 从 BOM 返回产品时以固定产品编号定位，常规快照刷新不会重新打开已关闭详情。
watch(() => [route.query.product_id, store.user?.id], () => {
  const id = Number(route.query.product_id)
  if (Number.isSafeInteger(id) && id > 0) void store.openProduct(id)
}, {immediate:true})
onUnmounted(() => {store.closeProduct(); store.closeBomDetail()})
function pageChange(page: number, size: number): void {query.value.page_size = size; void store.queryProducts(page)}
function reset(): void {query.value = {query:'',kind:null,model_id:null,page:1,page_size:query.value.page_size}}
function startBom(source?: Bom): void {
  if (detail.value && store.prepareProductBom(detail.value.material_id, source)) bomOpen.value = true
}
async function afterBomSaved(): Promise<void> {
  // 写后只刷新当前产品范围，不能把另一个产品的 BOM 显示在此详情中。
  if (productDetailId.value) await store.openProduct(productDetailId.value)
}
function changeSummary(value: ProductProfile): string {
  return [value.material.sku, value.material.name, productKindLabels[value.kind], value.model_name || '未归组',
    value.configuration_name || '未设置配置', value.material.specification || '未填写规格', value.material.unit].join(' · ')
}
function sameModel(): void {
  if (!detail.value?.model_id) return
  query.value.model_id = detail.value.model_id; query.value.query = ''; query.value.kind = null
  store.closeProduct()
}
</script>
<template>
  <section class="stack">
    <WorkspaceTable title="产品管理" :show-title="false" :data="result?.items ?? []" :columns="columns" :min-table-width="1180"
      :loading="productsLoading" :error="productsError"
      :pagination="{page: result?.page ?? query.page, pageSize: query.page_size, total: result?.total ?? 0, disabled: connectionLost}" @page-change="pageChange">
      <template #filters><div class="product-filters">
        <label>搜索产品<AppInput v-model.trim="query.query" maxlength="120" placeholder="编码、名称、规格、机型或配置" /></label>
        <label>产品类型<WorkspaceSelect v-model="query.kind" :options="[{value:null,label:'全部类型'},...productKinds.map(value=>({value,label:productKindLabels[value]}))]" /></label>
        <label>所属机型<WorkspaceSelect v-model="query.model_id" :options="[{value:null,label:'全部机型'},...models.map(row=>({value:row.id,label:`${row.code} · ${row.name}`}))]" /></label>
        <AppButton @click="reset">重置</AppButton><AppButton :disabled="productsLoading || connectionLost" @click="store.queryProducts()">查询</AppButton>
      </div></template>
      <template #actions><template v-if="store.can('catalog.manage')">
        <AppButton :disabled="busy || connectionLost" @click="modelsOpen = true">机型管理</AppButton>
        <AppButton :disabled="busy || connectionLost" @click="store.startProduct('existing')">纳入已有物料</AppButton>
        <AppButton variant="primary" :disabled="busy || connectionLost" @click="store.startProduct('new')">新增产品</AppButton>
      </template></template>
      <template #cell-sku="{row}"><strong>{{ row.material.sku }}</strong></template>
      <template #cell-name="{row}">{{ row.material.name }}</template><template #cell-kind="{row}">{{ productKindLabels[row.kind] }}</template>
      <template #cell-model="{row}">{{ row.model_name || '未归组' }}<small class="muted">{{ row.configuration_name || '未设置配置' }}</small></template>
      <template #cell-specification="{row}">{{ row.material.spec_summary || row.material.specification || '—' }}</template>
      <template #cell-unit="{row}">{{ row.material.unit }}</template>
      <template #cell-actions="{row}"><AppButton size="small" :disabled="busy || connectionLost" @click.capture="captureDialogOrigin('product-detail',$event)" @click="store.openProduct(row.id)">查看</AppButton></template>
      <template #empty>{{ productsError ? '产品查询失败，请重试。' : store.can('catalog.manage') ? '暂无匹配产品，可新建产品或纳入已有物料。' : '暂无匹配产品，请调整搜索条件。' }}</template>
    </WorkspaceTable>
    <ProductEditor v-if="!bomOpen && productEditorOpen" />
    <ProductModelsDialog v-model:show="modelsOpen" />
    <BomEditor v-model:show="bomOpen" @saved="afterBomSaved" />
    <BomDetailDialog />
    <WorkspaceDocumentDialog origin-key="product-detail" :show="showDetail" read-only title="产品详情" :data="[]" :columns="[]" :show-lines="false"
      :ready="!productDetailLoading" :load-error="productDetailError" :busy="busy" @update:show="!$event && store.closeProduct()" @invalidated="store.closeProduct">
      <template #basicInfo><template v-if="detail">
        <div class="document-detail-field"><span>产品编码</span><strong>{{ detail.material.sku }}</strong></div>
        <div class="document-detail-field"><span>产品名称</span><strong>{{ detail.material.name }}</strong></div>
        <div class="document-detail-field"><span>产品类型</span><strong>{{ productKindLabels[detail.kind] }}</strong></div>
        <div class="document-detail-field"><span>机型</span><strong>{{ detail.model_name || '未归组' }}</strong></div>
        <div class="document-detail-field"><span>配置</span><strong>{{ detail.configuration_name || '—' }}</strong></div>
        <div v-for="fact in facts" :key="fact.key" class="document-detail-field"><span>{{ fact.label }}</span><strong>{{ fact.value }}</strong></div>
      </template></template>
      <template #afterLines><template v-if="detail">
        <NCollapse v-if="technicalFacts.length" class="product-more"><AppCollapseItem name="specifications" title="规格与更多资料">
          <dl><div v-for="fact in technicalFacts" :key="fact.key"><dt>{{ fact.label }}</dt><dd>{{ fact.value }}</dd></div></dl>
        </AppCollapseItem></NCollapse>
        <div class="form-actions product-section-actions">
          <AppButton v-if="store.can('catalog.manage')" :disabled="busy || connectionLost" @click="store.startProduct('edit',detail.id)">编辑产品</AppButton>
          <AppButton v-if="detail.model_id" :disabled="busy" @click="sameModel">查看同机型产品</AppButton>
          <AppButton v-if="store.can('bom.create')" :disabled="busy || connectionLost" @click="startBom()">新建 BOM</AppButton>
        </div>
        <WorkspaceTable v-if="store.can('production.view')" title="关联 BOM" :data="productBomRecords" :columns="bomColumns" :min-table-width="860">
          <template #cell-version="{row}">#{{ row.id }} · V{{ row.version }}</template>
          <template #cell-status="{row}">{{ {draft:'草稿',active:'已启用',retired:'已停用',cancelled:'已取消'}[row.status] }}</template>
          <template #cell-source="{row}"><AppButton v-if="row.source_bom" size="small" :disabled="busy || connectionLost" @click="store.openBomDetail(row.source_bom.id)">{{ row.source_bom.product_name }} · V{{ row.source_bom.version }}</AppButton><span v-else>独立创建</span></template>
          <template #cell-actions="{row}"><div class="form-actions">
            <AppButton size="small" :disabled="busy || connectionLost" @click="store.openBomDetail(row.id)">BOM 详情</AppButton>
            <AppButton v-if="row.status !== 'cancelled' && store.can('bom.create')" size="small" :disabled="busy || connectionLost" @click="startBom(row)">复制派生</AppButton>
            <AppButton v-if="row.status === 'draft' && store.can('bom.activate')" size="small" :disabled="busy || connectionLost || productBomRecords.some(item=>item.status==='active')" @click="store.activateBom(row.id).then(afterBomSaved)">启用</AppButton>
            <AppButton v-if="row.status === 'active' && store.can('bom.retire')" size="small" :disabled="busy || connectionLost" @click="store.retireBom(row.id).then(afterBomSaved)">停用</AppButton>
            <AppButton v-if="row.status === 'draft' && store.can('bom.cancel')" size="small" :disabled="busy || connectionLost" @click="store.cancelBom(row.id).then(afterBomSaved)">取消草稿</AppButton>
          </div></template>
          <template #empty>此产品尚未建立 BOM。</template>
        </WorkspaceTable>
        <p v-else class="muted">当前账号没有生产查看权限，关联 BOM 内容不加载。</p>
        <section class="product-section-actions"><h3>产品变更记录</h3>
          <p v-if="!productChangeRecords.length" class="muted">暂无产品变更记录。</p>
          <NCollapse><AppCollapseItem v-for="change in productChangeRecords" :key="change.id" :name="change.id" :title="`${store.localTime(change.created_at)} · ${change.changed_by_name} · ${change.reason}`">
            <p v-if="change.before && 'material' in change.before">变更前：{{ changeSummary(change.before) }}</p>
            <p v-if="'material' in change.after">变更后：{{ changeSummary(change.after) }}</p>
          </AppCollapseItem></NCollapse>
        </section>
      </template></template>
    </WorkspaceDocumentDialog>
  </section>
</template>
<style scoped>
/* 筛选沿用公共表格，窄窗口换行而不撑宽整页；历史证据允许展开复制。 */
.product-filters { display:flex; flex-wrap:wrap; align-items:end; gap:12px; }
.product-filters label { min-width:160px; flex:1; }
small { display:block; margin-top:6px; }
.product-section-actions { margin:20px 0; }
.product-more { margin:16px 0; }
.product-more dl { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:16px; }
.product-more dt { color:var(--workspace-field-muted); font-size:12px; }
.product-more dd { margin:6px 0 0; white-space:pre-wrap; overflow-wrap:anywhere; }
</style>
