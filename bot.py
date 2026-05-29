import discord
from discord.ext import commands, tasks
import feedparser
import time
import os
import json
from pathlib import Path
import random
import asyncio
import urllib.request
import gc

# =========================
# CONFIG - MINIMAL
# =========================

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise ValueError("DISCORD_TOKEN is not set")

CHANNEL_ID = 1485298968404426802
CHECK_INTERVAL = 120
MAX_POSTED_LINKS = 800  # Further reduced
FEED_CACHE_TIME = 60
MAX_FEED_TIMEOUT = 8
SOCKET_TIMEOUT = 12

RSS_FEEDS = (  # Use tuple instead of list (immutable, smaller memory)
    "https://www.sydsvenskan.se/feeds/section/lund/feed.xml",
    "https://fetchrss.com/feed/1wKfj4GZ41sg1wKfii1T22YU.rss",
    "https://fetchrss.com/feed/1wKfj4GZ41sg1wScna6Pg6Ec.rss",
    "https://fetchrss.com/feed/1wKfj4GZ41sg1wScpJARnB4U.rss"
)

# Cache
feed_cache = {}
channel_cache = None
last_gc = 0

start_time = time.time()
current_time = start_time  # Cache current time

# Color constant (used in every embed)
BLUE = 0x0099FF

# Discord setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# =========================
# UTILITIES
# =========================

def load_posted_links():
    """Load posted links"""
    try:
        if Path("posted_links.json").exists():
            with open("posted_links.json", "r") as f:
                return set(json.load(f))
    except:
        pass
    return set()

def save_posted_links(links):
    """Save posted links efficiently"""
    try:
        # Convert to list and keep only last N items
        if len(links) > MAX_POSTED_LINKS:
            links_list = list(links)
            links = set(links_list[-MAX_POSTED_LINKS:])
        
        with open("posted_links.json", "w") as f:
            json.dump(list(links), f)
    except Exception as e:
        print(f"Save error: {e}")

def cleanup_memory():
    """Clean memory efficiently"""
    global feed_cache
    
    # Remove expired cache entries
    now = time.time()
    expired = [k for k, v in feed_cache.items() if now - v[0] > FEED_CACHE_TIME]
    for k in expired:
        del feed_cache[k]
    
    # Force GC
    gc.collect()

async def get_channel():
    """Get cached channel"""
    global channel_cache
    if channel_cache is None:
        channel_cache = await bot.fetch_channel(CHANNEL_ID)
    return channel_cache

async def fetch_feed(url):
    """Fetch feed with timeout"""
    try:
        req = urllib.request.Request(
            url,
            headers={'User-Agent': 'RSSBot/3.0', 'Accept-Encoding': 'gzip'}
        )
        response = await asyncio.wait_for(
            asyncio.to_thread(urllib.request.urlopen, req, timeout=SOCKET_TIMEOUT),
            timeout=MAX_FEED_TIMEOUT
        )
        data = response.read()
        response.close()
        return data
    except:
        return None

async def get_image(entry):
    """Extract image - only check media_content"""
    try:
        media = entry.get("media_content")
        if media and isinstance(media, list):
            url = media[0].get("url")
            if url and url.startswith("http"):
                return url
        
        thumb = entry.get("media_thumbnail")
        if thumb and isinstance(thumb, list):
            url = thumb[0].get("url")
            if url and url.startswith("http"):
                return url
    except:
        pass
    return None

# Pre-compile a simple HTML strip function (faster than BeautifulSoup)
def strip_html(text):
    """Strip HTML tags manually (faster than BeautifulSoup)"""
    if not text or '<' not in text:
        return text
    
    result = []
    in_tag = False
    for char in text:
        if char == '<':
            in_tag = True
        elif char == '>':
            in_tag = False
        elif not in_tag:
            result.append(char)
    
    return ''.join(result)

async def process_feed(feed_url):
    """Process single feed"""
    now = time.time()
    
    # Check cache
    if feed_url in feed_cache:
        cached_time, cached_feed = feed_cache[feed_url]
        if now - cached_time < FEED_CACHE_TIME:
            feed = cached_feed
        else:
            del feed_cache[feed_url]
            data = await fetch_feed(feed_url)
            feed = feedparser.parse(data) if data else None
            if feed:
                feed_cache[feed_url] = (now, feed)
    else:
        data = await fetch_feed(feed_url)
        feed = feedparser.parse(data) if data else None
        if feed:
            feed_cache[feed_url] = (now, feed)
    
    if not feed or not feed.entries:
        return 0
    
    channel = await get_channel()
    new_posts = 0
    
    # Only process last 15 entries
    for entry in list(reversed(feed.entries))[:15]:
        link = entry.get("link")
        if not link or link in posted_links:
            continue
        
        posted_links.add(link)
        
        try:
            title = entry.get("title", "Post")
            if len(title) > 150:
                title = title[:150]
            
            # Fast HTML stripping instead of BeautifulSoup
            desc = entry.get("description", "")
            if desc:
                clean = strip_html(desc)
                if len(clean) > 400:
                    clean = clean[:400]
            else:
                clean = ""
            
            image_url = await get_image(entry)
            
            # Create embed
            embed = discord.Embed(
                title=title,
                url=link,
                description=clean,
                color=BLUE
            )
            
            if image_url:
                embed.set_image(url=image_url)
            
            await channel.send(embed=embed)
            new_posts += 1
            
            # Small delay to prevent spikes
            await asyncio.sleep(0.2)
            
        except Exception as e:
            print(f"Post error: {e}")
    
    return new_posts

async def run_feeds():
    """Run all feeds"""
    global last_gc
    
    try:
        total_new = 0
        for feed_url in RSS_FEEDS:
            new = await process_feed(feed_url)
            total_new += new
            await asyncio.sleep(0.05)
        
        if total_new > 0:
            save_posted_links(posted_links)
        
        # GC every 5 minutes
        if time.time() - last_gc > 300:
            cleanup_memory()
            last_gc = time.time()
            
    except Exception as e:
        print(f"Run error: {e}")

# =========================
# BACKGROUND TASK
# =========================

@tasks.loop(seconds=CHECK_INTERVAL)
async def check_feeds():
    await run_feeds()

# =========================
# COMMANDS - ULTRA-MINIMAL
# =========================

def make_embed(title, description=""):
    """Helper to create embeds (reduces duplicate code)"""
    return discord.Embed(title=title, description=description, color=BLUE)

@bot.command()
async def ping(ctx):
    """Ping"""
    start = time.time()
    msg = await ctx.send("🏓")
    latency = round((time.time() - start) * 1000)
    await msg.edit(content=f"🏓 {latency}ms")

@bot.command()
async def uptime(ctx):
    """Uptime"""
    seconds = int(time.time() - start_time)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    await ctx.send(embed=make_embed("⏱️ Uptime", f"{h}h {m}m"))

@bot.command()
async def stats(ctx):
    """Stats"""
    embed = make_embed("📊 Stats")
    embed.add_field(name="Posts", value=str(len(posted_links)), inline=True)
    embed.add_field(name="Feeds", value=str(len(RSS_FEEDS)), inline=True)
    await ctx.send(embed=embed)

@bot.command()
async def refresh(ctx):
    """Check feeds"""
    msg = await ctx.send(embed=make_embed("🔄 Checking..."))
    await run_feeds()
    await msg.edit(embed=make_embed("✅ Done"))

@bot.command()
async def status(ctx):
    """Status"""
    embed = make_embed("🟢 Status")
    embed.add_field(name="Running", value="✅", inline=True)
    embed.add_field(name="Posts", value=str(len(posted_links)), inline=True)
    embed.add_field(name="Cache", value=f"{len(feed_cache)}", inline=True)
    await ctx.send(embed=embed)

@bot.command()
async def health(ctx):
    """Health check"""
    embed = make_embed("💚 Health")
    healthy = sum(1 for f in RSS_FEEDS if f in feed_cache)
    embed.add_field(name="Overall", value=f"{healthy}/{len(RSS_FEEDS)}", inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def settings(ctx):
    """Settings"""
    embed = make_embed("⚙️ Settings")
    embed.add_field(name="Check", value=f"{CHECK_INTERVAL}s", inline=True)
    embed.add_field(name="Cache", value=f"{FEED_CACHE_TIME}s", inline=True)
    embed.add_field(name="Max Posts", value=f"{MAX_POSTED_LINKS}", inline=True)
    await ctx.send(embed=embed)

@bot.command()
async def version(ctx):
    """Version"""
    embed = make_embed("ℹ️ Bot v3.2", "Ultra-optimized for 1GB RAM")
    embed.add_field(name="Memory", value="Minimal", inline=True)
    embed.add_field(name="CPU", value="Low", inline=True)
    await ctx.send(embed=embed)

@bot.command()
async def demo(ctx):
    """Demo"""
    embed = make_embed("🤖 Demo", "Ultra-optimized RSS bot")
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
        embed = make_embed("🎮 RPS", "🤝 Tie")
        embed.color = BLUE
    elif (choice, bot_choice) in wins:
        embed = make_embed("🎮 RPS", "🎉 Win!")
        embed.color = 0x00FF00
    else:
        embed = make_embed("🎮 RPS", "🤖 Lose")
        embed.color = 0xFF0000
    
    embed.add_field(name="You", value=choice, inline=True)
    embed.add_field(name="Bot", value=bot_choice, inline=True)
    await ctx.send(embed=embed)

@bot.command()
async def coin(ctx):
    """Coin flip"""
    result = "Heads" if random.random() > 0.5 else "Tails"
    await ctx.send(f"🪙 **{result}**")

@bot.command()
async def dice(ctx, sides: int = 6):
    """Dice roll"""
    sides = min(max(sides, 2), 100)
    result = random.randint(1, sides)
    await ctx.send(f"🎲 **{result}** (d{sides})")

@bot.command()
async def eightball(ctx, *, question=None):
    """Magic 8-ball"""
    if not question:
        await ctx.send("Usage: `!eightball Your question`")
        return
    
    answers = ["✅ Yes", "✅ Definitely", "❓ Maybe", "❓ Ask later", "❌ No", "❌ Doubtful"]
    embed = make_embed("🎱 8-Ball")
    embed.add_field(name="Q", value=question[:80], inline=False)
    embed.add_field(name="A", value=random.choice(answers), inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def games(ctx):
    """Games"""
    embed = make_embed("🎮 Games")
    embed.add_field(name="!rps", value="Rock Paper Scissors", inline=False)
    embed.add_field(name="!coin", value="Flip", inline=False)
    embed.add_field(name="!dice", value="Roll", inline=False)
    embed.add_field(name="!eightball", value="8-Ball", inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def help(ctx):
    """Help"""
    embed = make_embed("🤖 Commands")
    embed.add_field(name="Feeds", value="!refresh • !health", inline=False)
    embed.add_field(name="Info", value="!status • !stats • !settings", inline=False)
    embed.add_field(name="Basic", value="!ping • !uptime • !version", inline=False)
    embed.add_field(name="Games", value="!rps • !coin • !dice • !eightball", inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def feedinfo(ctx):
    """Feeds"""
    embed = make_embed("📡 Feeds")
    for i, url in enumerate(RSS_FEEDS, 1):
        short = url[:50] + "..." if len(url) > 50 else url
        embed.add_field(name=f"Feed {i}", value=short, inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def clear(ctx):
    """Clear posts"""
    msg = await ctx.send(embed=make_embed("⚠️ Clear?", "React ✅ to confirm"))
    await msg.add_reaction("✅")
    await msg.add_reaction("❌")
    
    def check(r, u):
        return u == ctx.author and str(r.emoji) in ["✅", "❌"]
    
    try:
        reaction, _ = await bot.wait_for("reaction_add", timeout=30, check=check)
        if str(reaction.emoji) == "✅":
            posted_links.clear()
            save_posted_links(posted_links)
            await msg.edit(embed=make_embed("✅ Cleared"))
    except:
        pass

# =========================
# EVENTS
# =========================

@bot.event
async def on_ready():
    global task_started
    print(f"✅ {bot.user} online - {len(posted_links)} posts tracked")
    
    if not task_started:
        check_feeds.start()
        task_started = True

task_started = False

# =========================
# RUN
# =========================

bot.run(TOKEN)
