# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Communication Rules

- **Always explain in Korean** - All explanations, descriptions, and responses must be in Korean
- **Code-related content in English** - Variable names, function names, comments in code, commit messages, and technical terms should remain in English

## Project Overview

A Discord bot for content reviews (movies, dramas, anime, manga, webtoons) using slash commands. Reviews are stored in PostgreSQL (Supabase). Also includes a daily entertainment news scheduler using Grok AI.

## Running the Bot

```bash
python piacia.py
```

**Required environment variables:**
- `Token` - Discord bot token
- `DATABASE_URL` - PostgreSQL connection string (Supabase)
- `TMDB_API` - TMDB API key for movie/drama/anime search
- `GROK_API_KEY` - Grok AI API key for news feature (optional)
- `NEWS_CHANNEL_ID` - Discord channel ID for daily news (optional)

## Code Architecture

### Core Components

| File | Purpose |
|------|---------|
| `piacia.py` | Main entry: `MyBot` class, slash commands, `ReviewForm` modal, `MovieSelectView` |
| `api_searcher.py` | `ContentSearcher` (TMDB/MangaDex/Naver), `GrokSearcher` (news via xai-sdk) |
| `database.py` | `Database` class with psycopg2, auto-creates `reviews` table on init |
| `news_scheduler.py` | `NewsScheduler` with discord.ext.tasks loop (13:00 KST daily) |
| `review_form.py` | `MOVIE_FORM`, `MANGA_FORM`, `WEBTOON_FORM` templates |

### Slash Commands

| Command | Description |
|---------|-------------|
| `/한줄평 [카테고리]` | Open review modal (tmdb/manga/webtoon) |
| `/내리뷰 [카테고리]` | Show user's recent 5 reviews |
| `/통계 [제목] [카테고리]` | Show content statistics |
| `/리뷰삭제 [제목] [카테고리]` | Delete user's review |
| `/뉴스` | Admin-only: Send daily news immediately |

### Key Flow: Review Submission

1. `/한줄평 [category]` → `ReviewForm` modal
2. User submits: title, score (0-5), one-line review, optional comment
3. Search by category:
   - **tmdb**: `search_tmdb_multiple()` → multi-result select menu if >1 result
   - **manga**: MangaDex API with Korean title priority
   - **webtoon**: Naver Webtoon API
4. `_save_and_send_review()`: duplicate check → DB save → format with template → send with poster

### Category System

Categories: `movie`, `drama`, `anime`, `manga`, `webtoon`

- TMDB auto-detects category from media_type and genre (animation=anime, tv=drama)
- Each category has emoji (`CATEGORY_EMOJI`) and Korean name (`CATEGORY_NAME`) mappings

### News Scheduler Architecture

`GrokSearcher.fetch_all_categorized_news()`:
1. Parallel calls to 3 groups (movie, drama, acg) via `asyncio.gather`
2. Each group uses xai-sdk with `web_search()` and `x_search()` tools
3. Merges results into 5 categories + generates headlines
4. `NewsScheduler` creates main embed + category buttons + discussion thread

### Database Schema

`reviews` table (auto-created on startup):
```sql
id SERIAL PRIMARY KEY,
user_id BIGINT NOT NULL,
username TEXT,
movie_title TEXT NOT NULL,
movie_year TEXT,
director TEXT,
score REAL NOT NULL,
one_line_review TEXT NOT NULL,
additional_comment TEXT,
category TEXT DEFAULT 'movie',
created_at TIMESTAMP DEFAULT NOW()
```

See [DB_SETUP.md](DB_SETUP.md) for Supabase setup.
