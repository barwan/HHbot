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
import urllib.request
import urllib.error
import gc
import sys

# =========================
# CONFIG 
# =========================

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise ValueError("DISCORD_TOKEN is not set")

CHANNEL_ID = 1485298968404426802

# LOW RESOURCE SETTINGS
CHECK_INTERVAL = 120  # Check every 2 minutes instead of 1 (halves CPU/memory usage)
POSTED_LINKS_FILE = "posted_links.json"
MAX_POSTED_LINKS = 1000  # Reduced from 5000 to save memory
FEED_CACHE_TIME = 60  # Longer cache to reduce parsing
MAX_FEED_TIMEOUT = 8
MAX_RETRIES = 2  # Reduced from 3
SOCKET_TIMEOUT = 12

# Memory optimization
MAX_CACHED_FEEDS = 3  # Only cache last 3 feeds
MAX_FEED_ENTRIES = 15  # Only process last 15 entries per feed
BATCH_SEND_DELAY = 0.5  # Delay between sends to reduce memory spikes
GARBAGE_COLLECT_INTERVAL = 300  # Force GC every 5 minutes

RSS_FEEDS = [
    "https://www.sydsvenskan.se/feeds/section/lund/feed.xml",
    "https://fetchrss.com/feed/1wKfj4GZ41sg1wKfii1T22YU.rss",
    "https://lund.se/system/rss-skapare",
    "https://fetchrss.com/feed/1wKfj4GZ41sg1wScna6Pg6Ec.rss",
    "https://fetchrss.com/feed/1wKfj4GZ41sg1wScpJARnB4U.rss"
]

# Global state - minimal memory footprint
feed_cache = {}
channel_cache = None
last_gc = time.time()

start_time = time.time()

# =========================
# DISCORD SETUP
# =========================

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# =========================
# MEMORY UTILITIES
# =========================

def cleanup_memory():
    """Aggressively clean up memory"""
    global feed_cache, last_gc
    
    # Clear old cache entries
    now = time.time()
    feed_cache = {k: v for k, v in feed_cache.items() if now - v[0] < FEED_CACHE_TIME}
    
    # Force garbage collection
    gc.collect()
    last_gc = now

def load_posted_links():
    """Load posted links efficiently"""
    try:
        if Path(POSTED_LINKS_FILE).exists():
            with open(POSTED_LINKS_FILE, "r") as f:
                return set(json.load(f))
    except:
        pass
    return set()

def save_posted_links(links):
    """Save only most recent links to minimize file size"""
    try:
        # Keep only 1000 most recent
        if len(links) > MAX_POSTED_LINKS:
            links = {list(links)[-MAX_POSTED_LINKS:]}
        with open(POSTED_LINKS_FILE, "w") as f:
            json.dump(list(links), f)
    except Exception as e:
        print(f"Save error: {e}")

posted_links = load_posted_links()
task_started = False

# =========================
# NETWORK OPTIMIZATIONS
# =========================

class OptimizedOpener:
    """Reusable opener with connection pooling"""
    def __init__(self):
        self.opener = urllib.request.build_opener()
        self.headers = {
            'User-Agent': 'RSSBot/3.0',
            'Accept-Encoding': 'gzip',
            'Connection': 'keep-alive',
            'Accept': 'application/rss+xml'
        }
    
    async def fetch(self, url):
        """Fetch with minimal overhead"""
        for attempt in range(MAX_RETRIES):
            try:
                req = urllib.request.Request(url, headers=self.headers)
                response = await asyncio.wait_for(
                    asyncio.to_thread(urllib.request.urlopen, req, timeout=SOCKET_TIMEOUT),
                    timeout=MAX_FEED_TIMEOUT
                )
                data = response.read()
                response.close()
                return data
            except:
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(0.1 * (attempt + 1))
        return None

opener = OptimizedOpener()

async def get_channel():
    """Cache channel reference globally"""
    global channel_cache
    if channel_cache is None:
        channel_cache = await bot.fetch_channel(CHANNEL_ID)
    return channel_cache

# =========================
# FEED PROCESSING (ULTRA-OPTIMIZED)
# =========================

async def get_image(entry):
    """Minimal image extraction - only check media_content"""
    try:
        # Only check most common field
        media = entry.get("media_content")
        if media and isinstance(media, list) and len(media) > 0:
            url = media[0].get("url")
            if url and url.startswith("http"):
                return url
        
        thumb = entry.get("media_thumbnail")
        if thumb and isinstance(thumb, list) and len(thumb) > 0:
            url = thumb[0].get("url")
            if url and url.startswith("http"):
                return url
    except:
        pass
    return None

async def process_feed(feed_url):
    """Process single feed with memory efficiency"""
    try:
        now = time.time()
        
        # Check cache first
        if feed_url in feed_cache:
            cached_time, cached_feed = feed_cache[feed_url]
            if now - cached_time < FEED_CACHE_TIME:
                feed = cached_feed
            else:
                del feed_cache[feed_url]
                data = await opener.fetch(feed_url)
                if not data:
                    return 0
                feed = feedparser.parse(data)
                feed_cache[feed_url] = (now, feed)
        else:
            data = await opener.fetch(feed_url)
            if not data:
                return 0
            feed = feedparser.parse(data)
            feed_cache[feed_url] = (now, feed)
        
        if not feed.entries:
            return 0
        
        channel = await get_channel()
        new_posts = 0
        
        # Only process last N entries
        entries = list(reversed(feed.entries))[:MAX_FEED_ENTRIES]
        
        for entry in entries:
            link = entry.get("link")
            
            if not link or link in posted_links:
                continue
            
            posted_links.add(link)
            
            try:
                title = entry.get("title", "Post")[:150]  # Limit title length
                
                # Minimal description processing
                desc = entry.get("description", "")
                if desc:
                    try:
                        soup = BeautifulSoup(desc, "html.parser")
                        clean = soup.get_text()[:500]  # Reduce from 2000 to 500
                    except:
                        clean = ""
                else:
                    clean = ""
                
                image_url = await get_image(entry)
                
                # Build minimal embed
                embed = discord.Embed(
                    title=title,
                    url=link,
                    description=clean,
                    color=0x0099FF  # Use integer instead of Color object
                )
                
                if image_url:
                    embed.set_image(url=image_url)
                
                await channel.send(embed=embed)
                new_posts += 1
                
                # Add delay to prevent memory spikes
                await asyncio.sleep(BATCH_SEND_DELAY)
                
            except Exception as e:
                print(f"Post error: {e}")
        
        return new_posts
        
    except Exception as e:
        print(f"Feed error: {e}")
        return 0

async def run_feeds():
    """Run all feeds sequentially to minimize memory usage"""
    global last_gc
    
    try:
        print(f"Feed check: {time.time() - start_time:.0f}s uptime")
        
        # Sequential instead of parallel (saves memory for 1vCPU)
        total_new = 0
        for feed_url in RSS_FEEDS:
            new = await process_feed(feed_url)
            total_new += new
            await asyncio.sleep(0.1)  # Minimal delay between feeds
        
        if total_new > 0:
            save_posted_links(posted_links)
            print(f"Posted {total_new} new articles")
        
        # Periodic garbage collection
        if time.time() - last_gc > GARBAGE_COLLECT_INTERVAL:
            cleanup_memory()
            
    except Exception as e:
        print(f"Run error: {e}")

# =========================
# BACKGROUND TASK
# =========================

@tasks.loop(seconds=CHECK_INTERVAL)
async def check_feeds():
    await run_feeds()

# =========================
# MINIMAL COMMANDS
# =========================

@bot.command()
async def ping(ctx):
    """Ping"""
    start = time.time()
    msg = await ctx.send("Pinging...")
    latency = round((time.time() - start) * 1000)
    await msg.edit(content=f"🏓 {latency}ms")

@bot.command()
async def uptime(ctx):
    """Uptime"""
    seconds = int(time.time() - start_time)
    hours = seconds // 3600
    mins = (seconds % 3600) // 60
    embed = discord.Embed(title="⏱️ Uptime", description=f"{hours}h {mins}m", color=0x0099FF)
    await ctx.send(embed=embed)

@bot.command()
async def stats(ctx):
    """Stats"""
    embed = discord.Embed(title="📊 Stats", color=0x0099FF)
    embed.add_field(name="Posts", value=str(len(posted_links)), inline=True)
    embed.add_field(name="Feeds", value=str(len(RSS_FEEDS)), inline=True)
    await ctx.send(embed=embed)

@bot.command()
async def refresh(ctx):
    """Check feeds now"""
    embed = discord.Embed(title="🔄 Checking...", color=0x0099FF)
    msg = await ctx.send(embed=embed)
    await run_feeds()
    embed = discord.Embed(title="✅ Done", color=0x0099FF)
    await msg.edit(embed=embed)

@bot.command()
async def status(ctx):
    """Bot status"""
    embed = discord.Embed(title="🟢 Status", color=0x0099FF)
    embed.add_field(name="Running", value="✅", inline=True)
    embed.add_field(name="Posts", value=str(len(posted_links)), inline=True)
    embed.add_field(name="Memory Cache", value=f"{len(feed_cache)} feeds", inline=True)
    await ctx.send(embed=embed)

@bot.command()
async def health(ctx):
    """Health check"""
    embed = discord.Embed(title="💚 Health", color=0x0099FF)
    healthy = 0
    
    for i, feed_url in enumerate(RSS_FEEDS, 1):
        if feed_url in feed_cache:
            healthy += 1
            status = "✅"
        else:
            status = "⚠️"
        embed.add_field(name=f"Feed {i}", value=status, inline=True)
    
    embed.add_field(name="Overall", value=f"{healthy}/{len(RSS_FEEDS)}", inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def settings(ctx):
    """Settings"""
    embed = discord.Embed(title="⚙️ Settings", color=0x0099FF)
    embed.add_field(name="Check Interval", value=f"{CHECK_INTERVAL}s", inline=True)
    embed.add_field(name="Cache Time", value=f"{FEED_CACHE_TIME}s", inline=True)
    embed.add_field(name="Max Posts Stored", value=f"{MAX_POSTED_LINKS}", inline=True)
    embed.add_field(name="Max Feed Entries", value=f"{MAX_FEED_ENTRIES}", inline=True)
    await ctx.send(embed=embed)

@bot.command()
async def version(ctx):
    """Version"""
    embed = discord.Embed(title="ℹ️ Version 3.1", color=0x0099FF)
    embed.add_field(name="Type", value="Ultra-Optimized for 1GB RAM", inline=False)
    embed.add_field(name="Features", value="• Sequential Processing\n• Aggressive Caching\n• Memory Cleanup\n• Minimal I/O", inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def demo(ctx):
    """Demo"""
    embed = discord.Embed(title="🤖 Demo", description="Ultra-optimized RSS bot", color=0x0099FF)
    embed.set_footer(text="✅ Running")
    await ctx.send(embed=embed)

@bot.command()
async def rps(ctx, choice=None):
    """Rock Paper Scissors"""
    if not choice or choice.lower() not in ["rock", "paper", "scissors"]:
        await ctx.send("Usage: `!rps rock/paper/scissors`")
        return
    
    choice = choice.lower()
    bot_choice = random.choice(["rock", "paper", "scissors"])
    wins = {("rock", "scissors"), ("paper", "rock"), ("scissors", "paper")}
    
    if choice == bot_choice:
        result = "🤝 Tie"
        color = 0x0099FF
    elif (choice, bot_choice) in wins:
        result = "🎉 Win"
        color = 0x00FF00
    else:
        result = "🤖 Lose"
        color = 0xFF0000
    
    embed = discord.Embed(title="🎮 RPS", color=color)
    embed.add_field(name="You", value=choice, inline=True)
    embed.add_field(name="Bot", value=bot_choice, inline=True)
    embed.add_field(name="Result", value=result, inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def coin(ctx):
    """Coin flip"""
    result = random.choice(["Heads", "Tails"])
    await ctx.send(f"🪙 **{result}**")

@bot.command()
async def dice(ctx, sides=6):
    """Dice roll"""
    sides = min(max(int(sides) if str(sides).isdigit() else 6, 2), 100)
    result = random.randint(1, sides)
    await ctx.send(f"🎲 **{result}** (d{sides})")

@bot.command()
async def eightball(ctx, *, question=None):
    """Magic 8-ball"""
    if not question:
        await ctx.send("Usage: `!eightball Your question`")
        return
    answers = ["✅ Yes", "✅ Definitely", "❓ Maybe", "❓ Ask later", "❌ No", "❌ Doubtful"]
    embed = discord.Embed(title="🎱 8-Ball", color=0x0099FF)
    embed.add_field(name="Q", value=question[:100], inline=False)
    embed.add_field(name="A", value=random.choice(answers), inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def games(ctx):
    """Games"""
    embed = discord.Embed(title="🎮 Games", color=0x0099FF)
    embed.add_field(name="!rps", value="Rock Paper Scissors", inline=False)
    embed.add_field(name="!coin", value="Coin Flip", inline=False)
    embed.add_field(name="!dice", value="Dice Roll", inline=False)
    embed.add_field(name="!eightball", value="Magic 8-Ball", inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def help(ctx):
    """Help"""
    embed = discord.Embed(title="🤖 Commands", color=0x0099FF)
    embed.add_field(name="Feeds", value="!refresh • !health • !feedinfo", inline=False)
    embed.add_field(name="Info", value="!status • !stats • !settings", inline=False)
    embed.add_field(name="Basic", value="!ping • !uptime • !version", inline=False)
    embed.add_field(name="Games", value="!rps • !coin • !dice • !eightball", inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def feedinfo(ctx):
    """Feed info"""
    embed = discord.Embed(title="📡 Feeds", color=0x0099FF)
    for i, url in enumerate(RSS_FEEDS, 1):
        short = url[:60] + "..." if len(url) > 60 else url
        embed.add_field(name=f"Feed {i}", value=short, inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def clear(ctx):
    """Clear posts"""
    embed = discord.Embed(title="⚠️ Clear?", description="React ✅ to confirm", color=0x0099FF)
    msg = await ctx.send(embed=embed)
    await msg.add_reaction("✅")
    await msg.add_reaction("❌")
    
    def check(r, u):
        return u == ctx.author and str(r.emoji) in ["✅", "❌"]
    
    try:
        reaction, _ = await bot.wait_for("reaction_add", timeout=30, check=check)
        if str(reaction.emoji) == "✅":
            posted_links.clear()
            save_posted_links(posted_links)
            await msg.edit(embed=discord.Embed(title="✅ Cleared", color=0x0099FF))
    except:
        pass

# =========================
# EVENTS
# =========================

@bot.event
async def on_ready():
    global task_started
    print(f"✅ {bot.user} online")
    print(f"Feeds: {len(RSS_FEEDS)}, Posts: {len(posted_links)}")
    
    if not task_started:
        check_feeds.start()
        task_started = True

# =========================
# MEMORY OPTIMIZATION
# =========================

# Limit Python's memory allocation
import resource
try:
    # Soft limit 800MB, hard limit 950MB
    resource.setrlimit(resource.RLIMIT_AS, (800*1024*1024, 950*1024*1024))
except:
    pass

# =========================
# RUN
# =========================

bot.run(TOKEN)
