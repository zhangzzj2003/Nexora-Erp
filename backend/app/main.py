"""FastAPI 应用组装与服务生命周期。"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from sqlalchemy import select
from app.core.database import migrate
from app.core.models import ServerIdentity
from app.core.orm import orm_session
from app.service.discovery import DiscoveryPublisher
from app.access.routes import router as access_router
from app.access.menus import router as menu_router
from app.catalog.routes import router as catalog_router
from app.purchase.receipts import router as receipts_router
from app.purchase.orders import router as purchase_router
from app.purchase.approvals import router as purchase_approvals_router
from app.purchase.requests import router as purchase_requests_router
from app.purchase.goods_receipts import router as goods_receipts_router
from app.purchase.returns import router as purchase_returns_router
from app.inventory.warehouse import router as inventory_router
from app.inventory.stocktake import router as stocktake_router
from app.inventory.stock import router as stock_router
from app.inventory.ledger import router as ledger_router
from app.inventory.valuation import router as valuation_router
from app.inventory.adjustments import router as adjustments_router
from app.inventory.inbounds import router as warehouse_inbounds_router
from app.inventory.outbounds import router as warehouse_outbounds_router
from app.sales.orders import router as sales_router
from app.sales.customers import router as customers_router
from app.sales.returns import router as sales_returns_router
from app.production.boms import router as production_router
from app.production.work_orders import router as work_orders_router
from app.production.material_issues import router as material_issues_router
from app.production.material_returns import router as material_returns_router
from app.production.completions import router as production_completions_router
from app.production.tools import router as production_tools_router
from app.production.costs import router as production_costs_router
from app.production.settlements import router as production_settlements_router
from app.finance.tools import router as finance_tools_router
from app.finance.routes import router as finance_router
from app.finance.ledger import router as finance_ledger_router
from app.finance.journals import router as journals_router
from app.finance.ledger_reports import router as ledger_reports_router
from app.finance.opening_balances import router as opening_balances_router
from app.finance.period_closing import router as period_closing_router
from app.finance.business_journals import router as business_journals_router
from app.finance.profit_transfers import router as profit_transfers_router
from app.reports.routes import router as reports_router
from app.inventory.trace import router as trace_router
from app.query.routes import router as table_query_router
from app.service.routes import router as service_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    # 启动时检查并升级本地数据库；不依赖桌面页面是否已经打开。
    migrate()
    publisher = None
    task = None
    port = os.environ.get("NEXORA_DISCOVERY_PORT")
    if port is not None:
        with orm_session() as db:
            instance_id = db.scalar(select(ServerIdentity.id).limit(1))
        publisher = DiscoveryPublisher(instance_id, "0.1.0", int(port))

        async def publish_periodically():
            # 系统服务可能早于网卡启动；重复检查也能处理 IP 地址变化。
            while True:
                try:
                    await asyncio.to_thread(publisher.sync)
                except Exception:
                    logging.getLogger(__name__).exception("局域网发现状态更新失败")
                await asyncio.sleep(15)

        task = asyncio.create_task(publish_periodically())
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if publisher is not None:
            await asyncio.to_thread(publisher.close)


app = FastAPI(title="Nexora ERP API", version="0.1.0", lifespan=lifespan)
# 路由只在这里组装；各功能目录负责自己的参数校验与业务接口。
for router in (
    trace_router, service_router, access_router, menu_router, table_query_router, catalog_router, receipts_router,
    inventory_router, stock_router, ledger_router, valuation_router, stocktake_router, adjustments_router,
    warehouse_inbounds_router, warehouse_outbounds_router,
    purchase_approvals_router, purchase_router, purchase_requests_router, goods_receipts_router,
    purchase_returns_router, customers_router, sales_router, sales_returns_router,
    production_tools_router, production_router, work_orders_router, material_issues_router,
    material_returns_router, production_completions_router, production_costs_router, production_settlements_router,
    finance_tools_router, finance_router, finance_ledger_router, journals_router, ledger_reports_router, opening_balances_router, period_closing_router, business_journals_router, profit_transfers_router, reports_router,
):
    app.include_router(router)
