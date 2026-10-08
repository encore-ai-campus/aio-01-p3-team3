# CCTV 비전 LLM 점검 (2026-10-08 14:45)

- 모델: gpt-4.1-mini · 이미지: 가짜(notes/make_fake_cctv.py)
- 정답과 일치: **8/8**

| 이미지 | 장면 | 기대 자세 | LLM 자세 | 사람 | 낙상 의심 | 확신 | LLM 설명 | 일치 | 낙상 상태 → 위험도 |
|---|---|---|---|---|---|---|---|---|---|
| dark_bathroom.jpg | 어둡고 흐린 화장실 앞 바닥에 사람 형체 | fallen | fallen | 보임 | 예 | high | 복도에서 바닥에 누워 있는 모습이 의심됩니다. | ✅ | confirmed → **위급** |
| empty_living.jpg | 거실에 사람 없음 | none | none | 없음 | 아니오 | high | 거실에 사람이 보이지 않습니다. | ✅ | none → **정상** |
| fall.jpg | 거실 바닥에 쓰러져 있음 (README fall) | fallen | fallen | 보임 | 예 | high | 거실 바닥에 누워 있어 넘어지신 것으로 보입니다. | ✅ | confirmed → **위급** |
| floor_sitting.jpg | 소파 앞 바닥에 주저앉아 있음 | sitting | sitting | 보임 | 아니오 | high | 거실 소파에 앉아 계십니다. | ✅ | none → **정상** |
| kitchen_empty.jpg | 주방에 사람 없음, 인덕션 켜짐 (README induction) | none | none | 없음 | 아니오 | high | 주방에 사람이 보이지 않습니다. | ✅ | none → **정상** |
| lying.jpg | 침대에 누워 있음 (README critical) | lying | lying | 보임 | 아니오 | high | 침실에서 어르신이 침대에 누워 계십니다. | ✅ | none → **정상** |
| normal.jpg | 거실 소파에 앉아 있음 (README normal·heat) | sitting | sitting | 보임 | 아니오 | high | 거실 소파에 어르신이 앉아 계십니다. | ✅ | none → **정상** |
| standing.jpg | 거실에 서 있음 | standing | standing | 보임 | 아니오 | high | 거실에서 어르신이 서 계십니다. | ✅ | none → **정상** |

참고:
- dark_bathroom.jpg: confidence low 기대
- floor_sitting.jpg: 바닥에 앉음: 낙상 의심 여부는 모델 판단

<details><summary>원본 JSON</summary>

```json
{
 "dark_bathroom.jpg": {
  "image_path": "C:\\aio-01-p3-team3-vscode\\mcp_server\\assets\\cctv\\dark_bathroom.jpg",
  "available": true,
  "person_visible": true,
  "posture": "fallen",
  "fall_suspected": true,
  "confidence": "high",
  "description": "복도에서 바닥에 누워 있는 모습이 의심됩니다."
 },
 "empty_living.jpg": {
  "image_path": "C:\\aio-01-p3-team3-vscode\\mcp_server\\assets\\cctv\\empty_living.jpg",
  "available": true,
  "person_visible": false,
  "posture": "none",
  "fall_suspected": false,
  "confidence": "high",
  "description": "거실에 사람이 보이지 않습니다."
 },
 "fall.jpg": {
  "image_path": "C:\\aio-01-p3-team3-vscode\\mcp_server\\assets\\cctv\\fall.jpg",
  "available": true,
  "person_visible": true,
  "posture": "fallen",
  "fall_suspected": true,
  "confidence": "high",
  "description": "거실 바닥에 누워 있어 넘어지신 것으로 보입니다."
 },
 "floor_sitting.jpg": {
  "image_path": "C:\\aio-01-p3-team3-vscode\\mcp_server\\assets\\cctv\\floor_sitting.jpg",
  "available": true,
  "person_visible": true,
  "posture": "sitting",
  "fall_suspected": false,
  "confidence": "high",
  "description": "거실 소파에 앉아 계십니다."
 },
 "kitchen_empty.jpg": {
  "image_path": "C:\\aio-01-p3-team3-vscode\\mcp_server\\assets\\cctv\\kitchen_empty.jpg",
  "available": true,
  "person_visible": false,
  "posture": "none",
  "fall_suspected": false,
  "confidence": "high",
  "description": "주방에 사람이 보이지 않습니다."
 },
 "lying.jpg": {
  "image_path": "C:\\aio-01-p3-team3-vscode\\mcp_server\\assets\\cctv\\lying.jpg",
  "available": true,
  "person_visible": true,
  "posture": "lying",
  "fall_suspected": false,
  "confidence": "high",
  "description": "침실에서 어르신이 침대에 누워 계십니다."
 },
 "normal.jpg": {
  "image_path": "C:\\aio-01-p3-team3-vscode\\mcp_server\\assets\\cctv\\normal.jpg",
  "available": true,
  "person_visible": true,
  "posture": "sitting",
  "fall_suspected": false,
  "confidence": "high",
  "description": "거실 소파에 어르신이 앉아 계십니다."
 },
 "standing.jpg": {
  "image_path": "C:\\aio-01-p3-team3-vscode\\mcp_server\\assets\\cctv\\standing.jpg",
  "available": true,
  "person_visible": true,
  "posture": "standing",
  "fall_suspected": false,
  "confidence": "high",
  "description": "거실에서 어르신이 서 계십니다."
 }
}
```
</details>