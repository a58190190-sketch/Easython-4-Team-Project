"""OpenCV based screenshot and visible-region inspection."""
from __future__ import annotations
import base64
from typing import Any

def analyze_capture(screenshot_data: str) -> dict[str, Any]:
    """Inspect the current viewport locally and discard the screenshot."""
    try:
        encoded = screenshot_data.split(",", 1)[-1]
        raw = base64.b64decode(encoded, validate=True)
        import cv2
        import numpy as np
        image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("이미지 디코딩 실패")
        height, width = image.shape[:2]
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 65, 155)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        regions = []
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            if w * h >= 300 and w >= 18 and h >= 12:
                regions.append({"x": int(x), "y": int(y), "width": int(w), "height": int(h)})
        regions.sort(key=lambda rect: rect["width"] * rect["height"], reverse=True)
        edge_density = float(cv2.countNonZero(edges)) / float(max(1, width * height))
        return {"ok": True, "width": width, "height": height, "region_count": len(regions), "edge_density": round(edge_density, 4)}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "width": 0, "height": 0, "region_count": 0, "edge_density": 0.0}
