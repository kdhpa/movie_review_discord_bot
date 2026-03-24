import discord
import aiohttp
import asyncio
from discord.ext import commands
from review_form import MOVIE_FORM, MANGA_FORM, WEBTOON_FORM

# 카테고리별 이모지 및 이름 매핑
CATEGORY_EMOJI = {"movie": "🎬", "drama": "📺", "anime": "🎌", "manga": "📚", "webtoon": "📱"}
CATEGORY_NAME = {"movie": "영화", "drama": "드라마", "anime": "애니", "manga": "만화", "webtoon": "웹툰"}
from database import Database
from api_searcher import ContentSearcher, GrokSearcher
from news_scheduler import NewsScheduler
from assistant_service import AssistantService
from review_interaction import ReviewReactionView
import io
import os

Token = os.getenv("Token")


# CATEGORY_EMOJI 역매핑 (emoji -> category)
EMOJI_CATEGORY = {emoji: cat for cat, emoji in CATEGORY_EMOJI.items()}


def parse_review_message(content):
    """리뷰 메시지에서 title과 category를 파싱
    첫 줄이 '{emoji}제목: {title}' 형식이어야 함
    Returns: (title, category) or (None, None)
    """
    if not content:
        return None, None

    first_line = content.split('\n')[0]

    for emoji, category in EMOJI_CATEGORY.items():
        prefix = f"{emoji}제목: "
        if first_line.startswith(prefix):
            title = first_line[len(prefix):].strip()
            return title, category

    return None, None


def parse_review_detail(content):
    """리뷰 메시지에서 director/author, year/platform 파싱"""
    lines = content.split('\n')
    if len(lines) < 3:
        return None, None

    director = None
    for prefix in ['🎥감독: ', '✍️작가: ']:
        if lines[1].startswith(prefix):
            director = lines[1][len(prefix):].strip()
            break

    year = None
    for prefix in ['📅개봉년도: ', '📅연재년도: ', '📍플랫폼: ']:
        if lines[2].startswith(prefix):
            year = lines[2][len(prefix):].strip()
            break

    return director, year


def is_current_review_message(review_data, message):
    """DB에 저장된 최신 리뷰 메시지인지 확인"""
    stored_message_id = review_data.get('message_id')
    stored_channel_id = review_data.get('channel_id')

    if stored_message_id and stored_channel_id:
        return stored_message_id == message.id and stored_channel_id == message.channel.id

    return True


def return_score_emoji(score):
    """별점을 이모지로 변환"""
    float_number = min(float(score), 5)
    int_number = int(float_number)
    none_number = int(5 - float_number)

    float_number = float_number % 1

    score_emoji = ":full_moon:" * int_number

    if 0.1 <= float_number <= 0.3:
        score_emoji += ':waning_crescent_moon:'
    elif float_number == 0.5:
        score_emoji += ':last_quarter_moon:'
    elif 0.6 <= float_number <= 0.9:
        score_emoji += ':waning_gibbous_moon:'

    if none_number > 0:
        score_emoji += ':new_moon:' * none_number

    score_emoji += f" ( {min(float(score), 5):.1f} )"

    return score_emoji


async def _save_and_send_review(
    interaction: discord.Interaction,
    db,
    movie_info: dict,
    category: str,
    score_float: float,
    line_comment: str,
    comment: str,
    author_id: int,
    author_name: str,
    display_name: str
):
    """리뷰 저장 및 메시지 전송 (공통 로직)"""
    print(f"[DEBUG] _save_and_send_review() 시작 - 작성자: {author_name}")

    title = movie_info['title']
    year = movie_info['year']
    director = movie_info['director']
    img_url = movie_info['img_url']
    db_category = movie_info['category']

    # 중복 확인
    print(f"[DEBUG] _save_and_send_review() 중복 확인 중...")
    if db.has_review(author_id, title, db_category):
        print(f"[DEBUG] _save_and_send_review() 중복 발견")
        await interaction.followup.send(
            f"❌ 이미 '{title}'에 대한 리뷰를 작성하셨습니다.\n`/리뷰삭제`로 기존 리뷰를 삭제하세요.",
            ephemeral=True
        )
        return

    # DB 저장
    print(f"[DEBUG] _save_and_send_review() DB 저장 중...")
    review_id = db.save_review(
        user_id=author_id,
        username=author_name,
        movie_title=title,
        movie_year=year,
        director=director,
        score=score_float,
        one_line_review=line_comment,
        additional_comment=comment,
        category=db_category,
        img_url=img_url
    )
    print(f"[DEBUG] _save_and_send_review() DB 저장 완료 - review_id: {review_id}")

    # 카테고리별 출력 형식
    emoji = CATEGORY_EMOJI.get(db_category, "🎬")
    cat_name = CATEGORY_NAME.get(db_category, "영화")

    if category == 'tmdb':
        filled_form = MOVIE_FORM.format(
            title=title,
            director_name=director,
            year=year,
            score=return_score_emoji(score_float),
            one_line_text=line_comment,
            author_name = display_name
        )
        filled_form = filled_form.replace("🎬", emoji)
        filled_form += f"\n🏷️ 카테고리: {cat_name}"
    elif category == 'manga':
        filled_form = MANGA_FORM.format(
            title=title,
            author=director,
            year=year,
            score=return_score_emoji(score_float),
            one_line_text=line_comment,
            author_name = display_name
        )
    else:  # webtoon
        filled_form = WEBTOON_FORM.format(
            title=title,
            platform=year,
            author=director,
            score=return_score_emoji(score_float),
            one_line_text=line_comment,
            author_name = display_name
        )

    if comment:
        filled_form += f"\n\n📝추가 코멘트 : {comment}"

    # 이미지 다운로드 및 전송
    print(f"[DEBUG] _save_and_send_review() 이미지 처리 - img_url: {img_url}")
    img_data = None

    if img_url:
        print(f"[DEBUG] _save_and_send_review() 이미지 다운로드 시작 - URL: {img_url}")
        timeout = aiohttp.ClientTimeout(total=30)
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': img_url
        }

        for attempt in range(3):
            try:
                async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                    async with session.get(img_url) as img_response:
                        print(f"[DEBUG] _save_and_send_review() 이미지 응답 상태: {img_response.status} (시도 {attempt + 1})")
                        if img_response.status == 200:
                            img_data = await img_response.read()
                            print(f"[DEBUG] _save_and_send_review() 이미지 다운로드 성공 (크기: {len(img_data)} bytes)")
                            break
                        else:
                            print(f"[DEBUG] _save_and_send_review() 이미지 다운로드 실패 (상태: {img_response.status})")
            except Exception as e:
                print(f"[ERROR] _save_and_send_review() 이미지 다운로드 중 오류 (시도 {attempt + 1}): {e}")

            if attempt < 2:
                await asyncio.sleep(1)

    view = ReviewReactionView()
    if img_data:
        file = discord.File(io.BytesIO(img_data), filename="image.jpg")
        sent_message = await interaction.followup.send(filled_form, file=file, view=view, wait=True)
        print(f"[DEBUG] _save_and_send_review() 이미지 포함 메시지 전송 완료")
    else:
        print(f"[DEBUG] _save_and_send_review() 이미지 없이 텍스트만 전송")
        sent_message = await interaction.followup.send(filled_form, view=view, wait=True)

    # message_id 저장
    if review_id and sent_message:
        db.update_message_id(review_id, sent_message.id, interaction.channel_id)
        print(f"[DEBUG] _save_and_send_review() message_id 저장 완료 - {sent_message.id}")

    print(f"[DEBUG] _save_and_send_review() 완료")


# ==================== 통합 Modal ====================

class MovieSelectMenu(discord.ui.Select):
    """TMDB 검색 결과 선택 메뉴"""

    def __init__(self, movies: list, form: 'ReviewForm'):
        options = [
            discord.SelectOption(
                label=f"{movie['title']} ({movie['year']})",
                description=f"{CATEGORY_NAME[movie['category']]}",
                value=str(idx),
                emoji=CATEGORY_EMOJI[movie['category']]
            )
            for idx, movie in enumerate(movies)
        ]

        super().__init__(
            placeholder="검색된 작품을 선택하세요",
            options=options,
            min_values=1,
            max_values=1
        )

        self.movies = movies
        self.form = form  # ReviewForm 인스턴스 직접 참조

    async def callback(self, interaction: discord.Interaction):
        print(f"[DEBUG] MovieSelectMenu.callback() 시작 - 작성자: {self.form.author_name}")

        selected_idx = int(self.values[0])
        movie = self.movies[selected_idx]

        print(f"[DEBUG] MovieSelectMenu.callback() 선택됨 - title: {movie['title']}, idx: {selected_idx}")

        await interaction.response.defer()

        # 감독 정보 지연 로딩
        if not movie.get('director'):
            print(f"[DEBUG] MovieSelectMenu.callback() 감독 정보 로딩 중...")
            async with aiohttp.ClientSession() as session:
                movie['director'] = await ContentSearcher._fetch_director_info(
                    session, movie['tmdb_id'], movie['media_type']
                )

        # 리뷰 저장 및 전송 - form에서 직접 참조
        await _save_and_send_review(
            interaction,
            self.form.db,
            movie,
            self.form.category,
            self.form.score,
            self.form.line_comment,
            self.form.comment,
            self.form.author_id,
            self.form.author_name,
            self.form.display_name
        )

        print(f"[DEBUG] MovieSelectMenu.callback() 완료")


class MovieSelectView(discord.ui.View):
    """TMDB 검색 결과 선택 View"""

    def __init__(self, movies: list, form: 'ReviewForm'):
        super().__init__(timeout=60.0)

        select_menu = MovieSelectMenu(movies, form)
        self.add_item(select_menu)

    async def on_timeout(self):
        print(f"[DEBUG] MovieSelectView.on_timeout() - 60초 타임아웃")
        for item in self.children:
            item.disabled = True


OTT_TYPE_NAME = {'flatrate': '🎬 구독 스트리밍', 'rent': '🏷️ 대여', 'buy': '💰 구매'}


def _build_ott_embed(movie, providers):
    emoji = CATEGORY_EMOJI.get(movie['category'], '🎬')
    cat_name = CATEGORY_NAME.get(movie['category'], '영화')
    embed = discord.Embed(title=f"{emoji} {movie['title']} ({movie['year']})", color=0x5865F2)
    embed.description = f"**{cat_name}** | 한국 스트리밍 정보"
    if movie.get('img_url'):
        embed.set_thumbnail(url=movie['img_url'])
    if not providers:
        embed.add_field(name="❌ 스트리밍 정보 없음", value="현재 한국에서 이용 가능한 스트리밍/대여/구매 정보가 없습니다.", inline=False)
    else:
        for ptype in ('flatrate', 'rent', 'buy'):
            items = providers.get(ptype, [])
            if items:
                embed.add_field(name=OTT_TYPE_NAME[ptype], value='\n'.join(f"• {i['name']}" for i in items), inline=False)
        if providers.get('link'):
            embed.add_field(name="🔗 자세히 보기", value=f"[JustWatch에서 보기]({providers['link']})", inline=False)
    embed.set_footer(text="데이터 제공: TMDB / JustWatch")
    return embed


class OTTSelectMenu(discord.ui.Select):
    """OTT 조회용 TMDB 검색 결과 선택 메뉴"""

    def __init__(self, movies: list):
        options = [
            discord.SelectOption(
                label=f"{movie['title']} ({movie['year']})",
                description=f"{CATEGORY_NAME[movie['category']]}",
                value=str(idx),
                emoji=CATEGORY_EMOJI[movie['category']]
            )
            for idx, movie in enumerate(movies)
        ]

        super().__init__(
            placeholder="검색된 작품을 선택하세요",
            options=options,
            min_values=1,
            max_values=1
        )

        self.movies = movies

    async def callback(self, interaction: discord.Interaction):
        selected_idx = int(self.values[0])
        movie = self.movies[selected_idx]

        await interaction.response.defer(ephemeral=True)

        async with aiohttp.ClientSession() as session:
            providers = await ContentSearcher.fetch_watch_providers(
                session, movie['tmdb_id'], movie['media_type']
            )

        embed = _build_ott_embed(movie, providers)
        await interaction.followup.send(embed=embed, ephemeral=True)


class OTTSelectView(discord.ui.View):
    """OTT 조회용 TMDB 검색 결과 선택 View"""

    def __init__(self, movies: list):
        super().__init__(timeout=60.0)
        self.add_item(OTTSelectMenu(movies))

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class ReviewForm(discord.ui.Modal, title="한줄평 작성"):
    def __init__(self, db, category, author_id: int, id_name: str, author_name: str, prefetched_info: tuple = None, prefetched_category: str = None):
        super().__init__()
        self.db = db
        self.category = category  # 'tmdb', 'manga', 'webtoon'
        # 작성자 정보 (생성 시 저장)
        self.display_name = author_name
        self.author_name = id_name
        self.author_id = author_id
        # 리뷰 데이터 (on_submit에서 저장)
        self.score = None
        self.line_comment = None
        self.comment = None
        # URL로 미리 가져온 만화 정보 (title, year, author, img_url)
        self.prefetched_info = prefetched_info
        self.prefetched_category = prefetched_category

        if prefetched_info:
            # URL로 정보가 있어도 제목 필드 표시 (기본값으로 자동 추출 제목)
            self.add_item(discord.ui.TextInput(
                label="작품 이름 (수정 가능)",
                default=prefetched_info[0],  # 자동 추출된 제목
                placeholder="필요시 수정하세요"
            ))
            self.add_item(discord.ui.TextInput(label="별점 (0-5)", style=discord.TextStyle.short, placeholder="예: 4.5"))
            self.add_item(discord.ui.TextInput(label="한줄평", style=discord.TextStyle.long, placeholder="한줄평을 입력하세요"))
            self.add_item(discord.ui.TextInput(label="추가 코멘트", style=discord.TextStyle.paragraph, placeholder="추가 내용을 입력하세요", required=False))
        else:
            # 기존 필드 모두 포함
            self.add_item(discord.ui.TextInput(label="작품 이름", placeholder="제목을 입력하세요"))
            self.add_item(discord.ui.TextInput(label="별점 (0-5)", style=discord.TextStyle.short, placeholder="예: 4.5"))
            self.add_item(discord.ui.TextInput(label="한줄평", style=discord.TextStyle.long, placeholder="한줄평을 입력하세요"))
            self.add_item(discord.ui.TextInput(label="추가 코멘트", style=discord.TextStyle.paragraph, placeholder="추가 내용을 입력하세요", required=False))

    async def on_submit(self, interaction: discord.Interaction):
        print(f"[DEBUG] ReviewForm.on_submit() 시작 - 카테고리: {self.category}, 작성자: {self.author_name}")

        # prefetched_info가 있으면 필드 인덱스가 다름 (제목 필드 추가됨)
        if self.prefetched_info:
            _, year, director, img_url = self.prefetched_info  # 자동 추출 제목 무시
            title = self.children[0].value  # 사용자가 입력/수정한 제목
            score = self.children[1].value  # 별점
            self.line_comment = self.children[2].value
            self.comment = self.children[3].value
            print(f"[DEBUG] ReviewForm.on_submit() prefetched_info 사용 - title: {title}, score: {score}")
        else:
            title = self.children[0].value
            score = self.children[1].value
            self.line_comment = self.children[2].value
            self.comment = self.children[3].value
            print(f"[DEBUG] ReviewForm.on_submit() 입력값 - title: {title}, score: {score}")

        try:
            self.score = float(score)
            if not (0 <= self.score <= 5):
                await interaction.response.send_message("❌ 별점은 0~5 사이의 숫자를 입력해주세요!", ephemeral=True)
                return
        except ValueError:
            await interaction.response.send_message("❌ 별점은 숫자만 입력해주세요!", ephemeral=True)
            return

        await interaction.response.defer()

        # prefetched_info가 있으면 검색 없이 바로 저장
        if self.prefetched_info:
            print(f"[DEBUG] ReviewForm.on_submit() prefetched_info로 바로 저장")
            movie_info = {
                'title': title,
                'year': year,
                'director': director,
                'img_url': img_url,
                'category': self.prefetched_category or 'manga'
            }

            await _save_and_send_review(
                interaction,
                self.db,
                movie_info,
                self.category,
                self.score,
                self.line_comment,
                self.comment,
                self.author_id,
                self.author_name,
                self.display_name
            )
            return

        original_title = title

        async with aiohttp.ClientSession() as session:
            # 카테고리별 검색
            print(f"[DEBUG] ReviewForm.on_submit() 검색 시작 - 카테고리: {self.category}")
            if self.category == 'tmdb':
                # TMDB: 다중 결과 검색
                movies = await ContentSearcher.search_tmdb_multiple(session, title)

                # 결과 없음
                if not movies:
                    print(f"[DEBUG] ReviewForm.on_submit() TMDB 검색 실패 - 결과 없음")
                    await interaction.followup.send(f"❌ '{original_title}'를 찾을 수 없습니다. 정확한 제목으로 다시 시도해주세요.", ephemeral=True)
                    return

                # 단일 결과 → 자동 선택
                if len(movies) == 1:
                    print(f"[DEBUG] ReviewForm.on_submit() TMDB 단일 결과 - 자동 선택")
                    movie = movies[0]

                    # 감독 정보 로딩
                    if not movie.get('director'):
                        movie['director'] = await ContentSearcher._fetch_director_info(
                            session, movie['tmdb_id'], movie['media_type']
                        )

                    # 기존 로직 계속
                    await _save_and_send_review(
                        interaction,
                        self.db,
                        movie,
                        self.category,
                        self.score,
                        self.line_comment,
                        self.comment,
                        self.author_id,
                        self.author_name,
                        self.display_name
                    )
                    return

                # 다중 결과 → Select Menu 표시
                print(f"[DEBUG] ReviewForm.on_submit() TMDB 다중 결과 - Select Menu 표시 ({len(movies)}개)")

                view = MovieSelectView(movies, self)

                await interaction.followup.send(
                    f"🔍 '{original_title}' 검색 결과 {len(movies)}개입니다. 작품을 선택하세요:",
                    view=view,
                    ephemeral=True
                )
                return

            elif self.category == 'manga':
                title, year, director, img_url = await ContentSearcher.search_manga(session, title)
                db_category = 'manga'
            else:  # webtoon
                title, year, director, img_url = await ContentSearcher.search_webtoon(session, title)
                db_category = 'webtoon'

            print(f"[DEBUG] ReviewForm.on_submit() 검색 결과 - title: {title}, year: {year}, director: {director}, img_url: {img_url}")

            # 검색 결과 없음 확인 (만화/웹툰만 해당)
            if title == None or director == None or year == None:
                print(f"[DEBUG] ReviewForm.on_submit() 검색 실패 - 결과 없음")
                await interaction.followup.send(f"❌ '{original_title}'를 찾을 수 없습니다. 정확한 제목으로 다시 시도해주세요.", ephemeral=True)
                return

            # 만화/웹툰: 기존 방식
            movie_info = {
                'title': title,
                'year': year,
                'director': director,
                'img_url': img_url,
                'category': db_category
            }

            await _save_and_send_review(
                interaction,
                self.db,
                movie_info,
                self.category,
                self.score,
                self.line_comment,
                self.comment,
                self.author_id,
                self.author_name,
                self.display_name
            )


# ==================== Edit Review Modal ====================

class EditReviewForm(discord.ui.Modal, title="리뷰 수정"):
    def __init__(self, db, review_data, channel, user_id, display_name, target_message=None):
        super().__init__()
        self.db = db
        self.review_data = review_data
        self.channel = channel
        self.user_id = user_id
        self.display_name = display_name
        self.target_message = target_message  # context menu에서 전달된 메시지

        # 기존 값을 default로 설정
        self.add_item(discord.ui.TextInput(
            label="별점 (0-5)",
            style=discord.TextStyle.short,
            default=str(review_data['score']),
            placeholder="예: 4.5"
        ))
        self.add_item(discord.ui.TextInput(
            label="한줄평",
            style=discord.TextStyle.long,
            default=review_data['one_line_review'],
            placeholder="한줄평을 입력하세요"
        ))
        self.add_item(discord.ui.TextInput(
            label="추가 코멘트",
            style=discord.TextStyle.paragraph,
            default=review_data['additional_comment'] or "",
            placeholder="추가 내용을 입력하세요",
            required=False
        ))

    async def on_submit(self, interaction: discord.Interaction):
        score_str = self.children[0].value
        one_line_review = self.children[1].value
        additional_comment = self.children[2].value

        # 별점 검증
        try:
            score = float(score_str)
            if not (0 <= score <= 5):
                await interaction.response.send_message("❌ 별점은 0~5 사이의 숫자를 입력해주세요!", ephemeral=True)
                return
        except ValueError:
            await interaction.response.send_message("❌ 별점은 숫자만 입력해주세요!", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        title = self.review_data['movie_title']
        category = self.review_data['category']

        # DB 업데이트
        updated = self.db.update_review(
            self.user_id, title, category,
            score, one_line_review, additional_comment
        )

        if not updated:
            await interaction.followup.send("❌ 리뷰 수정에 실패했습니다.", ephemeral=True)
            return

        # 수정 로그 기록
        self.db.log_review_action(
            user_id=self.user_id,
            username=self.display_name,
            action='edit',
            movie_title=title,
            category=category,
            old_score=self.review_data['score'],
            old_one_line_review=self.review_data['one_line_review'],
            old_additional_comment=self.review_data.get('additional_comment'),
            new_score=score,
            new_one_line_review=one_line_review,
            new_additional_comment=additional_comment
        )

        # 수정된 리뷰 메시지 생성
        year = self.review_data['movie_year']
        director = self.review_data['director']
        emoji = CATEGORY_EMOJI.get(category, "🎬")
        cat_name = CATEGORY_NAME.get(category, "영화")

        # 카테고리에 따른 검색 타입 결정
        if category in ['movie', 'drama', 'anime']:
            search_category = 'tmdb'
        elif category == 'manga':
            search_category = 'manga'
        else:
            search_category = 'webtoon'

        # 폼 생성
        if search_category == 'tmdb':
            filled_form = MOVIE_FORM.format(
                title=title,
                director_name=director,
                year=year,
                score=return_score_emoji(score),
                one_line_text=one_line_review,
                author_name=self.display_name
            )
            filled_form = filled_form.replace("🎬", emoji)
            filled_form += f"\n🏷️ 카테고리: {cat_name}"
        elif search_category == 'manga':
            filled_form = MANGA_FORM.format(
                title=title,
                author=director,
                year=year,
                score=return_score_emoji(score),
                one_line_text=one_line_review,
                author_name=self.display_name
            )
        else:  # webtoon
            filled_form = WEBTOON_FORM.format(
                title=title,
                platform=year,
                author=director,
                score=return_score_emoji(score),
                one_line_text=one_line_review,
                author_name=self.display_name
            )

        if additional_comment:
            filled_form += f"\n\n📝추가 코멘트 : {additional_comment}"

        # In-place edit 시도 (3단계 fallback)
        target_msg = None

        # 1단계: context menu에서 전달된 target_message
        if self.target_message:
            target_msg = self.target_message
            print(f"[DEBUG] EditReviewForm.on_submit() target_message 사용")

        # 2단계: DB에 저장된 message_id로 fetch
        if not target_msg:
            msg_id = self.review_data.get('message_id')
            ch_id = self.review_data.get('channel_id')
            if msg_id and ch_id:
                try:
                    channel = interaction.client.get_channel(ch_id) or await interaction.client.fetch_channel(ch_id)
                    target_msg = await channel.fetch_message(msg_id)
                    print(f"[DEBUG] EditReviewForm.on_submit() DB message_id로 메시지 fetch 성공")
                except Exception as e:
                    print(f"[DEBUG] EditReviewForm.on_submit() DB message_id로 메시지 fetch 실패: {e}")

        # 3단계: channel history scan
        if not target_msg:
            try:
                async for message in self.channel.history(limit=500):
                    if message.author == interaction.client.user:
                        if f"{emoji}제목: {title}" in message.content:
                            target_msg = message
                            print(f"[DEBUG] EditReviewForm.on_submit() channel history scan으로 메시지 발견")
                            break
            except Exception as e:
                print(f"[DEBUG] EditReviewForm.on_submit() channel history scan 실패: {e}")

        # 메시지를 찾은 경우: in-place edit (첨부파일 자동 보존)
        if target_msg:
            try:
                # 기존 반응 카운트 유지
                edit_view = ReviewReactionView()
                if self.review_data.get('id'):
                    reaction_counts = self.db.get_reaction_counts(self.review_data['id'])
                    edit_view.update_counts(reaction_counts)
                await target_msg.edit(content=filled_form, view=edit_view)
                if self.review_data.get('id'):
                    self.db.update_message_id(
                        self.review_data['id'],
                        target_msg.id,
                        target_msg.channel.id
                    )
                await interaction.followup.send(
                    f"✅ '{title}' ({cat_name}) 리뷰가 수정되었습니다.", ephemeral=True
                )
                print(f"[DEBUG] EditReviewForm.on_submit() in-place edit 성공")
                return
            except Exception as e:
                print(f"[ERROR] EditReviewForm.on_submit() in-place edit 실패: {e}")

        # 최종 fallback: 새 메시지로 전송 (이미지 다운로드 포함)
        print(f"[DEBUG] EditReviewForm.on_submit() 최종 fallback - 새 메시지로 전송")
        img_url = self.review_data.get('img_url')

        # img_url이 없으면 API 재검색
        if not img_url:
            async with aiohttp.ClientSession() as session:
                if search_category == 'tmdb':
                    _, _, _, img_url, _ = await ContentSearcher._search_tmdb_direct(session, title)
                elif search_category == 'manga':
                    _, _, _, img_url = await ContentSearcher.search_manga(session, title)
                else:
                    _, _, _, img_url = await ContentSearcher.search_webtoon(session, title)

            if img_url:
                self.db.update_review(
                    self.user_id, title, category,
                    score, one_line_review, additional_comment, img_url=img_url
                )

        # 이미지 다운로드 및 전송
        img_data = None
        if img_url:
            timeout = aiohttp.ClientTimeout(total=30)
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Referer': img_url
            }
            for attempt in range(3):
                try:
                    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                        async with session.get(img_url) as img_response:
                            if img_response.status == 200:
                                img_data = await img_response.read()
                                break
                except Exception as e:
                    print(f"[ERROR] EditReviewForm fallback 이미지 다운로드 오류 (시도 {attempt + 1}): {e}")
                if attempt < 2:
                    await asyncio.sleep(1)

        fallback_view = ReviewReactionView()
        if self.review_data.get('id'):
            fb_counts = self.db.get_reaction_counts(self.review_data['id'])
            fallback_view.update_counts(fb_counts)

        if img_data:
            file = discord.File(io.BytesIO(img_data), filename="image.jpg")
            sent_message = await interaction.followup.send(filled_form, file=file, view=fallback_view, wait=True)
        else:
            sent_message = await interaction.followup.send(filled_form, view=fallback_view, wait=True)

        if self.review_data.get('id') and sent_message:
            self.db.update_message_id(
                self.review_data['id'],
                sent_message.id,
                interaction.channel_id
            )

        await interaction.followup.send(
            f"✅ '{title}' ({cat_name}) 리뷰가 수정되었습니다. (기존 메시지를 찾지 못해 새로 전송)",
            ephemeral=True
        )


# ==================== Bot Class ====================

class MyBot(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.db = Database()
        self.news_scheduler = NewsScheduler(self)
        self.assistant_service = None

    async def on_ready(self):
        print(f'Logged in as {self.user}')

    async def setup_hook(self):
        # Persistent view 등록 (봇 재시작 후에도 기존 버튼 동작)
        self.add_view(ReviewReactionView())

        # Assistant Service 초기화
        self.assistant_service = AssistantService(self)
        await self.assistant_service.setup_gemini()

        self.tree.add_command(review_command)
        self.tree.add_command(my_reviews_command)
        self.tree.add_command(stats_command)
        self.tree.add_command(news_command)
        self.tree.add_command(delete_review_command)
        self.tree.add_command(edit_review_command)
        self.tree.add_command(ott_command)
        self.tree.add_command(edit_review_context)
        self.tree.add_command(write_review_context)
        self.tree.add_command(delete_review_context)
        self.tree.add_command(ranking_command)
        self.tree.add_command(migration_command)
        await self.tree.sync()

        # 뉴스 스케줄러 시작
        self.news_scheduler.start()

    async def on_message(self, message: discord.Message):
        # 봇 메시지 무시
        if message.author.bot:
            return

        # Assistant Service로 메시지 처리
        if self.assistant_service and self.assistant_service.monitor_channel_id:
            if message.channel.id == self.assistant_service.monitor_channel_id:
                await self.assistant_service.process_message(message)

        # 기본 커맨드 처리
        await self.process_commands(message)


# Intents 설정 (message_content 활성화)
intents = discord.Intents.default()
intents.message_content = True
bot = MyBot(command_prefix="/", intents=intents)


# ==================== Slash Commands ====================

@discord.app_commands.command(name="한줄평", description="리뷰를 작성합니다.")
@discord.app_commands.describe(카테고리="리뷰할 콘텐츠 종류", 링크="MangaDex 링크 (만화 카테고리 전용)")
@discord.app_commands.choices(카테고리=[
    discord.app_commands.Choice(name="🎬 영화/드라마/애니", value="tmdb"),
    discord.app_commands.Choice(name="📚 만화", value="manga"),
    discord.app_commands.Choice(name="📱 웹툰", value="webtoon"),
])
async def review_command(interaction: discord.Interaction, 카테고리: str, 링크: str = None):
    prefetched_info = None

    # 만화 카테고리 + 링크가 있으면 MangaDex에서 정보 미리 조회
    if 카테고리 == 'manga' and 링크:
        async with aiohttp.ClientSession() as session:
            prefetched_info = await ContentSearcher.fetch_manga_by_url(session, 링크)

        if not prefetched_info:
            await interaction.response.send_message("❌ 유효하지 않은 MangaDex URL입니다.", ephemeral=True)
            return

        print(f"[DEBUG] review_command() MangaDex URL로 정보 조회 성공: {prefetched_info[0]}")

    modal = ReviewForm(bot.db, 카테고리, interaction.user.id, str(interaction.user), interaction.user.display_name, prefetched_info)
    await interaction.response.send_modal(modal)


@discord.app_commands.command(name="내리뷰", description="내가 작성한 리뷰 목록을 조회합니다.")
@discord.app_commands.describe(카테고리="조회할 카테고리 (선택 안하면 전체)")
@discord.app_commands.choices(카테고리=[
    discord.app_commands.Choice(name="전체", value="all"),
    discord.app_commands.Choice(name="영화", value="movie"),
    discord.app_commands.Choice(name="드라마", value="drama"),
    discord.app_commands.Choice(name="애니", value="anime"),
    discord.app_commands.Choice(name="만화", value="manga"),
    discord.app_commands.Choice(name="웹툰", value="webtoon"),
])
async def my_reviews_command(interaction: discord.Interaction, 카테고리: str = "all"):
    category = None if 카테고리 == "all" else 카테고리
    reviews = bot.db.get_user_reviews(interaction.user.id, limit=5, category=category)

    if not reviews:
        await interaction.response.send_message("❌ 작성한 리뷰가 없습니다.", ephemeral=True)
        return

    title_text = f"{interaction.user.name}님의 최근 리뷰"
    if category:
        title_text += f" ({CATEGORY_NAME.get(category, category)})"

    embed = discord.Embed(title=title_text, color=0x00ff00)

    for review in reviews:
        cat = review.get('category', 'movie')
        emoji = CATEGORY_EMOJI.get(cat, "🎬")
        score_emoji = "🌕" * int(review['score'])

        # 카테고리별 표시 형식
        if cat == 'webtoon':
            subtitle = f"- {review['movie_year']}"  # 플랫폼
        else:
            subtitle = f"({review['movie_year']})"

        embed.add_field(
            name=f"{emoji} {review['movie_title']} {subtitle}",
            value=f"⭐ {score_emoji} {review['score']} /5\n💬 \"{review['one_line_review']}\"",
            inline=False
        )

    await interaction.response.send_message(embed=embed, ephemeral=True)


@discord.app_commands.command(name="통계", description="특정 작품의 평점 통계를 조회합니다.")
@discord.app_commands.describe(제목="검색할 작품 제목", 카테고리="카테고리 (선택 안하면 전체)")
@discord.app_commands.choices(카테고리=[
    discord.app_commands.Choice(name="전체", value="all"),
    discord.app_commands.Choice(name="영화", value="movie"),
    discord.app_commands.Choice(name="드라마", value="drama"),
    discord.app_commands.Choice(name="애니", value="anime"),
    discord.app_commands.Choice(name="만화", value="manga"),
    discord.app_commands.Choice(name="웹툰", value="webtoon"),
])
async def stats_command(interaction: discord.Interaction, 제목: str, 카테고리: str = "all"):
    category = None if 카테고리 == "all" else 카테고리
    stats = bot.db.get_content_stats(제목, category)

    if not stats or stats['review_count'] == 0:
        await interaction.response.send_message(f"❌ '{제목}'에 대한 리뷰가 없습니다.", ephemeral=True)
        return

    emoji = CATEGORY_EMOJI.get(category, "📊")

    embed = discord.Embed(title=f"{emoji} {제목} 통계", color=0x3498db)
    embed.add_field(name="리뷰 개수", value=f"{stats['review_count']}개", inline=True)
    embed.add_field(name="평균 평점", value=f"{stats['avg_score']:.2f}/5", inline=True)
    embed.add_field(name="최고 평점", value=f"{stats['max_score']}/5", inline=True)
    embed.add_field(name="최저 평점", value=f"{stats['min_score']}/5", inline=True)

    await interaction.response.send_message(embed=embed, ephemeral=True)


@discord.app_commands.command(name="뉴스", description="[관리자] 일일 엔터테인먼트 리포트를 즉시 전송합니다.")
@discord.app_commands.default_permissions(administrator=True)
async def news_command(interaction: discord.Interaction):
    await interaction.response.defer()

    success = await bot.news_scheduler.send_news_now(interaction.channel)

    if success:
        await interaction.followup.send("일일 엔터테인먼트 리포트를 전송했습니다.", ephemeral=True)
    else:
        await interaction.followup.send("뉴스를 가져오는 데 실패했습니다. GROK_API_KEY를 확인해주세요.", ephemeral=True)


@discord.app_commands.command(name="리뷰삭제", description="특정 작품의 내 리뷰를 삭제합니다.")
@discord.app_commands.describe(제목="삭제할 작품 제목", 카테고리="카테고리")
@discord.app_commands.choices(카테고리=[
    discord.app_commands.Choice(name="영화", value="movie"),
    discord.app_commands.Choice(name="드라마", value="drama"),
    discord.app_commands.Choice(name="애니", value="anime"),
    discord.app_commands.Choice(name="만화", value="manga"),
    discord.app_commands.Choice(name="웹툰", value="webtoon"),
])
async def delete_review_command(interaction: discord.Interaction, 제목: str, 카테고리: str = None):
    await interaction.response.defer(ephemeral=True)

    # 삭제 전 기존 데이터 조회 (로그용 + 메시지 삭제용)
    review = bot.db.get_user_review(interaction.user.id, 제목, 카테고리)

    if not review:
        await interaction.followup.send(f"❌ '{제목}' 리뷰를 찾을 수 없습니다.")
        return

    # 메시지 및 쓰레드 삭제 시도 (DB 삭제 전에 수행)
    message_deleted = False
    thread_deleted = False

    if review.get('message_id') and review.get('channel_id'):
        try:
            channel = bot.get_channel(review['channel_id'])
            if channel:
                message = await channel.fetch_message(review['message_id'])
                if message:
                    # 쓰레드가 있으면 먼저 삭제
                    if message.thread:
                        try:
                            await message.thread.delete()
                            thread_deleted = True
                        except Exception as e:
                            print(f"[WARN] Failed to delete thread: {e}")

                    # 메시지 삭제
                    await message.delete()
                    message_deleted = True
        except discord.NotFound:
            pass  # 메시지가 이미 삭제됨
        except Exception as e:
            print(f"[WARN] Failed to delete review message: {e}")

    # DB에서 삭제 (CASCADE로 reactions, comments도 자동 삭제)
    deleted = bot.db.delete_review(interaction.user.id, 제목, 카테고리)

    if deleted:
        # 삭제 로그 기록
        bot.db.log_review_action(
            user_id=interaction.user.id,
            username=interaction.user.display_name,
            action='delete',
            movie_title=제목,
            category=review.get('category', 카테고리),
            old_score=review['score'],
            old_one_line_review=review['one_line_review'],
            old_additional_comment=review.get('additional_comment')
        )

        cat_text = f" ({CATEGORY_NAME.get(카테고리, '')})" if 카테고리 else ""

        # 결과 메시지 구성
        result_parts = [f"✅ '{제목}'{cat_text} 리뷰가 삭제되었습니다."]
        if message_deleted:
            result_parts.append("메시지 삭제됨")
        if thread_deleted:
            result_parts.append("쓰레드 삭제됨")

        if message_deleted or thread_deleted:
            await interaction.followup.send(f"{result_parts[0]} ({', '.join(result_parts[1:])})")
        else:
            await interaction.followup.send(f"{result_parts[0]} (DB에서만 삭제됨)")
    else:
        await interaction.followup.send(f"❌ '{제목}' 리뷰 삭제 중 오류가 발생했습니다.")


@discord.app_commands.command(name="리뷰수정", description="작성한 리뷰를 수정합니다.")
@discord.app_commands.describe(제목="수정할 작품 제목", 카테고리="카테고리")
@discord.app_commands.choices(카테고리=[
    discord.app_commands.Choice(name="영화", value="movie"),
    discord.app_commands.Choice(name="드라마", value="drama"),
    discord.app_commands.Choice(name="애니", value="anime"),
    discord.app_commands.Choice(name="만화", value="manga"),
    discord.app_commands.Choice(name="웹툰", value="webtoon"),
])
async def edit_review_command(interaction: discord.Interaction, 제목: str, 카테고리: str = None):
    # DB에서 리뷰 조회
    review = bot.db.get_user_review(interaction.user.id, 제목, 카테고리)

    if not review:
        cat_text = f" ({CATEGORY_NAME.get(카테고리, '')})" if 카테고리 else ""
        await interaction.response.send_message(
            f"❌ '{제목}'{cat_text} 리뷰를 찾을 수 없습니다.",
            ephemeral=True
        )
        return

    # EditReviewForm 모달 표시
    modal = EditReviewForm(
        bot.db,
        review,
        interaction.channel,
        interaction.user.id,
        interaction.user.display_name
    )
    await interaction.response.send_modal(modal)


@discord.app_commands.command(name="어디서봐", description="작품의 OTT/스트리밍 정보를 조회합니다.")
@discord.app_commands.describe(제목="검색할 작품 제목")
async def ott_command(interaction: discord.Interaction, 제목: str):
    await interaction.response.defer(ephemeral=True)

    async with aiohttp.ClientSession() as session:
        movies = await ContentSearcher.search_tmdb_multiple(session, 제목)

        if not movies:
            await interaction.followup.send(f"❌ '{제목}'를 찾을 수 없습니다. 정확한 제목으로 다시 시도해주세요.", ephemeral=True)
            return

        if len(movies) == 1:
            movie = movies[0]
            providers = await ContentSearcher.fetch_watch_providers(
                session, movie['tmdb_id'], movie['media_type']
            )
            embed = _build_ott_embed(movie, providers)
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

    view = OTTSelectView(movies)
    await interaction.followup.send(
        f"🔍 '{제목}' 검색 결과 {len(movies)}개입니다. 작품을 선택하세요:",
        view=view,
        ephemeral=True
    )


# ==================== Context Menu Commands ====================

@discord.app_commands.context_menu(name="리뷰 수정")
async def edit_review_context(interaction: discord.Interaction, message: discord.Message):
    # 봇이 보낸 메시지인지 확인
    if message.author != interaction.client.user:
        await interaction.response.send_message("❌ 봇이 보낸 리뷰 메시지만 수정할 수 있습니다.", ephemeral=True)
        return

    # 메시지에서 title, category 파싱
    title, category = parse_review_message(message.content)
    if not title or not category:
        await interaction.response.send_message("❌ 리뷰 메시지를 인식할 수 없습니다.", ephemeral=True)
        return

    # DB에서 리뷰 조회 (소유권 확인)
    review = bot.db.get_user_review(interaction.user.id, title, category)
    if not review:
        await interaction.response.send_message(
            f"❌ '{title}' 리뷰를 찾을 수 없거나 본인의 리뷰가 아닙니다.", ephemeral=True
        )
        return

    if not is_current_review_message(review, message):
        await interaction.response.send_message(
            "❌ 최신 리뷰 메시지에서만 수정할 수 있습니다. 가장 최근에 전송된 리뷰 메시지로 다시 시도해주세요.",
            ephemeral=True
        )
        return

    # EditReviewForm 모달 표시 (target_message 전달)
    modal = EditReviewForm(
        bot.db,
        review,
        interaction.channel,
        interaction.user.id,
        interaction.user.display_name,
        target_message=message
    )
    await interaction.response.send_modal(modal)


# DB category → search category 매핑
CATEGORY_TO_SEARCH = {'movie': 'tmdb', 'drama': 'tmdb', 'anime': 'tmdb', 'manga': 'manga', 'webtoon': 'webtoon'}


@discord.app_commands.context_menu(name="나도 쓰기")
async def write_review_context(interaction: discord.Interaction, message: discord.Message):
    # 봇이 보낸 메시지인지 확인
    if message.author != interaction.client.user:
        await interaction.response.send_message("❌ 봇이 보낸 리뷰 메시지에서만 사용할 수 있습니다.", ephemeral=True)
        return

    # 메시지에서 title, category 파싱
    title, db_category = parse_review_message(message.content)
    if not title or not db_category:
        await interaction.response.send_message("❌ 리뷰 메시지를 인식할 수 없습니다.", ephemeral=True)
        return

    # director, year 파싱
    director, year = parse_review_detail(message.content)

    # 포스터 이미지 URL 획득
    img_url = message.attachments[0].url if message.attachments else None

    search_category = CATEGORY_TO_SEARCH[db_category]
    prefetched_info = (title, year, director, img_url)

    modal = ReviewForm(
        bot.db,
        search_category,
        interaction.user.id,
        str(interaction.user),
        interaction.user.display_name,
        prefetched_info=prefetched_info,
        prefetched_category=db_category
    )
    await interaction.response.send_modal(modal)


@discord.app_commands.context_menu(name="리뷰 삭제")
async def delete_review_context(interaction: discord.Interaction, message: discord.Message):
    # 먼저 defer로 응답 시간 연장
    await interaction.response.defer(ephemeral=True)

    # 봇이 보낸 메시지인지 확인
    if message.author != interaction.client.user:
        await interaction.followup.send("❌ 봇이 보낸 리뷰 메시지만 삭제할 수 있습니다.", ephemeral=True)
        return

    # 메시지에서 title, category 파싱
    title, category = parse_review_message(message.content)
    if not title or not category:
        await interaction.followup.send("❌ 리뷰 메시지를 인식할 수 없습니다.", ephemeral=True)
        return

    # DB에서 리뷰 조회 (소유권 확인)
    review = bot.db.get_user_review(interaction.user.id, title, category)
    if not review:
        await interaction.followup.send(
            f"❌ '{title}' 리뷰를 찾을 수 없거나 본인의 리뷰가 아닙니다.", ephemeral=True
        )
        return

    if not is_current_review_message(review, message):
        await interaction.followup.send(
            "❌ 최신 리뷰 메시지에서만 삭제할 수 있습니다. 가장 최근에 전송된 리뷰 메시지로 다시 시도해주세요.",
            ephemeral=True
        )
        return

    # DB 삭제
    deleted = bot.db.delete_review(interaction.user.id, title, category)
    if not deleted:
        await interaction.followup.send("❌ 리뷰 삭제에 실패했습니다.", ephemeral=True)
        return

    # 삭제 로그 기록
    bot.db.log_review_action(
        user_id=interaction.user.id,
        username=interaction.user.display_name,
        action='delete',
        movie_title=title,
        category=category,
        old_score=review['score'],
        old_one_line_review=review['one_line_review'],
        old_additional_comment=review.get('additional_comment')
    )

    # 메시지 삭제
    try:
        await message.delete()
    except Exception as e:
        print(f"[ERROR] delete_review_context() 메시지 삭제 실패: {e}")

    cat_name = CATEGORY_NAME.get(category, "")
    await interaction.followup.send(
        f"✅ '{title}' ({cat_name}) 리뷰가 삭제되었습니다.", ephemeral=True
    )


# ==================== 리뷰 랭킹 ====================

from review_interaction import REACTION_TYPES

@discord.app_commands.command(name="마이그레이션", description="[관리자] 채널의 레거시 리뷰 메시지를 DB로 마이그레이션합니다.")
@discord.app_commands.default_permissions(administrator=True)
@discord.app_commands.describe(채널="마이그레이션할 채널", 메시지수="스캔할 메시지 수 (기본 100)")
async def migration_command(interaction: discord.Interaction, 채널: discord.TextChannel, 메시지수: int = 100):
    await interaction.response.defer()

    progress_msg = await interaction.followup.send(
        f"🔄 {채널.mention} 채널에서 최근 {메시지수}개 메시지를 스캔 중...",
        wait=True
    )

    migrated = 0
    skipped = 0
    failed = 0
    processed = 0

    try:
        async for message in 채널.history(limit=메시지수):
            processed += 1

            # 봇 메시지는 스킵
            if message.author.bot:
                skipped += 1
                continue

            # 메시지 내용이 없으면 스킵
            if not message.content or len(message.content) < 10:
                skipped += 1
                continue

            # 이미 현재 형식인지 확인 (이모지로 시작하면 스킵)
            first_line = message.content.split('\n')[0]
            if any(first_line.startswith(f"{emoji}제목:") for emoji in CATEGORY_EMOJI.values()):
                skipped += 1
                continue

            # LLM으로 파싱 시도
            try:
                parsed = await GrokSearcher.parse_legacy_review(
                    message.content,
                    message.author.display_name
                )

                if not parsed:
                    skipped += 1
                    continue

                # 필수 필드 확인
                title = parsed.get('title')
                score = parsed.get('score')
                one_line = parsed.get('one_line_review')
                category = parsed.get('category', 'movie')

                if not title or score is None or not one_line:
                    skipped += 1
                    continue

                # score를 float로 변환 및 범위 확인
                try:
                    score = float(score)
                    score = max(0, min(5, score))
                except (ValueError, TypeError):
                    skipped += 1
                    continue

                # 카테고리 검증
                if category not in CATEGORY_EMOJI:
                    category = 'movie'

                # DB 저장
                review_id = bot.db.save_migrated_review(
                    user_id=message.author.id,
                    username=str(message.author),
                    movie_title=title,
                    movie_year=parsed.get('year'),
                    director=parsed.get('director'),
                    score=score,
                    one_line_review=one_line,
                    category=category,
                    created_at=message.created_at,
                    message_id=message.id,
                    channel_id=message.channel.id
                )

                if review_id:
                    migrated += 1
                    print(f"[MIGRATION] ✅ {title} ({category}) - {message.author.display_name}")
                else:
                    failed += 1

            except Exception as e:
                print(f"[MIGRATION] ❌ 파싱 오류: {e}")
                failed += 1

            # 10개마다 진행 상황 업데이트
            if processed % 10 == 0:
                await progress_msg.edit(
                    content=f"🔄 스캔 중... ({processed}/{메시지수})\n"
                            f"✅ 마이그레이션: {migrated} | ⏭️ 스킵: {skipped} | ❌ 실패: {failed}"
                )

    except Exception as e:
        await interaction.followup.send(f"❌ 마이그레이션 중 오류 발생: {e}")
        return

    # 최종 결과
    await progress_msg.edit(
        content=f"✅ **마이그레이션 완료**\n\n"
                f"📊 총 스캔: {processed}개\n"
                f"✅ 마이그레이션: {migrated}개\n"
                f"⏭️ 스킵: {skipped}개\n"
                f"❌ 실패: {failed}개"
    )


@discord.app_commands.command(name="리뷰랭킹", description="반응이 많은 인기 리뷰 TOP 10을 조회합니다.")
@discord.app_commands.describe(카테고리="카테고리별 필터링 (선택)")
@discord.app_commands.choices(카테고리=[
    discord.app_commands.Choice(name="🎬 영화", value="movie"),
    discord.app_commands.Choice(name="📺 드라마", value="drama"),
    discord.app_commands.Choice(name="🎌 애니", value="anime"),
    discord.app_commands.Choice(name="📚 만화", value="manga"),
    discord.app_commands.Choice(name="📱 웹툰", value="webtoon"),
])
async def ranking_command(interaction: discord.Interaction, 카테고리: discord.app_commands.Choice[str] = None):
    await interaction.response.defer()

    category = 카테고리.value if 카테고리 else None
    rankings = bot.db.get_review_ranking(limit=10, category=category)

    if not rankings:
        await interaction.followup.send("📊 아직 반응이 달린 리뷰가 없습니다.", ephemeral=True)
        return

    cat_label = 카테고리.name if 카테고리 else "전체"
    embed = discord.Embed(
        title=f"🏆 리뷰 랭킹 TOP {len(rankings)} ({cat_label})",
        color=discord.Color.gold(),
    )

    for idx, review in enumerate(rankings, 1):
        emoji = CATEGORY_EMOJI.get(review['category'], '🎬')
        cat_name = CATEGORY_NAME.get(review['category'], '영화')

        # Reaction breakdown
        counts = bot.db.get_reaction_counts(review['id'])
        breakdown = " ".join(
            f"{REACTION_TYPES[rt]['emoji']}{cnt}"
            for rt, cnt in counts.items() if cnt > 0
        )

        score_str = return_score_emoji(review['score'])
        field_name = f"{idx}. {emoji} {review['movie_title']}"
        field_value = (
            f"{score_str} | {cat_name}\n"
            f"✍️ {review['username']} | 💬 \"{review['one_line_review']}\"\n"
            f"반응: {breakdown} (총 {review['reaction_count']}개)"
        )
        embed.add_field(name=field_name, value=field_value, inline=False)

    await interaction.followup.send(embed=embed)


bot.run(Token)
