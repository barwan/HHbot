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
        new_posts = 0

        for feed_url in RSS_FEEDS:
            try:
                feed = feedparser.parse(feed_url)
                
                # Check for feed parsing errors
                if feed.bozo and isinstance(feed.bozo_exception, Exception):
                    print(f"Warning: Feed parsing error for {feed_url}: {feed.bozo_exception}")

                # Process entries in reverse (oldest to newest)
                for entry in reversed(feed.entries):
                    link = entry.get("link")

                    if not link:
                        continue
                    
                    # CRITICAL: Check if already posted BEFORE adding
                    if link in posted_links:
                        continue

                    title = entry.get("title", "New Post")
                    print(f"New post found: {title}")

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

                    # ADD TO POSTED LINKS AND SAVE BEFORE POSTING
                    posted_links.add(link)
                    save_posted_links(posted_links)

                    # Now send to Discord
                    await channel.send(embed=embed)
                    new_posts += 1
                    print(f"Posted: {title}")

            except Exception as e:
                await log_error(f"Error parsing feed {feed_url}: {str(e)}")

        if new_posts > 0:
            print(f"Feed check complete: {new_posts} new posts")

    except Exception as e:
        await log_error(f"Error in run_feeds: {str(e)}")

# =========================
# LOOP
# =========================

@tasks.loop(seconds=CHECK_INTERVAL)
async def check_feeds():
    await run_feeds()

# Track if task has been started to prevent multiple starts
task_started = False

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

    embed = discord.Embed(
        title="🏓 Pong!",
        color=discord.Color.blue()
    )
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
    """Manually trigger a feed check"""
    embed = discord.Embed(
        title="🔄 Checking feeds...",
        color=discord.Color.blue()
    )
    msg = await ctx.send(embed=embed)
    
    await run_feeds()
    
    embed = discord.Embed(
        title="✅ Feed check complete!",
        color=discord.Color.blue()
    )
    await msg.edit(embed=embed)


@bot.command()
async def stats(ctx):
    """Show number of posted links tracked"""
    embed = discord.Embed(
        title="📊 Bot Statistics",
        color=discord.Color.blue()
    )
    embed.add_field(name="Posts Tracked", value=str(len(posted_links)), inline=True)
    embed.add_field(name="Feeds Monitored", value=str(len(RSS_FEEDS)), inline=True)
    embed.add_field(name="Check Interval", value=f"{CHECK_INTERVAL}s", inline=True)
    
    await ctx.send(embed=embed)


@bot.command()
async def feeds(ctx):
    """Show all monitored RSS feeds"""
    embed = discord.Embed(
        title="📡 Monitored RSS Feeds",
        color=discord.Color.blue()
    )
    
    for i, feed_url in enumerate(RSS_FEEDS, 1):
        embed.add_field(name=f"Feed {i}", value=feed_url, inline=False)
    
    await ctx.send(embed=embed)


@bot.command()
async def demo(ctx):
    """Post a demo/test embed to show the bot is working"""
    demo_embed = discord.Embed(
        title="🤖 Demo Post - Bot is Working!",
        url="https://github.com",
        description="This is a test post from the RSS bot to verify everything is functioning correctly. The bot will post real news from RSS feeds to this channel.",
        color=discord.Color.blue()
    )
    
    demo_embed.add_field(
        name="📰 What This Bot Does",
        value="Monitors RSS feeds and posts new articles automatically.",
        inline=False
    )
    
    demo_embed.add_field(
        name="⏱️ Check Interval",
        value=f"Every {CHECK_INTERVAL} seconds",
        inline=True
    )
    
    demo_embed.add_field(
        name="📡 Feeds Monitored",
        value=f"{len(RSS_FEEDS)} feeds",
        inline=True
    )
    
    demo_embed.set_footer(text="✅ Bot is operational")
    
    await ctx.send(embed=demo_embed)
    print("Demo embed posted")


@bot.command()
async def clear(ctx):
    """Clear posted links history (⚠️ will cause spam on next restart!)"""
    embed = discord.Embed(
        title="⚠️ Warning",
        description="This will clear the posted links history. The bot may re-post old articles on the next feed check.\n\nReact with ✅ to confirm, or ❌ to cancel.",
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
            confirm_embed = discord.Embed(
                title="✅ Cleared",
                description="Posted links history has been cleared.",
                color=discord.Color.blue()
            )
            await msg.edit(embed=confirm_embed)
        else:
            cancel_embed = discord.Embed(
                title="❌ Cancelled",
                description="Clear operation cancelled.",
                color=discord.Color.blue()
            )
            await msg.edit(embed=cancel_embed)
    
    except:
        timeout_embed = discord.Embed(
            title="⏰ Timeout",
            description="Request timed out.",
            color=discord.Color.blue()
        )
        await msg.edit(embed=timeout_embed)


@bot.command()
async def about(ctx):
    """Show information about the bot"""
    embed = discord.Embed(
        title="ℹ️ About This Bot",
        description="A Discord bot that monitors RSS feeds and posts new articles to a channel.",
        color=discord.Color.blue()
    )
    embed.add_field(name="Purpose", value="Automatically share RSS feed updates", inline=False)
    embed.add_field(name="Current Feeds", value=str(len(RSS_FEEDS)), inline=True)
    embed.add_field(name="Posts Tracked", value=str(len(posted_links)), inline=True)
    embed.add_field(name="Uptime", value=f"{int((time.time() - start_time) / 3600)}h", inline=True)
    
    await ctx.send(embed=embed)


@bot.command()
async def helpbot(ctx):
    """Show available commands"""
    embed = discord.Embed(
        title="🤖 Available Commands",
        color=discord.Color.blue()
    )
    
    embed.add_field(name="!ping", value="Check bot latency", inline=False)
    embed.add_field(name="!uptime", value="Show how long bot has been running", inline=False)
    embed.add_field(name="!refresh", value="Manually check feeds now", inline=False)
    embed.add_field(name="!stats", value="Show bot statistics", inline=False)
    embed.add_field(name="!feeds", value="List all monitored RSS feeds", inline=False)
    embed.add_field(name="!demo", value="Post a demo/test message", inline=False)
    embed.add_field(name="!about", value="Show bot information", inline=False)
    embed.add_field(name="!clear", value="Clear posted links history (⚠️ warning)", inline=False)
    embed.add_field(name="!helpbot", value="Show this help message", inline=False)
    
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
    
    # Only start the task once to prevent spam from multiple on_ready calls
    if not task_started:
        check_feeds.start()
        task_started = True
        print("Feed checker started")
    else:
        print("Feed checker already running")

# =========================
# RUN
# =========================

bot.run(TOKEN)
