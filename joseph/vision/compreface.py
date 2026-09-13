"""adapter for a self-hosted exadel compreface instance (apache-2.0).

this is the explicitly-authorized backend the face_recognition channel was left open for.
recognition runs ONLY against the operator's own compreface collection -> the faces you
enrolled and are permitted to compare against. it is not an internet-wide face scanner.

    recognize -> candidate subject(s) + similarity from your collection (evidence, a lead)
    detect    -> landmarks / age / gender / mask / pose measurements (no identity)

both are best-effort and env-gated: with no url/key the channels stay CANNOT_RESOLVE. the
epistemic rule holds -> visual similarity is evidence for a candidate, never proof.
"""

from __future__ import annotations

from dataclasses import dataclass

from .channels import ChannelResult, CANNOT_RESOLVE


@dataclass(frozen=True)
class CompreFaceConfig:
    url: str
    recognition_key: str = ""
    detection_key: str = ""
    timeout: int = 20
    det_prob_threshold: float = 0.8
    prediction_count: int = 3

    @property
    def has_recognition(self) -> bool:
        return bool(self.url and self.recognition_key)

    @property
    def has_detection(self) -> bool:
        return bool(self.url and self.detection_key)


async def _post_image(endpoint: str, api_key: str, data: bytes, params: dict, timeout: int):
    """POST an image to a compreface endpoint. returns (status, json|None, error)."""
    try:
        import aiohttp
    except Exception:
        return 0, None, "aiohttp not installed"
    form = aiohttp.FormData()
    form.add_field("file", data, filename="image.jpg", content_type="application/octet-stream")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                endpoint,
                data=form,
                params={k: str(v) for k, v in params.items()},
                headers={"x-api-key": api_key},
                timeout=timeout,
            ) as resp:
                status = resp.status
                try:
                    body = await resp.json(content_type=None)
                except Exception:
                    body = None
                return status, body, "" if status < 400 else f"http {status}"
    except Exception as exc:  # network / dns / timeout
        return 0, None, f"{type(exc).__name__}"


async def recognize(cfg: CompreFaceConfig, data: bytes) -> ChannelResult:
    name = "face_recognition"
    if not cfg.has_recognition:
        return ChannelResult(
            name, CANNOT_RESOLVE, {},
            reason="identity matching disabled -> set COMPREFACE_URL + COMPREFACE_RECOGNITION_KEY to your own compreface instance",
            confidence=0.0,
        )
    endpoint = f"{cfg.url}/api/v1/recognition/recognize"
    params = {
        "limit": 0,
        "prediction_count": cfg.prediction_count,
        "det_prob_threshold": cfg.det_prob_threshold,
        "face_plugins": "age,gender,mask",
        "status": "true",
    }
    status, body, err = await _post_image(endpoint, cfg.recognition_key, data, params, cfg.timeout)
    if body is None or "result" not in (body or {}):
        return ChannelResult(name, CANNOT_RESOLVE, {}, reason=f"compreface unreachable/invalid response ({err or 'no result'})", confidence=0.0)

    faces = []
    for face in body.get("result", []):
        subjects = face.get("subjects", []) or []
        best = subjects[0] if subjects else None
        faces.append(
            {
                "box": face.get("box"),
                "candidates": [{"subject": s.get("subject"), "similarity": round(float(s.get("similarity", 0)), 4)} for s in subjects],
                "top_subject": best.get("subject") if best else None,
                "top_similarity": round(float(best.get("similarity", 0)), 4) if best else None,
                "age": face.get("age"),
                "gender": face.get("gender"),
                "mask": face.get("mask"),
            }
        )
    obs = {
        "faces": faces,
        "collection": "operator-controlled compreface collection",
        "note": "candidate match against YOUR enrolled subjects -> evidence/a lead, not proof of identity",
    }
    if not faces:
        return ChannelResult(name, "partial", obs, reason="no face detected in the image", confidence=0.3)
    top = max((f.get("top_similarity") or 0.0) for f in faces)
    return ChannelResult(name, "resolved", obs, confidence=min(0.85, float(top)))


async def detect(cfg: CompreFaceConfig, data: bytes) -> ChannelResult:
    name = "compreface_detect"
    if not cfg.has_detection:
        return ChannelResult(
            name, CANNOT_RESOLVE, {},
            reason="detection passthrough disabled -> set COMPREFACE_URL + COMPREFACE_DETECTION_KEY",
            confidence=0.0,
        )
    endpoint = f"{cfg.url}/api/v1/detection/detect"
    params = {
        "limit": 0,
        "det_prob_threshold": cfg.det_prob_threshold,
        "face_plugins": "landmarks,gender,age,mask,pose",
        "status": "true",
    }
    status, body, err = await _post_image(endpoint, cfg.detection_key, data, params, cfg.timeout)
    if body is None or "result" not in (body or {}):
        return ChannelResult(name, CANNOT_RESOLVE, {}, reason=f"compreface unreachable/invalid response ({err or 'no result'})", confidence=0.0)

    faces = []
    for face in body.get("result", []):
        faces.append(
            {
                "box": face.get("box"),
                "age": face.get("age"),
                "gender": face.get("gender"),
                "mask": face.get("mask"),
                "pose": face.get("pose"),
                "landmarks_count": len(face.get("landmarks", []) or []),
            }
        )
    obs = {"count": len(faces), "faces": faces, "note": "attribute measurement only -> no identity"}
    if not faces:
        return ChannelResult(name, "partial", obs, reason="no face detected", confidence=0.3)
    return ChannelResult(name, "resolved", obs, confidence=0.8)
