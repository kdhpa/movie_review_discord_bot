import discord
import aiohttp
import os
from datetime import datetime, time
from discord.ext import tasks
from api_searcher import GrokSearcher

NEWS_CHANNEL_ID = os.getenv("NEWS_CHANNEL_ID")

# 카테고리 상수 정의
CATEGORY_NAME = {
    "movie": "영화",
    "drama": "드라마",
    "anime": "애니메이션",
    "manga": "만화",
    "webtoon": "웹툰"
}

CATEGORY_EMOJI = {
    "movie": "🎬",
    "drama": "📺",
    "anime": "🎌",
    "manga": "📚",
    "webtoon": "📱"
}

CATEGORY_COLOR = {
    "movie": 0xE50914,   # 넷플릭스 레드
    "drama": 0x1DB954,   # 스포티파이 그린
    "anime": 0xFF6B9D,   # 핑크
    "manga": 0x3498DB,   # 블루
    "webtoon": 0x00D564  # 네이버 그린
}

CATEGORIES = ['movie', 'drama', 'anime', 'manga', 'webtoon']


class NewsDetailButton(discord.ui.Button):
    """카테고리별 상세 뉴스 버튼 (ephemeral)"""

    def __init__(self, category: str, news_data: list):
        super().__init__(
            style=discord.ButtonStyle.secondary,
            label=CATEGORY_NAME[category],
            emoji=CATEGORY_EMOJI[category]
        )
        self.category = category
        self.news_data = news_data

    async def callback(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title=f"{CATEGORY_EMOJI[self.category]} {CATEGORY_NAME[self.category]} 뉴스",
            color=CATEGORY_COLOR[self.category]
        )

        for news in self.news_data:
            source_text = f"\n📌 출처: {news.get('source', '미상')}" if news.get('source') else ""
            embed.add_field(
                name=news.get('title', '제목 없음'),
                value=f"{news.get('content', '내용 없음')}{source_text}",
                inline=False
            )

        embed.set_footer(text="💡 스레드에서 모든 뉴스를 확인하고 토론할 수 있어요!")
        await interaction.response.send_message(embed=embed, ephemeral=True)


class DailyNewsView(discord.ui.View):
    """일일 뉴스 리포트 View"""

    def __init__(self, news_data: dict):
        super().__init__(timeout=None)  # 버튼 영구 유지

        for category in CATEGORIES:
            if news_data.get(category) and len(news_data[category]) > 0:
                self.add_item(NewsDetailButton(
                    category=category,
                    news_data=news_data[category]
                ))


class NewsScheduler:
    """매일 특정 시간에 엔터테인먼트 소식을 전송하는 스케줄러"""

    def __init__(self, bot):
        self.bot = bot
        self._channel_id = int(NEWS_CHANNEL_ID) if NEWS_CHANNEL_ID else None

    def start(self):
        """스케줄러 시작"""
        if not self._channel_id:
            print("[WARNING] NEWS_CHANNEL_ID가 설정되지 않아 뉴스 스케줄러가 시작되지 않습니다.")
            return

        if not self.send_daily_news.is_running():
            self.send_daily_news.start()
            print(f"[INFO] 뉴스 전송 예약됨 - 매일 13:00 KST (채널 ID: {self._channel_id})")

    def stop(self):
        """스케줄러 중지"""
        if self.send_daily_news.is_running():
            self.send_daily_news.cancel()
            print("[INFO] 뉴스 스케줄러 중지됨")

    def _create_main_embed(self, news_data: dict) -> discord.Embed:
        """메인 뉴스 Embed 생성"""
        now = datetime.now()
        weekdays = ['월', '화', '수', '목', '금', '토', '일']
        date_str = f"{now.year}년 {now.month}월 {now.day}일 ({weekdays[now.weekday()]})"

        embed = discord.Embed(
            title="📰 일일 엔터테인먼트 리포트",
            color=0x5865F2  # Discord Blurple
        )
        embed.description = f"**{date_str}**\n━━━━━━━━━━━━━━━━━━━━━━━━━━"

        # 헤드라인 섹션
        headlines = news_data.get('headlines', [])
        if headlines:
            headline_text = ""
            for i, headline in enumerate(headlines[:5]):
                category = headline.get('category', 'movie')
                emoji = CATEGORY_EMOJI.get(category, '📰')
                title = headline.get('title', '제목 없음')
                summary = headline.get('summary', '')
                headline_text += f"{emoji} **{title}**\n└ {summary}\n"

            embed.add_field(
                name="🔥 오늘의 헤드라인",
                value=headline_text if headline_text else "헤드라인이 없습니다.",
                inline=False
            )

        # 카테고리별 뉴스 개수 요약
        category_summary_parts = []
        for category in CATEGORIES:
            news_list = news_data.get(category, [])
            if news_list:
                count = len(news_list)
                category_summary_parts.append(f"{CATEGORY_EMOJI[category]} {CATEGORY_NAME[category]} {count}건")

        if category_summary_parts:
            # 3개씩 나눠서 표시
            summary_line = " │ ".join(category_summary_parts)
            embed.add_field(
                name="━━━━━━━━━━━━━━━━━━━━━━━━━━\n📊 카테고리별 뉴스",
                value=summary_line,
                inline=False
            )

        embed.add_field(
            name="━━━━━━━━━━━━━━━━━━━━━━━━━━",
            value="👇 **버튼으로 상세 보기** (나만 보임)\n💬 **스레드에서 토론하기**",
            inline=False
        )

        embed.set_footer(text="Powered by Grok AI")
        return embed

    def _create_category_embed(self, category: str, news_list: list) -> discord.Embed:
        """카테고리별 상세 뉴스 Embed 생성 (스레드용)"""
        embed = discord.Embed(
            title=f"{CATEGORY_EMOJI[category]} {CATEGORY_NAME[category]} 뉴스",
            color=CATEGORY_COLOR[category]
        )

        for news in news_list:
            source_text = f"\n📌 출처: {news.get('source', '미상')}" if news.get('source') else ""
            embed.add_field(
                name=news.get('title', '제목 없음'),
                value=f"{news.get('content', '내용 없음')}{source_text}",
                inline=False
            )

        return embed

    def _create_fallback_embed(self, raw_content: str) -> discord.Embed:
        """폴백용 기존 형식 Embed 생성"""
        now = datetime.now()
        weekdays = ['월', '화', '수', '목', '금', '토', '일']
        date_str = f"{now.year}년 {now.month}월 {now.day}일 ({weekdays[now.weekday()]})"

        embed = discord.Embed(
            title="🎬 오늘의 엔터테인먼트 소식",
            description=raw_content,
            color=0xE50914
        )
        embed.set_footer(text=f"{date_str} | Powered by Grok AI")
        return embed

    @tasks.loop(time=time(hour=4, minute=0))  # UTC 04:00 = KST 13:00
    async def send_daily_news(self):
        """매일 13:00 KST에 엔터테인먼트 소식 전송"""
        print("[INFO] send_daily_news() 실행 중...")

        channel = self.bot.get_channel(self._channel_id)
        if not channel:
            print(f"[ERROR] 채널을 찾을 수 없습니다: {self._channel_id}")
            return

        await self._send_categorized_news(channel)

    @send_daily_news.before_loop
    async def before_send_daily_news(self):
        """봇이 준비될 때까지 대기"""
        await self.bot.wait_until_ready()
        print("[INFO] 뉴스 스케줄러 대기 완료 - 봇 준비됨")

    async def _send_categorized_news(self, channel):
        """카테고리별 뉴스 전송 (메인 로직) - 3그룹 병렬 호출 사용"""
        async with aiohttp.ClientSession() as session:
            news_data = await GrokSearcher.fetch_all_categorized_news(session)

        if not news_data:
            print("[ERROR] 뉴스를 가져오지 못했습니다.")
            return False

        # 폴백: raw_content만 있는 경우 기존 방식으로 표시
        if 'raw_content' in news_data:
            print("[INFO] 폴백 모드로 뉴스 전송")
            embed = self._create_fallback_embed(news_data['raw_content'])
            await channel.send(embed=embed)
            return True

        # 메인 Embed 생성
        main_embed = self._create_main_embed(news_data)

        # 카테고리 버튼 View 생성
        view = DailyNewsView(news_data)

        # 채널에 메인 메시지 전송
        message = await channel.send(embed=main_embed, view=view)

        # 스레드 생성 (토론용)
        date_str = datetime.now().strftime("%m/%d")
        thread = await message.create_thread(
            name=f"📰 {date_str} 뉴스 토론",
            auto_archive_duration=1440  # 24시간 후 아카이브
        )

        # 스레드에 카테고리별 상세 뉴스 전송
        for category in CATEGORIES:
            if news_data.get(category) and len(news_data[category]) > 0:
                embed = self._create_category_embed(category, news_data[category])
                await thread.send(embed=embed)

        print(f"[INFO] 카테고리별 뉴스 전송 완료 - 채널: {channel.name}")
        return True

    async def send_news_now(self, channel):
        """즉시 엔터테인먼트 소식 전송 (수동 테스트용)"""
        return await self._send_categorized_news(channel)
