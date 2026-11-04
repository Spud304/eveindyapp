from ninja import NinjaAPI
from ninja.security import django_auth

from apps.accounts.api import router as accounts_router
from apps.core.api import router as core_router
from apps.esidata.api import router as sync_router
from apps.esidata.overview_api import router as overview_router
from apps.planning.api import router as planning_router
from apps.planning.plans_api import router as plans_router
from apps.sde.api import router as sde_router

# django_auth is cookie-based, so ninja enforces CSRF on unsafe methods automatically.
api = NinjaAPI(
    title="EVE Indy API",
    version="0.1.0",
    auth=django_auth,
    urls_namespace="api",
)

api.add_router("/", core_router)
api.add_router("/", accounts_router)
api.add_router("/", planning_router)
api.add_router("/", plans_router)
api.add_router("/", sde_router)
api.add_router("/", sync_router)
api.add_router("/", overview_router)
