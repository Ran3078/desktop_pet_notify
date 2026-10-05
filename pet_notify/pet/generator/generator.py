"""角色生成器介面。

目前只有 LocalGenerator（本機：去背 + 程式動畫）。之後若要接 AI 服務（例如把照片轉成卡通角色、
生成不同動作的圖），實作一個新的 CharacterGenerator 子類別並放進 GENERATORS 即可，
建立精靈與輸出皮膚的程式都不用改。
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from PySide6.QtGui import QImage

from . import animator, background

log = logging.getLogger(__name__)


@dataclass
class GenerateOptions:
    bg_mode: str = background.AUTO            # auto / alpha / none
    tolerance: int = 40
    extra_colors: list[tuple[int, int, int]] = field(default_factory=list)
    seed_sides: set[str] | None = None        # 從哪些邊開始去背；None = 自動偵測


@dataclass
class GeneratedCharacter:
    cutout: QImage                                    # 去背、裁切後的角色圖
    states: dict[str, tuple[float, list[QImage]]]     # 狀態 → (fps, 影格)
    generator: str = ""


class CharacterGenerator(ABC):
    id: str = ""
    name: str = ""
    available: bool = True

    def cutout(self, image: QImage, options: GenerateOptions) -> QImage:
        """預覽用：只做去背與裁切。"""
        removed = background.remove_background(image, options.bg_mode, options.tolerance, options.extra_colors,
                                               options.seed_sides)
        return background.trim(removed, padding=1)  # 留白太多會讓角色腳底懸空

    @abstractmethod
    def generate(self, image: QImage, options: GenerateOptions) -> GeneratedCharacter: ...


class LocalGenerator(CharacterGenerator):
    id = "local"
    name = "本機自動生成"

    def generate(self, image: QImage, options: GenerateOptions) -> GeneratedCharacter:
        cut = self.cutout(image, options)
        if background.opaque_bounds(cut) is None:
            raise ValueError("去背後整張圖都是透明的，請把容差調低，或改成「不去背」。")
        states = animator.animate(cut)
        log.info("本機生成角色：%dx%d，%d 個狀態", cut.width(), cut.height(), len(states))
        return GeneratedCharacter(cut, states, self.id)


class AiGenerator(CharacterGenerator):
    """預留：AI 生成器。

    接法建議：
    1. cutout() 可以改用 AI 去背；generate() 把圖片送到圖片生成服務，要求輸出同一個角色的各個動作
    2. 把回傳的圖片依狀態整理成 {狀態: (fps, [QImage...])}；缺的狀態可以交給 animator 用 cutout 補
    3. API 金鑰請放在 .env（不要寫死在程式裡），並在呼叫前讓使用者確認圖片會上傳到外部服務
    """

    id = "ai"
    name = "AI 生成（尚未開放）"
    available = False

    def generate(self, image: QImage, options: GenerateOptions) -> GeneratedCharacter:
        raise NotImplementedError("AI 生成器尚未實作")


GENERATORS: list[CharacterGenerator] = [LocalGenerator(), AiGenerator()]


def available_generators() -> list[CharacterGenerator]:
    return [g for g in GENERATORS if g.available]
