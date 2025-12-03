from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import httpx

app = FastAPI(
    title="Private Literature Proxy",
    description="A lightweight proxy for academic search using CrossRef.",
    version="0.1.0",
    servers=[{"url": "https://literature-proxy.onrender.com"}],
)


# 允许跨域，方便以后前端或 GPT 调用
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 以后想限制来源可以改
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def extract_year_from_item(item: dict):
    """
    从 CrossRef 返回结果中提取年份。
    """
    issued = item.get("issued", {})
    parts = issued.get("date-parts", [])
    if parts and len(parts[0]) > 0:
        return parts[0][0]
    return None

@app.get("/search_crossref")
async def search_crossref(
    query: str = Query(..., description="搜索关键词，例如 'virtual reality nausea'"),
    rows: int = Query(10, ge=1, le=50, description="返回条数，1-50"),
):
    """
    使用 CrossRef 搜索文献。
    返回简化后的文献信息列表。
    """
    url = "https://api.crossref.org/works"
    params = {"query": query, "rows": rows}

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"CrossRef 请求失败: {e}")

    data = resp.json()
    items = data.get("message", {}).get("items", [])

    results = []
    for item in items:
        results.append({
            "title": item.get("title", [""])[0],
            "doi": item.get("DOI"),
            "year": extract_year_from_item(item),
            "container_title": item.get("container-title", [""])[0],
            "publisher": item.get("publisher"),
            "url": item.get("URL"),
        })

    return {
        "query": query,
        "count": len(results),
        "results": results,
    }

@app.get("/bibtex_from_doi")
async def bibtex_from_doi(
    doi: str = Query(..., description="文献 DOI，例如 '10.1145/3332165.3347899'")
):
    """
    通过 CrossRef 把 DOI 转换为 BibTeX。
    """
    url = f"https://api.crossref.org/works/{doi}/transform/application/x-bibtex"

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url)

    if resp.status_code != 200:
        raise HTTPException(
            status_code=resp.status_code,
            detail=f"获取 BibTeX 失败，状态码: {resp.status_code}",
        )

    return {
        "doi": doi,
        "bibtex": resp.text,
    }

@app.get("/")
async def root():
    return {
        "message": "Private Literature Proxy is running.",
        "endpoints": [
            "/search_crossref",
            "/bibtex_from_doi",
        ],
    }
