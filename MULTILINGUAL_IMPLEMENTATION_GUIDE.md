# AMEET v1.0 다국어 지원 구현 가이드

> **작성일**: 2025-10-17
> **목적**: 토론 주제의 언어를 자동 감지하여 해당 언어로 고품질 실시간 토론 및 보고서를 생성하는 기능 구현

---

## 📋 목차

1. [현재 상황 분석](#1-현재-상황-분석)
2. [핵심 문제점](#2-핵심-문제점)
3. [해결 방안 개요](#3-해결-방안-개요)
4. [상세 구현 가이드](#4-상세-구현-가이드)
5. [파일별 수정 사항](#5-파일별-수정-사항)
6. [테스트 시나리오](#6-테스트-시나리오)
7. [주의사항 및 고려사항](#7-주의사항-및-고려사항)

---

## 1. 현재 상황 분석

### 1.1 문제 정의

**현재 동작**: 토론 주제를 영문으로 입력해도 결과는 항상 한국어로 출력됨

**요구사항**:
- 토론 주제의 언어를 자동 감지
- 감지된 언어로 실시간 토론 및 최종 보고서 생성
- 단순 언어 전환이 아닌 **고품질, 자연스러운 언어 출력** 보장

### 1.2 한글 하드코딩 위치 분석

#### A. orchestrator.py (오케스트레이션 단계)

| 라인 | 내용 | 문제점 |
|------|------|--------|
| 290-302 | Jury Selector 시스템 프롬프트 | "must be in KOREAN" 하드코딩 |
| 329-335 | 기본 에이전트 프롬프트 템플릿 | "당신의 역할은...", "사용자가 질문한 언어로" (애매함) |
| 126, 154, 278 | Redis 진행 상황 메시지 | "AI가 '...' 주제를 분석하고 있습니다" |

#### B. discussion_flow.py (실시간 토론 단계)

| 라인 | 내용 | 문제점 |
|------|------|--------|
| 260-264 | 에이전트 발언 지시문 | "지금은 '모두 변론' 시간입니다..." |
| 74-78 | Search Coordinator 프롬프트 | "토론 주제:", "검색어를 생성해주세요" |
| 116-118 | Stance Analyst 입력 프롬프트 | "에이전트 이름:", "이전 발언:" |
| 509-512 | 사회자 안내 메시지 | "~이 종료되었습니다", 조사 처리 |
| 573-578 | 특별 지시문 | "관점에 대한 당신의 의견을 듣고싶어합니다" |
| 635-636 | 라운드 구분선 | "---------- ~차 토론 종료 ----------" |

#### C. report_generator.py (보고서 생성)

| 라인 | 내용 | 문제점 |
|------|------|--------|
| 391 | 보고서 섹션 제목 | "V. 참여자 발언 전문" |

#### D. models/discussion.py (데이터 모델)

**문제**: `DiscussionLog` 모델에 언어 정보 저장 필드 없음

---

## 2. 핵심 문제점

### 2.1 언어 제어 방식의 불안정성

현재 코드에는 3가지 패턴이 혼재되어 있음:

#### ✅ 패턴 A: 안정적 (summarizer.py)
```python
system_prompt = """
You are a research assistant...
The summary must be in Korean.
"""
```
- 프롬프트: 영문
- 언어 지시: 명시적 영문 ("must be in Korean")
- 결과: **가장 안정적**

#### ⚠️ 패턴 B: 불안정 (orchestrator.py:329-335)
```python
PROMPT_TEMPLATE = (
    "당신의 역할은 '{role}'이며...\n"
    "사용자가 질문한 언어로 답변하여야 합니다."  # ← 애매함
)
```
- 프롬프트: 한글
- 언어 지시: 애매함 ("사용자가 질문한 언어로")
- 문제: LLM이 혼란, "잘못된 한글" 출력 가능

#### ❌ 패턴 C: 가장 불안정 (discussion_flow.py:260-264)
```python
human_instruction = f"지금은 '모두 변론' 시간입니다..."
```
- 프롬프트: 한글
- 언어 지시: 없음
- 문제: 한글 프롬프트만으로는 언어 제어 불충분

### 2.2 한국어 품질 문제

LLM이 한국어를 생성할 때 발생하는 전형적인 문제:

| 문제 유형 | 나쁜 예시 (번역투) | 좋은 예시 (자연스러운 한국어) |
|----------|-------------------|---------------------------|
| "~것이다" 남발 | "이 정책은 경제에 도움이 되는 것이다" | "이 정책은 경제에 도움이 됩니다" |
| 영어식 어순 | "중요한 것은 우리가 빠르게 행동하는 것입니다" | "중요한 점은 신속한 대응입니다" |
| 수동태 과다 | "이 문제는 고려되어져야 합니다" | "이 문제를 반드시 고려해야 합니다" |
| 한자어 과다 | "본인의 견해를 피력하자면..." | "제 생각으로는..." |
| 격식 불일치 | "저는 생각함. 그것은..." | "저는 생각합니다. 그것은..." |

---

## 3. 해결 방안 개요

### 3.1 핵심 원칙

```
✅ 영문 프롬프트 + 영문 언어 지시 + 언어별 품질 가이드
```

### 3.2 3단계 품질 보장 시스템

```
┌─────────────────────────────────────────────────┐
│ 1단계: 언어 감지 (langdetect)                    │
│   - 토론 주제 분석                               │
│   - language 필드에 저장 (ko/en/ja)              │
└─────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────┐
│ 2단계: 언어별 스타일 가이드 적용                  │
│   - 영문 베이스 프롬프트                         │
│   - 번역투 금지 패턴 명시                        │
│   - 전문 토론 어투 가이드                        │
└─────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────┐
│ 3단계: Few-shot 예시 제공                        │
│   - 좋은 예시 3개 이상                           │
│   - 나쁜 예시 비교                               │
└─────────────────────────────────────────────────┘
```

### 3.3 구현 우선순위

1. **Phase 1** (필수): 데이터 모델 확장 + 언어 감지
2. **Phase 2** (핵심): 고품질 프롬프트 시스템 구축
3. **Phase 3** (완성도): 시스템 메시지 다국어화

---

## 4. 상세 구현 가이드

### 4.1 Phase 1: 데이터 모델 확장

#### 파일: `src/app/models/discussion.py`

**수정 위치**: Line 9-11

```python
# 수정 전
class DiscussionLog(Document):
    discussion_id: Annotated[str, Indexed(unique=True)]
    topic: str
    # ...

# 수정 후
class DiscussionLog(Document):
    discussion_id: Annotated[str, Indexed(unique=True)]
    topic: str
    language: str = Field(default="ko", description="토론 언어 (ISO 639-1 코드: ko, en, ja, etc.)")  # ← 추가
    # ...
```

#### 파일: `requirements.txt`

**추가 항목**:
```
langdetect==1.0.9
```

설치 명령:
```bash
pip install langdetect
pip-compile --output-file=requirements.txt requirements.in  # 필요시
```

---

### 4.2 Phase 2: 언어 감지 로직

#### 파일: `src/app/api/v1/discussions.py`

**수정 위치**: Line 88-96 (create_discussion 함수)

```python
# 수정 전
discussion_log = DiscussionLog(
    discussion_id=discussion_id,
    topic=topic,
    user_email=current_user.email,
    status="orchestrating"
)

# 수정 후
from langdetect import detect

# 토론 주제의 언어 자동 감지
try:
    detected_language = detect(topic)
    # 지원 언어로 제한
    supported_languages = {"ko", "en", "ja"}
    language = detected_language if detected_language in supported_languages else "en"
except:
    language = "ko"  # 기본값

discussion_log = DiscussionLog(
    discussion_id=discussion_id,
    topic=topic,
    language=language,  # ← 추가
    user_email=current_user.email,
    status="orchestrating"
)
```

---

### 4.3 Phase 3: 고품질 다국어 프롬프트 시스템

#### 신규 파일: `src/app/core/i18n.py`

**전체 코드**: (다음 섹션 참조)

이 파일에는 다음이 포함됨:
1. `LANGUAGE_STYLE_GUIDES`: 언어별 품질 가이드
2. `LANGUAGE_FEWSHOT_EXAMPLES`: Few-shot 예시
3. `get_language_quality_instruction()`: 품질 지시문 생성
4. `get_agent_system_prompt()`: 에이전트 프롬프트 생성
5. `SYSTEM_MESSAGES`: 시스템 메시지 템플릿
6. `get_message()`: 메시지 조회 함수

---

## 5. 파일별 수정 사항

### 5.1 신규 파일: `src/app/core/i18n.py`

**위치**: `C:\projects\ameet-v1.0\src\app\core\i18n.py`

**전체 코드**:

```python
# src/app/core/i18n.py

"""
고품질 다국어 지원 모듈
핵심: 언어 품질과 자연스러움 보장
"""

# =====================================================
# 1. 언어별 스타일 가이드 (품질 중심)
# =====================================================

LANGUAGE_STYLE_GUIDES = {
    "ko": """
**CRITICAL OUTPUT LANGUAGE INSTRUCTION:**
Your ENTIRE response MUST be in natural, high-quality Korean. Follow these strict rules:

**Korean Language Quality Standards:**
1. **Natural Korean Flow:**
   - ❌ AVOID: "~것이다", "~것입니다" overuse (translation-like patterns)
   - ✅ USE: Natural Korean endings like "~습니다", "~입니다"
   - ❌ AVOID: "본인의 견해를 피력하자면" (overly formal Chinese-origin words)
   - ✅ USE: "제 생각으로는", "제가 보기에는" (natural conversational style)

2. **Professional Debate Tone:**
   - Use formal but natural Korean (합쇼체 - "~습니다/~입니다")
   - Maintain consistent formality level throughout
   - Use domain-specific terminology appropriately
   - Sound like a native Korean expert, not a translation

3. **Forbidden Patterns (번역투 금지):**
   - ❌ "~되어지다" (double passive)
   - ❌ "~적으로" excessive usage
   - ❌ English word order: "중요한 것은 X하는 것이다"
   - ✅ Korean word order: "X하는 점이 중요합니다"

4. **Sentence Structure:**
   - Prefer active voice over passive
   - Keep sentences concise but complete
   - Use appropriate connectors (그러나, 따라서, 또한)

**Example Comparison:**
❌ BAD (Translation-like Korean):
"이 정책은 경제 성장에 긍정적인 영향을 미치는 것으로 판단되어집니다. 그것은 중요한 것입니다."

✅ GOOD (Natural Korean):
"이 정책은 경제 성장에 긍정적 영향을 미칠 것으로 판단됩니다. 매우 중요한 사안입니다."
""",

    "en": """
**CRITICAL OUTPUT LANGUAGE INSTRUCTION:**
Your ENTIRE response MUST be in professional English suitable for academic debate.

**English Language Quality Standards:**
1. Use clear, precise academic vocabulary
2. Maintain formal but accessible tone
3. Prefer active voice
4. Use domain-specific terminology correctly
5. Structure arguments logically with proper transitions

**Example:**
✅ GOOD: "This policy significantly impacts economic growth. The evidence clearly demonstrates..."
❌ AVOID: "This policy is like, really good for economy. It's super important..."
""",

    "ja": """
**CRITICAL OUTPUT LANGUAGE INSTRUCTION:**
Your ENTIRE response MUST be in natural, professional Japanese (日本語).

**Japanese Language Quality Standards:**
1. Use appropriate keigo (敬語) level: です・ます調
2. Use natural Japanese sentence structures
3. Prefer 漢語 for technical terms, やまとことば for natural flow
4. Avoid direct translations from English
5. Use appropriate discourse markers (しかし、したがって、また)

**Example:**
✅ GOOD: "この政策は経済成長に好影響を与えると考えられます。重要な課題です。"
❌ AVOID: "この政策は経済成長に対してポジティブな影響をもたらすことです。それは重要なことです。"
"""
}

# =====================================================
# 2. Few-shot 예시 기반 프롬프트 (언어별)
# =====================================================

LANGUAGE_FEWSHOT_EXAMPLES = {
    "ko": """
**Examples of High-Quality Korean Responses in Professional Debates:**

Example 1 - Opening Statement:
"AI 규제 강화에 대한 제 입장은 신중한 접근이 필요하다는 것입니다.
기술 혁신을 저해하지 않으면서도 윤리적 기준을 확립해야 합니다.
EU의 AI Act 사례를 보면, 위험도 기반 규제가 효과적임을 알 수 있습니다."

Example 2 - Rebuttal:
"앞선 주장에는 중요한 맹점이 있습니다.
시장 자율 규제만으로는 AI 윤리 문제를 해결할 수 없습니다.
Cambridge Analytica 사태가 이를 잘 보여줍니다."

Example 3 - Building on Previous Point:
"이전 발언에 전적으로 동의합니다.
여기에 덧붙이자면, 규제 기관의 전문성 확보도 필수적입니다.
현재 대부분의 정부 기관은 AI 기술을 제대로 이해하지 못하고 있습니다."

**Your response must match this quality level.**
""",

    "en": """
**Examples of High-Quality English Responses in Professional Debates:**

Example 1 - Opening Statement:
"My position on AI regulation emphasizes a balanced approach.
We must establish ethical standards without stifling innovation.
The EU's AI Act demonstrates that risk-based regulation can be effective."

Example 2 - Rebuttal:
"The previous argument overlooks a critical issue.
Market self-regulation alone cannot address AI ethics concerns.
The Cambridge Analytica incident clearly illustrates this point."

Example 3 - Building on Previous Point:
"I fully agree with the previous statement.
Additionally, regulatory agencies must develop technical expertise.
Most government bodies currently lack adequate understanding of AI technology."

**Your response must match this quality level.**
""",

    "ja": """
**日本語での専門的討論の高品質な回答例:**

例1 - 冒頭発言:
"AI規制強化に関する私の立場は、慎重なアプローチが必要だということです。
技術革新を阻害せずに倫理基準を確立すべきです。
EUのAI法の事例を見ると、リスクベース規制が効果的であることが分かります。"

例2 - 反論:
"先の主張には重要な盲点があります。
市場の自主規制だけではAI倫理問題を解決できません。
Cambridge Analytica事件がこれを明確に示しています。"

例3 - 前の発言への追加:
"前の発言に全面的に同意します。
さらに付け加えると、規制機関の専門性確保も不可欠です。
現在、大半の政府機関はAI技術を十分に理解していません。"

**あなたの回答もこの品質レベルに合わせてください。**
"""
}

# =====================================================
# 3. 언어별 출력 지시문 생성 함수
# =====================================================

def get_language_quality_instruction(language: str) -> str:
    """
    언어별 품질 보장 지시문을 반환합니다.
    스타일 가이드 + Few-shot 예시를 결합합니다.

    Args:
        language: 언어 코드 (ko, en, ja)

    Returns:
        완성된 품질 지시문
    """
    style_guide = LANGUAGE_STYLE_GUIDES.get(language, LANGUAGE_STYLE_GUIDES["en"])
    examples = LANGUAGE_FEWSHOT_EXAMPLES.get(language, LANGUAGE_FEWSHOT_EXAMPLES["en"])

    return f"\n\n{'='*60}\n{style_guide}\n\n{examples}\n{'='*60}\n"

# =====================================================
# 4. 에이전트 시스템 프롬프트 생성 (품질 중심)
# =====================================================

BASE_AGENT_PROMPT_TEMPLATE = """
You are assigned the role of '{role}' in a professional expert debate panel.

**Your Core Responsibilities:**
1. Speak exclusively from your role's perspective and expertise
2. Provide evidence-based arguments with specific data, cases, or research
3. Challenge weak logic or unsupported claims from other agents
4. Build upon or refute previous statements constructively
5. Introduce novel perspectives that deepen the discussion
6. As rounds progress, provide increasingly specific solutions rather than repeating general points

**Debate Conduct:**
- Maintain professional but conversational tone
- Use domain-specific terminology appropriately
- Structure arguments clearly: claim → evidence → reasoning
- Reference credible sources when making factual claims
- Acknowledge valid opposing points before rebutting
"""

def get_agent_system_prompt(role: str, language: str = "ko") -> str:
    """
    에이전트의 고품질 시스템 프롬프트를 생성합니다.

    Args:
        role: 에이전트 역할 (예: "Financial Analyst", "재무 분석가")
        language: 출력 언어 코드 (ko, en, ja)

    Returns:
        영문 베이스 프롬프트 + 언어별 품질 지시문
    """
    base_prompt = BASE_AGENT_PROMPT_TEMPLATE.format(role=role)
    quality_instruction = get_language_quality_instruction(language)

    return base_prompt + quality_instruction

# =====================================================
# 5. 시스템 메시지 템플릿 (다국어 지원)
# =====================================================

SYSTEM_MESSAGES = {
    "ko": {
        # 에이전트 지시문 (영문 유지)
        "round_opening_instruction": "This is the opening statement round. Present your initial position in {min_length} to {max_length} characters. Remember to use natural, professional Korean as instructed.",

        "round_n_instruction": "This is Round {n}. Consider previous agents' opinions and either refute, agree, or modify your position. Challenge logical inconsistencies. Present creative ideas. Provide specific alternatives rather than repeating previous arguments. Respond in {min_length} to {max_length} characters. Remember to use natural, professional Korean as instructed.",

        # UI 메시지 (한국어 직접 사용)
        "orchestration_analyzing": "AI가 '{topic}' 주제를 분석하고 있습니다...",
        "orchestration_keywords_found": "핵심 쟁점 {count}개를 발견했습니다",
        "orchestration_evidence_gathering": "'{keywords}' 키워드로 웹 검색 중...",
        "orchestration_evidence_complete": "웹 자료 {web_count}건, 파일 자료 {file_count}건 수집 완료",
        "orchestration_selecting_experts": "토론에 적합한 AI 전문가를 선정하고 있습니다...",
        "orchestration_ready": "'{experts}' 등 {total}명의 전문가가 선정되었습니다. 토론을 시작합니다!",

        "moderator_message": "{round_name}이 종료되었습니다. 사용자는 '{topic}' 투표에 '{vote}'을(를) 선택하였습니다. 다음 토론을 시작합니다.",
        "round_separator": "---------- {name} 종료 ----------",

        "special_directive": "\n\n--- Special Directive ---\nThe user wants to hear your opinion on the '{vote}' perspective from the previous round. Incorporate this perspective to strengthen or modify your argument, or refute other agents. However, if you think this perspective is not critical, you may proactively argue what direction this discussion should take or what issues should be developed further.\n-------------------\n",

        "search_coordinator_input": "Discussion Topic: {topic}\n\nDiscussion so far:\n{history}\n\nUser's instruction for next round: '{user_vote}'\n\nBased on the above, generate a single web search query that will be most helpful for the next discussion.",

        "stance_analyst_instruction": "Analyze the following discussion transcript:\n\n{transcript}",

        "report_transcript_title": "V. 참여자 발언 전문",

        "user_info_not_found": "사용자 정보 없음",
        "progress_waiting": "대기 중",
        "progress_loading": "진행 상황 정보를 불러오는 중입니다...",
        "progress_error": "진행 상황을 가져올 수 없습니다: {error}",
    },

    "en": {
        "round_opening_instruction": "This is the opening statement round. Present your initial position in {min_length} to {max_length} characters. Remember to use professional English as instructed.",

        "round_n_instruction": "This is Round {n}. Consider previous agents' opinions and either refute, agree, or modify your position. Challenge logical inconsistencies. Present creative ideas. Provide specific alternatives rather than repeating previous arguments. Respond in {min_length} to {max_length} characters. Remember to use professional English as instructed.",

        "orchestration_analyzing": "AI is analyzing the topic '{topic}'...",
        "orchestration_keywords_found": "Found {count} core issues",
        "orchestration_evidence_gathering": "Searching the web with '{keywords}' keywords...",
        "orchestration_evidence_complete": "Collected {web_count} web sources, {file_count} file sources",
        "orchestration_selecting_experts": "Selecting AI experts suitable for the discussion...",
        "orchestration_ready": "'{experts}' and {total} other experts selected. Starting discussion!",

        "moderator_message": "{round_name} has ended. The user selected '{vote}' in the '{topic}' vote. The next round begins.",
        "round_separator": "---------- End of {name} ----------",

        "special_directive": "\n\n--- Special Directive ---\nThe user wants to hear your opinion on the '{vote}' perspective from the previous round. Incorporate this perspective to strengthen or modify your argument, or refute other agents. However, if you think this perspective is not critical, you may proactively argue what direction this discussion should take or what issues should be developed further.\n-------------------\n",

        "search_coordinator_input": "Discussion Topic: {topic}\n\nDiscussion so far:\n{history}\n\nUser's instruction for next round: '{user_vote}'\n\nBased on the above, generate a single web search query that will be most helpful for the next discussion.",

        "stance_analyst_instruction": "Analyze the following discussion transcript:\n\n{transcript}",

        "report_transcript_title": "V. Full Transcript of Participant Statements",

        "user_info_not_found": "User information not found",
        "progress_waiting": "Waiting",
        "progress_loading": "Loading progress information...",
        "progress_error": "Unable to retrieve progress information: {error}",
    },

    "ja": {
        "round_opening_instruction": "これは冒頭発言のラウンドです。{min_length}文字から{max_length}文字で初期立場を提示してください。指示された通り、自然で専門的な日本語を使用してください。",

        "round_n_instruction": "これは第{n}ラウンドです。他のエージェントの意見を考慮し、反論、同意、または立場を修正してください。論理的矛盾に挑戦してください。創造的なアイデアを提示してください。前の議論を繰り返すのではなく、具体的な代案を提供してください。{min_length}文字から{max_length}文字で回答してください。指示された通り、自然で専門的な日本語を使用してください。",

        "orchestration_analyzing": "AIが'{topic}'というテーマを分析しています...",
        "orchestration_keywords_found": "{count}個の核心争点を発見しました",
        "orchestration_evidence_gathering": "'{keywords}'キーワードでWeb検索中...",
        "orchestration_evidence_complete": "Web資料{web_count}件、ファイル資料{file_count}件を収集完了",
        "orchestration_selecting_experts": "討論に適したAI専門家を選定しています...",
        "orchestration_ready": "'{experts}'など{total}名の専門家が選定されました。討論を開始します!",

        "moderator_message": "{round_name}が終了しました。ユーザーは'{topic}'投票で'{vote}'を選択しました。次の討論を開始します。",
        "round_separator": "---------- {name} 終了 ----------",

        "special_directive": "\n\n--- 特別指示 ---\nユーザーは前のラウンドの'{vote}'という観点についてのあなたの意見を聞きたがっています。この観点を取り入れて主張を強化または修正するか、他のエージェントに反論してください。ただし、この観点が重要でないと考える場合は、この討論がどの方向に重点を置くべきか、またはどのような議論を深化発展させるべきかを積極的に主張することもできます。\n-------------------\n",

        "search_coordinator_input": "討論テーマ: {topic}\n\nこれまでの討論内容:\n{history}\n\n次のラウンドへのユーザーの指示: '{user_vote}'\n\n上記に基づいて、次の討論に最も役立つ単一のWeb検索クエリを生成してください。",

        "stance_analyst_instruction": "次の討論記録を分析してください:\n\n{transcript}",

        "report_transcript_title": "V. 参加者発言全文",

        "user_info_not_found": "ユーザー情報が見つかりません",
        "progress_waiting": "待機中",
        "progress_loading": "進捗情報を読み込んでいます...",
        "progress_error": "進捗情報を取得できません: {error}",
    }
}

def get_message(language: str, key: str, **kwargs) -> str:
    """
    언어별 시스템 메시지를 가져옵니다.

    Args:
        language: 언어 코드 (ko, en, ja)
        key: 메시지 키
        **kwargs: 템플릿 변수

    Returns:
        포맷팅된 메시지
    """
    messages = SYSTEM_MESSAGES.get(language, SYSTEM_MESSAGES["en"])
    template = messages.get(key, "")

    if not template:
        # fallback to English
        template = SYSTEM_MESSAGES["en"].get(key, "")

    return template.format(**kwargs) if kwargs else template

# =====================================================
# 6. 언어 감지 헬퍼 함수
# =====================================================

def detect_language(text: str) -> str:
    """
    텍스트의 언어를 감지합니다.

    Args:
        text: 분석할 텍스트

    Returns:
        ISO 639-1 언어 코드 (ko, en, ja, ...)
    """
    try:
        from langdetect import detect
        detected = detect(text)

        # 지원 언어 목록으로 매핑
        supported_languages = {"ko", "en", "ja"}
        return detected if detected in supported_languages else "en"
    except Exception:
        return "en"  # fallback to English
```

---

### 5.2 orchestrator.py 수정

#### 수정 위치 1: Line 329-350 (기본 에이전트 프롬프트 생성)

```python
# ===== 수정 전 =====
PROMPT_TEMPLATE = (
    "당신의 역할은 '{role}'이며 지정된 역할 관점에서 말하세요.\n"
    "당신의 역할에 맞는 대화스타일을 사용하세요.\n"
    "토의 규칙을 숙지하고 토론의 목표를 달성하기 위해 제시된 의견들을 바탕으로 보완의견을 제시하거나, 주장을 강화,철회,수정 하세요.\n"
    "모든 의견은 논리적이고 일관성이 있어야 하며 신뢰할 수 있는 출처에 기반해야하고 자세하게 답변하여야 합니다.\n"
    "사용자가 질문한 언어로 답변하여야 합니다."
)

# ===== 수정 후 =====
from app.core.i18n import get_agent_system_prompt
from app.models.discussion import DiscussionLog

# 1. discussion_id로 language 조회
discussion = await DiscussionLog.find_one(DiscussionLog.discussion_id == discussion_id)
language = discussion.language if discussion else "ko"

# 2. 고품질 프롬프트 생성
PROMPT_TEMPLATE = get_agent_system_prompt(role=agent_name, language=language)
```

#### 수정 위치 2: Line 126, 154, 278, 410 (진행 상황 메시지)

```python
# ===== 수정 전 (Line 126) =====
await _update_progress(discussion_id, "주제 분석", f"AI가 '{topic}' 주제를 분석하고 있습니다...", 10)

# ===== 수정 후 =====
from app.core.i18n import get_message
from app.models.discussion import DiscussionLog

discussion = await DiscussionLog.find_one(DiscussionLog.discussion_id == discussion_id)
language = discussion.language if discussion else "ko"

await _update_progress(
    discussion_id,
    "주제 분석",  # 내부 식별용 (변경 안 함)
    get_message(language, "orchestration_analyzing", topic=topic),
    10
)

# ===== Line 154 수정 후 =====
await _update_progress(
    discussion_id,
    "주제 분석 완료",
    get_message(language, "orchestration_keywords_found", count=len(report.core_keywords)),
    25
)

# ===== Line 198 수정 후 =====
await _update_progress(
    discussion_id,
    "자료 수집",
    get_message(language, "orchestration_evidence_gathering", keywords=keywords_preview),
    35
)

# ===== Line 182-187 수정 후 =====
await _update_progress(
    discussion_id,
    "자료 수집 완료",
    get_message(language, "orchestration_evidence_complete", web_count=web_count, file_count=file_count),
    65
)

# ===== Line 278 수정 후 =====
await _update_progress(
    discussion_id,
    "전문가 선정",
    get_message(language, "orchestration_selecting_experts"),
    75
)

# ===== Line 410-415 수정 후 =====
expert_names = ', '.join([agent.name for agent in final_jury_details[:3]])
await _update_progress(
    discussion_id,
    "준비 완료",
    get_message(language, "orchestration_ready", experts=expert_names, total=len(final_jury_details)),
    100
)
```

---

### 5.3 discussion_flow.py 수정

#### 수정 위치 1: Line 74-78 (Search Coordinator)

```python
# ===== 수정 전 =====
human_prompt = (
    f"토론 주제: {discussion_log.topic}\n\n"
    f"지금까지의 토론 내용:\n{history_str}\n\n"
    f"사용자의 다음 라운드 지시사항: '{user_vote}'\n\n"
    "위 내용을 바탕으로, 다음 토론에 가장 도움이 될 단 하나의 웹 검색어를 생성해주세요."
)

# ===== 수정 후 =====
from app.core.i18n import get_message

human_prompt = get_message(
    discussion_log.language,
    "search_coordinator_input",
    topic=discussion_log.topic,
    history=history_str,
    user_vote=user_vote
)
```

#### 수정 위치 2: Line 116-127 (Stance Analyst)

```python
# ===== 수정 전 =====
transcript_to_analyze = (
    f"에이전트 이름: {agent_name}\n\n"
    f"이전 발언: \"{prev_statement}\"\n\n"
    f"현재 발언: \"{current_statement}\""
)

prompt = ChatPromptTemplate.from_messages([
    ("system", analyst_setting.config.prompt),
    ("human", "다음 토론 대화록을 분석하세요:\n\n{transcript}")
])

# ===== 수정 후 =====
from app.core.i18n import get_message

transcript_to_analyze = (
    f"에이전트 이름: {agent_name}\n\n"
    f"이전 발언: \"{prev_statement}\"\n\n"
    f"현재 발언: \"{current_statement}\""
)

prompt = ChatPromptTemplate.from_messages([
    ("system", analyst_setting.config.prompt),
    ("human", get_message(discussion_log.language, "stance_analyst_instruction", transcript="{transcript}"))
])
```

#### 수정 위치 3: Line 260-264 (에이전트 발언 지시문)

```python
# ===== 수정 전 =====
human_instruction = (
    f"지금은 '모두 변론' 시간입니다. 위 내용을 바탕으로 당신의 초기 입장을 최소 {min_response_length}자에서 최대 {max_response_length}자 이내로 설명해주세요."
    if turn_count == 0 else
    f"지금은 '{turn_count + 1}차 토론' 시간입니다. 이전의 에이전트들의 의견을 고려하여..."
)

# ===== 수정 후 =====
from app.core.i18n import get_message

# discussion_log에서 언어 정보 가져오기 (이 함수의 파라미터로 이미 전달됨)
language = discussion_log.language

human_instruction = (
    get_message(
        language,
        "round_opening_instruction",
        min_length=min_response_length,
        max_length=max_response_length
    )
    if turn_count == 0 else
    get_message(
        language,
        "round_n_instruction",
        n=turn_count + 1,
        min_length=min_response_length,
        max_length=max_response_length
    )
)
```

**주의**: 이 수정을 위해서는 `_run_single_agent_turn` 함수의 시그니처를 변경해야 합니다:

```python
# ===== 함수 시그니처 수정 =====
# 수정 전: Line 233
async def _run_single_agent_turn(
    agent_config: dict,
    topic: str,
    history: str,
    evidence: str,
    special_directive: str,
    discussion_id: str,
    turn_count: int
) -> str:

# 수정 후
async def _run_single_agent_turn(
    agent_config: dict,
    topic: str,
    history: str,
    evidence: str,
    special_directive: str,
    discussion_id: str,
    turn_count: int,
    language: str  # ← 추가
) -> str:
```

그리고 호출 부분도 수정 (Line 590-600):

```python
# ===== 수정 전 =====
task = _run_single_agent_turn(
    agent_config,
    discussion_log.topic,
    history_str,
    evidence_str,
    special_directive,
    discussion_log.discussion_id,
    current_turn
)

# ===== 수정 후 =====
task = _run_single_agent_turn(
    agent_config,
    discussion_log.topic,
    history_str,
    evidence_str,
    special_directive,
    discussion_log.discussion_id,
    current_turn,
    discussion_log.language  # ← 추가
)
```

#### 수정 위치 4: Line 509-512 (사회자 메시지)

```python
# ===== 수정 전 =====
round_name = "모두 변론" if discussion_log.turn_number == 1 else f"{discussion_log.turn_number - 1}차 토론"

last_char = user_vote[-1]
postposition = "을" if (ord(last_char) - 0xAC00) % 28 > 0 else "를"

moderator_message = (
    f"{round_name}이 종료되었습니다. "
    f"사용자는 '{discussion_log.current_vote['topic']}' 투표에 "
    f"'{user_vote}'{postposition} 선택하였습니다. 다음 토론을 시작합니다."
)

# ===== 수정 후 =====
from app.core.i18n import get_message

round_name = "모두 변론" if discussion_log.turn_number == 1 else f"{discussion_log.turn_number - 1}차 토론"

moderator_message = get_message(
    discussion_log.language,
    "moderator_message",
    round_name=round_name,
    topic=discussion_log.current_vote['topic'],
    vote=user_vote
)
```

**참고**: 조사 처리 로직은 영문/일본어에서는 불필요하므로 삭제됨

#### 수정 위치 5: Line 573-578 (특별 지시문)

```python
# ===== 수정 전 =====
special_directive = ""
if user_vote:
    special_directive = (
        f"\n\n--- 특별 지시문 ---\n"
        f"사용자는 직전 라운드에서 '{user_vote}' 관점에 대한 당신의 의견을 듣고싶어합니다."
        # ...
    )

# ===== 수정 후 =====
from app.core.i18n import get_message

special_directive = ""
if user_vote:
    special_directive = get_message(
        discussion_log.language,
        "special_directive",
        vote=user_vote
    )
```

#### 수정 위치 6: Line 635-636 (라운드 구분선)

```python
# ===== 수정 전 =====
round_name_for_separator = "모두 변론" if discussion_log.turn_number == 0 else f"{discussion_log.turn_number}차 토론"
separator_message = f"---------- {round_name_for_separator} 종료 ----------"

# ===== 수정 후 =====
from app.core.i18n import get_message

round_name_for_separator = "모두 변론" if discussion_log.turn_number == 0 else f"{discussion_log.turn_number}차 토론"
separator_message = get_message(
    discussion_log.language,
    "round_separator",
    name=round_name_for_separator
)
```

---

### 5.4 report_generator.py 수정

#### 수정 위치: Line 391 (보고서 섹션 제목)

```python
# ===== 수정 전 =====
full_transcript_section = f"""
<section class="mb-12">
    <div class="bg-white p-6 rounded-xl shadow-md">
        <h2 class="text-3xl font-bold text-gray-800 mb-6 text-center border-b pb-4">V. 참여자 발언 전문</h2>
        <div class="transcript-container space-y-4">{transcript_html_str}</div>
    </div>
</section>"""

# ===== 수정 후 =====
from app.core.i18n import get_message

# discussion_log에서 언어 가져오기 (이미 함수 내에 있음)
language = discussion_log.language

full_transcript_section = f"""
<section class="mb-12">
    <div class="bg-white p-6 rounded-xl shadow-md">
        <h2 class="text-3xl font-bold text-gray-800 mb-6 text-center border-b pb-4">
            {get_message(language, "report_transcript_title")}
        </h2>
        <div class="transcript-container space-y-4">{transcript_html_str}</div>
    </div>
</section>"""
```

---

### 5.5 summarizer.py 수정

#### 파일 전체 수정

```python
# ===== 수정 전 =====
# src/app/services/summarizer.py

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from app.core.config import settings

async def summarize_text(content: str, topic: str, discussion_id: str) -> str:
    """웹 콘텐츠 또는 파일 내용을 간결하게 요약하여 토론에 활용 가능한 형태로 만듭니다."""
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.0-flash-exp",
        temperature=0.1,
        google_api_key=settings.GOOGLE_API_KEY
    )

    system_prompt = """
    You are a research assistant. Your task is to summarize the provided text in 2-3 concise sentences. The summary must be directly relevant to the main discussion topic. Extract only the most critical facts, arguments, or data points. The summary must be in Korean.
    """

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", "Main Discussion Topic: {topic}\n\nText to Summarize:\n---\n{content}")
    ])

    chain = prompt | llm

    response = await chain.ainvoke(
        {"topic": topic, "content": content},
        config={"tags": [f"discussion_id:{discussion_id}", "task:summarize"]}
    )

    return response.content.strip()

# ===== 수정 후 =====
# src/app/services/summarizer.py

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from app.core.config import settings
from app.core.i18n import get_language_quality_instruction
from app.models.discussion import DiscussionLog

async def summarize_text(content: str, topic: str, discussion_id: str) -> str:
    """웹 콘텐츠 또는 파일 내용을 간결하게 요약하여 토론에 활용 가능한 형태로 만듭니다."""

    # 1. discussion_id로 언어 조회
    discussion = await DiscussionLog.find_one(DiscussionLog.discussion_id == discussion_id)
    language = discussion.language if discussion else "ko"

    llm = ChatGoogleGenerativeAI(
        model="gemini-2.0-flash-exp",
        temperature=0.1,
        google_api_key=settings.GOOGLE_API_KEY
    )

    # 2. 언어별 품질 가이드를 포함한 시스템 프롬프트 생성
    base_prompt = """
You are a research assistant. Your task is to summarize the provided text in 2-3 concise sentences.
The summary must be directly relevant to the main discussion topic.
Extract only the most critical facts, arguments, or data points.
"""
    system_prompt = base_prompt + get_language_quality_instruction(language)

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", "Main Discussion Topic: {topic}\n\nText to Summarize:\n---\n{content}")
    ])

    chain = prompt | llm

    response = await chain.ainvoke(
        {"topic": topic, "content": content},
        config={"tags": [f"discussion_id:{discussion_id}", f"language:{language}", "task:summarize"]}
    )

    return response.content.strip()
```

---

### 5.6 discussions.py 수정 (API 엔드포인트)

#### 수정 위치: Line 223, 323-334 (UI 메시지)

```python
# ===== Line 223 수정 =====
# 수정 전
user_name = user.name if user else "사용자 정보 없음"

# 수정 후
from app.core.i18n import get_message
user_name = user.name if user else get_message(discussion.language, "user_info_not_found")

# ===== Line 323-334 수정 (get_orchestration_progress) =====
# 수정 전
if not progress_json:
    return {
        "stage": "대기 중",
        "message": "진행 상황 정보를 불러오는 중입니다...",
        "progress": 0
    }

# 수정 후
from app.core.i18n import get_message
from app.models.discussion import DiscussionLog

if not progress_json:
    # discussion_id로 언어 조회
    discussion = await DiscussionLog.find_one(DiscussionLog.discussion_id == discussion_id)
    language = discussion.language if discussion else "ko"

    return {
        "stage": get_message(language, "progress_waiting"),
        "message": get_message(language, "progress_loading"),
        "progress": 0
    }

# ===== Line 333-334 수정 =====
# 수정 전
return {
    "stage": "오류",
    "message": f"진행 상황을 가져올 수 없습니다: {str(e)}",
    "progress": 0
}

# 수정 후
from app.core.i18n import get_message
from app.models.discussion import DiscussionLog

discussion = await DiscussionLog.find_one(DiscussionLog.discussion_id == discussion_id)
language = discussion.language if discussion else "ko"

return {
    "stage": "Error",
    "message": get_message(language, "progress_error", error=str(e)),
    "progress": 0
}
```

---

## 6. 테스트 시나리오

### 6.1 기본 테스트

#### 테스트 1: 한국어 토론

**입력**:
```
토론 주제: "AI 규제 강화가 혁신에 미치는 영향"
```

**기대 결과**:
- `language` 필드: `"ko"`
- 에이전트 발언: 자연스러운 한국어 (번역투 없음)
- 예시: "이 정책은 경제 성장에 긍정적 영향을 미칠 것으로 판단됩니다."
- ❌ 금지: "이 정책은 경제 성장에 긍정적인 영향을 미치는 것으로 판단되어집니다."

#### 테스트 2: 영어 토론

**입력**:
```
토론 주제: "Should AI development be regulated by government?"
```

**기대 결과**:
- `language` 필드: `"en"`
- 에이전트 발언: 전문적 영어
- 예시: "This policy significantly impacts economic growth. The evidence demonstrates..."
- 진행 상황: "AI is analyzing the topic..."

#### 테스트 3: 일본어 토론

**입력**:
```
토론 주제: "AI規制強化がイノベーションに与える影響"
```

**기대 결과**:
- `language` 필드: `"ja"`
- 에이전트 발언: 자연스러운 일본어 (です・ます調)
- 예시: "この政策は経済成長に好影響を与えると考えられます。"

---

### 6.2 품질 검증 테스트

#### 한국어 품질 체크리스트

에이전트 응답에서 다음을 확인:

- [ ] "~것이다" 남발 없음
- [ ] "~되어지다" (이중 피동) 없음
- [ ] 자연스러운 어순 (한국어 어순)
- [ ] 일관된 존댓말 (합쇼체)
- [ ] 전문 용어 적절히 사용
- [ ] 증거 기반 주장

#### 영어 품질 체크리스트

- [ ] 학술적 어휘 사용
- [ ] 능동태 선호
- [ ] 논리적 전개
- [ ] 구어체 표현 없음

---

### 6.3 엣지 케이스 테스트

#### 테스트 4: 혼합 언어 입력

**입력**:
```
토론 주제: "AI regulation and 혁신의 균형"
```

**기대 결과**:
- `langdetect`가 주요 언어 감지 (한국어로 판단될 가능성 높음)
- 감지 실패 시 기본값 `"en"` 적용

#### 테스트 5: 언어 감지 실패

**입력**:
```
토론 주제: "🤖🔥💡"  (이모지만 입력)
```

**기대 결과**:
- 예외 처리로 `"en"` (기본값) 적용
- 정상 동작 유지

---

## 7. 주의사항 및 고려사항

### 7.1 구현 시 주의사항

#### 🔴 절대 하지 말아야 할 것

1. **프롬프트를 한국어로 작성하지 말 것**
   - ❌ "당신의 역할은..."
   - ✅ "You are assigned the role..."

2. **언어 지시를 한국어로 하지 말 것**
   - ❌ "반드시 한국어로 답변하세요"
   - ✅ "Your ENTIRE response MUST be in Korean"

3. **단순 "~로 답변" 지시만 사용하지 말 것**
   - ❌ "Answer in Korean"
   - ✅ "Your ENTIRE response MUST be in natural, high-quality Korean. Follow these strict rules: ..."

#### ✅ 반드시 해야 할 것

1. **품질 가이드 포함**
   - 번역투 금지 패턴 명시
   - Few-shot 예시 제공

2. **영문 프롬프트 유지**
   - 모든 시스템 프롬프트는 영문 작성
   - 언어 지시도 영문으로

3. **언어 정보 전파**
   - `discussion_log.language`를 모든 함수에 전달
   - DB 조회 최소화 (파라미터로 전달)

---

### 7.2 성능 최적화

#### MongoDB 쿼리 최적화

현재 구현안에서는 언어 정보를 얻기 위해 여러 번 DB 조회가 발생합니다.

**최적화 방법**:

```python
# orchestrator.py에서
async def select_debate_team(report, jury_pool, special_agents, discussion_id) -> DebateTeam:
    # 함수 초반에 한 번만 조회
    discussion = await DiscussionLog.find_one(DiscussionLog.discussion_id == discussion_id)
    language = discussion.language if discussion else "ko"

    # 이후 language 변수 재사용
    PROMPT_TEMPLATE = get_agent_system_prompt(role=agent_name, language=language)

    # 메시지도 language 변수 사용
    await _update_progress(
        discussion_id,
        "분석",
        get_message(language, "orchestration_analyzing", topic=discussion.topic),
        10
    )
```

---

### 7.3 기존 데이터 마이그레이션

#### 문제

기존에 생성된 `DiscussionLog` 문서에는 `language` 필드가 없습니다.

#### 해결 방법 1: 기본값 활용

```python
# models/discussion.py에서 기본값 설정
language: str = Field(default="ko", ...)
```

이렇게 하면 기존 문서 조회 시 자동으로 `"ko"` 반환됩니다.

#### 해결 방법 2: 마이그레이션 스크립트 (선택)

기존 문서를 일괄 업데이트하고 싶다면:

```python
# scripts/migrate_language_field.py
from app.models.discussion import DiscussionLog
from app.db import init_db
import asyncio

async def migrate():
    await init_db()

    # language 필드가 없는 문서 찾기
    discussions = await DiscussionLog.find({"language": {"$exists": False}}).to_list()

    for disc in discussions:
        disc.language = "ko"  # 기존은 모두 한국어로 가정
        await disc.save()

    print(f"Migrated {len(discussions)} discussions")

if __name__ == "__main__":
    asyncio.run(migrate())
```

---

### 7.4 MongoDB의 에이전트 프롬프트 마이그레이션

#### 문제

현재 `AgentSettings` 컬렉션의 `config.prompt`가 모두 한국어로 저장되어 있습니다.

#### 해결 방법

**옵션 1**: 기존 프롬프트 유지 + 언어별 덮어쓰기

```python
# orchestrator.py에서 동적 에이전트 생성 시
# 기존 한국어 프롬프트를 영문 + 품질 가이드로 교체
PROMPT_TEMPLATE = get_agent_system_prompt(role=agent_name, language=language)
```

**옵션 2**: DB 일괄 업데이트 (권장)

Admin 패널에서 에이전트 편집 시 새로운 영문 프롬프트로 교체:

```python
# 새로운 기본 프롬프트 (영문)
new_default_prompt = """
You are assigned the role of '{role}' in a professional expert debate panel.
...
"""

# SystemSettings의 default_agent_prompt 업데이트
await settings_collection.update_one(
    {"key": "default_agent_prompt"},
    {"$set": {"value": new_default_prompt}},
    upsert=True
)
```

---

### 7.5 프론트엔드 고려사항

#### 현재 범위

이 구현안은 **백엔드(AI 응답 언어)**에만 집중합니다.

#### 추가 작업 필요 시

프론트엔드 UI 버튼, 레이블도 다국어화하려면:

1. `templates/index.html`에서 JavaScript로 언어 감지
2. UI 텍스트를 `i18n.js` 같은 파일로 관리
3. API 응답의 `language` 필드 기반으로 UI 언어 전환

**예시**:

```javascript
// static/js/i18n.js
const UI_MESSAGES = {
    ko: {
        start_discussion: "토론 시작하기",
        next_round: "다음 라운드",
        // ...
    },
    en: {
        start_discussion: "Start Discussion",
        next_round: "Next Round",
        // ...
    }
};

function updateUI(language) {
    document.querySelector('#start-btn').textContent = UI_MESSAGES[language].start_discussion;
}
```

---

### 7.6 LLM 모델별 특성

#### Gemini

- 한국어, 영어, 일본어 모두 우수
- Temperature 0.2-0.3 권장 (한국어 품질 안정)

#### GPT-4

- 다국어 성능 최고
- Temperature 0.1-0.2 권장

#### Claude

- 영어 최고 성능
- 한국어도 준수하나 프롬프트 중요성 더 높음

#### 모델별 설정 (선택적)

```python
# discussion_flow.py의 get_llm_client 확장
def get_llm_client(model_name: str, temperature: float, language: str = "ko"):
    # 한국어 출력 시 temperature 낮춤 (품질 안정화)
    if language == "ko" and temperature > 0.3:
        adjusted_temp = 0.2
        logger.info(f"Adjusted temperature for Korean: {temperature} -> {adjusted_temp}")
    else:
        adjusted_temp = temperature

    # ...
```

---

## 8. 구현 체크리스트

구현 전 이 체크리스트를 확인하세요:

### Phase 1: 기본 인프라

- [ ] `langdetect` 설치 (`pip install langdetect`)
- [ ] `requirements.txt` 업데이트
- [ ] `src/app/models/discussion.py`에 `language` 필드 추가
- [ ] `src/app/core/i18n.py` 파일 생성 (전체 코드)

### Phase 2: 언어 감지

- [ ] `src/app/api/v1/discussions.py` - `create_discussion` 함수 수정
- [ ] 테스트: 한국어, 영어, 일본어 토론 주제로 `language` 필드 확인

### Phase 3: 프롬프트 시스템

- [ ] `src/app/services/orchestrator.py` - 에이전트 프롬프트 생성 수정
- [ ] `src/app/services/orchestrator.py` - 진행 상황 메시지 수정 (5곳)
- [ ] 테스트: 새 에이전트 생성 시 고품질 프롬프트 확인

### Phase 4: 토론 흐름

- [ ] `src/app/services/discussion_flow.py` - `_run_single_agent_turn` 함수 시그니처 수정
- [ ] `src/app/services/discussion_flow.py` - 에이전트 지시문 수정 (Line 260-264)
- [ ] `src/app/services/discussion_flow.py` - Search Coordinator 수정 (Line 74-78)
- [ ] `src/app/services/discussion_flow.py` - Stance Analyst 수정 (Line 116-127)
- [ ] `src/app/services/discussion_flow.py` - 사회자 메시지 수정 (Line 509-512)
- [ ] `src/app/services/discussion_flow.py` - 특별 지시문 수정 (Line 573-578)
- [ ] `src/app/services/discussion_flow.py` - 구분선 수정 (Line 635-636)
- [ ] 테스트: 에이전트 발언 품질 (번역투 없음, 자연스러움)

### Phase 5: 보고서 & 기타

- [ ] `src/app/services/report_generator.py` - 섹션 제목 수정 (Line 391)
- [ ] `src/app/services/summarizer.py` - 전체 수정
- [ ] `src/app/api/v1/discussions.py` - UI 메시지 수정 (3곳)

### Phase 6: 테스트

- [ ] 한국어 토론 전체 플로우 테스트
- [ ] 영어 토론 전체 플로우 테스트
- [ ] 일본어 토론 전체 플로우 테스트
- [ ] 혼합 언어 입력 테스트
- [ ] 품질 검증 (번역투, 전문성)

### Phase 7: 배포 준비

- [ ] 기존 데이터 마이그레이션 (선택)
- [ ] 에이전트 프롬프트 업데이트 (Admin 패널)
- [ ] 로그 확인 (언어 감지, 프롬프트 생성)
- [ ] 문서화 업데이트

---

## 9. 트러블슈팅

### 문제 1: "잘못된 한글" 여전히 출력됨

**원인**:
- 프롬프트가 한국어로 작성됨
- 품질 가이드가 적용 안 됨

**해결**:
1. `i18n.py`의 `get_agent_system_prompt` 사용 확인
2. 프롬프트 로그 출력해서 영문 프롬프트 + 품질 가이드 포함 확인
3. Temperature 0.2로 낮춤

### 문제 2: 언어 감지가 잘못됨

**원인**:
- 토론 주제가 너무 짧음
- 혼합 언어

**해결**:
```python
# 짧은 텍스트는 감지 실패 가능
try:
    detected = detect(topic)
    if len(topic) < 10:
        # 짧으면 기본값 사용
        return "ko"
except:
    return "ko"
```

### 문제 3: DB에서 language 필드를 못 찾음

**원인**:
- 기존 데이터에 `language` 필드 없음

**해결**:
```python
# 모델에 기본값 설정
language: str = Field(default="ko", ...)

# 또는 조회 시 방어 코드
language = discussion.language if discussion and hasattr(discussion, 'language') else "ko"
```

---

## 10. 참고 자료

### LLM 프롬프팅 모범 사례

- [Anthropic Prompt Engineering Guide](https://docs.anthropic.com/claude/docs/prompt-engineering)
- [OpenAI Best Practices](https://platform.openai.com/docs/guides/prompt-engineering)

### 언어 품질 가이드

- [Korean Style Guide for Developers](https://github.com/tooling-lab/korean-style-guide)
- [Microsoft Korean Style Guide](https://www.microsoft.com/en-us/language/StyleGuides)

### 다국어 지원

- [langdetect Documentation](https://pypi.org/project/langdetect/)
- [ISO 639-1 Language Codes](https://en.wikipedia.org/wiki/List_of_ISO_639-1_codes)

---

## 마무리

이 가이드는 AMEET v1.0 시스템에 고품질 다국어 지원을 추가하기 위한 완전한 구현 명세입니다.

**핵심 원칙 재확인**:
1. ✅ 영문 프롬프트 + 영문 언어 지시
2. ✅ 언어별 품질 가이드 (번역투 금지)
3. ✅ Few-shot 예시 제공
4. ✅ 자연스러운 전문 토론 어투

다음 세션에서 이 문서를 기반으로 구현을 진행하시면 됩니다.

---

**문서 버전**: 1.0
**최종 수정**: 2025-10-17
**작성자**: Claude Code Analysis Session
