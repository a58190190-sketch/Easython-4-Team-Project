# Easython MVP Python 의존성

> 기본 모델은 `z-ai/glm-5.3-flash`입니다. 로컬 모델 다운로드는 하지 않습니다.

## 필수 라이브러리

| 라이브러리 | 용도 |
|---|---|
| `keyring` | NVIDIA NIM API 키를 Windows 자격 증명 저장소에 보관 |
| `opencv-python` | 브라우저 화면 캡처를 로컬에서 디코딩하고 윤곽/화면 영역 후보를 계산 |

## Python 표준 라이브러리

| 구성 요소 | 용도 |
|---|---|
| `tkinter` | 데스크톱 창과 채팅 UI |
| `http.server` | Chrome 확장 프로그램에서 로컬 페이지 데이터를 받는 서버 |
| `urllib.request` | NVIDIA NIM API 통신 |
| `html.parser` | 버튼·링크·입력 UI 요소 추출 |
| `json`, `threading`, `queue` 등 | 데이터 처리 및 백그라운드 요청 |

`install.bat`이 `requirements.txt`에 따라 라이브러리를 설치한 뒤 검증합니다. `run.bat`과 `app.py` 직접 실행도 같은 파일의 모든 패키지 이름과 버전 조건을 확인하며, 새 의존성을 추가하면 자동으로 누락/버전 불일치 목록에 포함합니다. API 요청은 NVIDIA NIM Chat Completions 엔드포인트를 사용합니다. 화면 이미지 자체는 NIM API로 보내지 않습니다.

현재 페이지의 HTML 크기와 추출한 UI 요소 수를 보고 요청 토큰량을 추정합니다. 세션 안에서 분당 최대 6회와 추정 20,000 토큰을 앱 내부 목표로 삼고, 큰 페이지일수록 더 길게 간격을 둡니다. 이는 NVIDIA가 보장한 계정별 한도가 아니며 추정 기반 보호 장치입니다. NIM이 429를 반환하면 앱이 최대 3회까지 대기 후 재시도합니다.


