from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import uvicorn
from services.box_service import BoxService
from services.dropbox_service import DropboxService
from helpers.token_helpers import TokenEncryptionHelper
import asyncio
import logging
import threading

# Setup logging
logger = logging.getLogger("oauth_server")

app = FastAPI()
box_service = BoxService()
dropbox_service = DropboxService()

# This will be set from bot.py
bot = None

# Reusable HTML template function
def get_success_html(service_name):
    """
    Generate HTML for successful authorization.
    
    Args:
        service_name: The name of the service (Box, Dropbox, etc.)
        
    Returns:
        str: HTML content for the success page
    """
    return f"""
    <!DOCTYPE html>
    <html>
        <head>
            <title>Authorization Successful</title>
            <style>
                body {{
                    font-family: Arial, sans-serif;
                    text-align: center;
                    padding: 50px;
                    background-color: #f8f9fa;
                }}
                .container {{
                    background-color: white;
                    border-radius: 8px;
                    padding: 30px;
                    box-shadow: 0 4px 6px rgba(0,0,0,0.1);
                    max-width: 500px;
                    margin: 0 auto;
                }}
                .success {{
                    color: #28a745;
                    font-size: 24px;
                    margin-bottom: 20px;
                }}
                .message {{
                    font-size: 18px;
                    margin-bottom: 15px;
                    color: #343a40;
                }}
                .footer {{
                    margin-top: 30px;
                    font-size: 14px;
                    color: #6c757d;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="success">✅ Authorization Successful!</div>
                <div class="message">Your {service_name} account has been connected to the Discord bot.</div>
                <div class="message">You can close this window and return to Discord.</div>
                <div class="footer">You will also receive a confirmation message in Discord.</div>
            </div>
        </body>
    </html>
    """

@app.get("/")
async def root():
    return {"message": "OAuth Callback Server for Box and Dropbox"}

@app.get("/box/callback")
async def box_callback(code: str, state: str):
    """
    Handle the OAuth callback from Box.
    
    This endpoint receives the authorization code from Box after a user
    authorizes the application. It exchanges the code for access and 
    refresh tokens, stores them securely, and notifies the user.
    """
    try:
        # Get user ID from state
        user_id = TokenEncryptionHelper.decrypt_token(state, box_service.encryption_key)
        logger.info(f"Received Box callback for user {user_id}")
        
        # Handle the callback - this stores the tokens
        await box_service.handle_auth_callback(state, code)
        
        # Notify the user through Discord
        if bot:
            # Schedule the notification in the bot's event loop
            asyncio.run_coroutine_threadsafe(notify_user(user_id, "Box"), bot.loop)
        
        # Use the reusable HTML template
        html_content = get_success_html("Box")
        
        return HTMLResponse(content=html_content)
    except Exception as e:
        logger.error(f"Error in Box callback: {str(e)}")
        return {"error": str(e)}

@app.get("/dropbox/callback")
async def dropbox_callback(code: str, state: str):
    """
    Handle the OAuth callback from Dropbox.
    
    This endpoint receives the authorization code from Dropbox after a user
    authorizes the application. It exchanges the code for access and 
    refresh tokens, stores them securely, and notifies the user.
    """
    try:
        # Get user ID from state
        user_id = TokenEncryptionHelper.decrypt_token(state, dropbox_service.encryption_key)
        logger.info(f"Received Dropbox callback for user {user_id}")
        
        # Handle the callback - this stores the tokens
        await dropbox_service.handle_auth_callback(state, code)
        
        # Notify the user through Discord
        if bot:
            # Schedule the notification in the bot's event loop
            asyncio.run_coroutine_threadsafe(notify_user(user_id, "Dropbox"), bot.loop)
        
        # Use the reusable HTML template
        html_content = get_success_html("Dropbox")
        
        return HTMLResponse(content=html_content)
    except Exception as e:
        logger.error(f"Error in Dropbox callback: {str(e)}")
        return {"error": str(e)}

async def notify_user(user_id, service_name):
    """
    Send a Discord message to notify the user that authorization was successful.
    
    Args:
        user_id: The Discord user ID
        service_name: The name of the service (Box, Dropbox, etc.)
    """
    try:
        user = await bot.fetch_user(int(user_id))
        if user:
            await user.send(f"✅ Your {service_name} account has been successfully connected! You can now use {service_name} commands.")
    except Exception as e:
        logger.error(f"Error notifying user about {service_name}: {str(e)}")

def start_server(bot_instance=None):
    """
    Start the FastAPI server in a background thread.
    
    Args:
        bot_instance: The Discord bot instance, used for user notifications
    
    Returns:
        thread: The thread running the server
    """
    global bot
    bot = bot_instance
    
    # Start the server in a separate thread
    def run_server():
        logger.info("Starting OAuth callback server on port 8000")
        uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
    
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    logger.info("Server thread started")
    
    return server_thread