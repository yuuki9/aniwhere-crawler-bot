"""검색 쿼리 입력 가드레일 (차단 키워드·길이).

부분 문자열 매치이므로 짧은 단어·애니 맥락과 겹치기 쉬운 항목은 제외한다.
매칭 순서: 긴 키워드를 먼저 검사해 (예: javascript 안의 script 오탐 방지).
"""

from fastapi import HTTPException

# q_lower = query.lower() 후 부분 문자열 검사
BLOCKED_KEYWORDS: list[str] = [
    # 정치·거버넌스·시사 논쟁 유도
    "국정감사", "국무총리", "선거", "시의원", "도의원", "민주당", "국민의힘",
    "정당", "국회", "대통령", "탄핵", "여당", "야당",
    "북핵", "외교", "국방", "의원",
    "정치", "정부", "행정부", "입법",
    # 종교·교리 (교회/스님 등은 작품 배경 질문과 겹아 제외 → LLM 프롬프트에서 처리)
    "힌두교", "카톨릭", "천주교", "개신교", "유대교",
    "이슬람", "기독교", "불교", "종교",
    "기도문", "코란", "성경",
    # 성인·음란 ("성인용 피규어" 등은 막지 않기 위해 성인·야한 제외)
    "포르노", "야동", "섹스", "자위", "노모",
    # 법률 자문
    "법률자문", "민사소송", "변호사", "고발",
    "소송", "고소",
    # 금융
    "선물옵션", "주식투자", "펀드추천", "코인시세",
    "암호화폐", "도지코인", "이더리움", "비트코인",
    # 개발·IT (짧은 java 등은 제외 — 자바스크립트 오탐)
    "stackoverflow", "타입스크립트", "자바스크립트",
    "프로그래밍", "typescript", "javascript",
    "리트코드", "깃허브", "파이썬", "코딩",
    "leetcode", "python", "golang",
    # 날씨
    "기상예보", "기상청", "태풍경로", "미세먼지", "황사", "날씨",
    # 부동산
    "전세금", "재개발", "부동산", "분양",
    # 일상·건강
    "칼로리계산", "다이어트식단", "요리법", "레시피",
    # 과제 대행
    "논문대행", "claude.ai", "openai", "챗지피티", "chatgpt",
]

# API 노출 메시지 (100자 미만 유지)
STEERING_DETAIL = "애니·만화·캐릭터·굿즈·가챠·매장·작품만 질문해 주세요."


def validate_query(query: str) -> None:
    q = query.strip()
    if len(q) < 2:
        raise HTTPException(400, "2자 이상 입력해 주세요.")
    if len(q) >= 100:
        raise HTTPException(400, "검색어는 99자 미만으로 입력해 주세요.")
    q_lower = query.lower()
    for keyword in sorted(BLOCKED_KEYWORDS, key=len, reverse=True):
        if keyword in q_lower:
            raise HTTPException(400, STEERING_DETAIL)
