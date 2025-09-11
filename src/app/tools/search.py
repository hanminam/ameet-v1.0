# src/app/tools/search.py

import asyncio
from typing import List, Dict, Any
from urllib.parse import quote

from langchain_community.utilities.tavily_search import TavilySearchAPIWrapper
from app.core.config import settings, logger
from langchain_core.tools import Tool
from langsmith import traceable
import yfinance as yf
from fredapi import Fred
import pandas as pd

# Tavily API 키가 설정되어 있는지 확인
if not settings.TAVILY_API_KEY:
    raise ValueError("TAVILY_API_KEY environment variable not set.")

if not settings.FRED_API_KEY:
    raise ValueError("FRED_API_KEY environment variable not set.")

# 검색 도구 인스턴스 생성 (k=5: 최대 5개의 결과 반환)
# --- Tool 대신 API Wrapper 인스턴스를 생성합니다. ---
tavily_api_wrapper = TavilySearchAPIWrapper(tavily_api_key=settings.TAVILY_API_KEY)

fred_client = Fred(api_key=settings.FRED_API_KEY)

# --- 동기 실행용 함수 생성 ---
@traceable
def perform_web_search_sync(query: str) -> list:
    """
    Tavily API 래퍼를 사용하여 웹 검색을 동기적으로 수행하고 로그를 남깁니다.
    """
    print(f"--- [Tool] 웹 검색 수행 (Sync Wrapper 사용): {query} ---")
    try:
        results = tavily_api_wrapper.results(
            query=query,
            max_results=5
        )
        return results
    except Exception as e:
        print(f"--- [Tool Error] 웹 검색 중 오류 발생: {e} ---")
        return []
    
@traceable
async def perform_web_search_async(query: str) -> list:
    """Tavily API 래퍼를 사용하여 웹 검색을 비동기적으로 수행합니다."""
    print(f"--- [Tool] 웹 검색 수행 (Async): {query} ---")
    try:
        return await asyncio.to_thread(tavily_api_wrapper.results, query=query, max_results=5)
    except Exception as e:
        print(f"--- [Tool Error] 웹 검색 중 오류 발생: {e} ---")
        return []

@traceable
def get_stock_price_sync(ticker: str, start_date: str, end_date: str) -> List[Dict[str, Any]]:
    """yfinance를 사용하여 특정 종목의 주가 데이터를 동기적으로 조회합니다."""
    print(f"--- [Tool] 주가 데이터 조회 (Sync): {ticker} from {start_date} to {end_date} ---")
    try:
        stock = yf.Ticker(ticker)
        history = stock.history(start=start_date, end=end_date)
        history.reset_index(inplace=True)
        history['Date'] = history['Date'].dt.strftime('%Y-%m-%d')
        return history.to_dict('records')
    except Exception as e:
        print(f"--- [Tool Error] 주가 데이터 조회 중 오류 발생: {e} ---")
        return []
    
@traceable
def get_stock_price_sync(ticker: str, start_date: str, end_date: str) -> List[Dict[str, Any]]:
    """yfinance를 사용하여 특정 종목의 주가 데이터를 동기적으로 조회합니다."""
    logger.info(f"--- [Tool] 주가 데이터 조회 (Sync): {ticker} from {start_date} to {end_date} ---")
    try:
        stock = yf.Ticker(ticker)
        history = stock.history(start=start_date, end=end_date, repair=True)
        
        history.reset_index(inplace=True)
        
        # 'Date' 열이 확실하게 datetime 형식이 되도록 명시적으로 변환합니다.
        history['Date'] = pd.to_datetime(history['Date']).dt.tz_localize(None)
        
        # 이제 .dt 접근자를 안전하게 사용할 수 있습니다.
        history['Date'] = history['Date'].dt.strftime('%Y-%m-%d')
        
        if not history.empty:
            return history.to_dict('records')
        else:
            logger.warning(f"--- [Tool Warning] yfinance에서 {ticker}에 대한 데이터를 반환하지 않았습니다.")
            return []
            
    except Exception as e:
        logger.error(f"--- [Tool Error] 주가 데이터 조회 중 오류 발생: {e} ---", exc_info=True)
        return []
    
@traceable
async def get_stock_price_async(ticker: str, start_date: str, end_date: str) -> List[Dict[str, Any]]:
    """yfinance를 사용하여 특정 종목의 주가 데이터를 비동기적으로 조회합니다."""
    return await asyncio.to_thread(get_stock_price_sync, ticker, start_date, end_date)

# --- 경제 데이터 조회 도구 ---
@traceable
def get_economic_data_sync(series_id: str, start_date: str, end_date: str) -> List[Dict[str, Any]]:
    """ FRED API를 사용하여 특정 기간의 경제 지표 데이터를 동기적으로 조회합니다."""
    logger.info(f"--- [Tool] 경제 데이터 조회 (Sync): {series_id} from {start_date} to {end_date} ---")
    try:
        # ID를 URL에 맞게 인코딩하는 로직 추가 ---
        # 공백이나 특수문자가 포함된 ID가 생성되더라도 안전하게 처리합니다.
        sanitized_series_id = quote(series_id)

        # 수정된 sanitized_series_id를 사용하여 API를 호출합니다.
        data = fred_client.get_series(sanitized_series_id, observation_start=start_date, observation_end=end_date)
        
        df = data.reset_index()
        df.columns = ['Date', 'Value']
        df['Date'] = df['Date'].dt.strftime('%Y-%m-%d')
        df.dropna(inplace=True)
        return df.to_dict('records')
    except Exception as e:
        # 만약 'EV MKT SHAR'처럼 존재하지 않는 ID라면 여기서 예외가 발생합니다.
        logger.error(f"--- [Tool Error] 경제 데이터 조회 중 오류 발생 (ID: {series_id}): {e} ---")
        return [] # 빈 리스트를 반환하여 파이프라인이 중단되지 않도록 합니다.

@traceable
async def get_economic_data_async(series_id: str, start_date: str, end_date: str) -> List[Dict[str, Any]]:
    """ FRED API를 사용하여 특정 기간의 경제 지표 데이터를 비동기적으로 조회합니다."""
    return await asyncio.to_thread(get_economic_data_sync, series_id, start_date, end_date)
    
# perform_web_search 함수를 LangChain Tool로 포장합니다.
web_search_tool = Tool(
    name="web_search",
    description="최신 뉴스, 시장 동향, 특정 주제에 대한 최신 정보 등 실시간 정보가 필요할 때 사용하는 웹 검색 도구입니다.",
    func=perform_web_search_sync,
    coroutine=perform_web_search_async
)

stock_price_tool = Tool(
    name="get_stock_price",
    description="주식 티커(ticker)와 기간(start_date, end_date)을 사용하여 특정 종목의 과거 주가 데이터를 조회할 때 사용합니다. (예: 'TSLA', '2023-01-01', '2023-12-31')",
    func=get_stock_price_sync,
    coroutine=get_stock_price_async
)

economic_data_tool = Tool(
    name="get_economic_data",
    description="미국의 주요 거시 경제 지표(예: 소비자물가지수, 실업률, GDP, 기준금리)를 조회할 때 사용합니다. FRED 데이터베이스의 시리즈 ID를 인자로 받습니다. (예: 'CPIAUCSL', 'UNRATE', 'FEDFUNDS')",
    func=get_economic_data_sync,
    coroutine=get_economic_data_async
)

# 사용 가능한 모든 도구를 딕셔너리 형태로 관리
available_tools = {
    "web_search": web_search_tool,
    "get_stock_price": stock_price_tool,
    "get_economic_data": economic_data_tool,
}