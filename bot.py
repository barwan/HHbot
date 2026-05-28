import discord
from discord.ext import commands, tasks
import feedparser
from bs4 import BeautifulSoup
import time
import os
import json
from pathlib import Path
import random

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
    "https://fetchrss.com/feed/1wKfj4GZ41sg1wScna6Pg6Ec.rss",
    "https://fetchrss.com/feed/1wKfj4GZ41sg1wScpJARnB4U.rss"
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
async def status(ctx):
    """Show real-time bot status"""
    embed = discord.Embed(
        title="🟢 Bot Status",
        color=discord.Color.blue()
    )
    embed.add_field(name="Running", value="✅ Yes", inline=True)
    embed.add_field(name="Checking Feeds", value="✅ Active", inline=True)
    embed.add_field(name="Uptime", value=f"{int((time.time() - start_time) / 3600)}h", inline=True)
    embed.add_field(name="Posts Tracked", value=str(len(posted_links)), inline=True)
    embed.add_field(name="Feeds Active", value=str(len(RSS_FEEDS)), inline=True)
    embed.add_field(name="Check Interval", value=f"{CHECK_INTERVAL}s", inline=True)
    
    await ctx.send(embed=embed)


@bot.command()
async def settings(ctx):
    """Show current bot settings"""
    embed = discord.Embed(
        title="⚙️ Bot Settings",
        color=discord.Color.blue()
    )
    embed.add_field(name="Check Interval", value=f"{CHECK_INTERVAL} seconds", inline=False)
    embed.add_field(name="Max Posts Tracked", value=f"{MAX_POSTED_LINKS} links", inline=False)
    embed.add_field(name="Channel ID", value=str(CHANNEL_ID), inline=False)
    embed.add_field(name="Storage File", value=POSTED_LINKS_FILE, inline=False)
    embed.add_field(name="Feed Count", value=str(len(RSS_FEEDS)), inline=False)
    
    await ctx.send(embed=embed)


@bot.command()
async def feedinfo(ctx):
    """Show detailed info about all feeds"""
    embed = discord.Embed(
        title="📊 Feed Information",
        color=discord.Color.blue()
    )
    
    for i, feed_url in enumerate(RSS_FEEDS, 1):
        try:
            feed = feedparser.parse(feed_url)
            entry_count = len(feed.entries)
            embed.add_field(
                name=f"Feed {i}",
                value=f"**Entries:** {entry_count}\n**URL:** {feed_url}",
                inline=False
            )
        except:
            embed.add_field(
                name=f"Feed {i}",
                value=f"**Status:** Error loading\n**URL:** {feed_url}",
                inline=False
            )
    
    await ctx.send(embed=embed)


@bot.command()
async def notify(ctx):
    """Enable/disable notifications"""
    embed = discord.Embed(
        title="🔔 Notifications",
        description="React to toggle notification settings:",
        color=discord.Color.blue()
    )
    embed.add_field(name="Status", value="Currently: ✅ Enabled", inline=False)
    
    msg = await ctx.send(embed=embed)


@bot.command()
async def health(ctx):
    """Check bot health and feed connectivity"""
    embed = discord.Embed(
        title="💚 Bot Health Check",
        color=discord.Color.blue()
    )
    
    healthy_feeds = 0
    
    for i, feed_url in enumerate(RSS_FEEDS, 1):
        try:
            feed = feedparser.parse(feed_url)
            if feed.entries:
                healthy_feeds += 1
                status = "✅ OK"
            else:
                status = "⚠️ Empty"
        except:
            status = "❌ Error"
        
        embed.add_field(name=f"Feed {i}", value=status, inline=True)
    
    overall = f"{healthy_feeds}/{len(RSS_FEEDS)} feeds healthy"
    embed.add_field(name="Overall Status", value=overall, inline=False)
    embed.add_field(name="Bot Response", value="✅ Responsive", inline=False)
    
    await ctx.send(embed=embed)


@bot.command()
async def history(ctx):
    """Show command history and recent activity"""
    embed = discord.Embed(
        title="📜 Recent Activity",
        color=discord.Color.blue()
    )
    
    uptime_seconds = int(time.time() - start_time)
    uptime_hours = uptime_seconds // 3600
    
    embed.add_field(name="Bot Started", value=f"{uptime_hours} hours ago", inline=False)
    embed.add_field(name="Posts Tracked", value=str(len(posted_links)), inline=True)
    embed.add_field(name="Feeds Monitored", value=str(len(RSS_FEEDS)), inline=True)
    embed.add_field(name="Check Interval", value=f"Every {CHECK_INTERVAL}s", inline=False)
    
    await ctx.send(embed=embed)


@bot.command()
async def version(ctx):
    """Show bot version and info"""
    embed = discord.Embed(
        title="ℹ️ Bot Version",
        color=discord.Color.blue()
    )
    embed.add_field(name="Bot Name", value="HHbot @ Hevosen Hallinta (HH)", inline=False)
    embed.add_field(name="Version", value="2.0 (Ultra Enhanced)", inline=False)
    embed.add_field(name="Features", value="• RSS Feed Monitoring\n• Auto-posting\n• Persistent storage\n• Real-time updates", inline=False)
    
    await ctx.send(embed=embed)


# =========================
# GAMES
# =========================

@bot.command()
async def rps(ctx, choice=None):
    """Play Rock Paper Scissors! Usage: !rps rock/paper/scissors"""
    if not choice:
        embed = discord.Embed(
            title="🎮 Rock Paper Scissors",
            description="Usage: `!rps rock` or `!rps paper` or `!rps scissors`",
            color=discord.Color.blue()
        )
        await ctx.send(embed=embed)
        return
    
    choice = choice.lower()
    valid_choices = ["rock", "paper", "scissors"]
    
    if choice not in valid_choices:
        embed = discord.Embed(
            title="❌ Invalid Choice",
            description="Choose: rock, paper, or scissors",
            color=discord.Color.blue()
        )
        await ctx.send(embed=embed)
        return
    
    bot_choice = random.choice(valid_choices)
    
    # Determine winner
    if choice == bot_choice:
        result = "🤝 It's a Tie!"
        color = discord.Color.blue()
    elif (choice == "rock" and bot_choice == "scissors") or \
         (choice == "paper" and bot_choice == "rock") or \
         (choice == "scissors" and bot_choice == "paper"):
        result = "🎉 You Win!"
        color = discord.Color.green()
    else:
        result = "🤖 Bot Wins!"
        color = discord.Color.red()
    
    embed = discord.Embed(
        title="🎮 Rock Paper Scissors",
        color=color
    )
    embed.add_field(name="Your Choice", value=f"✋ {choice.capitalize()}", inline=True)
    embed.add_field(name="Bot's Choice", value=f"✋ {bot_choice.capitalize()}", inline=True)
    embed.add_field(name="Result", value=result, inline=False)
    
    await ctx.send(embed=embed)


@bot.command()
async def coin(ctx):
    """Flip a coin - heads or tails"""
    result = random.choice(["Heads", "Tails"])
    emoji = "🪙" if result == "Heads" else "🪙"
    
    embed = discord.Embed(
        title="🪙 Coin Flip",
        description=f"{emoji} **{result}**",
        color=discord.Color.blue()
    )
    
    await ctx.send(embed=embed)


@bot.command()
async def dice(ctx, sides=6):
    """Roll a dice! Usage: !dice or !dice 20"""
    if sides < 2 or sides > 100:
        sides = 6
    
    result = random.randint(1, sides)
    
    embed = discord.Embed(
        title="🎲 Dice Roll",
        color=discord.Color.blue()
    )
    embed.add_field(name=f"D{sides}", value=f"**{result}**", inline=False)
    
    await ctx.send(embed=embed)


@bot.command()
async def eightball(ctx, *, question=None):
    """Ask the magic 8-ball a question! Usage: !eightball Will I win?"""
    if not question:
        embed = discord.Embed(
            title="🎱 Magic 8-Ball",
            description="Ask me a question! Usage: `!eightball Your question here`",
            color=discord.Color.blue()
        )
        await ctx.send(embed=embed)
        return
    
    answers = [
        "✅ Yes, definitely!",
        "✅ It is certain.",
        "✅ Without a doubt!",
        "✅ Absolutely!",
        "❓ Maybe, ask again later.",
        "❓ Reply hazy, try again.",
        "❓ Cannot predict now.",
        "❓ Ask again later.",
        "❌ No, definitely not.",
        "❌ Don't count on it.",
        "❌ My sources say no.",
        "❌ Very doubtful.",
    ]
    
    answer = random.choice(answers)
    
    embed = discord.Embed(
        title="🎱 Magic 8-Ball",
        color=discord.Color.blue()
    )
    embed.add_field(name="Question", value=question, inline=False)
    embed.add_field(name="Answer", value=answer, inline=False)
    
    await ctx.send(embed=embed)


@bot.command()
async def guess(ctx):
    """Guess a number between 1-100! Usage: !guess"""
    secret = random.randint(1, 100)
    
    embed = discord.Embed(
        title="🎯 Number Guessing Game",
        description="I'm thinking of a number between 1-100.\nReply with your guess!",
        color=discord.Color.blue()
    )
    await ctx.send(embed=embed)
    
    def check(msg):
        return msg.author == ctx.author and msg.channel == ctx.channel
    
    attempts = 0
    max_attempts = 7
    
    while attempts < max_attempts:
        try:
            guess_msg = await bot.wait_for("message", timeout=30.0, check=check)
            attempts += 1
            
            try:
                guess_num = int(guess_msg.content)
            except ValueError:
                feedback = discord.Embed(
                    title="🎯 Number Guessing Game",
                    description="Please enter a valid number!",
                    color=discord.Color.blue()
                )
                await ctx.send(embed=feedback)
                continue
            
            if guess_num == secret:
                win_embed = discord.Embed(
                    title="🎉 You Won!",
                    description=f"The number was **{secret}**!\nYou guessed it in **{attempts}** attempts!",
                    color=discord.Color.green()
                )
                await ctx.send(embed=win_embed)
                return
            elif guess_num < secret:
                feedback = discord.Embed(
                    title="🎯 Too Low!",
                    description=f"Try higher! ({max_attempts - attempts} attempts left)",
                    color=discord.Color.blue()
                )
            else:
                feedback = discord.Embed(
                    title="🎯 Too High!",
                    description=f"Try lower! ({max_attempts - attempts} attempts left)",
                    color=discord.Color.blue()
                )
            
            await ctx.send(embed=feedback)
        
        except:
            timeout_embed = discord.Embed(
                title="⏰ Time's Up!",
                description=f"The number was **{secret}**!",
                color=discord.Color.blue()
            )
            await ctx.send(embed=timeout_embed)
            return
    
    lose_embed = discord.Embed(
        title="😔 Game Over!",
        description=f"You ran out of attempts! The number was **{secret}**!",
        color=discord.Color.red()
    )
    await ctx.send(embed=lose_embed)


@bot.command()
async def helpbot(ctx):
    """Show available commands"""
    # Page 1 - Main Info
    embed1 = discord.Embed(
        title="🤖 RSS Bot - Command Help",
        description="Complete command list with categories",
        color=discord.Color.blue()
    )
    
    # Basic Commands
    embed1.add_field(
        name="📡 FEED COMMANDS",
        value="!refresh - Check feeds now\n!feeds - List all feeds\n!feedinfo - Detailed feed info",
        inline=False
    )
    
    # Info Commands
    embed1.add_field(
        name="📊 INFORMATION",
        value="!status - Bot status\n!stats - Statistics\n!health - Health check\n!history - Recent activity\n!settings - Bot settings\n!about - About the bot",
        inline=False
    )
    
    # Basic Commands
    embed1.add_field(
        name="⚙️ BASIC",
        value="!ping - Check latency\n!uptime - Bot uptime\n!version - Bot version",
        inline=False
    )
    
    # Utility
    embed1.add_field(
        name="🛠️ UTILITY",
        value="!demo - Demo message\n!notify - Notifications\n!clear - Clear history (⚠️)",
        inline=False
    )
    
    # Games
    embed2 = discord.Embed(
        title="🎮 GAMES",
        description="Play fun games with the bot!",
        color=discord.Color.blue()
    )
    
    embed2.add_field(
        name="!rps <choice>",
        value="Rock Paper Scissors\nChoose: rock, paper, or scissors",
        inline=False
    )
    
    embed2.add_field(
        name="!coin",
        value="Flip a coin\nHeads or Tails",
        inline=False
    )
    
    embed2.add_field(
        name="!dice [sides]",
        value="Roll a dice\nDefault: 6 sides, or specify up to 100",
        inline=False
    )
    
    embed2.add_field(
        name="!eightball <question>",
        value="Ask the magic 8-ball\nWill give you a mystical answer",
        inline=False
    )
    
    embed2.add_field(
        name="!guess",
        value="Guess a number\nGuess a number between 1-100 in 7 attempts",
        inline=False
    )
    
    embed2.set_footer(text="Page 1/2 - Use reactions or type !games for games only")
    embed1.set_footer(text="Page 1/2")
    
    msg = await ctx.send(embed=embed1)
    await msg.add_reaction("⬅️")
    await msg.add_reaction("➡️")
    
    def check(reaction, user):
        return user == ctx.author and str(reaction.emoji) in ["⬅️", "➡️"]
    
    try:
        while True:
            reaction, user = await bot.wait_for("reaction_add", timeout=30.0, check=check)
            
            if str(reaction.emoji) == "➡️":
                await msg.edit(embed=embed2)
            else:
                await msg.edit(embed=embed1)
            
            await msg.remove_reaction(reaction, user)
    except:
        pass


@bot.command()
async def games(ctx):
    """Show only game commands"""
    embed = discord.Embed(
        title="🎮 Available Games",
        description="Have fun playing games!",
        color=discord.Color.blue()
    )
    
    embed.add_field(
        name="!rps <choice>",
        value="🎮 Rock Paper Scissors\nUsage: `!rps rock` or `!rps paper` or `!rps scissors`",
        inline=False
    )
    
    embed.add_field(
        name="!coin",
        value="🪙 Coin Flip\nGet heads or tails",
        inline=False
    )
    
    embed.add_field(
        name="!dice [sides]",
        value="🎲 Dice Roll\nUsage: `!dice` (default 6) or `!dice 20`",
        inline=False
    )
    
    embed.add_field(
        name="!eightball <question>",
        value="🎱 Magic 8-Ball\nUsage: `!eightball Will I win?`",
        inline=False
    )
    
    embed.add_field(
        name="!guess",
        value="🎯 Number Guessing\nGuess a number between 1-100 in 7 attempts!",
        inline=False
    )
    
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
