import os
import discord
import logging
from discord.ext import commands
from dotenv import load_dotenv
from agent import MistralAgent

PREFIX = "!"

# Setup logging
logger = logging.getLogger("discord")

# Load the environment variables
load_dotenv()

# Create the bot with all intents
intents = discord.Intents.all()
bot = commands.Bot(command_prefix=PREFIX, intents=intents)

agent = MistralAgent()

# Get the token from the environment variables
token = os.getenv("DISCORD_TOKEN")

async def send_split_message(message: discord.Message, response: str | list[str]):
    """
    Sends a message that might be longer than Discord's character limit.
    Handles both string and list responses from the agent.
    """
    try:
        if isinstance(response, str):
            if len(response) <= 2000:
                await message.reply(response)
            else:
                # Send first chunk as reply
                chunks = [response[i:i+1900] for i in range(0, len(response), 1900)]
                await message.reply(chunks[0])
                # Send remaining chunks as regular messages
                for chunk in chunks[1:]:
                    await message.channel.send(chunk)
        elif isinstance(response, list):
            # Send first chunk as reply
            if response:
                await message.reply(response[0])
                # Send remaining chunks as regular messages
                for chunk in response[1:]:
                    await message.channel.send(chunk)
    except discord.errors.HTTPException as e:
        error_msg = f"Error sending message: {str(e)}"
        logger.error(error_msg)
        await message.channel.send(error_msg[:1900])

@bot.event
async def on_ready():
    """
    Called when the client is done preparing the data received from Discord.
    """
    logger.info(f"{bot.user} has connected to Discord!")

@bot.event
async def on_message(message: discord.Message):
    """
    Called when a message is sent in any channel the bot can see.
    """
    # Process commands first
    await bot.process_commands(message)

    # Ignore messages from self or other bots to prevent infinite loops
    if message.author.bot or message.content.startswith("!"):
        return

    # Log the incoming message
    logger.info(f"Processing message from {message.author}: {message.content}")
    
    try:
        async with message.channel.typing():
            response = await agent.run(message)
            await send_split_message(message, response)
    except Exception as e:
        error_msg = f"An error occurred while processing the message: {str(e)}"
        logger.error(error_msg)
        await message.channel.send(error_msg[:1900])

@bot.command(name="ping", help="Pings the bot.")
async def ping(ctx, *, arg=None):
    if arg is None:
        await ctx.send("Pong!")
    else:
        await ctx.send(f"Pong! Your argument was {arg}")

# Start the bot
bot.run(token)