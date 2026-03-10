"""
BULK Wrapped API - Full Version with Progress Streaming
"""

from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import os
import re
import requests
import json
import html
from datetime import datetime, timedelta
from collections import defaultdict

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# RapidAPI configuration
RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY", "")
RAPIDAPI_HOST = "twitter-api45.p.rapidapi.com"


@app.route('/')
def home():
    return jsonify({"status": "BULK Wrapped API is running", "version": "2.0"})


@app.route('/api/ping', methods=['GET'])
def ping():
    return jsonify({"status": "ok"})


@app.route('/api/wrapped', methods=['POST', 'OPTIONS'])
def get_wrapped():
    """Standard wrapped endpoint (no streaming)"""
    if request.method == 'OPTIONS':
        return '', 204
    
    data = request.json or {}
    handle = data.get('handle', '').strip().replace('@', '')
    
    if not handle:
        return jsonify({"error": "Handle is required"}), 400
    
    if not RAPIDAPI_KEY:
        return jsonify({"error": "API not configured"}), 500
    
    try:
        user_info = fetch_user_profile(handle)
        tweets = fetch_user_tweets(handle)
        bulk_tweets = filter_bulk_tweets(tweets)
        
        if not bulk_tweets:
            return jsonify({
                "error": "No BULK-related posts found for @" + handle,
                "handle": handle,
                "total_tweets_scanned": len(tweets),
                "found": False
            }), 404
        
        stats = calculate_wrapped_stats(bulk_tweets, handle)
        stats["profile_image"] = user_info.get("profile_image") if user_info else None
        stats["display_name"] = user_info.get("name") if user_info else handle
        
        # Add timeline data
        timeline = build_timeline(bulk_tweets, handle)
        
        return jsonify({
            "success": True,
            "handle": handle,
            "total_tweets_scanned": len(tweets),
            "bulk_tweets_found": len(bulk_tweets),
            "stats": stats,
            "timeline": timeline,
            "user": user_info
        })
        
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/wrapped/stream', methods=['GET'])
def get_wrapped_stream():
    """
    Streaming endpoint with Server-Sent Events for progress updates
    """
    handle = request.args.get('handle', '').strip().replace('@', '')
    
    if not handle:
        return jsonify({"error": "Handle is required"}), 400
    
    if not RAPIDAPI_KEY:
        return jsonify({"error": "API not configured"}), 500
    
    def generate():
        try:
            # Step 1: Fetch profile
            yield f"data: {json.dumps({'step': 'profile', 'message': 'Fetching profile...', 'progress': 5})}\n\n"
            user_info = fetch_user_profile(handle)
            
            # Step 2: Fetch tweets with progress
            all_tweets = []
            cursor = None
            max_pages = 50
            
            headers = {
                "x-rapidapi-key": RAPIDAPI_KEY,
                "x-rapidapi-host": RAPIDAPI_HOST
            }
            
            for page in range(max_pages):
                progress = 5 + int((page / max_pages) * 75)  # 5-80%
                yield f"data: {json.dumps({'step': 'scanning', 'message': f'Scanning page {page + 1}...', 'progress': progress, 'tweets_found': len(all_tweets)})}\n\n"
                
                url = f"https://{RAPIDAPI_HOST}/timeline.php"
                params = {"screenname": handle}
                if cursor:
                    params["cursor"] = cursor
                
                try:
                    response = requests.get(url, headers=headers, params=params, timeout=15)
                    
                    if response.status_code == 429:
                        yield f"data: {json.dumps({'step': 'scanning', 'message': 'Rate limited, processing what we have...', 'progress': 80})}\n\n"
                        break
                    
                    if response.status_code != 200:
                        if page == 0:
                            yield f"data: {json.dumps({'step': 'error', 'error': f'User @{handle} not found or private'})}\n\n"
                            return
                        break
                    
                    data = response.json()
                    timeline = data.get("timeline", [])
                    
                    if not timeline:
                        break
                    
                    all_tweets.extend(timeline)
                    cursor = data.get("next_cursor")
                    
                    if not cursor:
                        break
                        
                except requests.exceptions.Timeout:
                    break
                except Exception as e:
                    if page == 0:
                        yield f"data: {json.dumps({'step': 'error', 'error': str(e)})}\n\n"
                        return
                    break
            
            # Step 3: Filter tweets
            yield f"data: {json.dumps({'step': 'filtering', 'message': f'Found {len(all_tweets)} tweets, filtering for BULK...', 'progress': 85})}\n\n"
            bulk_tweets = filter_bulk_tweets(all_tweets)
            
            if not bulk_tweets:
                yield f"data: {json.dumps({'step': 'error', 'error': f'No BULK-related posts found for @{handle}', 'total_scanned': len(all_tweets)})}\n\n"
                return
            
            # Step 4: Calculate stats
            yield f"data: {json.dumps({'step': 'calculating', 'message': f'Found {len(bulk_tweets)} BULK posts! Calculating stats...', 'progress': 90})}\n\n"
            stats = calculate_wrapped_stats(bulk_tweets, handle)
            stats["profile_image"] = user_info.get("profile_image") if user_info else None
            stats["display_name"] = user_info.get("name") if user_info else handle
            
            # Step 5: Build timeline
            yield f"data: {json.dumps({'step': 'timeline', 'message': 'Building your journey timeline...', 'progress': 95})}\n\n"
            timeline = build_timeline(bulk_tweets, handle)
            
            # Step 6: Complete
            result = {
                "step": "complete",
                "progress": 100,
                "success": True,
                "handle": handle,
                "total_tweets_scanned": len(all_tweets),
                "bulk_tweets_found": len(bulk_tweets),
                "stats": stats,
                "timeline": timeline,
                "user": user_info
            }
            yield f"data: {json.dumps(result)}\n\n"
            
        except Exception as e:
            yield f"data: {json.dumps({'step': 'error', 'error': str(e)})}\n\n"
    
    return Response(generate(), mimetype='text/event-stream', headers={
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
        'Access-Control-Allow-Origin': '*'
    })


def fetch_user_profile(handle):
    """Fetch user's profile info including PFP"""
    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": RAPIDAPI_HOST
    }
    
    try:
        url = f"https://{RAPIDAPI_HOST}/screenname.php"
        response = requests.get(url, headers=headers, params={"screenname": handle}, timeout=10)
        
        if response.status_code != 200:
            return None
        
        data = response.json()
        
        profile_image = (
            data.get("profile_image_url_https") or
            data.get("profile_image_url") or
            data.get("avatar") or
            data.get("profile_pic_url") or
            data.get("profile_image")
        )
        
        if profile_image and "_normal" in profile_image:
            profile_image = profile_image.replace("_normal", "_400x400")
        
        return {
            "name": data.get("name") or handle,
            "screen_name": data.get("screen_name") or handle,
            "profile_image": profile_image,
            "followers": data.get("followers_count") or data.get("followers") or 0,
            "following": data.get("friends_count") or data.get("following") or 0,
            "bio": data.get("description") or data.get("bio") or ""
        }
        
    except Exception as e:
        print(f"Profile error: {e}")
        return None


def fetch_user_tweets(handle):
    """Fetch user tweets (non-streaming version)"""
    all_tweets = []
    cursor = None
    max_pages = 50
    
    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": RAPIDAPI_HOST
    }
    
    for page in range(max_pages):
        url = f"https://{RAPIDAPI_HOST}/timeline.php"
        params = {"screenname": handle}
        
        if cursor:
            params["cursor"] = cursor
        
        try:
            response = requests.get(url, headers=headers, params=params, timeout=15)
            
            if response.status_code != 200:
                if page == 0:
                    raise Exception(f"Failed to fetch user @{handle}")
                break
            
            data = response.json()
            timeline = data.get("timeline", [])
            
            if not timeline:
                break
            
            all_tweets.extend(timeline)
            cursor = data.get("next_cursor")
            
            if not cursor:
                break
                
        except requests.exceptions.Timeout:
            break
        except Exception as e:
            if page == 0:
                raise
            break
    
    return all_tweets


def filter_bulk_tweets(tweets):
    """
    Filter tweets related to BULK project.
    Rules:
    1. @bulktrade in text → count it
    2. "bulk" or "gbulk" + context keyword → count it
    3. "gbulk" alone → count it (gBULK token)
    4. Check quoted tweets, articles, notes for keywords
    
    Note: Article content is extracted from tweet.article.full_text by get_full_tweet_text()
    """
    bulk_tweets = []
    
    context_keywords = [
        "perp", "dex", "exchange", "trade", "long", "short",
        "liquidation", "decentralized", "trading", "community",
        "role", "og", "contributor", "@kdotcrypto", "@rizzy_sol",
        "@glowburger", "@junbug_sol", "bulkgram", "testnet",
        "airdrop", "token", "sol", "solana", "wrapped", "claim"
    ]
    
    for tweet in tweets:
        # Get ALL possible text content from the tweet (includes article.full_text)
        all_text = get_full_tweet_text(tweet)
        text_lower = all_text.lower()
        is_bulk_related = False
        
        # Rule 1: Direct @bulktrade mention
        if "@bulktrade" in text_lower:
            is_bulk_related = True
        
        # Rule 2: "bulk" + context keyword
        if not is_bulk_related and "bulk" in text_lower:
            for keyword in context_keywords:
                if keyword in text_lower:
                    is_bulk_related = True
                    break
        
        # Rule 3: "gbulk" (gBULK token) - always count
        if not is_bulk_related and "gbulk" in text_lower:
            is_bulk_related = True
        
        # Rule 4: Check user_mentions for @bulktrade
        if not is_bulk_related:
            user_mentions = tweet.get("entities", {}).get("user_mentions", [])
            for mention in user_mentions:
                if mention.get("screen_name", "").lower() == "bulktrade":
                    is_bulk_related = True
                    break
        
        # Rule 5: Check quoted tweet's user_mentions
        if not is_bulk_related:
            quoted_tweet = tweet.get("quoted_tweet") or tweet.get("quoted_status") or {}
            quoted_mentions = quoted_tweet.get("entities", {}).get("user_mentions", [])
            for mention in quoted_mentions:
                if mention.get("screen_name", "").lower() == "bulktrade":
                    is_bulk_related = True
                    break
        
        if is_bulk_related:
            tweet["extracted_media"] = extract_media_url(tweet)
            bulk_tweets.append(tweet)
    
    return bulk_tweets


def check_and_fetch_article(tweet):
    """
    Check if tweet contains an article URL and fetch its content
    Article URLs look like: x.com/i/article/... or twitter.com/i/article/...
    """
    # Get all URLs from the tweet
    urls = tweet.get("entities", {}).get("urls", [])
    
    for url_obj in urls:
        expanded_url = url_obj.get("expanded_url", "") or url_obj.get("url", "")
        
        # Check if it's an article URL
        if "/i/article/" in expanded_url or "/article/" in expanded_url:
            try:
                article_content = fetch_article_content(expanded_url)
                if article_content:
                    return article_content
            except Exception as e:
                print(f"Failed to fetch article: {e}")
                continue
    
    return None


def fetch_article_content(article_url):
    """
    Fetch Twitter article page and extract the text content
    Tries multiple methods since Twitter articles are JS-rendered
    """
    content = None
    
    # Method 1: Try direct fetch (might work for some articles)
    content = fetch_article_direct(article_url)
    if content and len(content) > 100:
        return content
    
    # Method 2: Try using a reader service (jina.ai)
    content = fetch_article_via_reader(article_url)
    if content and len(content) > 100:
        return content
    
    # Method 3: Try nitter (alternative Twitter frontend)
    content = fetch_article_via_nitter(article_url)
    if content and len(content) > 100:
        return content
    
    return content


def fetch_article_direct(article_url):
    """Direct fetch attempt"""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }
        
        response = requests.get(article_url, headers=headers, timeout=10, allow_redirects=True)
        
        if response.status_code != 200:
            return None
        
        html_content = response.text
        return extract_text_from_html(html_content)
        
    except Exception as e:
        print(f"Direct fetch failed: {e}")
        return None


def fetch_article_via_reader(article_url):
    """Use jina.ai reader to extract content from JS-rendered pages"""
    try:
        reader_url = f"https://r.jina.ai/{article_url}"
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; BulkWrapped/1.0)",
        }
        
        response = requests.get(reader_url, headers=headers, timeout=15)
        
        if response.status_code == 200:
            # Jina returns markdown-formatted text
            text = response.text
            if len(text) > 50:
                return text[:5000]  # Limit size
        
        return None
        
    except Exception as e:
        print(f"Reader fetch failed: {e}")
        return None


def fetch_article_via_nitter(article_url):
    """Try nitter instance for article content"""
    try:
        # Convert x.com/twitter.com URL to nitter
        # Articles might not work on nitter but worth trying
        nitter_url = article_url.replace("x.com", "nitter.net").replace("twitter.com", "nitter.net")
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
        
        response = requests.get(nitter_url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            return extract_text_from_html(response.text)
        
        return None
        
    except Exception as e:
        print(f"Nitter fetch failed: {e}")
        return None


def extract_text_from_html(html_content):
    """Extract readable text from HTML"""
    try:
        # Remove script and style tags
        html_content = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
        html_content = re.sub(r'<style[^>]*>.*?</style>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
        
        text_parts = []
        
        # Check og:description meta tag
        og_match = re.search(r'<meta[^>]*property=["\']og:description["\'][^>]*content=["\']([^"\']+)["\']', html_content, re.IGNORECASE)
        if og_match:
            text_parts.append(og_match.group(1))
        
        # Check twitter:description
        tw_match = re.search(r'<meta[^>]*name=["\']twitter:description["\'][^>]*content=["\']([^"\']+)["\']', html_content, re.IGNORECASE)
        if tw_match:
            text_parts.append(tw_match.group(1))
        
        # Look for article title
        title_match = re.search(r'<meta[^>]*property=["\']og:title["\'][^>]*content=["\']([^"\']+)["\']', html_content, re.IGNORECASE)
        if title_match:
            text_parts.append(title_match.group(1))
        
        # Try to extract from JSON-LD structured data
        json_ld_match = re.search(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html_content, re.DOTALL | re.IGNORECASE)
        if json_ld_match:
            try:
                json_data = json.loads(json_ld_match.group(1))
                if isinstance(json_data, dict):
                    article_body = json_data.get("articleBody") or json_data.get("text") or json_data.get("description", "")
                    if article_body:
                        text_parts.append(article_body)
            except:
                pass
        
        # Fallback: extract all text from body
        body_match = re.search(r'<body[^>]*>(.*?)</body>', html_content, re.DOTALL | re.IGNORECASE)
        if body_match:
            body = body_match.group(1)
            # Remove all HTML tags
            text = re.sub(r'<[^>]+>', ' ', body)
            # Clean up whitespace
            text = re.sub(r'\s+', ' ', text).strip()
            if len(text) > 100:
                text_parts.append(text[:2000])
        
        combined = " ".join(filter(None, text_parts))
        return html.unescape(combined) if combined else None
        
    except Exception as e:
        print(f"HTML extraction failed: {e}")
        return None


def html_decode(text):
    """Decode HTML entities"""
    try:
        return html.unescape(text)
    except:
        return text
    
    return bulk_tweets


def get_full_tweet_text(tweet):
    """
    Extract ALL text content from a tweet, including:
    - Regular text
    - Full text (for truncated tweets)
    - Note/Article content (Twitter long-form posts)
    - Quoted tweet text
    - Card/URL preview text
    """
    text_parts = []
    
    # Main tweet text (multiple possible field names)
    text_parts.append(tweet.get("text", ""))
    text_parts.append(tweet.get("full_text", ""))
    text_parts.append(tweet.get("tweet_text", ""))
    
    # Extended tweet (for tweets > 280 chars before note_tweet)
    extended = tweet.get("extended_tweet", {})
    if isinstance(extended, dict):
        text_parts.append(extended.get("full_text", ""))
    
    # Note tweet / Twitter article content - check ALL possible paths
    note_tweet = tweet.get("note_tweet") or {}
    if isinstance(note_tweet, dict):
        text_parts.append(note_tweet.get("text", ""))
        text_parts.append(note_tweet.get("content", ""))
        
        # Path: note_tweet.note_tweet_results.result.text (GraphQL API structure)
        note_results = note_tweet.get("note_tweet_results", {})
        if isinstance(note_results, dict):
            result = note_results.get("result", {})
            if isinstance(result, dict):
                text_parts.append(result.get("text", ""))
                # Rich text blocks
                entity_set = result.get("entity_set", {})
                if isinstance(entity_set, dict):
                    text_parts.append(entity_set.get("text", ""))
        
        # Notes can have rich text with multiple blocks
        rich_text = note_tweet.get("rich_text") or {}
        if isinstance(rich_text, dict):
            text_parts.append(rich_text.get("plain_text", ""))
            text_parts.append(rich_text.get("text", ""))
    
    # Article content (multiple possible structures)
    article = tweet.get("article") or tweet.get("twitter_article") or {}
    if isinstance(article, dict):
        text_parts.append(article.get("full_text", ""))  # THIS IS THE KEY ONE!
        text_parts.append(article.get("title", ""))
        text_parts.append(article.get("preview_text", ""))
        text_parts.append(article.get("text", ""))
        text_parts.append(article.get("content", ""))
        text_parts.append(article.get("body", ""))
        text_parts.append(article.get("subtitle", ""))
        # Article results structure
        results = article.get("article_results", {}).get("result", {})
        if isinstance(results, dict):
            text_parts.append(results.get("full_text", ""))
            text_parts.append(results.get("title", ""))
            text_parts.append(results.get("text", ""))
    
    # Tweet legacy field (some APIs use this)
    legacy = tweet.get("legacy", {})
    if isinstance(legacy, dict):
        text_parts.append(legacy.get("full_text", ""))
        text_parts.append(legacy.get("text", ""))
    
    # Quoted tweet text - check recursively
    quoted_tweet = tweet.get("quoted_tweet") or tweet.get("quoted_status") or {}
    if isinstance(quoted_tweet, dict):
        text_parts.append(quoted_tweet.get("text", ""))
        text_parts.append(quoted_tweet.get("full_text", ""))
        # Check quoted tweet's note/article too
        quoted_note = quoted_tweet.get("note_tweet") or {}
        if isinstance(quoted_note, dict):
            text_parts.append(quoted_note.get("text", ""))
            qn_results = quoted_note.get("note_tweet_results", {}).get("result", {})
            if isinstance(qn_results, dict):
                text_parts.append(qn_results.get("text", ""))
        # Quoted legacy
        quoted_legacy = quoted_tweet.get("legacy", {})
        if isinstance(quoted_legacy, dict):
            text_parts.append(quoted_legacy.get("full_text", ""))
    
    # Retweeted status
    retweeted = tweet.get("retweeted_status") or tweet.get("retweeted_tweet") or {}
    if isinstance(retweeted, dict):
        text_parts.append(retweeted.get("text", ""))
        text_parts.append(retweeted.get("full_text", ""))
    
    # Card/URL preview (sometimes has title/description)
    card = tweet.get("card") or tweet.get("url_card") or {}
    if isinstance(card, dict):
        text_parts.append(card.get("title", ""))
        text_parts.append(card.get("description", ""))
        # Card binding values
        binding = card.get("binding_values", {})
        if isinstance(binding, dict):
            for key in ["title", "description", "vanity_url"]:
                val = binding.get(key, {})
                if isinstance(val, dict):
                    text_parts.append(val.get("string_value", ""))
    
    # URL entities might have expanded URLs with text
    urls = tweet.get("entities", {}).get("urls", [])
    for url in urls:
        if isinstance(url, dict):
            text_parts.append(url.get("title", ""))
            text_parts.append(url.get("description", ""))
            text_parts.append(url.get("expanded_url", ""))
    
    # Combine all text parts, remove empty strings and duplicates
    full_text = " ".join(filter(None, text_parts))
    return full_text


def extract_media_url(tweet):
    """Extract media URL from tweet"""
    media = tweet.get("media")
    
    if isinstance(media, dict):
        photos = media.get("photo", [])
        if photos and len(photos) > 0:
            return photos[0].get("media_url_https") or photos[0].get("media_url")
        
        videos = media.get("video", [])
        if videos and len(videos) > 0:
            return videos[0].get("media_url_https") or videos[0].get("thumbnail_url")
    
    elif isinstance(media, list) and len(media) > 0:
        return media[0].get("media_url_https") or media[0].get("media_url")
    
    ext_media = tweet.get("extended_entities", {}).get("media", [])
    if ext_media and len(ext_media) > 0:
        return ext_media[0].get("media_url_https")
    
    ent_media = tweet.get("entities", {}).get("media", [])
    if ent_media and len(ent_media) > 0:
        return ent_media[0].get("media_url_https")
    
    return None


def parse_tweet_date(created_at):
    """Parse tweet date from various formats"""
    if not created_at:
        return None
    
    try:
        if 'T' in str(created_at):
            return datetime.fromisoformat(created_at.replace('Z', '+00:00'))
        else:
            return datetime.strptime(created_at, '%a %b %d %H:%M:%S %z %Y')
    except:
        return None


def calculate_wrapped_stats(tweets, handle):
    """Calculate wrapped statistics from tweets"""
    
    total_posts = len(tweets)
    total_views = 0
    total_likes = 0
    total_retweets = 0
    total_replies = 0
    
    most_viral_post = None
    most_liked_post = None
    max_views = 0
    max_likes = 0
    
    first_post_date = None
    first_post = None
    
    posts_by_month = defaultdict(int)
    
    for tweet in tweets:
        views = int(tweet.get('views', 0) or 0)
        likes = int(tweet.get('favorites', 0) or tweet.get('favorite_count', 0) or 0)
        retweets = int(tweet.get('retweets', 0) or tweet.get('retweet_count', 0) or 0)
        replies = int(tweet.get('replies', 0) or tweet.get('reply_count', 0) or 0)
        
        total_views += views
        total_likes += likes
        total_retweets += retweets
        total_replies += replies
        
        tweet_id = tweet.get('tweet_id') or tweet.get('id_str') or tweet.get('id', '')
        tweet_url = f"https://twitter.com/{handle}/status/{tweet_id}"
        media_url = tweet.get("extracted_media")
        
        if views > max_views:
            max_views = views
            most_viral_post = {
                "text": tweet.get('text', '')[:280],
                "views": views,
                "likes": likes,
                "url": tweet_url,
                "date": tweet.get('created_at', ''),
                "media": media_url
            }
        
        if likes > max_likes:
            max_likes = likes
            most_liked_post = {
                "text": tweet.get('text', '')[:280],
                "views": views,
                "likes": likes,
                "url": tweet_url,
                "date": tweet.get('created_at', ''),
                "media": media_url
            }
        
        created_at = tweet.get('created_at', '')
        post_date = parse_tweet_date(created_at)
        
        if post_date:
            if first_post_date is None or post_date < first_post_date:
                first_post_date = post_date
                first_post = {
                    "text": tweet.get('text', '')[:280],
                    "date": created_at,
                    "url": tweet_url,
                    "media": tweet.get("extracted_media")
                }
            
            month_key = post_date.strftime('%Y-%m')
            posts_by_month[month_key] += 1
    
    streak = calculate_streak(posts_by_month)
    
    first_post_formatted = None
    if first_post_date:
        first_post_formatted = first_post_date.strftime('%B %d, %Y')
    
    return {
        "total_posts": total_posts,
        "total_views": total_views,
        "total_likes": total_likes,
        "total_retweets": total_retweets,
        "total_replies": total_replies,
        "total_engagement": total_likes + total_retweets + total_replies,
        "most_viral_post": most_viral_post,
        "most_liked_post": most_liked_post,
        "first_post": first_post,
        "first_post_date": first_post_formatted,
        "posting_streak": streak,
        "posts_by_month": dict(posts_by_month)
    }


def calculate_streak(posts_by_month):
    """Calculate longest consecutive month posting streak"""
    if not posts_by_month:
        return 0
    
    sorted_months = sorted(posts_by_month.keys())
    
    if len(sorted_months) <= 1:
        return len(sorted_months)
    
    max_streak = 1
    current_streak = 1
    
    for i in range(1, len(sorted_months)):
        prev_year, prev_month = map(int, sorted_months[i-1].split('-'))
        curr_year, curr_month = map(int, sorted_months[i].split('-'))
        
        expected_year = prev_year + (prev_month // 12)
        expected_month = (prev_month % 12) + 1
        
        if curr_year == expected_year and curr_month == expected_month:
            current_streak += 1
            max_streak = max(max_streak, current_streak)
        else:
            current_streak = 1
    
    return max_streak


def build_timeline(tweets, handle):
    """
    Build chronological timeline with bi-weekly view milestones
    """
    if not tweets:
        return []
    
    # Parse all tweets with dates
    dated_tweets = []
    for tweet in tweets:
        post_date = parse_tweet_date(tweet.get('created_at'))
        if post_date:
            views = int(tweet.get('views', 0) or 0)
            likes = int(tweet.get('favorites', 0) or tweet.get('favorite_count', 0) or 0)
            tweet_id = tweet.get('tweet_id') or tweet.get('id_str') or tweet.get('id', '')
            
            dated_tweets.append({
                "date": post_date,
                "views": views,
                "likes": likes,
                "text": tweet.get('text', '')[:100],
                "url": f"https://twitter.com/{handle}/status/{tweet_id}",
                "media": tweet.get("extracted_media")
            })
    
    if not dated_tweets:
        return []
    
    # Sort by date (oldest first)
    dated_tweets.sort(key=lambda x: x["date"])
    
    timeline_events = []
    
    # First post event
    first = dated_tweets[0]
    timeline_events.append({
        "type": "first_post",
        "date": first["date"].strftime('%B %d, %Y'),
        "timestamp": first["date"].isoformat(),
        "title": "🚀 Journey Started",
        "description": "Your first BULK post",
        "text": first["text"],
        "url": first["url"]
    })
    
    # Calculate bi-weekly cumulative views
    if len(dated_tweets) > 1:
        start_date = dated_tweets[0]["date"]
        end_date = dated_tweets[-1]["date"]
        
        # Group by 2-week periods
        current_period_start = start_date
        period_views = 0
        period_posts = 0
        
        biweekly_data = []
        
        for tweet in dated_tweets:
            # Check if we've moved to a new 2-week period
            days_diff = (tweet["date"] - current_period_start).days
            
            if days_diff >= 14:
                # Save current period
                if period_posts > 0:
                    biweekly_data.append({
                        "period_start": current_period_start,
                        "views": period_views,
                        "posts": period_posts
                    })
                
                # Start new period
                current_period_start = tweet["date"]
                period_views = tweet["views"]
                period_posts = 1
            else:
                period_views += tweet["views"]
                period_posts += 1
        
        # Don't forget last period
        if period_posts > 0:
            biweekly_data.append({
                "period_start": current_period_start,
                "views": period_views,
                "posts": period_posts
            })
        
        # Add significant milestones (view milestones)
        cumulative_views = 0
        view_milestones = [1000, 5000, 10000, 50000, 100000, 500000, 1000000]
        reached_milestones = set()
        
        for i, period in enumerate(biweekly_data):
            cumulative_views += period["views"]
            
            # Check for view milestones
            for milestone in view_milestones:
                if cumulative_views >= milestone and milestone not in reached_milestones:
                    reached_milestones.add(milestone)
                    timeline_events.append({
                        "type": "milestone",
                        "date": period["period_start"].strftime('%B %d, %Y'),
                        "timestamp": period["period_start"].isoformat(),
                        "title": f"🎯 {format_number(milestone)} Views!",
                        "description": f"Reached {format_number(milestone)} cumulative views",
                        "cumulative_views": cumulative_views
                    })
        
        # Add bi-weekly summary data for chart
        timeline_events.append({
            "type": "biweekly_chart",
            "data": [
                {
                    "period": p["period_start"].strftime('%b %d'),
                    "views": p["views"],
                    "posts": p["posts"]
                }
                for p in biweekly_data
            ]
        })
    
    # Find most viral post
    most_viral = max(dated_tweets, key=lambda x: x["views"])
    if most_viral["views"] > 0:
        timeline_events.append({
            "type": "viral",
            "date": most_viral["date"].strftime('%B %d, %Y'),
            "timestamp": most_viral["date"].isoformat(),
            "title": f"🔥 Viral Hit: {format_number(most_viral['views'])} views",
            "description": "Your most viewed BULK post",
            "text": most_viral["text"],
            "url": most_viral["url"],
            "media": most_viral["media"]
        })
    
    # Sort timeline by date
    timeline_events.sort(key=lambda x: x.get("timestamp", "9999"))
    
    return timeline_events


def format_number(num):
    """Format number with K/M suffix"""
    if num >= 1000000:
        return f"{num/1000000:.1f}M"
    if num >= 1000:
        return f"{num/1000:.1f}K"
    return str(num)


# Debug endpoints
@app.route('/api/test', methods=['GET'])
def test_api():
    if not RAPIDAPI_KEY:
        return jsonify({"error": "RAPIDAPI_KEY not set"}), 500
    return jsonify({"status": "API configured", "key_preview": RAPIDAPI_KEY[:10] + "..."})


@app.route('/api/test-user', methods=['GET'])
def test_user():
    handle = request.args.get('handle', 'bulktrade')
    user_info = fetch_user_profile(handle)
    if user_info:
        return jsonify({"success": True, "user": user_info})
    return jsonify({"error": "Failed to fetch user"}), 500


@app.route('/api/debug-tweets', methods=['GET'])
def debug_tweets():
    """
    Debug endpoint to see raw tweet structure - helps identify article fields
    """
    handle = request.args.get('handle', 'bulktrade')
    limit = int(request.args.get('limit', 5))
    
    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": RAPIDAPI_HOST
    }
    
    try:
        url = f"https://{RAPIDAPI_HOST}/timeline.php"
        response = requests.get(url, headers=headers, params={"screenname": handle}, timeout=15)
        
        if response.status_code != 200:
            return jsonify({"error": f"Failed to fetch @{handle}"}), 400
        
        data = response.json()
        tweets = data.get("timeline", [])[:limit]
        
        # Show full structure of each tweet
        debug_info = []
        for i, tweet in enumerate(tweets):
            # Get all keys in the tweet
            all_keys = list(tweet.keys())
            
            # Extract text from various possible fields
            extracted = {
                "text": tweet.get("text", "")[:200],
                "full_text": tweet.get("full_text", "")[:200] if tweet.get("full_text") else None,
                "note_tweet": tweet.get("note_tweet"),
                "article": tweet.get("article"),
                "twitter_article": tweet.get("twitter_article"),
                "quoted_tweet_text": (tweet.get("quoted_tweet") or {}).get("text", "")[:100] if tweet.get("quoted_tweet") else None,
                "card": tweet.get("card"),
                "url_card": tweet.get("url_card"),
                "entities_urls": tweet.get("entities", {}).get("urls", []),
            }
            
            # Check what we extract with our function
            full_text_extracted = get_full_tweet_text(tweet)
            
            # Check for article URLs and try to fetch
            article_content = check_and_fetch_article(tweet)
            
            debug_info.append({
                "index": i,
                "all_keys": all_keys,
                "extracted_fields": extracted,
                "full_text_combined": full_text_extracted[:500],
                "article_content_fetched": article_content[:500] if article_content else None,
                "is_bulk_related": "@bulktrade" in (full_text_extracted + (article_content or "")).lower() or "bulk" in (full_text_extracted + (article_content or "")).lower()
            })
        
        return jsonify({
            "handle": handle,
            "total_in_page": len(data.get("timeline", [])),
            "showing": len(debug_info),
            "tweets": debug_info
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/debug-article', methods=['GET'])
def debug_article():
    """
    Debug endpoint to test fetching a specific article URL
    """
    article_url = request.args.get('url', '')
    
    if not article_url:
        return jsonify({"error": "Provide ?url=<article_url>"}), 400
    
    try:
        content = fetch_article_content(article_url)
        return jsonify({
            "url": article_url,
            "content_found": content is not None,
            "content": content[:2000] if content else None,
            "content_length": len(content) if content else 0
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/debug-tweet', methods=['GET'])
def debug_single_tweet():
    """
    Debug endpoint to fetch a specific tweet by ID and see all its data
    """
    tweet_id = request.args.get('id', '')
    
    if not tweet_id:
        return jsonify({"error": "Provide ?id=<tweet_id>"}), 400
    
    # Extract tweet ID from URL if full URL provided
    if "status/" in tweet_id:
        tweet_id = tweet_id.split("status/")[-1].split("?")[0].split("/")[0]
    
    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": RAPIDAPI_HOST
    }
    
    try:
        # Try to get tweet details
        url = f"https://{RAPIDAPI_HOST}/tweet.php"
        response = requests.get(url, headers=headers, params={"id": tweet_id}, timeout=15)
        
        if response.status_code != 200:
            return jsonify({"error": f"Failed to fetch tweet {tweet_id}", "status": response.status_code}), 400
        
        data = response.json()
        
        # Get all keys
        all_keys = list(data.keys()) if isinstance(data, dict) else []
        
        # Get the FULL article field - this might have the content!
        article_field = data.get("article")
        initial_tweets = data.get("initial_tweets")
        
        # Try to extract article content if there's an article URL
        article_content_fetched = None
        article_urls = []
        
        urls = data.get("entities", {}).get("urls", [])
        for url_obj in urls:
            expanded = url_obj.get("expanded_url", "")
            if "/i/article/" in expanded or "/article/" in expanded:
                article_urls.append(expanded)
                # Try to fetch it
                content = fetch_article_content(expanded)
                if content:
                    article_content_fetched = content
        
        return jsonify({
            "tweet_id": tweet_id,
            "all_keys": all_keys,
            "text": data.get("text", "")[:500],
            "full_text": data.get("full_text"),
            "display_text": data.get("display_text"),
            "note_tweet": data.get("note_tweet"),
            "entities_urls": urls,
            "article_urls_found": article_urls,
            "article_field_from_api": article_field,  # FULL article data from RapidAPI
            "initial_tweets": initial_tweets,  # Thread/article initial content
            "article_content_fetched": article_content_fetched[:1000] if article_content_fetched else None,
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True, threaded=True)
