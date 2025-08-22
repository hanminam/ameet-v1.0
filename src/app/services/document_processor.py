# src/app/services/document_processor.py

import io
from fastapi import UploadFile
import pypdf # PDF 처리를 위한 라이브러리

async def extract_text_from_txt(file: UploadFile) -> str:
    """UploadFile (TXT)에서 텍스트를 추출합니다."""
    contents = await file.read()
    return contents.decode("utf-8")

async def extract_text_from_pdf(file: UploadFile) -> str:
    """UploadFile (PDF)에서 텍스트를 추출합니다."""
    contents = await file.read()
    pdf_reader = pypdf.PdfReader(io.BytesIO(contents))
    text = ""
    for page in pdf_reader.pages:
        # 페이지에서 텍스트를 추출하고, 내용이 없는 경우 빈 문자열을 더합니다.
        text += page.extract_text() or ""
    return text

async def process_uploaded_file(file: UploadFile) -> str:
    """
    업로드된 파일을 MIME 타입에 따라 처리하여 텍스트를 추출합니다.
    """
    content_type = file.content_type
    if content_type == "text/plain":
        return await extract_text_from_txt(file)
    elif content_type == "application/pdf":
        return await extract_text_from_pdf(file)
    else:
        # MVP 단계에서는 지원하지 않는 파일 형식에 대해 에러를 발생시킵니다.
        raise ValueError(f"Unsupported file type: {content_type}")