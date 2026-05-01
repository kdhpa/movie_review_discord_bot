import os
import re
import json
import asyncio
from xai_sdk import Client
from xai_sdk.chat import user, system
from googletrans import Translator

TMDB_API_KEY = os.getenv("TMDB_API")
GROK_API_KEY = os.getenv("GROK_API_KEY")
translator = Translator()


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
                    # if not await is_korean(director):
                    #     director = await translate_to_korean(director)
            else:
                details_url = f"https://api.themoviedb.org/3/tv/{item_id}?api_key={TMDB_API_KEY}&language=ko-KR"
                async with session.get(details_url) as details_response:
                    details = await details_response.json()
                creators = details.get('created_by', [])
                if creators:
                    director = creators[0]['name']
                    # if not await is_korean(director):
                    #     director = await translate_to_korean(director)

            poster_path = item.get('poster_path')
            img_url = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else None

            return title, year, director, img_url, category

        return None, None, None, None, None

    @staticmethod
    async def _search_tmdb_multi_direct(session, name):
        """TMDB에서 최대 5개 결과 검색 (내부용)"""
        search_url = f"https://api.themoviedb.org/3/search/multi?api_key={TMDB_API_KEY}&query={name}&language=ko-KR"
        async with session.get(search_url) as response:
            data = await response.json()

        if not data.get('results'):
            return []

        results = [r for r in data['results'] if r.get('media_type') in ('movie', 'tv')]
        if not results:
            return []

        movies = []
        for item in results[:5]:  # 최대 5개만
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

            if not await is_korean(title):
                title = await translate_to_korean(title)

            poster_path = item.get('poster_path')
            img_url = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else None

            movies.append({
                'title': title,
                'year': year,
                'director': None,  # 지연 로딩
                'img_url': img_url,
                'category': category,
                'tmdb_id': item['id'],
                'media_type': media_type
            })

        return movies

    @staticmethod
    async def search_tmdb_multiple(session, name):
        """TMDB에서 최대 5개 검색 결과 반환"""
        print(f"[DEBUG] search_tmdb_multiple() 시작 - name: {name}")

        # 1차: 직접 검색
        print(f"[DEBUG] search_tmdb_multiple() [1차] TMDB 직접 검색 시도...")
        movies = await ContentSearcher._search_tmdb_multi_direct(session, name)

        if movies:
            print(f"[DEBUG] search_tmdb_multiple() [1차] 성공 - {len(movies)}개 결과 반환")
            return movies

        print(f"[DEBUG] search_tmdb_multiple() [1차] 실패")

        # 2차: 번역 후 재검색
        print(f"[DEBUG] search_tmdb_multiple() [2차] 영문 번역 시도...")
        translated = await translate_to_english(name)
        if translated and translated != name:
            print(f"[DEBUG] search_tmdb_multiple() [2차] 번역 성공: {translated} -> TMDB 재검색...")
            movies = await ContentSearcher._search_tmdb_multi_direct(session, translated)
            if movies:
                print(f"[DEBUG] search_tmdb_multiple() [2차] 성공 - {len(movies)}개 결과 반환")
                return movies
            print(f"[DEBUG] search_tmdb_multiple() [2차] TMDB 재검색 실패")
        else:
            print(f"[DEBUG] search_tmdb_multiple() [2차] 번역 실패 또는 동일: {translated}")

        print(f"[DEBUG] search_tmdb_multiple() 완료 - 반환값 없음")
        return []

    @staticmethod
    async def _fetch_director_info(session, tmdb_id, media_type):
        """특정 TMDB ID의 감독/제작자 정보 조회"""
        try:
            print(f"[DEBUG] _fetch_director_info() 시작 - tmdb_id: {tmdb_id}, media_type: {media_type}")

            if media_type == 'movie':
                credits_url = f"https://api.themoviedb.org/3/movie/{tmdb_id}/credits?api_key={TMDB_API_KEY}&language=ko-KR"
                async with session.get(credits_url) as credits_response:
                    credits = await credits_response.json()
                director_info = next((crew for crew in credits.get('crew', []) if crew['job'] == 'Director'), None)

                if director_info:
                    director = director_info.get('name')
                    print(f"[DEBUG] _fetch_director_info() 감독 발견: {director}")
                    return director
            else:
                details_url = f"https://api.themoviedb.org/3/tv/{tmdb_id}?api_key={TMDB_API_KEY}&language=ko-KR"
                async with session.get(details_url) as details_response:
                    details = await details_response.json()
                creators = details.get('created_by', [])
                if creators:
                    director = creators[0]['name']
                    print(f"[DEBUG] _fetch_director_info() 제작자 발견: {director}")
                    return director

            print(f"[DEBUG] _fetch_director_info() 정보 없음")
            return "정보 없음"
        except Exception as e:
            print(f"[ERROR] _fetch_director_info() 실패: {e}")
            return "정보 없음"

    @staticmethod
    async def fetch_watch_providers(session, tmdb_id, media_type):
        """TMDB Watch Providers API로 한국(KR) OTT 정보 조회"""
        endpoint = 'movie' if media_type == 'movie' else 'tv'
        url = f"https://api.themoviedb.org/3/{endpoint}/{tmdb_id}/watch/providers?api_key={TMDB_API_KEY}"
        async with session.get(url) as response:
            data = await response.json()
        kr_data = data.get('results', {}).get('KR')
        if not kr_data:
            return None
        providers = {}
        for provider_type in ('flatrate', 'rent', 'buy'):
            items = kr_data.get(provider_type, [])
            if items:
                providers[provider_type] = [
                    {'name': item['provider_name'], 'logo_path': item.get('logo_path')}
                    for item in items
                ]
        providers['link'] = kr_data.get('link')
        return providers if any(k in providers for k in ('flatrate', 'rent', 'buy')) else None

    @staticmethod
    def _extract_mangadex_id(url_or_name):
        """MangaDex URL에서 manga ID 추출 (UUID 형식)"""
        # https://mangadex.org/title/{uuid}/{slug} 형식
        pattern = r'mangadex\.org/title/([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})'
        match = re.search(pattern, url_or_name, re.IGNORECASE)
        if match:
            return match.group(1)
        return None

    @staticmethod
    async def fetch_manga_by_url(session, url):
        """URL에서 ID 추출 후 만화 정보 조회 (외부 호출용)
        Returns: (title, year, author, img_url, mangadex_id)
        """
        manga_id = ContentSearcher._extract_mangadex_id(url)
        if not manga_id:
            return None
        result = await ContentSearcher._fetch_manga_by_id(session, manga_id)
        # (title, year, author, img_url, mangadex_id) 형태로 반환
        if result[0] is not None:
            return result
        return None

    @staticmethod
    async def _fetch_manga_by_id(session, manga_id):
        """MangaDex ID로 직접 만화 정보 조회"""
        url = f"https://api.mangadex.org/manga/{manga_id}?includes[]=author&includes[]=cover_art"

        try:
            async with session.get(url) as response:
                if response.status != 200:
                    print(f"❌ MangaDex API error: status {response.status}")
                    return None, None, None, None, None

                data = await response.json()

            manga = data.get('data')
            if not manga:
                return None, None, None, None, None

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
                title = list(title_dict.values())[0] if title_dict else manga_id

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
                        img_url = f"https://uploads.mangadex.org/covers/{manga_id}/{filename}"
                        print(f"이미지 정보: {img_url}")
                    break

            print(f"MangaDex ID로 가져온 정보 - 제목: {title}, 년도: {year}, 작가: {author}, ID: {manga_id}")
            return title, year, author, img_url, manga_id

        except Exception as e:
            print(f"❌ MangaDex API error: {e}")
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
                manga_id = manga.get('id')
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
                            img_url = f"https://uploads.mangadex.org/covers/{manga_id}/{filename}"
                            print(f"이미지 정보: {img_url}")
                        break
                print(f"망가덱스에서 가져온 정보 - 제목: {title}, 년도: {year}, 작가: {author}, ID: {manga_id}")
                return title, year, author, img_url, manga_id

        except Exception as e:
            print(f"❌ MangaDex API error: {e}")

        return None, None, None, None, None

    @staticmethod
    async def search_manga(session, name):
        """MangaDex에서 만화 검색 (URL 또는 제목으로 검색)
        Returns: (title, year, author, img_url, mangadex_id)
        """
        print(f"[DEBUG] search_manga() 시작 - name: {name}")

        # 0차: MangaDex URL인지 확인
        manga_id = ContentSearcher._extract_mangadex_id(name)
        if manga_id:
            print(f"[DEBUG] search_manga() MangaDex URL 감지 - ID: {manga_id}")
            result = await ContentSearcher._fetch_manga_by_id(session, manga_id)
            if result[0] is not None:
                print(f"[DEBUG] search_manga() URL로 조회 성공 - title={result[0]}")
                return result
            print(f"[DEBUG] search_manga() URL로 조회 실패")
            return None, None, None, None, None

        # 1차: 영어로 번역 후 검색
        print(f"[DEBUG] search_manga() [1차] 영문 번역 시도...")
        translated_name = await translate_to_english(name)
        print(f"[DEBUG] search_manga() [1차] 번역됨: {translated_name}")
        result = await ContentSearcher._search_manga_direct(session, translated_name)
        print(f"[DEBUG] search_manga() [1차] MangaDex 검색 결과: {result}")

        # 한국어 제목이 있으면 반환
        if result[0] is not None and await is_korean(result[0]):
            print(f"[DEBUG] search_manga() [1차] 한국어 제목 발견 - 반환: title={result[0]}, year={result[1]}, author={result[2]}, id={result[4]}")
            return result

        print(f"[DEBUG] search_manga() [1차] 한국어 제목 없음")
        return None, None, None, None, None

    @staticmethod
    async def _search_naver_webtoon(session, name):
        """네이버 웹툰에서 직접 검색 (내부용)
        Returns: (title, platform, author, img_url, naver_title_id)
        """
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
                        title_id = str(webtoon.get('titleId')) if webtoon.get('titleId') else None
                        print(f"[DEBUG] _search_naver_webtoon() 완료 - title: {title}, author: {author}, titleId: {title_id}")

                        return title, "네이버웹툰", author, img_url, title_id
                else:
                    print(f"[DEBUG] _search_naver_webtoon() 상태 오류: {response.status}")
        except Exception as e:
            print(f"[ERROR] _search_naver_webtoon() 실패: {e}")

        print(f"[DEBUG] _search_naver_webtoon() 반환값 없음")
        return None, None, None, None, None

    @staticmethod
    async def search_webtoon(session, name):
        """웹툰 검색 (네이버 → 카카오 → Google 스크래핑)
        Returns: (title, platform, author, img_url, naver_title_id)
        """
        print(f"[DEBUG] search_webtoon() 시작 - name: {name}")

        # 1차: 네이버 웹툰 검색
        print(f"[DEBUG] search_webtoon() [1차] 네이버 웹툰 검색...")
        result = await ContentSearcher._search_naver_webtoon(session, name)
        if result[0] is not None:
            print(f"[DEBUG] search_webtoon() [1차] 성공 - 반환: {result}")
            return result

        print(f"[DEBUG] search_webtoon() [1차] 실패")
        return None, None, None, None, None


class GrokSearcher:
    """Grok AI API로 레거시 리뷰 메시지를 파싱하는 클래스 (마이그레이션용)"""

    @staticmethod
    def _parse_legacy_review_sync(message_content: str, author_name: str) -> dict:
        """동기 함수 - 레거시 리뷰 메시지를 LLM으로 파싱"""
        if not GROK_API_KEY:
            print("[ERROR] GROK_API_KEY가 설정되지 않았습니다.")
            return None

        client = Client(
            api_key=GROK_API_KEY,
            timeout=60,
        )

        chat = client.chat.create(model="grok-3-mini-fast")

        chat.append(system("""You are a parser that extracts review information from unstructured text messages.
Extract the following fields and return ONLY valid JSON (no markdown, no explanation):
- title: The title of the content being reviewed (movie, drama, anime, manga, webtoon)
- score: Rating score (convert to 0-5 scale, e.g. "8/10" → 4.0, "A+" → 5.0, "별 4개" → 4.0)
- one_line_review: The main review comment or opinion
- category: One of "movie", "drama", "anime", "manga", "webtoon" (guess based on context)
- year: Release year if mentioned (otherwise null)
- director: Director or author name if mentioned (otherwise null)

If you cannot extract meaningful review information, return {"error": "not_a_review"}"""))

        chat.append(user(f"""Parse this message and extract review information:

Message author: {author_name}
Message content:
{message_content}

Return only JSON."""))

        try:
            print(f"[DEBUG] _parse_legacy_review_sync() API 호출 시작")

            content = ""
            for response, chunk in chat.stream():
                if chunk.content:
                    content += chunk.content

            print(f"[DEBUG] _parse_legacy_review_sync() 응답: {content[:200]}...")

            if not content:
                return None

            # JSON 파싱
            if "```json" in content:
                json_start = content.find("```json") + 7
                json_end = content.find("```", json_start)
                content = content[json_start:json_end].strip()
            elif "```" in content:
                json_start = content.find("```") + 3
                json_end = content.find("```", json_start)
                content = content[json_start:json_end].strip()

            result = json.loads(content)

            if result.get("error"):
                return None

            return result

        except json.JSONDecodeError as e:
            print(f"[ERROR] _parse_legacy_review_sync() JSON 파싱 실패: {e}")
            return None
        except Exception as e:
            print(f"[ERROR] _parse_legacy_review_sync() 예외 발생: {e}")
            return None

    @staticmethod
    async def parse_legacy_review(message_content: str, author_name: str) -> dict:
        """비동기 래퍼 - 레거시 리뷰 메시지 파싱"""
        return await asyncio.to_thread(GrokSearcher._parse_legacy_review_sync, message_content, author_name)

