import discord
from discord.ext import commands, tasks
import feedparser
from bs4 import BeautifulSoup
import time
import os
import json
from pathlib import Path

# =========================
# CONFIG
# =========================

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise ValueError("DISCORD_TOKEN is not set")

CHANNEL_ID = 1485298968404426802

RSS_FEEDS = [
    "https://www.sydsvenskan.se/feeds/section/lund/feed.xml",
    "https://fetchrss.com/feed/1wKfj4GZ41sg1wKfii1T22YU.rss",
    "https://lund.se/system/rss-skapare"
]

CHECK_INTERVAL = 60  # seconds
POSTED_LINKS_FILE = "posted_links.json"
MAX_POSTED_LINKS = 5000  # Prevent memory bloat from infinitely growing set

start_time = time.time()

# =========================
# DISCORD SETUP
# =========================

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Load posted links from file to prevent spam after restart
def load_posted_links():
    """Load previously posted links from file"""
    if Path(POSTED_LINKS_FILE).exists():
        try:
            with open(POSTED_LINKS_FILE, "r") as f:
                return set(json.load(f))
        except Exception as e:
            print(f"Warning: Could not load posted_links.json: {e}")
            return set()
    return set()

def save_posted_links(links):
    """Save posted links to file for persistence across restarts"""
    try:
        # Keep only the most recent links to prevent file from growing too large
        links_list = list(links)[-MAX_POSTED_LINKS:]
        with open(POSTED_LINKS_FILE, "w") as f:
            json.dump(links_list, f)
    except Exception as e:
        print(f"Warning: Could not save posted_links.json: {e}")

posted_links = load_posted_links()

# =========================
# ERROR LOGGING
# =========================

async def log_error(msg):
    try:
        channel = await bot.fetch_channel(CHANNEL_ID)
        await channel.send(f"⚠️ Error: {msg}")
    except Exception as e:
        print(f"Failed to send error log: {msg} | Exception: {e}")

# =========================
# RSS LOGIC
# =========================

async def get_image(entry):
    """Extract image URL from RSS entry with multiple fallback methods"""
    try:
        # 1. media_content (common RSS field)
        media = entry.get("media_content")
        if media and isinstance(media, list) and len(media) > 0:
            url = media[0].get("url")
            if url and url.startswith(("http://", "https://")):
                return url

        # 2. media_thumbnail (very common in news feeds)
        thumb = entry.get("media_thumbnail")
        if thumb and isinstance(thumb, list) and len(thumb) > 0:
            url = thumb[0].get("url")
            if url and url.startswith(("http://", "https://")):
                return url

        # 3. enclosures
        enclosures = entry.get("enclosures", [])
        for e in enclosures:
            if "image" in e.get("type", ""):
                url = e.get("href")
                if url and url.startswith(("http://", "https://")):
                    return url

        # 4. try HTML description
        description = entry.get("description", "")
        if description:
            soup = BeautifulSoup(description, "html.parser")
            img = soup.find("img")
            if img and img.get("src"):
                url = img["src"]
                # Handle relative URLs
                if url.startswith(("http://", "https://")):
                    return url

    except Exception as e:
        print(f"Warning: Error extracting image: {e}")
    
    return None

async def run_feeds():
    """Fetch all RSS feeds and post new entries to Discord"""
    try:
        channel = await bot.fetch_channel(CHANNEL_ID)

        for feed_url in RSS_FEEDS:
            try:
                feed = feedparser.parse(feed_url)
                
                # Check for feed parsing errors
                if feed.bozo and isinstance(feed.bozo_exception, Exception):
                    print(f"Warning: Feed parsing error for {feed_url}: {feed.bozo_exception}")

                # Process entries in reverse (oldest to newest)
                for entry in reversed(feed.entries):
                    link = entry.get("link")

                    if not link or link in posted_links:
                        continue

                    posted_links.add(link)
                    save_posted_links(posted_links)

                    title = entry.get("title", "New Post")

                    # Clean description
                    description = entry.get("description", "")
                    soup = BeautifulSoup(description, "html.parser")
                    clean_text = soup.get_text()[:2000]

                    image_url = await get_image(entry)

                    embed = discord.Embed(
                        title=title,
                        url=link,
                        description=clean_text,
                        color=discord.Color.blue()
                    )

                    if image_url:
                        embed.set_image(url=image_url)

                    await channel.send(embed=embed)
                    print(f"Posted: {title}")

            except Exception as e:
                await log_error(f"Error parsing feed {feed_url}: {str(e)}")

    except Exception as e:
        await log_error(f"Error in run_feeds: {str(e)}")

# =========================
# LOOP
# =========================

@tasks.loop(seconds=CHECK_INTERVAL)
async def check_feeds():
    await run_feeds()

# =========================
# COMMANDS
# =========================

@bot.command()
async def ping(ctx):
    """Ping command - shows API latency and message latency"""
    start = time.time()
    msg = await ctx.send("Pinging...")
    end = time.time()

    api_latency = round(bot.latency * 1000)
    msg_latency = round((end - start) * 1000)

    await msg.edit(content=f"🏓 Pong!\nAPI: {api_latency}ms\nMsg: {msg_latency}ms")


@bot.command()
async def uptime(ctx):
    """Show bot uptime"""
    seconds = int(time.time() - start_time)
    minutes = seconds // 60
    hours = minutes // 60

    await ctx.send(f"⏱️ Uptime: {hours}h {minutes%60}m {seconds%60}s")


@bot.command()
async def refresh(ctx):
    """Manually trigger a feed check"""
    await ctx.send("🔄 Checking feeds...")
    await run_feeds()
    await ctx.send("✅ Done!")


@bot.command()
async def helpbot(ctx):
    """Show available commands"""
    await ctx.send("""
🤖 Commands:
!ping     - Check bot latency
!uptime   - Show how long bot has been running
!refresh  - Manually check feeds now
!helpbot  - Show this help message
""")


@bot.command()
async def stats(ctx):
    """Show number of posted links tracked"""
    await ctx.send(f"📊 Tracking {len(posted_links)} posted links")

# =========================
# EVENTS
# =========================

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    print(f"Loaded {len(posted_links)} previously posted links")
    print(f"Monitoring {len(RSS_FEEDS)} RSS feeds")
    check_feeds.start()

# =========================
# RUN
# =========================

bot.run(TOKEN)
