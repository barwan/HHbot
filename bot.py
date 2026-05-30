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
import random

# ==================== CONFIG ====================

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise ValueError("DISCORD_TOKEN is not set")

CHANNEL_ID = 1485298968404426802
CHECK_INTERVAL = 120

RSS_FEEDS = (
    "https://www.sydsvenskan.se/feeds/section/lund/feed.xml",
    "https://fetchrss.com/feed/1wKfj4GZ41sg1wKfii1T22YU.rss",
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

# ==================== GAMES ====================

@bot.command()
async def rps(ctx, choice=None):
    """Rock Paper Scissors - usage: !rps rock/paper/scissors"""
    if not choice or choice.lower() not in ["rock", "paper", "scissors"]:
        embed = discord.Embed(title="🎮 Rock Paper Scissors", description="Usage: `!rps rock/paper/scissors`", color=0x0099FF)
        await ctx.send(embed=embed)
        return
    
    choice = choice.lower()
    bot_choice = random.choice(["rock", "paper", "scissors"])
    wins = {("rock", "scissors"), ("paper", "rock"), ("scissors", "paper")}
    
    if choice == bot_choice:
        result, color = "🤝 Tie!", 0x0099FF
    elif (choice, bot_choice) in wins:
        result, color = "🎉 You Win!", 0x00FF00
    else:
        result, color = "🤖 Bot Wins!", 0xFF0000
    
    embed = discord.Embed(title="🎮 Rock Paper Scissors", color=color)
    embed.add_field(name="Your Choice", value=f"✋ {choice.capitalize()}", inline=True)
    embed.add_field(name="Bot's Choice", value=f"✋ {bot_choice.capitalize()}", inline=True)
    embed.add_field(name="Result", value=result, inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def coin(ctx):
    """Flip a coin"""
    result = random.choice(["Heads", "Tails"])
    embed = discord.Embed(title="🪙 Coin Flip", description=f"🪙 **{result}**", color=0x0099FF)
    await ctx.send(embed=embed)

@bot.command()
async def dice(ctx, sides: int = 6):
    """Roll a dice - usage: !dice or !dice 20"""
    sides = min(max(sides, 2), 100)
    result = random.randint(1, sides)
    embed = discord.Embed(title="🎲 Dice Roll", description=f"**d{sides}: {result}**", color=0x0099FF)
    await ctx.send(embed=embed)

@bot.command()
async def eightball(ctx, *, question=None):
    """Ask the magic 8-ball - usage: !eightball Your question?"""
    if not question:
        embed = discord.Embed(title="🎱 Magic 8-Ball", description="Usage: `!eightball Your question?`", color=0x0099FF)
        await ctx.send(embed=embed)
        return
    
    answers = [
        "✅ Yes, definitely!",
        "✅ It is certain.",
        "✅ Absolutely!",
        "❓ Maybe, ask again later.",
        "❓ Cannot predict now.",
        "❌ No, definitely not.",
        "❌ Don't count on it.",
        "❌ Very doubtful."
    ]
    
    embed = discord.Embed(title="🎱 Magic 8-Ball", color=0x0099FF)
    embed.add_field(name="Question", value=question, inline=False)
    embed.add_field(name="Answer", value=random.choice(answers), inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def games(ctx):
    """Show available games"""
    embed = discord.Embed(title="🎮 Games", color=0x0099FF)
    embed.add_field(name="!rps <choice>", value="Rock Paper Scissors (rock/paper/scissors)", inline=False)
    embed.add_field(name="!coin", value="Flip a coin (heads/tails)", inline=False)
    embed.add_field(name="!dice [sides]", value="Roll a dice (default 6, max 100)", inline=False)
    embed.add_field(name="!eightball <question>", value="Ask the magic 8-ball", inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def help(ctx):
    """Show available commands"""
    embed = discord.Embed(title="🤖 Commands", color=0x0099FF)
    embed.add_field(name="📡 Feeds", value="!refresh • !stats • !status", inline=False)
    embed.add_field(name="⚙️ Info", value="!settings • !help", inline=False)
    embed.add_field(name="🎮 Games", value="!rps • !coin • !dice • !eightball • !games", inline=False)
    embed.add_field(name="📊 Basic", value="!ping", inline=False)
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
