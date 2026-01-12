import discord
import requests
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


# ==================== Modal Classes ====================

class TMDBReviewForm(discord.ui.Modal, title="영화/드라마/애니 리뷰 작성"):
    def __init__(self, db):
        super().__init__()
        self.db = db
        self.add_item(discord.ui.TextInput(label="작품 이름", placeholder="영화, 드라마, 애니메이션 제목을 입력하세요"))
        self.add_item(discord.ui.TextInput(label="별점 (0-5)", style=discord.TextStyle.short, placeholder="예: 4.5"))
        self.add_item(discord.ui.TextInput(label="한줄평", style=discord.TextStyle.long, placeholder="한줄평을 입력하세요"))
        self.add_item(discord.ui.TextInput(label="추가 코멘트", style=discord.TextStyle.paragraph, placeholder="추가 내용을 입력하세요", required=False))

    async def on_submit(self, interaction: discord.Interaction):
        title = self.children[0].value
        score = self.children[1].value
        line_comment = self.children[2].value
        comment = self.children[3].value

        try:
            score_float = float(score)
            if not (0 <= score_float <= 5):
                await interaction.response.send_message("❌ 별점은 0~5 사이의 숫자를 입력해주세요!", ephemeral=True)
                return
        except ValueError:
            await interaction.response.send_message("❌ 별점은 숫자만 입력해주세요!", ephemeral=True)
            return

        await interaction.response.defer()

        # TMDB 검색 (카테고리 자동 분류: movie/drama/anime)
        title, year, director, img_url, category = ContentSearcher.search_tmdb(title)

        # 중복 확인
        if self.db.has_review(interaction.user.id, title, category):
            await interaction.followup.send(f"❌ 이미 '{title}'에 대한 리뷰를 작성하셨습니다.\n`/리뷰삭제`로 기존 리뷰를 삭제하세요.", ephemeral=True)
            return

        # DB 저장
        self.db.save_review(
            user_id=interaction.user.id,
            username=str(interaction.user),
            movie_title=title,
            movie_year=year,
            director=director,
            score=score_float,
            one_line_review=line_comment,
            additional_comment=comment,
            category=category
        )

        # 카테고리별 이모지 선택
        emoji = CATEGORY_EMOJI.get(category, "🎬")
        cat_name = CATEGORY_NAME.get(category, "영화")

        filled_form = MOVIE_FORM.format(
            title=title,
            director_name=director,
            year=year,
            score=return_score_emoji(score),
            one_line_text=line_comment
        )
        # 카테고리 표시 추가
        filled_form = filled_form.replace("🎬", emoji)
        filled_form += f"\n🏷️ 카테고리: {cat_name}"

        if comment:
            filled_form += f"\n\n📝추가 코멘트 : {comment}"

        if img_url:
            img_response = requests.get(img_url)
            file = discord.File(io.BytesIO(img_response.content), filename="poster.jpg")
            await interaction.followup.send(filled_form, file=file)
        else:
            await interaction.followup.send(filled_form)


class MangaReviewForm(discord.ui.Modal, title="만화 리뷰 작성"):
    def __init__(self, db):
        super().__init__()
        self.db = db
        self.add_item(discord.ui.TextInput(label="만화 이름", placeholder="제목을 입력하세요"))
        self.add_item(discord.ui.TextInput(label="별점 (0-5)", style=discord.TextStyle.short, placeholder="예: 4.5"))
        self.add_item(discord.ui.TextInput(label="한줄평", style=discord.TextStyle.long, placeholder="한줄평을 입력하세요"))
        self.add_item(discord.ui.TextInput(label="추가 코멘트", style=discord.TextStyle.paragraph, placeholder="추가 내용을 입력하세요", required=False))

    async def on_submit(self, interaction: discord.Interaction):
        title = self.children[0].value
        score = self.children[1].value
        line_comment = self.children[2].value
        comment = self.children[3].value

        try:
            score_float = float(score)
            if not (0 <= score_float <= 5):
                await interaction.response.send_message("❌ 별점은 0~5 사이의 숫자를 입력해주세요!", ephemeral=True)
                return
        except ValueError:
            await interaction.response.send_message("❌ 별점은 숫자만 입력해주세요!", ephemeral=True)
            return

        await interaction.response.defer()

        # 만화 정보 검색 (AniList)
        title, year, author, img_url = ContentSearcher.search_manga(title)

        # 중복 확인
        if self.db.has_review(interaction.user.id, title, 'manga'):
            await interaction.followup.send(f"❌ 이미 '{title}'에 대한 리뷰를 작성하셨습니다.\n`/리뷰삭제`로 기존 리뷰를 삭제하세요.", ephemeral=True)
            return

        # DB 저장
        self.db.save_review(
            user_id=interaction.user.id,
            username=str(interaction.user),
            movie_title=title,
            movie_year=year,
            director=author,  # 만화는 작가
            score=score_float,
            one_line_review=line_comment,
            additional_comment=comment,
            category='manga'
        )

        filled_form = MANGA_FORM.format(
            title=title,
            author=author,
            year=year,
            score=return_score_emoji(score),
            one_line_text=line_comment
        )

        if comment:
            filled_form += f"\n\n📝추가 코멘트 : {comment}"

        if img_url:
            img_response = requests.get(img_url)
            file = discord.File(io.BytesIO(img_response.content), filename="cover.jpg")
            await interaction.followup.send(filled_form, file=file)
        else:
            await interaction.followup.send(filled_form)


class WebtoonReviewForm(discord.ui.Modal, title="웹툰 리뷰 작성"):
    def __init__(self, db):
        super().__init__()
        self.db = db
        self.add_item(discord.ui.TextInput(label="웹툰 이름", placeholder="제목을 입력하세요"))
        self.add_item(discord.ui.TextInput(label="별점 (0-5)", style=discord.TextStyle.short, placeholder="예: 4.5"))
        self.add_item(discord.ui.TextInput(label="한줄평", style=discord.TextStyle.long, placeholder="한줄평을 입력하세요"))
        self.add_item(discord.ui.TextInput(label="추가 코멘트", style=discord.TextStyle.paragraph, placeholder="추가 내용을 입력하세요", required=False))

    async def on_submit(self, interaction: discord.Interaction):
        title = self.children[0].value
        score = self.children[1].value
        line_comment = self.children[2].value
        comment = self.children[3].value

        try:
            score_float = float(score)
            if not (0 <= score_float <= 5):
                await interaction.response.send_message("❌ 별점은 0~5 사이의 숫자를 입력해주세요!", ephemeral=True)
                return
        except ValueError:
            await interaction.response.send_message("❌ 별점은 숫자만 입력해주세요!", ephemeral=True)
            return

        await interaction.response.defer()

        # 웹툰 정보 검색
        title, platform, author, img_url = ContentSearcher.search_webtoon(title)

        # 중복 확인
        if self.db.has_review(interaction.user.id, title, 'webtoon'):
            await interaction.followup.send(f"❌ 이미 '{title}'에 대한 리뷰를 작성하셨습니다.\n`/리뷰삭제`로 기존 리뷰를 삭제하세요.", ephemeral=True)
            return

        # DB 저장 (platform을 movie_year 필드에 저장)
        self.db.save_review(
            user_id=interaction.user.id,
            username=str(interaction.user),
            movie_title=title,
            movie_year=platform,  # 웹툰은 플랫폼
            director=author,  # 웹툰은 작가
            score=score_float,
            one_line_review=line_comment,
            additional_comment=comment,
            category='webtoon'
        )

        filled_form = WEBTOON_FORM.format(
            title=title,
            platform=platform,
            author=author,
            score=return_score_emoji(score),
            one_line_text=line_comment
        )

        if comment:
            filled_form += f"\n\n📝추가 코멘트 : {comment}"

        if img_url:
            img_response = requests.get(img_url)
            file = discord.File(io.BytesIO(img_response.content), filename="thumbnail.jpg")
            await interaction.followup.send(filled_form, file=file)
        else:
            await interaction.followup.send(filled_form)


# ==================== Category Select ====================

class CategorySelect(discord.ui.Select):
    def __init__(self, db):
        self.db = db
        options = [
            discord.SelectOption(label="영화/드라마/애니", value="tmdb", emoji="🎬", description="TMDB에서 검색 (자동 분류)"),
            discord.SelectOption(label="만화", value="manga", emoji="📚", description="AniList에서 검색"),
            discord.SelectOption(label="웹툰", value="webtoon", emoji="📱", description="네이버에서만 검색(제발 카카오 유명한거는 ani로)"),
        ]
        super().__init__(placeholder="리뷰할 카테고리를 선택하세요", options=options)

    async def callback(self, interaction: discord.Interaction):
        category = self.values[0]

        if category == "tmdb":
            modal = TMDBReviewForm(self.db)
        elif category == "manga":
            modal = MangaReviewForm(self.db)
        else:
            modal = WebtoonReviewForm(self.db)

        await interaction.response.send_modal(modal)


class CategoryView(discord.ui.View):
    def __init__(self, db):
        super().__init__(timeout=60)
        self.add_item(CategorySelect(db))


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
async def review_command(interaction: discord.Interaction):
    view = CategoryView(bot.db)
    await interaction.response.send_message("📝 리뷰할 카테고리를 선택하세요:", view=view, ephemeral=True)


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
