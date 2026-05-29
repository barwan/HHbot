import discord
from discord.ext import commands, tasks
import feedparser
from bs4 import BeautifulSoup
import time
import os
import json
from pathlib import Path
import random
import asyncio
from datetime import datetime, timedelta
import aiohttp

# =========================
# CONFIG & CONSTANTS
# =========================

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise ValueError("DISCORD_TOKEN is not set")

CHANNEL_ID = 1485298968404426802
CHECK_INTERVAL = 60
POSTED_LINKS_FILE = "posted_links.json"
MAX_POSTED_LINKS = 5000
MAX_FEED_TIMEOUT = 5  # seconds per feed
FEED_CACHE_TIME = 30  # Cache feeds for 30 seconds

RSS_FEEDS = [
    "https://www.sydsvenskan.se/feeds/section/lund/feed.xml",
    "https://fetchrss.com/feed/1wKfj4GZ41sg1wKfii1T22YU.rss",
    "https://lund.se/system/rss-skapare",
    "https://fetchrss.com/feed/1wKfj4GZ41sg1wScna6Pg6Ec.rss",
    "https://fetchrss.com/feed/1wKfj4GZ41sg1wScpJARnB4U.rss"
]

# Cache
feed_cache = {}
last_feed_check = {}
channel_cache = {}

start_time = time.time()

# =========================
# DISCORD SETUP
# =========================

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Load posted links efficiently
def load_posted_links():
    """Load previously posted links from file"""
    try:
        if Path(POSTED_LINKS_FILE).exists():
            with open(POSTED_LINKS_FILE, "r") as f:
                return set(json.load(f))
    except Exception as e:
        print(f"Warning: Could not load posted_links.json: {e}")
    return set()

def save_posted_links(links):
    """Save posted links to file with optimization"""
    try:
        links_list = list(links)[-MAX_POSTED_LINKS:]
        with open(POSTED_LINKS_FILE, "w") as f:
            json.dump(links_list, f)
    except Exception as e:
        print(f"Warning: Could not save posted_links.json: {e}")

posted_links = load_posted_links()
task_started = False

# =========================
# ASYNC UTILITIES
# =========================

async def get_cached_feed(feed_url):
    """Get feed with caching to avoid redundant requests"""
    now = time.time()
    
    if feed_url in feed_cache:
        cached_time, cached_feed = feed_cache[feed_url]
        if now - cached_time < FEED_CACHE_TIME:
            return cached_feed
    
    try:
        # Use timeout to prevent hanging feeds
        feed = await asyncio.wait_for(
            asyncio.to_thread(feedparser.parse, feed_url),
            timeout=MAX_FEED_TIMEOUT
        )
        feed_cache[feed_url] = (now, feed)
        return feed
    except asyncio.TimeoutError:
        print(f"Feed timeout: {feed_url}")
        return None
    except Exception as e:
        print(f"Feed error: {e}")
        return None

async def get_channel():
    """Cache channel reference"""
    if CHANNEL_ID not in channel_cache:
        channel_cache[CHANNEL_ID] = await bot.fetch_channel(CHANNEL_ID)
    return channel_cache[CHANNEL_ID]

async def log_error(msg):
    """Async error logging"""
    try:
        channel = await get_channel()
        await channel.send(f"⚠️ Error: {msg}")
    except Exception as e:
        print(f"Failed to send error log: {msg} | Exception: {e}")

# =========================
# IMAGE EXTRACTION (OPTIMIZED)
# =========================

async def get_image(entry):
    """Extract image URL with early returns and validation"""
    try:
        # 1. media_content
        media = entry.get("media_content")
        if media and isinstance(media, list) and len(media) > 0:
            url = media[0].get("url")
            if url and url.startswith(("http://", "https://")):
                return url

        # 2. media_thumbnail
        thumb = entry.get("media_thumbnail")
        if thumb and isinstance(thumb, list) and len(thumb) > 0:
            url = thumb[0].get("url")
            if url and url.startswith(("http://", "https://")):
                return url

        # 3. enclosures
        for e in entry.get("enclosures", []):
            if "image" in e.get("type", ""):
                url = e.get("href")
                if url and url.startswith(("http://", "https://")):
                    return url

        # 4. HTML description (only if needed)
        description = entry.get("description", "")
        if description:
            try:
                soup = BeautifulSoup(description, "html.parser")
                img = soup.find("img")
                if img and img.get("src"):
                    url = img["src"]
                    if url.startswith(("http://", "https://")):
                        return url
            except:
                pass

    except Exception as e:
        print(f"Warning: Error extracting image: {e}")
    
    return None

# =========================
# FEED PROCESSING (OPTIMIZED)
# =========================

async def process_feed(feed_url, idx):
    """Process a single feed asynchronously"""
    feed = await get_cached_feed(feed_url)
    
    if not feed or not feed.entries:
        return 0
    
    channel = await get_channel()
    new_posts = 0
    
    # Reverse iterate for chronological order
    for entry in reversed(feed.entries):
        link = entry.get("link")
        
        if not link or link in posted_links:
            continue
        
        # Fast path: check if in set before processing
        posted_links.add(link)
        
        try:
            title = entry.get("title", "New Post")
            
            # Efficient description cleaning
            description = entry.get("description", "")
            if description:
                soup = BeautifulSoup(description, "html.parser")
                clean_text = soup.get_text()[:2000]
            else:
                clean_text = ""
            
            image_url = await get_image(entry)
            
            # Build embed
            embed = discord.Embed(
                title=title,
                url=link,
                description=clean_text,
                color=discord.Color.blue()
            )
            
            if image_url:
                embed.set_image(url=image_url)
            
            # Send and save together
            await channel.send(embed=embed)
            new_posts += 1
            print(f"Posted: {title}")
            
        except Exception as e:
            print(f"Error posting article: {e}")
    
    return new_posts

async def run_feeds():
    """Fetch all RSS feeds in parallel (optimized)"""
    try:
        print(f"Starting feed check at {datetime.now().strftime('%H:%M:%S')}")
        
        # Process all feeds in parallel instead of sequentially
        tasks_list = [
            process_feed(feed_url, idx) 
            for idx, feed_url in enumerate(RSS_FEEDS, 1)
        ]
        
        results = await asyncio.gather(*tasks_list, return_exceptions=True)
        
        # Count results
        total_new = sum(r for r in results if isinstance(r, int))
        failed = sum(1 for r in results if isinstance(r, Exception))
        
        if total_new > 0:
            print(f"Feed check complete: {total_new} new posts")
        
        # Save only once at the end
        save_posted_links(posted_links)
        
    except Exception as e:
        error_str = str(e)
        if "503" not in error_str and "connect" not in error_str.lower():
            await log_error(f"Error in run_feeds: {error_str}")

# =========================
# BACKGROUND TASK
# =========================

@tasks.loop(seconds=CHECK_INTERVAL)
async def check_feeds():
    await run_feeds()

# =========================
# OPTIMIZED COMMANDS
# =========================

@bot.command()
async def ping(ctx):
    """Ping - shows latency"""
    start = time.time()
    msg = await ctx.send("Pinging...")
    end = time.time()

    api_latency = round(bot.latency * 1000)
    msg_latency = round((end - start) * 1000)

    embed = discord.Embed(title="🏓 Pong!", color=discord.Color.blue())
    embed.add_field(name="API Latency", value=f"{api_latency}ms", inline=True)
    embed.add_field(name="Message Latency", value=f"{msg_latency}ms", inline=True)

    await msg.edit(embed=embed)

@bot.command()
async def uptime(ctx):
    """Show bot uptime"""
    seconds = int(time.time() - start_time)
    minutes = seconds // 60
    hours = minutes // 60

    embed = discord.Embed(
        title="⏱️ Bot Uptime",
        description=f"{hours}h {minutes%60}m {seconds%60}s",
        color=discord.Color.blue()
    )
    await ctx.send(embed=embed)

@bot.command()
async def refresh(ctx):
    """Manually check feeds"""
    embed = discord.Embed(title="🔄 Checking feeds...", color=discord.Color.blue())
    msg = await ctx.send(embed=embed)
    
    await run_feeds()
    
    embed = discord.Embed(title="✅ Feed check complete!", color=discord.Color.blue())
    await msg.edit(embed=embed)

@bot.command()
async def stats(ctx):
    """Show statistics"""
    embed = discord.Embed(title="📊 Bot Statistics", color=discord.Color.blue())
    embed.add_field(name="Posts Tracked", value=str(len(posted_links)), inline=True)
    embed.add_field(name="Feeds Monitored", value=str(len(RSS_FEEDS)), inline=True)
    embed.add_field(name="Check Interval", value=f"{CHECK_INTERVAL}s", inline=True)
    await ctx.send(embed=embed)

@bot.command()
async def feeds(ctx):
    """Show all feeds"""
    embed = discord.Embed(title="📡 Monitored RSS Feeds", color=discord.Color.blue())
    
    for i, feed_url in enumerate(RSS_FEEDS, 1):
        display_url = feed_url if len(feed_url) < 70 else feed_url[:67] + "..."
        embed.add_field(name=f"Feed {i} 📰", value=display_url, inline=False)
    
    embed.set_footer(text=f"Total feeds: {len(RSS_FEEDS)}")
    await ctx.send(embed=embed)

@bot.command()
async def feedinfo(ctx):
    """Show detailed feed info"""
    embed = discord.Embed(title="📊 Feed Information", color=discord.Color.blue())
    
    for i, feed_url in enumerate(RSS_FEEDS, 1):
        try:
            feed = await get_cached_feed(feed_url)
            if feed and feed.entries:
                entry_count = len(feed.entries)
                status = f"✅ {entry_count} entries"
            else:
                status = "⚠️ No entries"
            
            embed.add_field(
                name=f"Feed {i}",
                value=f"{status}\n{feed_url[:60]}...",
                inline=False
            )
        except Exception as e:
            embed.add_field(
                name=f"Feed {i}",
                value=f"❌ Error\n{feed_url[:60]}...",
                inline=False
            )
    
    await ctx.send(embed=embed)

@bot.command()
async def status(ctx):
    """Show bot status"""
    embed = discord.Embed(title="🟢 Bot Status", color=discord.Color.blue())
    embed.add_field(name="Running", value="✅ Yes", inline=True)
    embed.add_field(name="Checking Feeds", value="✅ Active", inline=True)
    embed.add_field(name="Uptime", value=f"{int((time.time() - start_time) / 3600)}h", inline=True)
    embed.add_field(name="Posts Tracked", value=str(len(posted_links)), inline=True)
    embed.add_field(name="Feeds Active", value=str(len(RSS_FEEDS)), inline=True)
    embed.add_field(name="Check Interval", value=f"{CHECK_INTERVAL}s", inline=True)
    
    await ctx.send(embed=embed)

@bot.command()
async def health(ctx):
    """Health check all feeds"""
    embed = discord.Embed(title="💚 Bot Health Check", color=discord.Color.blue())
    
    healthy_feeds = 0
    
    for i, feed_url in enumerate(RSS_FEEDS, 1):
        try:
            feed = await get_cached_feed(feed_url)
            if feed and feed.entries and len(feed.entries) > 0:
                healthy_feeds += 1
                status = "✅ OK"
            else:
                status = "⚠️ Empty"
        except Exception as e:
            status = f"❌ Error"
        
        embed.add_field(name=f"Feed {i}", value=status, inline=True)
    
    overall = f"{healthy_feeds}/{len(RSS_FEEDS)} feeds healthy"
    embed.add_field(name="Overall Status", value=overall, inline=False)
    embed.add_field(name="Bot Response", value="✅ Responsive", inline=False)
    
    await ctx.send(embed=embed)

@bot.command()
async def settings(ctx):
    """Show bot settings"""
    embed = discord.Embed(title="⚙️ Bot Settings", color=discord.Color.blue())
    embed.add_field(name="Check Interval", value=f"{CHECK_INTERVAL} seconds", inline=False)
    embed.add_field(name="Feed Timeout", value=f"{MAX_FEED_TIMEOUT} seconds", inline=False)
    embed.add_field(name="Cache Time", value=f"{FEED_CACHE_TIME} seconds", inline=False)
    embed.add_field(name="Max Tracked", value=f"{MAX_POSTED_LINKS} links", inline=False)
    embed.add_field(name="Feed Count", value=str(len(RSS_FEEDS)), inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def history(ctx):
    """Show activity"""
    embed = discord.Embed(title="📜 Recent Activity", color=discord.Color.blue())
    uptime_seconds = int(time.time() - start_time)
    uptime_hours = uptime_seconds // 3600
    
    embed.add_field(name="Bot Started", value=f"{uptime_hours} hours ago", inline=False)
    embed.add_field(name="Posts Tracked", value=str(len(posted_links)), inline=True)
    embed.add_field(name="Feeds Monitored", value=str(len(RSS_FEEDS)), inline=True)
    await ctx.send(embed=embed)

@bot.command()
async def about(ctx):
    """About the bot"""
    embed = discord.Embed(
        title="ℹ️ About This Bot",
        description="A high-performance Discord bot that monitors RSS feeds.",
        color=discord.Color.blue()
    )
    embed.add_field(name="Purpose", value="Automatically share RSS feed updates", inline=False)
    embed.add_field(name="Current Feeds", value=str(len(RSS_FEEDS)), inline=True)
    embed.add_field(name="Posts Tracked", value=str(len(posted_links)), inline=True)
    embed.add_field(name="Uptime", value=f"{int((time.time() - start_time) / 3600)}h", inline=True)
    await ctx.send(embed=embed)

@bot.command()
async def version(ctx):
    """Bot version"""
    embed = discord.Embed(title="ℹ️ Bot Version", color=discord.Color.blue())
    embed.add_field(name="Bot Name", value="RSS Feed Monitor", inline=False)
    embed.add_field(name="Version", value="3.0 (Optimized)", inline=False)
    embed.add_field(name="Features", value="• Async Feed Processing\n• Feed Caching\n• Parallel Tasks\n• Optimized Storage", inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def demo(ctx):
    """Demo message"""
    embed = discord.Embed(
        title="🤖 Demo Post - Bot is Working!",
        url="https://github.com",
        description="Test post from the optimized RSS bot.",
        color=discord.Color.blue()
    )
    embed.add_field(name="📰 Features", value="Fast, efficient feed monitoring", inline=False)
    embed.add_field(name="⏱️ Check Interval", value=f"{CHECK_INTERVAL}s", inline=True)
    embed.add_field(name="📡 Feeds", value=str(len(RSS_FEEDS)), inline=True)
    embed.set_footer(text="✅ Bot is operational")
    await ctx.send(embed=embed)

@bot.command()
async def clear(ctx):
    """Clear posted links (⚠️)"""
    embed = discord.Embed(
        title="⚠️ Warning",
        description="React ✅ to confirm, ❌ to cancel",
        color=discord.Color.blue()
    )
    msg = await ctx.send(embed=embed)
    
    await msg.add_reaction("✅")
    await msg.add_reaction("❌")
    
    def check(reaction, user):
        return user == ctx.author and str(reaction.emoji) in ["✅", "❌"]
    
    try:
        reaction, user = await bot.wait_for("reaction_add", timeout=30.0, check=check)
        
        if str(reaction.emoji) == "✅":
            posted_links.clear()
            save_posted_links(posted_links)
            embed = discord.Embed(title="✅ Cleared", color=discord.Color.blue())
            await msg.edit(embed=embed)
        else:
            embed = discord.Embed(title="❌ Cancelled", color=discord.Color.blue())
            await msg.edit(embed=embed)
    except:
        embed = discord.Embed(title="⏰ Timeout", color=discord.Color.blue())
        await msg.edit(embed=embed)

# =========================
# GAMES (OPTIMIZED)
# =========================

@bot.command()
async def rps(ctx, choice=None):
    """Rock Paper Scissors"""
    if not choice or choice.lower() not in ["rock", "paper", "scissors"]:
        embed = discord.Embed(title="🎮 Rock Paper Scissors", description="Usage: `!rps rock/paper/scissors`", color=discord.Color.blue())
        await ctx.send(embed=embed)
        return
    
    choice = choice.lower()
    bot_choice = random.choice(["rock", "paper", "scissors"])
    
    # Determine winner efficiently
    wins = {("rock", "scissors"), ("paper", "rock"), ("scissors", "paper")}
    
    if choice == bot_choice:
        result, color = "🤝 Tie!", discord.Color.blue()
    elif (choice, bot_choice) in wins:
        result, color = "🎉 You Win!", discord.Color.green()
    else:
        result, color = "🤖 Bot Wins!", discord.Color.red()
    
    embed = discord.Embed(title="🎮 Rock Paper Scissors", color=color)
    embed.add_field(name="Your Choice", value=f"✋ {choice.capitalize()}", inline=True)
    embed.add_field(name="Bot's Choice", value=f"✋ {bot_choice.capitalize()}", inline=True)
    embed.add_field(name="Result", value=result, inline=False)
    
    await ctx.send(embed=embed)

@bot.command()
async def coin(ctx):
    """Flip a coin"""
    result = random.choice(["Heads", "Tails"])
    embed = discord.Embed(title="🪙 Coin Flip", description=f"🪙 **{result}**", color=discord.Color.blue())
    await ctx.send(embed=embed)

@bot.command()
async def dice(ctx, sides=6):
    """Roll a dice"""
    sides = min(max(sides, 2), 100)
    result = random.randint(1, sides)
    embed = discord.Embed(title="🎲 Dice Roll", color=discord.Color.blue())
    embed.add_field(name=f"D{sides}", value=f"**{result}**", inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def eightball(ctx, *, question=None):
    """Magic 8-ball"""
    if not question:
        embed = discord.Embed(title="🎱 Magic 8-Ball", description="Usage: `!eightball Your question`", color=discord.Color.blue())
        await ctx.send(embed=embed)
        return
    
    answers = ["✅ Yes, definitely!", "✅ It is certain.", "✅ Absolutely!", "❓ Maybe, ask again later.", "❓ Cannot predict now.", "❌ No, definitely not.", "❌ Don't count on it.", "❌ Very doubtful."]
    
    embed = discord.Embed(title="🎱 Magic 8-Ball", color=discord.Color.blue())
    embed.add_field(name="Question", value=question, inline=False)
    embed.add_field(name="Answer", value=random.choice(answers), inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def guess(ctx):
    """Number guessing game"""
    secret = random.randint(1, 100)
    embed = discord.Embed(title="🎯 Number Guessing Game", description="Guess a number 1-100. Reply with your guess!", color=discord.Color.blue())
    await ctx.send(embed=embed)
    
    def check(msg):
        return msg.author == ctx.author and msg.channel == ctx.channel
    
    for attempt in range(7):
        try:
            guess_msg = await bot.wait_for("message", timeout=30.0, check=check)
            try:
                guess_num = int(guess_msg.content)
            except ValueError:
                await ctx.send(embed=discord.Embed(title="🎯 Invalid", description="Enter a number!", color=discord.Color.blue()))
                continue
            
            if guess_num == secret:
                embed = discord.Embed(title="🎉 You Won!", description=f"Number was **{secret}**!\nAttempts: **{attempt + 1}**", color=discord.Color.green())
                await ctx.send(embed=embed)
                return
            
            remaining = 7 - attempt - 1
            feedback = f"{'🔼 Too Low!' if guess_num < secret else '🔽 Too High!'}\nAttempts left: {remaining}"
            await ctx.send(embed=discord.Embed(title="🎯 Try Again", description=feedback, color=discord.Color.blue()))
        except:
            break
    
    embed = discord.Embed(title="😔 Game Over!", description=f"Number was **{secret}**!", color=discord.Color.red())
    await ctx.send(embed=embed)

@bot.command()
async def games(ctx):
    """Show games"""
    embed = discord.Embed(title="🎮 Available Games", color=discord.Color.blue())
    embed.add_field(name="!rps <choice>", value="Rock Paper Scissors", inline=False)
    embed.add_field(name="!coin", value="Coin Flip", inline=False)
    embed.add_field(name="!dice [sides]", value="Dice Roll", inline=False)
    embed.add_field(name="!eightball <question>", value="Magic 8-Ball", inline=False)
    embed.add_field(name="!guess", value="Number Guessing (1-100)", inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def helpbot(ctx):
    """Show help"""
    embed = discord.Embed(title="🤖 RSS Bot - Commands", color=discord.Color.blue())
    
    embed.add_field(name="📡 FEEDS", value="!refresh • !feeds • !feedinfo", inline=False)
    embed.add_field(name="📊 INFO", value="!status • !stats • !health • !history • !settings • !about", inline=False)
    embed.add_field(name="⚙️ BASIC", value="!ping • !uptime • !version", inline=False)
    embed.add_field(name="🛠️ UTILITY", value="!demo • !clear", inline=False)
    embed.add_field(name="🎮 GAMES", value="!rps • !coin • !dice • !eightball • !guess • !games", inline=False)
    
    await ctx.send(embed=embed)

# =========================
# EVENTS
# =========================

@bot.event
async def on_ready():
    global task_started
    print(f"Logged in as {bot.user}")
    print(f"Loaded {len(posted_links)} previously posted links")
    print(f"Monitoring {len(RSS_FEEDS)} RSS feeds")
    
    if not task_started:
        check_feeds.start()
        task_started = True
        print("Feed checker started")

# =========================
# RUN
# =========================

bot.run(TOKEN)
