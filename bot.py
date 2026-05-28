import discord
from discord.ext import commands, tasks
import feedparser
from bs4 import BeautifulSoup
import time

# =========================
# CONFIG
# =========================

TOKEN = os.getenv("DISCORD_TOKEN")

CHANNEL_ID = 1485298968404426802

RSS_FEEDS = [
    "https://www.sydsvenskan.se/feeds/section/lund/feed.xml",
    "https://www.sydsvenskan.se/feeds/section/burlov/feed.xml"
    "https://www.sydsvenskan.se/feeds/section/sverige/feed.xml"
    "https://www.sydsvenskan.se/feeds/section/varlden/feed.xml"
    "https://fetchrss.com/feed/1wKfj4GZ41sg1wKfii1T22YU.rss"
]

CHECK_INTERVAL = 60  # seconds

# =========================
# DISCORD SETUP
# =========================

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Store links already posted
posted_links = set()

# =========================
# IMAGE EXTRACTION
# =========================

async def get_image(entry):
    # media_content
    if "media_content" in entry:
        media = entry.media_content
        if media:
            if "url" in media[0]:
                return media[0]["url"]

    # enclosures
    if "enclosures" in entry:
        for enclosure in entry.enclosures:
            if enclosure.get("type", "").startswith("image"):
                return enclosure.get("href")

    # parse HTML for image
    description = entry.get("description", "")
    soup = BeautifulSoup(description, "html.parser")

    img = soup.find("img")

    if img and img.get("src"):
        return img["src"]

    return None

# =========================
# RSS CHECKER
# =========================

@tasks.loop(seconds=CHECK_INTERVAL)
async def check_feeds():
    channel = client.get_channel(CHANNEL_ID)

    if not channel:
        print("Channel not found")
        return

    for feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)

            feed_name = feed.feed.get("title", "RSS Feed")

            for entry in reversed(feed.entries):
                link = entry.get("link")

                if not link:
                    continue

                if link in posted_links:
                    continue

                posted_links.add(link)

                title = entry.get("title", "New Post")
                description = entry.get("description", "")

                # Clean HTML
                soup = BeautifulSoup(description, "html.parser")
                clean_description = soup.get_text()

                # Discord embed limit
                clean_description = clean_description[:4000]

                image_url = await get_image(entry)

                embed = discord.Embed(
                    title=title,
                    url=link,
                    description=clean_description,
                    color=discord.Color.blue()
                )

                embed.set_footer(text=feed_name)

                if image_url:
                    embed.set_image(url=image_url)

                await channel.send(embed=embed)

                print(f"Posted: {title}")

        except Exception as e:
            print(f"Error with feed {feed_url}: {e}")

# =========================
# Ping
# =========================

@bot.command()
async def ping(ctx):
    start = time.time()
    message = await ctx.send("Pinging...")
    end = time.time()

    api_latency = round(bot.latency * 1000)
    msg_latency = round((end - start) * 1000)

    await message.edit(content=f"🏓 Pong!\nAPI latency: {api_latency}ms\nMessage latency: {msg_latency}ms")

    start_time = time.time()

# =========================
# Uptime
# =========================

@bot.command()
async def uptime(ctx):
    seconds = int(time.time() - start_time)
    minutes = seconds // 60
    hours = minutes // 60

    await ctx.send(f"⏱️ Uptime: {hours}h {minutes%60}m {seconds%60}s")

# =========================
# Refresh
# =========================  
    
@bot.command()
async def refresh(ctx):
    await ctx.send("🔄 Checking feeds...")

    await check_feeds()  # or your function logic
    await ctx.send("✅ Done!")

# =========================
# Error
# =========================  

ERROR_CHANNEL_ID = 1485298968404426802

async def log_error(msg):
    channel = bot.get_channel(ERROR_CHANNEL_ID)
    if channel:
        await channel.send(f"⚠️ Error: {msg}")

# =========================
# Help
# =========================  

@bot.command()
async def helpbot(ctx):
    await ctx.send("""
🤖 Bot commands:
!ping - check latency
!uptime - bot uptime
!feeds - show RSS feeds
!refresh - force update
""")

# =========================
# EVENTS
# =========================

@client.event
async def on_ready():
    print(f"Logged in as {client.user}")
    check_feeds.start()

# =========================
# START BOT
# =========================

client.run(TOKEN)
