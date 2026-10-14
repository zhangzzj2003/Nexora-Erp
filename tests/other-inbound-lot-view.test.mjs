import assert from "node:assert/strict";
import { test } from "node:test";
import { createSSRApp, h } from "vue";
import { setup as setupSsrStyles } from "@css-render/vue3-ssr";
import { renderToString } from "@vue/server-renderer";
import { createPinia } from "pinia";
import { createServer } from "vite";
import vue from "@vitejs/plugin-vue";

const buttonModule = `import {defineComponent,h} from 'vue';export const buttons=[];
export default defineComponent({props:['disabled'],setup(p,{slots,attrs}){return()=>{
 const children=slots.default?.();const label=(children??[]).map(v=>typeof v.children==='string'?v.children:'').join('').trim();
 buttons.push({label,disabled:p.disabled,click:attrs.onClick});return h('button',attrs,children)}}});`;

test("其他入库列表区分待登记、已登记和旧单未分配批次", async (t) => {
  const fixture = `import {defineStore} from 'pinia';import {ref} from 'vue';
  export const calls=[];const documentApprovalTarget=ref(null);
  export const usePiniaAppStore=defineStore('inbound-lot-ui-test',()=>({
    documentApprovalTarget,documentApprovalError:ref(''),documentApprovalRecord:ref(null),documentApprovalLoading:ref(false),error:ref(''),notice:ref(''),busy:ref(false),connectionLost:ref(false),materials:ref([]),warehouses:ref([]),
    otherInbounds:ref([]),otherInboundForm:ref({lines:[]}),otherInboundReopenForms:ref({}),otherInboundReversalReasons:ref({}),
    initialDetailId:ref(0),
    can:code=>code==='other_inbound.post',localTime:value=>value,
    createOtherInbound(){},postOtherInbound(){},cancelOtherInbound(){},reverseOtherInbound(){},prepareOtherInboundReopen(){return true},
    openDocumentApproval(target){calls.push(['approval',target]);documentApprovalTarget.value=target;return true},
    closeDocumentApproval(){documentApprovalTarget.value=null},loadDocumentApproval(){}
  }));`;
  const server = await createServer({
    configFile: false,
    plugins: [
      {
        name: "other-inbound-lot-fixture",
        enforce: "pre",
        transform(code, id) {
          // SSR 每次渲染重建组件实例，预设详情 ID 才能渲染真实详情弹窗。
          if (id.endsWith("/OtherInboundsView.vue"))
            return code.replace(
              "const detailInboundId = ref(0)",
              "const detailInboundId = ref(store.initialDetailId)",
            );
          // 弹窗内容默认进入 teleport，改写导入为内联替身才能在主渲染结果中断言。
          if (id.endsWith("/WorkspaceDocumentDialog.vue"))
            return code.replace("'naive-ui'", "'virtual:other-inbound-modal'").replace(/(['"])[^'"]*AppModal\.vue\1/g, "'virtual:other-inbound-modal'");
        },
        resolveId(id, importer) {
          if (id === "virtual:other-inbound-modal")
            return "\0other-inbound-naive";
          if (
            importer?.includes("/warehouse/OtherInboundsView") &&
            id.endsWith("/store/app-store")
          )
            return "\0other-inbound-store";
          if (id.endsWith("/DocumentApprovalPanel.vue"))
            return "\0inbound-approval-placeholder";
          if (id.endsWith("/WorkspaceTable.vue"))
            return "\0other-inbound-table";
          if (id.endsWith("/AppButton.vue")) return "\0other-inbound-button";
          if (
            id === "naive-ui" &&
            (importer?.includes("OtherInboundsView") ||
              importer?.includes("WorkspaceDocumentDialog"))
          )
            return "\0other-inbound-naive";
        },
        load(id) {
          if (id === "\0inbound-approval-placeholder")
            return "export default {render(){return null}}";
          if (id === "\0other-inbound-store") return fixture;
          if (id === "\0other-inbound-button") return buttonModule;
          if (id === "\0other-inbound-table")
            return `import {defineComponent,h} from 'vue';export default defineComponent({props:{data:Array},setup(props,{slots}){return ()=>h('section',[slots.filters?.(),...props.data.flatMap(row=>['document','source','lines','actions'].map(key=>slots['cell-'+key]?.({row}))),slots.empty?.()])}})`;
          if (id === "\0other-inbound-naive")
            return `import {defineComponent,h} from 'vue';const Modal=defineComponent({props:{show:Boolean},setup(props,{slots}){return ()=>props.show?h('section',slots.default?.()):null}});export { NModal as default }; export const NModal=Modal,NDatePicker=Modal;`;
        },
      },
      vue(),
    ],
    optimizeDeps: { noDiscovery: true, include: [] },
    server: { middlewareMode: true, hmr: false },
    appType: "custom",
  });
  t.after(() => server.close());
  const { usePiniaAppStore, calls } = await server.ssrLoadModule(
    "\0other-inbound-store",
  );
  const { buttons } = await server.ssrLoadModule("\0other-inbound-button");
  const pinia = createPinia(),
    store = usePiniaAppStore(pinia);
  const { default: View } = await server.ssrLoadModule(
    "/src/renderer/src/views/workspace/warehouse/OtherInboundsView.vue",
  );
  // 原生下拉菜单在服务端渲染时需要样式收集器，避免访问浏览器 document。
  let vnode;
  const render = () => {
    buttons.length = 0;
    vnode = h(View);
    const app = createSSRApp({ render: () => vnode }).use(pinia);
    setupSsrStyles(app);
    return renderToString(app);
  };
  const inbound = {
    id: 3,
    status: "draft",
    reason: "gift",
    note: "赠品",
    warehouse_name: "主仓库",
    created_at: "2026-10-02",
    created_by_name: "admin",
    reference: "GIFT",
    reversal_id: null,
    reversal_reason: null,
    lines: [
      {
        id: 7,
        sku: "GIFT-3",
        material_name: "赠品物料",
        quantity: "2.125",
        unit: "件",
        physical_lots: [],
      },
    ],
  };
  store.otherInbounds = [inbound];
  assert.doesNotMatch(await render(), /登记实物批次（可选）|>确认入库</);
  // 行内业务按钮不出现，单号和「查看」两个入口点击都打开同一详情。
  store.otherInbounds = [{ ...inbound, approval: { status: "approved" } }];
  assert.ok(
    !buttons.some((button) =>
      ["确认入库", "登记实物批次（可选）"].includes(button.label),
    ),
  );
  for (const entry of ["查看", "#3"]) {
    calls.length = 0;
    const button = buttons.find((item) => item.label === entry);
    assert.ok(button, entry);
    await button.click();
    assert.deepEqual(calls.at(-1), [
      "approval",
      { document_type: "WarehouseInbound", document_id: 3, intent: "execute" },
    ]);
  }
  assert.equal(vnode.component.setupState.detailInbound.id, 3);
  // 批准后业务入口移入详情页脚；关闭详情时列表不泄漏业务按钮。
  store.initialDetailId = 3;
  const detail = await render();
  assert.match(detail, /其他入库详情/);
  assert.match(detail, />确认入库</);
  assert.match(detail, /登记实物批次（可选）/);
  assert.equal(
    buttons.filter((button) => button.label === "确认入库").length,
    1,
  );
  assert.equal(
    buttons.filter((button) => button.label === "登记实物批次（可选）").length,
    1,
  );
  store.initialDetailId = 0;
  assert.doesNotMatch(await render(), /登记实物批次（可选）|>确认入库</);
  store.otherInbounds = [{ ...inbound, status: "posted" }];
  assert.match(await render(), /普通入库，未登记实物批次/);
  store.otherInbounds = [
    {
      ...inbound,
      status: "posted",
      lines: [
        {
          ...inbound.lines[0],
          physical_lots: [
            { id: 1, code: "O3-L7-P1", quantity: "2.125", supplier_lot: null },
          ],
        },
      ],
    },
  ];
  const posted = await render();
  assert.match(posted, /O3-L7-P1/);
  assert.match(posted, /来源批号 未提供/);
  assert.doesNotMatch(posted, /未登记实物批次/);
});
