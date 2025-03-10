import os
import discord
import logging
from discord.ext import commands
from dotenv import load_dotenv
from agent import MistralAgent
from services.box_service import BoxService
from server import start_server 

PREFIX = "!"

# Setup logging
logger = logging.getLogger("discord")
logging.basicConfig(level=logging.INFO, 
                    format='[%(asctime)s] %(levelname)s - %(name)s: %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')

# Load the environment variables
load_dotenv()

# Create the bot with all intents
intents = discord.Intents.all()
bot = commands.Bot(command_prefix=PREFIX, intents=intents)

# Initialize agent with Semantic Kernel and Box plugins
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
    if message.author.bot or message.content.startswith(PREFIX):
        return

    # Log the incoming message
    logger.info(f"Processing message from {message.author}: {message.content}")
    
    try:
        async with message.channel.typing():
            # The agent will now use Semantic Kernel to process natural language
            # requests related to Box, without requiring specific commands
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

@bot.command(name="authorize-box", help="Authorize the bot to access your Box account")
async def authorize_box(ctx):
    """
    Sends a Box authorization link to the user via DM.
    """
    try:
        # Create Box service
        box_service = BoxService()
        
        # Get authorization URL for the user
        auth_url = await box_service.get_authorization_url(str(ctx.author.id))
        
        # Send the URL as a DM to the user
        await ctx.author.send(f"Please authorize access to your Box account by clicking this link: {auth_url}")
        await ctx.send("I've sent you a DM with the authorization link!")
    except Exception as e:
        error_msg = f"Error generating authorization link: {str(e)}"
        logger.error(error_msg)
        await ctx.send(error_msg[:1900])

@bot.command(name="box-upload", help="Upload a file to Box")
async def box_upload(ctx):
    """
    Uploads an attached file to Box.
    """
    if not ctx.message.attachments:
        await ctx.send("Please attach a file to upload.")
        return
    
    attachment = ctx.message.attachments[0]
    
    # Create temp directory if it doesn't exist
    if not os.path.exists("temp"):
        os.makedirs("temp")
    
    # Download the attachment
    file_path = f"temp/{attachment.filename}"
    await attachment.save(file_path)
    
    try:
        # Upload to Box
        box_service = BoxService()
        file_info = await box_service.upload_file(str(ctx.author.id), file_path, attachment.filename)
        
        # Send confirmation
        await ctx.send(f"File uploaded to Box! File ID: {file_info['id']}")
        
        # Clean up temp file
        if os.path.exists(file_path):
            os.remove(file_path)
    except Exception as e:
        error_msg = f"Error uploading file: {str(e)}"
        logger.error(error_msg)
        await ctx.send(error_msg[:1900])
        
        # Clean up temp file on error too
        if os.path.exists(file_path):
            os.remove(file_path)

# Start the web server in the background
server_thread = start_server(bot)

# Start the bot
bot.run(token)