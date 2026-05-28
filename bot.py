import discord
from discord.ext import commands, tasks
import feedparser
from bs4 import BeautifulSoup
import time
import os

# =========================
# CONFIG
# =========================

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise ValueError("DISCORD_TOKEN is not set")

CHANNEL_ID = 1485298968404426802

RSS_FEEDS = [
    "https://www.sydsvenskan.se/feeds/section/lund/feed.xml",
    "https://fetchrss.com/feed/1wKfj4GZ41sg1wKfii1T22YU.rss"
]

CHECK_INTERVAL = 60  # seconds

start_time = time.time()

# =========================
# DISCORD SETUP
# =========================

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

posted_links = set()

# =========================
# ERROR LOGGING
# =========================

async def log_error(msg):
    try:
        channel = await bot.fetch_channel(CHANNEL_ID)
        await channel.send(f"⚠️ Error: {msg}")
    except:
        print("Failed to send error log:", msg)

# =========================
# RSS LOGIC
# =========================

async def run_feeds():
    try:
        channel = await bot.fetch_channel(CHANNEL_ID)

        for feed_url in RSS_FEEDS:
            feed = feedparser.parse(feed_url)

            for entry in reversed(feed.entries):
                link = entry.get("link")

                if not link or link in posted_links:
                    continue

                posted_links.add(link)

                title = entry.get("title", "New Post")

                # clean description (optional)
                description = entry.get("description", "")
                soup = BeautifulSoup(description, "html.parser")
                clean_text = soup.get_text()[:2000]

                embed = discord.Embed(
                    title=title,
                    url=link,
                    description=clean_text,
                    color=discord.Color.blue()
                )

                await channel.send(embed=embed)

                print(f"Posted: {title}")

    except Exception as e:
        await log_error(str(e))

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
    start = time.time()
    msg = await ctx.send("Pinging...")
    end = time.time()

    api_latency = round(bot.latency * 1000)
    msg_latency = round((end - start) * 1000)

    await msg.edit(content=f"🏓 Pong!\nAPI: {api_latency}ms\nMsg: {msg_latency}ms")


@bot.command()
async def uptime(ctx):
    seconds = int(time.time() - start_time)
    minutes = seconds // 60
    hours = minutes // 60

    await ctx.send(f"⏱️ Uptime: {hours}h {minutes%60}m {seconds%60}s")


@bot.command()
async def refresh(ctx):
    await ctx.send("🔄 Checking feeds...")
    await run_feeds()
    await ctx.send("✅ Done!")


@bot.command()
async def helpbot(ctx):
    await ctx.send("""
🤖 Commands:
!ping
!uptime
!refresh
""")

# =========================
# EVENTS
# =========================

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    check_feeds.start()

# =========================
# RUN
# =========================

bot.run(TOKEN)
