# src/app/services/summarizer.py

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from app.core.config import settings, logger

async def summarize_text(content: str, topic: str, discussion_id: str) -> str:
    """
    주어진 텍스트 내용을 토론 주제와 관련하여 요약합니다.
    """
    # 내용이 너무 짧으면(약 2~3문장) 요약 없이 원본을 반환합니다.
    if len(content) < 150:
        return content
    
    logger.info(f"--- [DEBUG] Calling 'summarize_text' LLM with hardcoded model: 'gemini-2.5-flash' ---")

    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash", 
        temperature=0.0, 
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

    # LLM의 토큰 제한을 초과하지 않도록 입력 텍스트의 길이를 제한합니다.
    summary_result = await chain.ainvoke(
        {
            "topic": topic,
            "content": content[:8000]
        },
        config={"tags": [f"discussion_id:{discussion_id}"]}
    )

    return summary_result.content