"""
Notification modules for on-call agent
Supports Microsoft Teams webhook notifications
"""

from .teams_notifier import TeamsNotifier

__all__ = ['TeamsNotifier']
