"""
BULK Wrapped API - Fetches Twitter data via RapidAPI Twitter API45
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import requests
from datetime import datetime
from collections import defaultdict

app = Flask(__name__)
CORS(app)

# RapidAPI configuration
RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY", "")
RAPIDAPI_HOST = "twitter-api45.p.rapidapi.com"

@app.route('/')
def home():
    return jsonify({"status": "BULK Wrapped API is running"})


@app.route('/api/wrapped', methods=['POST'])
def get_wrapped():
    """
    Fetch user's @bulktrade mentions and calculate wrapped stats
    """
    data = request.json
    handle = data.get('handle', '').strip().replace('@', '')
    
    if not handle:
        return jsonify({"error": "Handle is required"}), 400
    
    if not RAPIDAPI_KEY:
        return jsonify({"error": "API not configured"}), 500
    
    try:
        # Fetch user's tweets
        tweets = fetch_user_tweets(handle)
        
        # Filter for @bulktrade mentions
        bulk_tweets = filter_bulk_tweets(tweets)
        
        if not bulk_tweets:
            return jsonify({
                "error": "No BULK-related posts found for @" + handle,
                "handle": handle,
                "total_tweets_scanned": len(tweets),
                "found": False
            }), 404
        
        # Calculate wrapped stats
        stats = calculate_wrapped_stats(bulk_tweets, handle)
        
        return jsonify({
            "success": True,
            "handle": handle,
            "total_tweets_scanned": len(tweets),
            "bulk_tweets_found": len(bulk_tweets),
            "stats": stats
        })
        
    except Exception as e:
        print(f"Error fetching wrapped: {e}")
        return jsonify({"error": str(e)}), 500


def fetch_user_tweets(handle):
    """
    Fetch user's timeline using RapidAPI Twitter API45
    """
    all_tweets = []
    cursor = None
    max_pages = 5  # Limit to 5 pages (~100 tweets) for speed
    
    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": RAPIDAPI_HOST
    }
    
    for page in range(max_pages):
        url = f"https://{RAPIDAPI_HOST}/timeline.php"
        params = {"screenname": handle}
        
        if cursor:
            params["cursor"] = cursor
        
        print(f"Fetching page {page + 1} for @{handle}...")
        
        response = requests.get(url, headers=headers, params=params, timeout=30)
        
        if response.status_code != 200:
            print(f"API error: {response.status_code} - {response.text}")
            if page == 0:
                raise Exception(f"Failed to fetch user @{handle}. They may not exist or have a private account.")
            break
        
        data = response.json()
        
        # Extract tweets from response
        timeline = data.get("timeline", [])
        if not timeline:
            break
        
        all_tweets.extend(timeline)
        
        # Get cursor for next page
        cursor = data.get("next_cursor")
        if not cursor:
            break
    
    print(f"Total tweets fetched: {len(all_tweets)}")
    return all_tweets


def filter_bulk_tweets(tweets):
    """
    Filter tweets that are related to BULK project.
    
    Rules:
    1. If tweet contains @bulktrade → count it
    2. If tweet contains "bulk" AND one of the context keywords → count it
    """
    bulk_tweets = []
    
    # Context keywords that confirm "bulk" is about the BULK project
    context_keywords = [
        "perp",
        "dex", 
        "exchange",
        "trade",
        "long",
        "short",
        "liquidation",
        "decentralized",
        "trading",
        "community",
        "role",
        "og",
        "contributor",
        "@kdotcrypto",
        "@rizzy_sol",
        "@glowburger",
        "@junbug_sol"
        "testnet"
        "mainnet"
    ]
    
    for tweet in tweets:
        text = tweet.get("text", "")
        text_lower = text.lower()
        is_bulk_related = False
        
        # Rule 1: Direct @bulktrade mention (in text or user_mentions)
        if "@bulktrade" in text_lower:
            is_bulk_related = True
        
        # Rule 2: "bulk" + context keyword
        if not is_bulk_related and "bulk" in text_lower:
            for keyword in context_keywords:
                if keyword in text_lower:
                    is_bulk_related = True
                    break
        
        # Rule 3: Check user_mentions for @bulktrade
        if not is_bulk_related:
            is_bulk_related = check_user_mentions(tweet)
        
        if is_bulk_related:
            # Extract media URL
            media_url = extract_media_url(tweet)
            tweet["extracted_media"] = media_url
            tweet["is_article"] = check_if_article(tweet)
            bulk_tweets.append(tweet)
    
    print(f"Found {len(bulk_tweets)} BULK-related tweets")
    return bulk_tweets


def check_photo_tags(tweet):
    """
    Check if @bulktrade is tagged in any photos
    """
    # Check media for tagged users
    media = tweet.get("media", {})
    
    # Could be dict or list
    if isinstance(media, dict):
        media_items = []
        if "photo" in media:
            media_items.extend(media.get("photo", []))
        if "video" in media:
            media_items.extend(media.get("video", []))
    elif isinstance(media, list):
        media_items = media
    else:
        media_items = []
    
    for item in media_items:
        # Check tagged_users / features / tags
        tagged_users = item.get("tagged_users", [])
        for user in tagged_users:
            screen_name = user.get("screen_name", "").lower()
            if screen_name == "bulktrade":
                return True
        
        # Check features.all.tags
        features = item.get("features", {})
        all_features = features.get("all", {})
        tags = all_features.get("tags", [])
        for tag in tags:
            screen_name = tag.get("screen_name", "").lower()
            if screen_name == "bulktrade":
                return True
        
        # Check ext_media_availability or other fields
        faces = item.get("faces", [])
        for face in faces:
            if face.get("screen_name", "").lower() == "bulktrade":
                return True
    
    # Check extended_entities
    extended = tweet.get("extended_entities", {})
    ext_media = extended.get("media", [])
    for item in ext_media:
        # Check features
        features = item.get("features", {})
        if features:
            for size_key in ["large", "medium", "small", "orig", "all"]:
                size_features = features.get(size_key, {})
                faces = size_features.get("faces", [])
                for face in faces:
                    if face.get("screen_name", "").lower() == "bulktrade":
                        return True
        
        # Direct tagged users on media item
        tagged = item.get("tagged_users", []) or item.get("tags", [])
        for user in tagged:
            if isinstance(user, dict):
                screen_name = user.get("screen_name", "") or user.get("name", "")
                if screen_name.lower() == "bulktrade":
                    return True
            elif isinstance(user, str):
                if user.lower() == "bulktrade":
                    return True
    
    return False


def check_user_mentions(tweet):
    """
    Check user_mentions in entities for @bulktrade
    """
    entities = tweet.get("entities", {})
    user_mentions = entities.get("user_mentions", [])
    
    for mention in user_mentions:
        screen_name = mention.get("screen_name", "").lower()
        if screen_name == "bulktrade":
            return True
    
    # Also check in extended_entities
    extended = tweet.get("extended_entities", {})
    ext_mentions = extended.get("user_mentions", [])
    
    for mention in ext_mentions:
        screen_name = mention.get("screen_name", "").lower()
        if screen_name == "bulktrade":
            return True
    
    return False


def extract_media_url(tweet):
    """
    Extract the best media URL from a tweet
    """
    media_url = None
    
    # Primary location: media.photo[]
    media = tweet.get("media", {})
    
    if isinstance(media, dict):
        # Check photo array
        photos = media.get("photo", [])
        if photos and len(photos) > 0:
            media_url = photos[0].get("media_url_https")
        
        # Check video array
        if not media_url:
            videos = media.get("video", [])
            if videos and len(videos) > 0:
                media_url = videos[0].get("media_url_https") or videos[0].get("thumbnail_url")
    
    elif isinstance(media, list) and len(media) > 0:
        media_url = media[0].get("media_url_https")
    
    # Fallback: extended_entities
    if not media_url:
        extended = tweet.get("extended_entities", {})
        if extended:
            ext_media = extended.get("media", [])
            if ext_media and len(ext_media) > 0:
                media_url = ext_media[0].get("media_url_https")
    
    # Fallback: entities.media
    if not media_url:
        entities = tweet.get("entities", {})
        if entities:
            ent_media = entities.get("media", [])
            if ent_media and len(ent_media) > 0:
                media_url = ent_media[0].get("media_url_https")
    
    return media_url


def check_if_article(tweet):
    """
    Check if tweet is a Twitter article (long-form content)
    """
    text = tweet.get("text", "")
    
    # Articles often have these indicators
    if "article" in text.lower():
        return True
    
    # Check for card type
    card = tweet.get("card", {})
    if card:
        card_type = card.get("type", "")
        if "article" in card_type.lower():
            return True
    
    # Check URL for article pattern
    urls = tweet.get("entities", {}).get("urls", [])
    for url in urls:
        expanded = url.get("expanded_url", "")
        if "/i/articles/" in expanded or "twitter.com/i/article" in expanded:
            return True
    
    return False


def calculate_wrapped_stats(tweets, handle):
    """
    Calculate all the wrapped statistics from tweets
    """
    
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
        # Extract metrics
        views = int(tweet.get('views', 0) or 0)
        likes = int(tweet.get('favorites', 0) or tweet.get('favorite_count', 0) or 0)
        retweets = int(tweet.get('retweets', 0) or tweet.get('retweet_count', 0) or 0)
        replies = int(tweet.get('replies', 0) or tweet.get('reply_count', 0) or 0)
        
        total_views += views
        total_likes += likes
        total_retweets += retweets
        total_replies += replies
        
        tweet_url = f"https://twitter.com/{handle}/status/{tweet.get('tweet_id', tweet.get('id', ''))}"
        media_url = tweet.get('extracted_media')
        
        # Track most viral (by views)
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
        
        # Track most liked
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
        
        # Track first post
        created_at = tweet.get('created_at', '')
        if created_at:
            try:
                # Parse Twitter date format
                if 'T' in str(created_at):
                    post_date = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                else:
                    # Format: "Wed Oct 10 20:19:24 +0000 2018"
                    post_date = datetime.strptime(created_at, '%a %b %d %H:%M:%S %z %Y')
                
                if first_post_date is None or post_date < first_post_date:
                    first_post_date = post_date
                    first_post = {
                        "text": tweet.get('text', '')[:280],
                        "date": created_at,
                        "url": tweet_url
                    }
                
                # Count by month
                month_key = post_date.strftime('%Y-%m')
                posts_by_month[month_key] += 1
                
            except Exception as e:
                print(f"Date parse error: {e} - {created_at}")
    
    # Calculate posting streak (consecutive months)
    streak = calculate_streak(posts_by_month)
    
    # Format first post date nicely
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
    """
    Calculate the longest consecutive month posting streak
    """
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


@app.route('/api/test', methods=['GET'])
def test_api():
    """Test endpoint to verify API connection"""
    if not RAPIDAPI_KEY:
        return jsonify({"error": "RAPIDAPI_KEY not set"}), 500
    
    return jsonify({
        "status": "API configured",
        "key_set": bool(RAPIDAPI_KEY),
        "key_preview": RAPIDAPI_KEY[:10] + "..." if RAPIDAPI_KEY else None
    })


@app.route('/api/test-user', methods=['GET'])
def test_user():
    """Test fetching a user's info"""
    handle = request.args.get('handle', 'bulktrade')
    
    if not RAPIDAPI_KEY:
        return jsonify({"error": "RAPIDAPI_KEY not set"}), 500
    
    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": RAPIDAPI_HOST
    }
    
    try:
        # Get user info
        url = f"https://{RAPIDAPI_HOST}/screenname.php"
        response = requests.get(url, headers=headers, params={"screenname": handle}, timeout=15)
        
        if response.status_code != 200:
            return jsonify({"error": f"API returned {response.status_code}"}), 500
        
        return jsonify({
            "success": True,
            "user": response.json()
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/debug-tweets', methods=['GET'])
def debug_tweets():
    """Debug endpoint to see raw tweet structure"""
    handle = request.args.get('handle', 'momotavrrr')
    
    if not RAPIDAPI_KEY:
        return jsonify({"error": "RAPIDAPI_KEY not set"}), 500
    
    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": RAPIDAPI_HOST
    }
    
    try:
        url = f"https://{RAPIDAPI_HOST}/timeline.php"
        response = requests.get(url, headers=headers, params={"screenname": handle}, timeout=30)
        
        if response.status_code != 200:
            return jsonify({"error": f"API returned {response.status_code}"}), 500
        
        data = response.json()
        timeline = data.get("timeline", [])
        
        # Find tweets with media
        tweets_with_media = []
        for tweet in timeline[:10]:
            has_media = bool(tweet.get("media")) or bool(tweet.get("extended_entities", {}).get("media"))
            tweets_with_media.append({
                "text": tweet.get("text", "")[:100],
                "has_media": has_media,
                "media_field": tweet.get("media"),
                "extended_entities": tweet.get("extended_entities"),
                "entities": tweet.get("entities"),
                "all_keys": list(tweet.keys())
            })
        
        return jsonify({
            "success": True,
            "total_tweets": len(timeline),
            "sample_tweets": tweets_with_media
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/debug-bulk', methods=['GET'])
def debug_bulk():
    """Debug endpoint to see which posts are detected as BULK-related"""
    handle = request.args.get('handle', 'momotavrrr')
    
    if not RAPIDAPI_KEY:
        return jsonify({"error": "RAPIDAPI_KEY not set"}), 500
    
    try:
        # Fetch tweets
        tweets = fetch_user_tweets(handle)
        
        # Context keywords
        context_keywords = [
            "perp", "dex", "exchange", "trade", "long", "short",
            "liquidation", "decentralized", "trading", "community",
            "role", "og", "contributor", "@kdotcrypto", "@rizzy_sol",
            "@glowburger", "@junbug_sol"
        ]
        
        # Analyze each tweet
        results = []
        for tweet in tweets[:50]:
            text = tweet.get("text", "")
            text_lower = text.lower()
            
            # Check @bulktrade
            has_at_bulktrade = "@bulktrade" in text_lower
            
            # Check "bulk" + context
            has_bulk_word = "bulk" in text_lower
            matched_context = None
            if has_bulk_word and not has_at_bulktrade:
                for kw in context_keywords:
                    if kw in text_lower:
                        matched_context = kw
                        break
            
            # Check user_mentions
            entities = tweet.get("entities", {})
            user_mentions = entities.get("user_mentions", [])
            mention_names = [m.get("screen_name", "").lower() for m in user_mentions]
            mentions_has_bulk = "bulktrade" in mention_names
            
            # Determine if BULK related
            is_bulk = has_at_bulktrade or (has_bulk_word and matched_context) or mentions_has_bulk
            
            results.append({
                "text_preview": text[:120] + "..." if len(text) > 120 else text,
                "detected_by": {
                    "@bulktrade_in_text": has_at_bulktrade,
                    "bulk_word": has_bulk_word,
                    "context_keyword": matched_context,
                    "user_mention": mentions_has_bulk
                },
                "is_bulk_related": is_bulk,
                "media_url": extract_media_url(tweet)
            })
        
        bulk_count = sum(1 for r in results if r["is_bulk_related"])
        
        return jsonify({
            "success": True,
            "handle": handle,
            "total_scanned": len(results),
            "bulk_related_count": bulk_count,
            "context_keywords": context_keywords,
            "tweets": results
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
