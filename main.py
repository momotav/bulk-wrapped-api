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
    Filter tweets that mention @bulktrade and extract media
    """
    bulk_tweets = []
    
    for tweet in tweets:
        text = tweet.get("text", "").lower()
        
        # Check if tweet mentions @bulktrade
        if "@bulktrade" in text or "bulktrade" in text:
            # Extract media URL
            media_url = extract_media_url(tweet)
            tweet["extracted_media"] = media_url
            
            # Check if it's an article (long-form content)
            tweet["is_article"] = check_if_article(tweet)
            
            bulk_tweets.append(tweet)
    
    print(f"Found {len(bulk_tweets)} tweets mentioning @bulktrade")
    return bulk_tweets


def extract_media_url(tweet):
    """
    Extract the best media URL from a tweet
    """
    media_url = None
    
    # Try different locations where media might be
    # 1. Direct media object
    media = tweet.get("media", {})
    if media:
        if isinstance(media, dict):
            if "photo" in media and media["photo"]:
                media_url = media["photo"][0].get("media_url_https")
            elif "video" in media and media["video"]:
                media_url = media["video"][0].get("media_url_https") or media["video"][0].get("thumbnail_url")
        elif isinstance(media, list) and media:
            media_url = media[0].get("media_url_https")
    
    # 2. Extended entities
    if not media_url:
        extended = tweet.get("extended_entities", {}) or tweet.get("entities", {})
        if extended:
            media_list = extended.get("media", [])
            if media_list:
                media_url = media_list[0].get("media_url_https")
    
    # 3. Media URL directly on tweet
    if not media_url:
        media_url = tweet.get("media_url") or tweet.get("media_url_https")
    
    # 4. Check for card/preview image (for articles/links)
    if not media_url:
        card = tweet.get("card", {}) or tweet.get("quoted_status", {})
        if card:
            media_url = card.get("thumbnail_image_url") or card.get("media_url_https")
    
    # 5. Try attachments
    if not media_url:
        attachments = tweet.get("attachments", {})
        if attachments:
            media_keys = attachments.get("media_keys", [])
            if media_keys:
                includes = tweet.get("includes", {})
                media_list = includes.get("media", [])
                for m in media_list:
                    if m.get("media_key") in media_keys:
                        media_url = m.get("url") or m.get("preview_image_url")
                        break
    
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


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
