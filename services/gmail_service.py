import os
import json
import base64
import logging
import mimetypes
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from datetime import datetime, timedelta
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
logger = logging.getLogger("gmail_service")

# Constants for platform and service
PLATFORM = "Google"
SERVICE = "GmailService"

# API URLs
GOOGLE_AUTH_BASE_URL = "https://accounts.google.com/o/oauth2/"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"

# Scopes for Gmail API
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly', 'https://www.googleapis.com/auth/gmail.send']


class GmailService:
    def __init__(self, config=None):
        """
        Initialize the Gmail service with configuration.
        
        Args:
            config: Configuration dictionary or None to load from .env
        """
        if config is None:
            load_dotenv()
            self.client_id = os.getenv("GOOGLE_CLIENT_ID")
            self.client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
            self.redirect_uri = os.getenv("GOOGLE_GMAIL_REDIRECT_URI")
            self.app_name = os.getenv("GOOGLE_APP_NAME", "GmailApp")
            
            # Get or generate encryption key using our helper
            self.encryption_key = load_or_generate_encryption_key()
        else:
            self.client_id = config.get("client_id")
            self.client_secret = config.get("client_secret")
            self.redirect_uri = config.get("redirect_uri")
            self.app_name = config.get("app_name", "GmailApp")
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
            raise ValueError("Google Redirect URI is not set in configuration.")
        
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
            raise ValueError("Google Redirect URI is not set in configuration.")
        
        # Decrypt the user_id from state
        user_id = TokenEncryptionHelper.decrypt_token(state, self.encryption_key)
        logger.info(f"Processing authorization callback for user {user_id}")
        
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
        Revoke the Gmail access for a user.
        
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
    
    async def get_email(self, user_id, message_id):
        """
        Get a specific email message.
        
        Args:
            user_id: The user's ID
            message_id: The ID of the message to retrieve
            
        Returns:
            dict: The full message data
        """
        service = await self._get_gmail_service(user_id)
        
        try:
            request = service.users().messages().get(userId='me', id=message_id)
            request.format = 'full'  # Get full message details
            message = await self._execute_request(request)
            return message
        except Exception as e:
            logger.error(f"Failed to get email: {str(e)}")
            raise Exception(f"Failed to get email: {str(e)}")
    
    async def get_recent_emails(self, user_id, max_results=10, unread_only=False):
        """
        Get recent emails from the user's inbox.
        
        Args:
            user_id: The user's ID
            max_results: Maximum number of emails to return
            unread_only: If True, only return unread emails
            
        Returns:
            list: Recent email messages
        """
        service = await self._get_gmail_service(user_id)
        
        try:
            # Build the request
            request = service.users().messages().list(userId='me', maxResults=max_results)
            
            # Set up label filters
            label_ids = ['INBOX']
            if unread_only:
                label_ids.append('UNREAD')
            request.labelIds = label_ids
            
            # Set up query to exclude promotional and social emails
            query = "in:inbox -category:promotions -category:social"
            if unread_only:
                query += " is:unread"
            request.q = query
            
            # Execute the request
            response = await self._execute_request(request)
            messages = []
            
            if 'messages' in response:
                for message_data in response['messages']:
                    message_id = message_data.get('id')
                    full_message = await self.get_email(user_id, message_id)
                    messages.append(full_message)
            
            return messages
        except Exception as e:
            logger.error(f"Failed to get recent emails: {str(e)}")
            raise Exception(f"Failed to get recent emails: {str(e)}")
    
    async def get_attachments(self, user_id, message_id, output_dir):
        """
        Download attachments from an email.
        
        Args:
            user_id: The user's ID
            message_id: The ID of the message
            output_dir: Directory to save attachments
            
        Returns:
            list: List of attachment filenames that were saved
        """
        try:
            filenames = []
            service = await self._get_gmail_service(user_id)
            
            # Ensure the output directory exists
            os.makedirs(output_dir, exist_ok=True)
            
            # Get the message
            message = service.users().messages().get(userId=user_id, id=message_id).execute()
            
            # Check if the message has parts
            if 'payload' not in message or 'parts' not in message['payload']:
                return filenames
            
            # Process each part
            for part in message['payload']['parts']:
                if part.get('filename') and part['filename'].strip():
                    if 'body' in part and 'attachmentId' in part['body']:
                        attachment_id = part['body']['attachmentId']
                        
                        # Get the attachment
                        attachment = service.users().messages().attachments().get(
                            userId=user_id,
                            messageId=message_id,
                            id=attachment_id
                        ).execute()
                        
                        # Decode the attachment data
                        file_data = base64.urlsafe_b64decode(attachment['data'])
                        
                        # Save the attachment
                        file_path = os.path.join(output_dir, part['filename'])
                        with open(file_path, 'wb') as f:
                            f.write(file_data)
                        
                        filenames.append(part['filename'])
            
            return filenames
        except Exception as e:
            logger.error(f"Failed to get attachments: {str(e)}")
            raise Exception(f"Failed to get attachments: {str(e)}")
    
    async def list_emails(self, user_id, max_results=10):
        """
        List emails in the user's inbox.
        
        Args:
            user_id: The user's ID
            max_results: Maximum number of emails to return
            
        Returns:
            list: Email message list
        """
        service = await self._get_gmail_service(user_id)
        
        try:
            # Create the request
            request = service.users().messages().list(
                userId='me',
                includeSpamTrash=False,
                maxResults=max_results
            )
            
            # Execute the request and get all pages
            messages = []
            response = await self._execute_request(request)
            
            if 'messages' in response:
                messages.extend(response['messages'])
            
            # Get any additional pages if needed
            while 'nextPageToken' in response and len(messages) < max_results:
                request.pageToken = response['nextPageToken']
                response = await self._execute_request(request)
                if 'messages' in response:
                    messages.extend(response['messages'])
            
            return messages[:max_results]
        except Exception as e:
            logger.error(f"Failed to list emails: {str(e)}")
            raise Exception(f"Failed to list emails: {str(e)}")
    
    async def search_emails(self, user_id, query, max_results=10):
        """
        Search for emails using a query.
        
        Args:
            user_id: The user's ID
            query: Search query string
            max_results: Maximum number of emails to return
            
        Returns:
            list: Matching email messages
        """
        service = await self._get_gmail_service(user_id)
        
        try:
            # Create the request
            request = service.users().messages().list(
                userId='me',
                q=query,
                includeSpamTrash=False,
                maxResults=max_results
            )
            
            # Execute the request and get all pages
            messages = []
            response = await self._execute_request(request)
            
            if 'messages' in response:
                messages.extend(response['messages'])
            
            # Get any additional pages if needed
            while 'nextPageToken' in response and len(messages) < max_results:
                request.pageToken = response['nextPageToken']
                response = await self._execute_request(request)
                if 'messages' in response:
                    messages.extend(response['messages'])
            
            return messages[:max_results]
        except Exception as e:
            logger.error(f"Failed to search emails: {str(e)}")
            raise Exception(f"Failed to search emails: {str(e)}")
    
    async def send_email(self, user_id, to_address, subject, body, attachment_paths=None):
        """
        Send an email using the user's Gmail account.
        
        Args:
            user_id: The user's ID
            to_address: Recipient email address
            subject: Email subject
            body: Email body content
            attachment_paths: Optional list of file paths to attach
        """
        service = await self._get_gmail_service(user_id)
        
        try:
            # Create a MIME message
            message = MIMEMultipart()
            message['to'] = to_address
            message['subject'] = subject
            
            # Attach the body as text/plain
            msg_body = MIMEText(body)
            message.attach(msg_body)
            
            # Attach any files
            if attachment_paths:
                for attachment_path in attachment_paths:
                    with open(attachment_path, 'rb') as f:
                        attachment_data = f.read()
                    
                    # Determine the MIME type
                    content_type, encoding = mimetypes.guess_type(attachment_path)
                    if content_type is None or encoding is not None:
                        content_type = 'application/octet-stream'
                    
                    main_type, sub_type = content_type.split('/', 1)
                    filename = os.path.basename(attachment_path)
                    
                    # Create the attachment
                    attachment = MIMEApplication(attachment_data, _subtype=sub_type)
                    attachment.add_header('Content-Disposition', 'attachment', filename=filename)
                    message.attach(attachment)
            
            # Encode the message for sending
            raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
            gmail_message = {'raw': raw_message}
            
            # Send the message
            await self._execute_request(
                service.users().messages().send(userId='me', body=gmail_message)
            )
            
            logger.info(f"Email sent to {to_address} with subject '{subject}'")
        except Exception as e:
            logger.error(f"Failed to send email: {str(e)}")
            raise Exception(f"Failed to send email: {str(e)}")
    
    async def mark_as_read(self, user_id, message_id):
        """
        Mark an email as read.
        
        Args:
            user_id: The user's ID
            message_id: The ID of the message to mark as read
        """
        service = await self._get_gmail_service(user_id)
        
        try:
            # Create the modify request
            modify_request = {
                'removeLabelIds': ['UNREAD']
            }
            
            # Execute the request
            await self._execute_request(
                service.users().messages().modify(
                    userId='me',
                    id=message_id,
                    body=modify_request
                )
            )
            
            logger.info(f"Marked message {message_id} as read")
        except Exception as e:
            logger.error(f"Failed to mark message as read: {str(e)}")
            raise Exception(f"Failed to mark message as read: {str(e)}")
    
    @staticmethod
    async def _execute_request(request):
        """
        Execute a Gmail API request with async compatibility.
        
        Args:
            request: The Gmail API request object
            
        Returns:
            dict: The response from the API
        """
        # In an actual async implementation, you'd use aiohttp or similar
        # Here we're just wrapping the synchronous execute in a function that can be awaited
        return request.execute()
    
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
    
    async def _get_gmail_service(self, user_id):
        """
        Get an authenticated Gmail service instance.
        
        Args:
            user_id: The user's ID
            
        Returns:
            Resource: The Gmail service instance
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
        
        # Build the Gmail service
        try:
            service = build('gmail', 'v1', credentials=credentials)
            return service
        except Exception as e:
            logger.error(f"Failed to build Gmail service: {str(e)}")
            raise self._create_auth_exception(user_id)
    
    def _create_auth_exception(self, user_id):
        """
        Create an authentication exception with reauthorization instructions.
        
        Args:
            user_id: The user's ID
            
        Returns:
            Exception: With reauthorization instructions
        """
        return Exception(
            "Your Gmail authorization has expired or is invalid. "
            "Please use the `!authorize-gmail` command to reconnect your Gmail account."
        )

    @staticmethod
    def base64_url_encode(input_string):
        """
        Base64 URL encode a string.
        
        Args:
            input_string: String to encode
            
        Returns:
            str: Base64 URL encoded string
        """
        input_bytes = input_string.encode('utf-8')
        base64_bytes = base64.b64encode(input_bytes)
        base64_string = base64_bytes.decode('utf-8')
        return base64_string.replace('+', '-').replace('/', '_').replace('=', '')
    
    @staticmethod
    def base64_url_decode(input_string):
        """
        Base64 URL decode a string.
        
        Args:
            input_string: String to decode
            
        Returns:
            bytes: Decoded bytes
        """
        # Add padding if needed
        base64_string = input_string.replace('-', '+').replace('_', '/')
        padding_needed = len(base64_string) % 4
        if padding_needed:
            base64_string += '=' * (4 - padding_needed)
        
        return base64.b64decode(base64_string)