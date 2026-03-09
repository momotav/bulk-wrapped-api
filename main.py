"""
BULK Wrapped API - Speed Optimized for Railway (30s timeout)
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


@app.route('/api/ping', methods=['GET'])
def ping():
    """Health check"""
    return jsonify({"status": "ok", "message": "Server is running"})


@app.route('/api/wrapped', methods=['POST', 'OPTIONS'])
def get_wrapped():
    """
    Fetch user's @bulktrade mentions and calculate wrapped stats
    SPEED OPTIMIZED: 3 pages max, 8s timeout per request
    """
    if request.method == 'OPTIONS':
        return '', 204
    
    data = request.json or {}
    handle = data.get('handle', '').strip().replace('@', '')
    
    if not handle:
        return jsonify({"error": "Handle is required"}), 400
    
    if not RAPIDAPI_KEY:
        return jsonify({"error": "API not configured"}), 500
    
    try:
        # Fetch user profile (for PFP)
        user_info = fetch_user_profile(handle)
        
        # Fetch user's tweets (FAST: 3 pages, 8s timeout)
        tweets = fetch_user_tweets_fast(handle)
        
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
        
        # Add user profile info to stats
        stats["profile_image"] = user_info.get("profile_image") if user_info else None
        stats["display_name"] = user_info.get("name") if user_info else handle
        
        return jsonify({
            "success": True,
            "handle": handle,
            "total_tweets_scanned": len(tweets),
            "bulk_tweets_found": len(bulk_tweets),
            "stats": stats,
            "user": user_info
        })
        
    except Exception as e:
        print(f"Error fetching wrapped: {e}")
        return jsonify({"error": str(e)}), 500


def fetch_user_profile(handle):
    """Fetch user's profile info including PFP"""
    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": RAPIDAPI_HOST
    }
    
    try:
        url = f"https://{RAPIDAPI_HOST}/screenname.php"
        response = requests.get(url, headers=headers, params={"screenname": handle}, timeout=5)
        
        if response.status_code != 200:
            print(f"Failed to fetch profile: {response.status_code}")
            return None
        
        data = response.json()
        
        # Extract profile image - try different possible fields
        profile_image = (
            data.get("profile_image_url_https") or
            data.get("profile_image_url") or
            data.get("avatar") or
            data.get("profile_pic_url") or
            data.get("profile_image")
        )
        
        # Get higher resolution image (remove _normal suffix)
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
        print(f"Error fetching profile: {e}")
        return None


def fetch_user_tweets_fast(handle):
    """
    FAST version: Only 3 pages, 8s timeout per request
    Total max time: ~24 seconds (fits in Railway 30s limit)
    """
    all_tweets = []
    cursor = None
    max_pages = 3  # REDUCED from 5 to 3
    
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
        
        try:
            response = requests.get(url, headers=headers, params=params, timeout=8)  # 8s timeout
            
            if response.status_code != 200:
                print(f"API error: {response.status_code}")
                if page == 0:
                    raise Exception(f"Failed to fetch user @{handle}. They may not exist or have a private account.")
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
            print(f"Timeout on page {page + 1}, using what we have")
            break
        except Exception as e:
            print(f"Error on page {page + 1}: {e}")
            if page == 0:
                raise
            break
    
    print(f"Total tweets fetched: {len(all_tweets)}")
    return all_tweets


def filter_bulk_tweets(tweets):
    """
    Filter tweets related to BULK project.
    Rules:
    1. @bulktrade in text → count it
    2. "bulk" + context keyword → count it
    """
    bulk_tweets = []
    
    context_keywords = [
        "perp", "dex", "exchange", "trade", "long", "short",
        "liquidation", "decentralized", "trading", "community",
        "role", "og", "contributor", "@kdotcrypto", "@rizzy_sol",
        "@glowburger", "@junbug_sol", "bulkgram", "testnet"
    ]
    
    for tweet in tweets:
        text = tweet.get("text", "")
        text_lower = text.lower()
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
        
        # Rule 3: Check user_mentions for @bulktrade
        if not is_bulk_related:
            user_mentions = tweet.get("entities", {}).get("user_mentions", [])
            for mention in user_mentions:
                if mention.get("screen_name", "").lower() == "bulktrade":
                    is_bulk_related = True
                    break
        
        if is_bulk_related:
            tweet["extracted_media"] = extract_media_url(tweet)
            bulk_tweets.append(tweet)
    
    print(f"Found {len(bulk_tweets)} BULK-related tweets")
    return bulk_tweets


def extract_media_url(tweet):
    """Extract media URL from tweet"""
    media = tweet.get("media")
    
    # Handle dict format
    if isinstance(media, dict):
        photos = media.get("photo", [])
        if photos and len(photos) > 0:
            return photos[0].get("media_url_https") or photos[0].get("media_url")
        
        videos = media.get("video", [])
        if videos and len(videos) > 0:
            return videos[0].get("media_url_https") or videos[0].get("thumbnail_url")
    
    # Handle list format
    elif isinstance(media, list) and len(media) > 0:
        return media[0].get("media_url_https") or media[0].get("media_url")
    
    # Fallback: extended_entities
    ext_media = tweet.get("extended_entities", {}).get("media", [])
    if ext_media and len(ext_media) > 0:
        return ext_media[0].get("media_url_https")
    
    # Fallback: entities.media
    ent_media = tweet.get("entities", {}).get("media", [])
    if ent_media and len(ent_media) > 0:
        return ent_media[0].get("media_url_https")
    
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
        # Extract metrics
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
        
        # Get media
        media_url = tweet.get("extracted_media")
        
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
                if 'T' in str(created_at):
                    post_date = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                else:
                    post_date = datetime.strptime(created_at, '%a %b %d %H:%M:%S %z %Y')
                
                if first_post_date is None or post_date < first_post_date:
                    first_post_date = post_date
                    first_post = {
                        "text": tweet.get('text', '')[:280],
                        "date": created_at,
                        "url": tweet_url
                    }
                
                month_key = post_date.strftime('%Y-%m')
                posts_by_month[month_key] += 1
                
            except Exception as e:
                print(f"Date parse error: {e}")
    
    # Calculate posting streak
    streak = calculate_streak(posts_by_month)
    
    # Format first post date
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


# Debug endpoints
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
        url = f"https://{RAPIDAPI_HOST}/screenname.php"
        response = requests.get(url, headers=headers, params={"screenname": handle}, timeout=10)
        
        if response.status_code != 200:
            return jsonify({"error": f"API returned {response.status_code}"}), 500
        
        return jsonify({
            "success": True,
            "user": response.json()
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/test-one-page', methods=['GET'])
def test_one_page():
    """Test fetching just one page of tweets"""
    handle = request.args.get('handle', 'momotavrrr')
    
    if not RAPIDAPI_KEY:
        return jsonify({"error": "RAPIDAPI_KEY not set"}), 500
    
    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": RAPIDAPI_HOST
    }
    
    try:
        url = f"https://{RAPIDAPI_HOST}/timeline.php"
        response = requests.get(url, headers=headers, params={"screenname": handle}, timeout=10)
        
        if response.status_code == 429:
            return jsonify({"error": "Rate limited! Upgrade RapidAPI plan."}), 429
        
        if response.status_code != 200:
            return jsonify({"error": f"API returned {response.status_code}"}), 500
        
        data = response.json()
        timeline = data.get("timeline", [])
        
        return jsonify({
            "success": True,
            "tweets_found": len(timeline),
            "first_tweet": timeline[0].get("text", "")[:100] if timeline else None
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/debug-bulk', methods=['GET'])
def debug_bulk():
    """Debug endpoint to check bulk detection"""
    handle = request.args.get('handle', 'momotavrrr')
    
    if not RAPIDAPI_KEY:
        return jsonify({"error": "RAPIDAPI_KEY not set"}), 500
    
    try:
        # Fetch 2 pages only for debug
        all_tweets = []
        cursor = None
        
        headers = {
            "x-rapidapi-key": RAPIDAPI_KEY,
            "x-rapidapi-host": RAPIDAPI_HOST
        }
        
        for page in range(2):
            url = f"https://{RAPIDAPI_HOST}/timeline.php"
            params = {"screenname": handle}
            if cursor:
                params["cursor"] = cursor
            
            response = requests.get(url, headers=headers, params=params, timeout=10)
            if response.status_code != 200:
                break
            
            data = response.json()
            timeline = data.get("timeline", [])
            all_tweets.extend(timeline)
            cursor = data.get("next_cursor")
            if not cursor:
                break
        
        # Context keywords
        context_keywords = [
            "perp", "dex", "exchange", "trade", "long", "short",
            "liquidation", "decentralized", "trading", "community",
            "role", "og", "contributor", "@kdotcrypto", "@rizzy_sol",
            "@glowburger", "@junbug_sol"
        ]
        
        # Analyze each tweet
        results = []
        bulk_count = 0
        
        for tweet in all_tweets:
            text = tweet.get("text", "")
            text_lower = text.lower()
            
            has_bulktrade = "@bulktrade" in text_lower
            has_bulk_word = "bulk" in text_lower
            
            # Check user mentions
            user_mention = False
            user_mentions = tweet.get("entities", {}).get("user_mentions", [])
            for mention in user_mentions:
                if mention.get("screen_name", "").lower() == "bulktrade":
                    user_mention = True
                    break
            
            # Find context keyword
            found_context = None
            if has_bulk_word:
                for kw in context_keywords:
                    if kw in text_lower:
                        found_context = kw
                        break
            
            # Determine if bulk related
            is_bulk = has_bulktrade or user_mention or (has_bulk_word and found_context)
            
            if is_bulk:
                bulk_count += 1
            
            results.append({
                "text_preview": text[:120] + "..." if len(text) > 120 else text,
                "is_bulk_related": is_bulk if not found_context else found_context,
                "media_url": extract_media_url(tweet),
                "detected_by": {
                    "@bulktrade_in_text": has_bulktrade,
                    "bulk_word": has_bulk_word,
                    "context_keyword": found_context,
                    "user_mention": user_mention
                }
            })
        
        return jsonify({
            "success": True,
            "handle": handle,
            "total_scanned": len(all_tweets),
            "bulk_related_count": bulk_count,
            "context_keywords": context_keywords,
            "tweets": results
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
