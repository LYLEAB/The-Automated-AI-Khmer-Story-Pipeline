"""
Pydantic V2 data models for the Khmer Story Pipeline.
"""
from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator


class SceneMood(str, Enum):
    MYSTERIOUS = "mysterious"
    JOYFUL = "joyful"
    DRAMATIC = "dramatic"
    PEACEFUL = "peaceful"
    TENSE = "tense"
    MELANCHOLIC = "melancholic"
    TRIUMPHANT = "triumphant"
    ROMANTIC = "romantic"


class KenBurnsPreset(str, Enum):
    ZOOM_IN = "zoom_in"
    ZOOM_OUT = "zoom_out"
    PAN_LEFT = "pan_left"
    PAN_RIGHT = "pan_right"


class ExportProfile(str, Enum):
    MOBILE = "mobile"    # 1080x1920 portrait 9:16
    LAPTOP = "laptop"    # 1920x1080 landscape 16:9
    BOTH = "both"


class Scene(BaseModel):
    scene_id: int = Field(..., ge=1, description="1-based scene index")
    khmer_narration: str = Field(..., min_length=1, description="Khmer Unicode narration text")
    visual_prompt: str = Field(..., min_length=1, description="English prompt for image generation")
    mood: SceneMood = Field(default=SceneMood.DRAMATIC)
    duration_hint_seconds: int = Field(default=15, ge=5, le=60)

    @field_validator("khmer_narration")
    @classmethod
    def validate_khmer(cls, v: str) -> str:
        if not any("\u1780" <= ch <= "\u17FF" for ch in v):
            raise ValueError("khmer_narration must contain Khmer Unicode characters (U+1780-U+17FF)")
        return v.strip()

    @field_validator("visual_prompt")
    @classmethod
    def clean_visual_prompt(cls, v: str) -> str:
        return v.strip()


class SceneList(BaseModel):
    story_title: str = Field(..., min_length=1, description="Story title in Khmer")
    story_title_en: str = Field(default="", description="Story title in English")
    total_scenes: int = Field(..., ge=1)
    scenes: List[Scene]


class EnrichedScene(Scene):
    audio_path: Optional[str] = None
    audio_duration_ms: Optional[float] = None
    image_path: Optional[str] = None
    ken_burns_preset: Optional[KenBurnsPreset] = None

    @property
    def audio_duration_s(self) -> float:
        if self.audio_duration_ms is None:
            return float(self.duration_hint_seconds)
        return self.audio_duration_ms / 1000.0


class StepStatus(str, Enum):
    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"


class PipelineState(BaseModel):
    story_prompt: str
    story_title: str = ""
    scenes_generated: bool = False
    audio_done_scenes: List[int] = Field(default_factory=list)
    images_done_scenes: List[int] = Field(default_factory=list)
    video_mobile_path: Optional[str] = None
    video_laptop_path: Optional[str] = None
    metadata_done: bool = False
    enriched_scenes: List[EnrichedScene] = Field(default_factory=list)

    def is_audio_done(self, scene_id: int) -> bool:
        return scene_id in self.audio_done_scenes

    def is_image_done(self, scene_id: int) -> bool:
        return scene_id in self.images_done_scenes

    def mark_audio_done(self, scene_id: int) -> None:
        if scene_id not in self.audio_done_scenes:
            self.audio_done_scenes.append(scene_id)

    def mark_image_done(self, scene_id: int) -> None:
        if scene_id not in self.images_done_scenes:
            self.images_done_scenes.append(scene_id)


class PublishMetadata(BaseModel):
    title_variants: List[str] = Field(..., min_length=1)
    description_khmer: str
    description_english: str
    hashtags: List[str]
    best_post_time: str = "18:00-21:00 Phnom Penh Time (Peak Engagement)"
    platform_notes: dict = Field(default_factory=dict)
