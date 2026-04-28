# 요약

<!-- 한 줄로 무엇을 바꾸는지 (예: feat(app): 검색 시 guardrails 적용) -->

## 변경 범위

<!-- 해당되는 항목만 체크 -->

- [ ] `app/` (FastAPI, RAG·Chroma·DB 등)
- [ ] 파이프라인 (루트: `run_pipeline.py`, `process_shops.py`, `retry_failed.py`, `embed_to_chromadb.py` 등)
- [ ] `scripts/` (마이그레이션·연결 확인 등)
- [ ] 배포·컨테이너 (`Dockerfile`, `docker-compose*.yml`)
- [ ] CI·워크플로 (`.github/workflows/`)
- [ ] 문서만 (`README`, `GIT_CONVENTIONS` 등)

## 맥락 / 배경 (선택)

<!-- 왜 필요한지. 이슈·슬랙 링크가 있으면 -->

## 확인한 것

<!-- 해당되는 항목만 -->

- [ ] 로컬에서 필요한 테스트·스クリプト 실행 또는 API 수동 확인
- [ ] FastAPI 라우트·요청·응답 스키마 변경 시 Swagger(`OpenAPI`)와 맞춤
- [ ] MySQL 스키마·마이그레이션·`scripts/` 스크립트 영향 시 롤백·재실행 방법 적음 또는 PR에 명시
- [ ] 파이프라인·Chroma·배포(`deploy-ec2.yml`) 관련 변경 시 EC2/Chroma 산출물·시크릿 영향 검토함

## 스크린샷 / 로그 (선택)

<!-- API 응답 예시, 파이프라인 로그 일부 등 -->

## 머지 후

<!-- `main` 머지 후 자동 배포가 있다면: 운영 공지 필요 여부, DB 마이그레이션 순서 등 -->

---

<!--
브랜치: feature/*, fix/*, chore/*
커밋·scope: GIT_CONVENTIONS.md 의 예시(app · pipeline · scripts · deploy · ci · docs · repo)
-->
