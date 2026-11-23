"""e2e sızıntı testi: StandardLoggingPayload'ı (spend log'a giden yük) dosyaya yazan logger.

Dosya yolu LEAK_LOG_PATH ortam değişkeninden alınır.
"""

from __future__ import annotations

import json
import os
from typing import Any

from litellm.integrations.custom_logger import CustomLogger


class LeakLogger(CustomLogger):
    def _write(self, kind: str, kwargs: dict[str, Any], response_obj: Any) -> None:
        path = os.environ.get("LEAK_LOG_PATH")
        if not path:
            return
        payload = kwargs.get("standard_logging_object")
        rec = {"kind": kind, "standard_logging_object": payload, "messages": kwargs.get("messages"), "response": str(response_obj)}
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")

    async def async_log_success_event(self, kwargs: dict[str, Any], response_obj: Any, start_time: Any, end_time: Any) -> None:
        self._write("success", kwargs, response_obj)

    async def async_log_failure_event(self, kwargs: dict[str, Any], response_obj: Any, start_time: Any, end_time: Any) -> None:
        self._write("failure", kwargs, response_obj)


leak_logger = LeakLogger()
