from __future__ import annotations

import json
from dataclasses import dataclass, field

from google.adk.runners import InMemoryRunner
from google.genai import types

from ..schemas.domain import ArtifactRef


@dataclass
class ArtifactContext:
    runner: InMemoryRunner
    app_name: str
    user_id: str
    session_id: str
    artifacts: list[ArtifactRef] = field(default_factory=list)

    async def save_text(self, filename: str, text: str, mime_type: str = "text/plain") -> ArtifactRef:
        part = types.Part.from_text(text=text)
        version = await self.runner.artifact_service.save_artifact(
            app_name=self.app_name,
            user_id=self.user_id,
            session_id=self.session_id,
            filename=filename,
            artifact=part,
            custom_metadata={"mime_type": mime_type},
        )
        ref = ArtifactRef(name=filename, mime_type=mime_type, version=version)
        self.artifacts.append(ref)
        return ref

    async def save_bytes(self, filename: str, payload: bytes, mime_type: str) -> ArtifactRef:
        part = types.Part.from_bytes(data=payload, mime_type=mime_type)
        version = await self.runner.artifact_service.save_artifact(
            app_name=self.app_name,
            user_id=self.user_id,
            session_id=self.session_id,
            filename=filename,
            artifact=part,
            custom_metadata={"mime_type": mime_type},
        )
        ref = ArtifactRef(name=filename, mime_type=mime_type, version=version)
        self.artifacts.append(ref)
        return ref

    async def save_json(self, filename: str, payload: dict) -> ArtifactRef:
        return await self.save_text(filename, json.dumps(payload, ensure_ascii=False, indent=2) + "\n", "application/json")

    async def load_text(self, filename: str, version: int | None = None) -> str:
        try:
            part = await self.runner.artifact_service.load_artifact(
                app_name=self.app_name,
                user_id=self.user_id,
                session_id=self.session_id,
                filename=filename,
                version=version,
            )
            if part is None:
                raise FileNotFoundError(f"Artifact not found: {filename}")
            if getattr(part, "text", None):
                return part.text
            inline_data = getattr(part, "inline_data", None)
            if inline_data and getattr(inline_data, "data", None):
                return inline_data.data.decode("utf-8")
            return str(part)
        except Exception as e:
            raise FileNotFoundError(f"Failed to load artifact {filename}: {str(e)}") from e
