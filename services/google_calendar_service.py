import os
import json
import logging
from datetime import datetime, timedelta
from urllib.parse import urlencode
from dotenv import load_dotenv

import requests
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from helpers.token_helpers import (
    TokenEncryptionHelper, 
    TokenStorageManager, 
    create_token_record,
    load_or_generate_encryption_key
)

# Setup logging
logger = logging.getLogger("google_calendar_service")

# Constants for platform and service
PLATFORM = "Google"
SERVICE = "GoogleCalendarService"

# API URLs
GOOGLE_AUTH_BASE_URL = "https://accounts.google.com/o/oauth2/"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"

# Scopes for Google Calendar API
SCOPES = ['https://www.googleapis.com/auth/calendar']


class GoogleCalendarService:
    def __init__(self, config=None):
        """
        Initialize the Google Calendar service with configuration.
        
        Args:
            config: Configuration dictionary or None to load from .env
        """
        if config is None:
            load_dotenv()
            self.client_id = os.getenv("GOOGLE_CLIENT_ID")
            self.client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
            self.redirect_uri = os.getenv("GOOGLE_CALENDAR_REDIRECT_URI")
            self.app_name = os.getenv("GOOGLE_APP_NAME", "GoogleCalendarApp")
            
            # Get or generate encryption key using our helper
            self.encryption_key = load_or_generate_encryption_key()
        else:
            self.client_id = config.get("client_id")
            self.client_secret = config.get("client_secret")
            self.redirect_uri = config.get("redirect_uri")
            self.app_name = config.get("app_name", "GoogleCalendarApp")
            self.encryption_key = config.get("encryption_key")
            
        # Initialize token storage
        self.token_storage = TokenStorageManager()

    async def get_authorization_url(self, user_id):
        """
        Get the authorization URL for Google OAuth flow.
        
        Args:
            user_id: The user's ID
            
        Returns:
            str: The authorization URL
        """
        if not self.client_id:
            raise ValueError("Google Client ID is not set in configuration.")
        if not self.redirect_uri:
            raise ValueError("Google Calendar Redirect URI is not set in configuration.")
        
        # Encrypt user_id as state parameter
        state = TokenEncryptionHelper.encrypt_token(user_id, self.encryption_key)
        
        # Create a Flow instance
        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "auth_uri": f"{GOOGLE_AUTH_BASE_URL}auth",
                    "token_uri": GOOGLE_TOKEN_URL,
                    "redirect_uris": [self.redirect_uri]
                }
            },
            scopes=SCOPES,
            redirect_uri=self.redirect_uri
        )
        
        # Generate authorization URL
        auth_url, _ = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            state=state,
            prompt='consent'  # Always show consent screen to get refresh token
        )
        
        logger.info(f"Generated authorization URL for user {user_id}")
        return auth_url
    
    async def handle_auth_callback(self, state, code):
        """
        Handle the authorization callback from Google.
        
        Args:
            state: The state parameter from the callback
            code: The authorization code from the callback
        """
        if not self.client_id:
            raise ValueError("Google Client ID is not set in configuration.")
        if not self.client_secret:
            raise ValueError("Google Client Secret is not set in configuration.")
        if not self.redirect_uri:
            raise ValueError("Google Calendar Redirect URI is not set in configuration.")
        
        # Decrypt the user_id from state
        user_id = TokenEncryptionHelper.decrypt_token(state, self.encryption_key)
        logger.info(f"Processing authorization callback for user {user_id}")
        
        # Create a Flow instance - but don't specify scopes this time
        # This lets the flow accept whatever scopes Google returns
        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "auth_uri": f"{GOOGLE_AUTH_BASE_URL}auth",
                    "token_uri": GOOGLE_TOKEN_URL,
                    "redirect_uris": [self.redirect_uri]
                }
            },
            scopes=None,  # Allow any scope to be returned
            redirect_uri=self.redirect_uri
        )
        
        # Exchange code for token
        try:
            flow.fetch_token(code=code)
            credentials = flow.credentials
            
            # Store token
            await self._store_token(
                user_id,
                credentials.token,
                credentials.refresh_token,
                credentials.expiry.timestamp() - datetime.now().timestamp()
            )
            logger.info(f"Successfully obtained and stored access token for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to obtain access token: {str(e)}")
            raise Exception(f"Failed to obtain user access token: {str(e)}")
    
    async def revoke_access(self, user_id):
        """
        Revoke the Google Calendar access for a user.
        
        Args:
            user_id: The user's ID
        """
        token_data = await self._get_token_data(user_id)
        if not token_data:
            raise ValueError("No valid token found for user")
        
        token = token_data.get("access_token")
        if not token:
            raise ValueError("No valid access token found for user")
        
        # Revoke the token
        params = {'token': token}
        response = requests.post(GOOGLE_REVOKE_URL, params=params)
        
        if response.status_code in (200, 204):
            # Delete the token from storage
            self.token_storage.delete_token(user_id, PLATFORM, SERVICE)
            logger.info(f"Successfully revoked access for user {user_id}")
        else:
            logger.error(f"Failed to revoke token: {response.status_code}")
            raise Exception(f"Failed to revoke token: {response.status_code}")
    
    async def get_user_timezone(self, user_id):
        """
        Get the user's calendar timezone.
        
        Args:
            user_id: The user's ID
            
        Returns:
            dict: Object containing the user's timezone
        """
        service = await self._get_calendar_service(user_id)
        
        try:
            calendar = service.calendars().get(calendarId='primary').execute()
            return {"timezone": calendar['timeZone']}
        except Exception as e:
            logger.error(f"Failed to get user timezone: {str(e)}")
            raise Exception(f"Failed to get user timezone: {str(e)}")
    
    async def get_events(self, user_id, start_date, end_date, max_results=10):
        """
        Get events from the user's primary calendar.
        
        Args:
            user_id: The user's ID
            start_date: Start date for events (datetime)
            end_date: End date for events (datetime)
            max_results: Maximum number of events to return
            
        Returns:
            list: The calendar events
        """
        service = await self._get_calendar_service(user_id)
        
        try:
            # Format dates to RFC3339 timestamp
            start_date_rfc = start_date.isoformat() + 'Z'
            end_date_rfc = end_date.isoformat() + 'Z'
            
            events_result = service.events().list(
                calendarId='primary',
                timeMin=start_date_rfc,
                timeMax=end_date_rfc,
                maxResults=max_results,
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            events = events_result.get('items', [])
            return events
        except Exception as e:
            logger.error(f"Failed to get events: {str(e)}")
            raise Exception(f"Failed to get events: {str(e)}")
    
    async def add_event(self, user_id, event_details):
        """
        Add an event to the user's primary calendar.
        
        Args:
            user_id: The user's ID
            event_details: Dictionary with event details
            
        Returns:
            dict: The created event
        """
        service = await self._get_calendar_service(user_id)
        
        try:
            event = service.events().insert(
                calendarId='primary',
                body=event_details
            ).execute()
            
            return event
        except Exception as e:
            logger.error(f"Failed to add event: {str(e)}")
            raise Exception(f"Failed to add event: {str(e)}")
    
    async def update_event(self, user_id, event_id, updated_event):
        """
        Update an event in the user's primary calendar.
        
        Args:
            user_id: The user's ID
            event_id: ID of the event to update
            updated_event: Dictionary with updated event details
            
        Returns:
            dict: The updated event
        """
        service = await self._get_calendar_service(user_id)
        
        try:
            event = service.events().update(
                calendarId='primary',
                eventId=event_id,
                body=updated_event
            ).execute()
            
            return event
        except Exception as e:
            logger.error(f"Failed to update event: {str(e)}")
            raise Exception(f"Failed to update event: {str(e)}")
    
    async def delete_event(self, user_id, event_id):
        """
        Delete an event from the user's primary calendar.
        
        Args:
            user_id: The user's ID
            event_id: ID of the event to delete
        """
        service = await self._get_calendar_service(user_id)
        
        try:
            service.events().delete(
                calendarId='primary',
                eventId=event_id
            ).execute()
            
            logger.info(f"Successfully deleted event {event_id}")
        except Exception as e:
            logger.error(f"Failed to delete event: {str(e)}")
            raise Exception(f"Failed to delete event: {str(e)}")
    
    async def get_event(self, user_id, event_id):
        """
        Get a specific event from the user's primary calendar.
        
        Args:
            user_id: The user's ID
            event_id: ID of the event to retrieve
            
        Returns:
            dict: The event details
        """
        service = await self._get_calendar_service(user_id)
        
        try:
            event = service.events().get(
                calendarId='primary',
                eventId=event_id
            ).execute()
            
            return event
        except Exception as e:
            logger.error(f"Failed to get event: {str(e)}")
            raise Exception(f"Failed to get event: {str(e)}")
    
    async def search_events(self, user_id, query, max_results=10):
        """
        Search for events in the user's primary calendar.
        
        Args:
            user_id: The user's ID
            query: Search query string
            max_results: Maximum number of results to return
            
        Returns:
            dict: Search results containing events
        """
        service = await self._get_calendar_service(user_id)
        
        try:
            events_result = service.events().list(
                calendarId='primary',
                q=query,
                maxResults=max_results,
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            return events_result
        except Exception as e:
            logger.error(f"Failed to search events: {str(e)}")
            raise Exception(f"Failed to search events: {str(e)}")
    
    async def share_event(self, user_id, event_id, shared_email):
        """
        Share an event with another user by adding them as an attendee.
        
        Args:
            user_id: The user's ID
            event_id: ID of the event to share
            shared_email: Email address of the user to share with
        """
        service = await self._get_calendar_service(user_id)
        
        try:
            # Get the event first
            event = service.events().get(
                calendarId='primary',
                eventId=event_id
            ).execute()
            
            # Initialize attendees list if it doesn't exist
            if 'attendees' not in event:
                event['attendees'] = []
            
            # Add the new attendee
            event['attendees'].append({'email': shared_email})
            
            # Update the event
            updated_event = service.events().update(
                calendarId='primary',
                eventId=event_id,
                body=event
            ).execute()
            
            logger.info(f"Successfully shared event {event_id} with {shared_email}")
            return updated_event
        except Exception as e:
            logger.error(f"Failed to share event: {str(e)}")
            raise Exception(f"Failed to share event: {str(e)}")
    
    async def create_calendar(self, user_id, calendar_name):
        """
        Create a new calendar for the user.
        
        Args:
            user_id: The user's ID
            calendar_name: Name for the new calendar
            
        Returns:
            str: ID of the created calendar
        """
        service = await self._get_calendar_service(user_id)
        
        try:
            calendar = {
                'summary': calendar_name,
                'timeZone': 'UTC'
            }
            
            created_calendar = service.calendars().insert(body=calendar).execute()
            
            logger.info(f"Successfully created calendar: {calendar_name}")
            return created_calendar['id']
        except Exception as e:
            logger.error(f"Failed to create calendar: {str(e)}")
            raise Exception(f"Failed to create calendar: {str(e)}")
    
    async def _store_token(self, user_id, access_token, refresh_token, expires_in):
        """
        Store a token in the token storage.
        
        Args:
            user_id: The user's ID
            access_token: The access token
            refresh_token: The refresh token
            expires_in: Expiration time in seconds
        """
        token_data = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": (datetime.utcnow() + timedelta(seconds=expires_in)).timestamp()
        }
        
        # Serialize and encrypt the token data
        serialized_token = json.dumps(token_data)
        encrypted_token = TokenEncryptionHelper.encrypt_token(serialized_token, self.encryption_key)
        
        # Store in the token storage using the helper function
        token_record = create_token_record(encrypted_token)
        
        self.token_storage.store_token(user_id, PLATFORM, SERVICE, token_record)
    
    async def _get_token_data(self, user_id):
        """
        Get token data from storage.
        
        Args:
            user_id: The user's ID
            
        Returns:
            dict: The token data or None if not found
        """
        token_record = self.token_storage.get_token(user_id, PLATFORM, SERVICE)
        
        if not token_record or not token_record.get("is_active") or token_record.get("is_revoked"):
            logger.info(f"No valid token found in the storage for user {user_id}")
            return None
        
        try:
            encrypted_token = token_record.get("encrypted_token")
            if not encrypted_token:
                return None
            
            decrypted_token = TokenEncryptionHelper.decrypt_token(encrypted_token, self.encryption_key)
            token_data = json.loads(decrypted_token)
            
            return token_data
        except Exception as e:
            logger.error(f"Error getting token data: {str(e)}")
            return None
    
    async def _load_token(self, user_id):
        """
        Load a token from the token storage.
        
        Args:
            user_id: The user's ID
            
        Returns:
            str: The access token, or None if not found or expired
        """
        token_data = await self._get_token_data(user_id)
        
        if not token_data:
            return None
        
        # Check if token is expired
        expires_at = token_data.get("expires_at")
        if expires_at and expires_at <= datetime.utcnow().timestamp():
            logger.info(f"Token expired for user {user_id}, attempting to refresh")
            refresh_token = token_data.get("refresh_token")
            if refresh_token:
                try:
                    return await self._refresh_token(user_id, refresh_token)
                except Exception as e:
                    logger.error(f"Error refreshing token: {str(e)}")
                    return None
            return None
        
        return token_data.get("access_token")
    
    async def _refresh_token(self, user_id, refresh_token):
        """
        Refresh an expired token.
        
        Args:
            user_id: The user's ID
            refresh_token: The refresh token
            
        Returns:
            str: The new access token
        """
        if not self.client_id:
            raise ValueError("Google Client ID is not set in configuration.")
        if not self.client_secret:
            raise ValueError("Google Client Secret is not set in configuration.")
        
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self.client_id,
            "client_secret": self.client_secret
        }
        
        logger.info(f"Attempting to refresh token for user {user_id}")
        response = requests.post(GOOGLE_TOKEN_URL, data=payload)
        response_data = response.json()
        
        if response.status_code == 200 and "access_token" in response_data:
            # Store the new token
            expires_in = response_data.get("expires_in", 3600)  # Default to 1 hour
            await self._store_token(
                user_id, 
                response_data["access_token"], 
                refresh_token,  # Keep the existing refresh token if not provided
                expires_in
            )
            logger.info(f"Successfully refreshed token for user {user_id}")
            return response_data["access_token"]
        else:
            error_msg = response_data.get("error_description", "Unknown error")
            logger.error(f"Failed to refresh token: {error_msg}")
            # If refresh fails, mark the token as revoked so we don't keep trying
            token_record = self.token_storage.get_token(user_id, PLATFORM, SERVICE)
            if token_record:
                token_record["is_revoked"] = True
                self.token_storage.store_token(user_id, PLATFORM, SERVICE, token_record)
            raise Exception(f"Failed to refresh token: {error_msg}")
    
    async def _get_calendar_service(self, user_id):
        """
        Get an authenticated Google Calendar service instance.
        
        Args:
            user_id: The user's ID
            
        Returns:
            Resource: The Calendar service instance
        """
        token_data = await self._get_token_data(user_id)
        
        if not token_data:
            raise self._create_auth_exception(user_id)
        
        # Check if token is expired
        expires_at = token_data.get("expires_at")
        if expires_at and expires_at <= datetime.utcnow().timestamp():
            # Refresh the token
            refresh_token = token_data.get("refresh_token")
            if not refresh_token:
                raise self._create_auth_exception(user_id)
            
            try:
                token_data["access_token"] = await self._refresh_token(user_id, refresh_token)
            except Exception:
                raise self._create_auth_exception(user_id)
        
        # Create credentials from token data
        expiry = datetime.fromtimestamp(token_data.get("expires_at", 0))
        credentials = Credentials(
            token=token_data.get("access_token"),
            refresh_token=token_data.get("refresh_token"),
            token_uri=GOOGLE_TOKEN_URL,
            client_id=self.client_id,
            client_secret=self.client_secret,
            expiry=expiry
        )
        
        # Build the Calendar service
        try:
            service = build('calendar', 'v3', credentials=credentials)
            return service
        except Exception as e:
            logger.error(f"Failed to build Calendar service: {str(e)}")
            raise self._create_auth_exception(user_id)
    
    def _create_auth_exception(self, user_id):
        """
        Create an authentication exception with reauthorization instructions.
        
        Args:
            user_id: The user's ID
            
        Returns:
            Exception: With reauthorization instructions
        """
        # Don't try to generate an auth URL here, just return the instruction
        return Exception(
            "Your Google Calendar authorization has expired or is invalid. "
            "Please use the `!authorize-gcalendar` command to reconnect your Google Calendar account."
        )