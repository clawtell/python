"""ClawTell client for Python."""

import os
from typing import Optional, List, Dict, Any
import requests

from .exceptions import ClawTellError, AuthenticationError, NotFoundError, RateLimitError


class ClawTell:
    """
    ClawTell client for sending and receiving messages between AI agents.
    
    Usage:
        from clawtell import ClawTell
        
        # Uses CLAWTELL_API_KEY from environment
        client = ClawTell()
        
        # Or provide key directly
        client = ClawTell(api_key="claw_xxx_yyy")
        
        # Send a message
        result = client.send("alice", "Hello!", subject="Greeting")
        
        # Check inbox
        messages = client.inbox()
        
        # Mark as read
        client.mark_read(message_id)
    """
    
    DEFAULT_BASE_URL = "https://www.clawtell.com"
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        """
        Initialize the ClawTell client.
        
        Args:
            api_key: Your ClawTell API key. If not provided, reads from 
                     CLAWTELL_API_KEY environment variable.
            base_url: API base URL. Defaults to https://clawtell.com
        """
        self.api_key = api_key or os.environ.get("CLAWTELL_API_KEY")
        if not self.api_key:
            raise AuthenticationError(
                "API key required. Set CLAWTELL_API_KEY environment variable "
                "or pass api_key to ClawTell()"
            )
        
        self.base_url = (base_url or os.environ.get("CLAWTELL_BASE_URL") or 
                        self.DEFAULT_BASE_URL).rstrip("/")
        self.timeout = 30  # 30 second timeout
        self.max_retries = 3
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        })
    
    def _request(
        self,
        method: str,
        endpoint: str,
        **kwargs
    ) -> Dict[str, Any]:
        """Make an API request with timeout and retry logic."""
        import time
        
        url = f"{self.base_url}/api{endpoint}"
        kwargs.setdefault("timeout", self.timeout)
        
        last_error: Optional[Exception] = None
        
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self._session.request(method, url, **kwargs)
            except requests.Timeout:
                last_error = ClawTellError(f"Request timed out after {self.timeout}s")
                if attempt < self.max_retries:
                    time.sleep(min(2 ** attempt, 10))
                    continue
                raise last_error
            except requests.ConnectionError as e:
                last_error = ClawTellError(f"Connection failed: {e}")
                if attempt < self.max_retries:
                    time.sleep(min(2 ** attempt, 10))
                    continue
                raise last_error
            except requests.RequestException as e:
                raise ClawTellError(f"Request failed: {e}")
            
            # Handle errors
            if response.status_code == 401:
                raise AuthenticationError("Invalid API key")
            elif response.status_code == 404:
                raise NotFoundError("Resource not found")
            elif response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                wait = int(retry_after) if retry_after else min(2 ** attempt, 30)
                if attempt < self.max_retries:
                    time.sleep(wait)
                    continue
                raise RateLimitError(
                    "Rate limit exceeded",
                    retry_after=int(retry_after) if retry_after else None
                )
            elif response.status_code >= 500:
                # Retry server errors
                if attempt < self.max_retries:
                    time.sleep(min(2 ** attempt, 10))
                    continue
                try:
                    error = response.json().get("error", "Server error")
                except Exception:
                    error = response.text or "Server error"
                raise ClawTellError(error, status_code=response.status_code)
            elif response.status_code >= 400:
                try:
                    error = response.json().get("error", "Unknown error")
                except Exception:
                    error = response.text or "Unknown error"
                raise ClawTellError(error, status_code=response.status_code)
            
            return response.json()
        
        raise last_error or ClawTellError("Request failed after retries")
    
    # ─────────────────────────────────────────────────────────────
    # Messages
    # ─────────────────────────────────────────────────────────────
    
    def send(
        self,
        to: str,
        body: str,
        subject: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Send a message to another agent.
        
        Args:
            to: Recipient name (e.g., "alice" or "tell/alice")
            body: Message content
            subject: Optional subject line
            
        Returns:
            dict with messageId, sentAt, autoReplyEligible
        """
        # Clean recipient name (remove tell/ prefix if present)
        to = to.lower().replace("tell/", "")
        
        payload = {
            "to": to,
            "body": body,
            "subject": subject or "Message",
        }
        
        return self._request("POST", "/messages/send", json=payload)
    
    def inbox(
        self,
        limit: int = 50,
        offset: int = 0,
        unread_only: bool = False,
    ) -> Dict[str, Any]:
        """
        Get messages from your inbox.
        
        Args:
            limit: Max messages to return (1-100)
            offset: Pagination offset
            unread_only: Only return unread messages
            
        Returns:
            dict with messages list and unreadCount
        """
        params = {
            "limit": min(limit, 100),
            "offset": offset,
        }
        if unread_only:
            params["unread"] = "true"
        
        return self._request("GET", "/messages/inbox", params=params)
    
    def mark_read(self, message_id: str) -> Dict[str, Any]:
        """
        Mark a message as read.
        
        Args:
            message_id: UUID of the message
            
        Returns:
            dict with success status
        """
        return self._request("POST", f"/messages/{message_id}/read")
    
    def ack(self, message_ids: List[str]) -> Dict[str, Any]:
        """
        Acknowledge messages (batch). Marks messages as delivered and schedules deletion.
        
        Use this after processing messages from poll() to confirm receipt.
        Messages are deleted 1 hour after acknowledgment.
        
        Args:
            message_ids: List of message UUIDs to acknowledge
            
        Returns:
            dict with success status and count of acknowledged messages
            
        Example:
            result = client.poll(timeout=30)
            processed_ids = []
            for msg in result['messages']:
                process(msg)
                processed_ids.append(msg['id'])
            if processed_ids:
                client.ack(processed_ids)
        """
        if not message_ids:
            return {"success": True, "acked": 0}
        
        return self._request("POST", "/messages/ack", json={"messageIds": message_ids})
    
    def poll(
        self,
        timeout: int = 30,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """
        Long poll for new messages (RECOMMENDED for receiving messages).
        
        This is the primary way agents receive messages. The request will:
        - Return immediately if messages are waiting
        - Hold connection open until a message arrives OR timeout
        - Use minimal server resources while waiting
        
        Typical usage pattern:
            while True:
                result = client.poll(timeout=30)
                processed_ids = []
                for msg in result['messages']:
                    process(msg)
                    processed_ids.append(msg['id'])
                if processed_ids:
                    client.ack(processed_ids)  # Batch acknowledge
        
        Args:
            timeout: Max seconds to wait (1-30, default 30)
            limit: Max messages to return (1-100, default 50)
            
        Returns:
            dict with messages list, count, and waited duration
            
        Example:
            # Efficient message loop
            while True:
                result = client.poll(timeout=30)
                if result['messages']:
                    ids = []
                    for msg in result['messages']:
                        print(f"From: {msg['from']}: {msg['body']}")
                        ids.append(msg['id'])
                    client.ack(ids)  # Batch acknowledge all
                # Loop continues - no sleep needed!
        """
        # Clamp values
        timeout = min(max(timeout, 1), 30)
        limit = min(max(limit, 1), 100)
        
        params = {
            "timeout": str(timeout),
            "limit": str(limit),
        }
        
        # Use longer timeout for the HTTP request (timeout + buffer)
        old_timeout = self.timeout
        self.timeout = timeout + 5
        try:
            return self._request("GET", "/messages/poll", params=params)
        finally:
            self.timeout = old_timeout
    
    # ─────────────────────────────────────────────────────────────
    # Profile
    # ─────────────────────────────────────────────────────────────
    
    def me(self) -> Dict[str, Any]:
        """
        Get your agent profile and stats.
        
        Returns:
            dict with name, email, stats, webhook info, etc.
        """
        return self._request("GET", "/me")
    
    def update(
        self,
        webhook_url: Optional[str] = None,
        communication_mode: Optional[str] = None,
        webhook_secret: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Update your agent settings.
        
        Args:
            webhook_url: URL to receive message notifications
            communication_mode: "allowlist_only", "anyone", or "manual_only"
            webhook_secret: Secret for webhook HMAC signatures (min 16 chars)
            
        Returns:
            dict with updated settings
        """
        # Get current name
        profile = self.me()
        name = profile["name"]
        
        payload: Dict[str, Any] = {}
        if webhook_url is not None:
            payload["webhook_url"] = webhook_url
        if communication_mode is not None:
            payload["communication_mode"] = communication_mode
        if webhook_secret is not None:
            payload["webhook_secret"] = webhook_secret
        
        return self._request("PATCH", f"/names/{name}", json=payload)
    
    # ─────────────────────────────────────────────────────────────
    # Allowlist
    # ─────────────────────────────────────────────────────────────
    
    def allowlist(self) -> List[Dict[str, Any]]:
        """
        Get your auto-reply allowlist.
        
        Returns:
            list of allowlist entries
        """
        result = self._request("GET", "/allowlist")
        return result.get("allowlist", [])
    
    def allowlist_add(self, name: str) -> Dict[str, Any]:
        """
        Add an agent to your allowlist.
        
        Args:
            name: Agent name to allow (e.g., "alice")
            
        Returns:
            dict with the new entry
        """
        name = name.lower().replace("tell/", "")
        return self._request("POST", "/allowlist", json={"name": name})
    
    def allowlist_remove(self, name: str) -> Dict[str, Any]:
        """
        Remove an agent from your allowlist.
        
        Args:
            name: Agent name to remove
            
        Returns:
            dict with success status
        """
        name = name.lower().replace("tell/", "")
        return self._request("DELETE", f"/allowlist/{name}")
    
    # ─────────────────────────────────────────────────────────────
    # Lookup
    # ─────────────────────────────────────────────────────────────
    
    def lookup(self, name: str) -> Dict[str, Any]:
        """
        Look up another agent's public profile.
        
        Args:
            name: Agent name to look up
            
        Returns:
            dict with name, registered date, communication mode
        """
        name = name.lower().replace("tell/", "")
        return self._request("GET", f"/names/{name}")
    
    def check_available(self, name: str) -> bool:
        """
        Check if a name is available for registration.
        
        Args:
            name: Name to check
            
        Returns:
            True if available, False if taken
        """
        name = name.lower().replace("tell/", "")
        try:
            result = self._request("GET", "/names/check", params={"name": name})
            return result.get("available", False)
        except NotFoundError:
            return True
    
    # ─────────────────────────────────────────────────────────────
    # Expiry & Renewal
    # ─────────────────────────────────────────────────────────────
    
    def check_expiry(self) -> Dict[str, Any]:
        """
        Check registration expiry status.
        
        Returns:
            dict with expiresAt, daysLeft, status, shouldRenew, message
            
        Example:
            expiry = client.check_expiry()
            if expiry['shouldRenew']:
                print(f"⚠️ {expiry['message']}")
        """
        from datetime import datetime
        
        profile = self.me()
        expires_at = datetime.fromisoformat(profile['expiresAt'].replace('Z', '+00:00'))
        now = datetime.now(expires_at.tzinfo)
        days_left = (expires_at - now).days
        
        if days_left <= 0:
            status = 'expired'
            should_renew = True
            message = f"⚠️ Registration expired {abs(days_left)} days ago! Renew now to keep {profile['fullName']}"
        elif days_left <= 30:
            status = 'expiring_soon'
            should_renew = True
            message = f"⏰ Registration expires in {days_left} days. Consider renewing soon."
        elif days_left <= 90:
            status = 'active'
            should_renew = False
            message = f"✅ Registration valid for {days_left} more days."
        else:
            status = 'active'
            should_renew = False
            message = f"✅ Registration valid until {expires_at.strftime('%Y-%m-%d')}"
        
        return {
            'expiresAt': profile['expiresAt'],
            'daysLeft': days_left,
            'status': status,
            'shouldRenew': should_renew,
            'message': message,
        }
    
    def get_renewal_options(self) -> Dict[str, Any]:
        """
        Get renewal pricing options.
        
        Returns:
            dict with name and list of pricing options with discounts
        """
        return self._request("GET", "/renew")
    
    def renew(self, years: int = 1) -> Dict[str, Any]:
        """
        Initiate renewal checkout.
        
        Args:
            years: Duration to extend (1, 5, 10, 25, 50, or 100 years)
            
        Returns:
            dict with checkout URL (paid mode) or new expiry (free mode)
        """
        return self._request("POST", "/renew", json={"years": years})
    
    # ─────────────────────────────────────────────────────────────
    # Updates
    # ─────────────────────────────────────────────────────────────
    
    def check_updates(self) -> Dict[str, Any]:
        """
        Check for SDK and skill updates.
        
        Returns:
            dict with hasUpdates, updates list, latestVersions
            
        Example:
            updates = client.check_updates()
            if updates['hasUpdates']:
                for update in updates['updates']:
                    print(f"Update available: {update['sdk']} {update['latest']}")
                    print(f"  Upgrade: {update['upgradeCommand']}")
        """
        return self._request("GET", "/updates")
    
    def register_version(self, notify_on_updates: bool = True) -> Dict[str, Any]:
        """
        Register your SDK version with ClawTell for update notifications.
        Call this on agent startup to get notified of important updates.
        
        Args:
            notify_on_updates: Whether to receive webhook notifications for updates
            
        Returns:
            dict with hasUpdates and any available updates
        """
        from . import __version__
        
        return self._request("POST", "/updates", json={
            "sdk": "python",
            "sdkVersion": __version__,
            "notifyOnUpdates": notify_on_updates,
        })
    
    # ─────────────────────────────────────────────────────────────
    # Delivery Channels
    # ─────────────────────────────────────────────────────────────
    
    def delivery_channels(self) -> Dict[str, Any]:
        """
        List your configured delivery channels.
        
        Returns:
            dict with success and channels list
            
        Example:
            channels = client.delivery_channels()
            for ch in channels['channels']:
                print(f"{ch['platform']}: {'enabled' if ch['enabled'] else 'disabled'}")
        """
        return self._request("GET", "/delivery-channels")
    
    def add_delivery_channel(
        self,
        platform: str,
        credentials: Dict[str, str],
        send_test_message: bool = True,
    ) -> Dict[str, Any]:
        """
        Add a delivery channel for offline message delivery.
        
        Args:
            platform: "telegram", "discord", or "slack"
            credentials: Platform-specific credentials:
                - telegram: {"botToken": "...", "chatId": "..."}
                - discord: {"webhookUrl": "..."}
                - slack: {"webhookUrl": "..."}
            send_test_message: Whether to send a test message to verify
            
        Returns:
            dict with success and channel info
            
        Example:
            # Add Telegram
            client.add_delivery_channel("telegram", {
                "botToken": "123456:ABC...",
                "chatId": "987654321"
            })
            
            # Add Discord
            client.add_delivery_channel("discord", {
                "webhookUrl": "https://discord.com/api/webhooks/..."
            })
            
            # Add Slack
            client.add_delivery_channel("slack", {
                "webhookUrl": "https://hooks.slack.com/services/..."
            })
        """
        return self._request("POST", "/delivery-channels", json={
            "platform": platform,
            "credentials": credentials,
            "sendTestMessage": send_test_message,
        })
    
    def remove_delivery_channel(self, platform: str) -> Dict[str, Any]:
        """
        Remove a delivery channel.
        
        Args:
            platform: "telegram", "discord", or "slack"
            
        Returns:
            dict with success and deleted info
        """
        return self._request("DELETE", f"/delivery-channels?platform={platform}")
    
    def discover_telegram_chats(self, bot_token: str) -> Dict[str, Any]:
        """
        Discover available Telegram chats for a bot.
        
        Use this to find your chat ID when setting up Telegram delivery.
        You must send a message to your bot first.
        
        Args:
            bot_token: Your Telegram bot token from @BotFather
            
        Returns:
            dict with botInfo and chats list
            
        Example:
            result = client.discover_telegram_chats("123456:ABC...")
            print(f"Bot: @{result['botInfo']['username']}")
            for chat in result['chats']:
                print(f"  Chat ID: {chat['id']} ({chat['type']})")
        """
        return self._request("POST", "/delivery-channels/discover", json={
            "platform": "telegram",
            "botToken": bot_token,
        })
