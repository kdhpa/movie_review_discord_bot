import aiohttp
import asyncio
import os
import re
import requests
from bs4 import BeautifulSoup
from googletrans import Translator

TMDB_API_KEY = os.getenv("TMDB_API")
translator = Translator()


async def scrape_google_search_info(query, content_type="만화"):
    """검색 결과에서 제목, 작가 정보 추출 (나무위키 → 위키백과 → 구글 순서)"""
    try:
        await asyncio.sleep(1)  # rate limit 방지
        loop = asyncio.get_event_loop()

        def _scrape():
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }

            # 1차 시도: 나무위키 직접 접근 (가장 빠름)
            print(f"  [1] 나무위키에서 '{query}' 검색 중...")
            namu_result = _scrape_namu_wiki(query, headers)
            if namu_result:
                return namu_result

            # 2차 시도: 위키백과 API
            print(f"  [2] 위키백과에서 '{query}' 검색 중...")
            wiki_result = _scrape_wikipedia(query, headers)
            if wiki_result:
                return wiki_result

            # 3차 시도: 구글 검색 (느리지만 최후의 수단)
            print(f"  [3] 구글에서 '{query} {content_type}' 검색 중...")
            google_result = _scrape_google_search(query, content_type, headers)
            if google_result:
                return google_result

            return None

        result = await loop.run_in_executor(None, _scrape)
        return result

    except Exception as e:
        print(f"❌ 스크래핑 에러: {e}")
        return None


def _scrape_namu_wiki(query, headers):
    """나무위키에서 정보 추출"""
    try:
        url = f"https://namu.wiki/w/{query}"
        response = requests.get(url, headers=headers, timeout=5)

        if response.status_code == 404:
            return None

        if response.status_code != 200:
            return None

        soup = BeautifulSoup(response.text, 'html.parser')

        # 제목 추출
        title_elem = soup.find('h1', {'class': 'wiki-title'})
        if not title_elem:
            return None

        title = title_elem.get_text(strip=True)

        # 작가/저자 정보 추출 (정보 박스에서)
        author = None
        year = None

        # 정보 박스 찾기
        info_box = soup.find('table', {'class': 'wikitable'})
        if info_box:
            rows = info_box.find_all('tr')
            for row in rows:
                cells = row.find_all('td')
                if len(cells) >= 2:
                    label = cells[0].get_text(strip=True).lower()
                    value = cells[1].get_text(strip=True)

                    # 작가/저자/원작 찾기
                    if any(k in label for k in ['작가', '저자', '원작', '작화', '각본']):
                        if not author:
                            author = value
                            break

        # 연도 정규식으로 추출
        year_match = re.search(r'(20\d{2})', response.text)
        if year_match:
            year = year_match.group(1)

        return {
            'title': title,
            'author': author or "정보 없음",
            'year': year,
            'img_url': None,
            'source': '나무위키'
        }

    except Exception as e:
        print(f"    ⚠️ 나무위키 파싱 실패: {e}")
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


def _scrape_wikipedia(query: str, headers: dict):
    """
    위키백과(ko)에서:
      1) search로 pageid/title 확보
      2) pageid로 revisions(content) = 통짜 위키텍스트 가져오기 (extracts 미사용)
      3) pageimages로 썸네일 가져오기
      4) 위키텍스트 기반으로 작가/연도 추출
    """
    try:
        api = "https://ko.wikipedia.org/w/api.php"

        # 1) 검색 -> pageid/title
        search_params = {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "format": "json",
            "srlimit": 1,
        }
        r = requests.get(api, params=search_params, headers=headers, timeout=5)
        r.raise_for_status()
        data = r.json()

        results = data.get("query", {}).get("search", [])
        if not results:
            return None

        title = results[0].get("title")
        pageid = results[0].get("pageid")
        if not title or not pageid:
            return None

        # 2) 통짜 위키텍스트 가져오기
        content_params = {
            "action": "query",
            "format": "json",
            "pageids": pageid,
            "prop": "revisions",
            "rvslots": "main",
            "rvprop": "content",
            "redirects": 1,
        }
        r2 = requests.get(api, params=content_params, headers=headers, timeout=5)
        r2.raise_for_status()
        data2 = r2.json()

        pages = data2.get("query", {}).get("pages", {})
        page = pages.get(str(pageid)) or next(iter(pages.values()), None)
        if not page or "missing" in page:
            return None

        revs = page.get("revisions", [])
        if not revs:
            return None

        # MediaWiki slots 구조
        wikitext = revs[0].get("slots", {}).get("main", {}).get("*")
        if not wikitext:
            # 구형 구조 fallback
            wikitext = revs[0].get("*")
        if not wikitext:
            return None

        # 3) 썸네일 별도 요청(pageimages)
        img_params = {
            "action": "query",
            "format": "json",
            "pageids": pageid,
            "prop": "pageimages",
            "piprop": "thumbnail",
            "pithumbsize": 400,
            "redirects": 1,
        }
        r3 = requests.get(api, params=img_params, headers=headers, timeout=5)
        r3.raise_for_status()
        data3 = r3.json()
        pages3 = data3.get("query", {}).get("pages", {})
        page3 = pages3.get(str(pageid)) or next(iter(pages3.values()), None)
        img_url = (page3.get("thumbnail") or {}).get("source") if page3 else None

        # 4) 작가/연도 추출
        # 4-1) 인포박스/템플릿에서 키 기반 우선 추출
        author = _extract_field_from_infobox(
            wikitext,
            keys=["작가", "저자", "원작", "글", "각본", "작화", "감독"]
        )

        # 4-2) 연도도 인포박스 키 우선 (있으면)
        year = _extract_field_from_infobox(
            wikitext,
            keys=["연도", "출시", "발매", "개봉", "연재 시작", "연재시작", "첫 연재", "첫방송", "방영 시작"]
        )
        # year가 "2022년 2월 16일" 같은 형태면 4자리만 뽑기
        year = _extract_year_from_text(year) if year else None

        # 4-3) 인포박스에서 못 찾았으면 본문 텍스트로 fallback
        cleaned = _clean_wikitext_minimal(wikitext)
        if not author:
            author = _extract_author_from_text(cleaned)
        if not year:
            year = _extract_year_from_text(cleaned)

        return {
            "title": title,
            "pageid": pageid,
            "author": author or "정보 없음",
            "year": year,
            "img_url": img_url,
        }

    except requests.RequestException as e:
        print(f"    ⚠️ 위키백과 요청 실패: {e}")
        return None
    except Exception as e:
        print(f"    ⚠️ 위키백과 파싱 실패: {e}")
        return None

def _scrape_google_search(query, content_type, headers):
    """구글 검색 결과에서 정보 추출 (최후의 수단)"""
    try:
        search_url = f"https://www.google.com/search?q={query}+{content_type}&hl=ko"
        response = requests.get(search_url, headers=headers, timeout=5)

        if response.status_code != 200:
            return None

        soup = BeautifulSoup(response.text, 'html.parser')

        # 검색 결과 snippet에서 첫 번째 결과 찾기
        search_results = soup.find_all('div', {'class': 'g'})

        for result in search_results:
            # 제목 찾기
            title_elem = result.find('h3')
            if not title_elem:
                continue

            title = title_elem.get_text(strip=True)

            # snippet에서 추가 정보 추출
            snippet_elem = result.find('div', {'style': '-webkit-line-clamp:2'})
            snippet = snippet_elem.get_text(strip=True) if snippet_elem else ""

            # 작가 정보 추출 시도
            author = None
            if '작가' in snippet or '저자' in snippet:
                parts = snippet.split('작가')[-1] if '작가' in snippet else snippet.split('저자')[-1]
                author = parts.split(',')[0].strip()[:50]

            if title:  # 제목이 있으면 반환
                return {
                    'title': title,
                    'author': author or "정보 없음",
                    'year': None,
                    'img_url': None,
                    'source': '구글 검색'
                }

        return None

    except Exception as e:
        print(f"    ⚠️ 구글 검색 파싱 실패: {e}")
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
        # 1차: 직접 검색
        result = await ContentSearcher._search_tmdb_direct(session, name)

        # 검색 성공 시 반환
        if result[0] is not None:
            return result

        # 2차: Google 스크래핑으로 정보 추출
        print(f"🔍 TMDB 직접 검색 실패, Google 스크래핑 시도: {name}")
        google_info = await scrape_google_search_info(name, "영화")

        if google_info and google_info.get('title'):
            print(f"🔍 Google에서 추출한 정보 - 제목: {google_info['title']}, 감독: {google_info.get('author')}")
            return google_info['title'], google_info.get('year'), google_info.get('author'), None, 'movie'

        # 3차: 번역 후 재검색
        translated = await translate_to_english(name)
        if translated and translated != name:
            print(f"🔍 번역된 제목으로 TMDB 재검색: {translated}")
            result = await ContentSearcher._search_tmdb_direct(session, translated)
            if result[0] is not None:
                return result

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
                        break

                return title, year, author, img_url

        except Exception as e:
            print(f"❌ MangaDex API error: {e}")

        return None, None, None, None

    @staticmethod
    async def search_manga(session, name):
        """MangaDex에서 만화 검색 (한국어 제목 없으면 Google 스크래핑)"""
        original_name = name

        # 1차: 영어로 번역 후 검색
        translated_name = await translate_to_english(name)
        result = await ContentSearcher._search_manga_direct(session, translated_name)

        # 한국어 제목이 있으면 반환
        if result[0] is not None and await is_korean(result[0]):
            return result

        # 3차: Google 스크래핑으로 정보 추출
        print(f"🔍 MangaDex에서 한국어 제목 못 찾음, Google 스크래핑 시도: {original_name}")
        google_info = await scrape_google_search_info(original_name, "만화")

        if google_info and google_info.get('title'):
            print(f"🔍 Google에서 추출한 정보 - 제목: {google_info['title']}, 작가: {google_info.get('author')}")
            # 이미지는 원래 MangaDex 결과가 있으면 사용, 없으면 None
            img_url = result[3] if result else None
            return google_info['title'], google_info.get('year') or result[1], google_info.get('author') or result[2], img_url or result[3]

        print(f"❌ MangaDex/Google: No results for '{original_name}'")
        return None, None, None, None

    @staticmethod
    async def _search_naver_webtoon(session, name):
        """네이버 웹툰에서 직접 검색 (내부용)"""
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }

        try:
            search_url = f"https://comic.naver.com/api/search/all?keyword={name}"
            async with session.get(search_url, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    webtoons = data.get('searchWebtoonResult', {}).get('searchViewList', [])

                    if webtoons:
                        webtoon = webtoons[0]
                        title = webtoon.get('titleName', name)
                        author = webtoon.get('displayAuthor')
                        img_url = webtoon.get('thumbnailUrl')

                        return title, "네이버웹툰", author, img_url
        except Exception as e:
            print(f"⚠️ Naver webtoon search failed: {e}")

        return None, None, None, None

    @staticmethod
    async def search_webtoon(session, name):
        """웹툰 검색 (네이버 → 카카오 → Google 스크래핑)"""
        # 1차: 네이버 웹툰 검색
        result = await ContentSearcher._search_naver_webtoon(session, name)
        if result[0] is not None:
            return result

        # 3차: Google 스크래핑으로 웹툰 정보 추출
        print(f"🔍 웹툰 직접 검색 실패, Google 스크래핑 시도: {name}")
        google_info = await scrape_google_search_info(name, "웹툰")

        if google_info and google_info.get('title'):
            print(f"🔍 Google에서 추출한 정보 - 제목: {google_info['title']}, 작가: {google_info.get('author')}")
            return google_info['title'], "Google 검색", google_info.get('author'), None

        print(f"❌ Webtoon: No results for '{name}'")
        return None, None, None, None
