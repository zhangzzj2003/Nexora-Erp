import assert from "node:assert/strict";
import { test } from "node:test";
import { createSSRApp, h } from "vue";
import { createPinia } from "pinia";
import { renderToString } from "@vue/server-renderer";
import { createServer } from "vite";
import vue from "@vitejs/plugin-vue";

const buttonModule = `import {defineComponent,h} from 'vue';export const buttons=[];
export default defineComponent({props:['disabled'],setup(p,{slots,attrs}){return()=>{
 const children=slots.default?.();const label=(children??[]).map(v=>typeof v.children==='string'?v.children:'').join('').trim();
 buttons.push({label,disabled:p.disabled,click:attrs.onClick});return h('button',attrs,children)}}});`;

test("采购入库列表明确区分待登记、已登记与旧单未分配批次", async (t) => {
  // 使用同一个 Pinia 状态，旧单无批次仍可查看，执行按钮只在详情页脚批准后出现。
  const fixture = `import {defineStore} from 'pinia';import {createAppState} from '/src/renderer/src/store/state.ts';
    export const calls=[];
    export const usePiniaAppStore=defineStore('receipt-lot-view',()=>{const state=createAppState();
      return {...state,can:code=>code==='receipt.post',localTime:value=>value,postReceipt(){},reverseReceipt(){},
        openDocumentApproval(target){calls.push(['approval',target]);state.documentApprovalTarget.value=target;return true},
        closeDocumentApproval(){state.documentApprovalTarget.value=null}}});`;
  const server = await createServer({
    configFile: false,
    plugins: [
      {
        name: "receipt-lot-view-fixture",
        enforce: "pre",
        resolveId(id, importer) {
          if (
            importer?.includes("/purchase/PurchaseReceiptsView") &&
            id.endsWith("/store/app-store")
          )
            return "\0receipt-lot-store";
          if (id.endsWith("/DocumentApprovalDialog.vue"))
            return "\0receipt-approval-dialog";
          if (id.endsWith("/WorkspaceTable.vue")) return "\0receipt-lot-table";
          if (id.endsWith("/AppButton.vue")) return "\0receipt-lot-button";
        },
        load(id) {
          if (id === "\0receipt-lot-store") return fixture;
          if (id === "\0receipt-approval-dialog")
            return `export default {render(){return this.$slots.footerActions?.()??null}}`;
          if (id === "\0receipt-lot-button") return buttonModule;
          if (id === "\0receipt-lot-table")
            return `import {defineComponent,h} from 'vue';export default defineComponent({props:{data:Array},setup(props,{slots}){return ()=>h('section',[slots.filters?.(),...(props.data??[]).flatMap(row=>['document','status','details','actions'].map(key=>slots['cell-'+key]?.({row}))),slots.empty?.()])}})`;
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
    "\0receipt-lot-store",
  );
  const { buttons } = await server.ssrLoadModule("\0receipt-lot-button");
  const pinia = createPinia(),
    store = usePiniaAppStore(pinia);
  const { default: View } = await server.ssrLoadModule(
    "/src/renderer/src/views/workspace/purchase/PurchaseReceiptsView.vue",
  );
  const render = async () => {
    buttons.length = 0;
    return renderToString(createSSRApp({ render: () => h(View) }).use(pinia));
  };
  const receipt = {
    id: 3,
    supplier_name: "供应商",
    warehouse_name: "主仓库",
    created_at: "2026-10-02",
    created_by_name: "admin",
    purchase_order_id: null,
    goods_receipt_id: null,
    reference: "",
    reversal_id: null,
    reversal_reason: null,
    status: "draft",
    lines: [
      {
        id: 7,
        sku: "LOT-3",
        material_name: "物料",
        quantity: "2.125",
        unit: "件",
        returned_quantity: "0",
        physical_lots: [],
      },
    ],
  };
  store.receipts = [receipt];
  assert.doesNotMatch(await render(), />确认入库<|登记实物批次（可选）/);
  // 行内只保留单号和「查看」两个入口，点击都打开同一详情。
  for (const entry of ["查看", "#3"]) {
    calls.length = 0;
    const button = buttons.find((item) => item.label === entry);
    assert.ok(button, entry);
    await button.click();
    assert.deepEqual(calls.at(-1), [
      "approval",
      { document_type: "Receipt", document_id: 3, intent: "execute" },
    ]);
  }
  // 关闭详情后批准单据也不会把业务按钮泄漏到页面其他位置。
  store.documentApprovalTarget = null;
  store.receipts = [{ ...receipt, approval: { status: "approved" } }];
  assert.doesNotMatch(await render(), /登记实物批次（可选）|>确认入库</);
  // 执行入口移入详情页脚，批准后同时提供普通入库与实物登记。
  store.documentApprovalTarget = {
    document_type: "Receipt",
    document_id: 3,
    intent: "execute",
  };
  const approved = await render();
  assert.match(approved, /登记实物批次（可选）/);
  assert.match(approved, />确认入库</);
  store.documentApprovalTarget = null;
  store.receipts = [{ ...receipt, status: "posted" }];
  assert.match(await render(), /普通入库，未登记实物批次/);
  store.receipts = [
    {
      ...receipt,
      status: "posted",
      lines: [
        {
          ...receipt.lines[0],
          physical_lots: [
            { id: 1, code: "R3-L7-P1", quantity: "2.125", supplier_lot: null },
          ],
        },
      ],
    },
  ];
  const posted = await render();
  assert.match(posted, /R3-L7-P1/);
  assert.match(posted, /供应商批号 未提供/);
  assert.doesNotMatch(posted, /未登记实物批次/);
});
