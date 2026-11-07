"""评测体系包（EVALUATION_PLAN V6 §11）。

独立于 production code（backend/app）运行；通过项目根 pytest 配置
pythonpath 指向 ``backend/`` 以 import ``app.*``。
"""

__all__ = ["__version__"]
__version__ = "1.0.0"