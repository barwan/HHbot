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
from datetime import datetime, timezone

# ==================== CONFIG ====================

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise ValueError("DISCORD_TOKEN is not set")

CHANNEL_ID = 1485298968404426802
GENERAL_CHANNEL_ID = 1444706522130288881
CHECK_INTERVAL = 120

RSS_FEEDS = (
    "https://www.sydsvenskan.se/feeds/section/lund/feed.xml",
    "https://fetchrss.com/feed/1wKfj4GZ41sg1wKfii1T22YU.rss",
    "https://fetchrss.com/feed/1wKfj4GZ41sg1wScna6Pg6Ec.rss",
    "https://fetchrss.com/feed/1wKfj4GZ41sg1wScpJARnB4U.rss"
)

# ==================== STATIC DATA ====================

BASSHUNTER_SONGS = [
    ("DotA (2006)",                                  "https://www.youtube.com/watch?v=qTsaS1Tm-Ic"),
    ("Vi Sitter I Ventrilo Och Spelar DotA (2006)",  "https://www.youtube.com/watch?v=aTJncWndUB8"),
    ("Boten Anna (2006)",                            "https://www.youtube.com/watch?v=1XK5-n4rR7Q"),
    ("Russia Privjet (2006)",                        "https://www.youtube.com/watch?v=6Lo5QK9NGO4"),
    ("Now You're Gone (2008)",                       "https://www.youtube.com/watch?v=vnuhOxHUHfE"),
    ("All I Ever Wanted (2008)",                     "https://www.youtube.com/watch?v=P3CxhBIrBho"),
    ("Angel in the Night (2008)",                    "https://www.youtube.com/watch?v=DC9Ar8gYNa4"),
    ("I Miss You (2008)",                            "https://www.youtube.com/watch?v=YtGb1UCkgt4"),
    ("Walk on Water (2009)",                         "https://www.youtube.com/watch?v=I4bbXvfxr6A"),
    ("Every Morning (2009)",                         "https://www.youtube.com/watch?v=gSAk__mmNV0"),
    ("Saturday (2010)",                              "https://www.youtube.com/watch?v=ctshBsHejGo"),
    ("Please Don't Go (2010)",                       "https://www.youtube.com/watch?v=h-TZ7tB3C9I"),
    ("Calling Time (2013)",                          "https://www.youtube.com/watch?v=xZttjQjwV-E"),
    ("Northern Light (2012)",                        "https://www.youtube.com/watch?v=RwMalVXESFM"),
    ("Crash & Burn (2013)",                          "https://www.youtube.com/watch?v=ojZ_xW-ybgI"),
]

# Måndag=0, Onsdag=2, Fredag=4, Söndag=6
PING_DAYS = {0, 2, 4, 6}

RANDOM_PINGS = [
    # Skämt
    ("😂 Skämt", "Varför bär skelett inte på väskor? För att de inte har några nerver."),
    ("😂 Skämt", "Vad kallar man en ko utan ben? Köttfärs."),
    ("😂 Skämt", "Vad kallar man en norsk kriminell? En fjordbrytare."),
    ("😂 Skämt", "Vad kallar man en dansk som vinner på lotto? En lycklig granne."),
    ("😂 Skämt", "Varför gick spöket till IKEA? Det behövde ett nytt lakan."),
    ("😂 Skämt", "Vad sa havet till stranden? Ingenting, det vinkade bara."),
    ("😂 Skämt", "Vad kallar man en snögubbe i juli? En pöl."),
    ("😂 Skämt", "Varför är matematikböcker så ledsna? De har så många problem."),
    ("😂 Skämt", "Hur vet man att en elefant har varit i kylskåpet? Det finns fotspår i smöret."),
    ("😂 Skämt", "Varför cyklar inte elefanter? De passar inte i cykelbyxor."),
    # Fakta
    ("🧠 Slumpmässig fakta", "En bläckfisk har tre hjärtan och blått blod."),
    ("🧠 Slumpmässig fakta", "Sverige har fler öar än något annat land i Europa – över 220 000 stycken."),
    ("🧠 Slumpmässig fakta", "Honungsbin flyger i snitt 88 000 km för att producera ett kilo honung."),
    ("🧠 Slumpmässig fakta", "Det tar 8 minuter och 20 sekunder för ljuset att nå jorden från solen."),
    ("🧠 Slumpmässig fakta", "Katter sover ungefär 16 timmar om dagen. Lyckliga katter."),
    ("🧠 Slumpmässig fakta", "En snigelsusp kan resa upp till 50 meter på en timme – om den verkligen anstränger sig."),
    ("🧠 Slumpmässig fakta", "Wombaters bajsar i kubform. Det är det enda djuret som gör det."),
    ("🧠 Slumpmässig fakta", "IKEA är uppkallad efter grundarens initialer och hemby: Ingvar Kamprad, Elmtaryd, Agunnaryd."),
    ("🧠 Slumpmässig fakta", "En grupp flamingos kallas en flamboyance. Passande."),
    ("🧠 Slumpmässig fakta", "Kroppen innehåller tillräckligt med järn för att smida en 8 cm lång spik."),
    # Frågor / interaktion
    ("🤔 Fråga för dagen", "Om du kunde äta en sak resten av livet, vad skulle det vara? Svara nedan 👇"),
    ("🤔 Fråga för dagen", "Vad är det bästa med att bo i Sverige? Svara nedan 👇"),
    ("🤔 Fråga för dagen", "Pizza eller tacos? Det här avgörs EN GÅNG FÖR ALLA. Svara nedan 👇"),
    ("🤔 Fråga för dagen", "Vilket är det bästa TV-spelet någonsin? Fight me. Svara nedan 👇"),
    ("🤔 Fråga för dagen", "Om du fick en superförmåga, vilken skulle du välja? Svara nedan 👇"),
    # Random/roligt
    ("💡 Dagens visdom", "Om du inte kan förklara något enkelt förstår du det inte tillräckligt bra. – Einstein (typ)"),
    ("💡 Dagens visdom", "En dag är 86 400 sekunder. Vad gör du med dina?"),
    ("💡 Dagens visdom", "Kom ihåg: även en bruten klocka har rätt två gånger om dagen."),
    ("🎲 Slumpen säger", "Dagens lyckliga nummer är: " + str(random.randint(1, 100))),
    ("🎲 Slumpen säger", "Sannolikheten att du ens existerar är 1 på 400 biljoner. Du vann redan lotteriet."),
    ("🎵 Basshunter-hörna", "Påminnelse: Dota av Basshunter är ett mästerverk och det är inte diskuterbart."),
    ("🇸🇪 Svenska klassiker", "Ingen fredag utan att påminna om att surströmming faktiskt är god. (Lögn.)"),
    ("☕ Påminnelse", "Har du druckit vatten idag? Drick vatten. Gå nu."),
    ("🌙 Kväll-check", "Vad har du åstadkommit idag? Även 'ingenting' räknas som ett val."),
]

JOKES = [
    "Varför bär skelett inte på väskor? För att de inte har några nerver.",
    "Vad kallas en sovande dinosaurie? En dinorsar.",
    "Varför fick fågelskrämman ett pris? För att den var enastående i sitt fält.",
    "Vad kallar man en blind dinosaurie? Doyouthinkhesaurus.",
    "Varför cyklade cykeln inte längre? Den var trött på att köra runt i cirklar.",
    "Vad sa havet till stranden? Ingenting, det vinkade bara.",
    "Varför är matematikböcker så ledsna? De har så många problem.",
    "Vad kallar man en ko utan ben? Köttfärs.",
    "Hur vet man att en elefant har varit i kylskåpet? Det finns fotspår i smöret.",
    "Varför fick tomaten rött? För att den såg salladskläderna.",
    "Vad kallar man en fisk utan ögon? En fsk.",
    "Varför kan man inte lita på atomer? De hittar på allt.",
    "Vad sa ena väggen till den andra väggen? Vi ses i hörnet.",
    "Varför är sjörövarnas pirat så billig? Den är alltid på REA.",
    "Vad kallar man en björn utan tänder? En gummibasse.",
    "Varför gick datorn till doktorn? Den hade ett virus.",
    "Vad kallar man en lat känguru? En pungsofa.",
    "Varför är Sverigekartan alltid ledsen? För att den alltid pekar norrut.",
    "Vad sa klockan till bältet? Du omger mig men jag tickar fortfarande.",
    "Varför kan inte cykeln stå själv? Den är tvåhjuling och behöver stöd.",
    "Vad kallar man en snögubbe i juli? En pöl.",
    "Varför fick fotbollsplanen ont? För att det stod elva man på den.",
    "Vad sa tallriken till skeden? Sluta röra om i mina känslor.",
    "Varför är kontoret alltid kallt? För att det är fullt av fläktar.",
    "Vad kallar man en norsk kriminell? En fjordbrytare.",
    "Varför sover fiskar aldrig? För att de är rädda att drömma om krokarna.",
    "Vad sa vänstra handen till den högra? Du är alltid så rätt.",
    "Varför cyklar inte elefanter? De passar inte i cykelbyxor.",
    "Vad kallar man en dansk som vinner på lotto? En lycklig granne.",
    "Varför gick spöket till IKEA? Det behövde ett nytt lakan.",
]

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

def load_ping_state():
    """Load last ping date"""
    try:
        if Path("ping_state.json").exists():
            with open("ping_state.json") as f:
                return json.load(f).get("last_ping", "")
    except:
        pass
    return ""

def save_ping_state(date_str):
    """Save last ping date"""
    try:
        with open("ping_state.json", "w") as f:
            json.dump({"last_ping": date_str}, f)
    except:
        pass

posted_links = load_posted_links()
last_ping_date = load_ping_state()
task_started = False
start_time = time.time()

# ==================== UTILITIES ====================

def get_image(entry):
    """Extract image URL from feed entry"""
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

        for entry in list(reversed(feed.entries))[:15]:
            link = entry.get("link")
            if not link or link in posted_links:
                continue

            posted_links.add(link)

            try:
                title = entry.get("title", "Post")[:150]
                desc = entry.get("description", "")
                clean = BeautifulSoup(desc, "html.parser").get_text()[:400] if desc else ""
                image_url = get_image(entry)

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

        if total > 0:
            save_posted_links(posted_links)
            print(f"Posted {total} new articles")

    except Exception as e:
        print(f"Run error: {e}")

# ==================== EVERYONE PING CHECKER ====================

async def check_everyone_ping():
    """Post @everyone with random content on Mon/Wed/Fri/Sun (once per day)"""
    global last_ping_date
    try:
        now = datetime.now(timezone.utc)
        if now.weekday() not in PING_DAYS:
            return
        today_str = now.strftime("%Y-%m-%d")
        if today_str == last_ping_date:
            return

        title, content = random.choice(RANDOM_PINGS)

        # Friday always gets the extra fredag message first
        channel = await bot.fetch_channel(GENERAL_CHANNEL_ID)
        if now.weekday() == 4:
            await channel.send("@everyone Nu e det fredag! 🎉")

        embed = discord.Embed(title=title, description=content, color=0xFF6600)
        await channel.send("@everyone", embed=embed)

        last_ping_date = today_str
        save_ping_state(today_str)
        print(f"✅ Everyone ping posted for {today_str} (day {now.weekday()})")
    except Exception as e:
        print(f"Ping check error: {e}")

# ==================== BACKGROUND TASK ====================

@tasks.loop(seconds=CHECK_INTERVAL)
async def check_feeds():
    """Background task to check feeds and everyone pings periodically"""
    await run_feeds()
    await check_everyone_ping()

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
    uptime_s = int(time.time() - start_time)
    h, m, s = uptime_s // 3600, (uptime_s % 3600) // 60, uptime_s % 60
    embed = discord.Embed(title="🟢 Status", color=0x0099FF)
    embed.add_field(name="Running", value="✅ Yes", inline=True)
    embed.add_field(name="Posts Tracked", value=str(len(posted_links)), inline=True)
    embed.add_field(name="Uptime", value=f"{h}h {m}m {s}s", inline=True)
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

# ==================== BASSHUNTER ====================

@bot.command()
async def basshunter(ctx):
    """Send a random Basshunter song with YouTube link"""
    name, url = random.choice(BASSHUNTER_SONGS)
    embed = discord.Embed(
        title=f"🎧 {name}",
        url=url,
        description=f"[▶️ Play on YouTube]({url})",
        color=0x9B59B6
    )
    embed.set_footer(text="NOW WE'RE GOING TO SWEDEN 🇸🇪")
    await ctx.send(embed=embed)

# ==================== JOKES ====================

@bot.command()
async def joke(ctx):
    """Tell a random shitty joke"""
    embed = discord.Embed(
        title="😂 Joke",
        description=random.choice(JOKES),
        color=0xF1C40F
    )
    await ctx.send(embed=embed)

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
async def choose(ctx, *, options=None):
    """Pick one of your options - usage: !choose pizza or burger or sushi"""
    if not options or " or " not in options.lower():
        embed = discord.Embed(title="🤔 Choose", description="Usage: `!choose option1 or option2 or option3`", color=0x0099FF)
        await ctx.send(embed=embed)
        return
    choices = [o.strip() for o in options.split(" or ") if o.strip()]
    if len(choices) < 2:
        await ctx.send("Give me at least 2 options separated by ` or `!")
        return
    pick = random.choice(choices)
    embed = discord.Embed(title="🤔 I Choose...", description=f"**{pick}**", color=0x2ECC71)
    await ctx.send(embed=embed)

@bot.command()
async def games(ctx):
    """Show available games"""
    embed = discord.Embed(title="🎮 Games", color=0x0099FF)
    embed.add_field(name="!rps <choice>", value="Rock Paper Scissors (rock/paper/scissors)", inline=False)
    embed.add_field(name="!coin", value="Flip a coin (heads/tails)", inline=False)
    embed.add_field(name="!dice [sides]", value="Roll a dice (default 6, max 100)", inline=False)
    embed.add_field(name="!eightball <question>", value="Ask the magic 8-ball", inline=False)
    embed.add_field(name="!choose <a or b or c>", value="Let the bot decide for you", inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def help(ctx):
    """Show available commands"""
    embed = discord.Embed(title="🤖 Commands", color=0x0099FF)
    embed.add_field(name="📡 Feeds", value="!refresh • !stats • !status", inline=False)
    embed.add_field(name="⚙️ Info", value="!settings • !help", inline=False)
    embed.add_field(name="🎮 Games", value="!rps • !coin • !dice • !eightball • !choose • !games", inline=False)
    embed.add_field(name="🎵 Fun", value="!basshunter • !joke", inline=False)
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

    await bot.change_presence(activity=discord.Game(name="!help för kommandon"))

    if not task_started:
        try:
            check_feeds.start()
            task_started = True
            print("✅ Feed checker started")
        except Exception as e:
            print(f"Error starting feed checker: {e}")

@bot.event
async def on_command_error(ctx, error):
    """Silently ignore unknown commands and bad args to save resources"""
    if isinstance(error, (commands.CommandNotFound, commands.BadArgument, commands.MissingRequiredArgument)):
        return
    print(f"Command error: {error}")

# ==================== RUN ====================

if __name__ == "__main__":
    bot.run(TOKEN)
