# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Discord bot for managing movie/media reviews. Users can write and manage reviews for movies, dramas, anime, manga, and webtoons via Discord slash commands. Reviews are stored in PostgreSQL with automatic content lookup via external APIs.

## Running the Bot

```bash
# Install dependencies
pip install -r requirements.txt

# Run the bot
python piacia.py
```

## Required Environment Variables

- `Token` - Discord bot token
- `TMDB_API` - TMDB API key
- `DATABASE_URL` - PostgreSQL connection string (format: `postgres://user:password@host:port/dbname`)

## Architecture

### File Structure

- **piacia.py** - Main entry point with Discord bot class, slash commands, and UI components
- **api_searcher.py** - External API integration (TMDB, MangaDex, Naver Webtoon) with Google Translate
- **database.py** - PostgreSQL operations and schema management
- **review_form.py** - Discord message templates for different content types

### Content Categories

The bot handles 5 content types with different API sources:
- **Movies/Dramas/Anime** - TMDB API (anime detected by genre ID 16)
- **Manga** - MangaDex API
- **Webtoons** - Naver Webtoon API

### Slash Commands

1. `/한줄평` - Write a review (triggers API search, shows selection menu if multiple results)
2. `/내리뷰` - View user's recent reviews with optional category filtering
3. `/통계` - Get aggregate statistics for specific content
4. `/리뷰삭제` - Delete a review

### Key Patterns

- All external operations use async/await with aiohttp
- ContentSearcher class centralizes API calls with automatic Korean translation
- Database class uses connection pooling via context manager
- UI uses Discord modals (ReviewForm) and select menus (MovieSelectView)
- Score display uses moon phase emojis (0-5 scale)

### Database Schema

Single `reviews` table with: user_id, username, movie_title, movie_year, director, score, one_line_review, additional_comment, category, created_at. Indices on user_id and movie_title.
