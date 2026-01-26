import discord
import aiohttp
import asyncio
from discord.ext import commands
from review_form import MOVIE_FORM, MANGA_FORM, WEBTOON_FORM

# 카테고리별 이모지 및 이름 매핑
CATEGORY_EMOJI = {"movie": "🎬", "drama": "📺", "anime": "🎌", "manga": "📚", "webtoon": "📱"}
CATEGORY_NAME = {"movie": "영화", "drama": "드라마", "anime": "애니", "manga": "만화", "webtoon": "웹툰"}
from database import Database
from api_searcher import ContentSearcher
import io
import os

Token = os.getenv("Token")


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

    return score_emoji


async def _save_and_send_review(
    interaction: discord.Interaction,
    db,
    movie_info: dict,
    category: str,
    score_float: float,
    line_comment: str,
    comment: str
):
    """리뷰 저장 및 메시지 전송 (공통 로직)"""
    print(f"[DEBUG] _save_and_send_review() 시작")

    title = movie_info['title']
    year = movie_info['year']
    director = movie_info['director']
    img_url = movie_info['img_url']
    db_category = movie_info['category']

    # 중복 확인
    print(f"[DEBUG] _save_and_send_review() 중복 확인 중...")
    if db.has_review(interaction.user.id, title, db_category):
        print(f"[DEBUG] _save_and_send_review() 중복 발견")
        await interaction.followup.send(
            f"❌ 이미 '{title}'에 대한 리뷰를 작성하셨습니다.\n`/리뷰삭제`로 기존 리뷰를 삭제하세요.",
            ephemeral=True
        )
        return

    # DB 저장
    print(f"[DEBUG] _save_and_send_review() DB 저장 중...")
    db.save_review(
        user_id=interaction.user.id,
        username=str(interaction.user),
        movie_title=title,
        movie_year=year,
        director=director,
        score=score_float,
        one_line_review=line_comment,
        additional_comment=comment,
        category=db_category
    )
    print(f"[DEBUG] _save_and_send_review() DB 저장 완료")

    # 카테고리별 출력 형식
    emoji = CATEGORY_EMOJI.get(db_category, "🎬")
    cat_name = CATEGORY_NAME.get(db_category, "영화")

    if category == 'tmdb':
        filled_form = MOVIE_FORM.format(
            title=title,
            director_name=director,
            year=year,
            score=return_score_emoji(score_float),
            one_line_text=line_comment
        )
        filled_form = filled_form.replace("🎬", emoji)
        filled_form += f"\n🏷️ 카테고리: {cat_name}"
    elif category == 'manga':
        filled_form = MANGA_FORM.format(
            title=title,
            author=director,
            year=year,
            score=return_score_emoji(score_float),
            one_line_text=line_comment
        )
    else:  # webtoon
        filled_form = WEBTOON_FORM.format(
            title=title,
            platform=year,
            author=director,
            score=return_score_emoji(score_float),
            one_line_text=line_comment
        )

    if comment:
        filled_form += f"\n\n📝추가 코멘트 : {comment}"

    # 이미지 다운로드 및 전송
    print(f"[DEBUG] _save_and_send_review() 이미지 처리 - img_url: {img_url}")
    if img_url:
        print(f"[DEBUG] _save_and_send_review() 이미지 다운로드 시작 - URL: {img_url}")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(img_url) as img_response:
                    print(f"[DEBUG] _save_and_send_review() 이미지 응답 상태: {img_response.status}")
                    if img_response.status == 200:
                        img_data = await img_response.read()
                        print(f"[DEBUG] _save_and_send_review() 이미지 다운로드 성공 (크기: {len(img_data)} bytes)")
                        file = discord.File(io.BytesIO(img_data), filename="image.jpg")
                        await interaction.followup.send(filled_form, file=file)
                        print(f"[DEBUG] _save_and_send_review() 이미지 포함 메시지 전송 완료")
                    else:
                        print(f"[DEBUG] _save_and_send_review() 이미지 다운로드 실패 (상태: {img_response.status}), 텍스트만 전송")
                        await interaction.followup.send(filled_form)
        except Exception as e:
            print(f"[ERROR] _save_and_send_review() 이미지 다운로드 중 오류: {e}")
            await interaction.followup.send(filled_form)
    else:
        print(f"[DEBUG] _save_and_send_review() img_url 없음, 텍스트만 전송")
        await interaction.followup.send(filled_form)

    print(f"[DEBUG] _save_and_send_review() 완료")


# ==================== 통합 Modal ====================

class MovieSelectMenu(discord.ui.Select):
    """TMDB 검색 결과 선택 메뉴"""

    def __init__(self, movies: list, review_data: dict):
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
        self.review_data = review_data
        self.db = None  # View에서 주입됨

    async def callback(self, interaction: discord.Interaction):
        print(f"[DEBUG] MovieSelectMenu.callback() 시작")

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

        # 리뷰 저장 및 전송
        await _save_and_send_review(
            interaction,
            self.db,
            movie,
            self.view.category,
            self.review_data['score'],
            self.review_data['line_comment'],
            self.review_data['comment']
        )

        print(f"[DEBUG] MovieSelectMenu.callback() 완료")


class MovieSelectView(discord.ui.View):
    """TMDB 검색 결과 선택 View"""

    def __init__(self, movies: list, review_data: dict, db, category: str):
        super().__init__(timeout=60.0)

        select_menu = MovieSelectMenu(movies, review_data)
        select_menu.db = db
        self.category = category
        self.add_item(select_menu)

    async def on_timeout(self):
        print(f"[DEBUG] MovieSelectView.on_timeout() - 60초 타임아웃")
        for item in self.children:
            item.disabled = True


class ReviewForm(discord.ui.Modal, title="한줄평 작성"):
    def __init__(self, db, category):
        super().__init__()
        self.db = db
        self.category = category  # 'tmdb', 'manga', 'webtoon'
        self.add_item(discord.ui.TextInput(label="작품 이름", placeholder="제목을 입력하세요"))
        self.add_item(discord.ui.TextInput(label="별점 (0-5)", style=discord.TextStyle.short, placeholder="예: 4.5"))
        self.add_item(discord.ui.TextInput(label="한줄평", style=discord.TextStyle.long, placeholder="한줄평을 입력하세요"))
        self.add_item(discord.ui.TextInput(label="추가 코멘트", style=discord.TextStyle.paragraph, placeholder="추가 내용을 입력하세요", required=False))

    async def on_submit(self, interaction: discord.Interaction):
        print(f"[DEBUG] ReviewForm.on_submit() 시작 - 카테고리: {self.category}")
        title = self.children[0].value
        score = self.children[1].value
        line_comment = self.children[2].value
        comment = self.children[3].value

        print(f"[DEBUG] ReviewForm.on_submit() 입력값 - title: {title}, score: {score}")

        try:
            score_float = float(score)
            if not (0 <= score_float <= 5):
                await interaction.response.send_message("❌ 별점은 0~5 사이의 숫자를 입력해주세요!", ephemeral=True)
                return
        except ValueError:
            await interaction.response.send_message("❌ 별점은 숫자만 입력해주세요!", ephemeral=True)
            return

        await interaction.response.defer()

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
                        score_float,
                        line_comment,
                        comment
                    )
                    return

                # 다중 결과 → Select Menu 표시
                print(f"[DEBUG] ReviewForm.on_submit() TMDB 다중 결과 - Select Menu 표시 ({len(movies)}개)")
                review_data = {
                    'score': score_float,
                    'line_comment': line_comment,
                    'comment': comment,
                    'user_id': interaction.user.id,
                    'username': str(interaction.user)
                }

                view = MovieSelectView(movies, review_data, self.db, self.category)

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
                score_float,
                line_comment,
                comment
            )


# ==================== Bot Class ====================

class MyBot(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.db = Database()

    async def on_ready(self):
        print(f'Logged in as {self.user}')

    async def setup_hook(self):
        self.tree.add_command(review_command)
        self.tree.add_command(my_reviews_command)
        self.tree.add_command(stats_command)
        self.tree.add_command(delete_review_command)
        await self.tree.sync()


bot = MyBot(command_prefix="/", intents=discord.Intents.default())


# ==================== Slash Commands ====================

@discord.app_commands.command(name="한줄평", description="리뷰를 작성합니다.")
@discord.app_commands.describe(카테고리="리뷰할 콘텐츠 종류")
@discord.app_commands.choices(카테고리=[
    discord.app_commands.Choice(name="🎬 영화/드라마/애니", value="tmdb"),
    discord.app_commands.Choice(name="📚 만화", value="manga"),
    discord.app_commands.Choice(name="📱 웹툰", value="webtoon"),
])
async def review_command(interaction: discord.Interaction, 카테고리: str):
    modal = ReviewForm(bot.db, 카테고리)
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
            value=f"⭐ {score_emoji} {review['score']}/5\n💬 \"{review['one_line_review']}\"",
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
    deleted = bot.db.delete_review(interaction.user.id, 제목, 카테고리)

    if deleted:
        cat_text = f" ({CATEGORY_NAME.get(카테고리, '')})" if 카테고리 else ""

        # 채널에서 메시지 삭제 시도
        deleted_count = 0

        async for message in interaction.channel.history(limit=500):
            if message.author == bot.user:
                # 카테고리별 이모지로 메시지 확인
                for cat, emoji in CATEGORY_EMOJI.items():
                    if f"{emoji}제목: {제목}" in message.content:
                        if 카테고리 is None or cat == 카테고리:
                            await message.delete()
                            deleted_count += 1
                            break

        if deleted_count > 0:
            await interaction.response.send_message(f"✅ '{제목}'{cat_text} 리뷰가 삭제되었습니다. (메시지 {deleted_count}개 삭제)", ephemeral=True)
        else:
            await interaction.response.send_message(f"✅ '{제목}'{cat_text} 리뷰가 DB에서 삭제되었습니다.", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ '{제목}' 리뷰를 찾을 수 없습니다.", ephemeral=True)


bot.run(Token)