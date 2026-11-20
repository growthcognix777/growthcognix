"""Brand & creative library. Files are Phase 1 Documents of the same client; colours, fonts and template
links are values. Only approved assets can be attached to content or quoted to the AI."""
from __future__ import annotations

import re

ASSET_KINDS = ["logo", "colour", "font", "product_image", "guideline", "template", "creative"]
FILE_KINDS = {"logo", "product_image", "guideline", "template", "creative"}
HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}){1,2}$")


def validate(kind: str, value: str | None, has_file: bool) -> str | None:
    if kind not in ASSET_KINDS:
        raise ValueError(f"Asset type must be one of {', '.join(ASSET_KINDS)}")
    v = (value or "").strip() or None
    if kind == "colour":
        if not v or not HEX.match(v):
            raise ValueError("Colour must be a hex value like #0B2A4A")
        return v.upper()
    if kind == "font":
        if not v:
            raise ValueError("Enter the font name")
        return v[:120]
    if kind in FILE_KINDS and not has_file and not (v and v.startswith("https://")):
        raise ValueError("Attach an uploaded file or give an https link to the asset")
    return v
