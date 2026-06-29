SEASON_LABEL = {
    'drama': '시즌',
    'anime': '기',
    'webtoon': '기',
    'manga': '부',
    'webnovel': '부',
}


def format_season(category, season):
    """시즌 표시 문자열 반환. season이 None이면 빈 문자열."""
    if season is None:
        return ""
    label = SEASON_LABEL.get(category, '시즌')
    return f" {season}{label}"


MOVIE_FORM = (
    "🎬제목: {title}{season_text}\n"
    "🎥감독: {director_name}\n"
    "📅개봉년도: {year}\n"
    "\n"
    "평점 : {score} \n"
    "\n"
    "\"{one_line_text}\"\n"
    "\n"
    "작성자: {author_name} \n"
)

MANGA_FORM = (
    "📚제목: {title}{season_text}\n"
    "✍️작가: {author}\n"
    "📅연재년도: {year}\n"
    "\n"
    "평점 : {score} \n"
    "\n"
    "\"{one_line_text}\"\n"
    "\n"
    "작성자: {author_name} \n"
)

WEBTOON_FORM = (
    "📱제목: {title}{season_text}\n"
    "✍️작가: {author}\n"
    "📍플랫폼: {platform}\n"
    "\n"
    "평점 : {score} \n"
    "\n"
    "\"{one_line_text}\"\n"
    "\n"
    "작성자: {author_name} \n"
)

WEBNOVEL_FORM = (
    "📖제목: {title}{season_text}\n"
    "✍️작가: {author}\n"
    "📍플랫폼: {platform}\n"
    "\n"
    "평점 : {score} \n"
    "\n"
    "\"{one_line_text}\"\n"
    "\n"
    "작성자: {author_name} \n"
)
