import discord
import aiohttp
import asyncio
import re
import html as html_lib
import time
from urllib.parse import parse_qs, urlparse, urljoin
from discord.ext import commands
from review_form import (
    MOVIE_FORM,
    MANGA_FORM,
    WEBTOON_FORM,
    WEBNOVEL_FORM,
    MUSIC_TRACK_FORM,
    GAME_FORM,
    format_season,
)

# 카테고리별 이모지 및 이름 매핑
CATEGORY_EMOJI = {"movie": "🎬", "drama": "📺", "anime": "🎌", "manga": "📚", "webtoon": "📱", "webnovel": "📖", "music_track": "🎵", "game": "🎮"}
CATEGORY_NAME = {"movie": "영화", "drama": "드라마", "anime": "애니", "manga": "만화", "webtoon": "웹툰", "webnovel": "웹소설", "music_track": "곡", "game": "게임"}
MUSIC_CATEGORIES = {"music_track"}
GAME_CATEGORIES = {"game"}
PROGRESS_UNIT_LABELS = {"manga": "권", "webtoon": "화", "webnovel": "화"}
WEBNOVEL_PLATFORM_ALIASES = {
    "문피아": "문피아",
    "munpia": "문피아",
    "카카오페이지": "카카오페이지",
    "카카페": "카카오페이지",
    "kakaopage": "카카오페이지",
    "시리즈": "시리즈",
    "네이버시리즈": "시리즈",
    "naverseries": "시리즈",
    "리디": "리디",
    "ridibooks": "리디",
    "ridi": "리디",
    "노벨피아": "노벨피아",
    "노벨 피아": "노벨피아",
    "novelpia": "노벨피아",
}
WEBNOVEL_PLATFORM_DOMAINS = {
    "novelpia.com": "노벨피아",
    "novelpia.co.kr": "노벨피아",
    "novelpia.page.link": "노벨피아",
    "novelpia.app.link": "노벨피아",
    "munpia.com": "문피아",
    "page.kakao.com": "카카오페이지",
    "series.naver.com": "시리즈",
    "ridibooks.com": "리디",
    "ridi.com": "리디",
}
MUSIC_LINK_DOMAINS = {
    "open.spotify.com",
    "spotify.link",
    "music.youtube.com",
    "youtube.com",
    "www.youtube.com",
    "youtu.be",
}
GAME_LINK_DOMAINS = {
    "store.steampowered.com",
}
from database import Database
from api_searcher import ContentSearcher, GrokSearcher
from assistant_service import AssistantService
from review_interaction import ReviewReactionView
import io
import os
from dotenv import load_dotenv

load_dotenv()

Token = os.getenv("Token")
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
IGDB_CLIENT_ID = os.getenv("IGDB_CLIENT_ID")
IGDB_CLIENT_SECRET = os.getenv("IGDB_CLIENT_SECRET")
SPOTIFY_ACCESS_TOKEN = None
SPOTIFY_TOKEN_EXPIRES_AT = 0
IGDB_ACCESS_TOKEN = None
IGDB_TOKEN_EXPIRES_AT = 0


# CATEGORY_EMOJI 역매핑 (emoji -> category)
EMOJI_CATEGORY = {emoji: cat for cat, emoji in CATEGORY_EMOJI.items()}


def parse_review_message(content):
    """리뷰 메시지에서 title, category, season을 파싱
    첫 줄이 '{emoji}제목: {title}' 또는 '{emoji}제목: {title} {N}{시즌/기/부}' 형식이어야 함
    Returns: (title, category, season) or (None, None, None)
    """
    if not content:
        return None, None, None

    first_line = content.split('\n')[0]

    for emoji, category in EMOJI_CATEGORY.items():
        prefix = f"{emoji}제목: "
        if first_line.startswith(prefix):
            title, season = split_title_season(first_line[len(prefix):].strip())
            return title, category, season

    return None, None, None


def parse_season_number(value):
    """'2', '2기', '2시즌', '2부' 값을 season 정수로 파싱."""
    if value is None:
        return None
    match = re.match(r'^\s*(\d+)\s*(시즌|기|부)?\s*$', str(value))
    return int(match.group(1)) if match else None


def split_title_season(title, default_season=None):
    """제목 끝의 시즌 표기를 분리."""
    title = (title or "").strip()
    match = re.match(r'^(.+?)\s+(\d+)(시즌|기|부)$', title)
    if match:
        return match.group(1).strip(), int(match.group(2))
    return title, default_season


def parse_review_detail(content):
    """리뷰 메시지에서 director/author, year/platform 파싱"""
    lines = content.split('\n')
    if len(lines) < 3:
        return None, None

    director = None
    for prefix in ['🎥감독: ', '✍️작가: ', '🎤아티스트: ', '🏢개발사: ']:
        if lines[1].startswith(prefix):
            director = lines[1][len(prefix):].strip()
            break

    year = None
    for prefix in ['📅개봉년도: ', '📅연재년도: ', '📍플랫폼: ', '📅발매년도: ', '📅출시년도: ']:
        if lines[2].startswith(prefix):
            year = lines[2][len(prefix):].strip()
            break

    return director, year


def resolve_review_message(db, message):
    """컨텍스트 메뉴 대상 메시지에서 리뷰 식별 정보를 찾는다.

    새 리뷰 메시지는 DB에 message_id가 저장되므로 그것을 우선 사용하고,
    오래된 메시지나 DB row를 찾지 못한 경우에만 텍스트 포맷 파싱으로 fallback한다.
    """
    review = db.get_review_by_message_id(message.id)
    if review:
        channel_id = review.get('channel_id')
        if channel_id is not None and int(channel_id) != message.channel.id:
            print(
                f"[WARN] resolve_review_message() channel mismatch: "
                f"db={channel_id}, message={message.channel.id}"
            )
        return (
            review.get('movie_title'),
            review.get('category'),
            review.get('season'),
            review
        )

    title, category, season = parse_review_message(message.content)
    return title, category, season, None


def parse_webnovel_meta(meta_text):
    """웹소설 수동 입력값에서 작가, 플랫폼을 분리."""
    meta_text = (meta_text or "").strip()
    if not meta_text:
        return "미상", "웹소설"

    separators = [" / ", "/", "|", ",", "·"]
    for separator in separators:
        if separator in meta_text:
            parts = [part.strip() for part in meta_text.split(separator)]
            author = parts[0] if len(parts) >= 1 else ""
            platform = parts[1] if len(parts) >= 2 else ""
            return author or "미상", normalize_webnovel_platform(platform)

    return meta_text, "웹소설"


def normalize_webnovel_platform(platform):
    """웹소설 플랫폼 표기를 저장용 이름으로 정규화."""
    platform = (platform or "").strip()
    if not platform:
        return "웹소설"
    key = platform.replace(" ", "").lower()
    for alias, canonical in WEBNOVEL_PLATFORM_ALIASES.items():
        if alias.replace(" ", "").lower() == key:
            return canonical
    return platform


def normalize_source_url(url):
    url = (url or "").strip()
    if not url:
        return None

    markdown_match = re.search(r'\((https?://[^)\s]+)\)', url)
    if markdown_match:
        url = markdown_match.group(1)

    url_match = re.search(r'https?://[^\s<>]+', url)
    if url_match:
        url = url_match.group(0)
    else:
        url = url.strip("<> \t\r\n")

    if not re.match(r'^https?://', url, re.IGNORECASE):
        url = f"https://{url}"

    url = url.strip("<> \t\r\n")
    parsed = urlparse(url)
    if not parsed.netloc:
        return None
    return parsed.geturl()


def detect_webnovel_platform_from_url(url):
    source_url = normalize_source_url(url)
    if not source_url:
        return None

    host = urlparse(source_url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]

    for domain, platform in WEBNOVEL_PLATFORM_DOMAINS.items():
        if host == domain or host.endswith(f".{domain}"):
            return platform
    return None


def normalize_host(url):
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def is_missing_music_value(value):
    value = str(value or "").strip()
    return not value or value.lower() in {"n/a", "none", "unknown"} or value in {"미상", "정보 없음"}


def is_music_link(url):
    source_url = normalize_source_url(url)
    if not source_url:
        return False

    host = normalize_host(source_url)
    return (
        host in MUSIC_LINK_DOMAINS
        or host.endswith(".spotify.com")
        or host.endswith(".youtube.com")
    )


def should_handle_as_music_link(url, category):
    if not is_music_link(url):
        return False

    host = normalize_host(url)
    if host == "spotify.link" or host.endswith("spotify.com") or host == "music.youtube.com":
        return True
    return category in MUSIC_CATEGORIES


def parse_steam_appid(url):
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    for idx, part in enumerate(parts):
        if part == "app" and idx + 1 < len(parts) and parts[idx + 1].isdigit():
            return int(parts[idx + 1])
    return None


def is_game_link(url):
    source_url = normalize_source_url(url)
    if not source_url:
        return False
    host = normalize_host(source_url)
    return host in GAME_LINK_DOMAINS and bool(parse_steam_appid(source_url))


def parse_spotify_type_from_url(url):
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    for idx, part in enumerate(parts):
        if part in ("album", "track") and idx + 1 < len(parts):
            return part, parts[idx + 1]
    return None, None


def parse_spotify_type_from_embed(html):
    match = re.search(r'open\.spotify\.com/embed(?:/[a-z-]+)?/(album|track)/([A-Za-z0-9]+)', html or "")
    if match:
        return match.group(1), match.group(2)
    return None, None


def parse_youtube_video_id(url):
    parsed = urlparse(url)
    host = normalize_host(url)
    if host == "youtu.be":
        video_id = parsed.path.strip("/").split("/")[0]
        return video_id or None
    query = parse_qs(parsed.query)
    return query.get("v", [None])[0]


def parse_youtube_music_type(url):
    parsed = urlparse(url)
    host = normalize_host(url)
    if host == "youtu.be":
        return "music_track"
    if parsed.path.startswith("/watch"):
        return "music_track"
    if parsed.path.startswith("/playlist"):
        return "music_album"
    return None


def clean_spotify_title(raw_title, category):
    title = (raw_title or "").strip()
    if not title:
        return None, None

    title = re.sub(r'\s*\|\s*Spotify\s*$', '', title, flags=re.IGNORECASE).strip()
    patterns = [
        r'^(?P<title>.+?)\s+-\s+song and lyrics by\s+(?P<artist>.+)$',
        r'^(?P<title>.+?)\s+-\s+song by\s+(?P<artist>.+)$',
        r'^(?P<title>.+?)\s+-\s+album by\s+(?P<artist>.+)$',
        r'^(?P<title>.+?)\s+by\s+(?P<artist>.+)$',
    ]
    for pattern in patterns:
        match = re.match(pattern, title, flags=re.IGNORECASE)
        if match:
            return match.group('title').strip(), match.group('artist').strip()

    parts = [part.strip() for part in re.split(r'\s*[·•]\s*', title) if part.strip()]
    if len(parts) >= 2:
        if category == "music_album":
            return parts[0], parts[1]
        return parts[0], parts[1]

    return title, None


def parse_music_artist_from_description(description):
    description = (description or "").strip()
    if not description:
        return None

    parts = [part.strip() for part in re.split(r'\s*[·•]\s*', description) if part.strip()]
    if len(parts) >= 2:
        return parts[1]
    return None


def parse_spotify_artist_from_description(description):
    description = (description or "").strip()
    if not description:
        return None

    parts = [part.strip() for part in re.split(r'\s*[·•]\s*', description) if part.strip()]
    if not parts:
        return None
    if parts[0].lower() in ("song", "album", "single", "ep") and len(parts) >= 2:
        return parts[1]
    if parts[0].lower().startswith("listen to ") and len(parts) >= 2:
        return parts[1]
    return parts[0]


def first_year_from_text(value):
    match = re.search(r'\b(19|20)\d{2}\b', str(value or ""))
    return match.group(0) if match else None


def best_youtube_thumbnail(thumbnails):
    thumbnails = thumbnails or {}
    for key in ("maxres", "standard", "high", "medium", "default"):
        if key in thumbnails and thumbnails[key].get("url"):
            return thumbnails[key]["url"]
    return None


def clean_youtube_track_title(title):
    title = (title or "").strip()
    title = re.sub(
        r'\s*[\[(](?:official\s+)?(?:music\s+)?(?:video|mv|m/v|audio|lyrics?|visualizer|performance)[\])]$',
        '',
        title,
        flags=re.IGNORECASE,
    ).strip()
    return title


def clean_youtube_artist(author_name):
    artist = (author_name or "").strip()
    artist = re.sub(r'\s*-\s*Topic$', '', artist, flags=re.IGNORECASE).strip()
    return artist or "미상"


def parse_youtube_title_artist(title, author_name):
    title = (title or "").strip()
    artist = clean_youtube_artist(author_name)
    if " - " in title:
        left, right = [part.strip() for part in title.split(" - ", 1)]
        if left and right:
            return clean_youtube_track_title(right), left
    return clean_youtube_track_title(title), artist


def is_generic_youtube_artist(artist):
    artist = (artist or "").lower()
    generic_words = (
        "official",
        "records",
        "recordings",
        "labels",
        "entertainment",
        "music",
        "vevo",
    )
    return any(word in artist for word in generic_words)


async def fetch_page_meta(session, source_url):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        )
    }
    try:
        async with session.get(source_url, headers=headers) as response:
            if response.status != 200:
                return {}
            html = await response.text()
            return {
                "title": extract_page_title(html),
                "description": extract_meta_content(html, "og:description", "twitter:description", "description"),
                "image": extract_page_image(html, source_url),
                "type": extract_meta_content(html, "og:type"),
                "author": extract_meta_content(html, "author", "article:author"),
                "release_date": extract_meta_content(html, "music:release_date"),
                "musician": extract_meta_content(html, "music:musician_description"),
            }
    except Exception as e:
        print(f"[WARN] fetch_page_meta() failed: {e}")
        return {}


async def resolve_redirect_url(session, source_url):
    try:
        async with session.get(
            source_url,
            headers={"User-Agent": "PieDiscordReviewBot/1.0"},
            allow_redirects=True,
        ) as response:
            final_url = str(response.url)
            return final_url if final_url and final_url != source_url else source_url
    except Exception as e:
        print(f"[WARN] resolve_redirect_url() failed: {e}")
        return source_url


async def get_spotify_access_token(session):
    global SPOTIFY_ACCESS_TOKEN, SPOTIFY_TOKEN_EXPIRES_AT

    if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
        return None

    now = time.time()
    if SPOTIFY_ACCESS_TOKEN and now < SPOTIFY_TOKEN_EXPIRES_AT - 60:
        return SPOTIFY_ACCESS_TOKEN

    try:
        async with session.post(
            "https://accounts.spotify.com/api/token",
            data={"grant_type": "client_credentials"},
            auth=aiohttp.BasicAuth(SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ) as response:
            if response.status != 200:
                print(f"[WARN] Spotify token API status={response.status}")
                return None

            data = await response.json()
            SPOTIFY_ACCESS_TOKEN = data.get("access_token")
            SPOTIFY_TOKEN_EXPIRES_AT = now + int(data.get("expires_in", 3600))
            return SPOTIFY_ACCESS_TOKEN
    except Exception as e:
        print(f"[WARN] Spotify token API failed: {e}")
        return None


def spotify_api_headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "User-Agent": "PieDiscordReviewBot/1.0",
    }


async def fetch_spotify_oembed(session, source_url):
    try:
        async with session.get(
            "https://open.spotify.com/oembed",
            params={"url": source_url},
            headers={"User-Agent": "PieDiscordReviewBot/1.0"},
        ) as response:
            if response.status == 200:
                return await response.json()
            print(f"[WARN] Spotify oEmbed status={response.status}")
    except Exception as e:
        print(f"[WARN] Spotify oEmbed failed: {e}")
    return {}


async def fetch_spotify_music_by_api(session, spotify_type, spotify_id, source_url):
    if spotify_type != "track" or not spotify_id:
        return None

    token = await get_spotify_access_token(session)
    if not token:
        return None

    endpoint = "tracks"
    try:
        async with session.get(
            f"https://api.spotify.com/v1/{endpoint}/{spotify_id}",
            headers=spotify_api_headers(token),
        ) as response:
            if response.status != 200:
                print(f"[WARN] Spotify {endpoint} API status={response.status}")
                return None
            data = await response.json()
    except Exception as e:
        print(f"[WARN] Spotify {endpoint} API failed: {e}")
        return None

    album = data.get("album") or {}
    images = album.get("images") or []
    return {
        "title": data.get("name"),
        "year": first_year_from_text(album.get("release_date")) or "N/A",
        "director": ", ".join(artist.get("name") for artist in data.get("artists", []) if artist.get("name")) or "미상",
        "img_url": images[0].get("url") if images else None,
        "category": "music_track",
        "source_url": source_url,
        "provider_id": spotify_id,
        "provider": "spotify_api",
    }


async def fetch_youtube_music_by_api(session, source_url, fallback_category):
    if not YOUTUBE_API_KEY:
        return None

    detected_category = parse_youtube_music_type(source_url)
    if detected_category == "music_album":
        return None
    category = "music_track"
    video_id = parse_youtube_video_id(source_url)

    if not video_id:
        return None

    try:
        async with session.get(
            "https://www.googleapis.com/youtube/v3/videos",
            params={
                "part": "snippet",
                "id": video_id,
                "key": YOUTUBE_API_KEY,
            },
        ) as response:
            if response.status != 200:
                print(f"[WARN] YouTube videos API status={response.status}")
                return None
            data = await response.json()
    except Exception as e:
        print(f"[WARN] YouTube videos API failed: {e}")
        return None

    items = data.get("items") or []
    if not items:
        return None

    snippet = items[0].get("snippet") or {}
    title, artist = parse_youtube_title_artist(
        snippet.get("title"),
        snippet.get("channelTitle")
    )
    return {
        "title": title,
        "year": first_year_from_text(snippet.get("publishedAt")) or "N/A",
        "director": artist or "미상",
        "img_url": best_youtube_thumbnail(snippet.get("thumbnails")),
        "category": "music_track",
        "source_url": source_url,
        "provider_id": video_id,
        "provider": "youtube_data_api",
    }


async def fetch_musicbrainz_enrichment(session, category, title, artist):
    if category not in MUSIC_CATEGORIES or not title:
        return None

    endpoint = "recording"
    result_key = "recordings"
    title_field = "recording"
    result_builder = ContentSearcher._music_track_result

    title_query = ContentSearcher._musicbrainz_query_phrase(title)
    artist_query = ContentSearcher._musicbrainz_query_phrase(artist) if artist and not is_generic_youtube_artist(artist) else None
    query = f"{title_field}:{title_query}"
    if artist_query:
        query = f"{query} AND artist:{artist_query}"

    try:
        data = await ContentSearcher._musicbrainz_get(
            session,
            endpoint,
            {"query": query, "limit": 5}
        )
    except Exception as e:
        print(f"[WARN] fetch_musicbrainz_enrichment() failed: {e}")
        return None

    items = (data or {}).get(result_key) or []
    if not items:
        return None

    return result_builder(items[0])


async def enrich_music_info_from_musicbrainz(session, music_info, prefer_artist=False, prefer_year=False):
    if not music_info or not music_info.get("title"):
        return music_info

    category = music_info.get("category")
    artist = music_info.get("director")
    title = music_info.get("title")
    should_enrich = (
        prefer_artist
        or prefer_year
        or is_missing_music_value(artist)
        or is_missing_music_value(music_info.get("year"))
    )
    if not should_enrich:
        return music_info

    try:
        enrichment = await fetch_musicbrainz_enrichment(session, category, title, artist)
    except Exception as e:
        print(f"[WARN] enrich_music_info_from_musicbrainz() failed: {e}")
        return music_info

    if not enrichment:
        return music_info

    if (prefer_artist or is_missing_music_value(music_info.get("director"))) and not is_missing_music_value(enrichment.get("director")):
        music_info["director"] = enrichment["director"]
    if (prefer_year or is_missing_music_value(music_info.get("year"))) and not is_missing_music_value(enrichment.get("year")):
        music_info["year"] = enrichment["year"]
    if not music_info.get("musicbrainz_id") and enrichment.get("musicbrainz_id"):
        music_info["musicbrainz_id"] = enrichment["musicbrainz_id"]
        music_info["musicbrainz_type"] = enrichment.get("musicbrainz_type")
    if not music_info.get("img_url") and enrichment.get("img_url"):
        music_info["img_url"] = enrichment["img_url"]

    provider = music_info.get("provider") or "music"
    if "musicbrainz" not in provider:
        music_info["provider"] = f"{provider}+musicbrainz"

    return music_info


async def fetch_spotify_music_by_url(session, source_url, fallback_category):
    lookup_url = source_url
    if normalize_host(source_url) == "spotify.link":
        resolved_url = await resolve_redirect_url(session, source_url)
        if normalize_host(resolved_url).endswith("spotify.com"):
            lookup_url = resolved_url

    spotify_type, spotify_id = parse_spotify_type_from_url(lookup_url)
    oembed_data = {}

    if not spotify_type or not spotify_id:
        oembed_data = await fetch_spotify_oembed(session, lookup_url)
        spotify_type, spotify_id = parse_spotify_type_from_embed(oembed_data.get("html"))

    if spotify_type == "album":
        return None

    api_result = await fetch_spotify_music_by_api(session, spotify_type, spotify_id, source_url)
    if api_result and api_result.get("title"):
        return api_result

    if spotify_type == "track":
        category = "music_track"
    else:
        category = fallback_category if fallback_category in MUSIC_CATEGORIES else "music_track"

    page_meta = await fetch_page_meta(session, lookup_url)
    page_type = (page_meta.get("type") or "").lower()
    if not spotify_type and page_type in ("music.song", "music: song"):
        spotify_type = "track"
        category = "music_track"
    elif not spotify_type and page_type in ("music.album", "music: album"):
        return None

    title, page_artist = clean_spotify_title(page_meta.get("title"), category)
    artist = (
        page_meta.get("musician")
        or page_artist
        or parse_spotify_artist_from_description(page_meta.get("description"))
        or page_meta.get("author")
    )
    img_url = page_meta.get("image")
    year = (
        first_year_from_text(page_meta.get("release_date"))
        or first_year_from_text(page_meta.get("description"))
    )

    if not title or not img_url or not spotify_type:
        if not oembed_data:
            oembed_data = await fetch_spotify_oembed(session, lookup_url)

        if not spotify_type:
            spotify_type, spotify_id = parse_spotify_type_from_embed(oembed_data.get("html"))
            if spotify_type == "album":
                return None
            elif spotify_type == "track":
                category = "music_track"

        if not title:
            title, oembed_artist = clean_spotify_title(oembed_data.get("title"), category)
            artist = artist or oembed_artist
        img_url = img_url or oembed_data.get("thumbnail_url")

    artist = artist or "미상"
    year = year or "N/A"

    if not title:
        return None

    music_info = {
        "title": title,
        "year": year,
        "director": artist,
        "img_url": img_url,
        "category": category,
        "source_url": source_url,
        "provider_id": spotify_id,
        "provider": "spotify",
    }
    return await enrich_music_info_from_musicbrainz(session, music_info)


async def fetch_youtube_music_by_url(session, source_url, fallback_category):
    if parse_youtube_music_type(source_url) == "music_album":
        return None

    api_result = await fetch_youtube_music_by_api(session, source_url, fallback_category)
    if api_result and api_result.get("title"):
        return await enrich_music_info_from_musicbrainz(
            session,
            api_result,
            prefer_artist=True,
            prefer_year=True
        )

    parsed = urlparse(source_url)
    query = parse_qs(parsed.query)
    oembed_url = source_url
    if normalize_host(source_url) == "music.youtube.com" and parsed.path.startswith("/watch") and query.get("v"):
        oembed_url = f"https://www.youtube.com/watch?v={query['v'][0]}"

    category = "music_track"

    oembed_data = {}
    try:
        async with session.get(
            "https://www.youtube.com/oembed",
            params={"url": oembed_url, "format": "json"},
            headers={"User-Agent": "PieDiscordReviewBot/1.0"},
        ) as response:
            if response.status == 200:
                oembed_data = await response.json()
            else:
                print(f"[WARN] YouTube oEmbed status={response.status}")
    except Exception as e:
        print(f"[WARN] YouTube oEmbed failed: {e}")

    title, artist = parse_youtube_title_artist(
        oembed_data.get("title"),
        oembed_data.get("author_name")
    )
    img_url = oembed_data.get("thumbnail_url")
    year = None

    if not title or not year:
        page_meta = await fetch_page_meta(session, source_url)
        if not title:
            title = clean_webnovel_title(page_meta.get("title"), "YouTube Music")
        artist = artist or page_meta.get("author") or parse_music_artist_from_description(page_meta.get("description"))
        img_url = img_url or page_meta.get("image")
        year = first_year_from_text(page_meta.get("release_date")) or first_year_from_text(page_meta.get("description"))

    if not title:
        return None

    music_info = {
        "title": title,
        "year": year or "N/A",
        "director": artist or "미상",
        "img_url": img_url,
        "category": category,
        "source_url": source_url,
        "provider": "youtube_music",
    }
    return await enrich_music_info_from_musicbrainz(
        session,
        music_info,
        prefer_artist=True,
        prefer_year=True
    )


async def fetch_music_by_url(session, source_url, fallback_category):
    host = normalize_host(source_url)
    if host == "spotify.link" or host.endswith("spotify.com"):
        return await fetch_spotify_music_by_url(session, source_url, fallback_category)
    if host in ("music.youtube.com", "youtube.com", "youtu.be") or host.endswith(".youtube.com"):
        return await fetch_youtube_music_by_url(session, source_url, fallback_category)
    return None


def year_from_unix_timestamp(value):
    try:
        return str(time.gmtime(int(value)).tm_year)
    except (TypeError, ValueError, OSError):
        return None


def igdb_image_url(image_id, size="cover_big"):
    if not image_id:
        return None
    return f"https://images.igdb.com/igdb/image/upload/t_{size}/{image_id}.jpg"


def igdb_query_phrase(value):
    return str(value or "").replace("\\", "\\\\").replace('"', '\\"')


def normalize_game_search_text(value):
    return re.sub(r'\s+', ' ', re.sub(r'[^0-9a-zA-Z가-힣]+', ' ', str(value or "").lower())).strip()


def igdb_game_result(item):
    involved_companies = item.get("involved_companies") or []
    developer_names = []
    fallback_company_names = []
    for involved in involved_companies:
        company = involved.get("company") if isinstance(involved, dict) else None
        company_name = company.get("name") if isinstance(company, dict) else None
        if company_name:
            fallback_company_names.append(company_name)
            if involved.get("developer"):
                developer_names.append(company_name)

    cover = item.get("cover") or {}
    slug = item.get("slug")
    igdb_id = item.get("id")
    return {
        "title": item.get("name") or "N/A",
        "year": year_from_unix_timestamp(item.get("first_release_date")) or "N/A",
        "director": ", ".join(developer_names or fallback_company_names) or "미상",
        "img_url": igdb_image_url(cover.get("image_id")),
        "category": "game",
        "igdb_id": igdb_id,
        "source_url": f"https://www.igdb.com/games/{slug}" if slug else None,
    }


async def get_igdb_access_token(session):
    global IGDB_ACCESS_TOKEN, IGDB_TOKEN_EXPIRES_AT

    if not IGDB_CLIENT_ID or not IGDB_CLIENT_SECRET:
        return None

    now = time.time()
    if IGDB_ACCESS_TOKEN and now < IGDB_TOKEN_EXPIRES_AT - 60:
        return IGDB_ACCESS_TOKEN

    try:
        async with session.post(
            "https://id.twitch.tv/oauth2/token",
            params={
                "client_id": IGDB_CLIENT_ID,
                "client_secret": IGDB_CLIENT_SECRET,
                "grant_type": "client_credentials",
            },
        ) as response:
            if response.status != 200:
                print(f"[WARN] IGDB token API status={response.status}")
                return None
            data = await response.json()
            IGDB_ACCESS_TOKEN = data.get("access_token")
            IGDB_TOKEN_EXPIRES_AT = now + int(data.get("expires_in", 3600))
            return IGDB_ACCESS_TOKEN
    except Exception as e:
        print(f"[WARN] IGDB token API failed: {e}")
        return None


async def search_igdb_games(session, title, limit=5):
    token = await get_igdb_access_token(session)
    if not token or not title:
        return []

    body = (
        f'search "{igdb_query_phrase(title)}"; '
        "fields name,slug,first_release_date,cover.image_id,"
        "involved_companies.developer,involved_companies.company.name,platforms.name; "
        f"limit {limit};"
    )
    try:
        async with session.post(
            "https://api.igdb.com/v4/games",
            headers={
                "Client-ID": IGDB_CLIENT_ID,
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Content-Type": "text/plain",
            },
            data=body,
        ) as response:
            if response.status != 200:
                print(f"[WARN] IGDB games API status={response.status}")
                return []
            data = await response.json()
    except Exception as e:
        print(f"[WARN] IGDB games API failed: {e}")
        return []

    results = [igdb_game_result(item) for item in data if item.get("name")]
    normalized_query = normalize_game_search_text(title)
    return sorted(
        results,
        key=lambda game: (
            normalize_game_search_text(game.get("title")) != normalized_query,
            not normalize_game_search_text(game.get("title")).startswith(normalized_query),
            game.get("year") == "N/A",
        )
    )


async def enrich_game_info_from_igdb(session, game_info):
    if not game_info or not game_info.get("title") or game_info.get("igdb_id"):
        return game_info

    results = await search_igdb_games(session, game_info["title"], limit=1)
    if not results:
        return game_info

    enrichment = results[0]
    if not game_info.get("year") or game_info.get("year") == "N/A":
        game_info["year"] = enrichment.get("year") or "N/A"
    if not game_info.get("director") or game_info.get("director") == "미상":
        game_info["director"] = enrichment.get("director") or "미상"
    if not game_info.get("img_url"):
        game_info["img_url"] = enrichment.get("img_url")
    game_info["igdb_id"] = enrichment.get("igdb_id")
    return game_info


async def fetch_steam_game_by_appid(session, steam_appid, source_url=None):
    if not steam_appid:
        return None

    source_url = source_url or f"https://store.steampowered.com/app/{steam_appid}"
    try:
        async with session.get(
            "https://store.steampowered.com/api/appdetails",
            params={"appids": steam_appid, "cc": "kr", "l": "koreana"},
            headers={"User-Agent": "PieDiscordReviewBot/1.0"},
        ) as response:
            if response.status != 200:
                print(f"[WARN] Steam appdetails API status={response.status}")
                return None
            data = await response.json()
    except Exception as e:
        print(f"[WARN] Steam appdetails API failed: {e}")
        return None

    app_data = (data or {}).get(str(steam_appid)) or {}
    if not app_data.get("success"):
        return None

    game = app_data.get("data") or {}
    developers = game.get("developers") or []
    release_date = game.get("release_date") or {}
    game_info = {
        "title": game.get("name"),
        "year": first_year_from_text(release_date.get("date")) or "N/A",
        "director": ", ".join(developers) if developers else "미상",
        "img_url": game.get("header_image"),
        "category": "game",
        "source_url": source_url,
        "steam_appid": steam_appid,
        "provider": "steam_store",
    }
    return game_info


async def fetch_steam_game_by_url(session, source_url):
    steam_appid = parse_steam_appid(source_url)
    return await fetch_steam_game_by_appid(session, steam_appid, source_url)


async def search_steam_games(session, title, limit=5):
    if not title:
        return []

    try:
        async with session.get(
            "https://store.steampowered.com/api/storesearch/",
            params={"term": title, "cc": "kr", "l": "koreana"},
            headers={"User-Agent": "PieDiscordReviewBot/1.0"},
        ) as response:
            if response.status != 200:
                print(f"[WARN] Steam storesearch API status={response.status}")
                return []
            data = await response.json()
    except Exception as e:
        print(f"[WARN] Steam storesearch API failed: {e}")
        return []

    results = []
    seen = set()
    for item in (data or {}).get("items", []):
        steam_appid = item.get("id") or item.get("appid")
        if not steam_appid or steam_appid in seen:
            continue
        seen.add(steam_appid)

        game_info = await fetch_steam_game_by_appid(session, steam_appid)
        if not game_info:
            game_info = {
                "title": item.get("name") or "N/A",
                "year": "N/A",
                "director": "미상",
                "img_url": item.get("tiny_image"),
                "category": "game",
                "steam_appid": steam_appid,
                "source_url": f"https://store.steampowered.com/app/{steam_appid}",
                "provider": "steam_search",
            }
        results.append(game_info)
        if len(results) >= limit:
            break

    normalized_query = normalize_game_search_text(title)
    return sorted(
        results,
        key=lambda game: (
            normalize_game_search_text(game.get("title")) != normalized_query,
            not normalize_game_search_text(game.get("title")).startswith(normalized_query),
            game.get("year") == "N/A",
        )
    )


async def search_game_candidates(session, title, limit=5):
    igdb_results = await search_igdb_games(session, title, limit=limit)
    if igdb_results:
        return igdb_results
    return await search_steam_games(session, title, limit=limit)


async def fetch_game_by_url(session, source_url):
    if is_game_link(source_url):
        return await fetch_steam_game_by_url(session, source_url)
    return None


async def send_ephemeral_interaction(
    interaction: discord.Interaction,
    content: str,
    *,
    view: discord.ui.View = None
) -> bool:
    try:
        if interaction.response.is_done():
            if interaction.response.type == discord.InteractionResponseType.deferred_channel_message:
                await interaction.edit_original_response(content=content, view=view)
            else:
                await interaction.followup.send(content, view=view, ephemeral=True)
        else:
            await interaction.response.send_message(content, view=view, ephemeral=True)
        return True
    except discord.HTTPException as e:
        code = getattr(e, "code", None)
        if code == 40060:
            try:
                await interaction.followup.send(content, view=view, ephemeral=True)
                return True
            except discord.HTTPException as followup_error:
                print(
                    f"[ERROR] send_ephemeral_interaction() followup after 40060 failed "
                    f"(code={getattr(followup_error, 'code', None)})",
                    flush=True
                )
                return False
        if code == 10062:
            print("[ERROR] send_ephemeral_interaction() failed - unknown interaction", flush=True)
            return False
        raise


def parse_html_attrs(tag):
    attrs = {}
    for match in re.finditer(r'([\w:-]+)\s*=\s*(["\'])(.*?)\2', tag, re.IGNORECASE | re.DOTALL):
        attrs[match.group(1).lower()] = html_lib.unescape(match.group(3).strip())
    return attrs


def normalize_page_asset_url(asset_url, base_url):
    asset_url = (asset_url or "").strip()
    if not asset_url:
        return None

    asset_url = html_lib.unescape(asset_url).replace("\\/", "/")
    if asset_url.startswith("//"):
        return f"https:{asset_url}"
    return urljoin(base_url, asset_url)


def extract_meta_content(html, *keys):
    wanted_keys = {key.lower() for key in keys}
    for tag_match in re.finditer(r'<meta\b[^>]*>', html, re.IGNORECASE | re.DOTALL):
        attrs = parse_html_attrs(tag_match.group(0))
        meta_key = attrs.get("property") or attrs.get("name") or attrs.get("itemprop")
        if meta_key and meta_key.lower() in wanted_keys and attrs.get("content"):
            return re.sub(r'\s+', ' ', attrs["content"]).strip()

    for key in keys:
        pattern = (
            r'<meta\b(?=[^>]*(?:property|name)=["\']'
            + re.escape(key)
            + r'["\'])(?=[^>]*content=["\']([^"\']+)["\'])[^>]*>'
        )
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            return re.sub(r'\s+', ' ', match.group(1)).strip()
    return None


def extract_novelpia_image(html, base_url):
    patterns = [
        r'https?:\\?/\\?/images\.novelpia\.com\\?/imagebox\\?/cover\\?/[^"\'<>\s]+',
        r'//images\.novelpia\.com/imagebox/cover/[^"\'<>\s]+',
        r'https?://images\.novelpia\.com/imagebox/cover/[^"\'<>\s]+',
    ]
    for pattern in patterns:
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            return normalize_page_asset_url(match.group(0), base_url)
    return None


def extract_page_image(html, base_url):
    img_url = extract_meta_content(
        html,
        "og:image",
        "og:image:url",
        "twitter:image",
        "twitter:image:src",
        "image",
        "thumbnailUrl",
    )
    if img_url:
        return normalize_page_asset_url(img_url, base_url)

    novelpia_img_url = extract_novelpia_image(html, base_url)
    if novelpia_img_url:
        return novelpia_img_url

    image_match = re.search(
        r'<img\b[^>]*(?:src|data-src|data-original)=["\']([^"\']+)["\'][^>]*>',
        html,
        re.IGNORECASE | re.DOTALL,
    )
    if image_match:
        return normalize_page_asset_url(image_match.group(1), base_url)
    return None


def extract_page_title(html):
    title = extract_meta_content(html, "og:title", "twitter:title")
    if not title:
        match = re.search(r'<title[^>]*>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
        if match:
            title = re.sub(r'\s+', ' ', match.group(1)).strip()
    return title


def clean_webnovel_title(title, platform):
    title = (title or "").strip()
    if not title:
        return None

    for separator in [" - ", " | ", " :: ", " : "]:
        if separator in title:
            parts = [part.strip() for part in title.split(separator) if part.strip()]
            filtered = [
                part for part in parts
                if platform not in part and "웹소설" not in part and "소설" != part
            ]
            if filtered:
                return filtered[0]
    return title


async def fetch_webnovel_by_url(session, url):
    """웹소설 링크에서 플랫폼과 공개 메타데이터를 best-effort로 가져온다."""
    source_url = normalize_source_url(url)
    if not source_url:
        return None

    platform = detect_webnovel_platform_from_url(source_url) or "웹소설"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        )
    }

    title = None
    author = "미상"
    img_url = None

    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with session.get(source_url, headers=headers, timeout=timeout) as response:
            if response.status == 200:
                html = await response.text()
                title = clean_webnovel_title(extract_page_title(html), platform)
                img_url = extract_page_image(html, source_url)
                author = extract_meta_content(html, "author", "article:author") or author
                print(
                    f"[DEBUG] fetch_webnovel_by_url() parsed - "
                    f"title={title}, platform={platform}, author={author}, img_url={img_url}",
                    flush=True
                )
            else:
                print(f"[WARN] fetch_webnovel_by_url() status={response.status}, url={source_url}")
    except Exception as e:
        print(f"[WARN] fetch_webnovel_by_url() failed: {e}")

    return title, platform, author, img_url, source_url


def format_progress_text(category, season=None, unit_to=None, latest_units=None):
    """진행도 표시 문자열 생성. 예: 2부 / 35.3% (120/340화)."""
    if unit_to is None:
        return ""

    unit_label = PROGRESS_UNIT_LABELS.get(category, "")
    season_label = format_season(category, season).strip()

    if latest_units and latest_units > 0:
        percent = min((unit_to / latest_units) * 100, 100)
        progress = f"{percent:.1f}% ({unit_to}/{latest_units}{unit_label})"
    else:
        progress = f"{unit_to}{unit_label}"

    return f"{season_label} / {progress}" if season_label else progress


def format_datetime(value):
    if not value:
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d %H:%M")
    return str(value)[:16]


def short_text(value, limit=70):
    value = (value or "").replace("\n", " ").strip()
    return value if len(value) <= limit else value[:limit - 1] + "…"


def format_history_scope(review):
    category = review.get('category')
    season = review.get('season')
    unit_to = review.get('unit_to')

    progress = format_progress_text(
        category,
        season,
        unit_to,
        review.get('latest_units')
    )
    if progress:
        return progress

    season_text = format_season(category, season).strip()
    return season_text or "전체"


def format_score_value(value):
    if value is None:
        return "-"
    return f"{float(value):.1f}".rstrip("0").rstrip(".")


def join_embed_lines(lines, max_chars=1000):
    selected = []
    current_len = 0
    for line in lines:
        next_len = current_len + len(line) + (1 if selected else 0)
        if next_len > max_chars:
            selected.append("…")
            break
        selected.append(line)
        current_len = next_len
    return "\n".join(selected) or "-"


def resolve_review_season(db, user_id, title, category, season):
    """수정/삭제 명령에서 사용할 season 값을 결정."""
    if season is not None:
        return None if season == 0 else season, None

    if not category:
        return None, None

    reviews_for_title = db.get_user_reviews_for_title(user_id, title, category)
    distinct_seasons = []
    seen = set()
    for review in reviews_for_title:
        review_season = review.get('season')
        season_key = review_season if review_season is not None else 0
        if season_key not in seen:
            seen.add(season_key)
            distinct_seasons.append(review_season)

    if len(distinct_seasons) == 1:
        return distinct_seasons[0], None

    if len(distinct_seasons) > 1:
        review_list = []
        for review_season in distinct_seasons:
            season_text = format_season(category, review_season)
            label = "전체 리뷰" if review_season is None else season_text.strip()
            review_list.append(f"• {label}")
        return None, (
            f"📋 '{title}'에 대한 기수가 {len(distinct_seasons)}개 있습니다:\n"
            + "\n".join(review_list)
            + "\n\n`기수` 값을 지정해주세요. 전체 리뷰는 `기수:0`입니다."
        )

    return None, None


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
    display_name: str,
    unit_to: int = None,  # 진행도 (영화는 None)
    latest_units: int = None
):
    """리뷰 저장 및 메시지 전송 (공통 로직)"""
    print(f"[DEBUG] _save_and_send_review() 시작 - 작성자: {author_name}")

    title = movie_info['title']
    year = movie_info['year']
    director = movie_info['director']
    img_url = movie_info['img_url']
    db_category = movie_info['category']
    season = movie_info.get('season')
    latest_units = movie_info.get('latest_units', latest_units)
    source_url = movie_info.get('source_url')

    # 1단계: contents 테이블에 작품 저장/조회
    print(f"[DEBUG] _save_and_send_review() contents 테이블 처리 중...")
    content_id = db.get_or_create_content(
        title=title,
        category=db_category,
        year_or_platform=year,
        creator=director,
        img_url=img_url,
        tmdb_id=movie_info.get('tmdb_id'),
        mangadex_id=movie_info.get('mangadex_id'),
        naver_title_id=movie_info.get('naver_title_id'),
        musicbrainz_id=movie_info.get('musicbrainz_id'),
        musicbrainz_type=movie_info.get('musicbrainz_type'),
        igdb_id=movie_info.get('igdb_id'),
        steam_appid=movie_info.get('steam_appid')
    )

    if not content_id:
        print(f"[ERROR] _save_and_send_review() content_id 생성 실패")
        await interaction.followup.send("❌ 작품 정보 저장에 실패했습니다.", ephemeral=True)
        return

    print(f"[DEBUG] _save_and_send_review() content_id: {content_id}")

    # 2단계: 중복 확인 (v2 메서드 사용)
    print(f"[DEBUG] _save_and_send_review() 중복 확인 중...")
    if db.has_review_v2(author_id, content_id, unit_to, season=season):
        print(f"[DEBUG] _save_and_send_review() 중복 발견")
        season_text = format_season(db_category, season)
        await interaction.followup.send(
            f"❌ 이미 '{title}{season_text}'에 대한 리뷰를 작성하셨습니다.\n"
            "`/리뷰삭제`로 기존 리뷰를 삭제하거나 `/리뷰수정`으로 수정하세요.",
            ephemeral=True
        )
        return

    # 3단계: DB 저장 (v2 메서드 사용)
    print(f"[DEBUG] _save_and_send_review() DB 저장 중...")
    review_id = db.save_review_v2(
        user_id=author_id,
        username=author_name,
        content_id=content_id,
        score=score_float,
        one_line_review=line_comment,
        additional_comment=comment,
        unit_to=unit_to,
        season=season,
        latest_units=latest_units,
        source_url=source_url
    )
    print(f"[DEBUG] _save_and_send_review() DB 저장 완료 - review_id: {review_id}")

    # 카테고리별 출력 형식
    emoji = CATEGORY_EMOJI.get(db_category, "🎬")
    cat_name = CATEGORY_NAME.get(db_category, "영화")
    season_text = format_season(db_category, season)

    if category == 'tmdb':
        filled_form = MOVIE_FORM.format(
            title=title,
            season_text=season_text,
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
            season_text=season_text,
            author=director,
            year=year,
            score=return_score_emoji(score_float),
            one_line_text=line_comment,
            author_name = display_name
        )
    elif category == 'webtoon':
        filled_form = WEBTOON_FORM.format(
            title=title,
            season_text=season_text,
            platform=year,
            author=director,
            score=return_score_emoji(score_float),
            one_line_text=line_comment,
            author_name = display_name
        )
    elif db_category == 'music_track':
        filled_form = MUSIC_TRACK_FORM.format(
            title=title,
            season_text=season_text,
            artist=director,
            year=year,
            score=return_score_emoji(score_float),
            one_line_text=line_comment,
            author_name=display_name
        )
    elif db_category == 'game':
        filled_form = GAME_FORM.format(
            title=title,
            season_text=season_text,
            developer=director,
            year=year,
            score=return_score_emoji(score_float),
            one_line_text=line_comment,
            author_name=display_name
        )
    else:  # webnovel
        filled_form = WEBNOVEL_FORM.format(
            title=title,
            season_text=season_text,
            platform=year,
            author=director,
            score=return_score_emoji(score_float),
            one_line_text=line_comment,
            author_name = display_name
        )

    if unit_to is not None:
        progress_text = format_progress_text(db_category, season, unit_to, latest_units)
        filled_form += f"\n📌진행도: {progress_text}"

    if source_url:
        filled_form += f"\n🔗작품 링크: <{source_url}>"

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
            'Referer': source_url or img_url
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

def truncate_option_text(value, limit=100):
    value = str(value or "").replace("\n", " ").strip()
    return value if len(value) <= limit else value[:limit - 1] + "…"


class MovieSelectMenu(discord.ui.Select):
    """TMDB 검색 결과 선택 메뉴"""

    def __init__(self, movies: list, form: 'ReviewForm'):
        options = [
            discord.SelectOption(
                label=truncate_option_text(f"{movie['title']} ({movie.get('year') or 'N/A'})"),
                description=truncate_option_text(
                    (movie.get('director') or CATEGORY_NAME[movie['category']])
                    if movie.get('category') in MUSIC_CATEGORIES or movie.get('category') == 'game'
                    else CATEGORY_NAME[movie['category']]
                ),
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

        if movie.get('category') in MUSIC_CATEGORIES:
            async with aiohttp.ClientSession() as session:
                movie = await ContentSearcher.hydrate_music_result(session, movie)
        # 감독 정보 지연 로딩
        elif not movie.get('director'):
            print(f"[DEBUG] MovieSelectMenu.callback() 감독 정보 로딩 중...")
            async with aiohttp.ClientSession() as session:
                movie['director'] = await ContentSearcher._fetch_director_info(
                    session, movie['tmdb_id'], movie['media_type']
                )

        movie['season'] = None if movie['category'] in ('movie', 'music_track', 'game') else self.form.season
        movie['latest_units'] = self.form.latest_units

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
            self.form.display_name,
            unit_to=self.form.unit_to,
            latest_units=self.form.latest_units
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
    def __init__(self, db, category, author_id: int, id_name: str, author_name: str,
                 prefetched_info: tuple = None, prefetched_category: str = None,
                 default_season: int = None, latest_units: int = None,
                 source_url: str = None):
        super().__init__()
        self.db = db
        self.category = category  # 'tmdb', 'manga', 'webtoon', 'webnovel'
        # 작성자 정보 (생성 시 저장)
        self.display_name = author_name
        self.author_name = id_name
        self.author_id = author_id
        self.source_url = normalize_source_url(source_url)
        if detect_webnovel_platform_from_url(self.source_url):
            self.category = 'webnovel'

        # 리뷰 데이터 (on_submit에서 저장)
        self.score = None
        self.line_comment = None
        self.comment = None
        self.unit_to = None  # 진행도 (manga/webtoon/webnovel)
        self.season = default_season
        self.latest_units = latest_units
        self.music_artist_query = None
        # URL로 미리 가져온 만화 정보 (title, year, author, img_url)
        self.prefetched_info = prefetched_info
        self.prefetched_category = prefetched_category

        if self.category in MUSIC_CATEGORIES:
            title_default = prefetched_info[0] if prefetched_info and prefetched_info[0] else None
            artist_default = prefetched_info[2] if prefetched_info and len(prefetched_info) > 2 and prefetched_info[2] else None

            title_input = discord.ui.TextInput(
                label="음악 이름",
                placeholder="곡명을 입력하세요"
            )
            if title_default:
                title_input.default = title_default
            self.add_item(title_input)

            artist_input = discord.ui.TextInput(
                label="아티스트 (선택)",
                placeholder="동명이 많은 경우 입력하세요",
                required=False
            )
            if artist_default and artist_default != "미상":
                artist_input.default = artist_default
            self.add_item(artist_input)

            self.add_item(discord.ui.TextInput(label="별점 (0-5)", style=discord.TextStyle.short, placeholder="예: 4.5"))
            self.add_item(discord.ui.TextInput(label="한줄평", style=discord.TextStyle.long, placeholder="한줄평을 입력하세요"))
            self.add_item(discord.ui.TextInput(label="추가 코멘트", style=discord.TextStyle.paragraph, placeholder="추가 내용을 입력하세요", required=False))
            return

        if self.category == 'webnovel':
            title_default = prefetched_info[0] if prefetched_info and prefetched_info[0] else None
            platform_default = None
            meta_placeholder = "예: 싱숑 / 노벨피아"
            if prefetched_info:
                prefetched_platform = prefetched_info[1] if len(prefetched_info) > 1 else None
                prefetched_author = prefetched_info[2] if len(prefetched_info) > 2 else None
                if prefetched_author and prefetched_author != "미상":
                    platform_default = f"{prefetched_author} / {prefetched_platform}"
                elif prefetched_platform:
                    meta_placeholder = f"예: 작가명 / {prefetched_platform}"
                if len(prefetched_info) >= 5:
                    self.source_url = self.source_url or normalize_source_url(prefetched_info[4])

            title_input = discord.ui.TextInput(
                label="작품 이름",
                placeholder="링크에서 못 가져오면 직접 입력",
                required=not bool(self.source_url)
            )
            if title_default:
                title_input.default = title_default
            self.add_item(title_input)

            meta_input = discord.ui.TextInput(
                label="작가 / 플랫폼 (선택)",
                placeholder=meta_placeholder,
                required=False
            )
            if platform_default:
                meta_input.default = platform_default
            self.add_item(meta_input)
            self.add_item(discord.ui.TextInput(
                label="진행도 - 화 (선택)",
                style=discord.TextStyle.short,
                placeholder="화 (예: 120)",
                required=False
            ))
            self.add_item(discord.ui.TextInput(label="별점 (0-5)", style=discord.TextStyle.short, placeholder="예: 4.5"))
            self.add_item(discord.ui.TextInput(label="한줄평", style=discord.TextStyle.long, placeholder="한줄평을 입력하세요"))
            return

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
            title_required = not (self.category == 'manga' and self.source_url)
            title_placeholder = "링크에서 못 가져오면 직접 입력" if not title_required else "제목을 입력하세요"
            self.add_item(discord.ui.TextInput(
                label="작품 이름",
                placeholder=title_placeholder,
                required=title_required
            ))
            self.add_item(discord.ui.TextInput(label="별점 (0-5)", style=discord.TextStyle.short, placeholder="예: 4.5"))
            self.add_item(discord.ui.TextInput(label="한줄평", style=discord.TextStyle.long, placeholder="한줄평을 입력하세요"))
            self.add_item(discord.ui.TextInput(label="추가 코멘트", style=discord.TextStyle.paragraph, placeholder="추가 내용을 입력하세요", required=False))

        # 진행도 필드 추가
        if self.category in PROGRESS_UNIT_LABELS:
            unit_label = PROGRESS_UNIT_LABELS[self.category]
            placeholder_text = f"{unit_label} (예: 52)" if unit_label == "화" else f"{unit_label} (예: 5)"

            self.add_item(discord.ui.TextInput(
                label=f"진행도 - {unit_label} (선택)",
                style=discord.TextStyle.short,
                placeholder=placeholder_text,
                required=False
            ))

    async def on_submit(self, interaction: discord.Interaction):
        print(f"[DEBUG] ReviewForm.on_submit() 시작 - 카테고리: {self.category}, 작성자: {self.author_name}")

        is_manual_webnovel = self.category == 'webnovel'
        is_music = self.category in MUSIC_CATEGORIES

        # prefetched_info가 있으면 필드 인덱스가 다름 (제목 필드 추가됨)
        if is_music:
            title = self.children[0].value.strip()
            self.music_artist_query = self.children[1].value.strip() or None
            score = self.children[2].value
            self.line_comment = self.children[3].value
            self.comment = self.children[4].value
            if self.prefetched_info:
                year = self.prefetched_info[1] or "N/A"
                director = self.music_artist_query or self.prefetched_info[2] or "미상"
                img_url = self.prefetched_info[3] if len(self.prefetched_info) > 3 else None
            print(
                f"[DEBUG] ReviewForm.on_submit() 음악 입력 - "
                f"title: {title}, artist: {self.music_artist_query}, score: {score}"
            )
        elif is_manual_webnovel:
            title = self.children[0].value.strip()
            director, year = parse_webnovel_meta(self.children[1].value)
            if self.prefetched_info:
                if not self.children[1].value.strip():
                    director = self.prefetched_info[2] or "미상"
                    year = self.prefetched_info[1] or "웹소설"
                elif year == "웹소설" and self.prefetched_info[1]:
                    year = self.prefetched_info[1]
            score = self.children[3].value
            self.line_comment = self.children[4].value
            self.comment = None
            print(f"[DEBUG] ReviewForm.on_submit() 웹소설 수동 입력 - title: {title}, score: {score}")
        elif self.prefetched_info:
            _, year, director, img_url = self.prefetched_info  # 자동 추출 제목 무시
            title = self.children[0].value.strip()
            score = self.children[1].value  # 별점
            self.line_comment = self.children[2].value
            self.comment = self.children[3].value
            print(f"[DEBUG] ReviewForm.on_submit() prefetched_info 사용 - title: {title}, score: {score}")
        else:
            title = self.children[0].value.strip()
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

        # 진행도 추출
        unit_to = None
        if is_manual_webnovel:
            unit_to_str = self.children[2].value
            if unit_to_str:
                try:
                    unit_to = int(unit_to_str)
                    if unit_to <= 0:
                        await interaction.response.send_message("❌ 진행도는 1 이상이어야 합니다.", ephemeral=True)
                        return
                except ValueError:
                    await interaction.response.send_message("❌ 진행도는 정수만 입력해주세요!", ephemeral=True)
                    return
        elif self.category in PROGRESS_UNIT_LABELS:
            # 진행도 필드는 항상 마지막 필드 (인덱스 4)
            field_idx = 4

            if len(self.children) > field_idx:
                unit_to_str = self.children[field_idx].value
                if unit_to_str:
                    try:
                        unit_to = int(unit_to_str)
                        if unit_to <= 0:
                            await interaction.response.send_message("❌ 진행도는 1 이상이어야 합니다.", ephemeral=True)
                            return
                    except ValueError:
                        await interaction.response.send_message("❌ 진행도는 정수만 입력해주세요!", ephemeral=True)
                        return

        # 진행도를 form에 저장 (MovieSelectMenu에서 사용)
        if self.latest_units and unit_to and unit_to > self.latest_units:
            unit_label = PROGRESS_UNIT_LABELS.get(self.category, "화")
            await interaction.response.send_message(
                f"❌ 진행도는 최신화({self.latest_units}{unit_label})보다 클 수 없습니다.",
                ephemeral=True
            )
            return

        self.unit_to = unit_to

        await interaction.response.defer()

        # prefetched_info가 있으면 검색 없이 바로 저장
        if self.prefetched_info and not is_manual_webnovel:
            print(f"[DEBUG] ReviewForm.on_submit() prefetched_info로 바로 저장")
            prefetched_db_category = self.prefetched_category or ('movie' if self.category == 'tmdb' else self.category)
            movie_info = {
                'title': title,
                'year': year,
                'director': director,
                'img_url': img_url,
                'category': prefetched_db_category,
                'season': None if prefetched_db_category in ('movie', 'music_track') else self.season,
                'latest_units': self.latest_units,
                'source_url': self.source_url
            }

            # prefetched_info에 외부 ID가 포함되어 있는지 확인 (5개 요소)
            if len(self.prefetched_info) >= 5:
                external_id = self.prefetched_info[4]
                if prefetched_db_category == 'manga':
                    movie_info['mangadex_id'] = external_id
                elif prefetched_db_category == 'webtoon':
                    movie_info['naver_title_id'] = external_id
                elif prefetched_db_category in MUSIC_CATEGORIES:
                    movie_info['musicbrainz_id'] = external_id
                    movie_info['musicbrainz_type'] = 'recording'
                elif prefetched_db_category == 'game':
                    if isinstance(external_id, dict):
                        movie_info['igdb_id'] = external_id.get('igdb_id')
                        movie_info['steam_appid'] = external_id.get('steam_appid')
                    else:
                        movie_info['igdb_id'] = external_id

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
                self.display_name,
                unit_to=unit_to,
                latest_units=self.latest_units
            )
            return

        if is_manual_webnovel:
            print(f"[DEBUG] ReviewForm.on_submit() 웹소설 수동 정보로 바로 저장")
            img_url = self.prefetched_info[3] if self.prefetched_info else None
            fetched_title = None
            if self.source_url:
                async with aiohttp.ClientSession() as session:
                    fetched_info = await fetch_webnovel_by_url(session, self.source_url)
                if fetched_info:
                    fetched_title, fetched_platform, fetched_author, fetched_img_url, _ = fetched_info
                    if year == "웹소설" and fetched_platform:
                        year = fetched_platform
                    if director == "미상" and fetched_author:
                        director = fetched_author
                    img_url = img_url or fetched_img_url
            if not title and fetched_title:
                title = fetched_title
            if not title:
                await interaction.followup.send(
                    "❌ 링크에서 작품 이름을 가져오지 못했습니다. 작품 이름을 직접 입력해주세요.",
                    ephemeral=True
                )
                return

            movie_info = {
                'title': title,
                'year': year,
                'director': director,
                'img_url': img_url,
                'category': 'webnovel',
                'season': self.season,
                'latest_units': self.latest_units,
                'source_url': self.source_url
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
                self.display_name,
                unit_to=unit_to,
                latest_units=self.latest_units
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

                    movie['season'] = None if movie['category'] == 'movie' else self.season
                    movie['latest_units'] = self.latest_units

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
                        self.display_name,
                        unit_to=unit_to,
                        latest_units=self.latest_units
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

            elif self.category in MUSIC_CATEGORIES:
                music_results = await ContentSearcher.search_music_track_multiple(
                    session,
                    title,
                    artist=self.music_artist_query
                )

                if not music_results:
                    print(f"[DEBUG] ReviewForm.on_submit() 음악 검색 실패 - 결과 없음")
                    artist_hint = " 아티스트명을 같이 입력해서" if not self.music_artist_query else ""
                    await interaction.followup.send(
                        f"❌ '{original_title}'를 찾을 수 없습니다.{artist_hint} 다시 시도해주세요.",
                        ephemeral=True
                    )
                    return

                if len(music_results) == 1:
                    print(f"[DEBUG] ReviewForm.on_submit() 음악 단일 결과 - 자동 선택")
                    music = await ContentSearcher.hydrate_music_result(session, music_results[0])
                    music['season'] = None
                    music['latest_units'] = self.latest_units

                    await _save_and_send_review(
                        interaction,
                        self.db,
                        music,
                        self.category,
                        self.score,
                        self.line_comment,
                        self.comment,
                        self.author_id,
                        self.author_name,
                        self.display_name,
                        unit_to=unit_to,
                        latest_units=self.latest_units
                    )
                    return

                print(f"[DEBUG] ReviewForm.on_submit() 음악 다중 결과 - Select Menu 표시 ({len(music_results)}개)")
                view = MovieSelectView(music_results, self)
                await interaction.followup.send(
                    f"🔍 '{original_title}' 검색 결과 {len(music_results)}개입니다. 음악을 선택하세요:",
                    view=view,
                    ephemeral=True
                )
                return

            elif self.category == 'game':
                game_results = await search_game_candidates(session, title)

                if not game_results:
                    print(f"[DEBUG] ReviewForm.on_submit() 게임 검색 실패 - 결과 없음")
                    await interaction.followup.send(
                        f"❌ '{original_title}'를 찾을 수 없습니다. 영문 제목이나 Steam 링크로 다시 시도해주세요.",
                        ephemeral=True
                    )
                    return

                if len(game_results) == 1:
                    print(f"[DEBUG] ReviewForm.on_submit() 게임 단일 결과 - 자동 선택")
                    game = game_results[0]
                    game['season'] = None
                    game['latest_units'] = self.latest_units

                    await _save_and_send_review(
                        interaction,
                        self.db,
                        game,
                        self.category,
                        self.score,
                        self.line_comment,
                        self.comment,
                        self.author_id,
                        self.author_name,
                        self.display_name,
                        unit_to=unit_to,
                        latest_units=self.latest_units
                    )
                    return

                print(f"[DEBUG] ReviewForm.on_submit() 게임 다중 결과 - Select Menu 표시 ({len(game_results)}개)")
                view = MovieSelectView(game_results, self)
                await interaction.followup.send(
                    f"🔍 '{original_title}' 검색 결과 {len(game_results)}개입니다. 게임을 선택하세요:",
                    view=view,
                    ephemeral=True
                )
                return

            elif self.category == 'manga':
                if self.source_url:
                    manga_info = await ContentSearcher.fetch_manga_by_url(session, self.source_url)
                    if not manga_info:
                        await interaction.followup.send("❌ 유효하지 않은 MangaDex URL입니다.", ephemeral=True)
                        return

                    fetched_title, year, director, img_url, mangadex_id = manga_info
                    title = title or fetched_title
                    print(
                        f"[DEBUG] ReviewForm.on_submit() MangaDex 링크 조회 성공 - "
                        f"title: {title}, id: {mangadex_id}"
                    )
                else:
                    title, year, director, img_url, mangadex_id = await ContentSearcher.search_manga(session, title)
                db_category = 'manga'
            else:  # webtoon
                title, year, director, img_url, naver_title_id = await ContentSearcher.search_webtoon(session, title)
                db_category = 'webtoon'

            print(f"[DEBUG] ReviewForm.on_submit() 검색 결과 - title: {title}, year: {year}, director: {director}, img_url: {img_url}")

            # 검색 결과 없음 확인 (만화/웹툰만 해당)
            if title == None or director == None or year == None:
                print(f"[DEBUG] ReviewForm.on_submit() 검색 실패 - 결과 없음")
                await interaction.followup.send(f"❌ '{original_title}'를 찾을 수 없습니다. 정확한 제목으로 다시 시도해주세요.", ephemeral=True)
                return

            # 만화/웹툰: 기존 방식 + 외부 ID 추가
            movie_info = {
                'title': title,
                'year': year,
                'director': director,
                'img_url': img_url,
                'category': db_category,
                'season': self.season,
                'latest_units': self.latest_units,
                'source_url': self.source_url
            }

            # 외부 ID 추가
            if db_category == 'manga':
                movie_info['mangadex_id'] = mangadex_id
            elif db_category == 'webtoon':
                movie_info['naver_title_id'] = naver_title_id

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
                self.display_name,
                unit_to=unit_to,
                latest_units=self.latest_units
            )


class ReviewLaunchView(discord.ui.View):
    def __init__(
        self,
        db,
        category: str,
        author_id: int,
        author_name: str,
        display_name: str,
        source_url: str = None,
        default_season: int = None,
        latest_units: int = None,
    ):
        super().__init__(timeout=300)
        self.db = db
        self.category = category
        self.author_id = author_id
        self.author_name = author_name
        self.display_name = display_name
        self.source_url = normalize_source_url(source_url)
        if detect_webnovel_platform_from_url(self.source_url):
            self.category = 'webnovel'
        self.default_season = default_season
        self.latest_units = latest_units

    @discord.ui.button(label="입력창 열기", style=discord.ButtonStyle.primary)
    async def open_review_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ 이 입력창은 명령을 실행한 사람만 열 수 있습니다.", ephemeral=True)
            return

        prefetched_info = None
        if self.category == 'webnovel' and self.source_url:
            platform = detect_webnovel_platform_from_url(self.source_url) or "웹소설"
            prefetched_info = (None, platform, "미상", None, self.source_url)
            print(
                f"[DEBUG] ReviewLaunchView.open_review_modal() 웹소설 링크 입력 - "
                f"platform={platform}, url={self.source_url}",
                flush=True
            )

        modal = ReviewForm(
            self.db,
            self.category,
            self.author_id,
            self.author_name,
            self.display_name,
            prefetched_info=prefetched_info,
            default_season=self.default_season,
            latest_units=self.latest_units,
            source_url=self.source_url
        )

        print(
            f"[DEBUG] ReviewLaunchView.open_review_modal() 모달 전송 직전 - "
            f"category={self.category}, has_link={bool(self.source_url)}, "
            f"source_url={self.source_url}, response_done={interaction.response.is_done()}",
            flush=True
        )

        try:
            await interaction.response.send_modal(modal)
        except discord.HTTPException as e:
            if getattr(e, "code", None) in (40060, 10062):
                print(
                    f"[ERROR] ReviewLaunchView.open_review_modal() Discord interaction 응답 실패 "
                    f"(code={getattr(e, 'code', None)}, category={self.category}, "
                    f"source_url={self.source_url}, response_done={interaction.response.is_done()})",
                    flush=True
                )
                try:
                    await interaction.followup.send(
                        "❌ 입력창을 여는 중 Discord 응답이 만료되었습니다. 버튼을 다시 눌러주세요.",
                        ephemeral=True
                    )
                except discord.HTTPException:
                    pass
                return
            raise


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
        season = self.review_data.get('season')

        # DB 업데이트
        updated = self.db.update_review(
            self.user_id, title, category,
            score, one_line_review, additional_comment,
            season=season
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
            new_additional_comment=additional_comment,
            season=season,
            unit_from=self.review_data.get('unit_from'),
            unit_to=self.review_data.get('unit_to'),
            latest_units=self.review_data.get('latest_units'),
            source_url=self.review_data.get('source_url')
        )

        # 수정된 리뷰 메시지 생성
        year = self.review_data['movie_year']
        director = self.review_data['director']
        emoji = CATEGORY_EMOJI.get(category, "🎬")
        cat_name = CATEGORY_NAME.get(category, "영화")
        season_text = format_season(category, season)

        # 카테고리에 따른 검색 타입 결정
        if category in ['movie', 'drama', 'anime']:
            search_category = 'tmdb'
        elif category == 'manga':
            search_category = 'manga'
        elif category == 'webtoon':
            search_category = 'webtoon'
        elif category in MUSIC_CATEGORIES:
            search_category = category
        elif category == 'game':
            search_category = 'game'
        else:
            search_category = 'webnovel'

        # 폼 생성
        if search_category == 'tmdb':
            filled_form = MOVIE_FORM.format(
                title=title,
                season_text=season_text,
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
                season_text=season_text,
                author=director,
                year=year,
                score=return_score_emoji(score),
                one_line_text=one_line_review,
                author_name=self.display_name
            )
        elif search_category == 'webtoon':
            filled_form = WEBTOON_FORM.format(
                title=title,
                season_text=season_text,
                platform=year,
                author=director,
                score=return_score_emoji(score),
                one_line_text=one_line_review,
                author_name=self.display_name
            )
        elif search_category == 'music_track':
            filled_form = MUSIC_TRACK_FORM.format(
                title=title,
                season_text=season_text,
                artist=director,
                year=year,
                score=return_score_emoji(score),
                one_line_text=one_line_review,
                author_name=self.display_name
            )
        elif search_category == 'game':
            filled_form = GAME_FORM.format(
                title=title,
                season_text=season_text,
                developer=director,
                year=year,
                score=return_score_emoji(score),
                one_line_text=one_line_review,
                author_name=self.display_name
            )
        else:  # webnovel
            filled_form = WEBNOVEL_FORM.format(
                title=title,
                season_text=season_text,
                platform=year,
                author=director,
                score=return_score_emoji(score),
                one_line_text=one_line_review,
                author_name=self.display_name
            )

        if self.review_data.get('unit_to') is not None:
            progress_text = format_progress_text(
                category,
                season,
                self.review_data['unit_to'],
                self.review_data.get('latest_units')
            )
            filled_form += f"\n📌진행도: {progress_text}"

        if self.review_data.get('source_url'):
            filled_form += f"\n🔗작품 링크: <{self.review_data['source_url']}>"

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
                        if f"{emoji}제목: {title}{season_text}" in message.content:
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
                    f"✅ '{title}{season_text}' ({cat_name}) 리뷰가 수정되었습니다.", ephemeral=True
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
                    _, _, _, img_url, _ = await ContentSearcher.search_manga(session, title)
                elif search_category == 'webtoon':
                    _, _, _, img_url, _ = await ContentSearcher.search_webtoon(session, title)
                elif search_category == 'webnovel' and self.review_data.get('source_url'):
                    fetched_info = await fetch_webnovel_by_url(session, self.review_data['source_url'])
                    if fetched_info:
                        _, _, _, img_url, _ = fetched_info
                elif search_category == 'music_track':
                    music_results = await ContentSearcher.search_music_track_multiple(
                        session,
                        title,
                        artist=director
                    )
                    if music_results:
                        music = await ContentSearcher.hydrate_music_result(session, music_results[0])
                        img_url = music.get('img_url')
                elif search_category == 'game':
                    game_results = await search_game_candidates(session, title, limit=1)
                    if game_results:
                        img_url = game_results[0].get('img_url')

            if img_url:
                self.db.update_review(
                    self.user_id, title, category,
                    score, one_line_review, additional_comment,
                    img_url=img_url,
                    season=season
                )

        # 이미지 다운로드 및 전송
        img_data = None
        if img_url:
            timeout = aiohttp.ClientTimeout(total=30)
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Referer': self.review_data.get('source_url') or img_url
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
            f"✅ '{title}{season_text}' ({cat_name}) 리뷰가 수정되었습니다. (기존 메시지를 찾지 못해 새로 전송)",
            ephemeral=True
        )


# ==================== Bot Class ====================

class MyBot(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.db = Database()
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
        self.tree.add_command(review_history_command)
        self.tree.add_command(delete_review_command)
        self.tree.add_command(edit_review_command)
        self.tree.add_command(ott_command)
        self.tree.add_command(edit_review_context)
        self.tree.add_command(write_review_context)
        self.tree.add_command(delete_review_context)
        self.tree.add_command(ranking_command)
        self.tree.add_command(migration_command)
        await self.tree.sync()

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
@discord.app_commands.describe(
    카테고리="리뷰할 콘텐츠 종류",
    링크="선택: 링크로 자동 입력. 지원: Steam, MangaDex, 웹소설, Spotify/YouTube Music",
    기수="시즌/기/부 번호 (선택)",
    최신화="현재 공개된 최신 화/권 수 (진행률 계산용, 선택)"
)
@discord.app_commands.choices(카테고리=[
    discord.app_commands.Choice(name="🎬 영화/드라마/애니", value="tmdb"),
    discord.app_commands.Choice(name="📚 만화", value="manga"),
    discord.app_commands.Choice(name="📱 웹툰", value="webtoon"),
    discord.app_commands.Choice(name="📖 웹소설", value="webnovel"),
    discord.app_commands.Choice(name="🎮 게임", value="game"),
    discord.app_commands.Choice(name="🎵 곡", value="music_track"),
])
async def review_command(
    interaction: discord.Interaction,
    카테고리: str,
    링크: str = None,
    기수: int = None,
    최신화: int = None
):
    source_url = normalize_source_url(링크)
    if 링크 and not source_url:
        await send_ephemeral_interaction(
            interaction,
            "❌ 링크 형식이 아닙니다. 예: `https://store.steampowered.com/app/...`, `https://open.spotify.com/track/...`"
        )
        return

    if source_url and should_handle_as_music_link(source_url, 카테고리):
        try:
            timeout = aiohttp.ClientTimeout(total=2.8)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                music_info = await fetch_music_by_url(session, source_url, 카테고리)
        except Exception as e:
            print(f"[WARN] review_command() 음악 링크 메타데이터 조회 실패: {e}")
            music_info = None

        if not music_info:
            await send_ephemeral_interaction(
                interaction,
                "❌ 음악 정보를 가져오지 못했습니다. Spotify 트랙 링크 또는 YouTube Music 곡 링크를 넣어주세요."
            )
            return

        카테고리 = music_info['category']
        prefetched_info = (
            music_info['title'],
            music_info.get('year') or "N/A",
            music_info.get('director') or "미상",
            music_info.get('img_url')
        )
        if music_info.get('musicbrainz_id'):
            prefetched_info = (
                music_info['title'],
                music_info.get('year') or "N/A",
                music_info.get('director') or "미상",
                music_info.get('img_url'),
                music_info.get('musicbrainz_id')
            )
        print(
            f"[DEBUG] review_command() 음악 링크 조회 성공 - "
            f"provider={music_info.get('provider')}, title={music_info.get('title')}, "
            f"artist={music_info.get('director')}, year={music_info.get('year')}",
            flush=True
        )
        modal = ReviewForm(
            bot.db,
            카테고리,
            interaction.user.id,
            str(interaction.user),
            interaction.user.display_name,
            prefetched_info=prefetched_info,
            prefetched_category=카테고리,
            source_url=source_url
        )
        try:
            await interaction.response.send_modal(modal)
        except discord.HTTPException as e:
            print(
                f"[ERROR] review_command() 음악 링크 모달 전송 실패 "
                f"(code={getattr(e, 'code', None)}, source_url={source_url})",
                flush=True
            )
            if not interaction.response.is_done():
                await send_ephemeral_interaction(
                    interaction,
                    "❌ 음악 링크 정보를 가져왔지만 입력창을 여는 중 Discord 응답이 만료되었습니다. 다시 시도해주세요."
                )
        return

    if source_url and 카테고리 in MUSIC_CATEGORIES:
        await send_ephemeral_interaction(
            interaction,
            "❌ 곡 링크는 Spotify 트랙 또는 YouTube Music 곡 링크만 지원합니다."
        )
        return

    if source_url and (카테고리 == 'game' or is_game_link(source_url)):
        if not is_game_link(source_url):
            await send_ephemeral_interaction(
                interaction,
                "❌ 게임 링크는 Steam 상점의 `/app/게임ID` 링크만 지원합니다."
            )
            return

        try:
            timeout = aiohttp.ClientTimeout(total=2.8)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                game_info = await fetch_game_by_url(session, source_url)
        except Exception as e:
            print(f"[WARN] review_command() 게임 링크 메타데이터 조회 실패: {e}")
            game_info = None

        if not game_info:
            await send_ephemeral_interaction(
                interaction,
                "❌ 게임 정보를 가져오지 못했습니다. Steam 상점 링크인지 확인해주세요."
            )
            return

        prefetched_info = (
            game_info['title'],
            game_info.get('year') or "N/A",
            game_info.get('director') or "미상",
            game_info.get('img_url'),
            {
                'igdb_id': game_info.get('igdb_id'),
                'steam_appid': game_info.get('steam_appid')
            }
        )
        print(
            f"[DEBUG] review_command() 게임 링크 조회 성공 - "
            f"provider={game_info.get('provider')}, title={game_info.get('title')}, "
            f"developer={game_info.get('director')}, year={game_info.get('year')}",
            flush=True
        )
        modal = ReviewForm(
            bot.db,
            'game',
            interaction.user.id,
            str(interaction.user),
            interaction.user.display_name,
            prefetched_info=prefetched_info,
            prefetched_category='game',
            source_url=source_url
        )
        try:
            await interaction.response.send_modal(modal)
        except discord.HTTPException as e:
            print(
                f"[ERROR] review_command() 게임 링크 모달 전송 실패 "
                f"(code={getattr(e, 'code', None)}, source_url={source_url})",
                flush=True
            )
            if not interaction.response.is_done():
                await send_ephemeral_interaction(
                    interaction,
                    "❌ 게임 정보를 가져왔지만 입력창을 여는 중 Discord 응답이 만료되었습니다. 다시 시도해주세요."
                )
        return

    detected_webnovel_platform = detect_webnovel_platform_from_url(source_url) if source_url else None
    if detected_webnovel_platform and 카테고리 != 'webnovel':
        print(
            f"[DEBUG] review_command() 웹소설 링크 도메인 감지로 카테고리 보정: "
            f"{카테고리} -> webnovel ({detected_webnovel_platform})"
        )
        카테고리 = 'webnovel'

    if 기수 is not None and 기수 <= 0:
        await send_ephemeral_interaction(interaction, "❌ 기수는 1 이상으로 입력해주세요.")
        return
    if 최신화 is not None and 최신화 <= 0:
        await send_ephemeral_interaction(interaction, "❌ 최신화는 1 이상으로 입력해주세요.")
        return

    view = ReviewLaunchView(
        bot.db,
        카테고리,
        interaction.user.id,
        str(interaction.user),
        interaction.user.display_name,
        source_url=source_url,
        default_season=기수,
        latest_units=최신화
    )

    category_text = CATEGORY_NAME.get(카테고리, 카테고리)
    emoji = CATEGORY_EMOJI.get(카테고리, "🎬")
    print(
        f"[DEBUG] review_command() 모달 버튼 followup 전송 - "
        f"category={카테고리}, has_link={bool(링크)}, "
        f"source_url={source_url}, response_done={interaction.response.is_done()}",
        flush=True
    )

    sent = await send_ephemeral_interaction(
        interaction,
        f"{emoji} {category_text} 한줄평 입력창을 열 준비가 됐습니다. 아래 버튼을 누르면 입력창이 열립니다.",
        view=view
    )
    if not sent:
        print(
            f"[ERROR] review_command() 모달 버튼 followup 전송 실패 "
            f"(category={카테고리}, has_link={bool(링크)}, source_url={source_url}, "
            f"response_done={interaction.response.is_done()})",
            flush=True
        )


@discord.app_commands.command(name="내리뷰", description="내가 작성한 리뷰 목록을 조회합니다.")
@discord.app_commands.describe(카테고리="조회할 카테고리 (선택 안하면 전체)")
@discord.app_commands.choices(카테고리=[
    discord.app_commands.Choice(name="전체", value="all"),
    discord.app_commands.Choice(name="영화", value="movie"),
    discord.app_commands.Choice(name="드라마", value="drama"),
    discord.app_commands.Choice(name="애니", value="anime"),
    discord.app_commands.Choice(name="만화", value="manga"),
    discord.app_commands.Choice(name="웹툰", value="webtoon"),
    discord.app_commands.Choice(name="웹소설", value="webnovel"),
    discord.app_commands.Choice(name="게임", value="game"),
    discord.app_commands.Choice(name="곡", value="music_track"),
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
        season_text = format_season(cat, review.get('season'))

        # 카테고리별 표시 형식
        if cat in ['webtoon', 'webnovel']:
            subtitle = f"- {review['movie_year']}"  # 플랫폼
        elif cat in MUSIC_CATEGORIES:
            subtitle = f"({review['movie_year']})" if review.get('movie_year') else ""
        else:
            subtitle = f"({review['movie_year']})"

        value = f"⭐ {score_emoji} {review['score']} /5\n💬 \"{review['one_line_review']}\""
        if cat in MUSIC_CATEGORIES and review.get('director'):
            value = f"🎤 {review['director']}\n{value}"
        if cat == 'game' and review.get('director'):
            value = f"🏢 {review['director']}\n{value}"
        if review.get('unit_to') is not None:
            progress_text = format_progress_text(
                cat,
                review.get('season'),
                review.get('unit_to'),
                review.get('latest_units')
            )
            value += f"\n📌 {progress_text}"
        if review.get('source_url'):
            value += f"\n🔗 <{review['source_url']}>"

        embed.add_field(
            name=f"{emoji} {review['movie_title']}{season_text} {subtitle}",
            value=value,
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
    discord.app_commands.Choice(name="웹소설", value="webnovel"),
    discord.app_commands.Choice(name="게임", value="game"),
    discord.app_commands.Choice(name="곡", value="music_track"),
])
async def stats_command(interaction: discord.Interaction, 제목: str, 카테고리: str = "all"):
    category = None if 카테고리 == "all" else 카테고리
    stats = bot.db.get_content_stats(제목, category)

    if not stats or stats['review_count'] == 0:
        await interaction.response.send_message(f"❌ '{제목}'에 대한 리뷰가 없습니다.", ephemeral=True)
        return

    emoji = CATEGORY_EMOJI.get(category, "📊")

    embed = discord.Embed(title=f"{emoji} {제목} 통계", color=0x3498db)
    embed.add_field(name="참여 유저 수", value=f"{stats['review_count']}명", inline=True)
    embed.add_field(name="평균 평점", value=f"{stats['avg_score']:.2f}/5", inline=True)
    embed.add_field(name="최고 평점", value=f"{stats['max_score']}/5", inline=True)
    embed.add_field(name="최저 평점", value=f"{stats['min_score']}/5", inline=True)

    await interaction.response.send_message(embed=embed, ephemeral=True)


@discord.app_commands.command(name="리뷰히스토리", description="작품별 진행 히스토리와 수정 내역을 조회합니다.")
@discord.app_commands.describe(
    제목="조회할 작품 제목",
    카테고리="카테고리 (선택)",
    기수="조회할 시즌/기/부 번호 (전체 리뷰는 0)",
    개수="가져올 기록 수 (1~20)"
)
@discord.app_commands.choices(카테고리=[
    discord.app_commands.Choice(name="🎬 영화", value="movie"),
    discord.app_commands.Choice(name="📺 드라마", value="drama"),
    discord.app_commands.Choice(name="🎞️ 애니", value="anime"),
    discord.app_commands.Choice(name="📚 만화", value="manga"),
    discord.app_commands.Choice(name="📱 웹툰", value="webtoon"),
    discord.app_commands.Choice(name="📖 웹소설", value="webnovel"),
    discord.app_commands.Choice(name="🎮 게임", value="game"),
    discord.app_commands.Choice(name="🎵 곡", value="music_track"),
])
async def review_history_command(
    interaction: discord.Interaction,
    제목: str,
    카테고리: str = None,
    기수: int = None,
    개수: int = 10
):
    if 기수 is not None and 기수 < 0:
        await interaction.response.send_message("❌ 기수는 0 이상으로 입력해주세요.", ephemeral=True)
        return

    limit = max(1, min(개수 or 10, 20))
    season_kwargs = {} if 기수 is None else {'season': None if 기수 == 0 else 기수}

    history = bot.db.get_review_history(
        interaction.user.id,
        제목,
        카테고리,
        limit=limit,
        **season_kwargs
    )
    logs = bot.db.get_review_logs(
        interaction.user.id,
        title=제목,
        category=카테고리,
        limit=limit,
        **season_kwargs
    )

    if not history and not logs:
        await interaction.response.send_message(f"❌ '{제목}'에 대한 히스토리를 찾을 수 없습니다.", ephemeral=True)
        return

    base_category = 카테고리 or (history[0]['category'] if history else logs[0].get('category'))
    emoji = CATEGORY_EMOJI.get(base_category, "🧾")
    embed = discord.Embed(title=f"{emoji} {제목} 리뷰 히스토리", color=0x5865F2)

    if history:
        latest = history[0]
        latest_scope = format_history_scope(latest)
        latest_value = (
            f"{latest_scope}\n"
            f"⭐ {format_score_value(latest['score'])}/5\n"
            f"💬 \"{short_text(latest['one_line_review'], 120)}\""
        )
        if latest.get('source_url'):
            latest_value += f"\n🔗 <{latest['source_url']}>"
        embed.add_field(
            name="최신 히스토리",
            value=latest_value,
            inline=False
        )

        history_lines = []
        for item in history:
            history_lines.append(
                f"`{format_datetime(item.get('created_at'))}` "
                f"{format_history_scope(item)} | "
                f"⭐ {format_score_value(item['score'])}/5 | "
                f"{short_text(item['one_line_review'])}"
            )
        embed.add_field(name="진행 히스토리", value=join_embed_lines(history_lines), inline=False)

    if logs:
        action_labels = {"edit": "수정", "delete": "삭제"}
        log_lines = []
        for log in logs:
            action = action_labels.get(log.get('action'), log.get('action', '기록'))
            scope = format_history_scope(log)
            score_part = format_score_value(log.get('old_score'))
            if log.get('new_score') is not None:
                score_part += f" → {format_score_value(log.get('new_score'))}"
            log_lines.append(
                f"`{format_datetime(log.get('created_at'))}` "
                f"{action} | {scope} | ⭐ {score_part}"
            )
        embed.add_field(name="수정/삭제 내역", value=join_embed_lines(log_lines), inline=False)

    await interaction.response.send_message(embed=embed, ephemeral=True)


@discord.app_commands.command(name="리뷰삭제", description="특정 작품의 내 리뷰를 삭제합니다.")
@discord.app_commands.describe(제목="삭제할 작품 제목", 카테고리="카테고리", 기수="삭제할 시즌/기/부 번호 (전체 리뷰는 0)")
@discord.app_commands.choices(카테고리=[
    discord.app_commands.Choice(name="영화", value="movie"),
    discord.app_commands.Choice(name="드라마", value="drama"),
    discord.app_commands.Choice(name="애니", value="anime"),
    discord.app_commands.Choice(name="만화", value="manga"),
    discord.app_commands.Choice(name="웹툰", value="webtoon"),
    discord.app_commands.Choice(name="웹소설", value="webnovel"),
    discord.app_commands.Choice(name="게임", value="game"),
    discord.app_commands.Choice(name="곡", value="music_track"),
])
async def delete_review_command(interaction: discord.Interaction, 제목: str, 카테고리: str = None, 기수: int = None):
    await interaction.response.defer(ephemeral=True)

    season_value, season_message = resolve_review_season(bot.db, interaction.user.id, 제목, 카테고리, 기수)
    if season_message:
        await interaction.followup.send(season_message, ephemeral=True)
        return
    season_kwargs = {} if 기수 is None and 카테고리 is None else {'season': season_value}

    # 삭제 전 기존 데이터 조회 (로그용 + 메시지 삭제용)
    review = bot.db.get_user_review(interaction.user.id, 제목, 카테고리, **season_kwargs)

    if not review:
        season_text = format_season(카테고리, season_value) if 카테고리 else ""
        await interaction.followup.send(f"❌ '{제목}{season_text}' 리뷰를 찾을 수 없습니다.")
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
    deleted = bot.db.delete_review(interaction.user.id, 제목, 카테고리, **season_kwargs)

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
            old_additional_comment=review.get('additional_comment'),
            season=review.get('season'),
            unit_from=review.get('unit_from'),
            unit_to=review.get('unit_to'),
            latest_units=review.get('latest_units'),
            source_url=review.get('source_url')
        )

        cat_text = f" ({CATEGORY_NAME.get(카테고리, '')})" if 카테고리 else ""
        season_text = format_season(review.get('category', 카테고리), review.get('season'))

        # 결과 메시지 구성
        result_parts = [f"✅ '{제목}{season_text}'{cat_text} 리뷰가 삭제되었습니다."]
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
@discord.app_commands.describe(제목="수정할 작품 제목", 카테고리="카테고리", 기수="수정할 시즌/기/부 번호 (전체 리뷰는 0)")
@discord.app_commands.choices(카테고리=[
    discord.app_commands.Choice(name="영화", value="movie"),
    discord.app_commands.Choice(name="드라마", value="drama"),
    discord.app_commands.Choice(name="애니", value="anime"),
    discord.app_commands.Choice(name="만화", value="manga"),
    discord.app_commands.Choice(name="웹툰", value="webtoon"),
    discord.app_commands.Choice(name="웹소설", value="webnovel"),
    discord.app_commands.Choice(name="게임", value="game"),
    discord.app_commands.Choice(name="곡", value="music_track"),
])
async def edit_review_command(interaction: discord.Interaction, 제목: str, 카테고리: str = None, 기수: int = None):
    season_value, season_message = resolve_review_season(bot.db, interaction.user.id, 제목, 카테고리, 기수)
    if season_message:
        await interaction.response.send_message(season_message, ephemeral=True)
        return
    season_kwargs = {} if 기수 is None and 카테고리 is None else {'season': season_value}

    # DB에서 리뷰 조회
    review = bot.db.get_user_review(interaction.user.id, 제목, 카테고리, **season_kwargs)

    if not review:
        cat_text = f" ({CATEGORY_NAME.get(카테고리, '')})" if 카테고리 else ""
        season_text = format_season(카테고리, season_value) if 카테고리 else ""
        await interaction.response.send_message(
            f"❌ '{제목}{season_text}'{cat_text} 리뷰를 찾을 수 없습니다.",
            ephemeral=True
        )
        return
    if review.get('category') == 'music_album':
        await interaction.response.send_message(
            "❌ 앨범 리뷰는 더 이상 지원하지 않습니다. 삭제 후 곡 리뷰로 새로 작성해주세요.",
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

    # 메시지에서 title, category, season 파싱 (message_id 우선)
    title, category, season, message_review = resolve_review_message(bot.db, message)
    if not title or not category:
        await interaction.response.send_message("❌ 리뷰 메시지를 인식할 수 없습니다.", ephemeral=True)
        return

    if message_review and int(message_review['user_id']) != interaction.user.id:
        await interaction.response.send_message(
            f"❌ '{title}' 리뷰를 찾을 수 없거나 본인의 리뷰가 아닙니다.", ephemeral=True
        )
        return

    # DB에서 리뷰 조회 (소유권 확인)
    review = bot.db.get_user_review(interaction.user.id, title, category, season=season)
    if not review:
        await interaction.response.send_message(
            f"❌ '{title}' 리뷰를 찾을 수 없거나 본인의 리뷰가 아닙니다.", ephemeral=True
        )
        return
    if review.get('category') == 'music_album':
        await interaction.response.send_message(
            "❌ 앨범 리뷰는 더 이상 지원하지 않습니다. 삭제 후 곡 리뷰로 새로 작성해주세요.",
            ephemeral=True
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
CATEGORY_TO_SEARCH = {
    'movie': 'tmdb',
    'drama': 'tmdb',
    'anime': 'tmdb',
    'manga': 'manga',
    'webtoon': 'webtoon',
    'webnovel': 'webnovel',
    'music_track': 'music_track',
    'game': 'game',
}


@discord.app_commands.context_menu(name="나도 쓰기")
async def write_review_context(interaction: discord.Interaction, message: discord.Message):
    # 봇이 보낸 메시지인지 확인
    if message.author != interaction.client.user:
        await interaction.response.send_message("❌ 봇이 보낸 리뷰 메시지에서만 사용할 수 있습니다.", ephemeral=True)
        return

    # 메시지에서 title, category, season 파싱 (message_id 우선)
    title, db_category, season, message_review = resolve_review_message(bot.db, message)
    if not title or not db_category:
        await interaction.response.send_message("❌ 리뷰 메시지를 인식할 수 없습니다.", ephemeral=True)
        return

    # director, year 파싱
    if message_review:
        director = message_review.get('director')
        year = message_review.get('movie_year')
    else:
        director, year = parse_review_detail(message.content)

    # 포스터 이미지 URL 획득
    img_url = message_review.get('img_url') if message_review else None
    if not img_url:
        img_url = message.attachments[0].url if message.attachments else None

    search_category = CATEGORY_TO_SEARCH.get(db_category)
    if not search_category:
        await interaction.response.send_message(
            "❌ 앨범 리뷰는 더 이상 지원하지 않습니다. 곡 리뷰로 새로 작성해주세요.",
            ephemeral=True
        )
        return
    prefetched_info = (title, year, director, img_url)

    modal = ReviewForm(
        bot.db,
        search_category,
        interaction.user.id,
        str(interaction.user),
        interaction.user.display_name,
        prefetched_info=prefetched_info,
        prefetched_category=db_category,
        default_season=season
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

    # 메시지에서 title, category, season 파싱 (message_id 우선)
    title, category, season, message_review = resolve_review_message(bot.db, message)
    if not title or not category:
        await interaction.followup.send("❌ 리뷰 메시지를 인식할 수 없습니다.", ephemeral=True)
        return

    if message_review and int(message_review['user_id']) != interaction.user.id:
        await interaction.followup.send(
            f"❌ '{title}' 리뷰를 찾을 수 없거나 본인의 리뷰가 아닙니다.", ephemeral=True
        )
        return

    # DB에서 리뷰 조회 (소유권 확인)
    review = message_review or bot.db.get_user_review(interaction.user.id, title, category, season=season)
    if not review:
        await interaction.followup.send(
            f"❌ '{title}' 리뷰를 찾을 수 없거나 본인의 리뷰가 아닙니다.", ephemeral=True
        )
        return

    if not message_review and not is_current_review_message(review, message):
        await interaction.followup.send(
            "❌ 최신 리뷰 메시지에서만 삭제할 수 있습니다. 가장 최근에 전송된 리뷰 메시지로 다시 시도해주세요.",
            ephemeral=True
        )
        return

    # DB 삭제
    if message_review:
        deleted = bot.db.delete_review_by_id(interaction.user.id, message_review['id'])
    else:
        deleted = bot.db.delete_review(interaction.user.id, title, category, season=season)
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
        old_additional_comment=review.get('additional_comment'),
        season=season,
        unit_from=review.get('unit_from'),
        unit_to=review.get('unit_to'),
        latest_units=review.get('latest_units'),
        source_url=review.get('source_url')
    )

    # 메시지 삭제
    try:
        await message.delete()
    except Exception as e:
        print(f"[ERROR] delete_review_context() 메시지 삭제 실패: {e}")

    cat_name = CATEGORY_NAME.get(category, "")
    season_text = format_season(category, season)
    await interaction.followup.send(
        f"✅ '{title}{season_text}' ({cat_name}) 리뷰가 삭제되었습니다.", ephemeral=True
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
                title, parsed_season = split_title_season(parsed.get('title'))
                score = parsed.get('score')
                one_line = parsed.get('one_line_review')
                category = parsed.get('category', 'movie')
                season = parse_season_number(parsed.get('season')) or parsed_season

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
                    channel_id=message.channel.id,
                    season=season
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
    discord.app_commands.Choice(name="📖 웹소설", value="webnovel"),
    discord.app_commands.Choice(name="🎮 게임", value="game"),
    discord.app_commands.Choice(name="🎵 곡", value="music_track"),
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

        season_text = format_season(review['category'], review.get('season'))
        score_str = return_score_emoji(review['score'])
        field_name = f"{idx}. {emoji} {review['movie_title']}{season_text}"
        field_value = (
            f"{score_str} | {cat_name}\n"
            f"✍️ {review['username']} | 💬 \"{review['one_line_review']}\"\n"
            f"반응: {breakdown} (총 {review['reaction_count']}개)"
        )
        embed.add_field(name=field_name, value=field_value, inline=False)

    await interaction.followup.send(embed=embed)


bot.run(Token)
