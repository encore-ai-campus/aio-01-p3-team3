"""시연용 가짜 CCTV 이미지 만들기 — 해든

[변경 기록]
2026-10-08 해든: 새 파일. 기화 님 실제 이미지가 오기 전까지 4단계(CCTV 비전 LLM 실제 호출)를 시험하려고 만듦.
  Pillow로 방·가구·사람 모양을 그려 CCTV처럼(흑백, 노이즈, 시간 표시) 저장한다. 실제 사진이 오면 같은 이름으로 바꾸면 됨.
2026-10-08 해든 (실제 점검 뒤): floor_sitting은 사람이 소파와 겹쳐 "소파에 앉음"으로 읽혀서 거실 바닥 한가운데로 옮기고,
  정답을 낙상 의심 true로 정함 (혼자 못 일어나는 상황일 수 있음).
2026-10-08 해든 (시연 시나리오 확정안): lying.jpg를 확정안 4-2 장면대로 "소파에 누워 움직임 없음"으로 바꿈 (예전: 침대).

실행 (저장소 맨 위 폴더에서):
    pip install pillow
    python notes/make_fake_cctv.py        → mcp_server/assets/cctv/*.jpg

이미지별 정답(기대하는 비전 LLM 결과)은 EXPECTED. notes/cctv_check.py가 이 값과 비교한다.
"""

import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "mcp_server" / "assets" / "cctv"
W, H = 640, 480

# 파일 → (장면 설명, 기대 posture, person_visible, fall_suspected 기대, 비고)
EXPECTED = {
    "normal.jpg":        ("거실 소파에 앉아 있음 (확정안 normal·heat)", "sitting", True, False, ""),
    "kitchen_empty.jpg": ("주방에 사람 없음, 인덕션 켜짐 (확정안 induction)", "none", False, False, ""),
    "fall.jpg":          ("거실 바닥에 쓰러져 있음 (확정안 fall)", "fallen", True, True, ""),
    "lying.jpg":         ("소파에 누워 움직임 없음 (확정안 critical)", "lying", True, False, ""),
    "standing.jpg":      ("거실에 서 있음", "standing", True, False, ""),
    "floor_sitting.jpg": ("거실 바닥 한가운데 주저앉아 있음", "sitting", True, True, "바닥에 앉음 → 낙상 의심(확인 필요)"),
    "dark_bathroom.jpg": ("어둡고 흐린 화장실 앞 바닥에 사람 형체", "fallen", True, True, "confidence low 기대"),
    "empty_living.jpg":  ("거실에 사람 없음", "none", False, False, ""),
}

SKIN, CLOTH, PANTS, HAIR = (215, 185, 165), (225, 225, 230), (35, 35, 45), (200, 200, 200)   # 흑백에서 잘 보이게 밝은 윗옷·어두운 바지


def font(size):
    for name in ("DejaVuSansMono.ttf", "consola.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def room(d, wall=(170, 165, 150), floor=(120, 100, 80)):
    """천장 모서리에 단 CCTV 시점: 뒤 벽 + 원근 바닥."""
    d.rectangle([0, 0, W, H], fill=wall)
    d.polygon([(0, H), (W, H), (W - 90, 250), (90, 250)], fill=floor)
    d.line([(90, 250), (0, 0)], fill=(140, 135, 120), width=3)
    d.line([(W - 90, 250), (W, 0)], fill=(140, 135, 120), width=3)
    d.line([(90, 250), (W - 90, 250)], fill=(100, 90, 75), width=3)
    for x in range(120, W - 90, 70):             # 마루 무늬
        d.line([(x, 250), (x - 60 + (x - W / 2) * 0.6, H)], fill=(110, 92, 74), width=1)


def sofa(d, x=330, y=200):
    d.rounded_rectangle([x, y, x + 230, y + 70], 12, fill=(110, 75, 60))           # 등받이
    d.rounded_rectangle([x - 10, y + 55, x + 240, y + 110], 12, fill=(125, 85, 68))  # 앉는 곳
    d.rectangle([x - 20, y + 40, x + 10, y + 115], fill=(100, 68, 55))
    d.rectangle([x + 220, y + 40, x + 250, y + 115], fill=(100, 68, 55))


def bed(d):
    d.rectangle([150, 190, 520, 330], fill=(150, 155, 165))      # 매트리스 (흰 윗옷과 구분되게 회색)
    d.rectangle([140, 150, 165, 340], fill=(110, 80, 60))         # 머리판
    d.rectangle([180, 205, 250, 245], fill=(235, 235, 240))      # 베개
    d.rectangle([150, 330, 520, 345], fill=(110, 80, 60))


def tv_and_table(d):
    d.rectangle([120, 120, 250, 200], fill=(30, 30, 35))
    d.rectangle([110, 200, 260, 250], fill=(95, 70, 55))
    d.ellipse([230, 330, 380, 380], fill=(105, 78, 60))


def kitchen(d, induction_on=True):
    d.rectangle([60, 170, 580, 290], fill=(190, 190, 185))       # 조리대
    d.rectangle([60, 160, 580, 175], fill=(150, 150, 145))
    d.rectangle([60, 60, 580, 140], fill=(160, 150, 130))        # 찬장
    for x in range(60, 580, 104):
        d.rectangle([x + 4, 64, x + 100, 136], outline=(130, 120, 100), width=2)
    d.rectangle([250, 172, 450, 230], fill=(25, 25, 28))         # 인덕션
    for cx in (300, 400):
        color = (230, 60, 30) if induction_on else (60, 60, 60)
        d.ellipse([cx - 32, 180, cx + 32, 222], outline=color, width=5)
    d.ellipse([370, 160, 430, 190], fill=(140, 140, 150))         # 냄비
    d.rectangle([475, 175, 560, 285], outline=(120, 120, 115), width=2)


def limb(d, a, b, w, color):
    d.line([a, b], fill=color, width=w)
    r = w // 2
    d.ellipse([b[0] - r, b[1] - r, b[0] + r, b[1] + r], fill=color)


def person_standing(d, x, y, s=1.0):
    head = (x, y)
    d.ellipse([x - 16 * s, y - 18 * s, x + 16 * s, y + 18 * s], fill=SKIN)
    d.chord([x - 16 * s, y - 20 * s, x + 16 * s, y + 6 * s], 180, 360, fill=HAIR)
    d.rounded_rectangle([x - 24 * s, y + 20 * s, x + 24 * s, y + 100 * s], 10, fill=CLOTH)
    limb(d, (x - 22 * s, y + 28 * s), (x - 34 * s, y + 95 * s), int(14 * s), CLOTH)
    limb(d, (x + 22 * s, y + 28 * s), (x + 34 * s, y + 95 * s), int(14 * s), CLOTH)
    limb(d, (x - 12 * s, y + 98 * s), (x - 14 * s, y + 185 * s), int(18 * s), PANTS)
    limb(d, (x + 12 * s, y + 98 * s), (x + 14 * s, y + 185 * s), int(18 * s), PANTS)
    return head


def person_sitting(d, x, y, s=1.0):
    """소파에 앉은 자세: 상체는 등받이 앞, 무릎이 앞으로 나오고 정강이는 바닥으로."""
    d.ellipse([x - 16 * s, y - 18 * s, x + 16 * s, y + 18 * s], fill=SKIN)
    d.chord([x - 16 * s, y - 20 * s, x + 16 * s, y + 6 * s], 180, 360, fill=HAIR)
    d.rounded_rectangle([x - 24 * s, y + 20 * s, x + 24 * s, y + 80 * s], 10, fill=CLOTH)
    limb(d, (x - 22 * s, y + 30 * s), (x - 30 * s, y + 78 * s), int(13 * s), CLOTH)
    limb(d, (x + 22 * s, y + 30 * s), (x + 30 * s, y + 78 * s), int(13 * s), CLOTH)
    d.rounded_rectangle([x - 28 * s, y + 72 * s, x + 28 * s, y + 100 * s], 8, fill=PANTS)   # 허벅지 (앞으로)
    limb(d, (x - 16 * s, y + 98 * s), (x - 18 * s, y + 140 * s), int(16 * s), PANTS)
    limb(d, (x + 16 * s, y + 98 * s), (x + 18 * s, y + 140 * s), int(16 * s), PANTS)


def person_lying(d, x, y, s=1.0, sprawled=False):
    """옆으로 누운 몸. sprawled면 팔다리가 벌어진 쓰러진 자세."""
    d.ellipse([x - 18 * s, y - 16 * s, x + 18 * s, y + 16 * s], fill=SKIN)
    d.chord([x - 20 * s, y - 16 * s, x + 4 * s, y + 16 * s], 90, 270, fill=HAIR)
    d.rounded_rectangle([x + 18 * s, y - 22 * s, x + 110 * s, y + 22 * s], 10, fill=CLOTH)
    if sprawled:
        limb(d, (x + 30 * s, y - 15 * s), (x + 10 * s, y - 70 * s), int(14 * s), CLOTH)    # 팔이 머리 위로
        limb(d, (x + 60 * s, y + 18 * s), (x + 70 * s, y + 65 * s), int(14 * s), CLOTH)
        limb(d, (x + 108 * s, y - 10 * s), (x + 195 * s, y - 40 * s), int(18 * s), PANTS)
        limb(d, (x + 108 * s, y + 10 * s), (x + 190 * s, y + 45 * s), int(18 * s), PANTS)
    else:
        limb(d, (x + 30 * s, y + 10 * s), (x + 95 * s, y + 18 * s), int(13 * s), CLOTH)
        limb(d, (x + 108 * s, y - 8 * s), (x + 200 * s, y - 6 * s), int(18 * s), PANTS)
        limb(d, (x + 108 * s, y + 8 * s), (x + 200 * s, y + 10 * s), int(18 * s), PANTS)


def floor_sit(d, x, y):
    """바닥에 주저앉아 소파에 기댄 자세 (다리를 앞으로 뻗음)."""
    d.ellipse([x - 16, y - 18, x + 16, y + 18], fill=SKIN)
    d.chord([x - 16, y - 20, x + 16, y + 6], 180, 360, fill=HAIR)
    d.rounded_rectangle([x - 24, y + 20, x + 24, y + 85], 10, fill=CLOTH)
    limb(d, (x - 22, y + 30), (x - 40, y + 80), 14, CLOTH)
    limb(d, (x + 22, y + 30), (x + 40, y + 80), 14, CLOTH)
    limb(d, (x - 10, y + 82), (x - 60, y + 150), 18, PANTS)
    limb(d, (x + 10, y + 82), (x + 30, y + 155), 18, PANTS)


def cctv_finish(img, cam, when, dark=False, blur=0):
    """흑백·노이즈·어안 느낌·시간 표시."""
    img = img.convert("L")
    if dark:
        img = img.point(lambda v: int(v * 0.28))
    if blur:
        img = img.filter(ImageFilter.GaussianBlur(blur))
    rnd = random.Random(cam + when)
    px = img.load()
    for _ in range(W * H // 6):
        x, y = rnd.randrange(W), rnd.randrange(H)
        px[x, y] = max(0, min(255, px[x, y] + rnd.randint(-28, 28)))
    img = img.convert("RGB")
    d = ImageDraw.Draw(img)
    f = font(16)
    d.rectangle([0, 0, W, 24], fill=(0, 0, 0))
    d.text((8, 4), f"{cam}   {when}", fill=(235, 235, 235), font=f)
    d.text((W - 60, 4), "● REC", fill=(220, 40, 40), font=f)
    # 가장자리 어둡게 (렌즈 비네팅)
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).ellipse([-120, -100, W + 120, H + 100], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(60))
    return Image.composite(img, Image.new("RGB", (W, H), (10, 10, 10)), mask)


def scene(name):
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    if name == "kitchen_empty.jpg":
        room(d, wall=(185, 180, 170), floor=(150, 140, 125))
        kitchen(d)
        return cctv_finish(img, "CAM 02 KITCHEN", "2026-10-08 14:05:12")
    if name == "dark_bathroom.jpg":
        room(d, wall=(160, 165, 170), floor=(140, 145, 150))
        d.rectangle([380, 60, 520, 250], fill=(120, 110, 95))      # 화장실 문
        d.ellipse([495, 150, 507, 162], fill=(200, 190, 150))
        person_lying(d, 200, 360, 0.9, sprawled=True)
        return cctv_finish(img, "CAM 04 HALL", "2026-10-08 03:22:08", dark=True, blur=3)

    room(d)
    tv_and_table(d)
    sofa(d)
    if name == "normal.jpg":
        person_sitting(d, 440, 190)
    elif name == "standing.jpg":
        person_standing(d, 300, 170)
    elif name == "fall.jpg":
        person_lying(d, 200, 400, 1.0, sprawled=True)
    elif name == "lying.jpg":
        person_lying(d, 338, 262, 0.95)    # 소파 앉는 곳 위에 누움 (머리는 왼쪽 팔걸이 쪽)
    elif name == "floor_sitting.jpg":
        floor_sit(d, 230, 290)       # 소파에서 떨어진 거실 한가운데 바닥 (10/8: 소파 앞에 두니 소파에 앉은 것으로 봄)
    return cctv_finish(img, "CAM 01 LIVING", "2026-10-08 14:32:10")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (desc, *_rest) in EXPECTED.items():
        scene(name).save(OUT / name, quality=85)
        print(f"{OUT.relative_to(ROOT) / name}  {desc}")


if __name__ == "__main__":
    main()
