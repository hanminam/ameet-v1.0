# src/app/tools/search.py

from langchain_community.tools.tavily_search import TavilySearchResults
from app.core.config import settings

# Tavily API 키가 설정되어 있는지 확인
if not settings.TAVILY_API_KEY:
    raise ValueError("TAVILY_API_KEY environment variable not set.")

# 검색 도구 인스턴스 생성 (k=5: 최대 5개의 결과 반환)
tavily_search = TavilySearchResults(k=5, tavily_api_key=settings.TAVILY_API_KEY)

async def perform_web_search(query: str) -> list:
    """
    주어진 쿼리로 웹 검색을 수행하고 결과 목록을 반환합니다.
    """
    print(f"--- [Tool] 웹 검색 수행: {query} ---")
    try:
        # LangChain 도구의 비동기 호출 메서드 'ainvoke' 사용
        results = await tavily_search.ainvoke(query)
        return results
    except Exception as e:
        print(f"--- [Tool Error] 웹 검색 중 오류 발생: {e} ---")
        return []