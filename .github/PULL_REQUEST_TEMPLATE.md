# 요약

<!-- 한 줄. 커밋과 맞추면 좋음: type(scope): 한글 설명 (scope 예: app, pipeline, scripts, deploy, ci, docs — GIT_CONVENTIONS.md) -->

## 변경 범위

<!-- 단일 FastAPI 앱 + 루트 파이프라인 스크립트 기준. 해당하는 경로만 [x] -->

해당하는 항목만 체크.

- [ ] `app/` — FastAPI, 라우트, 설정, 서비스(RAG·Chroma·크롤·DB 등)
- [ ] 파이프라인 — 루트 `run_pipeline.py`, `process_shops.py`, `retry_failed.py`, `embed_to_chromadb.py` 등
- [ ] `scripts/` — 마이그레이션, DB 연결 점검 등
- [ ] 컨테이너 — `Dockerfile`, `docker-compose*.yml`
- [ ] CI/CD — `.github/workflows/` (`ci.yml`, `deploy-ec2.yml` 등)
- [ ] 문서 — `README.md`, `GIT_CONVENTIONS.md`, `.github/PULL_REQUEST_TEMPLATE.md` 등

## 맥락 / 배경 (선택)

<!-- 왜 필요한지. 이슈·슬랙·노션 링크. 없으면 섹션 통째로 비워도 됨 -->

## 확인한 것

<!-- 해당 체크만 [x]. 직접 검증한 내용이 있으면 한 줄로 덧붙여도 됨 (예: docker build 통과, GET /api/v1/search 200) -->

- [ ] 로컬 또는 CI에서 변경 부분 검증함 (`docker build`, API 호출 등 — 이 레포에 맞게)
- [ ] API/DTO 변경 시 Swagger(OpenAPI)와 맞춤
- [ ] MySQL/`scripts/` 스키마 변경 시 롤백·재실행 방법 없음 또는 PR 본문에 적음
- [ ] 배포 워크플로·Chroma·시크릿 관련 수정 시 EC_HOST/Chroma/GitHub Secrets 영향 검토함

## 스크린샷 / 로그 (선택)

<!-- API 응답 JSON 일부, GitHub Actions 로그, 파이프라인 콘솔 출력 등. 없으면 섹션 삭제 가능 -->

## 머지 후

<!-- main 머지 시 deploy-ec2.yml path 필터에 걸리면 EC2 배포가 돌 수 있음. 시크릿(EC_HOST, EC2_PRIVATE_IP 등)·DB 순서·공지 필요 여부를 여기에 -->

- [ ] `main` 머지 시 변경 파일에 따라 **Deploy to EC2** 등이 돌아갈 수 있음 → 공지·시크릿·DB 순서 필요하면 기재
- [ ] 기타 후속 작업 없음

<!-- 후속 작업이 있으면 위 항목 체크 해제 후 아래에 나열 (예: 수동 compose 재기동, Chroma tarball 재업로드) -->

<!--
브랜치: feature/*, fix/*, chore/* (통일 규칙은 GIT_CONVENTIONS.md)
-->
