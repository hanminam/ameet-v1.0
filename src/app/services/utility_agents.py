# src/app/services/utility_agents.py

import json

def run_snr_agent(source_text: str) -> dict | None:
    """
    SNR 전문가 에이전트 (규칙 기반) - 특정 키워드가 있을 때만 작동하여 신호 대 잡음비를 평가합니다.
    """
    trigger_keywords = ["보고서", "데이터", "%", "달러", "만 명", "로이터", "블룸버그", "AP", "뉴스", "기사", "출처", "조선일보", "주간조선"]
    if not any(keyword in source_text for keyword in trigger_keywords):
        return None
    
    score = 50
    reasons = []
    if "보고서에 따르면" in source_text or "데이터에 따르면" in source_text:
        score += 25
        reasons.append("명시적 데이터/보고서 인용")
    if "%" in source_text or "달러" in source_text or "만 명" in source_text:
        score = min(100, score + 25)
        reasons.append("구체적 수치 포함")
    if any(k in source_text for k in ["로이터", "블룸버그", "AP", "조선일보", "주간조선"]):
        score = min(100, score + 30)
        reasons.append("신뢰도 높은 언론사 인용")
    
    if not reasons:
        reasons.append("일반적 주장")
        score -= 20
        
    return {"snr_score": max(0, score), "reason": ", ".join(reasons)}

def run_verifier_agent(statement: str) -> dict | None:
    """
    정보 검증부 에이전트 (규칙 기반) - 모든 발언에 대해 작동하며, 단정적 표현 사용 여부를 평가합니다.
    """
    
    # '기본 검증 완료' 상태를 기본값으로 설정
    status = "기본 검증 완료"
    reason = "발언에 특별한 주의가 필요한 단정적 표현은 발견되지 않았습니다."

    # 할루시네이션 가능성이 있는 단정적 표현은 여전히 탐지
    strong_claims = [k for k in ["반드시", "무조건", "100%", "명백히", "확실히"] if k in statement]
    if strong_claims:
        status = "주의 필요"
        reason = f"'{', '.join(strong_claims)}' 등 단정적인 표현이 사용되어 교차 검증이 필요합니다."
        
    return {"status": status, "reason": reason}