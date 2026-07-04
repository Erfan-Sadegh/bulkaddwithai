import os

import pytest


@pytest.mark.ai_live
def test_live_ai_key_is_available_for_manual_runs():
    if not os.getenv("AVALAI_API_KEY"):
        pytest.skip("AVALAI_API_KEY is not set")
    assert os.getenv("AVALAI_API_KEY")
