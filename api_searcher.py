import aiohttp
import asyncio
import os
import re
import requests
from urllib.parse import quote
from bs4 import BeautifulSoup
from googletrans import Translator

TMDB_API_KEY = os.getenv("TMDB_API")
translator = Translator()

def _is_blocked_or_challenge(html: str) -> bool:
    h = (html or "").lower()
    return any(k in h for k in [
        "cloudflare",
        "captcha",
        "checking your browser",
        "just a moment",
        "enable javascript",
        "bot detection",
    ])


def _extract_namu_title(soup: BeautifulSoup, html: str) -> str | None:
    # 1) OG title/meta
    og = soup.select_one('meta[property="og:title"]')
    if og and og.get("content"):
        return og["content"].strip()

    # 2) twitter title/meta
    tw = soup.select_one('meta[name="twitter:title"]')
    if tw and tw.get("content"):
        return tw["content"].strip()

    # 3) h1 계열(구버전/신버전 대비)
    for sel in ["h1.wiki-title", "h1", "header h1", ".wiki-heading h1", ".title h1"]:
        el = soup.select_one(sel)
        if el:
            t = el.get_text(" ", strip=True)
            if t:
                return t

    # 4) <title> 태그 fallback
    ttag = soup.title.get_text(" ", strip=True) if soup.title else None
    if ttag:
        # 보통 "문서명 - 나무위키" 이런 형태라 잘라줌
        ttag = re.sub(r"\s*-\s*나무위키\s*$", "", ttag).strip()
        if ttag:
            return ttag

    return None


async def scrape_google_search_info(query, content_type="만화"):
    """검색 결과에서 제목, 작가 정보 추출 (나무위키 → 위키백과 → 구글 순서)"""
    try:
        print(f"[DEBUG] scrape_google_search_info() 시작 - query: {query}, content_type: {content_type}")
        await asyncio.sleep(1)  # rate limit 방지
        loop = asyncio.get_event_loop()

        def _scrape():
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }

            # 1차 시도: 나무위키 직접 접근 (가장 빠름)
            print(f"[DEBUG] [1차] 나무위키에서 '{query}' 검색 시작...")
            namu_result = _scrape_namu_wiki(query, headers)
            if namu_result:
                print(f"[DEBUG] [1차] 나무위키 성공: {namu_result}")
                return namu_result
            print(f"[DEBUG] [1차] 나무위키 실패")

            # 2차 시도: 위키백과 API
            print(f"[DEBUG] [2차] 위키백과에서 '{query}' 검색 시작...")
            wiki_result = _scrape_wikipedia(query, headers)
            if wiki_result:
                print(f"[DEBUG] [2차] 위키백과 성공: {wiki_result}")
                return wiki_result
            print(f"[DEBUG] [2차] 위키백과 실패")

            print(f"[DEBUG] scrape_google_search_info() 반환값 None")
            return None

        result = await loop.run_in_executor(None, _scrape)
        return result

    except Exception as e:
        print(f"❌ 스크래핑 에러: {e}")
        return None


def _scrape_namu_wiki(query, headers):
    try:
        # 공백/특수문자 안전하게 인코딩
        safe_query = quote(query, safe="")
        url = f"https://namu.wiki/w/{safe_query}"
        print(f"[DEBUG] _scrape_namu_wiki() URL: {url}")

        response = requests.get(url, headers=headers, timeout=10, allow_redirects=True)
        print(f"[DEBUG] _scrape_namu_wiki() 응답 상태: {response.status_code}")

        if response.status_code == 404:
            print(f"[DEBUG] _scrape_namu_wiki() 404 Not Found")
            return None
        if response.status_code != 200:
            print(f"[DEBUG] _scrape_namu_wiki() 상태 오류: {response.status_code}")
            return None

        html = response.text
        if _is_blocked_or_challenge(html):
            print("[DEBUG] _scrape_namu_wiki() Cloudflare/봇 차단 감지")
            # 여기서 title 못뽑는 게 정상임(문서 HTML이 아님)
            return None

        soup = BeautifulSoup(html, "html.parser")

        title = _extract_namu_title(soup, html)
        print(f"[DEBUG] _scrape_namu_wiki() 제목 추출: {title}")
        if not title:
            print(f"[DEBUG] _scrape_namu_wiki() 제목 추출 실패")
            return None

        # 작가/저자: 테이블 클래스가 계속 바뀌어서 여러 후보로
        author = None
        year = None

        # infobox 후보들
        info_box = (
            soup.select_one("table.wikitable") or
            soup.select_one("table.wiki-table") or
            soup.select_one("table")  # 최후 fallback(너무 넓으면 제거)
        )

        if info_box:
            for row in info_box.select("tr"):
                cells = row.find_all(["th", "td"])
                if len(cells) >= 2:
                    label = cells[0].get_text(" ", strip=True).lower()
                    value = cells[1].get_text(" ", strip=True)

                    if any(k in label for k in ["작가", "저자", "원작", "작화", "각본", "감독"]):
                        author = value
                        print(f"[DEBUG] _scrape_namu_wiki() 작가 추출: {author}")
                        break

        if not author:
            print(f"[DEBUG] _scrape_namu_wiki() 작가 못 찾음")

        # 연도: 본문 전체에서 첫 20xx 찾기(너무 잘못 잡히면 인포박스 쪽으로 제한 가능)
        year_match = re.search(r"(20\d{2})", html)
        if year_match:
            year = year_match.group(1)
            print(f"[DEBUG] _scrape_namu_wiki() 연도 추출: {year}")
        else:
            print(f"[DEBUG] _scrape_namu_wiki() 연도 못 찾음")

        result = {
            "title": title,
            "author": author or "정보 없음",
            "year": year,
            "img_url": None,
            "source": "나무위키",
        }
        print(f"[DEBUG] _scrape_namu_wiki() 완료 - 반환: {result}")
        return result

    except Exception as e:
        print(f"[ERROR] _scrape_namu_wiki() 실패: {e}")
        return None


def _clean_wikitext_minimal(wt: str) -> str:
    """
    위키텍스트에서 작가/연도 추출을 위해 최소한의 노이즈만 제거.
    (완벽한 파서가 아니라 '추출용'으로만)
    """
    if not wt:
        return ""

    t = wt

    # 주석 제거
    t = re.sub(r"<!--.*?-->", " ", t, flags=re.DOTALL)

    # ref 태그 제거
    t = re.sub(r"<ref[^>]*>.*?</ref>", " ", t, flags=re.DOTALL)
    t = re.sub(r"<ref[^/>]*/\s*>", " ", t)

    # 템플릿/테이블 등 너무 복잡한 것 일부 완화(과도 제거는 역효과라 최소)
    # 링크 [[A|B]] -> B, [[A]] -> A
    t = re.sub(r"\[\[([^|\]]+)\|([^\]]+)\]\]", r"\2", t)
    t = re.sub(r"\[\[([^\]]+)\]\]", r"\1", t)

    # 외부링크 [http://... 라벨] -> 라벨
    t = re.sub(r"\[https?://[^\s\]]+\s+([^\]]+)\]", r"\1", t)

    # 굵게/기울임 마크업 제거
    t = t.replace("'''", "").replace("''", "")

    # 남은 태그 제거
    t = re.sub(r"<[^>]+>", " ", t)

    # 공백 정리
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _extract_field_from_infobox(wikitext: str, keys):
    """
    인포박스/템플릿에서 ' | 키 = 값 ' 형태를 우선 추출.
    keys: ['작가', '저자', ...]
    """
    if not wikitext:
        return None

    # 인포박스가 명시된 경우가 많지만 템플릿 이름이 다양해서 '키=' 라인을 직접 찾는 방식
    # 예: | 작가 = 우라나 케이
    #     | 저자 = ...
    for k in keys:
        # 줄 단위에서 안정적으로 찾기 위해 line anchor 사용
        m = re.search(rf"(?m)^\s*\|\s*{re.escape(k)}\s*=\s*(.+?)\s*$", wikitext)
        if m:
            value = m.group(1).strip()
            # 값 끝에 주석/템플릿/ref 등이 붙을 수 있으니 간단히 컷
            value = re.split(r"<ref|{{|}}|\[\[분류:|\[\[Category:", value)[0].strip()
            # 링크 [[A|B]] 같은 경우는 최소 치환
            value = re.sub(r"\[\[([^|\]]+)\|([^\]]+)\]\]", r"\2", value)
            value = re.sub(r"\[\[([^\]]+)\]\]", r"\1", value)
            return value[:80]
    return None


def _extract_year_from_text(text: str):
    if not text:
        return None
    m = re.search(r"(20\d{2})\s*년?", text)
    return m.group(1) if m else None


def _extract_author_from_text(text: str):
    """
    인포박스에서 못 찾았을 때 본문 텍스트에서 휴리스틱 추출
    """
    if not text:
        return None

    t = " ".join(text.split())

    patterns = [
        r'([가-힣A-Za-z·\s]+?)가\s+(?:쓰고\s+그린|그린|쓴)\s+(?:일본\s+)?(?:만화|소설|작품)',
        r'([가-힣A-Za-z·\s]+?)의\s+(?:일본\s+)?(?:만화|소설|작품)',
        r'(?:작가|저자|원작|글|각본|작화|감독)\s*[:：]\s*([가-힣A-Za-z·\s]+)',
        r'(?:작가|저자|원작|글|각본|작화|감독)\s+([가-힣A-Za-z·\s]+)',
    ]
    for p in patterns:
        m = re.search(p, t)
        if m:
            return m.group(1).strip()[:60]
    return None


def _pick_first_non_missing_page(pages: dict):
    # pages는 {"-1": {...missing...}} 같은 게 올 수 있어서 non-missing을 골라야 함
    for p in pages.values():
        if isinstance(p, dict) and "missing" not in p:
            return p
    return None

def _normalize_key(s: str) -> str:
    return re.sub(r"\s+", "", (s or "")).lower()

def _resolve_exact_title(api: str, query: str, headers: dict):
    params = {
        "action": "query",
        "format": "json",
        "titles": query,
        "redirects": 1,  # 넘겨주기 처리
    }
    data = requests.get(api, params=params, headers=headers, timeout=5).json()
    pages = data.get("query", {}).get("pages", {})
    page = _pick_first_non_missing_page(pages)
    if not page:
        return None
    return page.get("title"), page.get("pageid")

def _scrape_wikipedia(query: str, headers: dict, allow_search_fallback: bool = False):
    try:
        print(f"[DEBUG] _scrape_wikipedia() 시작 - query: {query}")
        api = "https://ko.wikipedia.org/w/api.php"

        # 0) 정확 제목(또는 리다이렉트) 먼저 확인
        resolved = _resolve_exact_title(api, query, headers)
        if resolved:
            title, pageid = resolved
            print(f"[DEBUG] _scrape_wikipedia() 정확 제목 찾음: title={title}, pageid={pageid}")
        else:
            print(f"[DEBUG] _scrape_wikipedia() 정확 제목 못 찾음, allow_search_fallback={allow_search_fallback}")
            if not allow_search_fallback:
                return None

            # 0-b) (옵션) 검색 fallback: 이 경우는 "정확 문서"가 아니라 "관련 문서"일 수 있음
            search_params = {
                "action": "query",
                "list": "search",
                "srsearch": query,
                "format": "json",
                "srlimit": 1,
            }
            data = requests.get(api, params=search_params, headers=headers, timeout=5).json()
            results = data.get("query", {}).get("search", [])
            if not results:
                print(f"[DEBUG] _scrape_wikipedia() 검색 결과 없음")
                return None

            title = results[0].get("title")
            pageid = results[0].get("pageid")
            if not title or not pageid:
                print(f"[DEBUG] _scrape_wikipedia() title/pageid 없음")
                return None

            # 너무 엉뚱한 문서 컷(원하면 완화 가능)
            if _normalize_key(title) != _normalize_key(query):
                print(f"[DEBUG] _scrape_wikipedia() 다른 문서 감지: {title}")
                return None

            print(f"[DEBUG] _scrape_wikipedia() 검색 결과: title={title}, pageid={pageid}")

        # 1) 통짜 위키텍스트
        content_params = {
            "action": "query",
            "format": "json",
            "pageids": pageid,
            "prop": "revisions",
            "rvslots": "main",
            "rvprop": "content",
            "redirects": 1,
        }
        data2 = requests.get(api, params=content_params, headers=headers, timeout=5).json()
        pages2 = data2.get("query", {}).get("pages", {})
        page = pages2.get(str(pageid)) or _pick_first_non_missing_page(pages2)
        if not page or "missing" in page:
            return None

        revs = page.get("revisions", [])
        if not revs:
            return None

        wikitext = revs[0].get("slots", {}).get("main", {}).get("*") or revs[0].get("*")
        if not wikitext:
            print(f"[DEBUG] _scrape_wikipedia() 위키텍스트 추출 실패")
            return None
        print(f"[DEBUG] _scrape_wikipedia() 위키텍스트 추출 성공 (길이: {len(wikitext)})")

        # 2) 썸네일
        img_params = {
            "action": "query",
            "format": "json",
            "pageids": pageid,
            "prop": "pageimages",
            "piprop": "thumbnail",
            "pithumbsize": 400,
            "redirects": 1,
        }
        data3 = requests.get(api, params=img_params, headers=headers, timeout=5).json()
        pages3 = data3.get("query", {}).get("pages", {})
        page3 = pages3.get(str(pageid)) or _pick_first_non_missing_page(pages3)
        img_url = (page3.get("thumbnail") or {}).get("source") if page3 else None
        print(f"[DEBUG] _scrape_wikipedia() 썸네일 URL: {img_url}")

        # 3) 작가/연도(네 함수들 그대로 사용)
        author = _extract_field_from_infobox(wikitext, keys=["작가", "저자", "원작", "글", "각본", "작화", "감독"])
        year_raw = _extract_field_from_infobox(wikitext, keys=["연도", "출시", "발매", "개봉", "연재 시작", "연재시작", "첫 연재", "첫방송", "방영 시작"])
        year = _extract_year_from_text(year_raw) if year_raw else None

        cleaned = _clean_wikitext_minimal(wikitext)
        if not author:
            author = _extract_author_from_text(cleaned)
        if not year:
            year = _extract_year_from_text(cleaned)

        print(f"[DEBUG] _scrape_wikipedia() 작가 추출: {author}")
        print(f"[DEBUG] _scrape_wikipedia() 연도 추출: {year}")

        result = {
            "title": title,
            "pageid": pageid,
            "author": author or "정보 없음",
            "year": year,
            "img_url": img_url,
        }
        print(f"[DEBUG] _scrape_wikipedia() 완료 - 반환: {result}")
        return result

    except Exception as e:
        print(f"    ⚠️ 위키백과 파싱 실패: {e}")
        return None


def _scrape_google_search(query, content_type, headers):
    """구글 검색 결과에서 정보 추출 (최후의 수단)"""
    try:
        print(f"[DEBUG] _scrape_google_search() 시작 - query: {query}, content_type: {content_type}")
        search_url = f"https://www.google.com/search?q={query}+{content_type}&hl=ko"
        print(f"[DEBUG] _scrape_google_search() 검색 URL: {search_url}")
        response = requests.get(search_url, headers=headers, timeout=5)
        print(f"[DEBUG] _scrape_google_search() 응답 상태: {response.status_code}")

        if response.status_code != 200:
            print(f"[DEBUG] _scrape_google_search() 상태 오류: {response.status_code}")
            return None

        soup = BeautifulSoup(response.text, 'html.parser')

        # 검색 결과 snippet에서 첫 번째 결과 찾기
        search_results = soup.find_all('div', {'class': 'g'})
        print(f"[DEBUG] _scrape_google_search() 검색 결과 개수: {len(search_results)}")

        for idx, result in enumerate(search_results):
            # 제목 찾기
            title_elem = result.find('h3')
            if not title_elem:
                continue

            title = title_elem.get_text(strip=True)
            print(f"[DEBUG] _scrape_google_search() [{idx}] 제목 추출: {title}")

            # snippet에서 추가 정보 추출
            snippet_elem = result.find('div', {'style': '-webkit-line-clamp:2'})
            snippet = snippet_elem.get_text(strip=True) if snippet_elem else ""
            print(f"[DEBUG] _scrape_google_search() [{idx}] snippet: {snippet[:100]}...")

            # 작가 정보 추출 시도
            author = None
            if '작가' in snippet or '저자' in snippet:
                parts = snippet.split('작가')[-1] if '작가' in snippet else snippet.split('저자')[-1]
                author = parts.split(',')[0].strip()[:50]
                print(f"[DEBUG] _scrape_google_search() [{idx}] 작가 추출: {author}")

            if title:  # 제목이 있으면 반환
                result_dict = {
                    'title': title,
                    'author': author or "정보 없음",
                    'year': None,
                    'img_url': None,
                    'source': '구글 검색'
                }
                print(f"[DEBUG] _scrape_google_search() 완료 - 반환: {result_dict}")
                return result_dict

        print(f"[DEBUG] _scrape_google_search() 반환값 없음")
        return None

    except Exception as e:
        print(f"[ERROR] _scrape_google_search() 실패: {e}")
        return None

async def is_korean(text):
    """한글이 포함되어 있는지 확인"""
    if not text:
        return False
    return bool(re.search('[가-힣]', text))


async def translate_to_korean(text):
    """영어/일본어 이름을 한국어로 번역"""
    if not text or text == "N/A" or await is_korean(text):
        return text

    try:
        result = await translator.translate(text, dest='ko')
        return result.text
    except Exception as e:
        print(f"Google Translate failed: {e}")
        # 번역 실패 시 원본 반환
        return text
    
async def translate_to_english(text):
    if not text or text == "N/A":
        return text

    try:
        result = await translator.translate(text, dest='en')
        return result.text
    except Exception as e:
        print(f"Google Translate failed: {e}")
        # 번역 실패 시 원본 반환
        return text

class ContentSearcher:
    """영화, 만화, 웹툰 검색 통합 클래스"""

    @staticmethod
    async def _search_tmdb_direct(session, name):
        """TMDB에서 직접 검색 (내부용)"""
        search_url = f"https://api.themoviedb.org/3/search/multi?api_key={TMDB_API_KEY}&query={name}&language=ko-KR"
        async with session.get(search_url) as response:
            data = await response.json()

        if data.get('results'):
            results = [r for r in data['results'] if r.get('media_type') in ('movie', 'tv')]
            if not results:
                return name, "N/A", "N/A", None, "movie"

            item = results[0]
            media_type = item.get('media_type')
            genre_ids = item.get('genre_ids', [])

            is_animation = 16 in genre_ids
            if is_animation:
                category = 'anime'
            elif media_type == 'tv':
                category = 'drama'
            else:
                category = 'movie'

            if media_type == 'movie':
                title = item.get('title', name)
                year = item['release_date'][:4] if item.get('release_date') else "N/A"
            else:
                title = item.get('name', name)
                year = item['first_air_date'][:4] if item.get('first_air_date') else "N/A"

            item_id = item['id']
            director = None

            if not await is_korean(title):
                title = await translate_to_korean(title)

            if media_type == 'movie':
                credits_url = f"https://api.themoviedb.org/3/movie/{item_id}/credits?api_key={TMDB_API_KEY}&language=ko-KR"
                async with session.get(credits_url) as credits_response:
                    credits = await credits_response.json()
                director_info = next((crew for crew in credits.get('crew', []) if crew['job'] == 'Director'), None)

                if director_info:
                    director = director_info.get('name')
                    if not await is_korean(director):
                        director = await translate_to_korean(director)
            else:
                details_url = f"https://api.themoviedb.org/3/tv/{item_id}?api_key={TMDB_API_KEY}&language=ko-KR"
                async with session.get(details_url) as details_response:
                    details = await details_response.json()
                creators = details.get('created_by', [])
                if creators:
                    director = creators[0]['name']
                    if not await is_korean(director):
                        director = await translate_to_korean(director)

            poster_path = item.get('poster_path')
            img_url = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else None

            return title, year, director, img_url, category

        return None, None, None, None, None

    @staticmethod
    async def search_tmdb(session, name):
        """TMDB multi search API로 영화/드라마/애니 검색 및 자동 분류 (Google fallback 포함)"""
        print(f"[DEBUG] search_tmdb() 시작 - name: {name}")

        # 1차: 직접 검색
        print(f"[DEBUG] search_tmdb() [1차] TMDB 직접 검색 시도...")
        result = await ContentSearcher._search_tmdb_direct(session, name)

        # 검색 성공 시 반환
        if result[0] is not None:
            print(f"[DEBUG] search_tmdb() [1차] 성공 - 반환: title={result[0]}, year={result[1]}, director={result[2]}, category={result[4]}")
            return result

        print(f"[DEBUG] search_tmdb() [1차] 실패")

        # 2차: Google 스크래핑으로 정보 추출
        print(f"[DEBUG] search_tmdb() [2차] Google 스크래핑 시도...")
        google_info = await scrape_google_search_info(name, "영화")

        if google_info and google_info.get('title'):
            print(f"[DEBUG] search_tmdb() [2차] 성공 - 제목: {google_info['title']}, 감독: {google_info.get('author')}")
            return google_info['title'], google_info.get('year'), google_info.get('author'), None, 'movie'

        print(f"[DEBUG] search_tmdb() [2차] 실패")

        # 3차: 번역 후 재검색
        print(f"[DEBUG] search_tmdb() [3차] 영문 번역 시도...")
        translated = await translate_to_english(name)
        if translated and translated != name:
            print(f"[DEBUG] search_tmdb() [3차] 번역 성공: {translated} -> TMDB 재검색...")
            result = await ContentSearcher._search_tmdb_direct(session, translated)
            if result[0] is not None:
                print(f"[DEBUG] search_tmdb() [3차] 성공 - 반환: title={result[0]}, year={result[1]}, director={result[2]}, category={result[4]}")
                return result
            print(f"[DEBUG] search_tmdb() [3차] TMDB 재검색 실패")
        else:
            print(f"[DEBUG] search_tmdb() [3차] 번역 실패 또는 동일: {translated}")

        print(f"[DEBUG] search_tmdb() 완료 - 반환값 없음")
        return None, None, None, None, None

    @staticmethod
    async def _search_manga_direct(session, name):
        """MangaDex에서 직접 검색 (내부용)"""
        url = f"https://api.mangadex.org/manga?title={name}&limit=1&includes[]=author&includes[]=cover_art"

        try:
            async with session.get(url) as response:
                data = await response.json()

            if data.get('data') and len(data['data']) > 0:
                manga = data['data'][0]
                attributes = manga.get('attributes', {})
                title_dict = attributes.get('title', {})
                alt_titles = attributes.get('altTitles', [])

                title = None
                # 1. title 객체에서 한국어 제목 찾기
                if 'ko' in title_dict:
                    title = title_dict['ko']

                # 2. altTitles에서 한국어 제목 찾기
                if not title:
                    for alt in alt_titles:
                        if 'ko' in alt:
                            title = alt['ko']
                            break

                # 3. title 객체에서 영어 제목 찾기
                if not title and 'en' in title_dict:
                    title = title_dict['en']

                # 4. 그래도 없으면 첫번째 제목 사용
                if not title:
                    title = list(title_dict.values())[0] if title_dict else name

                year = str(attributes.get('year')) if attributes.get('year') else None
                author = None
                relationships = manga.get('relationships', [])
                for rel in relationships:
                    if rel.get('type') == 'author':
                        author_attrs = rel.get('attributes', {})
                        author = author_attrs.get('name')
                        if author and not await is_korean(author):
                            author = await translate_to_korean(author)
                        break

                img_url = None
                for rel in relationships:
                    if rel.get('type') == 'cover_art':
                        cover_attrs = rel.get('attributes', {})
                        filename = cover_attrs.get('fileName')
                        if filename:
                            manga_id = manga.get('id')
                            img_url = f"https://uploads.mangadex.org/covers/{manga_id}/{filename}"
                            print(f"이미지 정보: {img_url}")
                        break
                print(f"망가덱스에서 가져온 정보 - 제목: {title}, 년도: {year}, 작가: {author}")
                return title, year, author, img_url

        except Exception as e:
            print(f"❌ MangaDex API error: {e}")

        return None, None, None, None

    @staticmethod
    async def search_manga(session, name):
        """MangaDex에서 만화 검색 (한국어 제목 없으면 Google 스크래핑)"""
        print(f"[DEBUG] search_manga() 시작 - name: {name}")
        original_name = name

        # 1차: 영어로 번역 후 검색
        print(f"[DEBUG] search_manga() [1차] 영문 번역 시도...")
        translated_name = await translate_to_english(name)
        print(f"[DEBUG] search_manga() [1차] 번역됨: {translated_name}")
        result = await ContentSearcher._search_manga_direct(session, translated_name)
        print(f"[DEBUG] search_manga() [1차] MangaDex 검색 결과: {result}")

        # 한국어 제목이 있으면 반환
        if result[0] is not None and await is_korean(result[0]):
            print(f"[DEBUG] search_manga() [1차] 한국어 제목 발견 - 반환: title={result[0]}, year={result[1]}, author={result[2]}")
            return result

        print(f"[DEBUG] search_manga() [1차] 한국어 제목 없음")

        # 2차: Google 스크래핑으로 정보 추출
        print(f"[DEBUG] search_manga() [2차] Google 스크래핑 시도...")
        google_info = await scrape_google_search_info(original_name, "만화")

        if google_info and google_info.get('title'):
            print(f"[DEBUG] search_manga() [2차] 성공 - 제목: {google_info['title']}, 작가: {google_info.get('author')}")
            # 이미지는 원래 MangaDex 결과가 있으면 사용, 없으면 None
            img_url = result[3] if result and len(result) > 3 else None
            print(f"[DEBUG] search_manga() [2차] 이미지 URL: {img_url or google_info.get('img_url')}")
            year = google_info.get('year') or (result[1] if result and len(result) > 1 else None)
            author = google_info.get('author') or (result[2] if result and len(result) > 2 else None)
            final_result = (google_info['title'], year, author, (img_url or google_info.get('img_url')))
            print(f"[DEBUG] search_manga() 완료 - 반환: {final_result}")
            return final_result

        print(f"[DEBUG] search_manga() [2차] 실패")
        print(f"[DEBUG] search_manga() 완료 - 반환값 없음")
        return None, None, None, None

    @staticmethod
    async def _search_naver_webtoon(session, name):
        """네이버 웹툰에서 직접 검색 (내부용)"""
        print(f"[DEBUG] _search_naver_webtoon() 시작 - name: {name}")
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }

        try:
            search_url = f"https://comic.naver.com/api/search/all?keyword={name}"
            print(f"[DEBUG] _search_naver_webtoon() 검색 URL: {search_url}")
            async with session.get(search_url, headers=headers) as response:
                print(f"[DEBUG] _search_naver_webtoon() 응답 상태: {response.status}")
                if response.status == 200:
                    data = await response.json()
                    webtoons = data.get('searchWebtoonResult', {}).get('searchViewList', [])
                    print(f"[DEBUG] _search_naver_webtoon() 검색 결과 개수: {len(webtoons)}")

                    if webtoons:
                        webtoon = webtoons[0]
                        title = webtoon.get('titleName', name)
                        author = webtoon.get('displayAuthor')
                        img_url = webtoon.get('thumbnailUrl')
                        print(f"[DEBUG] _search_naver_webtoon() 완료 - title: {title}, author: {author}")

                        return title, "네이버웹툰", author, img_url
                else:
                    print(f"[DEBUG] _search_naver_webtoon() 상태 오류: {response.status}")
        except Exception as e:
            print(f"[ERROR] _search_naver_webtoon() 실패: {e}")

        print(f"[DEBUG] _search_naver_webtoon() 반환값 없음")
        return None, None, None, None

    @staticmethod
    async def search_webtoon(session, name):
        """웹툰 검색 (네이버 → 카카오 → Google 스크래핑)"""
        print(f"[DEBUG] search_webtoon() 시작 - name: {name}")

        # 1차: 네이버 웹툰 검색
        print(f"[DEBUG] search_webtoon() [1차] 네이버 웹툰 검색...")
        result = await ContentSearcher._search_naver_webtoon(session, name)
        if result[0] is not None:
            print(f"[DEBUG] search_webtoon() [1차] 성공 - 반환: {result}")
            return result

        print(f"[DEBUG] search_webtoon() [1차] 실패")

        # 2차: Google 스크래핑으로 웹툰 정보 추출
        print(f"[DEBUG] search_webtoon() [2차] Google 스크래핑 시도...")
        google_info = await scrape_google_search_info(name, "웹툰")

        if google_info and google_info.get('title'):
            print(f"[DEBUG] search_webtoon() [2차] 성공 - 제목: {google_info['title']}, 작가: {google_info.get('author')}")
            final_result = (google_info['title'], "Google 검색", google_info.get('author'), None)
            print(f"[DEBUG] search_webtoon() 완료 - 반환: {final_result}")
            return final_result

        print(f"[DEBUG] search_webtoon() [2차] 실패")
        print(f"[DEBUG] search_webtoon() 완료 - 반환값 없음")
        return None, None, None, None
