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


@app.route('/api/debug-search', methods=['GET'])
def debug_search():
    """Debug endpoint to test search API directly"""
    handle = request.args.get('handle', '').strip().replace('@', '')
    pages = int(request.args.get('pages', 10))
    
    if not handle:
        return jsonify({"error": "Handle required"}), 400
    
    try:
        search_tweets = search_bulk_mentions(handle, max_pages=pages)
        
        # Get info from results
        tweets_info = []
        for tweet in search_tweets:
            tweets_info.append({
                "id": tweet.get('tweet_id') or tweet.get('id_str'),
                "date": tweet.get('created_at'),
                "text": tweet.get('text', '')[:100]
            })
        
        # Sort by date to find oldest
        sorted_tweets = sorted(tweets_info, key=lambda x: x['date'] if x['date'] else '')
        
        return jsonify({
            "handle": handle,
            "pages_searched": pages,
            "total_results": len(search_tweets),
            "oldest_tweet": sorted_tweets[0] if sorted_tweets else None,
            "newest_tweet": sorted_tweets[-1] if sorted_tweets else None,
            "first_10_tweets": tweets_info[:10]
        })
        
    except Exception as e:
        return jsonify({
            "error": str(e)
        })


@app.route('/api/debug-vip', methods=['GET'])
def debug_vip():
    """Debug endpoint to verify VIP config is deployed"""
    handle = request.args.get('handle', '').strip().replace('@', '').lower()
    vip_handles = ['kdotcrypto', 'rizzy_sol', 'junbug_sol', 'glowburger', 'bulktrade']
    is_vip = handle in vip_handles
    max_pages = 150 if is_vip else 50
    return jsonify({
        "handle": handle,
        "is_vip": is_vip,
        "max_pages": max_pages,
        "vip_handles": vip_handles,
        "version": "v3_search_enabled"
    })




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
            
            # VIP handles get more pages to find older tweets (back to May 2024)
            vip_handles = ['kdotcrypto', 'rizzy_sol', 'junbug_sol', 'glowburger', 'bulktrade']
            max_pages = 150 if handle.lower() in vip_handles else 50
            
            headers = {
                "x-rapidapi-key": RAPIDAPI_KEY,
                "x-rapidapi-host": RAPIDAPI_HOST
            }
            
            for page in range(max_pages):
                progress = 5 + int((page / max_pages) * 75)  # 5-80%
                vip_note = " (deep scan)" if handle.lower() in vip_handles else ""
                yield f"data: {json.dumps({'step': 'scanning', 'message': f'Scanning page {page + 1}/{max_pages}{vip_note}...', 'progress': progress, 'tweets_found': len(all_tweets)})}\n\n"
                
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
            
            # Step 2b: For VIP users, also search for @bulktrade mentions to find older tweets
            if handle.lower() in vip_handles:
                yield f"data: {json.dumps({'step': 'searching', 'message': 'Searching for older @bulktrade mentions...', 'progress': 82})}\n\n"
                search_tweets = search_bulk_mentions(handle, max_pages=100)
                if search_tweets:
                    original_count = len(all_tweets)
                    all_tweets = merge_tweets(all_tweets, search_tweets)
                    new_found = len(all_tweets) - original_count
                    yield f"data: {json.dumps({'step': 'searching', 'message': f'Found {new_found} additional tweets from search ({len(search_tweets)} total searched)', 'progress': 84})}\n\n"
                else:
                    yield f"data: {json.dumps({'step': 'searching', 'message': 'No additional tweets found from search', 'progress': 84})}\n\n"
            
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
    
    # VIP handles get more pages to find older tweets
    vip_handles = ['kdotcrypto', 'rizzy_sol', 'junbug_sol', 'glowburger', 'bulktrade']
    max_pages = 150 if handle.lower() in vip_handles else 50
    
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


def search_bulk_mentions(handle, max_pages=20):
    """
    Search for @bulktrade mentions from a specific user.
    This can find older tweets that timeline pagination doesn't reach.
    """
    all_tweets = []
    cursor = None
    
    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": RAPIDAPI_HOST
    }
    
    # Search query: @bulktrade from the user
    search_query = f"@bulktrade from:{handle}"
    
    for page in range(max_pages):
        url = f"https://{RAPIDAPI_HOST}/search.php"
        params = {
            "query": search_query,
            "search_type": "Latest"
        }
        
        if cursor:
            params["cursor"] = cursor
        
        try:
            response = requests.get(url, headers=headers, params=params, timeout=15)
            
            if response.status_code != 200:
                print(f"Search API error: {response.status_code}")
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
            print(f"Search timeout at page {page}")
            break
        except Exception as e:
            print(f"Search error: {e}")
            break
    
    print(f"Search found {len(all_tweets)} @bulktrade mentions from {handle}")
    return all_tweets


def merge_tweets(timeline_tweets, search_tweets):
    """
    Merge tweets from timeline and search, removing duplicates by tweet_id.
    """
    seen_ids = set()
    merged = []
    
    for tweet in timeline_tweets + search_tweets:
        tweet_id = tweet.get('tweet_id') or tweet.get('id_str') or tweet.get('id', '')
        if tweet_id and tweet_id not in seen_ids:
            seen_ids.add(tweet_id)
            merged.append(tweet)
    
    return merged


def filter_bulk_tweets(tweets):
    """
    Filter tweets related to BULK project.
    Rules:
    1. @bulktrade in text → count it
    2. "bulk" or "gbulk" + context keyword → count it
    3. "gbulk" alone → count it (gBULK token)
    4. Check quoted tweets, articles, notes for keywords
    
    Note: Article content is extracted from tweet.article.full_text by get_full_tweet_text()
    For article tweets, we fetch full data to get accurate stats.
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
        # Check if this is an article tweet - if so, fetch full data for stats
        tweet = enrich_article_tweet(tweet)
        
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


def enrich_article_tweet(tweet):
    """
    If tweet is an article (has /i/article/ URL), ALWAYS fetch full tweet data
    to get accurate stats (views, likes, etc.) since timeline.php may have incomplete data
    """
    # Check if it's an article tweet
    urls = tweet.get("entities", {}).get("urls", [])
    is_article = False
    for url_obj in urls:
        expanded = url_obj.get("expanded_url", "") or ""
        if "/i/article/" in expanded:
            is_article = True
            break
    
    # Also check text for article URL
    text = tweet.get("text", "") or ""
    if "/i/article/" in text:
        is_article = True
    
    if not is_article:
        return tweet
    
    # ALWAYS fetch full tweet data for articles
    tweet_id = tweet.get('tweet_id') or tweet.get('id_str') or tweet.get('id', '')
    if not tweet_id:
        return tweet
    
    try:
        full_tweet = fetch_single_tweet(tweet_id)
        if full_tweet:
            # Merge the full data into our tweet
            for key, value in full_tweet.items():
                if value is not None and value != '':
                    tweet[key] = value
            print(f"Enriched article tweet {tweet_id}: views={tweet.get('views')}, likes={tweet.get('likes')}, favorites={tweet.get('favorites')}")
    except Exception as e:
        print(f"Failed to enrich article tweet {tweet_id}: {e}")
    
    return tweet


def fetch_single_tweet(tweet_id):
    """Fetch full data for a single tweet using tweet.php endpoint"""
    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": RAPIDAPI_HOST
    }
    
    try:
        url = f"https://{RAPIDAPI_HOST}/tweet.php"
        response = requests.get(url, headers=headers, params={"id": tweet_id}, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            
            # Check for various error indicators
            if data is None:
                return None
            if isinstance(data, dict):
                # API returns error field for deleted/unavailable tweets
                if data.get('error') or data.get('errors'):
                    print(f"Tweet {tweet_id} unavailable: {data.get('error') or data.get('errors')}")
                    return None
                # Check if essential fields are missing (indicates bad data)
                if not data.get('text') and not data.get('full_text'):
                    print(f"Tweet {tweet_id} has no text content, may be deleted")
                    return None
            
            return data
        return None
    except Exception as e:
        print(f"Error fetching tweet {tweet_id}: {e}")
        return None


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
    """Extract media URL from tweet, including article cover images"""
    
    # Check article cover image first (for Twitter articles)
    article = tweet.get("article")
    if isinstance(article, dict):
        cover = article.get("cover_media")
        if cover:
            return cover
    
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


def safe_int(value):
    """Safely convert a value to int, handling strings and None"""
    if value is None:
        return 0
    try:
        # Handle string numbers like "96" or "7.5K"
        if isinstance(value, str):
            value = value.strip().lower()
            if not value:
                return 0
            # Handle K/M suffixes
            if value.endswith('k'):
                return int(float(value[:-1]) * 1000)
            elif value.endswith('m'):
                return int(float(value[:-1]) * 1000000)
            else:
                return int(float(value))
        return int(value)
    except (ValueError, TypeError):
        return 0


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
    
    # Collect all tweets with parsed dates for first_post selection
    tweets_with_dates = []
    
    posts_by_month = defaultdict(int)
    
    for tweet in tweets:
        # Extract stats - check multiple possible field names
        # API sometimes returns these as strings, so convert safely
        views = safe_int(tweet.get('views') or tweet.get('view_count') or 0)
        likes = safe_int(tweet.get('likes') or tweet.get('favorites') or tweet.get('favorite_count') or 0)
        retweets = safe_int(tweet.get('retweets') or tweet.get('retweet_count') or 0)
        replies = safe_int(tweet.get('replies') or tweet.get('reply_count') or 0)
        
        total_views += views
        total_likes += likes
        total_retweets += retweets
        total_replies += replies
        
        tweet_id = tweet.get('tweet_id') or tweet.get('id_str') or tweet.get('id', '')
        tweet_url = f"https://twitter.com/{handle}/status/{tweet_id}"
        
        # For articles, try to get the cover image
        article = tweet.get('article') or {}
        article_cover = article.get('cover_media') if isinstance(article, dict) else None
        media_url = tweet.get("extracted_media") or article_cover
        
        # For article tweets, get the title for display
        article_title = article.get('title', '') if isinstance(article, dict) else ''
        display_text = article_title if article_title else tweet.get('text', '')[:280]
        
        if views > max_views:
            max_views = views
            most_viral_post = {
                "text": display_text,
                "views": views,
                "likes": likes,
                "url": tweet_url,
                "date": tweet.get('created_at', ''),
                "media": media_url
            }
        
        if likes > max_likes:
            max_likes = likes
            most_liked_post = {
                "text": display_text,
                "views": views,
                "likes": likes,
                "url": tweet_url,
                "date": tweet.get('created_at', ''),
                "media": media_url
            }
        
        created_at = tweet.get('created_at', '')
        post_date = parse_tweet_date(created_at)
        
        if post_date:
            # Store tweet data for first_post selection
            tweets_with_dates.append({
                "tweet": tweet,
                "post_date": post_date,
                "display_text": display_text,
                "views": views,
                "likes": likes,
                "tweet_url": tweet_url,
                "media_url": media_url,
                "created_at": created_at,
                "tweet_id": tweet_id
            })
            
            month_key = post_date.strftime('%Y-%m')
            posts_by_month[month_key] += 1
    
    # Sort by date (oldest first) and find the first valid tweet
    tweets_with_dates.sort(key=lambda x: x["post_date"])
    
    first_post = None
    first_post_date = None
    
    # Try oldest tweets until we find one that exists
    for candidate in tweets_with_dates[:5]:  # Check up to 5 oldest tweets
        tweet_id = candidate["tweet_id"]
        
        # Try to fetch the tweet to verify it exists
        try:
            full_tweet = fetch_single_tweet(tweet_id)
            
            # Check if tweet was deleted/unavailable
            if full_tweet is None or full_tweet.get('error'):
                print(f"First post candidate {tweet_id} appears deleted, trying next...")
                continue
            
            # Tweet exists! Use it
            enriched_views = safe_int(full_tweet.get('views') or full_tweet.get('view_count') or candidate["views"])
            enriched_likes = safe_int(full_tweet.get('likes') or full_tweet.get('favorites') or full_tweet.get('favorite_count') or candidate["likes"])
            
            # Get media from full tweet if missing
            media = candidate["media_url"]
            if not media:
                article = full_tweet.get('article') or {}
                media = article.get('cover_media') if isinstance(article, dict) else None
            
            first_post = {
                "text": candidate["display_text"],
                "date": candidate["created_at"],
                "url": candidate["tweet_url"],
                "views": enriched_views,
                "likes": enriched_likes,
                "media": media
            }
            first_post_date = candidate["post_date"]
            print(f"Found valid first post {tweet_id}: views={enriched_views}, likes={enriched_likes}")
            break
            
        except Exception as e:
            print(f"Error checking first post candidate {tweet_id}: {e}")
            continue
    
    # Fallback: if no valid tweet found via API, use the oldest from timeline
    if first_post is None and tweets_with_dates:
        candidate = tweets_with_dates[0]
        first_post = {
            "text": candidate["display_text"],
            "date": candidate["created_at"],
            "url": candidate["tweet_url"],
            "views": candidate["views"],
            "likes": candidate["likes"],
            "media": candidate["media_url"]
        }
        first_post_date = candidate["post_date"]
        print(f"Using fallback first post (couldn't verify via API)")
    
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
            views = safe_int(tweet.get('views') or tweet.get('view_count') or 0)
            likes = safe_int(tweet.get('likes') or tweet.get('favorites') or tweet.get('favorite_count') or 0)
            tweet_id = tweet.get('tweet_id') or tweet.get('id_str') or tweet.get('id', '')
            
            # For articles, get cover image and title
            article = tweet.get('article') or {}
            article_cover = article.get('cover_media') if isinstance(article, dict) else None
            article_title = article.get('title', '') if isinstance(article, dict) else ''
            
            display_text = article_title if article_title else tweet.get('text', '')[:100]
            media_url = tweet.get("extracted_media") or article_cover
            
            dated_tweets.append({
                "date": post_date,
                "views": views,
                "likes": likes,
                "text": display_text,
                "url": f"https://twitter.com/{handle}/status/{tweet_id}",
                "media": media_url
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


@app.route('/api/debug-wrapped', methods=['GET'])
def debug_wrapped():
    """
    Debug endpoint that shows exactly what happens during wrapped generation
    Specifically tracks article tweets through the entire flow
    """
    handle = request.args.get('handle', '')
    
    if not handle:
        return jsonify({"error": "Provide ?handle=<username>"}), 400
    
    handle = handle.strip().replace('@', '')
    
    try:
        # Step 1: Fetch some tweets
        tweets = fetch_user_tweets_debug(handle, max_pages=10)
        
        # Step 2: Track article tweets before filtering
        article_tweets_before = []
        for tweet in tweets:
            urls = tweet.get("entities", {}).get("urls", [])
            for url_obj in urls:
                expanded = url_obj.get("expanded_url", "") or ""
                if "/i/article/" in expanded:
                    article_tweets_before.append({
                        "tweet_id": tweet.get("tweet_id") or tweet.get("id"),
                        "views_before": tweet.get("views"),
                        "likes_before": tweet.get("likes"),
                        "favorites_before": tweet.get("favorites"),
                        "has_article_field": "article" in tweet and tweet.get("article") is not None,
                    })
                    break
        
        # Step 3: Filter tweets (this calls enrich_article_tweet)
        bulk_tweets = filter_bulk_tweets(tweets)
        
        # Step 4: Track article tweets after filtering/enriching
        article_tweets_after = []
        for tweet in bulk_tweets:
            urls = tweet.get("entities", {}).get("urls", [])
            for url_obj in urls:
                expanded = url_obj.get("expanded_url", "") or ""
                if "/i/article/" in expanded:
                    article_tweets_after.append({
                        "tweet_id": tweet.get("tweet_id") or tweet.get("id"),
                        "views_after": tweet.get("views"),
                        "likes_after": tweet.get("likes"),
                        "favorites_after": tweet.get("favorites"),
                        "has_article_field": "article" in tweet and tweet.get("article") is not None,
                        "article_title": (tweet.get("article") or {}).get("title"),
                    })
                    break
        
        # Step 5: Calculate stats
        stats = calculate_wrapped_stats(bulk_tweets, handle)
        
        return jsonify({
            "handle": handle,
            "total_tweets_scanned": len(tweets),
            "bulk_tweets_found": len(bulk_tweets),
            "article_tweets_before_filter": article_tweets_before,
            "article_tweets_after_filter_and_enrich": article_tweets_after,
            "most_viral_post": stats.get("most_viral_post"),
            "most_liked_post": stats.get("most_liked_post"),
            "first_post": stats.get("first_post"),
            "first_post_date": stats.get("first_post_date"),
            "total_views": stats.get("total_views"),
            "total_likes": stats.get("total_likes"),
        })
        
    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500


def fetch_user_tweets_debug(handle, max_pages=10):
    """Fetch user tweets for debugging - limited pages"""
    all_tweets = []
    cursor = None
    
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
                break
            
            data = response.json()
            timeline = data.get("timeline", [])
            
            if not timeline:
                break
            
            all_tweets.extend(timeline)
            cursor = data.get("next_cursor")
            
            if not cursor:
                break
                
        except Exception as e:
            print(f"Error fetching page {page}: {e}")
            break
    
    return all_tweets


@app.route('/api/debug-timeline', methods=['GET'])
def debug_timeline():
    """
    Debug endpoint to see what timeline.php returns for a user's tweets
    Specifically looking for article tweets and their data structure
    """
    handle = request.args.get('handle', '')
    
    if not handle:
        return jsonify({"error": "Provide ?handle=<username>"}), 400
    
    handle = handle.strip().replace('@', '')
    
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
        tweets = data.get("timeline", [])
        
        # Find article tweets
        article_tweets = []
        for i, tweet in enumerate(tweets[:50]):  # Check first 50
            urls = tweet.get("entities", {}).get("urls", [])
            has_article_url = False
            article_url = None
            
            for url_obj in urls:
                expanded = url_obj.get("expanded_url", "") or ""
                if "/i/article/" in expanded:
                    has_article_url = True
                    article_url = expanded
                    break
            
            # Also check if text contains article URL pattern
            text = tweet.get("text", "")
            if "/i/article/" in text or "x.com/i/article" in text.lower():
                has_article_url = True
            
            if has_article_url:
                article_tweets.append({
                    "index": i,
                    "tweet_id": tweet.get("tweet_id") or tweet.get("id"),
                    "text": tweet.get("text", "")[:100],
                    "views_from_timeline": tweet.get("views"),
                    "likes_from_timeline": tweet.get("likes") or tweet.get("favorites"),
                    "has_article_field": "article" in tweet,
                    "article_field": tweet.get("article"),
                    "article_url": article_url,
                    "all_keys": list(tweet.keys())
                })
        
        return jsonify({
            "handle": handle,
            "total_tweets_in_page": len(tweets),
            "article_tweets_found": len(article_tweets),
            "article_tweets": article_tweets
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
