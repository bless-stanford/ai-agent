import os
import base64
import logging
from semantic_kernel.functions import kernel_function
from semantic_kernel.functions.kernel_function_from_prompt import KernelFunctionFromPrompt
from services.gmail_service import GmailService

logger = logging.getLogger("gmail_plugins")

class GmailPlugins:
    """
    Plugins for interacting with Gmail API.
    """
    
    def __init__(self, gmail_service=None):
        """
        Initialize the Gmail plugins with a GmailService.
        If no service is provided, a new one will be created.
        """
        self.gmail_service = gmail_service or GmailService()
    
    @kernel_function(
        name="get_recent_emails",
        description="Retrieves recent emails from the user's Gmail inbox"
    )
    async def get_recent_emails(
        self,
        max_results: int = 5,
        unread_only: bool = False,
        user_id: str = None,
        kernel = None
    ) -> str:
        """
        Retrieves recent emails from the user's Gmail inbox.
        
        Args:
            max_results: Maximum number of emails to retrieve (default: 5)
            unread_only: If True, only retrieves unread emails (default: False)
            user_id: The user's ID (automatically provided)
            
        Returns:
            str: Formatted list of recent emails or error message
        """
        try:
            if not user_id:
                return "Error: User ID not available. Please try again later."
            
            emails = await self.gmail_service.get_recent_emails(user_id, max_results, unread_only)
            
            if not emails or len(emails) == 0:
                status = "unread " if unread_only else ""
                return f"No {status}emails found in your inbox."
            
            # Format the emails into a readable summary
            summary = f"**{len(emails)} Recent{' Unread' if unread_only else ''} Emails:**\n\n"
            
            for i, email in enumerate(emails, 1):
                summary += self._format_email_summary(email, i)
            
            return summary
                
        except Exception as e:
            logger.error(f"Error retrieving emails: {str(e)}")
            return f"An error occurred while retrieving emails: {str(e)}"
    
    @kernel_function(
        name="search_emails",
        description="Searches for emails in the user's Gmail account using a query"
    )
    async def search_emails(
        self,
        query: str,
        max_results: int = 5,
        user_id: str = None,
        kernel = None
    ) -> str:
        """
        Searches for emails in the user's Gmail account.
        
        Args:
            query: Search query (e.g., from:example@gmail.com, subject:important)
            max_results: Maximum number of emails to retrieve
            user_id: The user's ID (automatically provided)
            
        Returns:
            str: Formatted search results or error message
        """
        try:
            if not user_id:
                return "Error: User ID not available. Please try again later."
            
            emails = await self.gmail_service.search_emails(user_id, query, max_results)
            
            if not emails or len(emails) == 0:
                return f"No emails found matching query '{query}'."
            
            # Format the emails into a readable summary
            summary = f"**Search Results for '{query}':**\n\n"
            
            for i, email in enumerate(emails, 1):
                # Get the full email message if we only have IDs
                if 'id' in email and not 'payload' in email:
                    full_email = await self.gmail_service.get_email(user_id, email['id'])
                    email = full_email
                
                summary += self._format_email_summary(email, i)
            
            return summary
                
        except Exception as e:
            logger.error(f"Error searching emails: {str(e)}")
            return f"An error occurred while searching emails: {str(e)}"
    
    @kernel_function(
        name="get_email",
        description="Retrieves and displays the content of a specific email"
    )
    async def get_email(
        self,
        message_id: str,
        user_id: str = None,
        kernel = None
    ) -> str:
        """
        Retrieves and displays the content of a specific email.
        
        Args:
            message_id: The ID of the email message to retrieve
            user_id: The user's ID (automatically provided)
            
        Returns:
            str: Formatted email content or error message
        """
        try:
            if not user_id:
                return "Error: User ID not available. Please try again later."
            
            email = await self.gmail_service.get_email(user_id, message_id)
            
            if not email:
                return f"Email with ID {message_id} not found."
            
            # Format the email into a detailed view
            formatted_email = self._format_email_detail(email)
            
            # Mark the email as read
            await self.gmail_service.mark_as_read(user_id, message_id)
            
            return formatted_email
                
        except Exception as e:
            logger.error(f"Error retrieving email: {str(e)}")
            return f"An error occurred while retrieving the email: {str(e)}"
    
    @kernel_function(
        name="mark_as_read",
        description="Marks an email as read"
    )
    async def mark_email_as_read(
        self,
        message_id: str,
        user_id: str = None,
        kernel = None
    ) -> str:
        """
        Marks an email as read.
        
        Args:
            message_id: The ID of the email message to mark as read
            user_id: The user's ID (automatically provided)
            
        Returns:
            str: Success message or error message
        """
        try:
            if not user_id:
                return "Error: User ID not available. Please try again later."
            
            await self.gmail_service.mark_as_read(user_id, message_id)
            return f"Email with ID {message_id} has been marked as read."
                
        except Exception as e:
            logger.error(f"Error marking email as read: {str(e)}")
            return f"An error occurred while marking the email as read: {str(e)}"
    
    @kernel_function(
        name="send_email",
        description="Sends an email from the user's Gmail account"
    )
    async def send_email(
        self,
        to_address: str,
        subject: str,
        body: str,
        attachment_paths: str = None,
        user_id: str = None,
        kernel = None
    ) -> str:
        """
        Sends an email from the user's Gmail account.
        
        Args:
            to_address: Email address of the recipient
            subject: Email subject
            body: Email body content
            attachment_paths: Optional comma-separated list of file paths to attach
            user_id: The user's ID (automatically provided)
            
        Returns:
            str: Success message or error message
        """
        try:
            if not user_id:
                return "Error: User ID not available. Please try again later."
            
            # Process attachment paths if provided
            attachments = None
            if attachment_paths:
                attachments = [path.strip() for path in attachment_paths.split(',')]
                
                # Verify all attachments exist
                for path in attachments:
                    if not os.path.exists(path):
                        return f"Error: Attachment file not found at path '{path}'."
            
            # Send the email
            await self.gmail_service.send_email(user_id, to_address, subject, body, attachments)
            
            # Construct success message
            success_msg = f"✅ Email sent successfully to {to_address}!\n"
            success_msg += f"**Subject:** {subject}\n"
            
            if attachments and len(attachments) > 0:
                attachment_names = [os.path.basename(path) for path in attachments]
                success_msg += f"**Attachments:** {', '.join(attachment_names)}"
            
            return success_msg
                
        except Exception as e:
            logger.error(f"Error sending email: {str(e)}")
            return f"An error occurred while sending the email: {str(e)}"
    
    @kernel_function(
        name="download_attachments",
        description="Downloads attachments from a specific email"
    )
    async def download_attachments(
        self,
        message_id: str,
        output_dir: str = "downloads",
        user_id: str = None,
        kernel = None
    ) -> str:
        """
        Downloads attachments from a specific email.
        
        Args:
            message_id: The ID of the email message
            output_dir: Directory where attachments should be saved
            user_id: The user's ID (automatically provided)
            
        Returns:
            str: Success message with attachment details or error message
        """
        try:
            if not user_id:
                return "Error: User ID not available. Please try again later."
            
            # Create the output directory if it doesn't exist
            os.makedirs(output_dir, exist_ok=True)
            
            # Download attachments
            filenames = await self.gmail_service.get_attachments(user_id, message_id, output_dir)
            
            if not filenames or len(filenames) == 0:
                return "No attachments found in the email."
            
            # Create success message
            success_msg = f"✅ Downloaded {len(filenames)} attachment(s) from email:\n"
            for i, filename in enumerate(filenames, 1):
                file_path = os.path.join(output_dir, filename)
                file_size = os.path.getsize(file_path)
                formatted_size = self._format_file_size(file_size)
                success_msg += f"{i}. **{filename}** ({formatted_size})\n"
            
            success_msg += f"\nAll files saved to directory: {os.path.abspath(output_dir)}"
            return success_msg
                
        except Exception as e:
            logger.error(f"Error downloading attachments: {str(e)}")
            return f"An error occurred while downloading attachments: {str(e)}"
    
    @kernel_function(
        name="compose_email",
        description="Creates a well-formatted email based on input parameters"
    )
    async def compose_email(
        self,
        to_address: str,
        subject: str,
        body_content: str,
        include_signature: bool = True,
        user_id: str = None,
        kernel = None
    ) -> str:
        """
        Creates a well-formatted email based on input parameters.
        
        Args:
            to_address: Email address of the recipient
            subject: Email subject
            body_content: Main content of the email body
            include_signature: Whether to include a signature (default: True)
            user_id: The user's ID (automatically provided)
            
        Returns:
            str: Formatted email ready for review and sending
        """
        try:
            if not user_id:
                return "Error: User ID not available. Please try again later."
            
            # Add a basic signature if requested
            signature = "\n\nBest regards,\nSent via Gmail API" if include_signature else ""
            
            # Format the email
            formatted_email = f"**To:** {to_address}\n\n"
            formatted_email += f"**Subject:** {subject}\n\n"
            formatted_email += f"**Body:**\n\n{body_content}{signature}\n\n"
            
            # Add instructions for sending
            formatted_email += (
                "---\n"
                "To send this email, use the `send_email` function with the following parameters:\n"
                f"- to_address: {to_address}\n"
                f"- subject: {subject}\n"
                f"- body: The content above\n"
                "- attachment_paths: (optional) comma-separated list of file paths"
            )
            
            return formatted_email
                
        except Exception as e:
            logger.error(f"Error composing email: {str(e)}")
            return f"An error occurred while composing the email: {str(e)}"
    
    @kernel_function(
        name="get_authorization_url",
        description="Gets the authorization URL for connecting a Gmail account"
    )
    async def get_authorization_url(
        self,
        user_id: str = None,
        kernel = None
    ) -> str:
        """
        Gets the authorization URL for connecting a Gmail account.
        
        Args:
            user_id: The user's ID (automatically provided)
            
        Returns:
            str: Authorization URL or error message
        """
        try:
            if not user_id:
                return "Error: User ID not available. Please try again later."
            
            auth_url = await self.gmail_service.get_authorization_url(user_id)
            
            return (
                "**Connect your Gmail account**\n\n"
                f"Please click the following link to authorize access to your Gmail account:\n\n{auth_url}\n\n"
                "After authorization, you will be redirected back to the application."
            )
                
        except Exception as e:
            logger.error(f"Error getting authorization URL: {str(e)}")
            return f"An error occurred while generating the authorization URL: {str(e)}"
    
    @kernel_function(
        name="revoke_access",
        description="Revokes access to the user's Gmail account"
    )
    async def revoke_access(
        self,
        user_id: str = None,
        kernel = None
    ) -> str:
        """
        Revokes access to the user's Gmail account.
        
        Args:
            user_id: The user's ID (automatically provided)
            
        Returns:
            str: Success message or error message
        """
        try:
            if not user_id:
                return "Error: User ID not available. Please try again later."
            
            await self.gmail_service.revoke_access(user_id)
            
            return "✅ Access to your Gmail account has been successfully revoked. The application no longer has access to your emails."
                
        except Exception as e:
            logger.error(f"Error revoking access: {str(e)}")
            return f"An error occurred while revoking access: {str(e)}"
    
    @kernel_function(
        name="search_and_summarize",
        description="Searches emails with a query and provides an AI-generated summary"
    )
    async def search_and_summarize(
        self,
        query: str,
        max_results: int = 5,
        user_id: str = None,
        kernel = None
    ) -> str:
        """
        Searches emails with a query and provides an AI-generated summary.
        
        Args:
            query: Search query for emails
            max_results: Maximum number of emails to include
            user_id: The user's ID (automatically provided)
            kernel: Semantic Kernel instance for summarization
            
        Returns:
            str: AI-generated summary of the emails or error message
        """
        try:
            if not user_id:
                return "Error: User ID not available. Please try again later."
            
            if not kernel:
                return "Error: Semantic Kernel not available. Please try again later."
            
            # Search for emails
            emails = await self.gmail_service.search_emails(user_id, query, max_results)
            
            if not emails or len(emails) == 0:
                return f"No emails found matching query '{query}'."
            
            # Get full email data
            full_emails = []
            for email_ref in emails:
                if 'id' in email_ref:
                    full_email = await self.gmail_service.get_email(user_id, email_ref['id'])
                    full_emails.append(full_email)
            
            # Format emails for summarization
            email_texts = []
            for i, email in enumerate(full_emails, 1):
                email_summary = self._extract_email_content(email, include_headers=True)
                email_texts.append(f"Email {i}:\n{email_summary}")
            
            all_emails_text = "\n\n".join(email_texts)
            
            # Create a summarization function
            summarize_function = KernelFunctionFromPrompt(
                function_name="SummarizeEmails",
                plugin_name=None,
                prompt="You are an email assistant. Summarize the following emails concisely, highlighting key points, "
                    "action items, and important details. If there are multiple emails, identify common themes or threads.\n\n"
                    "Emails to summarize:\n{{$emails}}\n\n"
                    "Summary:",
                template_format="semantic-kernel"
            )
            
            # Invoke the summarization function
            kernel_arguments = {
                "emails": all_emails_text
            }
            
            result = await kernel.invoke(summarize_function, **kernel_arguments)
            
            # Return the summary
            return f"**Summary of {len(full_emails)} emails matching '{query}':**\n\n{result.value}"
                
        except Exception as e:
            logger.error(f"Error summarizing emails: {str(e)}")
            return f"An error occurred while summarizing emails: {str(e)}"
    
    def _format_email_summary(self, email, index=None):
        """Format an email into a brief summary."""
        try:
            header_prefix = f"**{index}. " if index is not None else "**"
            
            # Extract headers
            headers = {}
            if 'payload' in email and 'headers' in email['payload']:
                for header in email['payload']['headers']:
                    headers[header.get('name', '').lower()] = header.get('value', '')
            
            # Get subject, from, and date
            subject = headers.get('subject', 'No Subject')
            sender = headers.get('from', 'Unknown Sender')
            date = headers.get('date', 'Unknown Date')
            
            # Create summary
            summary = f"{header_prefix}{subject}**\n"
            summary += f"   From: {sender}\n"
            summary += f"   Date: {date}\n"
            
            # Check for attachments
            has_attachments = False
            if 'payload' in email and 'parts' in email['payload']:
                for part in email['payload']['parts']:
                    if part.get('filename') and part['filename'].strip():
                        has_attachments = True
                        break
            
            if has_attachments:
                summary += "   📎 Has attachments\n"
            
            # Add ID for reference
            summary += f"   ID: {email.get('id', 'Unknown')}\n\n"
            
            return summary
        except Exception as e:
            logger.error(f"Error formatting email summary: {str(e)}")
            return f"[Error formatting email: {str(e)}]\n\n"
    
    def _format_email_detail(self, email):
        """Format an email into a detailed view."""
        try:
            # Extract headers
            headers = {}
            if 'payload' in email and 'headers' in email['payload']:
                for header in email['payload']['headers']:
                    headers[header.get('name', '').lower()] = header.get('value', '')
            
            # Get email details
            subject = headers.get('subject', 'No Subject')
            sender = headers.get('from', 'Unknown Sender')
            to = headers.get('to', 'Unknown Recipient')
            date = headers.get('date', 'Unknown Date')
            
            # Extract body
            body = self._extract_email_content(email)
            
            # Format the detailed view
            detail = f"**Subject:** {subject}\n\n"
            detail += f"**From:** {sender}\n"
            detail += f"**To:** {to}\n"
            detail += f"**Date:** {date}\n\n"
            
            # List attachments if any
            attachments = []
            if 'payload' in email and 'parts' in email['payload']:
                for part in email['payload']['parts']:
                    if part.get('filename') and part['filename'].strip():
                        attachments.append(part['filename'])
            
            if attachments:
                detail += "**Attachments:**\n"
                for attachment in attachments:
                    detail += f"- {attachment}\n"
                detail += "\n"
                detail += "To download attachments, use the `download_attachments` function with this email's ID.\n\n"
            
            # Add the email body
            detail += "**Message:**\n\n"
            detail += body
            
            # Add email ID for reference
            detail += f"\n\n**Email ID:** {email.get('id', 'Unknown')}"
            
            return detail
        except Exception as e:
            logger.error(f"Error formatting email detail: {str(e)}")
            return f"Error formatting email: {str(e)}"
    
    def _extract_email_content(self, email, include_headers=False):
        """
        Extract the body content from an email message.
        """
        try:
            if 'payload' not in email:
                return "No content found in email."
            
            # If including headers in the extraction (for summarization)
            headers_text = ""
            if include_headers and 'headers' in email['payload']:
                key_headers = ['from', 'to', 'subject', 'date']
                for header in email['payload']['headers']:
                    if header.get('name', '').lower() in key_headers:
                        headers_text += f"{header.get('name')}: {header.get('value')}\n"
                headers_text += "\n"
            
            # Function to extract text from parts
            def get_text_from_part(part):
                if 'body' in part and 'data' in part['body']:
                    data = part['body']['data']
                    try:
                        decoded = base64.urlsafe_b64decode(data).decode('utf-8')
                        return decoded
                    except Exception:
                        return "[Content could not be decoded]"
                return ""
            
            # Check if this is a multipart message
            if 'parts' in email['payload']:
                text_parts = []
                for part in email['payload']['parts']:
                    mime_type = part.get('mimeType', '')
                    if mime_type == 'text/plain':
                        text_parts.append(get_text_from_part(part))
                    elif 'parts' in part:  # Handle nested multipart
                        for subpart in part['parts']:
                            if subpart.get('mimeType', '') == 'text/plain':
                                text_parts.append(get_text_from_part(subpart))
                
                content = "\n".join(text_parts)
                return headers_text + (content if content else "[No plain text content found]")
            else:
                # Handle single part message
                mime_type = email['payload'].get('mimeType', '')
                if mime_type == 'text/plain':
                    content = get_text_from_part(email['payload'])
                    return headers_text + (content if content else "[Empty message]")
                else:
                    return headers_text + f"[Content is in {mime_type} format and cannot be displayed as text]"
        except Exception as e:
            logger.error(f"Error extracting email content: {str(e)}")
            return f"[Error extracting content: {str(e)}]"
    
    def _format_file_size(self, bytes):
        """Format file size in human-readable form."""
        sizes = ["B", "KB", "MB", "GB", "TB"]
        order = 0
        size = float(bytes)
        while size >= 1024 and order < len(sizes) - 1:
            order += 1
            size /= 1024
        
        return f"{size:.2f} {sizes[order]}"