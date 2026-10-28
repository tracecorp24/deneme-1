"""
core/human.py - İnsansı Davranış Modülü (Anti-Ban & Anti-Bot Bilişsel Simülasyon)
Bézier eğrileri ile fare hareketi, doğal titreşim (tremor), değişken klavye gecikmesi,
sayfa kaydırma ve jitter zamanlaması içerir.
"""
import time
import math
import random
from typing import Tuple, Optional
from patchright.sync_api import Page, Locator
from core.config import HUMAN_CONFIG


class HumanTiming:
    """Doğal insan tepki süreleri ve rastgele sapmalı (jitter) gecikmeler."""

    @staticmethod
    def sleep_jitter(base_sec: float, jitter_pct: Optional[float] = None) -> float:
        """Belirtilen temel süreye iki yönlü rastgele sapma (jitter) ekleyerek bekler."""
        pct = jitter_pct if jitter_pct is not None else HUMAN_CONFIG["jitter_pct"]
        deviation = base_sec * pct * (random.random() * 2 - 1)
        actual_delay = max(0.04, base_sec + deviation)
        time.sleep(actual_delay)
        return actual_delay

    @staticmethod
    def reaction_time() -> float:
        """Görsel bir olayın ardından insanın tepki süresi (200 - 450 ms)."""
        delay = random.uniform(0.20, 0.45)
        time.sleep(delay)
        return delay

    @staticmethod
    def micro_pause() -> float:
        """İki mikro hareket arası göz kırpma / kısa duraksama (80 - 180 ms)."""
        delay = random.uniform(0.08, 0.18)
        time.sleep(delay)
        return delay


class HumanMouse:
    """
    Kübik Bézier eğrileri ve el titreşimi simülasyonu ile insan fare hareketleri.
    Robotik doğrusal (linear) hareketleri tamamen engeller.
    """

    @staticmethod
    def _cubic_bezier(p0: Tuple[float, float], p1: Tuple[float, float],
                      p2: Tuple[float, float], p3: Tuple[float, float], t: float) -> Tuple[float, float]:
        """Kübik Bézier formülü: B(t) = (1-t)³P0 + 3(1-t)²tP1 + 3(1-t)t²P2 + t³P3"""
        u = 1 - t
        tt = t * t
        uu = u * u
        uuu = uu * u
        ttt = tt * t

        x = uuu * p0[0] + 3 * uu * t * p1[0] + 3 * u * tt * p2[0] + ttt * p3[0]
        y = uuu * p0[1] + 3 * uu * t * p1[1] + 3 * u * tt * p2[1] + ttt * p3[1]
        return (x, y)

    @classmethod
    def move(cls, page: Page, target_x: float, target_y: float,
             start_pos: Optional[Tuple[float, float]] = None) -> Tuple[float, float]:
        """
        Fare imlecini hedef koordinata doğal kavisli bir Bézier rotasıyla götürür.
        Hızlanma (ease-in), ortada maksimum hız, hedefe yaklaşırken yavaşlama (ease-out)
        ve el titremesi (tremor) uygular.
        """
        if start_pos is None:
            # Başlangıç noktası bilinmiyorsa ekranın mantıklı bir yerinden başla
            start_x = random.randint(150, 450)
            start_y = random.randint(150, 350)
        else:
            start_x, start_y = start_pos

        p0 = (start_x, start_y)
        p3 = (target_x, target_y)

        # Mesafe hesabı
        distance = math.hypot(p3[0] - p0[0], p3[1] - p0[1])
        if distance < 3:
            return (target_x, target_y)

        # Adım sayısı mesafe ile orantılıdır
        step_divisor = HUMAN_CONFIG["mouse_step_divisor"]
        min_steps = HUMAN_CONFIG["mouse_min_steps"]
        steps = max(min_steps, int(distance / step_divisor) + random.randint(4, 10))

        # Kontrol noktalarını doğru çizginin sağına/soluna hafif bükerek insan kavisi oluştur
        ctrl_angle = math.atan2(p3[1] - p0[1], p3[0] - p0[0]) + random.choice([-1, 1]) * random.uniform(0.25, 0.75)
        offset_dist = distance * random.uniform(0.15, 0.30)

        p1 = (
            p0[0] + offset_dist * math.cos(ctrl_angle) + random.uniform(-8, 8),
            p0[1] + offset_dist * math.sin(ctrl_angle) + random.uniform(-8, 8)
        )
        p2 = (
            p3[0] - offset_dist * math.cos(ctrl_angle) + random.uniform(-8, 8),
            p3[1] - offset_dist * math.sin(ctrl_angle) + random.uniform(-8, 8)
        )

        for i in range(1, steps + 1):
            t = i / steps
            # Smoothstep (ease-in ease-out eğrisi)
            t_smooth = t * t * (3.0 - 2.0 * t)
            cur_x, cur_y = cls._cubic_bezier(p0, p1, p2, p3, t_smooth)

            # İnce el titremesi (micro-tremor: ±0.8 piksel)
            cur_x += random.uniform(-0.8, 0.8)
            cur_y += random.uniform(-0.8, 0.8)

            page.mouse.move(cur_x, cur_y)
            time.sleep(random.uniform(
                HUMAN_CONFIG["mouse_micro_delay_min"],
                HUMAN_CONFIG["mouse_micro_delay_max"]
            ))

        # Hedefe varınca kısa bekleme (dwell)
        HumanTiming.sleep_jitter(0.12, 0.25)
        return (target_x, target_y)

    @classmethod
    def click_point(cls, page: Page, x: float, y: float,
                    start_pos: Optional[Tuple[float, float]] = None) -> Tuple[float, float]:
        """Koordinata fareyi kavisle taşır, hover bekler ve doğal tıklama uygular."""
        end_pos = cls.move(page, x, y, start_pos=start_pos)
        
        # Hover bekleme süresi
        dwell = random.uniform(HUMAN_CONFIG["hover_dwell_min"], HUMAN_CONFIG["hover_dwell_max"])
        time.sleep(dwell)

        # Mouse Down -> Basılı tutma -> Mouse Up
        page.mouse.down()
        hold_time = random.uniform(HUMAN_CONFIG["click_hold_min"], HUMAN_CONFIG["click_hold_max"])
        time.sleep(hold_time)
        page.mouse.up()

        # Tıklama sonrası hafif kayma (insan eli tıklayınca birkaç piksel oynar)
        drift_x = x + random.uniform(-2.0, 2.0)
        drift_y = y + random.uniform(-2.0, 2.0)
        page.mouse.move(drift_x, drift_y)
        HumanTiming.sleep_jitter(0.15, 0.3)
        return (drift_x, drift_y)

    @classmethod
    def click_locator(cls, page: Page, locator: Locator,
                      start_pos: Optional[Tuple[float, float]] = None) -> Tuple[float, float]:
        """Belirtilen Locator öğesine insan gibi yaklaşır ve tıklar."""
        box = locator.bounding_box()
        if not box:
            locator.scroll_into_view_if_needed()
            HumanTiming.sleep_jitter(0.25)
            box = locator.bounding_box()

        if not box:
            raise RuntimeError(f"Öğenin koordinatları alınamadı: {locator}")

        # Tıklama noktasını butonun tam ortası değil, iç %60'lık alanında rastgele bir nokta yap
        target_x = box["x"] + box["width"] * random.uniform(0.25, 0.75)
        target_y = box["y"] + box["height"] * random.uniform(0.25, 0.75)

        return cls.click_point(page, target_x, target_y, start_pos=start_pos)


class HumanKeyboard:
    """İnsan gibi doğal yazım ritmi (değişken harf aralıkları ve duraksamalar)."""

    @staticmethod
    def type_text(page: Page, locator: Locator, text: str, clear_first: bool = True):
        """Metni tuş tuş, doğal hız dalgalanmalarıyla yazar."""
        locator.scroll_into_view_if_needed()
        HumanMouse.click_locator(page, locator)
        HumanTiming.sleep_jitter(0.25)

        if clear_first:
            # Mevcut içeriği temizle
            locator.fill("")
            HumanTiming.sleep_jitter(0.15)

        for i, char in enumerate(text):
            page.keyboard.type(char)

            # Özel karakterlerde (nokta, @, çizgi) insanın düşünme duraksaması
            if char in ["@", ".", "-", "_", " "]:
                pause = random.uniform(
                    HUMAN_CONFIG["typing_special_pause_min"],
                    HUMAN_CONFIG["typing_special_pause_max"]
                )
                time.sleep(pause)
            else:
                # Normal harf aralığı
                keystroke_delay = random.uniform(
                    HUMAN_CONFIG["typing_delay_min"],
                    HUMAN_CONFIG["typing_delay_max"]
                )
                # Rastgele nadir kısa takılma (typing cadence)
                if random.random() < 0.08:
                    keystroke_delay += random.uniform(0.12, 0.25)
                time.sleep(keystroke_delay)

        HumanTiming.sleep_jitter(0.2)


class HumanScroll:
    """Doğal kademeli sayfa kaydırma."""

    @staticmethod
    def scroll_smooth(page: Page, pixels: int, steps: int = 4):
        """Sayfayı tek seferde zıplatmadan parçalı ve yumuşak kaydırır."""
        step_val = pixels / steps
        for _ in range(steps):
            jittered_step = step_val * random.uniform(0.85, 1.15)
            page.evaluate(f"window.scrollBy({{ top: {jittered_step}, behavior: 'smooth' }});")
            time.sleep(random.uniform(0.15, 0.30))
        HumanTiming.sleep_jitter(0.4)
