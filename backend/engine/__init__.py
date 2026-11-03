"""Planning engine: pure Python, no Flask/Django/DB access.

Build a `PlanInput`, call `plan()`, read the `PlanResult`.
"""

from .planner import PlanError, plan

__all__ = ["PlanError", "plan"]
