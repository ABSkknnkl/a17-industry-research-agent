from __future__ import annotations
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import backend.app.core.setup_env  # 自动注册五智能体路径
from backend.app.api.routes import router as api_router
from backend.app.core.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("fastapi_app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 行业研究五智能体协同服务启动中...")
    logger.info(f"  模型基座: {settings.LLM_MODEL} @ {settings.LLM_BASE_URL}")
    logger.info(f"  问财SkillHub配置完成，数据存储路径: {settings.DATA_DIR}")
    yield
    logger.info("🛑 行业研究五智能体协同服务已安全停止")


app = FastAPI(
    title="同花顺问财SkillHub五智能体行业研报系统",
    description="面向证券投资研究领域的多智能体流水线协同与全程人机协同研报生成后端",
    version="1.0.0",
    lifespan=lifespan,
)

# 允许跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载业务端点
app.include_router(api_router)


@app.get("/health")
@app.get("/health/ready")
async def health_check():
    return {
        "status": "ok",
        "service": "industry-research-multi-agent-backend",
        "llm_model": settings.LLM_MODEL,
        "agents_ready": True,
    }


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception(f"全局未捕获异常: {request.url} - {exc}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": f"服务器内部错误: {str(exc)}"},
    )
