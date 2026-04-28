# Git 컨벤션

브랜치 · 커밋 · 태그 규칙을 통일해 리뷰와 배포(EC2 포함)를 단순하게 만듭니다.  
커밋 제목은 `type(scope): 설명` 형식을 씁니다. **이 저장소는 단일 Python 프로젝트**이며, `client/`·`server/` 같은 모노레포 폴더 구분은 없습니다.

## 이 저장소 구조 요약

| 경로 · 구분 | 역할 |
|-------------|------|
| `app/` | FastAPI 앱 (`app/api`, `app/core`, `app/services`): 검색 API, RAG, Chroma 접근 등 |
| 루트 파이프라인 | `run_pipeline.py`, `process_shops.py`, `retry_failed.py`, `embed_to_chromadb.py` — CSV·크롤·정제·DB/Chroma 연동 |
| `scripts/` | DB 연결 확인, 마이그레이션·스키마 패치 등 보조 스크립트 |
| `Dockerfile`, `docker-compose*.yml` | 컨테이너·로컬/EC2 실행 |
| `.github/workflows/` | CI, EC2 배포 파이프라인 |

## 브랜치 전략

| 브랜치 | 목적 | 설명 |
|--------|------|------|
| `main` | 배포 기준 최신 | `main` 머지 후 GitHub Actions로 EC2 배포가 돌도록 설정되어 있음(워크플로 확인) |
| `feature/*` | 기능 개발 | 예: `feature/rag-threshold-env` |
| `fix/*` | 버그 수정 | 예: `fix/health-check-chroma` |
| `chore/*` | 설정·문서·CI만 | 예: `chore/ci-pr-template` |

팀에서 `develop`을 쓰기로 했다면 그 위에서 브랜치를 만들고 PR은 합의된 기본 브랜치로 열면 됩니다.

### 네이밍 예시

- 기능: `feature/pipeline-update-existing-flag`, `feature/search-query-guard`
- 수정: `fix/db-save-duplicate-shop`
- 잡무: `chore(deploy): compose 포트 설명 추가`

작업 브랜치는 `feature/*`, `fix/*`, `chore/*` 중 하나로 통일합니다.

## 커밋 메시지

### 언어

- **커밋 로그(제목·본문)는 한글을 사용합니다.** PR 설명도 동일하게 맞추는 것을 권장합니다.
- `feat`, `fix`, `app` 같은 **타입·scope는 영어**로 두고, 콜론 뒤 **설명은 한글**로 씁니다.

### 형식

```
type(scope): 짧은 설명 (한 줄)
```

- **scope**: 아래 목록 중 **변경 영역과 가장 가까운 하나**를 택합니다. 애매하면 `repo`(저장소 전반·설정) 또는 생략 대신 명확한 단어 하나만 씁니다.
- 본문이 필요하면 한 줄 띄우고 무엇을·왜 했는지 보강합니다.

### scope 가이드 (이 프로젝트 기준)

| scope | 넣으면 되는 변경 |
|--------|------------------|
| `app` | `app/` 패키지: API 라우트, `config`, 서비스(RAG·DB·Chroma ingest 등) |
| `pipeline` | 루트 파이프라인 스크립트만 다룰 때 (`run_pipeline.py`, `process_shops.py`, `retry_failed.py`, `embed_to_chromadb.py` 및 직접 연동 로직) |
| `scripts` | `scripts/` 아래 헬스체크·마이그레이션·패치 등 |
| `deploy` | `Dockerfile`, `docker-compose*.yml`, `.dockerignore` |
| `ci` | `.github/workflows/` — CI·배포 워크플로 |
| `docs` | `README.md`, 프로젝트 문서만 |
| `repo` | 루트 규칙 파일(`.coderabbit.yaml` 등)·PR 템플릿·`.gitignore` 등 코드 밖 저장소 설정 |

두 영역 이상 크게 건드리면 scope는 **가장 핵심인 하나**를 쓰거나 제목 한 줄로 요약 가능하면 `repo` 또는 `app` 하나로 묶어도 됩니다.

### 실제 로그 예시

- `feat(app): 검색 API에 거리 필터 추가`
- `fix(pipeline): --update-existing 시 Chroma 업서트 건너뛰는 문제 수정`
- `chore(deploy): EC2 compose에 output 볼륨 설명 추가`
- `ci: main 푸시 시 테스트 워크플로 트리거 범위 조정`

### type

| 타입 | 의미 |
|------|------|
| `feat` | 새 기능 |
| `fix` | 버그 수정 |
| `docs` | 문서만 |
| `style` | 포맷 등 (동작 변화 없음) |
| `refactor` | 리팩터링 (동작 유지) |
| `test` | 테스트 추가·수정 |
| `chore` | 빌드·설정·잡무 (scope로 구체화) |

## 권장 워크플로

1. `main`(또는 팀의 기본 브랜치)에서 작업 브랜치 생성  
2. 위 컨벤션에 맞게 커밋  
3. PR로 리뷰(CodeRabbit·사람 리뷰)  
4. 머지 후 배포 워크플로가 있다면 통과 확인

## 버전 태그 (`v*`)

- **릴리스 지점**에만 `v1.0.0`처럼 태그합니다. 매 커밋마다 태그할 필요는 없습니다.
- 이미 원격에 올린 태그는 무심코 지우면 clone·CI가 깨질 수 있습니다.

## 참고

- PR은 `.github/PULL_REQUEST_TEMPLATE.md`를 채워 올립니다.
