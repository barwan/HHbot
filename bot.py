import discord
from discord.ext import commands, tasks
import feedparser
from bs4 import BeautifulSoup
import time
import os
import json
from pathlib import Path
import asyncio
import urllib.request

# ==================== CONFIG ====================

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise ValueError("DISCORD_TOKEN is not set")

CHANNEL_ID = 1485298968404426802
CHECK_INTERVAL = 120

RSS_FEEDS = (
    "https://www.sydsvenskan.se/feeds/section/lund/feed.xml",
    "https://fetchrss.com/feed/1wKfj4GZ41sg1wKfii1T22YU.rss",
    "https://lund.se/system/rss-skapare",
    "https://fetchrss.com/feed/1wKfj4GZ41sg1wScna6Pg6Ec.rss",
    "https://fetchrss.com/feed/1wKfj4GZ41sg1wScpJARnB4U.rss"
)

# ==================== DISCORD SETUP ====================

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# ==================== STATE ====================

def load_posted_links():
    """Load posted links from file"""
    try:
        if Path("posted_links.json").exists():
            with open("posted_links.json") as f:
                return set(json.load(f))
    except:
        pass
    return set()

def save_posted_links(links):
    """Save posted links to file"""
    try:
        with open("posted_links.json", "w") as f:
            json.dump(list(links), f)
    except:
        pass

posted_links = load_posted_links()
task_started = False
start_time = time.time()

# ==================== UTILITIES ====================

def get_image(entry):
    """Extract image URL from feed entry"""
    try:
        # Check media_content
        media = entry.get("media_content")
        if media and isinstance(media, list):
            url = media[0].get("url")
            if url and url.startswith("http"):
                return url
        
        # Check media_thumbnail
        thumb = entry.get("media_thumbnail")
        if thumb and isinstance(thumb, list):
            url = thumb[0].get("url")
            if url and url.startswith("http"):
                return url
    except:
        pass
    return None

async def fetch_feed(url):
    """Fetch RSS feed with timeout"""
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'RSSBot/3.0'})
        response = await asyncio.wait_for(
            asyncio.to_thread(urllib.request.urlopen, req, timeout=10),
            timeout=8
        )
        data = response.read()
        response.close()
        return data
    except:
        return None

# ==================== FEED PROCESSING ====================

async def process_feed(feed_url):
    """Process a single RSS feed"""
    try:
        data = await fetch_feed(feed_url)
        if not data:
            return 0
        
        feed = feedparser.parse(data)
        if not feed or not feed.entries:
            return 0
        
        channel = await bot.fetch_channel(CHANNEL_ID)
        new_posts = 0
        
        # Process last 15 entries
        for entry in list(reversed(feed.entries))[:15]:
            link = entry.get("link")
            
            # Skip if no link or already posted
            if not link or link in posted_links:
                continue
            
            posted_links.add(link)
            
            try:
                # Get title and description
                title = entry.get("title", "Post")[:150]
                desc = entry.get("description", "")
                
                if desc:
                    soup = BeautifulSoup(desc, "html.parser")
                    clean = soup.get_text()[:400]
                else:
                    clean = ""
                
                # Get image
                image_url = get_image(entry)
                
                # Create and send embed
                embed = discord.Embed(
                    title=title,
                    url=link,
                    description=clean,
                    color=0x0099FF
                )
                
                if image_url:
                    embed.set_image(url=image_url)
                
                await channel.send(embed=embed)
                new_posts += 1
                
                # Delay to prevent rate limiting
                await asyncio.sleep(0.2)
                
            except Exception as e:
                print(f"Post error: {e}")
        
        return new_posts
        
    except Exception as e:
        print(f"Feed error: {e}")
        return 0

async def run_feeds():
    """Check all RSS feeds"""
    try:
        total = 0
        for url in RSS_FEEDS:
            total += await process_feed(url)
            await asyncio.sleep(0.05)
        
        # Save posted links if new posts found
        if total > 0:
            save_posted_links(posted_links)
            print(f"Posted {total} new articles")
            
    except Exception as e:
        print(f"Run error: {e}")

# ==================== BACKGROUND TASK ====================

@tasks.loop(seconds=CHECK_INTERVAL)
async def check_feeds():
    """Background task to check feeds periodically"""
    await run_feeds()

# ==================== COMMANDS ====================

@bot.command()
async def ping(ctx):
    """Check bot latency"""
    start = time.time()
    msg = await ctx.send("🏓")
    latency = round((time.time() - start) * 1000)
    await msg.edit(content=f"🏓 {latency}ms")

@bot.command()
async def stats(ctx):
    """Show bot statistics"""
    embed = discord.Embed(title="📊 Stats", color=0x0099FF)
    embed.add_field(name="Posts Tracked", value=str(len(posted_links)), inline=True)
    embed.add_field(name="Feeds Monitored", value=str(len(RSS_FEEDS)), inline=True)
    await ctx.send(embed=embed)

@bot.command()
async def status(ctx):
    """Show bot status"""
    embed = discord.Embed(title="🟢 Status", color=0x0099FF)
    embed.add_field(name="Running", value="✅ Yes", inline=True)
    embed.add_field(name="Posts Tracked", value=str(len(posted_links)), inline=True)
    await ctx.send(embed=embed)

@bot.command()
async def settings(ctx):
    """Show bot settings"""
    embed = discord.Embed(title="⚙️ Settings", color=0x0099FF)
    embed.add_field(name="Check Interval", value=f"{CHECK_INTERVAL}s", inline=True)
    embed.add_field(name="Channel ID", value=str(CHANNEL_ID), inline=True)
    await ctx.send(embed=embed)

@bot.command()
async def refresh(ctx):
    """Manually check feeds now"""
    msg = await ctx.send("🔄 Checking feeds...")
    await run_feeds()
    await msg.edit(content="✅ Feed check complete!")

@bot.command()
async def help(ctx):
    """Show available commands"""
    embed = discord.Embed(title="🤖 Commands", color=0x0099FF)
    embed.add_field(name="!ping", value="Check bot latency", inline=False)
    embed.add_field(name="!stats", value="Show statistics", inline=False)
    embed.add_field(name="!status", value="Show bot status", inline=False)
    embed.add_field(name="!settings", value="Show settings", inline=False)
    embed.add_field(name="!refresh", value="Check feeds manually", inline=False)
    await ctx.send(embed=embed)

# ==================== EVENTS ====================

@bot.event
async def on_ready():
    """Called when bot is ready"""
    global task_started
    print(f"✅ {bot.user} is online")
    print(f"Posts tracked: {len(posted_links)}")
    print(f"Monitoring {len(RSS_FEEDS)} feeds")
    
    if not task_started:
        try:
            check_feeds.start()
            task_started = True
            print("✅ Feed checker started")
        except Exception as e:
            print(f"Error starting feed checker: {e}")

# ==================== RUN ====================

if __name__ == "__main__":
    bot.run(TOKEN)
