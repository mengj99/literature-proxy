from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from venue_db import lookup_venue
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

def classify_article_kind(title: str, crossref_type: str | None, openalex_type: str | None) -> str:
    """粗分类：review / survey / original_research / other"""
    t = (title or "").lower()

    # 标题关键词判断（最强信号）
    review_keywords = ["review", "survey", "systematic review", "meta-analysis", "literature review"]
    if any(k in t for k in review_keywords):
        return "review_or_survey"

    # 类型字段里有时也会直接标 review
    ct = (crossref_type or "").lower()
    ot = (openalex_type or "").lower()
    if "review" in ct or "review" in ot:
        return "review_or_survey"

    # 其它都先归为 original_research，之后你可以再细分
    if ct or ot:
        return "original_research"

    return "other"


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
            "/venue_info",       # 你已经测通的
            "/paper_info"
        ]
    }

@app.get("/venue_info")
async def venue_info(venue: str = Query(..., description="Venue short name or full name")):
    found, data = lookup_venue(venue)
    if found:
        return {
            "found": True,
            "match_input": venue,
            **data
        }
    else:
        return {
            "found": False,
            "match_input": venue,
            **data
        }

@app.get("/paper_info")
async def paper_info(doi: str = Query(..., description="DOI of the paper")):
    """综合查询：CrossRef + OpenAlex，返回论文基础信息 + venue类型 + 引用量 + 是否综述"""

    doi = doi.strip()
    if not doi:
        return {"error": "Empty DOI"}

    # --------------------
    # 1. 查询 CrossRef
    # --------------------
    crossref_url = f"https://api.crossref.org/works/{doi}"
    crossref_data = None
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            r = await client.get(crossref_url)
            if r.status_code == 200:
                cr_json = r.json()
                crossref_data = cr_json.get("message", {})
            else:
                crossref_data = {}
        except Exception:
            crossref_data = {}

    # 从 CrossRef 提取一些字段
    cr_title = None
    cr_year = None
    cr_container = None
    cr_type = None
    cr_citations = None

    if crossref_data:
        titles = crossref_data.get("title") or []
        cr_title = titles[0] if titles else None

        issued = crossref_data.get("issued", {})
        date_parts = issued.get("date-parts", [])
        if date_parts and len(date_parts[0]) > 0:
            cr_year = date_parts[0][0]

        containers = crossref_data.get("container-title") or []
        cr_container = containers[0] if containers else None

        cr_type = crossref_data.get("type")
        cr_citations = crossref_data.get("is-referenced-by-count")

    # --------------------
    # 2. 查询 OpenAlex
    # --------------------
    openalex_url = f"https://api.openalex.org/works/https://doi.org/{doi}"
    oa_data = None
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            r = await client.get(openalex_url)
            if r.status_code == 200:
                oa_data = r.json()
            else:
                oa_data = {}
        except Exception:
            oa_data = {}

    oa_type = None
    oa_citations = None
    oa_host_type = None
    oa_id = None

    if oa_data:
        oa_type = oa_data.get("type")
        oa_citations = oa_data.get("cited_by_count")
        host_venue = oa_data.get("host_venue") or {}
        oa_host_type = host_venue.get("type")  # journal / conference / repository
        oa_id = oa_data.get("id")

    # --------------------
    # 3. 决定 venue_type（会/刊）
    # --------------------
    venue_type = "other"

    # 优先用 OpenAlex host_venue.type
    if oa_host_type:
        if oa_host_type == "journal":
            venue_type = "journal"
        elif oa_host_type == "conference":
            venue_type = "conference"

    # 备用：看 CrossRef/OpenAlex 的 type
    ct = (cr_type or "").lower()
    ot = (oa_type or "").lower()

    if venue_type == "other":
        if "journal-article" in ct or "journal-article" in ot:
            venue_type = "journal"
        elif "proceedings-article" in ct or "proceedings-article" in ot:
            venue_type = "conference"

    # --------------------
    # 4. 决定 article_kind（综述 or 研究）
    # --------------------
    article_kind = classify_article_kind(cr_title or "", cr_type, oa_type)

    # --------------------
    # 5. 决定引用量
    # --------------------
    # 优先用 OpenAlex 的 cited_by_count
    citation_count = oa_citations if oa_citations is not None else cr_citations

    return {
        "doi": doi,
        "title": cr_title,
        "year": cr_year,
        "container_title": cr_container,
        "venue_type": venue_type,          # conference / journal / other
        "article_kind": article_kind,      # review_or_survey / original_research / other
        "citation_count": citation_count,
        "sources": {
            "crossref_type": cr_type,
            "crossref_citation_count": cr_citations,
            "openalex_type": oa_type,
            "openalex_host_venue_type": oa_host_type,
            "openalex_id": oa_id,
        }
    }
