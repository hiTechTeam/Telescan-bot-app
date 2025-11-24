import pytest
from src.core.scripts import generate_code


@pytest.mark.asyncio
async def test_generate_code_length():
    code = await generate_code()

    assert len(code) == 8


@pytest.mark.asyncio
async def test_generate_code_randomness():
    len_codes = 1_000_000
    err_threshold = 0.001
    codes = {await generate_code() for _ in range(len_codes)}

    assert len(codes) > len_codes - (
        len_codes * err_threshold
    ), "Not enough randomness!"
