import discord
import requests
from discord.ext import commands
from dico_token import Token
from review_form import FORM
from database import Database
import json
import io
import os
# Token = os.getenv("Token")


class ReviewForm(discord.ui.Modal, title="리뷰 작성 폼"):
    def __init__(self, db):
        super().__init__()
        self.db = db

        # 입력 필드 추가
        self.add_item(discord.ui.TextInput(label="영화 이름", placeholder="제목을 입력하세요"))
        self.add_item(discord.ui.TextInput(label="영화 별점", style=discord.TextStyle.short, placeholder="별점을 입력하세요"))
        self.add_item(discord.ui.TextInput(label="영화 한줄평", style=discord.TextStyle.long, placeholder="한줄평을 입력하세요"))
        self.add_item(discord.ui.TextInput(label="영화 추가 내용", style=discord.TextStyle.paragraph, placeholder="추가 내용을 입력하세요", required=False))

    def return_score_emoji(self, score):
        float_number = min( float(score), 5 )
        int_number = int(float_number)
        none_number = int(5-int_number)

        float_number = float_number % 1

        score_emoji = ":full_moon:" * int_number

        if 0.1 <= float_number <= 0.3:
            score_emoji += ':waning_crescent_moon:'
        elif float_number == 0.5:
            score_emoji += ':last_quarter_moon:'
        elif 0.6 <= float_number <= 0.9:
            score_emoji += ':waning_gibbous_moon:'

        score_emoji += ':new_moon:' * none_number

        return score_emoji

    def namuWikiReturn(self, name):
        URL = f"ed858620292ea4710cb4dc894449f6ea"
        search_url = f"https://api.themoviedb.org/3/search/movie?api_key={URL}&query={name}&language=ko-KR"
        response = requests.get(search_url)
        data = response.json()

        if data['results']:
            movie = data['results'][0]
            title = movie['title']
            year = movie['release_date'][:4] if movie.get('release_date') else "N/A"
        
            # 상세 정보 가져오기 (감독 정보 포함)
            movie_id = movie['id']
            details_url = f"https://api.themoviedb.org/3/movie/{movie_id}/credits?api_key={URL}"
            credits = requests.get(details_url).json()
        
            director = next((crew['name'] for crew in credits['crew'] if crew['job'] == 'Director'), "N/A")
        
            # 포스터 이미지
            poster_path = movie.get('poster_path')
            print(poster_path)
            img_url = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else None
        
            return title, year, director, img_url


        return response

    async def on_submit(self, interaction: discord.Interaction):
        title = self.children[0].value
        score = self.children[1].value
        line_comment = self.children[2].value
        comment = self.children[3].value

        # 별점 검증
        try:
            score_float = float(score)
            if not (0 <= score_float <= 5):
                await interaction.response.send_message("❌ 별점은 0~5 사이의 숫자를 입력해주세요!",ephemeral=True)
                return
        except ValueError:
            await interaction.response.send_message("❌ 별점은 숫자만 입력해주세요!", ephemeral=True)
            return

        # 영화 정보 가져오기
        title, year, director, img_path = self.namuWikiReturn(title)

        # 중복 리뷰 확인
        if self.db.has_review(interaction.user.id, title):
            await interaction.response.send_message(f"❌ 이미 '{title}'에 대한 리뷰를 작성하셨습니다.\n기존 리뷰를 삭제하려면 `/리뷰삭제`를 사용하세요.", ephemeral=True)
            return

        # DB에 저장
        self.db.save_review(
            user_id=interaction.user.id,
            username=str(interaction.user),
            movie_title=title,
            movie_year=year,
            director=director,
            score=score_float,
            one_line_review=line_comment,
            additional_comment=comment
        )

        filled_form = FORM.format(
            title=title,
            director_name=director,
            year=year,
            score=self.return_score_emoji(score),
            one_line_text=line_comment,
            comment=comment
        )

        if comment:  # None, "", 공백이면 자동으로 false
            filled_form += f"\n\n📝추가 코멘트 : {comment}"


        if img_path:
            img_response = requests.get(img_path)
            file = discord.File(io.BytesIO(img_response.content), filename="poster.jpg")
            await interaction.response.send_message(filled_form, file=file)
        else:
            await interaction.response.send_message(filled_form)

class MyBot(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.db = Database()  # DB 인스턴스 생성

    async def on_ready(self):
        print(f'Logged in as {self.user}')

    async def setup_hook(self):
        # 모든 명령어 등록
        self.tree.add_command(review_command)
        self.tree.add_command(my_reviews_command)
        self.tree.add_command(movie_stats_command)
        self.tree.add_command(delete_review_command)
        await self.tree.sync()

bot = MyBot(command_prefix="/", intents=discord.Intents.default())

@discord.app_commands.command(name="한줄평", description="리뷰를 작성합니다.")
async def review_command(interaction: discord.Interaction):
    modal = ReviewForm(bot.db)
    await interaction.response.send_modal(modal)

@discord.app_commands.command(name="내리뷰", description="내가 작성한 리뷰 목록을 조회합니다.")
async def my_reviews_command(interaction: discord.Interaction):
    reviews = bot.db.get_user_reviews(interaction.user.id, limit=5)

    if not reviews:
        await interaction.response.send_message("❌ 작성한 리뷰가 없습니다.", ephemeral=True)
        return

    embed = discord.Embed(title=f"{interaction.user.name}님의 최근 리뷰", color=0x00ff00)

    for review in reviews:
        score_emoji = "🌕" * int(review['score'])
        embed.add_field(
            name=f"{review['movie_title']} ({review['movie_year']})",
            value=f"⭐ {score_emoji} {review['score']}/10\n💬 \"{review['one_line_review']}\"",
            inline=False
        )

    await interaction.response.send_message(embed=embed,ephemeral=True)

@discord.app_commands.command(name="영화통계", description="특정 영화의 평점 통계를 조회합니다.")
async def movie_stats_command(interaction: discord.Interaction, 영화제목: str):
    stats = bot.db.get_movie_stats(영화제목)

    if not stats or stats['review_count'] == 0:
        await interaction.response.send_message(f"❌ '{영화제목}'에 대한 리뷰가 없습니다.", ephemeral=True)
        return

    embed = discord.Embed(title=f"📊 {영화제목} 통계", color=0x3498db)
    embed.add_field(name="리뷰 개수", value=f"{stats['review_count']}개", inline=True)
    embed.add_field(name="평균 평점", value=f"{stats['avg_score']:.2f}/10", inline=True)
    embed.add_field(name="최고 평점", value=f"{stats['max_score']}/10", inline=True)
    embed.add_field(name="최저 평점", value=f"{stats['min_score']}/10", inline=True)

    await interaction.response.send_message(embed=embed,ephemeral=True)

@discord.app_commands.command(name="리뷰삭제", description="특정 영화의 내 리뷰를 삭제합니다.")
async def delete_review_command(interaction: discord.Interaction, 영화제목: str):
    deleted = bot.db.delete_review(interaction.user.id, 영화제목)

    if deleted:
        # 채널에서 해당 리뷰 메시지 찾아서 삭제
        deleted_count = 0
        async for message in interaction.channel.history(limit=500):
            # 봇이 보낸 메시지이고, 해당 유저의 리뷰인지 확인
            if message.author == bot.user and f"🎬제목: {영화제목}" in message.content:
                # 메시지 내용에서 유저 확인 (메시지에 유저 정보가 없으면 삭제)
                await message.delete()
                deleted_count += 1

        if deleted_count > 0:
            await interaction.response.send_message(f"✅ '{영화제목}' 리뷰가 삭제되었습니다. (메시지 {deleted_count}개 삭제)",ephemeral=True)
        else:
            await interaction.response.send_message(f"✅ '{영화제목}' 리뷰가 DB에서 삭제되었습니다. (채널 메시지는 찾지 못함)",ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ '{영화제목}' 리뷰를 찾을 수 없습니다.",ephemeral=True)

bot.run(Token)
