---
name: daily-git-report
description: 일일 git 활동 내역을 목록으로 만들어 지정된 폴더에 저장하는 스킬입니다.
version: 1.0.0
---

# 일일 Git 리포트 생성 스킬 (Daily Git Report Skill)

이 스킬은 사용자의 하루 동안의 git 활동을 자동으로 수집하여 Markdown 파일로 기록하는 기능을 제공합니다.

## 주요 기능
- 현재 날짜에 이루어진 모든 git 커밋 내역 추출.
- `git add` 된 변경사항(Staged) 및 수정 중인 파일(Unstaged) 내역 포함.
- 깔끔한 Markdown 리스트 형식으로 포맷팅.
- `agent-middleware/outputs/daily-git-report/YYYY-MM-DD.md` 경로에 자동 저장.

## 사용 방법
아래 스크립트를 실행하여 오늘의 리포트를 생성할 수 있습니다:
```bash
python3 scripts/generate_report.py
```

## 구조
- `scripts/generate_report.py`: git 로그 추출 및 파일 저장을 담당하는 핵심 로직.
- `examples/`: 생성된 리포트의 예시 포맷 제공.
