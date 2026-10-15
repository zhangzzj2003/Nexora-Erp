<script setup lang="ts">
import { computed, ref } from 'vue'
import AppButton from '../../../components/app/AppButton.vue'
import AppInput from '../../../components/app/AppInput.vue'
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import WorkspacePagination from '../../../components/workspace/WorkspacePagination.vue'
import { productKinds, productKindLabels } from '../../../../../shared/product-api'
import type { ProductModel, ProductProfile, ProductPage, ProductQuery } from '../../../../../shared/product-api'
const props = defineProps<{models:ProductModel[]; page:ProductPage|null; query:ProductQuery;
  selectedId:number; selected:ProductProfile|null; loading:boolean; error:string;
  busy:boolean; disconnected:boolean; canManage:boolean}>()
const emit = defineEmits<{
  series:[id:number|null]; select:[id:number]; newSeries:[]; newModel:[]; manage:[]; include:[];
  reset:[]; retry:[]; pageChange:[page:number,size:number]
}>()
const filterOpen=ref(false)
// 子节点来自当前服务端分页；系列目录始终完整，不把当前页条数冒充全局数量。
const children = computed(() => {
  if (props.loading || !props.page) return []
  const rows = [...props.page.items]
  // 刚保存或由固定编号定位的机型可能在另一页，保留一个明确的当前节点供操作。
  if (props.selected && props.selectedId === props.selected.id && !rows.some(row=>row.id===props.selectedId)
    && (props.query.model_id === null || props.selected.model_id === props.query.model_id)) rows.unshift(props.selected)
  return rows
})
const members = (id:number|null):ProductProfile[] => children.value.filter(row=>row.model_id===id)
</script>
<template>
  <aside class="product-tree" aria-label="产品系列与子机型">
    <header><h3>产品列表</h3></header>
    <div v-if="canManage" class="tree-create">
      <AppButton :disabled="busy || disconnected" @click="emit('newSeries')">新建系列</AppButton>
      <AppButton variant="primary" :disabled="busy || disconnected" @click="emit('newModel')">新建子机型</AppButton>
    </div>
    <div class="tree-search">
      <div class="tree-search-row"><AppInput v-model.trim="query.query" aria-label="搜索子机型" maxlength="120" placeholder="名称、编码或配置" :disabled="busy || disconnected" />
        <AppButton :aria-expanded="filterOpen || !!query.kind" :disabled="busy || disconnected" @click="filterOpen=!filterOpen">筛选</AppButton></div>
      <div v-if="filterOpen || query.kind" class="tree-filter"><WorkspaceSelect v-model="query.kind" aria-label="子机型类型" :options="[{value:null,label:'全部类型'},...productKinds.map(value=>({value,label:productKindLabels[value]}))]" :disabled="busy || disconnected" />
        <AppButton :disabled="busy || disconnected" @click="emit('reset')">重置</AppButton></div>
    </div>
    <nav class="tree-scroll" aria-label="选择系列与子机型">
      <AppButton variant="plain" class="tree-all" :aria-pressed="query.model_id===null" :disabled="busy || disconnected" @click="emit('series',null)">全部系列</AppButton>
      <p v-if="loading" role="status" class="muted">正在读取子机型…</p>
      <div v-else-if="error" role="alert"><p>{{ error }}</p><AppButton :disabled="disconnected" @click="emit('retry')">重试</AppButton></div>
      <ul class="tree-roots">
        <li v-for="model in models" :key="model.id">
          <AppButton variant="plain" class="tree-series" :class="{'is-current':query.model_id===model.id}" :aria-expanded="query.model_id===model.id || members(model.id).length>0" :disabled="busy || disconnected" @click="emit('series',model.id)">
            <span aria-hidden="true">{{ query.model_id===model.id || members(model.id).length ? '▾' : '▸' }}</span>
            <span class="series-label"><strong>{{ model.name }}</strong><small>{{ model.code }}</small></span>
          </AppButton>
          <ul v-if="members(model.id).length" class="tree-children">
            <li v-for="row in members(model.id)" :key="row.id"><AppButton variant="plain" class="tree-model" :class="{'is-active':selectedId===row.id}" :aria-pressed="selectedId===row.id" :disabled="busy || disconnected" @click="emit('select',row.id)">
              <!-- 名称只显示一次；配置有实际差异时才补充，避免未配置产品出现重复行。 -->
              <strong>{{ row.material.name }}</strong><small>{{ row.material.sku }}</small><span class="tree-product-meta"><span class="tree-kind">{{ productKindLabels[row.kind] }}</span><span v-if="row.configuration_name && row.configuration_name !== row.material.name">{{ row.configuration_name }}</span></span>
            </AppButton></li>
          </ul>
          <p v-else-if="query.model_id===model.id && !loading && !error" class="tree-empty muted">此系列暂无匹配子机型</p>
        </li>
        <li v-if="members(null).length"><h4 class="tree-unassigned">未归组产品 / 半成品</h4><ul class="tree-children">
          <li v-for="row in members(null)" :key="row.id"><AppButton variant="plain" class="tree-model" :class="{'is-active':selectedId===row.id}" :aria-pressed="selectedId===row.id" :disabled="busy || disconnected" @click="emit('select',row.id)">
            <!-- 名称只显示一次；配置有实际差异时才补充，避免未配置产品出现重复行。 -->
              <strong>{{ row.material.name }}</strong><small>{{ row.material.sku }}</small><span class="tree-product-meta"><span class="tree-kind">{{ productKindLabels[row.kind] }}</span><span v-if="row.configuration_name && row.configuration_name !== row.material.name">{{ row.configuration_name }}</span></span>
          </AppButton></li>
        </ul></li>
      </ul>
      <p v-if="!loading && !error && !children.length && query.model_id===null" class="tree-empty muted">{{ canManage ? '暂无子机型，可先新建系列，再建立子机型。' : '暂无匹配子机型，请调整搜索条件。' }}</p>
    </nav>
    <footer>
      <WorkspacePagination :page="page?.page ?? query.page" :page-size="query.page_size" :total="page?.total ?? 0" :disabled="loading || disconnected || busy" @change="(page,size)=>emit('pageChange',page,size)" />
      <div v-if="canManage" class="tree-maintenance"><AppButton size="small" :disabled="busy || disconnected" @click="emit('manage')">系列管理</AppButton><AppButton size="small" :disabled="busy || disconnected" @click="emit('include')">纳入已有物料</AppButton></div>
    </footer>
  </aside>
</template>
<style scoped>
/* 左侧独立滚动目录，系列与子机型缩进对应真实归属；右侧始终留给 BOM。 */
.product-tree { display:flex; flex-direction:column; gap:12px; height:max(560px,calc(100vh - 330px)); position:sticky; top:16px; min-width:0; padding:18px 14px; border:1px solid var(--workspace-field-border); border-radius:14px; background:var(--app-modal-surface); }
header h3 { margin:0; font-size:16px; } header p { margin:7px 0 0; font-size:12px; line-height:1.6; }
.tree-create,.tree-maintenance { display:flex; flex-wrap:wrap; gap:8px; }
.tree-create>* { flex:1; }
.tree-search { display:grid; gap:10px; } .tree-search label { display:grid; gap:7px; font-size:12px; }
.tree-filter,.tree-search-row { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:8px; }
.tree-scroll { flex:1; min-height:0; overflow:auto; }
.tree-roots,.tree-children { list-style:none; padding:0; margin:0; }
.tree-roots>li { margin-top:8px; }
.tree-all,.tree-series,.tree-model { width:100%; min-width:0; padding:10px 12px; border-radius:10px; text-align:left; white-space:normal; }
.tree-series { display:flex; align-items:center; justify-content:start; gap:8px; }
.series-label { display:grid; justify-items:start; gap:5px; }
/* 按钮内部承载文字网格，避免公共按钮的居中容器让不同长度的名称来回跳动。 */
.tree-model :deep(.n-button__content) { display:grid; justify-items:start; gap:5px; width:100%; text-align:left; }
.tree-product-meta { display:flex; align-items:center; flex-wrap:wrap; gap:6px; }
.tree-kind { padding:1px 5px; border-radius:4px; background:var(--app-accent-tint); color:var(--workspace-field-accent); }
small,.tree-product-meta { color:var(--workspace-field-muted); font-size:11px; overflow-wrap:anywhere; }
strong { font-size:13px; overflow-wrap:anywhere; }
.tree-all { text-align:left; color:var(--workspace-field-muted); }
.tree-series.is-current { background:var(--app-accent-tint); color:var(--workspace-field-accent); }
.tree-children { margin:4px 0 8px 15px; padding-left:10px; border-left:1px solid var(--workspace-field-border); }
.tree-model { margin-bottom:4px; border:1px solid transparent; }
.tree-model.is-active { border-color:var(--workspace-field-accent); background:var(--app-accent-tint); color:var(--workspace-field-accent); }
.tree-empty { margin:10px 12px; font-size:12px; line-height:1.7; }
.tree-unassigned { margin:14px 12px 8px; font-size:13px; color:var(--workspace-field-muted); }
footer { display:grid; gap:14px; padding-top:14px; border-top:1px solid var(--workspace-field-border); }
.tree-maintenance { justify-content:center; }
@media(max-width:760px) { .product-tree { position:static; height:480px; max-height:none; } }
</style>
