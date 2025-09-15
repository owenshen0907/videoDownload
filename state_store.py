# state_store.py
from __future__ import annotations
from typing import Dict

# 记录：page_url -> last_downloaded_path
PAGE_TO_PATH: Dict[str, str] = {}