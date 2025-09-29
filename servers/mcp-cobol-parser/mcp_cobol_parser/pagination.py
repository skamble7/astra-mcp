# File: servers/mcp-cobol-parser/mcp_cobol_parser/pagination.py
from __future__ import annotations
import base64, json
from pydantic import BaseModel, Field

ORDER_KEY = "krelpath"

class CursorV1(BaseModel):
    v: int = 1
    kinds: list[str] = Field(default_factory=lambda: ["source_index", "copybook", "program"])
    offset: int = 0
    ps: int = 100
    run_id: str
    order_key: str = ORDER_KEY

def encode_cursor(c: CursorV1) -> str:
    data = c.model_dump()
    raw = json.dumps(data, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")

def decode_cursor(s: str) -> CursorV1:
    raw = base64.urlsafe_b64decode(s.encode("ascii"))
    data = json.loads(raw)
    c = CursorV1(**data)
    if c.order_key != ORDER_KEY:
        raise ValueError("Cursor ordering changed; please restart without cursor.")
    return c
