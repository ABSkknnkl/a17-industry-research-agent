import sys
from pathlib import Path
import uvicorn

# 确保 backend 位于 sys.path
PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from backend.app.core.config import settings

def main():
    print("================================================================================")
    print("🚀 启动同花顺问财SkillHub五智能体研报后端服务")
    print(f"  服务地址: http://{settings.HOST}:{settings.PORT}")
    print(f"  接口文档: http://{settings.HOST}:{settings.PORT}/docs")
    print(f"  模型基座: {settings.LLM_MODEL}")
    print("================================================================================")
    uvicorn.run(
        "backend.app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=False,
        access_log=True,
    )

if __name__ == "__main__":
    main()
