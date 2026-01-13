import requests
import os
import re

TMDB_API_KEY = "ed858620292ea4710cb4dc894449f6ea"


def is_korean(text):
    """한글이 포함되어 있는지 확인"""
    if not text:
        return False
    return bool(re.search('[가-힣]', text))


def translate_to_korean(text):
    """영어/일본어 이름을 한국어로 번역"""
    if not text or text == "N/A" or is_korean(text):
        return text

    try:
        from googletrans import Translator
        translator = Translator()
        result = translator.translate(text, dest='ko')
        return result.text
    except:
        # 번역 실패 시 원본 반환
        return text


class ContentSearcher:
    """영화, 만화, 웹툰 검색 통합 클래스"""

    @staticmethod
    def search_tmdb(name):
        """TMDB multi search API로 영화/드라마/애니 검색 및 자동 분류"""
        search_url = f"https://api.themoviedb.org/3/search/multi?api_key={TMDB_API_KEY}&query={name}&language=ko-KR"
        response = requests.get(search_url)
        data = response.json()

        if data.get('results'):
            # movie 또는 tv만 필터링
            results = [r for r in data['results'] if r.get('media_type') in ('movie', 'tv')]
            if not results:
                return name, "N/A", "N/A", None, "movie"

            item = results[0]
            media_type = item.get('media_type')
            genre_ids = item.get('genre_ids', [])

            # 카테고리 판별 (16 = Animation)
            is_animation = 16 in genre_ids
            if is_animation:
                category = 'anime'
            elif media_type == 'tv':
                category = 'drama'
            else:
                category = 'movie'

            # 제목과 연도
            if media_type == 'movie':
                title = item.get('title', name)
                year = item['release_date'][:4] if item.get('release_date') else "N/A"
            else:  # tv
                title = item.get('name', name)
                year = item['first_air_date'][:4] if item.get('first_air_date') else "N/A"

            # 감독/제작자 정보
            item_id = item['id']
            director = None

            if media_type == 'movie':
                credits_url = f"https://api.themoviedb.org/3/movie/{item_id}/credits?api_key={TMDB_API_KEY}&language=ko-KR"
                credits = requests.get(credits_url).json()
                director_info = next((crew for crew in credits.get('crew', []) if crew['job'] == 'Director'), None)

                if director_info:
                    director = director_info.get('name')
                    # 한글이 아니면 번역 시도
                    if not is_korean(director):
                        director = translate_to_korean(director)
            else:  # tv - created_by 사용
                details_url = f"https://api.themoviedb.org/3/tv/{item_id}?api_key={TMDB_API_KEY}&language=ko-KR"
                details = requests.get(details_url).json()
                creators = details.get('created_by', [])
                if creators:
                    director = creators[0]['name']
                    if not is_korean(director):
                        director = translate_to_korean(director)

            # 포스터 이미지
            poster_path = item.get('poster_path')
            img_url = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else None

            return title, year, director, img_url, category

        return None, None, None, None, None

    @staticmethod
    def search_manga(name):
        """MangaDex API로 만화 검색"""
        url = f"https://api.mangadex.org/manga?title={name}&limit=1&includes[]=author&includes[]=cover_art"

        try:
            response = requests.get(url)
            data = response.json()

            if data.get('data') and len(data['data']) > 0:
                manga = data['data'][0]
                attributes = manga.get('attributes', {})

                # 제목 (ko > en 순으로 선택)
                title_dict = attributes.get('title', {})
                alt_titles = attributes.get('altTitles', [])

                title = None
                # 먼저 title에서 찾기
                for lang in ['en', 'ko']:
                    if lang in title_dict:
                        title = title_dict[lang]
                        break

                # altTitles에서 한국어 찾기
                if not title:
                    for alt in alt_titles:
                        if 'ko' in alt:
                            title = alt['ko']
                            break

                if not title:
                    title = list(title_dict.values())[0] if title_dict else name

                # 연도
                year = str(attributes.get('year')) if attributes.get('year') else None

                # 작가 (relationships에서 author 찾기)
                author = None
                relationships = manga.get('relationships', [])
                for rel in relationships:
                    if rel.get('type') == 'author':
                        author_attrs = rel.get('attributes', {})
                        author = author_attrs.get('name')
                        # 한글이 아니면 번역 시도
                        if author and not is_korean(author):
                            author = translate_to_korean(author)
                        break

                # 커버 이미지 (cover_art relationship에서 찾기)
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
            else:
                print(f"❌ MangaDex: No results for '{name}'")

        except Exception as e:
            print(f"❌ MangaDex API error: {e}")

        return None, None, None, None

    @staticmethod
    def search_webtoon(name):
        """네이버 웹툰 검색"""
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }

        try:
            search_url = f"https://comic.naver.com/api/search/all?keyword={name}"
            response = requests.get(search_url, headers=headers)

            if response.status_code == 200:
                data = response.json()
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
