import os
import re
from googletrans import Translator

TMDB_API_KEY = os.getenv("TMDB_API")
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
