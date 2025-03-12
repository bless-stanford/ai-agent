import json
import os
from datetime import datetime, timedelta
from semantic_kernel.functions import kernel_function
from semantic_kernel.functions.kernel_function_from_prompt import KernelFunctionFromPrompt
from services.google_calendar_service import GoogleCalendarService
import logging

logger = logging.getLogger("google_calendar_plugins")

class GoogleCalendarPlugins:
    """
    Plugins for interacting with Google Calendar.
    """
    
    def __init__(self, calendar_service=None):
        """
        Initialize the Google Calendar plugins with a GoogleCalendarService.
        If no service is provided, a new one will be created.
        """
        self.calendar_service = calendar_service or GoogleCalendarService()
    
    @kernel_function(
        name="create_calendar",
        description="Creates a new calendar in the user's Google Calendar account"
    )
    async def create_calendar(
        self,
        calendar_name: str,
        user_id: str = None,
        kernel = None
    ) -> str:
        """
        Creates a new calendar in the user's Google Calendar account.
        
        Args:
            calendar_name: Name of the calendar to create
            user_id: The user's ID (automatically provided)
            
        Returns:
            str: Success message with calendar details or error message
        """
        try:
            if not user_id:
                return "Error: User ID not available. Please try again later."
            
            calendar_id = await self.calendar_service.create_calendar(user_id, calendar_name)
            
            if calendar_id:
                return f"Calendar '{calendar_name}' created successfully with ID: {calendar_id}."
            else:
                return f"Failed to create calendar '{calendar_name}'."
                
        except Exception as e:
            logger.error(f"Error creating calendar: {str(e)}")
            return f"An error occurred while creating the calendar: {str(e)}"
    
    @kernel_function(
        name="add_event",
        description="Adds an event to the user's Google Calendar"
    )
    async def add_event(
        self,
        summary: str,
        description: str,
        start_date_time: str,
        end_date_time: str,
        location: str = "",
        is_all_day: str = "false",
        attendee_emails: str = "",
        user_id: str = None,
        kernel = None
    ) -> str:
        """
        Adds an event to the user's Google Calendar.
        
        Args:
            summary: Event summary/title
            description: Event description
            start_date_time: Start time (ISO 8601 - YYYY-MM-DDTHH:MM:SS±hh:mm)
            end_date_time: End time (ISO 8601 - YYYY-MM-DDTHH:MM:SS±hh:mm)
            location: Event location (optional)
            is_all_day: Whether this is an all-day event (default: "false")
            attendee_emails: Comma-separated list of attendee emails
            user_id: The user's ID (automatically provided)
            
        Returns:
            str: Success message with event details or error message
        """
        try:
            if not user_id:
                return "Error: User ID not available. Please try again later."
            
            # Parse datetime strings and is_all_day
            try:
                start_dt = datetime.fromisoformat(start_date_time.replace('Z', '+00:00'))
                end_dt = datetime.fromisoformat(end_date_time.replace('Z', '+00:00'))
                is_all_day_event = is_all_day.lower() == "true"
            except ValueError as e:
                return f"Error parsing date: {str(e)}"
            
            # Parse attendee emails
            attendees = []
            if attendee_emails:
                attendees = [{"email": email.strip()} for email in attendee_emails.split(",") if email.strip()]
            
            # Fetch user's timezone
            try:
                timezone_info = await self.calendar_service.get_user_timezone(user_id)
                user_timezone = timezone_info.get("timezone", "UTC")
            except Exception:
                user_timezone = "UTC"
            
            # Create event dictionary
            event = {
                "summary": summary,
                "description": description,
                "location": location,
                "start": {},
                "end": {},
                "attendees": attendees
            }
            
            # Set start and end dates/times
            if is_all_day_event:
                event["start"] = {"date": start_dt.strftime("%Y-%m-%d")}
                event["end"] = {"date": end_dt.strftime("%Y-%m-%d")}
            else:
                event["start"] = {
                    "dateTime": start_dt.isoformat(),
                    "timeZone": user_timezone
                }
                event["end"] = {
                    "dateTime": end_dt.isoformat(),
                    "timeZone": user_timezone
                }
            
            # Add the event
            added_event = await self.calendar_service.add_event(user_id, event)
            
            if added_event:
                event_link = "https://calendar.google.com/calendar/u/0/r"
                return f"Event added: {added_event.get('summary')}\nEvent link: {event_link}"
            else:
                return "Failed to add the event."
                
        except Exception as e:
            logger.error(f"Error adding event: {str(e)}")
            return f"An error occurred while adding the event: {str(e)}"
    
    @kernel_function(
        name="delete_event",
        description="Deletes an event from the user's Google Calendar"
    )
    async def delete_event(
        self,
        event_id_or_query: str,
        user_id: str = None,
        kernel = None
    ) -> str:
        """
        Deletes an event from the user's Google Calendar.
        
        Args:
            event_id_or_query: Event ID or search query
            user_id: The user's ID (automatically provided)
            
        Returns:
            str: Success message or error message
        """
        try:
            if not user_id:
                return "Error: User ID not available. Please try again later."
            
            # First try to delete assuming event_id_or_query is an event ID
            try:
                await self.calendar_service.delete_event(user_id, event_id_or_query)
                return f"Event deleted successfully. ID: {event_id_or_query}"
            except Exception:
                # If deletion fails, assume it's not an ID and proceed with search
                pass
            
            # Search for events matching the query
            search_results = await self.calendar_service.search_events(user_id, event_id_or_query)
            events = search_results.get("items", [])
            
            if not events:
                return f"No events found matching '{event_id_or_query}'."
            
            if len(events) == 1:
                event = events[0]
                await self.calendar_service.delete_event(user_id, event["id"])
                return f"Event deleted: {event.get('summary')} (ID: {event.get('id')})"
            
            # If multiple events and kernel is provided, find most relevant
            if kernel and len(events) > 1:
                most_relevant_event = await self._find_most_relevant_event(kernel, events, event_id_or_query)
                
                if most_relevant_event:
                    await self.calendar_service.delete_event(user_id, most_relevant_event["id"])
                    return f"Event deleted: {most_relevant_event.get('summary')} (ID: {most_relevant_event.get('id')})"
            
            # If multiple events and no most relevant found, return summary
            return "Multiple events found. Please be more specific:\n" + self._create_search_results_summary(events)
                
        except Exception as e:
            logger.error(f"Error deleting event: {str(e)}")
            return f"An error occurred while deleting the event: {str(e)}"
    
    @kernel_function(
        name="get_event",
        description="Gets details of a specific event from the user's Google Calendar"
    )
    async def get_event(
        self,
        search_query: str,
        user_id: str = None,
        kernel = None
    ) -> str:
        """
        Gets details of a specific event from the user's Google Calendar.
        
        Args:
            search_query: Search query or event ID
            user_id: The user's ID (automatically provided)
            
        Returns:
            str: Event details or error message
        """
        try:
            if not user_id:
                return "Error: User ID not available. Please try again later."
            
            # First try to get the event directly (in case search_query is an event ID)
            try:
                event = await self.calendar_service.get_event(user_id, search_query)
                return json.dumps(event, indent=2)
            except Exception:
                # If getting the event fails, assume it's not an ID and proceed with search
                pass
            
            # Search for events matching the query
            search_results = await self.calendar_service.search_events(user_id, search_query)
            events = search_results.get("items", [])
            
            if not events:
                return f"No events found matching '{search_query}'."
            
            if len(events) == 1:
                return json.dumps(events[0], indent=2)
            
            # If multiple events and kernel is provided, find most relevant
            if kernel and len(events) > 1:
                most_relevant_event = await self._find_most_relevant_event(kernel, events, search_query)
                
                if most_relevant_event:
                    return json.dumps(most_relevant_event, indent=2)
            
            # If multiple events and no most relevant found, return summary
            return "Multiple events found. Here's a summary:\n" + self._create_search_results_summary(events)
                
        except Exception as e:
            logger.error(f"Error getting event: {str(e)}")
            return f"An error occurred while getting the event: {str(e)}"
    
    @kernel_function(
        name="get_events",
        description="Gets events from the user's Google Calendar within a date range"
    )
    async def get_events(
        self,
        start_date: str,
        end_date: str,
        max_results: int = 10,
        user_id: str = None,
        kernel = None
    ) -> str:
        """
        Gets events from the user's Google Calendar within a date range.
        
        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            max_results: Maximum number of events to return
            user_id: The user's ID (automatically provided)
            
        Returns:
            str: List of events or error message
        """
        try:
            if not user_id:
                return "Error: User ID not available. Please try again later."
            
            try:
                start_dt = datetime.fromisoformat(start_date)
                end_dt = datetime.fromisoformat(end_date)
            except ValueError:
                # Try to parse as just date
                try:
                    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
                    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
                except ValueError as e:
                    return f"Error parsing date: {str(e)}"
            
            events = await self.calendar_service.get_events(user_id, start_dt, end_dt, max_results)
            
            if not events:
                return f"No events found in the date range {start_date} to {end_date}."
            
            return self._format_events(events)
                
        except Exception as e:
            logger.error(f"Error getting events: {str(e)}")
            return f"An error occurred while getting events: {str(e)}"
    
    @kernel_function(
        name="update_event",
        description="Updates an existing event in the user's Google Calendar"
    )
    async def update_event(
        self,
        event_id_or_query: str,
        summary: str,
        description: str,
        start_date_time: str,
        end_date_time: str,
        user_id: str = None,
        kernel = None
    ) -> str:
        """
        Updates an existing event in the user's Google Calendar.
        
        Args:
            event_id_or_query: Event ID or search query
            summary: New event summary/title
            description: New event description
            start_date_time: New start time (ISO 8601)
            end_date_time: New end time (ISO 8601)
            user_id: The user's ID (automatically provided)
            
        Returns:
            str: Success message or error message
        """
        try:
            if not user_id:
                return "Error: User ID not available. Please try again later."
            
            # Parse datetime strings
            try:
                start_dt = datetime.fromisoformat(start_date_time.replace('Z', '+00:00'))
                end_dt = datetime.fromisoformat(end_date_time.replace('Z', '+00:00'))
            except ValueError as e:
                return f"Error parsing date: {str(e)}"
            
            # Create updated event
            updated_event = {
                "summary": summary,
                "description": description,
                "start": {
                    "dateTime": start_dt.isoformat(),
                    "timeZone": "UTC"  # Default to UTC
                },
                "end": {
                    "dateTime": end_dt.isoformat(),
                    "timeZone": "UTC"  # Default to UTC
                }
            }
            
            # First try to update assuming event_id_or_query is an event ID
            try:
                result = await self.calendar_service.update_event(user_id, event_id_or_query, updated_event)
                event_link = f"https://www.google.com/calendar/event?eid={result.get('id')}"
                return f"Event updated: {result.get('summary')} (ID: {result.get('id')})\nEvent link: {event_link}"
            except Exception:
                # If update fails, assume it's not an ID and proceed with search
                pass
            
            # Search for events matching the query
            search_results = await self.calendar_service.search_events(user_id, event_id_or_query)
            events = search_results.get("items", [])
            
            if not events:
                return f"No events found matching '{event_id_or_query}'."
            
            if len(events) == 1:
                event = events[0]
                result = await self.calendar_service.update_event(user_id, event["id"], updated_event)
                event_link = f"https://www.google.com/calendar/event?eid={result.get('id')}"
                return f"Event updated: {result.get('summary')} (ID: {result.get('id')})\nEvent link: {event_link}"
            
            # If multiple events and kernel is provided, find most relevant
            if kernel and len(events) > 1:
                most_relevant_event = await self._find_most_relevant_event(kernel, events, event_id_or_query)
                
                if most_relevant_event:
                    result = await self.calendar_service.update_event(user_id, most_relevant_event["id"], updated_event)
                    event_link = f"https://www.google.com/calendar/event?eid={result.get('id')}"
                    return f"Event updated: {result.get('summary')} (ID: {result.get('id')})\nEvent link: {event_link}"
            
            # If multiple events and no most relevant found, return summary
            return "Multiple events found. Please be more specific:\n" + self._create_search_results_summary(events)
                
        except Exception as e:
            logger.error(f"Error updating event: {str(e)}")
            return f"An error occurred while updating the event: {str(e)}"
    
    @kernel_function(
        name="share_event",
        description="Shares an event with another user by adding them as an attendee"
    )
    async def share_event(
        self,
        event_id_or_query: str,
        shared_email: str,
        user_id: str = None,
        kernel = None
    ) -> str:
        """
        Shares an event with another user by adding them as an attendee.
        
        Args:
            event_id_or_query: Event ID or search query
            shared_email: Email of the user to share with
            user_id: The user's ID (automatically provided)
            
        Returns:
            str: Success message or error message
        """
        try:
            if not user_id:
                return "Error: User ID not available. Please try again later."
            
            # First try to share assuming event_id_or_query is an event ID
            try:
                await self.calendar_service.share_event(user_id, event_id_or_query, shared_email)
                event_link = f"https://www.google.com/calendar/event?eid={event_id_or_query}"
                return f"Event (ID: {event_id_or_query}) successfully shared with {shared_email}.\nEvent link: {event_link}"
            except Exception:
                # If sharing fails, assume it's not an ID and proceed with search
                pass
            
            # Search for events matching the query
            search_results = await self.calendar_service.search_events(user_id, event_id_or_query)
            events = search_results.get("items", [])
            
            if not events:
                return f"No events found matching '{event_id_or_query}'."
            
            if len(events) == 1:
                event = events[0]
                await self.calendar_service.share_event(user_id, event["id"], shared_email)
                event_link = f"https://www.google.com/calendar/event?eid={event.get('id')}"
                return f"Event shared: {event.get('summary')} (ID: {event.get('id')}) with {shared_email}\nEvent link: {event_link}"
            
            # If multiple events and kernel is provided, find most relevant
            if kernel and len(events) > 1:
                most_relevant_event = await self._find_most_relevant_event(kernel, events, event_id_or_query)
                
                if most_relevant_event:
                    await self.calendar_service.share_event(user_id, most_relevant_event["id"], shared_email)
                    event_link = f"https://www.google.com/calendar/event?eid={most_relevant_event.get('id')}"
                    return f"Event shared: {most_relevant_event.get('summary')} (ID: {most_relevant_event.get('id')}) with {shared_email}\nEvent link: {event_link}"
            
            # If multiple events and no most relevant found, return summary
            return "Multiple events found. Please be more specific:\n" + self._create_search_results_summary(events)
                
        except Exception as e:
            logger.error(f"Error sharing event: {str(e)}")
            return f"An error occurred while sharing the event: {str(e)}"
    
    async def _find_most_relevant_event(self, kernel, events, user_query):
        """
        Find the most relevant event from a list based on user query.
        
        Args:
            kernel: Semantic Kernel instance
            events: List of events
            user_query: The user's query
            
        Returns:
            dict: The most relevant event or None
        """
        try:
            # Create a function from prompt
            rank_events_function = KernelFunctionFromPrompt(
                function_name="RankEventsByRelevance",
                plugin_name=None,
                prompt="Given the user query: '{{$userQuery}}' and a list of event summaries and descriptions, "
                    "rank them by relevance and return the index of the most relevant event. "
                    "Do not add any comments or explanation to the response.\n"
                    "Event list: {{$eventList}}",
                template_format="semantic-kernel"
            )
            
            # Create event list string
            event_list = "\n".join([f"{i}: Summary: {event.get('summary', 'No title')}, Description: {event.get('description', 'No description')}"
                                    for i, event in enumerate(events)])
            
            # Create kernel arguments
            kernel_arguments = {
                "userQuery": user_query,
                "eventList": event_list
            }
            
            # Invoke the function
            result = await kernel.invoke(rank_events_function, **kernel_arguments)

            # Get the value from the result - might be a list or a string
            result_value = result.value

            # Handle different result types
            if isinstance(result_value, list) and len(result_value) > 0:
                result_text = str(result_value[0]).strip()
            elif isinstance(result_value, str):
                result_text = result_value.strip()
            else:
                # Fallback
                result_text = str(result_value).strip()

            try:
                most_relevant_index = int(result_text)
                if 0 <= most_relevant_index < len(events):
                    return events[most_relevant_index]
            except ValueError:
                logger.warning(f"Could not parse the relevance index from AI result: {result_text}")
            
            return None
            
        except Exception as e:
            logger.error(f"Error finding most relevant event: {str(e)}")
            return None
    
    def _format_events(self, events):
        """Format a list of events into a human-readable string."""
        if not events:
            return "No events found."
        
        formatted_events = []
        for event in events:
            formatted_event = f"Event: {event.get('summary', 'No title')}\n"
            
            # Format start time
            start = event.get('start', {})
            if 'dateTime' in start:
                start_time = datetime.fromisoformat(start['dateTime'].replace('Z', '+00:00'))
                formatted_event += f"Start: {start_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            elif 'date' in start:
                formatted_event += f"Start: {start['date']} (All day)\n"
            
            # Format end time
            end = event.get('end', {})
            if 'dateTime' in end:
                end_time = datetime.fromisoformat(end['dateTime'].replace('Z', '+00:00'))
                formatted_event += f"End: {end_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            elif 'date' in end:
                formatted_event += f"End: {end['date']} (All day)\n"
            
            # Add location if available
            if 'location' in event and event['location']:
                formatted_event += f"Location: {event['location']}\n"
            
            # Add description if available
            if 'description' in event and event['description']:
                formatted_event += f"Description: {event['description']}\n"
            
            formatted_events.append(formatted_event)
        
        return "\n".join(formatted_events)
    
    def _create_search_results_summary(self, events):
        """Create a summary of multiple search results."""
        if not events:
            return "No events found."
        
        summary = []
        for event in events:
            event_summary = f"ID: {event.get('id')}\n"
            event_summary += f"Summary: {event.get('summary', 'No title')}\n"
            
            # Format start time
            start = event.get('start', {})
            if 'dateTime' in start:
                start_time = datetime.fromisoformat(start['dateTime'].replace('Z', '+00:00'))
                event_summary += f"Start: {start_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            elif 'date' in start:
                event_summary += f"Start: {start['date']} (All day)\n"
            
            # Format end time
            end = event.get('end', {})
            if 'dateTime' in end:
                end_time = datetime.fromisoformat(end['dateTime'].replace('Z', '+00:00'))
                event_summary += f"End: {end_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            elif 'date' in end:
                event_summary += f"End: {end['date']} (All day)\n"
            
            # Add event link
            event_link = f"https://www.google.com/calendar/event?eid={event.get('id')}"
            event_summary += f"Link: {event_link}\n"
            
            summary.append(event_summary)
        
        return "\n".join(summary)
