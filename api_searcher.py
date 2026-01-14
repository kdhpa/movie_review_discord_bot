import aiohttp
import asyncio
import os
import re
import requests
from bs4 import BeautifulSoup
from googletrans import Translator
from googlesearch import search as google_search

TMDB_API_KEY = os.getenv("TMDB_API")
translator = Translator()


async def scrape_google_search_info(query, content_type="만화"):
    """Google 검색 결과에서 제목, 작가, 연도 정보 추출"""
    try:
        await asyncio.sleep(1)  # rate limit 방지
        loop = asyncio.get_event_loop()

        def _scrape():
            search_query = f"{query} {content_type}"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }

            try:
                # Google 검색
                urls = list(google_search(search_query, num_results=5, lang='ko'))

                for url in urls:
                    try:
                        response = requests.get(url, headers=headers, timeout=5)
                        if response.status_code != 200:
                            continue

                        soup = BeautifulSoup(response.text, 'html.parser')

                        # 나무위키에서 추출
                        if 'namu.wiki' in url:
                            title = soup.find('h1', {'class': 'wiki-title'})
                            if title:
                                title_text = title.get_text(strip=True)

                                # 작가/저자 정보 추출
                                author = None
                                author_patterns = ['저자', '작가', '원작', '만화가']
                                for pattern in author_patterns:
                                    author_elem = soup.find(string=re.compile(f'{pattern}|{pattern}', re.IGNORECASE))
                                    if author_elem:
                                        # 다음 텍스트 노드가 작가명
                                        parent = author_elem.parent
                                        if parent and parent.next_sibling:
                                            author = parent.next_sibling.get_text(strip=True)
                                            break

                                # 연도 추출
                                year = None
                                year_match = re.search(r'(20\d{2})', response.text)
                                if year_match:
                                    year = year_match.group(1)

                                if title_text:
                                    return {
                                        'title': title_text,
                                        'author': author or "정보 없음",
                                        'year': year,
                                        'img_url': None
                                    }

                        # Wikipedia에서 추출
                        elif 'wikipedia' in url:
                            title = soup.find('h1', {'class': 'firstHeading'})
                            if title:
                                title_text = title.get_text(strip=True)

                                # 정보상자(infobox)에서 작가 추출
                                author = None
                                infobox = soup.find('table', {'class': 'infobox'})
                                if infobox:
                                    rows = infobox.find_all('tr')
                                    for i, row in enumerate(rows):
                                        if re.search(r'저자|작가|원작|Author', row.get_text(), re.IGNORECASE):
                                            if i + 1 < len(rows):
                                                author = rows[i + 1].get_text(strip=True)
                                                break

                                year = None
                                year_match = re.search(r'(20\d{2})', response.text)
                                if year_match:
                                    year = year_match.group(1)

                                if title_text:
                                    return {
                                        'title': title_text,
                                        'author': author or "정보 없음",
                                        'year': year,
                                        'img_url': None
                                    }

                    except Exception as e:
                        print(f"⚠️ URL 파싱 실패 ({url}): {e}")
                        continue

                return None

            except Exception as e:
                print(f"❌ Google 검색 실패: {e}")
                return None

        result = await loop.run_in_executor(None, _scrape)
        return result

    except Exception as e:
        print(f"❌ Google 스크래핑 에러: {e}")
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
            return google_info['title'], google_info.get('year'), google_info.get('author'), img_url

        # 4차: 검색 결과가 전혀 없으면 원본 제목 반환
        if result[0] is not None:
            return result

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
