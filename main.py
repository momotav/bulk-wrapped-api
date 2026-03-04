"""
BULK Wrapped API - Fetches Twitter data via Apify and calculates wrapped stats
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import requests
from datetime import datetime
from collections import defaultdict

app = Flask(__name__)
CORS(app)

# Apify configuration
APIFY_TOKEN = os.environ.get("APIFY_TOKEN", "")
APIFY_ACTOR_ID = "61RPP7dywgiy0JPD0"  # Tweet Scraper V2

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
    
    if not APIFY_TOKEN:
        return jsonify({"error": "API not configured"}), 500
    
    try:
        # Call Apify to fetch user's tweets mentioning @bulktrade
        tweets = fetch_user_bulk_tweets(handle)
        
        if not tweets:
            return jsonify({
                "error": "No BULK-related posts found",
                "handle": handle,
                "found": False
            }), 404
        
        # Calculate wrapped stats
        stats = calculate_wrapped_stats(tweets, handle)
        
        return jsonify({
            "success": True,
            "handle": handle,
            "stats": stats
        })
        
    except Exception as e:
        print(f"Error fetching wrapped: {e}")
        return jsonify({"error": str(e)}), 500


def fetch_user_bulk_tweets(handle):
    """
    Use Apify Tweet Scraper V2 to search for user's tweets mentioning @bulktrade
    """
    
    # Search query: tweets from user mentioning @bulktrade
    search_query = f"from:{handle} @bulktrade"
    
    # Apify Actor run endpoint
    url = f"https://api.apify.com/v2/acts/{APIFY_ACTOR_ID}/run-sync-get-dataset-items"
    
    payload = {
        "searchTerms": [search_query],
        "maxTweets": 500,  # Get up to 500 tweets
        "sort": "Latest"
    }
    
    headers = {
        "Content-Type": "application/json"
    }
    
    params = {
        "token": APIFY_TOKEN
    }
    
    print(f"Fetching tweets for @{handle} mentioning @bulktrade...")
    
    response = requests.post(url, json=payload, headers=headers, params=params, timeout=300)
    
    if response.status_code != 200:
        print(f"Apify error: {response.status_code} - {response.text}")
        raise Exception(f"Failed to fetch tweets: {response.status_code}")
    
    tweets = response.json()
    print(f"Found {len(tweets)} tweets")
    
    return tweets


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
        # Extract metrics (field names may vary based on Apify response)
        views = tweet.get('viewCount') or tweet.get('views') or 0
        likes = tweet.get('likeCount') or tweet.get('likes') or tweet.get('favoriteCount') or 0
        retweets = tweet.get('retweetCount') or tweet.get('retweets') or 0
        replies = tweet.get('replyCount') or tweet.get('replies') or 0
        
        total_views += views
        total_likes += likes
        total_retweets += retweets
        total_replies += replies
        
        # Track most viral (by views)
        if views > max_views:
            max_views = views
            most_viral_post = {
                "text": tweet.get('text') or tweet.get('full_text') or '',
                "views": views,
                "likes": likes,
                "url": tweet.get('url') or tweet.get('tweetUrl') or '',
                "date": tweet.get('createdAt') or tweet.get('created_at') or ''
            }
        
        # Track most liked
        if likes > max_likes:
            max_likes = likes
            most_liked_post = {
                "text": tweet.get('text') or tweet.get('full_text') or '',
                "views": views,
                "likes": likes,
                "url": tweet.get('url') or tweet.get('tweetUrl') or '',
                "date": tweet.get('createdAt') or tweet.get('created_at') or ''
            }
        
        # Track first post
        created_at = tweet.get('createdAt') or tweet.get('created_at') or ''
        if created_at:
            try:
                # Try parsing date
                if 'T' in str(created_at):
                    post_date = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                else:
                    post_date = datetime.strptime(created_at, '%a %b %d %H:%M:%S +0000 %Y')
                
                if first_post_date is None or post_date < first_post_date:
                    first_post_date = post_date
                    first_post = {
                        "text": tweet.get('text') or tweet.get('full_text') or '',
                        "date": created_at,
                        "url": tweet.get('url') or tweet.get('tweetUrl') or ''
                    }
                
                # Count by month
                month_key = post_date.strftime('%Y-%m')
                posts_by_month[month_key] += 1
                
            except Exception as e:
                print(f"Date parse error: {e}")
    
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
    
    # Sort months
    sorted_months = sorted(posts_by_month.keys())
    
    if len(sorted_months) <= 1:
        return len(sorted_months)
    
    max_streak = 1
    current_streak = 1
    
    for i in range(1, len(sorted_months)):
        prev_year, prev_month = map(int, sorted_months[i-1].split('-'))
        curr_year, curr_month = map(int, sorted_months[i].split('-'))
        
        # Check if consecutive month
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
    """Test endpoint to verify Apify connection"""
    if not APIFY_TOKEN:
        return jsonify({"error": "APIFY_TOKEN not set"}), 500
    
    return jsonify({
        "status": "API configured",
        "token_set": bool(APIFY_TOKEN)
    })


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
