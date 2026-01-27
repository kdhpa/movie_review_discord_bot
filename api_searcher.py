import os
import re
import json
import asyncio
from datetime import datetime, timedelta
from googletrans import Translator

TMDB_API_KEY = os.getenv("TMDB_API")
GROK_API_KEY = os.getenv("GROK_API_KEY")
translator = Translator()

# 그룹별 뉴스 프롬프트 정의 (실시간 X/웹 검색용)
NEWS_GROUP_PROMPTS = {
    "movie": {
        "system": "당신은 영화 뉴스 속보 전문 기자입니다. X(트위터)와 웹에서 실시간 검색하여 방금 발표된 영화 소식과 루머를 찾습니다.",
        "query": """X와 웹을 검색하여 지금 막 화제가 되고 있는 영화 뉴스와 루머 2-3개를 찾아주세요.

검색 대상:
- 신작 발표, 캐스팅 확정/루머, 티저/예고편 공개
- 흥행 기록, 제작 소식, 업계 루머

반드시 아래 JSON 형식으로만 응답:
{"movie": [{"title": "제목", "content": "내용 2-3문장", "source": "출처 URL 또는 X 계정"}]}"""
    },
    "drama": {
        "system": "당신은 드라마/TV시리즈 속보 전문 기자입니다. X와 웹에서 실시간 검색하여 방금 발표된 드라마 소식을 찾습니다.",
        "query": """X와 웹을 검색하여 지금 막 화제가 되고 있는 드라마 뉴스 2-3개를 찾아주세요.

검색 대상:
- 한국 드라마, OTT(넷플릭스/디즈니+/티빙), 미드
- 신작 공개, 캐스팅, 시청률 기록, 시즌 발표

반드시 아래 JSON 형식으로만 응답:
{"drama": [{"title": "제목", "content": "내용 2-3문장", "source": "출처"}]}"""
    },
    "acg": {
        "system": "당신은 애니메이션/만화/웹툰 속보 전문 기자입니다. X와 웹에서 실시간 검색하여 방금 발표된 소식을 찾습니다.",
        "query": """X와 웹을 검색하여 지금 막 화제가 되고 있는 애니/만화/웹툰 뉴스를 찾아주세요.

검색 대상:
- anime: 일본 애니메이션 (방영, 극장판, 성우, 제작 발표)
- manga: 일본 만화 (연재, 완결, 작가 소식)
- webtoon: 한국 웹툰 (네이버/카카오, 영상화, 작가)
- 각 카테고리당 1-2개

반드시 아래 JSON 형식으로만 응답:
{
  "anime": [{"title": "제목", "content": "내용", "source": "출처"}],
  "manga": [{"title": "제목", "content": "내용", "source": "출처"}],
  "webtoon": [{"title": "제목", "content": "내용", "source": "출처"}]
}"""
    }
}

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
    async def search_tmdb(session, name):
        print(f"[DEBUG] search_tmdb() 시작 - name: {name}")

        # 1차: 직접 검색
        print(f"[DEBUG] search_tmdb() [1차] TMDB 직접 검색 시도...")
        result = await ContentSearcher._search_tmdb_direct(session, name)

        # 검색 성공 시 반환
        if result[0] is not None:
            print(f"[DEBUG] search_tmdb() [1차] 성공 - 반환: title={result[0]}, year={result[1]}, director={result[2]}, category={result[4]}")
            return result

        print(f"[DEBUG] search_tmdb() [1차] 실패")

        # 3차: 번역 후 재검색
        print(f"[DEBUG] search_tmdb() [2차] 영문 번역 시도...")
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
        return None, None, None, None


class GrokSearcher:
    """Grok AI API를 통해 영화 소식을 가져오는 클래스"""

    @staticmethod
    async def fetch_movie_news(session):
        """Grok API를 호출하여 영화 루머/소식 가져오기 - 실시간 X/웹 검색 지원"""
        if not GROK_API_KEY:
            print("[ERROR] GROK_API_KEY가 설정되지 않았습니다.")
            return None

        # 날짜 계산 (어제~오늘)
        today = datetime.now().strftime("%Y-%m-%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

        url = "https://api.x.ai/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {GROK_API_KEY}"
        }

        payload = {
            "model": "grok-4-1-fast",  # 검색 도구 지원 모델
            "messages": [
                {
                    "role": "system",
                    "content": "당신은 영화 소식 전문가입니다. X와 웹을 검색하여 최신 영화 루머, 제작 소식, 캐스팅 뉴스 등을 한국어로 알려주세요."
                },
                {
                    "role": "user",
                    "content": "X와 웹을 검색하여 오늘의 최신 영화 루머와 소식 3-5개를 알려주세요. 각 소식은 제목과 간단한 설명으로 구성해주세요. 출처(URL 또는 X 계정)를 함께 알려주세요."
                }
            ],
            "tools": [
                {
                    "type": "live_search",
                    "sources": [{"type": "x"}, {"type": "web"}],
                    "live_search": {
                        "max_results": 20
                    }
                }
            ],
            "temperature": 0.7
        }

        try:
            async with session.post(url, headers=headers, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    print(f"[DEBUG] GrokSearcher.fetch_movie_news() 성공")
                    return content
                else:
                    error_text = await response.text()
                    print(f"[ERROR] GrokSearcher.fetch_movie_news() 실패 - 상태: {response.status}, 오류: {error_text}")
                    return None
        except Exception as e:
            print(f"[ERROR] GrokSearcher.fetch_movie_news() 예외 발생: {e}")
            return None

    @staticmethod
    async def fetch_categorized_news(session):
        """카테고리별 엔터테인먼트 뉴스 가져오기 (JSON 형식) - 실시간 X/웹 검색 지원"""
        if not GROK_API_KEY:
            print("[ERROR] GROK_API_KEY가 설정되지 않았습니다.")
            return None

        # 날짜 계산 (어제~오늘)
        today = datetime.now().strftime("%Y-%m-%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

        url = "https://api.x.ai/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {GROK_API_KEY}"
        }

        payload = {
            "model": "grok-4-1-fast",  # 검색 도구 지원 모델
            "messages": [
                {
                    "role": "system",
                    "content": """당신은 엔터테인먼트 뉴스 전문가입니다. X와 웹을 검색하여 실시간 뉴스를 찾습니다.
반드시 아래 JSON 형식으로만 응답하세요. 다른 텍스트 없이 JSON만 출력하세요."""
                },
                {
                    "role": "user",
                    "content": """X와 웹을 검색하여 오늘의 최신 엔터테인먼트 소식을 카테고리별로 정리해주세요.

반드시 아래 JSON 형식으로 응답하세요:
{
  "headlines": [
    {"title": "헤드라인 제목", "summary": "한줄 요약", "category": "movie", "importance": 5}
  ],
  "movie": [
    {"title": "뉴스 제목", "content": "상세 내용 (2-3문장)", "source": "출처 URL 또는 X 계정"}
  ],
  "drama": [...],
  "anime": [...],
  "manga": [...],
  "webtoon": [...]
}

규칙:
- headlines: 가장 중요한 뉴스 3-5개 (importance 1-5, 높은 순으로 정렬)
- 각 카테고리당 2-3개의 뉴스
- 뉴스가 없는 카테고리는 빈 배열 []
- 실제 최신 뉴스만 포함 (오늘~어제)
- 영화(movie): 영화 제작, 캐스팅, 개봉 소식
- 드라마(drama): TV/OTT 드라마 소식
- 애니(anime): 일본 애니메이션 소식
- 만화(manga): 일본 만화 소식
- 웹툰(webtoon): 한국 웹툰 소식"""
                }
            ],
            "tools": [
                {
                    "type": "live_search",
                    "sources": [{"type": "x"}, {"type": "web"}],
                    "live_search": {
                        "max_results": 20
                    }
                }
            ],
            "temperature": 0.7
        }

        try:
            async with session.post(url, headers=headers, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    print(f"[DEBUG] GrokSearcher.fetch_categorized_news() 응답 수신")

                    # JSON 파싱 시도
                    try:
                        # JSON 블록 추출 (```json ... ``` 형식일 경우 처리)
                        if "```json" in content:
                            json_start = content.find("```json") + 7
                            json_end = content.find("```", json_start)
                            content = content[json_start:json_end].strip()
                        elif "```" in content:
                            json_start = content.find("```") + 3
                            json_end = content.find("```", json_start)
                            content = content[json_start:json_end].strip()

                        news_data = json.loads(content)
                        print(f"[DEBUG] GrokSearcher.fetch_categorized_news() JSON 파싱 성공")
                        return news_data
                    except json.JSONDecodeError as e:
                        print(f"[WARNING] JSON 파싱 실패: {e}")
                        print(f"[DEBUG] 원본 응답: {content[:500]}...")
                        # 폴백: 기존 방식으로 raw_content 반환
                        return {"raw_content": content}
                else:
                    error_text = await response.text()
                    print(f"[ERROR] GrokSearcher.fetch_categorized_news() 실패 - 상태: {response.status}, 오류: {error_text}")
                    return None
        except Exception as e:
            print(f"[ERROR] GrokSearcher.fetch_categorized_news() 예외 발생: {e}")
            return None

    @staticmethod
    async def _fetch_news_group(session, group: str):
        """특정 그룹의 뉴스 가져오기 (movie, drama, acg) - 실시간 X/웹 검색 지원"""
        if not GROK_API_KEY:
            print(f"[ERROR] GROK_API_KEY가 설정되지 않았습니다. (group: {group})")
            return {}

        prompts = NEWS_GROUP_PROMPTS.get(group)
        if not prompts:
            print(f"[ERROR] 알 수 없는 그룹: {group}")
            return {}

        # 날짜 계산 (어제~오늘)
        today = datetime.now().strftime("%Y-%m-%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

        url = "https://api.x.ai/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {GROK_API_KEY}"
        }

        payload = {
            "model": "grok-4-1-fast",  # 검색 도구 지원 모델
            "messages": [
                {"role": "system", "content": prompts["system"]},
                {"role": "user", "content": prompts["query"]}
            ],
            "tools": [
                {
                    "type": "live_search",
                    "sources": [{"type": "x"}, {"type": "web"}],
                    "live_search": {
                        "max_results": 20
                    }
                }
            ],
            "temperature": 0.7
        }

        try:
            print(f"[DEBUG] _fetch_news_group({group}) API 호출 시작")
            async with session.post(url, headers=headers, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    print(f"[DEBUG] _fetch_news_group({group}) 응답 수신")

                    # JSON 파싱
                    try:
                        # JSON 블록 추출 (```json ... ``` 형식일 경우 처리)
                        if "```json" in content:
                            json_start = content.find("```json") + 7
                            json_end = content.find("```", json_start)
                            content = content[json_start:json_end].strip()
                        elif "```" in content:
                            json_start = content.find("```") + 3
                            json_end = content.find("```", json_start)
                            content = content[json_start:json_end].strip()

                        news_data = json.loads(content)
                        print(f"[DEBUG] _fetch_news_group({group}) JSON 파싱 성공: {list(news_data.keys())}")
                        return news_data
                    except json.JSONDecodeError as e:
                        print(f"[WARNING] _fetch_news_group({group}) JSON 파싱 실패: {e}")
                        print(f"[DEBUG] 원본 응답: {content[:300]}...")
                        return {}
                else:
                    error_text = await response.text()
                    print(f"[ERROR] _fetch_news_group({group}) 실패 - 상태: {response.status}, 오류: {error_text}")
                    return {}
        except Exception as e:
            print(f"[ERROR] _fetch_news_group({group}) 예외 발생: {e}")
            return {}

    @staticmethod
    def _generate_headlines(news_data: dict) -> list:
        """카테고리별 뉴스에서 헤드라인 생성"""
        headlines = []
        importance_map = {"movie": 5, "drama": 4, "anime": 3, "manga": 2, "webtoon": 2}

        for category in ["movie", "drama", "anime", "manga", "webtoon"]:
            news_list = news_data.get(category, [])
            if news_list:
                # 각 카테고리에서 첫 번째 뉴스를 헤드라인으로 선정
                first_news = news_list[0]
                headlines.append({
                    "title": first_news.get("title", "제목 없음"),
                    "summary": first_news.get("content", "")[:50] + "..." if len(first_news.get("content", "")) > 50 else first_news.get("content", ""),
                    "category": category,
                    "importance": importance_map.get(category, 1)
                })

        # 중요도 순으로 정렬
        headlines.sort(key=lambda x: x["importance"], reverse=True)
        return headlines[:5]  # 최대 5개

    @staticmethod
    async def fetch_all_categorized_news(session):
        """3그룹 뉴스를 병렬로 수집 후 5개 카테고리로 분리"""
        groups = ['movie', 'drama', 'acg']

        # asyncio.gather로 3회 병렬 호출
        print(f"[INFO] fetch_all_categorized_news() 3그룹 병렬 호출 시작: {groups}")
        tasks = [GrokSearcher._fetch_news_group(session, g) for g in groups]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 결과 병합 (5개 카테고리로 분리)
        news_data = {"movie": [], "drama": [], "anime": [], "manga": [], "webtoon": []}

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                print(f"[ERROR] 그룹 '{groups[i]}' 호출 실패: {result}")
                continue
            if isinstance(result, dict):
                for key in news_data.keys():
                    if key in result:
                        news_data[key].extend(result[key])

        # 뉴스가 하나도 없으면 폴백
        total_news = sum(len(v) for v in news_data.values())
        if total_news == 0:
            print("[WARNING] 모든 그룹에서 뉴스를 가져오지 못함 - 기존 fetch_categorized_news() 폴백")
            return await GrokSearcher.fetch_categorized_news(session)

        # 헤드라인 생성
        news_data["headlines"] = GrokSearcher._generate_headlines(news_data)

        print(f"[INFO] fetch_all_categorized_news() 완료 - 총 {total_news}개 뉴스")
        return news_data
