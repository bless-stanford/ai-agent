import os
import discord
import logging
from discord.ext import commands
from dotenv import load_dotenv
from agent import MistralAgent
from services.box_service import BoxService
from services.gmail_service import GmailService
from services.dropbox_service import DropboxService
from services.google_drive_service import GoogleDriveService
from services.google_calendar_service import GoogleCalendarService
from server import start_server 
from datetime import datetime, timedelta

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

# Initialize agent with Semantic Kernel and cloud storage plugins
agent = MistralAgent()

# Get the token from the environment variables
token = os.getenv("DISCORD_TOKEN")

# Initialize cloud service instances
box_service = BoxService()
gmail_service = GmailService()
dropbox_service = DropboxService()
google_drive_service = GoogleDriveService()
google_calendar_service = GoogleCalendarService()

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
    # Ignore messages from self or other bots to prevent infinite loops
    if message.author.bot:
        return
    
    # If the message starts with the command prefix, only process it as a command
    # and don't try to handle it with the agent
    if message.content.startswith(PREFIX):
        await bot.process_commands(message)
        return
    
    # Only process non-command messages with the agent
    logger.info(f"Processing message from {message.author}: {message.content}")
    
    try:
        async with message.channel.typing():
            # The agent will now use Semantic Kernel to process natural language
            # requests related to cloud storage, without requiring specific commands
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
        # Get authorization URL for the user
        auth_url = await box_service.get_authorization_url(str(ctx.author.id))
        
        # Send the URL as a DM to the user
        await ctx.author.send(f"Please authorize access to your Box account by clicking this link: {auth_url}")
        await ctx.send("I've sent you a DM with the authorization link!")
    except Exception as e:
        error_msg = f"Error generating Box authorization link: {str(e)}"
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

@bot.command(name="dropbox-upload", help="Upload a file to Dropbox")
async def dropbox_upload(ctx):
    """
    Uploads an attached file to Dropbox.
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
        # Upload to Dropbox
        dropbox_service = DropboxService()
        dropbox_path = f"/{attachment.filename}"  # Will be stored in root folder
        file_info = await dropbox_service.upload_file(str(ctx.author.id), file_path, dropbox_path)
        
        # Send confirmation
        await ctx.send(f"File uploaded to Dropbox! Path: {file_info['path_display']}")
        
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

@bot.command(name="authorize-dropbox", help="Authorize the bot to access your Dropbox account")
async def authorize_dropbox(ctx):
    """
    Sends a Dropbox authorization link to the user via DM.
    """
    try:
        # Get authorization URL for the user
        auth_url = await dropbox_service.get_authorization_url(str(ctx.author.id))
        
        # Send the URL as a DM to the user
        await ctx.author.send(f"Please authorize access to your Dropbox account by clicking this link: {auth_url}")
        await ctx.send("I've sent you a DM with the authorization link!")
    except Exception as e:
        error_msg = f"Error generating Dropbox authorization link: {str(e)}"
        logger.error(error_msg)
        await ctx.send(error_msg[:1900])

@bot.command(name="authorize-gdrive", help="Authorize the bot to access your Google Drive account")
async def authorize_gdrive(ctx):
    """
    Sends a Google Drive authorization link to the user via DM.
    """
    try:
        # Get authorization URL for the user
        auth_url = await google_drive_service.get_authorization_url(str(ctx.author.id))
        
        # Send the URL as a DM to the user
        await ctx.author.send(f"Please authorize access to your Google Drive account by clicking this link: {auth_url}")
        await ctx.send("I've sent you a DM with the authorization link!")
    except Exception as e:
        error_msg = f"Error generating Google Drive authorization link: {str(e)}"
        logger.error(error_msg)
        await ctx.send(error_msg[:1900])

    
@bot.command(name="authorize-gmail", help="Authorize the bot to access your Gmail account")
async def authorize_gmail(ctx):
    """
    Sends a Gmail authorization link to the user via DM.
    """
    try:
        # Get authorization URL for the user
        auth_url = await gmail_service.get_authorization_url(str(ctx.author.id))
        
        # Send the URL as a DM to the user
        await ctx.author.send(f"Please authorize access to your Gmail account by clicking this link: {auth_url}")
        await ctx.send("I've sent you a DM with the authorization link!")
    except Exception as e:
        error_msg = f"Error generating Gmail authorization link: {str(e)}"
        logger.error(error_msg)
        await ctx.send(error_msg[:1900])

@bot.command(name="gdrive-upload", help="Upload a file to Google Drive")
async def gdrive_upload(ctx):
    """
    Uploads an attached file to Google Drive.
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
        # Upload to Google Drive
        file_info = await google_drive_service.upload_file(
            str(ctx.author.id), 
            file_path, 
            attachment.filename
        )
        
        # Send confirmation with view link
        view_link = file_info.get('webViewLink', 'No view link available')
        await ctx.send(f"File uploaded to Google Drive! File ID: {file_info['id']}\nView link: {view_link}")
        
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

@bot.command(name="gcalendar-create", help="Create a new calendar")
async def gcalendar_create(ctx, *, calendar_name=None):
    """
    Creates a new calendar in the user's Google Calendar account.
    
    Usage: !gcalendar-create My New Calendar
    """
    if not calendar_name:
        await ctx.send("Please provide a name for the calendar.\nUsage: `!gcalendar-create My New Calendar`")
        return
    
    try:
        calendar_id = await google_calendar_service.create_calendar(str(ctx.author.id), calendar_name)
        
        await ctx.send(f"Calendar created successfully!\nName: {calendar_name}\nID: {calendar_id}")
    except Exception as e:
        error_msg = f"Error creating calendar: {str(e)}"
        logger.error(error_msg)
        await ctx.send(error_msg[:1900])

@bot.command(name="gcalendar-add-event", help="Add an event to your Google Calendar")
async def gcalendar_add_event(ctx, *, event_data=None):
    """
    Adds an event to the user's Google Calendar.
    
    Usage: !gcalendar-add-event title | description | start_time | end_time | location
    Example: !gcalendar-add-event Team Meeting | Weekly sync | 2024-03-15T14:00:00 | 2024-03-15T15:00:00 | Conference Room
    """
    if not event_data:
        await ctx.send("Please provide event details in this format:\n`!gcalendar-add-event title | description | start_time | end_time | location`\n\nExample: `!gcalendar-add-event Team Meeting | Weekly sync | 2024-03-15T14:00:00 | 2024-03-15T15:00:00 | Conference Room`")
        return
    
    try:
        # Parse event data
        parts = event_data.split('|')
        if len(parts) < 4:
            await ctx.send("Please provide at least title, description, start time, and end time, separated by '|'")
            return
        
        title = parts[0].strip()
        description = parts[1].strip()
        start_time = parts[2].strip()
        end_time = parts[3].strip()
        location = parts[4].strip() if len(parts) > 4 else ""
        
        # Create event object
        event = {
            "summary": title,
            "description": description,
            "location": location,
            "start": {
                "dateTime": start_time,
                "timeZone": "UTC"
            },
            "end": {
                "dateTime": end_time,
                "timeZone": "UTC"
            }
        }
        
        # Add the event
        result = await google_calendar_service.add_event(str(ctx.author.id), event)
        
        # Create embed for nice display
        embed = discord.Embed(
            title="Event Added to Google Calendar",
            description=description,
            color=discord.Color.green()
        )
        
        embed.add_field(name="Title", value=title, inline=False)
        embed.add_field(name="Start", value=start_time, inline=True)
        embed.add_field(name="End", value=end_time, inline=True)
        if location:
            embed.add_field(name="Location", value=location, inline=False)
            
        event_link = f"https://calendar.google.com/calendar/event?eid={result.get('id', 'unknown')}"
        embed.add_field(name="Calendar Link", value=f"[Open in Google Calendar]({event_link})", inline=False)
        
        await ctx.send(embed=embed)
    except Exception as e:
        error_msg = f"Error adding event to Google Calendar: {str(e)}"
        logger.error(error_msg)
        await ctx.send(error_msg[:1900])

@bot.command(name="gcalendar-events", help="Get your upcoming events from Google Calendar")
async def gcalendar_events(ctx, days: int = 7):
    """
    Gets the user's upcoming events from Google Calendar.
    
    Args:
        days: Number of days to look ahead (default: 7)
    
    Usage: !gcalendar-events 
    Alternative: !gcalendar-events 14
    """
    try:
        # Calculate date range
        start_date = datetime.utcnow()
        end_date = start_date + timedelta(days=days)
        
        # Get events
        events = await google_calendar_service.get_events(
            str(ctx.author.id),
            start_date,
            end_date,
            max_results=10
        )
        
        if not events:
            await ctx.send(f"No events found in the next {days} days.")
            return
        
        # Create an embed for nice formatting
        embed = discord.Embed(
            title=f"Your Calendar: Next {days} Days",
            description=f"Showing your upcoming events from {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}",
            color=discord.Color.blue()
        )
        
        # Add events to the embed
        for event in events:
            # Get event details
            title = event.get('summary', 'No title')
            
            # Format start time
            start = event.get('start', {})
            if 'dateTime' in start:
                start_time = datetime.fromisoformat(start['dateTime'].replace('Z', '+00:00'))
                start_str = start_time.strftime('%Y-%m-%d %H:%M')
            elif 'date' in start:
                start_str = f"{start['date']} (All day)"
            else:
                start_str = "Unknown time"
            
            # Format location if available
            location = event.get('location', '')
            location_str = f"\nLocation: {location}" if location else ""
            
            # Add to embed
            embed.add_field(
                name=title,
                value=f"When: {start_str}{location_str}",
                inline=False
            )
        
        await ctx.send(embed=embed)
    except Exception as e:
        error_msg = f"Error retrieving events from Google Calendar: {str(e)}"
        logger.error(error_msg)
        await ctx.send(error_msg[:1900])

@bot.command(name="gcalendar-delete", help="Delete an event from your Google Calendar")
async def gcalendar_delete(ctx, *, event_query=None):
    """
    Deletes an event from the user's Google Calendar by searching for it.
    
    Usage: !gcalendar-delete Team Meeting
    Alternative: !gcalendar-delete [event-id]
    """
    if not event_query:
        await ctx.send("Please provide an event title or event ID to delete.\nUsage: `!gcalendar-delete Team Meeting`")
        return
    
    try:
        result = await google_calendar_service.delete_event(str(ctx.author.id), event_query)
        await ctx.send(result)
    except Exception as e:
        error_msg = f"Error deleting event: {str(e)}"
        logger.error(error_msg)
        await ctx.send(error_msg[:1900])

@bot.command(name="gcalendar-update", help="Update an existing event in your Google Calendar")
async def gcalendar_update(ctx, event_id=None, *, event_data=None):
    """
    Updates an existing event in the user's Google Calendar.
    
    Usage: !gcalendar-update event_id title | description | start_time | end_time
    Example: !gcalendar-update abc123 Updated Meeting | New description | 2024-03-15T15:00:00 | 2024-03-15T16:00:00
    """
    if not event_id or not event_data:
        await ctx.send("Please provide both an event ID and updated event details.\nUsage: `!gcalendar-update event_id title | description | start_time | end_time`")
        return
    
    try:
        # Parse event data
        parts = event_data.split('|')
        if len(parts) < 4:
            await ctx.send("Please provide at least title, description, start time, and end time, separated by '|'")
            return
        
        title = parts[0].strip()
        description = parts[1].strip()
        start_time = parts[2].strip()
        end_time = parts[3].strip()
        
        result = await google_calendar_service.update_event(
            str(ctx.author.id),
            event_id,
            {
                "summary": title,
                "description": description,
                "start": {
                    "dateTime": start_time,
                    "timeZone": "UTC"
                },
                "end": {
                    "dateTime": end_time,
                    "timeZone": "UTC"
                }
            }
        )
        
        await ctx.send(f"Event updated successfully!\nTitle: {result.get('summary')}\nID: {result.get('id')}")
    except Exception as e:
        error_msg = f"Error updating event: {str(e)}"
        logger.error(error_msg)
        await ctx.send(error_msg[:1900])

@bot.command(name="gcalendar-share", help="Share a calendar event with another user")
async def gcalendar_share(ctx, event_id=None, *, email=None):
    """
    Shares a calendar event with another user by adding them as an attendee.
    
    Usage: !gcalendar-share event_id email@example.com
    """
    if not event_id or not email:
        await ctx.send("Please provide both an event ID and an email to share with.\nUsage: `!gcalendar-share event_id email@example.com`")
        return
    
    try:
        result = await google_calendar_service.share_event(str(ctx.author.id), event_id, email)
        await ctx.send(f"Event shared successfully with {email}!")
    except Exception as e:
        error_msg = f"Error sharing event: {str(e)}"
        logger.error(error_msg)
        await ctx.send(error_msg[:1900])

@bot.command(name="cloud-status", help="Check your cloud service connections")
async def cloud_status(ctx):
    """
    Checks and reports the connection status for configured cloud services.
    """
    embed = discord.Embed(
        title="Cloud Services Status",
        description="Current status of your connected cloud services",
        color=discord.Color.blue()
    )
    
    embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.avatar.url if ctx.author.avatar else None)
    embed.set_footer(text="Use !authorize-* commands to connect services")
    embed.timestamp = discord.utils.utcnow()
    
    # Check Box connection
    try:
        # Try to load the token to see if the user is authenticated
        box_token = await box_service._load_token(str(ctx.author.id))
        if box_token:
            embed.add_field(
                name="Box Status", 
                value="✅ Connected", 
                inline=False
            )
        else:
            embed.add_field(
                name="Box Status", 
                value="❌ Not connected\n*Use !authorize-box to connect*", 
                inline=False
            )
    except Exception as e:
        embed.add_field(
            name="Box Status", 
            value=f"⚠️ Error checking connection\n```{str(e)}```", 
            inline=False
        )
    
    # Check Dropbox connection
    try:
        # Try to load the token to see if the user is authenticated
        dropbox_token = await dropbox_service._load_token(str(ctx.author.id))
        if dropbox_token:
            embed.add_field(
                name="Dropbox Status", 
                value="✅ Connected", 
                inline=False
            )
        else:
            embed.add_field(
                name="Dropbox Status", 
                value="❌ Not connected\n*Use !authorize-dropbox to connect*", 
                inline=False
            )
    except Exception as e:
        embed.add_field(
            name="Dropbox Status", 
            value=f"⚠️ Error checking connection\n```{str(e)}```", 
            inline=False
        )

    # Check Google Drive connection
    try:
        # Try to load the token to see if the user is authenticated
        gdrive_token = await google_drive_service._load_token(str(ctx.author.id))
        if gdrive_token:
            embed.add_field(
                name="Google Drive Status", 
                value="✅ Connected", 
                inline=False
            )
        else:
            embed.add_field(
                name="Google Drive Status", 
                value="❌ Not connected\n*Use !authorize-gdrive to connect*", 
                inline=False
            )
    except Exception as e:
        embed.add_field(
            name="Google Drive Status", 
            value=f"⚠️ Error checking connection\n```{str(e)}```", 
            inline=False
        )

    # Check Gmail connection
    try:
        # Try to load the token to see if the user is authenticated
        gmail_token = await gmail_service._load_token(str(ctx.author.id))
        if gmail_token:
            embed.add_field(
                name="Gmail Status", 
                value="✅ Connected", 
                inline=False
            )
        else:
            embed.add_field(
                name="Gmail Status", 
                value="❌ Not connected\n*Use !authorize-gmail to connect*", 
                inline=False
            )
    except Exception as e:
        embed.add_field(
            name="Gmail Status", 
            value=f"⚠️ Error checking connection\n```{str(e)}```", 
            inline=False
        )
    
    await ctx.send(embed=embed)

# Start the web server in the background
server_thread = start_server(bot)

# Start the bot
bot.run(token)