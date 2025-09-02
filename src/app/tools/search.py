# src/app/tools/search.py

import asyncio
from langchain_community.utilities.tavily_search import TavilySearchAPIWrapper
from app.core.config import settings
from langchain_core.tools import Tool

# Tavily API 키가 설정되어 있는지 확인
if not settings.TAVILY_API_KEY:
    raise ValueError("TAVILY_API_KEY environment variable not set.")

# 검색 도구 인스턴스 생성 (k=5: 최대 5개의 결과 반환)
# --- Tool 대신 API Wrapper 인스턴스를 생성합니다. ---
tavily_api_wrapper = TavilySearchAPIWrapper(tavily_api_key=settings.TAVILY_API_KEY)

async def perform_web_search(query: str) -> list:
    """
    Tavily API 래퍼를 사용하여 웹 검색을 수행하고,
    URL과 content가 포함된 사전(dictionary)의 리스트를 반환합니다.
    """
    print(f"--- [Tool] 웹 검색 수행 (API Wrapper 사용): {query} ---")
    try:
        # --- 래퍼의 results 메소드는 동기(sync) 방식이므로,
        # 비동기 환경에서 안전하게 실행하기 위해 asyncio.to_thread를 사용합니다.
        results = await asyncio.to_thread(
            tavily_api_wrapper.results,
            query=query,
            max_results=5 
        )
        # 결과 형식: [{'url': '...', 'content': '...'}, ...]
        return results
    except Exception as e:
        print(f"--- [Tool Error] 웹 검색 중 오류 발생: {e} ---")
        return []
    
# perform_web_search 함수를 LangChain Tool로 포장합니다.
web_search_tool = Tool(
    name="web_search",
    description="최신 뉴스, 주가, 시장 동향, 특정 주제에 대한 최신 정보 등 실시간 정보가 필요할 때 사용하는 웹 검색 도구입니다. 정확한 검색을 위해 구체적인 키워드를 사용하세요.",
    func=tavily_api_wrapper.results,      # 동기(sync) 실행용 함수
    coroutine=perform_web_search         # 비동기(async) 실행용 함수
)

# 사용 가능한 모든 도구를 딕셔너리 형태로 관리합니다.
available_tools = {
    "web_search": web_search_tool
}