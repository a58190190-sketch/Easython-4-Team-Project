# Easython-4-Team-Project
## 1. 이지톤 대회 주제
- AI를 활용한 사회적 문제해결 
## 2. 사용언어
- python
<<<<<<< Updated upstream
## 3. 우리팀 주제
- 기후위기 대처를 위한 분리수거 보조 소프트웨어/디지털 격차 해소를 위한 웹사이트 이용 가이드 생성 소프트웨어
=======

## 3. 실천 플래너 MVP 실행하기

Streamlit 앱의 첫 화면은 Gemini API를 연동한 재활용 도우미입니다. 카메라로 촬영하거나
사진 파일을 업로드하면 AI가 품목과 분리배출 방법을 한국어로 제안합니다.
실천 플래너 탭에서는 텀블러 사용, 대중교통 이용, 플로깅의 오늘 기록과 주간 집계,
월간 캘린더를 확인할 수 있습니다. 하나 이상 실천한 날은 새싹(🌱), 세 가지 모두 실천한 날은 꽃(🌸)으로 표시합니다.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
streamlit run Src/main.py
```

Gemini API 키는 [Google AI Studio](https://aistudio.google.com/apikey)에서 발급한 뒤,
앱을 실행하는 PowerShell 창에서 환경 변수로 설정하세요. 키를 코드나 저장소에 올리지 마세요.

```powershell
$env:GEMINI_API_KEY = "발급받은_API_키"
streamlit run Src/main.py
```

사진 분석 시 업로드한 이미지가 Gemini API로 전송됩니다. AI 결과는 참고 안내이며,
품목 상태와 거주 지역에 따라 배출 기준이 다를 수 있으니 지자체 안내를 확인해야 합니다.

기록은 `Src/planner_data.json`에 저장됩니다. 이 첫 버전은 실행 환경의 로컬 파일을
사용하므로, 배포 후 여러 사용자가 함께 쓰는 기능에는 데이터베이스가 필요합니다.
>>>>>>> Stashed changes
