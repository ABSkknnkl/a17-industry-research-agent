import asyncio
import time
from chart_generator.image_gen import generate_industry_chain_image, ImageGenSettings


def test_generate_industry_chain_image_guard_fast_return():
    """Verify that when IMAGE_API_KEY is not configured, generate_industry_chain_image returns None immediately."""
    settings = ImageGenSettings(
        api_key="",
        base_url="https://router.shengsuanyun.com/api/v1",
        model="openai/gpt-image-2",
        llm_api_key="mock-llm-key",
    )
    start = time.perf_counter()
    result = asyncio.run(generate_industry_chain_image(
        subject="人工智能",
        title="产业链全景图",
        option={},
        artifact_dir=None,
        chart_id="CHART-02",
        settings=settings,
    ))
    elapsed = time.perf_counter() - start
    assert result is None
    assert elapsed < 0.1, f"Expected near-instant return (<100ms), but took {elapsed:.3f}s"
