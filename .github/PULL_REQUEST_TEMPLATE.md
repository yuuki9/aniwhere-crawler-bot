# 요약

<!-- 한 줄 요약 (예: feat(api): 검색 guardrails 적용 / ci(deploy): bastion 배포 검증 추가) -->

## 변경 범위

해당하는 항목만 체크.

- [ ] `app/` — FastAPI, 라우트, 설정, 서비스(RAG·Chroma·크롤·DB 등)
- [ ] 파이프라인 — 루트 `run_pipeline.py`, `process_shops.py`, `retry_failed.py`, `embed_to_chromadb.py` 등
- [ ] `scripts/` — 마이그레이션, DB 연결 점검 등
- [ ] 컨테이너 — `Dockerfile`, `docker-compose*.yml`
- [ ] CI/CD — `.github/workflows/` (`ci.yml`, `deploy-ec2.yml` 등)
- [ ] 문서 — `README.md`, `GIT_CONVENTIONS.md` 등

## 맥락 / 배경 (선택)

<!-- 왜 하는지. 이슈·채팅 링크 -->

## 확인한 것

- [ ] 로컬 또는 CI에서 변경 부분 검증함 (`docker build`, API 호출 등 — 이 레포에 맞게)
- [ ] API/DTO 변경 시 Swagger(OpenAPI)와 맞춤
- [ ] MySQL/`scripts/` 스키마 변경 시 롤백·재실행 방법 없음 또는 PR 본문에 적음
- [ ] 배포 워크플로·Chroma·시크릿 관련 수정 시 bastion/Chroma/GitHub Secrets 영향 검토함

## 스크린샷 / 로그 (선택)

<!-- 응답 예시, Actions 로그, 파이프라인 출력 등 -->

## 머지 후

- [ ] `main` 머지 시 변경 파일에 따라 **Deploy to bastion** 등이 돌아갈 수 있음 → 공지·시크릿·DB 순서 필요하면 기재
- [ ] 기타 후속 작업 없음 또는: <!-- 설명 -->

<!--
브랜치·커밋 규칙: GIT_CONVENTIONS.md 참고 (feature/*, fix/*, chore/*, type(scope): …)
-->
