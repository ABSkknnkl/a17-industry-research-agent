"""chain-research 测试共享夹具：anyio 后端声明 + 断网隔离。"""

import pytest

pytestmark = pytest.mark.anyio


@pytest.fixture()
def anyio_backend():
    return "asyncio"
